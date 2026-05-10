import LeanDream.DSL

namespace LeanDream.ProofRouter

/-- Maximum circuit input arity for which the `decide` kernel tactic is fast
    enough for algebraic property proofs.  Circuits with more inputs use
    `native_decide` (compiled to native code) instead.

    Synced with the Python constant `leandream.proof_router.DECIDE_MAX_ARITY`. -/
def decideMaxArity : Nat := 4

/-- Which Lean tactic to use for a proof obligation. -/
inductive ProofStrategy
  | kernelDecide  -- `by decide`: kernel-checked; arity ≤ decideMaxArity
  | nativeDecide  -- `by native_decide`: compiled;  arity > decideMaxArity
  deriving Repr

def strategyFor (arity : Nat) : ProofStrategy :=
  if arity ≤ decideMaxArity then .kernelDecide else .nativeDecide

end LeanDream.ProofRouter
