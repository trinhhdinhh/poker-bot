"""Unit tests for engine/holdem.py: the rules, one situation at a time.
Comparisons against the real server's engine live in test_engine_vs_server.py."""
import random

import pytest

from engine.cards import FULL_DECK, to_pk
from engine.holdem import HoldemHand


def test_to_pk_card_names():
    names = {to_pk(c) for c in FULL_DECK}
    assert len(names) == 52 and {"As", "Th", "2c", "Kd"} <= names


@pytest.mark.parametrize("n", range(2, 10))
def test_seat_mapping_round_trips(n):
    for button in range(n):
        hand = HoldemHand(n, button, random.Random(0))
        assert [hand.index_of(hand.seat_of(i)) for i in range(n)] == list(range(n))
        assert hand.seat_of(n - 1) == button  # PokerKit's last index is the button


def test_three_players_blinds_and_first_actor():
    hand = HoldemHand(3, button=1, rng=random.Random(0))
    assert (hand.small_blind_seat, hand.big_blind_seat) == (2, 0)
    assert hand.bets == [20, 0, 10]
    assert hand.stacks == [980, 1000, 990]
    assert hand.pot == 30
    assert hand.current_seat == 1  # 3-handed, the button acts first preflop
    assert hand.phase == "PREFLOP"


def test_heads_up_button_posts_small_blind_and_acts_first():
    hand = HoldemHand(2, button=0, rng=random.Random(0))
    assert hand.bets == [10, 20]
    assert hand.current_seat == 0


def test_same_seed_same_cards_and_all_cards_distinct():
    a, b = HoldemHand(6, 0, random.Random(5)), HoldemHand(6, 0, random.Random(5))
    assert a.hole_cards == b.hole_cards
    dealt = [c for h in a.hole_cards for c in h]
    assert len(set(dealt)) == 12 and len(a.deck) == 52 - 12


def test_pokerkit_holds_the_cards_we_dealt():
    hand = HoldemHand(4, button=2, rng=random.Random(1))
    for seat in range(4):
        pk_cards = [repr(c) for c in hand.state.hole_cards[hand.index_of(seat)]]
        assert pk_cards == [to_pk(c) for c in hand.hole_cards[seat]]


def check_down(hand: HoldemHand) -> None:
    """Everyone just calls/checks to showdown."""
    while not hand.is_over:
        hand.act("check" if hand.legal_actions().can_check else "call")


def test_check_down_deals_a_full_board_with_no_pokerkit_warnings(recwarn):
    hand = HoldemHand(5, button=3, rng=random.Random(2))
    check_down(hand)
    assert len(hand.board) == 5 and hand.phase == "WAITING"
    assert len(hand.deck) == 52 - 10 - 3 - 5  # holes, 3 burns, board
    assert not [w for w in recwarn if "pokerkit" in str(w.filename)]


# ---- actions ------------------------------------------------------------------------------

def three_handed() -> HoldemHand:
    """3 players, button = seat 0 -> SB = seat 1, BB = seat 2, seat 0 acts first."""
    return HoldemHand(3, button=0, rng=random.Random(0))


def test_preflop_legal_actions():
    legal = three_handed().legal_actions()
    assert (legal.can_check, legal.can_call, legal.can_raise) == (False, True, True)
    assert (legal.min_target, legal.max_target) == (40, 1000)


def test_events_use_the_server_format():
    hand = three_handed()
    hand.act("raise", 60)
    hand.act("call")
    hand.act("fold")
    assert hand.events == [
        {"type": "raise", "player": "p0", "amount": 60, "target": 60, "street": "PREFLOP"},
        {"type": "call", "player": "p1", "amount": 50, "street": "PREFLOP"},
        {"type": "fold", "player": "p2", "street": "PREFLOP"},
    ]
    assert hand.phase == "FLOP" and len(hand.board) == 3 and hand.pot == 140


def test_min_raise_follows_the_last_full_raise_and_resets_each_street():
    hand = three_handed()
    hand.act("raise", 60)                          # raised by 40
    assert hand.legal_actions().min_target == 100  # next raise must add 40 again
    hand.act("raise", 200)                         # raised by 140
    assert hand.legal_actions().min_target == 340
    hand.act("call"); hand.act("call")
    assert hand.phase == "FLOP" and hand.minimum_raise == 20


@pytest.mark.parametrize("action, amount", [
    ("check", 0),        # facing the big blind
    ("raise", 39),       # less than a full raise and not all-in
    ("raise", 1001),     # more than the stack
    ("bet", 100),        # "bet" only when nobody has bet yet; preflop the big blind counts
    ("call", 20),        # call/check/fold never carry an amount
    ("raise", 50.5),     # integers only
    ("shove", 0),
])
def test_illegal_moves_are_rejected_and_change_nothing(action, amount):
    hand = three_handed()
    before = (hand.stacks, hand.bets, hand.current_seat, hand.events[:])
    with pytest.raises(ValueError):
        hand.act(action, amount)
    assert (hand.stacks, hand.bets, hand.current_seat, hand.events) == before


def test_bet_opens_a_street_and_fold_is_allowed_even_when_check_is_free():
    hand = three_handed()
    hand.act("call"); hand.act("call"); hand.act("check")  # to the flop
    hand.act("bet", 20)
    assert hand.current_bet == 20
    hand = three_handed()
    hand.act("call"); hand.act("call"); hand.act("fold")   # BB folds instead of checking
    assert hand.phase == "FLOP"


def test_all_in_and_call_runs_out_the_board():
    hand = three_handed()
    hand.act("raise", 1000)
    assert hand.legal_actions().can_raise is False  # all-in can't be re-raised: same stacks
    hand.act("fold")
    hand.act("call")
    assert hand.is_over and len(hand.board) == 5
    assert sorted(hand.results()) in ([-1000, -10, 1010], [-505, -10, 515])  # win, or split


# ---- observations ---------------------------------------------------------------------------

def test_observation_shows_own_cards_and_public_table():
    hand = three_handed()
    hand.act("raise", 60)
    obs = hand.observation(1)  # the small blind, now facing 60
    assert obs.player_id == "p1" and obs.is_my_turn and obs.phase == "PREFLOP"
    assert obs.hole_cards == hand.hole_cards[1] and obs.board == ()
    assert (obs.pot, obs.current_bet, obs.my_bet, obs.to_call, obs.my_stack) == (90, 60, 10, 50, 990)
    assert (obs.dealer, obs.small_blind_player, obs.big_blind_player) == ("p0", "p1", "p2")
    assert obs.position == 1 and obs.num_players == 3
    assert not hand.observation(2).is_my_turn
