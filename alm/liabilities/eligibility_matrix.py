"""Generates a product x feature eligibility matrix (eligible /
eligible-element / fail, with rule citations). Every row is produced by
actually running `evaluate_eligibility` against a constructed
`ModelPointAttributes`, so the matrix can't drift from the code that
decides real cases: it's a report of the gate's actual behaviour, not a
hand-typed table someone forgot to update after a rule changed.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from alm.contracts.model_points import ModelPointAttributes, ProductCode

from .eligibility import EligibilityResult, evaluate_eligibility

BASE_ELIGIBLE_PRODUCTS = [
    ProductCode.IND_ANNUITY_INPAY,
    ProductCode.BPA_INPAY,
    ProductCode.DEFERRED_ANNUITY,
]
ELIGIBLE_ELEMENT_PRODUCTS = [
    ProductCode.WP_GUARANTEED_ELEMENT,
    ProductCode.IP_INPAY,
    ProductCode.GROUP_DIS_DEPENDANT,
]
ALWAYS_INELIGIBLE_PRODUCTS = [
    ProductCode.UNIT_LINKED,
    ProductCode.FUTURE_PREMIUM_PAYING,
    ProductCode.DISCRETIONARY_WITH_PROFITS,
]


class MatrixRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_code: ProductCode
    scenario: str
    verdict: str  # "eligible", "eligible_element", or "fail"
    reason: str
    citation: str


def _verdict(result: EligibilityResult) -> str:
    if not result.eligible:
        return "fail"
    return "eligible_element" if result.eligible_element else "eligible"


def _row(product_code: ProductCode, scenario: str, **overrides) -> MatrixRow:
    attrs = ModelPointAttributes(
        model_point_id=f"{product_code.value}::{scenario}",
        product_code=product_code,
        currency="GBP",
        **overrides,
    )
    result = evaluate_eligibility(attrs)
    return MatrixRow(product_code=product_code, scenario=scenario, verdict=_verdict(result), reason=result.reason, citation=result.citation)


def generate_matrix() -> list[MatrixRow]:
    rows: list[MatrixRow] = []

    for pc in BASE_ELIGIBLE_PRODUCTS + ELIGIBLE_ELEMENT_PRODUCTS:
        rows.append(_row(pc, "baseline, no disqualifying features", in_payment_flag=True))

    for pc in ALWAYS_INELIGIBLE_PRODUCTS:
        rows.append(_row(pc, "baseline", in_payment_flag=True))

    rows.append(_row(ProductCode.UNKNOWN, "baseline"))

    for pc in BASE_ELIGIBLE_PRODUCTS + ELIGIBLE_ELEMENT_PRODUCTS:
        rows.append(_row(pc, "plus future_premium_flag", in_payment_flag=True, future_premium_flag=True))
        rows.append(_row(pc, "plus unit_linked_flag", in_payment_flag=True, unit_linked_flag=True))

    rows.append(_row(
        ProductCode.WP_GUARANTEED_ELEMENT, "plus discretionary_wp_flag (loses guaranteed-only status)",
        in_payment_flag=True, discretionary_wp_flag=True,
    ))
    rows.append(_row(
        ProductCode.IND_ANNUITY_INPAY, "plus discretionary_wp_flag",
        in_payment_flag=True, discretionary_wp_flag=True,
    ))

    rows.append(_row(
        ProductCode.DEFERRED_ANNUITY, "plus surrender_option_flag, constrained (MA 2.2(4)(b) evidenced)",
        in_payment_flag=False, surrender_option_flag=True, constrained_surrender_flag=True,
    ))
    rows.append(_row(
        ProductCode.DEFERRED_ANNUITY, "plus surrender_option_flag, unconstrained",
        in_payment_flag=False, surrender_option_flag=True, constrained_surrender_flag=False,
    ))
    rows.append(_row(
        ProductCode.IND_ANNUITY_INPAY, "plus surrender_option_flag (in-payment, no MA 2.2(4)(b) carve-out available)",
        in_payment_flag=True, surrender_option_flag=True, constrained_surrender_flag=True,
    ))

    return rows


def render_markdown(rows: list[MatrixRow] | None = None) -> str:
    rows = rows if rows is not None else generate_matrix()
    lines = [
        "# MA Eligibility Matrix",
        "",
        "Generated from `alm/liabilities/eligibility_matrix.py`, which runs each row through the actual",
        "`evaluate_eligibility` gate (`alm/liabilities/eligibility.py`). Regenerate with:",
        "",
        "```bash",
        ".venv/Scripts/python -c \"from alm.liabilities.eligibility_matrix import render_markdown; print(render_markdown())\" > ELIGIBILITY_MATRIX.md",
        "```",
        "",
        "| Product code | Scenario | Verdict | Reason | Citation |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r.product_code.value} | {r.scenario} | {r.verdict} | {r.reason} | {r.citation} |")
    return "\n".join(lines) + "\n"
