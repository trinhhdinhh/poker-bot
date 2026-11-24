"""Server JSON -> observation (hole cards, board, pot, to_call, position, street, stacks).

Pure parsing, no I/O. Later this module will call abstraction/ to produce the same
infoset key the trainer uses (see `infoset_key`). Never duplicate abstraction logic here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

SUITS = ("hearts", "diamonds", "clubs", "spades")
STREETS = ("PREFLOP", "FLOP", "TURN", "RIVER")


@dataclass(frozen=True)
class Card:
    rank: int  # 2-14 (J=11, Q=12, K=13, A=14)
    suit: str  # hearts | diamonds | clubs | spades


def parse_card(raw: dict) -> Optional[Card]:
    """Parse a server card from rank/suit (never `label`). Hidden cards -> None."""
    rank, suit = raw.get("rank"), raw.get("suit")
    if not isinstance(rank, int) or isinstance(rank, bool) or suit not in SUITS:
        return None
    return Card(rank, suit)


@dataclass(frozen=True)
class PlayerView:
    id: str
    stack: int
    bet: int
    folded: bool
    all_in: bool
    connected: bool
    in_hand: bool  # was dealt cards this hand


@dataclass(frozen=True)
class Observation:
    player_id: str
    match_number: int
    hand_number: int
    phase: str
    hole_cards: tuple[Card, ...]
    board: tuple[Card, ...]
    pot: int
    current_bet: int
    minimum_raise: int
    my_bet: int
    my_stack: int
    small_blind: int
    big_blind: int
    dealer: Optional[str]
    small_blind_player: Optional[str]
    big_blind_player: Optional[str]
    players: tuple[PlayerView, ...]
    is_my_turn: bool
    match_complete: bool

    @property
    def to_call(self) -> int:
        return max(0, self.current_bet - self.my_bet)

    @property
    def dealt_in(self) -> tuple[PlayerView, ...]:
        return tuple(p for p in self.players if p.in_hand)

    @property
    def num_players(self) -> int:
        """Players dealt into this hand."""
        return len(self.dealt_in)

    @property
    def active_opponents(self) -> tuple[PlayerView, ...]:
        """Opponents still in the hand (not folded)."""
        return tuple(p for p in self.dealt_in if p.id != self.player_id and not p.folded)

    @property
    def position(self) -> Optional[int]:
        """Seats after the dealer among dealt-in players: 0 = button, 1 = SB, 2 = BB, ..."""
        order = [p.id for p in self.dealt_in]
        if self.dealer not in order or self.player_id not in order:
            return None
        return (order.index(self.player_id) - order.index(self.dealer)) % len(order)


def parse_state(payload: dict, player_id: str) -> Observation:
    players = tuple(
        PlayerView(
            id=p["id"], stack=int(p["stack"]), bet=int(p["bet"]), folded=bool(p["folded"]),
            all_in=bool(p["all_in"]), connected=bool(p.get("connected", True)),
            in_hand=len(p.get("hole_cards") or []) > 0,
        )
        for p in payload.get("players", [])
    )
    me_raw = next((p for p in payload.get("players", []) if p["id"] == player_id), None)
    hole = tuple(c for c in (parse_card(x) for x in (me_raw or {}).get("hole_cards", [])) if c)
    board = tuple(c for c in (parse_card(x) for x in payload.get("community_cards", [])) if c)
    return Observation(
        player_id=player_id,
        match_number=int(payload.get("match_number", 1)),
        hand_number=int(payload.get("hand_number", 0)),
        phase=payload.get("phase", "WAITING"),
        hole_cards=hole,
        board=board,
        pot=int(payload.get("pot", 0)),
        current_bet=int(payload.get("current_bet", 0)),
        minimum_raise=int(payload.get("minimum_raise", payload.get("big_blind", 0))),
        my_bet=int(me_raw["bet"]) if me_raw else 0,
        my_stack=int(me_raw["stack"]) if me_raw else 0,
        small_blind=int(payload.get("small_blind", 0)),
        big_blind=int(payload.get("big_blind", 0)),
        dealer=payload.get("dealer"),
        small_blind_player=payload.get("small_blind_player"),
        big_blind_player=payload.get("big_blind_player"),
        players=players,
        is_my_turn=payload.get("current_turn") == player_id,
        match_complete=bool(payload.get("match_complete", False)),
    )


def state_signature(payload: dict) -> tuple:
    """Identifies a distinct table state; repeated broadcasts share a signature."""
    return (
        payload.get("match_number"), payload.get("hand_number"), payload.get("phase"),
        payload.get("pot"), payload.get("current_bet"), payload.get("current_turn"),
        len(payload.get("community_cards", [])),
        tuple((p["id"], p["stack"], p["bet"], p["folded"], p["all_in"]) for p in payload.get("players", [])),
    )


@dataclass
class HandHistory:
    """Betting history for the current hand, rebuilt from successive states.

    The server only sends `last_action` (latest event), so we append it whenever the
    table state changes. Each event is tagged with the street it happened on (the phase
    of the state *before* it, because an action that closes a street arrives already
    showing the next phase).
    """
    match_number: Optional[int] = None
    hand_number: Optional[int] = None
    events: list[dict] = field(default_factory=list)
    _last_signature: Optional[tuple] = None
    _last_phase: Optional[str] = None

    def update(self, payload: dict) -> None:
        key = (payload.get("match_number"), payload.get("hand_number"))
        if key != (self.match_number, self.hand_number):
            self.match_number, self.hand_number = key
            self.events, self._last_signature, self._last_phase = [], None, None
        sig = state_signature(payload)
        if sig == self._last_signature:
            return
        event = payload.get("last_action")
        if event and event.get("type") not in (None, "deal", "payout"):
            street = self._last_phase if self._last_phase in STREETS else payload.get("phase")
            self.events.append({**event, "street": street})
        self._last_signature, self._last_phase = sig, payload.get("phase")

    def on_street(self, street: str) -> list[dict]:
        return [e for e in self.events if e.get("street") == street]


def infoset_key(obs: Observation, history: HandHistory) -> str:
    """Abstract infoset key shared with training. Implemented in abstraction/ (build step 3)."""
    raise NotImplementedError("Card/action abstraction not implemented yet")
