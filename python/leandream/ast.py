"""AST types for the LeanDream circuit DSL.

The JSON shape produced by the LLM and stored in the proof forest is exactly
what these Pydantic models serialize. Each node has a `kind` discriminator;
`Mac` references a macro by name (resolved against `macros/registry.json`).
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class ArityError(Exception):
    """Raised when a macro is called with the wrong number of arguments."""


class ExpansionCycleError(Exception):
    """Raised when macro expansion detects a cycle."""


class ExpansionDepthError(Exception):
    """Raised when macro expansion exceeds the maximum depth."""


MAX_EXPANSION_DEPTH = 64


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # OpenAI structured outputs require every property to appear in `required`,
    # but Pydantic excludes fields that have defaults. Force-include them so
    # the generated JSON schema is accepted by `responses.parse`.
    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        if "properties" in schema:
            schema["required"] = list(schema["properties"].keys())
        return schema


class Var(_Node):
    kind: Literal["var"] = "var"
    index: int = Field(ge=0, description="Zero-based input index.")


class Const(_Node):
    kind: Literal["const"] = "const"
    value: bool


class Not(_Node):
    kind: Literal["not"] = "not"
    arg: "Circuit"


class And(_Node):
    kind: Literal["and"] = "and"
    left: "Circuit"
    right: "Circuit"


class Or(_Node):
    kind: Literal["or"] = "or"
    left: "Circuit"
    right: "Circuit"


class Xor(_Node):
    kind: Literal["xor"] = "xor"
    left: "Circuit"
    right: "Circuit"


class Mac(_Node):
    kind: Literal["mac"] = "mac"
    name: str = Field(description="Name of an installed macro (e.g. 'macro_3').")
    args: list["Circuit"] = Field(
        default_factory=list,
        description=(
            "Sub-circuit arguments for the parameterized macro. Length must "
            "equal the macro's arity. For arity 0 (constant macros) pass []."
        ),
    )


# Plain Union (not Field-discriminated) so Pydantic emits `anyOf` rather than
# `oneOf` in the JSON schema. OpenAI's structured-outputs API accepts `anyOf`
# but rejects `oneOf`. Pydantic still routes incoming JSON to the right variant
# via the `Literal` `kind` field on each model.
Circuit = Union[Var, Const, Not, And, Or, Xor, Mac]

Not.model_rebuild()
And.model_rebuild()
Or.model_rebuild()
Xor.model_rebuild()
Mac.model_rebuild()


def size(c: Circuit) -> int:
    """Number of AST nodes."""
    if isinstance(c, (Var, Const)):
        return 1
    if isinstance(c, Mac):
        return 1 + sum(size(a) for a in c.args)
    if isinstance(c, Not):
        return 1 + size(c.arg)
    if isinstance(c, (And, Or, Xor)):
        return 1 + size(c.left) + size(c.right)
    raise TypeError(f"unknown node: {c!r}")


def free_vars(c: Circuit) -> set[int]:
    if isinstance(c, Var):
        return {c.index}
    if isinstance(c, Const):
        return set()
    if isinstance(c, Mac):
        out: set[int] = set()
        for a in c.args:
            out |= free_vars(a)
        return out
    if isinstance(c, Not):
        return free_vars(c.arg)
    if isinstance(c, (And, Or, Xor)):
        return free_vars(c.left) | free_vars(c.right)
    raise TypeError(f"unknown node: {c!r}")


def substitute(body: Circuit, args: list[Circuit]) -> Circuit:
    """Substitute parameter slots in `body` with concrete `args`.

    A macro body uses `Var(i)` to mean parameter slot i. `substitute` walks the
    body and replaces every `Var(i)` with `args[i]`. Raises `ArityError` if a
    `Var(i)` index is out of range for the supplied args list.
    """
    def rec(node: Circuit) -> Circuit:
        if isinstance(node, Var):
            if node.index >= len(args):
                raise ArityError(
                    f"Var({node.index}) is out of range: macro body expected "
                    f"{len(args)} argument(s)"
                )
            return args[node.index]
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
    return rec(body)


def expand_macros(
    c: Circuit,
    registry: dict[str, Circuit],
    _stack: tuple[str, ...] = (),
) -> Circuit:
    """Replace every `Mac` reference with its registered body, with args
    substituted into parameter slots, recursively. Args themselves are
    expanded first so nested macros are fully resolved.

    Raises:
        KeyError: unknown macro name.
        ArityError: wrong number of arguments for a macro.
        ExpansionCycleError: macro expansion forms a cycle.
        ExpansionDepthError: expansion stack exceeds MAX_EXPANSION_DEPTH.
    """
    if isinstance(c, Mac):
        if c.name not in registry:
            raise KeyError(f"macro not in registry: {c.name!r}")
        if c.name in _stack:
            cycle = " -> ".join(_stack) + f" -> {c.name}"
            raise ExpansionCycleError(f"macro expansion cycle detected: {cycle}")
        if len(_stack) >= MAX_EXPANSION_DEPTH:
            raise ExpansionDepthError(
                f"macro expansion depth limit ({MAX_EXPANSION_DEPTH}) exceeded "
                f"at {c.name!r}"
            )
        body = registry[c.name]
        expected_arity = len(free_vars(body))
        if len(c.args) != expected_arity:
            raise ArityError(
                f"macro {c.name!r} expects {expected_arity} arg(s), "
                f"got {len(c.args)}"
            )
        new_stack = _stack + (c.name,)
        # Expand args in the *caller's* scope (_stack), not new_stack.
        # new_stack only guards the body — args are caller-context expressions
        # and a same-name arg (e.g. f(f(x))) is nested application, not a cycle.
        expanded_args = [expand_macros(a, registry, _stack) for a in c.args]
        substituted = substitute(body, expanded_args)
        return expand_macros(substituted, registry, new_stack)
    if isinstance(c, (Var, Const)):
        return c
    if isinstance(c, Not):
        return Not(arg=expand_macros(c.arg, registry, _stack))
    if isinstance(c, And):
        return And(
            left=expand_macros(c.left, registry, _stack),
            right=expand_macros(c.right, registry, _stack),
        )
    if isinstance(c, Or):
        return Or(
            left=expand_macros(c.left, registry, _stack),
            right=expand_macros(c.right, registry, _stack),
        )
    if isinstance(c, Xor):
        return Xor(
            left=expand_macros(c.left, registry, _stack),
            right=expand_macros(c.right, registry, _stack),
        )
    raise TypeError(f"unknown node: {c!r}")


def evaluate(c: Circuit, env: list[bool], registry: dict[str, Circuit] | None = None) -> bool:
    """Truth-table evaluation. Mirrors `Circuit.eval` in DSL.lean.
    For Mac nodes, expands the body with substituted args, then evaluates."""
    if isinstance(c, Var):
        return env[c.index] if c.index < len(env) else False
    if isinstance(c, Const):
        return c.value
    if isinstance(c, Mac):
        if registry is None or c.name not in registry:
            raise KeyError(f"macro not resolvable: {c.name!r}")
        body = registry[c.name]
        expected_arity = len(free_vars(body))
        if len(c.args) != expected_arity:
            raise ArityError(
                f"macro {c.name!r} expects {expected_arity} arg(s), "
                f"got {len(c.args)}"
            )
        substituted = substitute(body, c.args)
        return evaluate(substituted, env, registry)
    if isinstance(c, Not):
        return not evaluate(c.arg, env, registry)
    if isinstance(c, And):
        return evaluate(c.left, env, registry) and evaluate(c.right, env, registry)
    if isinstance(c, Or):
        return evaluate(c.left, env, registry) or evaluate(c.right, env, registry)
    if isinstance(c, Xor):
        return evaluate(c.left, env, registry) != evaluate(c.right, env, registry)
    raise TypeError(f"unknown node: {c!r}")
