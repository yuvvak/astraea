"""PRA Test 5 -- Modified Accumulated Shortfall (HP assets only, SS7/18
Appendix 1).

Same accumulation mechanic as Test 1 (see accumulated_cf_shortfall.py,
reused directly here rather than re-implemented), but run on the HP asset's
EXTENDED cash flow profile (latest permitted repayment date, with any
coupon step-up for the extension period) instead of the expected profile --
this is Test 1's mirror-image stress: cash arriving LATER than the liability
needs it (vs Test 4's earlier-than-expected stress), so a larger accumulated
shortfall is expected. Threshold is 5% (vs Test 1's 3%), per SS7/18 Appendix 1.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from alm.contracts.cashflows import CashFlowVector
from alm.contracts.curves import Curve
from alm.contracts.fs import FSTable
from alm.ma.hp_instrument import HPBond
from alm.ma.hypothecation import pd_haircut_cashflow_vector

from .accumulated_cf_shortfall import Test1Result, run_test1

TEST5_THRESHOLD = 0.05  # SS7/18 Appendix 1 default


class Test5Result(BaseModel):
    model_config = ConfigDict(frozen=True)

    hp_asset_id: str
    inner: Test1Result  # the underlying Test1-style accumulation result, run on the extended profile

    @property
    def passed(self) -> bool:
        return self.inner.passed

    @property
    def ratio(self) -> float:
        return self.inner.ratio


def run_test5(
    liability_cfs: CashFlowVector,
    hp_bond: HPBond,
    fs_table: FSTable,
    curve: Curve,
    valuation_date: date,
    threshold: float = TEST5_THRESHOLD,
) -> Test5Result:
    extended_cfv = hp_bond.extended_cashflows(valuation_date)
    pd_adjusted = pd_haircut_cashflow_vector(
        extended_cfv, hp_bond.currency, hp_bond.rating, hp_bond.sector, hp_bond.is_government, fs_table,
    )
    by_time: dict[float, float] = {}
    for cf in pd_adjusted.flows:
        by_time[cf.time] = by_time.get(cf.time, 0.0) + cf.amount

    inner = run_test1(liability_cfs, by_time, curve, threshold=threshold)
    return Test5Result(hp_asset_id=hp_bond.id, inner=inner)
