"""Firm FS additions: named add-ons to the published FS rate for
attestation, structure, construction, prepayment and HP risk. Kept as a
distinct, separately-reportable layer on top of
`fs_rate.fs_rate_for_assets`'s blended PD+CoD+LTAS rate, rather than
folded silently into it, since the annual MA attestation pack needs to
report these components individually, not just their sum.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FSAdditions(BaseModel):
    model_config = ConfigDict(frozen=True)

    attestation_bps: float = 0.0
    structure_bps: float = 0.0
    construction_bps: float = 0.0
    prepayment_bps: float = 0.0
    hp_bps: float = 0.0

    @property
    def total_bps(self) -> float:
        return self.attestation_bps + self.structure_bps + self.construction_bps + self.prepayment_bps + self.hp_bps

    @property
    def total_rate(self) -> float:
        return self.total_bps / 10_000.0


def apply_fs_additions(base_fs_rate: float, additions: FSAdditions) -> float:
    return base_fs_rate + additions.total_rate
