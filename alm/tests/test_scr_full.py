"""Full Standard Formula SCR golden test: currency, concentration,
counterparty default and operational risk sub-modules, plus the two-level
correlation aggregation (market = corr(spread, currency, concentration,
interest_rate); BSCR = corr(market, life, counterparty); SCR = BSCR +
operational), each cross-checked against an independent calculation, on a
3-asset portfolio
(A2 GBP corporate £600k, A3 USD corporate £150k, cash £50k, £800k total)
built specifically to give every sub-module a genuine non-zero result.
"""

from __future__ import annotations

import math

import pytest

from alm.examples.golden_toy import (
    build_cash_position,
    build_corporate_bond_position,
    build_fs_table,
    build_liability,
    build_rfr_curve,
    build_usd_bond_position,
)
from alm.scr import (
    CURRENCY_SHOCK,
    MARKET_RISK_CORRELATION_IR_FALL_BINDING,
    MARKET_RISK_CORRELATION_IR_RISE_BINDING,
    TOP_LEVEL_CORRELATION,
    aggregate_via_correlation,
    compute_concentration_scr,
    compute_counterparty_default_scr,
    compute_currency_scr,
    compute_full_standard_formula_scr,
    compute_interest_rate_scr,
    compute_operational_scr,
)
from alm.pra_calibration import concentration_threshold_and_factor
from alm.contracts.fs import RatingNotch

CORP_MV = 600_000.0
USD_MV = 150_000.0
CASH_MV = 50_000.0
TOTAL_MV = CORP_MV + USD_MV + CASH_MV


def _portfolio():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    fs_table = build_fs_table()
    corp = build_corporate_bond_position(CORP_MV)
    usd = build_usd_bond_position(USD_MV)
    cash = build_cash_position(CASH_MV)
    return cfs, curve, fs_table, [corp, usd, cash]


def test_currency_scr_only_counts_non_base_currency_exposure():
    _, curve, _, positions = _portfolio()
    result = compute_currency_scr(positions, curve)

    assert result.total_fx_exposure == pytest.approx(USD_MV)
    assert result.scr_currency == pytest.approx(CURRENCY_SHOCK * USD_MV, rel=1e-9)
    assert "pos_corp" not in result.exposure_by_position
    assert "pos_cash" not in result.exposure_by_position


def test_concentration_scr_matches_independent_sum_of_squares():
    """Both bond positions are A2/A3 (CQS2): real 3D29/3D30 threshold 3%,
    risk factor 21%. Cash is government (g_i = 0) and excluded entirely."""
    _, curve, _, positions = _portfolio()
    result = compute_concentration_scr(positions, curve)

    assert result.total_assets == pytest.approx(TOTAL_MV)

    expected_charges = {"pos_cash": 0.0}
    for pid, mv in [("pos_corp", CORP_MV), ("pos_usd_corp", USD_MV)]:
        threshold_pct, risk_factor = concentration_threshold_and_factor(RatingNotch.A2)
        assert (threshold_pct, risk_factor) == pytest.approx((0.03, 0.21))
        share = mv / TOTAL_MV
        excess = max(0.0, share - threshold_pct)
        expected_charges[pid] = excess * TOTAL_MV * risk_factor

    for pid, expected in expected_charges.items():
        assert result.charge_by_position[pid] == pytest.approx(expected, rel=1e-9)

    expected_scr = math.sqrt(sum(c ** 2 for c in expected_charges.values()))
    assert result.scr_concentration == pytest.approx(expected_scr, rel=1e-9)
    # sum-of-squares aggregation must be strictly less than a naive linear sum
    assert result.scr_concentration < sum(expected_charges.values())


def test_counterparty_default_scr_only_prices_cash_exposure():
    _, curve, _, positions = _portfolio()
    result = compute_counterparty_default_scr(positions, curve)

    assert result.cash_exposure == pytest.approx(CASH_MV)
    assert result.scr_counterparty == pytest.approx(0.15 * CASH_MV, rel=1e-9)


def test_operational_scr_is_045pct_of_tp_capped_at_30pct_of_bscr():
    curve = build_rfr_curve()
    liability = build_liability()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    bel = cfs.pv(curve)

    # comfortably below the cap
    result = compute_operational_scr(bel, bscr=10_000_000.0)
    assert result.scr_operational == pytest.approx(0.0045 * bel, rel=1e-9)
    assert result.capped is False

    # a tiny BSCR forces the 30% cap to bind instead
    capped_result = compute_operational_scr(bel, bscr=100.0)
    assert capped_result.scr_operational == pytest.approx(0.30 * 100.0, rel=1e-9)
    assert capped_result.capped is True


