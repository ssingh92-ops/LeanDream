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


def render_semantic_role_map(roles: dict[str, dict | None]) -> str:
    """Build a SEMANTIC ROLE MAP block from detected macro roles.

    Shows each role with actual macro name, arity, legal JSON schema, and
    arity warnings for macros commonly called with the wrong number of args.
    When AND and OR macros are both known, appends the explicit majority3
    formula using their actual macro names.
    """
    filled = [(role, info) for role, info in roles.items() if info is not None]
    if not filled:
        return ""
    lines = ["[SEMANTIC ROLE MAP — use these macro names for their boolean roles]"]
    for role, info in sorted(filled):
        label = _ROLE_LABELS.get(role, role)
        name = info["name"]
        arity = info["arity"]
        schema = info["legal_schema"]
        lines.append(f"  {label} → {name}(args={arity})")
        lines.append(f"    legal: {schema}")
        if role in ("carry_macro", "majority3_macro") and arity == 3:
            lines.append(f"    NEVER call {name} with 2 args — requires exactly 3")

    and_info = roles.get("and_macro")
    or_info  = roles.get("or_macro")
    and_m = and_info["name"] if and_info else None
    or_m  = or_info["name"] if or_info else None

    if and_m and or_m:
        formula_text = f"{or_m}({or_m}({and_m}(a,b), {and_m}(b,c)), {and_m}(a,c))"
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
        lines.append(f"  majority3 formula: majority(a,b,c) = {formula_text}")
        lines.append(f"  JSON: {formula_json}")

    # If a carry or majority3 macro exists, show direct 3-arg usage
    carry_info = roles.get("carry_macro") or roles.get("majority3_macro")
    if carry_info:
        cname = carry_info["name"]
        lines.append("")
        lines.append(f"  Direct 3-arg usage (carry/majority shortcut):")
        lines.append(f"  majority3(a,b,c) = {cname}(a, b, c)  [3 args required]")
        lines.append(f"  {carry_info['legal_schema']}")

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


# Concrete one-line theorem hints shown to the LLM for each proven property.
# Format: lambda macro_name -> human-readable equation string.
_PROP_HINTS: dict[str, Any] = {
    "commutative":           lambda m: f"{m}(a,b) = {m}(b,a)  [args interchangeable]",
    "idempotent":            lambda m: f"{m}(a,a) = a  [duplicate arg simplifies]",
    "associative":           lambda m: f"{m}({m}(a,b),c) = {m}(a,{m}(b,c))  [chain freely]",
    "involution":            lambda m: f"{m}({m}(a)) = a  [double negation cancels]",
    "constancy":             lambda m: f"{m}(a) = a  [identity function]",
    "identity_left_false":   lambda m: f"{m}(false,a) = a",
    "identity_left_true":    lambda m: f"{m}(true,a) = a",
    "identity_right_false":  lambda m: f"{m}(a,false) = a",
    "identity_right_true":   lambda m: f"{m}(a,true) = a",
    "annihilator_left_false":  lambda m: f"{m}(false,a) = false",
    "annihilator_left_true":   lambda m: f"{m}(true,a) = true",
    "annihilator_right_false": lambda m: f"{m}(a,false) = false",
    "annihilator_right_true":  lambda m: f"{m}(a,true) = true",
}


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
        lines.append(
            f"- {name} (arity {arity}, mined from {', '.join(members) or '?'}){suffix}: {body}"
        )
        # Expand each proven property into a concrete equation so the LLM can
        # use it directly without re-deriving the behaviour from the truth table.
        for p in props:
            hint_fn = _PROP_HINTS.get(p)
            if hint_fn:
                lines.append(f"    [theorem] {hint_fn(name)}")
    return "\n".join(lines)


# Truth tables are rendered in full up to this many rows. For larger arities
# only a representative sample is shown — the LLM should rely on `description`.
_TT_FULL_ROWS = 16


