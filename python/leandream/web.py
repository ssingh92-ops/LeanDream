"""FastAPI viewer for the LeanDream proof forest, macro registry, and spec library."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import installer, promptlog
from .attempts import RUNS_DIR, load as _load_run_attempts
from .verify import REPO_ROOT

SPECS_DIR = REPO_ROOT / "specs"
PROOFS_DIR = REPO_ROOT / "proofs"
PROMPTS_DIR = REPO_ROOT / "prompts"
STATIC_DIR = Path(__file__).resolve().parent / "web_static"
MACROS_LEAN_PATH = REPO_ROOT / "lean" / "LeanDream" / "Macros.lean"


app = FastAPI(title="LeanDream Viewer", docs_url="/api/docs", redoc_url=None)


@app.get("/api/stats")
def stats() -> dict:
    proof_count = sum(1 for _ in PROOFS_DIR.rglob("*.json")) if PROOFS_DIR.exists() else 0
    spec_count = sum(1 for _ in SPECS_DIR.glob("*.json")) if SPECS_DIR.exists() else 0
    prompt_count = sum(1 for _ in PROMPTS_DIR.rglob("*.json")) if PROMPTS_DIR.exists() else 0
    registry = installer.load_registry()
    iters_seen: set[int] = set()
    if PROOFS_DIR.exists():
        for f in PROOFS_DIR.rglob("*.json"):
            try:
                iters_seen.add(json.loads(f.read_text()).get("iteration", 0))
            except Exception:
                pass
    attempt_count = 0
    if RUNS_DIR.exists():
        for d in RUNS_DIR.iterdir():
            p = d / "attempts.jsonl"
            if p.exists():
                attempt_count += sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip())
    try:
        from .memory.card_store import load_all as _load_cards
        card_count = len(_load_cards())
    except Exception:
        card_count = 0
    return {
        "specs": spec_count,
        "proofs": proof_count,
        "macros": len(registry),
        "prompts": prompt_count,
        "attempts": attempt_count,
        "cards": card_count,
        "iterations_seen": sorted(iters_seen),
    }


@app.get("/api/runs")
def list_runs() -> list[str]:
    if not RUNS_DIR.exists():
        return []
    return sorted((d.name for d in RUNS_DIR.iterdir() if d.is_dir()), reverse=True)


@app.get("/api/runs/latest")
def latest_run() -> dict:
    """Return metadata about the most recently modified run directory."""
    if not RUNS_DIR.exists():
        return {"run_id": None, "message": "no runs yet"}
    dirs = sorted(
        (d for d in RUNS_DIR.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if not dirs:
        return {"run_id": None, "message": "no runs yet"}
    latest = dirs[0]
    from .metrics import load_summary
    summary = load_summary(latest) or {}
    attempt_count = 0
    p = latest / "attempts.jsonl"
    if p.exists():
        attempt_count = sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip())
    return {
        "run_id": latest.name,
        "attempts": attempt_count,
        "macros": summary.get("macro_count", 0),
        "verified": summary.get("total_verified", 0),
        "verify_rate": summary.get("overall_verify_rate", 0.0),
        "stage": summary.get("stage_reached"),
        "recommendation": summary.get("recommended_next_action"),
    }


@app.get("/api/attempts")
def list_all_attempts(run: str | None = None) -> list[dict]:
    """Return all attempt records, newest first. Pass ?run=<run_id> to filter."""
    if not RUNS_DIR.exists():
        return []
    if run:
        dirs = [RUNS_DIR / run]
    else:
        dirs = sorted(d for d in RUNS_DIR.iterdir() if d.is_dir())
    out: list[dict] = []
    for d in dirs:
        if d.is_dir():
            out.extend(_load_run_attempts(d))
    out.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return out


@app.get("/api/bandit")
def bandit_summary() -> dict:
    from .learning.contextual_bandit import ContextualBandit
    return ContextualBandit.load().summary()


@app.get("/api/cards")
def list_cards(card_type: str | None = None) -> list[dict]:
    from .memory.card_store import load_all
    cards = load_all()
    if card_type:
        cards = [c for c in cards if c.card_type == card_type]
    return [c.to_dict() for c in cards]


@app.get("/api/holes")
def list_holes(run: str | None = None) -> dict:
    """Return HoleCards for a run (or all accumulated holes).

    Response: {"holes": [...], "message": str}
    Sources checked (in order):
      1. Global card store (data/cards/cards.jsonl) filtered to relevant specs
      2. run-level attempts.jsonl for hole_detected status records
    """
    from .memory.card_store import load_all

    # Determine which specs appeared in this run (for filtering)
    run_specs: set[str] = set()
    if run:
        run_dir = RUNS_DIR / run
        if run_dir.exists():
            for rec in _load_run_attempts(run_dir):
                if s := rec.get("spec"):
                    run_specs.add(s)

    all_cards = load_all()
    hole_cards = [c for c in all_cards if c.card_type == "hole"]

    # If a run is selected, filter to holes whose specs appeared in that run
    if run_specs:
        filtered = []
        for c in hole_cards:
            card_specs = set(c.payload.get("specs") or [])
            if not card_specs or card_specs & run_specs:
                filtered.append(c)
        hole_cards = filtered

    # Also surface holes from attempt records (hole_detected status)
    extra_hole_ids: set[str] = set()
    if run:
        run_dir = RUNS_DIR / run
        if run_dir.exists():
            for rec in _load_run_attempts(run_dir):
                if rec.get("status") in ("hole_detected",) and rec.get("hole_type"):
                    # Synthesise a lightweight hole dict if not already in cards
                    hid = rec.get("spec", "?") + ":" + rec.get("hole_type", "?")
                    extra_hole_ids.add(hid)

    out = [c.to_dict() for c in hole_cards]
    if not out:
        msg = (
            f"No holes detected for run {run}" if run
            else "No holes detected across all runs"
        )
    else:
        msg = f"{len(out)} hole card(s)"
    return {"holes": out, "message": msg}


@app.get("/api/analysis")
def get_analysis(run: str | None = None) -> dict:
    """Return macro reuse / composition analysis for a run (or latest)."""
    from .analysis import analyse_run, run_analysis_to_dict
    if run:
        dirs = [RUNS_DIR / run] if (RUNS_DIR / run).exists() else []
    else:
        dirs = sorted(d for d in RUNS_DIR.iterdir() if d.is_dir()) if RUNS_DIR.exists() else []
    all_recs: list[dict] = []
    for d in dirs:
        all_recs.extend(_load_run_attempts(d))
    registry = installer.load_registry()
    analysis = analyse_run(all_recs, registry)
    return run_analysis_to_dict(analysis)


@app.get("/api/curriculum")
def get_curriculum() -> list[dict]:
    """Return curriculum stage definitions and current pass/fail state.

    First checks for stage_N_metrics.json files written by the curriculum runner.
    Falls back to evaluate_gate against all accumulated run directories.
    """
    from .curriculum import CURRICULUM, evaluate_gate
    registry = installer.load_registry()

    # Collect any stage metrics files written by run_curriculum()
    stage_file_data: dict[int, dict] = {}
    if RUNS_DIR.exists():
        for run_dir in sorted(d for d in RUNS_DIR.iterdir() if d.is_dir()):
            for stage in CURRICULUM:
                p = run_dir / f"stage_{stage.index}_metrics.json"
                if p.exists():
                    try:
                        stage_file_data[stage.index] = json.loads(p.read_text(encoding="utf-8"))
                    except Exception:
                        pass

    run_dirs = sorted(d for d in RUNS_DIR.iterdir() if d.is_dir()) if RUNS_DIR.exists() else []

    out = []
    for stage in CURRICULUM:
        if stage.index in stage_file_data:
            d = stage_file_data[stage.index]
            gate_dict = {
                "passed": d.get("gate_passed"),
                "verify_ratio": d.get("verify_ratio", 0.0),
                "macro_count": d.get("macro_count", 0),
                "reason": d.get("gate_reason", "from stage file"),
                "source": "stage_metrics_file",
            }
        elif run_dirs:
            try:
                gate = evaluate_gate(stage, run_dirs, registry)
                gate_dict = {
                    "passed": gate.passed,
                    "verify_ratio": gate.verify_ratio,
                    "macro_count": gate.macro_count,
                    "reason": gate.reason,
                    "source": "accumulated_runs",
                }
            except Exception as exc:
                gate_dict = {
                    "passed": None, "verify_ratio": 0.0, "macro_count": 0,
                    "reason": f"evaluation error: {exc}", "source": "error",
                }
        else:
            gate_dict = {
                "passed": None, "verify_ratio": 0.0, "macro_count": 0,
                "reason": "no runs yet", "source": "none",
            }
        out.append({
            "index": stage.index,
            "name": stage.name,
            "specs": stage.specs,
            "iterations": stage.iterations,
            "min_verify_ratio": stage.min_verify_ratio,
            "min_macros": stage.min_macros,
            "gate": gate_dict,
        })
    return out


@app.get("/api/summary")
def get_summary(run: str | None = None) -> dict:
    """Return summary.json for a run (or latest run)."""
    from .metrics import load_summary
    if run:
        target = RUNS_DIR / run
    else:
        if not RUNS_DIR.exists():
            return {}
        dirs = sorted(d for d in RUNS_DIR.iterdir() if d.is_dir())
        target = dirs[-1] if dirs else None
    if not target:
        return {}
    s = load_summary(target)
    return s or {}


@app.get("/api/forest-graph")
def forest_graph(run: str | None = None) -> dict:
    """Return proof forest as nodes+edges.

    When ?run=<run_id> is given:
      1. Loads runs/<run_id>/forest_graph.json if present.
      2. Otherwise reconstructs from runs/<run_id>/attempts.jsonl.
         Green = verified, Red = failed, Yellow = hole_detected.
    Always appends macro nodes (purple) and HoleCards (yellow dashed).
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_specs: dict[str, str] = {}

    # ---- Run-scoped reconstruction from attempts.jsonl ----
    if run:
        run_dir = RUNS_DIR / run if RUNS_DIR else None
        cached_graph = run_dir / "forest_graph.json" if run_dir else None
        if cached_graph and cached_graph.exists():
            try:
                return json.loads(cached_graph.read_text())
            except Exception:
                pass
        # Reconstruct from attempts.jsonl
        if run_dir and run_dir.exists():
            recs = _load_run_attempts(run_dir)
            for rec in recs:
                spec = rec.get("spec", "?")
                status = rec.get("status", "?")
                iteration = rec.get("iteration", 0)
                node_id = f"attempt:{spec}:{iteration}:{rec.get('timestamp','')[:19]}"

                if spec not in seen_specs:
                    sid = f"spec:{spec}"
                    seen_specs[spec] = sid
                    nodes.append({"id": sid, "label": spec, "type": "spec", "color": "#f59e0b"})

                if status == "verified":
                    color = "#22c55e"
                    ntype = "proof"
                elif status == "hole_detected":
                    color = "#facc15"
                    ntype = "hole"
                else:
                    color = "#f85149"
                    ntype = "failure"

                nodes.append({
                    "id": node_id,
                    "label": f"#{iteration}",
                    "type": ntype,
                    "color": color,
                    "spec": spec,
                    "status": status,
                    "iteration": iteration,
                    "elapsed": rec.get("lean_time_ms", 0) / 1000 if rec.get("lean_time_ms") else 0,
                    "error_type": rec.get("error_type"),
                    "proof_mode": rec.get("proof_mode"),
                })
                edges.append({"from": seen_specs[spec], "to": node_id})

    else:
        # Legacy: read from proofs directory
        if PROOFS_DIR.exists():
            for f in sorted(PROOFS_DIR.rglob("*.json")):
                try:
                    data = json.loads(f.read_text())
                except Exception:
                    continue
                spec = data.get("spec", "?")
                proof_id = f.name
                if spec not in seen_specs:
                    spec_node_id = f"spec:{spec}"
                    seen_specs[spec] = spec_node_id
                    nodes.append({"id": spec_node_id, "label": spec, "type": "spec", "color": "#f59e0b"})
                proof_node_id = f"proof:{proof_id}"
                nodes.append({
                    "id": proof_node_id,
                    "label": f"#{data.get('iteration',0)}",
                    "type": "proof",
                    "color": "#22c55e",
                    "spec": spec,
                    "iteration": data.get("iteration", 0),
                    "elapsed": data.get("elapsed_seconds", 0),
                })
                edges.append({"from": seen_specs[spec], "to": proof_node_id})

    # ---- Macro nodes (purple) always appended ----
    registry = installer.load_registry()
    for name, info in registry.items():
        nodes.append({
            "id": f"macro:{name}",
            "label": name,
            "type": "macro",
            "color": "#a855f7",
            "arity": info.get("arity", 0),
            "level": info.get("macro_level", 0),
            "body": info.get("body_repr", ""),
        })

    # ---- HoleCards (yellow, dashed edges) ----
    try:
        from .memory.card_store import load_all
        for card in load_all():
            if card.card_type == "hole":
                hid = card.payload.get("hole_id", card.card_id)
                spec_name = (card.payload.get("specs") or [None])[0]
                hole_node_id = f"hole:{hid}"
                # Skip if already added from attempt reconstruction
                if not any(n["id"] == hole_node_id for n in nodes):
                    nodes.append({
                        "id": hole_node_id,
                        "label": card.payload.get("hole_type", "hole"),
                        "type": "hole",
                        "color": "#facc15",
                        "severity": card.payload.get("severity", "warning"),
                        "spec": spec_name,
                    })
                    if spec_name and spec_name in seen_specs:
                        edges.append({"from": seen_specs[spec_name], "to": hole_node_id, "dashed": True})
    except Exception:
        pass

    return {"nodes": nodes, "edges": edges}


