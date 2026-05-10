"""Python truth-table quickcheck: fast semantic validation before Lean.

A quickcheck CAN fast-reject a circuit that produces wrong outputs for
some inputs.  It CANNOT certify correctness — only Lean can do that.

Circuits that pass the quickcheck still go to Lean unless a cached Lean
result already exists.  Circuits that fail never reach Lean.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ast import Circuit, ArityError, evaluate


@dataclass
class QuickcheckResult:
    passed: bool
    counterexample: dict | None = None
    checked: bool = True      # False if skipped (too large / evaluation error)
    error: str | None = None  # why check was skipped


# Maximum truth-table rows before we skip the Python check.
# 2^6 = 64 covers arities 1–6; above that we let Lean decide.
_MAX_ROWS = 64


def quickcheck(
    circuit: Circuit,
    spec: dict[str, Any],
    macro_circuits: dict[str, Circuit],
    *,
    max_rows: int = _MAX_ROWS,
) -> QuickcheckResult:
    """Evaluate *circuit* against *spec*'s truth table in pure Python.

    Args:
        circuit:       The candidate to check (unexpanded, Mac nodes allowed).
        spec:          Spec dict with ``truth_table`` list of
                       ``{"inputs": list[bool], "output": bool}`` rows.
        macro_circuits: Registry of expanded macro Circuit bodies (for Mac eval).
        max_rows:      Skip if truth table exceeds this size.

    Returns:
        ``QuickcheckResult(passed=False, counterexample=...)`` on first mismatch.
        ``QuickcheckResult(passed=True)`` if all rows match.
        ``QuickcheckResult(passed=True, checked=False)`` if check was skipped.

    Note:
        A ``passed=True`` result is NOT a proof — always follow with Lean.
    """
    tt = spec.get("truth_table", [])
    if not tt:
        return QuickcheckResult(passed=True, checked=False, error="empty truth table")
    if len(tt) > max_rows:
        return QuickcheckResult(
            passed=True, checked=False,
            error=f"truth table has {len(tt)} rows (> max_rows={max_rows}), skipped",
        )

    try:
        for row in tt:
            inputs: list[bool] = [bool(v) for v in row["inputs"]]
            expected: bool = bool(row["output"])
            actual: bool = evaluate(circuit, inputs, macro_circuits)
            if actual != expected:
                return QuickcheckResult(
                    passed=False,
                    counterexample={
                        "inputs": [int(v) for v in inputs],
                        "expected": int(expected),
                        "actual": int(actual),
                    },
                )
        return QuickcheckResult(passed=True)
    except (ArityError, KeyError) as exc:
        # Arity errors are already caught by preflight; skip quietly here.
        return QuickcheckResult(passed=True, checked=False, error=str(exc))
    except Exception as exc:
        return QuickcheckResult(passed=True, checked=False, error=str(exc))
