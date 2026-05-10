"""Macro reuse, compression, and composition analysis.

Computes the V4 benchmark metrics:
- macro_usage_rate: fraction of attempts that referenced at least one macro
- macro_reuse_count: total macro references across all attempts
- compression_ratio: avg(expanded_ast_size / raw_ast_size) for verified circuits
- macro_level_distribution: how many macros exist at each level
- macro_of_macro_candidate_count: from the mine_macro_compositions result
- specs_using_each_macro: reverse mapping from macro name to specs that used it
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helper: count AST nodes from a serialised dict
# ---------------------------------------------------------------------------

def _ast_size(d: Any) -> int:
    if not isinstance(d, dict):
        return 0
    count = 1
    for key in ("arg", "left", "right"):
        if key in d:
            count += _ast_size(d[key])
    for arg in d.get("args", []):
        count += _ast_size(arg)
    return count


def _has_mac(d: Any) -> bool:
    if not isinstance(d, dict):
        return False
    if d.get("kind") == "mac":
        return True
    for key in ("arg", "left", "right"):
        if key in d and _has_mac(d[key]):
            return True
    return any(_has_mac(a) for a in d.get("args", []))


def _mac_names(d: Any) -> list[str]:
    if not isinstance(d, dict):
        return []
    names = []
    if d.get("kind") == "mac":
        names.append(d.get("name", ""))
    for key in ("arg", "left", "right"):
        if key in d:
            names.extend(_mac_names(d[key]))
    for arg in d.get("args", []):
        names.extend(_mac_names(arg))
    return names


# ---------------------------------------------------------------------------
# Macro reuse analysis from attempt records
# ---------------------------------------------------------------------------

@dataclass
class MacroReuseMetrics:
    total_attempts: int
    attempts_with_macros: int
    macro_usage_rate: float
    total_macro_references: int
    macro_reuse_count: int               # refs to macros installed in > 1 spec
    avg_compression_ratio: float | None  # expanded/raw size ratio (verified only)
    specs_per_macro: dict[str, int]      # macro → distinct specs using it
    macro_call_counts: dict[str, int]    # macro → total call count


def analyse_macro_reuse(
    attempt_records: list[dict[str, Any]],
    registry: dict[str, dict] | None = None,
) -> MacroReuseMetrics:
    registry = registry or {}
    total = len(attempt_records)
    with_macros = 0
    total_refs = 0
    reuse_count = 0
    specs_per_macro: dict[str, set] = defaultdict(set)
    macro_calls: Counter = Counter()
    compression_ratios: list[float] = []

    for rec in attempt_records:
        raw = rec.get("raw_circuit")
        expanded = rec.get("expanded_circuit")
        spec = rec.get("spec", "?")

        if raw and _has_mac(raw):
            with_macros += 1
            for name in _mac_names(raw):
                macro_calls[name] += 1
                total_refs += 1
                specs_per_macro[name].add(spec)

        # Compression ratio: only for verified circuits
        if rec.get("status") == "verified" and raw and expanded:
            raw_sz = _ast_size(raw)
            exp_sz = _ast_size(expanded)
            if raw_sz > 0 and exp_sz > 0:
                compression_ratios.append(exp_sz / raw_sz)

    # Reuse = calls to macros used across more than one spec
    for name, s in specs_per_macro.items():
        if len(s) > 1:
            reuse_count += macro_calls[name]

    return MacroReuseMetrics(
        total_attempts=total,
        attempts_with_macros=with_macros,
        macro_usage_rate=with_macros / total if total else 0.0,
        total_macro_references=total_refs,
        macro_reuse_count=reuse_count,
        avg_compression_ratio=(
            sum(compression_ratios) / len(compression_ratios)
            if compression_ratios else None
        ),
        specs_per_macro={k: len(v) for k, v in specs_per_macro.items()},
        macro_call_counts=dict(macro_calls),
    )


# ---------------------------------------------------------------------------
# Macro level distribution
# ---------------------------------------------------------------------------

def macro_level_distribution(registry: dict[str, dict]) -> dict[int, int]:
    """Return {level: count} histogram of macro_level values."""
    dist: Counter = Counter()
    for info in registry.values():
        dist[info.get("macro_level", 0)] += 1
    return dict(dist)


# ---------------------------------------------------------------------------
# Full run analysis (combines everything)
# ---------------------------------------------------------------------------

@dataclass
class RunAnalysis:
    reuse: MacroReuseMetrics
    level_distribution: dict[int, int]
    macro_count: int
    theorem_count: int
    duplicate_rejections: int        # from installer logs (approximated)


def analyse_run(
    attempt_records: list[dict[str, Any]],
    registry: dict[str, dict] | None = None,
) -> RunAnalysis:
    registry = registry or {}
    reuse = analyse_macro_reuse(attempt_records, registry)
    level_dist = macro_level_distribution(registry)
    theorem_count = sum(len(info.get("properties") or {}) for info in registry.values())

    return RunAnalysis(
        reuse=reuse,
        level_distribution=level_dist,
        macro_count=len(registry),
        theorem_count=theorem_count,
        duplicate_rejections=0,  # installer doesn't emit a counter yet
    )


# ---------------------------------------------------------------------------
# Cross-run accumulated analysis
# ---------------------------------------------------------------------------

@dataclass
class AccumulatedAnalysis:
    runs_analysed: int
    run_ids: list[str]
    macro_growth: list[int]          # macro count at end of each run (ordered)
    hole_recurrence: dict[str, int]  # spec → how many runs it was a blocker
    mux2_status_by_run: list[str]    # "solved" | "unsolved" per run
    total_verified: int
    total_attempted: int
    bandit_top_arms: list[dict]      # top-5 arms by mean from latest bandit save


def analyse_accumulated_runs(
    runs_dir: "Path | None" = None,
) -> AccumulatedAnalysis:
    """Scan all run directories and build cross-run trend data."""
    from .attempts import RUNS_DIR, STATUS_VERIFIED, load as load_attempts

    base = runs_dir or RUNS_DIR
    run_dirs = sorted(base.iterdir()) if base.exists() else []

    run_ids: list[str] = []
    macro_growth: list[int] = []
    hole_recurrence: Counter = Counter()
    mux2_status: list[str] = []
    total_v = 0
    total_a = 0

    for rd in run_dirs:
        if not rd.is_dir():
            continue
        summary_path = rd / "summary.json"
        if not summary_path.exists():
            continue
        try:
            s = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        run_ids.append(rd.name)
        macro_growth.append(s.get("macro_count", 0))
        total_v += s.get("total_verified", 0)
        total_a += s.get("total_attempted", 0)

        for uh in s.get("unresolved_holes", []):
            spec = uh.split("/")[0]
            hole_recurrence[spec] += 1

        # Check if mux2 was solved in this run
        recs = load_attempts(rd)
        mux2_solved = any(
            r.get("spec") == "mux2" and r.get("status") == STATUS_VERIFIED
            for r in recs
        )
        mux2_status.append("solved" if mux2_solved else "unsolved")

    # Load bandit arms if available
    bandit_top: list[dict] = []
    try:
        from .learning.contextual_bandit import ContextualBandit
        from .attempts import RUNS_DIR as _RD
        bandit = ContextualBandit.load()
        arms = sorted(
            [{"arm": k, **v} for k, v in bandit.summary().items()],
            key=lambda x: x.get("mean", 0), reverse=True
        )[:5]
        bandit_top = arms
    except Exception:
        pass

    return AccumulatedAnalysis(
        runs_analysed=len(run_ids),
        run_ids=run_ids,
        macro_growth=macro_growth,
        hole_recurrence=dict(hole_recurrence.most_common()),
        mux2_status_by_run=mux2_status,
        total_verified=total_v,
        total_attempted=total_a,
        bandit_top_arms=bandit_top,
    )


def run_analysis_to_dict(a: RunAnalysis) -> dict:
    return {
        "macro_count": a.macro_count,
        "theorem_count": a.theorem_count,
        "macro_usage_rate": a.reuse.macro_usage_rate,
        "total_macro_references": a.reuse.total_macro_references,
        "macro_reuse_count": a.reuse.macro_reuse_count,
        "avg_compression_ratio": a.reuse.avg_compression_ratio,
        "attempts_with_macros": a.reuse.attempts_with_macros,
        "specs_per_macro": a.reuse.specs_per_macro,
        "macro_call_counts": a.reuse.macro_call_counts,
        "level_distribution": {str(k): v for k, v in a.level_distribution.items()},
    }


# ---------------------------------------------------------------------------
# CLI: leandream analyze
# ---------------------------------------------------------------------------

def _bar(label: str, value: float, total: float, width: int = 30) -> str:
    pct = value / total if total else 0.0
    filled = int(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"  {label:<20} [{bar}] {pct:.0%} ({int(value)}/{int(total)})"


def main() -> None:
    parser = argparse.ArgumentParser(prog="leandream analyze")
    parser.add_argument("--run", default=None, help="Analyse a specific run ID only.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = parser.parse_args()

    try:
        from . import installer
        registry = installer.load_registry()
    except Exception:
        registry = {}

    if args.run:
        from .attempts import RUNS_DIR, load as load_attempts
        run_dir = RUNS_DIR / args.run
        if not run_dir.exists():
            print(f"Run directory not found: {run_dir}")
            return
        attempt_records = load_attempts(run_dir)
        a = analyse_run(attempt_records, registry)
        if args.json:
            print(json.dumps(run_analysis_to_dict(a), indent=2))
        else:
            print(f"\n=== Run Analysis: {args.run} ===")
            print(f"  Macros installed : {a.macro_count}")
            print(f"  Theorems proven  : {a.theorem_count}")
            print(f"  Macro usage rate : {a.reuse.macro_usage_rate:.1%}")
            print(f"  Total macro refs : {a.reuse.total_macro_references}")
            print(f"  Cross-spec reuse : {a.reuse.macro_reuse_count}")
            cr = a.reuse.avg_compression_ratio
            print(f"  Avg compression  : {f'{cr:.2f}x' if cr else '—'}")
            print(f"  Macro level dist : {dict(sorted(a.level_distribution.items()))}")
    else:
        acc = analyse_accumulated_runs()
        if args.json:
            print(json.dumps({
                "runs_analysed": acc.runs_analysed,
                "run_ids": acc.run_ids,
                "macro_growth": acc.macro_growth,
                "hole_recurrence": acc.hole_recurrence,
                "mux2_status_by_run": acc.mux2_status_by_run,
                "total_verified": acc.total_verified,
                "total_attempted": acc.total_attempted,
                "bandit_top_arms": acc.bandit_top_arms,
            }, indent=2))
        else:
            print(f"\n=== Accumulated Analysis: {acc.runs_analysed} run(s) ===")
            if acc.macro_growth:
                print(f"  Macro count over runs : {acc.macro_growth}")
            if acc.hole_recurrence:
                print(f"  Hole recurrence (spec → #runs blocked):")
                for spec, cnt in acc.hole_recurrence.items():
                    print(f"    {spec:20s} : {cnt} run(s)")
            if acc.mux2_status_by_run:
                solved_n = acc.mux2_status_by_run.count("solved")
                print(f"  mux2 solved : {solved_n}/{len(acc.mux2_status_by_run)} runs")
            if acc.total_attempted:
                print(_bar("Overall verified", acc.total_verified, acc.total_attempted))
            if acc.bandit_top_arms:
                print(f"  Top bandit arms:")
                for arm in acc.bandit_top_arms:
                    print(f"    {arm.get('arm','?'):30s} mean={arm.get('mean',0):.3f}")


if __name__ == "__main__":
    main()
