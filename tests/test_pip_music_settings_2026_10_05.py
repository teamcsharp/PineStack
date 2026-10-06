"""[pip-music] The station keeps where the PiP music player sits (2026-10-05).

The normaliser is lifted out of app.py and run by itself: it drops every field
it does not know, so the player's place has to be one it knows.

Run from the repo root:  python3 tests/test_pip_music_settings_2026_10_05.py
"""
from __future__ import annotations

import math
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")


def lifted() -> dict[str, Any]:
    start = APP.index("PIP_DEFAULTS: dict[str, Any] = {")
    stop = APP.index("\ndef read_pip_settings()", start)
    scope: dict[str, Any] = {"Any": Any, "math": math}
    exec(compile(APP[start:stop], "app.py[pip settings]", "exec"), scope)
    return scope


class PipMusicSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scope = lifted()
        self.normalize = self.scope["normalize_pip_settings"]

    def test_a_fresh_station_has_a_place_for_the_player(self):
        out = self.normalize({})
        self.assertEqual(out["musicPosition"], {"x": .03, "y": .6})
        self.assertIs(out["musicExpanded"], False)

    def test_a_saved_place_and_size_come_back(self):
        out = self.normalize({"musicPosition": {"x": .41, "y": .62}, "musicExpanded": True})
        self.assertEqual(out["musicPosition"], {"x": .41, "y": .62})
        self.assertIs(out["musicExpanded"], True)

    def test_the_place_is_held_inside_the_window_and_nonsense_is_the_default(self):
        self.assertEqual(self.normalize({"musicPosition": {"x": 9, "y": -4}})["musicPosition"], {"x": 1, "y": 0})
        self.assertEqual(self.normalize({"musicPosition": {"x": "left", "y": float("nan")}})["musicPosition"], {"x": .03, "y": .6})
        self.assertEqual(self.normalize({"musicPosition": "top"})["musicPosition"], {"x": .03, "y": .6})
        self.assertEqual(self.normalize({"musicPosition": {"x": .5}})["musicPosition"], {"x": .5, "y": .6})
        for loose in (1, "true", None, [True]):
            self.assertIs(self.normalize({"musicExpanded": loose})["musicExpanded"], False)

    def test_the_defaults_are_never_written_through(self):
        first = self.normalize({"musicPosition": {"x": .9, "y": .9}})
        first["musicPosition"]["x"] = .1
        self.assertEqual(self.scope["PIP_DEFAULTS"]["musicPosition"], {"x": .03, "y": .6})
        self.assertEqual(self.normalize({})["musicPosition"], {"x": .03, "y": .6})

    def test_the_other_fields_are_as_they_were(self):
        out = self.normalize({"roulettePosition": {"x": .2, "y": .3}, "theme": "plum", "widgets": {"music": True}})
        self.assertEqual(out["roulettePosition"], {"x": .2, "y": .3})
        self.assertEqual(out["theme"], "plum")
        self.assertIs(out["widgets"]["music"], True)

    def test_a_partial_save_merges_the_place_with_what_is_kept(self):
        start = APP.index("async def api_put_pip_config(")
        route = APP[start:APP.index("\n@app.get(\"/api/settings\")", start)]
        self.assertIn('"messageTile", "roulettePosition", "musicPosition"):', route)
        self.assertIn("if isinstance(payload.get(key), dict): merged[key] = {**current[key], **payload[key]}", route)


if __name__ == "__main__":
    unittest.main()
