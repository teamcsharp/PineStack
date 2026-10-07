"""[book-nodes-8] 2026-10-06: a dynamic window is its own road, whatever road System 2's clock publishes it under.

/api/system2/hour showed every dynamic slot as kind "banter" with dynamic_kind "book_time"; the door's ledger
read 0 asks at 17:45. The chain and the runtime's active() now read the window's own kind.
"""
import asyncio
import re
import tempfile
import time
import unittest
from pathlib import Path

import app
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


def _system2_radio(started):
    """What System 2's _publish_clock leaves in _RADIO for a Book Time window."""
    return {"sched_kind": "banter",
            "sched_slot": {"kind": "banter", "dynamic_kind": "book_time", "id": "dynamic-book_time-900000",
                           "template_id": "dynamic-book_time-900000", "minutes": 6.5, "engine": "system2",
                           "occurrence": "hour-1791327600000:dynamic-book_time-900000"},
            "sched_pos": {"slot_id": "dynamic-book_time-900000", "started": started,
                          "occurrence": "hour-1791327600000:dynamic-book_time-900000", "preset": "system2"}}


class TheWindowUnderSystem2(unittest.TestCase):
    def _runtime(self, larder, radio):
        g = {"DATA_DIR": tempfile.mkdtemp(), "banter_turns": _turns, "dj_settings": lambda: {"host_name": "Dill", "cohost_name": "Skip"},
             "_LARDER": larder, "_RADIO": radio, "_READY_SHELF_REFUSED": [""]}
        rt = dsr.DynamicSegments(g)
        rt.original["dialogue_row_ready"] = lambda kind, row: bool(row.get("recorded"))
        rt.log = lambda *a, **k: None
        return rt

    def test_active_answers_the_window_s_own_kind(self):
        rt = self._runtime([], _system2_radio(1000))
        due = rt.active()
        self.assertEqual(due["kind"], "book_time", "System 2 said banter; the window is Book Time's")
        self.assertEqual(rt.occurrence(due), "dynamic-book_time-900000@1000", "the parts' key, from the template id and the start")
        plain = self._runtime([], {"sched_slot": {"kind": "banter", "id": "hour-03"}, "sched_pos": {"started": 1000}})
        self.assertEqual(plain.active()["kind"], "banter", "a plain banter entry stays banter")

    def test_the_door_is_asked_and_the_window_is_owned_under_system2(self):
        key = "dynamic-book_time-900000@1000"
        rt = self._runtime([_part(key, "opening", "A: Welcome to Book Time")], _system2_radio(1000))
        self.assertTrue(rt.window_owned())
        picks = []

        async def door(kind, track, pick=None, on_handoff=None, **kw):
            picks.append(pick)
            if callable(on_handoff):
                on_handoff()
            return ["said"]
        rt.g["_ready_shelf_air"] = door
        self.assertTrue(asyncio.new_event_loop().run_until_complete(rt.dispatch("book_time")))
        self.assertEqual(picks[0]["book_phase"], "opening")
        self.assertEqual(rt.last[key]["door"]["asked"], 1)

    def test_the_chain_serves_a_dynamic_window_as_its_own_kind(self):
        src = Path(app.__file__).read_text(encoding="utf-8")
        at = src.index('kind = str(_slot.get("kind") or "")')
        block = src[at:at + 1200]
        self.assertIn('_dyn = str(_slot.get("dynamic_kind") or "")', block)
        self.assertIn('if _dyn in ("book_time", "sfx_supercut"):', block)
        self.assertIn("kind = _dyn", block)
        self.assertIn('if kind in ("book_time", "sfx_supercut"):', src.split("async def schedule_extra_round", 1)[1][:600],
                      "the segment road still answers those kinds")


if __name__ == "__main__":
    unittest.main()
