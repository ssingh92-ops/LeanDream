"""Verifier: write Candidate.lean, run `lake build`, return verdict."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .ast import Circuit
from .proof_router import tactic_for
from .translate import candidate_lean_source

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEAN_DIR = REPO_ROOT / "lean"
CANDIDATE_PATH = LEAN_DIR / "LeanDream" / "Candidate.lean"

DEFAULT_TIMEOUT_SECONDS = 120

_DEFAULT_CANDIDATE_SOURCE = """\
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


@dataclass
class VerifyResult:
    ok: bool
    stdout: str
    stderr: str
    elapsed_seconds: float
    error: str | None = None
    proof_mode: str | None = None  # "decide" | "native_decide"


def reset_candidate() -> None:
    """Restore Candidate.lean to a trivially-valid default."""
    CANDIDATE_PATH.write_text(_DEFAULT_CANDIDATE_SOURCE)


def lake_build(timeout: int = DEFAULT_TIMEOUT_SECONDS) -> VerifyResult:
    """Run `lake build` in the Lean project directory."""
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            ["lake", "build"],
            cwd=LEAN_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.monotonic() - t0
        return VerifyResult(
            ok=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
            elapsed_seconds=elapsed,
            error=None if proc.returncode == 0 else f"exit {proc.returncode}",
        )
    except subprocess.TimeoutExpired as e:
        return VerifyResult(
            ok=False,
            stdout=e.stdout or "",
            stderr=e.stderr or "",
            elapsed_seconds=time.monotonic() - t0,
            error=f"timeout after {timeout}s",
        )
    except FileNotFoundError as e:
        return VerifyResult(
            ok=False,
            stdout="",
            stderr="",
            elapsed_seconds=time.monotonic() - t0,
            error=f"`lake` not found on PATH: {e}",
        )


def verify_candidate(
    candidate: Circuit,
    arity: int,
    lean_spec: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> VerifyResult:
    """Stage the candidate, run `lake build`, then restore the default file.

    Restoring after the run keeps subsequent builds (e.g., macro re-verification)
    from being blocked by a failing candidate left in the tree.
    """
    source = candidate_lean_source(candidate, arity, lean_spec)
    CANDIDATE_PATH.write_text(source)
    try:
        result = lake_build(timeout=timeout)
        result.proof_mode = tactic_for(arity)
        return result
    finally:
        reset_candidate()
