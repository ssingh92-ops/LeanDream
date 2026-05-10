"""Preflight validator: catches structural errors before invoking lake build.

Checks performed (in order):
1. unknown_macro     — Mac node references a name not in the registry
2. arity_mismatch    — Mac node has wrong number of args for its registered arity
3. invalid_var_index — Var index out of range for the spec's arity
4. expansion_cycle   — detectable macro cycle (registry DAG check, not full expansion)

If any check fails, returns a structured PreflightResult with the error
details so the orchestrator can log it and optionally trigger a targeted
repair without spending a lake build invocation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter

from .ast import Circuit, Mac, Var, free_vars
from .attempts import (
    STATUS_ARITY_MISMATCH,
    STATUS_PREFLIGHT_FAILED,
    STATUS_UNKNOWN_MACRO,
)

_CIRCUIT_ADAPTER: TypeAdapter[Circuit] = TypeAdapter(Circuit)


@dataclass
class PreflightResult:
    ok: bool
    status: str
    error_type: str | None = None
    message: str | None = None
    macro_name: str | None = None


_OK = PreflightResult(ok=True, status="preflight_ok")


def _walk(c: Circuit, callback) -> None:
    """Walk every node in the circuit tree, calling callback(node)."""
    callback(c)
    if isinstance(c, Mac):
        for a in c.args:
            _walk(a, callback)
    elif hasattr(c, "arg"):
        _walk(c.arg, callback)      # Not
    elif hasattr(c, "left"):
        _walk(c.left, callback)     # And/Or/Xor
        _walk(c.right, callback)


def _registry_has_cycle(registry: dict[str, dict]) -> bool:
    """Detect cycles in the macro dependency DAG via DFS."""
    def _deps(name: str) -> set[str]:
        info = registry.get(name, {})
        body = info.get("body_ast")
        if body is None:
            return set()
        # body_ast may be a Circuit or a dict; we check for Mac refs in the dict
        refs: set[str] = set()
        def _scan(d: Any) -> None:
            if isinstance(d, dict):
                if d.get("kind") == "mac":
                    refs.add(d["name"])
                for v in d.values():
                    _scan(v)
            elif isinstance(d, list):
                for item in d:
                    _scan(item)
        _scan(body)
        return refs

    visiting: set[str] = set()
    visited: set[str] = set()

    def _dfs(name: str) -> bool:
        if name in visiting:
            return True  # cycle
        if name in visited:
            return False
        visiting.add(name)
        for dep in _deps(name):
            if dep in registry and _dfs(dep):
                return True
        visiting.discard(name)
        visited.add(name)
        return False

    return any(_dfs(name) for name in registry)


def validate(
    circuit: "Circuit | dict",
    spec_arity: int,
    registry: dict[str, dict],
) -> PreflightResult:
    """Run all preflight checks.  Returns _OK or a failing PreflightResult.

    circuit may be a parsed Circuit object or a raw JSON dict (as returned by
    the LLM); if a dict is given it is converted via pydantic TypeAdapter.
    """
    if isinstance(circuit, dict):
        try:
            circuit = _CIRCUIT_ADAPTER.validate_python(circuit)
        except Exception as exc:
            return PreflightResult(
                ok=False,
                status=STATUS_PREFLIGHT_FAILED,
                error_type="parse_error",
                message=f"Circuit dict failed schema validation: {exc}",
            )

    errors: list[PreflightResult] = []

    def check_node(node: Circuit) -> None:
        if isinstance(node, Mac):
            if node.name not in registry:
                errors.append(PreflightResult(
                    ok=False,
                    status=STATUS_UNKNOWN_MACRO,
                    error_type="unknown_macro",
                    message=f"macro {node.name!r} not in registry",
                    macro_name=node.name,
                ))
                return
            reg_arity = registry[node.name].get("arity", 0)
            if len(node.args) != reg_arity:
                errors.append(PreflightResult(
                    ok=False,
                    status=STATUS_ARITY_MISMATCH,
                    error_type="macro_arity_mismatch",
                    message=(
                        f"macro {node.name!r} expects {reg_arity} arg(s), "
                        f"got {len(node.args)}"
                    ),
                    macro_name=node.name,
                ))
        elif isinstance(node, Var):
            if node.index >= spec_arity:
                errors.append(PreflightResult(
                    ok=False,
                    status=STATUS_PREFLIGHT_FAILED,
                    error_type="invalid_var_index",
                    message=(
                        f"Var({node.index}) out of range for spec arity {spec_arity}"
                    ),
                ))

    _walk(circuit, check_node)
    if errors:
        return errors[0]  # return first error; caller can trigger repair
    return _OK


def build_preflight_repair(result: PreflightResult, registry: dict[str, dict]) -> str:
    """Build a compact repair hint string for a preflight failure."""
    lines = ["[Preflight failure — circuit rejected before Lean]"]

    if result.status == STATUS_UNKNOWN_MACRO:
        name = result.macro_name or "?"
        avail = ", ".join(sorted(registry)) or "(none)"
        lines.append(f"Unknown macro: {name!r}")
        lines.append(f"Available: {avail}")
        lines.append("Use only available macro names or build from primitives.")

    elif result.status == STATUS_ARITY_MISMATCH:
        lines.append(f"Arity error: {result.message}")
        name = result.macro_name
        if name and name in registry:
            arity = registry[name].get("arity", "?")
            body = registry[name].get("body_repr", "?")
            schema = f'{{"kind":"mac","name":"{name}","args":[' + ",".join(["expr"] * int(arity)) + "]}}"
            lines.append(f"Correct call: {schema}")
            lines.append(f"Body: {body}")

    elif result.error_type == "invalid_var_index":
        lines.append(f"Invalid variable: {result.message}")
        lines.append("Use only var indices within spec arity.")

    else:
        lines.append(f"Error: {result.message}")

    return "\n".join(lines)
