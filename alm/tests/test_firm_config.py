"""alm/config/ golden test: round-trips a FirmConfig through JSON, confirms
its tolerance defaults are the SAME constants `validation.reconciliation`
already uses (not a second, possibly-diverging copy), and proves
`reconciliation_kwargs()` actually changes a real reconciliation report's
severity when overridden -- not just that the values are stored.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from alm.config import FirmConfig, load_firm_config, save_firm_config
from alm.validation.reconciliation import (
    DEFAULT_MATERIAL_TOLERANCE,
    DEFAULT_WATCH_TOLERANCE,
    CustomerFigures,
    DivergenceSeverity,
    build_reconciliation_report,
)

VALUATION_DATE = date(2026, 9, 8)


def test_default_tolerances_match_reconciliations_own_constants_not_a_second_copy():
    cfg = FirmConfig(valuation_date=VALUATION_DATE)
    assert cfg.material_tolerance == DEFAULT_MATERIAL_TOLERANCE
    assert cfg.watch_tolerance == DEFAULT_WATCH_TOLERANCE


def test_round_trips_through_json_exactly(tmp_path):
    cfg = FirmConfig(
        valuation_date=VALUATION_DATE, base_currency="GBP", reporting_currencies=("GBP", "USD"),
        matching_bucket_frequency="annual", scr_mode="standard_formula",
        material_tolerance=0.03, watch_tolerance=0.01,
    )
    path = tmp_path / "firm_config.json"
    save_firm_config(cfg, path)
    loaded = load_firm_config(path)
    assert loaded == cfg


def test_rejects_an_unrecognised_matching_bucket_frequency():
    with pytest.raises(ValidationError):
        FirmConfig(valuation_date=VALUATION_DATE, matching_bucket_frequency="fortnightly")


def test_reconciliation_kwargs_actually_changes_a_real_reports_severity():
    """independent MA = 135.4464bp, customer reports 140bp: a 3.37% relative
    gap -- material under the tighter default tolerance (2%), but only
    watch under a firm config that's set a looser 5% material tolerance."""
    customer = CustomerFigures(ma_bps=140.0)
    independent_ma_bps = 135.4463645158851

    default_cfg = FirmConfig(valuation_date=VALUATION_DATE)
    default_report = build_reconciliation_report(
        customer=customer, valuation_date=VALUATION_DATE, currency="GBP", liability_id="toy",
        independent_ma_bps=independent_ma_bps, independent_bel_basic_rfr=1.0, independent_bel_with_ma=1.0,
        independent_ma_benefit=1.0, independent_fs_rate_bps=1.0,
        **default_cfg.reconciliation_kwargs(),
    )
    assert default_report.overall_severity == DivergenceSeverity.MATERIAL

    lenient_cfg = FirmConfig(valuation_date=VALUATION_DATE, material_tolerance=0.05)
    lenient_report = build_reconciliation_report(
        customer=customer, valuation_date=VALUATION_DATE, currency="GBP", liability_id="toy",
        independent_ma_bps=independent_ma_bps, independent_bel_basic_rfr=1.0, independent_bel_with_ma=1.0,
        independent_ma_benefit=1.0, independent_fs_rate_bps=1.0,
        **lenient_cfg.reconciliation_kwargs(),
    )
    ma_comparison = next(c for c in lenient_report.comparisons if c.name == "MA (bps)")
    assert ma_comparison.severity == DivergenceSeverity.WATCH
