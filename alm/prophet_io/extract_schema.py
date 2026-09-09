"""Documented interface spec for the Prophet cash flow extract this adapter
consumes (project brief deliverable 10: "exact columns the extract must
contain"). No sample extract has been supplied yet -- this is a v1 default
schema, isolated here as the single point of contact with Prophet, so that
when a real extract layout is available only this file (plus a thin column-
rename mapping) needs to change, not `adapter.py` or anything downstream.

Format: long/denormalised CSV or parquet, **one row per model point per
projection period**. Static (non-time-varying) model point attributes are
repeated on every row for that model point -- this trades file size for a
trivial, join-free load. `product_code` maps 1:1 to
`alm.contracts.model_points.ProductCode`.

Columns
-------
model_point_id        str    unique key per Prophet model point / cohort
product_code           str    one of alm.contracts.model_points.ProductCode values
scheme_id              str    nullable; BPA scheme reference, else blank
currency                str    ISO 4217, e.g. "GBP"
valuation_date          date   ISO 8601, same for every row in one extract
t                        float  years from valuation_date for this row's cash flows
in_payment_flag          bool
inflation_linked_flag    bool
indexation_type          str    "level" | "fixed_esc" | "RPI" | "CPI" | "LPI_0_5" | "LPI_0_3" | "LPI_0_2_5" | "other"
future_premium_flag      bool
discretionary_wp_flag    bool
unit_linked_flag         bool
surrender_option_flag    bool
constrained_surrender_flag  bool   MA 2.2(4)(b) condition evidenced (deferred annuities only)
benefit_cf               float  best-estimate undiscounted benefit outgo for this period (>=0)
expense_cf               float  best-estimate undiscounted expense outgo for this period (>=0)
reinsurance_cf            float  best-estimate reinsurance RECOVERY for this period (>=0;
                                 netted off outgo downstream, not itself a negative number)
option_surrender_cf       float  option/surrender outgo for this period (>=0, 0 if none)
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

REQUIRED_COLUMNS = (
    "model_point_id", "product_code", "scheme_id", "currency", "valuation_date", "t",
    "in_payment_flag", "inflation_linked_flag", "indexation_type",
    "future_premium_flag", "discretionary_wp_flag", "unit_linked_flag",
    "surrender_option_flag", "constrained_surrender_flag",
    "benefit_cf", "expense_cf", "reinsurance_cf", "option_surrender_cf",
)


class ProphetExtractRow(BaseModel):
    """One validated row of the extract. `adapter.load_prophet_extract` builds
    one of these per CSV row before grouping by model_point_id -- catches
    malformed extracts at the boundary rather than deep inside the pipeline."""

    model_config = ConfigDict(frozen=True)

    model_point_id: str
    product_code: str
    scheme_id: str | None = None
    currency: str = Field(..., min_length=3, max_length=3)
    valuation_date: date
    t: float = Field(..., ge=0)
    in_payment_flag: bool
    inflation_linked_flag: bool
    indexation_type: str = "level"
    future_premium_flag: bool = False
    discretionary_wp_flag: bool = False
    unit_linked_flag: bool = False
    surrender_option_flag: bool = False
    constrained_surrender_flag: bool = False
    benefit_cf: float = 0.0
    expense_cf: float = 0.0
    reinsurance_cf: float = 0.0
    option_surrender_cf: float = 0.0
