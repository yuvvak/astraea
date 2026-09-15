"""Basic Own Funds and SCR coverage ratio: the headline solvency metric
insurers actually publish (Rothesay Life discloses 249% for FY2025).

Basic Own Funds is assets minus Technical Provisions (BEL with MA, plus
Risk Margin). This deliberately stops short of Solvency II's full capital
tiering (Tier 1/2/3, restricted vs unrestricted, eligibility caps) since
this engine has never modelled a firm's actual capital structure, so what
it reports is "basic" own funds, not "eligible" own funds. A real firm's
eligible figure is usually a bit lower once restricted capital drops out
(Rothesay: £9,272m available vs £9,116m eligible for FY2025).

Not the same thing as `StressLegResult.own_funds` in
`alm/stresses/runner.py`, which is a lighter asset-minus-BEL figure with
no Risk Margin, used there just to gauge stress sensitivity rather than
produce a real coverage ratio.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from alm.ma.engine import MAResult


class OwnFundsResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_market_value: float
    bel_with_ma: float
    risk_margin: float
    technical_provisions: float  # bel_with_ma + risk_margin
    basic_own_funds: float  # asset_market_value - technical_provisions
    scr_total: float
    coverage_ratio: float | None  # basic_own_funds / scr_total; None if scr_total <= 0


def compute_own_funds(ma: MAResult, risk_margin: float, scr_total: float) -> OwnFundsResult:
    if risk_margin < 0:
        raise ValueError(f"risk_margin must be >= 0, got {risk_margin}")
    if scr_total < 0:
        raise ValueError(f"scr_total must be >= 0, got {scr_total}")

    technical_provisions = ma.bel_with_ma + risk_margin
    basic_own_funds = ma.asset_market_value - technical_provisions
    coverage_ratio = basic_own_funds / scr_total if scr_total > 0 else None

    return OwnFundsResult(
        asset_market_value=ma.asset_market_value,
        bel_with_ma=ma.bel_with_ma,
        risk_margin=risk_margin,
        technical_provisions=technical_provisions,
        basic_own_funds=basic_own_funds,
        scr_total=scr_total,
        coverage_ratio=coverage_ratio,
    )
