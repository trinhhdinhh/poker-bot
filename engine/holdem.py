"""Offline No-Limit Hold'em simulator for self-play, built on PokerKit and matching the server's rules.

PokerKit enforces the betting rules (blinds, min-raise, all-ins, side pots, showdown, payouts).
This wrapper adds what our project needs on top:
  * our own seats and button: seat k is the k-th player at the table, like the server's player order;
  * dealing from our own seeded deck, in the server's order, so a seed replays a hand exactly and
    tests can give the server's engine the identical deck;
  * actions in the server's vocabulary and rules, with an event log in the live bot's format;
  * settling the pot exactly like the server (`results`), odd chips included;
  * `observation(seat)`: the same `Observation` the live bot parses from server JSON, so
    features/ has exactly one input format for training and for play.
"""
from __future__ import annotations

import random
import warnings
from typing import Optional

from pokerkit import Automation, Mode, NoLimitTexasHoldem

from bot.action_map import CALL, CHECK, FOLD, RAISE, Legal
from bot.adapter import STREETS, Card, Observation, PlayerView
from engine.cards import shuffled_deck, to_pk
from engine.evaluator import evaluate

STARTING_STACK, SMALL_BLIND, BIG_BLIND = 1000, 10, 20
MAX_PLAYERS = 20  # same limit as the server
BET = "bet"

# The chores PokerKit does for us automatically. Deliberately missing:
#  * HOLE_DEALING, BOARD_DEALING, CARD_BURNING -- we deal and burn from our own deck (otherwise
#    PokerKit burns from its own shuffled deck and can burn a card we later deal);
#  * HOLE_CARDS_SHOWING_OR_MUCKING, HAND_KILLING -- the showdown. `results()` settles pots itself
#    (like the server), so PokerKit's showdown is unused work: it was 76% of the engine's run time.
#    Without them PokerKit stops when the betting is over, and we finish the hand ourselves.
_AUTOMATIONS = (
    Automation.ANTE_POSTING,
    Automation.BET_COLLECTION,
    Automation.BLIND_OR_STRADDLE_POSTING,
    Automation.CHIPS_PUSHING,
    Automation.CHIPS_PULLING,
    Automation.RUNOUT_COUNT_SELECTION,  # cash-game mode asks "run it once or twice?"; this answers once
)


