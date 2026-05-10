"""JSON AST -> Lean source translator."""

from __future__ import annotations

from typing import Callable

from .ast import And, Circuit, Const, Mac, Not, Or, Var, Xor


def ast_to_lean(c: Circuit) -> str:
    """Render a Circuit AST as a Lean expression of type `LeanDream.Circuit`."""
    return _render(c, lambda i: f"(.var {i})")


def _render(c: Circuit, var_renderer: Callable[[int], str]) -> str:
    if isinstance(c, Var):
        return var_renderer(c.index)
    if isinstance(c, Const):
        return f"(.const {'true' if c.value else 'false'})"
    if isinstance(c, Not):
        return f"(.not {_render(c.arg, var_renderer)})"
    if isinstance(c, And):
        return f"(.and {_render(c.left, var_renderer)} {_render(c.right, var_renderer)})"
    if isinstance(c, Or):
        return f"(.or {_render(c.left, var_renderer)} {_render(c.right, var_renderer)})"
    if isinstance(c, Xor):
        return f"(.xor {_render(c.left, var_renderer)} {_render(c.right, var_renderer)})"
    if isinstance(c, Mac):
        if not c.args:
            return f"LeanDream.Macros.{c.name}"
        rendered_args = " ".join(f"({_render(a, var_renderer)})" for a in c.args)
        return f"(LeanDream.Macros.{c.name} {rendered_args})"
    raise TypeError(f"unknown node: {c!r}")


def macro_body_to_lean(body: Circuit, arity: int) -> str:
    """Render a parameterized macro body using `x0`, `x1`, ... for parameters.

    Free vars 0..arity-1 are treated as parameter slots; vars >= arity are
    kept as `(.var n)` (shouldn't occur in well-formed mined macros).
    """
    def render_var(i: int) -> str:
        return f"x{i}" if i < arity else f"(.var {i})"
    return _render(body, render_var)


CANDIDATE_TEMPLATE = """\
import LeanDream.DSL
import LeanDream.Specs
import LeanDream.Macros

namespace LeanDream.Candidate
open LeanDream

def arity : Nat := {arity}
def candidate : Circuit := {body}
def targetSpec : Circuit := {lean_spec}

end LeanDream.Candidate
"""


def candidate_lean_source(c: Circuit, arity: int, lean_spec: str) -> str:
    """Produce the full text of `LeanDream/Candidate.lean` for one verification run.

    `lean_spec` is a Lean term (e.g. "Specs.full_adder_sum") that names the
    reference circuit the candidate must be truth-table equivalent to.
    """
    return CANDIDATE_TEMPLATE.format(
        arity=arity,
        body=ast_to_lean(c),
        lean_spec=lean_spec,
    )


def macro_lean_def(name: str, body: Circuit, arity: int) -> str:
    """Render a parameterized `def <name> (x0 ... : Circuit) : Circuit := <body>`.

    For arity 0 emits a constant: `def <name> : Circuit := <body>`.
    """
    body_lean = macro_body_to_lean(body, arity)
    if arity == 0:
        return f"def {name} : Circuit := {body_lean}"
    params = " ".join(f"x{i}" for i in range(arity))
    return f"def {name} ({params} : Circuit) : Circuit := {body_lean}"


