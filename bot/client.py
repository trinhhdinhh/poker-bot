"""Live server client: WebSocket loop. Join, read state messages, act only on our turn.

Run: python -m bot.client <player_id> [--url ws://host:8000/ws] [--name NAME] [--hands N]

Based on the server's scripts/student_bot.py: dedupe repeated broadcasts, track `pending`,
build betting history across states, reset on new hand_number. Every decision < 2s;
on error/timeout: check if legal, else call if tiny, else fold.

`BotSession` holds all protocol logic and does no I/O (unit-testable);
`BotClient` owns the socket, reconnects, and decides when to stop.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import websockets

from bot.action_map import safe_fallback, to_server_action
from bot.adapter import HandHistory, Observation, parse_state, state_signature
from bot.policy import CheckCallPolicy, Policy

log = logging.getLogger("bot")

DEFAULT_URL = os.environ.get("POKER_WS_URL", "ws://localhost:8000/ws")
DECISION_TIMEOUT_SECONDS = 2.0  # server default turn limit is 5s
REPLACED_BY_RECONNECT = 4001    # server closes the old socket when our id joins elsewhere


@dataclass
class SessionStats:
    actions_sent: int = 0
    rejections: int = 0
    fallbacks: int = 0
    our_timeouts: int = 0
    errors: list[str] = field(default_factory=list)
    hands_completed: set = field(default_factory=set)  # (match_number, hand_number) we were dealt into, paid out


class BotSession:
    def __init__(self, player_id: str, policy: Optional[Policy] = None,
                 decision_timeout: float = DECISION_TIMEOUT_SECONDS):
        self.player_id = player_id
        self.policy = policy or CheckCallPolicy()
        self.decision_timeout = decision_timeout
        self.history = HandHistory()
        self.stats = SessionStats()
        self.obs: Optional[Observation] = None
        self.match_complete = False
        self.pending = False
        self._turn_key: Optional[tuple] = None  # turn we last acted on
        self._tried: list[dict] = []            # messages sent for that turn
        self._last_sig: Optional[tuple] = None

    def reset_connection(self) -> None:
        """Call after (re)connecting: nothing is in flight on the new socket."""
        self.pending = False

    @staticmethod
    def turn_key(payload: dict) -> tuple:
        return (payload.get("match_number"), payload.get("hand_number"), payload.get("phase"),
                payload.get("current_bet"),
                tuple((p["id"], p["bet"], p["folded"], p["all_in"]) for p in payload.get("players", [])))

    async def handle(self, message: dict) -> list[dict]:
        """Process one server message; return the messages to send back."""
        kind = message.get("type")
        if kind == "state":
            return await self._on_state(message.get("payload") or {})
        if kind == "action_result":
            payload = message.get("payload") or {}
            self.pending = False
            if payload.get("ok"):
                return []
            self.stats.rejections += 1
            log.warning("Rejected %s: %s", self._tried[-1] if self._tried else None, payload.get("error"))
            return self._retry_after_rejection()
        if kind == "error":
            text = message.get("message", "")
            self.stats.errors.append(text)
            log.warning("Server error: %s", text)
            if self.pending:  # our action was malformed
                self.pending = False
                return self._retry_after_rejection()
            return []
        return []  # pong / unknown

    async def _on_state(self, payload: dict) -> list[dict]:
        self.history.update(payload)
        obs = parse_state(payload, self.player_id)
        self.obs = obs
        self.match_complete = obs.match_complete

        sig = state_signature(payload)
        if sig != self._last_sig:
            self._last_sig = sig
            event = payload.get("last_action") or {}
            timeout = event.get("timeout")
            if timeout and timeout.get("player") == self.player_id:
                self.stats.our_timeouts += 1
                log.error("We timed out; server auto-%sed", timeout.get("action"))
            hand = (obs.match_number, obs.hand_number)
            dealt_in = any(p.id == self.player_id and p.in_hand for p in obs.players)
            # The payout event is re-sent (SHOWDOWN, then WAITING); count each hand we played once.
            if event.get("type") == "payout" and dealt_in and hand not in self.stats.hands_completed:
                self.stats.hands_completed.add(hand)
                log.info("Hand %s over: winners=%s pot=%s", obs.hand_number, event.get("winners"), event.get("pot"))

        if self.pending or not obs.is_my_turn:
            return []
        key = self.turn_key(payload)
        if key == self._turn_key:
            return []  # repeated broadcast of a turn we already answered
        action = await self._decide(obs)
        self._turn_key, self._tried = key, [action]
        return self._send(action)

    async def _decide(self, obs: Observation) -> dict:
        try:
            kind, target = await asyncio.wait_for(
                asyncio.to_thread(self.policy.act, obs, self.history), self.decision_timeout)
            return to_server_action(obs, kind, target)
        except Exception as exc:  # includes TimeoutError
            self.stats.fallbacks += 1
            log.error("Policy failed (%s: %s); using safe fallback", type(exc).__name__, exc)
            return safe_fallback(obs)

    def _retry_after_rejection(self) -> list[dict]:
        """Never resend the same move: try safe fallback, then the minimal legal action."""
        obs = self.obs
        if obs is None or not obs.is_my_turn:
            return []
        minimal = {"type": "action", "action": "check" if obs.to_call == 0 else "fold"}
        for candidate in (safe_fallback(obs), minimal):
            if candidate not in self._tried:
                self._tried.append(candidate)
                self.stats.fallbacks += 1
                return self._send(candidate)
        return []

    def _send(self, action: dict) -> list[dict]:
        obs = self.obs
        self.pending = True
        self.stats.actions_sent += 1
        if obs is not None:
            log.info("Hand %s %s: %s%s (to_call=%s pot=%s stack=%s)", obs.hand_number, obs.phase,
                     action["action"], f" to {action['amount']}" if "amount" in action else "",
                     obs.to_call, obs.pot, obs.my_stack)
        return [action]


class BotClient:
    def __init__(self, player_id: str, url: str = DEFAULT_URL, name: Optional[str] = None,
                 policy: Optional[Policy] = None, stop_after_hands: Optional[int] = None,
                 stay_after_match: bool = False, reconnect: bool = True):
        self.player_id = player_id
        self.url = url
        self.name = name or player_id
        self.session = BotSession(player_id, policy)
        self.stop_after_hands = stop_after_hands
        self.stay_after_match = stay_after_match
        self.reconnect = reconnect

    def _should_stop(self) -> bool:
        if self.stop_after_hands is not None and len(self.session.stats.hands_completed) >= self.stop_after_hands:
            log.info("Played %d hands; stopping", len(self.session.stats.hands_completed))
            return True
        if self.session.match_complete and not self.stay_after_match:
            log.info("Match complete; stopping")
            return True
        return False

    async def run(self) -> SessionStats:
        attempt = 0
        while True:
            try:
                async with websockets.connect(self.url) as ws:
                    attempt = 0
                    self.session.reset_connection()
                    await ws.send(json.dumps({"type": "join", "player_id": self.player_id, "name": self.name}))
                    log.info("Connected to %s as %s", self.url, self.player_id)
                    async for raw in ws:
                        try:
                            message = json.loads(raw)
                        except json.JSONDecodeError:
                            log.warning("Ignoring non-JSON message: %r", raw[:200])
                            continue
                        log.debug("<- %s", raw)
                        for out in await self.session.handle(message):
                            log.debug("-> %s", out)
                            await ws.send(json.dumps(out))
                        if self._should_stop():
                            return self.session.stats
            except websockets.ConnectionClosed as exc:
                code = exc.rcvd.code if exc.rcvd else None
                if code == REPLACED_BY_RECONNECT:
                    log.error("Another connection joined as %s; exiting", self.player_id)
                    return self.session.stats
                log.warning("Connection closed (code=%s)", code)
            except OSError as exc:
                log.warning("Cannot connect to %s: %s", self.url, exc)
            if not self.reconnect:
                return self.session.stats
            attempt += 1
            delay = min(2 ** attempt, 10)
            log.info("Reconnecting in %ss", delay)
            await asyncio.sleep(delay)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Bayou Poker bot client")
    parser.add_argument("player_id")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--name", default=None)
    parser.add_argument("--hands", type=int, default=None, help="stop after N completed hands")
    parser.add_argument("--stay", action="store_true", help="keep running after the match completes")
    parser.add_argument("--no-reconnect", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true", help="log raw messages")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    client = BotClient(args.player_id, args.url, args.name, stop_after_hands=args.hands,
                       stay_after_match=args.stay, reconnect=not args.no_reconnect)
    try:
        stats = asyncio.run(client.run())
    except KeyboardInterrupt:
        return
    log.info("Done: %d hands, %d actions, %d rejections, %d fallbacks, %d timeouts",
             len(stats.hands_completed), stats.actions_sent, stats.rejections, stats.fallbacks, stats.our_timeouts)


if __name__ == "__main__":
    main()
