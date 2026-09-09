"""Stress runner: revalue assets, remap FS, re-hypothecate, recompute MA,
re-run Test 1, and report the own-funds impact -- the SS8/18 5-step logic
(revalue assets; update FS; check MA criteria still met; recompute MA;
own-funds), minus the internal-model scenario-set interface (SCR mode,
deferred). Every stress explicitly reports base vs stressed Test 1
pass/fail rather than assuming MA survives the stress unexamined (project
brief: "report if MA criteria fail in stress -- do not silently assume MA
remains").
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from alm.contracts.assets import AssetPosition, InterestRateSwap
from alm.contracts.cashflows import CashFlowVector
from alm.contracts.curves import Curve
from alm.contracts.fs import FSTable
from alm.ma.engine import MAResult, compute_ma
from alm.ma.fs_rate import fs_rate_for_assets
from alm.ma.hypothecation import HypothecationResult, hypothecate
from alm.tests_pra.accumulated_cf_shortfall import Test1Result, run_test1

from .scenario import StressSpec, apply_stress


class StressLegResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_asset_market_value: float
    hypothecation: HypothecationResult
    fs_rate: float
    ma: MAResult
    test1: Test1Result
    own_funds: float  # total asset MV - BEL with MA


class StressResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    spec: StressSpec
    base: StressLegResult
    stressed: StressLegResult
    own_funds_impact: float  # stressed.own_funds - base.own_funds
    ma_rate_impact_bps: float
    test1_passed_before: bool
    test1_passed_after: bool
    ma_criteria_maintained: bool  # False if Test 1 flips pass->fail (or was already failing) under stress


def reproject_swaps(positions: list[AssetPosition], curve: Curve) -> list[AssetPosition]:
    """Rebuild any `InterestRateSwap` position's instrument via `from_curve`
    against the given curve, so its expected net cash flows reflect THAT
    curve's own forward rates rather than staying frozen at whatever curve
    the swap was originally constructed from (see `InterestRateSwap`'s
    docstring). Used for the stressed leg of a rate-moving scenario --
    without this, a rate stress would re-discount the swap's *unchanged*
    expected cash flows at the new curve, which understates the shock's
    real effect on a floating leg. Non-swap positions pass through
    unchanged."""
    reprojected: list[AssetPosition] = []
    for p in positions:
        if isinstance(p.instrument, InterestRateSwap):
            new_swap = InterestRateSwap.from_curve(
                id=p.instrument.id, currency=p.instrument.currency, notional=p.instrument.notional,
                fixed_rate=p.instrument.fixed_rate, maturity_years=p.instrument.maturity_years, curve=curve,
                payment_frequency=p.instrument.payment_frequency, receive_fixed=p.instrument.receive_fixed,
                rating=p.instrument.rating, sector=p.instrument.sector,
            )
            reprojected.append(p.model_copy(update={"instrument": new_swap}))
        else:
            reprojected.append(p)
    return reprojected


def _run_leg(
    liability_cfs: CashFlowVector,
    positions: list[AssetPosition],
    fs_table: FSTable,
    valuation_date: date,
    curve: Curve,
) -> StressLegResult:
    total_mv = sum(p.resolved_market_value(curve) for p in positions)
    hyp = hypothecate(liability_cfs, positions, fs_table, valuation_date, curve)
    fs_rate = fs_rate_for_assets(positions, fs_table, valuation_date, curve)
    # MA is computed on the actual market value of ALL assets assigned to the MA portfolio
    # (Component A+B+C together, i.e. `total_mv`) -- NOT hyp.component_ab_market_value, which
    # is trimmed to exactly BEL by construction (Component B tops up to BEL and no further)
    # and would make r1 == r2 (=> MA == -FS_rate) whenever the portfolio holds any surplus.
    # See golden Scenario A/B in ma/engine.py and Test 3, both of which correctly use an
    # un-trimmed market value as the r1 target.
    ma = compute_ma(liability_cfs, total_mv, fs_rate, curve)
    test1 = run_test1(liability_cfs, hyp.component_a_pd_adjusted_by_time, curve)
    own_funds = total_mv - ma.bel_with_ma
    return StressLegResult(
        total_asset_market_value=total_mv, hypothecation=hyp, fs_rate=fs_rate,
        ma=ma, test1=test1, own_funds=own_funds,
    )


def run_stress(
    spec: StressSpec,
    liability_cfs: CashFlowVector,
    positions: list[AssetPosition],
    base_curve: Curve,
    base_fs_table: FSTable,
    valuation_date: date,
) -> StressResult:
    base_leg = _run_leg(liability_cfs, positions, base_fs_table, valuation_date, base_curve)

    stressed_curve, stressed_fs_table, stressed_liability_cfs = apply_stress(spec, base_curve, base_fs_table, liability_cfs)
    stressed_positions = reproject_swaps(positions, stressed_curve)
    stressed_leg = _run_leg(stressed_liability_cfs, stressed_positions, stressed_fs_table, valuation_date, stressed_curve)

    return StressResult(
        spec=spec,
        base=base_leg,
        stressed=stressed_leg,
        own_funds_impact=stressed_leg.own_funds - base_leg.own_funds,
        ma_rate_impact_bps=stressed_leg.ma.ma_bps - base_leg.ma.ma_bps,
        test1_passed_before=base_leg.test1.passed,
        test1_passed_after=stressed_leg.test1.passed,
        ma_criteria_maintained=base_leg.test1.passed and stressed_leg.test1.passed,
    )
