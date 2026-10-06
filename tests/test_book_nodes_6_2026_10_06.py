"""[book-nodes-6] 2026-10-06: the part with a take missing is the one that needs the voicing pass.

The 16:45 opening stood at 3 of 10 takes for an hour: the worker's pre-window pass ran only when every part was
already ready, and only while the larder writer was idle.
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


def _part(occurrence, phase, script, recorded=True, handed=False, at=None):
    row = {"at": at or time.time(), "script": script, "dynamic_kind": "book_time", "dynamic_occurrence": occurrence,
           "book_phase": phase, "book_cast": {"A": "Dill", "B": "Skip"}, "book_station": "Pine Box FM",
           "book_source": {"title": "A History of Brands"}, "recorded": recorded}
    if handed:
        row["dynamic_handed_off"] = True
    return row


class TheVoicingPass(unittest.TestCase):
    def _runtime(self, larder):
        g = {"DATA_DIR": tempfile.mkdtemp(), "banter_turns": _turns, "dj_settings": lambda: {"host_name": "Dill", "cohost_name": "Skip"},
             "_LARDER": larder, "_RADIO": {}}
        rt = dsr.DynamicSegments(g)
        rt.original["dialogue_row_ready"] = lambda kind, row: bool(row.get("recorded"))
        return rt

    def test_unvoiced_parts_names_the_parts_not_ready_opening_first(self):
        key = "dynamic-book_time-900000@1000"
        due = {"kind": "book_time", "slot_id": "dynamic-book_time-900000", "due_at": 1000}
        larder = [_part(key, "discussion", "A: later", recorded=False, at=3), _part(key, "opening", "A: Welcome", recorded=False, at=2),
                  _part(key, "closing", "A: bye", recorded=True, at=4), _part(key, "opening", "A: old", recorded=False, handed=True, at=1)]
        rt = self._runtime(larder)
        got = rt.unvoiced_parts(due)
        self.assertEqual([r["book_phase"] for r in got], ["opening", "discussion"], "not ready, in the episode's order, the handed-off one aside")
        for r in larder:
            r["recorded"] = True
        self.assertEqual(rt.unvoiced_parts(due), [])

    def test_the_worker_sends_the_pass_for_an_unvoiced_part_writer_or_no_writer(self):
        src = Path(dsr.__file__).read_text(encoding="utf-8")
        body = src.split("async def worker(self):", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("if rows and self.unvoiced_parts(due):", body)
        self.assertNotIn("all(self.original['dialogue_row_ready']('banter', row) for row in rows)", body, "every-part-ready is no longer the condition")
        unvoiced_at = body.index("if rows and self.unvoiced_parts(due):")
        writer_at = body.index("_LARDER_WRITING", unvoiced_at)
        self.assertLess(unvoiced_at, writer_at, "the writer's flag guards only the coverage case that follows")

    def test_the_door_s_room_is_ninety_seconds(self):
        self.assertEqual(dsr.DynamicSegments.BOOK_REMAKE_SECONDS, 90.0)


if __name__ == "__main__":
    unittest.main()
