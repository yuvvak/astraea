"""Standard Formula SCR for the MA portfolio (deliverable 8: "SF SCR
skeleton for the MA portfolio including spread + longevity + MA-in-stress").

Sub-modules: spread, currency, interest rate and concentration (market
risk), longevity (life underwriting risk), counterparty default, and
operational risk, aggregated as:

    market  = corr({spread, currency, interest_rate, concentration})
    BSCR    = corr({market, life, counterparty})
    SCR     = max(0, BSCR + operational - LAC_DT)

using the generic correlation aggregator in `scr/correlation.py`, treated as
a notional standalone calculation for the MA portfolio (SF Part 9: "no
diversification between MAP, other RFFs and the remaining part" -- there is
only one portfolio in this v1, so that constraint is trivially satisfied;
the aggregation boundary is fixed here so a second MAP/RFF can be added
later without diversifying across the boundary by accident).

Every stress recomputes MA in full (via `stresses.run_stress`, or -- for
longevity specifically -- the fixed-MA-rate mechanism in
`compute_longevity_scr` below) rather than freezing the base MA and only
shocking BEL (project brief: "Recalculate MA inside each SF scenario (do
not freeze base MA)").

`compute_full_standard_formula_scr` expands any `FundHolding` position into
its constituents before every sub-module below runs (`look_through.py`),
so a fund's underlying spread/currency/concentration/counterparty exposure
is priced at the constituent level, not hidden behind one opaque fund MV.

The counterparty default sub-module prices cash/deposit exposure,
in-the-money derivative (swap) exposure, and net (collateral-adjusted)
reinsurance recoverable exposure -- an out-of-the-money swap, or a fully
collateralized reinsurance position, correctly contributes nothing.

Spread risk (3D17), currency risk (3D32), interest rate risk (3D4-3D6),
concentration risk (3D26-3D31), operational risk (Article 204) and every
correlation parameter used (market sub-module and top-level BSCR) are now
the REAL PRA Rulebook / Solvency II Delegated Regulation Annex IV figures
-- verified against prarulebook.co.uk and cross-checked against
independent sources; see each constant's own comment (in this module or
`alm/pra_calibration.py`) for the rule citation. Counterparty default
remains an ILLUSTRATIVE PLACEHOLDER: the real Article 199 Type 1/Type 2
formula (loss-given-default, probability of default by rating, and a
piecewise variance-of-losses aggregation across counterparties) is
substantially more involved than a table lookup, and was deliberately left
unimplemented this session rather than risk a subtly wrong regulatory
capital formula -- see `compute_counterparty_default_scr`'s docstring.
A later research pass (2026-09-10) confirmed the Article 199 PD-by-CQS
table (CQS0 0.002% up to CQS5/6 4.2%) and the Type 1 LGD formulas for
reinsurance/derivative/mortgage exposures against primary legislative
text, but could NOT confirm the Type 1 cross-counterparty variance
aggregation formula or the Type 2 flat-factor article against primary
text -- only against secondary sources reproducing it without citing the
underlying article. That gap is exactly the "piecewise variance-of-losses
aggregation" this docstring already flagged as the hard part; implementing
against unconfirmed pieces would trade an honest placeholder for a formula
that looks real but isn't fully verified, so this sub-module is still
deliberately left as-is.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from alm.contracts.assets import AssetPosition, Cash, InterestRateSwap, ReinsuranceRecoverable
from alm.contracts.cashflows import CashFlowVector
from alm.contracts.curves import Curve
from alm.contracts.fs import FSTable, RatingNotch
from alm.ma.engine import MAResult, compute_ma
from alm.ma.fs_rate import fs_rate_for_assets
from alm.pra_calibration import (
    BSCR_CORRELATION,
    CURRENCY_SHOCK,
    MARKET_RISK_CORRELATION_IR_FALL_BINDING,
    MARKET_RISK_CORRELATION_IR_RISE_BINDING,
    OPERATIONAL_BSCR_CAP_FRACTION,
    OPERATIONAL_TP_FACTOR,
    RATING_TO_CQS,
    SPREAD_STRESS_TABLE,
    UNASSESSED_SPREAD_STRESS_TABLE,
    concentration_threshold_and_factor,
    macaulay_duration,
    shock_curve_down,
    shock_curve_up,
    spread_stress_pct,
)
from alm.stresses.runner import reproject_swaps

from .correlation import aggregate_via_correlation
from .look_through import expand_look_through

LONGEVITY_SHOCK_BEL_UPLIFT = 0.20      # SF longevity sub-module, approximated as a permanent BEL uplift
COUNTERPARTY_CASH_FACTOR = 0.15        # illustrative flat charge on cash/deposit counterparty exposure

# Illustrative placeholder charge on in-the-money derivative (swap) counterparty exposure, by counterparty
# rating -- a much lower scale than the cash factor above, reflecting that cleared/collateralized derivative
# counterparties are typically higher quality than an uncollateralized deposit counterparty; not the real
# EIOPA Type 1 exposure formula (which uses LGD, PD by rating, and a variance-based aggregation for a small
# number of large independent exposures).
COUNTERPARTY_DERIVATIVE_FACTORS: dict[RatingNotch, float] = {
    RatingNotch.AAA: 0.005, RatingNotch.AA1: 0.005, RatingNotch.AA2: 0.005, RatingNotch.AA3: 0.005,
    RatingNotch.A1: 0.01, RatingNotch.A2: 0.01, RatingNotch.A3: 0.01,
    RatingNotch.BBB1: 0.02, RatingNotch.BBB2: 0.02, RatingNotch.BBB3: 0.02,
    RatingNotch.BB1: 0.04, RatingNotch.BB2: 0.04, RatingNotch.BB3: 0.04,
    RatingNotch.B_AND_BELOW: 0.08, RatingNotch.UNRATED: 0.08,
}

# Illustrative placeholder charge on NET (collateral-adjusted) reinsurance counterparty exposure, by
# counterparty rating -- a coarser scale than the derivative table above, reflecting reinsurance
# counterparties' typically longer-tenor, less-frequently-collateralized exposure profile; not the real
# EIOPA Type 1 formula (see COUNTERPARTY_DERIVATIVE_FACTORS comment -- the same caveat applies here).
COUNTERPARTY_REINSURANCE_FACTORS: dict[RatingNotch, float] = {
    RatingNotch.AAA: 0.01, RatingNotch.AA1: 0.01, RatingNotch.AA2: 0.01, RatingNotch.AA3: 0.01,
    RatingNotch.A1: 0.02, RatingNotch.A2: 0.02, RatingNotch.A3: 0.02,
    RatingNotch.BBB1: 0.04, RatingNotch.BBB2: 0.04, RatingNotch.BBB3: 0.04,
    RatingNotch.BB1: 0.08, RatingNotch.BB2: 0.08, RatingNotch.BB3: 0.08,
    RatingNotch.B_AND_BELOW: 0.15, RatingNotch.UNRATED: 0.15,
}

MARKET_LIFE_CORRELATION = 0.25  # Solvency II Annex IV correlation parameter, market <-> life SCR (kept for backward compat)

# Real Annex IV market-risk correlation matrix (see `alm.pra_calibration` for the citation and
# the IR-rise/IR-fall variants); `MARKET_CORRELATION` here defaults to the rise-binding variant
# for any caller that doesn't need the conditional behaviour `compute_full_standard_formula_scr`
# applies automatically.
MARKET_CORRELATION: dict[tuple[str, str], float] = MARKET_RISK_CORRELATION_IR_RISE_BINDING
TOP_LEVEL_CORRELATION: dict[tuple[str, str], float] = BSCR_CORRELATION


class SpreadScrResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    scr_spread: float
    contributions_by_position: dict[str, float]


class InterestRateScrResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    scr_interest_rate: float  # higher of the 3D5 (rise) / 3D6 (fall) own-funds loss, floored at 0
    own_funds_base: float
    own_funds_up: float
    own_funds_down: float
    binding_direction: str  # "rise" or "fall" -- whichever shock produced the larger loss; drives the Annex IV IR-vs-spread correlation choice


class LongevityScrResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    scr_longevity: float  # loss in own funds under the shock, i.e. base own_funds - stressed own_funds, floored at 0
    base_ma: MAResult
    own_funds_base: float
    own_funds_stressed: float
    bel_with_ma_stressed: float


class CurrencyScrResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    scr_currency: float
    base_currency: str
    total_fx_exposure: float
    exposure_by_position: dict[str, float]


class ConcentrationScrResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    scr_concentration: float
    total_assets: float
    threshold_pct: dict[str, float]  # by position id -- now CQS-banded (3D29), not a single flat rate
    charge_by_position: dict[str, float]
    excess_share_by_position: dict[str, float]


class CounterpartyDefaultScrResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    scr_counterparty: float
    cash_exposure: float
    cash_charge: float
    derivative_exposure: float  # sum of positive-MV swap positions only
    derivative_charge: float
    derivative_charge_by_position: dict[str, float]
    reinsurance_exposure: float  # sum of (gross MV - collateral), floored at 0 per position
    reinsurance_charge: float
    reinsurance_charge_by_position: dict[str, float]


class OperationalScrResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    scr_operational: float
    op_provisions: float  # 0.45% x life TP net of reinsurance excl. risk margin
    bscr: float
    bscr_cap: float  # 30% x BSCR
    capped: bool  # True if op_provisions exceeded the 30%xBSCR cap


class MAPStandardFormulaSCR(BaseModel):
    """Spread + longevity only -- the original v1 skeleton. Kept unchanged
    (including its exact aggregation result) for backward compatibility;
    see `FullStandardFormulaSCR` for the complete sub-module set."""

    model_config = ConfigDict(frozen=True)

    spread: SpreadScrResult
    longevity: LongevityScrResult
    correlation_market_life: float
    scr_total: float


class FullStandardFormulaSCR(BaseModel):
    model_config = ConfigDict(frozen=True)

    spread: SpreadScrResult
    currency: CurrencyScrResult
    concentration: ConcentrationScrResult
    interest_rate: InterestRateScrResult
    longevity: LongevityScrResult
    counterparty: CounterpartyDefaultScrResult
    operational: OperationalScrResult
    market_scr: float
    bscr: float
    lac_dt: float
    scr_total: float


def compute_spread_scr(
    positions: list[AssetPosition],
    curve: Curve,
) -> SpreadScrResult:
    """3D17: stress_i (by CQS + modified duration, or the unassessed-bond
    formula for UNRATED) times market value, summed across every non-
    government position."""
    contributions: dict[str, float] = {}
    for p in positions:
        bond = p.instrument
        if getattr(bond, "is_government", False):
            contributions[p.id] = 0.0
            continue
        rating = getattr(bond, "rating", RatingNotch.UNRATED)
        duration = macaulay_duration(p, curve)
        factor = spread_stress_pct(rating, duration)
        contributions[p.id] = factor * p.resolved_market_value(curve)
    return SpreadScrResult(scr_spread=sum(contributions.values()), contributions_by_position=contributions)


def compute_interest_rate_scr(
    liability_cfs: CashFlowVector,
    positions: list[AssetPosition],
    curve: Curve,
    fs_table: FSTable,
    valuation_date: date,
) -> InterestRateScrResult:
    """3D4-3D6: the higher of the 3D5 (rise) / 3D6 (fall) own-funds loss.
    A genuine market stress -- unlike `compute_longevity_scr`'s documented
    fixed-MA-rate exception for pure life risk, this follows the module's
    general "recalculate MA inside each SF scenario" convention (see module
    docstring): assets are repriced and MA/BEL are fully re-derived on each
    shocked curve. Swap positions are reprojected against the shocked curve
    first via `stresses.runner.reproject_swaps`, so a floating leg's
    expected cash flows reflect the shocked forward rates rather than the
    base curve's frozen ones (the same gotcha `stresses.runner.run_stress`
    already handles for market/ORSA scenarios)."""
    base_mv = sum(p.resolved_market_value(curve) for p in positions)
    base_fs_rate = fs_rate_for_assets(positions, fs_table, valuation_date, curve)
    base_ma = compute_ma(liability_cfs, base_mv, base_fs_rate, curve)
    own_funds_base = base_mv - base_ma.bel_with_ma

    def _leg(shocked_curve: Curve) -> float:
        shocked_positions = reproject_swaps(positions, shocked_curve)
        mv = sum(p.resolved_market_value(shocked_curve) for p in shocked_positions)
        fs_rate = fs_rate_for_assets(shocked_positions, fs_table, valuation_date, shocked_curve)
        ma = compute_ma(liability_cfs, mv, fs_rate, shocked_curve)
        return mv - ma.bel_with_ma

    own_funds_up = _leg(shock_curve_up(curve))
    own_funds_down = _leg(shock_curve_down(curve))
    loss_up = own_funds_base - own_funds_up
    loss_down = own_funds_base - own_funds_down
    loss = max(0.0, loss_up, loss_down)
    binding_direction = "rise" if loss_up >= loss_down else "fall"

    return InterestRateScrResult(
        scr_interest_rate=loss, own_funds_base=own_funds_base,
        own_funds_up=own_funds_up, own_funds_down=own_funds_down,
        binding_direction=binding_direction,
    )


def compute_currency_scr(
    positions: list[AssetPosition],
    curve: Curve,
    base_currency: str = "GBP",
    fx_shock: float = CURRENCY_SHOCK,
) -> CurrencyScrResult:
    exposure_by_position: dict[str, float] = {}
    for p in positions:
        if p.instrument.currency != base_currency:
            exposure_by_position[p.id] = p.resolved_market_value(curve)
    total = sum(exposure_by_position.values())
    return CurrencyScrResult(
        scr_currency=fx_shock * total, base_currency=base_currency,
        total_fx_exposure=total, exposure_by_position=exposure_by_position,
    )


def compute_concentration_scr(positions: list[AssetPosition], curve: Curve) -> ConcentrationScrResult:
    """3D26-3D31: single-name concentration charge, one 'name' per position
    (v1 simplification: no issuer field yet to group positions sharing an
    issuer -- see contracts/assets.py). Government positions are excluded
    entirely (3D26.4: exposures with g_i = 0 are excluded from the single-
    name exposure calculation), matching this codebase's existing gilt
    convention. Every other position's own threshold (CT_i) and risk
    factor (g_i) now come from the real CQS-banded 3D29/3D30 tables (was a
    flat 3%/12% placeholder); XS_i = max(0, MV_i - CT_i * total assets),
    Conc_i = g_i * XS_i, aggregated by sum-of-squares (undiversified
    single-name risk) per 3D27.
    """
    mv_by_position = {p.id: p.resolved_market_value(curve) for p in positions}
    total_assets = sum(mv_by_position.values())

    charge_by_position: dict[str, float] = {}
    excess_share_by_position: dict[str, float] = {}
    threshold_by_position: dict[str, float] = {}
    for p in positions:
        pid = p.id
        mv = mv_by_position[pid]
        if getattr(p.instrument, "is_government", False):
            excess_share_by_position[pid] = 0.0
            charge_by_position[pid] = 0.0
            threshold_by_position[pid] = 0.0
            continue
        rating = getattr(p.instrument, "rating", RatingNotch.UNRATED)
        threshold_pct, risk_factor = concentration_threshold_and_factor(rating)
        threshold_by_position[pid] = threshold_pct
        share = mv / total_assets if total_assets > 0 else 0.0
        excess_share = max(0.0, share - threshold_pct)
        excess_share_by_position[pid] = excess_share
        charge_by_position[pid] = excess_share * total_assets * risk_factor

    scr_concentration = sum(c ** 2 for c in charge_by_position.values()) ** 0.5

    return ConcentrationScrResult(
        scr_concentration=scr_concentration, total_assets=total_assets,
        threshold_pct=threshold_by_position,
        charge_by_position=charge_by_position, excess_share_by_position=excess_share_by_position,
    )


def compute_counterparty_default_scr(
    positions: list[AssetPosition],
    curve: Curve,
    cash_charge_factor: float = COUNTERPARTY_CASH_FACTOR,
    derivative_charge_factors: dict[RatingNotch, float] = COUNTERPARTY_DERIVATIVE_FACTORS,
    reinsurance_charge_factors: dict[RatingNotch, float] = COUNTERPARTY_REINSURANCE_FACTORS,
) -> CounterpartyDefaultScrResult:
    cash_exposure = sum(p.resolved_market_value(curve) for p in positions if isinstance(p.instrument, Cash))
    cash_charge = cash_charge_factor * cash_exposure

    derivative_exposure = 0.0
    derivative_charge_by_position: dict[str, float] = {}
    for p in positions:
        if not isinstance(p.instrument, InterestRateSwap):
            continue
        mv = p.resolved_market_value(curve)
        if mv <= 0:
            continue  # out-of-the-money: no counterparty credit exposure TO us
        derivative_exposure += mv
        factor = derivative_charge_factors.get(p.instrument.rating, derivative_charge_factors[RatingNotch.UNRATED])
        derivative_charge_by_position[p.id] = factor * mv
    derivative_charge = sum(derivative_charge_by_position.values())

    reinsurance_exposure = 0.0
    reinsurance_charge_by_position: dict[str, float] = {}
    for p in positions:
        if not isinstance(p.instrument, ReinsuranceRecoverable):
            continue
        gross_mv = p.resolved_market_value(curve)
        # collateral reduces NET COUNTERPARTY EXPOSURE only -- never the asset's own market
        # value (see ReinsuranceRecoverable docstring: "do not treat FundedRe collateral as
        # automatically MA-eligible"). gross_mv itself is untouched everywhere else this
        # position is used (MA calc, spread SCR, etc); only this counterparty charge nets
        # off collateral.
        net_exposure = max(0.0, gross_mv - p.instrument.collateral_value)
        if net_exposure <= 0:
            continue
        reinsurance_exposure += net_exposure
        factor = reinsurance_charge_factors.get(p.instrument.rating, reinsurance_charge_factors[RatingNotch.UNRATED])
        reinsurance_charge_by_position[p.id] = factor * net_exposure
    reinsurance_charge = sum(reinsurance_charge_by_position.values())

    return CounterpartyDefaultScrResult(
        scr_counterparty=cash_charge + derivative_charge + reinsurance_charge,
        cash_exposure=cash_exposure, cash_charge=cash_charge,
        derivative_exposure=derivative_exposure, derivative_charge=derivative_charge,
        derivative_charge_by_position=derivative_charge_by_position,
        reinsurance_exposure=reinsurance_exposure, reinsurance_charge=reinsurance_charge,
        reinsurance_charge_by_position=reinsurance_charge_by_position,
    )


def compute_operational_scr(
    bel_net_of_reinsurance: float,
    bscr: float,
    tp_factor: float = OPERATIONAL_TP_FACTOR,
    bscr_cap_fraction: float = OPERATIONAL_BSCR_CAP_FRACTION,
) -> OperationalScrResult:
    """Article 204: SCR_op = min(0.30 x BSCR, Op) + 0.25 x Exp_ul. This
    engine only models Op_provisions (`tp_factor` x life TP net of
    reinsurance, excluding risk margin -- `bel_net_of_reinsurance` here is
    the caller's own basic-RFR BEL, the closest available proxy since this
    engine doesn't separately track a risk-margin-inclusive TP figure at
    this call site); Op_premiums isn't modelled (see module docstring:
    no material ongoing premium on a back-book annuity portfolio), and
    Exp_ul is 0 (no unit-linked business)."""
    op_provisions = tp_factor * bel_net_of_reinsurance
    bscr_cap = bscr_cap_fraction * bscr
    capped = op_provisions > bscr_cap
    scr_operational = min(op_provisions, bscr_cap)
    return OperationalScrResult(
        scr_operational=scr_operational, op_provisions=op_provisions,
        bscr=bscr, bscr_cap=bscr_cap, capped=capped,
    )


def compute_longevity_scr(
    liability_cfs: CashFlowVector,
    positions: list[AssetPosition],
    curve: Curve,
    fs_table: FSTable,
    valuation_date: date,
    shock: float = LONGEVITY_SHOCK_BEL_UPLIFT,
) -> LongevityScrResult:
    """A pure life-underwriting stress does not change the market value of
    assets already held, nor the credit spread the market demands for them
    -- so unlike `stresses.run_stress` (which fully re-hypothecates and
    re-derives the MA rate from scratch, appropriate for a genuine market/
    ORSA scenario), this holds the BASE CASE's MA RATE fixed and only
    re-discounts the shocked (bigger) liability cash flows at that same
    rate. This deliberately avoids a real pathology in the plain two-AER
    re-solve: because r1 is defined purely as "the rate that reproduces a
    *fixed* target market value" for *whatever* liability cash flow shape is
    handed to it, re-deriving r1 against uniformly-scaled-up liability cash
    flows against the SAME fixed MV causes MA to inflate almost exactly
    enough to offset the BEL increase -- which would make a longevity
    stress show near-zero or even negative SCR, hiding a real risk. Holding
    the asset-side MA rate fixed and shocking only the liability side is the
    standard convention (life risk changes reserves via cash flow changes,
    not by retroactively re-pricing the asset portfolio's credit spread).
    """
    market_value = sum(p.resolved_market_value(curve) for p in positions)
    fs_rate = fs_rate_for_assets(positions, fs_table, valuation_date, curve)
    base_ma = compute_ma(liability_cfs, market_value, fs_rate, curve)

    stressed_liability_cfs = liability_cfs.scale(1.0 + shock, id_suffix="_longevity_shock")
    ma_curve = curve.shift_parallel(base_ma.ma_rate)
    bel_with_ma_stressed = stressed_liability_cfs.pv(ma_curve)

    own_funds_base = market_value - base_ma.bel_with_ma
    own_funds_stressed = market_value - bel_with_ma_stressed
    loss = max(0.0, own_funds_base - own_funds_stressed)

    return LongevityScrResult(
        scr_longevity=loss, base_ma=base_ma,
        own_funds_base=own_funds_base, own_funds_stressed=own_funds_stressed,
        bel_with_ma_stressed=bel_with_ma_stressed,
    )


def compute_map_standard_formula_scr(
    liability_cfs: CashFlowVector,
    positions: list[AssetPosition],
    curve: Curve,
    fs_table: FSTable,
    valuation_date: date,
    longevity_shock: float = LONGEVITY_SHOCK_BEL_UPLIFT,
    correlation: float = MARKET_LIFE_CORRELATION,
) -> MAPStandardFormulaSCR:
    """Spread + longevity only. Preserved unchanged for backward
    compatibility; see `compute_full_standard_formula_scr` for the complete
    sub-module set (currency, concentration, interest rate, counterparty,
    operational)."""
    spread = compute_spread_scr(positions, curve)
    longevity = compute_longevity_scr(liability_cfs, positions, curve, fs_table, valuation_date, longevity_shock)

    scr_total = aggregate_via_correlation(
        {"spread": spread.scr_spread, "longevity": longevity.scr_longevity},
        {("spread", "longevity"): correlation},
    )

    return MAPStandardFormulaSCR(
        spread=spread, longevity=longevity, correlation_market_life=correlation, scr_total=scr_total,
    )


def compute_full_standard_formula_scr(
    liability_cfs: CashFlowVector,
    positions: list[AssetPosition],
    curve: Curve,
    fs_table: FSTable,
    valuation_date: date,
    base_currency: str = "GBP",
    longevity_shock: float = LONGEVITY_SHOCK_BEL_UPLIFT,
    fx_shock: float = CURRENCY_SHOCK,
    counterparty_cash_factor: float = COUNTERPARTY_CASH_FACTOR,
    top_level_correlation: dict[tuple[str, str], float] = TOP_LEVEL_CORRELATION,
    lac_dt: float = 0.0,
) -> FullStandardFormulaSCR:
    positions = expand_look_through(positions)

    spread = compute_spread_scr(positions, curve)
    currency = compute_currency_scr(positions, curve, base_currency, fx_shock)
    concentration = compute_concentration_scr(positions, curve)
    interest_rate = compute_interest_rate_scr(liability_cfs, positions, curve, fs_table, valuation_date)
    longevity = compute_longevity_scr(liability_cfs, positions, curve, fs_table, valuation_date, longevity_shock)
    counterparty = compute_counterparty_default_scr(positions, curve, counterparty_cash_factor)

    # Annex IV: the interest-rate-vs-spread correlation depends on which interest rate shock
    # (rise/fall) was actually binding for THIS portfolio -- see InterestRateScrResult.binding_direction.
    market_correlation = (
        MARKET_RISK_CORRELATION_IR_RISE_BINDING if interest_rate.binding_direction == "rise"
        else MARKET_RISK_CORRELATION_IR_FALL_BINDING
    )
    market_scr = aggregate_via_correlation(
        {
            "spread": spread.scr_spread, "currency": currency.scr_currency,
            "concentration": concentration.scr_concentration, "interest_rate": interest_rate.scr_interest_rate,
        },
        market_correlation,
    )
    bscr = aggregate_via_correlation(
        {"market": market_scr, "life": longevity.scr_longevity, "counterparty": counterparty.scr_counterparty},
        top_level_correlation,
    )
    operational = compute_operational_scr(longevity.base_ma.bel_basic_rfr, bscr)
    scr_total = max(0.0, bscr + operational.scr_operational - lac_dt)

    return FullStandardFormulaSCR(
        spread=spread, currency=currency, concentration=concentration, interest_rate=interest_rate,
        longevity=longevity, counterparty=counterparty, operational=operational,
        market_scr=market_scr, bscr=bscr, lac_dt=lac_dt, scr_total=scr_total,
    )
