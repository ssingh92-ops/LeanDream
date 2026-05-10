"""Main loop: LLM -> verify -> record -> mine -> install -> repeat."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from . import attempts, forest, installer, miner, properties
from .learning.contextual_bandit import ContextualBandit, _macros_used, compute_reward
from .memory.indexer import run_indexer
from .memory import retriever as _mem_retriever
from .memory import prompt_pack as _mem_prompt_pack
from .memory.theorem_exporter import run_exporter as _run_theorem_exporter
from .repair import build_repair_pack, is_repairable
from .ast import (
    ArityError,
    Circuit,
    ExpansionCycleError,
    ExpansionDepthError,
    expand_macros,
)
from .verify import REPO_ROOT, reset_candidate, verify_candidate

SPECS_DIR = REPO_ROOT / "specs"
PROOFS_DIR = REPO_ROOT / "proofs"
PROMPTS_DIR = REPO_ROOT / "prompts"
MACROS_REGISTRY = REPO_ROOT / "macros" / "registry.json"
MACROS_LEAN = REPO_ROOT / "lean" / "LeanDream" / "Macros.lean"
PROPERTIES_LEAN = REPO_ROOT / "lean" / "LeanDream" / "Properties.lean"

_CIRCUIT_ADAPTER: TypeAdapter[Circuit] = TypeAdapter(Circuit)

_EMPTY_MACROS_LEAN = """\
import LeanDream.DSL

namespace LeanDream.Macros
open LeanDream

-- Mined macros are appended below this line by the installer.
-- BEGIN MACROS

-- END MACROS

end LeanDream.Macros
"""

_EMPTY_PROPERTIES_LEAN = """\
import LeanDream.DSL
import LeanDream.Macros

namespace LeanDream.Properties
open LeanDream

-- Theorems are appended here by leandream.properties.prove_all.

