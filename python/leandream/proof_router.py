"""Python mirror of lean/LeanDream/ProofRouter.lean.

Selects the Lean tactic for a circuit proof based on input arity.
The threshold is synced with `ProofRouter.decideMaxArity = 4` in Lean:

  arity ≤ 4  →  `decide`        (kernel-checked, no compilation)
  arity > 4  →  `native_decide` (compiled to native code, scales better)

For property theorems quantified over `Bool` (macros always have small arity),
`decide` is always sufficient.  `native_decide` is reserved for candidate
verification, where the arity can be 3 or more and the circuit is arbitrary.
"""
from __future__ import annotations

DECIDE_MAX_ARITY: int = 4  # mirrors ProofRouter.decideMaxArity in Lean


def tactic_for(arity: int) -> str:
    """Return the Lean tactic name appropriate for a proof of this arity."""
    return "decide" if arity <= DECIDE_MAX_ARITY else "native_decide"
