"""[pip-free] [pip-art] [pip-find] The station keeps every PiP widget's layout, and a request can name its record (2026-10-05).

The normaliser is lifted out of app.py and run by itself; the request route's shape is read.

Run from the repo root:  python3 tests/test_pip_layout_settings_2026_10_05.py
"""
from __future__ import annotations

import math
import re
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


class PipLayoutSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scope = lifted()
        self.normalize = self.scope["normalize_pip_settings"]

    def test_a_fresh_station_has_no_layout_and_a_whole_player(self):
        out = self.normalize({})
        self.assertEqual(out["layout"], {})
        self.assertIs(out["musicArtOnly"], False)

    def test_an_entry_is_kept_within_bounds_and_only_for_a_widget(self):
        out = self.normalize({"layout": {
            "dialogue": {"x": 1.4, "y": -.2, "w": .5, "h": .25, "s": 9, "o": 0, "t": [0, 10, 0, 60]},
            "chat": {"x": .1, "y": .2, "t": [0, 0, 0, 0]},
            "cast": {"s": 1.25},
            "camera": {"o": .5},
            "nobody": {"x": .5, "y": .5},
            "music": "not an object",
            "voices": {"s": "big"},
        }, "musicArtOnly": True})
        self.assertEqual(out["layout"]["dialogue"], {"x": 1.0, "y": 0.0, "w": .5, "h": .25, "s": 3.0, "o": .1, "t": [0.0, 10.0, 0.0, 45.0]})
        self.assertEqual(out["layout"]["chat"], {"x": .1, "y": .2}, "four zero trims are no trims")
        self.assertEqual(out["layout"]["cast"], {"s": 1.25})
        self.assertEqual(out["layout"]["camera"], {"o": .5}, "the camera carries an entry too")
        self.assertNotIn("nobody", out["layout"])
        self.assertNotIn("music", out["layout"])
        self.assertNotIn("voices", out["layout"], "an entry with nothing usable is no entry")
        self.assertIs(out["musicArtOnly"], True)

    def test_the_desk_and_the_station_keep_the_same_entry(self):
        """What pip-window.cjs keeps is what the station keeps: the desk's normaliser rounds to four
        places and trims to one, as this one does."""
        out = self.normalize({"layout": {"task": {"x": .123456, "y": .5, "s": 1.23456, "t": [1.26, 0, 0, 0]}}})
        self.assertEqual(out["layout"]["task"], {"x": .1235, "y": .5, "s": 1.2346, "t": [1.3, 0.0, 0.0, 0.0]})

    def test_a_posted_layout_replaces_and_null_clears(self):
        route = APP[APP.index('@app.post("/api/pip/config")'):APP.index("\n@app.", APP.index('@app.post("/api/pip/config")') + 10)]
        self.assertIn('merged["layout"] = payload["layout"] if isinstance(payload["layout"], dict) else {}', route)
        self.assertIn('if "layout" in payload:', route)

    def test_a_request_may_name_its_record(self):
        route = APP[APP.index('@app.post("/api/dj/request")'):APP.index("\n@app.", APP.index('@app.post("/api/dj/request")') + 10)]
        self.assertIn('track_id=str(payload.get("id") or "").strip()', route)
        fn = APP[APP.index("async def dj_request(query: str, now: bool = False, track_id: str = \"\")"):]
        fn = fn[:fn.index("\nasync def ", 10)]
        self.assertIn("chosen = music_track(track_id) if track_id else None", fn)
        self.assertIn("hits = [chosen] if chosen else music_search(query, limit=1)", fn)
        self.assertTrue(re.search(r"def music_track\(track_id: str\)", APP), "music_track exists")


if __name__ == "__main__":
    unittest.main()
