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
    TYPE_HOLE,
    TYPE_MACRO,
    TYPE_PROOF_TRACE,
    TYPE_STRATEGY,
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
        schema = p.get("legal_call_schema", "")
        schema_str = f" | call: {schema}" if schema else ""
        tt = p.get("tt_key", "")
        tt_str = f" tt:{tt}" if tt else ""
        return (
            f"MACRO: {p.get('name', '?')} "
            f"(arity {p.get('arity', '?')}, support {p.get('support', '?')}{tt_str}) "
            f"→ {p.get('body_repr', '?')}{prop_str}{schema_str}"
        )
    if c.card_type == TYPE_THEOREM_PROPERTY:
        stmt = p.get("lean_statement", "")
        stmt_str = f" — {stmt[:60]}" if stmt else ""
        return f"THEOREM: {p.get('macro_name', '?')}.{p.get('property_name', '?')}{stmt_str}"
    if c.card_type == TYPE_DSL_ACTION:
        return f"DSL: {p.get('name', '?')} — {p.get('description', '')}"
    if c.card_type == TYPE_STRATEGY:
        formula = p.get("formula", "")
        return f"STRATEGY: {p.get('name', '?')} — {formula}"
    if c.card_type == TYPE_HOLE:
        note = (p.get("evidence") or {}).get("note", "")
        return (
            f"HOLE: {p.get('hole_type', '?')} on {', '.join(p.get('specs') or ['?'])} "
            f"[{p.get('status', 'unresolved')}]{f' — {note[:80]}' if note else ''}"
        )
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
