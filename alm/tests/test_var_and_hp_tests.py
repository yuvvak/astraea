"""PRA Test 2 (VaR), Test 4 (HP Loss Test) and Test 5 (Modified Accumulated
Shortfall), checked against independent cross-calculations, on the golden
toy fixtures.
"""

from __future__ import annotations

import pytest
from scipy.optimize import brentq

from alm.contracts.cashflows import CashFlowKind
from alm.examples.golden_toy import (
    build_corporate_bond_position,
    build_fs_table,
    build_gilt_position,
    build_hp_bond,
    build_liability,
    build_rfr_curve,
)
from alm.tests_pra.hp_loss_test import TEST4_THRESHOLD, run_test4
from alm.tests_pra.modified_accumulated_shortfall import TEST5_THRESHOLD, run_test5
from alm.tests_pra.var_test import TEST2_THRESHOLD, run_test2

HP_MARKET_VALUE = 500_000.0


# ---------------------------------------------------------------- Test 2 ---

def test_test2_var_legs_and_independent_ir_repricing_cross_check():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    bel = cfs.pv(curve)

    gilt = build_gilt_position(bel=bel)
    corp = build_corporate_bond_position(600_000.0)

    result = run_test2([gilt, corp], curve, bel, curve.valuation_date)

    # independent re-pricing of the interest rate leg, not reusing run_test2's internals
    base_mv = gilt.resolved_market_value(curve) + corp.resolved_market_value(curve)
    up_curve = curve.shift_parallel(0.01)
    down_curve = curve.shift_parallel(-0.01)
    mv_up = gilt.resolved_market_value(up_curve) + corp.resolved_market_value(up_curve)
    mv_down = gilt.resolved_market_value(down_curve) + corp.resolved_market_value(down_curve)
    expected_var = max(0.0, base_mv - mv_up, base_mv - mv_down)

    assert result.interest_rate.base_value == pytest.approx(base_mv, rel=1e-9)
    assert result.interest_rate.var == pytest.approx(expected_var, rel=1e-9)
    assert result.interest_rate.ratio_to_bel == pytest.approx(expected_var / bel, rel=1e-9)
    # bonds lose value when rates rise: the up-shock must be the binding scenario here
    assert result.interest_rate.value_up_shock < result.interest_rate.base_value

    # single-currency, no inflation-linked assets in this portfolio: both legs must be exactly zero
    assert result.inflation.var == 0.0
    assert result.inflation.passed is True
    assert result.currency.var == 0.0
    assert result.currency.passed is True

    assert result.interest_rate.threshold == TEST2_THRESHOLD == 0.01
    # with the v1 illustrative 100bp shock calibration on ~1.4x BEL of bond duration risk,
    # this portfolio genuinely breaches 1% of BEL -- a correct result given the placeholder
    # shock size (see var_test.py docstring), not a bug
    assert result.interest_rate.passed is False


# ---------------------------------------------------------------- Test 4 ---

def test_test4_hp_loss_test_yield_erosion_matches_independent_solve():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)

    hp = build_hp_bond(HP_MARKET_VALUE)
    fs_table = build_fs_table()
    fs_entry = fs_table.lookup(hp.currency, hp.rating, hp.sector, hp.maturity_years)
    fs_rate = fs_entry.fs_bps_floored / 10_000.0

    result = run_test4(cfs, hp, market_value=HP_MARKET_VALUE, fs_rate=fs_rate, curve=curve, valuation_date=curve.valuation_date)

    # r_asset_expected must be exactly the coupon rate: MV == notional and coupon == yield => price == par
    assert result.rate_asset_expected == pytest.approx(0.05, abs=1e-6)

    # independent closed-form cross-check of r_asset_loss_minimizing: 8 years of 5% coupons
    # (25,000 p.a. on 500,000 notional) then a terminal amount at year 10 of
    # 500,000 * 1.03^2 (2 years' prudent reinvestment at 3%), solved for the flat
    # rate that prices this stream at 500,000 -- coded independently of solve_aer
    coupon = HP_MARKET_VALUE * 0.05
    terminal = HP_MARKET_VALUE * (1.03 ** 2)

    def pv(r):
        return sum(coupon / (1 + r) ** t for t in range(1, 9)) + terminal / (1 + r) ** 10 - HP_MARKET_VALUE

    independent_r = brentq(pv, -0.5, 2.0, xtol=1e-12)
    assert result.rate_asset_loss_minimizing == pytest.approx(independent_r, abs=1e-9)
    assert result.rate_asset_loss_minimizing < result.rate_asset_expected

    assert result.reinvestment_yield_erosion == pytest.approx(
        result.rate_asset_expected - result.rate_asset_loss_minimizing, abs=1e-12
    )
    assert result.reinvestment_yield_erosion > 0

    assert result.ma_loss == pytest.approx(result.base_ma.ma_benefit - result.stressed_ma.ma_benefit, rel=1e-9)
    assert result.ma_loss >= 0  # the stress can never IMPROVE the MA benefit
    assert result.ratio == pytest.approx(result.ma_loss / result.base_ma.ma_benefit, rel=1e-9)
    assert result.threshold == TEST4_THRESHOLD == 0.05
    assert result.passed is (result.ratio <= 0.05)


# ---------------------------------------------------------------- Test 5 ---

def test_test5_extended_profile_reaches_the_latest_permitted_date():
    hp = build_hp_bond(HP_MARKET_VALUE)
    curve = build_rfr_curve()
    extended = hp.extended_cashflows(curve.valuation_date)

    principal_flows = [cf for cf in extended.flows if cf.kind == CashFlowKind.PRINCIPAL]
    assert len(principal_flows) == 1
    assert principal_flows[0].time == pytest.approx(hp.latest_repayment_years)
    assert principal_flows[0].amount == pytest.approx(hp.notional, rel=1e-9)

    # step-up coupons appear after maturity_years, up to and including latest_repayment_years
    # (the final step-up coupon and the principal repayment legitimately share that last date)
    step_up_flows = [
        cf for cf in extended.flows
        if cf.kind == CashFlowKind.COUPON and hp.maturity_years < cf.time <= hp.latest_repayment_years
    ]
    assert len(step_up_flows) == round(hp.latest_repayment_years - hp.maturity_years)
    for cf in step_up_flows:
        assert cf.amount == pytest.approx(hp.notional * hp.step_up_rate)


def test_test5_modified_accumulated_shortfall_runs_and_flags_the_expected_mismatch():
    """This single HP position (notional 500k) is deliberately NOT sized to
    fully back the whole 10y/100k-p.a. liability (BEL ~811k) on its own --
    same rationale as the portfolio Test 1 case in
    test_hypothecation_and_pra_tests.py: Test 5 correctly reports a large
    shortfall here because one small, lumpy HP position cannot replicate a
    much bigger smooth annuity liability by itself. That is a correct
    diagnosis of a real mismatch, not a bug in the test."""
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)

    hp = build_hp_bond(HP_MARKET_VALUE)
    fs_table = build_fs_table()

    result = run_test5(cfs, hp, fs_table, curve, curve.valuation_date)

    assert result.inner.threshold == TEST5_THRESHOLD == 0.05
    assert result.inner.pv_liabilities_rfr == pytest.approx(cfs.pv(curve), rel=1e-9)
    assert result.ratio > result.inner.threshold
    assert result.passed is False
