"""FS aggregation: turn a per-cash-flow, per-rating/sector/term FS lookup into
a single present-value-weighted FS rate (decimal p.a.) for a set of assigned
assets, for use in the two-AER MA formula.

This is a v1 simplification. MA 4.9-4.11 requires FS to be assigned per cash
flow (by the rating/sector/term of that specific flow, not the asset's WAL) --
that per-flow assignment IS done here, inline below; what is simplified is
collapsing the resulting per-flow FS into one weighted rate to subtract from
(r1 - r2), rather than pushing a per-flow haircut through the AER1 solve
itself. Swap in a per-flow CF haircut before the AER1 solve if the firm's
validated methodology requires it -- the two are equivalent to first order
for a reasonably flat FS profile, and exactly equal when FS is flat across
the assigned cash flows (e.g. the golden examples).
"""

from __future__ import annotations

from datetime import date

from alm.contracts.assets import AssetPosition
from alm.contracts.curves import Curve
from alm.contracts.fs import FSTable


def fs_rate_for_assets(
    positions: list[AssetPosition],
    fs_table: FSTable,
    valuation_date: date,
    weighting_curve: Curve,
) -> float:
    """PV-weighted average FS rate (decimal p.a.) across all assigned asset
    cash flows. Government/sovereign positions contribute FS = 0 (PRA
    convention: gilts are treated as FS-nil for MA purposes)."""
    total_weight = 0.0
    total_weighted_fs = 0.0
    for pos in positions:
        bond = pos.instrument
        cfv = pos.cashflows(valuation_date)
        for cf in cfv.flows:
            weight = cf.amount * weighting_curve.discount_factor(cf.time)
            if bond.is_government:
                fs_decimal = 0.0
            else:
                entry = fs_table.lookup(bond.currency, bond.rating, bond.sector, cf.time)
                fs_decimal = entry.fs_bps_floored / 10_000.0
            total_weight += weight
            total_weighted_fs += weight * fs_decimal
    if total_weight <= 0:
        return 0.0
    return total_weighted_fs / total_weight
