"""Real PRA Rulebook Standard Formula market-risk calibration data (3D
Market Risk Module), verified against prarulebook.co.uk during this
session: interest rate risk (3D4-3D6), spread risk on bonds/loans (3D17),
and the FX shock (3D32).

Deliberately a standalone, dependency-free module (only `alm.contracts`) so
that BOTH `alm.scr` (the SCR sub-modules) and `alm.tests_pra` (PRA Test 2's
VaR shocks) can reuse the same real calibration without creating a
scr<->stresses<->tests_pra import cycle -- `alm.scr.standard_formula`
depends on `alm.stresses.runner` (for swap reprojection under stress),
which depends on `alm.tests_pra.accumulated_cf_shortfall`; if this
calibration data lived inside `alm.scr` instead, `tests_pra.var_test`
importing it would close that cycle. Keep new shared PRA-calibration data
here, not inside `alm.scr`, for the same reason.
"""

from __future__ import annotations

from alm.contracts.assets import AssetPosition, FundHolding
from alm.contracts.curves import Curve
from alm.contracts.fs import RatingNotch

# ---------------------------------------------------------- 3D5/3D6: interest rate risk ---

# 3D5: rise% by maturity (years). Values in fraction terms (0.70 = 70%).
RISE_TABLE: dict[float, float] = {
    1: 0.70, 2: 0.70, 3: 0.64, 4: 0.59, 5: 0.55, 6: 0.52, 7: 0.49, 8: 0.47,
    9: 0.44, 10: 0.42, 11: 0.39, 12: 0.37, 13: 0.35, 14: 0.34, 15: 0.33,
    16: 0.31, 17: 0.30, 18: 0.29, 19: 0.27, 20: 0.26, 90: 0.20,
}
RISE_FLOOR_PP = 0.01  # 3D5.4: the increase at any maturity must be >= 1 percentage point

# 3D6: fall% by maturity (years).
FALL_TABLE: dict[float, float] = {
    1: 0.75, 2: 0.65, 3: 0.56, 4: 0.50, 5: 0.46, 6: 0.42, 7: 0.39, 8: 0.36,
    9: 0.33, 10: 0.31, 11: 0.30, 12: 0.29, 13: 0.28, 14: 0.28, 15: 0.27,
    16: 0.28, 17: 0.28, 18: 0.28, 19: 0.29, 20: 0.29, 90: 0.20,
}


def _interpolated_shock_pct(table: dict[float, float], maturity: float) -> float:
    terms = sorted(table.keys())
    if maturity <= terms[0]:
        return table[terms[0]]
    if maturity >= terms[-1]:
        return table[terms[-1]]
    lo = max(t for t in terms if t <= maturity)
    hi = min(t for t in terms if t >= maturity)
    if lo == hi:
        return table[lo]
    frac = (maturity - lo) / (hi - lo)
    return table[lo] + frac * (table[hi] - table[lo])


def shocked_rate_up(base_rate: float, maturity: float) -> float:
    """3D5: the shocked rate at `maturity`, given the current basic RFR
    `base_rate` at that same maturity."""
    increase = base_rate * _interpolated_shock_pct(RISE_TABLE, maturity)
    increase = max(increase, RISE_FLOOR_PP)
    return base_rate + increase


def shocked_rate_down(base_rate: float, maturity: float) -> float:
    """3D6: the shocked rate at `maturity`. Nil decrease when the basic RFR
    at that maturity is already negative (3D6.5)."""
    if base_rate < 0:
        return base_rate
    decrease = base_rate * _interpolated_shock_pct(FALL_TABLE, maturity)
    return base_rate - decrease


def shock_curve_up(curve: Curve) -> Curve:
    """Return a new curve with every published term point individually
    shocked per 3D5 (NOT a parallel shift -- each maturity gets its own
    interpolated rise%)."""
    shocked_rates = tuple(shocked_rate_up(r, t) for t, r in zip(curve.terms, curve.rates))
    return Curve(
        currency=curve.currency, valuation_date=curve.valuation_date,
        terms=curve.terms, rates=shocked_rates, name=f"{curve.name}+3D5_rise",
    )


def shock_curve_down(curve: Curve) -> Curve:
    """Return a new curve with every published term point individually
    shocked per 3D6."""
    shocked_rates = tuple(shocked_rate_down(r, t) for t, r in zip(curve.terms, curve.rates))
    return Curve(
        currency=curve.currency, valuation_date=curve.valuation_date,
        terms=curve.terms, rates=shocked_rates, name=f"{curve.name}-3D6_fall",
    )


# --------------------------------------------------------------- 3D32: currency risk ---

CURRENCY_SHOCK = 0.25  # 3D32.4/3D32.5: real PRA Rulebook FX shock (verified against prarulebook.co.uk)


# ------------------------------------------------------ 3D17: spread risk on bonds/loans ---

