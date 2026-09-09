"""PRA risk-free rate curve loader (project brief: "PRA published technical
information: risk-free curves... by currency... ingest official XLSX; do
not hard-code spreads").

No real PRA-published RFR file has been supplied to validate this against.
The PRA's actual monthly RFR workbook is a wide, multi-tab format (one tab
per currency, one column per term point, separate tabs for the basic curve
vs with-MA/with-VA variants) that this project has not seen a live copy of.
Rather than guess at that exact layout and risk silently mis-mapping a
column, this loader defines and documents a simple, unambiguous **long
format** instead: one row per (currency, term) pair. This is the same
pattern used for `prophet_io`'s extract schema: a documented v1 default,
isolated behind one small module, so wiring up the real PRA file later is a
thin adapter (reshape wide-to-long, or extend this loader with a
`sheet_name`/wide-column mapping) rather than a rewrite of anything that
consumes a `Curve`.

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


def save_rfr_curve_to_xlsx(curve: Curve, path: str | Path) -> None:
    """Convenience for building fixtures / round-tripping a Curve already
    held in memory back into the loader's documented format."""
    df = pd.DataFrame({
        "currency": [curve.currency] * len(curve.terms),
        "term_years": list(curve.terms),
        "rate": list(curve.rates),
    })
    df.to_excel(path, index=False)
