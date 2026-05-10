"""Verifier: write Candidate.lean, run `lake build`, return verdict."""

from __future__ import annotations

import hashlib
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

# Lean toolchain version — baked into cache keys so changing the toolchain
# automatically invalidates all cached results.
def _lean_toolchain_version() -> str:
    toolchain_file = LEAN_DIR / "lean-toolchain"
    if toolchain_file.exists():
        return toolchain_file.read_text().strip()
    return "unknown"

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
    cached: bool = False           # True when result came from disk cache


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


def _lean_cache_key(source: str, lean_spec: str) -> str:
    digest = hashlib.sha256(source.encode()).hexdigest()[:20]
    return f"{lean_spec}|{digest}|{_lean_toolchain_version()}"


def verify_candidate(
    candidate: Circuit,
    arity: int,
    lean_spec: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    *,
    registry_hash: str = "",
) -> VerifyResult:
    """Stage the candidate, run `lake build`, then restore the default file.

    Checks a persistent disk cache before invoking Lean.  The cache key
    covers the generated source + Lean toolchain version so changing either
    automatically invalidates the entry.

    Args:
        candidate:     Circuit to verify.
        arity:         Number of spec inputs.
        lean_spec:     Lean spec identifier (e.g. ``"Specs.and2"``).
        timeout:       Seconds before lake build is killed.
        registry_hash: Optional extra discriminator (e.g. hash of current
                       macro registry) baked into the cache key.
    """
    from .cache import lean_verify_cache

    source = candidate_lean_source(candidate, arity, lean_spec)
    cache_key = _lean_cache_key(source + registry_hash, lean_spec)

    cache = lean_verify_cache()
    hit = cache.get(cache_key)
    if hit is not None:
        return VerifyResult(
            ok=hit["ok"],
            stdout=hit.get("stdout", ""),
            stderr=hit.get("stderr", ""),
            elapsed_seconds=0.0,
            error=hit.get("error"),
            proof_mode=hit.get("proof_mode"),
            cached=True,
        )

    CANDIDATE_PATH.write_text(source)
    try:
        result = lake_build(timeout=timeout)
        result.proof_mode = tactic_for(arity)
    finally:
        reset_candidate()

    cache.put(cache_key, {
        "ok": result.ok,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error": result.error,
        "proof_mode": result.proof_mode,
    })
    return result
