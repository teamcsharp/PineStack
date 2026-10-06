"""[sfx-voices] Clips with a picture are lifted to the voices' level, with the gain of this moment (2026-10-06).

Run from the repo root:  python3 tests/test_sfx_voices_level_2026_10_06.py
"""
import __future__
import re
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")


def function_source(name: str) -> str:
    start = APP.index("\ndef %s(" % name) + 1
    end = APP.index("\n\n\ndef ", start)
    return APP[start:end] + "\n"


def constant(name: str) -> float:
    m = re.search(r'^%s = float\(os\.getenv\("%s", "(-?[0-9.]+)"\)\)' % (name, name), APP, re.M)
    assert m, name
    return float(m.group(1))


class VoicesLevel(unittest.TestCase):
    def setUp(self):
        self.ns = {"Any": Any, "SFX_TARGET_LUFS": constant("SFX_TARGET_LUFS"), "SFX_TP_DB": constant("SFX_TP_DB"),
                   "SFX_LEVEL_TRANSIENT_LU": 1.5, "SFX_GAIN_MIN_DB": 0.75}
        src = function_source("sfx_gain_now") + "\n\n" + function_source("sfx_gain_db")
        exec(compile(src, "app.py", "exec", flags=__future__.annotations.compiler_flag, dont_inherit=True), self.ns)

    def test_the_target_and_the_ceiling_are_the_voices_own(self):
        self.assertEqual(self.ns["SFX_TARGET_LUFS"], -14.0, "the DJ renders measure -13.5 LUFS")
        self.assertEqual(self.ns["SFX_TP_DB"], -2.0, "the voices' loudnorm ceiling is -1.5 dBTP")

    def test_a_speech_shaped_clip_can_now_reach_the_voices(self):
        gain = self.ns["sfx_gain_db"]({"i": -28.0, "tp": -14.0})
        self.assertEqual(gain, 13.5, "ceiling - tp + 1.5 = 13.5 of the 14 wanted; under -6 dBTP it was 9.5")

    def test_a_peaky_clip_is_still_capped_by_its_peak(self):
        gain = self.ns["sfx_gain_db"]({"i": -28.0, "tp": -3.0})
        self.assertEqual(gain, 2.5, "the limiter on the stream catches the rest (the squeezed road)")

    def test_the_gain_of_this_moment_comes_from_the_measurement(self):
        stale = {"db": 2.0, "i": -24.0, "tp": -12.0}          # measured under the old target: 2 dB would have reached -16 under the old cap
        now = self.ns["sfx_gain_now"](stale)
        self.assertEqual(now["db"], 10.0, "-14 - (-24) = 10, under the cap of -2 + 12 + 1.5")
        self.assertEqual(now["i"], -24.0)
        self.assertEqual(stale["db"], 2.0, "the book entry itself is not rewritten")

    def test_already_at_the_level_entries_get_a_gain_when_the_target_moves(self):
        asis = {"asis": "already at the level", "i": -16.2}
        now = self.ns["sfx_gain_now"](asis)
        self.assertEqual(now["db"], 2.2)

    def test_close_enough_goes_out_as_it_is(self):
        now = self.ns["sfx_gain_now"]({"db": 3.0, "i": -14.4, "tp": -4.0})
        self.assertIsNone(now["db"])

    def test_no_measurement_keeps_its_gain_and_nothing_is_not_a_thing(self):
        self.assertEqual(self.ns["sfx_gain_now"]({"db": 4.0}), {"db": 4.0})
        self.assertIsNone(self.ns["sfx_gain_now"](None))

    def test_the_route_asks_for_the_gain_of_this_moment(self):
        self.assertIn("_gain = sfx_gain_now(await asyncio.to_thread(sfx_gain_known, raw))", APP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
