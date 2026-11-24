"""End-to-end: start the real Bayou Poker Server, connect three of our bots, play hands.

Needs the server checkout at ./ai-poker-server and its deps (pip install -r requirements-dev.txt).
Skipped automatically if either is missing. Run alone with: pytest -m integration
"""
import asyncio
import importlib.util
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
import websockets

from bot.client import BotClient

SERVER_DIR = Path(__file__).resolve().parent.parent / "ai-poker-server"
HANDS = 3

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (SERVER_DIR / "app" / "server.py").exists(), reason="ai-poker-server checkout not found"),
    pytest.mark.skipif(importlib.util.find_spec("fastapi") is None or importlib.util.find_spec("uvicorn") is None,
                       reason="server deps missing: pip install -r requirements-dev.txt"),
]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_url():
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=SERVER_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.time() + 15
        while True:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                break
            except OSError:
                if proc.poll() is not None or time.time() > deadline:
                    out = proc.stdout.read().decode() if proc.stdout else ""
                    pytest.fail(f"server did not start:\n{out}")
                time.sleep(0.2)
        yield f"ws://127.0.0.1:{port}/ws"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


async def dealer(url: str, players: int, hands: int, done: asyncio.Event) -> None:
    """Observer that deals the next hand whenever the table is idle (the instructor's Start button)."""
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "observe"}))
        requested_for = None
        while not done.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            message = json.loads(raw)
            if message.get("type") != "state":
                continue
            state = message["payload"]
            connected = sum(p["connected"] for p in state["players"])
            if (state["phase"] == "WAITING" and state["can_start"] and not state["paused"]
                    and connected >= players and state["hands_completed"] < hands
                    and requested_for != state["hands_completed"]):
                requested_for = state["hands_completed"]
                await ws.send(json.dumps({"type": "start_hand"}))


def test_bots_play_full_hands_against_real_server(server_url):
    async def scenario():
        bots = [BotClient(f"test-{i}", server_url, stop_after_hands=HANDS, reconnect=False) for i in range(3)]
        done = asyncio.Event()
        dealer_task = asyncio.create_task(dealer(server_url, len(bots), HANDS, done))
        try:
            return await asyncio.wait_for(asyncio.gather(*(b.run() for b in bots)), timeout=60)
        finally:
            done.set()
            await dealer_task

    all_stats = asyncio.run(scenario())
    for stats in all_stats:
        assert len(stats.hands_completed) >= HANDS
        assert stats.actions_sent > 0
        assert stats.rejections == 0, stats.errors
        assert stats.our_timeouts == 0
        assert stats.errors == []
