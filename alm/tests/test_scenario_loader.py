"""File-based scenario set golden test: a round-trip through JSON must
reproduce the exact same StressSpec objects, and running a loaded scenario
must produce identical results to constructing the same StressSpec directly
in code (already covered by test_stresses.py).
"""

from __future__ import annotations

import json

import pytest

from alm.examples.golden_toy import build_corporate_bond_position, build_fs_table, build_liability, build_rfr_curve
from alm.stresses import StressSpec, load_scenario_set, run_stress, save_scenario_set


def test_round_trip_preserves_every_field(tmp_path):
    specs = [
        StressSpec(name="rates_down_100bp", description="parallel -100bp", curve_shift=-0.01),
        StressSpec(name="spread_widen_50pct", description="FS x1.5", fs_widening_multiplier=1.5),
        StressSpec(name="longevity_up_5pct", description="liability +5%", liability_shock_multiplier=1.05),
    ]
    path = tmp_path / "scenario_pack.json"
    save_scenario_set(specs, path)

    loaded = load_scenario_set(path)

    assert len(loaded) == len(specs)
    for original, reloaded in zip(specs, loaded):
        assert reloaded == original


def test_malformed_scenario_file_fails_loudly(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(ValueError, match="must contain a JSON list"):
        load_scenario_set(path)


def test_loaded_scenario_produces_identical_results_to_constructing_it_directly(tmp_path):
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    corp = build_corporate_bond_position(750_000.0)
    fs_table = build_fs_table()

    direct_spec = StressSpec(name="rates_down_100bp", curve_shift=-0.01)
    direct_result = run_stress(direct_spec, cfs, [corp], curve, fs_table, curve.valuation_date)

    path = tmp_path / "pack.json"
    save_scenario_set([direct_spec], path)
    loaded_spec = load_scenario_set(path)[0]
    loaded_result = run_stress(loaded_spec, cfs, [corp], curve, fs_table, curve.valuation_date)

    assert loaded_result.stressed.ma.ma_bps == pytest.approx(direct_result.stressed.ma.ma_bps, rel=1e-9)
    assert loaded_result.own_funds_impact == pytest.approx(direct_result.own_funds_impact, rel=1e-9)
