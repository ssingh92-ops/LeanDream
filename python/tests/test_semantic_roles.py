"""Tests for semantic role binding: detect_macro_roles() and render_semantic_role_map()."""

from __future__ import annotations

import pytest

from leandream.hole_detector import detect_macro_roles, _TT_ROLE_MAP
from leandream.prompts import render_semantic_role_map, _is_majority_or_carry_spec, build_majority_role_pack


# ---------------------------------------------------------------------------
# detect_macro_roles
# ---------------------------------------------------------------------------

def test_detect_macro_roles_empty():
    roles = detect_macro_roles({})
    for role in _TT_ROLE_MAP.values():
        assert roles[role] is None


def test_detect_macro_roles_basic():
    registry = {
        "macro_1":  {"tt_key": "0001", "arity": 2},
        "macro_2":  {"tt_key": "0110", "arity": 2},
        "macro_3":  {"tt_key": "0111", "arity": 2},
        "macro_10": {"tt_key": "01",   "arity": 1},
    }
    roles = detect_macro_roles(registry)
    assert roles["and_macro"] == "macro_1"
    assert roles["xor_macro"] == "macro_2"
    assert roles["or_macro"]  == "macro_3"
    assert roles["not_macro"] == "macro_10"
    assert roles["nand_macro"] is None
    assert roles["majority3_macro"] is None


def test_detect_macro_roles_majority_and_carry():
    registry = {
        "macro_4": {"tt_key": "00010111", "arity": 3},  # majority3
        "macro_5": {"tt_key": "00011011", "arity": 3},  # carry
        "macro_8": {"tt_key": "01101001", "arity": 3},  # xor3
        "macro_9": {"tt_key": "0110100110010110", "arity": 4},  # xor4
    }
    roles = detect_macro_roles(registry)
    assert roles["majority3_macro"] == "macro_4"
    assert roles["carry_macro"]     == "macro_5"
    assert roles["xor3_macro"]      == "macro_8"
    assert roles["xor4_macro"]      == "macro_9"


def test_detect_macro_roles_first_match_wins():
    registry = {
        "macro_a": {"tt_key": "0001", "arity": 2},
        "macro_b": {"tt_key": "0001", "arity": 2},  # duplicate role
    }
    roles = detect_macro_roles(registry)
    assert roles["and_macro"] == "macro_a"


def test_detect_macro_roles_unknown_tt_ignored():
    registry = {
        "macro_x": {"tt_key": "FFFF", "arity": 2},
        "macro_1": {"tt_key": "0001", "arity": 2},
    }
    roles = detect_macro_roles(registry)
    assert roles["and_macro"] == "macro_1"


# ---------------------------------------------------------------------------
# render_semantic_role_map
# ---------------------------------------------------------------------------

def test_render_empty_roles_is_empty():
    roles = {v: None for v in _TT_ROLE_MAP.values()}
    assert render_semantic_role_map(roles) == ""


def test_render_includes_filled_roles():
    roles = {v: None for v in _TT_ROLE_MAP.values()}
    roles["and_macro"] = "macro_1"
    roles["or_macro"]  = "macro_3"
    out = render_semantic_role_map(roles)
    assert "macro_1" in out
    assert "macro_3" in out
    assert "SEMANTIC ROLE MAP" in out


def test_render_majority3_formula_injected_when_and_or_known():
    roles = {v: None for v in _TT_ROLE_MAP.values()}
    roles["and_macro"] = "macro_1"
    roles["or_macro"]  = "macro_3"
    out = render_semantic_role_map(roles)
    assert "majority3 formula" in out
    assert "macro_3(macro_3(macro_1(a,b)" in out


def test_render_no_formula_when_and_missing():
    roles = {v: None for v in _TT_ROLE_MAP.values()}
    roles["or_macro"] = "macro_3"
    out = render_semantic_role_map(roles)
    assert "majority3 formula" not in out


def test_render_formula_json_well_formed():
    roles = {v: None for v in _TT_ROLE_MAP.values()}
    roles["and_macro"] = "macro_1"
    roles["or_macro"]  = "macro_3"
    out = render_semantic_role_map(roles)
    import json
    # Extract the JSON line
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
# build_majority_role_pack
# ---------------------------------------------------------------------------

def test_build_majority_role_pack_returns_empty_for_and2():
    roles = {v: None for v in _TT_ROLE_MAP.values()}
    roles["and_macro"] = "macro_1"
    spec = _make_spec(2, lambda ins: ins[0] and ins[1])
    assert build_majority_role_pack(spec, roles) == ""


def test_build_majority_role_pack_returns_map_for_majority3():
    roles = {v: None for v in _TT_ROLE_MAP.values()}
    roles["and_macro"] = "macro_1"
    roles["or_macro"]  = "macro_3"
    spec = _make_spec(3, lambda ins: sum(ins) > 1)
    pack = build_majority_role_pack(spec, roles)
    assert "macro_1" in pack
    assert "macro_3" in pack
    assert "majority3 formula" in pack
