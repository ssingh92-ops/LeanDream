"""Curriculum runner: stage-gated multi-stage macro learning.

A curriculum groups specs into ordered stages. Each stage runs for a fixed
number of iterations; a *stage gate* checks whether the system has met minimum
thresholds before advancing.  If a gate fails, the stage repeats (up to
`max_retries` times) before the curriculum terminates early with a diagnostic.

Stages
------
0  Smoke        Quick sanity: can Lean verify any circuit at all?
1  Connectives  Learn AND, OR, XOR, NOT equivalents.
2  Adder        Half-adder and full-adder discovery.
3  Mux          Multiplexer (hardest — needs arity-3 macro composition).
4  Full         Run all specs together to consolidate the macro library.

Usage
-----
    leandream-curriculum                  # full curriculum
    leandream-curriculum --start 2        # resume from Adder stage
    leandream-curriculum --mock           # dry-run with reference circuits
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

from . import installer
from .attempts import RUNS_DIR, STATUS_VERIFIED, load as load_attempts
from .hole_detector import detect_holes
from .metrics import (
    IterationMetrics,
    RunSummary,
    compute_iteration_metrics,
    compute_run_summary,
    load_summary,
    save_metrics,
    save_summary,
)


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

@dataclass
class StageGate:
    index: int
    name: str
    specs: list[str]          # spec names (without .json)
    iterations: int
    min_verify_ratio: float   # fraction of specs that must be verified at least once
    min_macros: int           # macros installed before gate passes
    max_retries: int = 1      # how many extra repetitions before giving up


CURRICULUM: list[StageGate] = [
    StageGate(
        index=0, name="smoke",
        specs=["and2", "xor2"],
        iterations=1, min_verify_ratio=1.0, min_macros=0,
    ),
    StageGate(
        index=1, name="connectives",
        specs=["and2", "xor2", "or2", "nand2", "half_adder_sum", "half_adder_carry"],
        iterations=3, min_verify_ratio=0.75, min_macros=1,
    ),
    StageGate(
        index=2, name="adder",
        specs=["full_adder_sum", "full_adder_carry", "parity3", "mux2"],
        iterations=5, min_verify_ratio=0.5, min_macros=3,
    ),
    StageGate(
        index=3, name="mux",
        specs=["parity4", "xor_chain4", "majority3"],
        iterations=5, min_verify_ratio=0.5, min_macros=5,
        max_retries=2,
    ),
    StageGate(
        index=4, name="full",
        specs=["all"],
        iterations=5, min_verify_ratio=0.6, min_macros=6,
    ),
]


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    passed: bool
    stage: StageGate
    verify_ratio: float
    macro_count: int
    reason: str


def evaluate_gate(
    stage: StageGate,
    run_dirs: list[Any],          # list of Path for this stage's run(s)
    registry: dict,
) -> GateResult:
    """Check whether a stage gate passes."""
    all_recs: list[dict] = []
    for rd in run_dirs:
        all_recs.extend(load_attempts(rd))

    # Which specs were verified at least once?
    specs_verified: set[str] = {
        r["spec"] for r in all_recs if r.get("status") == STATUS_VERIFIED
    }
    stage_specs = set(stage.specs) if stage.specs != ["all"] else set(
        r.get("spec", "") for r in all_recs
    )
    if not stage_specs:
        verify_ratio = 0.0
    else:
        verify_ratio = len(specs_verified & stage_specs) / len(stage_specs)

    macro_count = len(registry)

    if verify_ratio < stage.min_verify_ratio:
        return GateResult(
            passed=False, stage=stage,
            verify_ratio=verify_ratio, macro_count=macro_count,
            reason=(
                f"verify ratio {verify_ratio:.0%} < required {stage.min_verify_ratio:.0%}"
            ),
        )
    if macro_count < stage.min_macros:
        return GateResult(
            passed=False, stage=stage,
            verify_ratio=verify_ratio, macro_count=macro_count,
            reason=(
                f"macro count {macro_count} < required {stage.min_macros}"
            ),
        )

    return GateResult(
        passed=True, stage=stage,
        verify_ratio=verify_ratio, macro_count=macro_count,
        reason="all thresholds met",
    )


# ---------------------------------------------------------------------------
# Curriculum runner
# ---------------------------------------------------------------------------

@dataclass
class CurriculumResult:
    stages_completed: int
    stage_reached: int | None
    gate_results: list[GateResult] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)


def _write_stage_outputs(
    run_dirs: list[Any],
    stage: StageGate,
    gate: "GateResult",
    registry: dict,
) -> None:
    """Write stage_N_metrics.json and append to curriculum_summary.json."""
    if not run_dirs:
        return
    run_dir = run_dirs[-1]

    # stage_N_metrics.json
    all_recs: list[dict] = []
    for rd in run_dirs:
        all_recs.extend(load_attempts(rd))
    per_spec: dict[str, dict] = {}
    for rec in all_recs:
        sn = rec.get("spec", "?")
        if sn not in per_spec:
            per_spec[sn] = {"verified": 0, "total": 0}
        per_spec[sn]["total"] += 1
        if rec.get("status") == STATUS_VERIFIED:
            per_spec[sn]["verified"] += 1
    stage_metrics = {
        "stage_index": stage.index,
        "stage_name": stage.name,
        "specs": stage.specs,
        "gate_passed": gate.passed,
        "verify_ratio": gate.verify_ratio,
        "macro_count": gate.macro_count,
        "gate_reason": gate.reason,
        "per_spec": per_spec,
    }
    metrics_path = run_dir / f"stage_{stage.index}_metrics.json"
    metrics_path.write_text(json.dumps(stage_metrics, indent=2), encoding="utf-8")

    # Append to curriculum_summary.json (always written to the last run_dir)
    summary_path = run_dir / "curriculum_summary.json"
    existing: list[dict] = []
    if summary_path.exists():
        try:
            existing = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    existing.append(stage_metrics)
    summary_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def run_curriculum(
    *,
    start_stage: int = 0,
    end_stage: int = 4,
    mock: bool = False,
    model: str | None = None,
    min_support: int = 2,
    min_size: int = 3,
    verbose: bool = True,
) -> CurriculumResult:
    """Execute the curriculum from start_stage through end_stage.

    Returns a CurriculumResult summarising which stages passed.
    """
    from .orchestrator import load_specs, run as orchestrator_run

    result = CurriculumResult(stages_completed=0, stage_reached=None)

    stages = [s for s in CURRICULUM if start_stage <= s.index <= end_stage]
    if not stages:
        print("No stages in range.", file=sys.stderr)
        return result

    for stage in stages:
        if verbose:
            print(f"\n{'='*60}")
            print(f"CURRICULUM  Stage {stage.index}: {stage.name.upper()}")
            print(f"  specs: {stage.specs}")
            print(f"  iterations: {stage.iterations}")
            print(f"  gate: verify≥{stage.min_verify_ratio:.0%}, macros≥{stage.min_macros}")
            print(f"{'='*60}")

        specs = load_specs(stage.specs)
        if not specs:
            print(f"  WARNING: no specs found for stage {stage.name}, skipping.", file=sys.stderr)
            continue

        stage_run_dirs = []
        gate_passed = False

        for attempt_num in range(stage.max_retries + 1):
            if attempt_num > 0 and verbose:
                print(f"\n  [retry {attempt_num}/{stage.max_retries}] stage {stage.name}")

            orchestrator_run(
                specs,
                iterations=stage.iterations,
                min_support=min_support,
                min_size=min_size,
                model=model,
                mock=mock,
            )

            # Collect the most recent run_dir
            run_dirs_all = sorted(RUNS_DIR.iterdir()) if RUNS_DIR.exists() else []
            if run_dirs_all:
                stage_run_dirs.append(run_dirs_all[-1])
                result.run_ids.append(run_dirs_all[-1].name)

            registry = installer.load_registry()
            gate = evaluate_gate(stage, stage_run_dirs, registry)
            result.gate_results.append(gate)

            _write_stage_outputs(stage_run_dirs, stage, gate, registry)

            if verbose:
                icon = "✓" if gate.passed else "✗"
                print(
                    f"\n  {icon} gate [{stage.name}]: "
                    f"verify={gate.verify_ratio:.0%}, macros={gate.macro_count}  "
                    f"— {gate.reason}"
                )

            if gate.passed:
                gate_passed = True
                break

        result.stages_completed += 1
        result.stage_reached = stage.index

        if not gate_passed:
            print(
                f"\n  CURRICULUM STOPPED: stage {stage.name!r} gate failed after "
                f"{stage.max_retries + 1} attempt(s).",
                file=sys.stderr,
            )
            break

    if verbose:
        print(f"\n{'='*60}")
        print(f"CURRICULUM COMPLETE")
        print(f"  stages completed: {result.stages_completed}")
        print(f"  stage reached:    {result.stage_reached}")
        print(f"{'='*60}")

    return result


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(prog="leandream-curriculum")
    parser.add_argument("--start", type=int, default=0, help="First stage index (0–4).")
    parser.add_argument("--end", type=int, default=4, help="Last stage index (0–4).")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--min-support", type=int, default=2)
    parser.add_argument("--min-size", type=int, default=3)
    args = parser.parse_args()

    run_curriculum(
        start_stage=args.start,
        end_stage=args.end,
        mock=args.mock,
        model=args.model,
        min_support=args.min_support,
        min_size=args.min_size,
    )


if __name__ == "__main__":
    main()
