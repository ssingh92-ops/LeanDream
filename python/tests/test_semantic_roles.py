"""Tests for semantic role binding: detect_macro_roles() and render_semantic_role_map()."""

from __future__ import annotations

import json

import pytest

from leandream.hole_detector import detect_macro_roles, _TT_ROLE_MAP
from leandream.prompts import render_semantic_role_map, _is_majority_or_carry_spec, build_majority_role_pack


# ---------------------------------------------------------------------------
# detect_macro_roles — return type is dict[str, dict | None]
# ---------------------------------------------------------------------------

def test_detect_macro_roles_empty():
    roles = detect_macro_roles({})
    for role in _TT_ROLE_MAP.values():
        assert roles[role] is None


def test_detect_macro_roles_basic():
    registry = {
        "macro_1":  {"tt_key": "0001", "arity": 2, "body_repr": "(.and x0 x1)"},
        "macro_2":  {"tt_key": "0110", "arity": 2, "body_repr": "(.xor x0 x1)"},
        "macro_3":  {"tt_key": "0111", "arity": 2, "body_repr": "(.or x0 x1)"},
        "macro_10": {"tt_key": "01",   "arity": 1, "body_repr": "(.not x0)"},
    }
    roles = detect_macro_roles(registry)
    assert roles["and_macro"]["name"] == "macro_1"
    assert roles["and_macro"]["arity"] == 2
    assert roles["xor_macro"]["name"] == "macro_2"
    assert roles["xor_macro"]["arity"] == 2
    assert roles["or_macro"]["name"]   == "macro_3"
    assert roles["or_macro"]["arity"]  == 2
    assert roles["not_macro"]["name"]  == "macro_10"
    assert roles["not_macro"]["arity"] == 1
    assert roles["nand_macro"] is None
    assert roles["majority3_macro"] is None


def test_detect_macro_roles_includes_legal_schema():
    registry = {"macro_1": {"tt_key": "0001", "arity": 2}}
    roles = detect_macro_roles(registry)
    info = roles["and_macro"]
    assert info is not None
    assert "legal_schema" in info
    schema_str = info["legal_schema"]
    assert '"kind":"mac"' in schema_str
    assert '"name":"macro_1"' in schema_str
    # 2-arg schema contains exactly 2 "expr" placeholders
    assert schema_str.count("expr") == 2


def test_detect_macro_roles_majority_and_carry():
    registry = {
        "macro_4": {"tt_key": "00010111", "arity": 3},  # majority3
        "macro_5": {"tt_key": "00011011", "arity": 3},  # carry
        "macro_8": {"tt_key": "01101001", "arity": 3},  # xor3
        "macro_9": {"tt_key": "0110100110010110", "arity": 4},  # xor4
    }
    roles = detect_macro_roles(registry)
    assert roles["majority3_macro"]["name"] == "macro_4"
    assert roles["majority3_macro"]["arity"] == 3
    assert roles["carry_macro"]["name"]      == "macro_5"
    assert roles["carry_macro"]["arity"]     == 3
    assert roles["xor3_macro"]["name"]       == "macro_8"
    assert roles["xor4_macro"]["name"]       == "macro_9"


def test_detect_macro_roles_carry_legal_schema_has_3_args():
    registry = {"macro_4": {"tt_key": "00010111", "arity": 3, "body_repr": "..."}}
    roles = detect_macro_roles(registry)
    info = roles["majority3_macro"]
    schema_str = info["legal_schema"]
    assert '"name":"macro_4"' in schema_str
    # 3-arg schema contains exactly 3 "expr" placeholders
    assert schema_str.count("expr") == 3, f"majority3 schema must have 3 args, got: {schema_str}"


def test_detect_macro_roles_first_match_wins():
    registry = {
        "macro_a": {"tt_key": "0001", "arity": 2},
        "macro_b": {"tt_key": "0001", "arity": 2},
    }
    roles = detect_macro_roles(registry)
    assert roles["and_macro"]["name"] == "macro_a"


def test_detect_macro_roles_unknown_tt_ignored():
    registry = {
        "macro_x": {"tt_key": "FFFF", "arity": 2},
        "macro_1": {"tt_key": "0001", "arity": 2},
    }
    roles = detect_macro_roles(registry)
    assert roles["and_macro"]["name"] == "macro_1"


# ---------------------------------------------------------------------------
# render_semantic_role_map — arity/schema visible, warnings for carry/majority
# ---------------------------------------------------------------------------

