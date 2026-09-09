"""Hypothecation with a derivative position: covers three real fixes made
while wiring InterestRateSwap into the waterfall.

1. A negative cash flow (e.g. a swap's net outflow in a period) must
   INCREASE remaining liability need at that bucket, not be silently
   dropped (the old code's `if cf.amount <= 0: continue` discarded it).
2. Derivatives must not be assigned to Component A (assigned_pv/total_pv
   is not a meaningful fraction for a mixed-sign cash flow stream).
3. Component B's fraction_b guard must key off `abs(mv_p) > tolerance`,
   not `mv_p > tolerance` -- a negative-MV position (an out-of-the-money
   swap) is a well-defined non-zero divisor, and using the wrong guard
   left fraction_b silently at 0 while `covered_mv` was still correctly
   adjusted, double-counting the position's value into Component C via
   the `fraction_c = max(0, 1 - fa - fb)` fallback.

Every fix is checked against the invariant that must always hold:
component_ab_market_value + component_c_market_value == total portfolio
market value.
"""

from __future__ import annotations

import pytest

from alm.contracts.assets import AssetPosition, InterestRateSwap
from alm.contracts.fs import RatingNotch
from alm.examples.golden_toy import build_corporate_bond_position, build_fs_table, build_liability, build_rfr_curve
from alm.ma.hypothecation import hypothecate

CORP_MV = 500_000.0
SWAP_NOTIONAL = 1_000_000.0
SWAP_FIXED_RATE = 0.06  # paying 6% fixed vs 4% floating -> out of the money


def _portfolio():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    fs_table = build_fs_table()
    corp = build_corporate_bond_position(CORP_MV)
    swap = InterestRateSwap.from_curve(
        id="swap_hedge", currency="GBP", notional=SWAP_NOTIONAL, fixed_rate=SWAP_FIXED_RATE,
        maturity_years=10.0, curve=curve, receive_fixed=False, rating=RatingNotch.A2,
    )
    swap_pos = AssetPosition(id="pos_swap", instrument=swap)
    return cfs, curve, fs_table, corp, swap_pos


def test_swap_market_value_is_negative_out_of_the_money():
    _, curve, _, _, swap_pos = _portfolio()
    assert swap_pos.resolved_market_value(curve) < 0


def test_derivative_gets_zero_fraction_a_never_assigned_to_component_a():
    cfs, curve, fs_table, corp, swap_pos = _portfolio()
    result = hypothecate(cfs, [corp, swap_pos], fs_table, curve.valuation_date, curve)

    swap_assignment = result.assignment_for("pos_swap")
    assert swap_assignment.fraction_a == 0.0
    assert swap_assignment.market_value_a == pytest.approx(0.0)


def test_negative_cashflows_increase_remaining_liability_at_that_bucket():
    cfs, curve, fs_table, corp, swap_pos = _portfolio()

    # baseline: corp bond alone, no swap
    baseline = hypothecate(cfs, [corp], fs_table, curve.valuation_date, curve)
    # with the swap added: every bucket the swap has a negative cash flow in
    # must show a HIGHER remaining liability than the baseline (the swap's
    # own draw stacks on top of whatever the corp bond didn't already cover)
    with_swap = hypothecate(cfs, [corp, swap_pos], fs_table, curve.valuation_date, curve)

    swap_cfv = swap_pos.cashflows(curve.valuation_date)
    negative_times = {f.time for f in swap_cfv.flows if f.amount < 0}
    assert len(negative_times) == 10  # every period is negative for this deeply OTM pay-fixed swap

    for t in negative_times:
        assert with_swap.remaining_liability_by_time[t] > baseline.remaining_liability_by_time[t]


def test_negative_mv_position_gets_correct_fraction_b_not_double_counted_in_c():
    cfs, curve, fs_table, corp, swap_pos = _portfolio()
    result = hypothecate(cfs, [corp, swap_pos], fs_table, curve.valuation_date, curve)

    swap_assignment = result.assignment_for("pos_swap")
    swap_mv = swap_pos.resolved_market_value(curve)

    # the swap's entire (negative) MV must land in B, not silently fall through
    # to C via the fraction_c = max(0, 1-fa-fb) fallback
    assert swap_assignment.fraction_b == pytest.approx(1.0, rel=1e-9)
    assert swap_assignment.market_value_b == pytest.approx(swap_mv, rel=1e-9)
    assert swap_assignment.fraction_c == pytest.approx(0.0, abs=1e-9)
    assert swap_assignment.market_value_c == pytest.approx(0.0, abs=1e-6)


def test_component_ab_plus_c_equals_total_portfolio_market_value():
    """The invariant that would have been silently violated by the fraction_b
    guard bug: every pound of market value must land in exactly one of
    A+B or C, never double-counted and never dropped."""
    cfs, curve, fs_table, corp, swap_pos = _portfolio()
    result = hypothecate(cfs, [corp, swap_pos], fs_table, curve.valuation_date, curve)

    total_mv = corp.resolved_market_value(curve) + swap_pos.resolved_market_value(curve)
    assert result.component_ab_market_value + result.component_c_market_value == pytest.approx(total_mv, rel=1e-9)


def test_existing_bond_only_portfolios_are_completely_unaffected():
    """Regression: for any portfolio with only non-negative cash flows and
    positive market values (every instrument type before InterestRateSwap),
    the new `abs(mv_p)` guard and the negative-cash-flow branch must never
    trigger, so results must be byte-for-byte identical to before."""
    from alm.examples.golden_toy import build_gilt5y_position

    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    fs_table = build_fs_table()
    gilt5 = build_gilt5y_position(300_000.0)
    corp600 = build_corporate_bond_position(600_000.0)

    result = hypothecate(cfs, [gilt5, corp600], fs_table, curve.valuation_date, curve)

    # matches the exact figures established in test_hypothecation_and_pra_tests.py
    assert result.component_a_market_value == pytest.approx(354_281.6555479865, rel=1e-9)
    assert result.component_ab_market_value == pytest.approx(811_089.5779355026, rel=1e-9)
    assert result.component_c_market_value == pytest.approx(88_910.42206449732, rel=1e-9)
