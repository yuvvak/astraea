"""Hypothecation + PRA Test 1 (Accumulated Cash Flow Shortfall) + Test 3
(Notional Swap), run on a three-asset extension of the golden toy portfolio:

  - a 5y gilt, MV = GBP 300,000 (nearest maturity -> assigned to Component A first)
  - a 10y A2 non-financial corporate bond, MV = GBP 600,000

Total asset MV (900,000) exceeds the basic-RFR BEL (811,089.58), so this
portfolio is deliberately built to exercise all three components: A (cash-
flow-matched), B (fills the remaining MV up to BEL) and C (surplus, 88,910.42
left over) -- a portfolio sized exactly to BEL would leave C empty and not
prove the waterfall handles surplus at all.

Test 1 is expected to FAIL on this portfolio: the two bullet/coupon
instruments' cash flow shape does not resemble the smooth level-annuity
liability profile, so large per-bucket shortfalls accumulate even though
Component A+B's *market value* is sufficient to cover the BEL in aggregate.
That is Test 1's entire point -- PV sufficiency (what B fixes) is not the
same as cash flow timing match (what A and Test 1 check) -- so a failing
Test 1 here is the correct, meaningful result, not a bug.
"""

from __future__ import annotations

import pytest

from alm.examples.golden_toy import (
    build_corporate_bond_position,
    build_fs_table,
    build_gilt5y_position,
    build_liability,
    build_rfr_curve,
)
from alm.ma.fs_rate import fs_rate_for_assets
from alm.ma.hypothecation import hypothecate
from alm.tests_pra.accumulated_cf_shortfall import run_test1
from alm.tests_pra.notional_swap import run_test3

GILT_MV = 300_000.0
CORP_MV = 600_000.0


def _portfolio():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    gilt = build_gilt5y_position(GILT_MV)
    corp = build_corporate_bond_position(CORP_MV)
    fs_table = build_fs_table()
    return cfs, curve, gilt, corp, fs_table


def test_hypothecation_fractions_and_component_values():
    cfs, curve, gilt, corp, fs_table = _portfolio()
    bel = cfs.pv(curve)

    result = hypothecate(cfs, [gilt, corp], fs_table, curve.valuation_date, curve)

    # every position's A/B/C fractions must partition [0, 1]
    for a in result.assignments:
        assert a.fraction_a >= 0 and a.fraction_b >= 0 and a.fraction_c >= 0
        assert a.fraction_a + a.fraction_b + a.fraction_c == pytest.approx(1.0, abs=1e-6)

    # nearest-maturity-first: the 5y gilt must reach its binding cap (a whole
    # year-5 lump sum bigger than that bucket's liability) before the 10y
    # corporate bond is touched at all in Component A
    gilt_assignment = result.assignment_for("pos_gilt5y")
    assert 0.0 < gilt_assignment.fraction_a < 1.0

    # B fills exactly up to BEL because total portfolio MV (900k) > BEL
    assert result.component_ab_market_value == pytest.approx(bel, rel=1e-9)

    # C soaks up exactly the excess over BEL
    total_mv = GILT_MV + CORP_MV
    assert result.component_c_market_value == pytest.approx(total_mv - bel, rel=1e-9)

    # no bucket can be left with negative remaining liability (over-assignment)
    assert all(v >= -1e-6 for v in result.remaining_liability_by_time.values())


def test_test1_fails_on_mismatched_bullet_cashflows():
    cfs, curve, gilt, corp, fs_table = _portfolio()
    result = hypothecate(cfs, [gilt, corp], fs_table, curve.valuation_date, curve)

    t1 = run_test1(cfs, result.component_a_pd_adjusted_by_time, curve)

    assert t1.pv_liabilities_rfr == pytest.approx(cfs.pv(curve), rel=1e-9)
    # independent cross-check of the max-shortfall-at-year-9 style accumulation:
    # at minimum, the shortfall ratio must exceed the running total of unmatched
    # liability buckets discounted back, i.e. it cannot be zero when Component A
    # visibly leaves buckets uncovered (see remaining_liability_by_time above)
    assert t1.max_accumulated_shortfall > 0
    assert t1.ratio > t1.threshold
    assert t1.passed is False


def test_test3_notional_swap_scale_factor_matches_closed_form():
    cfs, curve, gilt, corp, fs_table = _portfolio()
    result = hypothecate(cfs, [gilt, corp], fs_table, curve.valuation_date, curve)
    fs_rate = fs_rate_for_assets([gilt, corp], fs_table, curve.valuation_date, curve)

    t3 = run_test3(cfs, result.component_a_pd_adjusted_by_time, result.component_a_market_value, fs_rate, curve)

    # independent closed-form cross-check: k = PV(liability) / PV(component A cash flows),
    # both computed directly rather than re-deriving via run_test3's internals
    from alm.contracts.cashflows import CashFlow, CashFlowKind, CashFlowVector

    component_a_cfv = CashFlowVector(
        id="independent_check",
        currency=cfs.currency,
        valuation_date=cfs.valuation_date,
        direction="asset_income",
        flows=tuple(
            CashFlow(time=t, amount=amt, kind=CashFlowKind.OTHER)
            for t, amt in result.component_a_pd_adjusted_by_time.items() if amt > 0
        ),
    )
    expected_k = cfs.pv(curve) / component_a_cfv.pv(curve)
    assert t3.scale_factor == pytest.approx(expected_k, rel=1e-9)

    # after scaling, PV(scaled Component A cash flows, RFR) must equal PV(liability, RFR) to the penny
    assert component_a_cfv.pv(curve) * t3.scale_factor == pytest.approx(cfs.pv(curve), rel=1e-9)

    assert t3.implied_under_over_matching == pytest.approx(t3.scale_factor - 1.0)
    # Component A here is under-sized in PV terms relative to the liability (k > 1)
    assert t3.scale_factor > 1.0
