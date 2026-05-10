"""A canned 'LLM' that returns the reference solution for each spec.

Used by the `--mock` flag of the orchestrator so the verify -> mine -> install
pipeline can be exercised without OpenAI API access. The mocked answers are
intentionally written in slightly different ways across overlapping
sub-circuits so the miner has structure to discover.
"""

from __future__ import annotations

from typing import Any

from .ast import And, Circuit, Const, Not, Or, Var, Xor

REFERENCE: dict[str, Circuit] = {
    "and2": And(left=Var(index=0), right=Var(index=1)),
    "or2": Or(left=Var(index=0), right=Var(index=1)),
    "xor2": Xor(left=Var(index=0), right=Var(index=1)),
    "nand2": Not(arg=And(left=Var(index=0), right=Var(index=1))),
    "mux2": Or(
        left=And(left=Var(index=0), right=Var(index=1)),
        right=And(left=Not(arg=Var(index=0)), right=Var(index=2)),
    ),
    "half_adder_sum": Xor(left=Var(index=0), right=Var(index=1)),
    "half_adder_carry": And(left=Var(index=0), right=Var(index=1)),
    "full_adder_sum": Xor(
        left=Xor(left=Var(index=0), right=Var(index=1)),
        right=Var(index=2),
    ),
    "full_adder_carry": Or(
        left=And(left=Var(index=0), right=Var(index=1)),
        right=And(
            left=Var(index=2),
            right=Xor(left=Var(index=0), right=Var(index=1)),
        ),
    ),
    "parity3": Xor(
        left=Xor(left=Var(index=0), right=Var(index=1)),
        right=Var(index=2),
    ),
}


def generate_circuit(
    spec: dict[str, Any],
    installed_macros: dict[str, dict[str, Any]] | None = None,
    *,
    model: str | None = None,
    iteration: int = 0,
    memory_pack: str = "",
) -> tuple[Circuit, str]:
    name = spec["name"]
    if name not in REFERENCE:
        raise KeyError(f"no mock for spec {name!r}")
    return REFERENCE[name], "mock reference solution"
