"""Macro installer: append candidates to Macros.lean and re-verify by `lake build`."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from .ast import Circuit
from .hierarchy import compute_macro_level
from .miner import MacroCandidate
from .translate import macro_body_to_lean, macro_lean_def
from .truthtable import negated_table, truth_table
from .verify import LEAN_DIR, lake_build, reset_candidate

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MACROS_LEAN_PATH = LEAN_DIR / "LeanDream" / "Macros.lean"
REGISTRY_DIR = REPO_ROOT / "macros"
REGISTRY_PATH = REGISTRY_DIR / "registry.json"

_BEGIN = "-- BEGIN MACROS"
_END = "-- END MACROS"

_ADAPTER: TypeAdapter[Circuit] = TypeAdapter(Circuit)


def load_registry() -> dict[str, dict]:
    if not REGISTRY_PATH.exists():
        return {}
    return json.loads(REGISTRY_PATH.read_text())


def save_registry(registry: dict[str, dict]) -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2))


def _heuristic_info_structure(tt_key: str, arity: int) -> dict:
    """Lightweight heuristic information-structure tags for a single-output macro.

    These are NOT Lean-certified — the notes field records this explicitly.
    """
    info: dict = {
        "information_preserving": None,
        "information_losing": None,
        "reversible_embedding": None,
        "uses_ancilla": None,
        "cleans_garbage": None,
        "notes": None,
    }
    if arity == 1:
        if tt_key in ("01", "10"):
            info["information_preserving"] = True
            info["information_losing"] = False
            info["notes"] = "heuristic: arity-1 bijection (identity or NOT)"
        else:
            info["information_losing"] = True
            info["information_preserving"] = False
            info["notes"] = "heuristic: arity-1 constant function"
    elif arity >= 2:
        info["information_losing"] = True
        info["information_preserving"] = False
        info["notes"] = "heuristic: single-output Boolean, arity >= 2"
    return info


def installed_circuits(registry: dict[str, dict]) -> dict[str, Circuit]:
    """Return name -> macro body Circuit for use by the macro expander.

    Body has free vars 0..arity-1 as parameter slots; substitute() at expansion
    time replaces them with concrete args.
    """
    return {name: _ADAPTER.validate_python(info["ast"]) for name, info in registry.items()}


def next_macro_name(registry: dict[str, dict]) -> str:
    n = 1
    while f"macro_{n}" in registry:
        n += 1
    return f"macro_{n}"


def _render_macros_block(registry: dict[str, dict]) -> str:
    lines: list[str] = []
    for name, info in registry.items():
        ast = _ADAPTER.validate_python(info["ast"])
        lines.append(macro_lean_def(name, ast, info["arity"]))
    return "\n".join(lines)


def _write_macros_file(registry: dict[str, dict]) -> None:
    block = _render_macros_block(registry)
    text = MACROS_LEAN_PATH.read_text()
    pre, _, rest = text.partition(_BEGIN)
    _, _, post = rest.partition(_END)
    new = f"{pre}{_BEGIN}\n{block}\n{_END}{post}"
    MACROS_LEAN_PATH.write_text(new)


def install(candidates: list[MacroCandidate], *, verbose: bool = True) -> dict[str, dict]:
    """Try to install each candidate; reject any that breaks `lake build`.

    Returns the updated registry dict.
    """
    registry = load_registry()
    known_keys = {info["key"] for info in registry.values()}
    reset_candidate()

    accepted = 0
    rejected = 0
    skipped = 0
    tt_skipped = 0

    # Index existing macros by (arity, tt_key) so we can fast-reject
    # truth-table-equivalent candidates (and their NOT-flips).
    existing_by_tt: dict[tuple[int, str], str] = {}
    for nm, info in registry.items():
        tt = info.get("tt_key")
        if tt:
            existing_by_tt[(info["arity"], tt)] = nm

    body_circuits = installed_circuits(registry)

    for cand in candidates:
        if cand.key in known_keys:
            skipped += 1
            continue

        # Compute truth table; reject if it (or its NOT-flip) matches an existing macro.
        try:
            tt = truth_table(cand.ast, cand.arity, body_circuits)
        except Exception as e:
            rejected += 1
            if verbose:
                print(f"  - rejected (truth-table eval failed: {e})")
            continue
        neg = negated_table(tt)
        match = existing_by_tt.get((cand.arity, tt))
        neg_match = existing_by_tt.get((cand.arity, neg))
        if match is not None:
            tt_skipped += 1
            if verbose:
                body_repr = macro_body_to_lean(cand.ast, cand.arity)
                print(f"  ~ skipped (TT-equivalent to {match}): {body_repr}")
            continue
        if neg_match is not None:
            tt_skipped += 1
            if verbose:
                body_repr = macro_body_to_lean(cand.ast, cand.arity)
                print(f"  ~ skipped (NOT-equivalent to {neg_match}): {body_repr}")
            continue

        name = next_macro_name(registry)
        info = {
            "key": cand.key,
            "ast": _ADAPTER.dump_python(cand.ast, mode="json"),
            "arity": cand.arity,
            "support": cand.support,
            "occurrences": cand.occurrences,
            "members": cand.members,
            "body_repr": macro_body_to_lean(cand.ast, cand.arity),
            "properties": [],
            "tt_key": tt,
            "info_structure": _heuristic_info_structure(tt, cand.arity),
            "macro_level": 0,  # updated below after successful lake build
        }
        registry[name] = info
        _write_macros_file(registry)
        result = lake_build()
        if result.ok:
            levels = compute_macro_level(registry)
            info["macro_level"] = levels.get(name, 0)
            known_keys.add(cand.key)
            existing_by_tt[(cand.arity, tt)] = name
            body_circuits[name] = cand.ast
            accepted += 1
            if verbose:
                arity_str = f"({cand.arity})" if cand.arity else "()"
                print(
                    f"  + installed {name}{arity_str} lvl={info['macro_level']}"
                    f" (support={cand.support}): {info['body_repr']}"
                )
        else:
            del registry[name]
            _write_macros_file(registry)
            rejected += 1
            if verbose:
                print(f"  - rejected {name} (lake build failed): {info['body_repr']}")

    save_registry(registry)
    if verbose:
        print(
            f"  install summary: accepted={accepted} rejected={rejected} "
            f"skipped_key_dup={skipped} skipped_tt_equiv={tt_skipped} "
            f"total_in_registry={len(registry)}"
        )
    return registry
