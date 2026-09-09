"""Prophet extract adapter: eligibility gate + cash flow mapping + netting +
aggregation, checked against hand-computable expectations for each of the
six model points in `examples.prophet_fixture`.
"""

from __future__ import annotations

import pytest

from alm.examples.golden_toy import build_rfr_curve
from alm.examples.prophet_fixture import CURRENCY, build_extract_dataframe
from alm.prophet_io.adapter import aggregate_net_liability_cashflows, load_prophet_extract


@pytest.fixture()
def loaded(tmp_path):
    csv_path = tmp_path / "prophet_extract.csv"
    build_extract_dataframe().to_csv(csv_path, index=False)
    return load_prophet_extract(csv_path)


def test_ineligible_model_points_are_excluded_with_correct_citations(loaded):
    excluded_ids = {r.model_point_id for r in loaded.excluded}
    assert excluded_ids == {"MP003", "MP005", "MP006"}

    by_id = {r.model_point_id: r for r in loaded.excluded}
    assert "unit_linked" in by_id["MP003"].reason
    assert "MA 2.2" in by_id["MP003"].citation

    assert "future_premium" in by_id["MP005"].reason
    assert "2.2(1)" in by_id["MP005"].citation or "2.5" in by_id["MP005"].citation

    assert "constrained_surrender_flag" in by_id["MP006"].reason
    assert "2.2(4)(b)" in by_id["MP006"].citation

    # none of the excluded model points' cash flows leak into the eligible sets
    for mpid in excluded_ids:
        assert mpid not in loaded.eligible_net_cashflows
        assert mpid not in loaded.eligible_gross_cashflows


def test_eligible_model_points_present_with_correct_eligibility_flags(loaded):
    eligible_ids = set(loaded.eligible_net_cashflows.keys())
    assert eligible_ids == {"MP001", "MP002", "MP004"}

    assert loaded.eligibility_by_model_point["MP001"].eligible_element is False
    assert loaded.eligibility_by_model_point["MP002"].eligible_element is False
    assert loaded.eligibility_by_model_point["MP004"].eligible_element is True  # WP guaranteed element


def test_mp002_reinsurance_recovery_nets_off_benefit_and_expense(loaded):
    net = loaded.eligible_net_cashflows["MP002"]
    # 30,000 benefit + 300 expense - 2,000 reinsurance recovery = 28,300 per year, for t=1,2,3
    assert len(net.flows) == 3
    for cf in net.flows:
        assert cf.amount == pytest.approx(28_300.0)


def test_mp001_gross_cashflows_kept_separate_by_kind_for_audit(loaded):
    gross = loaded.eligible_gross_cashflows["MP001"]
    total_benefit = sum(cf.amount for cf in gross.flows if cf.kind.value == "benefit")
    total_expense = sum(cf.amount for cf in gross.flows if cf.kind.value == "expense")
    assert total_benefit == pytest.approx(150_000.0)  # 50,000 x 3 years
    assert total_expense == pytest.approx(1_500.0)     # 500 x 3 years


def test_aggregation_sums_across_model_points_at_the_same_time(loaded):
    """This is the regression check for the same-time dict-accumulation bug
    fixed in ma/hypothecation.py and tests_pra/accumulated_cf_shortfall.py:
    three eligible model points all have a cash flow at t=1,2,3, so the
    aggregated liability vector must reflect the SUM of all three at each
    time, not just the last one processed."""
    aggregated = aggregate_net_liability_cashflows(loaded, CURRENCY, id="toy_prophet_liability")
    curve = build_rfr_curve()

    # expected net per year: MP001 (50,500) + MP002 (28,300) + MP004 (10,000) = 88,800
    expected_annual = 50_500.0 + 28_300.0 + 10_000.0
    by_time: dict[float, float] = {}
    for cf in aggregated.flows:
        by_time[cf.time] = by_time.get(cf.time, 0.0) + cf.amount
    assert by_time == pytest.approx({1.0: expected_annual, 2.0: expected_annual, 3.0: expected_annual})

    expected_pv = sum(expected_annual * curve.discount_factor(t) for t in (1, 2, 3))
    assert aggregated.pv(curve) == pytest.approx(expected_pv, rel=1e-9)