def render_truth_table(spec: dict[str, Any]) -> str:
    inputs = spec["inputs"]
    arity = spec.get("arity", len(inputs))
    table = spec["truth_table"]
    header = ["| " + " | ".join(inputs) + " | output |",
              "|" + "---|" * (len(inputs) + 1)]
    if len(table) <= _TT_FULL_ROWS:
        rows = list(table)
        truncated = False
    else:
        # Sample first half + last half so all-zeros and all-ones rows appear.
        keep = _TT_FULL_ROWS // 2
        rows = table[:keep] + table[-keep:]
        truncated = True
    body = []
    for row in rows:
        cells = ["1" if v else "0" for v in row["inputs"]]
        out = "1" if row["output"] else "0"
        body.append("| " + " | ".join(cells) + f" | {out} |")
    out_lines = header + body
    if truncated:
        out_lines.append(
            f"  (truncated — table has 2^{arity} = {len(table)} rows; "
            f"rely on the spec description for the full function)"
        )
    return "\n".join(out_lines)


def _compose_first_section(
    spec: dict[str, Any],
    installed_macros: dict[str, dict[str, Any]],
) -> str:
    """Add an aggressive macro-composition nudge for high-arity specs.

    Active when arity ≥ 4 AND there are ≥ 3 installed macros — below those
    bars the LLM doesn't have either the need (small specs) or the vocabulary
    (empty registry) for composition to be the obvious win.
    """
    arity = spec.get("arity", 0)
    # Fire on any non-trivial arity once even one macro exists. Earlier nudges
    # mean more `mac` references appear in raw circuits, which feed the
    # composition miner.
    if arity < 3 or len(installed_macros) < 1:
        return ""

    # Approximate node count for a primitive-only solution: roughly arity-1
    # binary operators for an XOR/OR/AND tree, more for majority-style specs.
    primitive_estimate = max(1, 4 * (arity - 1))

    candidates: list[tuple[str, dict[str, Any]]] = []
    for name, info in installed_macros.items():
        if info.get("alias_of"):
            continue
        if info.get("arity", 0) <= 1:
            continue
        candidates.append((name, info))
    # Sort by support desc so the most-used macros lead.
    candidates.sort(key=lambda kv: kv[1].get("support", 0), reverse=True)

    if not candidates:
        return ""

    lines = [
        "",
        "Composition guidance:",
        f"  This spec has arity {arity}. A primitive-only solution would take "
        f"~{primitive_estimate} AST nodes. Composing installed macros is "
        f"strongly preferred — verified circuits that reference macros earn "
        f"higher reward and contribute to deeper macro discovery.",
        "  Top candidates by support (the bandit ranks these first):",
    ]
    for name, info in candidates[:6]:
        body = info.get("body_repr", "?")
        macro_arity = info.get("arity", "?")
        props = info.get("properties", []) or []
        prop_str = f"  [{', '.join(props)}]" if props else ""
        lines.append(f"    - {name}/{macro_arity}: {body}{prop_str}")
    lines.append(
        "  Reach for these when the spec exposes a sub-pattern they compute. "
        "Two parity-of-4 macros XOR'd together is a parity-of-8 — you do not "
        "need to write 7 nested xor nodes."
    )
    return "\n".join(lines) + "\n"


def build_user_prompt(
    spec: dict[str, Any],
    installed_macros: dict[str, dict[str, Any]],
    memory_pack: str = "",
) -> str:
    memory_section = f"\n{memory_pack}\n" if memory_pack else ""
    compose_section = _compose_first_section(spec, installed_macros)
    return f"""\
Spec: {spec['name']}
{spec.get('description', '').strip()}

Arity: {spec['arity']}
Inputs: {', '.join(spec['inputs'])} (index 0 = {spec['inputs'][0]}, etc.)

Truth table:
{render_truth_table(spec)}
{compose_section}{memory_section}\
Installed macros you may reference via {{"kind": "mac", "name": ...}}:
{render_macros(installed_macros)}

Produce a single JSON expression tree that computes the output column for \
every input row. Output ONLY the JSON for the `circuit` field of the response \
schema; do not include any commentary in `reasoning` longer than one short \
sentence.
"""
