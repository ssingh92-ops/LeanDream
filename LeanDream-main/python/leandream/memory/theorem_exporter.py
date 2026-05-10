"""Export proven theorem properties from the macro registry into RAG memory cards.

Creates `theorem_property` Cards for every algebraic property that Lean has
accepted for an installed macro.  Idempotent: a card is skipped if an identical
(macro_name, property_name) pair is already present in the store.

Usage:
    from leandream.memory.theorem_exporter import run_exporter
    n = run_exporter(registry)   # returns count of new cards appended
"""
from __future__ import annotations

from .cards import Card, theorem_property_card
from .card_store import append_many, load_all


# ---------------------------------------------------------------------------
# Statement generation
# ---------------------------------------------------------------------------

def _statement_for(prop_name: str, macro_name: str, arity: int) -> str:
    """Return a Lean-like statement string for a known algebraic property name."""
    lean_ref = f"Macros.{macro_name}"
    env = "(fun _ => false)"

    def call(args: str) -> str:
        return f"({lean_ref} {args}).eval {env}"

    if prop_name == "commutative":
        return (
            f"∀ a b : Bool, {call('(.const a) (.const b)')} = "
            f"{call('(.const b) (.const a)')}"
        )
    if prop_name == "idempotent":
        return f"∀ a : Bool, {call('(.const a) (.const a)')} = a"
    if prop_name == "associative":
        return (
            f"∀ a b c : Bool, "
            f"{call(f'({lean_ref} (.const a) (.const b)) (.const c)')} = "
            f"{call(f'(.const a) ({lean_ref} (.const b) (.const c))')}"
        )
    if prop_name == "involution":
        return f"∀ a : Bool, ({lean_ref} ({lean_ref} (.const a))).eval {env} = a"
    if prop_name == "constancy":
        return f"∀ a : Bool, ({lean_ref} (.const a)).eval {env} = a"

    # identity_{side}_{e} / annihilator_{side}_{e}
    parts = prop_name.split("_", 2)
    if len(parts) == 3 and parts[0] in ("identity", "annihilator"):
        kind, side, e = parts
        args = (
            f"(.const {e}) (.const a)"
            if side == "left"
            else f"(.const a) (.const {e})"
        )
        rhs = "a" if kind == "identity" else e
        return f"∀ a : Bool, {call(args)} = {rhs}"

    return f"[{macro_name}: {prop_name}]"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def export_theorem_cards(registry: dict[str, dict]) -> list[Card]:
    """Build theorem_property Cards for all proven properties in the registry.

    Does not write to the store — call run_exporter() for that.
    """
    cards: list[Card] = []
    for macro_name, info in registry.items():
        props = info.get("properties", [])
        if not props:
            continue
        arity = info.get("arity", 0)
        info_structure = info.get("info_structure")
        for prop_name in props:
            stmt = _statement_for(prop_name, macro_name, arity)
            cards.append(
                theorem_property_card(
                    macro_name=macro_name,
                    property_name=prop_name,
                    lean_statement=stmt,
                    info_structure=info_structure,
                )
            )
    return cards


def run_exporter(registry: dict[str, dict], *, verbose: bool = False) -> int:
    """Append new theorem cards to the card store; return the count added.

    Idempotent: a (macro_name, property_name) pair already in the store is
    not re-added even if the macro was re-proved in a later run.
    """
    existing = load_all()
    existing_keys: set[tuple[str, str]] = {
        (c.payload.get("macro_name", ""), c.payload.get("property_name", ""))
        for c in existing
        if c.card_type == "theorem_property"
    }

    new_cards = export_theorem_cards(registry)
    to_add = [
        c for c in new_cards
        if (c.payload["macro_name"], c.payload["property_name"]) not in existing_keys
    ]
    if to_add:
        append_many(to_add)
        if verbose:
            for c in to_add:
                print(
                    f"  [theorem-card] {c.payload['macro_name']}: "
                    f"{c.payload['property_name']}"
                )
    return len(to_add)
