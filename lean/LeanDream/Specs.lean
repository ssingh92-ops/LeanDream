import LeanDream.DSL

namespace LeanDream.Specs
open LeanDream

-- 2-input AND
def and2_arity : Nat := 2
def and2 : Circuit := .and (.var 0) (.var 1)

-- 2-input OR
def or2_arity : Nat := 2
def or2 : Circuit := .or (.var 0) (.var 1)

-- 2-input XOR
def xor2_arity : Nat := 2
def xor2 : Circuit := .xor (.var 0) (.var 1)

-- 2-input NAND
def nand2_arity : Nat := 2
def nand2 : Circuit := .not (.and (.var 0) (.var 1))

-- 2-to-1 mux: var 0 = sel, var 1 = a, var 2 = b; output = sel ? a : b
def mux2_arity : Nat := 3
def mux2 : Circuit :=
  .or (.and (.var 0) (.var 1)) (.and (.not (.var 0)) (.var 2))

-- Half-adder sum: a XOR b
def half_adder_sum_arity : Nat := 2
def half_adder_sum : Circuit := .xor (.var 0) (.var 1)

-- Half-adder carry: a AND b
def half_adder_carry_arity : Nat := 2
def half_adder_carry : Circuit := .and (.var 0) (.var 1)

-- Full-adder sum: a XOR b XOR cin
def full_adder_sum_arity : Nat := 3
def full_adder_sum : Circuit := .xor (.xor (.var 0) (.var 1)) (.var 2)

-- Full-adder carry: (a AND b) OR (cin AND (a XOR b))
def full_adder_carry_arity : Nat := 3
def full_adder_carry : Circuit :=
  .or (.and (.var 0) (.var 1)) (.and (.var 2) (.xor (.var 0) (.var 1)))

-- 3-input parity (odd): a XOR b XOR c
def parity3_arity : Nat := 3
def parity3 : Circuit := .xor (.xor (.var 0) (.var 1)) (.var 2)

-- 3-input majority: output 1 when ≥2 inputs are 1
def majority3_arity : Nat := 3
def majority3 : Circuit :=
  .or (.or (.and (.var 0) (.var 1)) (.and (.var 1) (.var 2))) (.and (.var 0) (.var 2))

-- 4-input parity (odd): a XOR b XOR c XOR d
def parity4_arity : Nat := 4
def parity4 : Circuit := .xor (.xor (.xor (.var 0) (.var 1)) (.var 2)) (.var 3)

-- 4-input XOR chain: ((a XOR b) XOR (c XOR d))
def xor_chain4_arity : Nat := 4
def xor_chain4 : Circuit := .xor (.xor (.var 0) (.var 1)) (.xor (.var 2) (.var 3))

-- Stage 5: motif-rich nonlinear composition specs

-- 3-input AND: a AND b AND c
def and3_arity : Nat := 3
def and3 : Circuit := .and (.and (.var 0) (.var 1)) (.var 2)

-- 3-input OR: a OR b OR c
def or3_arity : Nat := 3
def or3 : Circuit := .or (.or (.var 0) (.var 1)) (.var 2)

-- 2-input XNOR: NOT (a XOR b)
def xnor2_arity : Nat := 2
def xnor2 : Circuit := .not (.xor (.var 0) (.var 1))

-- 4-input majority: output 1 when at least 3 inputs are 1
def majority4_arity : Nat := 4
def majority4 : Circuit :=
  .or (.or (.and (.var 0) (.and (.var 1) (.var 2)))
           (.and (.var 0) (.and (.var 1) (.var 3))))
      (.or (.and (.var 0) (.and (.var 2) (.var 3)))
           (.and (.var 1) (.and (.var 2) (.var 3))))

