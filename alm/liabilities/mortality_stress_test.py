"""MA 2.2(3)/2.4 mortality-stress eligibility test: mortality risk is
allowed in the MA portfolio only if a prescribed adverse mortality stress
does not increase BEL by more than 5%. This is an eligibility gate on
whether a specific liability's mortality exposure may sit in the MA
portfolio at all, distinct from `scr.standard_formula.compute_longevity_scr`
(a capital charge computed on liabilities already accepted as eligible).

v1 stress mechanism: extend the liability's cash flow stream by a fixed
number of extra years at the final period's amount and frequency, a proxy
for people surviving longer than the base assumption (mortality improvement
is adverse for an annuity because it means MORE payments, not bigger ones --
unlike a uniform cash-flow scale, this actually discriminates between
liabilities of different duration and size, which a flat percentage scale
would not: scaling every cash flow by a fixed factor reproduces that same
factor as the BEL delta by construction, regardless of the liability's
shape, and would make the pass/fail test tautological). `MORTALITY_STRESS_
EXTRA_YEARS` is an illustrative placeholder (1 year), not the PRA's or the
firm's real prescribed mortality improvement stress; swap it when available.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from alm.contracts.cashflows import CashFlow, CashFlowVector
from alm.contracts.curves import Curve

MORTALITY_STRESS_EXTRA_YEARS = 1.0  # illustrative placeholder, see module docstring
MORTALITY_STRESS_BEL_THRESHOLD = 0.05  # MA 2.2(3)/2.4 regulatory default


class MortalityStressEligibilityResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    liability_id: str
    bel_base: float
    bel_stressed: float
    delta_ratio: float
    threshold: float
    extra_years: float
    passed: bool


def apply_mortality_improvement_stress(liability_cfs: CashFlowVector, extra_years: float = MORTALITY_STRESS_EXTRA_YEARS) -> CashFlowVector:
    if not liability_cfs.flows:
        return liability_cfs
    sorted_flows = sorted(liability_cfs.flows, key=lambda cf: cf.time)
    last = sorted_flows[-1]
    step = last.time - sorted_flows[-2].time if len(sorted_flows) >= 2 else last.time
    n_extra = round(extra_years / step) if step > 0 else 0
    extra_flows = tuple(
        CashFlow(time=last.time + (i + 1) * step, amount=last.amount, kind=last.kind, inflation_linked=last.inflation_linked)
        for i in range(n_extra)
    )
    return liability_cfs.model_copy(update={
        "id": liability_cfs.id + "_mortality_stress",
        "flows": tuple(sorted_flows) + extra_flows,
    })


def evaluate_mortality_stress_eligibility(
    liability_cfs: CashFlowVector,
    curve: Curve,
    extra_years: float = MORTALITY_STRESS_EXTRA_YEARS,
    threshold: float = MORTALITY_STRESS_BEL_THRESHOLD,
) -> MortalityStressEligibilityResult:
    bel_base = liability_cfs.pv(curve)
    stressed_cfs = apply_mortality_improvement_stress(liability_cfs, extra_years)
    bel_stressed = stressed_cfs.pv(curve)
    delta_ratio = (bel_stressed - bel_base) / bel_base if bel_base > 0 else 0.0

    return MortalityStressEligibilityResult(
        liability_id=liability_cfs.id, bel_base=bel_base, bel_stressed=bel_stressed,
        delta_ratio=delta_ratio, threshold=threshold, extra_years=extra_years,
        passed=delta_ratio <= threshold,
    )
