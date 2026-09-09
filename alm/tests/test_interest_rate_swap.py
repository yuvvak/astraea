"""InterestRateSwap golden tests: a par swap (fixed rate == flat curve
rate) must produce exactly zero net cash flows and zero market value; an
off-market swap's net cash flows and market value are cross-checked
against an independent closed-form annuity PV; and receive-fixed vs
pay-fixed must be exact sign flips of each other.
"""

from __future__ import annotations

import pytest

from alm.contracts.assets import InterestRateSwap
from alm.examples.golden_toy import build_rfr_curve

NOTIONAL = 1_000_000.0
TERM = 10.0
FLAT_RATE = 0.04  # golden_toy's RFR_FLAT_RATE


def test_par_swap_has_zero_net_cashflows_and_zero_market_value():
    curve = build_rfr_curve()
    swap = InterestRateSwap.from_curve(
        id="swap_par", currency="GBP", notional=NOTIONAL, fixed_rate=FLAT_RATE,
        maturity_years=TERM, curve=curve, receive_fixed=True,
    )
    cfv = swap.contractual_cashflows(curve.valuation_date)

    assert len(cfv.flows) == 10
    for f in cfv.flows:
        assert f.amount == pytest.approx(0.0, abs=1e-6)
    assert swap.price(curve) == pytest.approx(0.0, abs=1e-6)


def test_off_market_receive_fixed_swap_matches_independent_annuity_pv():
    curve = build_rfr_curve()
    fixed_rate = 0.05  # 100bp above the flat 4% floating curve
    swap = InterestRateSwap.from_curve(
        id="swap_5pct", currency="GBP", notional=NOTIONAL, fixed_rate=fixed_rate,
        maturity_years=TERM, curve=curve, receive_fixed=True,
    )
    cfv = swap.contractual_cashflows(curve.valuation_date)

    # on a flat curve, the annual forward rate is exactly the flat rate, so
    # the net cash flow every period is exactly (fixed - floating) * notional
    expected_net_per_period = (fixed_rate - FLAT_RATE) * NOTIONAL
    for f in cfv.flows:
        assert f.amount == pytest.approx(expected_net_per_period, rel=1e-9)

    independent_pv = sum(expected_net_per_period * curve.discount_factor(t) for t in range(1, 11))
    assert swap.price(curve) == pytest.approx(independent_pv, rel=1e-9)
    assert swap.price(curve) > 0  # receiving above-market fixed is valuable


def test_pay_fixed_is_the_exact_negative_of_receive_fixed():
    curve = build_rfr_curve()
    receive = InterestRateSwap.from_curve(
        id="swap_receive", currency="GBP", notional=NOTIONAL, fixed_rate=0.05,
        maturity_years=TERM, curve=curve, receive_fixed=True,
    )
    pay = InterestRateSwap.from_curve(
        id="swap_pay", currency="GBP", notional=NOTIONAL, fixed_rate=0.05,
        maturity_years=TERM, curve=curve, receive_fixed=False,
    )

    assert pay.price(curve) == pytest.approx(-receive.price(curve), rel=1e-9)

    receive_flows = {f.time: f.amount for f in receive.contractual_cashflows(curve.valuation_date).flows}
    pay_flows = {f.time: f.amount for f in pay.contractual_cashflows(curve.valuation_date).flows}
    for t in receive_flows:
        assert pay_flows[t] == pytest.approx(-receive_flows[t], rel=1e-9)


def test_frozen_projection_does_not_reproject_under_a_different_curve():
    """A swap built from one curve keeps its frozen expected cash flows even
    when priced against a different curve -- pricing discounts the SAME
    frozen amounts at the new curve, it does not re-derive new forward
    rates. This is the documented v1 limitation, verified directly rather
    than just asserted in prose."""
    curve = build_rfr_curve()
    swap = InterestRateSwap.from_curve(
        id="swap_frozen", currency="GBP", notional=NOTIONAL, fixed_rate=0.05,
        maturity_years=TERM, curve=curve, receive_fixed=True,
    )
    original_flows = swap.contractual_cashflows(curve.valuation_date).flows

    shifted_curve = curve.shift_parallel(-0.01)  # -100bp
    flows_under_shifted_curve = swap.contractual_cashflows(shifted_curve.valuation_date).flows

    # same instrument object, same frozen amounts, regardless of which curve prices it
    assert [f.amount for f in flows_under_shifted_curve] == [f.amount for f in original_flows]

    # but the MARKET VALUE still differs, because pricing discounts those frozen
    # amounts at whichever curve is passed to price()
    assert swap.price(curve) != pytest.approx(swap.price(shifted_curve))
