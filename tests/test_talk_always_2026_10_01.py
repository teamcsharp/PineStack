"""[talk-always] "Find out and fix why the DJs aren't coming out of the tablet ...
make sure it is always able to start generated and running dialogue" (the
operator, 2026-10-01).

Measured that night: 64 of 66 phone calls in 12 h NEVER MADE AIR, 30 of 45 banter
rounds on the larder could never air, and why-quiet said "nothing obviously
wrong" because it counted the "NEVER MADE AIR" row as a DJ line. Each test here
fails on the code before [talk-always]:

  [live-legs]       a live call's copied protocol leg is re-written, not held
  [gate-accounted]  the booth counts the copy gate's own drops as decided
  [reserve-dry]     a dry reserve no longer refuses live writing
  [why-quiet-heard] drop rows are not DJ lines; heard, lost calls, refusals
"""
import ast
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import system3  # noqa: E402
import why_quiet as wq  # noqa: E402
from test_system3_turnchain import (CALL_A, CALL_B, conv_of, fresh_writer, no_copies, stuck_writer,  # noqa: E402
                                    turns_of, written)

APP_TEXT = (ROOT / "app.py").read_text(encoding="utf-8")


def app_function(name, env):
    """One top-level function out of app.py, compiled against `env` - the
    station is never imported."""
    for node in ast.parse(APP_TEXT).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            exec(compile(ast.Module([node], []), "app.py:" + name, "exec"), env)
            return env[name]
    raise AssertionError("app.py has no function " + name)


def walk(conv, turns, writer, **kw):
    run = system3.gate_open(conv, turns, None, **kw)
    asks = []
    while True:
        ask = system3.gate_next(conv, run)
        if not ask:
            break
        asks.append(dict(ask))
        said = writer(len(asks), ask, run)
        got = turns_of(said)
        system3.gate_take(conv, run, got[0][1] if got else said)
    return run, system3.gate_close(conv, run), asks


class LiveLegs(unittest.TestCase):
    def test_before_a_live_call_was_held_for_one_copied_leg(self):
        conv = conv_of(CALL_A)
        _run, out, asks = walk(conv, written(CALL_A), fresh_writer, rewrites=0, visits=0)
        self.assertEqual(asks, [])
        self.assertIn("could not be written without copying", out["held"])

    def test_a_live_call_rewrites_its_protocol_legs_and_airs(self):
        for cid in (CALL_A, CALL_B):
            conv = conv_of(cid)
            run, out, asks = walk(conv, written(cid), fresh_writer, rewrites=system3.GATE_LIVE_REWRITES,
                                  visits=system3.GATE_LIVE_VISITS, legs_only=True)
            self.assertEqual(out["held"], "", cid)
            self.assertLessEqual(len(asks), system3.GATE_LIVE_VISITS)
            fixed = {r["at"] for r in run["rows"] if r["fixed"]}
            self.assertTrue(asks and all(a["at"] in fixed for a in asks), "only protocol legs are re-written")
            self.assertTrue(all(a["attempt"] == 1 for a in asks))
            no_copies(self, conv, out["script"])

    def test_the_runtime_opens_a_live_gate_on_the_legs(self):
        src = (ROOT / "system3_runtime.py").read_text(encoding="utf-8")
        self.assertIn("legs = bool(not prepared and self.settings.get(\"repair\", True))", src)
        self.assertIn("legs_only=legs", src)


class GateAccounted(unittest.TestCase):
    def test_gate_counts_name_the_planned_turns_it_dropped(self):
        conv = conv_of(CALL_A)
        run, _out, _asks = walk(conv, written(CALL_A), stuck_writer)
        dropped = [r["turn_id"] for r in run["rows"] if r["state"] == "dropped" and r["turn"] is not None]
        self.assertTrue(dropped)
        self.assertEqual(sorted(system3.gate_counts(conv)["dropped_ids"]), sorted(dropped))

    def test_the_gates_drops_are_decided_not_missing(self):
        f = app_function("s3_gate_dropped", {"Any": object})
        s3 = {"gate": {"dropped_ids": ["c:t03", "c:t07", "c:t09"]}}
        self.assertEqual(f(s3, {"0": "c:t00", "1": "c:t09"}), 2)     # t09 is bound: not a drop
        self.assertEqual(f({}, {}), 0)
        self.assertEqual(f(None, None), 0)

    def test_booth_and_readiness_both_ask(self):
        self.assertIn("planned = max(len(positions), planned - s3_gate_dropped(s3, ids))", APP_TEXT)
        self.assertIn("_s3_planned = max(len(_s3_positions), _s3_planned - s3_gate_dropped(_round_s3, _s3_ids))",
                      APP_TEXT)
        self.assertIn("not s3_coverage_ok(len(positions), planned)", APP_TEXT)
        self.assertIn("not s3_coverage_ok(len(_s3_positions), _s3_planned)", APP_TEXT)

    def test_coverage_not_all_or_nothing(self):
        """[s3-coverage] the live misses of 2026-10-01 air; fragments still do not."""
        f = app_function("s3_coverage_ok", {"S3_COVERAGE": 0.66})
        self.assertTrue(f(20, 21))     # one turn the bind could not align
        self.assertTrue(f(16, 23))
        self.assertTrue(f(9, 9))
        self.assertFalse(f(4, 28))     # the writer gave a fragment
        self.assertFalse(f(7, 24))
        self.assertFalse(f(2, 2))      # not a conversation
        self.assertFalse(f(0, 0))


