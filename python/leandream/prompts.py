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
