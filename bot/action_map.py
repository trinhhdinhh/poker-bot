"""Menu action (fold / check-call / raise to X, see features/actions.py) -> a legal server action.

Server rules (ai-poker-server README + app/engine.py place_action):
- bet/raise `amount` = total for this street (int), in [current_bet + minimum_raise, my.bet + my.stack];
  only an all-in (target == my.bet + my.stack) may be smaller than a full raise.
- check only when my.bet == current_bet; call/check/fold must not carry an amount.
- No raising when every other live player is all-in.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bot.adapter import Observation

FOLD, CHECK, CALL, RAISE = "fold", "check", "call", "raise"


@dataclass(frozen=True)
class Legal:
    can_check: bool
    can_call: bool
    can_raise: bool
    min_target: int  # smallest legal raise target (may be the all-in amount)
    max_target: int  # all-in target


def legal_actions(obs: Observation) -> Legal:
    to_call = obs.to_call
    max_target = obs.my_bet + obs.my_stack
    full_min = obs.current_bet + max(obs.minimum_raise, 1)
    opponents_can_act = any(not p.all_in for p in obs.active_opponents)
    can_raise = opponents_can_act and max_target > obs.current_bet
    return Legal(
        can_check=to_call == 0,
        can_call=to_call > 0,
        can_raise=can_raise,
        min_target=min(full_min, max_target),
        max_target=max_target,
    )


def to_server_action(obs: Observation, kind: str, target: Optional[int] = None) -> dict:
    """Map a desired action to a legal server message, degrading gracefully."""
    legal = legal_actions(obs)
    if kind == RAISE:
        if not legal.can_raise:
            kind = CALL
        else:
            amount = legal.min_target if target is None else int(target)
            amount = max(legal.min_target, min(amount, legal.max_target))
            return {"type": "action", "action": RAISE, "amount": amount}
    if kind == CALL and not legal.can_call:
        kind = CHECK
    if kind == CHECK and not legal.can_check:
        kind = FOLD
    if kind == FOLD and legal.can_check:
        kind = CHECK  # never fold when checking is free
    return {"type": "action", "action": kind}


def safe_fallback(obs: Observation) -> dict:
    """Used on errors/timeouts: check if legal, call if cheap (<= 1 big blind), else fold."""
    if obs.to_call == 0:
        return {"type": "action", "action": CHECK}
    if obs.to_call <= max(obs.big_blind, 1):
        return {"type": "action", "action": CALL}
    return {"type": "action", "action": FOLD}
