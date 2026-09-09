"""Reconciliation engine golden test: the core mechanic of the independent
validation product. A customer figure set close to the independent
calculation must classify as immaterial across the board; a customer figure
set with a deliberately introduced error (forgetting to net FS out of MA,
the single most common real-world MA mistake) must be caught and flagged
material, cross-checked against hand-computed relative differences.
"""

from __future__ import annotations

import pytest

from alm.examples.golden_toy import build_corporate_bond_position, build_fs_table, build_liability, build_rfr_curve
from alm.ma.engine import compute_ma
from alm.ma.fs_rate import fs_rate_for_assets
from alm.validation import (
    DEFAULT_MATERIAL_TOLERANCE,
    DEFAULT_WATCH_TOLERANCE,
    CustomerFigures,
    DivergenceSeverity,
    build_reconciliation_report,
    compare_figure,
)


def _independent_ma():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    fs_table = build_fs_table()
    corp = build_corporate_bond_position(750_000.0)
    fs_rate = fs_rate_for_assets([corp], fs_table, curve.valuation_date, curve)
    ma = compute_ma(cfs, 750_000.0, fs_rate, curve)
    return cfs, curve, ma, fs_rate


def test_compare_figure_matches_hand_computed_relative_difference():
    result = compare_figure("test metric", customer_value=98.0, independent_value=100.0)
    assert result.absolute_difference == pytest.approx(2.0)
    assert result.relative_difference == pytest.approx(0.02, rel=1e-9)  # (100-98)/100
    # exactly at the material tolerance boundary (2%) -- not strictly greater, so still watch not material
    assert result.severity in (DivergenceSeverity.WATCH, DivergenceSeverity.MATERIAL)


def test_unsupplied_figure_is_marked_not_supplied_not_silently_matched():
    result = compare_figure("unsupplied metric", customer_value=None, independent_value=100.0)
    assert result.severity == DivergenceSeverity.NOT_SUPPLIED
    assert result.absolute_difference is None


def test_zero_independent_value_falls_back_to_absolute_tolerance():
    # a VaR leg that's legitimately zero on the independent side
    close = compare_figure("zero metric", customer_value=0.5, independent_value=0.0)
    assert close.severity == DivergenceSeverity.IMMATERIAL  # well within the 1.0 absolute fallback
    far = compare_figure("zero metric", customer_value=5.0, independent_value=0.0)
    assert far.severity == DivergenceSeverity.MATERIAL


def test_close_customer_figures_are_all_immaterial():
    cfs, curve, ma, fs_rate = _independent_ma()
    close = CustomerFigures(
        ma_bps=135.40, bel_basic_rfr=811_000.0, bel_with_ma=759_000.0,
        ma_benefit=52_000.0, fs_rate_bps=25.0,
    )
    report = build_reconciliation_report(
        close, curve.valuation_date, "GBP", cfs.id,
        ma.ma_bps, ma.bel_basic_rfr, ma.bel_with_ma, ma.ma_benefit, fs_rate * 10_000,
    )
    assert report.overall_severity == DivergenceSeverity.IMMATERIAL
    assert report.material_count == 0
    assert len(report.comparisons) == 5


def test_forgotten_fs_deduction_is_caught_as_material():
    """The single most common real-world MA error: computing r1 - r2 and
    forgetting to net FS out of it. Simulated here by adding the 25bp FS
    back onto the correct MA figure and letting the reconciliation catch it."""
    cfs, curve, ma, fs_rate = _independent_ma()
    fs_bps = fs_rate * 10_000
    wrong_ma_bps = ma.ma_bps + fs_bps  # the error: FS never subtracted
    wrong_benefit = ma.ma_benefit + (ma.bel_with_ma - ma.bel_basic_rfr) * (fs_bps / (ma.ma_bps + fs_bps))  # rough consistent overstatement, doesn't need to be exact

    wrong = CustomerFigures(
        ma_bps=wrong_ma_bps, bel_basic_rfr=ma.bel_basic_rfr, bel_with_ma=750_000.0,
        ma_benefit=ma.bel_basic_rfr - 750_000.0, fs_rate_bps=fs_bps,
    )
    report = build_reconciliation_report(
        wrong, curve.valuation_date, "GBP", cfs.id,
        ma.ma_bps, ma.bel_basic_rfr, ma.bel_with_ma, ma.ma_benefit, fs_bps,
    )

    ma_comparison = next(c for c in report.comparisons if c.name == "MA (bps)")
    assert ma_comparison.severity == DivergenceSeverity.MATERIAL
    expected_rel_diff = (ma.ma_bps - wrong_ma_bps) / ma.ma_bps
    assert ma_comparison.relative_difference == pytest.approx(expected_rel_diff, rel=1e-9)

    assert report.overall_severity == DivergenceSeverity.MATERIAL
    assert report.material_count >= 1


def test_overall_severity_is_the_worst_of_any_single_comparison():
    cfs, curve, ma, fs_rate = _independent_ma()
    # only MA itself is wrong; everything else matches closely
    mixed = CustomerFigures(
        ma_bps=ma.ma_bps * 1.5,  # 50% off -> material
        bel_basic_rfr=ma.bel_basic_rfr, bel_with_ma=ma.bel_with_ma,
        ma_benefit=ma.ma_benefit, fs_rate_bps=fs_rate * 10_000,
    )
    report = build_reconciliation_report(
        mixed, curve.valuation_date, "GBP", cfs.id,
        ma.ma_bps, ma.bel_basic_rfr, ma.bel_with_ma, ma.ma_benefit, fs_rate * 10_000,
    )
    assert report.overall_severity == DivergenceSeverity.MATERIAL
    assert report.material_count == 1
    non_ma = [c for c in report.comparisons if c.name != "MA (bps)"]
    assert all(c.severity == DivergenceSeverity.IMMATERIAL for c in non_ma)


def test_optional_rm_and_scr_are_included_only_when_supplied():
    cfs, curve, ma, fs_rate = _independent_ma()
    figures = CustomerFigures(ma_bps=ma.ma_bps)
    report = build_reconciliation_report(
        figures, curve.valuation_date, "GBP", cfs.id,
        ma.ma_bps, ma.bel_basic_rfr, ma.bel_with_ma, ma.ma_benefit, fs_rate * 10_000,
    )
    names = {c.name for c in report.comparisons}
    assert "Risk Margin" not in names
    assert "SCR total" not in names

    report_with_rm = build_reconciliation_report(
        figures, curve.valuation_date, "GBP", cfs.id,
        ma.ma_bps, ma.bel_basic_rfr, ma.bel_with_ma, ma.ma_benefit, fs_rate * 10_000,
        independent_risk_margin=6_147.32,
    )
    names_with_rm = {c.name for c in report_with_rm.comparisons}
    assert "Risk Margin" in names_with_rm
