"""Abstract action (fold / call / half pot / pot / all-in) -> legal server action.

bet/raise amount = total for this street (int), clamped to [current_bet + minimum_raise, my.bet + my.stack].
"""
