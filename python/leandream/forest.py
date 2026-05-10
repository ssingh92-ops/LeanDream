"""Proof forest: persist accepted candidates as JSON files on disk.

Each accepted run stores both `expanded` (fully macro-resolved AST, used for
mining) and `raw` (the original AST as emitted by the LLM, with `mac` refs
intact, kept so we can see which macros are being reused).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from pydantic import TypeAdapter

from .ast import Circuit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROOFS_DIR = REPO_ROOT / "proofs"

_ADAPTER: TypeAdapter[Circuit] = TypeAdapter(Circuit)


@dataclass
class ProofRecord:
    spec: str
    timestamp: str
    iteration: int
    elapsed_seconds: float
    expanded: Circuit
    raw: Circuit
    path: Path


def record(
    spec: str,
    expanded: Circuit,
    raw: Circuit,
    iteration: int,
    elapsed_seconds: float,
) -> Path:
    PROOFS_DIR.mkdir(parents=True, exist_ok=True)
    spec_dir = PROOFS_DIR / spec
    spec_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = spec_dir / f"{ts}.json"
    payload = {
        "spec": spec,
        "timestamp": ts,
        "iteration": iteration,
        "elapsed_seconds": elapsed_seconds,
        "expanded": _ADAPTER.dump_python(expanded, mode="json"),
        "raw": _ADAPTER.dump_python(raw, mode="json"),
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def iter_records() -> Iterator[ProofRecord]:
    if not PROOFS_DIR.exists():
        return
    for f in sorted(PROOFS_DIR.rglob("*.json")):
        data = json.loads(f.read_text())
        yield ProofRecord(
            spec=data["spec"],
            timestamp=data["timestamp"],
            iteration=data.get("iteration", 0),
            elapsed_seconds=data.get("elapsed_seconds", 0.0),
            expanded=_ADAPTER.validate_python(data["expanded"]),
            raw=_ADAPTER.validate_python(data["raw"]),
            path=f,
        )


def stats() -> dict[str, int]:
    """Return spec_name -> count of accepted proofs."""
    out: dict[str, int] = {}
    if not PROOFS_DIR.exists():
        return out
    for spec_dir in PROOFS_DIR.iterdir():
        if spec_dir.is_dir():
            out[spec_dir.name] = sum(1 for _ in spec_dir.glob("*.json"))
    return out
