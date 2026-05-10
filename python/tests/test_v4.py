"""V4 / V4.1 unit tests.

Covers: hole detection, preflight validation, repair templates,
metrics computation, analysis, MacroCard schema, StrategyCard.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _attempt(spec, status, *, repair_pass=0, error_type=None, arity_err=False,
             raw_circuit=None, iteration=1):
    rec = {
        "spec": spec,
        "status": status,
        "repair_pass": repair_pass,
        "iteration": iteration,
        "raw_circuit": raw_circuit,
    }
    if error_type:
        rec["error_type"] = error_type
    if arity_err:
        rec["status"] = "arity_mismatch"
        rec["error_type"] = "arity_mismatch"
    return rec


# ---------------------------------------------------------------------------
# Hole detector tests
# ---------------------------------------------------------------------------

def test_hole_never_verified_basic():
    from leandream.hole_detector import detect_holes
    from leandream.failure_modes import HOLE_NEVER_VERIFIED

    specs = [{"name": "and2", "arity": 2}]
    attempts = [_attempt("and2", "lean_failed") for _ in range(3)]
    holes = detect_holes(specs, attempts, registry={})

    assert any(h.hole_type == HOLE_NEVER_VERIFIED and h.spec == "and2" for h in holes)
    blocker = next(h for h in holes if h.hole_type == HOLE_NEVER_VERIFIED)
    assert blocker.severity == "blocker"
    assert blocker.resolution == "unresolved"


def test_hole_or2_resolved_by_macro():
    from leandream.hole_detector import detect_holes
    from leandream.failure_modes import HOLE_NEVER_VERIFIED

    specs = [{"name": "or2", "arity": 2}]
    attempts = [_attempt("or2", "lean_failed") for _ in range(3)]
    registry = {"macro_1": {"arity": 2, "tt_key": "0111"}}  # OR semantics
    holes = detect_holes(specs, attempts, registry=registry)

    or_hole = next((h for h in holes if h.spec == "or2" and h.hole_type == HOLE_NEVER_VERIFIED), None)
    assert or_hole is not None
    assert or_hole.resolution == "resolved"
    assert or_hole.resolved_by == "macro_1"
    assert or_hole.severity == "info"


def test_hole_mux2_specific():
    from leandream.hole_detector import detect_holes
    from leandream.failure_modes import HOLE_NEVER_VERIFIED

    specs = [{"name": "mux2", "arity": 3}]
    attempts = [_attempt("mux2", "lean_failed") for _ in range(3)]
    holes = detect_holes(specs, attempts, registry={})

    mux_hole = next((h for h in holes if h.spec == "mux2" and h.hole_type == HOLE_NEVER_VERIFIED), None)
    assert mux_hole is not None
    assert mux_hole.severity == "blocker"
    assert "mux_construction_hole" in mux_hole.evidence.get("hole_subtype", "")


def test_hole_prompt_detected():
    from leandream.hole_detector import detect_holes
    from leandream.failure_modes import HOLE_PROMPT

    specs = [{"name": "and2", "arity": 2}]
    # 4 arity_mismatch failures out of 4 total = 100% arity error rate
    attempts = [_attempt("and2", "arity_mismatch", error_type="arity_mismatch") for _ in range(4)]
    registry = {"macro_1": {"arity": 2, "tt_key": "0011"}}
    holes = detect_holes(specs, attempts, registry=registry)

    assert any(h.hole_type == HOLE_PROMPT and h.spec == "and2" for h in holes)


def test_hole_repair_detected():
    from leandream.hole_detector import detect_holes
    from leandream.failure_modes import HOLE_REPAIR

    specs = [{"name": "and2", "arity": 2}]
    attempts = [
        _attempt("and2", "arity_mismatch", repair_pass=1, error_type="arity_mismatch"),
        _attempt("and2", "arity_mismatch", repair_pass=1, error_type="arity_mismatch"),
    ]
    holes = detect_holes(specs, attempts, registry={})

    assert any(h.hole_type == HOLE_REPAIR and h.spec == "and2" for h in holes)


def test_hole_sort_order():
    from leandream.hole_detector import detect_holes

    specs = [
        {"name": "and2", "arity": 2},
        {"name": "or2", "arity": 2},
    ]
    # and2: never verified (blocker); or2: 4 arity failures => prompt hole (warning)
    attempts = (
        [_attempt("and2", "lean_failed") for _ in range(3)] +
        [_attempt("or2", "arity_mismatch", error_type="arity_mismatch") for _ in range(4)]
    )
    registry = {"macro_1": {"arity": 2, "tt_key": "0011"}}
    holes = detect_holes(specs, attempts, registry=registry)

    severities = [h.severity for h in holes]
    # Blockers must come before warnings
    first_warning_idx = next((i for i, s in enumerate(severities) if s == "warning"), len(severities))
    assert all(s == "blocker" for s in severities[:first_warning_idx])


# ---------------------------------------------------------------------------
# Preflight tests
# ---------------------------------------------------------------------------

def test_preflight_passes_valid_circuit():
    from leandream.preflight import validate

    circuit = {"kind": "and", "left": {"kind": "var", "index": 0}, "right": {"kind": "var", "index": 1}}
    registry = {}
    result = validate(circuit, spec_arity=2, registry=registry)
    assert result.ok


def test_preflight_catches_unknown_macro():
    from leandream.preflight import validate

    circuit = {"kind": "mac", "name": "nonexistent", "args": [{"kind": "var", "index": 0}]}
    result = validate(circuit, spec_arity=1, registry={})
    assert not result.ok
    assert "nonexistent" in result.message


def test_preflight_catches_arity_mismatch():
    from leandream.preflight import validate

    circuit = {
        "kind": "mac", "name": "and_macro",
        "args": [{"kind": "var", "index": 0}],  # provides 1 arg, arity=2
    }
    registry = {"and_macro": {"arity": 2}}
    result = validate(circuit, spec_arity=2, registry=registry)
    assert not result.ok
    assert "arg" in result.message.lower()


def test_preflight_catches_invalid_var_index():
    from leandream.preflight import validate

    circuit = {"kind": "var", "index": 5}  # spec_arity=2 → vars 0..1
    result = validate(circuit, spec_arity=2, registry={})
    assert not result.ok


# ---------------------------------------------------------------------------
# Repair template tests
# ---------------------------------------------------------------------------

def test_build_arity_repair_pack():
    from leandream.repair import build_repair_pack
    from leandream.attempts import STATUS_ARITY_MISMATCH

    pack = build_repair_pack(
        STATUS_ARITY_MISMATCH,
        "macro_1 called with 3 args but expects 2",
        registry={"macro_1": {"arity": 2}},
    )
    assert "macro_1" in pack
    assert "arity" in pack.lower()


def test_build_semantic_repair_pack():
    from leandream.repair import build_semantic_repair_pack

    pack = build_semantic_repair_pack(
        spec_name="and2",
        failing_input=[True, False],
        expected_output=False,
        actual_output=True,
    )
    assert "and2" in pack
    assert "0" in pack  # bool converted to int in the template


def test_build_hole_guided_repair_pack():
    from leandream.repair import build_hole_guided_repair_pack
    from leandream.failure_modes import HOLE_NEVER_VERIFIED

    pack = build_hole_guided_repair_pack(
        hole_type=HOLE_NEVER_VERIFIED,
        spec_name="mux2",
        available_macros=["macro_1"],
        counterexample="(True, False, True) -> expected False got True",
    )
    assert "mux2" in pack


# ---------------------------------------------------------------------------
# Metrics tests
# ---------------------------------------------------------------------------

def test_compute_iteration_metrics():
    from leandream.metrics import compute_iteration_metrics

    attempts = [
        {"spec": "and2", "iteration": 1, "status": "verified", "repair_pass": 0},
        {"spec": "and2", "iteration": 1, "status": "lean_failed", "repair_pass": 0},
        {"spec": "or2", "iteration": 1, "status": "verified", "repair_pass": 1},
    ]
    m = compute_iteration_metrics(
        run_id="test_run",
        iteration=1,
        attempt_records=attempts,
        cur_macro_count=2,
        prev_macro_count=1,
    )
    assert m.verified == 2
    assert m.attempted == 3
    assert m.repair_success == 1
    assert m.new_macros == 1
    assert abs(m.verify_rate - 2/3) < 1e-9


def test_compute_run_summary_decision_fields():
    from leandream.metrics import compute_iteration_metrics, compute_run_summary, IterationMetrics

    iter_metrics = [
        IterationMetrics(
            run_id="r", iteration=1, stage=0,
            verified=4, attempted=5, repair_success=0,
            new_macros=2, new_theorems=0, rag_card_count=10,
            bandit_entropy=0.5, avg_llm_ms=None, avg_lean_ms=None,
        )
    ]
    summary = compute_run_summary(
        run_id="r",
        iteration_metrics=iter_metrics,
        macro_count=3,
        stage_gate_passed=True,
    )
    assert summary.should_continue_to_next_stage is True
    assert summary.recommended_next_action == "proceed_to_next_stage"


def test_compute_run_summary_blocking_reasons():
    from leandream.metrics import compute_run_summary, IterationMetrics
    from leandream.hole_detector import Hole
    from leandream.failure_modes import HOLE_NEVER_VERIFIED

    iter_metrics = [
        IterationMetrics(
            run_id="r", iteration=1, stage=0,
            verified=1, attempted=5, repair_success=0,
            new_macros=0, new_theorems=0, rag_card_count=0,
            bandit_entropy=0.0, avg_llm_ms=None, avg_lean_ms=None,
        )
    ]
    holes = [
        Hole(spec="mux2", hole_type=HOLE_NEVER_VERIFIED, severity="blocker",
             evidence={"attempts": 5}),
    ]
    summary = compute_run_summary(
        run_id="r",
        iteration_metrics=iter_metrics,
        hole_objects=holes,
        stage_gate_passed=False,
    )
    assert "mux2" in " ".join(summary.blocking_reasons)
    # mux2 blocking hole → specific diagnostic action takes priority over generic rerun
    assert summary.recommended_next_action == "inspect_mux_hole"


# ---------------------------------------------------------------------------
# MacroCard schema test
# ---------------------------------------------------------------------------

def test_macro_card_has_legal_call_schema():
    from leandream.memory.cards import macro_card

    card = macro_card(
        name="and_macro", arity=2,
        body_repr="And(v0, v1)", properties=["idempotent"],
        support=5, members=["and2"],
        tt_key="0001", macro_level=0,
    )
    payload = card.payload
    assert "legal_call_schema" in payload
    schema = payload["legal_call_schema"]
    assert '"name":"and_macro"' in schema
    assert schema.count("expr") == 2
    assert payload["trust_level"] == "lean_verified"
    assert payload["tt_key"] == "0001"


# ---------------------------------------------------------------------------
# StrategyCard tests
# ---------------------------------------------------------------------------

def test_strategy_card_fields():
    from leandream.memory.cards import strategy_card, TYPE_STRATEGY

    card = strategy_card(
        name="mux2_formula",
        description="mux decomp",
        formula="mux2(s,a,b) = (s AND a) OR (NOT s AND b)",
        applicable_specs=["mux2"],
    )
    assert card.card_type == TYPE_STRATEGY
    assert "strategy:mux2_formula" in card.tags
    assert "spec:mux2" in card.tags
    assert card.payload["trust_level"] == "prompt_hint"
    assert "formula" in card.payload


def test_index_strategies_returns_builtin_cards():
    from leandream.memory.indexer import index_strategies

    cards = index_strategies()
    names = [c.payload["name"] for c in cards]
    assert "mux2_formula" in names
    assert "majority3_formula" in names
    assert "parity3_formula" in names


# ---------------------------------------------------------------------------
# Curriculum stage spec test
# ---------------------------------------------------------------------------

def test_curriculum_stage_specs():
    from leandream.curriculum import CURRICULUM

    stage_map = {s.name: s for s in CURRICULUM}

    # Stage 0: smoke — should use xor2 not or2
    assert "xor2" in stage_map["smoke"].specs
    assert "or2" not in stage_map["smoke"].specs

    # Stage 1: connectives — includes half_adder specs
    connectives = stage_map["connectives"].specs
    assert "half_adder_sum" in connectives
    assert "half_adder_carry" in connectives

    # Stage 2: adder — includes mux2
    adder = stage_map["adder"].specs
    assert "mux2" in adder
    assert "full_adder_sum" in adder

    # Stage 3: mux — harder specs, no mux2
    mux = stage_map["mux"].specs
    assert "parity4" in mux
    assert "majority3" in mux
    assert "mux2" not in mux