-- Formula-generated specs are appended below by leandream.specs_gen.regenerate.
-- BEGIN GENERATED
-- gt4: arity 4, generated from formula 'leandream.spec_formulas:gt'
def gt4_arity : Nat := 4
def gt4 : Circuit := (.or (.and (.var 0) (.not (.var 2))) (.and (.not (.xor (.var 0) (.var 2))) (.or (.and (.var 1) (.not (.var 3))) (.and (.not (.xor (.var 1) (.var 3))) (.const false)))))

-- lt4: arity 4, generated from formula 'leandream.spec_formulas:lt'
def lt4_arity : Nat := 4
def lt4 : Circuit := (.or (.and (.not (.var 0)) (.var 2)) (.and (.not (.xor (.var 0) (.var 2))) (.or (.and (.not (.var 1)) (.var 3)) (.and (.not (.xor (.var 1) (.var 3))) (.const false)))))

-- majority5: arity 5, generated from formula 'leandream.spec_formulas:majority'
def majority5_arity : Nat := 5
def majority5 : Circuit := (.or (.or (.or (.or (.or (.or (.or (.or (.or (.and (.and (.var 0) (.var 1)) (.var 2)) (.and (.and (.var 0) (.var 1)) (.var 3))) (.and (.and (.var 0) (.var 1)) (.var 4))) (.and (.and (.var 0) (.var 2)) (.var 3))) (.and (.and (.var 0) (.var 2)) (.var 4))) (.and (.and (.var 0) (.var 3)) (.var 4))) (.and (.and (.var 1) (.var 2)) (.var 3))) (.and (.and (.var 1) (.var 2)) (.var 4))) (.and (.and (.var 1) (.var 3)) (.var 4))) (.and (.and (.var 2) (.var 3)) (.var 4)))

-- majority7: arity 7, generated from formula 'leandream.spec_formulas:majority'
def majority7_arity : Nat := 7
def majority7 : Circuit := (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.or (.and (.and (.and (.var 0) (.var 1)) (.var 2)) (.var 3)) (.and (.and (.and (.var 0) (.var 1)) (.var 2)) (.var 4))) (.and (.and (.and (.var 0) (.var 1)) (.var 2)) (.var 5))) (.and (.and (.and (.var 0) (.var 1)) (.var 2)) (.var 6))) (.and (.and (.and (.var 0) (.var 1)) (.var 3)) (.var 4))) (.and (.and (.and (.var 0) (.var 1)) (.var 3)) (.var 5))) (.and (.and (.and (.var 0) (.var 1)) (.var 3)) (.var 6))) (.and (.and (.and (.var 0) (.var 1)) (.var 4)) (.var 5))) (.and (.and (.and (.var 0) (.var 1)) (.var 4)) (.var 6))) (.and (.and (.and (.var 0) (.var 1)) (.var 5)) (.var 6))) (.and (.and (.and (.var 0) (.var 2)) (.var 3)) (.var 4))) (.and (.and (.and (.var 0) (.var 2)) (.var 3)) (.var 5))) (.and (.and (.and (.var 0) (.var 2)) (.var 3)) (.var 6))) (.and (.and (.and (.var 0) (.var 2)) (.var 4)) (.var 5))) (.and (.and (.and (.var 0) (.var 2)) (.var 4)) (.var 6))) (.and (.and (.and (.var 0) (.var 2)) (.var 5)) (.var 6))) (.and (.and (.and (.var 0) (.var 3)) (.var 4)) (.var 5))) (.and (.and (.and (.var 0) (.var 3)) (.var 4)) (.var 6))) (.and (.and (.and (.var 0) (.var 3)) (.var 5)) (.var 6))) (.and (.and (.and (.var 0) (.var 4)) (.var 5)) (.var 6))) (.and (.and (.and (.var 1) (.var 2)) (.var 3)) (.var 4))) (.and (.and (.and (.var 1) (.var 2)) (.var 3)) (.var 5))) (.and (.and (.and (.var 1) (.var 2)) (.var 3)) (.var 6))) (.and (.and (.and (.var 1) (.var 2)) (.var 4)) (.var 5))) (.and (.and (.and (.var 1) (.var 2)) (.var 4)) (.var 6))) (.and (.and (.and (.var 1) (.var 2)) (.var 5)) (.var 6))) (.and (.and (.and (.var 1) (.var 3)) (.var 4)) (.var 5))) (.and (.and (.and (.var 1) (.var 3)) (.var 4)) (.var 6))) (.and (.and (.and (.var 1) (.var 3)) (.var 5)) (.var 6))) (.and (.and (.and (.var 1) (.var 4)) (.var 5)) (.var 6))) (.and (.and (.and (.var 2) (.var 3)) (.var 4)) (.var 5))) (.and (.and (.and (.var 2) (.var 3)) (.var 4)) (.var 6))) (.and (.and (.and (.var 2) (.var 3)) (.var 5)) (.var 6))) (.and (.and (.and (.var 2) (.var 4)) (.var 5)) (.var 6))) (.and (.and (.and (.var 3) (.var 4)) (.var 5)) (.var 6)))

