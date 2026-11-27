"""Our engine vs the real server's engine: same seats, same deck, same moves -> same everything.

Every test here plays hands in both engines side by side (see `server_hand`) and compares them.
Skipped when ./ai-poker-server isn't cloned. For a longer run of the random-hands test:
    ENGINE_STRESS_HANDS=20000 pytest tests/test_engine_vs_server.py
"""
import os
import random

import pytest

from bot.action_map import legal_actions as bot_legal_actions
from bot.adapter import HandHistory, parse_state
from engine.bench import random_move
from engine.holdem import HoldemHand
from tests.server_ref import load_server_engine, requires_server, server_hand

pytestmark = requires_server

STRESS_HANDS = int(os.environ.get("ENGINE_STRESS_HANDS", "1000"))


@pytest.fixture(scope="module")
def server():
    return load_server_engine()


def both(server, n: int, button: int, seed: int) -> tuple[HoldemHand, object]:
    return HoldemHand(n, button, random.Random(seed)), server_hand(server, n, button, seed)


def server_results(theirs) -> list[int]:
    theirs.finalize_showdown()  # the server holds showdown payouts until this is called
    return [p.profit_loss for p in theirs.players.values()]


@pytest.mark.parametrize("n", [2, 3, 6, 9])
def test_start_of_hand(server, n):
    for seed in range(20):
        button = seed % n
        ours, theirs = both(server, n, button, seed)
        assert theirs.dealer == f"p{button}"
        assert (theirs.small_blind_player, theirs.big_blind_player) == (f"p{ours.small_blind_seat}", f"p{ours.big_blind_seat}")
        assert theirs.current_turn == f"p{ours.current_seat}"
        assert theirs.pot == ours.pot
        for seat, p in enumerate(theirs.players.values()):
            assert [(c.rank, c.suit.value) for c in p.hole_cards] == [(c.rank, c.suit) for c in ours.hole_cards[seat]]
            assert (p.stack, p.bet) == (ours.stacks[seat], ours.bets[seat])


def test_check_down_board_and_payouts(server):
    for seed in range(50):
        n = 2 + seed % 5
        ours, theirs = both(server, n, seed % n, seed)
        while not ours.is_over:
            event = ours.act("check" if ours.legal_actions().can_check else "call")
            assert theirs.place_action(event["player"], event["type"], 0)["ok"]
        assert [(c.rank, c.suit.value) for c in theirs.community_cards] == [(c.rank, c.suit) for c in ours.board]
        assert server_results(theirs) == ours.results()


def test_random_hands_match_action_by_action(server):
    """STRESS_HANDS random hands, 2-9 players: after every action the player to act, current bet,
    minimum raise, pot, event and stacks agree; at the end every seat's result agrees exactly."""
    rng = random.Random(123)
    for seed in range(STRESS_HANDS):
        n = rng.randint(2, 9)
        ours, theirs = both(server, n, rng.randrange(n), seed)
        while not ours.is_over:
            assert theirs.current_turn == f"p{ours.current_seat}"
            assert (theirs.current_bet, theirs.minimum_raise, theirs.pot) == (ours.current_bet, ours.minimum_raise, ours.pot)
            action, amount = random_move(ours, rng)
            event = ours.act(action, amount)
            result = theirs.place_action(event["player"], action, amount)
            assert result["ok"], result
            if theirs.last_action["type"] != "payout":  # the hand's last action is replaced by the payout
                assert {k: v for k, v in event.items() if k != "street"} == theirs.last_action
            if not ours.is_over:  # at showdown the server holds payouts until finalize_showdown()
                assert [p.stack for p in theirs.players.values()] == ours.stacks
        assert theirs.current_turn is None
        assert sum(ours.results()) == 0
        assert server_results(theirs) == ours.results(), f"seed {seed}"


def test_observations_and_history_match_what_the_live_bot_sees(server):
    """At every decision, for every seat: the engine's Observation equals what bot/adapter.py
    parses from the server's JSON, the engine's event log equals the HandHistory the live bot
    rebuilds from successive server states, and the engine's legal actions equal the live bot's."""
    rng = random.Random(7)
    for seed in range(300):
        n = rng.randint(2, 6)
        ours, theirs = both(server, n, rng.randrange(n), seed)
        histories = [HandHistory() for _ in range(n)]
        while not ours.is_over:
            for seat in range(n):
                payload = theirs.snapshot(f"p{seat}")
                histories[seat].update(payload)
                assert ours.observation(seat) == parse_state(payload, f"p{seat}")
                assert histories[seat].events == ours.events
            assert ours.legal_actions() == bot_legal_actions(ours.observation(ours.current_seat))
            action, amount = random_move(ours, rng)
            event = ours.act(action, amount)
            assert theirs.place_action(event["player"], action, amount)["ok"]


def wild_move(hand: HoldemHand, rng: random.Random) -> tuple[str, object]:
    """A move that is often illegal: amounts right at and around every limit, wrong action names,
    amounts on actions that take none, non-integers."""
    legal, bet = hand.legal_actions(), hand.current_bet
    action = rng.choice(["fold", "check", "call", "bet", "raise", "raise", "allin"])
    if action in ("bet", "raise"):
        amount = rng.choice([0, bet, bet + 1, legal.min_target - 1, legal.min_target, legal.max_target,
                             legal.max_target + 1, rng.randint(0, 1100), 60.0, True, -20])
    else:
        amount = rng.choice([0, 0, 0, 20])
    return action, amount


def test_same_moves_are_accepted_and_rejected(server):
    """Throw wild moves at both engines. Whenever the server rejects one, ours must too (and change
    nothing); whenever the server accepts one, ours must accept it and stay in step."""
    rng = random.Random(42)
    accepted = rejected = 0
    for seed in range(400):
        n = rng.randint(2, 6)
        ours, theirs = both(server, n, rng.randrange(n), seed)
        while not ours.is_over:
            for _ in range(5):
                action, amount = wild_move(ours, rng)
                player = f"p{ours.current_seat}"
                server_ok = theirs.place_action(player, action, amount)["ok"]
                if not server_ok:
                    before = (ours.stacks, ours.bets, ours.current_seat, len(ours.events))
                    with pytest.raises(ValueError):
                        ours.act(action, amount)
                    assert (ours.stacks, ours.bets, ours.current_seat, len(ours.events)) == before
                    rejected += 1
                else:
                    ours.act(action, amount)  # must not raise
                    accepted += 1
                    break
            else:  # five rejections in a row: make a normal move to keep the hand going
                action, amount = random_move(ours, rng)
                event = ours.act(action, amount)
                assert theirs.place_action(event["player"], action, amount)["ok"]
            if not ours.is_over:
                assert theirs.current_turn == f"p{ours.current_seat}"
                assert [p.stack for p in theirs.players.values()] == ours.stacks
        assert server_results(theirs) == ours.results()
    assert accepted > 1000 and rejected > 1000  # both paths were really exercised
