"""Tests for the JSON -> Lean translator."""

from leandream.ast import And, Const, Mac, Not, Or, Var, Xor
from leandream.translate import ast_to_lean, candidate_lean_source


def test_var():
    assert ast_to_lean(Var(index=3)) == "(.var 3)"


def test_const():
    assert ast_to_lean(Const(value=True)) == "(.const true)"
    assert ast_to_lean(Const(value=False)) == "(.const false)"


def test_not():
    assert ast_to_lean(Not(arg=Var(index=0))) == "(.not (.var 0))"


def test_binops():
    a, b = Var(index=0), Var(index=1)
    assert ast_to_lean(And(left=a, right=b)) == "(.and (.var 0) (.var 1))"
    assert ast_to_lean(Or(left=a, right=b)) == "(.or (.var 0) (.var 1))"
    assert ast_to_lean(Xor(left=a, right=b)) == "(.xor (.var 0) (.var 1))"


def test_macro_ref():
    assert ast_to_lean(Mac(name="macro_3")) == "LeanDream.Macros.macro_3"


def test_full_adder_carry_renders():
    # (a AND b) OR (cin AND (a XOR b))
    a, b, cin = Var(index=0), Var(index=1), Var(index=2)
    ast = Or(
        left=And(left=a, right=b),
        right=And(left=cin, right=Xor(left=a, right=b)),
    )
    expected = (
        "(.or (.and (.var 0) (.var 1)) "
        "(.and (.var 2) (.xor (.var 0) (.var 1))))"
    )
    assert ast_to_lean(ast) == expected


def test_candidate_template_includes_imports_and_namespace():
    src = candidate_lean_source(Var(index=0), arity=1, lean_spec="Specs.and2")
    assert "import LeanDream.DSL" in src
    assert "import LeanDream.Specs" in src
    assert "import LeanDream.Macros" in src
    assert "namespace LeanDream.Candidate" in src
    assert "def arity : Nat := 1" in src
    assert "def candidate : Circuit := (.var 0)" in src
    assert "def targetSpec : Circuit := Specs.and2" in src
