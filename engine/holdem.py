"""Offline no-limit Hold'em simulator matching server rules (stack 1000, blinds 10/20, 3+ players).

DMC self-play runs millions of hands here, so it must be fast and exactly match the server
(min-raise, short all-ins, side pots, fresh stack every hand). Consider wrapping an existing library
(e.g. PokerKit) instead of writing one from scratch.
"""
