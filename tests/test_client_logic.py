"""BotSession protocol logic, fed fake server messages (no network)."""
import asyncio
import time

from bot.client import BotSession
from tests.factories import make_state, msg, player


def run(session, *messages):
    async def go():
        out = []
        for m in messages:
            out.extend(await session.handle(m))
        return out
    return asyncio.run(go())


def test_acts_once_on_our_turn_and_dedupes_broadcasts():
    s = BotSession("a")
    state = make_state()
    assert run(s, msg(state)) == [{"type": "action", "action": "call"}]
    assert s.pending
    assert run(s, msg(state)) == []  # pending
    run(s, {"type": "action_result", "payload": {"ok": True}})
    assert run(s, msg(state)) == []  # same turn rebroadcast after result


def test_ignores_other_players_turns():
    s = BotSession("a")
    assert run(s, msg(make_state(current_turn="b"))) == []
    assert not s.pending


def test_new_turn_same_hand_gets_new_action():
    s = BotSession("a")
    run(s, msg(make_state()), {"type": "action_result", "payload": {"ok": True}})
    flop = make_state(phase="FLOP", current_bet=0, community_cards=[],
                      players=[player("a", bet=0), player("b", bet=0, hidden=True), player("c", bet=0, hidden=True)])
    assert run(s, msg(flop)) == [{"type": "action", "action": "check"}]


def test_rejection_falls_back_without_repeating():
    s = BotSession("a")
    state = make_state(current_bet=200)  # facing a big bet -> policy says call
    assert run(s, msg(state)) == [{"type": "action", "action": "call"}]
    out = run(s, {"type": "action_result", "payload": {"ok": False, "error": "nope"}})
    assert out == [{"type": "action", "action": "fold"}]  # safe fallback (to_call > BB)
    out = run(s, {"type": "action_result", "payload": {"ok": False, "error": "nope"}})
    assert out == []  # everything tried; let the server's timeout handle it
    assert s.stats.rejections == 2


def test_error_while_pending_counts_as_rejection():
    s = BotSession("a")
    run(s, msg(make_state(current_bet=10)))  # check
    out = run(s, {"type": "error", "message": "Invalid action payload"})
    # safe fallback is also "check" (already tried) -> minimal is check too -> nothing left
    assert out == []
    assert not s.pending


class SlowPolicy:
    def act(self, obs, history):
        time.sleep(0.5)
        return ("raise", 500)


class BrokenPolicy:
    def act(self, obs, history):
        raise RuntimeError("boom")


def test_policy_timeout_uses_fallback():
    s = BotSession("a", policy=SlowPolicy(), decision_timeout=0.05)
    assert run(s, msg(make_state())) == [{"type": "action", "action": "call"}]
    assert s.stats.fallbacks == 1


def test_policy_exception_uses_fallback():
    s = BotSession("a", policy=BrokenPolicy())
    assert run(s, msg(make_state(current_bet=10))) == [{"type": "action", "action": "check"}]


def test_tracks_payouts_timeouts_and_match_complete():
    s = BotSession("a")
    timed_out = make_state(current_turn="b", last_action={"type": "fold", "player": "a",
                                                          "timeout": {"player": "a", "action": "fold"}})
    run(s, msg(timed_out), msg(timed_out))
    assert s.stats.our_timeouts == 1
    paid = make_state(phase="WAITING", current_turn=None, match_complete=True,
                      last_action={"type": "payout", "winners": ["b"], "pot": 30})
    run(s, msg(paid), msg(paid))
    assert s.stats.hands_completed == {(1, 1)}
    assert s.match_complete
