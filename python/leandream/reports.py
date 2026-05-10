"""Per-run report generation.

Usage:
    leandream report --run <run_id>

Writes runs/<run_id>/report.md and prints a summary.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .analysis import analyse_run, run_analysis_to_dict
from .attempts import RUNS_DIR, STATUS_VERIFIED, load as load_attempts
from .hole_detector import detect_holes
from .metrics import IterationMetrics, RunSummary, load_summary


def _load_run_dir(run_id: str) -> Path:
    d = RUNS_DIR / run_id
    if not d.exists():
        raise SystemExit(f"run directory not found: {d}")
    return d


def _section(n: int, title: str, body: str) -> str:
    return f"\n## {n}. {title}\n\n{body}\n"


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _fmt_ms(x: float | None) -> str:
    if x is None:
        return "—"
    if x < 1000:
        return f"{x:.0f} ms"
    return f"{x / 1000:.2f} s"


def generate_report(run_id: str, specs: list[dict] | None = None) -> Path:
    """Write runs/<run_id>/report.md.  Returns the path."""
    run_dir = _load_run_dir(run_id)
    all_attempts = load_attempts(run_dir)
    summary: dict | None = load_summary(run_dir)

    # ---- Basic stats --------------------------------------------------------
    total = len(all_attempts)
    verified_recs = [r for r in all_attempts if r.get("status") == STATUS_VERIFIED]
    n_verified = len(verified_recs)
    n_failed = total - n_verified

    # Per-spec breakdown
    spec_counts: dict[str, dict] = defaultdict(lambda: {"verified": 0, "total": 0})
    for r in all_attempts:
        sn = r.get("spec", "?")
        spec_counts[sn]["total"] += 1
        if r.get("status") == STATUS_VERIFIED:
            spec_counts[sn]["verified"] += 1

    # Failure mode breakdown
    status_counts: Counter = Counter(r.get("status") for r in all_attempts)

    # Repair stats
    repair_attempts = [r for r in all_attempts if r.get("repair_pass", 0) == 1]
    repair_verified = sum(1 for r in repair_attempts if r.get("status") == STATUS_VERIFIED)

    # Timing
    llm_times = [r["llm_time_ms"] for r in all_attempts if r.get("llm_time_ms")]
    lean_times = [r["lean_time_ms"] for r in all_attempts if r.get("lean_time_ms")]
    avg_llm = sum(llm_times) / len(llm_times) if llm_times else None
    avg_lean = sum(lean_times) / len(lean_times) if lean_times else None

    # Macro / model usage
    models = Counter(r.get("model") for r in all_attempts if r.get("model"))
    proof_modes = Counter(r.get("proof_mode") for r in verified_recs if r.get("proof_mode"))

    # Macro reuse analysis
    try:
        from . import installer
        registry = installer.load_registry()
    except Exception:
        registry = {}
    run_anal = analyse_run(all_attempts, registry)

    # Hole detection
    holes = []
    if specs:
        holes = detect_holes(specs, all_attempts)

    # Iterations
    iterations = sorted({r.get("iteration") for r in all_attempts if r.get("iteration") is not None})

    # ---- Assemble sections --------------------------------------------------
    sections: list[str] = []

    # 1. Run Identity
    sections.append(_section(1, "Run Identity", f"""
| Field | Value |
|-------|-------|
| Run ID | `{run_id}` |
| Total attempts | {total} |
| Verified | {n_verified} ({_fmt_pct(n_verified / total) if total else '—'}) |
| Failed | {n_failed} |
| Iterations | {len(iterations)} |
""".strip()))

    # 2. Verification Summary
    sections.append(_section(2, "Verification Summary", f"""
