"""Firm-wide configuration (named in the original brief, previously empty --
README's "Not yet built" gap: "valuation date, currency list, matching-
bucket frequency and materiality thresholds are all still passed as
explicit function arguments throughout, with no single place to set
firm-wide defaults").

`FirmConfig` is that single place: a pydantic model a firm can load from a
JSON file (same pattern as `stresses.scenario_loader`'s `StressSpec` sets),
review, and version-control, rather than hunting through call sites for the
right default to override. It does NOT force every consuming function to
take a `FirmConfig` parameter -- most of this engine's functions already
take valuation date/currency/tolerances explicitly, a deliberately testable
design this module doesn't change. Instead, `FirmConfig` centralises the
firm's chosen values and exposes small helpers (e.g.
`reconciliation_kwargs`) that hand them to existing call sites, so a firm
edits one file instead of several call sites.

`material_tolerance` / `watch_tolerance` default to
`validation.reconciliation`'s existing constants (the canonical values),
not a second, possibly-diverging copy.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from alm.validation.reconciliation import DEFAULT_MATERIAL_TOLERANCE, DEFAULT_WATCH_TOLERANCE

MatchingBucketFrequency = Literal["annual", "quarterly", "monthly"]
ScrMode = Literal["standard_formula", "internal_model"]
HypothecationAlgorithm = Literal["greedy_nearest_maturity"]


class FirmConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    valuation_date: date
    base_currency: str = Field("GBP", min_length=3, max_length=3)
    reporting_currencies: tuple[str, ...] = Field(
        ("GBP",), description="Currencies this firm's MA portfolio(s) are reported in; base_currency need not be the only one."
    )
    matching_bucket_frequency: MatchingBucketFrequency = Field(
        "annual",
        description="Documents this engine's existing assumption (every liability/asset cash "
        "flow model in alm/contracts/ and alm/ma/hypothecation.py projects annual periods) -- "
        "not yet a live switch: changing this value alone does not reproject cash flows at a "
        "different frequency. A documented v1 boundary, not a silent gap.",
    )
    scr_mode: ScrMode = Field("standard_formula", description="Confirmed firm default per README's 'Open inputs' section.")
    hypothecation_algorithm: HypothecationAlgorithm = Field(
        "greedy_nearest_maturity", description="The only algorithm `ma/hypothecation.py` implements; named here so a future second algorithm has a place to be selected."
    )
    material_tolerance: float = Field(DEFAULT_MATERIAL_TOLERANCE, gt=0, description="Reconciliation: relative difference above which a figure is flagged material.")
    watch_tolerance: float = Field(DEFAULT_WATCH_TOLERANCE, gt=0, description="Reconciliation: relative difference above which a figure is flagged watch.")

    def reconciliation_kwargs(self) -> dict[str, float]:
        """Ready to splat into `validation.reconciliation.build_reconciliation_report`
        or `compare_figure`: `build_reconciliation_report(..., **cfg.reconciliation_kwargs())`."""
        return {"material_tolerance": self.material_tolerance, "watch_tolerance": self.watch_tolerance}


def load_firm_config(path: str | Path) -> FirmConfig:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return FirmConfig(**data)


def save_firm_config(config: FirmConfig, path: str | Path) -> None:
    path = Path(path)
    path.write_text(json.dumps(config.model_dump(mode="json"), indent=2), encoding="utf-8")
