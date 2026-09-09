"""ReinsuranceRecoverable golden tests: gross market value must be
identical whether or not the position is funded/collateralized (the brief's
explicit "do not treat FundedRe collateral as automatically MA-eligible"
requirement), while the counterparty default SCR charge correctly nets
collateral off NET exposure only -- a fully-collateralized position must
contribute exactly zero to counterparty risk despite its full market value
still counting everywhere else (MA calc, spread SCR, etc).
"""

from __future__ import annotations

import pytest

from alm.contracts.assets import AssetPosition, ReinsuranceRecoverable
from alm.contracts.fs import RatingNotch
from alm.examples.golden_toy import build_rfr_curve
from alm.scr import COUNTERPARTY_REINSURANCE_FACTORS, compute_counterparty_default_scr

RECOVERY_PER_YEAR = 50_000.0
YEARS = (1.0, 2.0, 3.0, 4.0, 5.0)


def _recoverable(id: str, is_funded: bool, collateral_value: float) -> ReinsuranceRecoverable:
    return ReinsuranceRecoverable(
        id=id, currency="GBP",
        expected_recovery_cashflows=tuple((t, RECOVERY_PER_YEAR) for t in YEARS),
        rating=RatingNotch.A2, is_funded=is_funded, collateral_value=collateral_value,
    )


def test_market_value_matches_independent_annuity_pv():
    curve = build_rfr_curve()
    recoverable = _recoverable("re_test", is_funded=False, collateral_value=0.0)
    position = AssetPosition(id="pos_re", instrument=recoverable)

    independent_mv = sum(RECOVERY_PER_YEAR * curve.discount_factor(t) for t in YEARS)
    assert position.resolved_market_value(curve) == pytest.approx(independent_mv, rel=1e-9)
    assert recoverable.maturity_years == 5.0


def test_collateral_never_reduces_market_value():
    curve = build_rfr_curve()
    unfunded = _recoverable("re_unfunded", is_funded=False, collateral_value=0.0)
    fully_collateralized = _recoverable("re_funded", is_funded=True, collateral_value=1_000_000.0)  # far more than gross MV

    pos_unfunded = AssetPosition(id="pos_unfunded", instrument=unfunded)
    pos_funded = AssetPosition(id="pos_funded", instrument=fully_collateralized)

    assert pos_unfunded.resolved_market_value(curve) == pytest.approx(pos_funded.resolved_market_value(curve), rel=1e-9)


def test_fully_collateralized_position_contributes_zero_counterparty_charge():
    curve = build_rfr_curve()
    unfunded = _recoverable("re_unfunded", is_funded=False, collateral_value=0.0)
    pos_unfunded = AssetPosition(id="pos_unfunded", instrument=unfunded)
    gross_mv = pos_unfunded.resolved_market_value(curve)

    fully_collateralized = _recoverable("re_funded", is_funded=True, collateral_value=gross_mv)
    pos_funded = AssetPosition(id="pos_funded", instrument=fully_collateralized)

    result = compute_counterparty_default_scr([pos_unfunded, pos_funded], curve)

    assert "pos_funded" not in result.reinsurance_charge_by_position
    assert result.reinsurance_exposure == pytest.approx(gross_mv, rel=1e-9)  # only the unfunded position

    expected_charge = COUNTERPARTY_REINSURANCE_FACTORS[RatingNotch.A2] * gross_mv
    assert result.reinsurance_charge_by_position["pos_unfunded"] == pytest.approx(expected_charge, rel=1e-9)
    assert result.reinsurance_charge == pytest.approx(expected_charge, rel=1e-9)
    assert result.scr_counterparty == pytest.approx(expected_charge, rel=1e-9)


def test_partial_collateral_leaves_only_the_uncollateralized_net_exposure():
    curve = build_rfr_curve()
    gross_mv = sum(RECOVERY_PER_YEAR * curve.discount_factor(t) for t in YEARS)
    partial_collateral = gross_mv * 0.4
    partially_funded = _recoverable("re_partial", is_funded=True, collateral_value=partial_collateral)
    position = AssetPosition(id="pos_partial", instrument=partially_funded)

    result = compute_counterparty_default_scr([position], curve)

    expected_net_exposure = gross_mv - partial_collateral
    assert result.reinsurance_exposure == pytest.approx(expected_net_exposure, rel=1e-9)

    expected_charge = COUNTERPARTY_REINSURANCE_FACTORS[RatingNotch.A2] * expected_net_exposure
    assert result.reinsurance_charge == pytest.approx(expected_charge, rel=1e-9)
