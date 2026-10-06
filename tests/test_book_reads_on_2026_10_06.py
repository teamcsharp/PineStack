"""[book-reads-on] 2026-10-06: Book Time reads on through its book instead of repeating its welcome.

Measured: 32 of 74 Book Time parts in the larder refused by the phase gates for wording; the live
banter road and the segment's door shared one admission, so the opening aired twice; the window
waited for a completeness it never reached.
"""
import ast
import asyncio
import re
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

import app
import dynamic_segments_runtime as dsr
import pantry_lifecycle


def _turns(script, *a, **k):
    out = []
    for m in re.finditer(r"(?:^|\n)\s*([ABCDE]):\s*(.*?)(?=(?:\n\s*[ABCDE]:)|\Z)", str(script or ""), re.S):
        out.append((m.group(1), " ".join(m.group(2).split())))
    return out


def _runtime(larder=None, radio=None, ready=None):
    g = {"DATA_DIR": tempfile.mkdtemp(), "banter_turns": _turns, "dj_settings": lambda: {"host_name": "Dill", "cohost_name": "Skip"},
         "_LARDER": larder if larder is not None else [], "_RADIO": radio or {}}
    rt = dsr.DynamicSegments(g)
    rt.original["dialogue_row_ready"] = ready or (lambda kind, row: bool(row.get("recorded")))
    return rt


def _part(occurrence, phase, script, recorded=True, at=None, handed=False):
    row = {"at": at or time.time(), "script": script, "dynamic_kind": "book_time", "dynamic_occurrence": occurrence,
           "book_phase": phase, "book_cast": {"A": "Dill", "B": "Skip"}, "book_station": "Pine Box FM",
           "book_source": {"title": "Presidential anecdotes -- Boller, Paul F"}, "recorded": recorded}
    if handed:
        row["dynamic_handed_off"] = True
    return row


class Mending(unittest.TestCase):
    def test_an_opening_without_names_or_title_is_mended_and_passes(self):
        rt = _runtime()
        row = _part("o@1", "opening", "A: Welcome listeners to Book Time on Pine Box FM. We are diving in today.\nB: Yes we are, this one is a treat.")
        self.assertTrue(rt.phase_error(row), "before: the gate refuses it")
        fixes = rt.repair_phase(row)
        self.assertIn("the title", fixes)
        self.assertIn("A introduces Dill", fixes)
        self.assertIn("B introduces Skip", fixes)
        self.assertEqual(rt.phase_error(row), "", "after: the gate lets it through")
        self.assertIn("I'm Dill.", row["script"])
        self.assertIn("And I'm Skip.", row["script"])
        self.assertIn("We are reading Presidential anecdotes.", row["script"])
        self.assertEqual(row["book_phase_repaired"]["phase"], "opening")

    def test_an_opening_without_a_welcome_gets_one_and_loses_its_sign_off(self):
        rt = _runtime()
        row = _part("o@1", "opening", "A: I'm Dill, and we are reading Presidential anecdotes.\nB: And I'm Skip. Thanks for Book Time, back to the music.")
        self.assertTrue(rt.phase_error(row))
        fixes = rt.repair_phase(row)
        self.assertIn("the welcome", fixes)
        self.assertIn("a sign-off struck from the opening", fixes)
        self.assertEqual(rt.phase_error(row), "")
        self.assertTrue(row["script"].startswith("A: Welcome to Book Time on Pine Box FM."))

    def test_a_discussion_that_welcomes_is_struck_not_refused(self):
        rt = _runtime()
        row = _part("o@1", "discussion", "A: Welcome back to Book Time on Pine Box FM. The brakes hissed as the train left.\nB: That hiss is the whole point of the passage.")
        self.assertEqual(rt.phase_error(row), "Discussion must not welcome listeners or close Book Time")
        self.assertIn("a welcome struck from the discussion", rt.repair_phase(row))
        self.assertEqual(rt.phase_error(row), "")
        self.assertNotIn("Welcome", row["script"])
        self.assertIn("The brakes hissed", row["script"])

    def test_a_closing_without_its_sign_off_gets_one(self):
        rt = _runtime()
        row = _part("o@1", "closing", "A: So that is where Coolidge left it.\nB: A fine place to stop.")
        self.assertTrue(rt.phase_error(row))
        self.assertIn("the sign-off", rt.repair_phase(row))
        self.assertEqual(rt.phase_error(row), "")
        self.assertIn("That is Book Time on Pine Box FM.", row["script"])

    def test_a_part_that_cannot_be_mended_is_still_refused(self):
        rt = _runtime()
        row = _part("o@1", "verse", "A: la la")
        self.assertEqual(rt.repair_phase(row), "")
        self.assertTrue(rt.phase_error(row))