| Metric | Value |
|--------|-------|
| Verify rate | {_fmt_pct(n_verified / total) if total else '—'} |
| Repair attempts | {len(repair_attempts)} |
| Repair successes | {repair_verified} ({_fmt_pct(repair_verified / len(repair_attempts)) if repair_attempts else '—'}) |
""".strip()))

    # 3. Per-Spec Results
    spec_rows = []
    for sn, counts in sorted(spec_counts.items()):
        rate = counts["verified"] / counts["total"] if counts["total"] else 0.0
        spec_rows.append(
            f"| {sn} | {counts['verified']} | {counts['total']} | {_fmt_pct(rate)} |"
        )
    spec_table = (
        "| Spec | Verified | Attempts | Rate |\n"
        "|------|----------|----------|------|\n"
        + "\n".join(spec_rows)
    ) if spec_rows else "_No data._"
    sections.append(_section(3, "Per-Spec Results", spec_table))

    # 4. Failure Mode Breakdown
    fail_rows = [
        f"| `{status}` | {count} |"
        for status, count in status_counts.most_common()
        if status != STATUS_VERIFIED
    ]
    fail_table = (
        "| Status | Count |\n|--------|-------|\n" + "\n".join(fail_rows)
    ) if fail_rows else "_No failures._"
    sections.append(_section(4, "Failure Mode Breakdown", fail_table))

    # 5. Iteration-by-Iteration Progress
    iter_rows = []
    for it in iterations:
        it_recs = [r for r in all_attempts if r.get("iteration") == it]
        it_v = sum(1 for r in it_recs if r.get("status") == STATUS_VERIFIED)
        it_rate = it_v / len(it_recs) if it_recs else 0.0
        iter_rows.append(f"| {it} | {it_v} | {len(it_recs)} | {_fmt_pct(it_rate)} |")
    iter_table = (
        "| Iteration | Verified | Attempts | Rate |\n"
        "|-----------|----------|----------|------|\n"
        + "\n".join(iter_rows)
    ) if iter_rows else "_No data._"
    sections.append(_section(5, "Iteration-by-Iteration Progress", iter_table))

    # 6. Timing Analysis
    sections.append(_section(6, "Timing Analysis", f"""
| Metric | Value |
|--------|-------|
| Avg LLM time | {_fmt_ms(avg_llm)} |
| Avg Lean time | {_fmt_ms(avg_lean)} |
| LLM calls measured | {len(llm_times)} |
| Lean calls measured | {len(lean_times)} |
""".strip()))

    # 7. Proof Mode Usage
    pm_rows = [f"| `{pm}` | {cnt} |" for pm, cnt in proof_modes.most_common()]
    pm_table = (
        "| proof_mode | Uses |\n|------------|------|\n" + "\n".join(pm_rows)
    ) if pm_rows else "_No proof_mode data recorded (upgrade to V4 verify.py)._"
    sections.append(_section(7, "Proof Mode (proof_mode) Distribution", pm_table))

    # 8. Model Usage
    model_rows = [f"| `{m}` | {cnt} |" for m, cnt in models.most_common()]
    model_table = (
        "| Model | Calls |\n|-------|-------|\n" + "\n".join(model_rows)
    ) if model_rows else "_No model data._"
    sections.append(_section(8, "Model Usage", model_table))

    # 9. Macro Reuse & Composition
    compression = run_anal.reuse.avg_compression_ratio
    sections.append(_section(9, "Macro Reuse & Composition", f"""
| Metric | Value |
|--------|-------|
| Attempts using macros | {run_anal.reuse.attempts_with_macros} / {run_anal.reuse.total_attempts} ({_fmt_pct(run_anal.reuse.macro_usage_rate)}) |
| Total macro references | {run_anal.reuse.total_macro_references} |
| Cross-spec reuse count | {run_anal.reuse.macro_reuse_count} |
| Avg expansion ratio | {f"{compression:.2f}x" if compression else "—"} |
| Macro level >0 count | {sum(v for k, v in run_anal.level_distribution.items() if k > 0)} |
""".strip()))

    # 10. Repair Analysis
    if repair_attempts:
        repair_by_status: Counter = Counter(r.get("error_type") for r in repair_attempts)
        r_rows = [f"| `{et}` | {cnt} |" for et, cnt in repair_by_status.most_common()]
        repair_detail = (
            "| Original Error Type | Repair Attempts |\n|---------------------|-----------------|\n"
            + "\n".join(r_rows)
        )
    else:
        repair_detail = "_No repair attempts._"
    sections.append(_section(10, "Repair Analysis", repair_detail))

    # 11. Coverage Holes (including mux/majority status)
    if holes:
        hole_rows = [
            f"| {h.spec} | `{h.hole_type}` | {h.severity} | {h.resolution} | {json.dumps(h.evidence)} |"
            for h in holes
        ]
        hole_table = (
            "| Spec | Hole Type | Severity | Resolution | Evidence |\n"
            "|------|-----------|----------|------------|----------|\n"
            + "\n".join(hole_rows)
        )
    else:
        hole_table = "_No holes detected._"

    # Explicit mux2 and majority/carry status
    mux_holes = [h for h in holes if "mux" in h.spec or "conditional" in h.hole_type]
    majority_holes = [h for h in holes if "majority" in h.spec or "carry" in h.spec or "majority_carry" in h.hole_type]
    mux_status = (
        f"mux2 status: {mux_holes[0].resolution} ({mux_holes[0].hole_type})" if mux_holes
        else "mux2 status: no hole detected (verified or not yet attempted)"
    )
    majority_status = (
        f"majority/carry status: {majority_holes[0].resolution} ({majority_holes[0].hole_type})" if majority_holes
        else "majority/carry status: no hole detected"
    )

    sections.append(_section(11, "Coverage Holes", f"""{hole_table}

