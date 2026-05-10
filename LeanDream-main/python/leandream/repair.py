"""One-shot error repair for the LLM→Lean pipeline.

When an attempt fails with a repairable error, the orchestrator calls
build_repair_pack() to produce a compact context string and passes it as
memory_pack to a single retry.  No infinite repair loops — each spec gets
at most one repair attempt per iteration.

Repairable errors and their repair strategy:
  STATUS_UNKNOWN_MACRO   — list available macros; tell LLM not to invent names
  STATUS_ARITY_MISMATCH  — show the correct macro arity and body; ask to fix call
  STATUS_EXPANSION_CYCLE — warn about recursion
  STATUS_EXPANSION_DEPTH — warn about nesting depth
  STATUS_LEAN_FAILED     — include the Lean error excerpt; ask to recheck truth table

Non-repairable (no information gain from retry):
  STATUS_LLM_ERROR       — LLM itself failed; retry without new info is pointless
  STATUS_SCHEMA_ERROR    — structured output schema error (handled by openai SDK)
  STATUS_INTERNAL_ERROR  — unexpected crash
"""
from __future__ import annotations

import re

from .attempts import (
    STATUS_ARITY_MISMATCH,
    STATUS_EXPANSION_CYCLE,
    STATUS_EXPANSION_DEPTH,
    STATUS_LEAN_FAILED,
    STATUS_UNKNOWN_MACRO,
)

REPAIRABLE = frozenset([
    STATUS_UNKNOWN_MACRO,
    STATUS_ARITY_MISMATCH,
    STATUS_EXPANSION_CYCLE,
    STATUS_EXPANSION_DEPTH,
    STATUS_LEAN_FAILED,
])


def is_repairable(status: str) -> bool:
    return status in REPAIRABLE


def _extract_macro_name_from_arity_error(message: str | None) -> str | None:
    if not message:
        return None
    m = re.search(r"macro '([^']+)' expects", message)
    return m.group(1) if m else None


def build_repair_pack(
    status: str,
    error_message: str | None,
    *,
    registry: dict | None = None,
    lean_stderr_tail: str | None = None,
    macro_name: str | None = None,
) -> str:
    """Build a compact repair context string for injection into the retry prompt.

    The returned string is passed as memory_pack to the next generation call.
    It is designed to be short: the LLM already has the spec and truth table;
    this only adds the error and a targeted hint.
    """
    lines = ["[Repair context — previous attempt failed]"]

    if status == STATUS_UNKNOWN_MACRO:
        # macro_name may come from str(KeyError), which wraps in extra quotes
        clean_name = (macro_name or "").strip("'\"").replace("macro not in registry: ", "").strip("'\"")
        lines.append(f"Error: unknown macro {clean_name!r} — not in registry.")
        if registry:
            avail = ", ".join(sorted(registry)) or "(none)"
            lines.append(f"Available macros: {avail}")
        lines.append("Do not invent macro names. Only use macros listed above.")

    elif status == STATUS_ARITY_MISMATCH:
        lines.append(f"Error: macro arity mismatch — {error_message}")
        # Try to extract macro name and show its signature
        name = macro_name or _extract_macro_name_from_arity_error(error_message)
        if name and registry and name in registry:
            arity = registry[name].get("arity", "?")
            body = registry[name].get("body_repr", "?")
            lines.append(f"Hint: {name} has arity {arity} (body: {body}).")
            lines.append(f"Pass exactly {arity} sub-circuit argument(s) in args.")

    elif status == STATUS_EXPANSION_CYCLE:
        lines.append(f"Error: macro expansion cycle — {error_message}")
        lines.append("Hint: macros cannot reference themselves, directly or indirectly.")

    elif status == STATUS_EXPANSION_DEPTH:
        lines.append(f"Error: macro expansion too deep — {error_message}")
        lines.append("Hint: avoid deeply nested macro calls (max depth 64).")

    elif status == STATUS_LEAN_FAILED:
        lines.append("Error: Lean rejected the circuit — it does not match the truth table.")
        if lean_stderr_tail:
            relevant = [
                l for l in lean_stderr_tail.splitlines()
                if l.startswith("error:") and "build failed" not in l
            ][:5]
            if not relevant:
                relevant = lean_stderr_tail.splitlines()[-4:]
            if relevant:
                lines.append("Lean error (excerpt):")
                lines.extend(f"  {l}" for l in relevant)
        lines.append("Recheck every truth-table row before emitting the circuit.")

    return "\n".join(lines)
