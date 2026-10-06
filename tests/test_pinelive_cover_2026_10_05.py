"""[plcover] [pip-rec] The live set's cover can be chosen, and the recorder widget is a shared PiP setting (2026-10-05).

Run from the repo root:  python3 tests/test_pinelive_cover_2026_10_05.py
"""
from __future__ import annotations

import math
import re
import time
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PL = (ROOT / "pinelive.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
APP = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")


def lifted(art_dir: Path) -> dict[str, Any]:
    """The cover section of pinelive.py by itself: the memo, the override, _plart_cover."""
    start = PL.index("_PLART_MEMO: dict[str, tuple[str, bytes]] = {}")
    stop = PL.index("\nasync def art_response(", start)
    scope: dict[str, Any] = {"Any": Any, "Path": Path, "time": time, "PLART_DIR": art_dir}
    exec(compile(PL[start:stop], "pinelive.py[cover]", "exec"), scope)
    return scope


class Cover(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "a.jpg").write_bytes(b"AAAA")
        (self.dir / "b.png").write_bytes(b"BBBB")
        self.ns = lifted(self.dir)

    def test_without_a_choice_the_covers_roll(self):
        got = self.ns["_plart_cover"]("set-1")
        self.assertIn(got[1], (b"AAAA", b"BBBB"))
        self.assertEqual(self.ns["plart_override_view"](), {"name": "", "set": False, "event": ""})

    def test_a_choice_for_the_running_set_is_the_cover_and_a_new_set_rolls_again(self):
        self.ns["plart_override_set"]("image/jpeg", b"COVER", "clip.mp4", "set-1")
        self.assertEqual(self.ns["_plart_cover"]("set-1"), ("image/jpeg", b"COVER"))
        self.assertEqual(self.ns["plart_override_view"](), {"name": "clip.mp4", "set": True, "event": "set-1"})
        rolled = self.ns["_plart_cover"]("set-2")
        self.assertIn(rolled[1], (b"AAAA", b"BBBB"), "another set is not the chosen set")

    def test_a_choice_made_between_sets_is_taken_by_the_next_set(self):
        self.ns["plart_override_set"]("image/png", b"NEXT", "render.png", "")
        self.assertEqual(self.ns["_plart_cover"]("set-9"), ("image/png", b"NEXT"))
        self.assertEqual(self.ns["plart_override_view"]()["event"], "set-9", "and now belongs to it")
        self.assertEqual(self.ns["_plart_cover"]("set-9"), ("image/png", b"NEXT"), "and stays its cover")

    def test_clearing_returns_to_the_rolled_pictures(self):
        self.ns["plart_override_set"]("image/jpeg", b"COVER", "clip.mp4", "set-1")
        self.ns["plart_override_set"]("", b"", "", "")
        self.assertFalse(self.ns["plart_override_view"]()["set"])
        self.assertIn(self.ns["_plart_cover"]("set-1")[1], (b"AAAA", b"BBBB"))

    def test_the_route_and_the_state_are_wired(self):
        route = PL[PL.index('@app.post("/api/pinelive/cover")'):PL.index('@app.get("/api/pinelive/state")')]
        for piece in ('body.get("clear")', 'str(body.get("clip_id") or "")', 'str(body.get("generation") or "")',
                      '_app("_render_poster")', '_app("comfy_output_find")', '_app("sfx_by_id")', 'plart_override_set(kind, data, name, event)',
                      'event = PL.event_id() if PL.event is not None else ""'):
            self.assertIn(piece, route, piece)
        self.assertIn('"cover_override": plart_override_view(),', PL)
        self.assertIn('"voices": False, "roulette": False, "rec": False},', APP, "the recorder widget is a shared PiP setting")


if __name__ == "__main__":
    unittest.main()
