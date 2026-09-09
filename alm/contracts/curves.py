"""Discount curve contract.

A `Curve` holds a term structure of *annual effective* zero rates (PRA RFR
convention: rates are quoted as annual compounding spot rates, term in
years from the valuation date). This is the "basic RFR" (no MA, no VA, no
RFR-TMTP adjustment) unless explicitly constructed as a shifted curve
(e.g. RFR + MA, or a stressed curve).

Interpolation: linear on the zero rate between published term points,
flat-extrapolated beyond the first/last published term. This is a
documented simplification -- PRA published curves are annual-term-point
(1y..150y) and firms typically use linear-on-zero-rate or log-linear on
discount factor; if the firm's validated R code uses a different
convention it must be swapped in here (single point of control).
"""

from __future__ import annotations

from datetime import date
from typing import Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Curve(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    currency: str = Field(..., min_length=3, max_length=3)
    valuation_date: date
    terms: tuple[float, ...] = Field(..., description="Years from valuation date, strictly increasing")
    rates: tuple[float, ...] = Field(..., description="Annual effective zero rates, e.g. 0.0325 for 3.25%")
    name: str = "curve"

    @field_validator("rates")
    @classmethod
    def _same_length(cls, v, info):
        terms = info.data.get("terms")
        if terms is not None and len(terms) != len(v):
            raise ValueError("terms and rates must be the same length")
        return v

    @field_validator("terms")
    @classmethod
    def _strictly_increasing(cls, v):
        arr = np.asarray(v, dtype=float)
        if len(arr) == 0:
            raise ValueError("curve must have at least one term point")
        if np.any(np.diff(arr) <= 0):
            raise ValueError("terms must be strictly increasing")
        return v

    def zero_rate(self, t: float) -> float:
        """Annual effective zero rate at time t (years), linear-on-zero-rate interpolation,
        flat-extrapolated beyond the published range."""
        terms = np.asarray(self.terms, dtype=float)
        rates = np.asarray(self.rates, dtype=float)
        if t <= terms[0]:
            return float(rates[0])
        if t >= terms[-1]:
            return float(rates[-1])
        return float(np.interp(t, terms, rates))

    def discount_factor(self, t: float) -> float:
        if t <= 0:
            return 1.0
        r = self.zero_rate(t)
        return (1.0 + r) ** (-t)

    def shift_parallel(self, delta: float, name: str | None = None) -> "Curve":
        """Return a new curve with every zero rate shifted by `delta` (e.g. + MA)."""
        return Curve(
            currency=self.currency,
            valuation_date=self.valuation_date,
            terms=self.terms,
            rates=tuple(r + delta for r in self.rates),
            name=name or f"{self.name}+{delta * 10000:.1f}bp",
        )

    @classmethod
    def flat(cls, rate: float, currency: str = "GBP", valuation_date: date | None = None,
             max_term: float = 100.0, name: str = "flat") -> "Curve":
        """Synthetic flat curve. For examples/tests only -- production curves must come
        from `market_data.rfr_loader` (PRA published RFR file), never hard-coded."""
        vd = valuation_date or date.today()
        return cls(
            currency=currency,
            valuation_date=vd,
            terms=(0.5, max_term),
            rates=(rate, rate),
            name=name,
        )
