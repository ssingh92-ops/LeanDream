import LeanDream.DSL
import LeanDream.Macros
namespace LeanDream.TheoremGen
open LeanDream
-- Generated theorems below

-- theorem: macro_1_comm
theorem macro_1_comm (x0 x1 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_1 x0 x1).eval env = (Macros.macro_1 x1 x0).eval env := by
  intro env; simp [Macros.macro_1, Circuit.eval]
  <;> cases x0.eval env <;> cases x1.eval env <;> rfl

-- theorem: macro_1_idem
theorem macro_1_idem (x0 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_1 x0 x0).eval env = x0.eval env := by
  intro env; simp [Macros.macro_1, Circuit.eval]

-- theorem: macro_1_ann_false_left
theorem macro_1_ann_false_left (x0 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_1 (.const false) x0).eval env = false := by
  intro env; simp [Macros.macro_1, Circuit.eval]

-- theorem: macro_1_ann_false_right
theorem macro_1_ann_false_right (x0 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_1 x0 (.const false)).eval env = false := by
  intro env; simp [Macros.macro_1, Circuit.eval]

-- theorem: macro_1_id_true_left
theorem macro_1_id_true_left (x0 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_1 (.const true) x0).eval env = x0.eval env := by
  intro env; simp [Macros.macro_1, Circuit.eval]

-- theorem: macro_1_id_true_right
theorem macro_1_id_true_right (x0 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_1 x0 (.const true)).eval env = x0.eval env := by
  intro env; simp [Macros.macro_1, Circuit.eval]

-- theorem: macro_10_inv_inv
theorem macro_10_inv_inv (x0 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_10 (Macros.macro_10 x0)).eval env = x0.eval env := by
  intro env; simp [Macros.macro_10, Circuit.eval]

-- theorem: macro_2_comm
theorem macro_2_comm (x0 x1 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_2 x0 x1).eval env = (Macros.macro_2 x1 x0).eval env := by
  intro env; simp [Macros.macro_2, Circuit.eval]
  <;> cases x0.eval env <;> cases x1.eval env <;> rfl

-- theorem: macro_2_id_false_left
theorem macro_2_id_false_left (x0 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_2 (.const false) x0).eval env = x0.eval env := by
  intro env; simp [Macros.macro_2, Circuit.eval]

-- theorem: macro_2_id_false_right
theorem macro_2_id_false_right (x0 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_2 x0 (.const false)).eval env = x0.eval env := by
  intro env; simp [Macros.macro_2, Circuit.eval]

-- theorem: macro_3_comm
theorem macro_3_comm (x0 x1 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_3 x0 x1).eval env = (Macros.macro_3 x1 x0).eval env := by
  intro env; simp [Macros.macro_3, Circuit.eval]
  <;> cases x0.eval env <;> cases x1.eval env <;> rfl

-- theorem: macro_3_idem
theorem macro_3_idem (x0 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_3 x0 x0).eval env = x0.eval env := by
  intro env; simp [Macros.macro_3, Circuit.eval]

-- theorem: macro_3_ann_true_left
theorem macro_3_ann_true_left (x0 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_3 (.const true) x0).eval env = true := by
  intro env; simp [Macros.macro_3, Circuit.eval]

-- theorem: macro_3_ann_true_right
theorem macro_3_ann_true_right (x0 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_3 x0 (.const true)).eval env = true := by
  intro env; simp [Macros.macro_3, Circuit.eval]

-- theorem: macro_3_id_false_left
theorem macro_3_id_false_left (x0 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_3 (.const false) x0).eval env = x0.eval env := by
  intro env; simp [Macros.macro_3, Circuit.eval]

-- theorem: macro_3_id_false_right
theorem macro_3_id_false_right (x0 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_3 x0 (.const false)).eval env = x0.eval env := by
  intro env; simp [Macros.macro_3, Circuit.eval]

-- theorem: macro_7_ann_false_right
theorem macro_7_ann_false_right (x0 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_7 x0 (.const false)).eval env = false := by
  intro env; simp [Macros.macro_7, Circuit.eval]

-- theorem: macro_7_id_false_left
theorem macro_7_id_false_left (x0 : Circuit) :
    ∀ env : Nat → Bool,
      (Macros.macro_7 (.const false) x0).eval env = x0.eval env := by
  intro env; simp [Macros.macro_7, Circuit.eval]