# Real PRA Rulebook 3D17 spread risk stress table (bonds/loans WITH an
# external credit assessment), verified against prarulebook.co.uk this
# session; the CQS0=0.9%-for-duration<=5 anchor was independently
# cross-checked against a second source after the first fetch's rendering
# put the CQS/value columns one out of step. stress_i = a_i + b_i *
# (duration - band_start), bands keyed by their start; duration is floored
# at 1 year (3D17.2) before lookup. CQS5 and CQS6 share one table (3D17.3).
SPREAD_STRESS_TABLE: dict[int, tuple[tuple[float, float, float], ...]] = {
    0: ((0.0, 0.000, 0.009), (5.0, 0.045, 0.005), (10.0, 0.070, 0.005), (15.0, 0.095, 0.005), (20.0, 0.120, 0.005)),
    1: ((0.0, 0.000, 0.011), (5.0, 0.055, 0.006), (10.0, 0.085, 0.005), (15.0, 0.110, 0.005), (20.0, 0.135, 0.005)),
    2: ((0.0, 0.000, 0.014), (5.0, 0.070, 0.007), (10.0, 0.105, 0.005), (15.0, 0.130, 0.005), (20.0, 0.155, 0.005)),
    3: ((0.0, 0.000, 0.025), (5.0, 0.125, 0.015), (10.0, 0.200, 0.010), (15.0, 0.250, 0.010), (20.0, 0.300, 0.005)),
    4: ((0.0, 0.000, 0.045), (5.0, 0.225, 0.025), (10.0, 0.350, 0.018), (15.0, 0.440, 0.005), (20.0, 0.466, 0.005)),
    5: ((0.0, 0.000, 0.075), (5.0, 0.375, 0.042), (10.0, 0.585, 0.005), (15.0, 0.610, 0.005), (20.0, 0.635, 0.005)),
}
SPREAD_STRESS_TABLE[6] = SPREAD_STRESS_TABLE[5]  # 3D17.3: CQS5 and CQS6 share the same stress table

# 3D17.4: bonds/loans WITHOUT a credit assessment and without eligible collateral.
UNASSESSED_SPREAD_STRESS_TABLE: tuple[tuple[float, float, float], ...] = (
    (0.0, 0.000, 0.030), (5.0, 0.150, 0.017), (10.0, 0.235, 0.012), (20.0, 0.355, 0.005),
)

RATING_TO_CQS: dict[RatingNotch, int] = {
    RatingNotch.AAA: 0,
    RatingNotch.AA1: 1, RatingNotch.AA2: 1, RatingNotch.AA3: 1,
    RatingNotch.A1: 2, RatingNotch.A2: 2, RatingNotch.A3: 2,
    RatingNotch.BBB1: 3, RatingNotch.BBB2: 3, RatingNotch.BBB3: 3,
    RatingNotch.BB1: 4, RatingNotch.BB2: 4, RatingNotch.BB3: 4,
    RatingNotch.B_AND_BELOW: 5,
    # UNRATED is NOT mapped here -- it uses UNASSESSED_SPREAD_STRESS_TABLE (3D17.4), not a CQS lookup.
}


def _piecewise_stress(table: tuple[tuple[float, float, float], ...], duration: float, cap_at_one: bool = True) -> float:
    duration = max(duration, 1.0)  # 3D17.2 floor
    band_start, a_i, b_i = table[0]
    for start, a, b in table:
        if duration >= start:
            band_start, a_i, b_i = start, a, b
    stress = a_i + b_i * (duration - band_start)
    if cap_at_one and band_start == table[-1][0]:
        stress = min(stress, 1.0)
    return stress


def spread_stress_pct(rating: RatingNotch, duration: float) -> float:
    """3D17: the stress_i fraction (e.g. 0.05 = 5%) for a bond/loan of this
    rating and (already-floored) modified duration."""
    if rating not in RATING_TO_CQS:
        return _piecewise_stress(UNASSESSED_SPREAD_STRESS_TABLE, duration)
    return _piecewise_stress(SPREAD_STRESS_TABLE[RATING_TO_CQS[rating]], duration)


def macaulay_duration(position: AssetPosition, curve: Curve) -> float:
    """PV-weighted-average-time duration of the position's own contractual
    cash flows on `curve`. The Delegated Regulation/PRA Rulebook doesn't
    mandate one specific duration methodology for 3D17's `dur_i` input --
    this is a documented v1 choice, consistent with this project's existing
    "explicit judgment call, cited" convention (see e.g. Bond's docstring).

    A `FundHolding` has no single cash-flow shape of its own once its
    constituents span more than one currency (`CashFlowVector.merge`
    correctly refuses to combine those into one vector) -- so a fund's
    duration is instead the market-value-weighted average of its own
    constituents' durations, the standard portfolio-duration convention."""
    instrument = position.instrument
    if isinstance(instrument, FundHolding):
        total_mv = sum(cp.resolved_market_value(curve) for cp in instrument.constituent_positions)
        if total_mv <= 0:
            return 1.0
        return sum(
            macaulay_duration(cp, curve) * cp.resolved_market_value(curve)
            for cp in instrument.constituent_positions
        ) / total_mv
    cfs = instrument.contractual_cashflows(curve.valuation_date)
    weighted_time = 0.0
    total_pv = 0.0
    for cf in cfs.flows:
        pv = cf.amount * curve.discount_factor(cf.time)
        weighted_time += cf.time * pv
        total_pv += pv
    if total_pv <= 0:
        return 1.0  # degenerate/zero-PV position -- 3D17.2's 1-year floor applies regardless
    return weighted_time / total_pv
