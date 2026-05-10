"""Card type definitions for the RAG-lite memory system.

Every card has:
  card_id        — unique 16-char hex identifier
  card_type      — one of the TYPE_* constants below
  created_at     — ISO-8601 UTC timestamp
  tags           — list of string tags for retrieval
  info_structure — lightweight information-structure fields (see below)
  payload        — card-type-specific data dict

Information-structure fields (all bool | None, plus an optional notes string):
  information_preserving  — circuit output encodes all input information
  information_losing      — multiple inputs map to the same output
  reversible_embedding    — lossy-looking function implemented via ancilla trick
  uses_ancilla            — circuit uses extra helper wires
  cleans_garbage          — ancilla wires are uncomputed back to 0 after use
  notes                   — short optional human-readable explanation

IMPORTANT: These tags are heuristic hints unless payload explicitly references
a Lean proof or theorem. V3 does not enforce reversibility via Lean checking.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

TYPE_PROOF_TRACE = "proof_trace"
TYPE_FAILURE = "failure"
TYPE_MACRO = "macro"
TYPE_THEOREM_PROPERTY = "theorem_property"
TYPE_DSL_ACTION = "dsl_action"

NULL_INFO_STRUCTURE: dict[str, Any] = {
    "information_preserving": None,
    "information_losing": None,
    "reversible_embedding": None,
    "uses_ancilla": None,
    "cleans_garbage": None,
    "notes": None,
}

_INFO_KEYS = tuple(NULL_INFO_STRUCTURE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _merge_info(override: dict | None) -> dict[str, Any]:
    out = dict(NULL_INFO_STRUCTURE)
    if override:
        out.update({k: v for k, v in override.items() if k in NULL_INFO_STRUCTURE})
    return out


def _info_tags(info: dict) -> list[str]:
    return [k for k in ("information_preserving", "information_losing",
                        "reversible_embedding", "uses_ancilla", "cleans_garbage")
            if info.get(k) is True]


@dataclass
class Card:
    card_id: str
    card_type: str
    created_at: str
    tags: list[str]
    info_structure: dict[str, Any]
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "card_type": self.card_type,
            "created_at": self.created_at,
            "tags": self.tags,
            "info_structure": self.info_structure,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Card":
        return cls(
            card_id=d["card_id"],
            card_type=d["card_type"],
            created_at=d["created_at"],
            tags=d.get("tags", []),
            info_structure=d.get("info_structure", dict(NULL_INFO_STRUCTURE)),
            payload=d.get("payload", {}),
        )


def proof_trace_card(
    spec: str,
    circuit_raw: dict,
    circuit_expanded: dict,
    iteration: int,
    elapsed_seconds: float,
    gates: set[str] | None = None,
    info_structure: dict | None = None,
) -> Card:
    info = _merge_info(info_structure)
    tags = [
        f"spec:{spec}",
        "verified",
        f"iter:{iteration}",
        *(f"gate:{g}" for g in sorted(gates or [])),
        *_info_tags(info),
    ]
    return Card(
        card_id=_new_id(),
        card_type=TYPE_PROOF_TRACE,
        created_at=_now(),
        tags=tags,
        info_structure=info,
        payload={
            "spec": spec,
            "iteration": iteration,
            "elapsed_seconds": elapsed_seconds,
            "circuit_raw": circuit_raw,
            "circuit_expanded": circuit_expanded,
        },
    )


def failure_card(
    spec: str,
    error_type: str | None,
    message: str | None,
    iteration: int = 0,
    circuit_raw: dict | None = None,
    info_structure: dict | None = None,
) -> Card:
    info = _merge_info(info_structure)
    tags = [
        f"spec:{spec}",
        "failed",
        f"error:{error_type or 'unknown'}",
        f"iter:{iteration}",
        *_info_tags(info),
    ]
    return Card(
        card_id=_new_id(),
        card_type=TYPE_FAILURE,
        created_at=_now(),
        tags=tags,
        info_structure=info,
        payload={
            "spec": spec,
            "iteration": iteration,
            "error_type": error_type,
            "message": message,
            "circuit_raw": circuit_raw,
        },
    )


def macro_card(
    name: str,
    arity: int,
    body_repr: str,
    properties: list[str],
    support: int,
    members: list[str],
    info_structure: dict | None = None,
) -> Card:
    info = _merge_info(info_structure)
    tags = [
        "macro",
        f"macro:{name}",
        f"arity:{arity}",
        f"support:{support}",
        *(f"spec:{m}" for m in members),
        *(f"property:{p}" for p in properties),
        *_info_tags(info),
    ]
    return Card(
        card_id=_new_id(),
        card_type=TYPE_MACRO,
        created_at=_now(),
        tags=tags,
        info_structure=info,
        payload={
            "name": name,
            "arity": arity,
            "body_repr": body_repr,
            "properties": properties,
            "support": support,
            "members": members,
        },
    )


def theorem_property_card(
    macro_name: str,
    property_name: str,
    lean_statement: str | None = None,
    info_structure: dict | None = None,
) -> Card:
    info = _merge_info(info_structure)
    tags = [
        "theorem_property",
        f"macro:{macro_name}",
        f"property:{property_name}",
        *_info_tags(info),
    ]
    return Card(
        card_id=_new_id(),
        card_type=TYPE_THEOREM_PROPERTY,
        created_at=_now(),
        tags=tags,
        info_structure=info,
        payload={
            "macro_name": macro_name,
            "property_name": property_name,
            "lean_statement": lean_statement,
        },
    )


def dsl_action_card(
    name: str,
    description: str,
    lean_snippet: str | None = None,
    info_structure: dict | None = None,
) -> Card:
    info = _merge_info(info_structure)
    tags = [
        "dsl_action",
        f"action:{name}",
        *_info_tags(info),
    ]
    return Card(
        card_id=_new_id(),
        card_type=TYPE_DSL_ACTION,
        created_at=_now(),
        tags=tags,
        info_structure=info,
        payload={
            "name": name,
            "description": description,
            "lean_snippet": lean_snippet,
        },
    )