end LeanDream.Properties
"""


def reset_state() -> None:
    """Wipe all accumulated state: proofs, prompts, macro registry, Macros.lean, Properties.lean."""
    cleared: list[str] = []
    if PROOFS_DIR.exists():
        shutil.rmtree(PROOFS_DIR)
        cleared.append("proofs/")
    if PROMPTS_DIR.exists():
        shutil.rmtree(PROMPTS_DIR)
        cleared.append("prompts/")
    if MACROS_REGISTRY.exists():
        MACROS_REGISTRY.unlink()
        cleared.append("macros/registry.json")
    MACROS_LEAN.write_text(_EMPTY_MACROS_LEAN)
    cleared.append("lean/LeanDream/Macros.lean (reset to empty)")
    PROPERTIES_LEAN.write_text(_EMPTY_PROPERTIES_LEAN)
    cleared.append("lean/LeanDream/Properties.lean (reset to empty)")
    reset_candidate()
    cleared.append("lean/LeanDream/Candidate.lean (reset to placeholder)")
    print("reset:")
    for c in cleared:
        print(f"  - {c}")


def load_specs(names: list[str]) -> list[dict[str, Any]]:
    if names == ["all"]:
        files = sorted(SPECS_DIR.glob("*.json"))
    else:
        files = [SPECS_DIR / f"{n}.json" for n in names]
    out = []
    for p in files:
        if not p.exists():
            print(f"warning: spec file not found: {p}", file=sys.stderr)
            continue
        out.append(json.loads(p.read_text()))
    return out


def _dump(c: Circuit) -> dict:
    return _CIRCUIT_ADAPTER.dump_python(c, mode="json")


def _run_one_attempt(
    spec: dict[str, Any],
    ordered_registry: dict[str, dict],
    generate,
    macro_circuits: dict[str, Circuit],
    *,
    model: str | None,
    iteration: int,
    memory_pack: str,
) -> dict[str, Any]:
    """Run generate→expand→verify for one spec. Returns a structured outcome dict.

    Does NOT log attempts, update the bandit, or record to the proof forest —
    those side-effects stay in the caller so this function stays pure.
    """
    import re as _re

    llm_t0 = time.monotonic()
    circuit: Circuit | None = None
    reasoning = ""

    try:
        circuit, reasoning = generate(
            spec, ordered_registry, model=model, iteration=iteration,
            memory_pack=memory_pack,
        )
    except Exception as e:
        return {
            "status": attempts.STATUS_LLM_ERROR,
            "circuit": None, "expanded": None,
            "error_type": type(e).__name__, "error_message": str(e),
            "llm_ms": (time.monotonic() - llm_t0) * 1000,
            "lean_ms": None, "lean_stdout": None, "lean_stderr": None,
            "proof_path": None, "reasoning": "", "macro_name": None,
        }
    llm_ms = (time.monotonic() - llm_t0) * 1000

    try:
        expanded = expand_macros(circuit, macro_circuits)
    except KeyError as e:
        raw = str(e).strip("'\"")
        return {
            "status": attempts.STATUS_UNKNOWN_MACRO,
            "circuit": circuit, "expanded": None,
            "error_type": "KeyError", "error_message": str(e),
            "llm_ms": llm_ms, "lean_ms": None, "lean_stdout": None, "lean_stderr": None,
            "proof_path": None, "reasoning": reasoning, "macro_name": raw,
        }
    except ArityError as e:
        m = _re.search(r"macro '([^']+)' expects", str(e))
        return {
            "status": attempts.STATUS_ARITY_MISMATCH,
            "circuit": circuit, "expanded": None,
            "error_type": "ArityError", "error_message": str(e),
            "llm_ms": llm_ms, "lean_ms": None, "lean_stdout": None, "lean_stderr": None,
            "proof_path": None, "reasoning": reasoning,
            "macro_name": m.group(1) if m else None,
        }
    except ExpansionCycleError as e:
        return {
            "status": attempts.STATUS_EXPANSION_CYCLE,
            "circuit": circuit, "expanded": None,
            "error_type": "ExpansionCycleError", "error_message": str(e),
            "llm_ms": llm_ms, "lean_ms": None, "lean_stdout": None, "lean_stderr": None,
            "proof_path": None, "reasoning": reasoning, "macro_name": None,
        }
    except ExpansionDepthError as e:
        return {
            "status": attempts.STATUS_EXPANSION_DEPTH,
            "circuit": circuit, "expanded": None,
            "error_type": "ExpansionDepthError", "error_message": str(e),
            "llm_ms": llm_ms, "lean_ms": None, "lean_stdout": None, "lean_stderr": None,
            "proof_path": None, "reasoning": reasoning, "macro_name": None,
        }

    result = verify_candidate(circuit, spec["arity"], spec["lean_spec"])
    lean_ms = result.elapsed_seconds * 1000

    if result.ok:
        path = forest.record(
            spec["name"], expanded, circuit, iteration, result.elapsed_seconds
        )
        return {
            "status": attempts.STATUS_VERIFIED,
            "circuit": circuit, "expanded": expanded,
            "error_type": None, "error_message": None,
            "llm_ms": llm_ms, "lean_ms": lean_ms,
            "lean_stdout": result.stdout, "lean_stderr": result.stderr,
            "proof_path": path, "reasoning": reasoning, "macro_name": None,
        }
    return {
        "status": attempts.STATUS_LEAN_FAILED,
        "circuit": circuit, "expanded": expanded,
        "error_type": result.error, "error_message": result.error,
        "llm_ms": llm_ms, "lean_ms": lean_ms,
        "lean_stdout": result.stdout, "lean_stderr": result.stderr,
        "proof_path": None, "reasoning": reasoning, "macro_name": None,
    }


def _print_outcome(outcome: dict[str, Any]) -> None:
    status = outcome["status"]
    if outcome.get("reasoning"):
        print(f"    note: {outcome['reasoning'].strip()}")
    if status == attempts.STATUS_VERIFIED:
        path = outcome["proof_path"]
        secs = (outcome["lean_ms"] or 0) / 1000
        print(f"    ✓ verified in {secs:.1f}s -> {path.name}")
    elif status == attempts.STATUS_LLM_ERROR:
        print(f"    LLM error: {outcome['error_message']!r}")
    elif status == attempts.STATUS_UNKNOWN_MACRO:
        print(f"    rejected: unknown macro {outcome['error_message']}")
    elif status == attempts.STATUS_ARITY_MISMATCH:
        print(f"    rejected: macro arity mismatch — {outcome['error_message']}")
    elif status == attempts.STATUS_EXPANSION_CYCLE:
        print(f"    rejected: expansion cycle — {outcome['error_message']}")
    elif status == attempts.STATUS_EXPANSION_DEPTH:
        print(f"    rejected: expansion depth limit — {outcome['error_message']}")
    elif status == attempts.STATUS_LEAN_FAILED:
        blob = ((outcome.get("lean_stderr") or outcome.get("lean_stdout") or "")).strip()
        err_lines = [l for l in blob.splitlines()
                     if l.startswith("error:") and "build failed" not in l]
        tail = err_lines[:5] if err_lines else blob.splitlines()[-8:]
        print(f"    ✗ failed: {outcome['error_type'] or 'mismatch'}")
        for line in tail:
            print(f"      {line}")


def _log_attempt(
    run_dir: Path,
    run_id: str,
    spec_name: str,
    iteration: int,
    outcome: dict[str, Any],
    *,
    proposer_name: str,
    model: str | None,
    repair_pass: int = 0,
) -> None:
    circuit = outcome["circuit"]
    expanded = outcome["expanded"]
    attempts.log(
        run_dir,
        run_id=run_id, iteration=iteration, spec=spec_name,
        status=outcome["status"], proposer=proposer_name,
        error_type=outcome["error_type"], message=outcome["error_message"],
        llm_time_ms=outcome["llm_ms"], lean_time_ms=outcome["lean_ms"],
        raw_circuit=_dump(circuit) if circuit else None,
        expanded_circuit=_dump(expanded) if expanded else None,
        lean_stdout=outcome["lean_stdout"], lean_stderr=outcome["lean_stderr"],
        proof_id=outcome["proof_path"].name if outcome["proof_path"] else None,
        model=model, repair_pass=repair_pass,
    )


def run_iteration(
    iteration: int,
    specs: list[dict[str, Any]],
    *,
    run_id: str,
    run_dir: Path,
    model: str | None,
    generate,
    proposer_name: str,
) -> tuple[int, int]:
    """One pass through every spec. Returns (verified, attempted)."""
    registry = installer.load_registry()
    macro_circuits = installer.installed_circuits(registry)

    verified = 0
    attempted = 0

    # Load bandit + RAG card corpus once per iteration
    bandit = ContextualBandit.load()
    rag_cards = run_indexer(registry=registry)

    for spec in specs:
        attempted += 1
        spec_name = spec["name"]
        print(f"  spec: {spec_name}", flush=True)

        # --- Bandit: rank macros by Thompson sample, best first ---------------
        if registry:
            _macro_keys = [f"macro:{n}" for n in registry]
            _ranked = bandit.rank(_macro_keys)
            ordered_registry = {
                k[len("macro:"):]: registry[k[len("macro:"):]]
                for k in _ranked if k[len("macro:"):] in registry
            }
        else:
            ordered_registry = registry

        # --- RAG retrieval for this spec --------------------------------------
        arity = spec.get("arity", 0)
        query_tags = ["verified", "macro", f"spec:{spec_name}", f"arity:{arity}"]
        rag_results = _mem_retriever.retrieve(query_tags, rag_cards, top_k=5)
        memory_pack_str = _mem_prompt_pack.pack(rag_results, char_budget=600)

        # --- First attempt ---------------------------------------------------
        outcome = _run_one_attempt(
            spec, ordered_registry, generate, macro_circuits,
            model=model, iteration=iteration, memory_pack=memory_pack_str,
        )
        _print_outcome(outcome)
        _log_attempt(run_dir, run_id, spec_name, iteration, outcome,
                     proposer_name=proposer_name, model=model, repair_pass=0)

        # Track the FINAL outcome for the bandit update (repair may override)
        final_status = outcome["status"]
        final_circuit = outcome["circuit"]

        if outcome["status"] == attempts.STATUS_VERIFIED:
            verified += 1

        # --- One-shot repair attempt (if eligible) ---------------------------
        elif is_repairable(outcome["status"]):
            repair_pack = build_repair_pack(
                outcome["status"], outcome["error_message"],
                registry=ordered_registry,
                lean_stderr_tail=outcome.get("lean_stderr"),
                macro_name=outcome.get("macro_name"),
            )
            print(f"    → repair ({outcome['status']})...", flush=True)
            outcome_r = _run_one_attempt(
                spec, ordered_registry, generate, macro_circuits,
                model=model, iteration=iteration, memory_pack=repair_pack,
            )
            _print_outcome(outcome_r)
            _log_attempt(run_dir, run_id, spec_name, iteration, outcome_r,
                         proposer_name=proposer_name, model=model, repair_pass=1)

            if outcome_r["status"] == attempts.STATUS_VERIFIED:
                verified += 1
                final_status = attempts.STATUS_VERIFIED
                final_circuit = outcome_r["circuit"]
            # else: keep original failure as final_status for bandit

        # --- Bandit update (always based on FINAL outcome) -------------------
        reward = compute_reward(final_status)
        bandit.update(f"spec:{spec_name}", reward)
        raw_d = _dump(final_circuit) if final_circuit else None
        if raw_d:
            for mac_name in _macros_used(raw_d):
                bandit.update(f"macro:{mac_name}", reward)
        bandit.save()

    return verified, attempted


def run(
    specs: list[dict[str, Any]],
    *,
    iterations: int,
    min_support: int,
    min_size: int,
    model: str | None,
    mock: bool,
) -> None:
    if mock:
        from . import mock_llm
        generate = mock_llm.generate_circuit
        proposer_name = "mock"
        print("(mock mode: using reference solutions, no LLM calls)")
    else:
        from . import llm
        generate = llm.generate_circuit
        proposer_name = "llm"

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
    run_dir = attempts.run_dir_for(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"run_id: {run_id}  (logs: runs/{run_id}/)")

    for i in range(iterations):
        print(f"\n=== iteration {i + 1}/{iterations} ===")
        verified, attempted = run_iteration(
            i,
            specs,
            run_id=run_id,
            run_dir=run_dir,
            model=model,
            generate=generate,
            proposer_name=proposer_name,
        )
        print(f"  iteration verified {verified}/{attempted}")

        records = list(forest.iter_records())
        current_registry = installer.load_registry()
        candidates = miner.mine(records, min_support=min_support, min_size=min_size)
        reg_names = set(current_registry) if current_registry else None
        comp_candidates = miner.mine_macro_compositions(
            records, min_support=min_support, min_size=2,
            registered_macros=reg_names,
        )
        seen_keys = {c.key for c in candidates}
        for cc in comp_candidates:
            if cc.key not in seen_keys:
                candidates.append(cc)
                seen_keys.add(cc.key)
        print(
            f"  mined {len(candidates)} candidate macro(s) from {len(records)} proof(s)"
            f" ({len(comp_candidates)} composition candidate(s))"
        )
        if candidates:
            registry = installer.install(candidates)
        else:
            registry = installer.load_registry()
        if registry:
            print("  proving properties...")
            registry = properties.prove_all(registry)
            installer.save_registry(registry)
            n_exported = _run_theorem_exporter(registry)
            if n_exported:
                print(f"  exported {n_exported} new theorem card(s) to memory")

    print("\n=== run complete ===")
    print(f"proof forest: {forest.stats()}")
    reg = installer.load_registry()
    print(f"installed macros: {len(reg)}")
    for name, info in reg.items():
        print(f"  {name} (support {info['support']}): {info['body_repr']}")

    all_attempts = attempts.load(run_dir)
    total = len(all_attempts)
    ok_count = sum(1 for a in all_attempts if a["status"] == attempts.STATUS_VERIFIED)
    fail_count = total - ok_count
    print(
        f"attempts: {total} total, {ok_count} verified, {fail_count} failed"
        f"  (see runs/{run_id}/attempts.jsonl)"
    )

    bandit = ContextualBandit.load()
    summary = bandit.summary()
    if summary:
        print("bandit posteriors:")
        for key, stats in sorted(summary.items()):
            print(f"  {key}: mean={stats['mean']:.3f}  n={stats['n']:.0f}"
                  f"  (α={stats['alpha']:.2f}, β={stats['beta']:.2f})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="leandream")
    parser.add_argument(
        "--specs",
        nargs="+",
        default=["all"],
        help="Spec names (without .json) or 'all'.",
    )
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--min-support", type=int, default=2)
    parser.add_argument("--min-size", type=int, default=3)
    parser.add_argument("--model", default=None, help="Override LEANDREAM_MODEL.")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use canned reference circuits instead of calling the LLM.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe proofs/, prompts/, macro registry, and Macros.lean before running.",
    )
    args = parser.parse_args()

    if args.reset:
        reset_state()

    specs = load_specs(args.specs)
    if not specs:
        raise SystemExit("no specs to run")
    run(
        specs,
        iterations=args.iterations,
        min_support=args.min_support,
        min_size=args.min_size,
        model=args.model,
        mock=args.mock,
    )


if __name__ == "__main__":
    main()
