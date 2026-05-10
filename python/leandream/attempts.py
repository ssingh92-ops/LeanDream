"""Structured attempt logging for every LLM→Lean cycle.

Every attempt — successful or not — is appended to `runs/<run_id>/attempts.jsonl`.
This makes failures first-class data: red proof-forest edges, FailureCards for
RAG retrieval, and bandit learning signal all flow from this log.

Schema (all fields are optional except run_id, iteration, status, timestamp):
{
  "run_id": str,
  "iteration": int,
  "stage": int | null,        # curriculum stage index (V4)
  "spec": str,
  "timestamp": str,           # ISO-8601 UTC
  "proposer": str,            # "llm" | "mock" | ...
  "status": str,              # see STATUS_* constants below
  "error_type": str | null,
  "message": str | null,
  "llm_time_ms": float | null,
  "lean_time_ms": float | null,
  "prompt_chars": int | null,
  "raw_circuit": dict | null, # JSON AST as emitted by LLM (with mac refs)
  "expanded_circuit": dict | null,  # fully expanded AST that Lean saw
  "lean_stdout_tail": str | null,
  "lean_stderr_tail": str | null,
  "counterexample": list | null,
  "proof_id": str | null,     # filename of accepted proof-forest record
  "proof_mode": str | null,   # "decide" | "native_decide" (V4)
  "model": str | null,
  "info_structure": dict | null,  # lightweight information-structure tags (heuristic)
  "repair_pass": int | null,      # 0 = original attempt, 1 = one-shot repair
  "hole_type": str | null,        # hole classification if STATUS_HOLE_DETECTED (V4)
}
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = REPO_ROOT / "runs"

# --- Status constants ---------------------------------------------------------
# Successful
STATUS_VERIFIED = "verified"
# Lean-layer failures
STATUS_LEAN_FAILED = "lean_failed"
STATUS_LEAN_TIMEOUT = "lean_timeout"
STATUS_SEMANTIC_MISMATCH = "semantic_mismatch"  # valid Lean, wrong TT
# LLM / parse failures
STATUS_LLM_ERROR = "llm_error"
STATUS_SCHEMA_ERROR = "schema_error"
STATUS_PARSE_ERROR = "parse_error"
# Macro / expansion failures
STATUS_UNKNOWN_MACRO = "unknown_macro"
STATUS_ARITY_MISMATCH = "arity_mismatch"
STATUS_EXPANSION_CYCLE = "expansion_cycle"
STATUS_EXPANSION_DEPTH = "expansion_depth"
STATUS_ARITY_OVERFLOW = "arity_overflow"  # proposed arity > supported limit
# Preflight / policy failures
STATUS_PREFLIGHT_FAILED = "preflight_failed"  # validator rejected before Lean
STATUS_REPEATED_FAILURE = "repeated_failure"  # same circuit failed 3+ times
# Hole-related
STATUS_HOLE_DETECTED = "hole_detected"  # spec has a structural coverage hole
# Misc
STATUS_INTERNAL_ERROR = "internal_error"
STATUS_BUDGET_EXCEEDED = "budget_exceeded"  # circuit or prompt too large

# --- Repairable statuses (superset of repair.py's REPAIRABLE) ---------------
REPAIRABLE_STATUSES = frozenset({
    STATUS_UNKNOWN_MACRO,
    STATUS_ARITY_MISMATCH,
    STATUS_EXPANSION_CYCLE,
    STATUS_EXPANSION_DEPTH,
    STATUS_LEAN_FAILED,
    STATUS_SEMANTIC_MISMATCH,
    STATUS_PREFLIGHT_FAILED,
})


def _tail(text: str | None, lines: int = 12) -> str | None:
    if not text:
        return None
    tail = "\n".join(text.strip().splitlines()[-lines:])
    return tail or None


def log(
    run_dir: Path,
    *,
    run_id: str,
    iteration: int,
    spec: str,
    status: str,
    proposer: str = "llm",
    error_type: str | None = None,
    message: str | None = None,
    llm_time_ms: float | None = None,
    lean_time_ms: float | None = None,
    prompt_chars: int | None = None,
    raw_circuit: Any | None = None,
    expanded_circuit: Any | None = None,
    lean_stdout: str | None = None,
    lean_stderr: str | None = None,
    counterexample: list | None = None,
    proof_id: str | None = None,
    proof_mode: str | None = None,
    model: str | None = None,
    info_structure: dict | None = None,
    repair_pass: int | None = None,
    stage: int | None = None,
    hole_type: str | None = None,
    retrieved_card_ids: list[str] | None = None,
    environment: dict | None = None,
) -> None:
    """Append one attempt record to `<run_dir>/attempts.jsonl`."""
    run_dir.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "run_id": run_id,
        "iteration": iteration,
        "stage": stage,
        "spec": spec,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "proposer": proposer,
        "status": status,
        "error_type": error_type,
        "message": message,
        "llm_time_ms": llm_time_ms,
        "lean_time_ms": lean_time_ms,
        "prompt_chars": prompt_chars,
        "raw_circuit": raw_circuit,
        "expanded_circuit": expanded_circuit,
        "lean_stdout_tail": _tail(lean_stdout),
        "lean_stderr_tail": _tail(lean_stderr),
        "counterexample": counterexample,
        "proof_id": proof_id,
        "proof_mode": proof_mode,
        "model": model,
        "info_structure": info_structure,
        "repair_pass": repair_pass,
        "hole_type": hole_type,
        "retrieved_card_ids": retrieved_card_ids or [],
        "environment": environment or {},
    }
    path = run_dir / "attempts.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load(run_dir: Path) -> list[dict]:
    path = run_dir / "attempts.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def run_dir_for(run_id: str) -> Path:
    return RUNS_DIR / run_id
