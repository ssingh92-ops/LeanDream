import LeanDream.DSL

namespace LeanDream.SimpSets
open LeanDream

/-! ## Circuit.eval unfolding lemmas

These `@[simp]` lemmas let `simp` reduce `Circuit.eval` expressions without
requiring full truth-table enumeration via `decide`.  Useful for manual or
semi-automated proofs that construct the circuit term symbolically.
-/

@[simp]
theorem eval_var (i : Nat) (env : Nat → Bool) :
    (Circuit.var i).eval env = env i := rfl

@[simp]
theorem eval_const (b : Bool) (env : Nat → Bool) :
    (Circuit.const b).eval env = b := rfl

@[simp]
theorem eval_not (c : Circuit) (env : Nat → Bool) :
    (Circuit.not c).eval env = !(c.eval env) := rfl

@[simp]
theorem eval_and (a b : Circuit) (env : Nat → Bool) :
    (Circuit.and a b).eval env = (a.eval env && b.eval env) := rfl

@[simp]
theorem eval_or (a b : Circuit) (env : Nat → Bool) :
    (Circuit.or a b).eval env = (a.eval env || b.eval env) := rfl

@[simp]
theorem eval_xor (a b : Circuit) (env : Nat → Bool) :
    (Circuit.xor a b).eval env = Bool.xor (a.eval env) (b.eval env) := rfl

/-! ## Boolean algebra simplification lemmas

Short-circuit and identity rules frequently needed when reasoning about
circuit outputs.  Keeps proof states small by normalizing obvious sub-goals.
-/

@[simp] theorem bool_not_not (b : Bool) : (!(!b)) = b := by cases b <;> rfl

@[simp] theorem bool_and_self  (b : Bool) : (b && b) = b := by cases b <;> rfl
@[simp] theorem bool_or_self   (b : Bool) : (b || b) = b := by cases b <;> rfl
@[simp] theorem bool_xor_self  (b : Bool) : Bool.xor b b = false := by cases b <;> rfl

@[simp] theorem bool_and_false_left  (b : Bool) : (false && b) = false := rfl
@[simp] theorem bool_and_false_right (b : Bool) : (b && false) = false := by cases b <;> rfl
@[simp] theorem bool_or_false_left   (b : Bool) : (false || b) = b := rfl
@[simp] theorem bool_or_false_right  (b : Bool) : (b || false) = b := by cases b <;> rfl

@[simp] theorem bool_and_true_left   (b : Bool) : (true && b) = b := rfl
@[simp] theorem bool_and_true_right  (b : Bool) : (b && true) = b := by cases b <;> rfl
@[simp] theorem bool_or_true_left    (b : Bool) : (true || b) = true := rfl
@[simp] theorem bool_or_true_right   (b : Bool) : (b || true) = true := by cases b <;> rfl

@[simp] theorem bool_xor_false_left  (b : Bool) : Bool.xor false b = b := by cases b <;> rfl
@[simp] theorem bool_xor_false_right (b : Bool) : Bool.xor b false = b := by cases b <;> rfl
@[simp] theorem bool_xor_true_left   (b : Bool) : Bool.xor true b = !b := by cases b <;> rfl
@[simp] theorem bool_xor_true_right  (b : Bool) : Bool.xor b true = !b := by cases b <;> rfl

end LeanDream.SimpSets
