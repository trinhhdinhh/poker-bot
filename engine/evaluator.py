"""Hand evaluator: the best 5-card poker hand out of 5-7 cards.

Returns a score `(category, tiebreakers)`. Python compares tuples left to right, so
`score_a > score_b` means hand A wins, and equal scores split the pot.

The score is exactly what the server's `PokerEngine.evaluate_best_hand` returns (as a tuple),
so ties and splits resolve identically. The server gets there by trying all 21 five-card
subsets of 7 cards. We get the same answer in one pass by counting ranks and suits, which is
about 18x faster (3 us vs 51 us per 7-card hand) -- it matters because self-play evaluates millions of showdowns.
"""
from __future__ import annotations
from typing import Iterable, Optional
from bot.adapter import Card

HIGH_CARD, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)

Score = tuple[int, tuple[int, ...]]

_RANKS_DESC = tuple(range(14, 1, -1))  # A, K, ..., 2


def straight_high(ranks: set[int]) -> Optional[int]:
    """Top card of the best straight in `ranks`, or None. A-2-3-4-5 (the wheel) counts as 5-high."""
    if 14 in ranks:
        ranks = ranks | {1}  # an ace also plays low
    for high in range(14, 4, -1):
        if all(r in ranks for r in range(high - 4, high + 1)):
            return high
    return None


def evaluate(cards: Iterable[Card]) -> Score:
    cards = list(cards)
    if len(cards) < 5:  # same fallback as the server (never happens at a real showdown)
        return HIGH_CARD, tuple(sorted((c.rank for c in cards), reverse=True))

    # 1. Count how many cards of each rank, and group ranks by suit.
    counts = [0] * 15  # counts[rank]; index 0 and 1 unused
    by_suit: dict[str, list[int]] = {}
    for c in cards:
        counts[c.rank] += 1
        by_suit.setdefault(c.suit, []).append(c.rank)

    # 2. Flush / straight flush. With 7 cards at most one suit can have 5+ cards.
    flush: Optional[Score] = None
    for suited in by_suit.values():
        if len(suited) >= 5:
            sf_high = straight_high(set(suited))
            if sf_high:
                return STRAIGHT_FLUSH, (sf_high,)
            flush = FLUSH, tuple(sorted(suited, reverse=True)[:5])

    # 3. Rank groups, each list highest rank first.
    quads = [r for r in _RANKS_DESC if counts[r] == 4]
    trips = [r for r in _RANKS_DESC if counts[r] == 3]
    pairs = [r for r in _RANKS_DESC if counts[r] == 2]

    def kickers(exclude: tuple[int, ...], n: int) -> tuple[int, ...]:
        """The n highest ranks we hold that aren't already used in the hand."""
        return tuple(r for r in _RANKS_DESC if counts[r] and r not in exclude)[:n]

    # 4. Check categories from strongest to weakest; the first match is the best hand.
    if quads:
        return QUADS, (quads[0], *kickers((quads[0],), 1))
    if trips and (len(trips) >= 2 or pairs):
        # Two sets of trips: the lower one plays as the pair (e.g. KKK + 999 -> kings full of nines).
        return FULL_HOUSE, (trips[0], max(trips[1:] + pairs))
    if flush:
        return flush
    high = straight_high({c.rank for c in cards})
    if high:
        return STRAIGHT, (high,)
    if trips:
        return TRIPS, (trips[0], *kickers((trips[0],), 2))
    if len(pairs) >= 2:
        # Three pairs: only the top two count; the third pair's rank can still be the kicker.
        top, second = pairs[0], pairs[1]
        return TWO_PAIR, (top, second, *kickers((top, second), 1))
    if pairs:
        return PAIR, (pairs[0], *kickers((pairs[0],), 3))
    return HIGH_CARD, kickers((), 5)
