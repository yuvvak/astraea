"""Stress runner golden tests, on the single-corporate-bond portfolio from
golden Scenario B (MV=750,000 < BEL=811,089.58 -- the realistic funding
case, base MA = 135.4464bp, already established in test_golden_ma.py).

Three stress families are exercised, each with a closed-form cross-check
independent of the runner's own internals:

1. Parallel rate shock (-100bp): this position's market_value is a FIXED
   quoted override (see AssetPosition -- not repriced off the curve), so MV
   is unchanged by the shock; but MA still moves, because r2 (the basic-RFR
   AER) tracks the curve while r1 (solved purely from liability cash flows
   and the fixed MV) does not. A -100bp curve shift must therefore move MA
   by *exactly* +100bp, and -- a genuine invariant of the two-AER formula,
   not a coincidence -- BEL-with-MA is exactly unchanged (own_funds_impact
   ~= 0), because BEL-with-MA discounts the (unchanged) liability at
   r2+ma_rate = r1-FS, which is itself invariant to the curve shift.
2. Credit spread widening (FS x1.5): must move MA by exactly
   -(Δfs_rate) in bps, since FS only ever enters as a subtracted rate,
   nothing else in the two-AER solve depends on the FS table.
3. A liability shock (+5%, longevity-style placeholder): BEL must scale by
   exactly 1.05x (linear in cash flow amounts); own_funds is cross-checked
   against an independent MV - BEL_with_MA recomputation.

Test 1 fails both before and after every scenario here (same single-bullet-
bond-vs-smooth-annuity mismatch already documented in
test_hypothecation_and_pra_tests.py) -- `ma_criteria_maintained` is
correctly False throughout, which is the point of the flag: it must never
silently assert MA survived a stress it wasn't checked against.
"""

from __future__ import annotations

import pytest

from alm.examples.golden_toy import build_corporate_bond_position, build_fs_table, build_liability, build_rfr_curve
from alm.stresses import StressSpec, run_stress

CORP_MV = 750_000.0


def _base():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    corp = build_corporate_bond_position(CORP_MV)
    fs_table = build_fs_table()
    return cfs, curve, corp, fs_table


def test_rate_shock_moves_ma_by_exactly_the_shock_and_leaves_own_funds_invariant():
    cfs, curve, corp, fs_table = _base()
    spec = StressSpec(name="rates_down_100bp", curve_shift=-0.01)

    result = run_stress(spec, cfs, [corp], curve, fs_table, curve.valuation_date)

    assert result.base.total_asset_market_value == pytest.approx(CORP_MV)
    assert result.stressed.total_asset_market_value == pytest.approx(CORP_MV)  # fixed quoted MV, not curve-repriced

    assert result.base.ma.ma_bps == pytest.approx(135.4464, abs=1e-3)  # matches golden Scenario B exactly
    assert result.ma_rate_impact_bps == pytest.approx(100.0, abs=1e-6)

    assert result.own_funds_impact == pytest.approx(0.0, abs=1e-4)

    assert result.test1_passed_before is False
    assert result.test1_passed_after is False
    assert result.ma_criteria_maintained is False


def test_spread_widening_moves_ma_by_exactly_the_fs_delta():
    cfs, curve, corp, fs_table = _base()
    spec = StressSpec(name="spread_widen_50pct", fs_widening_multiplier=1.5)

    result = run_stress(spec, cfs, [corp], curve, fs_table, curve.valuation_date)

    assert result.base.fs_rate == pytest.approx(0.0025)
    assert result.stressed.fs_rate == pytest.approx(0.00375)  # x1.5

    expected_delta_bps = (result.stressed.fs_rate - result.base.fs_rate) * -10_000
    assert result.ma_rate_impact_bps == pytest.approx(expected_delta_bps, abs=1e-6)
    assert result.stressed.ma.ma_bps < result.base.ma.ma_bps  # wider spreads -> larger FS deduction -> lower MA


def test_liability_shock_scales_bel_linearly_and_own_funds_is_self_consistent():
    cfs, curve, corp, fs_table = _base()
    spec = StressSpec(name="longevity_up_5pct", liability_shock_multiplier=1.05)

    result = run_stress(spec, cfs, [corp], curve, fs_table, curve.valuation_date)

    assert result.stressed.ma.bel_basic_rfr == pytest.approx(result.base.ma.bel_basic_rfr * 1.05, rel=1e-9)

    # independent cross-check of own_funds = total MV - BEL_with_MA, for both legs
    assert result.base.own_funds == pytest.approx(result.base.total_asset_market_value - result.base.ma.bel_with_ma, rel=1e-9)
    assert result.stressed.own_funds == pytest.approx(
        result.stressed.total_asset_market_value - result.stressed.ma.bel_with_ma, rel=1e-9
    )
    assert result.own_funds_impact == pytest.approx(result.stressed.own_funds - result.base.own_funds, rel=1e-9)
