"""Asset instrument contracts: a plain fixed-rate bullet bond (also used for
index-linked gilts, via `inflation_linked` + `assumed_inflation_rate`),
cash, an amortizing loan (infra debt, ERM restructured notes, project
finance, CRE loans), a fixed-for-floating interest rate swap and a
year-on-year inflation swap (see `InterestRateSwap`'s docstring for the
shared narrower scope -- frozen expected cash flows at construction;
`stresses.runner.reproject_swaps` rebuilds an `InterestRateSwap`'s
projection under a stressed curve, but `InflationSwap`'s flat inflation
assumption has no curve to reproject from), a reinsurance recoverable (see
`ReinsuranceRecoverable`'s docstring on why funded collateral is tracked
separately from market value, never netted into it), and a look-through
fund holding (`FundHolding`, expanded to its constituents for SF SCR --
see `scr.look_through`). Still deferred: the fuller derivatives set
(currency swaps, swaptions).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cashflows import CashFlow, CashFlowKind, CashFlowVector
from .curves import Curve
from .fs import AssetSector, RatingNotch


class Bond(BaseModel):
    """Plain fixed-rate bullet bond: annual (or sub-annual) coupons + bullet
    principal. Sufficient for gilts and vanilla corporates.

    Set `inflation_linked=True` to model an index-linked gilt: every cash
    flow (coupon and principal) is uplifted by `(1 + assumed_inflation_rate)^t`
    and tagged `CashFlow.inflation_linked=True`, which is what feeds PRA
    Test 2's inflation VaR leg. `assumed_inflation_rate` is a flat
    illustrative assumption (documented v1 simplification -- a real IL gilt
    should be priced off a real yield curve, not the nominal RFR curve with
    an inflation uplift bolted on; swap `price()` for a dedicated real-curve
    pricer once one exists).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    currency: str = Field(..., min_length=3, max_length=3)
    notional: float = Field(..., gt=0)
    coupon_rate: float = Field(..., ge=0, description="Annual coupon rate, e.g. 0.04 for 4%")
    coupon_frequency: int = Field(1, description="Coupons per year (1, 2, 4, 12)")
    maturity_years: float = Field(..., gt=0, description="Years from valuation date to redemption")
    rating: RatingNotch
    sector: AssetSector
    is_government: bool = False
    inflation_linked: bool = False
    assumed_inflation_rate: float = Field(0.0, description="Flat illustrative inflation assumption applied to CF amounts when inflation_linked=True")

    def contractual_cashflows(self, valuation_date: date) -> CashFlowVector:
        step = 1.0 / self.coupon_frequency
        coupon_per_period = self.notional * self.coupon_rate / self.coupon_frequency
        n_periods = round(self.maturity_years / step)
        flows: list[CashFlow] = []
        for i in range(1, n_periods + 1):
            t = i * step
            uplift = (1.0 + self.assumed_inflation_rate) ** t if self.inflation_linked else 1.0
            flows.append(CashFlow(time=t, amount=coupon_per_period * uplift, kind=CashFlowKind.COUPON, inflation_linked=self.inflation_linked))
        if flows:
            last_time = flows[-1].time
            principal_uplift = (1.0 + self.assumed_inflation_rate) ** last_time if self.inflation_linked else 1.0
            flows.append(CashFlow(time=last_time, amount=self.notional * principal_uplift, kind=CashFlowKind.PRINCIPAL, inflation_linked=self.inflation_linked))
        return CashFlowVector(
            id=self.id, currency=self.currency, valuation_date=valuation_date,
            direction="asset_income", flows=tuple(flows),
        )

    def price(self, curve: Curve) -> float:
        """Market value = PV of contractual cash flows on the given (asset-appropriate) curve.
        For golden examples we price directly off the RFR curve, i.e. the asset is
        assumed to trade at a yield equal to RFR (+ any spread already embedded in
        the curve passed in)."""
        return self.contractual_cashflows(curve.valuation_date).pv(curve)


