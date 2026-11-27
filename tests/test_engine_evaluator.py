import random

import pytest

from bot.adapter import Card
from engine.cards import FULL_DECK, shuffled_deck
from engine.evaluator import (FLUSH, FULL_HOUSE, HIGH_CARD, PAIR, QUADS, STRAIGHT, STRAIGHT_FLUSH, TRIPS,
                              TWO_PAIR, evaluate)
from tests.server_ref import load_server_engine, requires_server

SUIT = {"h": "hearts", "d": "diamonds", "c": "clubs", "s": "spades"}
RANK = {"T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}


def hand(text: str) -> list[Card]:
    """'Ah Kd 2c' -> cards. Short notation keeps the test cases readable."""
    return [Card(RANK.get(t[0]) or int(t[0]), SUIT[t[1]]) for t in text.split()]


def test_deck_has_52_unique_cards():
    assert len(set(FULL_DECK)) == 52


def test_same_seed_deals_same_deck():
    assert shuffled_deck(random.Random(7)) == shuffled_deck(random.Random(7))


@pytest.mark.parametrize("cards, expected", [
    ("Ah Kh Qh Jh Th 2c 3d", (STRAIGHT_FLUSH, (14,))),
    ("Ah 2h 3h 4h 5h Kc Kd", (STRAIGHT_FLUSH, (5,))),      # steel wheel beats the kings
    ("9s 9h 9d 9c Ah 2c 3d", (QUADS, (9, 14))),
    ("Ks Kh Kd 9c 9h 9d 2c", (FULL_HOUSE, (13, 9))),        # two trips -> full house
    ("Ks Kh Kd 9c 9h 2d 2c", (FULL_HOUSE, (13, 9))),        # trips + two pairs: higher pair plays
    ("Ah 9h 7h 4h 2h 3h Kc", (FLUSH, (14, 9, 7, 4, 3))),   # 6 hearts: best 5 only
    ("Ah 2c 3d 4s 5h Kc Qd", (STRAIGHT, (5,))),             # wheel
    ("9h Tc Jd Qs Kh Ac 2d", (STRAIGHT, (14,))),
    ("7h 7c 7d As Kh 2c 3d", (TRIPS, (7, 14, 13))),
    ("Ah Ac Kd Ks Qh Qc 2d", (TWO_PAIR, (14, 13, 12))),     # third pair's rank is the kicker
    ("Ah Ac Kd Ks 2h 2c Qd", (TWO_PAIR, (14, 13, 12))),
    ("Jh Jc 9d 7s 5h 3c 2d", (PAIR, (11, 9, 7, 5))),
    ("Ah Jc 9d 7s 5h 3c 2d", (HIGH_CARD, (14, 11, 9, 7, 5))),
])
def test_known_hands(cards, expected):
    assert evaluate(hand(cards)) == expected


@requires_server
def test_matches_server_evaluator_on_random_hands():
    """Differential test: 20k random 5/6/7-card hands must score exactly like the server."""
    server = load_server_engine()
    to_server = {s.value: s for s in server.Suit}
    rng = random.Random(0)
    for _ in range(20_000):
        cards = rng.sample(FULL_DECK, rng.choice((5, 6, 7)))
        cat, breakers = server.PokerEngine.evaluate_best_hand(server.Card(c.rank, to_server[c.suit]) for c in cards)
        assert evaluate(cards) == (cat, tuple(breakers)), cards
