"""[kitchen] 2026-10-06: a stopped station keeps its kitchen open.

"Right now the station is offline. So during this time I want it banking up and
working through rolling rule and building up scripts and stacking the covers."

Measured before the fix: dj_stop left every worker room `stopped`, 481 unheard
rounds on the shelves, 37 gazette reviews and 11 mixtape rounds written but never
recorded, and every banking bypass read radio_paused() - the other switch.
"""
import ast
import asyncio
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import app

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


def settings(**over):
    base = dict(app.DEFAULT_DJ)
    base.update(over)
    return base


class OffAir(unittest.TestCase):
    """off_air() is the pause OR the kitchen; rooms_open() is the show OR the kitchen."""

    def test_off_air_is_paused_or_kitchen(self):
        with mock.patch.dict(app._KITCHEN, {"on": False}), \
                mock.patch.object(app, "radio_paused", lambda: False):
            self.assertFalse(app.off_air())
        with mock.patch.dict(app._KITCHEN, {"on": False}), \
                mock.patch.object(app, "radio_paused", lambda: True):
            self.assertTrue(app.off_air())
        with mock.patch.dict(app._KITCHEN, {"on": True}), \
                mock.patch.object(app, "radio_paused", lambda: False):
            self.assertTrue(app.off_air())

    def test_a_never_started_station_answers_as_before(self):
        # _RADIO has no "on" until the first start: every older test's world.
        with mock.patch.dict(app._KITCHEN, {"on": False}), \
                mock.patch.dict(app._RADIO, {}, clear=False), \
                mock.patch.object(app, "radio_paused", lambda: False):
            app._RADIO.pop("on", None)
            self.assertFalse(app.off_air())
            self.assertFalse(app.rooms_open())

    def test_rooms_open(self):
        with mock.patch.dict(app._KITCHEN, {"on": False}), mock.patch.dict(app._RADIO, {"on": True}):
            self.assertTrue(app.rooms_open())
        with mock.patch.dict(app._KITCHEN, {"on": True}), mock.patch.dict(app._RADIO, {"on": False}):
            self.assertTrue(app.rooms_open())
        with mock.patch.dict(app._KITCHEN, {"on": False}), mock.patch.dict(app._RADIO, {"on": False}):
            self.assertFalse(app.rooms_open())


class BankingBypassesFollowTheKitchen(unittest.TestCase):
    """The paused banking rules hold with the show switched off and the kitchen open."""

    def kitchen(self, **dj):
        return [mock.patch.dict(app._KITCHEN, {"on": True}),
                mock.patch.dict(app._RADIO, {"on": False}),
                mock.patch.object(app, "radio_paused", lambda: False),
                mock.patch.object(app, "dj_settings", lambda: settings(**dj))]

    def closed(self, **dj):
        return [mock.patch.dict(app._KITCHEN, {"on": False}),
                mock.patch.dict(app._RADIO, {"on": False}),
                mock.patch.object(app, "radio_paused", lambda: False),
                mock.patch.object(app, "dj_settings", lambda: settings(**dj))]

    def run_with(self, patches, fn):
        for p in patches:
            p.start()
        try:
            return fn()
        finally:
            for p in patches:
                p.stop()

    def test_build_lift_and_the_work_target(self):
        self.assertEqual(self.run_with(self.kitchen(), app.build_lift), 3.0)
        with mock.patch.object(app, "surplus", lambda: 0.0):
            self.assertEqual(self.run_with(self.closed(), app.build_lift), 1.0)
        base = self.run_with(self.closed(), app.prepare_target_seconds)
        self.assertEqual(self.run_with(self.kitchen(), app.prepare_work_target_seconds), base * 3.0)

    def test_bank_ahead_counts_with_the_kitchen_open(self):
        dj = {"bank_ahead_roads": "caller,manager", "bank_ahead_hours": 72}
        self.assertEqual(self.run_with(self.kitchen(**dj), lambda: app.bank_ahead_hours("caller")), 72.0)
        self.assertEqual(self.run_with(self.closed(**dj), lambda: app.bank_ahead_hours("caller")), 0.0)
        self.assertEqual(self.run_with(self.kitchen(**dj), lambda: app.bank_ahead_hours("news")), 0.0)

    def test_pantry_window_is_open_for_the_kitchen(self):
        self.assertIn("everything is a window", self.run_with(self.kitchen(), app.pantry_window))

    def test_the_plot_act_holds_for_the_kitchen(self):
        self.assertTrue(self.run_with(self.kitchen(), lambda: app.plotline_frozen({})))

    def test_the_recording_booths_bank_in_parallel_for_the_kitchen(self):
        got = self.run_with(self.kitchen(), app.recording_booths)
        self.assertTrue(got["paused"])
        self.assertEqual(got["prep_limit"], got["capacity"])

    def test_unfinished_rows_count_every_round_shelf(self):
        self.assertIn("gazette_review", app.ROUND_SHELF_KINDS)
        self.assertIn("mixtape", app.ROUND_SHELF_KINDS)
        for kind in ("manager", "caller", "gallery", "news"):
            self.assertIn(kind, app.ROUND_SHELF_KINDS)
        shelf = {"gazette_review": [{"entry": {"script": "A: hello", "lines": 4}}],
                 "mixtape": [{"entry": {"script": "B: tape", "lines": 3}}],
                 "ad": [{"entry": {"script": "C: buy", "lines": 1}}]}
        patches = self.kitchen() + [
            mock.patch.dict(app._PAUSE_UNFINISHED_MEMO, {"at": 0.0, "n": 0}),
            mock.patch.object(app, "_SHELF", shelf),
            mock.patch.object(app, "_LARDER", []),
            mock.patch.object(app, "dialogue_row_ready", lambda kind, row: False),
            mock.patch.object(app, "dialogue_row_viable", lambda kind, row: True),
        ]
        self.assertEqual(self.run_with(patches, app._pause_unfinished_rows), 2)
        patches = self.closed() + patches[4:]
        self.assertEqual(self.run_with(patches, app._pause_unfinished_rows), 0)

    def test_the_gazette_prints_while_the_kitchen_banks(self):
        self.assertTrue(self.run_with(self.kitchen(paper_hourly=True), app.paper_hourly_enabled))
        self.assertFalse(self.run_with(self.closed(paper_hourly=True), app.paper_hourly_enabled))
        self.assertFalse(self.run_with(self.kitchen(paper_hourly=False), app.paper_hourly_enabled))