class AmortizingLoan(BaseModel):
    """An amortizing loan: interest + scheduled principal repayment each
    period, no bullet at maturity. Covers infrastructure debt, project
    finance, social housing and CRE loans, and ERM-restructured notes
    (equity release mortgages usually get securitised into MA-eligible
    notes, so we just model the note cash flows here). These are grouped
    under one instrument because they share the same cash flow shape
    (interest plus scheduled principal); what differs between them in
    practice (covenant structure, prepayment terms, seniority) isn't
    modelled yet.

    `amortization_style`:
    - "level_principal": equal principal repaid each period (interest
      shrinks over time as the outstanding balance shrinks).
    - "level_payment": equal total payment each period, mortgage/annuity
      style (interest portion shrinks, principal portion grows) -- the
      typical shape for a restructured ERM note.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    currency: str = Field(..., min_length=3, max_length=3)
    notional: float = Field(..., gt=0)
    coupon_rate: float = Field(..., ge=0, description="Annual interest rate on the outstanding balance")
    coupon_frequency: int = Field(1, description="Payments per year (1, 2, 4, 12)")
    maturity_years: float = Field(..., gt=0, description="Years from valuation date to full repayment")
    amortization_style: str = Field("level_payment", description='"level_principal" or "level_payment"')
    rating: RatingNotch = RatingNotch.BBB2
    sector: AssetSector = AssetSector.OTHER
    is_government: bool = False

    def contractual_cashflows(self, valuation_date: date) -> CashFlowVector:
        step = 1.0 / self.coupon_frequency
        periodic_rate = self.coupon_rate / self.coupon_frequency
        n_periods = round(self.maturity_years / step)

        flows: list[CashFlow] = []
        remaining = self.notional

        if self.amortization_style == "level_principal":
            principal_per_period = self.notional / n_periods
            for i in range(1, n_periods + 1):
                t = i * step
                interest = remaining * periodic_rate
                flows.append(CashFlow(time=t, amount=interest, kind=CashFlowKind.COUPON))
                flows.append(CashFlow(time=t, amount=principal_per_period, kind=CashFlowKind.PRINCIPAL))
                remaining -= principal_per_period
        elif self.amortization_style == "level_payment":
            if periodic_rate > 0:
                payment = self.notional * periodic_rate / (1.0 - (1.0 + periodic_rate) ** (-n_periods))
            else:
                payment = self.notional / n_periods
            for i in range(1, n_periods + 1):
                t = i * step
                interest = remaining * periodic_rate
                principal_payment = payment - interest
                flows.append(CashFlow(time=t, amount=interest, kind=CashFlowKind.COUPON))
                flows.append(CashFlow(time=t, amount=principal_payment, kind=CashFlowKind.PRINCIPAL))
                remaining -= principal_payment
        else:
            raise ValueError(f"unknown amortization_style {self.amortization_style!r}: expected 'level_principal' or 'level_payment'")

        return CashFlowVector(
            id=self.id, currency=self.currency, valuation_date=valuation_date,
            direction="asset_income", flows=tuple(flows),
        )

    def price(self, curve: Curve) -> float:
        return self.contractual_cashflows(curve.valuation_date).pv(curve)


class InterestRateSwap(BaseModel):
    """Vanilla fixed-for-floating interest rate swap, used to extend or
    adjust matching duration where it meets MA asset conditions.

    Unlike Bond/Cash/AmortizingLoan (whose contractual cash flows are fixed
    at construction and independent of any curve), a swap's floating leg is
    inherently curve-dependent: the expected floating cash flow for a
    period is the curve's own forward rate for that period. Rather than
    changing `contractual_cashflows`'s signature for every instrument in
    this module (a change touched by every caller across the codebase),
    this PROJECTS AND FREEZES the expected net cash flows at construction
    time, via `from_curve`, using the curve's implied forward rates. A
    swap built from today's curve does NOT automatically reproject under a
    later stressed curve: rebuild it via `from_curve(..., stressed_curve)`
    for the stressed expected cash flows. This is a documented v1
    limitation, not a silent gap.

    Net settlement amounts CAN be negative (an amount owed TO the
    counterparty in a given period) -- an intentional, narrow exception to
    the rest of this module's positive-magnitude convention (see
    `CashFlow.amount`'s docstring), because a derivative's net cash flow is
    genuinely bidirectional, unlike a bond coupon or a liability benefit.

    NOT YET wired into `ma.hypothecation`'s cash-flow-matching waterfall,
    which assumes non-negative asset cash flows throughout (a negative
    `take` there would incorrectly *increase* remaining liability rather
    than reduce it). Use swaps directly with `ma.engine.compute_ma` (which
    only needs market value, not cash-flow-level bucket matching) until
    hypothecation is extended to handle bidirectional cash flows.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    currency: str = Field(..., min_length=3, max_length=3)
    notional: float = Field(..., gt=0)
    fixed_rate: float = Field(..., ge=0)
    payment_frequency: int = 1
    maturity_years: float = Field(..., gt=0)
    receive_fixed: bool = Field(True, description="True: receive fixed, pay floating (extends duration on the asset side). False: pay fixed, receive floating.")
    rating: RatingNotch = RatingNotch.AAA
    sector: AssetSector = AssetSector.FINANCIAL
    is_government: bool = False
    projected_net_cashflows: tuple[tuple[float, float], ...] = Field((), description="(time, net_amount) pairs frozen at construction by from_curve; net_amount may be negative.")

    @classmethod
    def from_curve(
        cls,
        id: str,
        currency: str,
        notional: float,
        fixed_rate: float,
        maturity_years: float,
        curve: Curve,
        payment_frequency: int = 1,
        receive_fixed: bool = True,
        rating: RatingNotch = RatingNotch.AAA,
        sector: AssetSector = AssetSector.FINANCIAL,
    ) -> "InterestRateSwap":
        step = 1.0 / payment_frequency
        n_periods = round(maturity_years / step)
        sign = 1.0 if receive_fixed else -1.0

        projected: list[tuple[float, float]] = []
        for i in range(1, n_periods + 1):
            t_prev, t = (i - 1) * step, i * step
            df_prev, df = curve.discount_factor(t_prev), curve.discount_factor(t)
            forward_rate = (df_prev / df - 1.0) * payment_frequency
            net = sign * (fixed_rate - forward_rate) * notional / payment_frequency
            projected.append((t, net))

        return cls(
            id=id, currency=currency, notional=notional, fixed_rate=fixed_rate,
            payment_frequency=payment_frequency, maturity_years=maturity_years,
            receive_fixed=receive_fixed, rating=rating, sector=sector,
            projected_net_cashflows=tuple(projected),
        )

    def contractual_cashflows(self, valuation_date: date) -> CashFlowVector:
        flows = tuple(CashFlow(time=t, amount=amt, kind=CashFlowKind.OTHER) for t, amt in self.projected_net_cashflows)
        return CashFlowVector(
            id=self.id, currency=self.currency, valuation_date=valuation_date,
            direction="asset_income", flows=flows,
        )

    def price(self, curve: Curve) -> float:
        return self.contractual_cashflows(curve.valuation_date).pv(curve)


