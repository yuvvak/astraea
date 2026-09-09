"""Swap reprojection under a rate stress: `reproject_swaps` must rebuild the
swap's expected net cash flows from the STRESSED curve's own forward rates,
not just re-discount the frozen construction-time amounts. The difference
is large and economically real (a swap's floating leg genuinely responds
to a rate move), cross-checked against an independent closed-form annuity
PV at the stressed rate.
"""

from __future__ import annotations

import pytest

from alm.contracts.assets import AssetPosition, InterestRateSwap
from alm.contracts.fs import RatingNotch
from alm.examples.golden_toy import build_fs_table, build_liability, build_rfr_curve
from alm.stresses import StressSpec, reproject_swaps, run_stress

NOTIONAL = 1_000_000.0
FIXED_RATE = 0.05
BASE_RATE = 0.04
STRESSED_RATE = 0.03  # -100bp


def _swap_position():
    curve = build_rfr_curve()
    swap = InterestRateSwap.from_curve(
        id="swap_hedge", currency="GBP", notional=NOTIONAL, fixed_rate=FIXED_RATE,
        maturity_years=10.0, curve=curve, receive_fixed=True, rating=RatingNotch.A2,
    )
    return curve, AssetPosition(id="pos_swap", instrument=swap)


def test_reprojection_produces_a_materially_different_mv_than_naive_rediscounting():
    curve, swap_pos = _swap_position()
    stressed_curve = curve.shift_parallel(-0.01)

    naive_mv = swap_pos.resolved_market_value(stressed_curve)  # old behavior: frozen CFs, new discount rate only
    reprojected = reproject_swaps([swap_pos], stressed_curve)
    reprojected_mv = reprojected[0].resolved_market_value(stressed_curve)

    # the reprojected MV must be far larger: the floating leg itself moved, not just the discount rate
    assert reprojected_mv > naive_mv * 1.5


def test_reprojected_mv_matches_independent_closed_form_annuity_pv():
    curve, swap_pos = _swap_position()
    stressed_curve = curve.shift_parallel(-0.01)
    reprojected = reproject_swaps([swap_pos], stressed_curve)
    reprojected_mv = reprojected[0].resolved_market_value(stressed_curve)

    expected_net_per_period = (FIXED_RATE - STRESSED_RATE) * NOTIONAL
    independent_pv = sum(expected_net_per_period * stressed_curve.discount_factor(t) for t in range(1, 11))
    assert reprojected_mv == pytest.approx(independent_pv, rel=1e-9)


def test_run_stress_uses_the_reprojected_value_automatically():
    curve, swap_pos = _swap_position()
    liability = build_liability()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    fs_table = build_fs_table()

    spec = StressSpec(name="rates_down_100bp", curve_shift=-0.01)
    result = run_stress(spec, cfs, [swap_pos], curve, fs_table, curve.valuation_date)

    stressed_curve = curve.shift_parallel(-0.01)
    reprojected = reproject_swaps([swap_pos], stressed_curve)
    expected_mv = reprojected[0].resolved_market_value(stressed_curve)

    assert result.stressed.total_asset_market_value == pytest.approx(expected_mv, rel=1e-9)
    assert result.base.total_asset_market_value == pytest.approx(swap_pos.resolved_market_value(curve), rel=1e-9)


def test_non_swap_positions_are_unaffected_by_reprojection():
    from alm.examples.golden_toy import build_corporate_bond_position

    curve, swap_pos = _swap_position()
    corp = build_corporate_bond_position(500_000.0)
    stressed_curve = curve.shift_parallel(-0.01)

    reprojected = reproject_swaps([corp, swap_pos], stressed_curve)
    corp_after = next(p for p in reprojected if p.id == "pos_corp")
    # same instrument object (Bond is untouched by reproject_swaps); MV computed fresh off
    # the stressed curve just as it always would be, no special-casing needed
    assert corp_after.instrument is corp.instrument
    assert corp_after.resolved_market_value(stressed_curve) == pytest.approx(corp.resolved_market_value(stressed_curve), rel=1e-9)
