"""Per-iteration and per-run metrics computation and persistence.

Outputs three files per run (written to runs/<run_id>/):
  metrics.csv   — one row per iteration
  summary.json  — rolled-up run totals
  report.md     — human-readable 12-section markdown report
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .attempts import STATUS_VERIFIED, RUNS_DIR


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class IterationMetrics:
    run_id: str
    iteration: int
    stage: int | None
    verified: int
    attempted: int
    repair_success: int      # verified only on repair pass
    new_macros: int
    new_theorems: int
    rag_card_count: int
    bandit_entropy: float    # average H = -(a/(a+b))*log2(a/(a+b)) - ... over all arms
    avg_llm_ms: float | None
    avg_lean_ms: float | None

    @property
    def verify_rate(self) -> float:
        return self.verified / self.attempted if self.attempted else 0.0


@dataclass
class RunSummary:
    run_id: str
    iterations: int
    total_verified: int
    total_attempted: int
    total_repair_success: int
    macro_count: int
    theorem_count: int
    rag_card_count: int
    avg_verify_rate: float
    peak_verify_rate: float
    stage_reached: int | None
    holes_detected: int
    # V4.1 decision fields
    should_continue_to_next_stage: bool = False
    blocking_reasons: list[str] = field(default_factory=list)
    unresolved_holes: list[str] = field(default_factory=list)
    top_failure_modes: list[str] = field(default_factory=list)
    recommended_next_action: str = "inspect_run_data"

    @property
    def overall_verify_rate(self) -> float:
        return self.total_verified / self.total_attempted if self.total_attempted else 0.0


# ---------------------------------------------------------------------------
# Computation helpers
# ---------------------------------------------------------------------------

def _digamma(x: float) -> float:
    """Digamma function approximation via asymptotic expansion (accurate for x > 0)."""
    import math
    # Shift small x up using recurrence ψ(x) = ψ(x+1) - 1/x
    result = 0.0
    while x < 6.0:
        result -= 1.0 / x
        x += 1.0
    # Asymptotic expansion for large x
    result += math.log(x) - 1.0 / (2.0 * x)
    inv_x2 = 1.0 / (x * x)
    result -= inv_x2 * (1.0/12.0 - inv_x2 * (1.0/120.0 - inv_x2 / 252.0))
    return result


def _beta_entropy(alpha: float, beta: float) -> float:
    """Differential entropy of Beta(alpha, beta) in nats."""
    import math
    try:
        ab = alpha + beta
        return (
            math.lgamma(alpha) + math.lgamma(beta) - math.lgamma(ab)
            - (alpha - 1) * _digamma(alpha)
            - (beta - 1) * _digamma(beta)
            + (ab - 2) * _digamma(ab)
        )
    except Exception:
        return 0.0


def _bandit_entropy(bandit_summary: dict[str, dict]) -> float:
    """Mean Beta entropy across all bandit arms."""
    if not bandit_summary:
        return 0.0
    entropies = [
        _beta_entropy(v["alpha"], v["beta"])
        for v in bandit_summary.values()
    ]
    return sum(entropies) / len(entropies)


def compute_iteration_metrics(
    run_id: str,
    iteration: int,
    attempt_records: list[dict[str, Any]],
    *,
    prev_macro_count: int = 0,
    cur_macro_count: int = 0,
    prev_theorem_count: int = 0,
    cur_theorem_count: int = 0,
    rag_card_count: int = 0,
    bandit_summary: dict | None = None,
    stage: int | None = None,
) -> IterationMetrics:
    """Derive IterationMetrics from the flat attempt list for one iteration."""
    iter_recs = [r for r in attempt_records if r.get("iteration") == iteration]

    verified = sum(1 for r in iter_recs if r.get("status") == STATUS_VERIFIED)
    attempted = len(iter_recs)

    # Repair success = verified on repair_pass=1
    repair_success = sum(
        1 for r in iter_recs
        if r.get("status") == STATUS_VERIFIED and r.get("repair_pass", 0) == 1
    )

    llm_times = [r["llm_time_ms"] for r in iter_recs if r.get("llm_time_ms") is not None]
    lean_times = [r["lean_time_ms"] for r in iter_recs if r.get("lean_time_ms") is not None]

    return IterationMetrics(
        run_id=run_id,
        iteration=iteration,
        stage=stage,
        verified=verified,
        attempted=attempted,
        repair_success=repair_success,
        new_macros=max(0, cur_macro_count - prev_macro_count),
        new_theorems=max(0, cur_theorem_count - prev_theorem_count),
        rag_card_count=rag_card_count,
        bandit_entropy=_bandit_entropy(bandit_summary or {}),
        avg_llm_ms=sum(llm_times) / len(llm_times) if llm_times else None,
        avg_lean_ms=sum(lean_times) / len(lean_times) if lean_times else None,
    )


def compute_run_summary(
    run_id: str,
    iteration_metrics: list[IterationMetrics],
    *,
    macro_count: int = 0,
    theorem_count: int = 0,
    rag_card_count: int = 0,
    holes_detected: int = 0,
    stage_reached: int | None = None,
    hole_objects: list | None = None,
    attempt_records: list[dict] | None = None,
    stage_gate_passed: bool | None = None,
) -> RunSummary:
    total_verified = sum(m.verified for m in iteration_metrics)
    total_attempted = sum(m.attempted for m in iteration_metrics)
    total_repair = sum(m.repair_success for m in iteration_metrics)
    rates = [m.verify_rate for m in iteration_metrics if m.attempted]
    avg_verify_rate = sum(rates) / len(rates) if rates else 0.0
    peak_verify_rate = max(rates) if rates else 0.0

    # --- Decision fields ------------------------------------------------------
    blocking_reasons: list[str] = []
    unresolved_holes: list[str] = []
    top_failure_modes: list[str] = []

    if hole_objects:
        blockers = [h for h in hole_objects if h.severity == "blocker" and h.resolution == "unresolved"]
        for h in blockers:
            blocking_reasons.append(f"{h.spec}: {h.hole_type}")
            unresolved_holes.append(f"{h.spec}/{h.hole_type}")

    if attempt_records:
        fail_counter: Counter = Counter(
            r.get("error_type") or r.get("status")
            for r in attempt_records
            if r.get("status") != "verified"
        )
        top_failure_modes = [m for m, _ in fail_counter.most_common(3) if m]

    # --- Recommended next action ----------------------------------------------
    should_continue = False
    action = "inspect_run_data"

    # Count arity mismatch failures for specific majority/carry diagnosis
    arity_mismatch_count = 0
    majority_verify_count = 0
    majority_total_count = 0
    if attempt_records:
        for r in attempt_records:
            spec = r.get("spec", "")
            status = r.get("status", "")
            if spec in ("majority3", "full_adder_carry") and r.get("repair_pass", 0) == 0:
                majority_total_count += 1
                if status == "verified":
                    majority_verify_count += 1
                elif status == "arity_mismatch":
                    arity_mismatch_count += 1

    majority_rate = majority_verify_count / majority_total_count if majority_total_count else None

    if total_attempted == 0:
        action = "run_the_orchestrator_first"
    elif stage_gate_passed is True:
        should_continue = True
        action = "proceed_to_next_stage"
    elif stage_gate_passed is False:
        # Diagnose why gate failed
        mux_blocked = any("mux2" in r for r in blocking_reasons)
        arity_dominant = arity_mismatch_count >= 2
        majority_low = majority_rate is not None and majority_rate < 0.5
        if mux_blocked:
            action = "inspect_mux_hole"
        elif arity_dominant and majority_low:
            action = "fix_macro_arity_prompt"
        else:
            action = "rerun_stage_with_more_iterations"
    elif blocking_reasons:
        mux_blocked = any("mux2" in r for r in blocking_reasons)
        arity_dominant = arity_mismatch_count >= 2
        if mux_blocked:
            action = "inspect_mux_hole"
        elif arity_dominant:
            action = "fix_macro_arity_prompt"
        else:
            action = "do_not_increase_complexity_yet"
    elif avg_verify_rate >= 0.6 and macro_count >= 2:
        should_continue = True
        action = "proceed_to_next_stage"
    elif avg_verify_rate >= 0.4:
        if arity_mismatch_count >= 2:
            action = "fix_macro_arity_prompt"
        else:
            action = "rerun_stage_with_more_iterations"
    else:
        action = "do_not_increase_complexity_yet"

    return RunSummary(
        run_id=run_id,
        iterations=len(iteration_metrics),
        total_verified=total_verified,
        total_attempted=total_attempted,
        total_repair_success=total_repair,
        macro_count=macro_count,
        theorem_count=theorem_count,
        rag_card_count=rag_card_count,
        avg_verify_rate=avg_verify_rate,
        peak_verify_rate=peak_verify_rate,
        stage_reached=stage_reached,
        holes_detected=holes_detected,
        should_continue_to_next_stage=should_continue,
        blocking_reasons=blocking_reasons,
        unresolved_holes=unresolved_holes,
        top_failure_modes=top_failure_modes,
        recommended_next_action=action,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_CSV_FIELDS = [
    "run_id", "iteration", "stage",
    "verified", "attempted", "verify_rate",
    "repair_success", "new_macros", "new_theorems",
    "rag_card_count", "bandit_entropy",
    "avg_llm_ms", "avg_lean_ms",
]


def save_metrics(run_dir: Path, metrics: list[IterationMetrics]) -> Path:
    """Write metrics.csv to run_dir.  Returns the path."""
    path = run_dir / "metrics.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for m in metrics:
            row = asdict(m)
            row["verify_rate"] = f"{m.verify_rate:.4f}"
            writer.writerow({k: row.get(k, "") for k in _CSV_FIELDS})
    return path


def save_summary(run_dir: Path, summary: RunSummary) -> Path:
    """Write summary.json to run_dir.  Returns the path."""
    path = run_dir / "summary.json"
    data = asdict(summary)
    data["overall_verify_rate"] = summary.overall_verify_rate
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load_summary(run_dir: Path) -> dict | None:
    path = run_dir / "summary.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