**{mux_status}**

**{majority_status}**
""".strip()))

    # 12. Macro Registry Snapshot
    try:
        from . import installer
        registry = installer.load_registry()
        macro_rows = [
            f"| `{name}` | {info.get('arity', '?')} | {info.get('macro_level', '?')} "
            f"| {info.get('tt_key', '—')} | {', '.join(info.get('properties') or [])} |"
            for name, info in registry.items()
        ]
        macro_table = (
            "| Macro | Arity | Level | tt_key | Properties |\n"
            "|-------|-------|-------|--------|------------|\n"
            + "\n".join(macro_rows)
        ) if macro_rows else "_No macros installed._"
    except Exception:
        macro_table = "_Registry unavailable._"
    sections.append(_section(12, "Macro Registry Snapshot", macro_table))

    # 13. Curriculum Stage Result
    curriculum_body_lines: list[str] = []
    stage_summary_path = None
    if summary:
        stage_reached = summary.get("stage_reached")
        curriculum_body_lines.append(f"**Stage reached:** {stage_reached if stage_reached is not None else '—'}")
        curriculum_body_lines.append("")
        action = summary.get("recommended_next_action", "—")
        curriculum_body_lines.append(f"**Recommended next action:** `{action}`")
        blocking = summary.get("blocking_reasons", [])
        if blocking:
            curriculum_body_lines.append("")
            curriculum_body_lines.append("**Blocking reasons:**")
            for br in blocking:
                curriculum_body_lines.append(f"- {br}")
        unresolved = summary.get("unresolved_holes", [])
        if unresolved:
            curriculum_body_lines.append("")
            curriculum_body_lines.append("**Unresolved holes:**")
            for uh in unresolved:
                curriculum_body_lines.append(f"- `{uh}`")
        top_fails = summary.get("top_failure_modes", [])
        if top_fails:
            curriculum_body_lines.append("")
            curriculum_body_lines.append("**Top failure modes:**")
            for fm in top_fails:
                curriculum_body_lines.append(f"- `{fm}`")
    else:
        curriculum_body_lines.append("_No summary.json found — run the orchestrator first._")

    # Try to load curriculum_summary.json from run_dir
    curr_summary_path = run_dir / "curriculum_summary.json"
    if curr_summary_path.exists():
        try:
            stage_records: list[dict] = json.loads(curr_summary_path.read_text(encoding="utf-8"))
            if stage_records:
                curriculum_body_lines.append("")
                curriculum_body_lines.append("**Stage gate history:**")
                gate_rows = [
                    f"| {sr['stage_index']} | {sr['stage_name']} "
                    f"| {'✓' if sr['gate_passed'] else '✗'} "
                    f"| {sr['verify_ratio']:.0%} | {sr['macro_count']} | {sr['gate_reason']} |"
                    for sr in stage_records
                ]
                curriculum_body_lines.append(
                    "| Stage | Name | Passed | Verify | Macros | Reason |\n"
                    "|-------|------|--------|--------|--------|--------|\n"
                    + "\n".join(gate_rows)
                )
        except Exception:
            pass
    sections.append(_section(13, "Curriculum Stage Result", "\n".join(curriculum_body_lines)))

    # 14. DSL Growth Summary & Information-Structure Observations
    level_dist = run_anal.level_distribution
    level_rows = [
        f"| {lvl} | {cnt} |" for lvl, cnt in sorted(level_dist.items())
    ]
    level_table = (
        "| Macro Level | Count |\n|-------------|-------|\n" + "\n".join(level_rows)
    ) if level_rows else "_No macros._"

    info_obs: list[str] = []
    for name, info in registry.items() if hasattr(registry, "items") else []:
        is_info = info.get("info_structure") or {}
        if is_info.get("information_preserving"):
            info_obs.append(f"- `{name}` (arity {info.get('arity', '?')}): information-preserving (bijection)")
        elif is_info.get("information_losing"):
            info_obs.append(f"- `{name}` (arity {info.get('arity', '?')}): information-losing (fan-in)")
    info_obs_str = "\n".join(info_obs) if info_obs else "_No info-structure annotations recorded._"

    sections.append(_section(14, "DSL Growth Summary & Information-Structure Observations", f"""
