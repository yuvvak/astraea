"""MA calculation core: the "two annual effective rates" method.

See SS7/18 4.3-4.17 and IRPR regs 5-6:

  r1 = AER such that PV(liability CFs, r1) = MV(assigned assets)
  r2 = AER such that PV(liability CFs, r2) = BEL discounted on the basic RFR
       term structure (no MA, no VA, no RFR-TMTP)
  MA  = r1 - r2 - FS_rate

FS_rate is the PV-weighted-average fundamental spread across the assigned
asset cash flows (see `fs_rate.fs_rate_for_assets`) -- deducted so that MA
reflects only the illiquidity premium, not compensation for expected default
losses or downgrade risk, which the FS already prices in.

This module does NOT do hypothecation (Component A/B/C split) or the SIG cap
-- v1 assumes the caller has already decided which assets are assigned to
back which liability cash flows and passes in a single MV and FS_rate for
that assigned set. Hypothecation is layered on top once this reproduces the
golden example (see repo README, implementation order).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from alm.contracts.cashflows import CashFlowVector
from alm.contracts.curves import Curve

from .two_aer import solve_aer


class MAResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    liability_id: str
    currency: str
    bel_basic_rfr: float
    asset_market_value: float
    rate_asset_implied: float  # r1
    rate_basic_rfr_aer: float  # r2
    fs_rate: float
    ma_rate: float  # r1 - r2 - fs_rate, i.e. MA in decimal (multiply by 10,000 for bps)
    bel_with_ma: float
    ma_benefit: float  # bel_basic_rfr - bel_with_ma

    @property
    def ma_bps(self) -> float:
        return self.ma_rate * 10_000.0


def compute_ma(
    liability_cfs: CashFlowVector,
    asset_market_value: float,
    fs_rate: float,
    rfr_curve: Curve,
) -> MAResult:
    if liability_cfs.direction != "liability_outgo":
        raise ValueError(f"expected a liability cash flow vector, got direction={liability_cfs.direction!r}")

    bel = liability_cfs.pv(rfr_curve)
    r2 = solve_aer(liability_cfs, bel)
    r1 = solve_aer(liability_cfs, asset_market_value)
    ma_rate = r1 - r2 - fs_rate

    ma_curve = rfr_curve.shift_parallel(ma_rate, name=f"{rfr_curve.name}+MA")
    bel_with_ma = liability_cfs.pv(ma_curve)

    return MAResult(
        liability_id=liability_cfs.id,
        currency=liability_cfs.currency,
        bel_basic_rfr=bel,
        asset_market_value=asset_market_value,
        rate_asset_implied=r1,
        rate_basic_rfr_aer=r2,
        fs_rate=fs_rate,
        ma_rate=ma_rate,
        bel_with_ma=bel_with_ma,
        ma_benefit=bel - bel_with_ma,
    )
