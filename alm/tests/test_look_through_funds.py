"""Look-through fund golden test: a fund holding A2 GBP corporate + A3 USD
corporate constituents must be expanded to those constituents before SF SCR
sub-modules run, surfacing both the fund's real credit composition (spread
SCR) and its hidden FX exposure (currency SCR) -- neither of which an
opaque, un-expanded fund position (rating defaults to UNRATED, currency is
just whatever the fund itself declares) could show.
"""

from __future__ import annotations

import pytest

from alm.contracts.assets import AssetPosition, FundHolding
from alm.contracts.fs import RatingNotch
from alm.examples.golden_toy import build_corporate_bond_position, build_fs_table, build_usd_bond_position, build_rfr_curve
from alm.scr import compute_currency_scr, compute_spread_scr, expand_look_through
from alm.scr.standard_formula import spread_stress_pct


def _independent_macaulay_duration(position, curve):
    instrument = position.instrument
    if isinstance(instrument, FundHolding):
        total_mv = sum(cp.resolved_market_value(curve) for cp in instrument.constituent_positions)
        return sum(_independent_macaulay_duration(cp, curve) * cp.resolved_market_value(curve) for cp in instrument.constituent_positions) / total_mv
    cfs = instrument.contractual_cashflows(curve.valuation_date)
    weighted, total_pv = 0.0, 0.0
    for cf in cfs.flows:
        pv = cf.amount * curve.discount_factor(cf.time)
        weighted += cf.time * pv
        total_pv += pv
    return weighted / total_pv

CORP_DIRECT_MV = 300_000.0
CORP_IN_FUND_MV = 400_000.0
USD_IN_FUND_MV = 100_000.0


def _portfolio():
    curve = build_rfr_curve()
    corp_direct = build_corporate_bond_position(CORP_DIRECT_MV)
    corp_in_fund = build_corporate_bond_position(CORP_IN_FUND_MV)
    usd_in_fund = build_usd_bond_position(USD_IN_FUND_MV)
    fund = FundHolding(id="fund_1", currency="GBP", constituent_positions=(corp_in_fund, usd_in_fund))
    fund_pos = AssetPosition(id="pos_fund", instrument=fund)
    return curve, corp_direct, fund_pos


def test_fund_market_value_equals_sum_of_constituents():
    curve, _, fund_pos = _portfolio()
    assert fund_pos.resolved_market_value(curve) == pytest.approx(CORP_IN_FUND_MV + USD_IN_FUND_MV, rel=1e-9)


def test_expansion_replaces_the_fund_with_its_constituents():
    curve, corp_direct, fund_pos = _portfolio()
    expanded = expand_look_through([corp_direct, fund_pos])

    ids = {p.id for p in expanded}
    assert ids == {"pos_corp", "pos_fund::pos_corp", "pos_fund::pos_usd_corp"}
    assert len(expanded) == 3


def test_currency_scr_only_sees_the_hidden_usd_exposure_after_expansion():
    curve, corp_direct, fund_pos = _portfolio()

    opaque = compute_currency_scr([corp_direct, fund_pos], curve)
    assert opaque.total_fx_exposure == 0.0  # the fund itself is declared GBP; its USD constituent is invisible

    expanded = expand_look_through([corp_direct, fund_pos])
    look_through = compute_currency_scr(expanded, curve)
    assert look_through.total_fx_exposure == pytest.approx(USD_IN_FUND_MV, rel=1e-9)


def test_spread_scr_reflects_actual_constituent_ratings_not_a_flat_unrated_factor():
    curve, corp_direct, fund_pos = _portfolio()

    opaque = compute_spread_scr([corp_direct, fund_pos], curve)
    fund_mv = fund_pos.resolved_market_value(curve)
    # without look-through, the fund's own (default UNRATED) rating drives its whole charge --
    # 3D17.4's unassessed-bond formula, via the fund's own aggregate duration
    fund_duration = _independent_macaulay_duration(fund_pos, curve)
    expected_opaque_fund_charge = spread_stress_pct(RatingNotch.UNRATED, fund_duration) * fund_mv
    assert opaque.contributions_by_position["pos_fund"] == pytest.approx(expected_opaque_fund_charge, rel=1e-9)

    expanded = expand_look_through([corp_direct, fund_pos])
    look_through = compute_spread_scr(expanded, curve)

    corp_in_fund = next(p for p in expanded if p.id == "pos_fund::pos_corp")
    usd_in_fund = next(p for p in expanded if p.id == "pos_fund::pos_usd_corp")
    expected_corp_in_fund_charge = spread_stress_pct(RatingNotch.A2, _independent_macaulay_duration(corp_in_fund, curve)) * CORP_IN_FUND_MV
    expected_usd_in_fund_charge = spread_stress_pct(RatingNotch.A3, _independent_macaulay_duration(usd_in_fund, curve)) * USD_IN_FUND_MV
    assert look_through.contributions_by_position["pos_fund::pos_corp"] == pytest.approx(expected_corp_in_fund_charge, rel=1e-9)
    assert look_through.contributions_by_position["pos_fund::pos_usd_corp"] == pytest.approx(expected_usd_in_fund_charge, rel=1e-9)

    expected_direct_charge = spread_stress_pct(RatingNotch.A2, _independent_macaulay_duration(corp_direct, curve)) * CORP_DIRECT_MV
    total_expected = expected_direct_charge + expected_corp_in_fund_charge + expected_usd_in_fund_charge
    assert look_through.scr_spread == pytest.approx(total_expected, rel=1e-9)

    # look-through gives a materially different (here: much lower) total than the opaque UNRATED fallback
    assert look_through.scr_spread != pytest.approx(opaque.scr_spread, rel=1e-2)


def test_full_scr_uses_look_through_automatically():
    from alm.ma.engine import compute_ma
    from alm.ma.fs_rate import fs_rate_for_assets
    from alm.scr import compute_full_standard_formula_scr
    from alm.examples.golden_toy import build_liability

    curve, corp_direct, fund_pos = _portfolio()
    liability = build_liability()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    fs_table = build_fs_table()

    full = compute_full_standard_formula_scr(cfs, [corp_direct, fund_pos], curve, fs_table, curve.valuation_date)

    assert "pos_fund::pos_corp" in full.spread.contributions_by_position
    assert "pos_fund" not in full.spread.contributions_by_position
    assert full.currency.total_fx_exposure == pytest.approx(USD_IN_FUND_MV, rel=1e-9)
