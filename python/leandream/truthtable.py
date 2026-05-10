"""Truth-table computation and canonical encoding for parameterized macros.

A macro of arity k is reduced to a 2^k-bit string by evaluating its body on
every Boolean assignment to its k parameters. This is the macro's *semantic
fingerprint* — two macros with the same key compute the same Boolean function,
regardless of how their AST is shaped.
"""

from __future__ import annotations

from .ast import Circuit, Var, evaluate


def _all_envs(arity: int) -> list[list[bool]]:
    """All Boolean assignments of length `arity`, lexicographic by index 0 lsb."""
    out: list[list[bool]] = [[]]
    for _ in range(arity):
        out = [env + [False] for env in out] + [env + [True] for env in out]
    return out


def truth_table(body: Circuit, arity: int, registry: dict[str, Circuit] | None = None) -> str:
    """Return a string of `0`/`1` of length 2^arity. Bit i is the macro's
    output on the input assignment whose decimal-encoded index is i (bit 0 of i
    = parameter x0, bit 1 = x1, ...). Macros referenced via `Mac` nodes are
    resolved via `registry` (param substitution included)."""
    rows: list[str] = []
    for env in _all_envs(arity):
        rows.append("1" if evaluate(body, env, registry) else "0")
    return "".join(rows)


def negated_table(tt: str) -> str:
    return "".join("0" if c == "1" else "1" for c in tt)


def canonical_keys(tt: str) -> tuple[str, str]:
    """Return (tt, neg_tt) so duplicate detection can also catch NOT-flips."""
    return tt, negated_table(tt)
