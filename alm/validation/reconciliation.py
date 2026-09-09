"""Independent validation / reconciliation: the core mechanic of running this
engine as a second opinion alongside a firm's existing MA/SCR process,
rather than as a replacement for it.

`CustomerFigures` is whatever headline numbers the customer's own in-house
or vendor engine produced for a given valuation. `build_reconciliation_report`
runs this engine's own independent calculation on the same portfolio and
compares the two, figure by figure, flagging any material divergence rather
than silently accepting agreement or disagreement. Every field in
`CustomerFigures` is optional: a firm reconciling only its headline MA rate
in year one, and its full RM/SCR breakdown in year two, both produce a valid
report, with unsupplied figures explicitly marked as skipped rather than
silently treated as a match.

Tolerances are relative (a fraction of the independent value) by default,
because absolute differences on figures spanning basis points to millions
of pounds aren't comparable on one scale; a metric that can legitimately be
exactly zero (e.g. a VaR leg with no exposure) falls back to an absolute
tolerance so a zero-vs-zero comparison doesn't divide by zero.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict

DEFAULT_MATERIAL_TOLERANCE = 0.02   # >2% relative difference: material, escalate
DEFAULT_WATCH_TOLERANCE = 0.005     # >0.5% relative difference: watch, not yet material
ZERO_FALLBACK_ABSOLUTE_TOLERANCE = 1.0  # when the independent value is ~0, an absolute gap this small is immaterial


class DivergenceSeverity(str, Enum):
    NOT_SUPPLIED = "not_supplied"
    IMMATERIAL = "immaterial"
    WATCH = "watch"
    MATERIAL = "material"


class CustomerFigures(BaseModel):
    """Headline figures from the customer's own existing engine, supplied for
    reconciliation. Every field optional -- only supplied figures are compared."""

    model_config = ConfigDict(frozen=True)

    ma_bps: float | None = None
    bel_basic_rfr: float | None = None
    bel_with_ma: float | None = None
    ma_benefit: float | None = None
    fs_rate_bps: float | None = None
    risk_margin: float | None = None
    scr_total: float | None = None
    test1_ratio: float | None = None


class FigureComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    customer_value: float | None
    independent_value: float | None
    absolute_difference: float | None
    relative_difference: float | None
    severity: DivergenceSeverity
    note: str


class ReconciliationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    valuation_date: date
    currency: str
    liability_id: str
    comparisons: tuple[FigureComparison, ...]
    material_count: int
    watch_count: int
    overall_severity: DivergenceSeverity


def compare_figure(
    name: str,
    customer_value: float | None,
    independent_value: float | None,
    material_tolerance: float = DEFAULT_MATERIAL_TOLERANCE,
    watch_tolerance: float = DEFAULT_WATCH_TOLERANCE,
) -> FigureComparison:
    if customer_value is None:
        return FigureComparison(
            name=name, customer_value=None, independent_value=independent_value,
            absolute_difference=None, relative_difference=None,
            severity=DivergenceSeverity.NOT_SUPPLIED, note="not supplied by customer, skipped",
        )

    abs_diff = independent_value - customer_value

    if abs(independent_value) > ZERO_FALLBACK_ABSOLUTE_TOLERANCE:
        rel_diff = abs_diff / abs(independent_value)
        if abs(rel_diff) > material_tolerance:
            severity = DivergenceSeverity.MATERIAL
        elif abs(rel_diff) > watch_tolerance:
            severity = DivergenceSeverity.WATCH
        else:
            severity = DivergenceSeverity.IMMATERIAL
        note = f"{rel_diff:+.2%} relative to the independent figure"
    else:
        # independent value is ~0: relative comparison is meaningless, fall back to an absolute gap
        rel_diff = None
        if abs(abs_diff) > ZERO_FALLBACK_ABSOLUTE_TOLERANCE:
            severity = DivergenceSeverity.MATERIAL
        else:
            severity = DivergenceSeverity.IMMATERIAL
        note = f"independent value ~0, absolute gap {abs_diff:+.4f}"

    return FigureComparison(
        name=name, customer_value=customer_value, independent_value=independent_value,
        absolute_difference=abs_diff, relative_difference=rel_diff,
        severity=severity, note=note,
    )


_SEVERITY_RANK = {
    DivergenceSeverity.NOT_SUPPLIED: 0,
    DivergenceSeverity.IMMATERIAL: 1,
    DivergenceSeverity.WATCH: 2,
    DivergenceSeverity.MATERIAL: 3,
}


def build_reconciliation_report(
    customer: CustomerFigures,
    valuation_date: date,
    currency: str,
    liability_id: str,
    independent_ma_bps: float,
    independent_bel_basic_rfr: float,
    independent_bel_with_ma: float,
    independent_ma_benefit: float,
    independent_fs_rate_bps: float,
    independent_risk_margin: float | None = None,
    independent_scr_total: float | None = None,
    independent_test1_ratio: float | None = None,
    material_tolerance: float = DEFAULT_MATERIAL_TOLERANCE,
    watch_tolerance: float = DEFAULT_WATCH_TOLERANCE,
) -> ReconciliationReport:
    pairs: list[tuple[str, float | None, float | None]] = [
        ("MA (bps)", customer.ma_bps, independent_ma_bps),
        ("BEL, basic RFR", customer.bel_basic_rfr, independent_bel_basic_rfr),
        ("BEL, with MA", customer.bel_with_ma, independent_bel_with_ma),
        ("MA benefit", customer.ma_benefit, independent_ma_benefit),
        ("FS rate (bps)", customer.fs_rate_bps, independent_fs_rate_bps),
    ]
    if independent_risk_margin is not None:
        pairs.append(("Risk Margin", customer.risk_margin, independent_risk_margin))
    if independent_scr_total is not None:
        pairs.append(("SCR total", customer.scr_total, independent_scr_total))
    if independent_test1_ratio is not None:
        pairs.append(("Test 1 ratio", customer.test1_ratio, independent_test1_ratio))

    comparisons = tuple(
        compare_figure(name, cust_val, indep_val, material_tolerance, watch_tolerance)
        for name, cust_val, indep_val in pairs
    )

    material_count = sum(1 for c in comparisons if c.severity == DivergenceSeverity.MATERIAL)
    watch_count = sum(1 for c in comparisons if c.severity == DivergenceSeverity.WATCH)
    overall_severity = max((c.severity for c in comparisons), key=lambda s: _SEVERITY_RANK[s], default=DivergenceSeverity.NOT_SUPPLIED)

    return ReconciliationReport(
        generated_at=datetime.now(timezone.utc), valuation_date=valuation_date, currency=currency,
        liability_id=liability_id, comparisons=comparisons, material_count=material_count,
        watch_count=watch_count, overall_severity=overall_severity,
    )
