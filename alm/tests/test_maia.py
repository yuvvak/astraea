"""MAIA regularisation clock and exposure limit golden tests, cross-checked
against independent date-arithmetic and percentage calculations.
"""

from __future__ import annotations

from datetime import date

import pytest

from alm.examples.golden_toy import build_corporate_bond_position, build_liability, build_rfr_curve
from alm.ma.maia import (
    MAIA_EXPOSURE_HARD_CAP_GBP,
    MAIA_EXPOSURE_PCT_OF_BEL,
    MAIA_REGULARISATION_MONTHS,
    check_maia_exposure,
    check_maia_regularisation,
    maia_exposure_limit,
)


def _maia_position(entry_date: date):
    corp = build_corporate_bond_position(750_000.0)
    return corp.model_copy(update={"is_maia": True, "maia_entry_date": entry_date})


def test_non_maia_position_raises_on_regularisation_check():
    corp = build_corporate_bond_position(750_000.0)
    with pytest.raises(ValueError, match="not flagged as MAIA"):
        check_maia_regularisation(corp, as_of_date=date(2026, 9, 8))


def test_maia_entry_date_required_when_flagged():
    from pydantic import ValidationError

    from alm.contracts.assets import AssetPosition, Bond
    from alm.contracts.fs import AssetSector, RatingNotch

    bond = Bond(
        id="test_bond", currency="GBP", notional=100_000.0, coupon_rate=0.04,
        maturity_years=5.0, rating=RatingNotch.A2, sector=AssetSector.NON_FINANCIAL,
    )
    with pytest.raises(ValidationError, match="maia_entry_date is required"):
        AssetPosition(id="pos_no_date", instrument=bond, is_maia=True)


def test_just_under_24_months_does_not_breach():
    position = _maia_position(date(2024, 9, 8))
    status = check_maia_regularisation(position, as_of_date=date(2026, 9, 8))

    independent_months = (date(2026, 9, 8) - date(2024, 9, 8)).days / 30.4375
    assert status.months_elapsed == pytest.approx(independent_months, rel=1e-9)
    assert status.clock_months == MAIA_REGULARISATION_MONTHS == 24
    assert status.months_elapsed < 24
    assert status.breach is False
    assert status.months_remaining == pytest.approx(24 - independent_months, rel=1e-9)


def test_30_months_breaches_the_clock():
    position = _maia_position(date(2024, 9, 8))
    status = check_maia_regularisation(position, as_of_date=date(2027, 3, 8))

    assert status.months_elapsed > 24
    assert status.breach is True
    assert status.months_remaining < 0


def test_exposure_limit_uses_5pct_of_bel_when_below_the_hard_cap():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    bel = cfs.pv(curve)

    regulatory_limit, effective_limit = maia_exposure_limit(bel)
    assert regulatory_limit == pytest.approx(MAIA_EXPOSURE_PCT_OF_BEL * bel, rel=1e-9)
    assert regulatory_limit < MAIA_EXPOSURE_HARD_CAP_GBP
    assert effective_limit == pytest.approx(regulatory_limit, rel=1e-9)


def test_exposure_limit_hard_cap_binds_for_a_very_large_bel():
    huge_bel = 100_000_000_000.0  # 5% of this is 5bn, above the 2bn hard cap
    regulatory_limit, effective_limit = maia_exposure_limit(huge_bel)
    assert regulatory_limit == pytest.approx(MAIA_EXPOSURE_HARD_CAP_GBP)
    assert effective_limit == pytest.approx(MAIA_EXPOSURE_HARD_CAP_GBP)


def test_firm_specific_limit_can_be_tighter_than_the_regulatory_one():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    bel = cfs.pv(curve)

    regulatory_limit, effective_limit = maia_exposure_limit(bel, firm_specific_limit=10_000.0)
    assert regulatory_limit > 10_000.0
    assert effective_limit == pytest.approx(10_000.0)


def test_exposure_breach_reports_correct_excess_and_ignores_non_maia_positions():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    bel = cfs.pv(curve)

    maia_position = _maia_position(date(2024, 9, 8))
    non_maia_position = build_corporate_bond_position(300_000.0)  # different id, not flagged

    result = check_maia_exposure([maia_position, non_maia_position], curve, bel)

    # only the MAIA-flagged position counts toward total exposure
    assert result.total_maia_market_value == pytest.approx(750_000.0)
    assert result.regulatory_limit == pytest.approx(MAIA_EXPOSURE_PCT_OF_BEL * bel, rel=1e-9)
    assert result.breach is True
    assert result.excess == pytest.approx(750_000.0 - result.effective_limit, rel=1e-9)
