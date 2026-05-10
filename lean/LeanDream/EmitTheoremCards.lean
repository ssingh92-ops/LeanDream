import LeanDream.DSL
import LeanDream.Macros
import LeanDream.Properties
import LeanDream.ProofRouter

namespace LeanDream.EmitTheoremCards
open LeanDream

/-!
## Theorem Card Metadata

Each `TheoremCard` records a Lean-verified algebraic property of a DSL macro.
Python reads `theorem_cards.json` (written by `lean/scripts/emit_cards.py`) and
indexes these as `theorem_property` cards in the RAG store.

Trust level: `lean_theorem_checked` — Lean type-checker verified these.
-/

structure TheoremCard where
  theorem_name  : String
  macro_name    : String   -- e.g. "macro_1"
  property      : String   -- e.g. "comm"
  lean_statement: String   -- the ∀ statement as a string
  proof_mode    : String   -- "simp_decide" | "circuit_decide" | "cases_rfl"
  trust_level   : String   -- always "lean_theorem_checked"
  deriving Repr

private def mk (tn mn prop stmt pm : String) : TheoremCard :=
  { theorem_name := tn, macro_name := mn, property := prop,
    lean_statement := stmt, proof_mode := pm,
    trust_level := "lean_theorem_checked" }

/-! ### Registered theorem cards for macro_1 (AND) -/

def cards_macro_1 : List TheoremCard := [
  mk "macro_1_comm"          "macro_1" "comm"
     "∀ a b : Bool, (macro_1 (.const a) (.const b)).eval env = (macro_1 (.const b) (.const a)).eval env"
     "circuit_decide",
  mk "macro_1_comm_circ"     "macro_1" "comm_circuit"
     "∀ (x y : Circuit) env, (macro_1 x y).eval env = (macro_1 y x).eval env"
     "simp_decide",
  mk "macro_1_assoc_circ"    "macro_1" "assoc_circuit"
     "∀ (x y z : Circuit) env, (macro_1 (macro_1 x y) z).eval env = (macro_1 x (macro_1 y z)).eval env"
     "simp_decide",
  mk "macro_1_idem_circ"     "macro_1" "idem_circuit"
     "∀ (x : Circuit) env, (macro_1 x x).eval env = x.eval env"
     "simp_decide",
  mk "macro_1_ann_false_left"  "macro_1" "annihilator_false_left"
     "∀ (x : Circuit) env, (macro_1 (.const false) x).eval env = false"
     "simp_decide",
  mk "macro_1_ann_false_right" "macro_1" "annihilator_false_right"
     "∀ (x : Circuit) env, (macro_1 x (.const false)).eval env = false"
     "simp_decide",
  mk "macro_1_id_true_left"    "macro_1" "identity_true_left"
     "∀ (x : Circuit) env, (macro_1 (.const true) x).eval env = x.eval env"
     "simp_decide",
  mk "macro_1_id_true_right"   "macro_1" "identity_true_right"
     "∀ (x : Circuit) env, (macro_1 x (.const true)).eval env = x.eval env"
     "simp_decide"
]

/-! ### Registered theorem cards for macro_2 (XOR) -/

def cards_macro_2 : List TheoremCard := [
  mk "macro_2_comm_circ"       "macro_2" "comm_circuit"
     "∀ (x y : Circuit) env, (macro_2 x y).eval env = (macro_2 y x).eval env"
     "simp_decide",
  mk "macro_2_assoc_circ"      "macro_2" "assoc_circuit"
     "∀ (x y z : Circuit) env, (macro_2 (macro_2 x y) z).eval env = (macro_2 x (macro_2 y z)).eval env"
     "simp_decide",
  mk "macro_2_self_cancel"     "macro_2" "self_cancel"
     "∀ (x : Circuit) env, (macro_2 x x).eval env = false"
     "simp_decide",
  mk "macro_2_id_false_left"   "macro_2" "identity_false_left"
     "∀ (x : Circuit) env, (macro_2 (.const false) x).eval env = x.eval env"
     "simp_decide",
  mk "macro_2_id_false_right"  "macro_2" "identity_false_right"
     "∀ (x : Circuit) env, (macro_2 x (.const false)).eval env = x.eval env"
     "simp_decide"
]

/-! ### Registered theorem cards for macro_3 (OR) -/

def cards_macro_3 : List TheoremCard := [
  mk "macro_3_comm_circ"       "macro_3" "comm_circuit"
     "∀ (x y : Circuit) env, (macro_3 x y).eval env = (macro_3 y x).eval env"
     "simp_decide",
  mk "macro_3_assoc_circ"      "macro_3" "assoc_circuit"
     "∀ (x y z : Circuit) env, (macro_3 (macro_3 x y) z).eval env = (macro_3 x (macro_3 y z)).eval env"
     "simp_decide",
  mk "macro_3_idem_circ"       "macro_3" "idem_circuit"
     "∀ (x : Circuit) env, (macro_3 x x).eval env = x.eval env"
     "simp_decide",
  mk "macro_3_ann_true_left"   "macro_3" "annihilator_true_left"
     "∀ (x : Circuit) env, (macro_3 (.const true) x).eval env = true"
     "simp_decide",
  mk "macro_3_ann_true_right"  "macro_3" "annihilator_true_right"
     "∀ (x : Circuit) env, (macro_3 x (.const true)).eval env = true"
     "simp_decide",
  mk "macro_3_id_false_left"   "macro_3" "identity_false_left"
     "∀ (x : Circuit) env, (macro_3 (.const false) x).eval env = x.eval env"
     "simp_decide",
  mk "macro_3_id_false_right"  "macro_3" "identity_false_right"
     "∀ (x : Circuit) env, (macro_3 x (.const false)).eval env = x.eval env"
     "simp_decide"
]

/-! ### Cross-operator identities -/

def cards_cross : List TheoremCard := [
  mk "de_morgan_and_circ"    "macro_1" "de_morgan_and"
     "∀ (x y : Circuit) env, (Circuit.not (macro_1 x y)).eval env = (macro_3 (Circuit.not x) (Circuit.not y)).eval env"
     "simp_decide",
  mk "de_morgan_or_circ"     "macro_3" "de_morgan_or"
     "∀ (x y : Circuit) env, (Circuit.not (macro_3 x y)).eval env = (macro_1 (Circuit.not x) (Circuit.not y)).eval env"
     "simp_decide",
  mk "xor_via_and_or_circ"   "macro_2" "xor_decomposition"
     "∀ (x y : Circuit) env, (macro_2 x y).eval env = (macro_3 (macro_1 x (Circuit.not y)) (macro_1 (Circuit.not x) y)).eval env"
     "cases_rfl"
]

def allCards : List TheoremCard :=
  cards_macro_1 ++ cards_macro_2 ++ cards_macro_3 ++ cards_cross

/-- Total number of Lean-verified theorem cards. -/
def cardCount : Nat := allCards.length

end LeanDream.EmitTheoremCards
