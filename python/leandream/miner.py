"""Frequent-subtree miner with structural-equivalence grouping.

A subtree's *canonical form* renumbers its free `var`s to 0, 1, 2, ... in
left-to-right occurrence order. Two subtrees with the same canonical form
denote the same parametric circuit (e.g. `var 5 AND var 7` and
`var 0 AND var 1` both canonicalize to `var 0 AND var 1`).

A subtree's structural hash key is a stable string representation of its
canonical form. Candidates are grouped by this key — that is the
equivalence-class miner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator

from .ast import And, Circuit, Const, Mac, Not, Or, Var, Xor, free_vars, size
from .forest import ProofRecord


def all_subtrees(c: Circuit) -> Iterator[Circuit]:
    """Yield every subtree of `c` (including `c` itself), pre-order."""
    yield c
    if isinstance(c, Not):
        yield from all_subtrees(c.arg)
    elif isinstance(c, (And, Or, Xor)):
        yield from all_subtrees(c.left)
        yield from all_subtrees(c.right)


def canonicalize(c: Circuit) -> Circuit:
    """Rename free `var`s to occurrence-order indices. Constants and macro
    references are left alone. The result has free vars 0..k-1 where k is the
    number of distinct vars in `c`."""
    mapping: dict[int, int] = {}

    def rec(node: Circuit) -> Circuit:
        if isinstance(node, Var):
            if node.index not in mapping:
                mapping[node.index] = len(mapping)
            return Var(index=mapping[node.index])
        if isinstance(node, Const):
            return node
        if isinstance(node, Mac):
            return Mac(name=node.name, args=[rec(a) for a in node.args])
        if isinstance(node, Not):
            return Not(arg=rec(node.arg))
        if isinstance(node, And):
            return And(left=rec(node.left), right=rec(node.right))
        if isinstance(node, Or):
            return Or(left=rec(node.left), right=rec(node.right))
        if isinstance(node, Xor):
            return Xor(left=rec(node.left), right=rec(node.right))
        raise TypeError(f"unknown node: {node!r}")

    return rec(c)


def hash_key(c: Circuit) -> str:
    """Stable, hashable representation of an AST."""
    if isinstance(c, Var):
        return f"v{c.index}"
    if isinstance(c, Const):
        return f"c{1 if c.value else 0}"
    if isinstance(c, Mac):
        args_str = ",".join(hash_key(a) for a in c.args)
        return f"m:{c.name}({args_str})"
    if isinstance(c, Not):
        return f"n({hash_key(c.arg)})"
    if isinstance(c, And):
        return f"a({hash_key(c.left)},{hash_key(c.right)})"
    if isinstance(c, Or):
        return f"o({hash_key(c.left)},{hash_key(c.right)})"
    if isinstance(c, Xor):
        return f"x({hash_key(c.left)},{hash_key(c.right)})"
    raise TypeError(f"unknown node: {c!r}")


@dataclass
class MacroCandidate:
    key: str  # canonical hash key, used for dedupe across runs
    ast: Circuit  # canonical AST
    support: int  # number of distinct proofs (records) containing this subtree
    occurrences: int  # total appearances across the corpus
    arity: int  # number of free vars in the canonical form
    members: list[str] = field(default_factory=list)  # specs from which this was mined


def mine(
    records: Iterable[ProofRecord],
    *,
    min_support: int = 2,
    min_size: int = 3,
) -> list[MacroCandidate]:
    """Return frequent-subtree candidates ordered by (support desc, size desc).

    `records` are typically the output of `forest.iter_records()`. Each record's
    `expanded` AST is mined; macro references are not re-expanded here (the
    forest writer is responsible for that).
    """
    by_key: dict[str, dict] = {}

    record_list = list(records)
    for idx, rec in enumerate(record_list):
        for sub in all_subtrees(rec.expanded):
            if size(sub) < min_size:
                continue
            canon = canonicalize(sub)
            key = hash_key(canon)
            entry = by_key.setdefault(
                key,
                {
                    "ast": canon,
                    "support": set(),
                    "occurrences": 0,
                    "members": set(),
                },
            )
            entry["occurrences"] += 1
            entry["support"].add(idx)
            entry["members"].add(rec.spec)

    candidates: list[MacroCandidate] = []
    for key, entry in by_key.items():
        if len(entry["support"]) < min_support:
            continue
        ast = entry["ast"]
        candidates.append(
            MacroCandidate(
                key=key,
                ast=ast,
                support=len(entry["support"]),
                occurrences=entry["occurrences"],
                arity=len(free_vars(ast)),
                members=sorted(entry["members"]),
            )
        )

    candidates.sort(key=lambda m: (-m.support, -size(m.ast), m.key))
    return candidates


def _has_mac_ref(c: Circuit) -> bool:
    """Return True if c contains any Mac node."""
    if isinstance(c, Mac):
        return True
    if isinstance(c, Not):
        return _has_mac_ref(c.arg)
    if isinstance(c, (And, Or, Xor)):
        return _has_mac_ref(c.left) or _has_mac_ref(c.right)
    return False


def _mac_names_in(c: Circuit) -> set[str]:
    """Return all macro names referenced anywhere in c."""
    if isinstance(c, Mac):
        return {c.name} | {n for a in c.args for n in _mac_names_in(a)}
    if isinstance(c, Not):
        return _mac_names_in(c.arg)
    if isinstance(c, (And, Or, Xor)):
        return _mac_names_in(c.left) | _mac_names_in(c.right)
    return set()


def mine_macro_compositions(
    records: Iterable[ProofRecord],
    *,
    min_support: int = 2,
    min_size: int = 2,
    registered_macros: set[str] | None = None,
) -> list[MacroCandidate]:
    """Mine frequent subtrees that contain macro references from raw circuits.

    Complements mine() (which operates on expanded circuits). Results represent
    macro-of-macro composition patterns visible in LLM-emitted raw circuits.

    `registered_macros`: if provided, skip subtrees that reference unknown names.
    `min_size` defaults to 2 so a single mac-node with one Var arg qualifies.
    """
    by_key: dict[str, dict] = {}
    record_list = list(records)

    for idx, rec in enumerate(record_list):
        if rec.raw is None:
            continue
        for sub in all_subtrees(rec.raw):
            if size(sub) < min_size:
                continue
            if not _has_mac_ref(sub):
                continue
            if registered_macros is not None:
                if not _mac_names_in(sub).issubset(registered_macros):
                    continue
            canon = canonicalize(sub)
            key = hash_key(canon)
            entry = by_key.setdefault(
                key,
                {"ast": canon, "support": set(), "occurrences": 0, "members": set()},
            )
            entry["occurrences"] += 1
            entry["support"].add(idx)
            entry["members"].add(rec.spec)

    candidates: list[MacroCandidate] = []
    for key, entry in by_key.items():
        if len(entry["support"]) < min_support:
            continue
        ast = entry["ast"]
        candidates.append(
            MacroCandidate(
                key=key,
                ast=ast,
                support=len(entry["support"]),
                occurrences=entry["occurrences"],
                arity=len(free_vars(ast)),
                members=sorted(entry["members"]),
            )
        )
    candidates.sort(key=lambda m: (-m.support, -size(m.ast), m.key))
    return candidates
