"""PRA Test 4 -- MA Loss Test (HP assets only, SS7/18 Appendix 1).

For each HP asset, find the contractual cash flow profile within its
permitted bounds that minimises MA benefit, and check that the resulting MA
loss (relative to the expected-profile MA benefit) does not exceed the
threshold (5%, PRA default).

v1 methodology (SS7/18 leaves this as a firm methodology choice -- see
project brief, "implement a default and make it configurable; document the
choice"): market value is a today-observable fact and does not itself change
under a hypothetical future repayment scenario, so instead of perturbing MV
(which -- checked explicitly in this engine -- moves the MA rate the WRONG
way: a *lower* asset-side PV target makes the two-AER solve return a
*higher* r1, since r1 is solved purely from "what flat rate reproduces this
target PV", independent of adequacy) this isolates the asset's OWN
achievable yield under each profile, at the SAME market value:

  r_asset_expected    = AER solving PV(expected_cash flows,    r) = MV
  r_asset_loss_minimizing = AER solving PV(loss-minimising cash flows, r) = MV

Because the loss-minimising profile spends part of its life earning only the
prudent (spread-limited) reinvestment rate instead of the instrument's full
coupon, `r_asset_loss_minimizing <= r_asset_expected` always. The gap is the
reinvestment-risk yield erosion, subtracted directly from the base case's MA
rate to get the stressed MA rate -- so the stress acts on the *yield*, never
on the observed MV.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from alm.contracts.cashflows import CashFlowVector
from alm.contracts.curves import Curve
from alm.ma.engine import MAResult, compute_ma
from alm.ma.hp_instrument import HPBond
from alm.ma.two_aer import solve_aer

TEST4_THRESHOLD = 0.05  # SS7/18 Appendix 1 default


class Test4Result(BaseModel):
    model_config = ConfigDict(frozen=True)

    hp_asset_id: str
    market_value: float
    rate_asset_expected: float
    rate_asset_loss_minimizing: float
    reinvestment_yield_erosion: float  # rate_asset_expected - rate_asset_loss_minimizing, >= 0
    base_ma: MAResult
    stressed_ma: MAResult
    ma_loss: float  # base_ma.ma_benefit - stressed_ma.ma_benefit, >= 0
    ratio: float  # ma_loss / base_ma.ma_benefit
    threshold: float
    passed: bool


def run_test4(
    liability_cfs: CashFlowVector,
    hp_bond: HPBond,
    market_value: float,
    fs_rate: float,
    curve: Curve,
    valuation_date: date,
    threshold: float = TEST4_THRESHOLD,
) -> Test4Result:
    expected_cfv = hp_bond.expected_cashflows(valuation_date)
    loss_min_cfv = hp_bond.loss_minimizing_cashflows(valuation_date)

    r_asset_expected = solve_aer(expected_cfv, market_value)
    r_asset_loss_min = solve_aer(loss_min_cfv, market_value)
    yield_erosion = max(0.0, r_asset_expected - r_asset_loss_min)

    base_ma = compute_ma(liability_cfs, market_value, fs_rate, curve)

    r2 = base_ma.rate_basic_rfr_aer
    stressed_ma_rate = base_ma.ma_rate - yield_erosion
    # re-express the stressed MA rate as an equivalent asset-side target PV so
    # compute_ma's own r1 solve reproduces it exactly (keeps a single code
    # path for "BEL discounted at RFR+MA", never duplicated here)
    equivalent_target_pv = liability_cfs.pv_flat(r2 + stressed_ma_rate + fs_rate)
    stressed_ma = compute_ma(liability_cfs, equivalent_target_pv, fs_rate, curve)

    ma_loss = base_ma.ma_benefit - stressed_ma.ma_benefit
    ratio = ma_loss / base_ma.ma_benefit if base_ma.ma_benefit > 0 else 0.0

    return Test4Result(
        hp_asset_id=hp_bond.id,
        market_value=market_value,
        rate_asset_expected=r_asset_expected,
        rate_asset_loss_minimizing=r_asset_loss_min,
        reinvestment_yield_erosion=yield_erosion,
        base_ma=base_ma,
        stressed_ma=stressed_ma,
        ma_loss=ma_loss,
        ratio=ratio,
        threshold=threshold,
        passed=ratio <= threshold,
    )
