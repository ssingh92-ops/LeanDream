import LeanDream.DSL
import LeanDream.Macros
import LeanDream.ProofMode

namespace LeanDream.Properties
open LeanDream

theorem macro_1_comm : ∀ a b : Bool, (Macros.macro_1 (.const a) (.const b)).eval (fun _ => false) = (Macros.macro_1 (.const b) (.const a)).eval (fun _ => false) := by circuit_decide
theorem macro_1_idem : ∀ a : Bool, (Macros.macro_1 (.const a) (.const a)).eval (fun _ => false) = a := by circuit_decide
theorem macro_1_assoc : ∀ a b c : Bool, (Macros.macro_1 (Macros.macro_1 (.const a) (.const b)) (.const c)).eval (fun _ => false) = (Macros.macro_1 (.const a) (Macros.macro_1 (.const b) (.const c))).eval (fun _ => false) := by circuit_decide
theorem macro_1_ann_left_false : ∀ a : Bool, (Macros.macro_1 (.const false) (.const a)).eval (fun _ => false) = false := by circuit_decide
theorem macro_1_id_left_true : ∀ a : Bool, (Macros.macro_1 (.const true) (.const a)).eval (fun _ => false) = a := by circuit_decide
theorem macro_1_ann_right_false : ∀ a : Bool, (Macros.macro_1 (.const a) (.const false)).eval (fun _ => false) = false := by circuit_decide
theorem macro_1_id_right_true : ∀ a : Bool, (Macros.macro_1 (.const a) (.const true)).eval (fun _ => false) = a := by circuit_decide
theorem macro_2_comm : ∀ a b : Bool, (Macros.macro_2 (.const a) (.const b)).eval (fun _ => false) = (Macros.macro_2 (.const b) (.const a)).eval (fun _ => false) := by circuit_decide
theorem macro_2_assoc : ∀ a b c : Bool, (Macros.macro_2 (Macros.macro_2 (.const a) (.const b)) (.const c)).eval (fun _ => false) = (Macros.macro_2 (.const a) (Macros.macro_2 (.const b) (.const c))).eval (fun _ => false) := by circuit_decide
theorem macro_2_id_left_false : ∀ a : Bool, (Macros.macro_2 (.const false) (.const a)).eval (fun _ => false) = a := by circuit_decide
theorem macro_2_id_right_false : ∀ a : Bool, (Macros.macro_2 (.const a) (.const false)).eval (fun _ => false) = a := by circuit_decide
theorem macro_7_comm : ∀ a b : Bool, (Macros.macro_7 (.const a) (.const b)).eval (fun _ => false) = (Macros.macro_7 (.const b) (.const a)).eval (fun _ => false) := by circuit_decide
theorem macro_7_idem : ∀ a : Bool, (Macros.macro_7 (.const a) (.const a)).eval (fun _ => false) = a := by circuit_decide
theorem macro_7_assoc : ∀ a b c : Bool, (Macros.macro_7 (Macros.macro_7 (.const a) (.const b)) (.const c)).eval (fun _ => false) = (Macros.macro_7 (.const a) (Macros.macro_7 (.const b) (.const c))).eval (fun _ => false) := by circuit_decide
theorem macro_7_id_left_false : ∀ a : Bool, (Macros.macro_7 (.const false) (.const a)).eval (fun _ => false) = a := by circuit_decide
theorem macro_7_ann_left_true : ∀ a : Bool, (Macros.macro_7 (.const true) (.const a)).eval (fun _ => false) = true := by circuit_decide
theorem macro_7_id_right_false : ∀ a : Bool, (Macros.macro_7 (.const a) (.const false)).eval (fun _ => false) = a := by circuit_decide
theorem macro_7_ann_right_true : ∀ a : Bool, (Macros.macro_7 (.const a) (.const true)).eval (fun _ => false) = true := by circuit_decide
theorem macro_11_ann_left_false : ∀ a : Bool, (Macros.macro_11 (.const false) (.const a)).eval (fun _ => false) = false := by circuit_decide
theorem macro_11_id_right_false : ∀ a : Bool, (Macros.macro_11 (.const a) (.const false)).eval (fun _ => false) = a := by circuit_decide
theorem macro_12_inv : ∀ a : Bool, (Macros.macro_12 (Macros.macro_12 (.const a))).eval (fun _ => false) = a := by circuit_decide
end LeanDream.Properties
