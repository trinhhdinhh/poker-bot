import random

import pytest

from bot.action_map import ABSTRACT, to_server_action


def make(cur=20, min_raise=20, pot=30, bet=0, stack=1000):
    # Build a fake (state, me). Defaults = preflop, we're not in a blind, facing the 20 big blind.
    state = {"current_bet": cur, "minimum_raise": min_raise, "pot": pot}
    me = {"bet": bet, "stack": stack}
    return state, me


# --- fold / check / call -----------------------------------------------------

def test_fold_when_facing_a_bet():
    state, me = make()                              # Arrange
    result = to_server_action("fold", state, me)    # Act
    assert result["action"] == "fold"               # Assert


def test_fold_becomes_check_when_free():
    # Big blind, nobody raised: folding would throw away a free look.
    state, me = make(bet=20)
    assert to_server_action("fold", state, me)["action"] == "check"


def test_call_when_facing_a_bet():
    state, me = make()
    assert to_server_action("call", state, me)["action"] == "call"


def test_call_becomes_check_when_nothing_to_call():
    state, me = make(bet=20)
    assert to_server_action("call", state, me)["action"] == "check"


@pytest.mark.parametrize("abstract", ["half_pot", "pot", "allin"])
def test_too_short_to_raise_calls_instead(abstract):
    # 15 chips facing a 20 bet: any raise is impossible, so it's an all-in call.
    state, me = make(stack=15)
    assert to_server_action(abstract, state, me)["action"] == "call"


@pytest.mark.parametrize("abstract", ["half_pot", "pot", "allin"])
def test_stack_exactly_covers_call_calls(abstract):
    # bet + stack == current_bet: calling puts us all-in, there is nothing left to raise with.
    state, me = make(bet=0, stack=20)
    assert to_server_action(abstract, state, me)["action"] == "call"


# --- raise sizes ---------------------------------------------------------------

@pytest.mark.parametrize("abstract, kwargs, amount", [
    ("half_pot", {},                                   45),    # 20 + int(0.5 * (30 + 20))
    ("pot",      {},                                   70),    # 20 + (30 + 20)
    ("allin",    {},                                   1000),  # bet 0 + stack 1000
    ("half_pot", {"cur": 0, "pot": 20},                20),    # target 10, raised to min 0 + 20
    ("pot",      {"cur": 0, "pot": 200, "stack": 50},  50),    # target 200, capped at stack
    ("allin",    {"bet": 20, "stack": 980},            1000),  # big blind shoves: total = 20 + 980
    ("pot",      {"cur": 100, "min_raise": 80, "pot": 250, "bet": 20}, 430),  # 100 + (250 + 80)
])
def test_raise_sizes(abstract, kwargs, amount):
    state, me = make(**kwargs)
    result = to_server_action(abstract, state, me)
    assert result == {"type": "action", "action": "raise", "amount": amount}


def test_short_all_in_below_min_raise():
    # 150 chips facing 100 with min raise 100: min target 200 is out of reach, so we shove 150.
    # NOTE: assumes the server accepts a short all-in raise. Check app/engine.py; if it rejects
    # these, change to_server_action to call here and update this test.
    state, me = make(cur=100, min_raise=100, pot=200, stack=150)
    assert to_server_action("pot", state, me) == {"type": "action", "action": "raise", "amount": 150}


def test_amount_is_int_with_odd_pot():
    # Half of an odd pot is a float; the server only accepts integers.
    state, me = make(cur=0, pot=75)
    result = to_server_action("half_pot", state, me)
    assert isinstance(result["amount"], int)
    assert result["amount"] == 37


def test_fold_and_call_omit_amount():
    state, me = make()
    assert "amount" not in to_server_action("fold", state, me)
    assert "amount" not in to_server_action("call", state, me)


# --- rules that must always hold ----------------------------------------------

def test_always_legal_on_random_states():
    rng = random.Random(0)          # fixed seed, so a failure is reproducible
    for _ in range(5000):
        cur = rng.choice([0, 20, 40, 100, 300])
        state, me = make(cur=cur, min_raise=rng.choice([20, 40, 100]),
                         pot=rng.randint(30, 2000),
                         bet=rng.randint(0, cur), stack=rng.randint(0, 1000))
        min_to = cur + state["minimum_raise"]
        max_to = me["bet"] + me["stack"]
        for a in ABSTRACT:
            r = to_server_action(a, state, me)
            assert r["type"] == "action"
            assert r["action"] in ("fold", "check", "call", "raise")
            if r["action"] == "check":
                assert me["bet"] == cur
            if r["action"] == "fold":
                assert me["bet"] < cur                  # never fold when checking is free
            if r["action"] == "raise":
                assert isinstance(r["amount"], int)
                assert cur < r["amount"] <= max_to
                assert r["amount"] >= min_to or r["amount"] == max_to   # short all-in only