class InflationSwap(BaseModel):
    """Year-on-year inflation swap: one leg pays a fixed rate, the other
    pays realized inflation, used to match inflation-linked liabilities
    without holding an IL gilt directly.

    Same construction pattern as `InterestRateSwap`: expected net cash
    flows are projected and frozen at construction via `from_assumption`,
    here using a flat illustrative inflation assumption (the same
    convention `Bond.assumed_inflation_rate` uses for index-linked gilts --
    no real inflation term structure exists in this engine yet) rather
    than curve-implied forward rates. Every period's flow is tagged
    `inflation_linked=True`, so it feeds PRA Test 2's inflation VaR leg
    exactly like an IL gilt's cash flows do. Carries the same net-
    settlement-can-be-negative exception as `InterestRateSwap`, and the
    same "not wired into hypothecation" scope limit.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    currency: str = Field(..., min_length=3, max_length=3)
    notional: float = Field(..., gt=0)
    fixed_rate: float = Field(..., ge=0)
    payment_frequency: int = 1
    maturity_years: float = Field(..., gt=0)
    receive_inflation: bool = Field(True, description="True: receive inflation-linked growth, pay fixed. False: pay inflation-linked growth, receive fixed.")
    assumed_inflation_rate: float = Field(0.025, description="Flat illustrative inflation assumption, same convention as Bond.assumed_inflation_rate")
    rating: RatingNotch = RatingNotch.AAA
    sector: AssetSector = AssetSector.FINANCIAL
    is_government: bool = False
    projected_net_cashflows: tuple[tuple[float, float], ...] = Field((), description="(time, net_amount) pairs frozen at construction by from_assumption; net_amount may be negative")

    @classmethod
    def from_assumption(
        cls,
        id: str,
        currency: str,
        notional: float,
        fixed_rate: float,
        maturity_years: float,
        payment_frequency: int = 1,
        receive_inflation: bool = True,
        assumed_inflation_rate: float = 0.025,
        rating: RatingNotch = RatingNotch.AAA,
        sector: AssetSector = AssetSector.FINANCIAL,
    ) -> "InflationSwap":
        step = 1.0 / payment_frequency
        n_periods = round(maturity_years / step)
        sign = 1.0 if receive_inflation else -1.0

        projected = tuple(
            (i * step, sign * (assumed_inflation_rate - fixed_rate) * notional / payment_frequency)
            for i in range(1, n_periods + 1)
        )

        return cls(
            id=id, currency=currency, notional=notional, fixed_rate=fixed_rate,
            payment_frequency=payment_frequency, maturity_years=maturity_years,
            receive_inflation=receive_inflation, assumed_inflation_rate=assumed_inflation_rate,
            rating=rating, sector=sector, projected_net_cashflows=projected,
        )

    def contractual_cashflows(self, valuation_date: date) -> CashFlowVector:
        flows = tuple(
            CashFlow(time=t, amount=amt, kind=CashFlowKind.OTHER, inflation_linked=True)
            for t, amt in self.projected_net_cashflows
        )
        return CashFlowVector(
            id=self.id, currency=self.currency, valuation_date=valuation_date,
            direction="asset_income", flows=flows,
        )

    def price(self, curve: Curve) -> float:
        return self.contractual_cashflows(curve.valuation_date).pv(curve)


class ReinsuranceRecoverable(BaseModel):
    """A reinsurance recoverable: the insurer's expected recovery schedule
    from a reinsurance counterparty, ceded against (a portion of) the
    underlying liability cash flows.

    Unlike a bond, there's no coupon/notional structure. The recovery
    schedule is supplied directly as (time, amount) pairs, since it mirrors
    whatever portion of the ceded liability cash flows the treaty covers.

    `is_funded` / `collateral_value`: for funded reinsurance, collateral
    held against the counterparty reduces net counterparty exposure (used
    by the counterparty default SCR sub-module), but is never netted into
    `price()` / market value. Don't treat funded-Re collateral as
    automatically MA-eligible: the asset's own MV (what backs the MA
    calculation) is always the gross expected recovery PV, and collateral
    is a counterparty-risk mitigant tracked separately, not a reduction to
    the recoverable itself.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    currency: str = Field(..., min_length=3, max_length=3)
    expected_recovery_cashflows: tuple[tuple[float, float], ...] = Field(..., min_length=1, description="(time, amount) pairs, the expected recovery schedule")
    rating: RatingNotch = RatingNotch.UNRATED
    sector: AssetSector = AssetSector.FINANCIAL
    is_government: bool = False
    is_funded: bool = False
    collateral_value: float = Field(0.0, ge=0, description="Collateral held against this counterparty exposure; reduces net counterparty exposure only, never market value")

    @property
    def maturity_years(self) -> float:
        return max(t for t, _ in self.expected_recovery_cashflows)

    def contractual_cashflows(self, valuation_date: date) -> CashFlowVector:
        flows = tuple(CashFlow(time=t, amount=amt, kind=CashFlowKind.REINSURANCE) for t, amt in self.expected_recovery_cashflows)
        return CashFlowVector(
            id=self.id, currency=self.currency, valuation_date=valuation_date,
            direction="asset_income", flows=flows,
        )

    def price(self, curve: Curve) -> float:
        return self.contractual_cashflows(curve.valuation_date).pv(curve)


