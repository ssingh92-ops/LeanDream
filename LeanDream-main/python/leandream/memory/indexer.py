"""Convert proof forest records, macro registry, and attempt logs into cards.

Information-structure inference (heuristic, not Lean-certified):
- arity == 1 AND tt in {"01","10"}: bijection (identity / NOT) → information_preserving
- arity == 1, other: constant → information_losing
- arity >= 2, single Bool output: pigeonhole argument → information_losing

These inferences are tagged with notes="heuristic:..." so downstream code
can distinguish them from Lean-proven properties.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import TypeAdapter

from ..ast import Circuit
from ..attempts import STATUS_VERIFIED
from ..attempts import load as _load_attempts
from ..forest import iter_records
from .cards import (
    NULL_INFO_STRUCTURE,
    Card,
    failure_card,
    macro_card,
    proof_trace_card,
    theorem_property_card,
)

_ADAPTER: TypeAdapter[Circuit] = TypeAdapter(Circuit)


# ---------------------------------------------------------------------------
# Heuristic info-structure inference
# ---------------------------------------------------------------------------

def _infer_info_structure(tt_key: str | None, arity: int | None) -> dict:
    """Heuristic information-structure from truth table string and input arity."""
    info = dict(NULL_INFO_STRUCTURE)
    if tt_key is None or arity is None:
        return info
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
        # Single Bool output, 2^arity inputs → can't be injective for arity > 1
        info["information_losing"] = True
        info["information_preserving"] = False
        info["notes"] = "heuristic: single-output Boolean, arity >= 2"
    return info


# ---------------------------------------------------------------------------
# Gate set extraction from AST dict
# ---------------------------------------------------------------------------

def _gates_from_dict(c: dict) -> set[str]:
    """Walk a serialised Circuit dict and collect all gate kind names."""
    kind = c.get("kind", "")
    kinds: set[str] = {kind} if kind else set()
    for key in ("arg", "left", "right"):
        if key in c:
            kinds |= _gates_from_dict(c[key])
    for arg in c.get("args", []):
        kinds |= _gates_from_dict(arg)
    return kinds - {"var", "const", "mac"}  # keep only operator kinds


# ---------------------------------------------------------------------------
# Indexers
# ---------------------------------------------------------------------------

def index_proofs() -> list[Card]:
    """Scan proof forest (green edges) and emit ProofTraceCards."""
    cards: list[Card] = []
    for rec in iter_records():
        raw_dict = _ADAPTER.dump_python(rec.raw, mode="json")
        exp_dict = _ADAPTER.dump_python(rec.expanded, mode="json")
        gates = _gates_from_dict(exp_dict)
        cards.append(proof_trace_card(
            spec=rec.spec,
            circuit_raw=raw_dict,
            circuit_expanded=exp_dict,
            iteration=rec.iteration,
            elapsed_seconds=rec.elapsed_seconds,
            gates=gates,
        ))
    return cards


def index_failures(run_dir: Path) -> list[Card]:
    """Scan attempts.jsonl for failed attempts and emit FailureCards."""
    cards: list[Card] = []
    for attempt in _load_attempts(run_dir):
        if attempt.get("status") == STATUS_VERIFIED:
            continue
        cards.append(failure_card(
            spec=attempt.get("spec", "unknown"),
            error_type=attempt.get("error_type") or attempt.get("status"),
            message=attempt.get("message"),
            iteration=attempt.get("iteration", 0),
            circuit_raw=attempt.get("raw_circuit"),
        ))
    return cards


def index_macros(registry: dict[str, dict]) -> list[Card]:
    """Emit MacroCards for every entry in the macro registry.

    If the registry entry already has an info_structure field, use it as-is;
    otherwise infer heuristically from tt_key + arity.
    """
    cards: list[Card] = []
    for name, info in registry.items():
        stored_info = info.get("info_structure")
        if not stored_info:
            stored_info = _infer_info_structure(info.get("tt_key"), info.get("arity"))
        cards.append(macro_card(
            name=name,
            arity=info.get("arity") or 0,
            body_repr=info.get("body_repr", ""),
            properties=info.get("properties") or [],
            support=info.get("support", 0),
            members=info.get("members") or [],
            info_structure=stored_info,
        ))
    return cards


def index_properties(registry: dict[str, dict]) -> list[Card]:
    """Emit TheoremPropertyCards for each proven algebraic property."""
    cards: list[Card] = []
    for name, info in registry.items():
        for prop in (info.get("properties") or []):
            cards.append(theorem_property_card(
                macro_name=name,
                property_name=prop,
            ))
    return cards


def run_indexer(
    run_dir: Path | None = None,
    registry: dict[str, dict] | None = None,
    *,
    include_failures: bool = False,
) -> list[Card]:
    """Run all indexers and return the combined card list.

    include_failures: whether to include FailureCards (requires run_dir).
                      Off by default to keep prompt context clean during a run.
    """
    cards: list[Card] = []
    cards.extend(index_proofs())
    if include_failures and run_dir is not None:
        cards.extend(index_failures(run_dir))
    if registry is not None:
        cards.extend(index_macros(registry))
        cards.extend(index_properties(registry))
    return cards