### Macro Level Distribution

{level_table}

### Information-Structure Observations

{info_obs_str}

### DSL Maturity Assessment

{"DSL hierarchy growing — level >0 macros present." if sum(v for k,v in level_dist.items() if k>0) > 0 else "DSL flat — all macros at level 0 (no macro-of-macro compositions yet)."}
""".strip()))

    # ---- Recommendations (section 15) ----------------------------------------
    recs: list[str] = []
    if n_verified == 0:
        recs.append("- **No proofs verified.** Check LLM connectivity and spec files.")
    if holes:
        blocker_holes = [h for h in holes if h.severity == "blocker"]
        if blocker_holes:
            recs.append(
                f"- **{len(blocker_holes)} blocker hole(s) detected:** "
                + ", ".join(f"`{h.spec}` ({h.hole_type})" for h in blocker_holes)
                + ". Do not increase complexity yet — resolve holes first."
            )
    if repair_verified == 0 and repair_attempts:
        recs.append("- Repair attempts all failed — tighten repair prompt templates (V4 templates A–E).")
    if avg_lean and avg_lean > 30_000:
        recs.append(f"- Avg Lean time {_fmt_ms(avg_lean)} is high — consider lowering `--min-size`.")
    if run_anal.reuse.macro_usage_rate < 0.3 and run_anal.macro_count > 0:
        recs.append(
            f"- Macro usage rate {_fmt_pct(run_anal.reuse.macro_usage_rate)} is low — "
            "prompt hardening (MacroCard arity schemas) may help."
        )
    if run_anal.reuse.macro_usage_rate >= 0.4 and not holes:
        recs.append("- Macro reuse is healthy. Proceed to macro composition stage.")
    level_gt0 = sum(v for k, v in run_anal.level_distribution.items() if k > 0)
    if level_gt0 == 0 and run_anal.macro_count >= 3:
        recs.append("- No macro-of-macro compositions yet. Mine raw ASTs for level-1 patterns.")
    if level_gt0 > 0:
        recs.append(f"- Macro level >0 detected ({level_gt0} macro(s)). DSL hierarchy is growing.")
    if not recs:
        recs.append("- System operating normally. Continue accumulating proofs.")
    sections.append(_section(15, "Recommendations", "\n".join(recs)))

    # 17. Speed Report
    from collections import defaultdict as _dd
    total_llm_ms = sum(r.get("llm_time_ms") or 0 for r in all_attempts)
    total_lean_ms = sum(r.get("lean_time_ms") or 0 for r in all_attempts)
    lean_cached_count = sum(1 for r in all_attempts if r.get("lean_cached"))
    lean_total = sum(1 for r in all_attempts if r.get("lean_time_ms") is not None)
    lean_cache_rate = lean_cached_count / lean_total if lean_total else 0.0
    qc_rejected = sum(1 for r in all_attempts if r.get("error_type") == "quickcheck_failed")
    qc_total = sum(1 for r in all_attempts if r.get("quickcheck_ms") is not None)
    # Per-spec average lean time — find top 5 slowest
    spec_lean: dict[str, list[float]] = _dd(list)
    for r in all_attempts:
        lt = r.get("lean_time_ms")
        if lt:
            spec_lean[r.get("spec", "?")].append(lt)
    top5_slow = sorted(
        ((sn, sum(ts) / len(ts)) for sn, ts in spec_lean.items()),
        key=lambda x: -x[1],
    )[:5]
    slow_rows = "\n".join(
        f"| {sn} | {_fmt_ms(avg_t)} |" for sn, avg_t in top5_slow
    ) or "_No data._"
    # Cache stats
    try:
        from .cache import lean_verify_cache, llm_response_cache, property_prove_cache
        lean_cs = lean_verify_cache().stats()
        llm_cs = llm_response_cache().stats()
        prop_cs = property_prove_cache().stats()
        cache_rows = (
            f"| lean_verify | {lean_cs['hits']} | {lean_cs['misses']} | {lean_cs['hit_rate']:.1%} | {lean_cs['size']} |\n"
            f"| llm_response | {llm_cs['hits']} | {llm_cs['misses']} | {llm_cs['hit_rate']:.1%} | {llm_cs['size']} |\n"
            f"| property_prove | {prop_cs['hits']} | {prop_cs['misses']} | {prop_cs['hit_rate']:.1%} | {prop_cs['size']} |"
        )
    except Exception:
        cache_rows = "_Cache stats unavailable._"
    speed_body = f"""
