"""MA eligibility gate. Every model point coming out of `prophet_io` (or the
reference projector) must pass through `evaluate_eligibility` before its cash
flows are allowed anywhere near the MA engine. Fails closed: an unrecognised
product code, or a recognised one with a disqualifying flag set, is
ineligible -- it is never silently included (project brief: "Flag ineligible
contracts rather than silently including them.").

Citations are named constants, not inlined, per the brief's non-functional
requirement that every regulatory threshold/rule be traceable in comments.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from alm.contracts.model_points import ModelPointAttributes, ProductCode

# IRPR = Insurance and Reinsurance Undertakings (Prudential Requirements) Regulations 2023
CITATION_NO_FUTURE_PREMIUMS = "MA 2.2(1)/2.5; IRPR reg 5 -- no future premium-paying contracts except specified eligible elements"
CITATION_NO_DISCRETIONARY_WP = "MA 2.3/2.5 -- with-profits contracts eligible only for the contractually guaranteed, non-discretionary component"
CITATION_NO_UNIT_LINKED = "MA 2.2 -- unit-linked/drawdown benefits are not MA-eligible (benefit value depends on investment performance)"
CITATION_CONSTRAINED_SURRENDER = "MA 2.2(4)(b) -- deferred annuity surrender/CETV/PCLS only eligible where surrender value <= value of covering assets at exercise"
CITATION_UNCONSTRAINED_SURRENDER = "MA 2.2 -- policyholder options other than the MA 2.2(4)(b)-constrained surrender are not MA-eligible"
CITATION_UNKNOWN_PRODUCT = "Not on the firm's MA-eligible product list (project brief scope) -- fails closed pending explicit classification"
CITATION_ELIGIBLE_BASE = "MA 2.2 -- eligible individual/BPA annuity in payment, no future premiums, no disqualifying options"
CITATION_ELIGIBLE_ELEMENT = "MA 2.3/2.5 -- eligible element of an otherwise ineligible contract"


class EligibilityResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_point_id: str
    eligible: bool
    eligible_element: bool  # True if eligible only as a carved-out element (MA 2.3/2.5), not the whole contract
    reason: str
    citation: str


_ELIGIBLE_ELEMENT_CODES = {
    ProductCode.WP_GUARANTEED_ELEMENT,
    ProductCode.IP_INPAY,
    ProductCode.GROUP_DIS_DEPENDANT,
}
_BASE_ELIGIBLE_CODES = {
    ProductCode.IND_ANNUITY_INPAY,
    ProductCode.BPA_INPAY,
    ProductCode.DEFERRED_ANNUITY,
}
_ALWAYS_INELIGIBLE_CODES = {
    ProductCode.UNIT_LINKED,
    ProductCode.FUTURE_PREMIUM_PAYING,
    ProductCode.DISCRETIONARY_WITH_PROFITS,
}


def evaluate_eligibility(attrs: ModelPointAttributes) -> EligibilityResult:
    mpid = attrs.model_point_id

    def ineligible(reason: str, citation: str) -> EligibilityResult:
        return EligibilityResult(model_point_id=mpid, eligible=False, eligible_element=False, reason=reason, citation=citation)

    # 1. explicit fail-closed product codes
    if attrs.product_code in _ALWAYS_INELIGIBLE_CODES:
        citation = {
            ProductCode.UNIT_LINKED: CITATION_NO_UNIT_LINKED,
            ProductCode.FUTURE_PREMIUM_PAYING: CITATION_NO_FUTURE_PREMIUMS,
            ProductCode.DISCRETIONARY_WITH_PROFITS: CITATION_NO_DISCRETIONARY_WP,
        }[attrs.product_code]
        return ineligible(f"product_code={attrs.product_code.value} is explicitly excluded from the MA liability set", citation)

    # 2. unrecognised product code -- fail closed
    if attrs.product_code == ProductCode.UNKNOWN:
        return ineligible("product_code is UNKNOWN / not on the MA-eligible product list", CITATION_UNKNOWN_PRODUCT)

    # 3. universal disqualifying flags, regardless of product code
    if attrs.unit_linked_flag:
        return ineligible("unit_linked_flag is set", CITATION_NO_UNIT_LINKED)
    if attrs.discretionary_wp_flag and attrs.product_code != ProductCode.WP_GUARANTEED_ELEMENT:
        return ineligible("discretionary_wp_flag is set on a non-guaranteed-element product", CITATION_NO_DISCRETIONARY_WP)

    # 4. future premiums are always disqualifying. Eligible elements (MA 2.3/2.5) are
    # specifically DEFINED as not depending on future premiums, so future_premium_flag=True
    # on one of those product codes is a data inconsistency, not a valid carve-out: fail closed
    # rather than silently exempt it (caught via the generated eligibility matrix, see
    # ELIGIBILITY_MATRIX.md / eligibility_matrix.py).
    is_eligible_element_code = attrs.product_code in _ELIGIBLE_ELEMENT_CODES
    if attrs.future_premium_flag:
        return ineligible("future_premium_flag is set", CITATION_NO_FUTURE_PREMIUMS)

    # 5. surrender/option constraint (deferred annuities only, MA 2.2(4)(b))
    if attrs.surrender_option_flag:
        if attrs.product_code != ProductCode.DEFERRED_ANNUITY:
            return ineligible("surrender_option_flag is set on a non-deferred product", CITATION_UNCONSTRAINED_SURRENDER)
        if not attrs.constrained_surrender_flag:
            return ineligible(
                "surrender_option_flag is set but constrained_surrender_flag is not -- "
                "MA 2.2(4)(b) condition (surrender value <= covering assets) is not evidenced",
                CITATION_CONSTRAINED_SURRENDER,
            )

    # 6. eligible-element products
    if is_eligible_element_code:
        return EligibilityResult(
            model_point_id=mpid, eligible=True, eligible_element=True,
            reason=f"product_code={attrs.product_code.value} is a recognised MA 2.3/2.5 eligible element",
            citation=CITATION_ELIGIBLE_ELEMENT,
        )

    # 7. base eligible products
    if attrs.product_code in _BASE_ELIGIBLE_CODES:
        return EligibilityResult(
            model_point_id=mpid, eligible=True, eligible_element=False,
            reason=f"product_code={attrs.product_code.value} meets MA 2.2 base eligibility conditions",
            citation=CITATION_ELIGIBLE_BASE,
        )

    # Should be unreachable given the enum is exhaustively covered above; fail closed rather
    # than silently include if a new ProductCode is ever added without updating this gate.
    return ineligible(f"product_code={attrs.product_code.value} not handled by any eligibility rule", CITATION_UNKNOWN_PRODUCT)
