"""SIG cap golden test: MA on sub-investment-grade assets is capped at the
same rate an investment-grade asset of the same duration/class would earn,
by lifting FS just enough to bring MA down to the cap exactly. Investment-
grade assets are never touched, even when their raw MA is far above the
cap value (the cap is SIG-only by definition).
"""

from __future__ import annotations

import pytest

from alm.contracts.fs import RatingNotch
from alm.examples.golden_toy import build_liability, build_rfr_curve
from alm.ma.engine import compute_ma
from alm.ma.sig_cap import SIG_CAP_MA_RATE, compute_ma_with_sig_cap

MARKET_VALUE = 500_000.0
FS_RATE = 0.05


def _liability_cfs():
    liability = build_liability()
    curve = build_rfr_curve()
    return liability.best_estimate_cashflows(curve.valuation_date), curve


def test_sig_asset_is_capped_to_exactly_the_cap_rate():
    cfs, curve = _liability_cfs()
    result = compute_ma_with_sig_cap(cfs, MARKET_VALUE, FS_RATE, curve, RatingNotch.BB1)

    assert result.pre_cap.ma_rate > SIG_CAP_MA_RATE  # confirms the scenario actually breaches the cap
    assert result.capped is True
    assert result.result.ma_rate == pytest.approx(SIG_CAP_MA_RATE, abs=1e-9)
    assert result.result.ma_bps == pytest.approx(150.0, abs=1e-6)

    # independent cross-check: lifting FS by fs_lift_rate and recomputing MA directly
    # (not via compute_ma_with_sig_cap) must reproduce the same capped result
    independent = compute_ma(cfs, MARKET_VALUE, FS_RATE + result.fs_lift_rate, curve)
    assert independent.ma_rate == pytest.approx(SIG_CAP_MA_RATE, abs=1e-9)
    assert independent.ma_benefit == pytest.approx(result.result.ma_benefit, rel=1e-9)


def test_fs_lift_equals_the_breach_amount():
    cfs, curve = _liability_cfs()
    result = compute_ma_with_sig_cap(cfs, MARKET_VALUE, FS_RATE, curve, RatingNotch.BB1)

    expected_lift = result.pre_cap.ma_rate - SIG_CAP_MA_RATE
    assert result.fs_lift_rate == pytest.approx(expected_lift, abs=1e-12)
    assert result.fs_lift_rate > 0


def test_investment_grade_asset_is_never_capped():
    cfs, curve = _liability_cfs()
    # same inputs that triggered a breach for BB1 above
    result = compute_ma_with_sig_cap(cfs, MARKET_VALUE, FS_RATE, curve, RatingNotch.A2)

    assert result.pre_cap.ma_rate > SIG_CAP_MA_RATE  # would have breached the cap if it applied
    assert result.capped is False
    assert result.fs_lift_rate == 0.0
    assert result.result.ma_bps == pytest.approx(result.pre_cap.ma_bps, rel=1e-9)


def test_sig_asset_under_the_cap_is_left_alone():
    cfs, curve = _liability_cfs()
    # a much smaller FS-implied spread, MV close to BEL so raw MA stays below the cap
    bel = cfs.pv(curve)
    result = compute_ma_with_sig_cap(cfs, bel * 0.999, 0.0010, curve, RatingNotch.BB1)

    assert result.pre_cap.ma_rate <= SIG_CAP_MA_RATE
    assert result.capped is False
    assert result.result.ma_bps == pytest.approx(result.pre_cap.ma_bps, rel=1e-9)