| Metric | Value |
|--------|-------|
| Total LLM time | {_fmt_ms(total_llm_ms)} |
| Total Lean time | {_fmt_ms(total_lean_ms)} |
| Avg LLM / attempt | {_fmt_ms(total_llm_ms / total if total else None)} |
| Avg Lean / attempt | {_fmt_ms(total_lean_ms / total if total else None)} |
| Lean cache hits | {lean_cached_count} / {lean_total} ({lean_cache_rate:.1%}) |
| Quickcheck fast-rejects | {qc_rejected} / {qc_total} |

### Cache Statistics (this session)

| Cache | Hits | Misses | Hit Rate | Size |
|-------|------|--------|----------|------|
{cache_rows}

### Top 5 Slowest Specs (avg Lean ms)

| Spec | Avg Lean Time |
|------|---------------|
{slow_rows}
""".strip()
    sections.append(_section(17, "Speed Report", speed_body))

    # ---- Stop/Go Decision (section 16) ----------------------------------------
    overall_rate = n_verified / total if total else 0.0
    majority_attempts = [r for r in all_attempts if r.get("spec") == "majority3" and r.get("repair_pass", 0) == 0]
    majority_verified = sum(1 for r in majority_attempts if r.get("status") == STATUS_VERIFIED)
    majority_rate = majority_verified / len(majority_attempts) if majority_attempts else None
    arity_mismatch_count = sum(1 for r in all_attempts if r.get("status") == "arity_mismatch")
    level_gt0 = sum(v for k, v in run_anal.level_distribution.items() if k > 0)

    def _yn(cond: bool | None, yes="✓ Yes", no="✗ No", na="—") -> str:
        if cond is None:
            return na
        return yes if cond else no

    def _warn(cond: bool | None, yes="✓ Yes", warn="⚠ Partial", no="✗ No", na="—") -> str:
        if cond is None:
            return na
        return yes if cond else no

    action = summary.get("recommended_next_action", "inspect_run_data") if summary else "inspect_run_data"
    blocker_holes = [h for h in holes if h.severity == "blocker" and h.resolution == "unresolved"]

    stopgo_rows = [
        f"| Stage overall ≥ 90%? | {_yn(overall_rate >= 0.9)} | {_fmt_pct(overall_rate)} |",
        f"| majority3 verified? | {_yn(majority_rate is None, 'not attempted', _yn(majority_rate >= 0.75) if majority_rate is not None else '—')} | {(_fmt_pct(majority_rate) if majority_rate is not None else '—')} |",
        f"| Arity mismatches? | {_yn(arity_mismatch_count == 0, 'None', f'{arity_mismatch_count} (fix_macro_arity_prompt)')} | count={arity_mismatch_count} |",
        f"| DSL growing vertically? | {_yn(level_gt0 > 0)} | level>0 macros: {level_gt0} |",
        f"| Macro reuse healthy? | {_yn(run_anal.reuse.macro_usage_rate >= 0.5)} | {_fmt_pct(run_anal.reuse.macro_usage_rate)} usage |",
        f"| Blocker holes? | {_yn(len(blocker_holes) == 0, 'None', f'{len(blocker_holes)} blocker(s)')} | {', '.join(h.spec for h in blocker_holes) or 'none'} |",
        f"| Proceed to next stage? | {_yn(action == 'proceed_to_next_stage')} | action: `{action}` |",
    ]
    stopgo_table = (
        "| Question | Answer | Detail |\n"
        "|----------|--------|--------|\n"
        + "\n".join(stopgo_rows)
    )
    sections.append(_section(16, "Stop/Go Decision", f"""{stopgo_table}

**Recommended next action: `{action}`**
""".strip()))

    # ---- Write report -------------------------------------------------------
    header = f"# LeanDream Run Report\n\nRun: `{run_id}`\n"
    body = header + "".join(sections)
    report_path = run_dir / "report.md"
    report_path.write_text(body, encoding="utf-8")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(prog="leandream report")
    parser.add_argument("--run", required=True, help="Run ID (e.g. 20260509T120000_abc12345)")
    args = parser.parse_args()

    # Try to load specs for hole detection
    try:
        from .orchestrator import load_specs
        specs = load_specs(["all"])
    except Exception:
        specs = None

    path = generate_report(args.run, specs=specs)
    print(f"report written: {path}")

    summary = load_summary(RUNS_DIR / args.run)
    if summary:
        print(f"  verify rate: {_fmt_pct(summary.get('overall_verify_rate', 0))}")
        print(f"  macros: {summary.get('macro_count', '?')}")
        print(f"  holes: {summary.get('holes_detected', '?')}")


if __name__ == "__main__":
    main()
