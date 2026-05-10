import LeanDream.DSL

namespace LeanDream.ProofMode

/-- Prove a Boolean circuit property by truth-table enumeration.

    Tries `decide` first: the kernel checks the proof directly, which is
    fast for properties quantified over Bool (arity ≤ 4).
    Falls back to `native_decide` which compiles to native code — useful
    when the kernel is too slow for deeper nesting. -/
macro "circuit_decide" : tactic => `(tactic| first | decide | native_decide)

end LeanDream.ProofMode