def test_render_empty_roles_is_empty():
    roles = {v: None for v in _TT_ROLE_MAP.values()}
    assert render_semantic_role_map(roles) == ""


def test_render_includes_filled_roles_with_arity():
    roles = {v: None for v in _TT_ROLE_MAP.values()}
    roles["and_macro"] = {"name": "macro_1", "arity": 2, "tt_key": "0001",
                          "role": "and_macro", "legal_schema": '{"kind":"mac","name":"macro_1","args":[expr,expr]}', "body_repr": ""}
    roles["or_macro"]  = {"name": "macro_3", "arity": 2, "tt_key": "0111",
                          "role": "or_macro",  "legal_schema": '{"kind":"mac","name":"macro_3","args":[expr,expr]}', "body_repr": ""}
    out = render_semantic_role_map(roles)
    assert "macro_1" in out
    assert "macro_3" in out
    assert "args=2" in out
    assert "SEMANTIC ROLE MAP" in out
    assert "legal:" in out


def test_render_majority3_formula_injected_when_and_or_known():
    roles = {v: None for v in _TT_ROLE_MAP.values()}
    roles["and_macro"] = {"name": "macro_1", "arity": 2, "tt_key": "0001",
                          "role": "and_macro", "legal_schema": '{"kind":"mac","name":"macro_1","args":[expr,expr]}', "body_repr": ""}
    roles["or_macro"]  = {"name": "macro_3", "arity": 2, "tt_key": "0111",
                          "role": "or_macro",  "legal_schema": '{"kind":"mac","name":"macro_3","args":[expr,expr]}', "body_repr": ""}
    out = render_semantic_role_map(roles)
    assert "majority3 formula" in out
    assert "macro_3(macro_3(macro_1(a,b)" in out


def test_render_carry_macro_warns_3_args():
    roles = {v: None for v in _TT_ROLE_MAP.values()}
    roles["majority3_macro"] = {"name": "macro_4", "arity": 3, "tt_key": "00010111",
                                "role": "majority3_macro", "legal_schema": '{"kind":"mac","name":"macro_4","args":[expr,expr,expr]}', "body_repr": ""}
    out = render_semantic_role_map(roles)
    assert "NEVER call macro_4 with 2 args" in out
    assert "3 args required" in out or "exactly 3" in out


def test_render_carry_macro_shows_direct_usage():
    roles = {v: None for v in _TT_ROLE_MAP.values()}
    roles["majority3_macro"] = {"name": "macro_4", "arity": 3, "tt_key": "00010111",
                                "role": "majority3_macro", "legal_schema": '{"kind":"mac","name":"macro_4","args":[expr,expr,expr]}', "body_repr": ""}
    out = render_semantic_role_map(roles)
    assert "Direct 3-arg usage" in out
    assert "macro_4(a, b, c)" in out


def test_render_no_formula_when_and_missing():
    roles = {v: None for v in _TT_ROLE_MAP.values()}
    roles["or_macro"] = {"name": "macro_3", "arity": 2, "tt_key": "0111",
                         "role": "or_macro", "legal_schema": '{"kind":"mac","name":"macro_3","args":[expr,expr]}', "body_repr": ""}
    out = render_semantic_role_map(roles)
    assert "majority3 formula" not in out


def test_render_formula_json_well_formed():
    roles = {v: None for v in _TT_ROLE_MAP.values()}
    roles["and_macro"] = {"name": "macro_1", "arity": 2, "tt_key": "0001",
                          "role": "and_macro", "legal_schema": '{"kind":"mac","name":"macro_1","args":[expr,expr]}', "body_repr": ""}
    roles["or_macro"]  = {"name": "macro_3", "arity": 2, "tt_key": "0111",
                          "role": "or_macro",  "legal_schema": '{"kind":"mac","name":"macro_3","args":[expr,expr]}', "body_repr": ""}
    out = render_semantic_role_map(roles)
    for line in out.splitlines():
        if line.strip().startswith("JSON:"):
            json_str = line.strip()[len("JSON:"):].strip()
            parsed = json.loads(json_str)
            assert parsed["kind"] == "mac"
            assert parsed["name"] == "macro_3"
            break
    else:
        pytest.fail("No JSON line found in render output")


# ---------------------------------------------------------------------------
# _is_majority_or_carry_spec
# ---------------------------------------------------------------------------

