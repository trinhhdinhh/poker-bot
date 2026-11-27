"""Random play and a speed benchmark for the engine.

`random_move` is a random player, used by the tests and as a baseline opponent.
Run the benchmark with:  python -m engine.bench [--hands 20000] [--players 6]
"""
from __future__ import annotations

import argparse
import random
import time

from engine.holdem import HoldemHand


def random_move(hand: HoldemHand, rng: random.Random) -> tuple[str, int]:
    """A random legal move, biased towards the interesting cases (min-raises and all-ins)."""
    legal = hand.legal_actions()
    options = ["fold", "check" if legal.can_check else "call"] * 2
    if legal.can_raise:
        options += ["min", "max", "mid", "mid"]
    choice = rng.choice(options)
    if choice in ("min", "max", "mid"):
        target = {"min": legal.min_target, "max": legal.max_target,
                  "mid": rng.randint(legal.min_target, legal.max_target)}[choice]
        return ("bet" if hand.current_bet == 0 else "raise"), target
    return choice, 0


def play_random_hand(n_players: int, rng: random.Random, observe: bool = False) -> int:
    """Play one hand with random players; returns the number of decisions.
    observe=True also builds the acting player's Observation at every decision, like training will."""
    hand = HoldemHand(n_players, rng.randrange(n_players), rng)
    decisions = 0
    while not hand.is_over:
        if observe:
            hand.observation(hand.current_seat)
        hand.act(*random_move(hand, rng))
        decisions += 1
    hand.results()
    return decisions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hands", type=int, default=20_000)
    parser.add_argument("--players", type=int, default=6)
    args = parser.parse_args()
    for observe in (False, True):
        rng = random.Random(0)
        start = time.perf_counter()
        decisions = sum(play_random_hand(args.players, rng, observe) for _ in range(args.hands))
        seconds = time.perf_counter() - start
        label = "with observations" if observe else "engine only      "
        print(f"{label}: {args.hands / seconds:7.0f} hands/s, {decisions / seconds:7.0f} decisions/s "
              f"({args.players} players, {decisions / args.hands:.1f} decisions/hand)")


if __name__ == "__main__":
    main()
