"""Internal-model SCR interface (SS8/18): scenario set in, stressed values
out, MA engine rerun per the SS8/18 five-step logic (revalue assets;
update FS; check MA criteria still met; recompute MA; own-funds), which
is exactly what `stresses.run_stress` already does. This module is the
scenario-set-to-SCR contract on top of it, not a new stress mechanism.

Deliberately scoped down to a named-scenario internal model rather than a
full economic scenario generator: SCR is the worst own-funds loss across
a curated, firm-supplied scenario set (e.g. a LIST/ORSA pack loaded via
`stresses.scenario_loader`), not a percentile of a simulated loss
distribution. There's no scenario generator here, and "the 99.5th
percentile of N scenarios" would be a meaningless statistic for the
small, hand-picked scenario sets this is designed to run. A firm with a
real stochastic ESG can build its own percentile aggregation on top of
the same per-scenario `StressResult` objects this returns.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from alm.contracts.assets import AssetPosition
from alm.contracts.cashflows import CashFlowVector
from alm.contracts.curves import Curve
from alm.contracts.fs import FSTable
from alm.stresses.runner import StressResult, run_stress
from alm.stresses.scenario import StressSpec
from alm.stresses.scenario_loader import load_scenario_set


class InternalModelSCRResult(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    scr: float  # the worst own-funds loss across the scenario set, floored at 0
    worst_scenario_name: str
    n_scenarios: int
    scenario_own_funds_impact: dict[str, float]   # scenario name -> own-funds loss (positive = loss)
    scenario_ma_criteria_maintained: dict[str, bool]  # scenario name -> Test 1 still passes after the stress
    scenario_results: dict[str, StressResult]  # full per-scenario detail, for drill-down


def run_internal_model_scr(
    scenario_specs: list[StressSpec],
    liability_cfs: CashFlowVector,
    positions: list[AssetPosition],
    base_curve: Curve,
    fs_table: FSTable,
    valuation_date: date,
) -> InternalModelSCRResult:
    if not scenario_specs:
        raise ValueError("internal model SCR requires at least one scenario")

    impacts: dict[str, float] = {}
    maintained: dict[str, bool] = {}
    results: dict[str, StressResult] = {}

    for spec in scenario_specs:
        result = run_stress(spec, liability_cfs, positions, base_curve, fs_table, valuation_date)
        loss = result.base.own_funds - result.stressed.own_funds
        impacts[spec.name] = loss
        maintained[spec.name] = result.ma_criteria_maintained
        results[spec.name] = result

    worst_name = max(impacts, key=lambda name: impacts[name])
    scr = max(0.0, impacts[worst_name])

    return InternalModelSCRResult(
        scr=scr, worst_scenario_name=worst_name, n_scenarios=len(scenario_specs),
        scenario_own_funds_impact=impacts, scenario_ma_criteria_maintained=maintained,
        scenario_results=results,
    )


def run_internal_model_scr_from_file(
    scenario_file: str,
    liability_cfs: CashFlowVector,
    positions: list[AssetPosition],
    base_curve: Curve,
    fs_table: FSTable,
    valuation_date: date,
) -> InternalModelSCRResult:
    specs = load_scenario_set(scenario_file)
    return run_internal_model_scr(specs, liability_cfs, positions, base_curve, fs_table, valuation_date)
