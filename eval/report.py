"""Generate comparison reports from eval run artifacts."""

from __future__ import annotations

import json
from pathlib import Path

_ARTIFACTS_DIR = Path("artifacts")


def load_run(run_id: str) -> dict[str, object]:
    path = _ARTIFACTS_DIR / run_id / "raw_results.json"
    if not path.exists():
        raise FileNotFoundError(f"Run artifacts not found: {path}")
    with open(path) as f:
        return json.load(f)  # type: ignore[return-value]


def latest_run_id() -> str | None:
    dirs = sorted(_ARTIFACTS_DIR.iterdir(), reverse=True)
    for d in dirs:
        if (d / "raw_results.json").exists():
            return d.name
    return None
