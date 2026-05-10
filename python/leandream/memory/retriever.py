"""Symbolic card retrieval by feature-tag overlap with optional info-structure boost.

Scoring formula per card:
  base     = |query_tags ∩ card_tags| / max(|query_tags|, 1)
  score    = base * type_weight + info_boost

type_weight prefers verified proofs > macros > theorems > failures > dsl_actions.
info_boost adds 0.1 for each info-structure key the caller prefers that is True
on the card (e.g. "information_preserving", "cleans_garbage").

Cards with zero matching tags are excluded from results.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .cards import (
    Card,
    TYPE_DSL_ACTION,
    TYPE_FAILURE,
    TYPE_MACRO,
    TYPE_PROOF_TRACE,
    TYPE_THEOREM_PROPERTY,
)

_TYPE_WEIGHT: dict[str, float] = {
    TYPE_PROOF_TRACE: 1.0,
    TYPE_MACRO: 0.9,
    TYPE_THEOREM_PROPERTY: 0.8,
    TYPE_FAILURE: 0.6,
    TYPE_DSL_ACTION: 0.5,
}

_INFO_KEYS = frozenset([
    "information_preserving",
    "information_losing",
    "reversible_embedding",
    "uses_ancilla",
    "cleans_garbage",
])

_INFO_BOOST = 0.10  # per matched preferred info-structure key


@dataclass
class RetrievalResult:
    card: Card
    score: float
    matched_tags: list[str] = field(default_factory=list)


def retrieve(
    query_tags: list[str],
    cards: list[Card],
    *,
    top_k: int = 5,
    info_structure_prefer: list[str] | None = None,
    exclude_types: list[str] | None = None,
) -> list[RetrievalResult]:
    """Return top-k cards ranked by tag overlap and optional info-structure boost.

    query_tags            — feature tags describing the current generation context,
                            e.g. ["spec:xor_reduce", "verified", "gate:xor", "arity:2"]
    info_structure_prefer — info-structure keys to apply a boost for,
                            e.g. ["information_preserving", "cleans_garbage"]
    exclude_types         — card type strings to omit from results
    """
    query_set = set(query_tags)
    prefer_set = set(info_structure_prefer or []) & _INFO_KEYS
    exclude = set(exclude_types or [])

    results: list[RetrievalResult] = []
    for card in cards:
        if card.card_type in exclude:
            continue
        matched = sorted(query_set & set(card.tags))
        if not matched:
            continue
        base = len(matched) / max(len(query_set), 1)
        type_weight = _TYPE_WEIGHT.get(card.card_type, 0.5)
        info_boost = sum(
            _INFO_BOOST
            for key in prefer_set
            if card.info_structure.get(key) is True
        )
        results.append(RetrievalResult(
            card=card,
            score=base * type_weight + info_boost,
            matched_tags=matched,
        ))

    results.sort(key=lambda r: (-r.score, r.card.created_at))
    return results[:top_k]
