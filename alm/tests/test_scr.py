"""SF SCR skeleton golden test: spread + longevity sub-modules, aggregated
with the market<->life correlation parameter, on the single-corporate-bond
portfolio (MV=750,000, A2 non-financial, base MA=135.4464bp -- same
portfolio as test_stresses.py).
"""

from __future__ import annotations

import math

import pytest

from alm.examples.golden_toy import build_corporate_bond_position, build_fs_table, build_liability, build_rfr_curve
from alm.scr import (
    LONGEVITY_SHOCK_BEL_UPLIFT,
    MARKET_LIFE_CORRELATION,
    compute_longevity_scr,
    compute_map_standard_formula_scr,
    compute_spread_scr,
)
from alm.contracts.fs import RatingNotch

CORP_MV = 750_000.0


def _base():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    corp = build_corporate_bond_position(CORP_MV)
    fs_table = build_fs_table()
    return cfs, curve, corp, fs_table


def _independent_macaulay_duration(position, curve):
    """Reimplemented directly from the position's cash flows, NOT via
    `alm.scr.macaulay_duration`, to keep this an independent cross-check."""
    cfs = position.instrument.contractual_cashflows(curve.valuation_date)
    weighted, total_pv = 0.0, 0.0
    for cf in cfs.flows:
        pv = cf.amount * curve.discount_factor(cf.time)
        weighted += cf.time * pv
        total_pv += pv
    return weighted / total_pv


def test_spread_scr_is_the_real_3d17_cqs2_stress_times_market_value():
    cfs, curve, corp, fs_table = _base()
    result = compute_spread_scr([corp], curve)

    # CORP_A2_4_75pct_10y is a 10y A2 (CQS2) bond -- duration falls in the
    # 5-10y band: stress = 7.0% + 0.7% * (dur - 5) (PRA Rulebook 3D17).
    duration = _independent_macaulay_duration(corp, curve)
    assert 5.0 < duration < 10.0
    expected_factor = 0.070 + 0.007 * (duration - 5.0)
    assert result.scr_spread == pytest.approx(expected_factor * CORP_MV, rel=1e-9)
    assert result.contributions_by_position["pos_corp"] == pytest.approx(expected_factor * CORP_MV, rel=1e-9)


def test_longevity_scr_holds_ma_rate_fixed_and_only_shocks_bel():
    cfs, curve, corp, fs_table = _base()
    result = compute_longevity_scr(cfs, [corp], curve, fs_table, curve.valuation_date)

    # independent cross-check: re-discount the 20%-larger liability at exactly
    # (base RFR + base MA rate), coded directly rather than via the module
    stressed_cfs = cfs.scale(1.0 + LONGEVITY_SHOCK_BEL_UPLIFT, id_suffix="_check")
    ma_curve = curve.shift_parallel(result.base_ma.ma_rate)
    expected_bel_with_ma_stressed = stressed_cfs.pv(ma_curve)
    assert result.bel_with_ma_stressed == pytest.approx(expected_bel_with_ma_stressed, rel=1e-9)

    expected_loss = max(0.0, result.own_funds_base - result.own_funds_stressed)
    assert result.scr_longevity == pytest.approx(expected_loss, rel=1e-9)
    assert result.scr_longevity > 0  # a 20% BEL uplift at a fixed MA rate/MV must be a real loss

    assert result.own_funds_base == pytest.approx(CORP_MV - result.base_ma.bel_with_ma, rel=1e-9)


def test_map_standard_formula_scr_aggregates_with_the_correlation_formula():
    cfs, curve, corp, fs_table = _base()
    result = compute_map_standard_formula_scr(cfs, [corp], curve, fs_table, curve.valuation_date)

    s = result.spread.scr_spread
    l = result.longevity.scr_longevity
    rho = result.correlation_market_life
    assert rho == MARKET_LIFE_CORRELATION == 0.25

    expected_total = math.sqrt(s * s + l * l + 2 * rho * s * l)
    assert result.scr_total == pytest.approx(expected_total, rel=1e-9)

    # aggregated SCR must be less than the naive sum (correlation < 1 gives sub-additivity)
    assert result.scr_total < s + l
    # and at least as large as either standalone leg
    assert result.scr_total >= max(s, l)
