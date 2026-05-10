"""One-shot error repair for the LLM→Lean pipeline.

Repairable errors → targeted hint strings injected as memory_pack for a retry.
Each spec gets at most one repair attempt per iteration.

Template catalogue (V4):
  A. arity_mismatch   — exact arity table + legal JSON schema
  B. unknown_macro    — available macro list
  C. semantic_mismatch — failing truth-table row + counterexample
  D. hole_guided      — hole type + target signature + existing repair paths
  E. repeated_failure — blocks same-circuit resubmission
  F. expansion errors — cycle / depth warnings
  G. lean_failed      — Lean error excerpt
"""
from __future__ import annotations

import re

from .attempts import (
    STATUS_ARITY_MISMATCH,
    STATUS_EXPANSION_CYCLE,
    STATUS_EXPANSION_DEPTH,
    STATUS_LEAN_FAILED,
    STATUS_PREFLIGHT_FAILED,
    STATUS_REPEATED_FAILURE,
    STATUS_SEMANTIC_MISMATCH,
    STATUS_UNKNOWN_MACRO,
)

REPAIRABLE = frozenset([
    STATUS_UNKNOWN_MACRO,
    STATUS_ARITY_MISMATCH,
    STATUS_EXPANSION_CYCLE,
    STATUS_EXPANSION_DEPTH,
    STATUS_LEAN_FAILED,
    STATUS_SEMANTIC_MISMATCH,
    STATUS_PREFLIGHT_FAILED,
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

    elif status == STATUS_SEMANTIC_MISMATCH:
        lines.append("Error: circuit has correct structure but wrong truth table.")
        if error_message:
            lines.append(f"Mismatch details: {error_message}")
        lines.append("Do not resubmit the same circuit. Verify each input row manually.")
        lines.append("Return corrected JSON only.")

    elif status == STATUS_PREFLIGHT_FAILED:
        lines.append(f"Error: circuit rejected before Lean — {error_message}")
        name = macro_name or _extract_macro_name_from_arity_error(error_message)
        if name and registry and name in registry:
            arity = registry[name].get("arity", "?")
            body = registry[name].get("body_repr", "?")
            args_repr = ", ".join(["expr"] * int(arity)) if str(arity).isdigit() else "..."
            schema = f'{{"kind":"mac","name":"{name}","args":[{args_repr}]}}'
            lines.append(f"Correct call for {name}: {schema}")
            lines.append(f"Body: {body}")
        elif registry:
            macro_table = _build_macro_table(registry)
            lines.append("Available macros (arity | legal schema):")
            lines.extend(macro_table)
        lines.append("Return corrected JSON only.")

    return "\n".join(lines)


def build_semantic_repair_pack(
    spec_name: str,
    failing_input: list[bool] | None,
    expected_output: bool | None,
    actual_output: bool | None,
) -> str:
    """Template C: semantic mismatch with a specific counterexample."""
    lines = ["[Repair context — semantic mismatch]"]
    lines.append(f"Spec: {spec_name}")
    if failing_input is not None:
        lines.append(f"Failing input: {[int(b) for b in failing_input]}")
    if expected_output is not None:
        lines.append(f"Expected output: {int(expected_output)}")
    if actual_output is not None:
        lines.append(f"Actual output: {int(actual_output)}")
    lines.append("Do not repeat the same candidate.")
    lines.append("Trace through every truth-table row before emitting the circuit.")
    lines.append("Return corrected JSON only.")
    return "\n".join(lines)


def build_hole_guided_repair_pack(
    hole_type: str,
    spec_name: str,
    available_macros: list[str] | None = None,
    counterexample: list | None = None,
) -> str:
    """Template D: hole-guided repair — hints without inventing new primitives."""
    lines = ["[Repair context — structural hole detected]"]
    lines.append(f"Spec: {spec_name}")
    lines.append(f"Hole type: {hole_type}")
    if counterexample:
        lines.append(f"Counterexample: {counterexample}")
    if available_macros:
        lines.append("Try combining existing macros/primitives first:")
        for m in available_macros:
            lines.append(f"  {m}")
    lines.append("Do not invent new primitive operations.")
    lines.append("Do not use macro names not listed above.")
    lines.append("Return corrected JSON only.")
    return "\n".join(lines)


def build_repeated_failure_pack(
    macro_name: str | None,
    registry: dict | None = None,
) -> str:
    """Template E: blocks resubmission of the same failing pattern."""
    lines = ["[Repair context — repeated failure pattern detected]"]
    lines.append("Your last repair attempt repeated the same error type.")
    if macro_name and registry and macro_name in registry:
        arity = registry[macro_name].get("arity", "?")
        lines.append(f"Do not call {macro_name!r} with the wrong arity again.")
        lines.append(f"{macro_name} requires exactly {arity} argument(s).")
    if registry:
        macro_table = _build_macro_table(registry)
        lines.append("Full macro arity table:")
        lines.extend(macro_table)
    lines.append("Return a completely different approach or use primitives only.")
    return "\n".join(lines)


def _build_macro_table(registry: dict) -> list[str]:
    """Return compact arity-table lines for all macros in the registry."""
    rows = []
    for name, info in sorted(registry.items()):
        arity = info.get("arity", 0)
        body = info.get("body_repr", "")
        args_repr = ", ".join(["expr"] * arity)
        schema = f'{{"kind":"mac","name":"{name}","args":[{args_repr}]}}'
        rows.append(f'  {name}(args={arity}): {body}  →  {schema}')
    return rows
