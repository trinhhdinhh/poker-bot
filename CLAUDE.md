# CLAUDE.md

## Project
AI course group project: a poker bot trained with **Deep Monte Carlo (DMC) reinforcement learning**
(self-play + a neural Q-network, in the style of DouZero) that plays on the class server
**Bayou Poker Server** (https://github.com/binaya07/ai-poker-server).
The only goal is to win on that server. We train directly on No-Limit Hold'em — no toy games
(Kuhn, Leduc, etc.).

## The target game (from the server — this is what the bot must actually play)
- **No-Limit Texas Hold'em**, multiplayer (server allows up to 20 seats; expect 3+ bots, not heads-up).
- Starting stack **1000**, blinds **10/20** → 50 big blinds deep. **Every hand starts with a fresh 1000**;
  the winner is the highest cumulative `profit_loss` over the match (`max_hands`, default 100).
- **Turn timeout: 5 s by default** (`turn_timeout_seconds` in the server's `config.toml`; the class server may differ).
  On timeout the server checks if legal, otherwise folds.
  → All training happens **offline**. At play time the bot only encodes the state and runs one small forward pass.
- Disconnecting folds a live hand; rejoining with the same id keeps the seat and closes the old socket (code 4001).

## How it works
1. **Features** turn a game state into a fixed-size vector (raw cards, money in big blinds, position,
   betting history) and each menu action into its own vector. No card bucketing — the network learns it.
2. **Offline training (DMC)**: bots play hands against each other in `engine/`. Each hand is one episode
   (stacks reset every hand, so hands are independent). Every decision is labelled with that seat's final
   chip result for the hand (in big blinds), and a network Q(state, action) is fitted to those returns
   with MSE. Actors explore with epsilon-greedy. Opponents: mostly the current network, plus rule-based
   bots and older checkpoints.
3. **Live play**: the bot builds the same features from server JSON, scores every legal menu action
   with the network, plays the best one, and maps it to a legal server action. No learning at play time.

## Repo layout
| Path | Purpose |
|---|---|
| `bot/` | **Live server client** — connects to the server and plays |
| `features/` | State + action encoding and the action menu, **shared by training and the bot** |
| `engine/` | Offline No-Limit Hold'em simulator matching the server's rules (runs self-play) |
| `training/` | DMC self-play, the Q-network, and the training entry point |
| `eval/` | Offline matches between bots, win rate in mbb/hand |
| `tests/` | Unit tests + an integration test against the real server |
| `results/checkpoints/` | Trained models (`.pt`) — git-ignored |

### `bot/` (done: connection infrastructure, see build step 1)
- `client.py` — WebSocket loop. `BotSession` (no I/O, unit-tested) dedupes repeated broadcasts, tracks
  `pending`, runs the policy under a 2 s timeout, falls back after rejections; `BotClient` owns the
  socket and reconnects. Run: `python -m bot.client group-1 [--url ...] [--hands N] [-v]`.
- `adapter.py` — server JSON → `Observation` (hole cards, board, pot, to-call, position, stacks) and
  `HandHistory` built from successive states; `encode_state` will call `features/`.
- `policy.py` — `Policy` interface. Today: `CheckCallPolicy`. Later: load the Q-network, take the argmax
  over legal menu actions; fall back to an equity-vs-pot-odds rule if no model or on error.
- `action_map.py` — menu action → a **legal** server action (clamps raise sizes, handles all-ins).

### `features/`
- `encoding.py` — state → float vector: one-hot hole cards and board (52 each), street, players dealt in /
  still active, position from the button, pot / to-call / stacks / bets in big blinds (opponents padded
  to max seats), last K betting actions. Carries `ENCODING_VERSION`.
- `actions.py` — action menu (fold, check/call, raise ½ pot, pot, 2× pot, all-in), legal-menu filtering,
  action encoding, and raise targets in server terms.

### `engine/`
- `holdem.py` — `HoldemHand(n_players, button, rng)`: one hand with server rules, built on **PokerKit**
  (cash-game mode, so folding when a check is free is allowed, as on the server). Our seats 0..n-1 ↔
  PokerKit indices via `seat_of`/`index_of`. We deal and burn from our own seeded deck in the server's
  order. API: `current_seat`, `legal_actions()` (→ `bot.action_map.Legal`), `act("fold|check|call|bet|raise",
  amount)` (amount = street total; illegal → `ValueError`, nothing changes), `events` (same shape as
  `bot.adapter.HandHistory.events`), `observation(seat)` (→ `bot.adapter.Observation`), `results()` (chips
  per seat = the DMC reward). `results()` settles pots **ourselves**, layer by layer like the server, because
  PokerKit hands out odd chips differently. PokerKit's showdown automations are off (they were 76% of run time):
  the hand is over when betting ends, and we deal any remaining board ourselves. `minimum_raise` is also
  tracked by us, as the server does. Speed: ~4,000 hands/s at 6 players (`python -m engine.bench`).
- `cards.py` — `FULL_DECK`, `shuffled_deck(rng)`, `to_pk(card)`. `evaluator.py` — 7-card hand score, identical
  to the server's `evaluate_best_hand` (used by `results()` and the rule-based bot).
- `bench.py` — `random_move` (random legal player) and `python -m engine.bench` (hands/s).
- Verified by `tests/test_engine_vs_server.py`: random hands in our engine and the server's `app/engine.py`
  side by side, compared after every action (state, events, observations via `parse_state`, legal moves,
  accepted/rejected moves, final results). Longer run: `ENGINE_STRESS_HANDS=20000 pytest tests/test_engine_vs_server.py`.

### `training/`
- `model.py` — MLP: concat(state, action) → expected return in big blinds. Shared with `bot/policy.py`.
- `dmc.py` — actors (epsilon-greedy self-play in `engine/`) + learner (MSE on Monte Carlo returns),
  opponent pool of current/older networks and rule-based bots.
- `train.py` — runs training, saves checkpoints to `results/checkpoints/`. Run: `python -m training.train`.

### `eval/`
- `match.py` — play many hands offline between bots (DMC model vs rule-based, always-call, random,
  older checkpoints); report mbb/hand with a confidence interval, rotating seats.

## Build order
| Step | What | Done when |
|---|---|---|
| 1 | `bot/` connection + rule-based policy | Plays full sessions on a local server, no illegal moves or timeouts (connection ✅, rule policy TODO) |
| 2 | `engine/` | Hands resolve exactly like on the server; fast enough for self-play ✅ |
| 3 | `features/` | Unit-tested; the same `Observation` gives the same vector from engine and from server JSON |
| 4 | `training/` | DMC loss goes down; checkpoints saved |
| 5 | `eval/` | Trained bot beats the rule-based and always-call bots offline |
| 6 | Load the model in `bot/policy.py` (rule-based stays as fallback) | Beats the demo bots on the local server |

Steps 1 and 2–3 can be built in parallel. Start small (3 players, small MLP, short runs) and scale up.

## Server protocol (essentials)
- Connect: `ws://localhost:8000/ws` (Docker: `ws://poker-server:8000/ws`).
- Join: `{"type":"join","player_id":"group-X","name":"..."}` — one socket = one player.
- Act only when `state.payload.current_turn == our id`. Wait for the next `state` message, not the action_result's embedded state.
- Action: `{"type":"action","action":"check|call|fold|bet|raise","amount":N}`
  - `amount` for bet/raise = **total for this street**, not extra chips. Integer only.
  - Min raise target = `current_bet + minimum_raise`. Max = `my.bet + my.stack` (all-in = raise to max; no separate all-in action).
  - `check` only if `my.bet == current_bet`. `bet` only if `current_bet == 0` (`raise` also works as an opening bet).
  - To-call = `current_bet - my.bet`.
- Cards: `{"rank":2-14,"suit":"hearts|diamonds|clubs|spades"}`; hidden = `"?"`. Use rank/suit, never `label`.
- Use `hand_number` to reset per-hand memory. `last_action` is only the latest event, not full history —
  **the client must build its own betting history** from successive states if the policy needs it.
- Invalid actions are rejected without changing anything. Never retry the same invalid move; fall back to call/check/fold.

## Key design decisions
- **Training and the bot must use the same `features/` code.** If the encoding differs even slightly, the
  network sees garbage with no error. Never duplicate feature logic in `bot/`. Models are saved with
  `ENCODING_VERSION`; the bot refuses a model whose version doesn't match.
- **Engine and live play must produce the same `Observation`.** Write `features/` against `Observation`
  (from `bot/adapter.py`) and have `engine/` produce it too, so there is one encoding path.
- Action menu: fold, check/call, ½ pot, pot, 2× pot, all-in. Opponents' real bet sizes go into the
  history features as pot fractions (no rounding to the menu needed).
- Reward = chips won minus chips put in for the hand, in big blinds — exactly what the server ranks on.
  Monte Carlo returns are high-variance; use many hands, and consider subtracting a baseline later.
- Pure self-play can learn exploitable habits; keep rule-based bots and older checkpoints in the
  opponent pool and track win rate against them in `eval/`.
- **Safety net:** every decision must return within ~2 seconds. Policy calls run under a timeout;
  on any error or timeout, check if legal, call if to-call ≤ 1 BB, otherwise fold.

## Conventions
- Python 3.11+. `pip install -r requirements.txt`. Add libraries there as they're adopted
  (`pokerkit` for the engine; expected: `numpy`, `torch` for the network). Inference runs on CPU.
- Feature branches + PR with one reviewer; `pytest` must pass before merge.
- Don't commit trained models or logs; share checkpoints out-of-band if large.
- Changes to `features/` affect both training and the bot — they need group agreement, a bump of
  `ENCODING_VERSION`, and invalidate old models.

## Running against the server locally
```sh
# terminal 1 (in the ai-poker-server repo)
python -m uvicorn app.server:app --host 0.0.0.0 --port 8000
# terminals 2+ (in this repo)
python -m bot.client group-1
python scripts/demo_bots.py   # from the server repo, for opponents
```
Then open http://localhost:8000 and click **Start** (or `demo_bots.py --auto-start` to deal automatically).

The server repo is cloned (git-ignored) at `./ai-poker-server/`. `pip install -r requirements-dev.txt` adds its
deps; then `pytest` also runs `tests/test_integration_server.py`, which starts the real server, connects three of
our bots, deals hands via an observer's `start_hand`, and asserts no rejected actions or timeouts.
