"""Component A/B/C hypothecation: greedy nearest-maturity cash-flow-matching
waterfall. This is the v1 default algorithm; swap the `hypothecate`
function body for a firm's actual algorithm later, nothing downstream
depends on it being greedy.

Component A: PD-adjusted asset cash flows assigned to replicate liability
cash flows *bucket by bucket*, nearest-maturity asset first, never assigning
more than the remaining liability amount in that bucket (MA 2.2(1) / SS7/18
"replicate expected cash flows").

Component B: additional assets (by market value, not bucket-matched) needed
so that A + B's market value covers the BEL, again nearest-maturity-first
from whatever's left over after A.

Component C: whatever's left over -- surplus assets still in the MA
portfolio.

Assignment is tracked as a *present-value fraction* of each position (0..1
of that position's own PD-adjusted cash flow PV assigned to A, then of its
market value to B, remainder to C) rather than a single "units held"
fraction constrained by the worst bucket -- a single scalar-per-position cap
is pathological: one oversized cash flow at a bucket the liability has
already fully met would zero out the assignment of that entire position at
every other bucket too. Per-bucket assignment avoids that.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from alm.contracts.assets import AssetPosition, InterestRateSwap
from alm.contracts.cashflows import CashFlowVector
from alm.contracts.curves import Curve
from alm.contracts.fs import FSTable


def pd_haircut_cashflow_vector(
    cfv: CashFlowVector, currency: str, rating, sector, is_government: bool, fs_table: FSTable,
) -> CashFlowVector:
    """Haircut each contractual cash flow by its own cumulative PD, derived
    from the FS PD-only component as an annual marginal-default-rate proxy:
    cum_pd(t) = 1 - (1 - fs_pd_rate)^t. This is a documented v1
    simplification of "PD-adjusted cash flows" (FS PD bps is a risk-neutral
    spread component, not literally an annual default probability) --
    swappable once the firm's validated PD-adjustment convention is known.
    Government cash flows get fs_pd_rate = 0 (PRA convention: gilts FS-nil).

    Generic over the cash flow vector's source so it can PD-haircut both
    ordinary `Bond` positions (via `pd_adjusted_cashflows` below) and the
    standalone HP instrument profiles used by PRA Tests 4/5
    (`ma.hp_instrument`), without those two callers duplicating the haircut
    formula.
    """
    adjusted = []
    for cf in cfv.flows:
        if is_government:
            pd_rate = 0.0
        else:
            entry = fs_table.lookup(currency, rating, sector, cf.time)
            pd_rate = entry.fs_pd_bps / 10_000.0
        cum_pd = 1.0 - (1.0 - pd_rate) ** cf.time
        adjusted.append(cf.model_copy(update={"amount": cf.amount * (1.0 - cum_pd)}))
    return cfv.model_copy(update={"id": cfv.id + "_pd_adj", "flows": tuple(adjusted)})


def pd_adjusted_cashflows(position: AssetPosition, fs_table: FSTable, valuation_date: date) -> CashFlowVector:
    bond = position.instrument
    cfv = position.cashflows(valuation_date)
    return pd_haircut_cashflow_vector(cfv, bond.currency, bond.rating, bond.sector, bond.is_government, fs_table)


class PositionAssignment(BaseModel):
    model_config = ConfigDict(frozen=True)

    position_id: str
    fraction_a: float
    fraction_b: float
    fraction_c: float
    market_value_a: float
    market_value_b: float
    market_value_c: float


class HypothecationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    liability_id: str
    bel: float
    assignments: tuple[PositionAssignment, ...]
    component_a_pd_adjusted_by_time: dict[float, float]
    component_a_market_value: float
    component_ab_market_value: float
    component_c_market_value: float
    remaining_liability_by_time: dict[float, float]

    def assignment_for(self, position_id: str) -> PositionAssignment:
        for a in self.assignments:
            if a.position_id == position_id:
                return a
        raise KeyError(position_id)


def hypothecate(
    liability_cfs: CashFlowVector,
    positions: list[AssetPosition],
    fs_table: FSTable,
    valuation_date: date,
    curve: Curve,
    tolerance: float = 1e-6,
) -> HypothecationResult:
    if liability_cfs.direction != "liability_outgo":
        raise ValueError("hypothecate expects a liability cash flow vector")

    bel = liability_cfs.pv(curve)
    remaining_liability: dict[float, float] = {}
    for cf in liability_cfs.flows:
        remaining_liability[cf.time] = remaining_liability.get(cf.time, 0.0) + cf.amount

    ordered = sorted(positions, key=lambda p: p.instrument.maturity_years)

    component_a_by_time: dict[float, float] = {}
    fraction_a: dict[str, float] = {}

    for p in ordered:
        pd_cfv = pd_adjusted_cashflows(p, fs_table, valuation_date).scale(p.units, id_suffix="")
        is_derivative = isinstance(p.instrument, InterestRateSwap)
        total_pv = pd_cfv.pv(curve)
        assigned_pv = 0.0
        for cf in pd_cfv.flows:
            if cf.amount < 0:
                # A negative cash flow (e.g. a derivative's net outflow in a period, see
                # InterestRateSwap) is an extra draw on the portfolio, not a contribution:
                # it increases the remaining liability need at that bucket rather than being
                # silently skipped (the old `if cf.amount <= 0: continue` dropped it entirely,
                # understating what Component A/Test 1 needed to cover) or matched via the
                # min()/take mechanic below, which assumes non-negative amounts throughout.
                remaining_liability[cf.time] = remaining_liability.get(cf.time, 0.0) + (-cf.amount)
                continue
            if is_derivative:
                # Derivatives (net-settled, bidirectional cash flows) do not participate in
                # Component A's literal cash-flow replication test -- assigned_pv/total_pv
                # is not a meaningful fraction for a mixed-sign cash flow stream (it can
                # exceed 1, since assigned_pv only ever sums positive contributions while
                # total_pv nets against the negative periods too). Their net economic value
                # is reflected in market value only, via Component B/C below.
                continue
            if cf.amount <= 0:
                continue
            avail = remaining_liability.get(cf.time, 0.0)
            if avail <= tolerance:
                continue
            take = min(cf.amount, avail)
            remaining_liability[cf.time] = avail - take
            component_a_by_time[cf.time] = component_a_by_time.get(cf.time, 0.0) + take
            assigned_pv += take * curve.discount_factor(cf.time)
        fraction_a[p.id] = (assigned_pv / total_pv) if total_pv > tolerance else 0.0

    component_a_mv = sum(fraction_a[p.id] * p.resolved_market_value(curve) for p in ordered)

    fraction_b: dict[str, float] = {p.id: 0.0 for p in ordered}
    covered_mv = component_a_mv
    if covered_mv < bel - tolerance:
        for p in ordered:
            leftover_frac = 1.0 - fraction_a[p.id]
            if leftover_frac <= tolerance:
                continue
            mv_p = p.resolved_market_value(curve)
            leftover_mv = leftover_frac * mv_p
            needed = bel - covered_mv
            if needed <= tolerance:
                break
            take_mv = min(leftover_mv, needed)
            # guard against dividing by a negligible mv_p (0 or near-0), not merely a
            # non-positive one: a genuinely negative mv_p (e.g. an out-of-the-money
            # derivative) is a well-defined, non-zero divisor, and skipping it here
            # left fraction_b silently at 0 while `covered_mv` below was still correctly
            # adjusted -- double-counting the position's value into Component C's
            # fraction_c = max(0, 1 - fa - fb) fallback further down.
            fraction_b[p.id] = take_mv / mv_p if abs(mv_p) > tolerance else 0.0
            covered_mv += take_mv

    assignments = []
    total_c_mv = 0.0
    for p in ordered:
        fa, fb = fraction_a[p.id], fraction_b[p.id]
        fc = max(0.0, 1.0 - fa - fb)
        mv_p = p.resolved_market_value(curve)
        mv_a, mv_b, mv_c = fa * mv_p, fb * mv_p, fc * mv_p
        total_c_mv += mv_c
        assignments.append(PositionAssignment(
            position_id=p.id, fraction_a=fa, fraction_b=fb, fraction_c=fc,
            market_value_a=mv_a, market_value_b=mv_b, market_value_c=mv_c,
        ))

    return HypothecationResult(
        liability_id=liability_cfs.id,
        bel=bel,
        assignments=tuple(assignments),
        component_a_pd_adjusted_by_time=component_a_by_time,
        component_a_market_value=component_a_mv,
        component_ab_market_value=covered_mv,
        component_c_market_value=total_c_mv,
        remaining_liability_by_time=remaining_liability,
    )
