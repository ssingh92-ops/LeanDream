"""leandream audit v41 — check all V4.1 integration points.

Usage:
    leandream audit v41
    leandream audit v41 --json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .verify import REPO_ROOT

# ---- Paths ------------------------------------------------------------------

RUNS_DIR = REPO_ROOT / "runs"
CARDS_PATH = REPO_ROOT / "data" / "cards" / "cards.jsonl"
BANDIT_PATH = REPO_ROOT / "data" / "bandit" / "bandit.json"
PROPERTIES_LEAN = REPO_ROOT / "lean" / "LeanDream" / "Properties.lean"
MACROS_LEAN = REPO_ROOT / "lean" / "LeanDream" / "Macros.lean"

# ---- Result collection ------------------------------------------------------

_PASS = "PASS"
_FAIL = "FAIL"
_WARN = "WARN"


class AuditResult:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, level: str, label: str, message: str) -> None:
        self.items.append({"level": level, "label": label, "message": message})

    def ok(self, label: str, message: str) -> None:
        self.add(_PASS, label, message)

    def fail(self, label: str, message: str) -> None:
        self.add(_FAIL, label, message)

    def warn(self, label: str, message: str) -> None:
        self.add(_WARN, label, message)

    def counts(self) -> tuple[int, int, int]:
        p = sum(1 for i in self.items if i["level"] == _PASS)
        f = sum(1 for i in self.items if i["level"] == _FAIL)
        w = sum(1 for i in self.items if i["level"] == _WARN)
        return p, f, w

    def print_text(self) -> None:
        for item in self.items:
            print(f"[{item['level']}] {item['label']}: {item['message']}")
        p, f, w = self.counts()
        print(f"\nSUMMARY: {p} PASS, {f} FAIL, {w} WARN")

    def print_json(self) -> None:
        p, f, w = self.counts()
        print(json.dumps({
            "results": self.items,
            "summary": {"pass": p, "fail": f, "warn": w},
        }, indent=2))


# ---- Helper: find most-recent run dir ---------------------------------------

def _latest_run_dir() -> Path | None:
    if not RUNS_DIR.exists():
        return None
    dirs = sorted(
        (d for d in RUNS_DIR.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    return dirs[0] if dirs else None


def _load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


# ---- Check A: Attempt records -----------------------------------------------

def check_attempts(ar: AuditResult) -> None:
    label = "A. Attempt records"
    latest = _latest_run_dir()
    if latest is None:
        ar.fail(label, "no run directories found under runs/")
        return

    records = _load_jsonl(latest / "attempts.jsonl")
    if not records:
        ar.fail(label, f"runs/{latest.name}/attempts.jsonl is empty or missing")
        return

    # Sample up to 20 records
    sample = records[:20]
    required = {"run_id", "stage", "iteration", "spec", "status", "error_type",
                "proof_mode", "repair_pass"}
    optional_warn = {"retrieved_card_ids", "environment", "info_structure"}

    missing_required: list[str] = []
    missing_ast: list[int] = []
    missing_optional: set[str] = set()

    for rec in sample:
        missing_required.extend(f for f in required if f not in rec)
        if rec.get("raw_circuit") is None and rec.get("raw_ast") is None:
            missing_ast.append(rec.get("iteration", "?"))
        for f in optional_warn:
            if f not in rec:
                missing_optional.add(f)

    issues: list[str] = []
    if missing_required:
        issues.append(f"missing required fields: {sorted(set(missing_required))}")
    if missing_ast:
        issues.append(f"{len(missing_ast)} record(s) missing both raw_circuit and raw_ast")

    if issues:
        ar.fail(label, f"{len(sample)} attempts sampled — " + "; ".join(issues))
    else:
        ar.ok(label, f"{len(sample)} attempts sampled, all have required fields")

    if missing_optional:
        ar.warn(
            f"{label} (optional fields)",
            f"fields not present in sampled records: {sorted(missing_optional)}"
        )


# ---- Check B: Endpoints (inspect FastAPI routes) ----------------------------

def check_endpoints(ar: AuditResult) -> None:
    label = "B. Endpoints"
    required_routes = {
        "/api/runs",
        "/api/runs/latest",
        "/api/holes",
        "/api/forest-graph",
        "/api/summary",
        "/api/metrics",
        "/api/attempts",
        "/api/proof-modes",
        "/api/info-structure",
        "/api/accumulated-analysis",
    }
    try:
        from .web import app  # type: ignore[import]
        registered = {route.path for route in app.routes}
        missing = required_routes - registered
        if missing:
            ar.fail(label, f"missing routes: {sorted(missing)}")
        else:
            ar.ok(label, f"all {len(required_routes)} required routes present")
    except Exception as exc:
        ar.fail(label, f"could not import leandream.web: {exc}")


# ---- Check C: Card types in the card store ----------------------------------

def check_card_types(ar: AuditResult) -> None:
    label = "C. Card types"
    required_types = {"macro", "theorem_property", "failure", "hole", "strategy"}
    warn_if_zero = {"hole", "failure"}

    records = _load_jsonl(CARDS_PATH)
    if not records:
        ar.warn(label, f"cards.jsonl is empty or missing at {CARDS_PATH}")
        return

    by_type: dict[str, int] = {}
    for rec in records:
        ct = rec.get("card_type", "unknown")
        by_type[ct] = by_type.get(ct, 0) + 1

    missing = required_types - set(by_type)
    zero_warn = [t for t in warn_if_zero if by_type.get(t, 0) == 0]

    if missing:
        # Some of these may just be zero — distinguish
        present_counts = {t: by_type.get(t, 0) for t in required_types}
        truly_missing = {t for t in missing if by_type.get(t, 0) == 0}
        if truly_missing & warn_if_zero:
            for t in sorted(truly_missing & warn_if_zero):
                ar.warn(label, f"no {t} cards yet (needs a run with relevant data)")
            truly_missing -= warn_if_zero
        if truly_missing:
            ar.fail(label, f"card types with 0 cards: {sorted(truly_missing)}")
        else:
            ar.ok(label, f"required types present (counts: {present_counts})")
    else:
        counts_str = ", ".join(f"{t}:{by_type[t]}" for t in sorted(required_types))
        if zero_warn:
            for t in sorted(zero_warn):
                ar.warn(label, f"no {t} cards yet (needs a run with relevant data)")
        ar.ok(label, f"all card types present — {counts_str}")


# ---- Check D: HoleCard payload fields ---------------------------------------

def check_hole_cards(ar: AuditResult) -> None:
    label = "D. HoleCard payload"
    required_fields = {"hole_id", "hole_type", "specs", "severity", "status",
                       "detected_by", "trust_level", "evidence"}

    records = _load_jsonl(CARDS_PATH)
    hole_records = [r for r in records if r.get("card_type") == "hole"]

    if not hole_records:
        ar.warn(label, "no hole cards found — skip field validation (run with failures to generate)")
        return

    failures: list[str] = []
    for rec in hole_records:
        payload = rec.get("payload", {})
        missing = sorted(required_fields - set(payload))
        if missing:
            hid = payload.get("hole_id", rec.get("card_id", "?"))
            failures.append(f"hole {hid!r} missing: {missing}")

    if failures:
        ar.fail(label, f"{len(hole_records)} cards checked — " + "; ".join(failures[:5]))
    else:
        ar.ok(label, f"{len(hole_records)} hole card(s) checked, all fields present")


# ---- Check E: MacroCard payload fields --------------------------------------

def check_macro_cards(ar: AuditResult) -> None:
    label = "E. MacroCard payload"
    required_fields = {"name", "arity", "body_repr", "legal_call_schema", "trust_level", "properties"}
    warn_fields = {"tt_key"}

    records = _load_jsonl(CARDS_PATH)
    macro_records = [r for r in records if r.get("card_type") == "macro"]

    if not macro_records:
        ar.warn(label, "no macro cards found in card store")
        return

    failures: list[str] = []
    warn_missing: set[str] = set()
    for rec in macro_records:
        payload = rec.get("payload", {})
        missing = sorted(required_fields - set(payload))
        if missing:
            failures.append(f"macro {payload.get('name', '?')!r} missing: {missing}")
        for f in warn_fields:
            if f not in payload or payload[f] is None:
                warn_missing.add(f)

    if failures:
        ar.fail(label, f"{len(macro_records)} cards checked — " + "; ".join(failures[:5]))
    else:
        ar.ok(label, f"{len(macro_records)} macro card(s) checked, all required fields present")

    if warn_missing:
        ar.warn(f"{label} (optional)", f"fields absent/null in some cards: {sorted(warn_missing)}")


# ---- Check F: StrategyCard existence ----------------------------------------

def check_strategy_cards(ar: AuditResult) -> None:
    label = "F. StrategyCard existence"
    records = _load_jsonl(CARDS_PATH)
    strategy_records = [r for r in records if r.get("card_type") == "strategy"]

    if not strategy_records:
        ar.fail(label, "no strategy cards found in card store — run indexer to populate")
        return

    with_formula = [r for r in strategy_records if r.get("payload", {}).get("formula")]
    names = {r.get("payload", {}).get("name") for r in strategy_records}

    issues: list[str] = []
    if not with_formula:
        issues.append("no strategy card has a non-null formula")
    if "mux2_formula" not in names:
        issues.append("mux2_formula card not found")
    if "majority3_formula" not in names:
        issues.append("majority3_formula card not found")

    if issues:
        ar.fail(label, f"{len(strategy_records)} strategy cards — " + "; ".join(issues))
    else:
        ar.ok(label,
              f"{len(strategy_records)} strategy cards, {len(with_formula)} with formula, "
              "mux2_formula and majority3_formula present")


# ---- Check G: Bandit file ---------------------------------------------------

def check_bandit(ar: AuditResult) -> None:
    label = "G. Bandit file"
    if not BANDIT_PATH.exists():
        ar.fail(label, f"bandit.json not found at {BANDIT_PATH}")
        return
    try:
        data = json.loads(BANDIT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        ar.fail(label, f"bandit.json is not valid JSON: {exc}")
        return

    if not data:
        ar.warn(label, "bandit.json exists but is empty")
        return

    # Look for arms key or any dict/list content
    if isinstance(data, dict):
        keys = list(data.keys())
        ar.ok(label, f"bandit.json present, top-level keys: {keys[:6]}")
    elif isinstance(data, list):
        ar.ok(label, f"bandit.json present, {len(data)} entries")
    else:
        ar.warn(label, f"bandit.json has unexpected root type: {type(data).__name__}")


# ---- Check H: Runs directory ------------------------------------------------

def check_runs_dir(ar: AuditResult) -> None:
    label = "H. Runs directory"
    if not RUNS_DIR.exists():
        ar.fail(label, f"runs/ directory not found at {RUNS_DIR}")
        return

    run_dirs_with_attempts = [
        d for d in RUNS_DIR.iterdir()
        if d.is_dir() and (d / "attempts.jsonl").exists()
    ]
    if not run_dirs_with_attempts:
        ar.fail(label, "runs/ directory exists but no run contains attempts.jsonl")
    else:
        ar.ok(label,
              f"{len(run_dirs_with_attempts)} run(s) with attempts.jsonl "
              f"(latest: {sorted(run_dirs_with_attempts, key=lambda d: d.stat().st_mtime)[-1].name})")


# ---- Check I: Properties.lean -----------------------------------------------

def check_properties_lean(ar: AuditResult) -> None:
    label = "I. Properties.lean"
    if not PROPERTIES_LEAN.exists():
        ar.fail(label, f"file not found: {PROPERTIES_LEAN}")
        return

    text = PROPERTIES_LEAN.read_text(encoding="utf-8")
    count = text.count("theorem ")
    if count >= 20:
        ar.ok(label, f"{count} 'theorem ' occurrences found (>= 20 required)")
    else:
        ar.fail(label, f"only {count} 'theorem ' occurrences found (need >= 20)")


# ---- Check J: Macros.lean ---------------------------------------------------

def check_macros_lean(ar: AuditResult) -> None:
    label = "J. Macros.lean"
    if not MACROS_LEAN.exists():
        ar.fail(label, f"file not found: {MACROS_LEAN}")
        return

    text = MACROS_LEAN.read_text(encoding="utf-8")
    count = text.count("def macro_")
    if count >= 1:
        ar.ok(label, f"{count} 'def macro_' definition(s) found")
    else:
        ar.fail(label, "no 'def macro_' definitions found in Macros.lean")


# ---- Check K: RAG indexer integration ---------------------------------------

def check_rag_indexer(ar: AuditResult) -> None:
    label = "K. RAG indexer integration"
    try:
        from .memory import indexer  # noqa: F401
    except Exception as exc:
        ar.fail(label, f"cannot import leandream.memory.indexer: {exc}")
        return

    missing: list[str] = []
    for fn_name in ("run_indexer", "index_strategies"):
        if not hasattr(indexer, fn_name):
            missing.append(fn_name)

    if missing:
        ar.fail(label, f"leandream.memory.indexer missing: {missing}")
    else:
        ar.ok(label, "run_indexer and index_strategies importable from leandream.memory.indexer")


# ---- Check L: Reports check -------------------------------------------------

def check_report(ar: AuditResult) -> None:
    label = "L. Reports check"
    latest = _latest_run_dir()
    if latest is None:
        ar.warn(label, "no run directories found — cannot check report.md")
        return

    report_path = latest / "report.md"
    if not report_path.exists():
        ar.warn(label, f"report.md not found in latest run {latest.name} — run `leandream report`")
        return

    text = report_path.read_text(encoding="utf-8").lower()
    expected_sections = ["holes", "failure", "mux", "majority", "macro reuse", "proof_mode"]
    missing_sections = [s for s in expected_sections if s not in text]

    if missing_sections:
        for s in missing_sections:
            ar.warn(label, f"section keyword '{s}' not found in report.md")
        ar.ok(label,
              f"report.md found in {latest.name} ({len(expected_sections) - len(missing_sections)}/"
              f"{len(expected_sections)} sections present)")
    else:
        ar.ok(label, f"report.md found in {latest.name}, all expected section keywords present")


# ---- Main entrypoint --------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    # Normalise invocation: accept both "v41 [--json]" and "audit v41 [--json]"
    # so the command works as `leandream-audit v41` or `leandream audit v41`.
    if argv and argv[0] == "audit":
        argv = argv[1:]

    if not argv or argv[0] != "v41":
        print("Usage: leandream audit v41 [--json]", file=sys.stderr)
        sys.exit(1)

    as_json = "--json" in argv

    ar = AuditResult()

    check_attempts(ar)
    check_endpoints(ar)
    check_card_types(ar)
    check_hole_cards(ar)
    check_macro_cards(ar)
    check_strategy_cards(ar)
    check_bandit(ar)
    check_runs_dir(ar)
    check_properties_lean(ar)
    check_macros_lean(ar)
    check_rag_indexer(ar)
    check_report(ar)

    if as_json:
        ar.print_json()
    else:
        ar.print_text()

    _, fails, _ = ar.counts()
    sys.exit(1 if fails > 0 else 0)


if __name__ == "__main__":
    main()
