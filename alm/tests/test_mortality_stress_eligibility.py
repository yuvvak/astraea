"""MA 2.2(3)/2.4 mortality-stress eligibility test, cross-checked against an
independent closed-form calculation of the single extra cash flow's PV.
"""

from __future__ import annotations

import pytest

from alm.contracts.liabilities import LevelAnnuityCohort
from alm.examples.golden_toy import build_liability, build_rfr_curve
from alm.liabilities.mortality_stress_test import (
    MORTALITY_STRESS_BEL_THRESHOLD,
    apply_mortality_improvement_stress,
    evaluate_mortality_stress_eligibility,
)


def test_stress_extends_by_exactly_one_period_at_the_final_amount():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)

    stressed = apply_mortality_improvement_stress(cfs, extra_years=1.0)

    assert len(stressed.flows) == len(cfs.flows) + 1
    extra = [f for f in stressed.flows if f.time > 10.0]
    assert len(extra) == 1
    assert extra[0].time == pytest.approx(11.0)
    assert extra[0].amount == pytest.approx(100_000.0)


def test_golden_liability_fails_the_5pct_threshold():
    """A single extra £100k payment at year 11, on a BEL of £811,089.58,
    should push BEL up by roughly 8% (much more than the 5% threshold) --
    a real, non-tautological consequence of this liability's actual size
    and duration, not a fixed shock-equals-threshold construction."""
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)

    result = evaluate_mortality_stress_eligibility(cfs, curve)

    # independent closed-form cross-check: PV of a single £100,000 payment at t=11
    # under the flat 4% curve, added to the known base BEL
    extra_pv = 100_000.0 * (1.04 ** -11)
    expected_bel_stressed = result.bel_base + extra_pv
    assert result.bel_stressed == pytest.approx(expected_bel_stressed, rel=1e-9)

    expected_ratio = extra_pv / result.bel_base
    assert result.delta_ratio == pytest.approx(expected_ratio, rel=1e-9)
    assert result.delta_ratio > MORTALITY_STRESS_BEL_THRESHOLD
    assert result.passed is False
    assert result.threshold == MORTALITY_STRESS_BEL_THRESHOLD == 0.05


def test_uniform_amount_scaling_leaves_the_ratio_unchanged():
    """Scaling every cash flow (including the final period the stress
    extrapolates from) by a fixed factor scales the extra payment's PV by
    that same factor, so the ratio is scale-invariant under a uniform
    amount scale-up. This confirms the test responds to duration/shape,
    not simply to how large the annual payment is."""
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    big_cfs = cfs.scale(50.0, id_suffix="_big")  # same 10y shape, 50x the annual amount

    result = evaluate_mortality_stress_eligibility(big_cfs, curve)
    assert result.delta_ratio == pytest.approx(0.0800874464712851, rel=1e-6)
    assert result.passed is False  # still fails: scaling amount alone never helps


def test_a_longer_duration_liability_passes_the_same_stress():
    """What actually changes the outcome is TERM, not amount: a 30y annuity
    at the same £100,000 p.a. absorbs the same one extra year's payment as
    a much smaller percentage of a much larger BEL."""
    curve = build_rfr_curve()
    long_liability = LevelAnnuityCohort(
        id="long_30y", currency="GBP", annual_payment=100_000.0, payment_frequency=1, term_years=30.0,
    )
    cfs = long_liability.best_estimate_cashflows(curve.valuation_date)

    result = evaluate_mortality_stress_eligibility(cfs, curve)

    extra_pv = 100_000.0 * (1.04 ** -31)
    expected_ratio = extra_pv / result.bel_base
    assert result.delta_ratio == pytest.approx(expected_ratio, rel=1e-9)
    assert result.delta_ratio < MORTALITY_STRESS_BEL_THRESHOLD
    assert result.passed is True
