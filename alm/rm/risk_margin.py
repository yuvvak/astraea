"""Risk Margin: Solvency UK reformed cost-of-capital method with life
tapering.

  RM = CoC * sum_{t=0}^{n} taper(t) * SCR(t) / (1 + r_basic(t+1))^(t+1)
  taper(t) = max(lambda^t, floor)

CoC = 4%, life taper lambda = 0.9, floor = 0.25. SCR(t) is the capital for
non-hedgeable risks of the reference undertaking after transfer of the MA
portfolio (longevity, expense, residual operational, non-hedgeable credit
on FS, etc.). This module doesn't compute SCR(t) itself (see `alm.scr`
for the Standard Formula base-date SCR), it either takes a full
user-supplied runoff path, or approximates one.

Discounting is on the basic RFR curve only, no MA, no VA: Risk Margin
sits outside the MA discounting of BEL.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from alm.contracts.cashflows import CashFlowVector
from alm.contracts.curves import Curve

RM_COST_OF_CAPITAL = 0.04    # Solvency UK reform cost-of-capital rate
RM_TAPER_LAMBDA = 0.90       # life taper lambda
RM_TAPER_FLOOR = 0.25        # taper floor


def taper_factor(t: int, lam: float = RM_TAPER_LAMBDA, floor: float = RM_TAPER_FLOOR) -> float:
    return max(lam ** t, floor)


class RiskMarginResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    risk_margin: float
    coc: float
    lam: float
    floor: float
    scr_path: dict[int, float]
    taper_factors: dict[int, float]
    discounted_terms: dict[int, float]  # coc * taper(t) * SCR(t) * discount_factor(t+1), the summand at each t


def compute_risk_margin(
    scr_path: dict[int, float],
    basic_rfr_curve: Curve,
    coc: float = RM_COST_OF_CAPITAL,
    lam: float = RM_TAPER_LAMBDA,
    floor: float = RM_TAPER_FLOOR,
) -> RiskMarginResult:
    taper_factors = {t: taper_factor(t, lam, floor) for t in scr_path}
    discounted_terms = {
        t: coc * taper_factors[t] * scr_path[t] * basic_rfr_curve.discount_factor(t + 1)
        for t in scr_path
    }
    risk_margin = sum(discounted_terms.values())
    return RiskMarginResult(
        risk_margin=risk_margin, coc=coc, lam=lam, floor=floor,
        scr_path=dict(scr_path), taper_factors=taper_factors, discounted_terms=discounted_terms,
    )


def approximate_scr_runoff(
    scr_0: float,
    liability_cfs: CashFlowVector,
    curve: Curve,
    n_years: int,
) -> dict[int, float]:
    """Standard annuity approximation for when a full projected SCR(t)
    path isn't supplied: SCR(t) ~= SCR(0) * BEL(t) / BEL(0), where BEL(t)
    is the present value at
    time t (forward-valued from today's curve) of liability cash flows
    remaining after t -- i.e. non-hedgeable risk capital is assumed to run
    off proportionally to the remaining liability, a common simplification
    but not a substitute for an actual projected SCR(t) when the firm has
    one (pass it to `compute_risk_margin` directly instead).
    """
    bel_0 = liability_cfs.pv(curve)
    result: dict[int, float] = {}
    for t in range(0, n_years + 1):
        remaining = [cf for cf in liability_cfs.flows if cf.time > t]
        if not remaining or bel_0 <= 0:
            result[t] = 0.0
            continue
        pv_at_0 = sum(cf.amount * curve.discount_factor(cf.time) for cf in remaining)
        df_t = curve.discount_factor(t)
        pv_at_t = pv_at_0 / df_t if df_t > 0 else 0.0
        result[t] = scr_0 * (pv_at_t / bel_0)
    return result