class ReserveDry(unittest.TestCase):
    def coming(self, larder, withheld=()):
        env = {"time": time, "_LARDER": larder, "RESERVE_COMING_S": 900.0,
               "_larder_current": lambda e: True,
               "s3_binding_withheld": lambda e: "incomplete" if e.get("id") in withheld else ""}
        return app_function("larder_banter_coming", env)()

    def test_a_shelf_of_unairable_rounds_is_not_catching_up(self):
        now = time.time()
        larder = [{"id": "a", "at": now}, {"id": "b", "at": now}, {"id": "c", "at": now, "aired_at": now}]
        self.assertEqual(self.coming(larder, withheld=("a", "b")), (0, 2))

    def test_a_fresh_recordable_round_is_on_its_way_a_stale_one_is_not(self):
        now = time.time()
        self.assertEqual(self.coming([{"id": "a", "at": now - 60}]), (1, 0))
        self.assertEqual(self.coming([{"id": "a", "at": now - 3600}]), (0, 1))

    def test_the_refusal_asks_the_reserve(self):
        self.assertIn("_coming, _never = larder_banter_coming()", APP_TEXT)
        self.assertIn("a live round is written now, tinted before it airs [reserve-dry]", APP_TEXT)
        # the line is %-formatted: a bare "100% talk" raised ValueError and killed every live write
        self.assertIn('pipeline_log("air", "100%% talk found no zero-work larder round and the reserve is NOT "',
                      APP_TEXT)


class WhyQuietHeard(unittest.TestCase):
    def test_a_never_made_air_row_is_not_a_dj_line(self):
        chat = [{"who": "dj", "kind": "banter", "text": "hello", "ts": 1},
                {"who": "drop", "kind": "drop", "text": "☎ Deacon Fry on line 29 NEVER MADE AIR", "ts": 2},
                {"who": "host", "kind": "banter", "text": "On line 29: Deacon Fry", "ts": 3}]
        self.assertEqual(wq.last_dj_line(chat)["text"], "hello")

    def test_published_but_not_heard_is_a_stop(self):
        now = time.time()
        base = {"on": True, "playout_verdict": "shadow", "engines": {"xtts": True}, "talk": 100,
                "last_dj": {"ts": now - 30}}
        got = wq.findings(dict(base, heard_at=now - 900, owner=""), now)
        self.assertEqual(got[0]["level"], "stop")
        self.assertIn("no page has played one for 15 min", got[0]["what"])
        self.assertIn("owned by nobody", got[0]["what"])
        self.assertEqual([r["level"] for r in wq.findings(dict(base, heard_at=now - 20), now)], ["info"])

    def test_lost_calls_and_refusals_are_named(self):
        now = time.time()
        chat = [{"who": "drop", "name": n, "text": "☎ %s on line 3 NEVER MADE AIR" % n, "ts": int(now - 60)}
                for n in ("Furx", "Drunk Tony", "Deacon Fry")]
        lost = wq.calls_lost(chat, now)
        self.assertEqual((lost["lost"], lost["aired"]), (3, 0))
        ev = [{"ts": (now - 10) * 1000, "text": "100% talk found no zero-work larder round; "
               "live writing is refused while the reserve catches up"}] * 7
        roads = wq.road_counts(ev, now)
        self.assertEqual(roads["refused"], 7)
        f = {"on": True, "playout_verdict": "shadow", "engines": {"xtts": True}, "talk": 100,
             "last_dj": {"ts": now - 30}, "heard_at": now - 20, "calls_lost": lost, "roads": roads,
             "reserve": {"coming": 0, "never": 30}}
        whats = " | ".join(r["what"] for r in wq.findings(f, now))
        self.assertIn("3 phone call(s) in the last hour NEVER MADE AIR", whats)
        self.assertIn("refused to write live 7 times", whats)
        self.assertIn("Deacon Fry", whats)

    def test_wired(self):
        self.assertIn('facts["heard_at"] = _why_quiet.last_heard(_chat)', APP_TEXT)


if __name__ == "__main__":
    unittest.main()
