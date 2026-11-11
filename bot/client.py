"""Live server client: WebSocket loop. Join, read state messages, act only on our turn.

Run: python -m bot.client <player_id>
Base on the server's scripts/student_bot.py. Dedupe repeated broadcasts, track pending,
build betting history across states, reset on new hand_number. Every decision < 2s;
on error/timeout: check if legal, else fold.
"""