class KitchenRooms(unittest.IsolatedAsyncioTestCase):
    """kitchen_start opens the roster behind a stopped show; radio_stop closes it."""

    async def test_kitchen_rooms_run_with_the_show_off_and_close_with_radio_stop(self):
        ran = []

        async def room_a():
            ran.append("a")
            await asyncio.sleep(3600)

        async def room_b():
            ran.append("b")
            await asyncio.sleep(3600)

        loaders = ("_larder_load", "_dialogue_recovery_load", "_pantry_load", "track_talk_load",
                   "track_talk_restore_queue", "_box_hold_load", "render_backlog_load")
        patches = [mock.patch.object(app, name, lambda: None) for name in loaders]
        patches += [mock.patch.object(app, "kitchen_roster", lambda: [("a", room_a), ("b", room_b)]),
                    mock.patch.object(app, "pipeline_log", lambda *a, **k: None),
                    mock.patch.dict(app._RADIO, {"on": False}),
                    mock.patch.dict(app._KITCHEN, {"on": False}),
                    mock.patch.object(app, "_RADIO_WORKERS", {}),
                    mock.patch.object(app, "_RADIO_TASK", []),
                    mock.patch.object(app, "_SEGMENT_TASK", [])]
        for p in patches:
            p.start()
        try:
            self.assertEqual(app.kitchen_start("test"), 2)
            self.assertTrue(app.kitchen_open())
            self.assertEqual(app.kitchen_start("again"), 0)         # idempotent
            await asyncio.sleep(0.05)
            self.assertEqual(sorted(ran), ["a", "b"])
            state = app.radio_worker_state()
            self.assertTrue(state["kitchen"])
            self.assertEqual(state["kitchen_rooms"], 2)
            self.assertEqual(state["running"], 2)
            self.assertTrue(all(row["kitchen"] for row in state["workers"]))
            app.radio_stop()
            self.assertFalse(app.kitchen_open())
            await asyncio.sleep(0.05)
            self.assertTrue(all(row["state"] == "stopped" for row in app.radio_worker_state()["workers"]))
        finally:
            for p in reversed(patches):
                p.stop()

    async def test_a_show_that_is_on_does_not_open_a_kitchen(self):
        with mock.patch.dict(app._RADIO, {"on": True}), mock.patch.dict(app._KITCHEN, {"on": False}):
            self.assertEqual(app.kitchen_start("test"), 0)
            self.assertFalse(app.kitchen_open())

    async def test_a_plain_show_worker_still_stops_with_the_switch(self):
        ran = []

        async def room():
            ran.append(1)
            await asyncio.sleep(3600)

        with mock.patch.dict(app._RADIO, {"on": False}), mock.patch.dict(app._KITCHEN, {"on": False}), \
                mock.patch.object(app, "_RADIO_WORKERS", {}), mock.patch.object(app, "_RADIO_TASK", []):
            app.radio_worker_start("plain", room)
            await asyncio.sleep(0.05)
            self.assertEqual(ran, [])                 # the factory never ran
            # a worker that never ran keeps its "starting" row (as before the kitchen)
            self.assertNotEqual(app._RADIO_WORKERS["plain"]["state"], "running")