class HoldemHand:
    """One hand of No-Limit Hold'em. Every hand starts fresh (stacks reset), like on the server.

    Seats are numbered 0..n-1 around the table; `button` is the dealer's seat.
    PokerKit numbers players differently: index 0 = first seat left of the button (the small blind
    for 3+ players), ..., last index = the button. `index_of` / `seat_of` convert between the two.
    """

    def __init__(self, n_players: int, button: int = 0, rng: Optional[random.Random] = None,
                 player_ids: Optional[tuple[str, ...]] = None, stack: int = STARTING_STACK,
                 small_blind: int = SMALL_BLIND, big_blind: int = BIG_BLIND, hand_number: int = 1):
        if not 2 <= n_players <= MAX_PLAYERS:
            raise ValueError(f"n_players must be 2..{MAX_PLAYERS}")
        if not 0 <= button < n_players:
            raise ValueError("button must be a seat number")
        self.n = n_players
        self.button = button
        self.player_ids = tuple(player_ids) if player_ids else tuple(f"p{i}" for i in range(n_players))
        if len(self.player_ids) != n_players or len(set(self.player_ids)) != n_players:
            raise ValueError("need one unique player id per seat")
        self.small_blind, self.big_blind = small_blind, big_blind
        self.hand_number = hand_number  # only shown in observations (the server counts hands per match)

        # Who posts the blinds. Heads-up is special: the button posts the small blind (server rule,
        # and PokerKit does the same -- confirmed in step A).
        if n_players == 2:
            self.small_blind_seat, self.big_blind_seat = button, (button + 1) % 2
        else:
            self.small_blind_seat, self.big_blind_seat = (button + 1) % n_players, (button + 2) % n_players

        self.deck: list[Card] = shuffled_deck(rng or random.Random())
        self.board: list[Card] = []
        self.folded = [False] * n_players
        self.events: list[dict] = []          # every action, like bot.adapter.HandHistory.events
        self.minimum_raise = big_blind        # server's `minimum_raise`: smallest legal raise INCREMENT

        # Creating the state posts the blinds (automated); then PokerKit waits for hole cards.
        self.state = NoLimitTexasHoldem.create_state(
            _AUTOMATIONS,
            True,                      # ante trimming (irrelevant: no antes)
            0,                         # antes
            (small_blind, big_blind),  # blinds
            big_blind,                 # minimum bet = 1 big blind
            (stack,) * n_players,      # everyone starts with the same stack
            n_players,
            # Cash-game mode lets a player fold even when checking is free. The server allows that
            # too; PokerKit's default tournament mode refuses it.
            mode=Mode.CASH_GAME,
        )
        self.contributed = self.bets          # chips each seat has put in this hand (blinds so far)
        self.hole_cards: tuple[tuple[Card, ...], ...] = self._deal_hole_cards()

    # ---- seats <-> PokerKit indices -------------------------------------------------------------
    def seat_of(self, index: int) -> int:
        return (self.button + 1 + index) % self.n

    def index_of(self, seat: int) -> int:
        return (seat - self.button - 1) % self.n

    # ---- dealing --------------------------------------------------------------------------------
    def _deal_hole_cards(self) -> tuple[tuple[Card, ...], ...]:
        """Deal exactly like the server: one card at a time, starting left of the button, two
        passes, popping from the END of the deck. Then tell PokerKit who got what."""
        order = [self.seat_of(i) for i in range(self.n)]  # left of button first, button last
        hands: list[list[Card]] = [[] for _ in range(self.n)]
        for _ in range(2):
            for seat in order:
                hands[seat].append(self.deck.pop())
        # PokerKit deals to index 0, 1, 2, ... which is the same `order`.
        for seat in order:
            self.state.deal_hole("".join(to_pk(c) for c in hands[seat]))
        return tuple(tuple(h) for h in hands)

    def _deal_board_if_needed(self) -> None:
        """When a betting round ends, PokerKit asks for a burn card and then the board cards.
        Like the server: burn one, then deal 3 (flop) or 1 (turn, river)."""
        while True:
            if self.state.can_burn_card():
                self.state.burn_card(to_pk(self.deck.pop()))
            elif self.state.can_deal_board():
                self.state.deal_board("".join(to_pk(c) for c in self._deal_street()))
            else:
                break
        # Betting is over with 2+ players left (PokerKit is waiting at its showdown step, which we
        # skip). After an all-in that can happen before the river, so deal the rest of the board
        # ourselves, in the same burn-then-deal order. PokerKit doesn't need these cards.
        if self.state.showdown_index is not None:
            while len(self.board) < 5:
                self.deck.pop()  # burn
                self._deal_street()

    def _deal_street(self) -> list[Card]:
        """Take the next street's cards from our deck: 3 for the flop, else 1."""
        cards = [self.deck.pop() for _ in range(3 if not self.board else 1)]
        self.board.extend(cards)
        return cards

    # ---- read-only views ------------------------------------------------------------------------
    @property
    def is_over(self) -> bool:
        """No more decisions: everyone but one folded (PokerKit finished the hand), or the betting
        is over and only the showdown is left (we settle that in `results()`)."""
        return not self.state.status or self.state.showdown_index is not None

    @property
    def current_seat(self) -> Optional[int]:
        """Seat whose turn it is, or None (hand over, or cards are being run out)."""
        index = self.state.actor_index
        return None if index is None else self.seat_of(index)

    @property
    def phase(self) -> str:
        """Server phase name. After the hand the server shows WAITING, so we do too."""
        street = self.state.street_index
        return "WAITING" if self.is_over or street is None else STREETS[street]

    @property
    def stacks(self) -> list[int]:
        """Chips behind for each seat. After a showdown these are still the pre-payout stacks;
        use `results()` for who won what."""
        return [self.state.stacks[self.index_of(seat)] for seat in range(self.n)]

    @property
    def bets(self) -> list[int]:
        """Chips each seat has put in on the current street (the server's `bet`)."""
        return [self.state.bets[self.index_of(seat)] for seat in range(self.n)]

    @property
    def pot(self) -> int:
        """Everything put in this hand, including the current street's bets (the server's `pot`)."""
        return self.state.total_pot_amount

    @property
    def current_bet(self) -> int:
        """Highest bet on this street -- what everyone has to match (the server's `current_bet`)."""
        return max(self.state.bets)

    # ---- actions --------------------------------------------------------------------------------
    def _require_turn(self) -> int:
        seat = self.current_seat
        if seat is None:
            raise ValueError("No player can act right now")
        return seat

    def legal_actions(self) -> Legal:
        """What the player to act may do, by the server's rules (see bot/action_map.py)."""
        seat = self._require_turn()
        bet, stack = self.bets[seat], self.stacks[seat]
        max_target = bet + stack  # raising to this = all-in
        # Server rule: no raising when every other player still in the hand is all-in.
        others_can_act = any(not self.folded[s] and self.stacks[s] > 0 for s in range(self.n) if s != seat)
        return Legal(
            can_check=bet == self.current_bet,
            can_call=bet < self.current_bet,
            can_raise=others_can_act and max_target > self.current_bet,
            # A full raise adds at least `minimum_raise`; only an all-in may be smaller.
            min_target=min(self.current_bet + self.minimum_raise, max_target),
            max_target=max_target,
        )

    def act(self, action: str, amount: int = 0) -> dict:
        """Play the current player's move, given like a server message:
        fold | check | call | bet | raise, where `amount` (bet/raise only) is the TOTAL bet for this
        street. Illegal moves raise ValueError and change nothing -- the server rejects them too.
        Returns the event, shaped like the server's `last_action` plus the street it happened on."""
        seat = self._require_turn()
        legal, street, player = self.legal_actions(), self.phase, self.player_ids[seat]
        if type(amount) is not int or amount < 0:
            raise ValueError("amount must be a non-negative integer")
        if action in (FOLD, CHECK, CALL) and amount != 0:
            raise ValueError("Only bet or raise accepts an amount")

        if action == FOLD:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # PokerKit warns when folding instead of a free check
                self.state.fold()
            self.folded[seat] = True
            event = {"type": "fold", "player": player}
        elif action == CHECK:
            if not legal.can_check:
                raise ValueError("Cannot check while facing a bet")
            self.state.check_or_call()
            event = {"type": "check", "player": player}
        elif action == CALL:
            # Chips actually paid: less than to-call when the caller goes all-in. The server also
            # accepts "call" with nothing to call; it then pays 0, just like a check.
            paid = self.state.checking_or_calling_amount
            self.state.check_or_call()
            self.contributed[seat] += paid
            event = {"type": "call", "player": player, "amount": paid}
        elif action in (BET, RAISE):
            if action == BET and self.current_bet != 0:
                raise ValueError("Use raise when facing an existing bet")
            if not legal.can_raise:
                raise ValueError("Cannot raise now")
            if not legal.min_target <= amount <= legal.max_target:
                raise ValueError(f"Raise target must be in [{legal.min_target}, {legal.max_target}]")
            raise_size, paid = amount - self.current_bet, amount - self.bets[seat]
            self.state.complete_bet_or_raise_to(amount)
            self.contributed[seat] += paid
            if raise_size >= self.minimum_raise:  # a short all-in does not change the min raise
                self.minimum_raise = raise_size
            event = {"type": "raise", "player": player, "amount": paid, "target": amount}  # server says "raise" for bets too
        else:
            raise ValueError(f"Unknown action {action!r}")

        event["street"] = street
        self.events.append(event)
        self._deal_board_if_needed()
        if self.phase != street:  # a new betting round starts: min raise back to one big blind
            self.minimum_raise = self.big_blind
        return event

    # ---- what a player sees ---------------------------------------------------------------------
    def observation(self, seat: int) -> Observation:
        """The table as `seat` sees it: own hole cards only, everything else public.

        Field for field the same as `bot.adapter.parse_state(server_json, player_id)` gives the live
        bot for the same moment of the same hand (tested against the server). That's what lets
        features/ encode training data and live play with one piece of code."""
        stacks, bets, ids = self.stacks, self.bets, self.player_ids
        players = tuple(
            PlayerView(id=ids[s], stack=stacks[s], bet=bets[s], folded=self.folded[s],
                       all_in=not self.folded[s] and stacks[s] == 0,
                       connected=True,  # nobody disconnects offline
                       in_hand=True)    # fresh stacks every hand, so everyone is dealt in
            for s in range(self.n)
        )
        return Observation(
            player_id=ids[seat],
            match_number=1,
            hand_number=self.hand_number,
            phase=self.phase,
            hole_cards=self.hole_cards[seat],
            board=tuple(self.board),
            pot=self.pot,
            current_bet=max(bets),
            minimum_raise=self.minimum_raise,
            my_bet=bets[seat],
            my_stack=stacks[seat],
            small_blind=self.small_blind,
            big_blind=self.big_blind,
            dealer=ids[self.button],
            small_blind_player=ids[self.small_blind_seat],
            big_blind_player=ids[self.big_blind_seat],
            players=players,
            is_my_turn=self.current_seat == seat,
            match_complete=False,
        )

    # ---- end of hand ----------------------------------------------------------------------------
    def results(self) -> list[int]:
        """Chips won (+) or lost (-) by each seat this hand: the DMC reward, and exactly what the
        server adds to `profit_loss`. They always sum to zero.

        We settle the pot ourselves instead of using PokerKit's `payoffs`, because the two split
        odd chips differently. The server cuts the pot into layers, one per contribution level, and
        splits each layer among its best eligible hands, giving each layer's leftover chips to the
        tied winners in seat order starting left of the button. PokerKit splits whole pots. So when
        tied players split, the odd chips can land on different seats (found by the server test).
        This mirrors the server's `_return_uncalled_bet` and `_resolve_showdown`."""
        if not self.is_over:
            raise ValueError("The hand is not over yet")
        contributed = self.contributed[:]

        # 1. Return the part of the biggest bet that nobody matched.
        top, second = sorted(range(self.n), key=lambda s: contributed[s], reverse=True)[:2]
        contributed[top] = contributed[second]  # `top` is the biggest, so this only ever lowers it

        payouts = [0] * self.n
        contenders = [s for s in range(self.n) if not self.folded[s]]
        if len(contenders) == 1:  # everyone else folded: no showdown, winner takes it all
            payouts[contenders[0]] = sum(contributed)
        else:
            # 2. Showdown, layer by layer (side pots). Seat order for odd chips: left of the button first.
            scores = {s: evaluate(list(self.hole_cards[s]) + self.board) for s in contenders}
            seats_from_button = [self.seat_of(i) for i in range(self.n)]
            previous = 0
            for level in sorted({c for c in contributed if c}):
                layer = (level - previous) * sum(1 for c in contributed if c >= level)
                eligible = [s for s in contenders if contributed[s] >= level]
                if eligible:
                    best = max(scores[s] for s in eligible)
                    winners = [s for s in seats_from_button if s in eligible and scores[s] == best]
                    share, odd_chips = divmod(layer, len(winners))
                    for s in winners:
                        payouts[s] += share
                    for s in winners[:odd_chips]:
                        payouts[s] += 1
                previous = level
        return [payouts[s] - contributed[s] for s in range(self.n)]
