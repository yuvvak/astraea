"""A small synthetic Prophet-extract-shaped dataset exercising the
eligibility gate: some clearly eligible model points (incl. one eligible
element and one with a reinsurance recovery to net off), and several that
must be excluded for distinct, hand-checkable reasons. Used by
`alm/tests/test_prophet_adapter.py` -- not a real Prophet output, since none
has been supplied yet (see README "open inputs").
"""

from __future__ import annotations

from datetime import date

import pandas as pd

VALUATION_DATE = date(2026, 9, 8)
CURRENCY = "GBP"

_BASE_ROW = dict(
    scheme_id=None, currency=CURRENCY, valuation_date=VALUATION_DATE.isoformat(),
    in_payment_flag=True, inflation_linked_flag=False, indexation_type="level",
    future_premium_flag=False, discretionary_wp_flag=False, unit_linked_flag=False,
    surrender_option_flag=False, constrained_surrender_flag=False,
    expense_cf=0.0, reinsurance_cf=0.0, option_surrender_cf=0.0,
)


def build_extract_dataframe() -> pd.DataFrame:
    rows = []

    # MP001: eligible individual annuity, in payment, 3 years, GBP 50,000 p.a. + GBP 500 p.a. expense
    for t in (1, 2, 3):
        rows.append({**_BASE_ROW, "model_point_id": "MP001", "product_code": "IND_ANNUITY_INPAY",
                     "t": t, "benefit_cf": 50_000.0, "expense_cf": 500.0})

    # MP002: eligible individual annuity with a reinsurance recovery to net off
    # (net = 30,000 + 300 - 2,000 = 28,300 per year)
    for t in (1, 2, 3):
        rows.append({**_BASE_ROW, "model_point_id": "MP002", "product_code": "IND_ANNUITY_INPAY",
                     "t": t, "benefit_cf": 30_000.0, "expense_cf": 300.0, "reinsurance_cf": 2_000.0})

    # MP003: unit-linked -- must be excluded (MA 2.2, unit-linked not eligible)
    for t in (1, 2, 3):
        rows.append({**_BASE_ROW, "model_point_id": "MP003", "product_code": "IND_ANNUITY_INPAY",
                     "unit_linked_flag": True, "t": t, "benefit_cf": 999_999.0})

    # MP004: eligible element -- guaranteed component of a with-profits annuity (no discretion)
    for t in (1, 2, 3):
        rows.append({**_BASE_ROW, "model_point_id": "MP004", "product_code": "WP_GUARANTEED_ELEMENT",
                     "t": t, "benefit_cf": 10_000.0})

    # MP005: future-premium-paying -- must be excluded (MA 2.2(1)/2.5)
    for t in (1, 2, 3):
        rows.append({**_BASE_ROW, "model_point_id": "MP005", "product_code": "IND_ANNUITY_INPAY",
                     "future_premium_flag": True, "t": t, "benefit_cf": 20_000.0})

    # MP006: deferred annuity with an unconstrained surrender option -- must be excluded
    # (MA 2.2(4)(b) condition not evidenced: constrained_surrender_flag is False)
    for t in (5, 6, 7):
        rows.append({**_BASE_ROW, "model_point_id": "MP006", "product_code": "DEFERRED_ANNUITY",
                     "in_payment_flag": False, "surrender_option_flag": True,
                     "t": t, "benefit_cf": 15_000.0})

    return pd.DataFrame(rows)
