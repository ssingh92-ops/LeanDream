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

end LeanDream.Specs