class Admission(unittest.TestCase):
    def test_only_the_dispatch_door_takes_an_episodes_parts(self):
        rt = _runtime()
        row = _part("dynamic-book_time-900000@100", "opening", "A: hi")
        request = {"kind": "book_time", "slot": {}, "slot_id": "dynamic-book_time-900000", "due_at": 100, "occurrence": ""}
        self.assertFalse(rt.admission_matches(row, request), "the live banter road may not")
        self.assertTrue(rt.admission_matches(row, dict(request, dispatch=True)), "the segment's door may")
        other = _part("dynamic-book_time-900000@50", "discussion", "A: more")
        self.assertFalse(rt.admission_matches(other, dict(request, dispatch=True)))
        rt.carry_from = "dynamic-book_time-900000@50"
        self.assertTrue(rt.admission_matches(other, dict(request, dispatch=True)), "a carried episode's parts may")
        plain = {"script": "A: plain banter"}
        self.assertFalse(rt.admission_matches(plain, dict(request, dispatch=True)), "a plain round is not Book Time")
        self.assertTrue(rt.admission_matches(plain, {"kind": "banter", "slot": {}, "slot_id": "", "due_at": 0, "occurrence": ""}))

    def test_the_wrapper_marks_the_dispatch_door(self):
        src = Path(dsr.__file__).read_text(encoding="utf-8")
        self.assertIn("request['dispatch'] = door == '_ready_shelf_air' and kw.get('pick') is not None", src)


class TheWindow(unittest.TestCase):
    def _radio(self, started):
        return {"sched_slot": {"kind": "book_time", "id": "dynamic-book_time-900000", "minutes": 6.5},
                "sched_pos": {"started": started, "occurrence": ""}}

    def _run(self, rt):
        picks = []

        async def door(kind, track, pick=None, on_handoff=None, **kw):
            picks.append(pick)
            if callable(on_handoff):
                on_handoff()
            return ["said"]
        rt.g["_ready_shelf_air"] = door
        got = asyncio.new_event_loop().run_until_complete(rt.dispatch("book_time"))
        return got, picks

    def test_the_window_airs_its_recorded_opening_without_waiting_for_the_rest(self):
        key = "dynamic-book_time-900000@1000"
        larder = [_part(key, "discussion", "A: later", recorded=False, at=3), _part(key, "opening", "A: Welcome to Book Time", at=2)]
        rt = _runtime(larder, self._radio(1000))
        got, picks = self._run(rt)
        self.assertTrue(got)
        self.assertEqual(picks[0]["book_phase"], "opening")
        self.assertTrue(picks[0]["dynamic_handed_off"])
        self.assertTrue(rt.last[key]["started"])

    def test_a_window_with_nothing_of_its_own_reads_on_from_the_last_episode(self):
        key, old = "dynamic-book_time-900000@2000", "dynamic-book_time-2700000@1200"
        larder = [_part(old, "opening", "A: welcome", at=1, handed=True), _part(old, "discussion", "A: part two", at=2),
                  _part(old, "closing", "A: bye", at=3), _part("dynamic-book_time-900000@500", "discussion", "A: older book", at=0)]
        rt = _runtime(larder, self._radio(2000))
        got, picks = self._run(rt)
        self.assertTrue(got)
        self.assertEqual(picks[0]["script"], "A: part two", "the latest unfinished episode, its next unaired part")
        self.assertEqual(rt.last[key]["carried_from"], old)
        self.assertEqual(rt.carry_from, "", "the carry mark is cleared after the handoff")

    def test_an_episode_does_not_begin_mid_book_when_nothing_can_be_carried(self):
        key = "dynamic-book_time-900000@3000"
        rt = _runtime([_part(key, "discussion", "A: mid", at=1)], self._radio(3000))
        got, picks = self._run(rt)
        self.assertFalse(got)
        self.assertEqual(picks, [])


class OutOfTurnNeverTakesAPart(unittest.TestCase):
    def test_the_larder_doors_skip_segment_parts(self):
        now = time.time()
        part = {"at": now - 9000, "script": "A: Welcome to Book Time", "dynamic_kind": "book_time", "prep_kind": "banter"}
        plain = {"at": now - 5000, "script": "A: a plain round", "prep_kind": "banter"}
        from unittest import mock
        with mock.patch.object(app, "_LARDER", [part, plain]), mock.patch.object(app, "_READY_SHELF_BUSY", set()), \
                mock.patch.object(app, "dialogue_row_ready", lambda kind, row: True):
            self.assertIs(app.larder_oldest_ready(), plain)
        with mock.patch.object(app, "_LARDER", [part]), mock.patch.object(app, "pipeline_log", lambda *a, **k: None):
            self.assertEqual(asyncio.new_event_loop().run_until_complete(app.larder_round_air(part, None)), [])
        src = Path(app.__file__).read_text(encoding="utf-8")
        self.assertIn('if (dialogue_entry(row) or row).get("dynamic_kind"):      # [bank-first-3] never a segment\'s part', src)
        self.assertIn('and not (dialogue_entry(r) or r).get("dynamic_kind")   # [bank-first-3]', src)

    def test_the_lifecycle_out_of_turn_rule_skips_segment_parts(self):
        host = {"RESCUE_ROADS_OPEN": ("banter",), "cupboard_unheard_after": lambda: 120.0, "dialogue_row_ready": lambda k, r: True,
                "_SHELF": {}, "_LARDER": []}
        life = pantry_lifecycle.PantryLifecycle(host, Path(tempfile.mkdtemp()) / "l.json")
        life.policy["mode"] = "air"
        now = time.time()
        self.assertTrue(life.out_of_turn("banter", {"at": now - 1000, "script": "A: x"}))
        self.assertFalse(life.out_of_turn("banter", {"at": now - 1000, "script": "A: x", "dynamic_kind": "book_time"}))


if __name__ == "__main__":
    unittest.main()