@app.get("/api/metrics")
def get_metrics(run: str | None = None) -> list[dict]:
    """Return metrics.csv rows as JSON for a run (or latest)."""
    import csv
    if run:
        target = RUNS_DIR / run
    else:
        if not RUNS_DIR.exists():
            return []
        dirs = sorted(d for d in RUNS_DIR.iterdir() if d.is_dir())
        target = dirs[-1] if dirs else None
    if not target:
        return []
    p = target / "metrics.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


@app.get("/api/proof-modes")
def get_proof_modes(run: str | None = None) -> dict:
    """Distribution of proof modes (decide/native_decide/failed) for a run."""
    from collections import Counter
    from .memory.card_store import load_all as _load_all_cards
    if run:
        target = RUNS_DIR / run
    else:
        if not RUNS_DIR.exists():
            return {}
        dirs = sorted(d for d in RUNS_DIR.iterdir() if d.is_dir())
        target = dirs[-1] if dirs else None
    if not target:
        return {}
    all_recs = _load_run_attempts(target)
    verified = [r for r in all_recs if r.get("status") == "verified"]
    mode_counter: Counter = Counter(r.get("proof_mode") or "unknown" for r in verified)
    failed_counter: Counter = Counter(r.get("status") for r in all_recs if r.get("status") != "verified")
    registry = installer.load_registry()
    properties_proved = sum(len(info.get("properties") or {}) for info in registry.values())
    return {
        "proof_mode_distribution": dict(mode_counter),
        "total_verified": len(verified),
        "total_failed": len(all_recs) - len(verified),
        "top_failure_modes": dict(failed_counter.most_common(5)),
        "properties_proved": properties_proved,
        "theorem_cards_exported": sum(
            1 for c in _load_all_cards()
            if c.card_type == "theorem_property"
        ),
    }


