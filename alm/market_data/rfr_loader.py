"""PRA risk-free rate curve loader, reading the official published XLSX
rather than hard-coding curve points.

The PRA's actual monthly RFR workbook is a wide, multi-tab format (one tab
per currency, one column per term point, separate tabs for the basic curve
vs with-MA/with-VA variants and their up/down shocks). Rather than force
every caller to know that layout, `load_rfr_curve_from_xlsx` below defines
a simple, unambiguous long format instead: one row per (currency, term)
pair, the same pattern used for `prophet_io`'s extract schema.
`load_rfr_curve_from_pra_workbook` (further down this file) is the adapter
for the real published workbook, checked against the 31 Aug 2026 release
in `alm/market_data/pra_reference/`.

Expected columns (any sheet name, first sheet read by default):
  currency      ISO 4217, e.g. "GBP"
  term_years    float, years from the valuation date
  rate          float, annual effective zero rate, e.g. 0.0325 for 3.25%
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from alm.contracts.curves import Curve

REQUIRED_RFR_COLUMNS = ("currency", "term_years", "rate")


def load_rfr_curve_from_xlsx(
    path: str | Path,
    currency: str,
    valuation_date: date,
    sheet_name: str | int = 0,
    name: str | None = None,
) -> Curve:
    df = pd.read_excel(path, sheet_name=sheet_name)
    missing = set(REQUIRED_RFR_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"RFR file {path} is missing required columns: {sorted(missing)}")

    rows = df[df["currency"] == currency].sort_values("term_years")
    if rows.empty:
        raise ValueError(f"RFR file {path} has no rows for currency {currency!r}")

    return Curve(
        currency=currency,
        valuation_date=valuation_date,
        terms=tuple(float(t) for t in rows["term_years"]),
        rates=tuple(float(r) for r in rows["rate"]),
        name=name or f"PRA_RFR_{currency}_{valuation_date.isoformat()}",
    )


# Bank of England technical-information workbook: row 3 in each currency block
# starts with this prefix before an underscore (e.g. "GB_31_08_2026_SWP_..."),
# NOT the ISO 4217 currency code itself for GBP/USD/CAD -- verified against the
# 31 Aug 2026 release, `alm/market_data/pra_reference/risk-free-curves-31-aug-2026.xlsx`.
CURRENCY_TO_PRA_WORKBOOK_PREFIX: dict[str, str] = {"EUR": "EUR", "GBP": "GB", "USD": "US", "CAD": "CA"}


def load_rfr_curve_from_pra_workbook(
    path: str | Path,
    currency: str,
    valuation_date: date,
    sheet_name: str = "RFR_spot_no_VA",
    name: str | None = None,
) -> Curve:
    """Adapter for the REAL Bank of England-published Solvency II technical
    information workbook (bankofengland.co.uk, Solvency II technical
    information page), as opposed to `load_rfr_curve_from_xlsx`'s documented
    v1 long format above. Verified against the 31 Aug 2026 release:

    Each currency occupies one column within `sheet_name` (the basic RFR,
    no VA). Row 3 of that column holds an internal curve code starting with
    the currency's prefix (see `CURRENCY_TO_PRA_WORKBOOK_PREFIX` -- GBP/USD/
    CAD use their 2-letter country code, not the ISO 4217 currency code).
    Data rows run from row 11 (term = 1 year) downward, one row per
    additional year, until the first blank cell -- this loader locates the
    currency's column by searching row 3 rather than hardcoding a column
    index, since a currency's position has already been seen to differ from
    the RFR-vs-FS workbook and may shift release to release.
    """
    import openpyxl

    prefix = CURRENCY_TO_PRA_WORKBOOK_PREFIX.get(currency, currency)
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[sheet_name]

    col = None
    for cell in next(ws.iter_rows(min_row=3, max_row=3, max_col=ws.max_column)):
        if isinstance(cell.value, str) and cell.value.split("_")[0] == prefix:
            col = cell.column
            break
    if col is None:
        raise ValueError(f"PRA workbook {path} has no curve code starting with {prefix!r} (currency {currency!r}) in row 3 of sheet {sheet_name!r}")

    terms: list[float] = []
    rates: list[float] = []
    row = 11
    while True:
        rate = ws.cell(row=row, column=col).value
        if rate is None:
            break
        terms.append(float(row - 10))
        rates.append(float(rate))
        row += 1
    if not terms:
        raise ValueError(f"PRA workbook {path}: found column for {currency!r} but no rate data from row 11")

    return Curve(
        currency=currency, valuation_date=valuation_date,
        terms=tuple(terms), rates=tuple(rates),
        name=name or f"PRA_RFR_real_{currency}_{valuation_date.isoformat()}",
    )


def save_rfr_curve_to_xlsx(curve: Curve, path: str | Path) -> None:
    """Convenience for building fixtures / round-tripping a Curve already
    held in memory back into the loader's documented format."""
    df = pd.DataFrame({
        "currency": [curve.currency] * len(curve.terms),
        "term_years": list(curve.terms),
        "rate": list(curve.rates),
    })
    df.to_excel(path, index=False)
