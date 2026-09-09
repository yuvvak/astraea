"""Cash flow vector contract shared by liabilities, assets, MA engine and tests.

A single `CashFlowVector` (with a `kind`) is the unit of exchange between every
module in this repo: the Prophet adapter emits these, the asset library emits
these, the MA engine and PRA tests only ever consume/produce these -- so a
golden CF file can substitute for a live Prophet run in unit tests.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Iterable

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from .curves import Curve


class CashFlowKind(str, Enum):
    BENEFIT = "benefit"
    EXPENSE = "expense"
    REINSURANCE = "reinsurance"
    COUPON = "coupon"
    PRINCIPAL = "principal"
    OPTION_SURRENDER = "option_surrender"
    OTHER = "other"


class CashFlow(BaseModel):
    model_config = ConfigDict(frozen=True)

    time: float = Field(..., ge=0, description="Years from valuation date")
    amount: float = Field(..., description="Positive magnitude of the payment (see CashFlowVector's sign convention docstring) for every instrument type except a net-settled derivative's period cash flow, which is genuinely bidirectional and may be negative -- see contracts/assets.py's InterestRateSwap.")
    kind: CashFlowKind = CashFlowKind.OTHER
    inflation_linked: bool = False


class CashFlowVector(BaseModel):
    """An ordered set of cash flows for one position/cohort, all in one currency.

    Sign convention: amounts are stored as *positive magnitudes* of the payment;
    whether it is a liability outgo or an asset income is carried by
    `direction` ("liability_outgo" or "asset_income"), not by sign. This avoids
    sign-flip bugs when the same vector is reused across MA, Test 1 and stresses.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    currency: str = Field(..., min_length=3, max_length=3)
    valuation_date: date
    direction: str = Field(..., pattern="^(liability_outgo|asset_income)$")
    flows: tuple[CashFlow, ...]

    def times(self) -> np.ndarray:
        return np.array([cf.time for cf in self.flows], dtype=float)

    def amounts(self) -> np.ndarray:
        return np.array([cf.amount for cf in self.flows], dtype=float)

    def pv(self, curve: Curve) -> float:
        """Present value discounting each flow at the curve's zero rate for its own term."""
        if not self.flows:
            return 0.0
        return float(sum(cf.amount * curve.discount_factor(cf.time) for cf in self.flows))

    def pv_flat(self, rate: float) -> float:
        """Present value at a single flat annual effective rate (used by the two-AER solver)."""
        if not self.flows:
            return 0.0
        return float(sum(cf.amount * (1.0 + rate) ** (-cf.time) for cf in self.flows))

    def total(self) -> float:
        return float(sum(cf.amount for cf in self.flows))

    def filter_kind(self, *kinds: CashFlowKind) -> "CashFlowVector":
        kept = tuple(cf for cf in self.flows if cf.kind in kinds)
        return self.model_copy(update={"flows": kept})

    def scale(self, factor: float, id_suffix: str = "_scaled") -> "CashFlowVector":
        scaled = tuple(cf.model_copy(update={"amount": cf.amount * factor}) for cf in self.flows)
        return self.model_copy(update={"id": self.id + id_suffix, "flows": scaled})

    def net_by_time(self, id: str, sign_by_kind: dict[CashFlowKind, int] | None = None) -> "CashFlowVector":
        """Collapse to one flow per distinct time, applying a per-kind sign so
        that e.g. reinsurance recoveries (which reduce net insurer outgo) net
        off against benefit/expense outgo rather than adding to it. Default
        signs: everything is +1 (adds to outgo/income) except REINSURANCE,
        which is -1 -- see project brief, "outwards reinsurance ... as a
        reduction to liability CFs". Resulting flows are tagged CashFlowKind.OTHER
        since they no longer represent a single original kind.
        """
        signs = sign_by_kind or {k: (-1 if k == CashFlowKind.REINSURANCE else 1) for k in CashFlowKind}
        totals: dict[float, float] = {}
        for cf in self.flows:
            totals[cf.time] = totals.get(cf.time, 0.0) + signs.get(cf.kind, 1) * cf.amount
        flows = tuple(
            CashFlow(time=t, amount=amt, kind=CashFlowKind.OTHER)
            for t, amt in sorted(totals.items())
        )
        return self.model_copy(update={"id": id, "flows": flows})

    @classmethod
    def merge(cls, vectors: Iterable["CashFlowVector"], id: str) -> "CashFlowVector":
        vectors = list(vectors)
        if not vectors:
            raise ValueError("cannot merge an empty list of cash flow vectors")
        currency = vectors[0].currency
        direction = vectors[0].direction
        valuation_date = vectors[0].valuation_date
        for v in vectors:
            if v.currency != currency:
                raise ValueError(f"currency mismatch: {v.currency} vs {currency}")
            if v.direction != direction:
                raise ValueError(f"direction mismatch: {v.direction} vs {direction}")
        all_flows = tuple(cf for v in vectors for cf in v.flows)
        return cls(id=id, currency=currency, valuation_date=valuation_date, direction=direction, flows=all_flows)
