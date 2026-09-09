"""PRA Test 1 -- Accumulated Cash Flow Shortfall (SS7/18 Appendix 1).

Project BEL cash flows and Component A cash flows (after PD-only FS
adjustment); accumulate the bucket-by-bucket surplus/shortfall at the basic
RFR; the test passes if the maximum accumulated shortfall, as a fraction of
PV(liabilities @ RFR), does not exceed the named threshold (3%, PRA default).

Bucket frequency: this v1 implementation uses whatever time grid the
liability cash flow vector is defined on (the golden examples use an annual
grid). SS7/18 requires monthly running if the firm is writing new business
into the matching fund, else quarterly -- that's a cash-flow-grid choice
made upstream (Prophet extract / reference projector), not something this
test enforces itself; wire the firm's actual matching-bucket frequency in
via `alm/config` once the Prophet adapter exists.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from alm.contracts.cashflows import CashFlowVector
from alm.contracts.curves import Curve

TEST1_THRESHOLD = 0.03  # SS7/18 Appendix 1 default; named constant, not inlined


class Test1Result(BaseModel):
    model_config = ConfigDict(frozen=True)

    liability_id: str
    pv_liabilities_rfr: float
    max_accumulated_shortfall: float
    ratio: float
    threshold: float
    passed: bool
    accumulated_series: tuple[tuple[float, float], ...]  # (time, accumulated balance)


def run_test1(
    liability_cfs: CashFlowVector,
    component_a_pd_adjusted_by_time: dict[float, float],
    curve: Curve,
    threshold: float = TEST1_THRESHOLD,
) -> Test1Result:
    liability_by_time: dict[float, float] = {}
    for cf in liability_cfs.flows:
        liability_by_time[cf.time] = liability_by_time.get(cf.time, 0.0) + cf.amount
    times = sorted(set(liability_by_time) | set(component_a_pd_adjusted_by_time))

    accumulated = 0.0
    prev_time = 0.0
    max_shortfall = 0.0
    series: list[tuple[float, float]] = []

    for t in times:
        if t > prev_time:
            # roll the running balance forward at the curve's implied forward rate
            # between prev_time and t (correct for any curve shape, not just flat)
            growth = curve.discount_factor(prev_time) / curve.discount_factor(t)
            accumulated *= growth
        asset_amt = component_a_pd_adjusted_by_time.get(t, 0.0)
        liab_amt = liability_by_time.get(t, 0.0)
        accumulated += asset_amt - liab_amt
        series.append((t, accumulated))
        if -accumulated > max_shortfall:
            max_shortfall = -accumulated
        prev_time = t

    pv_liabilities = liability_cfs.pv(curve)
    ratio = max_shortfall / pv_liabilities if pv_liabilities > 0 else 0.0

    return Test1Result(
        liability_id=liability_cfs.id,
        pv_liabilities_rfr=pv_liabilities,
        max_accumulated_shortfall=max_shortfall,
        ratio=ratio,
        threshold=threshold,
        passed=ratio <= threshold,
        accumulated_series=tuple(series),
    )