def _make_spec(arity: int, fn) -> dict:
    from itertools import product
    tt = []
    for combo in product([False, True], repeat=arity):
        inputs = list(combo)
        tt.append({"inputs": inputs, "output": fn(inputs)})
    return {"arity": arity, "truth_table": tt}


def test_majority3_detected():
    spec = _make_spec(3, lambda ins: sum(ins) > 1)
    assert _is_majority_or_carry_spec(spec)


def test_carry_detected():
    def carry(ins):
        a, b, cin = ins
        return (a and b) or (cin and (a != b))
    spec = _make_spec(3, carry)
    assert _is_majority_or_carry_spec(spec)


def test_and2_not_detected():
    spec = _make_spec(2, lambda ins: ins[0] and ins[1])
    assert not _is_majority_or_carry_spec(spec)


def test_xor2_not_detected():
    spec = _make_spec(2, lambda ins: ins[0] != ins[1])
    assert not _is_majority_or_carry_spec(spec)


# ---------------------------------------------------------------------------
# build_majority_role_pack — returns empty for non-majority specs
# ---------------------------------------------------------------------------

def _make_roles_with_and_or() -> dict:
    roles = {v: None for v in _TT_ROLE_MAP.values()}
    roles["and_macro"] = {"name": "macro_1", "arity": 2, "tt_key": "0001",
                          "role": "and_macro", "legal_schema": '{"kind":"mac","name":"macro_1","args":[expr,expr]}', "body_repr": ""}
    roles["or_macro"]  = {"name": "macro_3", "arity": 2, "tt_key": "0111",
                          "role": "or_macro",  "legal_schema": '{"kind":"mac","name":"macro_3","args":[expr,expr]}', "body_repr": ""}
    return roles


def test_build_majority_role_pack_returns_empty_for_and2():
    spec = _make_spec(2, lambda ins: ins[0] and ins[1])
    assert build_majority_role_pack(spec, _make_roles_with_and_or()) == ""


def test_build_majority_role_pack_returns_map_for_majority3():
    spec = _make_spec(3, lambda ins: sum(ins) > 1)
    pack = build_majority_role_pack(spec, _make_roles_with_and_or())
    assert "macro_1" in pack
    assert "macro_3" in pack
    assert "majority3 formula" in pack


def test_build_majority_role_pack_includes_carry_macro_if_present():
    roles = _make_roles_with_and_or()
    roles["majority3_macro"] = {"name": "macro_4", "arity": 3, "tt_key": "00010111",
                                "role": "majority3_macro",
                                "legal_schema": '{"kind":"mac","name":"macro_4","args":[expr,expr,expr]}',
                                "body_repr": ""}
    spec = _make_spec(3, lambda ins: sum(ins) > 1)
    pack = build_majority_role_pack(spec, roles)
    assert "macro_4" in pack
    assert "NEVER call macro_4 with 2 args" in pack
    assert "3 args required" in pack or "exactly 3" in pack


# ---------------------------------------------------------------------------
# Stage 5 spec existence
# ---------------------------------------------------------------------------

def test_stage5_exists_in_curriculum():
    from leandream.curriculum import CURRICULUM
    stage5 = [s for s in CURRICULUM if s.index == 5]
    assert len(stage5) == 1, "Stage 5 must exist in CURRICULUM"
    s = stage5[0]
    assert s.name == "motif"
    assert len(s.specs) >= 4, "Stage 5 must have at least 4 motif-rich specs"


def test_stage5_specs_are_motif_rich():
    from leandream.curriculum import CURRICULUM
    stage5 = next(s for s in CURRICULUM if s.index == 5)
    # Must include majority3, mux2, or similar nonlinear motif specs
    motif_specs = {"majority3", "mux2", "and3", "or3", "majority4"}
    overlap = set(stage5.specs) & motif_specs
    assert len(overlap) >= 2, f"Stage 5 should include at least 2 motif specs, got: {stage5.specs}"


def test_and3_spec_file_exists():
    from leandream.verify import REPO_ROOT
    spec_path = REPO_ROOT / "specs" / "and3.json"
    assert spec_path.exists(), "and3.json spec file must exist"


def test_majority4_spec_file_exists():
    from leandream.verify import REPO_ROOT
    spec_path = REPO_ROOT / "specs" / "majority4.json"
    assert spec_path.exists(), "majority4.json spec file must exist"
