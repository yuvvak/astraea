"""Basic Own Funds and SCR coverage ratio.

The headline solvency metric real insurers publish -- Rothesay Life Plc
discloses an SCR coverage ratio of 249% for FY2025 (see the "Rothesay
Benchmark" artifact and Annual Report and Accounts 2025, Note F.1) -- is
Own Funds eligible to meet the SCR, divided by the SCR itself. This
engine already computes the SCR (`alm/scr/standard_formula.py`) and the
Risk Margin (`alm/rm/risk_margin.py`), but had never turned those into a
coverage ratio because it never computed Own Funds. This module closes
that gap.

`compute_own_funds` uses real Solvency II methodology: Basic Own Funds is
the excess of assets over liabilities, where "liabilities" here means
Technical Provisions -- BEL discounted with the Matching Adjustment, plus
the Risk Margin. It deliberately stops at "Basic" Own Funds and does not
attempt Solvency II's capital-tiering system (Tier 1/2/3, restricted vs
unrestricted, eligibility caps against the SCR/MCR), because this engine
has never modeled a firm's actual capital structure (share capital,
subordinated loan notes, Restricted Tier 1 debt) -- only the asset and
liability side of an MA portfolio. A real firm's ELIGIBLE Own Funds (what
actually counts toward its coverage ratio) can differ from Basic Own
Funds once ineligible or restricted capital is excluded: Rothesay's own
FY2025 disclosure shows Own Funds available of £9,272m against Own Funds
eligible of £9,116m (Note F.1). This module reports the former, clearly
labelled `basic_own_funds`, not the latter.

Distinct from, and not to be confused with, `StressLegResult.own_funds`
in `alm/stresses/runner.py`: that is a lighter-weight "asset market value
minus BEL with MA" figure (Risk Margin not subtracted), used there only
to gauge how sensitive an MA portfolio's own funds are to a stress
scenario -- not to produce a genuine SCR coverage ratio, which needs the
Risk Margin included in Technical Provisions to be Solvency-II-faithful.
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
