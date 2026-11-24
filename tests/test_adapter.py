from bot.adapter import Card, HandHistory, parse_card, parse_state
from tests.factories import HIDDEN, card, make_state, player


def test_parse_card_uses_rank_and_suit():
    assert parse_card(card(14, "spades")) == Card(14, "spades")
    assert parse_card({"rank": 10, "suit": "hearts", "label": "garbage"}) == Card(10, "hearts")
    assert parse_card(HIDDEN) is None


def test_preflop_observation():
    obs = parse_state(make_state(), "a")
    assert obs.hole_cards == (Card(14, "spades"), Card(13, "spades"))
    assert obs.board == ()
    assert obs.to_call == 10
    assert obs.my_stack == 990 and obs.my_bet == 10
    assert obs.is_my_turn
    assert obs.num_players == 3
    assert obs.position == 1  # small blind (dealer is c)
    assert [p.id for p in obs.active_opponents] == ["b", "c"]


def test_flop_hidden_cards_and_undealt_player():
    state = make_state(
        phase="FLOP", current_bet=0, pot=60, current_turn="b",
        community_cards=[card(2, "hearts"), card(7, "clubs"), card(12, "diamonds")],
        players=[player("a", bet=0, stack=980), player("b", bet=0, hidden=True),
                 player("c", bet=0, folded=True, hidden=True), player("late", bet=0, stack=1000, cards=[])],
    )
    obs = parse_state(state, "a")
    assert len(obs.board) == 3
    assert obs.to_call == 0
    assert not obs.is_my_turn
    assert obs.num_players == 3  # "late" joined mid-hand, not dealt in
    assert [p.id for p in obs.active_opponents] == ["b"]


def test_waiting_state_without_us():
    obs = parse_state(make_state(phase="WAITING", players=[], current_turn=None, dealer=None, current_bet=0), "a")
    assert obs.hole_cards == () and obs.position is None and obs.to_call == 0


def test_history_tracks_actions_dedupes_and_resets():
    h = HandHistory()
    s1 = make_state()
    h.update(s1)
    h.update(s1)  # repeated broadcast
    assert h.events == []  # deal is not a betting event

    s2 = make_state(current_turn="b", last_action={"type": "call", "player": "a", "amount": 10},
                    players=[player("a", stack=980, bet=20), player("b", hidden=True), player("c", bet=0, stack=1000, hidden=True)])
    h.update(s2)
    h.update(s2)
    assert h.events == [{"type": "call", "player": "a", "amount": 10, "street": "PREFLOP"}]

    # BB checks, closing preflop: the state already shows FLOP but the check belongs to PREFLOP.
    s3 = make_state(phase="FLOP", current_bet=0, current_turn="a", last_action={"type": "check", "player": "b"},
                    players=[player("a", bet=0), player("b", bet=0, hidden=True), player("c", bet=0, folded=True, hidden=True)])
    h.update(s3)
    assert h.events[-1]["street"] == "PREFLOP"
    assert len(h.on_street("PREFLOP")) == 2

    h.update(make_state(hand_number=2))
    assert h.events == [] and h.hand_number == 2
