"""Golden-file tests: MA, BEL and the AER solver checked against independent
hand/closed-form calculations, not just against the engine's own internals.

Deliverable 9 ("golden test: small portfolio where MA bps ... can be checked
by hand") and the instruction to reproduce the toy gilt-vs-annuity example
before any further module is scaffolded.
"""

from __future__ import annotations

import math

import pytest

from alm.examples.golden_toy import (
    LIABILITY_ANNUAL_PAYMENT,
    LIABILITY_TERM_YEARS,
    RFR_FLAT_RATE,
    build_corporate_bond_position,
    build_fs_table,
    build_gilt_position,
    build_liability,
    build_rfr_curve,
)
from alm.ma.engine import compute_ma
from alm.ma.fs_rate import fs_rate_for_assets
from alm.ma.two_aer import solve_aer


def closed_form_annuity_pv(payment: float, rate: float, n: int) -> float:
    """Independent closed-form PV of a level annual annuity-certain, used as
    ground truth (deliberately not sharing code with CashFlowVector.pv)."""
    return payment * (1 - (1 + rate) ** (-n)) / rate


def closed_form_annuity_rate(payment: float, target_pv: float, n: int) -> float:
    """Independent bisection for the flat rate that PVs a level annuity to
    `target_pv`, used to cross-check `solve_aer` without reusing it."""
    lo, hi = 1e-6, 2.0

    def f(r):
        return closed_form_annuity_pv(payment, r, n) - target_pv

    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def test_bel_matches_closed_form_annuity():
    liability = build_liability()
    curve = build_rfr_curve()
    bel = liability.best_estimate_cashflows(curve.valuation_date).pv(curve)
    expected = closed_form_annuity_pv(LIABILITY_ANNUAL_PAYMENT, RFR_FLAT_RATE, int(LIABILITY_TERM_YEARS))
    assert bel == pytest.approx(expected, rel=1e-9)
    # sanity: known value to 2dp, 100k p.a. for 10y at 4% flat
    assert bel == pytest.approx(811_090.0, abs=50.0)


def test_r2_equals_flat_rfr_rate_exactly():
    """Invariant: when the RFR curve is flat at rate x, the AER that
    reproduces the basic-RFR BEL must equal x (to solver tolerance),
    regardless of the liability cash flow shape."""
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    bel = cfs.pv(curve)
    r2 = solve_aer(cfs, bel)
    assert r2 == pytest.approx(RFR_FLAT_RATE, abs=1e-9)


def test_scenario_a_gilt_backed_annuity_ma_is_zero():
    """Gilt priced off the same RFR curve, MV set to exactly BEL: MA must be
    exactly zero (government FS = 0, and r1 == r2 by construction)."""
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    bel = cfs.pv(curve)

    gilt_position = build_gilt_position(bel=bel)
    mv = gilt_position.resolved_market_value(curve)
    assert mv == pytest.approx(bel, rel=1e-9)  # gilt priced at par at the RFR curve

    fs_rate = fs_rate_for_assets([gilt_position], build_fs_table(), curve.valuation_date, curve)
    assert fs_rate == 0.0  # government => FS nil by PRA convention

    result = compute_ma(cfs, asset_market_value=mv, fs_rate=fs_rate, rfr_curve=curve)

    assert result.ma_bps == pytest.approx(0.0, abs=1e-6)
    assert result.rate_asset_implied == pytest.approx(result.rate_basic_rfr_aer, abs=1e-9)
    assert result.bel_with_ma == pytest.approx(result.bel_basic_rfr, rel=1e-9)
    assert result.ma_benefit == pytest.approx(0.0, abs=1e-3)


def test_scenario_b_corporate_bond_ma_positive_and_matches_independent_calc():
    """Corporate bond, MV < basic-RFR BEL (realistic funding position): MA
    must be strictly positive, and r1 must match an independently-computed
    bisection root, and MA must equal r1 - r2 - FS_rate to the penny."""
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    bel = cfs.pv(curve)

    corp_mv = 750_000.0
    corp_position = build_corporate_bond_position(market_value=corp_mv)
    fs_table = build_fs_table()

    fs_rate = fs_rate_for_assets([corp_position], fs_table, curve.valuation_date, curve)
    # single FS entry covering the whole 10y term => uniform 25bp across every cash flow
    assert fs_rate == pytest.approx(0.0025, rel=1e-9)

    result = compute_ma(cfs, asset_market_value=corp_mv, fs_rate=fs_rate, rfr_curve=curve)

    independent_r1 = closed_form_annuity_rate(LIABILITY_ANNUAL_PAYMENT, corp_mv, int(LIABILITY_TERM_YEARS))
    assert result.rate_asset_implied == pytest.approx(independent_r1, abs=1e-6)
    assert result.rate_basic_rfr_aer == pytest.approx(RFR_FLAT_RATE, abs=1e-9)

    expected_ma_rate = independent_r1 - RFR_FLAT_RATE - 0.0025
    assert result.ma_rate == pytest.approx(expected_ma_rate, abs=1e-9)

    assert result.ma_rate > 0
    assert result.ma_bps == pytest.approx(expected_ma_rate * 10_000, abs=1e-6)

    # BEL with MA must sit between the asset MV and the basic-RFR BEL:
    # MA nets off FS, so the MA-discounted reserve is more prudent (higher)
    # than raw asset MV, but still much lower than the undiscounted-spread BEL.
    assert corp_mv < result.bel_with_ma < bel


def test_aer_solver_rejects_nonpositive_target_pv():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    with pytest.raises(Exception):
        solve_aer(cfs, target_pv=0.0)
