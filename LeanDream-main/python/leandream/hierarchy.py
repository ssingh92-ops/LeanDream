"""Macro dependency graph and level computation for the installed macro registry.

macro_level(m) = 0 if m references no other macros in the registry.
macro_level(m) = 1 + max(macro_level(dep) for dep in direct_deps(m)) otherwise.

The installer guarantees a DAG (each macro only references already-installed
macros), so there are no cycles and levels are well-defined.
"""
from __future__ import annotations

from pydantic import TypeAdapter

from .ast import And, Circuit, Mac, Not, Or, Xor

_ADAPTER: TypeAdapter[Circuit] = TypeAdapter(Circuit)


def _mac_refs_in(c: Circuit) -> set[str]:
    """Return all macro names directly referenced in c (without expanding them)."""
    if isinstance(c, Mac):
        result = {c.name}
        for arg in c.args:
            result |= _mac_refs_in(arg)
        return result
    if isinstance(c, Not):
        return _mac_refs_in(c.arg)
    if isinstance(c, (And, Or, Xor)):
        return _mac_refs_in(c.left) | _mac_refs_in(c.right)
    return set()


def macro_deps(registry: dict[str, dict]) -> dict[str, set[str]]:
    """Return {macro_name: set_of_macro_names_it_directly_references}."""
    known = set(registry)
    deps: dict[str, set[str]] = {}
    for name, info in registry.items():
        ast = _ADAPTER.validate_python(info["ast"])
        deps[name] = _mac_refs_in(ast) & known
    return deps


def compute_macro_level(registry: dict[str, dict]) -> dict[str, int]:
    """Return {macro_name: macro_level} computed by topological recursion."""
    deps = macro_deps(registry)
    levels: dict[str, int] = {}

    def _level(name: str, seen: frozenset[str] = frozenset()) -> int:
        if name in levels:
            return levels[name]
        if name in seen:
            return 0  # cycle guard (should not happen with a valid registry)
        d = deps.get(name, set())
        lvl = (1 + max(_level(dep, seen | {name}) for dep in d)) if d else 0
        levels[name] = lvl
        return lvl

    for name in registry:
        _level(name)
    return levels


def build_dep_graph(registry: dict[str, dict]) -> dict[str, list[str]]:
    """Return adjacency list {name: [sorted deps]} for display or export."""
    deps = macro_deps(registry)
    return {name: sorted(deps.get(name, set())) for name in registry}
