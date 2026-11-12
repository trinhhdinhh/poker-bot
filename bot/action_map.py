"""Abstract action (fold / call / half pot / pot / all-in) -> legal server action.

bet/raise amount = total for this street (int), clamped to [current_bet + minimum_raise, my.bet + my.stack].
"""

ABSTRACT = ("fold", "call", "half_pot", "pot", "allin")

def to_server_action(abstract: str, state: dict, me: dict) -> dict:
    cur, mine, stack = state["current_bet"], me["bet"], me["stack"]
    to_call = max(0, cur - mine)
    max_to = mine + stack                      # all-in target
    min_to = cur + state["minimum_raise"]

    if abstract == "fold":
        return {"type": "action", "action": "check"} if to_call == 0 else {"type": "action", "action": "fold"}
    if abstract == "call" or max_to <= cur:    # can't raise: check or call
        return {"type": "action", "action": "check" if to_call == 0 else "call"}

    if abstract == "allin":
        target = max_to
    else:
        frac = 0.5 if abstract == "half_pot" else 1.0
        target = cur + int(frac * (state["pot"] + to_call))
    target = min(max(target, min_to), max_to)  # clamp to the legal range
    return {"type": "action", "action": "raise", "amount": int(target)}


