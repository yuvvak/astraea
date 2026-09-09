"""Prophet extract adapter: CSV -> validated rows -> eligibility gate ->
per-model-point CashFlowVectors. This is the primary liability path (project
brief: "Primary path: ingest Prophet model-point and cash-flow extracts").

Every model point is run through `liabilities.eligibility.evaluate_eligibility`
before its cash flows are trusted anywhere downstream; ineligible model
points are collected in `ProphetLoadResult.excluded` and never appear in
`eligible_net_cashflows` or `eligible_gross_cashflows` -- there is no code
path that lets an ineligible contract's cash flows reach the MA engine
silently.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict

from alm.contracts.cashflows import CashFlow, CashFlowKind, CashFlowVector
from alm.contracts.model_points import ModelPointAttributes, ProductCode
from alm.liabilities.eligibility import EligibilityResult, evaluate_eligibility

from .extract_schema import REQUIRED_COLUMNS, ProphetExtractRow


class ProphetLoadResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    eligible_gross_cashflows: dict[str, CashFlowVector]  # per model point, kinds kept separate (audit trail)
    eligible_net_cashflows: dict[str, CashFlowVector]     # per model point, netted (reinsurance offsets outgo)
    excluded: tuple[EligibilityResult, ...]
    eligibility_by_model_point: dict[str, EligibilityResult]  # includes eligible ones too, for a full audit log


def _rows_to_model_point_attributes(rows: list[ProphetExtractRow]) -> ModelPointAttributes:
    first = rows[0]
    try:
        product_code = ProductCode(first.product_code)
    except ValueError:
        product_code = ProductCode.UNKNOWN
    return ModelPointAttributes(
        model_point_id=first.model_point_id,
        product_code=product_code,
        currency=first.currency,
        scheme_id=first.scheme_id,
        in_payment_flag=first.in_payment_flag,
        inflation_linked_flag=first.inflation_linked_flag,
        indexation_type=first.indexation_type,
        future_premium_flag=first.future_premium_flag,
        discretionary_wp_flag=first.discretionary_wp_flag,
        unit_linked_flag=first.unit_linked_flag,
        surrender_option_flag=first.surrender_option_flag,
        constrained_surrender_flag=first.constrained_surrender_flag,
    )


def _rows_to_gross_cashflow_vector(model_point_id: str, currency: str, valuation_date: date, rows: list[ProphetExtractRow]) -> CashFlowVector:
    flows: list[CashFlow] = []
    for row in rows:
        if row.benefit_cf:
            flows.append(CashFlow(time=row.t, amount=row.benefit_cf, kind=CashFlowKind.BENEFIT, inflation_linked=row.inflation_linked_flag))
        if row.expense_cf:
            flows.append(CashFlow(time=row.t, amount=row.expense_cf, kind=CashFlowKind.EXPENSE))
        if row.reinsurance_cf:
            flows.append(CashFlow(time=row.t, amount=row.reinsurance_cf, kind=CashFlowKind.REINSURANCE))
        if row.option_surrender_cf:
            flows.append(CashFlow(time=row.t, amount=row.option_surrender_cf, kind=CashFlowKind.OPTION_SURRENDER))
    return CashFlowVector(
        id=model_point_id, currency=currency, valuation_date=valuation_date,
        direction="liability_outgo", flows=tuple(flows),
    )


def load_prophet_extract(path: str | Path) -> ProphetLoadResult:
    df = pd.read_csv(path)
    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Prophet extract {path} is missing required columns: {sorted(missing)}")

    rows_by_mp: dict[str, list[ProphetExtractRow]] = {}
    for record in df.to_dict(orient="records"):
        row = ProphetExtractRow(**{k: (None if pd.isna(v) else v) for k, v in record.items() if k in ProphetExtractRow.model_fields})
        rows_by_mp.setdefault(row.model_point_id, []).append(row)

    eligible_gross: dict[str, CashFlowVector] = {}
    eligible_net: dict[str, CashFlowVector] = {}
    excluded: list[EligibilityResult] = []
    eligibility_log: dict[str, EligibilityResult] = {}

    for mpid, rows in rows_by_mp.items():
        rows.sort(key=lambda r: r.t)
        attrs = _rows_to_model_point_attributes(rows)
        result = evaluate_eligibility(attrs)
        eligibility_log[mpid] = result

        if not result.eligible:
            excluded.append(result)
            continue

        gross = _rows_to_gross_cashflow_vector(mpid, attrs.currency, rows[0].valuation_date, rows)
        eligible_gross[mpid] = gross
        eligible_net[mpid] = gross.net_by_time(id=mpid + "_net")

    return ProphetLoadResult(
        eligible_gross_cashflows=eligible_gross,
        eligible_net_cashflows=eligible_net,
        excluded=tuple(excluded),
        eligibility_by_model_point=eligibility_log,
    )


def aggregate_net_liability_cashflows(result: ProphetLoadResult, currency: str, id: str) -> CashFlowVector:
    """Merge every eligible model point's net cash flows into one per-currency
    liability CashFlowVector for the MA engine. Flows are concatenated, not
    pre-summed per time -- PV/Test1/hypothecation all sum contributions
    correctly across multiple flows at the same time (see
    CashFlowVector.pv and the accumulation loops in ma/hypothecation.py and
    tests_pra/accumulated_cf_shortfall.py, both fixed to accumulate rather
    than overwrite same-time entries)."""
    vectors = [v for v in result.eligible_net_cashflows.values() if v.currency == currency]
    if not vectors:
        raise ValueError(f"no eligible model points in currency {currency}")
    return CashFlowVector.merge(vectors, id=id)
