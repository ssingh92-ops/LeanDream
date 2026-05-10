"""Regenerate the formula-driven section of `lean/LeanDream/Specs.lean`.

Hand-written specs above the BEGIN GENERATED marker are preserved verbatim.
Specs below it are rewritten from the contents of `specs/*.json` whose JSON
contains a `formula` field.

This module is invoked from the orchestrator's spec-load path so the file is
always in sync with the JSON library before `lake build` runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import spec_formulas
from .translate import ast_to_lean
from .verify import REPO_ROOT

SPECS_DIR = REPO_ROOT / "specs"
SPECS_LEAN = REPO_ROOT / "lean" / "LeanDream" / "Specs.lean"

_BEGIN = "-- BEGIN GENERATED"
_END = "-- END GENERATED"


def _generate_block() -> str:
    """Build the text that lives between the BEGIN/END markers."""
    lines: list[str] = []
    if not SPECS_DIR.exists():
        return ""
    for path in sorted(SPECS_DIR.glob("*.json")):
        try:
            spec = json.loads(path.read_text())
        except Exception:
            continue
        formula_ref = spec.get("formula")
        if not formula_ref:
            continue
        name = spec["name"]
        arity = spec["arity"]
        try:
            _, builder = spec_formulas.resolve(formula_ref)
            ast = builder(arity)
        except Exception as e:
            lines.append(f"-- skipped {name}: {e}")
            continue
        body = ast_to_lean(ast)
        lines.append(f"-- {name}: arity {arity}, generated from formula '{formula_ref}'")
        lines.append(f"def {name}_arity : Nat := {arity}")
        lines.append(f"def {name} : Circuit := {body}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n" if lines else ""


def regenerate() -> Path:
    """Rewrite the GENERATED section. Idempotent — safe to call repeatedly."""
    if not SPECS_LEAN.exists():
        raise FileNotFoundError(SPECS_LEAN)
    text = SPECS_LEAN.read_text()
    if _BEGIN not in text or _END not in text:
        raise RuntimeError(
            f"{SPECS_LEAN} is missing the {_BEGIN} / {_END} markers"
        )
    pre, _, rest = text.partition(_BEGIN)
    _, _, post = rest.partition(_END)
    block = _generate_block()
    new = f"{pre}{_BEGIN}\n{block}{_END}{post}"
    SPECS_LEAN.write_text(new)
    return SPECS_LEAN


def expand_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """If `spec` has a `formula` field, fill in `truth_table` from it.

    Existing `truth_table` is preserved; the formula path only adds it when
    missing. `lean_spec` defaults to `Specs.<name>` so verify_candidate can
    find the regenerated reference circuit.
    """
    if "formula" not in spec:
        return spec
    if not spec.get("truth_table"):
        spec = dict(spec)
        spec["truth_table"] = spec_formulas.expand_truth_table(
            spec["formula"], spec["arity"]
        )
    if not spec.get("lean_spec"):
        spec = dict(spec)
        spec["lean_spec"] = f"Specs.{spec['name']}"
    if not spec.get("inputs"):
        spec = dict(spec)
        spec["inputs"] = [f"x{i}" for i in range(spec["arity"])]
    return spec
