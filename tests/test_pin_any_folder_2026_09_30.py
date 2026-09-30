"""[pin-any-folder] a folder the clip book holds can be pinned, whatever root
it lives under (sfx_ads under COMFY_OUTPUT was listed and refused)."""
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "app.py").read_text(encoding="utf-8")


class ThePin(unittest.TestCase):
    def test_the_gate_asks_the_book(self):
        self.assertIn("root_ok = await asyncio.to_thread(sfx_pin_folder_known, path)", SRC)

    def test_the_query_is_a_prefix_not_a_like(self):
        # '_' in "sfx_ads" is a LIKE wildcard; substr compares it literally
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE clips (path TEXT, playable INT)")
        con.executemany("INSERT INTO clips VALUES (?, 1)", [("/comfy-output/sfx_ads/a.mp4",),
                                                          ("/comfy-output/sfxXads2/b.mp4",)])
        q = "SELECT 1 FROM clips WHERE playable = 1 AND substr(path, 1, ?) = ? LIMIT 1"
        self.assertIn(q, SRC)
        for folder, want in (("/comfy-output/sfx_ads", True), ("/comfy-output/sfxXads", False),
                             ("/comfy-output/sfx_a", False)):
            prefix = folder.rstrip("/") + "/"
            got = con.execute(q, (len(prefix), prefix)).fetchone() is not None
            self.assertEqual(got, want, folder)


class TheTakeover(unittest.TestCase):
    def test_the_video_door_names_the_pin(self):
        # [pin-takeover] the tablet's larder filled in from every folder
        self.assertIn('"pin": sfx_pin_public(),', SRC)
        self.assertIn("def sfx_pin_public() -> dict[str, Any] | None:", SRC)

    def test_one_tap_brings_listen_back(self):
        # [tap-out] a bare Listen picture ignored single taps: stuck full screen
        js = (ROOT / "desktop" / "renderer" / "listen.js").read_text(encoding="utf-8")
        self.assertIn("if (bare) { toggleBare(); tapAt = 0; stir(); return true; }", js)


if __name__ == "__main__":
    unittest.main()
