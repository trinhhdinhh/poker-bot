"""Decide an action.

Later: look up the trained strategy table; if the spot is missing, fall back to a rule
(call/raise when equity beats pot odds, else fold/check). For now only a placeholder
policy exists so the connection infrastructure can be exercised end to end.
"""
from __future__ import annotations

from typing import Optional, Protocol

from bot.action_map import CALL, CHECK
from bot.adapter import HandHistory, Observation

Decision = tuple[str, Optional[int]]  # (fold|check|call|raise, raise target or None)


class Policy(Protocol):
    def act(self, obs: Observation, history: HandHistory) -> Decision: ...


class CheckCallPolicy:
    """Check when free, otherwise call. Never raises, so it can't make sizing mistakes."""

    def act(self, obs: Observation, history: HandHistory) -> Decision:
        return (CHECK, None) if obs.to_call == 0 else (CALL, None)
