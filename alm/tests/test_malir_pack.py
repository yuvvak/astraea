"""MALIR attestation pack golden test: FS additions must reduce MA by
exactly their total in bps, the HP cap breach must match the standalone
hp_cap calculation exactly, and the rendered table's Result/Threshold
columns must not repeat the earlier swap bug from the general reporting
pack.
"""

from __future__ import annotations

import pytest

from alm.examples.golden_toy import build_corporate_bond_position, build_fs_table, build_hp_bond, build_liability, build_rfr_curve
from alm.ma import FSAdditions, check_hp_cap
from alm.ma.engine import compute_ma
from alm.ma.fs_rate import fs_rate_for_assets
from alm.reporting import MatchingTestPack, build_malir_pack, render_malir_markdown
from alm.tests_pra.hp_loss_test import run_test4

ADDITIONS = FSAdditions(attestation_bps=2.0, structure_bps=1.5, construction_bps=0.5, prepayment_bps=1.0, hp_bps=3.0)


def _pack():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    fs_table = build_fs_table()
    corp = build_corporate_bond_position(750_000.0)
    base_fs = fs_rate_for_assets([corp], fs_table, curve.valuation_date, curve)
    ma = compute_ma(cfs, 750_000.0, base_fs + ADDITIONS.total_rate, curve)

    hp = build_hp_bond(500_000.0)
    fs_entry = fs_table.lookup(hp.currency, hp.rating, hp.sector, hp.maturity_years)
    fs_hp = fs_entry.fs_bps_floored / 10_000.0
    t4 = run_test4(cfs, hp, 500_000.0, fs_hp, curve, curve.valuation_date)
    hp_cap = check_hp_cap(t4.base_ma.ma_benefit, t4.base_ma.ma_benefit + ma.ma_benefit)

    return build_malir_pack(
        valuation_date=curve.valuation_date, currency="GBP", ma=ma, base_fs_rate=base_fs,
        fs_additions=ADDITIONS, hp_cap=hp_cap, matching_tests=MatchingTestPack(test4=t4),
    ), base_fs


def test_ma_rate_drops_by_exactly_the_additions_total():
    pack, base_fs = _pack()
    # base scenario B MA (no additions) is the established 135.4464bp golden figure
    expected_ma_bps_with_additions = 135.4463645158851 - ADDITIONS.total_bps
    assert pack.ma.ma_bps == pytest.approx(expected_ma_bps_with_additions, rel=1e-9)
    assert pack.fs_rate_with_additions == pytest.approx(base_fs + ADDITIONS.total_rate, rel=1e-9)


def test_hp_cap_matches_the_standalone_calculation():
    pack, _ = _pack()
    assert pack.hp_cap is not None
    assert pack.hp_cap.hp_ma_benefit == pytest.approx(306_299.43986471003, rel=1e-6)
    assert pack.hp_cap.breach is True
    assert pack.hp_cap.ratio > 0.10


def test_markdown_result_and_threshold_columns_are_correctly_ordered():
    pack, _ = _pack()
    md = render_malir_markdown(pack)

    test4_line = next(l for l in md.splitlines() if l.startswith("| 4 -"))
    cells = [c.strip() for c in test4_line.strip("|").split("|")]
    _, result, threshold, status = cells

    assert result.endswith("%")
    assert threshold.startswith("<=")
    assert status == "PASS"


def test_pack_without_hp_cap_still_renders():
    liability = build_liability()
    curve = build_rfr_curve()
    cfs = liability.best_estimate_cashflows(curve.valuation_date)
    fs_table = build_fs_table()
    corp = build_corporate_bond_position(750_000.0)
    base_fs = fs_rate_for_assets([corp], fs_table, curve.valuation_date, curve)
    ma = compute_ma(cfs, 750_000.0, base_fs, curve)

    pack = build_malir_pack(valuation_date=curve.valuation_date, currency="GBP", ma=ma, base_fs_rate=base_fs, fs_additions=FSAdditions())
    md = render_malir_markdown(pack)

    assert "not applicable" in md
    assert "# Annual MA Attestation Data Pack" in md
