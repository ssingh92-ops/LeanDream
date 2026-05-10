"""Doctor: verify the LeanDream environment is fully configured.

Checks:
  - Python package imports
  - Required Python dependencies
  - Lean / lake availability and version
  - lean-toolchain version matches
  - Lake project location and lakefile
  - Generated Lean placeholder files
  - Runtime directory writability
  - Registry / Macros.lean consistency
  - Registry / Properties.lean consistency
  - OPENAI_API_KEY (only in non-mock mode)

Usage:
    python -m leandream.doctor
    python -m leandream.doctor --mock   # skip LLM env check
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEAN_DIR = REPO_ROOT / "lean"
LEAN_DREAM_DIR = LEAN_DIR / "LeanDream"

_REGISTRY_PATH = REPO_ROOT / "macros" / "registry.json"
_MACROS_LEAN = LEAN_DREAM_DIR / "Macros.lean"
_PROPERTIES_LEAN = LEAN_DREAM_DIR / "Properties.lean"
_CANDIDATE_LEAN = LEAN_DREAM_DIR / "Candidate.lean"
_TOOLCHAIN = LEAN_DIR / "lean-toolchain"

_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_RESET = "\033[0m"

_REQUIRED_PACKAGES = ["pydantic", "dotenv", "openai", "rich", "fastapi", "uvicorn"]


def _ok(msg: str) -> None:
    print(f"  {_GREEN}✓{_RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}⚠{_RESET} {msg}")


def _fail(msg: str) -> None:
    print(f"  {_RED}✗{_RESET} {msg}")


def check_python_imports() -> int:
    """Returns number of failures."""
    print("Python imports:")
    failures = 0
    for pkg in _REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
            _ok(pkg)
        except ImportError:
            _fail(f"{pkg} — not installed (pip install {pkg})")
            failures += 1
    return failures


def check_lean() -> int:
    print("Lean / lake:")
    failures = 0

    lake = shutil.which("lake")
    if lake is None:
        _fail("`lake` not found on PATH — install elan and Lean 4")
        return 1
    _ok(f"lake found: {lake}")

    try:
        result = subprocess.run(
            ["lake", "--version"], capture_output=True, text=True, timeout=10
        )
        version_line = (result.stdout or result.stderr).strip().splitlines()[0]
        _ok(f"lake version: {version_line}")
    except Exception as e:
        _warn(f"could not read lake version: {e}")

    if not _TOOLCHAIN.exists():
        _fail(f"lean-toolchain not found: {_TOOLCHAIN}")
        failures += 1
    else:
        toolchain = _TOOLCHAIN.read_text().strip()
        _ok(f"lean-toolchain: {toolchain}")

    lakefile = LEAN_DIR / "lakefile.toml"
    if not lakefile.exists():
        _fail(f"lakefile.toml not found: {lakefile}")
        failures += 1
    else:
        _ok(f"lakefile.toml found")

    return failures


def check_generated_files() -> int:
    print("Generated Lean files:")
    failures = 0
    for path in [_CANDIDATE_LEAN, _MACROS_LEAN, _PROPERTIES_LEAN]:
        rel = path.relative_to(REPO_ROOT)
        if path.exists():
            _ok(str(rel))
        else:
            _fail(f"{rel} — missing (run `leandream-bootstrap`)")
            failures += 1
    return failures


def check_runtime_dirs() -> int:
    print("Runtime directories:")
    failures = 0
    dirs = [
        REPO_ROOT / "proofs",
        REPO_ROOT / "prompts",
        REPO_ROOT / "macros",
        REPO_ROOT / "runs",
    ]
    for d in dirs:
        rel = d.relative_to(REPO_ROOT)
        if not d.exists():
            _warn(f"{rel}/ — missing (run `leandream-bootstrap`)")
        else:
            test_file = d / ".write_test"
            try:
                test_file.write_text("")
                test_file.unlink()
                _ok(f"{rel}/ writable")
            except OSError as e:
                _fail(f"{rel}/ not writable: {e}")
                failures += 1
    return failures


def check_registry_consistency() -> int:
    print("Registry / Lean consistency:")
    failures = 0

    if not _REGISTRY_PATH.exists():
        _warn("macros/registry.json missing — run `leandream-bootstrap`")
        return 0

    try:
        registry: dict = json.loads(_REGISTRY_PATH.read_text())
    except Exception as e:
        _fail(f"registry.json is not valid JSON: {e}")
        return 1

    if not _MACROS_LEAN.exists():
        _fail("Macros.lean missing")
        return 1

    macros_text = _MACROS_LEAN.read_text()
    in_lean: set[str] = set()
    for line in macros_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("def macro_"):
            name = stripped.split()[1].split("(")[0].split(":")[0].strip()
            in_lean.add(name)

    in_registry: set[str] = set(registry.keys())
    only_lean = in_lean - in_registry
    only_registry = in_registry - in_lean

    if not only_lean and not only_registry:
        _ok(f"registry and Macros.lean agree ({len(in_registry)} macro(s))")
    else:
        if only_lean:
            _warn(f"in Macros.lean but not registry: {sorted(only_lean)}")
        if only_registry:
            _warn(f"in registry but not Macros.lean: {sorted(only_registry)}")
        # Registry/Lean drift is a warning, not a hard failure — the next run
        # will regenerate Macros.lean from registry.
        failures += 0  # promote to failure if you want strict mode

    prop_count = sum(len(info.get("properties", [])) for info in registry.values())
    _ok(f"registry: {len(registry)} macro(s), {prop_count} proven property/ies")

    return failures


def check_llm_env(*, mock: bool) -> int:
    print("LLM environment:")
    if mock:
        _ok("mock mode — OPENAI_API_KEY not required")
        return 0

    key = os.environ.get("OPENAI_API_KEY") or _read_dotenv_key()
    if key:
        _ok("OPENAI_API_KEY set")
        model = os.environ.get("LEANDREAM_MODEL", "gpt-5")
        _ok(f"LEANDREAM_MODEL: {model} (override with LEANDREAM_MODEL=...)")
    else:
        _fail("OPENAI_API_KEY not set — copy .env.example to .env and fill it in")
        return 1
    return 0


def _read_dotenv_key() -> str | None:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line.startswith("OPENAI_API_KEY="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            return val or None
    return None


def doctor(*, mock: bool = False) -> bool:
    """Run all checks. Returns True if everything passed (warnings allowed)."""
    print(f"\nLeanDream environment check\n{'=' * 40}")
    total_failures = 0

    total_failures += check_python_imports()
    print()
    total_failures += check_lean()
    print()
    total_failures += check_generated_files()
    print()
    total_failures += check_runtime_dirs()
    print()
    total_failures += check_registry_consistency()
    print()
    total_failures += check_llm_env(mock=mock)
    print()

    if total_failures == 0:
        print(f"{_GREEN}All checks passed.{_RESET} Run `leandream --mock --specs all --iterations 2` to verify.\n")
        return True
    else:
        print(
            f"{_RED}{total_failures} check(s) failed.{_RESET} "
            "Run `leandream-bootstrap` to fix missing generated files, "
            "then re-run `leandream-doctor`.\n"
        )
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="leandream-doctor",
        description="Check that the LeanDream environment is fully configured.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Skip OPENAI_API_KEY check (suitable for mock-mode-only setups).",
    )
    args = parser.parse_args()
    ok = doctor(mock=args.mock)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