@app.get("/api/lean-engineering")
def get_lean_engineering(run: str | None = None) -> dict:
    """Lean proof engineering summary: proof modes, macro theorem coverage, theorem gen results."""
    from collections import Counter
    from .memory.card_store import load_all as _load_all_cards

    # Determine target run directory (same logic as other run-scoped endpoints)
    if run:
        target = RUNS_DIR / run
    else:
        if not RUNS_DIR.exists():
            target = None
        else:
            dirs = sorted(d for d in RUNS_DIR.iterdir() if d.is_dir())
            target = dirs[-1] if dirs else None

    # Proof mode distribution (reuse logic from get_proof_modes)
    proof_mode_dist: dict[str, int] = {}
    total_verified = 0
    if target and target.exists():
        all_recs = _load_run_attempts(target)
        verified = [r for r in all_recs if r.get("status") == "verified"]
        total_verified = len(verified)
        mode_counter: Counter = Counter(r.get("proof_mode") or "unknown" for r in verified)
        proof_mode_dist = dict(mode_counter)

    # Registry / card store data
    registry = installer.load_registry()
    stable_macros = list(registry.keys())

    try:
        all_cards = _load_all_cards()
    except Exception:
        all_cards = []

    # Count theorem_property cards total and per macro
    theorem_cards = [c for c in all_cards if c.card_type == "theorem_property"]
    theorem_cards_total = len(theorem_cards)

    # Group theorem cards by macro name to decide coverage
    cards_by_macro: dict[str, list] = {}
    for c in theorem_cards:
        mname = c.payload.get("macro_name") or c.payload.get("name")
        if mname:
            cards_by_macro.setdefault(mname, []).append(c)

    macros_with_lean_theorems: list[str] = []
    macros_prompt_only: list[str] = []
    for mname in stable_macros:
        cards = cards_by_macro.get(mname, [])
        has_lean = any(
            c.payload.get("trust_level") == "lean_theorem_checked"
            for c in cards
        )
        if has_lean:
            macros_with_lean_theorems.append(mname)
        else:
            macros_prompt_only.append(mname)

    lean_checked_properties = len(macros_with_lean_theorems)
    prompt_only_properties = len(macros_prompt_only)

    # Theorem generation results
    theorem_gen_results: list[dict] = []
    if target and target.exists():
        tgr_path = target / "theorem_gen_results.json"
        if tgr_path.exists():
            try:
                theorem_gen_results = json.loads(tgr_path.read_text(encoding="utf-8"))
            except Exception:
                theorem_gen_results = []

    # Proof holes (hole-type cards)
    proof_holes = [c.to_dict() for c in all_cards if c.card_type == "hole"]

    return {
        "proof_mode_distribution": proof_mode_dist,
        "total_verified": total_verified,
        "theorem_cards_total": theorem_cards_total,
        "lean_checked_properties": lean_checked_properties,
        "prompt_only_properties": prompt_only_properties,
        "stable_macros": stable_macros,
        "macros_with_lean_theorems": macros_with_lean_theorems,
        "macros_prompt_only": macros_prompt_only,
        "theorem_gen_results": theorem_gen_results,
        "proof_holes": proof_holes,
    }


