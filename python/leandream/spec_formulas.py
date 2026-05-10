"""Formula library for parametric specs.

A formula entry is `(fn, circuit_builder)`:
  - `fn(inputs: list[bool]) -> bool` is the semantic ground truth used at
    spec-load time to populate the JSON truth-table for the prompt.
  - `circuit_builder(arity: int) -> Circuit` produces a primitive-only AST
    that computes the same function — emitted into Specs.lean so the verifier
    has a reference circuit. Must agree with `fn` for every input vector.

Formulas keep `specs/parity8.json` to one line. The loader reads
`{"formula": "leandream.spec_formulas:parity"}`, resolves it here, and
inflates the truth-table on the fly.
"""

from __future__ import annotations

from functools import reduce
from itertools import combinations
from operator import xor as _xor
from typing import Callable

from .ast import And, Circuit, Const, Not, Or, Var, Xor


# ---------------------------------------------------------------------------
# Bool functions
# ---------------------------------------------------------------------------

def parity(inputs: list[bool]) -> bool:
    """Odd parity (XOR-fold) over inputs."""
    return reduce(_xor, inputs, False)


def majority(inputs: list[bool]) -> bool:
    """Strict majority — true when more than half of the inputs are true.
    Convention: a tie (n even) is false."""
    return sum(1 for b in inputs if b) > len(inputs) // 2


def and_chain(inputs: list[bool]) -> bool:
    return all(inputs)


def or_chain(inputs: list[bool]) -> bool:
    return any(inputs)


def iff_all(inputs: list[bool]) -> bool:
    """All bits equal to each other."""
    if not inputs:
        return True
    return all(b == inputs[0] for b in inputs)


def n_bit_eq(inputs: list[bool]) -> bool:
    """Left half equals right half. Requires even arity."""
    n = len(inputs)
    if n % 2 != 0:
        raise ValueError(f"n_bit_eq needs even arity, got {n}")
    half = n // 2
    return inputs[:half] == inputs[half:]


# ---------------------------------------------------------------------------
# Circuit builders (primitive-only, used to emit Specs.lean entries)
# ---------------------------------------------------------------------------

def _xor_tree(arity: int) -> Circuit:
    """Left-folded XOR over var 0 .. var (arity-1)."""
    if arity == 0:
        return Const(value=False)
    if arity == 1:
        return Var(index=0)
    acc: Circuit = Var(index=0)
    for i in range(1, arity):
        acc = Xor(left=acc, right=Var(index=i))
    return acc


def _and_tree(arity: int) -> Circuit:
    if arity == 0:
        return Const(value=True)
    if arity == 1:
        return Var(index=0)
    acc: Circuit = Var(index=0)
    for i in range(1, arity):
        acc = And(left=acc, right=Var(index=i))
    return acc


def _or_tree(arity: int) -> Circuit:
    if arity == 0:
        return Const(value=False)
    if arity == 1:
        return Var(index=0)
    acc: Circuit = Var(index=0)
    for i in range(1, arity):
        acc = Or(left=acc, right=Var(index=i))
    return acc


def parity_circuit(arity: int) -> Circuit:
    return _xor_tree(arity)


def and_chain_circuit(arity: int) -> Circuit:
    return _and_tree(arity)


def or_chain_circuit(arity: int) -> Circuit:
    return _or_tree(arity)


def majority_circuit(arity: int) -> Circuit:
    """OR over every (arity//2 + 1)-subset of inputs, AND'd together.
    Result is the standard sum-of-products form of `sum(inputs) > arity // 2`."""
    threshold = arity // 2 + 1
    if threshold > arity:
        return Const(value=False)
    terms: list[Circuit] = []
    for combo in combinations(range(arity), threshold):
        if len(combo) == 1:
            term: Circuit = Var(index=combo[0])
        else:
            term = Var(index=combo[0])
            for i in combo[1:]:
                term = And(left=term, right=Var(index=i))
        terms.append(term)
    if not terms:
        return Const(value=False)
    out: Circuit = terms[0]
    for t in terms[1:]:
        out = Or(left=out, right=t)
    return out


def iff_all_circuit(arity: int) -> Circuit:
    """All inputs equal each other. Encoded as `AND_{i<arity-1} (xnor v_i v_{i+1})`,
    where `xnor a b = not (xor a b)`."""
    if arity <= 1:
        return Const(value=True)
    pairs: list[Circuit] = []
    for i in range(arity - 1):
        pairs.append(Not(arg=Xor(left=Var(index=i), right=Var(index=i + 1))))
    out: Circuit = pairs[0]
    for p in pairs[1:]:
        out = And(left=out, right=p)
    return out


