"""Minimal Highly-Predictable (HP) asset instrument, sufficient to exercise
PRA Tests 4 and 5 (SS7/18 Appendix 1) -- MA Chapter 5 defines HP assets as
having *bounded* contractual variability in cash flow timing/amount (e.g. a
loan that must fully repay somewhere between an earliest and a latest
permitted date). The full HP engine (expert-judgement controls, default-if-
bounds-breached logic, the broader asset library) is deferred; this is only
the cash-flow-profile machinery the two HP tests need.

Three profiles are generated from the same instrument:

- `expected_cashflows`: the contractual base case -- coupon to `maturity_years`,
  bullet principal at `maturity_years`.
- `loss_minimizing_cashflows` (Test 4): principal repaid at the EARLIEST
  permitted date, with the early receipt assumed prudently reinvested (SS7/18:
  "optional prudent reinvestment... spread limited") at a reduced rate out to
  `maturity_years` -- modelling reinvestment risk, the economic mechanism
  Test 4 exists to catch.
- `extended_cashflows` (Test 5): principal repaid at the LATEST permitted
  date instead, with a step-up coupon applied for the extension period --
  modelling the opposite risk, cash arriving later than the liability needs
  it, which shows up as a larger PRA Test 1-style accumulated shortfall.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alm.contracts.cashflows import CashFlow, CashFlowKind, CashFlowVector
from alm.contracts.fs import AssetSector, RatingNotch


class HPBond(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    currency: str = Field(..., min_length=3, max_length=3)
    notional: float = Field(..., gt=0)
    coupon_rate: float = Field(..., ge=0)
    coupon_frequency: int = 1
    maturity_years: float = Field(..., gt=0, description="Contractual base-case (expected) repayment date")
    earliest_repayment_years: float = Field(..., gt=0, description="Earliest permitted repayment date (Test 4 bound)")
    latest_repayment_years: float = Field(..., gt=0, description="Latest permitted repayment date (Test 5 bound)")
    step_up_rate: float = Field(..., ge=0, description="Coupon rate applied during the maturity->latest extension period")
    prudent_reinvestment_rate: float = Field(..., ge=0, description="Rate the early-received principal is assumed reinvested at, from earliest_repayment_years to maturity_years -- must be spread-limited (SS7/18), i.e. materially below coupon_rate")
    rating: RatingNotch
    sector: AssetSector
    is_government: bool = False

    @model_validator(mode="after")
    def _bounds_are_ordered(self):
        if not (self.earliest_repayment_years < self.maturity_years < self.latest_repayment_years):
            raise ValueError("require earliest_repayment_years < maturity_years < latest_repayment_years")
        if self.prudent_reinvestment_rate >= self.coupon_rate:
            raise ValueError("prudent_reinvestment_rate must be spread-limited: below coupon_rate")
        return self

    def _coupon_leg(self, end_time: float, rate: float, step: float) -> list[CashFlow]:
        n_periods = round(end_time / step)
        coupon = self.notional * rate / self.coupon_frequency
        return [CashFlow(time=(i + 1) * step, amount=coupon, kind=CashFlowKind.COUPON) for i in range(n_periods)]

    def expected_cashflows(self, valuation_date: date) -> CashFlowVector:
        step = 1.0 / self.coupon_frequency
        flows = self._coupon_leg(self.maturity_years, self.coupon_rate, step)
        flows.append(CashFlow(time=self.maturity_years, amount=self.notional, kind=CashFlowKind.PRINCIPAL))
        return CashFlowVector(
            id=self.id + "_expected", currency=self.currency, valuation_date=valuation_date,
            direction="asset_income", flows=tuple(sorted(flows, key=lambda cf: cf.time)),
        )

    def loss_minimizing_cashflows(self, valuation_date: date) -> CashFlowVector:
        """Test 4: principal received at the earliest permitted date, then
        prudently reinvested (at a reduced, spread-limited rate) out to the
        original maturity date, landing as a single terminal amount there."""
        step = 1.0 / self.coupon_frequency
        flows = self._coupon_leg(self.earliest_repayment_years, self.coupon_rate, step)
        reinvestment_years = self.maturity_years - self.earliest_repayment_years
        terminal_amount = self.notional * (1.0 + self.prudent_reinvestment_rate) ** reinvestment_years
        flows.append(CashFlow(time=self.maturity_years, amount=terminal_amount, kind=CashFlowKind.PRINCIPAL))
        return CashFlowVector(
            id=self.id + "_loss_min", currency=self.currency, valuation_date=valuation_date,
            direction="asset_income", flows=tuple(sorted(flows, key=lambda cf: cf.time)),
        )

    def extended_cashflows(self, valuation_date: date) -> CashFlowVector:
        """Test 5: principal repaid at the latest permitted date instead of
        the expected maturity, with a step-up coupon for the extension leg."""
        step = 1.0 / self.coupon_frequency
        flows = self._coupon_leg(self.maturity_years, self.coupon_rate, step)
        extension_years = self.latest_repayment_years - self.maturity_years
        n_extension_periods = round(extension_years / step)
        step_up_coupon = self.notional * self.step_up_rate / self.coupon_frequency
        for i in range(n_extension_periods):
            flows.append(CashFlow(time=self.maturity_years + (i + 1) * step, amount=step_up_coupon, kind=CashFlowKind.COUPON))
        flows.append(CashFlow(time=self.latest_repayment_years, amount=self.notional, kind=CashFlowKind.PRINCIPAL))
        return CashFlowVector(
            id=self.id + "_extended", currency=self.currency, valuation_date=valuation_date,
            direction="asset_income", flows=tuple(sorted(flows, key=lambda cf: cf.time)),
        )