class WiredWhereItMatters(unittest.TestCase):
    """The roads that own the decision call the kitchen, read from app.py itself."""

    def test_dj_stop_opens_the_kitchen_and_waits_to_hand_the_engines_back(self):
        calls = _calls(_function("dj_stop"))
        self.assertIn("kitchen_start", calls)
        self.assertIn("kitchen_has_work", calls)
        self.assertIn("_fm_off_offload", calls)

    def test_a_boot_switched_off_opens_the_kitchen(self):
        self.assertIn("kitchen_start", _calls(_function("resume_radio")))

    def test_radio_stop_closes_the_kitchen(self):
        src = ast.get_source_segment(SOURCE, _function("radio_stop"))
        self.assertIn('_KITCHEN["on"] = False', src)

    def test_the_roster_is_the_preparation_rooms_only(self):
        names = {name for name, _f in app.kitchen_roster()}
        for room in ("pantry", "larder", "flow_release", "tint_recovery", "sfx_speech",
                     "ad_studio", "storage", "speakerbox_index", "kitchen"):
            self.assertIn(room, names)
        for air in ("show", "needle", "torrent_talk", "dead_air", "unheard", "caller",
                    "news", "ad", "upstairs", "gap", "box_delivery", "continuity", "talk_watch"):
            self.assertNotIn(air, names)

    def test_the_keepers_read_the_kitchen_not_the_switch(self):
        for name in ("larder_keeper", "pantry_keeper", "ad_studio_clock", "storage_keeper",
                     "speakbox_index_clock", "sfx_speech_bite", "tint_recovery_step",
                     "switchboard_keeper", "_sfxguy_ready_clock", "topic_cook_once"):
            self.assertIn("rooms_open", _calls(_function(name)), name)
        for name in ("build_lift", "bank_ahead_hours", "prepare_work_target_seconds",
                     "pantry_window", "_pause_unfinished_rows", "prep_plan", "_prep_one_work",
                     "prep_room_left", "recording_booths", "recording_sitting", "retint_shelf",
                     "retint_one", "tint_budget", "tint_should_stop", "call_produce_tick",
                     "plotline_frozen", "workshop_tick", "sfx_speech_clock", "larder_keeper",
                     "pantry_keeper", "response_bank_clock"):
            self.assertIn("off_air", _calls(_function(name)), name)

    def test_the_gazette_has_its_kitchen_desks(self):
        for name in ("_desk_rolled", "_desk_library"):
            _function(name)
        src = ast.get_source_segment(SOURCE, _function("paper_print"))
        self.assertIn('_run("rolled", _desk_rolled)', src)
        self.assertIn('_run("library", _desk_library)', src)


class KitchenDesks(unittest.TestCase):
    """The two code-only desks say what the kitchen did, and stand down when it did nothing."""

    def test_rolled_desk_reports_the_hour(self):
        now = time.time()
        larder = [{"road": "banter", "at": now - 100, "script": "A: We open on the weather.\nB: Do we.",
                   "dice": [{"text": "asks, pointedly, if they are sure"}], "system3": {"conversation_id": "x"},
                   "seconds": 41.0},
                  {"road": "banter", "at": now - 9000, "script": "old"}]
        shelf = {"gazette_review": [{"entry": {"road": "gazette_review", "at": now - 50,
                                               "script": "A: The Gazette says.", "turn_dice": [1]}}]}
        m = {"offline": True, "since": now - 3600, "until": now}
        with mock.patch.object(app, "_LARDER", larder), mock.patch.object(app, "_SHELF", shelf):
            got = app._desk_rolled(m)
        self.assertTrue(got)
        self.assertEqual(got["meta"]["kicker"], "THE KITCHEN")
        self.assertIn("| banter | 1 | 1 | 1 | 41 |", got["body"])
        self.assertIn("| gazette review | 1 | 1 | 0 | 0 |", got["body"])
        self.assertIn("We open on the weather.", got["body"])
        self.assertIn("the dice said: asks, pointedly", got["body"])
        self.assertEqual(got["meta"]["stats"][0]["value"], "2")

    def test_rolled_desk_stands_down_on_air_or_with_nothing_written(self):
        now = time.time()
        with mock.patch.object(app, "_LARDER", []), mock.patch.object(app, "_SHELF", {}):
            self.assertIsNone(app._desk_rolled({"offline": True, "since": now - 3600, "until": now}))
        with mock.patch.object(app, "_LARDER", [{"at": now - 10, "script": "x"}]):
            self.assertIsNone(app._desk_rolled({"since": now - 3600, "until": now}))

    def test_library_desk_reads_the_counters(self):
        with mock.patch.dict(app._SFX_SPEECH, {"done": 40, "heard": 31, "empty": 9, "running": False, "why": ""}), \
                mock.patch.dict(app._SFX_MATCH, {"rows": 364853}):
            got = app._desk_library({"offline": True})
        self.assertTrue(got)
        self.assertIn("listened to 40 clips", got["body"])
        self.assertIn("364853 clips", got["body"])
        self.assertIsNone(app._desk_library({}))


if __name__ == "__main__":
    unittest.main()
