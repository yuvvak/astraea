"""Risk Margin golden test: CoC=4%, taper λ=0.9 floor 0.25, discounted on the
basic RFR curve, cross-checked against an independently-coded summation.
"""

from __future__ import annotations

import pytest

from alm.examples.golden_toy import build_liability, build_rfr_curve
from alm.rm import (
    RM_COST_OF_CAPITAL,
    RM_TAPER_FLOOR,
    RM_TAPER_LAMBDA,
    approximate_scr_runoff,
    compute_risk_margin,
    taper_factor,
)

SCR_0_RATE = 0.05  # illustrative: SCR(0) = 5% of BEL(0)


def test_taper_factor_floor_binds_only_at_high_t():
    assert taper_factor(0) == 1.0
    assert taper_factor(1) == pytest.approx(0.9)
    assert taper_factor(10) == pytest.approx(0.9 ** 10)
    assert taper_factor(10) > RM_TAPER_FLOOR  # floor not yet binding
    # 0.9^14 = 0.2288 < 0.25, so the floor must bind from t=14 on
    assert 0.9 ** 14 < RM_TAPER_FLOOR
    assert taper_factor(14) == pytest.approx(RM_TAPER_FLOOR)
    assert taper_factor(50) == pytest.approx(RM_TAPER_FLOOR)


def test_approximate_scr_runoff_matches_bel_runoff_proportion():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    bel_0 = cfs.pv(curve)
    scr_0 = SCR_0_RATE * bel_0

    path = approximate_scr_runoff(scr_0, cfs, curve, n_years=10)

    assert path[0] == pytest.approx(scr_0, rel=1e-9)
    assert path[10] == pytest.approx(0.0, abs=1e-9)  # no liability cash flows remain after t=10
    # monotonically decreasing (level annuity, flat curve -> BEL(t) strictly shrinks with t)
    values = [path[t] for t in range(11)]
    assert all(values[i] > values[i + 1] for i in range(10))


def test_risk_margin_matches_independent_summation():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    bel_0 = cfs.pv(curve)
    scr_0 = SCR_0_RATE * bel_0

    scr_path = approximate_scr_runoff(scr_0, cfs, curve, n_years=10)
    result = compute_risk_margin(scr_path, curve)

    # independent recomputation of RM = CoC * sum_t taper(t) * SCR(t) * df(t+1),
    # coded directly rather than reusing compute_risk_margin's internals
    independent_rm = sum(
        RM_COST_OF_CAPITAL * (RM_TAPER_LAMBDA ** t if RM_TAPER_LAMBDA ** t > RM_TAPER_FLOOR else RM_TAPER_FLOOR)
        * scr_path[t] * curve.discount_factor(t + 1)
        for t in scr_path
    )
    assert result.risk_margin == pytest.approx(independent_rm, rel=1e-9)
    assert result.risk_margin > 0
    # RM should be a modest fraction of BEL for this illustrative 5%-of-BEL SCR path
    assert 0 < result.risk_margin / bel_0 < 0.05

    assert result.coc == RM_COST_OF_CAPITAL == 0.04
    assert result.lam == RM_TAPER_LAMBDA == 0.90
    assert result.floor == RM_TAPER_FLOOR == 0.25

    assert sum(result.discounted_terms.values()) == pytest.approx(result.risk_margin, rel=1e-9)
