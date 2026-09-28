"""[s3-segment] Every line of the script names the scheduled segment it went out in.

The operator (2026-09-28): "every conversation should be chained as the
"segment" per the station that is scheduled with everything for that segment
occuring within the section of the messenger view."

The failure this replaces was silent: nothing on the record named the entry a
line went out in. identity.schedule_occurrence_id was empty on 276 of 276
conversations, no ledger or air-log row carried an entry, segment_inspect
(#1168) said "the ledger does not record which one a finished round was
written for", and the director attributed aired lines to entries by their time
window. The stamp is taken when a line takes its PLACE in the script (its
block) - measured over six hours, stamped then a segment never reopens walking
the script in order; stamped when heard it would have reopened 17 times.
"""
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

ROOT = Path(app.__file__).resolve().parent


def s2_position(occ, template, start, ends, label, kind, index=4):
    pos = {"slot_id": template, "started": start, "occurrence": occ, "hour": "2026-09-28T03",
           "index": index, "preset": "system2", "deadline": ends}
    slot = {"id": template, "template_id": template, "kind": kind, "label": label, "start": start,
            "deadline": ends, "minutes": (ends - start) / 60.0, "system2_slot_id": occ, "occurrence": occ,
            "engine": "system2", "hour_key": "2026-09-28T03"}
    return pos, slot


class FakeSystem2:
    def __init__(self, plans=(), on_brief=None):
        self.enabled = True
        self._plans = list(plans)
        self._event_plans = []
        self.briefs = 0
        self.on_brief = on_brief

    def current_slot_brief(self):
        self.briefs += 1
        if self.on_brief:
            self.on_brief()
        return {}


class Station:
    """The schedule's published position, System2 and the ledger, in a sandbox."""

    def __init__(self, pos=None, slot=None, system2=None):
        self.pos, self.slot, self.system2 = pos, slot, system2

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.stack = ExitStack()
        for name, value in (("SCRIPT_LEDGER_PATH", root / "script_ledger.jsonl"),
                            ("SCRIPT_LEDGER_SEQ_PATH", root / "seq.json"),
                            ("SCRIPT_RESERVED_PATH", root / "reserved.jsonl"),
                            ("_SCRIPT_LEDGER_MEMO", {"at": 0.0, "rows": []}),
                            ("_SCRIPT_RESERVED", {}),
                            ("_SCRIPT_RESERVED_STATE", {"loaded": False}),
                            ("_SEGMENT_SEEN", [])):
            self.stack.enter_context(mock.patch.object(app, name, value))
        self.stack.enter_context(mock.patch.dict(app.__dict__, {
            "system3_observe_ledger": None, "system3_segment_block": None,
            "_system2": (lambda: self.system2) if self.system2 is not None else None}))
        self.stack.enter_context(mock.patch.dict(app._RADIO, {"sched_pos": dict(self.pos or {}),
                                                             "sched_slot": dict(self.slot or {})}))
        return self

    def __exit__(self, *exc):
        self.stack.close()
        self.tmp.cleanup()

    def rows(self):
        path = app.SCRIPT_LEDGER_PATH
        return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def lines(prefix, n=3, cid="c1"):
    return [{"line_id": "%s%d" % (prefix, i), "who": "dj", "kind": "dialogue", "text": "line %d" % i,
             "seconds": 1.0, "turn": i, "system3": {"conversation_id": cid, "mode": "active",
                                                   "turn_id": "%s:t%02d" % (cid, i)}} for i in range(n)]


