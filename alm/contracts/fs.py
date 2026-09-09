"""Fundamental Spread contract.

PRA publishes FS (PD component + Cost-of-Downgrade component) by currency,
credit quality step / rating, sector (financial / non-financial / other /
government-related), and maturity bucket, alongside the RFR file. The Long-
Term Average Spread (LTAS) floor is a separate published series applied as a
floor to the FS. See SS7/18 4.9-4.11 and IRPR reg 6.

This module defines the *shape* of the table (`FSTable`) and lookup keys
(`RatingNotch`, `AssetSector`). The actual numbers must be loaded from the
official PRA XLSX via `market_data.fs_loader` -- never hard-coded here.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RatingNotch(str, Enum):
    """Rough notch scale; production mapping from external agency ratings
    (Moody's/S&P/Fitch) to PRA credit quality steps belongs in market_data."""

    AAA = "AAA"
    AA1 = "AA1"
    AA2 = "AA2"
    AA3 = "AA3"
    A1 = "A1"
    A2 = "A2"
    A3 = "A3"
    BBB1 = "BBB1"
    BBB2 = "BBB2"
    BBB3 = "BBB3"
    BB1 = "BB1"
    BB2 = "BB2"
    BB3 = "BB3"
    B_AND_BELOW = "B_AND_BELOW"
    UNRATED = "UNRATED"

    @property
    def is_investment_grade(self) -> bool:
        return self in {
            RatingNotch.AAA, RatingNotch.AA1, RatingNotch.AA2, RatingNotch.AA3,
            RatingNotch.A1, RatingNotch.A2, RatingNotch.A3,
            RatingNotch.BBB1, RatingNotch.BBB2, RatingNotch.BBB3,
        }


class AssetSector(str, Enum):
    GOVERNMENT = "government"
    FINANCIAL = "financial"
    NON_FINANCIAL = "non_financial"
    OTHER = "other"


class FSEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    currency: str = Field(..., min_length=3, max_length=3)
    rating: RatingNotch
    sector: AssetSector
    term_years: float = Field(..., ge=0, description="Upper bound of the term bucket this entry applies to")
    fs_pd_bps: float = Field(..., description="Probability-of-default component, in bps p.a.")
    fs_cod_bps: float = Field(..., description="Cost-of-downgrade component, in bps p.a.")
    ltas_floor_bps: float = Field(0.0, description="Long-term average spread floor, in bps p.a.")

    @property
    def fs_bps(self) -> float:
        """FS before the LTAS floor is applied."""
        return self.fs_pd_bps + self.fs_cod_bps

    @property
    def fs_bps_floored(self) -> float:
        return max(self.fs_bps, self.ltas_floor_bps)


class FSTable(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str = Field(..., description="e.g. 'PRA FS 2026-08' or 'synthetic/example'")
    entries: tuple[FSEntry, ...]

    def lookup(self, currency: str, rating: RatingNotch, sector: AssetSector, term_years: float) -> FSEntry:
        """Nearest term bucket at or above `term_years`; falls back to the longest bucket available."""
        candidates = [
            e for e in self.entries
            if e.currency == currency and e.rating == rating and e.sector == sector
        ]
        if not candidates:
            raise KeyError(f"no FS entry for {currency}/{rating}/{sector}")
        candidates.sort(key=lambda e: e.term_years)
        for e in candidates:
            if term_years <= e.term_years:
                return e
        return candidates[-1]
