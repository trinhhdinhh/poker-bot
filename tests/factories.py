"""Builders for fake server `state` payloads, shaped like app/engine.py PokerEngine.snapshot()."""
from __future__ import annotations

import copy

HIDDEN = {"rank": "?", "suit": "?", "label": "??"}


def card(rank: int, suit: str) -> dict:
    return {"rank": rank, "suit": suit, "label": f"{rank}{suit[0].upper()}"}


def player(pid: str, stack=980, bet=20, folded=False, all_in=False, cards=None, hidden=False) -> dict:
    hole = cards if cards is not None else ([HIDDEN, HIDDEN] if hidden else [card(14, "spades"), card(13, "spades")])
    return {"id": pid, "name": pid, "stack": stack, "bet": bet, "folded": folded, "all_in": all_in,
            "connected": True, "hole_cards": hole, "profit_loss": 0, "hands_played": 0}


def make_state(**overrides) -> dict:
    """Default: 3-handed preflop, dealer=c, SB=a, BB=b, `a` (us) to act facing the BB."""
    state = {
        "phase": "PREFLOP", "pot": 30, "community_cards": [],
        "players": [
            player("a", stack=990, bet=10),
            player("b", stack=980, bet=20, hidden=True),
            player("c", stack=1000, bet=0, hidden=True),
        ],
        "current_turn": "a", "dealer": "c", "small_blind_player": "a", "big_blind_player": "b",
        "hand_number": 1, "last_action": {"type": "deal", "dealer": "c", "small_blind": "a", "big_blind": "b"},
        "small_blind": 10, "big_blind": 20, "current_bet": 20, "minimum_raise": 20,
        "starting_stack": 1000, "max_hands": 100, "hands_completed": 0, "match_complete": False,
        "match_number": 1, "can_start": False, "running": False, "paused": False,
        "speed": {"action_delay": 0.0, "showdown_reveal": 3.0},
    }
    state.update(copy.deepcopy(overrides))
    return state


def msg(payload: dict) -> dict:
    return {"type": "state", "payload": payload}
