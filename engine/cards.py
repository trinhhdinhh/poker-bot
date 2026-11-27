"""Cards and the deck.

We reuse `Card` from bot/adapter.py so the engine and the live bot describe cards the same
way (rank 2-14, suit string). That matters later: features/ encodes `Observation`s, and both
the engine and the server parser must hand it identical objects.
"""
from __future__ import annotations
import random
from bot.adapter import SUITS, Card

RANKS = tuple(range(2, 15))

# Built once; every hand shuffles a copy. Card is frozen (immutable), so sharing is safe.
FULL_DECK: tuple[Card, ...] = tuple(Card(rank, suit) for suit in SUITS for rank in RANKS)

_RANK_CHARS = {10: "T", 11: "J", 12: "Q", 13: "K", 14: "A"}


def to_pk(card: Card) -> str:
    """PokerKit's 2-character card name: Card(14, "spades") -> "As", Card(10, "hearts") -> "Th"."""
    return _RANK_CHARS.get(card.rank, str(card.rank)) + card.suit[0]


def shuffled_deck(rng: random.Random) -> list[Card]:
    # Return a shuffled deck of 52 cards. The RNG is passed in so tests can be deterministic.
    deck = list(FULL_DECK)
    rng.shuffle(deck)
    return deck
