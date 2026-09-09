"""Model point attribute schema: the static (non-time-varying) fields that
drive MA eligibility for one Prophet model point / cohort. Time-varying cash
flows are carried separately (one row per period) by `prophet_io` -- this
module only fixes the *product taxonomy* and the eligibility-relevant flags
that both `prophet_io` (producer) and `liabilities.eligibility` (consumer)
share, so the two never drift apart on field names.

`ProductCode` is a v1 subset of the MA-eligible UK annuity universe (project
brief scope section) -- individual annuities, BPA, deferred annuities and the
three named eligible-elements. It is NOT the full taxonomy (LPI variants,
GMP/anti-franking, impaired-life etc. are attributes of these product codes,
not separate codes, and are not yet modelled). Anything not in this enum
must resolve to `ProductCode.UNKNOWN`, which the eligibility gate always
fails closed -- see `liabilities.eligibility`.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ProductCode(str, Enum):
    # MA 2.2 -- individual lifetime annuities, in payment, no future premiums, no options
    IND_ANNUITY_INPAY = "IND_ANNUITY_INPAY"
    # MA 2.2 -- bulk purchase annuity, in payment
    BPA_INPAY = "BPA_INPAY"
    # MA 2.2(4)(b) -- deferred annuity; eligible only if any surrender/CETV/PCLS option is
    # constrained so surrender value <= value of covering assets at exercise
    DEFERRED_ANNUITY = "DEFERRED_ANNUITY"
    # MA 2.3/2.5 -- eligible element: contractually guaranteed component of a with-profits
    # annuity only (no discretionary benefit, no dependence on future premiums/investment performance)
    WP_GUARANTEED_ELEMENT = "WP_GUARANTEED_ELEMENT"
    # MA 2.3/2.5 -- eligible element: in-payment income protection (recovery-time risk only)
    IP_INPAY = "IP_INPAY"
    # MA 2.3/2.5 -- eligible element: in-payment group death-in-service dependant annuity
    GROUP_DIS_DEPENDANT = "GROUP_DIS_DEPENDANT"
    # Explicitly excluded families (brief, "explicitly EXCLUDE") -- kept in the enum so the
    # extract can *say* what a contract is and be correctly rejected, rather than mis-mapping
    # it to UNKNOWN and losing the specific reason.
    UNIT_LINKED = "UNIT_LINKED"
    FUTURE_PREMIUM_PAYING = "FUTURE_PREMIUM_PAYING"
    DISCRETIONARY_WITH_PROFITS = "DISCRETIONARY_WITH_PROFITS"
    UNKNOWN = "UNKNOWN"


class ModelPointAttributes(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_point_id: str
    product_code: ProductCode
    currency: str = Field(..., min_length=3, max_length=3)
    scheme_id: str | None = None

    in_payment_flag: bool = True
    inflation_linked_flag: bool = False
    indexation_type: str = "level"  # "level" | "fixed_esc" | "RPI" | "CPI" | "LPI_0_5" | "LPI_0_3" | "LPI_0_2_5" | "other"

    future_premium_flag: bool = False
    discretionary_wp_flag: bool = False
    unit_linked_flag: bool = False
    surrender_option_flag: bool = False
    # MA 2.2(4)(b): surrender value <= value of covering assets at exercise -- must be
    # demonstrated, not assumed; only relevant when surrender_option_flag is True
    constrained_surrender_flag: bool = False
