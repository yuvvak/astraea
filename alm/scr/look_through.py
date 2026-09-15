"""Look-through funds: expand any `FundHolding` position into its
constituent positions before running SF SCR sub-modules that need name-,
currency-, or rating-level granularity (spread, currency, concentration,
counterparty default). Treating a fund as one opaque exposure would hide
the concentration and currency risk sitting inside it. Non-fund positions
pass through unchanged, and funds nested inside funds are expanded
recursively.
"""

from __future__ import annotations

from alm.contracts.assets import AssetPosition, FundHolding


def expand_look_through(positions: list[AssetPosition]) -> list[AssetPosition]:
    expanded: list[AssetPosition] = []
    for p in positions:
        if isinstance(p.instrument, FundHolding):
            for constituent in p.instrument.constituent_positions:
                scaled = constituent.model_copy(update={
                    "id": f"{p.id}::{constituent.id}",
                    "units": constituent.units * p.units,
                    "market_value": constituent.market_value * p.units if constituent.market_value is not None else None,
                })
                expanded.extend(expand_look_through([scaled]))
        else:
            expanded.append(p)
    return expanded
