"""Reporting pack golden test: assembles a full pack from real results
across every module built so far (MA, hypothecation, all 5 PRA tests, 3
stresses, RM, SF SCR, IM SCR), checks the markdown table columns render in
the right order (regression test for a real Result/Threshold column swap
caught while building this), and round-trips through JSON export/import.
"""

from __future__ import annotations

import pytest

from alm.examples.golden_toy import (
    build_corporate_bond_position,
    build_fs_table,
    build_gilt5y_position,
    build_gilt_position,
    build_hp_bond,
    build_liability,
    build_rfr_curve,
)
from alm.ma.engine import compute_ma
from alm.ma.fs_rate import fs_rate_for_assets
from alm.ma.hypothecation import hypothecate
from alm.reporting import MatchingTestPack, build_reporting_pack, export_json, load_json, render_markdown
from alm.rm import approximate_scr_runoff, compute_risk_margin
from alm.scr import compute_full_standard_formula_scr, run_internal_model_scr
from alm.stresses import StressSpec, run_stress
from alm.tests_pra.accumulated_cf_shortfall import run_test1
from alm.tests_pra.hp_loss_test import run_test4
from alm.tests_pra.modified_accumulated_shortfall import run_test5
from alm.tests_pra.notional_swap import run_test3
from alm.tests_pra.var_test import run_test2


def _full_pack():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    bel = cfs.pv(curve)
    fs_table = build_fs_table()

    corp = build_corporate_bond_position(750_000.0)
    fs_c = fs_rate_for_assets([corp], fs_table, curve.valuation_date, curve)
    ma = compute_ma(cfs, 750_000.0, fs_c, curve)

    gilt5 = build_gilt5y_position(300_000.0)
    corp600 = build_corporate_bond_position(600_000.0)
    hyp = hypothecate(cfs, [gilt5, corp600], fs_table, curve.valuation_date, curve)
    t1 = run_test1(cfs, hyp.component_a_pd_adjusted_by_time, curve)
    fs_blend = fs_rate_for_assets([gilt5, corp600], fs_table, curve.valuation_date, curve)
    t3 = run_test3(cfs, hyp.component_a_pd_adjusted_by_time, hyp.component_a_market_value, fs_blend, curve)

    gilt_bel = build_gilt_position(bel=bel)
    t2 = run_test2([gilt_bel, corp600], curve, bel, curve.valuation_date)

    hp = build_hp_bond(500_000.0)
    fs_entry = fs_table.lookup(hp.currency, hp.rating, hp.sector, hp.maturity_years)
    fs_hp = fs_entry.fs_bps_floored / 10_000.0
    t4 = run_test4(cfs, hp, 500_000.0, fs_hp, curve, curve.valuation_date)
    t5 = run_test5(cfs, hp, fs_table, curve, curve.valuation_date)

    specs = [
        StressSpec(name="rates_down_100bp", curve_shift=-0.01),
        StressSpec(name="spread_widen_50pct", fs_widening_multiplier=1.5),
        StressSpec(name="longevity_up_5pct", liability_shock_multiplier=1.05),
    ]
    stress_results = [run_stress(s, cfs, [corp], curve, fs_table, curve.valuation_date) for s in specs]

    scr0 = 0.05 * bel
    scr_path = approximate_scr_runoff(scr0, cfs, curve, n_years=10)
    rm = compute_risk_margin(scr_path, curve)

    sf_scr = compute_full_standard_formula_scr(cfs, [corp], curve, fs_table, curve.valuation_date)
    im_scr = run_internal_model_scr(specs, cfs, [corp], curve, fs_table, curve.valuation_date)

    return build_reporting_pack(
        valuation_date=curve.valuation_date, currency="GBP", ma=ma, hypothecation=hyp,
        matching_tests=MatchingTestPack(test1=t1, test2=t2, test3=t3, test4=t4, test5=t5),
        stresses=stress_results, risk_margin=rm, scr_standard_formula=sf_scr, scr_internal_model=im_scr,
    )


def test_pack_carries_every_established_golden_figure():
    pack = _full_pack()

    assert pack.ma.ma_bps == pytest.approx(135.4463645158851, rel=1e-9)
    assert pack.hypothecation.component_a_market_value == pytest.approx(354_281.6555479865, rel=1e-9)
    assert pack.matching_tests.test1.ratio == pytest.approx(0.6840511580211358, rel=1e-9)
    assert pack.matching_tests.test1.passed is False
    assert pack.matching_tests.test4.passed is True
    assert pack.matching_tests.test5.passed is False
    assert pack.risk_margin.risk_margin == pytest.approx(6147.315983873259, rel=1e-6)
    assert pack.scr_standard_formula.scr_total > 0
    assert pack.scr_internal_model.worst_scenario_name == "spread_widen_50pct"


def test_markdown_result_and_threshold_columns_are_not_swapped():
    """Regression test: an earlier version of _test_row had its parameter
    order out of sync with its call sites, silently swapping the Result and
    Threshold columns for every row (e.g. Test 1 showed '<= 3%' under
    Result and '68.41%' under Threshold)."""
    pack = _full_pack()
    md = render_markdown(pack)

    lines = md.splitlines()
    test1_line = next(l for l in lines if l.startswith("| 1 -"))
    cells = [c.strip() for c in test1_line.strip("|").split("|")]
    name, result, threshold, status = cells

    assert result.endswith("%")  # a ratio, e.g. "68.41%"
    assert threshold.startswith("<=")  # a threshold expression, e.g. "<= 3%"
    assert status == "FAIL"


def test_json_round_trip_preserves_every_field(tmp_path):
    pack = _full_pack()
    path = tmp_path / "pack.json"
    export_json(pack, path)
    loaded = load_json(path)

    assert loaded.ma.ma_bps == pack.ma.ma_bps
    assert loaded.matching_tests.test1.ratio == pack.matching_tests.test1.ratio
    assert loaded.scr_standard_formula.scr_total == pack.scr_standard_formula.scr_total
    assert loaded.scr_internal_model.scr == pack.scr_internal_model.scr
    assert len(loaded.stresses) == len(pack.stresses)


def test_pack_without_optional_sections_still_renders():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    fs_table = build_fs_table()
    corp = build_corporate_bond_position(750_000.0)
    fs_c = fs_rate_for_assets([corp], fs_table, curve.valuation_date, curve)
    ma = compute_ma(cfs, 750_000.0, fs_c, curve)

    pack = build_reporting_pack(valuation_date=curve.valuation_date, currency="GBP", ma=ma)
    md = render_markdown(pack)

    assert "# MA Reporting Pack" in md
    assert "## Matching Adjustment" in md
    assert "## Hypothecation" not in md
    assert "## Risk Margin" not in md
