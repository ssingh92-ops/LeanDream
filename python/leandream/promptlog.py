"""Persistent log of every LLM call: prompts in, response out."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .verify import REPO_ROOT

PROMPTS_DIR = REPO_ROOT / "prompts"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def record(
    *,
    spec: str,
    iteration: int,
    model: str,
    system_prompt: str,
    user_prompt: str,
    macros_in_prompt: list[str],
    elapsed_seconds: float,
    ok: bool,
    response_circuit: dict | None = None,
    reasoning: str = "",
    error: str | None = None,
) -> Path:
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    spec_dir = PROMPTS_DIR / spec
    spec_dir.mkdir(exist_ok=True)
    timestamp = _ts()
    path = spec_dir / f"{timestamp}.json"
    payload: dict[str, Any] = {
        "spec": spec,
        "iteration": iteration,
        "timestamp": timestamp,
        "model": model,
        "elapsed_seconds": elapsed_seconds,
        "ok": ok,
        "macros_in_prompt": macros_in_prompt,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "reasoning": reasoning,
        "response_circuit": response_circuit,
        "error": error,
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


@dataclass
class PromptIndex:
    spec: str
    iteration: int
    timestamp: str
    model: str
    elapsed_seconds: float
    ok: bool
    macros_count: int
    filename: str


def iter_index() -> Iterator[PromptIndex]:
    if not PROMPTS_DIR.exists():
        return
    for f in sorted(PROMPTS_DIR.rglob("*.json")):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        yield PromptIndex(
            spec=data.get("spec", ""),
            iteration=data.get("iteration", 0),
            timestamp=data.get("timestamp", ""),
            model=data.get("model", ""),
            elapsed_seconds=data.get("elapsed_seconds", 0.0),
            ok=bool(data.get("ok", False)),
            macros_count=len(data.get("macros_in_prompt", []) or []),
            filename=f.name,
        )


def load(spec: str, filename: str) -> dict:
    p = PROMPTS_DIR / spec / filename
    return json.loads(p.read_text())
