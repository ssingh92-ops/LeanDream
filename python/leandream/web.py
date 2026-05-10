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
