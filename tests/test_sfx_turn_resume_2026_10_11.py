"""Run the real air transitions without booting a second station."""
import ast
import asyncio
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


SOURCE = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8"))
FUNCTIONS = {n.name: n for n in SOURCE.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def actual(names, namespace):
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    nodes = [copy.deepcopy(FUNCTIONS[n]) for n in names]
    for node in nodes:
        node.decorator_list = []
    tree = ast.fix_missing_locations(ast.Module(body=[future] + nodes, type_ignores=[]))
    exec(compile(tree, "actual-station-transitions", "exec"), namespace)
    return namespace


class AirTransitions(unittest.TestCase):
    def station(self, *, owned=False, paused=True):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = {"dj": {"sfx_video_mode": True, "sfx_video_banking_owned": owned}}
        radio = {"paused": paused, "paused_at": 99 if paused else 0,
                 "voice_clips": [{"endless": True, "broadcast_ms": 105000},
                                 {"silent_picture": True, "broadcast_ms": 110000}]}
        ns = {"time": SimpleNamespace(time=lambda: 100), "json": json,
              "_RADIO": radio, "_SFX_CYCLE": {}, "_PAGE_AIR_UNTIL": [120],
              "load_settings": lambda: copy.deepcopy(settings),
              "save_settings": lambda value: settings.update(copy.deepcopy(value)),
              "dj_settings": lambda: settings["dj"],
              "radio_paused": lambda: radio["paused"],
              "airlog_pause_note": Mock(), "gap_mark": Mock(), "dj_skip": Mock(),
              "_LAST_PLAYOUT": {}, "_LAST_SAID": [1], "_TALK_ACK_BASE": [0],
              "_TALK_ACK": {}, "GAP_RESUME_RUNWAY_SECONDS": 600,
              "fire_and_forget": Mock(), "reel_open": Mock(return_value=object()),
              "PAUSE_PATH": Path(directory.name) / "pause.json",
              "radio_paused_for": lambda: 0, "prepared_seconds": lambda: 30,
              "pipeline_log": Mock()}
        actual(["radio_pause_set", "sfx_video_mode_on", "sfx_video_banking_owned",
                "sfx_video_banking_set", "_sfx_video_withdraw"], ns)
        return ns, settings, radio

    def test_explicit_resume_ends_background_video_regardless_of_pause_ownership(self):
        for owned, paused in [(False, True), (True, True), (False, False)]:
            with self.subTest(owned=owned, paused=paused):
                ns, settings, radio = self.station(owned=owned, paused=paused)
                ns["radio_pause_set"](False, "operator returned to air")
                self.assertFalse(radio["paused"])
                self.assertFalse(settings["dj"]["sfx_video_mode"])
                self.assertFalse(settings["dj"]["sfx_video_banking_owned"])
                self.assertEqual(radio["voice_clips"],
                                 [{"silent_picture": True, "broadcast_ms": 110000}])
                ns["dj_skip"].assert_called_once()
                ns["reel_open"].assert_called_once()
                ns["airlog_pause_note"].assert_called_once()

    def test_ending_endless_still_respects_a_separate_operator_pause(self):
        ns, settings, radio = self.station(owned=False)
        ns["sfx_video_banking_set"](False)
        self.assertTrue(radio["paused"])
        self.assertFalse(settings["dj"]["sfx_video_mode"])
        ns["dj_skip"].assert_not_called()

    def test_ending_an_owned_pause_resumes_once(self):
        ns, settings, radio = self.station(owned=True)
        ns["sfx_video_banking_set"](False)
        self.assertFalse(radio["paused"])
        ns["dj_skip"].assert_called_once()
        ns["reel_open"].assert_called_once()


class InFlightVideo(unittest.IsolatedAsyncioTestCase):
    async def test_resume_while_clip_is_loading_cannot_publish_background_audio(self):
        mode = [True]
        async def pick(*args):
            return Path("clip.mp4"), 5, "matched", 1
        async def level(path, *args):
            mode[0] = False  # operator resumes while the worker is awaited
            return path, "levelled"
        async def sleep(delay):
            raise asyncio.CancelledError
        publish = Mock()
        ns = {"asyncio": SimpleNamespace(sleep=sleep, CancelledError=asyncio.CancelledError),
              "time": SimpleNamespace(time=lambda: 100),
              "sfx_video_mode_on": lambda: mode[0], "sfx_video_hourly_rebuild": lambda now: False,
              "_SFX_CYCLE": {}, "_SFX_INTERMISSION": {}, "sfx_reachable": lambda: True,
              "sfx_match_video_pick_async": pick, "sfx_cycle_slot": lambda seconds: seconds,
              "sfx_level_for_air": level, "SFX_LEVEL_WAIT": 2,
              "page_picture_append": publish}
        actual(["sfx_video_cycle"], ns)
        with self.assertRaises(asyncio.CancelledError):
            await ns["sfx_video_cycle"]()
        publish.assert_not_called()
        self.assertEqual(ns["_SFX_CYCLE"]["queued"], 0)

    async def test_intermission_also_cancels_a_clip_loading_during_resume(self):
        mode = [True]
        async def worker(fn, *args):
            return fn(*args)
        async def level(path, *args):
            mode[0] = False
            return path, "levelled"
        ns = {"asyncio": SimpleNamespace(to_thread=worker, CancelledError=asyncio.CancelledError),
              "time": SimpleNamespace(time=lambda: 100), "Path": Path,
              "sfx_video_mode_on": lambda: mode[0], "sfx_intermission_shelf": lambda: [1],
              "sfx_intermission_pick": lambda shelf: {"path": "clip.mp4"},
              "sfx_seconds": lambda path: 5, "sfx_cycle_slot": lambda seconds: seconds,
              "sfx_level_for_air": level, "SFX_LEVEL_WAIT": 2, "page_picture_append": Mock()}
        actual(["sfx_intermission_turn"], ns)
        self.assertIsNone(await ns["sfx_intermission_turn"](100, 100))
        ns["page_picture_append"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