def n_bit_eq_circuit(arity: int) -> Circuit:
    """AND of XNOR pairs between left half and right half. Requires even arity."""
    if arity % 2 != 0:
        raise ValueError(f"n_bit_eq needs even arity, got {arity}")
    if arity == 0:
        return Const(value=True)
    half = arity // 2
    pairs: list[Circuit] = []
    for i in range(half):
        pairs.append(Not(arg=Xor(left=Var(index=i), right=Var(index=half + i))))
    out: Circuit = pairs[0]
    for p in pairs[1:]:
        out = And(left=out, right=p)
    return out


# ---------------------------------------------------------------------------
# Asymmetric formulas (added to give the miner non-XOR shapes)
# ---------------------------------------------------------------------------
#
# Convention for two-half specs (lt, gt, rotate_eq): the first arity/2 inputs
# form A (MSB at index 0), the second arity/2 form B (MSB at half).

def _bits_to_int(bits: list[bool]) -> int:
    """Treat bits[0] as MSB, fold to integer."""
    n = 0
    for b in bits:
        n = (n << 1) | (1 if b else 0)
    return n


def lt(inputs: list[bool]) -> bool:
    """Unsigned `A < B` where the first half of inputs is A, second half is B."""
    if len(inputs) % 2 != 0:
        raise ValueError(f"lt needs even arity, got {len(inputs)}")
    half = len(inputs) // 2
    return _bits_to_int(inputs[:half]) < _bits_to_int(inputs[half:])


def gt(inputs: list[bool]) -> bool:
    if len(inputs) % 2 != 0:
        raise ValueError(f"gt needs even arity, got {len(inputs)}")
    half = len(inputs) // 2
    return _bits_to_int(inputs[:half]) > _bits_to_int(inputs[half:])


def at_least_two(inputs: list[bool]) -> bool:
    """Threshold-2: output 1 iff ≥ 2 inputs are 1."""
    return sum(1 for b in inputs if b) >= 2


def is_one_hot(inputs: list[bool]) -> bool:
    """Output 1 iff exactly one input is 1."""
    return sum(1 for b in inputs if b) == 1


def nor_chain(inputs: list[bool]) -> bool:
    """NOT (OR over inputs)."""
    return not any(inputs)


def nand_chain(inputs: list[bool]) -> bool:
    """NOT (AND over inputs)."""
    return not all(inputs)


def is_palindrome(inputs: list[bool]) -> bool:
    """Output 1 iff inputs read the same forwards and backwards."""
    return inputs == inputs[::-1]


def rotate_eq(inputs: list[bool]) -> bool:
    """First half rotated left by 1 equals second half."""
    if len(inputs) % 2 != 0:
        raise ValueError(f"rotate_eq needs even arity, got {len(inputs)}")
    half = len(inputs) // 2
    a = inputs[:half]
    b = inputs[half:]
    rotated = a[1:] + a[:1]
    return rotated == b


def comparator_lt_circuit(arity: int) -> Circuit:
    """Recursive comparator: A_msb<B_msb OR (A_msb==B_msb AND lt(rest))."""
    if arity % 2 != 0:
        raise ValueError(f"lt circuit needs even arity, got {arity}")
    half = arity // 2

    def rec(i: int) -> Circuit:
        if i >= half:
            return Const(value=False)  # equal at every bit ⇒ not less than
        a_i: Circuit = Var(index=i)
        b_i: Circuit = Var(index=half + i)
        # A_i < B_i iff (¬A_i) ∧ B_i
        less_at_i = And(left=Not(arg=a_i), right=b_i)
        # A_i = B_i iff ¬(A_i ⊕ B_i)
        eq_at_i: Circuit = Not(arg=Xor(left=a_i, right=b_i))
        return Or(left=less_at_i, right=And(left=eq_at_i, right=rec(i + 1)))

    return rec(0)


def comparator_gt_circuit(arity: int) -> Circuit:
    if arity % 2 != 0:
        raise ValueError(f"gt circuit needs even arity, got {arity}")
    half = arity // 2

    def rec(i: int) -> Circuit:
        if i >= half:
            return Const(value=False)
        a_i: Circuit = Var(index=i)
        b_i: Circuit = Var(index=half + i)
        gt_at_i = And(left=a_i, right=Not(arg=b_i))
        eq_at_i: Circuit = Not(arg=Xor(left=a_i, right=b_i))
        return Or(left=gt_at_i, right=And(left=eq_at_i, right=rec(i + 1)))

    return rec(0)


def at_least_two_circuit(arity: int) -> Circuit:
    """OR over every pair-AND. C(n,2) terms."""
    if arity < 2:
        return Const(value=False)
    pairs: list[Circuit] = []
    for i, j in combinations(range(arity), 2):
        pairs.append(And(left=Var(index=i), right=Var(index=j)))
    out: Circuit = pairs[0]
    for p in pairs[1:]:
        out = Or(left=out, right=p)
    return out


