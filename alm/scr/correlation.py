"""Generic Standard Formula correlation aggregation:

    SCR = sqrt( sum_i sum_j Corr(i,j) * SCR_i * SCR_j )

with Corr(i,i) = 1 implied. Used both for the market-risk sub-module
aggregation (spread, currency, concentration) and the top-level BSCR
aggregation (market, life, counterparty default), so the two-variable
formula used before this module existed (`sqrt(s^2 + l^2 + 2*rho*s*l)`) is
just this same formula for a 2x2 case -- `compute_map_standard_formula_scr`
is refactored to call this rather than reimplementing the algebra, with no
change in its result.
"""

from __future__ import annotations


def aggregate_via_correlation(values: dict[str, float], correlation: dict[tuple[str, str], float]) -> float:
    names = list(values.keys())
    total = 0.0
    for i in names:
        for j in names:
            if i == j:
                corr = 1.0
            else:
                corr = correlation.get((i, j))
                if corr is None:
                    corr = correlation.get((j, i), 0.0)
            total += corr * values[i] * values[j]
    return total ** 0.5 if total > 0 else 0.0
