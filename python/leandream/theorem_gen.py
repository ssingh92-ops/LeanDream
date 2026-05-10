"""Generate and verify Lean theorem attempts for stable macros.

For each stable macro in the registry this module:
  1. Enumerates candidate properties (comm, idem, annihilator, identity,
     inv_inv) appropriate to the macro's arity.
  2. Writes a full Lean theorem declaration to a scratch file
     (lean/LeanDream/TheoremGen.lean) and attempts to build it with
     ``lake build LeanDream.TheoremGen``.
  3. Records each attempt as proved or failed and returns the list.

Usage (CLI)::

    leandream-theorem-gen [--run <run_id>] [--registry <path>]
                          [--min-support <n>]

The lean_dir is REPO_ROOT / "lean" (where lakefile.toml lives).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .verify import REPO_ROOT

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

LEAN_DIR: Path = REPO_ROOT / "lean"
THEOREM_GEN_LEAN: Path = LEAN_DIR / "LeanDream" / "TheoremGen.lean"
MACROS_REGISTRY: Path = REPO_ROOT / "macros" / "registry.json"

_THEOREM_GEN_HEADER = """\
import LeanDream.DSL
import LeanDream.Macros
namespace LeanDream.TheoremGen
open LeanDream
-- Generated theorems below
"""

# Build timeout for a single theorem attempt (seconds).
_BUILD_TIMEOUT = 60

# ---------------------------------------------------------------------------
# 1. list_stable_macros
# ---------------------------------------------------------------------------


def list_stable_macros(registry: dict[str, Any], min_support: int = 2) -> list[str]:
    """Return macro names with support >= *min_support*, de-duplicated by tt_key.

    Macros that share the same truth-table key are semantically identical;
    only the first one encountered (by name sort order) is kept so we do not
    generate duplicate theorems.

    Args:
        registry:    The parsed registry dict (macro_name -> entry).
        min_support: Minimum number of proof records a macro must appear in.

    Returns:
        Sorted list of qualifying macro names.
    """
    seen_tt_keys: set[str] = set()
    stable: list[str] = []

    for name in sorted(registry.keys()):
        entry = registry[name]
        support = entry.get("support", 0)
        if support < min_support:
            continue
        tt_key = entry.get("tt_key", "")
        if tt_key and tt_key in seen_tt_keys:
            continue  # duplicate semantics — skip
        if tt_key:
            seen_tt_keys.add(tt_key)
        stable.append(name)

    return stable


# ---------------------------------------------------------------------------
# 2. _property_theorems
# ---------------------------------------------------------------------------

# Lean namespace prefix used when referencing macros inside theorems.
_MACRO_NS = "Macros"


def _property_theorems(
    macro_name: str,
    arity: int,
    macro_lean_name: str,
) -> list[dict[str, str]]:
    """Return candidate theorems for a macro.

    Each entry is::

        {"property": <short_name>, "lean_code": <full_lean_theorem_text>}

    The ``lean_code`` is a complete, self-contained Lean theorem declaration
    that can be appended to TheoremGen.lean.

    Args:
        macro_name:      Python-side name, e.g. ``"macro_1"``.
        arity:           Number of Circuit arguments the macro takes.
        macro_lean_name: Lean-side qualified name, e.g. ``"Macros.macro_1"``.
    """
    theorems: list[dict[str, str]] = []

    def _thm(prop: str, lean_code: str) -> dict[str, str]:
        return {"property": prop, "lean_code": lean_code}

    # Simp hints are always the macro definition plus Circuit.eval.
    _simp_base = f"[{macro_lean_name}, Circuit.eval]"
    _simp_ext = (
        f"{_simp_base}\n"
        "  <;> cases x0.eval env <;> cases x1.eval env <;> rfl"
    )

    if arity == 1:
        # inv_inv: apply the macro twice and get back the original.
        thm_name = f"{macro_name}_inv_inv"
        lean_code = (
            f"theorem {thm_name} (x0 : Circuit) :\n"
            f"    ∀ env : Nat → Bool,\n"
            f"      ({macro_lean_name} ({macro_lean_name} x0)).eval env = x0.eval env := by\n"
            f"  intro env; simp {_simp_base}"
        )
        theorems.append(_thm("inv_inv", lean_code))

    elif arity == 2:
        call = f"({macro_lean_name} x0 x1)"
        call_swap = f"({macro_lean_name} x1 x0)"
        call_idem = f"({macro_lean_name} x0 x0)"

        # -- comm --
        thm_name = f"{macro_name}_comm"
        lean_code = (
            f"theorem {thm_name} (x0 x1 : Circuit) :\n"
            f"    ∀ env : Nat → Bool,\n"
            f"      {call}.eval env = {call_swap}.eval env := by\n"
            f"  intro env; simp {_simp_base}"
        )
        # Fallback variant using case-split, appended separately if simp fails.
        lean_code_fallback = (
            f"theorem {thm_name} (x0 x1 : Circuit) :\n"
            f"    ∀ env : Nat → Bool,\n"
            f"      {call}.eval env = {call_swap}.eval env := by\n"
            f"  intro env; simp {_simp_ext}"
        )
        theorems.append(_thm("comm", lean_code))
        theorems.append(_thm("comm_cases", lean_code_fallback))

        # -- idem --
        thm_name = f"{macro_name}_idem"
        lean_code = (
            f"theorem {thm_name} (x0 : Circuit) :\n"
            f"    ∀ env : Nat → Bool,\n"
            f"      {call_idem}.eval env = x0.eval env := by\n"
            f"  intro env; simp {_simp_base}"
        )
        theorems.append(_thm("idem", lean_code))

        # -- ann_false_left: macro(false, x0) = false --
        thm_name = f"{macro_name}_ann_false_left"
        lean_code = (
            f"theorem {thm_name} (x0 : Circuit) :\n"
            f"    ∀ env : Nat → Bool,\n"
            f"      ({macro_lean_name} (.const false) x0).eval env = false := by\n"
            f"  intro env; simp {_simp_base}"
        )
        theorems.append(_thm("ann_false_left", lean_code))

        # -- ann_true_left: macro(true, x0) = true --
        thm_name = f"{macro_name}_ann_true_left"
        lean_code = (
            f"theorem {thm_name} (x0 : Circuit) :\n"
            f"    ∀ env : Nat → Bool,\n"
            f"      ({macro_lean_name} (.const true) x0).eval env = true := by\n"
            f"  intro env; simp {_simp_base}"
        )
        theorems.append(_thm("ann_true_left", lean_code))

        # -- ann_false_right: macro(x0, false) = false --
        thm_name = f"{macro_name}_ann_false_right"
        lean_code = (
            f"theorem {thm_name} (x0 : Circuit) :\n"
            f"    ∀ env : Nat → Bool,\n"
            f"      ({macro_lean_name} x0 (.const false)).eval env = false := by\n"
            f"  intro env; simp {_simp_base}"
        )
        theorems.append(_thm("ann_false_right", lean_code))

        # -- ann_true_right: macro(x0, true) = true --
        thm_name = f"{macro_name}_ann_true_right"
        lean_code = (
            f"theorem {thm_name} (x0 : Circuit) :\n"
            f"    ∀ env : Nat → Bool,\n"
            f"      ({macro_lean_name} x0 (.const true)).eval env = true := by\n"
            f"  intro env; simp {_simp_base}"
        )
        theorems.append(_thm("ann_true_right", lean_code))

        # -- id_false_left: macro(false, x0) = x0 --
        thm_name = f"{macro_name}_id_false_left"
        lean_code = (
            f"theorem {thm_name} (x0 : Circuit) :\n"
            f"    ∀ env : Nat → Bool,\n"
            f"      ({macro_lean_name} (.const false) x0).eval env = x0.eval env := by\n"
            f"  intro env; simp {_simp_base}"
        )
        theorems.append(_thm("id_false_left", lean_code))

        # -- id_true_left: macro(true, x0) = x0 --
        thm_name = f"{macro_name}_id_true_left"
        lean_code = (
            f"theorem {thm_name} (x0 : Circuit) :\n"
            f"    ∀ env : Nat → Bool,\n"
            f"      ({macro_lean_name} (.const true) x0).eval env = x0.eval env := by\n"
            f"  intro env; simp {_simp_base}"
        )
        theorems.append(_thm("id_true_left", lean_code))

        # -- id_false_right: macro(x0, false) = x0 --
        thm_name = f"{macro_name}_id_false_right"
        lean_code = (
            f"theorem {thm_name} (x0 : Circuit) :\n"
            f"    ∀ env : Nat → Bool,\n"
            f"      ({macro_lean_name} x0 (.const false)).eval env = x0.eval env := by\n"
            f"  intro env; simp {_simp_base}"
        )
        theorems.append(_thm("id_false_right", lean_code))

        # -- id_true_right: macro(x0, true) = x0 --
        thm_name = f"{macro_name}_id_true_right"
        lean_code = (
            f"theorem {thm_name} (x0 : Circuit) :\n"
            f"    ∀ env : Nat → Bool,\n"
            f"      ({macro_lean_name} x0 (.const true)).eval env = x0.eval env := by\n"
            f"  intro env; simp {_simp_base}"
        )
        theorems.append(_thm("id_true_right", lean_code))

    # Arity >= 3: no generic patterns to attempt; skip.

    return theorems


# ---------------------------------------------------------------------------
# 3. _write_and_build_theorem
# ---------------------------------------------------------------------------


def _write_and_build_theorem(
    lean_dir: Path,
    theorem_code: str,
    theorem_name: str,
) -> bool:
    """Append *theorem_code* to TheoremGen.lean, run ``lake build``, return success.

    On failure the appended block is removed so the file stays in a clean state
    for the next attempt.

    Args:
        lean_dir:      Directory containing lakefile.toml (LEAN_DIR).
        theorem_code:  Full Lean theorem text (no trailing newline needed).
        theorem_name:  Human-readable identifier used in log messages.

    Returns:
        True if ``lake build LeanDream.TheoremGen`` exits 0, False otherwise.
    """
    target_file = lean_dir / "LeanDream" / "TheoremGen.lean"

    # Read current contents so we can restore on failure.
    original_text = target_file.read_text(encoding="utf-8")

    # Append the new theorem block.
    separator = f"\n-- theorem: {theorem_name}\n"
    new_text = original_text + separator + theorem_code + "\n"
    target_file.write_text(new_text, encoding="utf-8")

    try:
        result = subprocess.run(
            ["lake", "build", "LeanDream.TheoremGen"],
            cwd=lean_dir,
            capture_output=True,
            text=True,
            timeout=_BUILD_TIMEOUT,
        )
        if result.returncode == 0:
            return True
        # Build failed — restore original file.
        target_file.write_text(original_text, encoding="utf-8")
        return False
    except subprocess.TimeoutExpired:
        target_file.write_text(original_text, encoding="utf-8")
        return False
    except FileNotFoundError:
        # `lake` not on PATH — restore and propagate via return value.
        target_file.write_text(original_text, encoding="utf-8")
        return False


# ---------------------------------------------------------------------------
# 4. generate_theorems_for_registry
# ---------------------------------------------------------------------------


def generate_theorems_for_registry(
    registry: dict[str, Any],
    lean_dir: Path | None = None,
    run_dir: Path | None = None,
    min_support: int = 2,
) -> list[dict[str, Any]]:
    """Try to prove properties for every stable macro in *registry*.

    Creates (or resets) ``lean/LeanDream/TheoremGen.lean`` with the standard
    header, then for each stable macro attempts every candidate property
    theorem.  Results are returned as a list and optionally written to
    ``<run_dir>/theorem_gen_results.json``.

    Args:
        registry:    Parsed registry dict.
        lean_dir:    Override for the Lean project root (default: LEAN_DIR).
        run_dir:     If given, results JSON is written here.
        min_support: Passed through to :func:`list_stable_macros`.

    Returns:
        List of dicts::

            {
                "macro":      macro_name,
                "property":   property_short_name,
                "status":     "proved" | "failed" | "skipped",
                "lean_name":  full theorem identifier,
            }
    """
    if lean_dir is None:
        lean_dir = LEAN_DIR

    # Verify that lake is reachable before doing any work.
    if shutil.which("lake") is None:
        print(
            "[theorem_gen] WARNING: `lake` not found on PATH. "
            "Returning empty results.",
            file=sys.stderr,
        )
        return []

    # Ensure the TheoremGen.lean scratch file exists with the right header.
    theorem_gen_path = lean_dir / "LeanDream" / "TheoremGen.lean"
    theorem_gen_path.write_text(_THEOREM_GEN_HEADER, encoding="utf-8")

    stable_macros = list_stable_macros(registry, min_support=min_support)
    results: list[dict[str, Any]] = []

    for macro_name in stable_macros:
        entry = registry[macro_name]
        arity: int = entry.get("arity", 0)

        # Lean-qualified name for use inside theorem statements.
        macro_lean_name = f"Macros.{macro_name}"

        candidates = _property_theorems(macro_name, arity, macro_lean_name)
        if not candidates:
            # Arity >= 3 or unknown — nothing to attempt.
            continue

        for candidate in candidates:
            prop = candidate["property"]
            lean_code = candidate["lean_code"]

            # Derive the Lean theorem name from the first line of lean_code.
            # Pattern: "theorem <name> ..."
            first_line = lean_code.strip().splitlines()[0]
            parts = first_line.split()
            lean_thm_name = parts[1] if len(parts) >= 2 else f"{macro_name}_{prop}"

            success = _write_and_build_theorem(lean_dir, lean_code, lean_thm_name)

            status = "proved" if success else "failed"
            record: dict[str, Any] = {
                "macro": macro_name,
                "property": prop,
                "status": status,
                "lean_name": lean_thm_name,
            }
            results.append(record)

    # Optionally persist results.
    if run_dir is not None:
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        out_path = run_dir / "theorem_gen_results.json"
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    return results


# ---------------------------------------------------------------------------
# 5. main() — CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI: ``leandream-theorem-gen [--run <run_id>] [--registry <path>]``."""
    parser = argparse.ArgumentParser(
        prog="leandream-theorem-gen",
        description="Generate and verify Lean theorems for stable macros.",
    )
    parser.add_argument(
        "--run",
        metavar="RUN_ID",
        default=None,
        help="Run directory name (under REPO_ROOT/runs/) to write results into.",
    )
    parser.add_argument(
        "--registry",
        metavar="PATH",
        default=None,
        help="Path to registry.json (default: macros/registry.json).",
    )
    parser.add_argument(
        "--min-support",
        metavar="N",
        type=int,
        default=2,
        help="Minimum support count to consider a macro stable (default: 2).",
    )
    args = parser.parse_args()

    # Resolve registry path.
    registry_path = Path(args.registry) if args.registry else MACROS_REGISTRY
    if not registry_path.exists():
        print(
            f"[theorem_gen] ERROR: registry not found at {registry_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    registry: dict[str, Any] = json.loads(registry_path.read_text(encoding="utf-8"))

    # Resolve optional run directory.
    run_dir: Path | None = None
    if args.run:
        run_dir = REPO_ROOT / "runs" / args.run

    t0 = time.monotonic()
    results = generate_theorems_for_registry(
        registry,
        lean_dir=LEAN_DIR,
        run_dir=run_dir,
        min_support=args.min_support,
    )
    elapsed = time.monotonic() - t0

    # Summarise.
    proved = [r for r in results if r["status"] == "proved"]
    failed = [r for r in results if r["status"] == "failed"]

    macros_with_new_theorems: set[str] = {r["macro"] for r in proved}

    print(f"\n=== theorem_gen summary ({elapsed:.1f}s) ===")
    print(f"  Proved : {len(proved)}")
    print(f"  Failed : {len(failed)}")
    if macros_with_new_theorems:
        print(
            "  Macros with new theorems: "
            + ", ".join(sorted(macros_with_new_theorems))
        )
    else:
        print("  No new theorems proved.")

    if run_dir:
        print(f"  Results written to: {run_dir / 'theorem_gen_results.json'}")
