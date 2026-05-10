"""Tests for the frequent-subtree miner."""

from dataclasses import dataclass
from pathlib import Path

from leandream.ast import And, Circuit, Not, Or, Var, Xor
from leandream.forest import ProofRecord
from leandream.miner import canonicalize, hash_key, mine


def _record(spec: str, expanded: Circuit, idx: int = 0) -> ProofRecord:
    return ProofRecord(
        spec=spec,
        timestamp="t",
        iteration=idx,
        elapsed_seconds=0.0,
        expanded=expanded,
        raw=expanded,
        path=Path("/tmp/dummy.json"),
    )


def test_canonicalize_renumbers_vars_in_occurrence_order():
    # var 5 AND var 7  ->  var 0 AND var 1
    c = And(left=Var(index=5), right=Var(index=7))
    canon = canonicalize(c)
    assert isinstance(canon, And)
    assert canon.left == Var(index=0)
    assert canon.right == Var(index=1)


def test_canonicalize_is_idempotent_under_renaming():
    a = And(left=Var(index=2), right=Var(index=9))
    b = And(left=Var(index=0), right=Var(index=1))
    assert hash_key(canonicalize(a)) == hash_key(canonicalize(b))


def test_canonicalize_distinguishes_shape():
    a = And(left=Var(index=0), right=Var(index=1))
    b = Or(left=Var(index=0), right=Var(index=1))
    assert hash_key(canonicalize(a)) != hash_key(canonicalize(b))


def test_canonicalize_preserves_repeat_var_pattern():
    # var 3 AND var 3  ->  var 0 AND var 0  (NOT  var 0 AND var 1)
    c = And(left=Var(index=3), right=Var(index=3))
    canon = canonicalize(c)
    assert canon == And(left=Var(index=0), right=Var(index=0))


def test_mine_recovers_planted_subtree():
    # Shared subtree across two records: (var 0 AND var 1)
    shared = And(left=Var(index=0), right=Var(index=1))
    rec1 = _record("specA", Or(left=shared, right=Var(index=2)))
    rec2 = _record("specB", Not(arg=And(left=Var(index=4), right=Var(index=5))))
    # rec2's And uses different var indices, but canonically matches `shared`
    candidates = mine([rec1, rec2], min_support=2, min_size=3)
    keys = [c.key for c in candidates]
    assert hash_key(canonicalize(shared)) in keys


def test_mine_filters_below_min_support():
    rec = _record("only", And(left=Var(index=0), right=Var(index=1)))
    # Only one record; min_support=2 means the And shouldn't pass
    candidates = mine([rec], min_support=2, min_size=3)
    assert candidates == []


def test_mine_filters_below_min_size():
    shared = And(left=Var(index=0), right=Var(index=1))  # size 3
    rec1 = _record("a", shared)
    rec2 = _record("b", shared)
    # min_size=4 excludes the size-3 And
    candidates = mine([rec1, rec2], min_support=2, min_size=4)
    assert candidates == []


def test_mine_groups_equivalent_subtrees():
    # Two records each containing two structurally-identical XORs with different
    # var indices. Miner should group them under one key.
    a = Xor(left=Var(index=0), right=Var(index=1))
    b = Xor(left=Var(index=2), right=Var(index=3))
    rec1 = _record("p", And(left=a, right=b))
    rec2 = _record("q", Or(left=a, right=b))
    candidates = mine([rec1, rec2], min_support=2, min_size=3)
    xor_key = hash_key(canonicalize(a))
    matching = [c for c in candidates if c.key == xor_key]
    assert len(matching) == 1
    # Each record has two XOR appearances, total 4
    assert matching[0].occurrences == 4
    assert matching[0].support == 2
