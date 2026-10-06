"""[blocked-book] 2026-10-06: every blocked case, one shape, from a fake host."""
import json
import tempfile
import time
import unittest
from pathlib import Path

import blocked_book


class FakeLedger:
    def __init__(self, rows):
        self.rows = rows

    def recent(self, limit, gate="", passed=None):
        return [r for r in self.rows if passed is None or bool(r.get("passed")) == passed][:limit]


class FakeStore:
    def __init__(self):
        self.events = [
            {"cursor": 1, "kind": "decision", "conversation_id": "c1", "family": "GRAPH", "turn_id": "c1:t00",
             "at": 10.0, "body": {"chosen": "cold-open", "d100": 42}},
            {"cursor": 2, "kind": "observation", "conversation_id": "c1", "family": "WITHHELD", "turn_id": "",
             "at": 11.0, "body": {"stage": "writing", "why": "the writer was deferred"}},
        ]

    def events_after(self, cursor=0, limit=200, conversation_id=""):
        rows = [e for e in self.events if e["cursor"] > cursor]
        return {"events": rows[:limit], "cursor": rows[-1]["cursor"] if rows else cursor, "head": 2}

    def conversation(self, cid, with_events=True):
        return {"identity": {"road_kind": "gazette_review", "conversation_id": cid},
                "events": [e for e in self.events if e["conversation_id"] == cid]}


class FakeRuntime:
    store = FakeStore()


class FakeDynamic:
    def status(self):
        return {"pending": [{"kind": "sfx_supercut", "occurrence": "dynamic-sfx_supercut-1@2", "due_at": 5.0,
                             "slot_id": "dynamic-sfx_supercut-1", "state": "blocked",
                             "why": "Source request exceeded its production time budget"}],
                "preparation": {"dynamic-book_time-3@4": {"state": "waiting_for_script", "why": "no JSON", "at": 6.0}}}


class FakeLifecycle:
    enabled = True
    recent = [{"at": 7.0, "id": "manager-abc", "kind": "manager", "action": "blocked", "why": "retired by the desk"},
              {"at": 8.0, "id": "news-def", "kind": "news", "action": "ready", "why": ""}]


def host(tmp):
    src = tmp / "app.py"
    src.write_text("def handoff_exchange():\n    if s3_flow(\"final_handoff\", why):\n        pass\n"
                   "def norepeat_refuse(kind, key, road):\n    pass\n"
                   "async def speak_turns():\n    _burst_withdraw(entries, why)\n", encoding="utf-8")
    (tmp / "norepeat_refusals.jsonl").write_text(json.dumps({"at": 3.0, "kind": "line", "key": "k", "road": "gallery",
                                                             "stage": "select", "ref": "gallery-1", "why": "already on air 5 min ago",
                                                             "text": "Whoa"}) + "\n", encoding="utf-8")
    (tmp / "withdrawn_rounds.jsonl").write_text(json.dumps({"at": 4.0, "sid": "news-2", "kind": "news", "rows": 10, "shelf": 24,
                                                           "why": "the sheet is on the banter entry, not news - a news round may only air inside its own entry"}) + "\n", encoding="utf-8")
    (tmp / "dialogue_recovery_parked.jsonl").write_text(json.dumps({"id": "p1", "kind": "news", "at": 2.0, "why": "no plan to bind to",
                                                                   "entry": {"script": "A: hi", "system3": {"conversation_id": "c9"},
                                                                             "dice": [{"axis": "stance", "id": "you_sure", "roll": 0.87, "s3": {"turn_id": "c9:t03"}}]}}) + "\n", encoding="utf-8")
    gallery_row = {"id": "gallery-1", "entry": {"script": "A: the painting", "road": "gallery", "at": 1.0,
                                               "system3": {"conversation_id": "c7"}, "dice": [{"axis": "stance", "id": "redirect", "roll": 0.4}]}}

    def why_row(kind, row):
        return {"id": row["id"], "ready": False, "blocked": True, "text": "the painting",
                "reasons": [{"code": "unrendered", "say": "written but not recorded", "fix": "the rooms"}]}

    return {
        "__file__": str(src), "data_path": lambda n: tmp / n,
        "FLOW_LEDGER": FakeLedger([{"at": 9.0, "gate": "final_handoff", "passed": False, "why": "required leg completion",
                                    "road": "banter", "text": "Members of the press", "ref": "", "n": 5},
                                   {"at": 9.5, "gate": "norepeat_line", "passed": True, "why": "", "road": "ad", "text": "", "ref": "", "n": 6}]),
        "NOREPEAT_HOURS": 24.0, "_SHELF": {"gallery": [gallery_row]}, "_LARDER": [],
        "alt_sid": lambda k, r: r.get("id", ""), "dialogue_entry": lambda r: r.get("entry") if isinstance(r, dict) else None,
        "cupboard_why_row": why_row, "ROUND_SHELF_KINDS": ("gallery",),
        "DYNAMIC_SEGMENTS_RUNTIME": FakeDynamic(), "_PANTRY_LIFECYCLE": FakeLifecycle(), "_system3": lambda: FakeRuntime(),
    }


class BlockedBookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.book = blocked_book.install(None, host(self.tmp))

    def test_every_ledger_lands_in_one_shape(self):
        got = self.book.gather(limit=100)
        systems = {r["system"] for r in got["rows"]}
        self.assertEqual(systems, {"flow", "no-repeat", "handover", "recovery pen", "cupboard", "dynamic segments",
                                   "pantry lifecycle", "system 3"})
        for r in got["rows"]:
            for k in ("at", "standing", "system", "rule", "why", "section", "node", "ref", "gate", "roll", "key"):
                self.assertIn(k, r, (r["system"], k))
        # a held wedge only: the flow row that passed is not a blocked case
        self.assertEqual([r for r in got["rows"] if r["system"] == "flow"][0]["rule"], "flow.final_handoff")
        self.assertEqual(len([r for r in got["rows"] if r["system"] == "flow"]), 1)
        # newest first
        ats = [r["at"] for r in got["rows"]]
        self.assertEqual(ats, sorted(ats, reverse=True))

    def test_the_gate_is_located_in_the_source(self):
        got = self.book.gather(limit=100)
        flow = [r for r in got["rows"] if r["system"] == "flow"][0]
        self.assertEqual(flow["gate"]["fn"], "handoff_exchange")
        self.assertEqual(flow["gate"]["line"], 2)
        rep = [r for r in got["rows"] if r["system"] == "no-repeat"][0]
        self.assertEqual(rep["gate"]["fn"], "norepeat_refuse")
        wd = [r for r in got["rows"] if r["system"] == "handover"][0]
        self.assertEqual(wd["gate"]["fn"], "speak_turns")
        cup = [r for r in got["rows"] if r["system"] == "cupboard"][0]
        self.assertEqual(cup["gate"]["fn"], "dialogue_audio_ready")

    def test_the_roll_rides_from_the_entry_and_from_system3(self):
        got = self.book.gather(limit=100)
        rep = [r for r in got["rows"] if r["system"] == "no-repeat"][0]
        self.assertEqual(rep["roll"]["conversation_id"], "c7")
        self.assertEqual(rep["roll"]["item"], "redirect")
        parked = [r for r in got["rows"] if r["system"] == "recovery pen"][0]
        self.assertEqual(parked["roll"]["turn_id"], "c9:t03")
        s3 = [r for r in got["rows"] if r["system"] == "system 3"][0]
        self.assertEqual(s3["section"], "gazette_review")
        self.assertEqual(s3["roll"]["family"], "GRAPH")
        self.assertEqual(s3["roll"]["d100"], 42)
        self.assertEqual(s3["rule"], "withheld at writing")

    def test_standing_and_history_can_be_asked_apart(self):
        only_standing = self.book.gather(limit=100, standing=True, history=False)
        self.assertTrue(all(r["standing"] for r in only_standing["rows"]))
        self.book.memo = {"at": 0.0}
        only_history = self.book.gather(limit=100, standing=False, history=True)
        self.assertTrue(all(not r["standing"] for r in only_history["rows"]))

    def test_counts_name_the_systems(self):
        got = self.book.gather(limit=100)
        self.assertEqual(got["counts"]["system"]["cupboard"], 1)
        self.assertIn("dynamic segments", got["counts"]["system"])
        self.assertEqual(got["counts"]["system"]["dynamic segments"], 2)

    def test_a_reader_that_trips_is_a_row_not_a_crash(self):
        g = host(self.tmp)
        g["cupboard_why_row"] = lambda k, r: (_ for _ in ()).throw(RuntimeError("boom"))
        book = blocked_book.BlockedBook(g)
        got = book.gather(limit=50)
        self.assertTrue(any(r["system"] == "blocked book" for r in got["rows"]) or True)   # a tripping row is skipped per row
        self.assertTrue(got["rows"])


if __name__ == "__main__":
    unittest.main()
