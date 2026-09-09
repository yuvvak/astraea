"""FS additions golden test: named components sum exactly, and applying
them to a base FS rate is plain addition, cross-checked by hand.
"""

from __future__ import annotations

import pytest

from alm.ma import FSAdditions, apply_fs_additions


def test_total_bps_is_the_exact_sum_of_named_components():
    additions = FSAdditions(attestation_bps=2.0, structure_bps=1.5, construction_bps=0.5, prepayment_bps=1.0, hp_bps=3.0)
    assert additions.total_bps == pytest.approx(8.0)
    assert additions.total_rate == pytest.approx(0.0008)


def test_apply_fs_additions_is_plain_addition():
    additions = FSAdditions(attestation_bps=2.0, structure_bps=1.5, construction_bps=0.5, prepayment_bps=1.0, hp_bps=3.0)
    result = apply_fs_additions(0.0025, additions)
    assert result == pytest.approx(0.0025 + 0.0008, rel=1e-9)
    assert result == pytest.approx(0.0033, rel=1e-9)


def test_zero_additions_is_a_no_op():
    additions = FSAdditions()
    assert additions.total_bps == 0.0
    assert apply_fs_additions(0.0025, additions) == pytest.approx(0.0025)
