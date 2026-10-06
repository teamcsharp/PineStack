"""[bank-first] 2026-10-06: bank first, everywhere it fits.

"Make sure there is nothing in the cupboard that sits there and gets no play."
Measured before the fix: 361 finished rounds never heard, 304 past the dial, the
sweep 36 walks / 0 airings; gazette_review and banter shut out of turn, banter rows
refused at the shelf door, the gazette slot never in turn for its own shelf, the
mixtape intro never looking at its ten banked intros.
"""
import ast
import asyncio
import tempfile
import time
import types
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import app
import gazette_review_runtime
import pantry_lifecycle

SOURCE = Path(app.__file__).read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function(name):
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError("no top-level function %s" % name)


def _calls(node):
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class RoadsAndDial(unittest.TestCase):
    def test_the_out_of_turn_door_names_the_gazette_review_and_banter(self):
        self.assertIn("gazette_review", app.RESCUE_ROADS_OPEN)
        self.assertIn("banter", app.RESCUE_ROADS_OPEN)
        self.assertNotIn("mixtape", app.RESCUE_ROADS_OPEN, "a tape's intro belongs to the tape that is on")
        self.assertNotIn("supercut_react", app.RESCUE_ROADS_OPEN, "the answer belongs to its supercut")
        for kind in ("manager", "gallery", "news", "caller", "ad", "station_id"):
            self.assertIn(kind, app.RESCUE_ROADS_OPEN)

    def test_the_dial_defaults_to_a_quarter_hour(self):
        self.assertIn('os.getenv("PINE_UNHEARD_HOURS", "0.25")', SOURCE)
        self.assertLessEqual(app.CUPBOARD_UNHEARD_HOURS, 2.0)

    def test_the_sweep_and_the_rescue_have_the_larder_transport(self):
        self.assertIn("larder_round_air", _calls(_function("unheard_stock_air")))
        self.assertIn("unheard_out_of_turn", _calls(_function("unheard_stock_air")))
        self.assertIn("larder_round_air", _calls(_function("dead_air_rescue")))
        self.assertIn("road_source", _calls(_function("unheard_pick")))
        self.assertIn("mixtape_banked_intro", _calls(_function("dj_mixtape_intro")))
        self.assertIn("mixtape_banked_intro", _calls(_function("mixtape_pick")))


class ThePick(unittest.TestCase):
    def test_unheard_pick_walks_the_larder(self):
        now = time.time()
        entry = {"at": now - 3600, "script": "A: hello\nB: hi", "prep_kind": "banter"}
        with mock.patch.object(app, "_PANTRY_LIFECYCLE", None), \
                mock.patch.object(app, "_LARDER", [entry]), \
                mock.patch.object(app, "_SHELF", {}), \
                mock.patch.object(app, "cupboard_cued", lambda: []), \
                mock.patch.object(app, "unheard_road_out", lambda kind, now=None: False), \
                mock.patch.object(app, "cupboard_unheard_after", lambda: 120.0), \
                mock.patch.object(app, "dialogue_row_ready", lambda kind, row: True), \
                mock.patch.object(app, "_READY_SHELF_BUSY", set()), \
                mock.patch.object(app, "_UNHEARD_REFUSED", {}):
            kind, row, age = app.unheard_pick()
        self.assertEqual(kind, "banter")
        self.assertIs(row, entry)
        self.assertGreater(age, 3000)

    def test_unheard_out_of_turn_reads_the_window_under_the_lifecycle(self):
        on = types.SimpleNamespace(enabled=True)
        with mock.patch.object(app, "_PANTRY_LIFECYCLE", on), \
                mock.patch.object(app, "_ready_slot_window", lambda kind: {"kind": "news", "deadline": time.time() + 60}):
            self.assertTrue(app.unheard_out_of_turn("gallery"))
            self.assertFalse(app.unheard_out_of_turn("news"))
        with mock.patch.object(app, "_PANTRY_LIFECYCLE", None):
            self.assertTrue(app.unheard_out_of_turn("news"), "without the lifecycle the sweep always rescues")


