"""[book-nodes-4] 2026-10-06: a segment's window owns the air; the cupboard's out-of-turn doors stand aside in it.

The 15:45 window: the opening was prepared, and the unheard sweep put two banked banter rounds out of turn
inside the window; the segment's door found the floor busy and said nothing.
"""
import asyncio
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import app
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


def _radio(kind, started, slot_id="dynamic-book_time-900000"):
    return {"sched_slot": {"kind": kind, "id": slot_id, "minutes": 6.5}, "sched_pos": {"started": started, "occurrence": ""}}


def _runtime(larder=None, radio=None, shelf=None):
    g = {"DATA_DIR": tempfile.mkdtemp(), "banter_turns": _turns, "dj_settings": lambda: {"host_name": "Dill", "cohost_name": "Skip"},
         "_LARDER": larder if larder is not None else [], "_RADIO": radio or {}, "_SHELF": shelf or {}}
    rt = dsr.DynamicSegments(g)
    rt.original["dialogue_row_ready"] = lambda kind, row: bool(row.get("recorded"))
    return rt


class TheWindowOwnsTheAir(unittest.TestCase):
    def test_a_plain_entry_owns_nothing(self):
        rt = _runtime([_part("dynamic-book_time-900000@1000", "opening", "A: hi")], _radio("banter", 1000))
        self.assertFalse(rt.window_owned())

    def test_a_book_time_window_with_a_part_of_its_own_owns_the_air(self):
        key = "dynamic-book_time-900000@1000"
        rt = _runtime([_part(key, "opening", "A: hi", recorded=False)], _radio("book_time", 1000))
        self.assertTrue(rt.window_owned(), "a part not yet handed off, even one still re-makeable, holds the window")

    def test_a_window_whose_parts_all_went_out_and_nothing_to_carry_owns_nothing(self):
        key = "dynamic-book_time-900000@1000"
        rt = _runtime([_part(key, "opening", "A: hi", handed=True)], _radio("book_time", 1000))
        self.assertFalse(rt.window_owned(), "the sweep may fill the rest of the window")

    def test_a_window_with_a_carry_owns_the_air(self):
        key, old = "dynamic-book_time-900000@2000", "dynamic-book_time-2700000@1200"
        larder = [_part(old, "opening", "A: welcome", at=1, handed=True), _part(old, "discussion", "A: part two", at=2)]
        rt = _runtime(larder, _radio("book_time", 2000))
        self.assertTrue(rt.window_owned())

    def test_a_supercut_window_with_its_row_owns_the_air(self):
        key = "dynamic-sfx_supercut-3480000@3000"
        rt = _runtime([], _radio("sfx_supercut", 3000, "dynamic-sfx_supercut-3480000"),
                      {"sfx_supercut": [{"dynamic_occurrence": key, "audio": "x.wav"}]})
        self.assertTrue(rt.window_owned())
        rt.g["_SHELF"]["sfx_supercut"][0]["dynamic_handed_off"] = True
        self.assertFalse(rt.window_owned())

    def test_install_hands_the_station_the_question(self):
        src = Path(dsr.__file__).read_text(encoding="utf-8")
        self.assertIn("g['dynamic_segment_window_owned'] = runtime.window_owned", src)
        self.assertTrue(callable(getattr(app, "dynamic_segment_window_owned", None)), "installed on the station")


class TheDoorSaysWhatItDid(unittest.TestCase):
    def _run(self, rt, door_says):
        picks, logs = [], []
        rt.log = lambda message, error="": logs.append((message, error))

        async def door(kind, track, pick=None, on_handoff=None, **kw):
            picks.append(pick)
            if door_says and callable(on_handoff):
                on_handoff()
            return ["said"] if door_says else []
        rt.g["_ready_shelf_air"] = door
        got = asyncio.new_event_loop().run_until_complete(rt.dispatch("book_time"))
        return got, picks, logs

    def test_nothing_airable_is_said(self):
        key = "dynamic-book_time-900000@1000"
        rt = _runtime([_part(key, "opening", "A: hi", recorded=False)], _radio("book_time", 1000))
        got, picks, logs = self._run(rt, True)
        self.assertFalse(got)
        self.assertEqual(picks, [])
        self.assertTrue(any("nothing of the episode is airable yet" in m for m, _ in logs), logs)

    def test_the_airing_and_the_refusal_are_said(self):
        key = "dynamic-book_time-900000@1000"
        rt = _runtime([_part(key, "opening", "A: Welcome")], _radio("book_time", 1000))
        got, picks, logs = self._run(rt, True)
        self.assertTrue(got)
        self.assertTrue(any(m == "Book Time window: aired the opening part" for m, _ in logs), logs)
        rt2 = _runtime([_part(key, "opening", "A: Welcome")], _radio("book_time", 1000))
        got, picks, logs = self._run(rt2, False)
        self.assertFalse(got)
        self.assertTrue(any("the door refused the opening part" in m for m, _ in logs), logs)


class TheCupboardStandsAside(unittest.TestCase):
    def test_larder_oldest_ready_answers_nothing_while_a_window_is_owned(self):
        now = time.time()
        plain = {"at": now - 5000, "script": "A: a plain round", "prep_kind": "banter"}
        with mock.patch.object(app, "_LARDER", [plain]), mock.patch.object(app, "_READY_SHELF_BUSY", set()), \
                mock.patch.object(app, "dialogue_row_ready", lambda kind, row: True), \
                mock.patch.object(app, "dynamic_segment_window_owned", lambda: True, create=True):
            self.assertIsNone(app.larder_oldest_ready())
        with mock.patch.object(app, "_LARDER", [plain]), mock.patch.object(app, "_READY_SHELF_BUSY", set()), \
                mock.patch.object(app, "dialogue_row_ready", lambda kind, row: True), \
                mock.patch.object(app, "dynamic_segment_window_owned", lambda: False, create=True):
            self.assertIs(app.larder_oldest_ready(), plain)

    def test_the_sweep_reads_the_same_question(self):
        src = Path(app.__file__).read_text(encoding="utf-8")
        self.assertIn('return _unheard_no("a segment\'s window owns the air: nothing goes out of turn inside it")', src)
        self.assertIn('_owned = globals().get("dynamic_segment_window_owned")               # [book-nodes-4] Book Time / the supercut', src)


if __name__ == "__main__":
    unittest.main()