def is_one_hot_circuit(arity: int) -> Circuit:
    """(at-least-one) AND NOT (at-least-two)."""
    if arity == 0:
        return Const(value=False)
    if arity == 1:
        return Var(index=0)
    at_least_one: Circuit = Var(index=0)
    for i in range(1, arity):
        at_least_one = Or(left=at_least_one, right=Var(index=i))
    at_least_two_c = at_least_two_circuit(arity)
    return And(left=at_least_one, right=Not(arg=at_least_two_c))


def nor_chain_circuit(arity: int) -> Circuit:
    if arity == 0:
        return Const(value=True)
    if arity == 1:
        return Not(arg=Var(index=0))
    acc: Circuit = Var(index=0)
    for i in range(1, arity):
        acc = Or(left=acc, right=Var(index=i))
    return Not(arg=acc)


def nand_chain_circuit(arity: int) -> Circuit:
    if arity == 0:
        return Const(value=False)
    if arity == 1:
        return Not(arg=Var(index=0))
    acc: Circuit = Var(index=0)
    for i in range(1, arity):
        acc = And(left=acc, right=Var(index=i))
    return Not(arg=acc)


def is_palindrome_circuit(arity: int) -> Circuit:
    """AND of XNORs between mirror positions."""
    if arity <= 1:
        return Const(value=True)
    pairs: list[Circuit] = []
    for i in range(arity // 2):
        j = arity - 1 - i
        pairs.append(Not(arg=Xor(left=Var(index=i), right=Var(index=j))))
    out: Circuit = pairs[0]
    for p in pairs[1:]:
        out = And(left=out, right=p)
    return out


def rotate_eq_circuit(arity: int) -> Circuit:
    """AND_i (XNOR (B_i, A_{(i+1) mod half}))."""
    if arity % 2 != 0:
        raise ValueError(f"rotate_eq needs even arity, got {arity}")
    half = arity // 2
    if half == 0:
        return Const(value=True)
    if half == 1:
        # rotate of 1 element is itself; A_0 must equal B_0
        return Not(arg=Xor(left=Var(index=0), right=Var(index=1)))
    pairs: list[Circuit] = []
    for i in range(half):
        a_target = Var(index=(i + 1) % half)
        b_i: Circuit = Var(index=half + i)
        pairs.append(Not(arg=Xor(left=b_i, right=a_target)))
    out: Circuit = pairs[0]
    for p in pairs[1:]:
        out = And(left=out, right=p)
    return out


# ---------------------------------------------------------------------------
# Registry: name -> (bool function, circuit builder)
# ---------------------------------------------------------------------------

FORMULAS: dict[str, tuple[Callable[[list[bool]], bool], Callable[[int], Circuit]]] = {
    "parity": (parity, parity_circuit),
    "majority": (majority, majority_circuit),
    "and_chain": (and_chain, and_chain_circuit),
    "or_chain": (or_chain, or_chain_circuit),
    "iff_all": (iff_all, iff_all_circuit),
    "n_bit_eq": (n_bit_eq, n_bit_eq_circuit),
    "lt": (lt, comparator_lt_circuit),
    "gt": (gt, comparator_gt_circuit),
    "at_least_two": (at_least_two, at_least_two_circuit),
    "is_one_hot": (is_one_hot, is_one_hot_circuit),
    "nor_chain": (nor_chain, nor_chain_circuit),
    "nand_chain": (nand_chain, nand_chain_circuit),
    "is_palindrome": (is_palindrome, is_palindrome_circuit),
    "rotate_eq": (rotate_eq, rotate_eq_circuit),
}


def resolve(formula_ref: str) -> tuple[Callable[[list[bool]], bool], Callable[[int], Circuit]]:
    """Resolve a formula reference like 'leandream.spec_formulas:parity'
    or just 'parity' (short form keyed in FORMULAS)."""
    short = formula_ref.split(":")[-1]
    if short not in FORMULAS:
        raise KeyError(f"unknown formula: {formula_ref!r} (known: {sorted(FORMULAS)})")
    return FORMULAS[short]


# ---------------------------------------------------------------------------
# Truth-table generation
# ---------------------------------------------------------------------------

def all_input_vectors(arity: int) -> list[list[bool]]:
    out: list[list[bool]] = [[]]
    for _ in range(arity):
        out = [v + [False] for v in out] + [v + [True] for v in out]
    return out


def expand_truth_table(formula_ref: str, arity: int) -> list[dict]:
    """Return a list of `{"inputs": [...], "output": bool}` rows."""
    fn, _ = resolve(formula_ref)
    rows: list[dict] = []
    for vec in all_input_vectors(arity):
        rows.append({"inputs": vec, "output": fn(vec)})
    return rows
