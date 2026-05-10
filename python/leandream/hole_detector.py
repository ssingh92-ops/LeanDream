"""Deterministic hole detection over the spec+proof-forest state.

Seven hole types
----------------
HOLE_NEVER_VERIFIED     Spec has zero accepted proofs after ≥ min_attempts tries.
                        → construction_hole: cannot build with current tools.
HOLE_ARITY_TOO_HIGH     Spec arity > DECIDE_MAX_ARITY with repeated timeouts.
                        → proof_hole: verification route too expensive.
HOLE_MACRO_DEPS_MISSING Arity ≥ 3 spec with no macros installed.
                        → macro_hole: missing abstraction not yet available.
HOLE_LLM_CONSISTENTLY_WRONG  LLM resubmits same wrong circuit ≥ threshold times.
                        → class_hole or expressivity_hole.
HOLE_SEMANTIC_GAP       Forest has proofs but none verified in recent window.
                        → proof forest may be stale.
HOLE_PROMPT             LLM receives the right cards but repeatedly misuses them
                        (arity errors dominate even after repair).
HOLE_REPAIR             Repair prompt repeats same failure type twice or more.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .attempts import (
    STATUS_ARITY_MISMATCH,
    STATUS_LEAN_TIMEOUT,
    STATUS_PREFLIGHT_FAILED,
    STATUS_UNKNOWN_MACRO,
    STATUS_VERIFIED,
)
from .failure_modes import (
    HOLE_AFFINE_TARGET,
    HOLE_ARITY_TOO_HIGH,
    HOLE_CONDITIONAL,
    HOLE_LLM_CONSISTENTLY_WRONG,
    HOLE_MACRO_DEPS_MISSING,
    HOLE_MAJORITY_CARRY,
    HOLE_NEVER_VERIFIED,
    HOLE_NONLINEAR_PRODUCT,
    HOLE_OR_LIKE,
    HOLE_PROMPT,
    HOLE_REPAIR,
    HOLE_SEMANTIC_GAP,
)
from .proof_router import DECIDE_MAX_ARITY


@dataclass
class Hole:
    spec: str
    hole_type: str
    severity: str  # "blocker" | "warning" | "info"
    evidence: dict[str, Any] = field(default_factory=dict)
    resolution: str = "unresolved"  # "unresolved" | "resolved" | "repair_attempted"
    resolved_by: str | None = None  # e.g. "macro_6" for OR-like holes

    def __str__(self) -> str:
        return f"Hole({self.spec!r}, {self.hole_type}, {self.severity}, {self.resolution})"


# Tunable thresholds
_MIN_ATTEMPTS_BEFORE_HOLE = 3
_CONSISTENT_FAILURE_THRESHOLD = 3
_ARITY_ERROR_RATE_FOR_PROMPT_HOLE = 0.5  # 50%+ of failures are arity-related
_REPAIR_REPEAT_THRESHOLD = 2             # same error type after repair


def _canonical_hash_from_attempt(rec: dict) -> str | None:
    raw = rec.get("raw_circuit")
    if not raw:
        return None
    import json
    try:
        return json.dumps(raw, sort_keys=True)
    except Exception:
        return None


def _or_like_resolved_by(registry: dict[str, dict]) -> str | None:
    """If a macro with OR semantics (tt_key='0111') exists, return its name."""
    for name, info in registry.items():
        if info.get("tt_key") == "0111":
            return name
    return None


def _macro_with_tt(registry: dict[str, dict], tt_key: str) -> str | None:
    """Return name of first macro whose truth-table key matches, or None."""
    for name, info in registry.items():
        if info.get("tt_key") == tt_key:
            return name
    return None


def _macro_for_spec(registry: dict[str, dict], spec_name: str) -> str | None:
    """Return name of first macro that was mined from this spec, or None."""
    for name, info in registry.items():
        if spec_name in (info.get("members") or []):
            return name
    return None


# Truth-table key → semantic role name.  Ordered from most specific (arity-4) down.
_TT_ROLE_MAP: dict[str, str] = {
    "0001": "and_macro",
    "0110": "xor_macro",
    "0111": "or_macro",
    "1110": "nand_macro",
    "1000": "nor_macro",
    "1001": "xnor_macro",
    "01":   "not_macro",
    "00010111": "majority3_macro",
    "00011011": "carry_macro",
    "01101001": "xor3_macro",
    "0110100110010110": "xor4_macro",
}


def detect_macro_roles(registry: dict[str, dict]) -> dict[str, dict | None]:
    """Scan registry macros by truth-table key; return {role: info_dict | None}.

    Each info_dict contains: name, arity, tt_key, role, legal_schema, body_repr.
    Roles: and_macro, or_macro, xor_macro, not_macro, nand_macro, nor_macro,
    xnor_macro, majority3_macro, carry_macro, xor3_macro, xor4_macro.
    First match per role wins (registry insertion order is stable).
    """
    roles: dict[str, dict | None] = {v: None for v in _TT_ROLE_MAP.values()}
    for name, info in registry.items():
        tt_key = info.get("tt_key", "")
        role = _TT_ROLE_MAP.get(tt_key)
        if role and roles[role] is None:
            arity = info.get("arity", 0)
            args_repr = ", ".join(["expr"] * arity)
            roles[role] = {
                "name": name,
                "arity": arity,
                "tt_key": tt_key,
                "role": role,
                "legal_schema": f'{{"kind":"mac","name":"{name}","args":[{args_repr}]}}',
                "body_repr": info.get("body_repr", ""),
            }
    return roles


def _classify_tt_structure(spec: dict) -> str | None:
    """Classify a spec's truth table structure for expressive hole detection.

    Returns one of the HOLE_*_TARGET strings or None for unclassified/large arities.
    Uses the 'inputs'/'output' rows directly so ordering is unambiguous.
    """
    tt = spec.get("truth_table", [])
    n = spec.get("arity", 0)
    if not tt or n == 0 or n > 4:
        return None

    rows = tt  # list of {"inputs": [bool, ...], "output": bool}

    # OR-like: output is False iff all inputs are False
    if all(
        (not any(r["inputs"]) and not r["output"])
        or (any(r["inputs"]) and r["output"])
        for r in rows
    ):
        return HOLE_OR_LIKE

    # AND-like: output is True iff all inputs are True
    if all(
        (all(r["inputs"]) and r["output"])
        or (not all(r["inputs"]) and not r["output"])
        for r in rows
    ):
        return HOLE_NONLINEAR_PRODUCT

    # NAND-like: output is False iff all inputs are True
    if all(
        (all(r["inputs"]) and not r["output"])
        or (not all(r["inputs"]) and r["output"])
        for r in rows
    ):
        return HOLE_NONLINEAR_PRODUCT

    # Affine/parity: output == XOR of all inputs (sum mod 2 == 1)
    if all(bool(r["output"]) == (sum(r["inputs"]) % 2 == 1) for r in rows):
        return HOLE_AFFINE_TARGET

    # Conditional/mux (n=3): inputs[0] = sel; output = inputs[1] if sel else inputs[2]
    if n == 3 and all(
        r["output"] == (r["inputs"][1] if r["inputs"][0] else r["inputs"][2])
        for r in rows
    ):
        return HOLE_CONDITIONAL

    # Majority (any n): output is True iff strictly more than n/2 inputs are True
    if all(bool(r["output"]) == (sum(r["inputs"]) > n / 2) for r in rows):
        return HOLE_MAJORITY_CARRY

    # Carry-like (n=3): (a AND b) OR (cin AND (a XOR b))
    if n == 3 and all(
        bool(r["output"]) == bool(
            (r["inputs"][0] and r["inputs"][1])
            or (r["inputs"][2] and (r["inputs"][0] != r["inputs"][1]))
        )
        for r in rows
    ):
        return HOLE_MAJORITY_CARRY

    # XOR-chain (n=4): same as parity — already caught above if linear
    # Default for anything with product terms
    return HOLE_NONLINEAR_PRODUCT


def _expressive_class_hole(
    spec_name: str,
    structure: str,
    failed: list[dict],
    registry: dict,
) -> "Hole | None":
    """Create an expressive-class hole based on truth-table structure.

    Checks whether the needed primitives already exist before suggesting new ones.
    Holes should direct the prompt/repair toward existing macros when possible.
    """
    if not failed:
        return None

    and_macro = _macro_with_tt(registry, "0001")   # 2-input AND
    or_macro  = _macro_with_tt(registry, "0111")   # 2-input OR
    xor_macro = _macro_with_tt(registry, "0110")   # 2-input XOR
    n_fail = len(failed)

    if structure == HOLE_AFFINE_TARGET:
        # XOR/parity: the built-in xor gate always works. Failure = composition or prompt gap.
        if xor_macro:
            note = (
                f"XOR macro ({xor_macro}) exists. "
                "Failure is a composition gap — LLM should use the built-in xor gate "
                f"or compose {xor_macro} calls. Do NOT add another XOR primitive."
            )
            retrieve = ["affine", "xor", f"macro:{xor_macro}", f"spec:{spec_name}"]
        else:
            note = (
                "Affine/parity target. No XOR macro installed. "
                "LLM should use the built-in xor gate directly."
            )
            retrieve = ["affine", "xor", f"spec:{spec_name}"]
        return Hole(
            spec=spec_name, hole_type=HOLE_AFFINE_TARGET, severity="warning",
            evidence={
                "structure": "affine_target",
                "note": note,
                "xor_macro": xor_macro,
                "failure_count": n_fail,
                "retrieve_tags": retrieve,
            },
        )

    if structure == HOLE_NONLINEAR_PRODUCT:
        if and_macro:
            note = (
                f"AND macro ({and_macro}) exists. "
                "Failure is a composition gap — compose the existing AND macro "
                "with other gates. Do NOT suggest adding another AND primitive."
            )
            retrieve = [f"macro:{and_macro}", "nonlinear", f"spec:{spec_name}"]
        else:
            note = (
                "Product/AND-like target. No AND macro installed. "
                "LLM should use the built-in and gate directly. "
                "Consider mining an AND abstraction macro."
            )
            retrieve = ["and", f"spec:{spec_name}"]
        return Hole(
            spec=spec_name, hole_type=HOLE_NONLINEAR_PRODUCT, severity="info",
            evidence={
                "structure": "nonlinear_product_target",
                "note": note,
                "and_macro": and_macro,
                "failure_count": n_fail,
                "retrieve_tags": retrieve,
            },
        )

    if structure == HOLE_OR_LIKE:
        if or_macro:
            return Hole(
                spec=spec_name, hole_type=HOLE_OR_LIKE, severity="info",
                evidence={
                    "structure": "or_like_target",
                    "note": f"OR macro ({or_macro}) exists — resolution: use {or_macro}.",
                    "or_macro": or_macro,
                    "failure_count": n_fail,
                },
                resolution="resolved",
                resolved_by=or_macro,
            )
        else:
            return Hole(
                spec=spec_name, hole_type=HOLE_OR_LIKE, severity="warning",
                evidence={
                    "structure": "or_like_target",
                    "note": (
                        "No OR macro installed. LLM should use the built-in or gate. "
                        "Consider mining an OR abstraction macro."
                    ),
                    "failure_count": n_fail,
                    "retrieve_tags": ["or", f"spec:{spec_name}"],
                },
            )

    if structure == HOLE_CONDITIONAL:
        # Mux needs AND + NOT + OR composition.
        if and_macro and or_macro:
            note = (
                f"AND macro ({and_macro}) and OR macro ({or_macro}) both exist. "
                "This is a COMPOSITION GAP — mux(sel,a,b) = OR(AND(sel,a), AND(NOT(sel),b)). "
                "Do NOT add AND or OR primitives; compose from the existing macros. "
                "Retrieve strategy:mux2_formula for the explicit formula."
            )
            retrieve = [
                "strategy:mux2_formula", f"macro:{and_macro}", f"macro:{or_macro}",
                f"spec:{spec_name}", "conditional",
            ]
            sev = "warning"
        elif and_macro and not or_macro:
            note = (
                f"AND macro ({and_macro}) exists but no OR macro. "
                "Need OR to complete mux composition: OR(AND(sel,a), AND(NOT(sel),b)). "
                "Use the built-in or gate or mine an OR macro first."
            )
            retrieve = [f"macro:{and_macro}", "or", f"spec:{spec_name}", "conditional"]
            sev = "warning"
        else:
            note = (
                "No AND or OR macros installed. "
                "Use built-in gates: mux(sel,a,b) = or(and(sel,a), and(not(sel),b)). "
                "Retrieve strategy:mux2_formula."
            )
            retrieve = ["strategy:mux2_formula", f"spec:{spec_name}", "conditional"]
            sev = "warning"
        return Hole(
            spec=spec_name, hole_type=HOLE_CONDITIONAL, severity=sev,
            evidence={
                "structure": "conditional_target",
                "note": note,
                "and_macro": and_macro,
                "or_macro": or_macro,
                "failure_count": n_fail,
                "suggested_composition": "or(and(sel,a), and(not(sel),b))",
                "retrieve_tags": retrieve,
            },
        )

    if structure == HOLE_MAJORITY_CARRY:
        carry_macro = _macro_for_spec(registry, "full_adder_carry")
        and_name = and_macro or "and"
        or_name  = or_macro  or "or"
        formula  = f"{or_name}({or_name}({and_name}(a,b), {and_name}(b,c)), {and_name}(a,c))"
        if carry_macro:
            note = (
                f"Full-adder carry macro ({carry_macro}) exists. "
                f"majority(a,b,c) = {formula}. "
                "Retrieve strategy:majority3_formula for the explicit JSON."
            )
            retrieve = [
                f"macro:{carry_macro}", "strategy:majority3_formula",
                f"spec:{spec_name}", "majority",
            ]
            if and_macro:
                retrieve.insert(0, f"macro:{and_macro}")
            if or_macro:
                retrieve.insert(1, f"macro:{or_macro}")
            sev = "info"
        elif and_macro:
            note = (
                f"AND macro ({and_macro}) exists"
                + (f" and OR macro ({or_macro}) exists" if or_macro else "") + ". "
                f"majority(a,b,c) = {formula}. "
                "Composition gap — do NOT add AND or OR again. "
                "Retrieve strategy:majority3_formula."
            )
            retrieve = [
                f"macro:{and_macro}", "strategy:majority3_formula",
                f"spec:{spec_name}", "majority",
            ]
            if or_macro:
                retrieve.insert(1, f"macro:{or_macro}")
            sev = "warning"
        else:
            note = (
                f"OR-of-ANDs pattern. No named AND macro. "
                f"Use built-in gates: majority(a,b,c) = {formula}."
            )
            retrieve = ["strategy:majority3_formula", f"spec:{spec_name}"]
            sev = "warning"
        return Hole(
            spec=spec_name, hole_type=HOLE_MAJORITY_CARRY, severity=sev,
            evidence={
                "structure": "majority_or_carry_target",
                "note": note,
                "and_macro": and_macro,
                "or_macro": or_macro,
                "carry_macro": carry_macro,
                "failure_count": n_fail,
                "retrieve_tags": retrieve,
            },
        )

    return None


def detect_holes(
    specs: list[dict[str, Any]],
    all_attempts: list[dict[str, Any]],
    registry: dict[str, dict] | None = None,
) -> list[Hole]:
    """Analyse attempt history and registry to find coverage holes.

    Returns Hole objects sorted by severity (blockers first).
    """
    registry = registry or {}
    holes: list[Hole] = []

    # Pre-compute: is OR-like hole resolved?
    or_macro = _or_like_resolved_by(registry)

    # Index attempts by spec
    by_spec: dict[str, list[dict]] = defaultdict(list)
    for rec in all_attempts:
        name = rec.get("spec")
        if name:
            by_spec[name].append(rec)

    for spec in specs:
        name = spec["name"]
        arity = spec.get("arity", 0)
        spec_attempts = by_spec[name]
        n_attempts = len(spec_attempts)
        verified = [r for r in spec_attempts if r.get("status") == STATUS_VERIFIED]
        failed = [r for r in spec_attempts if r.get("status") != STATUS_VERIFIED]

        # --- HOLE_NEVER_VERIFIED (construction_hole) --------------------------
        if n_attempts >= _MIN_ATTEMPTS_BEFORE_HOLE and not verified:
            # Special case: or2 / or-related spec resolved by OR macro
            is_or_spec = name in ("or2",)
            if is_or_spec and or_macro:
                holes.append(Hole(
                    spec=name, hole_type=HOLE_NEVER_VERIFIED, severity="info",
                    evidence={"attempts": n_attempts, "note": "or-like construction hole"},
                    resolution="resolved", resolved_by=or_macro,
                ))
            elif name == "mux2":
                # mux2 always gets enriched evidence regardless of path
                mux_arity_errors = sum(
                    1 for r in failed
                    if r.get("status") in (STATUS_ARITY_MISMATCH, STATUS_PREFLIGHT_FAILED, STATUS_UNKNOWN_MACRO)
                )
                mux_note = (
                    "macro arity misuse dominates"
                    if failed and mux_arity_errors / len(failed) > 0.4
                    else "missing mux/conditional abstraction"
                )
                holes.append(Hole(
                    spec=name, hole_type=HOLE_NEVER_VERIFIED, severity="blocker",
                    evidence={
                        "attempts": n_attempts,
                        "arity_errors": mux_arity_errors,
                        "hole_subtype": "mux_construction_hole",
                        "note": mux_note,
                    },
                ))
            else:
                holes.append(Hole(
                    spec=name, hole_type=HOLE_NEVER_VERIFIED, severity="blocker",
                    evidence={"attempts": n_attempts},
                ))

        # --- HOLE_ARITY_TOO_HIGH (proof_hole) ---------------------------------
        if arity > DECIDE_MAX_ARITY:
            timeout_count = sum(1 for r in spec_attempts if r.get("status") == STATUS_LEAN_TIMEOUT)
            if timeout_count >= 2:
                holes.append(Hole(
                    spec=name, hole_type=HOLE_ARITY_TOO_HIGH, severity="blocker",
                    evidence={"arity": arity, "timeout_count": timeout_count},
                ))

        # --- HOLE_LLM_CONSISTENTLY_WRONG (class/expressivity hole) -----------
        hash_counts: Counter[str] = Counter()
        for rec in failed:
            h = _canonical_hash_from_attempt(rec)
            if h:
                hash_counts[h] += 1
        most_common_count = hash_counts.most_common(1)[0][1] if hash_counts else 0
        if most_common_count >= _CONSISTENT_FAILURE_THRESHOLD:
            holes.append(Hole(
                spec=name, hole_type=HOLE_LLM_CONSISTENTLY_WRONG, severity="warning",
                evidence={
                    "repeated_circuit_count": most_common_count,
                    "distinct_failed_circuits": len(hash_counts),
                },
            ))

        # --- HOLE_PROMPT (prompt_hole) ----------------------------------------
        # LLM keeps making arity/unknown-macro errors even when macros are installed
        if n_attempts >= _MIN_ATTEMPTS_BEFORE_HOLE and registry:
            arity_errors = sum(
                1 for r in failed
                if r.get("status") in (STATUS_ARITY_MISMATCH, STATUS_PREFLIGHT_FAILED, STATUS_UNKNOWN_MACRO)
            )
            if failed and arity_errors / len(failed) >= _ARITY_ERROR_RATE_FOR_PROMPT_HOLE:
                holes.append(Hole(
                    spec=name, hole_type=HOLE_PROMPT, severity="warning",
                    evidence={
                        "arity_error_rate": round(arity_errors / len(failed), 2),
                        "arity_errors": arity_errors,
                        "total_failures": len(failed),
                        "note": "MacroCard arity schema may not be reaching the LLM",
                    },
                ))

        # --- HOLE_REPAIR (repair_hole) ----------------------------------------
        # Repair attempt repeated the same error type as the original
        repair_attempts = [r for r in spec_attempts if r.get("repair_pass", 0) == 1]
        if len(repair_attempts) >= _REPAIR_REPEAT_THRESHOLD:
            repair_same_error = sum(
                1 for r in repair_attempts
                if r.get("error_type") and r["error_type"] in (
                    STATUS_ARITY_MISMATCH, STATUS_PREFLIGHT_FAILED, STATUS_UNKNOWN_MACRO
                )
            )
            if repair_same_error >= _REPAIR_REPEAT_THRESHOLD:
                holes.append(Hole(
                    spec=name, hole_type=HOLE_REPAIR, severity="warning",
                    evidence={
                        "repair_attempts": len(repair_attempts),
                        "same_error_count": repair_same_error,
                        "note": "Repair prompt is not fixing the root cause",
                    },
                ))

        # --- HOLE_SEMANTIC_GAP -----------------------------------------------
        if verified and n_attempts >= 5:
            recent = spec_attempts[-5:]
            recent_verified = [r for r in recent if r.get("status") == STATUS_VERIFIED]
            if not recent_verified:
                holes.append(Hole(
                    spec=name, hole_type=HOLE_SEMANTIC_GAP, severity="info",
                    evidence={
                        "total_verified": len(verified),
                        "recent_window": 5,
                        "recent_verified": 0,
                    },
                ))

        # --- EXPRESSIVE-CLASS holes (V4.2) -----------------------------------
        # Fire when there are meaningful failures, even if the spec was eventually
        # verified. The structural insight (composition gap vs. missing primitive)
        # is still useful for future prompts.  Suppress when failures are rare
        # relative to verifications (no persistent pattern).
        if len(failed) >= _MIN_ATTEMPTS_BEFORE_HOLE - 1 and len(failed) > len(verified):
            structure = _classify_tt_structure(spec)
            if structure:
                exp_hole = _expressive_class_hole(name, structure, failed, registry)
                if exp_hole:
                    holes.append(exp_hole)

    # --- HOLE_MACRO_DEPS_MISSING (macro_hole) --------------------------------
    if not registry:
        for spec in specs:
            if spec.get("arity", 0) >= 3:
                spec_attempts_list = by_spec[spec["name"]]
                if len(spec_attempts_list) >= _MIN_ATTEMPTS_BEFORE_HOLE:
                    verified_count = sum(1 for r in spec_attempts_list if r.get("status") == STATUS_VERIFIED)
                    if not verified_count:
                        holes.append(Hole(
                            spec=spec["name"], hole_type=HOLE_MACRO_DEPS_MISSING, severity="warning",
                            evidence={"macro_count": 0, "spec_arity": spec["arity"]},
                        ))

    # --- mux2-specific: always flag as construction_hole if never solved -----
    mux2_attempts = by_spec.get("mux2", [])
    mux2_verified = [r for r in mux2_attempts if r.get("status") == STATUS_VERIFIED]
    if len(mux2_attempts) >= _MIN_ATTEMPTS_BEFORE_HOLE and not mux2_verified:
        # Determine specific mux hole sub-type from failure evidence
        mux_arity_errors = sum(
            1 for r in mux2_attempts
            if r.get("status") in (STATUS_ARITY_MISMATCH, STATUS_PREFLIGHT_FAILED, STATUS_UNKNOWN_MACRO)
        )
        mux_total_fail = len([r for r in mux2_attempts if r.get("status") != STATUS_VERIFIED])
        already_flagged = any(h.spec == "mux2" and h.hole_type == HOLE_NEVER_VERIFIED for h in holes)
        if not already_flagged:
            note = (
                "macro arity misuse dominates" if mux_total_fail and mux_arity_errors / mux_total_fail > 0.4
                else "missing mux/conditional abstraction"
            )
            holes.append(Hole(
                spec="mux2", hole_type=HOLE_NEVER_VERIFIED, severity="blocker",
                evidence={
                    "attempts": len(mux2_attempts),
                    "arity_errors": mux_arity_errors,
                    "hole_subtype": "mux_construction_hole",
                    "note": note,
                },
            ))

    # Sort: blockers first, then warnings, then info; resolved last
    _sev = {"blocker": 0, "warning": 1, "info": 2}
    _res = {"unresolved": 0, "repair_attempted": 1, "resolved": 2}
    holes.sort(key=lambda h: (_sev.get(h.severity, 3), _res.get(h.resolution, 0)))
    return holes


def holes_by_spec(holes: list[Hole]) -> dict[str, list[Hole]]:
    out: dict[str, list[Hole]] = defaultdict(list)
    for h in holes:
        out[h.spec].append(h)
    return dict(out)