def test_full_scr_aggregation_matches_independent_two_level_correlation():
    cfs, curve, fs_table, positions = _portfolio()
    result = compute_full_standard_formula_scr(cfs, positions, curve, fs_table, curve.valuation_date)

    # independent re-aggregation, coded directly against the same correlation tables rather
    # than reusing compute_full_standard_formula_scr's own call chain; the IR-vs-spread
    # correlation depends on which real 3D5/3D6 shock actually bound for this portfolio
    # (Annex IV), read from an independently-run compute_interest_rate_scr, not assumed
    independent_ir = compute_interest_rate_scr(cfs, positions, curve, fs_table, curve.valuation_date)
    market_correlation = (
        MARKET_RISK_CORRELATION_IR_RISE_BINDING if independent_ir.binding_direction == "rise"
        else MARKET_RISK_CORRELATION_IR_FALL_BINDING
    )
    expected_market = aggregate_via_correlation(
        {
            "spread": result.spread.scr_spread, "currency": result.currency.scr_currency,
            "concentration": result.concentration.scr_concentration, "interest_rate": result.interest_rate.scr_interest_rate,
        },
        market_correlation,
    )
    assert result.market_scr == pytest.approx(expected_market, rel=1e-9)

    expected_bscr = aggregate_via_correlation(
        {"market": expected_market, "life": result.longevity.scr_longevity, "counterparty": result.counterparty.scr_counterparty},
        TOP_LEVEL_CORRELATION,
    )
    assert result.bscr == pytest.approx(expected_bscr, rel=1e-9)

    expected_operational = min(0.0045 * result.longevity.base_ma.bel_basic_rfr, 0.30 * expected_bscr)
    assert result.operational.scr_operational == pytest.approx(expected_operational, rel=1e-9)

    expected_total = expected_bscr + expected_operational
    assert result.scr_total == pytest.approx(expected_total, rel=1e-9)


def test_lac_dt_reduces_scr_total_but_never_below_zero():
    cfs, curve, fs_table, positions = _portfolio()
    base = compute_full_standard_formula_scr(cfs, positions, curve, fs_table, curve.valuation_date)

    reduced = compute_full_standard_formula_scr(cfs, positions, curve, fs_table, curve.valuation_date, lac_dt=50_000.0)
    assert reduced.scr_total == pytest.approx(base.scr_total - 50_000.0, rel=1e-9)

    wiped_out = compute_full_standard_formula_scr(cfs, positions, curve, fs_table, curve.valuation_date, lac_dt=base.bscr + base.operational.scr_operational + 1_000_000.0)
    assert wiped_out.scr_total == 0.0


def test_bscr_correlation_life_counterparty_is_the_real_025_not_the_old_placeholder_zero():
    """Regression test: this codebase previously used 0.00 for the life<->
    counterparty-default BSCR correlation (an illustrative placeholder);
    the real Annex IV value, confirmed against two independent sources,
    is 0.25."""
    assert TOP_LEVEL_CORRELATION[("life", "counterparty")] == pytest.approx(0.25)


def test_market_correlation_ir_spread_pair_is_the_only_difference_between_rise_and_fall_variants():
    diff_keys = {
        k for k in MARKET_RISK_CORRELATION_IR_RISE_BINDING
        if MARKET_RISK_CORRELATION_IR_RISE_BINDING[k] != MARKET_RISK_CORRELATION_IR_FALL_BINDING[k]
    }
    assert diff_keys == {("interest_rate", "spread")}
    assert MARKET_RISK_CORRELATION_IR_RISE_BINDING[("interest_rate", "spread")] == pytest.approx(0.0)
    assert MARKET_RISK_CORRELATION_IR_FALL_BINDING[("interest_rate", "spread")] == pytest.approx(0.5)


def test_full_scr_selects_the_matching_correlation_variant_for_whichever_shock_actually_bound():
    cfs, curve, fs_table, positions = _portfolio()
    ir = compute_interest_rate_scr(cfs, positions, curve, fs_table, curve.valuation_date)
    result = compute_full_standard_formula_scr(cfs, positions, curve, fs_table, curve.valuation_date)

    expected_ir_spread_corr = 0.0 if ir.binding_direction == "rise" else 0.5
    naive_market = aggregate_via_correlation(
        {
            "spread": result.spread.scr_spread, "currency": result.currency.scr_currency,
            "concentration": result.concentration.scr_concentration, "interest_rate": result.interest_rate.scr_interest_rate,
        },
        {**MARKET_RISK_CORRELATION_IR_RISE_BINDING, ("interest_rate", "spread"): expected_ir_spread_corr},
    )
    assert result.market_scr == pytest.approx(naive_market, rel=1e-9)


def test_concentration_scr_excludes_government_positions_entirely():
    from alm.examples.golden_toy import build_gilt5y_position
    _, curve, _, positions = _portfolio()
    gilt = build_gilt5y_position(1_000_000.0)  # a large gilt position -- would dominate concentration if not excluded
    result = compute_concentration_scr(positions + [gilt], curve)
    assert result.charge_by_position["pos_gilt5y"] == 0.0
    assert result.excess_share_by_position["pos_gilt5y"] == 0.0


def test_correlation_aggregation_reduces_to_the_old_two_variable_formula():
    """Sanity check that the generic aggregator is exactly the algebra the
    original 2-variable spread/longevity formula used, for a simple case."""
    s, l, rho = 37_500.0, 151_810.48, 0.25
    expected = math.sqrt(s * s + l * l + 2 * rho * s * l)
    actual = aggregate_via_correlation({"spread": s, "longevity": l}, {("spread", "longevity"): rho})
    assert actual == pytest.approx(expected, rel=1e-9)
