"""Typed failure taxonomy for LeanDream attempt records.

Provides structured descriptions for every STATUS_* constant and the seven
hole-type codes used by hole_detector.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from .attempts import (
    STATUS_ARITY_MISMATCH,
    STATUS_ARITY_OVERFLOW,
    STATUS_BUDGET_EXCEEDED,
    STATUS_EXPANSION_CYCLE,
    STATUS_EXPANSION_DEPTH,
    STATUS_HOLE_DETECTED,
    STATUS_INTERNAL_ERROR,
    STATUS_LEAN_FAILED,
    STATUS_LEAN_TIMEOUT,
    STATUS_LLM_ERROR,
    STATUS_PARSE_ERROR,
    STATUS_PREFLIGHT_FAILED,
    STATUS_REPEATED_FAILURE,
    STATUS_SCHEMA_ERROR,
    STATUS_SEMANTIC_MISMATCH,
    STATUS_UNKNOWN_MACRO,
    STATUS_VERIFIED,
)

# ---------------------------------------------------------------------------
# Hole type codes (5 deterministic hole classes)
# ---------------------------------------------------------------------------
# Core structural holes
HOLE_NEVER_VERIFIED = "hole_never_verified"          # construction_hole: cannot build with current tools
HOLE_ARITY_TOO_HIGH = "hole_arity_too_high"          # proof_hole: verification route too expensive
HOLE_MACRO_DEPS_MISSING = "hole_macro_deps_missing"  # macro_hole: needs abstraction not yet installed
HOLE_LLM_CONSISTENTLY_WRONG = "hole_llm_consistently_wrong"  # class_hole or expressivity_hole
HOLE_SEMANTIC_GAP = "hole_semantic_gap"              # proof forest stale / partial coverage

# Prompt/interaction holes (V4.1)
HOLE_PROMPT = "hole_prompt"   # LLM has the right cards but repeatedly misuses them
HOLE_REPAIR = "hole_repair"   # Repair prompt repeats same failure type

# Expressive-class holes (V4.2) — classified by truth-table structure
HOLE_AFFINE_TARGET      = "hole_affine_target"       # XOR/parity: affine over GF(2)
HOLE_NONLINEAR_PRODUCT  = "hole_nonlinear_product"   # AND/NAND/carry: product terms required
HOLE_OR_LIKE            = "hole_or_like"             # OR semantics: 0 only when all inputs are 0
HOLE_CONDITIONAL        = "hole_conditional"         # Mux/selector: one input selects between cases
HOLE_MAJORITY_CARRY     = "hole_majority_carry"      # OR-of-ANDs: majority or carry-like

ALL_HOLE_TYPES = (
    HOLE_NEVER_VERIFIED,
    HOLE_ARITY_TOO_HIGH,
    HOLE_MACRO_DEPS_MISSING,
    HOLE_LLM_CONSISTENTLY_WRONG,
    HOLE_SEMANTIC_GAP,
    HOLE_PROMPT,
    HOLE_REPAIR,
    HOLE_AFFINE_TARGET,
    HOLE_NONLINEAR_PRODUCT,
    HOLE_OR_LIKE,
    HOLE_CONDITIONAL,
    HOLE_MAJORITY_CARRY,
)


@dataclass(frozen=True)
class FailureMode:
    code: str
    description: str
    repairable: bool
    layer: str  # "llm" | "expansion" | "lean" | "policy" | "system"
    repair_strategy: str | None = None


FAILURE_MODES: dict[str, FailureMode] = {
    STATUS_VERIFIED: FailureMode(
        code=STATUS_VERIFIED,
        description="Circuit verified correct by Lean.",
        repairable=False,
        layer="lean",
    ),
    STATUS_LEAN_FAILED: FailureMode(
        code=STATUS_LEAN_FAILED,
        description="lake build failed; circuit does not match spec.",
        repairable=True,
        layer="lean",
        repair_strategy="arity_guided",
    ),
    STATUS_LEAN_TIMEOUT: FailureMode(
        code=STATUS_LEAN_TIMEOUT,
        description="lake build exceeded the timeout limit.",
        repairable=False,
        layer="lean",
    ),
    STATUS_SEMANTIC_MISMATCH: FailureMode(
        code=STATUS_SEMANTIC_MISMATCH,
        description="Lean accepted the build but truth table does not match spec.",
        repairable=True,
        layer="lean",
        repair_strategy="semantic_guided",
    ),
    STATUS_LLM_ERROR: FailureMode(
        code=STATUS_LLM_ERROR,
        description="LLM call raised an exception (network, rate-limit, etc.).",
        repairable=False,
        layer="llm",
    ),
    STATUS_SCHEMA_ERROR: FailureMode(
        code=STATUS_SCHEMA_ERROR,
        description="LLM response failed Pydantic schema validation.",
        repairable=True,
        layer="llm",
        repair_strategy="schema_hint",
    ),
    STATUS_PARSE_ERROR: FailureMode(
        code=STATUS_PARSE_ERROR,
        description="LLM response could not be parsed as JSON.",
        repairable=True,
        layer="llm",
        repair_strategy="schema_hint",
    ),
    STATUS_UNKNOWN_MACRO: FailureMode(
        code=STATUS_UNKNOWN_MACRO,
        description="LLM referenced a macro name not in the registry.",
        repairable=True,
        layer="expansion",
        repair_strategy="macro_list",
    ),
    STATUS_ARITY_MISMATCH: FailureMode(
        code=STATUS_ARITY_MISMATCH,
        description="LLM called a macro with the wrong number of arguments.",
        repairable=True,
        layer="expansion",
        repair_strategy="arity_hint",
    ),
    STATUS_EXPANSION_CYCLE: FailureMode(
        code=STATUS_EXPANSION_CYCLE,
        description="Macro expansion detected a recursive cycle.",
        repairable=False,
        layer="expansion",
    ),
    STATUS_EXPANSION_DEPTH: FailureMode(
        code=STATUS_EXPANSION_DEPTH,
        description="Macro expansion exceeded the maximum nesting depth.",
        repairable=False,
        layer="expansion",
    ),
    STATUS_ARITY_OVERFLOW: FailureMode(
        code=STATUS_ARITY_OVERFLOW,
        description="Proposed circuit arity exceeds the supported limit.",
        repairable=False,
        layer="policy",
    ),
    STATUS_PREFLIGHT_FAILED: FailureMode(
        code=STATUS_PREFLIGHT_FAILED,
        description="Preflight validator rejected the circuit before Lean.",
        repairable=True,
        layer="policy",
        repair_strategy="preflight_hint",
    ),
    STATUS_REPEATED_FAILURE: FailureMode(
        code=STATUS_REPEATED_FAILURE,
        description="The same circuit (by canonical hash) failed 3+ times on this spec.",
        repairable=False,
        layer="policy",
    ),
    STATUS_HOLE_DETECTED: FailureMode(
        code=STATUS_HOLE_DETECTED,
        description="Spec identified as a structural coverage hole; skipped.",
        repairable=False,
        layer="policy",
    ),
    STATUS_INTERNAL_ERROR: FailureMode(
        code=STATUS_INTERNAL_ERROR,
        description="Unexpected internal exception during orchestration.",
        repairable=False,
        layer="system",
    ),
    STATUS_BUDGET_EXCEEDED: FailureMode(
        code=STATUS_BUDGET_EXCEEDED,
        description="Circuit or prompt exceeded the configured size budget.",
        repairable=False,
        layer="policy",
    ),
}


def classify(status: str) -> FailureMode:
    """Return the FailureMode descriptor for a status code."""
    return FAILURE_MODES.get(
        status,
        FailureMode(
            code=status,
            description=f"Unknown status: {status!r}",
            repairable=False,
            layer="system",
        ),
    )


def is_repairable(status: str) -> bool:
    return classify(status).repairable


def repair_strategy(status: str) -> str | None:
    return classify(status).repair_strategy
