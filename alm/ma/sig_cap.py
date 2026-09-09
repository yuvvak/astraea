"""SIG cap: MA on sub-investment-grade (SIG) assets cannot exceed MA on
investment-grade assets of the same duration and asset class (MA rule; see
project brief "Apply SIG cap: MA on sub-investment-grade assets cannot
exceed MA on IG assets of same duration and asset class; lift FS if
needed"). When a SIG asset's raw two-AER MA rate breaches the cap, FS is
"lifted" (increased) just enough that the recomputed MA rate equals the cap
exactly -- never silently truncated, so the FS breakdown stays auditable
(project brief non-functional requirement: "every MA bp traceable to asset
CFs, FS table version, hypothecation set").

v1 methodology: no real IG spread-curve-by-duration table has been
supplied, so `SIG_CAP_MA_RATE` is a single illustrative flat cap (150bp),
clearly flagged as a placeholder -- swap it for a duration-graded curve
sourced from the firm's actual IG asset holdings once available; the cap
mechanism itself (lift FS until MA == cap) does not change.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from alm.contracts.cashflows import CashFlowVector
from alm.contracts.curves import Curve
from alm.contracts.fs import RatingNotch

from .engine import MAResult, compute_ma

SIG_CAP_MA_RATE = 0.0150  # illustrative placeholder flat cap (150bp) -- see module docstring


class SigCapResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    rating: RatingNotch
    cap_rate: float
    capped: bool
    fs_lift_rate: float  # 0.0 when not capped
    pre_cap: MAResult
    result: MAResult  # == pre_cap when not capped


def compute_ma_with_sig_cap(
    liability_cfs: CashFlowVector,
    asset_market_value: float,
    fs_rate: float,
    curve: Curve,
    rating: RatingNotch,
    cap_rate: float = SIG_CAP_MA_RATE,
) -> SigCapResult:
    pre_cap = compute_ma(liability_cfs, asset_market_value, fs_rate, curve)

    if rating.is_investment_grade or pre_cap.ma_rate <= cap_rate:
        return SigCapResult(rating=rating, cap_rate=cap_rate, capped=False, fs_lift_rate=0.0, pre_cap=pre_cap, result=pre_cap)

    fs_lift = pre_cap.ma_rate - cap_rate
    lifted_fs_rate = fs_rate + fs_lift
    capped_result = compute_ma(liability_cfs, asset_market_value, lifted_fs_rate, curve)

    return SigCapResult(
        rating=rating, cap_rate=cap_rate, capped=True, fs_lift_rate=fs_lift,
        pre_cap=pre_cap, result=capped_result,
    )
