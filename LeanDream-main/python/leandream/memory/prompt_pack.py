"""Format retrieved cards into a compact string for inclusion in the LLM prompt.

The returned string is meant to be inserted into the user prompt between the
truth-table block and the macros block. It is empty when there are no results,
so callers can safely concatenate it without adding blank sections.

Character budget (not true token count) is enforced conservatively: each card
line is added until the running total would exceed the budget minus space for
the optional info-structure hint.
"""
from __future__ import annotations

from .cards import (
    TYPE_DSL_ACTION,
    TYPE_FAILURE,
    TYPE_MACRO,
    TYPE_PROOF_TRACE,
    TYPE_THEOREM_PROPERTY,
)
from .retriever import RetrievalResult

_HEADER = "[Memory — retrieved context]\n"
_INFO_HINT = (
    "Information-structure hint: prefer patterns tagged information_preserving "
    "or cleans_garbage when applicable."
)


def _format_result(r: RetrievalResult) -> str:
    c = r.card
    p = c.payload
    if c.card_type == TYPE_PROOF_TRACE:
        return (
            f"VERIFIED: {p.get('spec', '?')} "
            f"(iter {p.get('iteration', '?')}, {p.get('elapsed_seconds', 0):.1f}s)"
        )
    if c.card_type == TYPE_FAILURE:
        return (
            f"FAILURE: {p.get('spec', '?')} — "
            f"{p.get('error_type', 'unknown')} (iter {p.get('iteration', '?')})"
        )
    if c.card_type == TYPE_MACRO:
        props = p.get("properties") or []
        prop_str = f" [props: {', '.join(props)}]" if props else ""
        return (
            f"MACRO: {p.get('name', '?')} "
            f"(arity {p.get('arity', '?')}, support {p.get('support', '?')}) "
            f"→ {p.get('body_repr', '?')}{prop_str}"
        )
    if c.card_type == TYPE_THEOREM_PROPERTY:
        return f"THEOREM: {p.get('macro_name', '?')}.{p.get('property_name', '?')}"
    if c.card_type == TYPE_DSL_ACTION:
        return f"DSL: {p.get('name', '?')} — {p.get('description', '')}"
    return f"CARD({c.card_type}): {sorted(p)[:3]}"


def pack(
    results: list[RetrievalResult],
    *,
    char_budget: int = 600,
    info_structure_hint: bool = False,
) -> str:
    """Format retrieval results into a compact prompt string.

    Returns an empty string when there are no results (safe to concatenate).
    """
    if not results:
        return ""

    hint_chars = len(_INFO_HINT) + 2 if info_structure_hint else 0
    lines: list[str] = [_HEADER]
    used = len(_HEADER) + hint_chars

    for r in results:
        line = _format_result(r)
        if used + len(line) + 1 > char_budget:
            break
        lines.append(line)
        used += len(line) + 1

    if len(lines) == 1:
        return ""

    if info_structure_hint:
        lines.append(_INFO_HINT)

    return "\n".join(lines)
