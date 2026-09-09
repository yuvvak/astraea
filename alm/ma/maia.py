"""MAIA (Matching Adjustment Investment Accelerator) tracking: the 24-month
regularisation clock and the exposure limit, min(5% of MA BEL net of
reinsurance, GBP 2bn) or a tighter firm-specific limit (project brief:
"MAIA assets (flag, 24-month regularisation clock, exposure vs min(5% MA
BEL net of RI, GBP 2bn) or firm-specific limit)").

This module only checks and reports; it does not decide remediation
(recapture, reclassification, or an application for an extension are firm/
PRA process decisions outside this engine's scope).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from alm.contracts.assets import AssetPosition
from alm.contracts.curves import Curve

MAIA_REGULARISATION_MONTHS = 24  # project brief "24-month regularisation clock"
MAIA_EXPOSURE_PCT_OF_BEL = 0.05  # project brief "5% MA BEL net of RI"
MAIA_EXPOSURE_HARD_CAP_GBP = 2_000_000_000.0  # project brief "GBP 2bn"


class MAIARegularisationStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    position_id: str
    entry_date: date
    as_of_date: date
    months_elapsed: float
    clock_months: int
    months_remaining: float  # negative once breached
    breach: bool


class MAIAExposureResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_maia_market_value: float
    bel_net_of_ri: float
    regulatory_limit: float  # min(5% of BEL, hard cap)
    firm_specific_limit: float | None
    effective_limit: float  # min(regulatory_limit, firm_specific_limit) if set, else regulatory_limit
    breach: bool
    excess: float


def _months_between(start: date, end: date) -> float:
    """Whole-and-fractional months between two dates, using 30.4375-day
    average months (365.25 / 12) -- a documented approximation; swap for a
    real day-count convention if the firm's MAIA process requires one."""
    return (end - start).days / 30.4375


def check_maia_regularisation(
    position: AssetPosition,
    as_of_date: date,
    clock_months: int = MAIA_REGULARISATION_MONTHS,
) -> MAIARegularisationStatus:
    if not position.is_maia or position.maia_entry_date is None:
        raise ValueError(f"position {position.id!r} is not flagged as MAIA (is_maia=False or no maia_entry_date)")

    months_elapsed = _months_between(position.maia_entry_date, as_of_date)
    months_remaining = clock_months - months_elapsed

    return MAIARegularisationStatus(
        position_id=position.id, entry_date=position.maia_entry_date, as_of_date=as_of_date,
        months_elapsed=months_elapsed, clock_months=clock_months, months_remaining=months_remaining,
        breach=months_remaining < 0,
    )


def maia_exposure_limit(bel_net_of_ri: float, firm_specific_limit: float | None = None) -> tuple[float, float]:
    """Returns (regulatory_limit, effective_limit)."""
    regulatory_limit = min(MAIA_EXPOSURE_PCT_OF_BEL * bel_net_of_ri, MAIA_EXPOSURE_HARD_CAP_GBP)
    effective_limit = min(regulatory_limit, firm_specific_limit) if firm_specific_limit is not None else regulatory_limit
    return regulatory_limit, effective_limit


def check_maia_exposure(
    positions: list[AssetPosition],
    curve: Curve,
    bel_net_of_ri: float,
    firm_specific_limit: float | None = None,
) -> MAIAExposureResult:
    maia_positions = [p for p in positions if p.is_maia]
    total_maia_mv = sum(p.resolved_market_value(curve) for p in maia_positions)

    regulatory_limit, effective_limit = maia_exposure_limit(bel_net_of_ri, firm_specific_limit)
    excess = max(0.0, total_maia_mv - effective_limit)

    return MAIAExposureResult(
        total_maia_market_value=total_maia_mv, bel_net_of_ri=bel_net_of_ri,
        regulatory_limit=regulatory_limit, firm_specific_limit=firm_specific_limit,
        effective_limit=effective_limit, breach=excess > 0, excess=excess,
    )
