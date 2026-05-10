import LeanDream.DSL
import LeanDream.Specs
import LeanDream.Macros
import LeanDream.Candidate

namespace LeanDream.Verify
open LeanDream

/-- The proof obligation. If `lake build` succeeds, the candidate is
    truth-table equivalent to the target spec on `arity`-many inputs. -/
theorem candidate_correct :
    Circuit.equivOn Candidate.arity Candidate.candidate Candidate.targetSpec = true := by
  native_decide

end LeanDream.Verify