class TheLarderTransport(unittest.TestCase):
    def test_larder_round_air_does_the_live_roads_bookkeeping_then_airs(self):
        now = time.time()
        entry = {"at": now - 900, "script": "A: one\nB: two", "prep_kind": "banter"}
        other = {"at": now - 100, "script": "A: x\nB: y", "prep_kind": "banter"}
        larder = [entry, other]
        aired: list[Any] = []
        handed: list[int] = []

        async def fake_air(e, track, on_handoff=None, **kw):
            aired.append(e)
            if callable(on_handoff):
                on_handoff()
            return ["one", "two"]

        with mock.patch.object(app, "_LARDER", larder), \
                mock.patch.object(app, "dialogue_row_ready", lambda kind, row: True), \
                mock.patch.object(app, "larder_reair_gate", lambda at: (at, None)), \
                mock.patch.object(app, "stock_used_by", lambda: {}), \
                mock.patch.object(app, "stock_expires_at", lambda kind, row: now + 86400), \
                mock.patch.object(app, "repeat_safe", lambda kind, row: True), \
                mock.patch.object(app, "row_innings", lambda kind, row: 3), \
                mock.patch.object(app, "_larder_save", lambda: None), \
                mock.patch.object(app, "gap_round_flag", lambda flag: None), \
                mock.patch.object(app, "pipeline_log", lambda *a, **k: None), \
                mock.patch.object(app, "_banter_air", fake_air):
            said = _run(app.larder_round_air(entry, None, on_handoff=lambda: handed.append(1)))
        self.assertEqual(said, ["one", "two"])
        self.assertIs(aired[0], entry)
        self.assertEqual(entry["aired"], 1)
        self.assertGreater(entry["aired_at"], now - 5)
        self.assertEqual(handed, [1])
        self.assertEqual(larder, [other, entry], "an aired round with innings left rests at the END of the larder")

    def test_larder_round_air_refuses_a_row_that_left(self):
        with mock.patch.object(app, "_LARDER", []), mock.patch.object(app, "pipeline_log", lambda *a, **k: None):
            said = _run(app.larder_round_air({"at": 1}, None))
        self.assertEqual(said, [])

    def test_larder_oldest_ready_is_the_longest_waiting_unaired_round(self):
        now = time.time()
        old = {"at": now - 5000, "script": "A: a"}
        young = {"at": now - 50, "script": "A: b"}
        aired = {"at": now - 9000, "script": "A: c", "aired": 1, "aired_at": now - 100}
        with mock.patch.object(app, "_LARDER", [young, aired, old]), \
                mock.patch.object(app, "_READY_SHELF_BUSY", set()), \
                mock.patch.object(app, "dialogue_row_ready", lambda kind, row: True):
            self.assertIs(app.larder_oldest_ready(), old)


class TheLifecyclePick(unittest.TestCase):
    def _lifecycle(self, host):
        tmp = tempfile.mkdtemp()
        life = pantry_lifecycle.PantryLifecycle(host, Path(tmp) / "life.json")
        life.policy["mode"] = "air"
        return life

    def test_out_of_turn_admits_a_never_aired_row_past_the_dial_on_an_open_road(self):
        now = time.time()
        host = {"RESCUE_ROADS_OPEN": ("gallery", "banter"), "cupboard_unheard_after": lambda: 120.0,
                "dialogue_row_ready": lambda kind, row: True, "_SHELF": {}, "_LARDER": []}
        life = self._lifecycle(host)
        row = {"at": now - 1000, "entry": {"script": "A: x"}}
        self.assertTrue(life.out_of_turn("gallery", row))
        self.assertFalse(life.out_of_turn("mixtape", row), "mixtape is not open out of turn")
        self.assertFalse(life.out_of_turn("gallery", {"at": now - 30, "entry": {}}), "inside the dial it waits")
        self.assertFalse(life.out_of_turn("gallery", {"at": now - 1000, "aired": 1, "aired_at": now - 10}), "aired is not unheard")

    def test_pick_takes_an_out_of_turn_row_when_nothing_is_compatible(self):
        now = time.time()
        row = {"at": now - 1000, "entry": {"script": "A: x"}}
        host = {"RESCUE_ROADS_OPEN": ("gallery",), "cupboard_unheard_after": lambda: 120.0,
                "dialogue_row_ready": lambda kind, r: True, "_SHELF": {"gallery": [row]}, "_LARDER": [],
                "_ready_slot_window": lambda kind: {"kind": "news", "deadline": now + 200},
                "cupboard_row_seconds": lambda kind, r: 30.0, "playout_floor": lambda: 0.0,
                "system3_pick": lambda *a, **k: 0, "pipeline_log": lambda *a, **k: None}
        life = self._lifecycle(host)
        kind, got, age = life.pick()
        self.assertEqual(kind, "gallery")
        self.assertIs(got, row)
        self.assertGreater(age, 900)


