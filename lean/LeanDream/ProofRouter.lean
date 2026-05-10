import LeanDream.DSL

namespace LeanDream.ProofRouter

/-- Maximum circuit input arity for which the `decide` kernel tactic is fast.
    Synced with the Python constant `leandream.proof_router.DECIDE_MAX_ARITY`. -/
def decideMaxArity : Nat := 4

/-- Proof routes attempted by the router, in priority order.

    Priority:
      1. simpDecide      — simp + decide for ground-level boolean goals
      2. macroProperty   — a named property theorem from Properties.lean covers this
      3. theoremProperty — a generated/exported Lean theorem card covers this
      4. kernelDecide    — `by decide`: kernel truth-table check (arity ≤ 4)
      5. nativeDecide    — `by native_decide`: compiled truth-table (arity > 4)
      6. failed          — no route succeeded
-/
inductive ProofStrategy
  | simpDecide       -- `by intro env; simp [Macros.macroN, Circuit.eval]`
  | macroProperty    -- named structural property theorem in Properties.lean
  | theoremProperty  -- generated theorem exported to TheoremGen.lean
  | kernelDecide     -- `by decide`: full truth-table, kernel-level
  | nativeDecide     -- `by native_decide`: full truth-table, native
  | failed           -- no route succeeded
  deriving Repr, BEq

/-- Rendered tactic block for a given strategy. -/
def tacticFor (s : ProofStrategy) (macroLeanName : String) : String :=
  match s with
  | .simpDecide      => s!"by intro env; simp [{macroLeanName}, Circuit.eval]"
  | .macroProperty   => "by exact ‹_›  -- property theorem applied"
  | .theoremProperty => "by exact ‹_›  -- generated theorem applied"
  | .kernelDecide    => "by decide"
  | .nativeDecide    => "by native_decide"
  | .failed          => "-- FAILED: no proof route succeeded"

/-- Classic fallback: pick decide vs native_decide by arity. -/
def decideFallback (arity : Nat) : ProofStrategy :=
  if arity ≤ decideMaxArity then .kernelDecide else .nativeDecide

/-- Ordered sequence of strategies to try for an arity-n circuit spec. -/
def routeOrder (arity : Nat) : List ProofStrategy :=
  [.simpDecide, .macroProperty, .theoremProperty, decideFallback arity]

end LeanDream.ProofRouter
