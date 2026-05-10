"""JSONL-backed card store at data/cards/cards.jsonl."""

from __future__ import annotations

import json
from pathlib import Path

from .cards import Card

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CARDS_DIR = REPO_ROOT / "data" / "cards"
CARDS_PATH = CARDS_DIR / "cards.jsonl"


def append(card: Card) -> None:
    """Append a single card to the store."""
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    with CARDS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(card.to_dict()) + "\n")


def append_many(cards: list[Card]) -> None:
    """Append multiple cards in one open/close."""
    if not cards:
        return
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    with CARDS_PATH.open("a", encoding="utf-8") as f:
        for c in cards:
            f.write(json.dumps(c.to_dict()) + "\n")


def load_all() -> list[Card]:
    """Load all cards from the JSONL store."""
    if not CARDS_PATH.exists():
        return []
    out: list[Card] = []
    for line in CARDS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(Card.from_dict(json.loads(line)))
            except Exception:
                pass
    return out


def load_by_type(card_type: str) -> list[Card]:
    return [c for c in load_all() if c.card_type == card_type]


def rebuild(cards: list[Card]) -> None:
    """Rewrite the entire store from a list of cards."""
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    with CARDS_PATH.open("w", encoding="utf-8") as f:
        for c in cards:
            f.write(json.dumps(c.to_dict()) + "\n")


def clear() -> None:
    """Delete the card store file."""
    if CARDS_PATH.exists():
        CARDS_PATH.unlink()
