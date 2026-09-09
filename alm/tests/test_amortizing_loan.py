"""AmortizingLoan golden tests (covers infra debt, ERM restructured notes,
project finance, CRE loans): both amortization styles checked against
independent closed-form mortgage/loan-amortization formulas.
"""

from __future__ import annotations

import pytest

from alm.contracts.assets import AmortizingLoan, AssetPosition
from alm.contracts.cashflows import CashFlowKind
from alm.contracts.fs import AssetSector, RatingNotch
from alm.examples.golden_toy import build_rfr_curve

NOTIONAL = 500_000.0
COUPON = 0.05
TERM = 10.0


def _loan(style: str) -> AmortizingLoan:
    return AmortizingLoan(
        id=f"loan_{style}", currency="GBP", notional=NOTIONAL, coupon_rate=COUPON,
        coupon_frequency=1, maturity_years=TERM, amortization_style=style,
        rating=RatingNotch.BBB2, sector=AssetSector.OTHER,
    )


def test_level_principal_repays_equal_principal_each_year_with_declining_interest():
    curve = build_rfr_curve()
    loan = _loan("level_principal")
    cfv = loan.contractual_cashflows(curve.valuation_date)

    principal_flows = sorted([f for f in cfv.flows if f.kind == CashFlowKind.PRINCIPAL], key=lambda f: f.time)
    coupon_flows = sorted([f for f in cfv.flows if f.kind == CashFlowKind.COUPON], key=lambda f: f.time)
    assert len(principal_flows) == 10
    assert len(coupon_flows) == 10

    expected_principal_per_period = NOTIONAL / 10
    for f in principal_flows:
        assert f.amount == pytest.approx(expected_principal_per_period, rel=1e-9)

    # independent closed-form: interest at period i = (notional - (i-1)*principal_per_period) * coupon_rate
    for i, f in enumerate(coupon_flows, start=1):
        remaining_before = NOTIONAL - (i - 1) * expected_principal_per_period
        assert f.amount == pytest.approx(remaining_before * COUPON, rel=1e-9)

    total_principal = sum(f.amount for f in principal_flows)
    assert total_principal == pytest.approx(NOTIONAL, rel=1e-9)


def test_level_payment_matches_the_standard_mortgage_formula():
    curve = build_rfr_curve()
    loan = _loan("level_payment")
    cfv = loan.contractual_cashflows(curve.valuation_date)

    # independent closed-form: payment = P * r / (1 - (1+r)^-n)
    expected_payment = NOTIONAL * COUPON / (1.0 - (1.0 + COUPON) ** (-10))

    by_time: dict[float, float] = {}
    for f in cfv.flows:
        by_time[f.time] = by_time.get(f.time, 0.0) + f.amount
    assert len(by_time) == 10
    for t, total in by_time.items():
        assert total == pytest.approx(expected_payment, rel=1e-9)

    total_principal = sum(f.amount for f in cfv.flows if f.kind == CashFlowKind.PRINCIPAL)
    assert total_principal == pytest.approx(NOTIONAL, rel=1e-9)

    total_paid = sum(f.amount for f in cfv.flows)
    assert total_paid == pytest.approx(expected_payment * 10, rel=1e-9)


def test_level_payment_market_value_matches_independent_pv():
    curve = build_rfr_curve()
    loan = _loan("level_payment")
    position = AssetPosition(id="pos_erm_note", instrument=loan)

    cfv = loan.contractual_cashflows(curve.valuation_date)
    independent_mv = sum(f.amount * curve.discount_factor(f.time) for f in cfv.flows)
    assert position.resolved_market_value(curve) == pytest.approx(independent_mv, rel=1e-9)
    # coupon (5%) > RFR (4%) -> priced at a premium to par
    assert position.resolved_market_value(curve) > NOTIONAL


def test_unknown_amortization_style_raises():
    curve = build_rfr_curve()
    loan = AmortizingLoan(
        id="bad", currency="GBP", notional=NOTIONAL, coupon_rate=COUPON,
        maturity_years=TERM, amortization_style="bullet_style_typo",
    )
    with pytest.raises(ValueError, match="unknown amortization_style"):
        loan.contractual_cashflows(curve.valuation_date)
