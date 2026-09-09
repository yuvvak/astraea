"""Derivative counterparty default SCR golden test: only in-the-money swap
positions represent counterparty credit exposure to us, so an out-of-the-
money swap must contribute exactly zero, cross-checked against the
independent swap pricing already established in test_interest_rate_swap.py.
"""

from __future__ import annotations

import pytest

from alm.contracts.assets import AssetPosition, InterestRateSwap
from alm.contracts.fs import RatingNotch
from alm.examples.golden_toy import build_rfr_curve
from alm.scr import COUNTERPARTY_DERIVATIVE_FACTORS, compute_counterparty_default_scr

NOTIONAL = 1_000_000.0
TERM = 10.0


def test_only_in_the_money_swap_contributes_to_counterparty_exposure():
    curve = build_rfr_curve()
    itm = InterestRateSwap.from_curve(
        id="swap_itm", currency="GBP", notional=NOTIONAL, fixed_rate=0.05,
        maturity_years=TERM, curve=curve, receive_fixed=True, rating=RatingNotch.A2,
    )
    otm = InterestRateSwap.from_curve(
        id="swap_otm", currency="GBP", notional=NOTIONAL, fixed_rate=0.03,
        maturity_years=TERM, curve=curve, receive_fixed=True, rating=RatingNotch.A2,
    )
    pos_itm = AssetPosition(id="pos_swap_itm", instrument=itm)
    pos_otm = AssetPosition(id="pos_swap_otm", instrument=otm)

    itm_mv = pos_itm.resolved_market_value(curve)
    otm_mv = pos_otm.resolved_market_value(curve)
    assert itm_mv > 0
    assert otm_mv < 0

    result = compute_counterparty_default_scr([pos_itm, pos_otm], curve)

    assert result.derivative_exposure == pytest.approx(itm_mv, rel=1e-9)
    assert "pos_swap_otm" not in result.derivative_charge_by_position

    expected_charge = COUNTERPARTY_DERIVATIVE_FACTORS[RatingNotch.A2] * itm_mv
    assert result.derivative_charge_by_position["pos_swap_itm"] == pytest.approx(expected_charge, rel=1e-9)
    assert result.derivative_charge == pytest.approx(expected_charge, rel=1e-9)
    assert result.scr_counterparty == pytest.approx(expected_charge, rel=1e-9)
    assert result.cash_exposure == 0.0
    assert result.cash_charge == 0.0


def test_rating_drives_the_charge_factor():
    curve = build_rfr_curve()
    aaa_swap = InterestRateSwap.from_curve(
        id="swap_aaa", currency="GBP", notional=NOTIONAL, fixed_rate=0.05,
        maturity_years=TERM, curve=curve, receive_fixed=True, rating=RatingNotch.AAA,
    )
    bb_swap = InterestRateSwap.from_curve(
        id="swap_bb", currency="GBP", notional=NOTIONAL, fixed_rate=0.05,
        maturity_years=TERM, curve=curve, receive_fixed=True, rating=RatingNotch.BB1,
    )
    pos_aaa = AssetPosition(id="pos_swap_aaa", instrument=aaa_swap)
    pos_bb = AssetPosition(id="pos_swap_bb", instrument=bb_swap)

    result = compute_counterparty_default_scr([pos_aaa, pos_bb], curve)

    mv = pos_aaa.resolved_market_value(curve)  # identical MV for both, same fixed rate/notional/term
    assert result.derivative_charge_by_position["pos_swap_aaa"] == pytest.approx(0.005 * mv, rel=1e-9)
    assert result.derivative_charge_by_position["pos_swap_bb"] == pytest.approx(0.04 * mv, rel=1e-9)
    # a lower-rated counterparty must always cost more for the same exposure
    assert result.derivative_charge_by_position["pos_swap_bb"] > result.derivative_charge_by_position["pos_swap_aaa"]
