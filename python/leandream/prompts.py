"""Prompt construction for the LLM."""

from __future__ import annotations

import json
from typing import Any

from .ast import Circuit
from .miner import hash_key


SYSTEM_PROMPT = """\
You are a circuit-construction assistant. You write programs in a small \
combinational-circuit DSL. Each program is a JSON expression tree built from \
these constructors:

  {"kind": "var",   "index": <int>}                -- input bit at index
  {"kind": "const", "value": <true|false>}         -- literal
  {"kind": "not",   "arg":   <expr>}               -- logical NOT
  {"kind": "and",   "left":  <expr>, "right": <expr>}
  {"kind": "or",    "left":  <expr>, "right": <expr>}
  {"kind": "xor",   "left":  <expr>, "right": <expr>}
  {"kind": "mac",   "name": "<macro_name>", "args": [<expr>, <expr>, ...]}

Macros are PARAMETERIZED: each one takes a fixed number of sub-circuit args \
(its arity). When you reference a macro, the `args` list MUST have exactly \
that many entries, and each entry is itself any valid Circuit expression. \
Inside a macro definition, the i-th input is referred to as `x_i`; you don't \
write that yourself — you just provide args in order.

Example: if `macro_1` is the parameterized `and(x0, x1)`, then \
`{"kind":"mac","name":"macro_1","args":[{"kind":"var","index":0}, {"kind":"var","index":2}]}` \
denotes `var(0) AND var(2)`.

Constraints:
- The program must compute the truth table you are given.
- Inputs are referenced by zero-based index (0, 1, 2, ...).
- Prefer using installed macros when their behavior matches a piece of the \
target. Reusing macros is encouraged because it keeps programs small and \
readable, and the system mines repeated structure to grow this macro library.
- A macro's PROVEN PROPERTIES (commutativity, idempotence, identity, ...) are \
listed alongside its body when present — use them to justify substitutions.
- Do not invent macro names that are not in the installed list. Do not pass \
the wrong number of args to a macro.
"""


_ROLE_LABELS: dict[str, str] = {
    "and_macro":      "AND(a,b)",
    "or_macro":       "OR(a,b)",
    "xor_macro":      "XOR(a,b)",
    "not_macro":      "NOT(a)",
    "nand_macro":     "NAND(a,b)",
    "nor_macro":      "NOR(a,b)",
    "xnor_macro":     "XNOR(a,b)",
    "majority3_macro":"majority(a,b,c)",
    "carry_macro":    "full_adder_carry(a,b,cin)",
    "xor3_macro":     "XOR3(a,b,c)",
    "xor4_macro":     "XOR4(a,b,c,d)",
}


def render_semantic_role_map(roles: dict[str, str | None]) -> str:
    """Build a SEMANTIC ROLE MAP block from detected macro roles.

    Only includes non-None roles.  When AND and OR macros are both known,
    appends the explicit majority3 formula using their actual macro names.
    """
    filled = [(role, macro) for role, macro in roles.items() if macro is not None]
    if not filled:
        return ""
    lines = ["[SEMANTIC ROLE MAP — use these macro names for their boolean roles]"]
    for role, macro in sorted(filled):
        label = _ROLE_LABELS.get(role, role)
        lines.append(f"  {label} → {macro}")
    and_m = roles.get("and_macro")
    or_m  = roles.get("or_macro")
    if and_m and or_m:
        formula_text = (
            f"{or_m}({or_m}({and_m}(a,b), {and_m}(b,c)), {and_m}(a,c))"
        )
        formula_json = (
            f'{{"kind":"mac","name":"{or_m}","args":['
            f'{{"kind":"mac","name":"{or_m}","args":['
            f'{{"kind":"mac","name":"{and_m}","args":[{{"kind":"var","index":0}},{{"kind":"var","index":1}}]}},'
            f'{{"kind":"mac","name":"{and_m}","args":[{{"kind":"var","index":1}},{{"kind":"var","index":2}}]}}'
            f']}},'
            f'{{"kind":"mac","name":"{and_m}","args":[{{"kind":"var","index":0}},{{"kind":"var","index":2}}]}}'
            f']}}'
        )
        lines.append("")
        lines.append(f"  majority3 formula:  majority(a,b,c) = {formula_text}")
        lines.append(f"  JSON: {formula_json}")
    return "\n".join(lines)


def _is_majority_or_carry_spec(spec: dict[str, Any]) -> bool:
    """True if spec truth table matches majority or full-adder-carry pattern."""
    tt = spec.get("truth_table", [])
    n = spec.get("arity", 0)
    if not tt or n not in (3, 4):
        return False
    if all(bool(r["output"]) == (sum(r["inputs"]) > n / 2) for r in tt):
        return True
    if n == 3 and all(
        bool(r["output"]) == bool(
            (r["inputs"][0] and r["inputs"][1])
            or (r["inputs"][2] and (r["inputs"][0] != r["inputs"][1]))
        )
        for r in tt
    ):
        return True
    return False


def build_majority_role_pack(spec: dict[str, Any], roles: dict[str, str | None]) -> str:
    """Return a role-map pack for majority/carry specs; empty string otherwise."""
    if not _is_majority_or_carry_spec(spec):
        return ""
    return render_semantic_role_map(roles)


def render_macros(installed: dict[str, dict[str, Any]]) -> str:
    if not installed:
        return "(no macros installed yet)"
    lines = []
    for name, info in installed.items():
        body = info.get("body_repr", "<unknown>")
        arity = info.get("arity", "?")
        members = info.get("members", [])
        props = info.get("properties", []) or []
        alias = info.get("alias_of")
        suffix = f" [alias of {alias}]" if alias else ""
        prop_str = f" {{props: {', '.join(props)}}}" if props else ""
        lines.append(
            f"- {name} (arity {arity}, mined from {', '.join(members) or '?'}){suffix}: {body}{prop_str}"
        )
    return "\n".join(lines)


def render_truth_table(spec: dict[str, Any]) -> str:
    inputs = spec["inputs"]
    rows = ["| " + " | ".join(inputs) + " | output |", "|" + "---|" * (len(inputs) + 1)]
    for row in spec["truth_table"]:
        cells = ["1" if v else "0" for v in row["inputs"]]
        out = "1" if row["output"] else "0"
        rows.append("| " + " | ".join(cells) + f" | {out} |")
    return "\n".join(rows)


def build_user_prompt(
    spec: dict[str, Any],
    installed_macros: dict[str, dict[str, Any]],
    memory_pack: str = "",
) -> str:
    memory_section = f"\n{memory_pack}\n" if memory_pack else ""
    return f"""\
Spec: {spec['name']}
{spec.get('description', '').strip()}

Arity: {spec['arity']}
Inputs: {', '.join(spec['inputs'])} (index 0 = {spec['inputs'][0]}, etc.)

Truth table:
{render_truth_table(spec)}{memory_section}
Installed macros you may reference via {{"kind": "mac", "name": ...}}:
{render_macros(installed_macros)}

Produce a single JSON expression tree that computes the output column for \
every input row. Output ONLY the JSON for the `circuit` field of the response \
schema; do not include any commentary in `reasoning` longer than one short \
sentence.
"""
