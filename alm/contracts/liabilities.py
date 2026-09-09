"""Minimal liability contracts for the v1 golden example.

Full eligibility engine, Prophet adapter and the broader product taxonomy
(BPA, deferred annuities, LPI, GMP, eligible-elements splitting, etc.) are
deferred until the MA engine reproduces the golden example. This module only
covers a level, single-life, in-payment annuity with no options -- the
simplest MA-eligible liability (IRPR reg 5 / MA 2.2).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from .cashflows import CashFlow, CashFlowKind, CashFlowVector


class LevelAnnuityCohort(BaseModel):
    """A cohort of single-life, level, in-payment annuities with no guarantee
    period and no escalation -- deterministic best-estimate cash flow = annual
    payment x survivors, using a supplied survival curve (or, for the golden
    example, a fixed term with 100% certainty to keep the hand-calc exact)."""

    model_config = ConfigDict(frozen=True)

    id: str
    currency: str = Field(..., min_length=3, max_length=3)
    annual_payment: float = Field(..., gt=0, description="Total annual benefit in payment across the cohort")
    payment_frequency: int = Field(1, description="Payments per year")
    term_years: float = Field(..., gt=0, description="Certain term in years (golden-example simplification; replace with survival probabilities for real cohorts)")
    survival_probabilities: tuple[float, ...] | None = Field(
        None, description="Optional per-period survival probability, same length as the number of payment periods; if omitted, certain (=1.0) payments are assumed for the golden example only")

    def best_estimate_cashflows(self, valuation_date: date) -> CashFlowVector:
        step = 1.0 / self.payment_frequency
        amount_per_period = self.annual_payment / self.payment_frequency
        n_periods = round(self.term_years / step)
        flows: list[CashFlow] = []
        for i in range(1, n_periods + 1):
            t = i * step
            surv = 1.0
            if self.survival_probabilities is not None:
                idx = i - 1
                surv = self.survival_probabilities[idx] if idx < len(self.survival_probabilities) else 0.0
            flows.append(CashFlow(time=t, amount=amount_per_period * surv, kind=CashFlowKind.BENEFIT))
        return CashFlowVector(
            id=self.id, currency=self.currency, valuation_date=valuation_date,
            direction="liability_outgo", flows=tuple(flows),
        )


# Alias for forward compatibility with the fuller product taxonomy (BPA, deferred, etc.)
LiabilityCohort = LevelAnnuityCohort
