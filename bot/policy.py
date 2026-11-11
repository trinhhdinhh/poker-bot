"""Decide an action: look up the trained strategy table; if the spot is missing,
fall back to a rule (call/raise when equity beats pot odds, else fold/check).
"""
