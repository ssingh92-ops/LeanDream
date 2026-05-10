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
from .hole_detector import detect_holes, detect_macro_roles
from .prompts import build_majority_role_pack, build_user_prompt, SYSTEM_PROMPT
from .learning.contextual_bandit import ContextualBandit, _macros_used, compute_reward
from .memory.indexer import run_indexer
from .memory import retriever as _mem_retriever
from .memory import prompt_pack as _mem_prompt_pack
from .memory.theorem_exporter import run_exporter as _run_theorem_exporter
from .theorem_gen import generate_theorems_for_registry as _gen_theorems
from .metrics import (
    compute_iteration_metrics,
    compute_run_summary,
    save_metrics,
    save_summary,
)
from .preflight import build_preflight_repair, validate as preflight_validate
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
    use_llm_cache: bool = True,
    registry_hash: str = "",
) -> dict[str, Any]:
    """Run generate→expand→preflight→quickcheck→verify for one spec.

    Returns a structured outcome dict.  Does NOT log attempts, update the
    bandit, or record to the proof forest — those side-effects stay in the
    caller so this function stays pure.

    Phase timings are included in the returned dict:
      llm_ms, preflight_ms, quickcheck_ms, lean_ms
    """
    import re as _re
    from .quickcheck import quickcheck

    timings: dict[str, float | None] = {
        "llm_ms": None, "preflight_ms": None,
        "quickcheck_ms": None, "lean_ms": None,
    }

    # ----- LLM / generate ---------------------------------------------------
    llm_t0 = time.monotonic()
    circuit: Circuit | None = None
    reasoning = ""

    try:
        circuit, reasoning = generate(
            spec, ordered_registry, model=model, iteration=iteration,
            memory_pack=memory_pack,
            **({"use_cache": use_llm_cache} if hasattr(generate, "__self__") or True else {}),
        )
    except TypeError:
        # Fallback for generate functions that don't accept use_cache kwarg
        circuit, reasoning = generate(
            spec, ordered_registry, model=model, iteration=iteration,
            memory_pack=memory_pack,
        )
    except Exception as e:
        timings["llm_ms"] = (time.monotonic() - llm_t0) * 1000
        return {
            "status": attempts.STATUS_LLM_ERROR,
            "circuit": None, "expanded": None,
            "error_type": type(e).__name__, "error_message": str(e),
            "lean_stdout": None, "lean_stderr": None,
            "proof_path": None, "reasoning": "", "macro_name": None,
            "proof_mode": None, "lean_cached": False,
            **timings,
        }
    timings["llm_ms"] = (time.monotonic() - llm_t0) * 1000

    # ----- Macro expansion --------------------------------------------------
    try:
        expanded = expand_macros(circuit, macro_circuits)
    except KeyError as e:
        raw = str(e).strip("'\"")
        return {
            "status": attempts.STATUS_UNKNOWN_MACRO,
            "circuit": circuit, "expanded": None,
            "error_type": "KeyError", "error_message": str(e),
            "lean_stdout": None, "lean_stderr": None,
            "proof_path": None, "reasoning": reasoning, "macro_name": raw,
            "proof_mode": None, "lean_cached": False,
            **timings,
        }
    except ArityError as e:
        m = _re.search(r"macro '([^']+)' expects", str(e))
        return {
            "status": attempts.STATUS_ARITY_MISMATCH,
            "circuit": circuit, "expanded": None,
            "error_type": "ArityError", "error_message": str(e),
            "lean_stdout": None, "lean_stderr": None,
            "proof_path": None, "reasoning": reasoning,
            "macro_name": m.group(1) if m else None,
            "proof_mode": None, "lean_cached": False,
            **timings,
        }
    except ExpansionCycleError as e:
        return {
            "status": attempts.STATUS_EXPANSION_CYCLE,
            "circuit": circuit, "expanded": None,
            "error_type": "ExpansionCycleError", "error_message": str(e),
            "lean_stdout": None, "lean_stderr": None,
            "proof_path": None, "reasoning": reasoning, "macro_name": None,
            "proof_mode": None, "lean_cached": False,
            **timings,
        }
    except ExpansionDepthError as e:
        return {
            "status": attempts.STATUS_EXPANSION_DEPTH,
            "circuit": circuit, "expanded": None,
            "error_type": "ExpansionDepthError", "error_message": str(e),
            "lean_stdout": None, "lean_stderr": None,
            "proof_path": None, "reasoning": reasoning, "macro_name": None,
            "proof_mode": None, "lean_cached": False,
            **timings,
        }

    # ----- Preflight --------------------------------------------------------
    pf_t0 = time.monotonic()
    preflight = preflight_validate(circuit, spec["arity"], ordered_registry)
    timings["preflight_ms"] = (time.monotonic() - pf_t0) * 1000
    if not preflight.ok:
        return {
            "status": preflight.status,
            "circuit": circuit, "expanded": None,
            "error_type": preflight.error_type, "error_message": preflight.message,
            "lean_stdout": None, "lean_stderr": None,
            "proof_path": None, "reasoning": reasoning,
            "macro_name": preflight.macro_name, "proof_mode": None,
            "lean_cached": False,
            **timings,
        }

    # ----- Python quickcheck (fast rejection before Lean) -------------------
    qc_t0 = time.monotonic()
    qc = quickcheck(circuit, spec, macro_circuits)
    timings["quickcheck_ms"] = (time.monotonic() - qc_t0) * 1000
    if not qc.passed:
        return {
            "status": attempts.STATUS_LEAN_FAILED,
            "circuit": circuit, "expanded": expanded,
            "error_type": "quickcheck_failed",
            "error_message": f"Python quickcheck failed: {qc.counterexample}",
            "lean_stdout": None, "lean_stderr": None,
            "proof_path": None, "reasoning": reasoning, "macro_name": None,
            "proof_mode": None, "lean_cached": False,
            **timings,
        }

    # ----- Lean verification ------------------------------------------------
    result = verify_candidate(circuit, spec["arity"], spec["lean_spec"],
                              registry_hash=registry_hash)
    timings["lean_ms"] = result.elapsed_seconds * 1000

    if result.ok:
        path = forest.record(
            spec["name"], expanded, circuit, iteration, result.elapsed_seconds
        )
        return {
            "status": attempts.STATUS_VERIFIED,
            "circuit": circuit, "expanded": expanded,
            "error_type": None, "error_message": None,
            "lean_stdout": result.stdout, "lean_stderr": result.stderr,
            "proof_path": path, "reasoning": reasoning, "macro_name": None,
            "proof_mode": result.proof_mode, "lean_cached": result.cached,
            **timings,
        }
    return {
        "status": attempts.STATUS_LEAN_FAILED,
        "circuit": circuit, "expanded": expanded,
        "error_type": result.error, "error_message": result.error,
        "lean_stdout": result.stdout, "lean_stderr": result.stderr,
        "proof_path": None, "reasoning": reasoning, "macro_name": None,
        "proof_mode": result.proof_mode, "lean_cached": result.cached,
        **timings,
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
    stage: int | None = None,
    retrieved_card_ids: list[str] | None = None,
    environment: dict | None = None,
) -> None:
    circuit = outcome["circuit"]
    expanded = outcome["expanded"]
    attempts.log(
        run_dir,
        run_id=run_id, iteration=iteration, spec=spec_name,
        status=outcome["status"], proposer=proposer_name,
        error_type=outcome["error_type"], message=outcome["error_message"],
        llm_time_ms=outcome["llm_ms"], lean_time_ms=outcome["lean_ms"],
        preflight_ms=outcome.get("preflight_ms"),
        quickcheck_ms=outcome.get("quickcheck_ms"),
        lean_cached=outcome.get("lean_cached", False),
        raw_circuit=_dump(circuit) if circuit else None,
        expanded_circuit=_dump(expanded) if expanded else None,
        lean_stdout=outcome["lean_stdout"], lean_stderr=outcome["lean_stderr"],
        proof_id=outcome["proof_path"].name if outcome["proof_path"] else None,
        proof_mode=outcome.get("proof_mode"),
        model=model, repair_pass=repair_pass, stage=stage,
        retrieved_card_ids=retrieved_card_ids,
        environment=environment,
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
    import hashlib as _hashlib
    registry = installer.load_registry()
    macro_circuits = installer.installed_circuits(registry)
    registry_hash = _hashlib.sha256(
        json.dumps(sorted(registry.keys())).encode()
    ).hexdigest()[:16]
    _macro_roles = detect_macro_roles(registry)

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
        retrieved_ids = [c.card.card_id for c in rag_results]

        # Inject semantic role map for majority/carry specs so LLM can use real macro names
        _role_pack = build_majority_role_pack(spec, _macro_roles)
        if _role_pack:
            memory_pack_str = (memory_pack_str + "\n" + _role_pack).strip() if memory_pack_str else _role_pack

        user_prompt_preview = build_user_prompt(spec, ordered_registry, memory_pack_str)
        prompt_chars = len(SYSTEM_PROMPT) + len(user_prompt_preview)
        env_ctx = {
            "spec": spec_name,
            "arity": arity,
            "available_macros": list(ordered_registry.keys()),
            "retrieved_card_ids": retrieved_ids,
            "retrieved_card_count": len(retrieved_ids),
            "prompt_chars": prompt_chars,
            "prompt_budget": 600,
            "model": model,
        }

        # --- First attempt ---------------------------------------------------
        outcome = _run_one_attempt(
            spec, ordered_registry, generate, macro_circuits,
            model=model, iteration=iteration, memory_pack=memory_pack_str,
            registry_hash=registry_hash,
        )
        _print_outcome(outcome)
        _log_attempt(run_dir, run_id, spec_name, iteration, outcome,
                     proposer_name=proposer_name, model=model, repair_pass=0,
                     retrieved_card_ids=retrieved_ids, environment=env_ctx)

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
            # For majority/carry specs, append role map (with arity warnings) to
            # repair prompt for BOTH lean_failed AND arity_mismatch — the LLM
            # needs the 3-arg schema even when it previously got the arity wrong.
            if _role_pack and outcome["status"] in (
                attempts.STATUS_LEAN_FAILED, attempts.STATUS_ARITY_MISMATCH
            ):
                repair_pack = repair_pack + "\n" + _role_pack
            print(f"    → repair ({outcome['status']})...", flush=True)
            outcome_r = _run_one_attempt(
                spec, ordered_registry, generate, macro_circuits,
                model=model, iteration=iteration, memory_pack=repair_pack,
                use_llm_cache=False, registry_hash=registry_hash,
            )
            _print_outcome(outcome_r)
            _log_attempt(run_dir, run_id, spec_name, iteration, outcome_r,
                         proposer_name=proposer_name, model=model, repair_pass=1,
                         retrieved_card_ids=retrieved_ids,
                         environment={**env_ctx, "raw_or_expanded": "repair"})

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

    # --- Hole detection (post-iteration) ------------------------------------
    all_iter_attempts = attempts.load(run_dir)
    current_registry = installer.load_registry()
    holes = detect_holes(specs, all_iter_attempts, current_registry)
    if holes:
        from .memory.card_store import append as _append_card
        from .memory.indexer import index_holes
        hole_cards = index_holes(holes)
        for hc in hole_cards:
            _append_card(hc)
        blocker_count = sum(1 for h in holes if h.severity == "blocker")
        print(
            f"  holes: {len(holes)} detected "
            f"({blocker_count} blocker(s)) — {len(hole_cards)} HoleCard(s) stored"
        )

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

    iteration_metrics_list = []
    prev_macro_count = len(installer.load_registry())
    prev_theorem_count = 0
    rag_card_count = 0
    last_mined_record_count = 0  # incremental mining: only re-mine when forest grows

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
        if len(records) > last_mined_record_count:
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
            last_mined_record_count = len(records)
            print(
                f"  mined {len(candidates)} candidate macro(s) from {len(records)} proof(s)"
                f" ({len(comp_candidates)} composition candidate(s))"
            )
        else:
            candidates = []
            print(f"  no new proofs since last mining pass — skipping miner")
        if candidates:
            registry = installer.install(candidates)
        else:
            registry = installer.load_registry()
        n_exported = 0
        if registry:
            print("  proving properties...")
            registry = properties.prove_all(registry)
            installer.save_registry(registry)
            n_exported = _run_theorem_exporter(registry)
            if n_exported:
                print(f"  exported {n_exported} new theorem card(s) to memory")
            # Auto-generate TheoremGen.lean theorems so the GUI and reports can
            # show which properties were Lean-verified via simp (not just decide).
            try:
                _gen_theorems(registry, run_dir=run_dir)
            except Exception:
                pass  # theorem_gen failures are non-fatal

        # --- Metrics ----------------------------------------------------------
        cur_macro_count = len(registry) if registry else 0
        bandit_summary: dict = {}
        try:
            bandit_summary = ContextualBandit.load().summary()
        except Exception:
            pass
        try:
            from .memory.card_store import load_all as _load_cards
            rag_card_count = len(list(_load_cards()))
        except Exception:
            rag_card_count = 0
        iter_metrics = compute_iteration_metrics(
            run_id, i,
            attempts.load(run_dir),
            prev_macro_count=prev_macro_count,
            cur_macro_count=cur_macro_count,
            prev_theorem_count=prev_theorem_count,
            cur_theorem_count=prev_theorem_count + n_exported,
            rag_card_count=rag_card_count,
            bandit_summary=bandit_summary,
        )
        iteration_metrics_list.append(iter_metrics)
        prev_macro_count = cur_macro_count
        prev_theorem_count += n_exported

    print("\n=== run complete ===")
    print(f"proof forest: {forest.stats()}")
    reg = installer.load_registry()
    print(f"installed macros: {len(reg)}")
    for name, info in reg.items():
        print(f"  {name} (support {info['support']}): {info['body_repr']}")

    all_attempts_recs = attempts.load(run_dir)
    total = len(all_attempts_recs)
    ok_count = sum(1 for a in all_attempts_recs if a["status"] == attempts.STATUS_VERIFIED)
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

    # --- Persist metrics / summary ------------------------------------------
    if iteration_metrics_list:
        save_metrics(run_dir, iteration_metrics_list)
        run_summary = compute_run_summary(
            run_id, iteration_metrics_list,
            macro_count=len(reg),
            theorem_count=prev_theorem_count,
            rag_card_count=rag_card_count,
        )
        save_summary(run_dir, run_summary)
        print(f"  metrics: runs/{run_id}/metrics.csv  summary: runs/{run_id}/summary.json")


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
