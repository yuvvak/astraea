"""HP MA benefit cap golden test, using the already-established HP Test 4
scenario (base MA benefit £306,299.44) combined with the corporate
Scenario B MA benefit (£52,037.19) from test_golden_ma.py as the "rest of
portfolio" MA benefit, for a hand-checkable breach case.
"""

from __future__ import annotations

import pytest

from alm.examples.golden_toy import build_corporate_bond_position, build_fs_table, build_hp_bond, build_liability, build_rfr_curve
from alm.ma.engine import compute_ma
from alm.ma.fs_rate import fs_rate_for_assets
from alm.ma.hp_cap import HP_CAP_RATIO, check_hp_cap

HP_MA_BENEFIT = 306_299.43986471003  # from test_var_and_hp_tests.py::test_test4, base_ma.ma_benefit
NON_HP_MA_BENEFIT = 52_037.189652724424  # from test_golden_ma.py, Scenario B ma_benefit


def test_hp_benefit_matches_the_established_test4_scenario():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    hp = build_hp_bond(500_000.0)
    fs_table = build_fs_table()
    fs_entry = fs_table.lookup(hp.currency, hp.rating, hp.sector, hp.maturity_years)
    fs_rate = fs_entry.fs_bps_floored / 10_000.0
    result = compute_ma(cfs, 500_000.0, fs_rate, curve)
    assert result.ma_benefit == pytest.approx(HP_MA_BENEFIT, rel=1e-9)


def test_hp_cap_breach_on_a_hp_heavy_portfolio():
    total = HP_MA_BENEFIT + NON_HP_MA_BENEFIT
    result = check_hp_cap(HP_MA_BENEFIT, total)

    expected_ratio = HP_MA_BENEFIT / total
    assert result.ratio == pytest.approx(expected_ratio, rel=1e-9)
    assert result.ratio > HP_CAP_RATIO
    assert result.breach is True

    expected_allowed = HP_CAP_RATIO * total
    assert result.allowed_hp_benefit == pytest.approx(expected_allowed, rel=1e-9)
    expected_excess = HP_MA_BENEFIT - expected_allowed
    assert result.excess_benefit == pytest.approx(expected_excess, rel=1e-9)
    assert result.excess_benefit > 0


def test_hp_cap_passes_on_a_hp_light_portfolio():
    # same HP benefit, but a much larger non-HP book behind it, enough to push
    # the HP share below 10% (needs total > HP_MA_BENEFIT / 0.10 ~= £3.06m)
    total = HP_MA_BENEFIT + NON_HP_MA_BENEFIT * 60
    result = check_hp_cap(HP_MA_BENEFIT, total)

    assert result.ratio < HP_CAP_RATIO
    assert result.breach is False
    assert result.excess_benefit == 0.0


def test_hp_cap_ratio_is_the_regulatory_default():
    assert HP_CAP_RATIO == pytest.approx(0.10)


def test_zero_total_ma_benefit_is_handled_without_division_error():
    result = check_hp_cap(hp_ma_benefit=0.0, total_ma_benefit=0.0)
    assert result.ratio == 0.0
    assert result.breach is False
    assert result.excess_benefit == 0.0
