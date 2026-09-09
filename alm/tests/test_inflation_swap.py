"""InflationSwap golden tests: net cash flows and market value cross-checked
against an independent closed-form annuity PV, receive vs pay inflation are
exact sign flips, and every flow is correctly tagged inflation_linked=True
so it feeds PRA Test 2's inflation VaR leg alongside IL gilts.
"""

from __future__ import annotations

import pytest

from alm.contracts.assets import AssetPosition, InflationSwap
from alm.contracts.cashflows import CashFlowKind
from alm.examples.golden_toy import build_corporate_bond_position, build_gilt_position, build_liability, build_rfr_curve
from alm.tests_pra.var_test import run_test2

NOTIONAL = 1_000_000.0
FIXED_RATE = 0.01
ASSUMED_INFLATION = 0.025
TERM = 10.0


def test_receive_inflation_swap_matches_independent_annuity_pv():
    curve = build_rfr_curve()
    swap = InflationSwap.from_assumption(
        id="infl_swap", currency="GBP", notional=NOTIONAL, fixed_rate=FIXED_RATE,
        maturity_years=TERM, receive_inflation=True, assumed_inflation_rate=ASSUMED_INFLATION,
    )
    position = AssetPosition(id="pos_infl_swap", instrument=swap)
    cfv = position.cashflows(curve.valuation_date)

    assert len(cfv.flows) == 10
    expected_net_per_period = (ASSUMED_INFLATION - FIXED_RATE) * NOTIONAL
    for f in cfv.flows:
        assert f.amount == pytest.approx(expected_net_per_period, rel=1e-9)
        assert f.inflation_linked is True
        assert f.kind == CashFlowKind.OTHER

    independent_pv = sum(expected_net_per_period * curve.discount_factor(t) for t in range(1, 11))
    assert position.resolved_market_value(curve) == pytest.approx(independent_pv, rel=1e-9)
    assert position.resolved_market_value(curve) > 0  # assumed inflation exceeds the fixed rate


def test_pay_inflation_is_the_exact_negative_of_receive_inflation():
    curve = build_rfr_curve()
    receive = InflationSwap.from_assumption(
        id="swap_receive", currency="GBP", notional=NOTIONAL, fixed_rate=FIXED_RATE,
        maturity_years=TERM, receive_inflation=True, assumed_inflation_rate=ASSUMED_INFLATION,
    )
    pay = InflationSwap.from_assumption(
        id="swap_pay", currency="GBP", notional=NOTIONAL, fixed_rate=FIXED_RATE,
        maturity_years=TERM, receive_inflation=False, assumed_inflation_rate=ASSUMED_INFLATION,
    )

    assert pay.price(curve) == pytest.approx(-receive.price(curve), rel=1e-9)


def test_inflation_swap_feeds_pra_test2_inflation_var_leg():
    curve = build_rfr_curve()
    liability = build_liability()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    bel = cfs.pv(curve)

    swap = InflationSwap.from_assumption(
        id="infl_swap", currency="GBP", notional=NOTIONAL, fixed_rate=FIXED_RATE,
        maturity_years=TERM, receive_inflation=True, assumed_inflation_rate=ASSUMED_INFLATION,
    )
    swap_pos = AssetPosition(id="pos_infl_swap", instrument=swap)
    gilt = build_gilt_position(bel=bel)
    corp = build_corporate_bond_position(600_000.0)

    result = run_test2([gilt, corp, swap_pos], curve, bel, curve.valuation_date)

    swap_mv = swap_pos.resolved_market_value(curve)
    assert result.inflation.base_value == pytest.approx(swap_mv, rel=1e-9)
    assert result.inflation.var == pytest.approx(swap_mv * 0.01, rel=1e-9)  # +/-1% illustrative shock
