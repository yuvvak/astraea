"""PRA Test 2 -- 99.5th percentile 1-year VaR (SS7/18 Appendix 1).

Undiversified 1-year 99.5% VaR of the assets required to cover BEL
(Component A+B, market values NOT PD-stripped) for interest-rate, inflation
and currency risk, each assessed separately; each risk's VaR must be <= 1%
of BEL.

v1 methodology: rather than a full stochastic 1-year distribution, apply
prescribed shocks that are *assumed already calibrated* to the 99.5th
percentile (the brief: "Align shock specifications with the firm's matching
methodology; make shock files configurable (PRA/internal calibration)") --
this mirrors how Standard Formula market risk sub-modules work (a named
stress IS the 99.5th-percentile event, not a percentile of a simulated
distribution). The magnitudes below (100bp parallel rate shock, 100bp
inflation shock, 20% FX shock) are ILLUSTRATIVE PLACEHOLDERS, clearly not the
PRA's actual calibration -- swap `ShockSpec` for the firm's real shock file
once available; nothing else in this module needs to change.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from alm.contracts.assets import AssetPosition
from alm.contracts.curves import Curve

TEST2_THRESHOLD = 0.01  # SS7/18 Appendix 1 default: each risk's VaR <= 1% of BEL


class ShockSpec(BaseModel):
    """Illustrative v1 default shock calibration -- see module docstring."""

    model_config = ConfigDict(frozen=True)

    interest_rate_shock: float = 0.01   # +/- 100bp parallel
    inflation_shock: float = 0.01       # +/- 100bp on inflation-linked cash flow amounts
    fx_shock: float = 0.20              # +/- 20% on non-base-currency market value


DEFAULT_SHOCK_SPEC = ShockSpec()


class VaRLegResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    risk: str
    base_value: float
    value_up_shock: float
    value_down_shock: float
    var: float  # max(0, base - worst-case value)
    ratio_to_bel: float
    threshold: float
    passed: bool


class Test2Result(BaseModel):
    model_config = ConfigDict(frozen=True)

    bel: float
    interest_rate: VaRLegResult
    inflation: VaRLegResult
    currency: VaRLegResult

    @property
    def passed(self) -> bool:
        return self.interest_rate.passed and self.inflation.passed and self.currency.passed


def _total_market_value(positions: list[AssetPosition], curve: Curve) -> float:
    return sum(p.resolved_market_value(curve) for p in positions)


def _leg_result(risk: str, base_value: float, value_up: float, value_down: float, bel: float, threshold: float) -> VaRLegResult:
    var = max(0.0, base_value - value_up, base_value - value_down)
    ratio = var / bel if bel > 0 else 0.0
    return VaRLegResult(
        risk=risk, base_value=base_value, value_up_shock=value_up, value_down_shock=value_down,
        var=var, ratio_to_bel=ratio, threshold=threshold, passed=ratio <= threshold,
    )


def run_test2(
    positions: list[AssetPosition],
    curve: Curve,
    bel: float,
    valuation_date: date,
    base_currency: str = "GBP",
    shock: ShockSpec = DEFAULT_SHOCK_SPEC,
    threshold: float = TEST2_THRESHOLD,
) -> Test2Result:
    base_mv = _total_market_value(positions, curve)

    # -- interest rate leg: parallel shift of the whole curve, reprice every position
    mv_up = _total_market_value(positions, curve.shift_parallel(shock.interest_rate_shock))
    mv_down = _total_market_value(positions, curve.shift_parallel(-shock.interest_rate_shock))
    ir_leg = _leg_result("interest_rate", base_mv, mv_up, mv_down, bel, threshold)

    # -- inflation leg: shock the amount of every cash flow flagged inflation-linked;
    #    zero impact (and zero VaR) when the portfolio holds no inflation-linked assets,
    #    which is the correct, hand-checkable answer for the golden gilt/corporate portfolio
    infl_base = 0.0
    infl_up = 0.0
    infl_down = 0.0
    for p in positions:
        cfv = p.cashflows(valuation_date)
        for cf in cfv.flows:
            if not cf.inflation_linked:
                continue
            df = curve.discount_factor(cf.time)
            infl_base += cf.amount * df
            infl_up += cf.amount * (1.0 + shock.inflation_shock) * df
            infl_down += cf.amount * (1.0 - shock.inflation_shock) * df
    infl_leg = _leg_result("inflation", infl_base, infl_up, infl_down, bel, threshold)

    # -- currency leg: shock the market value of every non-base-currency position;
    #    zero for a single-currency GBP portfolio, again correctly so
    fx_base = sum(p.resolved_market_value(curve) for p in positions if p.instrument.currency != base_currency)
    fx_up = fx_base * (1.0 + shock.fx_shock)
    fx_down = fx_base * (1.0 - shock.fx_shock)
    fx_leg = _leg_result("currency", fx_base, fx_up, fx_down, bel, threshold)

    return Test2Result(bel=bel, interest_rate=ir_leg, inflation=infl_leg, currency=fx_leg)
