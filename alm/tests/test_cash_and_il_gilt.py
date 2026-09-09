"""Cash and index-linked gilt asset types, cross-checked by hand, plus the
first genuine (non-zero) exercise of PRA Test 2's inflation VaR leg, which
was always exactly zero before because no inflation-linked asset existed
in any portfolio.
"""

from __future__ import annotations

import pytest

from alm.contracts.cashflows import CashFlowKind
from alm.examples.golden_toy import (
    build_cash_position,
    build_corporate_bond_position,
    build_gilt_position,
    build_il_gilt_position,
    build_liability,
    build_rfr_curve,
)
from alm.tests_pra.var_test import run_test2


def test_cash_position_is_a_single_flow_at_t_zero_with_no_discounting():
    curve = build_rfr_curve()
    cash = build_cash_position(50_000.0)

    assert cash.resolved_market_value(curve) == pytest.approx(50_000.0)

    cfv = cash.cashflows(curve.valuation_date)
    assert len(cfv.flows) == 1
    flow = cfv.flows[0]
    assert flow.time == 0.0
    assert flow.amount == pytest.approx(50_000.0)
    assert flow.kind == CashFlowKind.PRINCIPAL

    assert cash.instrument.is_government is True  # FS-nil, PRA convention


def test_il_gilt_cashflows_match_the_inflation_uplift_formula():
    curve = build_rfr_curve()
    il = build_il_gilt_position(200_000.0, assumed_inflation_rate=0.025)
    cfv = il.cashflows(curve.valuation_date)

    coupon_flows = [f for f in cfv.flows if f.kind == CashFlowKind.COUPON]
    principal_flows = [f for f in cfv.flows if f.kind == CashFlowKind.PRINCIPAL]
    assert len(coupon_flows) == 10
    assert len(principal_flows) == 1

    for f in cfv.flows:
        assert f.inflation_linked is True

    real_coupon = 200_000.0 * 0.0125
    for f in coupon_flows:
        expected = real_coupon * (1.025 ** f.time)
        assert f.amount == pytest.approx(expected, rel=1e-9)

    expected_principal = 200_000.0 * (1.025 ** 10)
    assert principal_flows[0].amount == pytest.approx(expected_principal, rel=1e-9)
    assert principal_flows[0].time == pytest.approx(10.0)

    # independent cross-check of the priced market value: PV of the uplifted
    # cash flows at the nominal RFR curve, computed directly rather than via
    # AssetPosition.resolved_market_value
    independent_mv = sum(f.amount * curve.discount_factor(f.time) for f in cfv.flows)
    assert il.resolved_market_value(curve) == pytest.approx(independent_mv, rel=1e-9)


def test_pra_test2_inflation_leg_is_now_genuinely_nonzero():
    """Before this instrument existed, Test 2's inflation leg was always
    exactly 0 (no inflation-linked cash flows anywhere) -- a correct but
    untested-in-anger code path. This portfolio finally exercises it."""
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    bel = cfs.pv(curve)

    gilt = build_gilt_position(bel=bel)
    corp = build_corporate_bond_position(600_000.0)
    il = build_il_gilt_position(200_000.0)

    result = run_test2([gilt, corp, il], curve, bel, curve.valuation_date)

    il_mv = il.resolved_market_value(curve)
    assert result.inflation.base_value == pytest.approx(il_mv, rel=1e-9)

    # a uniform +/-1% shock to every inflation-linked cash flow amount scales
    # its PV by exactly +/-1% (PV is linear in cash flow amount), so VaR must
    # be exactly 1% of the inflation-linked base value
    assert result.inflation.var == pytest.approx(il_mv * 0.01, rel=1e-9)
    assert result.inflation.ratio_to_bel == pytest.approx(result.inflation.var / bel, rel=1e-9)
    assert result.inflation.passed is True  # well inside the 1%-of-BEL threshold

    # the currency leg is still correctly zero: every position here is GBP
    assert result.currency.var == 0.0
