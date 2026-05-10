"""Bootstrap: ensure runtime state is valid for a fresh clone, fresh unzip, or after reset.

Run before the first real or mock run to guarantee:
  - All Lean generated placeholders exist and are syntactically valid.
  - All runtime directories exist with correct permissions.
  - The macro registry exists (empty if never populated).
  - Properties.lean and Macros.lean are present.
  - `lake build` can succeed from a clean state.

Usage:
    python -m leandream.bootstrap
    python -m leandream.bootstrap --reset    # wipe generated state first
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEAN_DIR = REPO_ROOT / "lean"
LEAN_DREAM_DIR = LEAN_DIR / "LeanDream"

_CANDIDATE_SOURCE = """\
import LeanDream.DSL
import LeanDream.Specs
import LeanDream.Macros

namespace LeanDream.Candidate
open LeanDream

-- Trivial placeholder so `lake build` succeeds when no candidate is staged.

def arity : Nat := 2
def candidate : Circuit := .and (.var 0) (.var 1)
def targetSpec : Circuit := Specs.and2

end LeanDream.Candidate
"""

_EMPTY_MACROS = """\
import LeanDream.DSL

namespace LeanDream.Macros
open LeanDream

-- Mined macros are appended below this line by the installer.
-- BEGIN MACROS

-- END MACROS

end LeanDream.Macros
"""

_EMPTY_PROPERTIES = """\
import LeanDream.DSL
import LeanDream.Macros

namespace LeanDream.Properties
open LeanDream

-- Theorems are appended here by leandream.properties.prove_all.

end LeanDream.Properties
"""

_RUNTIME_DIRS = [
    REPO_ROOT / "proofs",
    REPO_ROOT / "prompts",
    REPO_ROOT / "macros",
    REPO_ROOT / "runs",
    REPO_ROOT / "data" / "macros",
    REPO_ROOT / "data" / "properties",
    REPO_ROOT / "data" / "classes",
]

_GENERATED_FILES: list[tuple[Path, str]] = [
    (LEAN_DREAM_DIR / "Candidate.lean", _CANDIDATE_SOURCE),
    (LEAN_DREAM_DIR / "Macros.lean", _EMPTY_MACROS),
    (LEAN_DREAM_DIR / "Properties.lean", _EMPTY_PROPERTIES),
]

_REGISTRY_PATH = REPO_ROOT / "macros" / "registry.json"


def _ensure_dirs(*, verbose: bool) -> None:
    for d in _RUNTIME_DIRS:
        if not d.exists():
            d.mkdir(parents=True)
            if verbose:
                print(f"  created  {d.relative_to(REPO_ROOT)}/")


def _ensure_generated_files(*, verbose: bool) -> None:
    for path, content in _GENERATED_FILES:
        if not path.exists():
            path.write_text(content)
            if verbose:
                print(f"  created  {path.relative_to(REPO_ROOT)}")


def _ensure_registry(*, verbose: bool) -> None:
    if not _REGISTRY_PATH.exists():
        _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _REGISTRY_PATH.write_text(json.dumps({}))
        if verbose:
            print(f"  created  {_REGISTRY_PATH.relative_to(REPO_ROOT)}")


def _reset_generated(*, verbose: bool) -> None:
    print("resetting generated state...")
    cleared: list[str] = []

    for d in [REPO_ROOT / "proofs", REPO_ROOT / "prompts", REPO_ROOT / "runs"]:
        if d.exists():
            shutil.rmtree(d)
            cleared.append(f"{d.name}/")

    if _REGISTRY_PATH.exists():
        _REGISTRY_PATH.unlink()
        cleared.append("macros/registry.json")

    for path, content in _GENERATED_FILES:
        path.write_text(content)
        cleared.append(str(path.relative_to(REPO_ROOT)))

    for item in cleared:
        print(f"  reset  {item}")


def bootstrap(*, reset: bool = False, verbose: bool = True) -> None:
    if reset:
        _reset_generated(verbose=verbose)

    if verbose:
        print("bootstrapping LeanDream runtime state...")

    _ensure_dirs(verbose=verbose)
    _ensure_generated_files(verbose=verbose)
    _ensure_registry(verbose=verbose)

    if verbose:
        print("bootstrap complete — run `leandream-doctor` to verify the full environment.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="leandream-bootstrap",
        description="Ensure LeanDream runtime state is valid for a fresh clone/unzip.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe generated state (proofs, prompts, registry, generated Lean) before bootstrapping.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational output.",
    )
    args = parser.parse_args()
    bootstrap(reset=args.reset, verbose=not args.quiet)


if __name__ == "__main__":
    main()
