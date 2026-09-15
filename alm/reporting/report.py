"""Reporting pack: consolidates already-computed MA, matching-test, stress,
Risk Margin and SCR results into one structured object, a markdown
narrative, and a timestamped JSON export in the style of a MALIR evidence
file.

Composed from already-computed results rather than re-running the
pipeline internally, because different tests in this codebase legitimately
use different portfolio slices (Tests 1-3 run on the 3-asset portfolio,
Tests 4-5 on a standalone HP bond, stresses on the single-corporate-bond
scenario), matching how a real firm actually works: each calculation runs
with the portfolio/scenario appropriate to it, and the reporting pack's
job is just to consolidate and present the results, not decide which
portfolio backs which test.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from alm.capital.own_funds import OwnFundsResult
from alm.ma.engine import MAResult
from alm.ma.hypothecation import HypothecationResult
from alm.rm.risk_margin import RiskMarginResult
from alm.scr.internal_model import InternalModelSCRResult
from alm.scr.standard_formula import FullStandardFormulaSCR
from alm.stresses.runner import StressResult
from alm.tests_pra.accumulated_cf_shortfall import Test1Result
from alm.tests_pra.hp_loss_test import Test4Result
from alm.tests_pra.modified_accumulated_shortfall import Test5Result
from alm.tests_pra.notional_swap import Test3Result
from alm.tests_pra.var_test import Test2Result


class MatchingTestPack(BaseModel):
    model_config = ConfigDict(frozen=True)

    test1: Test1Result | None = None
    test2: Test2Result | None = None
    test3: Test3Result | None = None
    test4: Test4Result | None = None
    test5: Test5Result | None = None


class ReportingPack(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    valuation_date: date
    currency: str
    liability_id: str
    ma: MAResult
    hypothecation: HypothecationResult | None = None
    matching_tests: MatchingTestPack = MatchingTestPack()
    stresses: tuple[StressResult, ...] = ()
    risk_margin: RiskMarginResult | None = None
    scr_standard_formula: FullStandardFormulaSCR | None = None
    scr_internal_model: InternalModelSCRResult | None = None
    own_funds: OwnFundsResult | None = None


def build_reporting_pack(
    valuation_date: date,
    currency: str,
    ma: MAResult,
    hypothecation: HypothecationResult | None = None,
    matching_tests: MatchingTestPack | None = None,
    stresses: list[StressResult] | None = None,
    risk_margin: RiskMarginResult | None = None,
    scr_standard_formula: FullStandardFormulaSCR | None = None,
    scr_internal_model: InternalModelSCRResult | None = None,
    own_funds: OwnFundsResult | None = None,
) -> ReportingPack:
    return ReportingPack(
        generated_at=datetime.now(timezone.utc),
        valuation_date=valuation_date,
        currency=currency,
        liability_id=ma.liability_id,
        ma=ma,
        hypothecation=hypothecation,
        matching_tests=matching_tests or MatchingTestPack(),
        stresses=tuple(stresses or ()),
        risk_margin=risk_margin,
        scr_standard_formula=scr_standard_formula,
        scr_internal_model=scr_internal_model,
        own_funds=own_funds,
    )


def _test_row(name: str, result_desc: str, threshold_desc: str, passed: bool | None) -> str:
    status = "n/a" if passed is None else ("PASS" if passed else "FAIL")
    return f"| {name} | {result_desc} | {threshold_desc} | {status} |"


def render_markdown(pack: ReportingPack) -> str:
    lines = [
        "# MA Reporting Pack",
        "",
        f"Generated: {pack.generated_at.isoformat()}",
        f"Valuation date: {pack.valuation_date.isoformat()}",
        f"Currency: {pack.currency}",
        f"Liability: {pack.liability_id}",
        "",
        "## Matching Adjustment",
        "",
        f"- MA: {pack.ma.ma_bps:.4f} bp",
        f"- BEL (basic RFR): {pack.ma.bel_basic_rfr:,.2f}",
        f"- BEL (with MA): {pack.ma.bel_with_ma:,.2f}",
        f"- MA benefit: {pack.ma.ma_benefit:,.2f}",
        f"- FS rate: {pack.ma.fs_rate * 10_000:.2f} bp",
        f"- r1 (asset-implied): {pack.ma.rate_asset_implied * 100:.4f}%",
        f"- r2 (basic RFR AER): {pack.ma.rate_basic_rfr_aer * 100:.4f}%",
        "",
    ]

    if pack.hypothecation is not None:
        h = pack.hypothecation
        lines += [
            "## Hypothecation",
            "",
            f"- Component A market value: {h.component_a_market_value:,.2f}",
            f"- Component A+B market value: {h.component_ab_market_value:,.2f}",
            f"- Component C market value: {h.component_c_market_value:,.2f}",
            f"- BEL: {h.bel:,.2f}",
            "",
        ]

    lines += ["## PRA Matching Tests", "", "| Test | Result | Threshold | Status |", "|---|---|---|---|"]
    mt = pack.matching_tests
    if mt.test1:
        lines.append(_test_row("1 - Accumulated CF Shortfall", f"{mt.test1.ratio:.2%}", f"<= {mt.test1.threshold:.0%}", mt.test1.passed))
    if mt.test2:
        lines.append(_test_row(
            "2 - VaR (IR/Infl/FX)",
            f"IR {mt.test2.interest_rate.ratio_to_bel:.2%} / Infl {mt.test2.inflation.ratio_to_bel:.2%} / FX {mt.test2.currency.ratio_to_bel:.2%}",
            f"<= {mt.test2.interest_rate.threshold:.0%} each", mt.test2.passed,
        ))
    if mt.test3:
        lines.append(_test_row("3 - Notional Swap", f"k={mt.test3.scale_factor:.4f}", "diagnostic, no threshold", None))
    if mt.test4:
        lines.append(_test_row("4 - MA Loss Test (HP)", f"{mt.test4.ratio:.2%}", f"<= {mt.test4.threshold:.0%}", mt.test4.passed))
    if mt.test5:
        lines.append(_test_row("5 - Modified Accumulated Shortfall (HP)", f"{mt.test5.ratio:.2%}", f"<= {mt.test5.inner.threshold:.0%}", mt.test5.passed))
    lines.append("")

    if pack.stresses:
        lines += ["## Stresses", "", "| Scenario | Base MA (bp) | Stressed MA (bp) | Own funds impact | Test 1 before -> after |", "|---|---|---|---|---|"]
        for s in pack.stresses:
            lines.append(
                f"| {s.spec.name} | {s.base.ma.ma_bps:.4f} | {s.stressed.ma.ma_bps:.4f} | "
                f"{s.own_funds_impact:,.2f} | {s.test1_passed_before} -> {s.test1_passed_after} |"
            )
        lines.append("")

    if pack.risk_margin is not None:
        rm = pack.risk_margin
        lines += ["## Risk Margin", "", f"- Risk Margin: {rm.risk_margin:,.2f}", f"- CoC: {rm.coc:.0%}, lambda: {rm.lam}, floor: {rm.floor}", ""]

    if pack.scr_standard_formula is not None:
        scr = pack.scr_standard_formula
        lines += [
            "## Standard Formula SCR",
            "",
            f"- Spread: {scr.spread.scr_spread:,.2f}",
            f"- Currency: {scr.currency.scr_currency:,.2f}",
            f"- Concentration: {scr.concentration.scr_concentration:,.2f}",
            f"- Longevity: {scr.longevity.scr_longevity:,.2f}",
            f"- Counterparty default: {scr.counterparty.scr_counterparty:,.2f}",
            f"- Operational: {scr.operational.scr_operational:,.2f}",
            f"- Market SCR: {scr.market_scr:,.2f}",
            f"- BSCR: {scr.bscr:,.2f}",
            f"- SCR total: {scr.scr_total:,.2f}",
            "",
        ]

    if pack.scr_internal_model is not None:
        im = pack.scr_internal_model
        lines += [
            "## Internal Model SCR",
            "",
            f"- SCR (worst scenario: {im.worst_scenario_name}): {im.scr:,.2f}",
            f"- Scenarios run: {im.n_scenarios}",
            "",
        ]

    if pack.own_funds is not None:
        of = pack.own_funds
        coverage_str = f"{of.coverage_ratio:.0%}" if of.coverage_ratio is not None else "n/a (SCR = 0)"
        lines += [
            "## Own Funds and SCR Coverage",
            "",
            f"- Asset market value: {of.asset_market_value:,.2f}",
            f"- Technical Provisions (BEL with MA + Risk Margin): {of.technical_provisions:,.2f}",
            f"- Basic Own Funds: {of.basic_own_funds:,.2f}",
            f"- SCR total: {of.scr_total:,.2f}",
            f"- SCR coverage ratio: {coverage_str}",
            "",
        ]

    return "\n".join(lines) + "\n"


def export_json(pack: ReportingPack, path: str | Path) -> None:
    Path(path).write_text(pack.model_dump_json(indent=2), encoding="utf-8")


def load_json(path: str | Path) -> ReportingPack:
    return ReportingPack.model_validate_json(Path(path).read_text(encoding="utf-8"))
