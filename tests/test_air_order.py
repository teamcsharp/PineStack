"""[air-order] Everything waits its turn, and the script numbers a line where
it entered the air queue.

"Nothing airs before something committed earlier. Interjections, clips and ads
join the queue behind the rounds already waiting. Anything time-bound that goes
stale while it waits (an intro for a record already playing) is dropped and
recorded, never aired late." (operator, 2026-09-27)"""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app
from playout_sequencer import LinearSequencer, MODE_LINEAR

ROOT = Path(app.__file__).resolve().parent


class LedgerSandbox:
    """The script ledger, its counter and the page-door numbers in a temp dir."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.stack = ExitStack()
        for name, value in (("SCRIPT_LEDGER_PATH", root / "script_ledger.jsonl"),
                            ("SCRIPT_LEDGER_SEQ_PATH", root / "seq.json"),
                            ("SCRIPT_RESERVED_PATH", root / "reserved.jsonl"),
                            ("_SCRIPT_LEDGER_MEMO", {"at": 0.0, "rows": []}),
                            ("_SCRIPT_RESERVED", {}),
                            ("_SCRIPT_RESERVED_STATE", {"loaded": False})):
            self.stack.enter_context(mock.patch.object(app, name, value))
        self.stack.enter_context(mock.patch.dict(app.__dict__, {"system3_observe_ledger": None}))
        return self

    def __exit__(self, *exc):
        self.stack.close()
        self.tmp.cleanup()

    def rows(self):
        path = app.SCRIPT_LEDGER_PATH
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def heard(rid, text, kind="interject", at=None, who="dj"):
    return {"id": rid, "who": who, "kind": kind, "text": text, "aired": "stream",
            "heard_ack_at": at or time.time(), "air_at": at or time.time(), "seconds": 3.0}


class NumberingTests(unittest.TestCase):
    def test_a_line_keeps_the_number_it_took_at_the_page_door(self):
        with LedgerSandbox() as box:
            line = app.script_ledger_reserve(["i1", "i1-punct-1"])
            self.assertTrue(line)
            self.assertEqual(app.script_ledger_reserve(["i1", "i1-punct-1"]), line,
                             "a republish is not a new place in the order")
            # a round is written down after the line joined the air queue
            rnd = app.script_ledger_commit("sid1", [{"line_id": "r1", "who": "dj", "text": "round line"}], "banter")
            self.assertGreater(rnd, line)
            # the line is heard - it is written under the number it took at the door
            now = time.time()
            caught = app.script_ledger_catch_up([heard("i1", "an interjection", at=now),
                                                 heard("i1-punct-1", "a clip", kind="sfx", at=now + 3)])
            self.assertEqual(caught, 2)
            mine = sorted((r["block"], r["ord"], r["line_id"]) for r in box.rows() if r["line_id"].startswith("i1"))
            self.assertEqual(mine, [(line, 0, "i1"), (line, 1, "i1-punct-1")])
            self.assertTrue(all(r["scripted"] is False for r in box.rows() if r["line_id"].startswith("i1")))
            order = app.script_ledger_order()
            self.assertLess(order["i1"], order["r1"], "the script reads the line before the round")
            self.assertNotIn("i1", app._SCRIPT_RESERVED, "a written number is spent")

    def test_the_numbers_outlive_a_restart(self):
        with LedgerSandbox():
            line = app.script_ledger_reserve(["a", "b"])
            app._SCRIPT_RESERVED.clear()
            app._SCRIPT_RESERVED_STATE["loaded"] = False
            self.assertEqual(app.script_ledger_reserved("b")[0], line)
            self.assertEqual(app.script_ledger_reserved("b")[2], 1)

    def test_a_line_nobody_numbered_is_still_caught_up_when_heard(self):
        with LedgerSandbox() as box:
            self.assertEqual(app.script_ledger_catch_up([heard("x1", "said by the box", at=time.time())]), 1)
            self.assertEqual([r["line_id"] for r in box.rows()], ["x1"])

    def test_a_line_parked_before_a_round_was_written_reads_before_it(self):
        with LedgerSandbox(), ExitStack() as stack:
            for name, value in (("air_order_strict", lambda: True),
                                ("playout_held_keys", lambda: ["sid:earlier"]),
                                ("_PAGE_WAITING", []), ("_PAGE_DELIVERIES", {}),
                                ("_AIR_ORDER", {"parked": 0, "flushed": 0, "dropped": 0, "exempt": 0,
                                                "last_park": "", "last_drop": ""})):
                stack.enter_context(mock.patch.object(app, name, value))
            self.assertTrue(app.page_waiting_park({"row_id": "id1", "kind": "station_id", "text": "an ident"}))
            later = app.script_ledger_commit("sidB", [{"line_id": "b1", "text": "a round written after"}], "banter")
            app.script_ledger_catch_up([heard("id1", "an ident")])
            order = app.script_ledger_order()
            self.assertTrue(later)
            self.assertLess(order["id1"], order["b1"], "it joined the air queue before the round was written")

    def test_the_memo_stays_in_script_order(self):
        with LedgerSandbox():
            line = app.script_ledger_reserve(["early"])
            app.script_ledger_commit("s", [{"line_id": "later-round", "text": "x"}], "banter")
            app._SCRIPT_LEDGER_MEMO.update({"at": time.time(), "rows": app.script_ledger_rows()})
            app.script_ledger_catch_up([heard("early", "first on the page")])
            memo = app._SCRIPT_LEDGER_MEMO["rows"]
            self.assertEqual([r["line_id"] for r in memo], ["early", "later-round"])
            self.assertEqual(memo[0]["block"], line)


class Recorder:
    def __init__(self):
        self.sent = []

    def __call__(self, clip):
        self.sent.append(dict(clip))
        return clip.get("delivery_id") or "d%d" % len(self.sent)


class WaitingLineTests(unittest.TestCase):
    def reserve(self, ids, at=0.0):
        self.reserved.append(list(ids))
        return len(self.reserved)

    def setUp(self):
        self.held = ["sid:r1"]
        self.reserved = []
        self.pub = Recorder()
        self.stack = ExitStack()
        for name, value in (("air_order_strict", lambda: True),
                            ("playout_held_keys", lambda: list(self.held)),
                            ("page_feed_append", self.pub),
                            ("radio_paused", lambda: False),
                            ("admission_controller", lambda: None),
                            ("_PAGE_WAITING", []),
                            ("_AIR_ORDER", {"parked": 0, "flushed": 0, "dropped": 0, "exempt": 0,
                                            "last_park": "", "last_drop": ""}),
                            ("_RECORD_BOUND_LINES", {}),
                            ("_PAGE_DELIVERIES", {}),
                            ("_RENDER_BACKLOG", []),
                            ("render_backlog_save", lambda: None),
                            # never the live ledger's numbers from a test
                            ("script_ledger_reserve", self.reserve)):
            self.stack.enter_context(mock.patch.object(app, name, value))
        self.radio = {"chat": [], "dropped": [], "voice_cut_ms": 0}
        self.stack.enter_context(mock.patch.object(app, "_RADIO", self.radio))
        self.stack.enter_context(mock.patch.object(app, "line_review_capture", lambda *a, **k: None))
        self.stack.enter_context(mock.patch.object(app, "line_review_drop_gate", lambda why: ("drop", False)))

    def tearDown(self):
        self.stack.close()

    def clip(self, rid, **extra):
        return {"row_id": rid, "who": "dj", "kind": "interject", "text": "line " + rid,
                "url": "/media/%s.wav?t=x" % rid, "ts": 1, "broadcast_ms": 5, **extra}

    def test_a_line_waits_off_the_page_until_the_round_ahead_has_gone(self):
        did = app.page_waiting_park(self.clip("j1"), {"why": "a committed banter round goes next"})
        self.assertTrue(did)
        self.assertEqual(self.pub.sent, [], "nothing reaches the page while the round waits")
        self.assertEqual(app.page_waiting_flush(), 0)
        self.held.clear()                            # the round went out
        self.assertEqual(app.page_waiting_flush(), 1)
        sent = self.pub.sent[0]
        self.assertEqual(sent["delivery_id"], did, "the producer's delivery id holds")
        self.assertNotIn("broadcast_ms", sent, "stamped afresh behind the round")
        self.assertGreater(sent["ts"], 1, "a fresh place for the page's cursor")
        self.assertIn("air_waited", sent)

    def test_the_line_keeps_the_order_the_lines_arrived_in(self):
        app.page_waiting_park(self.clip("j1"))
        self.held.clear()
        # the round has gone but the first line has not been freed yet: the
        # second queues behind it, and they go in order
        with mock.patch.object(app, "page_waiting_flush", lambda why="": 0):
            self.assertTrue(app.page_waiting_park(self.clip("j2")))
        app.page_waiting_flush()
        self.assertEqual([c["row_id"] for c in self.pub.sent], ["j1", "j2"])

    def test_a_line_is_numbered_where_it_joined_the_line(self):
        app.page_waiting_park(self.clip("j1", stream={"rows": [{"id": "j1"}, {"id": "j1-punct-1"}]}))
        self.assertEqual(self.reserved, [["j1", "j1-punct-1"]],
                         "numbered at park time, before the round it waits for goes")

    def test_a_parked_line_is_a_delivery_in_flight(self):
        did = app.page_waiting_park(self.clip("j1"))
        got = app._PAGE_DELIVERIES[did]
        self.assertEqual(got["state"], "waiting")
        self.assertFalse(app.page_delivery_waits(got), "not a clip the page holds")
        self.assertFalse(got["speech"], "not dialogue offered to the page yet")

    def test_a_line_that_waited_too_long_is_withdrawn_and_recorded(self):
        self.radio["chat"].append({"id": "j1", "text": "line j1", "aired": "published"})
        did = app.page_waiting_park(self.clip("j1"))
        app._RENDER_BACKLOG.extend([{"id": "j1", "delivery_id": did}, {"id": "k", "delivery_id": "other"}])
        with mock.patch.object(app, "PAGE_WAIT_MAX_S", -1):
            app.page_waiting_flush()
        self.assertEqual(self.pub.sent, [], "never aired late")
        self.assertEqual(app._PAGE_DELIVERIES[did]["state"], "withdrawn")
        self.assertEqual([h["id"] for h in app._RENDER_BACKLOG], ["k"], "the backlog lets go of it")
        self.assertEqual(self.radio["chat"][0]["aired"], "withdrawn")
        self.assertIn("[air-order]", self.radio["chat"][0]["withdrawn_why"])
        self.assertTrue(any("[air-order]" in d["why"] for d in self.radio["dropped"]))
        self.assertEqual(app._AIR_ORDER["dropped"], 1)

    def test_an_intro_whose_record_left_is_dropped_not_aired(self):
        app._RECORD_BOUND_LINES["j1"] = {"id": "t1", "part": "intro", "cut_at": time.time()}
        with mock.patch.object(app, "record_bound_note", lambda *a, **k: None):
            app.page_waiting_park(self.clip("j1", kind="intro"))
            self.held.clear()
            app.page_waiting_flush()
        self.assertEqual(self.pub.sent, [])
        self.assertIn("record", app._AIR_ORDER["last_drop"])

    def test_a_person_does_not_wait(self):
        self.assertEqual(app.page_waiting_park(self.clip("h1"), by_hand=True), "")
        self.assertEqual(app.page_waiting_park(self.clip("h2"), producer="script_line_replay:135339"), "")
        self.assertEqual(app.page_waiting_park(self.clip("h3"), producer="play_phone_ring:101730"), "")
        self.assertEqual(app._AIR_ORDER["exempt"], 3)

    def test_nothing_waits_when_no_round_is_waiting(self):
        self.held.clear()
        self.assertEqual(app.page_waiting_park(self.clip("j1")), "")

    def test_a_paused_station_keeps_the_line_in_place(self):
        app.page_waiting_park(self.clip("j1"))
        self.held.clear()
        with mock.patch.object(app, "radio_paused", lambda: True):
            self.assertEqual(app.page_waiting_flush(), 0)
        self.assertEqual(len(app._PAGE_WAITING), 1)

    def test_switched_off_everything_goes(self):
        app.page_waiting_park(self.clip("j1"))
        with mock.patch.object(app, "air_order_strict", lambda: False):
            self.assertEqual(app.page_waiting_flush(), 1)


class CommittedRoundTests(unittest.TestCase):
    def test_a_line_with_a_welded_clip_is_not_a_round(self):
        two_rows = {"stream": {"rows": [{"id": "a"}, {"id": "a-punct-1"}], "length": 4}}
        with mock.patch.object(app, "air_order_strict", lambda: True):
            self.assertFalse(app.playout_is_committed_round(two_rows))
            self.assertTrue(app.playout_is_committed_round({**two_rows, "playout_key": "sid:x"}))
        with mock.patch.object(app, "air_order_strict", lambda: False):
            self.assertTrue(app.playout_is_committed_round(two_rows))


class SequencerTests(unittest.TestCase):
    def test_held_keys_are_the_rounds_waiting_in_script_order(self):
        now = [1000.0]
        seq = LinearSequencer(clock=lambda: now[0], mode_reader=lambda: MODE_LINEAR,
                              held_stale_s=30, events_path=Path(tempfile.mkdtemp()) / "e.jsonl")
        seq.hold("later", block=12, seconds=20, lines=3, road="banter", audio_ready=True)
        seq.hold("first", block=11, seconds=15, lines=2, road="caller", audio_ready=True)
        self.assertEqual(seq.held_keys(), ["first", "later"])
        seq.dispatched("occ", route="page", starts_at=now[0], seconds=15, key="first")
        self.assertEqual(seq.held_keys(), ["later"])


class PatchTests(unittest.TestCase):
    def test_the_tool_is_applied(self):
        got = subprocess.run([sys.executable, str(ROOT / "tools" / "air_order_patch.py"),
                              str(ROOT / "app.py")], capture_output=True, text=True)
        self.assertEqual(got.returncode, 2, got.stdout + got.stderr)


if __name__ == "__main__":
    unittest.main()
