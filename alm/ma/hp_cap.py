"""HP MA benefit cap: aggregate MA benefit from Highly Predictable assets
must not exceed a set fraction of total MA benefit. 10% is the regulatory
default, named as a constant rather than inlined, and passed as a
parameter so a firm policy can override it without touching this function.

This module only checks and reports the breach and the excess amount, it
doesn't decide how to remediate. Reducing HP MA vs holding extra FS is a
firm policy choice, so callers act on `HPCapResult.breach` and
`excess_benefit` according to whatever remediation they choose.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

HP_CAP_RATIO = 0.10  # regulatory default: <= 10% of total MA benefit


class HPCapResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    hp_ma_benefit: float
    total_ma_benefit: float
    ratio: float
    cap_ratio: float
    breach: bool
    allowed_hp_benefit: float
    excess_benefit: float  # 0.0 when not breached


def check_hp_cap(hp_ma_benefit: float, total_ma_benefit: float, cap_ratio: float = HP_CAP_RATIO) -> HPCapResult:
    ratio = hp_ma_benefit / total_ma_benefit if total_ma_benefit > 0 else 0.0
    allowed = cap_ratio * total_ma_benefit
    breach = ratio > cap_ratio
    excess = max(0.0, hp_ma_benefit - allowed)

    return HPCapResult(
        hp_ma_benefit=hp_ma_benefit, total_ma_benefit=total_ma_benefit, ratio=ratio,
        cap_ratio=cap_ratio, breach=breach, allowed_hp_benefit=allowed, excess_benefit=excess,
    )
