"""Own Funds / SCR coverage ratio golden test: independently recomputes
Basic Own Funds (asset market value minus Technical Provisions, where
Technical Provisions = BEL with MA + Risk Margin) by hand rather than
trusting `compute_own_funds`'s own arithmetic, on the same fixtures the
reporting-pack golden test already uses, and checks the coverage ratio
divides correctly, including the SCR-is-zero edge case.
"""

from __future__ import annotations

import pytest

from alm.capital import compute_own_funds
from alm.examples.golden_toy import build_corporate_bond_position, build_fs_table, build_liability, build_rfr_curve
from alm.ma.engine import compute_ma
from alm.ma.fs_rate import fs_rate_for_assets
from alm.reporting import build_reporting_pack, render_markdown
from alm.rm import approximate_scr_runoff, compute_risk_margin
from alm.scr import compute_full_standard_formula_scr


def _ma_and_rm():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    bel = cfs.pv(curve)
    fs_table = build_fs_table()

    corp = build_corporate_bond_position(750_000.0)
    fs_c = fs_rate_for_assets([corp], fs_table, curve.valuation_date, curve)
    ma = compute_ma(cfs, 750_000.0, fs_c, curve)

    scr_path = approximate_scr_runoff(0.05 * bel, cfs, curve, n_years=10)
    rm = compute_risk_margin(scr_path, curve)
    return ma, rm, cfs, curve, fs_table, corp


def test_basic_own_funds_matches_independent_hand_arithmetic():
    ma, rm, *_ = _ma_and_rm()
    scr_total = 40_000.0

    result = compute_own_funds(ma, rm.risk_margin, scr_total)

    independent_tp = ma.bel_with_ma + rm.risk_margin
    independent_own_funds = ma.asset_market_value - independent_tp
    assert result.technical_provisions == pytest.approx(independent_tp, rel=1e-12)
    assert result.basic_own_funds == pytest.approx(independent_own_funds, rel=1e-12)
    assert result.coverage_ratio == pytest.approx(independent_own_funds / scr_total, rel=1e-12)


def test_coverage_ratio_is_none_when_scr_is_zero_not_a_divide_by_zero_error():
    ma, rm, *_ = _ma_and_rm()
    result = compute_own_funds(ma, rm.risk_margin, scr_total=0.0)
    assert result.coverage_ratio is None
    assert result.scr_total == 0.0


def test_rejects_negative_risk_margin_or_scr():
    ma, rm, *_ = _ma_and_rm()
    with pytest.raises(ValueError):
        compute_own_funds(ma, risk_margin=-1.0, scr_total=1.0)
    with pytest.raises(ValueError):
        compute_own_funds(ma, risk_margin=rm.risk_margin, scr_total=-1.0)


def test_own_funds_is_distinct_from_the_lighter_weight_stress_own_funds_field():
    """StressLegResult.own_funds (alm/stresses/runner.py) is asset MV minus
    BEL with MA only -- no Risk Margin subtracted. This module's Basic Own
    Funds subtracts the Risk Margin too, so it must come out lower whenever
    Risk Margin is positive (it always is here)."""
    ma, rm, *_ = _ma_and_rm()
    result = compute_own_funds(ma, rm.risk_margin, scr_total=40_000.0)

    lighter_weight_own_funds = ma.asset_market_value - ma.bel_with_ma
    assert rm.risk_margin > 0
    assert result.basic_own_funds == pytest.approx(lighter_weight_own_funds - rm.risk_margin, rel=1e-12)
    assert result.basic_own_funds < lighter_weight_own_funds


def test_reporting_pack_renders_own_funds_section_with_a_coverage_ratio():
    ma, rm, cfs, curve, fs_table, corp = _ma_and_rm()
    sf_scr = compute_full_standard_formula_scr(cfs, [corp], curve, fs_table, curve.valuation_date)
    own_funds = compute_own_funds(ma, rm.risk_margin, sf_scr.scr_total)

    pack = build_reporting_pack(
        valuation_date=curve.valuation_date, currency="GBP", ma=ma,
        risk_margin=rm, scr_standard_formula=sf_scr, own_funds=own_funds,
    )
    md = render_markdown(pack)

    assert "## Own Funds and SCR Coverage" in md
    assert f"{own_funds.basic_own_funds:,.2f}" in md
    assert own_funds.coverage_ratio is not None
    assert f"{own_funds.coverage_ratio:.0%}" in md


def test_reporting_pack_omits_own_funds_section_when_not_supplied():
    ma, _rm, _cfs, curve, *_ = _ma_and_rm()
    pack = build_reporting_pack(valuation_date=curve.valuation_date, currency="GBP", ma=ma)
    md = render_markdown(pack)
    assert "## Own Funds and SCR Coverage" not in md