@app.get("/api/info-structure")
def get_info_structure() -> dict:
    """Tagged info-structure observations across all macros and proof traces."""
    from .memory.card_store import load_all as _load_cards_info
    cards = _load_cards_info()
    registry = installer.load_registry()

    ip_macros = []
    il_macros = []
    for name, info in registry.items():
        is_ = info.get("info_structure") or {}
        if is_.get("information_preserving"):
            ip_macros.append({"name": name, "arity": info.get("arity"), "tt_key": info.get("tt_key")})
        elif is_.get("information_losing"):
            il_macros.append({"name": name, "arity": info.get("arity"), "tt_key": info.get("tt_key")})

    # Count trace cards with info_structure annotations
    annotated_traces = sum(
        1 for c in cards
        if c.card_type == "proof_trace" and any(
            c.info_structure.get(k) is not None
            for k in ("information_preserving", "information_losing")
        )
    )

    return {
        "information_preserving_macros": ip_macros,
        "information_losing_macros": il_macros,
        "annotated_proof_traces": annotated_traces,
        "total_macros": len(registry),
        "summary": {
            "preserving": len(ip_macros),
            "losing": len(il_macros),
            "unannotated": len(registry) - len(ip_macros) - len(il_macros),
        },
    }


@app.get("/api/accumulated-analysis")
def get_accumulated_analysis() -> dict:
    """Cross-run accumulated metrics for macro growth, hole recurrence, and bandit."""
    from .analysis import analyse_accumulated_runs
    acc = analyse_accumulated_runs()
    return {
        "runs_analysed": acc.runs_analysed,
        "run_ids": acc.run_ids,
        "macro_growth": acc.macro_growth,
        "hole_recurrence": acc.hole_recurrence,
        "mux2_status_by_run": acc.mux2_status_by_run,
        "total_verified": acc.total_verified,
        "total_attempted": acc.total_attempted,
        "bandit_top_arms": acc.bandit_top_arms,
    }


