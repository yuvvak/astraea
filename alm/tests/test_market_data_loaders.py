"""market_data loader golden tests: round-trip an RFR curve and an FS table
through the documented XLSX format, and prove a curve/FS table loaded this
way reproduces the exact golden Scenario B MA figure (135.4464bp) when fed
the same inputs as the hand-built golden_toy fixtures, not just that the
loader parses without error.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from alm.contracts.curves import Curve
from alm.contracts.fs import AssetSector, FSEntry, FSTable, RatingNotch
from alm.examples.golden_toy import CURRENCY, RFR_FLAT_RATE, build_liability
from alm.ma.engine import compute_ma
from alm.ma.fs_rate import fs_rate_for_assets
from alm.market_data import (
    load_fs_table_from_pra_workbook,
    load_fs_table_from_xlsx,
    load_rfr_curve_from_pra_workbook,
    load_rfr_curve_from_xlsx,
    save_fs_table_to_xlsx,
    save_rfr_curve_to_xlsx,
)

VALUATION_DATE = date(2026, 9, 8)

PRA_REFERENCE_DIR = Path(__file__).resolve().parents[1] / "market_data" / "pra_reference"
REAL_RFR_PATH = PRA_REFERENCE_DIR / "risk-free-curves-31-aug-2026.xlsx"
REAL_FS_PATH = PRA_REFERENCE_DIR / "risk-free-fs-pod-and-cod-31-aug-2026.xlsx"


def test_rfr_curve_round_trips_exactly(tmp_path):
    curve = Curve.flat(RFR_FLAT_RATE, currency=CURRENCY, valuation_date=VALUATION_DATE, name="golden_flat")
    path = tmp_path / "rfr.xlsx"
    save_rfr_curve_to_xlsx(curve, path)

    loaded = load_rfr_curve_from_xlsx(path, CURRENCY, VALUATION_DATE)
    assert loaded.terms == curve.terms
    assert loaded.rates == curve.rates
    for t in (0.5, 1.0, 5.0, 10.0, 50.0):
        assert loaded.zero_rate(t) == pytest.approx(curve.zero_rate(t), rel=1e-12)


def test_rfr_loader_rejects_missing_columns(tmp_path):
    import pandas as pd
    bad_path = tmp_path / "bad_rfr.xlsx"
    pd.DataFrame({"currency": ["GBP"], "term_years": [1.0]}).to_excel(bad_path, index=False)  # missing "rate"
    with pytest.raises(ValueError, match="missing required columns"):
        load_rfr_curve_from_xlsx(bad_path, "GBP", VALUATION_DATE)


def test_rfr_loader_rejects_unknown_currency(tmp_path):
    curve = Curve.flat(0.04, currency="GBP", valuation_date=VALUATION_DATE)
    path = tmp_path / "rfr.xlsx"
    save_rfr_curve_to_xlsx(curve, path)
    with pytest.raises(ValueError, match="no rows for currency"):
        load_rfr_curve_from_xlsx(path, "USD", VALUATION_DATE)


def test_fs_table_round_trips_exactly(tmp_path):
    fs_table = FSTable(source="test", entries=(
        FSEntry(currency="GBP", rating=RatingNotch.A2, sector=AssetSector.NON_FINANCIAL, term_years=50.0, fs_pd_bps=18.0, fs_cod_bps=7.0, ltas_floor_bps=0.0),
        FSEntry(currency="USD", rating=RatingNotch.A3, sector=AssetSector.NON_FINANCIAL, term_years=50.0, fs_pd_bps=20.0, fs_cod_bps=8.0, ltas_floor_bps=0.0),
    ))
    path = tmp_path / "fs.xlsx"
    save_fs_table_to_xlsx(fs_table, path)

    loaded = load_fs_table_from_xlsx(path)
    entry = loaded.lookup("GBP", RatingNotch.A2, AssetSector.NON_FINANCIAL, 10.0)
    assert entry.fs_pd_bps == pytest.approx(18.0)
    assert entry.fs_cod_bps == pytest.approx(7.0)
    assert entry.fs_bps_floored == pytest.approx(25.0)

    entry_usd = loaded.lookup("USD", RatingNotch.A3, AssetSector.NON_FINANCIAL, 10.0)
    assert entry_usd.fs_bps_floored == pytest.approx(28.0)


def test_loaded_curve_and_fs_table_reproduce_the_golden_ma_figure(tmp_path):
    """The real proof: feed a curve and FS table loaded from XLSX, not built
    directly in code, through the exact same MA calculation as golden
    Scenario B, and confirm it reproduces 135.4464bp to nine decimal places."""
    from alm.contracts.assets import AssetPosition, Bond

    curve = Curve.flat(RFR_FLAT_RATE, currency=CURRENCY, valuation_date=VALUATION_DATE, name="golden_flat")
    rfr_path = tmp_path / "rfr.xlsx"
    save_rfr_curve_to_xlsx(curve, rfr_path)
    loaded_curve = load_rfr_curve_from_xlsx(rfr_path, CURRENCY, VALUATION_DATE)

    fs_table = FSTable(source="golden", entries=(
        FSEntry(currency=CURRENCY, rating=RatingNotch.A2, sector=AssetSector.NON_FINANCIAL, term_years=50.0, fs_pd_bps=18.0, fs_cod_bps=7.0, ltas_floor_bps=0.0),
    ))
    fs_path = tmp_path / "fs.xlsx"
    save_fs_table_to_xlsx(fs_table, fs_path)
    loaded_fs = load_fs_table_from_xlsx(fs_path)

    liability = build_liability()
    cfs = liability.best_estimate_cashflows(loaded_curve.valuation_date)

    bond = Bond(
        id="CORP_A2_4_75pct_10y", currency=CURRENCY, notional=780_000.0, coupon_rate=0.0475,
        coupon_frequency=1, maturity_years=10.0, rating=RatingNotch.A2, sector=AssetSector.NON_FINANCIAL,
    )
    position = AssetPosition(id="pos_corp", instrument=bond, market_value=750_000.0)

    fs_rate = fs_rate_for_assets([position], loaded_fs, loaded_curve.valuation_date, loaded_curve)
    result = compute_ma(cfs, 750_000.0, fs_rate, loaded_curve)

    assert result.ma_bps == pytest.approx(135.4463645158851, rel=1e-9)
    assert result.ma_benefit == pytest.approx(52_037.189652724424, rel=1e-9)


# ---------------------------------------------------------- real PRA workbook ---
#
# These load the ACTUAL Bank of England-published files checked into
# `alm/market_data/pra_reference/` (see SOURCE.md there) -- real published
# data changes every month, so these assert plausibility, not a hand-solved
# golden number (see `test_loaded_curve_and_fs_table_reproduce_the_golden_ma_figure`
# above for that proof against the documented v1 format instead).

def test_real_rfr_workbook_loads_a_sane_gbp_curve():
    curve = load_rfr_curve_from_pra_workbook(REAL_RFR_PATH, "GBP", date(2026, 8, 31))

    assert curve.currency == "GBP"
    assert curve.terms[0] == 1.0
    assert curve.terms[-1] >= 100.0  # PRA publishes out to 150y
    assert list(curve.terms) == sorted(curve.terms)  # strictly increasing, as Curve requires
    for t in (1, 10, 30, 50, 100):
        assert -0.02 < curve.zero_rate(t) < 0.15  # plausible nominal GBP rate range


def test_real_rfr_workbook_rejects_unknown_currency():
    with pytest.raises(ValueError, match="no curve code starting with"):
        load_rfr_curve_from_pra_workbook(REAL_RFR_PATH, "ZZZ", date(2026, 8, 31))


def test_real_fs_workbook_loads_sane_gbp_entries_for_every_sourced_notch():
    fs_table = load_fs_table_from_pra_workbook(REAL_FS_PATH, "GBP")

    assert len(fs_table.entries) > 0
    seen_sectors = {e.sector for e in fs_table.entries}
    assert seen_sectors == {AssetSector.FINANCIAL, AssetSector.NON_FINANCIAL}

    # every sourced notch (see CQS_TO_RATING_NOTCHES) must have at least one entry
    from alm.market_data.fs_loader import CQS_TO_RATING_NOTCHES
    seen_ratings = {e.rating.value for e in fs_table.entries}
    for notches in CQS_TO_RATING_NOTCHES.values():
        for notch in notches:
            assert notch in seen_ratings

    entry = fs_table.lookup("GBP", RatingNotch.A2, AssetSector.NON_FINANCIAL, 10.0)
    assert 0.0 <= entry.fs_bps < 500.0  # plausible: a few hundred bps at most for an A-rated 10y bond
    assert entry.fs_pd_bps + entry.fs_cod_bps == pytest.approx(entry.fs_bps, rel=1e-9)

    # credit quality must be monotonically non-decreasing in FS at a fixed maturity:
    # A-rated (CQS2) must never cost MORE spread than BB-rated (CQS4) at the same term
    a_entry = fs_table.lookup("GBP", RatingNotch.A2, AssetSector.NON_FINANCIAL, 10.0)
    bb_entry = fs_table.lookup("GBP", RatingNotch.BB2, AssetSector.NON_FINANCIAL, 10.0)
    assert a_entry.fs_bps <= bb_entry.fs_bps
