"""File-based scenario sets for `StressSpec` (project brief: "Combined
LIST-style and firm ORSA scenarios via scenario files"). A scenario file is
just a JSON list of `StressSpec`-shaped objects; since `StressSpec` is
already a pydantic model, loading is validation, not parsing, so a
malformed scenario file fails loudly rather than silently producing a
no-op stress.
"""

from __future__ import annotations

import json
from pathlib import Path

from .scenario import StressSpec


def load_scenario_set(path: str | Path) -> list[StressSpec]:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"scenario file {path} must contain a JSON list of scenario objects, got {type(data).__name__}")
    return [StressSpec(**entry) for entry in data]


def save_scenario_set(specs: list[StressSpec], path: str | Path) -> None:
    path = Path(path)
    payload = [spec.model_dump() for spec in specs]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
