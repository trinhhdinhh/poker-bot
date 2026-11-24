"""State encoding, SHARED by training and the live bot.

Turns an observation (from engine/ during training, from bot/adapter.py live) into a fixed-size
float vector for the Q-network. Planned features:
- cards: one-hot 52 for our hole cards, one-hot 52 for the board (no bucketing; the net learns it)
- street (one-hot 4), number of players dealt in, players still active, our position from the button
- money in big blinds: pot, to_call, our stack, our street bet, each opponent's stack/bet (padded to max seats)
- betting history: the last K actions as (street, relative seat, action type, size in pot fractions)
Any change to this file changes the input layout and invalidates trained models (bump ENCODING_VERSION).
"""
ENCODING_VERSION = 0
