"""Loads the real server's rules engine (./ai-poker-server/app/engine.py) as a reference.

Our engine must behave exactly like the server, so tests run both on the same input and compare.
The server's engine.py is pure Python with no dependencies, so we import it straight from the
file. Tests that use it are skipped when the server checkout is missing.
"""
from __future__ import annotations
import importlib.util
import random
from pathlib import Path
import pytest

from engine.cards import shuffled_deck

SERVER_ENGINE = Path(__file__).resolve().parent.parent / "ai-poker-server" / "app" / "engine.py"

requires_server = pytest.mark.skipif(not SERVER_ENGINE.exists(), reason="ai-poker-server checkout not found")


def load_server_engine():
    spec = importlib.util.spec_from_file_location("server_engine", SERVER_ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def server_hand(server, n: int, button: int, seed: int):
    """The server's engine set up like HoldemHand(n, button, Random(seed)): same seats, same deck."""
    engine = server.PokerEngine()
    for i in range(n):
        engine.add_player(f"p{i}", f"p{i}")
    deck = [server.Card(c.rank, server.Suit(c.suit)) for c in shuffled_deck(random.Random(seed))]
    engine._build_deck = lambda: deck
    engine.dealer_index = button - 1  # start_hand moves the button one seat on
    engine.start_hand()
    return engine