class TheSlotWindow(unittest.TestCase):
    def test_a_gazette_review_slot_is_in_turn_for_its_own_shelf(self):
        now = time.time()
        radio = {"on": True, "sched_pos": {"occurrence": "o1", "slot_id": "s1", "started": now - 10},
                 "sched_slot": {"id": "s1", "kind": "gazette_review", "minutes": 4}}
        with mock.patch.object(app, "_system2", lambda: types.SimpleNamespace(enabled=False)), \
                mock.patch.object(app, "_RADIO", radio), \
                mock.patch.object(app, "schedule_read", lambda: {"enabled": True}):
            own = app._ready_slot_window("gazette_review")
            prep = app._ready_slot_window("banter")
        self.assertEqual(own["kind"], "gazette_review")
        self.assertGreater(own["deadline"], now)
        self.assertEqual(prep["kind"], "banter", "the prep road still sees its window")
        self.assertGreater(prep["deadline"], now)


class TheMixtape(unittest.TestCase):
    def test_a_banked_intro_fits_its_tape_or_names_no_tape(self):
        now = time.time()
        mine = {"at": now - 500, "entry": {"script": "A: It is MX tape - October 5 and it goes on NOW"}}
        theirs = {"at": now - 900, "entry": {"script": "A: It is MX tape - June 1, wow"}}
        plain = {"at": now - 700, "entry": {"script": "A: a package from MX, tear it open"}}
        with mock.patch.object(app, "_SHELF", {"mixtape": [theirs, plain, mine]}), \
                mock.patch.object(app, "_READY_SHELF_BUSY", set()), \
                mock.patch.object(app, "dialogue_row_ready", lambda kind, row: True):
            self.assertIs(app.mixtape_banked_intro({"title": "MX tape - October 5"}), mine)
            self.assertIs(app.mixtape_banked_intro({"title": "MX tape - March 9"}), plain, "no intro names it: a plain one")
            with mock.patch.object(app, "_SHELF", {"mixtape": [theirs]}):
                self.assertIsNone(app.mixtape_banked_intro({"title": "MX tape - March 9"}), "another tape's intro never")

    def test_the_intro_takes_the_banked_round_through_the_shelf_door(self):
        row = {"at": 1, "entry": {"script": "A: x"}}
        calls: list[Any] = []

        async def door(kind, track, rescue=False, pick=None, **kw):
            calls.append((kind, rescue, pick))
            return ["a", "b"]

        with mock.patch.object(app, "mixtape_banked_intro", lambda tape: row), \
                mock.patch.object(app, "_ready_shelf_air", door):
            said = _run(app.dj_mixtape_intro({"title": "MX tape - October 5"}))
        self.assertEqual(said, ["a", "b"])
        self.assertEqual(calls, [("mixtape", True, row)])


class TheGazetteReview(unittest.TestCase):
    def test_banked_finds_the_review_of_this_edition(self):
        now = time.time()
        g = {"_SHELF": {"gazette_review": [
                {"at": now - 100, "entry": {"gazette_review": {"edition": "e2"}}},
                {"at": now - 900, "entry": {"gazette_review": {"edition": "e1"}}},
                {"at": now - 950, "entry": {"gazette_review": {"edition": "e1"}}, "aired_at": now - 10},
                {"at": now - 500, "entry": {"gazette_review": {"edition": "e1"}}}]},
             "dialogue_row_ready": lambda kind, row: True, "_READY_SHELF_BUSY": set(),
             "DATA_DIR": tempfile.mkdtemp()}
        runtime = gazette_review_runtime.GazetteReview(g)
        got = runtime.banked({"edition": "e1"})
        self.assertEqual(got["at"], now - 900, "the oldest unaired review of the edition")
        self.assertIsNone(runtime.banked({"edition": "e9"}))

    def test_the_slot_wrapper_calls_the_door_before_writing(self):
        src = Path(gazette_review_runtime.__file__).read_text(encoding="utf-8")
        self.assertIn("runtime.banked(receipt)", src)
        self.assertIn('g.get("_ready_shelf_air")', src)


if __name__ == "__main__":
    unittest.main()