@app.get("/api/specs")
def list_specs() -> list[dict]:
    if not SPECS_DIR.exists():
        return []
    out = []
    for f in sorted(SPECS_DIR.glob("*.json")):
        out.append(json.loads(f.read_text()))
    return out


@app.get("/api/specs/{name}")
def get_spec(name: str) -> dict:
    p = SPECS_DIR / f"{name}.json"
    if not p.exists():
        raise HTTPException(404, f"spec not found: {name}")
    return json.loads(p.read_text())


@app.get("/api/macros")
def list_macros() -> dict:
    return installer.load_registry()


@app.get("/api/macros/lean")
def macros_lean_source() -> dict:
    if not MACROS_LEAN_PATH.exists():
        raise HTTPException(404, "Macros.lean not found")
    return {"source": MACROS_LEAN_PATH.read_text()}


@app.get("/api/proofs")
def list_proofs() -> list[dict]:
    if not PROOFS_DIR.exists():
        return []
    out = []
    for f in sorted(PROOFS_DIR.rglob("*.json")):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        out.append({
            "spec": data.get("spec"),
            "timestamp": data.get("timestamp"),
            "iteration": data.get("iteration", 0),
            "elapsed_seconds": data.get("elapsed_seconds", 0.0),
            "filename": f.name,
        })
    out.sort(key=lambda r: (r["spec"], r["timestamp"]))
    return out


