"""The annual MA attestation data pack: a narrower, MALIR-specific view
than the general `ReportingPack`, putting FS additions, the HP cash-flow
cap, and matching evidence front and centre rather than everything the
engine can produce.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from pydantic import BaseModel, ConfigDict

from alm.ma.engine import MAResult
from alm.ma.fs_additions import FSAdditions
from alm.ma.hp_cap import HPCapResult

from .report import MatchingTestPack


class MALIRPack(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    valuation_date: date
    currency: str
    liability_id: str
    ma: MAResult
    base_fs_rate: float
    fs_additions: FSAdditions
    fs_rate_with_additions: float
    hp_cap: HPCapResult | None = None
    matching_tests: MatchingTestPack = MatchingTestPack()


def build_malir_pack(
    valuation_date: date,
    currency: str,
    ma: MAResult,
    base_fs_rate: float,
    fs_additions: FSAdditions,
    hp_cap: HPCapResult | None = None,
    matching_tests: MatchingTestPack | None = None,
) -> MALIRPack:
    return MALIRPack(
        generated_at=datetime.now(timezone.utc),
        valuation_date=valuation_date,
        currency=currency,
        liability_id=ma.liability_id,
        ma=ma,
        base_fs_rate=base_fs_rate,
        fs_additions=fs_additions,
        fs_rate_with_additions=base_fs_rate + fs_additions.total_rate,
        hp_cap=hp_cap,
        matching_tests=matching_tests or MatchingTestPack(),
    )


def render_malir_markdown(pack: MALIRPack) -> str:
    lines = [
        "# Annual MA Attestation Data Pack",
        "",
        f"Generated: {pack.generated_at.isoformat()}",
        f"Valuation date: {pack.valuation_date.isoformat()}",
        f"Currency: {pack.currency}",
        f"Liability: {pack.liability_id}",
        "",
        "## MA benefit",
        "",
        f"- MA: {pack.ma.ma_bps:.4f} bp",
        f"- MA benefit: {pack.ma.ma_benefit:,.2f}",
        "",
        "## FS additions",
        "",
        f"- Base FS rate: {pack.base_fs_rate * 10_000:.2f} bp",
        f"- Attestation: {pack.fs_additions.attestation_bps:.2f} bp",
        f"- Structure: {pack.fs_additions.structure_bps:.2f} bp",
        f"- Construction: {pack.fs_additions.construction_bps:.2f} bp",
        f"- Prepayment: {pack.fs_additions.prepayment_bps:.2f} bp",
        f"- HP: {pack.fs_additions.hp_bps:.2f} bp",
        f"- Total additions: {pack.fs_additions.total_bps:.2f} bp",
        f"- FS rate with additions: {pack.fs_rate_with_additions * 10_000:.2f} bp",
        "",
    ]

    lines.append("## HP cash-flow cap")
    lines.append("")
    if pack.hp_cap is not None:
        hc = pack.hp_cap
        lines += [
            f"- HP MA benefit: {hc.hp_ma_benefit:,.2f}",
            f"- Total MA benefit: {hc.total_ma_benefit:,.2f}",
            f"- Ratio: {hc.ratio:.2%} (cap {hc.cap_ratio:.0%})",
            f"- Breach: {hc.breach}",
        ]
        if hc.breach:
            lines.append(f"- Excess over cap: {hc.excess_benefit:,.2f}")
    else:
        lines.append("- No HP assets in this portfolio (cap not applicable).")
    lines.append("")

    lines += ["## Matching evidence", "", "| Test | Result | Threshold | Status |", "|---|---|---|---|"]
    mt = pack.matching_tests
    if mt.test1:
        status = "PASS" if mt.test1.passed else "FAIL"
        lines.append(f"| 1 - Accumulated CF Shortfall | {mt.test1.ratio:.2%} | <= {mt.test1.threshold:.0%} | {status} |")
    if mt.test2:
        status = "PASS" if mt.test2.passed else "FAIL"
        lines.append(
            f"| 2 - VaR (IR/Infl/FX) | IR {mt.test2.interest_rate.ratio_to_bel:.2%} / "
            f"Infl {mt.test2.inflation.ratio_to_bel:.2%} / FX {mt.test2.currency.ratio_to_bel:.2%} | "
            f"<= {mt.test2.interest_rate.threshold:.0%} each | {status} |"
        )
    if mt.test3:
        lines.append(f"| 3 - Notional Swap | k={mt.test3.scale_factor:.4f} | diagnostic, no threshold | n/a |")
    if mt.test4:
        status = "PASS" if mt.test4.passed else "FAIL"
        lines.append(f"| 4 - MA Loss Test (HP) | {mt.test4.ratio:.2%} | <= {mt.test4.threshold:.0%} | {status} |")
    if mt.test5:
        status = "PASS" if mt.test5.passed else "FAIL"
        lines.append(f"| 5 - Modified Accumulated Shortfall (HP) | {mt.test5.ratio:.2%} | <= {mt.test5.inner.threshold:.0%} | {status} |")

    return "\n".join(lines) + "\n"
