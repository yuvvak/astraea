"""PRA Test 3 -- Notional Swap (SS7/18 Appendix 1, current version).

Scale Component A's market value and PD-adjusted cash flows by a single
factor k until the PV of the future surplus/shortfall, discounted at the
basic RFR, is zero -- i.e. find k such that:

    PV(k * componentA_pd_adjusted_cfs, RFR) = PV(liability_cfs, RFR)

which has the closed form k = PV(liability) / PV(componentA_pd_adjusted),
no root-finding required (both sides are linear in k). Report base MA (on
the un-scaled Component A), notional-swap MA (on the scaled Component A),
the scaled market value, and k - 1 as the implied under/over-matching
(k > 1: Component A was under-sized relative to the liability in PV terms;
k < 1: over-sized).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from alm.contracts.cashflows import CashFlow, CashFlowKind, CashFlowVector
from alm.contracts.curves import Curve
from alm.ma.engine import MAResult, compute_ma


class Test3Result(BaseModel):
    model_config = ConfigDict(frozen=True)

    liability_id: str
    scale_factor: float
    implied_under_over_matching: float  # scale_factor - 1
    base_ma: MAResult
    notional_swap_ma: MAResult
    component_a_market_value: float
    scaled_market_value: float


def run_test3(
    liability_cfs: CashFlowVector,
    component_a_pd_adjusted_by_time: dict[float, float],
    component_a_market_value: float,
    fs_rate: float,
    curve: Curve,
) -> Test3Result:
    component_a_cfv = CashFlowVector(
        id="component_a_pd_adjusted",
        currency=liability_cfs.currency,
        valuation_date=liability_cfs.valuation_date,
        direction="asset_income",
        flows=tuple(
            CashFlow(time=t, amount=amt, kind=CashFlowKind.OTHER)
            for t, amt in sorted(component_a_pd_adjusted_by_time.items())
            if amt > 0
        ),
    )

    pv_liability = liability_cfs.pv(curve)
    pv_component_a = component_a_cfv.pv(curve)
    if pv_component_a <= 0:
        raise ValueError("Component A has zero or negative present value; cannot run Test 3")

    k = pv_liability / pv_component_a

    base_ma = compute_ma(liability_cfs, component_a_market_value, fs_rate, curve)
    scaled_mv = k * component_a_market_value
    notional_swap_ma = compute_ma(liability_cfs, scaled_mv, fs_rate, curve)

    return Test3Result(
        liability_id=liability_cfs.id,
        scale_factor=k,
        implied_under_over_matching=k - 1.0,
        base_ma=base_ma,
        notional_swap_ma=notional_swap_ma,
        component_a_market_value=component_a_market_value,
        scaled_market_value=scaled_mv,
    )
