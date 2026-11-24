from bot.action_map import legal_actions, safe_fallback, to_server_action
from bot.adapter import parse_state
from tests.factories import make_state, player


def obs_of(**kw):
    return parse_state(make_state(**kw), "a")


def act(obs, kind, target=None):
    return to_server_action(obs, kind, target)


def test_check_vs_call():
    facing = obs_of()
    assert act(facing, "check") == {"type": "action", "action": "fold"}  # can't check facing a bet
    assert act(facing, "call") == {"type": "action", "action": "call"}
    free = obs_of(current_bet=10)
    assert act(free, "call") == {"type": "action", "action": "check"}
    assert act(free, "fold") == {"type": "action", "action": "check"}  # never fold for free


def test_no_amount_on_non_raise_actions():
    for kind in ("fold", "check", "call"):
        assert "amount" not in act(obs_of(), kind)


def test_raise_is_clamped_to_legal_range():
    obs = obs_of()  # current_bet 20, min raise 20, my bet 10 + stack 990
    legal = legal_actions(obs)
    assert (legal.min_target, legal.max_target) == (40, 1000)
    assert act(obs, "raise", 25)["amount"] == 40
    assert act(obs, "raise", 5000)["amount"] == 1000
    assert act(obs, "raise", 75.9)["amount"] == 75
    assert isinstance(act(obs, "raise", 75.9)["amount"], int)
    assert act(obs, "raise")["amount"] == 40


def test_short_stack_raise_becomes_all_in():
    obs = obs_of(players=[player("a", stack=15, bet=10), player("b", hidden=True), player("c", bet=0, hidden=True)])
    legal = legal_actions(obs)
    assert legal.can_raise and legal.min_target == legal.max_target == 25
    assert act(obs, "raise", 200) == {"type": "action", "action": "raise", "amount": 25}


def test_cannot_raise_when_stack_only_covers_call():
    obs = obs_of(players=[player("a", stack=5, bet=10), player("b", hidden=True), player("c", bet=0, hidden=True)])
    assert not legal_actions(obs).can_raise
    assert act(obs, "raise", 500) == {"type": "action", "action": "call"}


def test_cannot_raise_against_only_all_in_opponents():
    obs = obs_of(players=[player("a", stack=990, bet=10), player("b", stack=0, bet=20, all_in=True, hidden=True),
                          player("c", bet=0, folded=True, hidden=True)])
    assert act(obs, "raise", 100) == {"type": "action", "action": "call"}


def test_safe_fallback():
    assert safe_fallback(obs_of(current_bet=10))["action"] == "check"
    assert safe_fallback(obs_of())["action"] == "call"  # to_call 10 <= BB
    assert safe_fallback(obs_of(current_bet=200))["action"] == "fold"