class SegmentOnAirTests(unittest.TestCase):
    def test_now_is_the_engines_published_position(self):
        now = time.time()
        pos, slot = s2_position("hour-1:hour-05", "hour-05", now - 60, now + 180, "Banter during recordings", "banter")
        with Station(pos, slot):
            got = app.segment_on_air()
        self.assertEqual(got, {"id": "hour-1:hour-05", "template": "hour-05", "kind": "banter",
                               "label": "Banter during recordings", "start": round(now - 60, 3),
                               "ends": round(now + 180, 3), "hour": "2026-09-28T03", "index": 4,
                               "engine": "system2"})

    def test_the_legacy_walk_is_a_segment_too(self):
        now = time.time()
        pos = {"preset": "canonical hour", "index": 2, "started": now - 30, "hour": "", "slot_id": "slot-news",
               "occurrence": "a" * 40, "actions_done": []}
        slot = {"id": "slot-news", "kind": "news", "label": "News coverage", "minutes": 3}
        with Station(pos, slot):
            got = app.segment_on_air()
            self.assertEqual((got["id"], got["kind"], got["label"], got["engine"]),
                             ("a" * 40, "news", "News coverage", "schedule"))
            self.assertAlmostEqual(got["ends"], now - 30 + 180, places=2)
            app._RADIO["sched_slot"] = {"id": "slot-other", "kind": "caller", "label": "Call"}
            stale = app.segment_on_air()
        self.assertEqual((stale["id"], stale["kind"], stale["label"]), ("a" * 40, "", ""),
                         "an entry published for another position is not this one's")

    def test_no_running_order_is_no_segment(self):
        with Station({}, {}):
            self.assertEqual(app.segment_on_air(), {})

    def test_a_closed_system2_window_is_read_again(self):
        now = time.time()
        old_pos, old_slot = s2_position("hour-1:hour-04", "hour-04", now - 300, now - 10, "Ad read", "ad")
        new_pos, new_slot = s2_position("hour-1:hour-05", "hour-05", now - 10, now + 230, "Banter", "banter")

        def publish():
            app._RADIO["sched_pos"], app._RADIO["sched_slot"] = dict(new_pos), dict(new_slot)
        s2 = FakeSystem2(on_brief=publish)
        with Station(old_pos, old_slot, system2=s2):
            got = app.segment_on_air()
        self.assertEqual(s2.briefs, 1)
        self.assertEqual(got["id"], "hour-1:hour-05")

    def test_a_moment_already_past_is_the_segment_the_air_was_in(self):
        now = time.time()
        a = {"id": "A", "template": "a", "kind": "ad", "label": "Ad read", "start": now - 600, "ends": now - 300,
             "hour": "", "index": 1, "engine": "system2", "seen": now - 590}
        b = {"id": "B", "template": "b", "kind": "banter", "label": "Banter", "start": now - 300, "ends": now + 300,
             "hour": "", "index": 2, "engine": "system2", "seen": now - 200}
        plan = {"slots": [{"id": "Z", "template_id": "z", "kind": "news", "label": "News", "start": now - 2000,
                           "deadline": now - 1800, "hour_key": "2026-09-28T02", "ordinal": 0}]}
        with Station({}, {}, system2=FakeSystem2(plans=[plan])):
            app._SEGMENT_SEEN.extend([a, b])
            self.assertEqual(app.segment_on_air(now - 400)["id"], "A")
            self.assertEqual(app.segment_on_air(now - 250)["id"], "B", "its window, before it was first seen")
            self.assertNotIn("seen", app.segment_on_air(now - 250))
            self.assertEqual(app.segment_on_air(now - 1900)["id"], "Z", "System2's planned window")
            self.assertEqual(app.segment_on_air(now - 5000), {}, "never a guess")
        with Station({}, {}):
            app._SEGMENT_SEEN.extend([a])
            self.assertEqual(app.segment_on_air(now - 1900), {})

    def test_the_segments_handed_out_are_remembered_once_each(self):
        now = time.time()
        pos, slot = s2_position("hour-1:hour-05", "hour-05", now - 60, now + 180, "Banter", "banter")
        with Station(pos, slot):
            app.segment_on_air()
            app.segment_on_air()
            self.assertEqual([x["id"] for x in app._SEGMENT_SEEN], ["hour-1:hour-05"])


