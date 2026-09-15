"""PRA Fundamental Spread table loader (PD, CoD, LTAS floor, by currency,
rating, sector, term), reading the official XLSX rather than hard-coding
spreads.

Same approach as `rfr_loader.py`: defines a simple, unambiguous long
format (one row per currency/rating/sector/term-bucket combination) for
`load_fs_table_from_xlsx` below, rather than requiring every caller to
know the PRA's actual published layout. `load_fs_table_from_pra_workbook`
(further down this file) is the adapter for the real published workbook,
checked against the 31 Aug 2026 release in `alm/market_data/pra_reference/`.

Expected columns (any sheet name, first sheet read by default):
  currency        ISO 4217, e.g. "GBP"
  rating          a RatingNotch value, e.g. "A2", "BBB1", "UNRATED"
  sector          an AssetSector value: "government", "financial", "non_financial", "other"
  term_years      float, upper bound of the term bucket this row applies to
  fs_pd_bps       float, probability-of-default component, in bps p.a.
  fs_cod_bps      float, cost-of-downgrade component, in bps p.a.
  ltas_floor_bps  float, long-term average spread floor, in bps p.a. (0.0 if not supplied)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from alm.contracts.fs import AssetSector, FSEntry, FSTable, RatingNotch

REQUIRED_FS_COLUMNS = ("currency", "rating", "sector", "term_years", "fs_pd_bps", "fs_cod_bps")


def load_fs_table_from_xlsx(
    path: str | Path,
    source: str | None = None,
    sheet_name: str | int = 0,
) -> FSTable:
    df = pd.read_excel(path, sheet_name=sheet_name)
    missing = set(REQUIRED_FS_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"FS file {path} is missing required columns: {sorted(missing)}")

    entries = []
    for _, row in df.iterrows():
        entries.append(FSEntry(
            currency=row["currency"],
            rating=RatingNotch(row["rating"]),
            sector=AssetSector(row["sector"]),
            term_years=float(row["term_years"]),
            fs_pd_bps=float(row["fs_pd_bps"]),
            fs_cod_bps=float(row["fs_cod_bps"]),
            ltas_floor_bps=float(row["ltas_floor_bps"]) if "ltas_floor_bps" in df.columns and pd.notna(row.get("ltas_floor_bps")) else 0.0,
        ))

    return FSTable(source=source or f"PRA_FS_{Path(path).name}", entries=tuple(entries))


# The real workbook only distinguishes CQS 0-6 (financial/non-financial), not this
# project's finer AA1/AA2/AA3-style notches -- every notch in a CQS band gets the
# same published CQS-level FS/CoD (the real file has no finer granularity to give
# them). CQS6 has no distinct notch in this project's RatingNotch scale, so it isn't
# emitted (the same choice `alm.pra_calibration.RATING_TO_CQS` makes for 3D17).
CQS_TO_RATING_NOTCHES: dict[int, tuple[str, ...]] = {
    0: ("AAA",), 1: ("AA1", "AA2", "AA3"), 2: ("A1", "A2", "A3"),
    3: ("BBB1", "BBB2", "BBB3"), 4: ("BB1", "BB2", "BB3"), 5: ("B_AND_BELOW",),
}
FS_SECTOR_LABELS: dict[AssetSector, str] = {AssetSector.FINANCIAL: "Financial", AssetSector.NON_FINANCIAL: "Non-financial"}


def load_fs_table_from_pra_workbook(path: str | Path, currency: str, source: str | None = None) -> FSTable:
    """Adapter for the REAL Bank of England-published Fundamental Spread/PoD/
    CoD workbook (bankofengland.co.uk, Solvency II technical information
    page), as opposed to `load_fs_table_from_xlsx`'s documented v1 long
    format above. Verified against the 31 Aug 2026 release:

    One sheet per currency (sheet name == the currency code, e.g. "GBP").
    Within it, a "{Financial|Non-financial}. Fundamental spread(percentages)"
    header cell sits directly above the CQS-0 column of a block shaped
    maturity(1..30) x CQS(0..6); a "... Cost of downgrade(percentages)"
    header sits 10 columns to the right of the FS header, same row/maturity
    layout. This loader locates each header by text search (not a hardcoded
    column index), then reads the FS/CoD blocks beneath it.

    The published "Fundamental spread(percentages)" value is used directly
    as `fs_pd_bps + fs_cod_bps` (i.e. `fs_pd_bps` is backed out as
    FS_total - CoD, in bps), NOT re-derived from the workbook's separate raw
    PD tables -- PRA's own PD-to-credit-risk-component formula (the 50%
    LGD-style assumption feeding into FS) and the LTAS floor (LTAS_Govts/
    LTAS_Corps/LTAS_Specifics sheets) are NOT reproduced here; this loader
    takes PRA's own published FS total as authoritative rather than
    re-deriving it. `ltas_floor_bps` is left at 0.0 for the same reason --
    a documented v1 boundary, not a silent gap. Government sector isn't
    sourced here either: gilts get FS=0 by convention (`Bond.is_government`),
    matching how the rest of this codebase already treats them.
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    if currency not in wb.sheetnames:
        raise ValueError(f"PRA FS workbook {path} has no sheet for currency {currency!r}")
    ws = wb[currency]

    entries: list[FSEntry] = []
    for sector, label in FS_SECTOR_LABELS.items():
        fs_header = _find_header_cell(ws, f"{label}. Fundamental spread(percentages)")
        cod_header = _find_header_cell(ws, f"{label}. Cost of downgrade(percentages)")
        if fs_header is None or cod_header is None:
            raise ValueError(f"PRA FS workbook {path}, sheet {currency!r}: could not locate the {label!r} FS/CoD headers")
        fs_row, fs_col = fs_header
        cod_row, cod_col = cod_header

        maturity_col = fs_col - 1
        data_row = fs_row + 4  # header row -> blank -> "Credit quality steps" -> GBP/0..6 -> first data row
        while True:
            maturity = ws.cell(row=data_row, column=maturity_col).value
            if maturity is None:
                break
            for cqs, notches in CQS_TO_RATING_NOTCHES.items():
                fs_pct = ws.cell(row=data_row, column=fs_col + cqs).value
                cod_pct = ws.cell(row=cod_row + (data_row - fs_row), column=cod_col + cqs).value
                if fs_pct is None or cod_pct is None:
                    continue
                fs_total_bps = float(fs_pct) * 100.0
                cod_bps = float(cod_pct) * 100.0
                for notch in notches:
                    entries.append(FSEntry(
                        currency=currency, rating=RatingNotch(notch), sector=sector,
                        term_years=float(maturity), fs_pd_bps=fs_total_bps - cod_bps,
                        fs_cod_bps=cod_bps, ltas_floor_bps=0.0,
                    ))
            data_row += 1

    return FSTable(source=source or f"PRA_FS_real_{currency}_{Path(path).name}", entries=tuple(entries))


def _find_header_cell(ws, text: str) -> tuple[int, int] | None:
    for row in ws.iter_rows(min_row=1, max_row=60):
        for cell in row:
            if isinstance(cell.value, str) and cell.value == text:
                return cell.row, cell.column
    return None


def save_fs_table_to_xlsx(fs_table: FSTable, path: str | Path) -> None:
    df = pd.DataFrame([{
        "currency": e.currency, "rating": e.rating.value, "sector": e.sector.value,
        "term_years": e.term_years, "fs_pd_bps": e.fs_pd_bps, "fs_cod_bps": e.fs_cod_bps,
        "ltas_floor_bps": e.ltas_floor_bps,
    } for e in fs_table.entries])
    df.to_excel(path, index=False)
