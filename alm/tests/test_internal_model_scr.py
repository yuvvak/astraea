"""Internal-model SCR golden test: worst-of-scenario-set SCR on the same
three stress scenarios already established in test_stresses.py, cross-
checked against an independently re-run `run_stress` call for the winning
scenario, plus a file-based round trip through the scenario loader.
"""

from __future__ import annotations

import pytest

from alm.examples.golden_toy import build_corporate_bond_position, build_fs_table, build_liability, build_rfr_curve
from alm.scr import run_internal_model_scr, run_internal_model_scr_from_file
from alm.stresses import StressSpec, run_stress, save_scenario_set

SPECS = [
    StressSpec(name="rates_down_100bp", curve_shift=-0.01),
    StressSpec(name="spread_widen_50pct", fs_widening_multiplier=1.5),
    StressSpec(name="longevity_up_5pct", liability_shock_multiplier=1.05),
]


def _portfolio():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    fs_table = build_fs_table()
    corp = build_corporate_bond_position(750_000.0)
    return cfs, curve, fs_table, [corp]


def test_worst_scenario_is_spread_widening_not_rates_or_longevity():
    """Rates: own-funds impact ~0 (established invariant). Longevity: own
    funds actually IMPROVES here (a documented two-AER artifact -- see
    scr/standard_formula.py docstring), i.e. a negative loss. Spread
    widening is the only scenario with a genuine positive loss, so it must
    win."""
    cfs, curve, fs_table, positions = _portfolio()
    result = run_internal_model_scr(SPECS, cfs, positions, curve, fs_table, curve.valuation_date)

    assert result.worst_scenario_name == "spread_widen_50pct"
    assert result.n_scenarios == 3
    assert result.scenario_own_funds_impact["longevity_up_5pct"] < 0
    assert abs(result.scenario_own_funds_impact["rates_down_100bp"]) < 1e-4


def test_scr_matches_an_independent_rerun_of_the_winning_scenario():
    cfs, curve, fs_table, positions = _portfolio()
    result = run_internal_model_scr(SPECS, cfs, positions, curve, fs_table, curve.valuation_date)

    winning_spec = next(s for s in SPECS if s.name == result.worst_scenario_name)
    independent = run_stress(winning_spec, cfs, positions, curve, fs_table, curve.valuation_date)
    independent_loss = independent.base.own_funds - independent.stressed.own_funds

    assert result.scr == pytest.approx(independent_loss, rel=1e-9)
    assert result.scr == pytest.approx(4588.360005108407, rel=1e-6)


def test_scr_is_never_negative_even_if_every_scenario_is_a_gain():
    cfs, curve, fs_table, positions = _portfolio()
    gain_only_specs = [StressSpec(name="longevity_up_5pct", liability_shock_multiplier=1.05)]
    result = run_internal_model_scr(gain_only_specs, cfs, positions, curve, fs_table, curve.valuation_date)

    assert result.scenario_own_funds_impact["longevity_up_5pct"] < 0
    assert result.scr == 0.0


def test_empty_scenario_set_raises():
    cfs, curve, fs_table, positions = _portfolio()
    with pytest.raises(ValueError, match="at least one scenario"):
        run_internal_model_scr([], cfs, positions, curve, fs_table, curve.valuation_date)


def test_file_based_scenario_run_matches_the_in_memory_result(tmp_path):
    cfs, curve, fs_table, positions = _portfolio()
    in_memory = run_internal_model_scr(SPECS, cfs, positions, curve, fs_table, curve.valuation_date)

    path = tmp_path / "im_scenario_pack.json"
    save_scenario_set(SPECS, path)
    from_file = run_internal_model_scr_from_file(str(path), cfs, positions, curve, fs_table, curve.valuation_date)

    assert from_file.scr == pytest.approx(in_memory.scr, rel=1e-9)
    assert from_file.worst_scenario_name == in_memory.worst_scenario_name