class Cash(BaseModel):
    """Cash / near-cash: immediately available, no cash flow projection
    beyond a single flow at t=0. Treated as FS-nil like gilts (PRA
    convention), and given `maturity_years=0.0` purely so it sorts first in
    the nearest-maturity-first hypothecation waterfall (ma/hypothecation.py)."""

    model_config = ConfigDict(frozen=True)

    id: str
    currency: str = Field(..., min_length=3, max_length=3)
    notional: float = Field(..., gt=0)
    rating: RatingNotch = RatingNotch.AAA
    sector: AssetSector = AssetSector.GOVERNMENT
    is_government: bool = True
    maturity_years: float = 0.0

    def contractual_cashflows(self, valuation_date: date) -> CashFlowVector:
        return CashFlowVector(
            id=self.id, currency=self.currency, valuation_date=valuation_date,
            direction="asset_income",
            flows=(CashFlow(time=0.0, amount=self.notional, kind=CashFlowKind.PRINCIPAL),),
        )

    def price(self, curve: Curve) -> float:
        return self.notional


class FundHolding(BaseModel):
    """A fund holding, modelled on a look-through basis: `constituent_positions`
    is the fund's actual underlying holdings, and SCR sub-modules that need
    look-through treatment (spread, currency, concentration, counterparty)
    expand a `FundHolding` position into those constituents rather than
    treating the fund as one opaque exposure. See
    `scr.look_through.expand_look_through`.

    Not wired into `ma.hypothecation`'s cash-flow-matching waterfall or the
    MA calculation itself, look-through is scoped to SCR for now. A fund's
    aggregate cash flows/price (via `contractual_cashflows`/`price` below)
    are still well-defined for MA/BEL purposes, just not decomposed into
    constituents there.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    currency: str = Field(..., min_length=3, max_length=3)
    constituent_positions: tuple[AssetPosition, ...] = Field(..., min_length=1)
    rating: RatingNotch = RatingNotch.UNRATED
    sector: AssetSector = AssetSector.OTHER
    is_government: bool = False
    maturity_years: float = Field(1.0, description="Placeholder for interfaces expecting a single maturity; a fund has no single maturity")

    def contractual_cashflows(self, valuation_date: date) -> CashFlowVector:
        vectors = [p.cashflows(valuation_date) for p in self.constituent_positions]
        return CashFlowVector.merge(vectors, id=self.id)

    def price(self, curve: Curve) -> float:
        return sum(p.resolved_market_value(curve) for p in self.constituent_positions)


class AssetPosition(BaseModel):
    """A holding of an instrument, with the market value fixed at valuation date
    (either supplied, e.g. from custodian data, or derived via the instrument's
    own `price` method)."""

    model_config = ConfigDict(frozen=True)

    id: str
    instrument: Bond | Cash | AmortizingLoan | InterestRateSwap | InflationSwap | ReinsuranceRecoverable | FundHolding
    units: float = Field(1.0, gt=0, description="Multiple of `instrument.notional` held")
    market_value: float | None = Field(None, description="If None, derived by pricing off the curve supplied at run time")
    is_maia: bool = Field(False, description="Matching Adjustment Investment Accelerator asset -- see ma/maia.py for the 24-month regularisation clock and exposure limit")
    maia_entry_date: date | None = Field(None, description="Date the asset entered the MA portfolio under MAIA; required when is_maia=True")

    @model_validator(mode="after")
    def _maia_entry_date_required(self):
        if self.is_maia and self.maia_entry_date is None:
            raise ValueError("maia_entry_date is required when is_maia=True")
        return self

    def cashflows(self, valuation_date: date) -> CashFlowVector:
        return self.instrument.contractual_cashflows(valuation_date).scale(self.units, id_suffix="")

    def resolved_market_value(self, curve: Curve) -> float:
        if self.market_value is not None:
            return self.market_value * self.units
        return self.instrument.price(curve) * self.units


# FundHolding.constituent_positions forward-references AssetPosition, defined below it in this
# module; rebuild now that both names exist so pydantic can resolve the circular reference.
FundHolding.model_rebuild()
