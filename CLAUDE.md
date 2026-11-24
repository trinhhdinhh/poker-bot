# CLAUDE.md

## Project
AI course group project: a poker bot trained with **Counterfactual Regret Minimization (CFR)**
that plays on the class server **Bayou Poker Server** (https://github.com/binaya07/ai-poker-server).
The only goal is to win on that server. We train directly on No-Limit Hold'em — no toy games
(Kuhn, Leduc, etc.).

## The target game (from the server — this is what the bot must actually play)
- **No-Limit Texas Hold'em**, multiplayer (server allows up to 20 seats; expect 3+ bots, not heads-up).
- Starting stack **1000**, blinds **10/20** → 50 big blinds deep. **Every hand starts with a fresh 1000**;
  the winner is the highest cumulative `profit_loss` over the match (`max_hands`, default 100).
- **Turn timeout: 5 s by default** (`turn_timeout_seconds` in the server's `config.toml`; the class server may differ).
  On timeout the server checks if legal, otherwise folds.
  → All CFR training happens **offline**. At play time the bot only does a fast lookup + light computation.
- Disconnecting folds a live hand; rejoining with the same id keeps the seat and closes the old socket (code 4001).

## How it works
1. **Abstraction** shrinks Hold'em to a size CFR can handle (cards → buckets, bets → a small menu).
2. **Offline training**: MCCFR plays the abstracted game against itself and saves a strategy table.
3. **Live play**: the bot turns server JSON into the same abstract key, looks up the table, and sends
   a legal action. No learning at play time.

## Repo layout
| Path | Purpose |
|---|---|
| `bot/` | **Live server client** — connects to the server and plays |
| `abstraction/` | Card + action abstraction, **shared by training and the bot** |
| `engine/` | Offline No-Limit Hold'em simulator matching the server's rules |
| `training/` | MCCFR and the training entry point |
| `eval/` | Offline matches between bots, win rate in mbb/hand |
| `tests/` | Unit tests |
| `results/checkpoints/` | Trained strategy tables — git-ignored |

### `bot/`
- `client.py` — WebSocket loop: join, read `state` / `action_result` / `error`, act only on our turn.
  Base it on the server's `scripts/student_bot.py` (dedupe repeated broadcasts, track `pending`).
- `adapter.py` — server JSON → observation (hole cards, board, pot, to-call, position, street, stacks)
  and the abstract infoset key (via `abstraction/`).
- `policy.py` — loads the strategy table and picks an action; falls back to an equity-vs-pot-odds
  rule when the spot isn't in the table.
- `action_map.py` — abstract action (fold / check-call / ½ pot / pot / all-in) → a **legal** server action.

### `abstraction/`
- `cards.py` — preflop: 169 canonical hands (AKs, 72o, …); postflop: equity buckets.
- `actions.py` — the action menu, and mapping opponents' off-menu bet sizes to the nearest abstract size.

### `engine/`
- `holdem.py` — simulator with server rules (stack 1000, blinds 10/20, min-raise, all-ins, side pots).
  Prefer wrapping an existing library (e.g. PokerKit) over writing one; verify it matches the server.

### `training/`
- `mccfr.py` — external-sampling Monte Carlo CFR on the abstracted game, 3+ players.
- `train.py` — runs training, saves the table to `results/checkpoints/`. Run: `python -m training.train`.

### `eval/`
- `match.py` — play many hands offline between bots (trained vs rule-based, random, always-call);
  report mbb/hand with a confidence interval, rotating seats.

## Build order
| Step | What | Done when |
|---|---|---|
| 1 | `bot/` with the rule-based policy | Plays full sessions on a local server, no illegal moves or timeouts |
| 2 | `engine/` | Hands resolve exactly like on the server |
| 3 | `abstraction/` | Unit-tested and fast enough to run every turn |
| 4 | `training/` | Strategy table saved |
| 5 | `eval/` | Trained bot beats the rule-based bot offline |
| 6 | Load the table in `bot/policy.py` (rule-based stays as fallback) | Beats the demo bots on the local server |

Steps 1 and 2–3 can be built in parallel. Start training small (few buckets, 3 players) and scale up.

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
- **Training and the bot must use the same `abstraction/` code.** If bucketing differs even slightly,
  the bot looks up the wrong strategy with no error. Never duplicate abstraction logic in `bot/`.
- Action abstraction: fold, check/call, ½ pot, pot, all-in. Opponents' other sizes map to the nearest one.
- CFR's theoretical guarantees only hold heads-up. For multiway pots we train MCCFR anyway
  (works well in practice, as in Pluribus) and fall back to the equity rule where the table has no data.
- **Safety net:** every decision must return within ~2 seconds. Wrap policy calls in a timeout;
  on any error or timeout, check if legal, otherwise fold (or call if to-call is tiny).

## Conventions
- Python 3.11+. `pip install -r requirements.txt`. Add libraries there as they're adopted (e.g. `numpy`, `pokerkit`).
- Feature branches + PR with one reviewer; `pytest` must pass before merge.
- Don't commit trained tables or logs; share checkpoints out-of-band if large.
- Changes to `abstraction/` affect both training and the bot — they need group agreement and invalidate old tables.

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