@app.get("/api/proofs/{spec}/{filename}")
def get_proof(spec: str, filename: str) -> dict:
    p = PROOFS_DIR / spec / filename
    if not p.exists():
        raise HTTPException(404, f"proof not found: {spec}/{filename}")
    return json.loads(p.read_text())


@app.get("/api/prompts")
def list_prompts() -> list[dict]:
    out = []
    for ix in promptlog.iter_index():
        out.append({
            "spec": ix.spec,
            "iteration": ix.iteration,
            "timestamp": ix.timestamp,
            "model": ix.model,
            "elapsed_seconds": ix.elapsed_seconds,
            "ok": ix.ok,
            "macros_count": ix.macros_count,
            "filename": ix.filename,
        })
    out.sort(key=lambda r: (r["iteration"], r["spec"], r["timestamp"]))
    return out


@app.get("/api/prompts/{spec}/{filename}")
def get_prompt(spec: str, filename: str) -> dict:
    p = PROMPTS_DIR / spec / filename
    if not p.exists():
        raise HTTPException(404, f"prompt not found: {spec}/{filename}")
    return json.loads(p.read_text())


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> None:
    """CLI entry point: `leandream-web` or `python -m leandream.web`."""
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(prog="leandream-web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    print(f"LeanDream viewer at http://{args.host}:{args.port}")
    uvicorn.run(
        "leandream.web:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
