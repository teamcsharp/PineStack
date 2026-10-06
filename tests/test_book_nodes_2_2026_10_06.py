"""[book-nodes-2] 2026-10-06: the shelf re-read notes and keeps; a turned-away part comes back.

"I dont want wedges or gates." The 14:45 window: three closings written, each struck by the re-read, none aired.
"""
import re
import tempfile
import time
import unittest
from pathlib import Path

import dynamic_segments_runtime as dsr


def _turns(script, *a, **k):
    out = []
    for m in re.finditer(r"(?:^|\n)\s*([ABCDE]):\s*(.*?)(?=(?:\n\s*[ABCDE]:)|\Z)", str(script or ""), re.S):
        out.append((m.group(1), " ".join(m.group(2).split())))
    return out


def _runtime(larder=None):
    g = {"DATA_DIR": tempfile.mkdtemp(), "banter_turns": _turns, "dj_settings": lambda: {"host_name": "Dill", "cohost_name": "Skip"},
         "_LARDER": larder if larder is not None else [], "_RADIO": {}}
    rt = dsr.DynamicSegments(g)
    rt.original["dialogue_row_ready"] = lambda kind, row: True
    return rt


def _part(occurrence, phase, script):
    return {"at": time.time(), "script": script, "dynamic_kind": "book_time", "dynamic_occurrence": occurrence,
            "book_phase": phase, "book_cast": {"A": "Dill", "B": "Skip"}, "book_station": "Pine Box FM",
            "book_source": {"title": "A History of Brands"}, "sid": "s-" + phase, "recorded": True}


class TheShelfReRead(unittest.TestCase):
    def test_prepare_book_never_strikes_a_part(self):
        src = Path(dsr.__file__).read_text(encoding="utf-8")
        body = src.split("async def prepare_book", 1)[1]
        body = body.split("\n    async def ", 1)[0] if "\n    async def " in body else body
        body = body.split("\n    def ", 1)[0]
        self.assertNotIn("self.reject_phase(", body, "the writer's re-read of the shelf strikes nothing")
        self.assertIn("self.note_phase(row, why)", body, "what the old rule would have said is a note")
        self.assertNotIn("rows = kept", body)

    def test_a_turned_away_part_comes_back_even_when_the_old_rule_still_objects(self):
        occ = "dynamic-book_time-2700000@1791319500"
        bad = _part(occ, "closing", "A: Oh, come ON! We need to start digging into this.\nB: Incredible! It is all about patience now.")
        rt = _runtime([bad])
        why = rt.phase_error(bad)
        self.assertTrue(why, "the old closing rule still has an opinion about it")
        rt.reject_phase(bad, why)
        self.assertTrue(bad["dynamic_superseded"])
        self.assertEqual(rt.book_rows(occ), [], "a superseded part is off the episode")
        rows = []
        back = rt.readmit_phases(occ, rows)
        self.assertEqual(back, 1, "it comes back whatever the rule thinks")
        self.assertNotIn("dynamic_superseded", bad)
        self.assertNotIn("dynamic_phase_rejected", bad)
        self.assertEqual(bad["book_phase_note"]["phase"], "closing", "the rule's opinion is kept as a note")
        self.assertEqual(len(rt.book_rows(occ)), 1)


if __name__ == "__main__":
    unittest.main()
