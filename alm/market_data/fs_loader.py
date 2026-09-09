"""PRA Fundamental Spread table loader (project brief: "Fundamental Spreads
(PD, CoD, LTAS floor), by currency, rating, sector, term ... ingest official
XLSX; do not hard-code spreads").

Same documented-v1-default posture as `rfr_loader.py`: no real PRA-published
FS file has been supplied, so this defines a simple, unambiguous long
format (one row per currency/rating/sector/term-bucket combination) rather
than guessing the PRA's actual published layout.

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


def save_fs_table_to_xlsx(fs_table: FSTable, path: str | Path) -> None:
    df = pd.DataFrame([{
        "currency": e.currency, "rating": e.rating.value, "sector": e.sector.value,
        "term_years": e.term_years, "fs_pd_bps": e.fs_pd_bps, "fs_cod_bps": e.fs_cod_bps,
        "ltas_floor_bps": e.ltas_floor_bps,
    } for e in fs_table.entries])
    df.to_excel(path, index=False)