-- min2_of4: arity 4, generated from formula 'leandream.spec_formulas:at_least_two'
def min2_of4_arity : Nat := 4
def min2_of4 : Circuit := (.or (.or (.or (.or (.or (.and (.var 0) (.var 1)) (.and (.var 0) (.var 2))) (.and (.var 0) (.var 3))) (.and (.var 1) (.var 2))) (.and (.var 1) (.var 3))) (.and (.var 2) (.var 3)))

-- nand4: arity 4, generated from formula 'leandream.spec_formulas:nand_chain'
def nand4_arity : Nat := 4
def nand4 : Circuit := (.not (.and (.and (.and (.var 0) (.var 1)) (.var 2)) (.var 3)))

-- nor4: arity 4, generated from formula 'leandream.spec_formulas:nor_chain'
def nor4_arity : Nat := 4
def nor4 : Circuit := (.not (.or (.or (.or (.var 0) (.var 1)) (.var 2)) (.var 3)))

-- one_hot4: arity 4, generated from formula 'leandream.spec_formulas:is_one_hot'
def one_hot4_arity : Nat := 4
def one_hot4 : Circuit := (.and (.or (.or (.or (.var 0) (.var 1)) (.var 2)) (.var 3)) (.not (.or (.or (.or (.or (.or (.and (.var 0) (.var 1)) (.and (.var 0) (.var 2))) (.and (.var 0) (.var 3))) (.and (.var 1) (.var 2))) (.and (.var 1) (.var 3))) (.and (.var 2) (.var 3)))))

-- palindrome6: arity 6, generated from formula 'leandream.spec_formulas:is_palindrome'
def palindrome6_arity : Nat := 6
def palindrome6 : Circuit := (.and (.and (.not (.xor (.var 0) (.var 5))) (.not (.xor (.var 1) (.var 4)))) (.not (.xor (.var 2) (.var 3))))

-- parity6: arity 6, generated from formula 'leandream.spec_formulas:parity'
def parity6_arity : Nat := 6
def parity6 : Circuit := (.xor (.xor (.xor (.xor (.xor (.var 0) (.var 1)) (.var 2)) (.var 3)) (.var 4)) (.var 5))

-- parity8: arity 8, generated from formula 'leandream.spec_formulas:parity'
def parity8_arity : Nat := 8
def parity8 : Circuit := (.xor (.xor (.xor (.xor (.xor (.xor (.xor (.var 0) (.var 1)) (.var 2)) (.var 3)) (.var 4)) (.var 5)) (.var 6)) (.var 7))

-- rotate_eq6: arity 6, generated from formula 'leandream.spec_formulas:rotate_eq'
def rotate_eq6_arity : Nat := 6
def rotate_eq6 : Circuit := (.and (.and (.not (.xor (.var 3) (.var 1))) (.not (.xor (.var 4) (.var 2)))) (.not (.xor (.var 5) (.var 0))))
-- END GENERATED

end LeanDream.Specs
