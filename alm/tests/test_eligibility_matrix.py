"""Eligibility matrix generator: verified against specific known rows (not
just "it runs"), plus a regression check that the checked-in
ELIGIBILITY_MATRIX.md exactly matches what the current code generates, so
the two can never silently drift apart.
"""

from __future__ import annotations

from pathlib import Path

from alm.contracts.model_points import ProductCode
from alm.liabilities.eligibility_matrix import generate_matrix, render_markdown

REPO_ROOT = Path(__file__).resolve().parents[2]


def _find(rows, product_code: ProductCode, scenario_substring: str):
    matches = [r for r in rows if r.product_code == product_code and scenario_substring in r.scenario]
    assert len(matches) == 1, f"expected exactly one row for {product_code}/{scenario_substring!r}, got {len(matches)}"
    return matches[0]


def test_base_eligible_products_pass_baseline():
    rows = generate_matrix()
    for pc in (ProductCode.IND_ANNUITY_INPAY, ProductCode.BPA_INPAY, ProductCode.DEFERRED_ANNUITY):
        row = _find(rows, pc, "baseline, no disqualifying features")
        assert row.verdict == "eligible"


def test_eligible_element_products_are_flagged_as_elements_not_full_eligible():
    rows = generate_matrix()
    for pc in (ProductCode.WP_GUARANTEED_ELEMENT, ProductCode.IP_INPAY, ProductCode.GROUP_DIS_DEPENDANT):
        row = _find(rows, pc, "baseline, no disqualifying features")
        assert row.verdict == "eligible_element"


def test_always_ineligible_products_fail():
    rows = generate_matrix()
    for pc in (ProductCode.UNIT_LINKED, ProductCode.FUTURE_PREMIUM_PAYING, ProductCode.DISCRETIONARY_WITH_PROFITS):
        row = _find(rows, pc, "baseline")
        assert row.verdict == "fail"


def test_future_premium_flag_is_disqualifying_even_on_eligible_element_products():
    """Regression: this used to be silently exempted for eligible-element
    product codes, which is wrong because eligible elements are specifically
    DEFINED as not depending on future premiums; the flag being set is a
    data inconsistency, not a valid carve-out."""
    rows = generate_matrix()
    for pc in (ProductCode.IND_ANNUITY_INPAY, ProductCode.WP_GUARANTEED_ELEMENT, ProductCode.IP_INPAY, ProductCode.GROUP_DIS_DEPENDANT):
        row = _find(rows, pc, "plus future_premium_flag")
        assert row.verdict == "fail", f"{pc} with future_premium_flag should fail, got {row.verdict}"


def test_deferred_annuity_surrender_constrained_vs_unconstrained():
    rows = generate_matrix()
    constrained = _find(rows, ProductCode.DEFERRED_ANNUITY, "constrained (MA 2.2(4)(b) evidenced)")
    assert constrained.verdict == "eligible"

    unconstrained = _find(rows, ProductCode.DEFERRED_ANNUITY, "unconstrained")
    assert unconstrained.verdict == "fail"
    assert "2.2(4)(b)" in unconstrained.citation


def test_every_row_has_a_citation():
    rows = generate_matrix()
    assert len(rows) > 20
    for row in rows:
        assert row.citation, f"row {row.product_code}/{row.scenario} has no citation"
        assert row.reason, f"row {row.product_code}/{row.scenario} has no reason"


def test_checked_in_matrix_file_matches_current_code():
    checked_in = (REPO_ROOT / "ELIGIBILITY_MATRIX.md").read_text(encoding="utf-8")
    fresh = render_markdown()
    assert checked_in == fresh, (
        "ELIGIBILITY_MATRIX.md is stale: regenerate with "
        "`.venv/Scripts/python -c \"from alm.liabilities.eligibility_matrix import render_markdown; "
        "print(render_markdown())\" > ELIGIBILITY_MATRIX.md`"
    )
