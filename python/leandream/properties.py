"""Generate and prove algebraic properties of installed macros via Lean.

For each macro M of arity 2 we attempt to prove (with `by decide` over Bool):
  - commutativity     : M a b = M b a
  - idempotence       : M a a = a
  - associativity     : M (M a b) c = M a (M b c)
  - identity (left/right, 0/1)   : M e a = a  (or  M a e = a)
  - annihilator (left/right, 0/1): M e a = e  (or  M a e = e)

For arity 1 we attempt:
  - involution        : M (M a) = a
  - constancy         : M a = a   (degenerate; mostly catches identity-shaped macros)

Properties are proved per-macro so a single failed theorem cannot wipe properties
for other macros. Surviving theorems live in `lean/LeanDream/Properties.lean`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pydantic import TypeAdapter

from .ast import Circuit
from .truthtable import truth_table
from .verify import LEAN_DIR, lake_build, reset_candidate

PROPERTIES_LEAN_PATH = LEAN_DIR / "LeanDream" / "Properties.lean"

_ADAPTER: TypeAdapter[Circuit] = TypeAdapter(Circuit)

_HEADER = """\
import LeanDream.DSL
import LeanDream.Macros
import LeanDream.ProofMode

namespace LeanDream.Properties
open LeanDream

"""
_FOOTER = "\nend LeanDream.Properties\n"


@dataclass
class Property:
    name: str           # short label stored in registry, e.g. "commutative"
    theorem_name: str   # full Lean theorem identifier, e.g. "macro_1_comm"
    statement: str      # everything after `theorem <name> :` and before `:= by decide`
    predicate: Callable[[str], bool]  # given the macro's TT, does this property hold?


# --- Predicates over a 2^arity-bit truth table -------------------------------
#
# Bit i of the TT (0-indexed) is the macro's output on the assignment whose
# binary expansion (lsb = x0) equals i. So for arity 2, TT bits are M(0,0),
# M(1,0), M(0,1), M(1,1).

def _bit(tt: str, i: int) -> bool:
    return tt[i] == "1"


def _arity2_predicates() -> dict[str, Callable[[str], bool]]:
    P: dict[str, Callable[[str], bool]] = {}
    # M(a,b) = M(b,a)  <=>  bit at (a,b)=01 equals bit at (b,a)=10
    P["commutative"] = lambda tt: _bit(tt, 1) == _bit(tt, 2)
    # M(a,a) = a:  M(0,0)=0  and  M(1,1)=1
    P["idempotent"] = lambda tt: not _bit(tt, 0) and _bit(tt, 3)
    # Associativity: enumerate over a,b,c in Bool^3 using the TT directly.
    def assoc(tt: str) -> bool:
        for a in (False, True):
            for b in (False, True):
                for c in (False, True):
                    ab = _bit(tt, (1 if a else 0) | (2 if b else 0))
                    abc_left = _bit(tt, (1 if ab else 0) | (2 if c else 0))
                    bc = _bit(tt, (1 if b else 0) | (2 if c else 0))
                    abc_right = _bit(tt, (1 if a else 0) | (2 if bc else 0))
                    if abc_left != abc_right:
                        return False
        return True
    P["associative"] = assoc
    # Identity / annihilator on each (side, constant)
    for side in ("left", "right"):
        for e_str, e in (("false", False), ("true", True)):
            def make_id(side=side, e=e):
                def _f(tt: str) -> bool:
                    for a in (False, True):
                        if side == "left":
                            idx = (1 if e else 0) | (2 if a else 0)
                        else:
                            idx = (1 if a else 0) | (2 if e else 0)
                        if _bit(tt, idx) != a:
                            return False
                    return True
                return _f

            def make_ann(side=side, e=e):
                def _f(tt: str) -> bool:
                    for a in (False, True):
                        if side == "left":
                            idx = (1 if e else 0) | (2 if a else 0)
                        else:
                            idx = (1 if a else 0) | (2 if e else 0)
                        if _bit(tt, idx) != e:
                            return False
                    return True
                return _f

            P[f"identity_{side}_{e_str}"] = make_id()
            P[f"annihilator_{side}_{e_str}"] = make_ann()
    return P


def _arity1_predicates() -> dict[str, Callable[[str], bool]]:
    P: dict[str, Callable[[str], bool]] = {}
    # involution: M(M(a)) = a  <=>  M(M(0))=0 and M(M(1))=1
    def inv(tt: str) -> bool:
        m0 = _bit(tt, 0)  # M(0)
        m1 = _bit(tt, 1)  # M(1)
        return _bit(tt, 1 if m0 else 0) == False and _bit(tt, 1 if m1 else 0) == True
    P["involution"] = inv
    # constancy: M(a) = a, ie M(0)=0 and M(1)=1 (the identity function)
    P["constancy"] = lambda tt: not _bit(tt, 0) and _bit(tt, 1)
    return P


# --- Lean theorem templates --------------------------------------------------

def _arity2_properties(macro_name: str, lean_ref: str) -> list[Property]:
    preds = _arity2_predicates()
    eval_env = "(fun _ => false)"

    def call(args: str) -> str:
        return f"({lean_ref} {args}).eval {eval_env}"

    out: list[Property] = []
    out.append(Property(
        name="commutative",
        theorem_name=f"{macro_name}_comm",
        statement=(
            f"∀ a b : Bool, "
            f"{call('(.const a) (.const b)')} = {call('(.const b) (.const a)')}"
        ),
        predicate=preds["commutative"],
    ))
    out.append(Property(
        name="idempotent",
        theorem_name=f"{macro_name}_idem",
        statement=(
            f"∀ a : Bool, {call('(.const a) (.const a)')} = a"
        ),
        predicate=preds["idempotent"],
    ))
    out.append(Property(
        name="associative",
        theorem_name=f"{macro_name}_assoc",
        statement=(
            f"∀ a b c : Bool, "
            f"{call(f'({lean_ref} (.const a) (.const b)) (.const c)')} = "
            f"{call(f'(.const a) ({lean_ref} (.const b) (.const c))')}"
        ),
        predicate=preds["associative"],
    ))
    for side in ("left", "right"):
        for e in ("false", "true"):
            args = (
                f"(.const {e}) (.const a)" if side == "left" else f"(.const a) (.const {e})"
            )
            out.append(Property(
                name=f"identity_{side}_{e}",
                theorem_name=f"{macro_name}_id_{side}_{e}",
                statement=f"∀ a : Bool, {call(args)} = a",
                predicate=preds[f"identity_{side}_{e}"],
            ))
            out.append(Property(
                name=f"annihilator_{side}_{e}",
                theorem_name=f"{macro_name}_ann_{side}_{e}",
                statement=f"∀ a : Bool, {call(args)} = {e}",
                predicate=preds[f"annihilator_{side}_{e}"],
            ))
    return out


def _arity1_properties(macro_name: str, lean_ref: str) -> list[Property]:
    preds = _arity1_predicates()
    eval_env = "(fun _ => false)"
    call_inner = f"({lean_ref} (.const a)).eval {eval_env}"
    out: list[Property] = []
    out.append(Property(
        name="involution",
        theorem_name=f"{macro_name}_inv",
        statement=(
            f"∀ a : Bool, "
            f"({lean_ref} ({lean_ref} (.const a))).eval {eval_env} = a"
        ),
        predicate=preds["involution"],
    ))
    out.append(Property(
        name="constancy",
        theorem_name=f"{macro_name}_const",
        statement=f"∀ a : Bool, {call_inner} = a",
        predicate=preds["constancy"],
    ))
    return out


def candidates_for(macro_name: str, arity: int) -> list[Property]:
    lean_ref = f"Macros.{macro_name}"
    if arity == 2:
        return _arity2_properties(macro_name, lean_ref)
    if arity == 1:
        return _arity1_properties(macro_name, lean_ref)
    return []  # arity 0 (constants) and arity >= 3: out of scope


def _write_properties(theorems: list[tuple[str, str]]) -> None:
    body_lines: list[str] = []
    for theorem_name, statement in theorems:
        body_lines.append(f"theorem {theorem_name} : {statement} := by circuit_decide")
    PROPERTIES_LEAN_PATH.write_text(_HEADER + "\n".join(body_lines) + _FOOTER)


def prove_all(registry: dict[str, dict], *, verbose: bool = True) -> dict[str, dict]:
    """Prove algebraic properties for every non-alias macro.

    Strategy:
    1. Per-macro property cache check: if (macro_name, tt_key, toolchain) is
       cached, skip Lean for that macro entirely.
    2. Fast path for uncached macros: collect all their Python-pre-filtered
       theorems, write one Properties.lean, run one lake build.
    3. If fast path fails, fall back to per-macro isolation.
    4. Cache newly-proven results so future runs skip Lean for unchanged macros.
    """
    from .cache import property_prove_cache
    from .verify import _lean_toolchain_version

    reset_candidate()
    prop_cache = property_prove_cache()
    toolchain = _lean_toolchain_version()

    body_circuits: dict[str, Circuit] = {
        nm: _ADAPTER.validate_python(info["ast"])
        for nm, info in registry.items()
        if info.get("ast") is not None
    }

    # Collect per-macro candidate properties (Python pre-filtered).
    macro_candidates: dict[str, list[Property]] = {}
    macro_tt: dict[str, str] = {}

    for name, info in registry.items():
        arity = info.get("arity", 0)
        cands = candidates_for(name, arity)
        if not cands:
            macro_candidates[name] = []
            continue

        tt = info.get("tt_key")
        if not tt:
            body = body_circuits.get(name)
            if body is None:
                macro_candidates[name] = []
                continue
            tt = truth_table(body, arity, body_circuits)

        macro_tt[name] = tt
        passing = [p for p in cands if p.predicate(tt)]
        macro_candidates[name] = passing

    # --- Per-macro cache check -----------------------------------------------
    cached_props: dict[str, list[str]] = {}   # macro_name -> already-proven props
    uncached: list[str] = []                   # macros that need Lean

    for name, props in macro_candidates.items():
        tt = macro_tt.get(name, "")
        cache_key = f"{name}|{tt}|{toolchain}"
        hit = prop_cache.get(cache_key)
        if hit is not None:
            cached_props[name] = hit.get("properties", [])
        elif props:
            uncached.append(name)
        else:
            cached_props[name] = []

    # Apply cached results immediately
    n_cached = len(cached_props)
    for name, ok_names in cached_props.items():
        registry[name]["properties"] = ok_names
        if verbose and ok_names:
            print(f"  ✦ {name} [cached]: {', '.join(ok_names)}")

    if not uncached:
        # All macros were cached — rebuild Properties.lean for consistency
        all_theorems = [
            (p.theorem_name, p.statement)
            for name, props in macro_candidates.items()
            for p in props
            if p.name in set(cached_props.get(name, []))
        ]
        _write_properties(all_theorems)
        if verbose and n_cached:
            print(f"  property cache: all {n_cached} macro(s) served from cache — Lean skipped")
        return registry

    if verbose and n_cached:
        print(f"  property cache: {n_cached} cached, {len(uncached)} new macro(s) need Lean")

    # Already-accepted theorems from cached macros (needed in Properties.lean baseline)
    accepted_baseline: list[tuple[str, str]] = [
        (p.theorem_name, p.statement)
        for name in cached_props
        for p in macro_candidates.get(name, [])
        if p.name in set(cached_props.get(name, []))
    ]

    # Fast path: all uncached macros in one build.
    uncached_theorems = [
        (p.theorem_name, p.statement)
        for name in uncached
        for p in macro_candidates[name]
    ]
    _write_properties(accepted_baseline + uncached_theorems)
    fast = lake_build()

    def _cache_put(name: str, ok_names: list[str]) -> None:
        tt = macro_tt.get(name, "")
        prop_cache.put(f"{name}|{tt}|{toolchain}", {"properties": ok_names})

    if fast.ok:
        for name in uncached:
            props = macro_candidates[name]
            ok_names = [p.name for p in props]
            registry[name]["properties"] = ok_names
            _cache_put(name, ok_names)
            if verbose and ok_names:
                print(f"  ✦ {name}: {', '.join(ok_names)}")
        return registry

    # Slow path: per-macro isolation for uncached macros.
    if verbose:
        print("  ! fast-path Properties.lean build failed — falling back to per-macro isolation")

    accepted: list[tuple[str, str]] = list(accepted_baseline)
    for name in uncached:
        props = macro_candidates[name]
        if not props:
            registry[name]["properties"] = []
            _cache_put(name, [])
            continue

        candidate_theorems = [(p.theorem_name, p.statement) for p in props]
        _write_properties(accepted + candidate_theorems)
        result = lake_build()
        if result.ok:
            accepted.extend(candidate_theorems)
            ok_names = [p.name for p in props]
            registry[name]["properties"] = ok_names
            _cache_put(name, ok_names)
            if verbose:
                print(f"  ✦ {name}: {', '.join(ok_names)}")
        else:
            registry[name]["properties"] = []
            _cache_put(name, [])
            if verbose:
                print(
                    f"  ! {name}: all properties rejected by Lean "
                    f"(Python predicate disagreement — marking failed_properties)"
                )
            registry[name]["failed_properties"] = [p.name for p in props]

    # Write the final accepted set.
    _write_properties(accepted)
    return registry