class LedgerStampTests(unittest.TestCase):
    def test_every_row_of_a_block_names_the_segment_on_air(self):
        now = time.time()
        pos, slot = s2_position("hour-1:hour-05", "hour-05", now - 60, now + 180, "Banter during recordings", "banter")
        with Station(pos, slot) as st:
            block = app.script_ledger_commit("sid-1", lines("L"), "banter")
            rows = st.rows()
        self.assertEqual(block, 1)
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["segment"]["id"] for r in rows}, {"hour-1:hour-05"})
        self.assertEqual(rows[0]["segment"]["label"], "Banter during recordings")

    def test_a_numbered_line_names_the_segment_it_was_numbered_in(self):
        """A line numbered at the page door and heard later is written under the
        moment it took its number - the order the document keeps."""
        now = time.time()
        pos, slot = s2_position("hour-1:hour-06", "hour-06", now - 30, now + 210, "Upstairs", "manager")
        before = {"id": "hour-1:hour-05", "template": "hour-05", "kind": "banter", "label": "Banter",
                  "start": now - 270, "ends": now - 30, "hour": "", "index": 4, "engine": "system2",
                  "seen": now - 260}
        with Station(pos, slot) as st:
            app._SEGMENT_SEEN.append(before)
            app.script_ledger_commit("", lines("I", 1, cid="i1"), "", block=7, at=now - 40)
            app.script_ledger_commit("", lines("J", 1, cid="i2"), "")
            rows = st.rows()
        self.assertEqual([(r["block"], r["segment"]["id"]) for r in rows],
                         [(7, "hour-1:hour-05"), (8, "hour-1:hour-06")])

    def test_the_register_is_handed_every_block(self):
        now = time.time()
        pos, slot = s2_position("hour-1:hour-05", "hour-05", now - 60, now + 180, "Banter", "banter")
        got = []
        with Station(pos, slot):
            app.__dict__["system3_segment_block"] = lambda *a: got.append(a)
            rows = lines("L")
            block = app.script_ledger_commit("sid-9", rows, "banter")
        self.assertEqual(len(got), 1)
        b, at, sid, handed, seg, road = got[0]
        self.assertEqual((b, sid, road), (block, "sid-9", "banter"))
        self.assertIs(handed, rows)
        self.assertEqual(seg["id"], "hour-1:hour-05")
        self.assertAlmostEqual(at, now, delta=5)

    def test_no_schedule_no_stamp_and_no_register(self):
        got = []
        with Station({}, {}) as st:
            app.__dict__["system3_segment_block"] = lambda *a: got.append(a)
            app.script_ledger_commit("sid-1", lines("L"), "banter")
            rows = st.rows()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all("segment" not in r for r in rows))
        self.assertEqual(got, [])

    def test_a_register_that_fails_never_costs_the_script(self):
        now = time.time()
        pos, slot = s2_position("hour-1:hour-05", "hour-05", now - 60, now + 180, "Banter", "banter")

        def boom(*a):
            raise RuntimeError("the register is down")
        with Station(pos, slot) as st:
            app.__dict__["system3_segment_block"] = boom
            block = app.script_ledger_commit("sid-1", lines("L"), "banter")
            rows = st.rows()
        self.assertEqual(block, 1)
        self.assertEqual(len(rows), 3)

    def test_the_segment_inspector_names_the_one_entry(self):
        now = time.time()
        pos, slot = s2_position("hour-1:hour-05", "hour-05", now - 60, now + 180, "Banter during recordings", "banter")
        with Station(pos, slot):
            block = app.script_ledger_commit("sid-1", lines("L"), "banter")
            app._SCRIPT_LEDGER_MEMO["at"] = 0.0
            got = app.segment_inspect(block)
        self.assertEqual(got["segment"]["id"], "hour-1:hour-05")
        self.assertEqual(got["slot"]["occurrence"], "hour-1:hour-05")
        self.assertEqual(got["slot"]["slot_id"], "hour-05")
        self.assertIn("the ledger recorded the scheduled segment", got["slot"]["say"])


class PatchTests(unittest.TestCase):
    def test_the_tool_is_applied(self):
        got = subprocess.run([sys.executable, str(ROOT / "tools" / "system3_segment_stamp_patch.py"),
                              str(ROOT / "app.py")], capture_output=True, text=True)
        self.assertEqual(got.returncode, 2, got.stdout + got.stderr)


if __name__ == "__main__":
    unittest.main()
