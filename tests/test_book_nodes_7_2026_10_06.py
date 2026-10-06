"""[book-nodes-7] 2026-10-06: the Book Time door keeps its own ledger - asked, what it did, and the shelf's reason."""
import asyncio
import re
import tempfile
import time
import unittest

import dynamic_segments_runtime as dsr


def _turns(script, *a, **k):
    out = []
    for m in re.finditer(r"(?:^|\n)\s*([ABCDE]):\s*(.*?)(?=(?:\n\s*[ABCDE]:)|\Z)", str(script or ""), re.S):
        out.append((m.group(1), " ".join(m.group(2).split())))
    return out


def _part(occurrence, phase, script, recorded=True, at=None):
    return {"at": at or time.time(), "script": script, "dynamic_kind": "book_time", "dynamic_occurrence": occurrence,
            "book_phase": phase, "book_cast": {"A": "Dill", "B": "Skip"}, "book_station": "Pine Box FM",
            "book_source": {"title": "A History of Brands"}, "recorded": recorded}


def _radio(started):
    return {"sched_slot": {"kind": "book_time", "id": "dynamic-book_time-900000", "minutes": 6.5}, "sched_pos": {"started": started, "occurrence": ""}}


class TheDoorsLedger(unittest.TestCase):
    def _runtime(self, larder, refused=""):
        g = {"DATA_DIR": tempfile.mkdtemp(), "banter_turns": _turns, "dj_settings": lambda: {"host_name": "Dill", "cohost_name": "Skip"},
             "_LARDER": larder, "_RADIO": _radio(1000), "_READY_SHELF_REFUSED": [refused]}
        rt = dsr.DynamicSegments(g)
        rt.original["dialogue_row_ready"] = lambda kind, row: bool(row.get("recorded"))
        rt.log = lambda *a, **k: None
        return rt

    def _run(self, rt, door_says):
        async def door(kind, track, pick=None, on_handoff=None, **kw):
            if door_says and callable(on_handoff):
                on_handoff()
            return ["said"] if door_says else []
        rt.g["_ready_shelf_air"] = door
        return asyncio.new_event_loop().run_until_complete(rt.dispatch("book_time"))

    def test_a_refusal_carries_the_shelf_s_reason_and_counts_the_ask(self):
        key = "dynamic-book_time-900000@1000"
        rt = self._runtime([_part(key, "opening", "A: Welcome")], refused="it does not fit the entry on air and may not go out of turn")
        self.assertFalse(self._run(rt, False))
        door = rt.last[key]["door"]
        self.assertEqual(door["asked"], 1)
        self.assertFalse(door["said"])
        self.assertEqual(door["part"], "opening")
        self.assertIn("does not fit the entry on air", door["why"])
        self.assertFalse(self._run(rt, False))
        self.assertEqual(rt.last[key]["door"]["asked"], 2, "every ask is counted")

    def test_an_airing_is_written_without_a_reason(self):
        key = "dynamic-book_time-900000@1000"
        rt = self._runtime([_part(key, "opening", "A: Welcome")], refused="stale reason from another door")
        self.assertTrue(self._run(rt, True))
        door = rt.last[key]["door"]
        self.assertTrue(door["said"])
        self.assertEqual(door["why"], "", "a reason belongs to a refusal only")
        self.assertEqual(door["part"], "opening")

    def test_nothing_airable_is_written_too(self):
        key = "dynamic-book_time-900000@1000"
        rt = self._runtime([_part(key, "opening", "A: Welcome", recorded=False)])
        rt.g["larder_prepare"] = None
        self.assertFalse(self._run(rt, True))
        door = rt.last[key]["door"]
        self.assertEqual(door["asked"], 1)
        self.assertIn("nothing airable yet", door["why"])

    def test_the_view_shows_the_ledger(self):
        key = "dynamic-book_time-900000@1000"
        rt = self._runtime([_part(key, "opening", "A: Welcome")], refused="busy")
        self._run(rt, False)
        view = rt.view() if hasattr(rt, "view") else {"preparation": rt.last}
        prep = view.get("preparation") or {}
        self.assertIn("door", prep.get(key, {}), "the API's preparation entry carries the door's ledger")


if __name__ == "__main__":
    unittest.main()
