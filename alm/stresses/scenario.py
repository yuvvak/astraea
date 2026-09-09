"""Stress scenario definitions: a `StressSpec` names a shock and how to apply
it to the base curve / FS table / liability cash flows. File-based scenario
sets (project brief: "Combined LIST-style and firm ORSA scenarios via
scenario files") are a natural extension of this -- `StressSpec` is already
a pydantic model, so a scenario file is just a list of these serialised to
JSON/YAML; that loader is not built yet (v1 default: construct `StressSpec`
directly in code/tests), the shape is fixed here so it slots in later
without changing `runner.py`.

v1 covers three stress families, matching what the golden portfolio can
actually exercise:
  - parallel nominal rate shock (curve_shift_bps)
  - credit spread widening (fs_widening_multiplier, applied to FS PD+CoD
    multiplicatively -- "instantaneous downgrade matrices" and "rating
    migration" are more granular versions of this same mechanism, deferred
    until a fuller asset library exists)
  - a longevity/mortality-style liability shock (liability_shock_multiplier,
    a crude uniform scaling proxy -- real longevity/mortality stresses
    belong in Prophet or the reference projector re-running with a shocked
    assumption set, not a flat multiplier; this is a placeholder for the
    "insurance stresses" family until that's wired up)
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from alm.contracts.cashflows import CashFlowVector
from alm.contracts.curves import Curve
from alm.contracts.fs import FSEntry, FSTable


class StressSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    curve_shift: float = 0.0                    # additive, decimal (e.g. -0.01 for -100bp)
    fs_widening_multiplier: float = 1.0          # multiplicative on fs_pd_bps and fs_cod_bps
    liability_shock_multiplier: float = 1.0      # multiplicative on every liability cash flow amount


def apply_stress(
    spec: StressSpec,
    base_curve: Curve,
    base_fs_table: FSTable,
    base_liability_cfs: CashFlowVector,
) -> tuple[Curve, FSTable, CashFlowVector]:
    stressed_curve = base_curve.shift_parallel(spec.curve_shift, name=f"{base_curve.name}__{spec.name}") if spec.curve_shift else base_curve

    if spec.fs_widening_multiplier != 1.0:
        widened_entries = tuple(
            FSEntry(
                currency=e.currency, rating=e.rating, sector=e.sector, term_years=e.term_years,
                fs_pd_bps=e.fs_pd_bps * spec.fs_widening_multiplier,
                fs_cod_bps=e.fs_cod_bps * spec.fs_widening_multiplier,
                ltas_floor_bps=e.ltas_floor_bps,
            )
            for e in base_fs_table.entries
        )
        stressed_fs_table = FSTable(source=f"{base_fs_table.source}__{spec.name}", entries=widened_entries)
    else:
        stressed_fs_table = base_fs_table

    stressed_liability_cfs = (
        base_liability_cfs.scale(spec.liability_shock_multiplier, id_suffix=f"__{spec.name}")
        if spec.liability_shock_multiplier != 1.0
        else base_liability_cfs
    )

    return stressed_curve, stressed_fs_table, stressed_liability_cfs
