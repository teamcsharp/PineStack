"""[sfx-even] Every clip with a picture at the DJs' level; a peak-held clip is squeezed, not left a whisper (2026-10-05).

Run from the repo root:  python3 tests/test_sfx_even_2026_10_05.py
"""
import __future__
import json
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")


def section():
    a = APP.index("# --- [nas-gain] A VIDEO'S LEVEL IS A NUMBER")
    b = APP.index('@app.on_event("startup")\nasync def _sfx_gain_start', a)
    return APP[a:b]


class Even(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("CREATE TABLE clips (sid TEXT, path TEXT)")
        self.counts = {}
        self.ns = {"Any": Any, "Path": Path, "json": json, "time": time, "RLock": threading.RLock, "shutil": shutil,
                   "DATA_DIR": self.dir, "SFX_TARGET_LUFS": -16.0, "SFX_TP_DB": -6.0, "SFX_LEVEL_TRANSIENT_LU": 1.5,
                   "SFX_TP_MARGIN_DB": 1.0, "SFX_GAIN_SQUEEZE_LU": 3.0, "_SFX_VIDEO_LEVEL": self.counts,
                   "SFX_LEVELLED": self.dir, "SFX_VIDEO_LEVEL_MARK": "lu1", "_SFX_DB_LOCK": threading.RLock(),
                   "sfx_db_reader": lambda: self.db, "sfx_id": lambda p: "id_" + p.stem,
                   "sfx_loudness": lambda p: {"i": -30.0, "tp": -12.0, "peak": -12.0}, "_sfx_ffmpeg": lambda: "/usr/local/bin/ffmpeg"}
        exec(compile(section(), "app.py", "exec", flags=__future__.annotations.compiler_flag, dont_inherit=True), self.ns)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_the_station_aims_at_the_level_the_djs_are_heard_at(self):
        self.assertIn('SFX_TARGET_LUFS = float(os.getenv("SFX_TARGET_LUFS", "-16"))', APP)
        self.assertIn('SFX_GAIN_SQUEEZE_LU = float(os.getenv("SFX_GAIN_SQUEEZE_LU", "3"))', APP)

    def test_a_clip_the_gain_can_reach_takes_the_plain_gain(self):
        chain, how = self.ns["sfx_gain_chain"](4.0, {"i": -20.0, "tp": -12.0})
        self.assertEqual(how, "gain")
        self.assertEqual(chain, "volume=4.00dB,alimiter=limit=0.4467:level=disabled")
        self.assertEqual(self.ns["sfx_gain_chain"](-4.5)[0], "volume=-4.50dB,alimiter=limit=0.4467:level=disabled", "no measurement, the old road exactly")

    def test_a_peak_held_clip_is_squeezed_to_the_target(self):
        # a whisper with one bang: -30 LUFS, true peak -3 dBTP. The peak rule allows
        # -6 - (-3) + 1.5 = -1.5 -> 0 dB of lift; the target wants +14: held by 14 LU.
        db = self.ns["sfx_gain_db"]({"i": -30.0, "tp": -3.0})
        self.assertEqual(db, 0.0)
        chain, how = self.ns["sfx_gain_chain"](db, {"i": -30.0, "tp": -3.0})
        self.assertEqual(how, "squeezed")
        self.assertEqual(chain, "volume=14.00dB,alimiter=limit=0.4467:attack=5:release=120:level=disabled", "[sfx-sync] the full lift, the limiter holds the bangs; no lookahead")
        # held by less than the squeeze: the plain gain stands
        chain, how = self.ns["sfx_gain_chain"](6.0, {"i": -24.0, "tp": -8.0})
        self.assertEqual(how, "gain")

    def test_the_box_slider_moves_every_clip_the_same_way(self):
        self.ns["box_gain"] = lambda: 1.6                     # +4.08 dB, the knob the DJs and the stings track
        chain, how = self.ns["sfx_gain_chain"](4.0, {"i": -20.0, "tp": -12.0})
        self.assertEqual(how, "gain")
        self.assertTrue(chain.startswith("volume=8.08dB,alimiter=limit=0.7147"), chain)   # the ceiling moved with it
        chain, how = self.ns["sfx_gain_chain"](0.0, {"i": -30.0, "tp": -3.0})
        self.assertEqual((how, chain), ("squeezed", "volume=18.08dB,alimiter=limit=0.7147:attack=5:release=120:level=disabled"))
        self.ns["box_gain"] = lambda: (_ for _ in ()).throw(RuntimeError("no settings"))
        self.assertEqual(self.ns["sfx_gain_chain"](1.0)[0], "volume=1.00dB,alimiter=limit=0.4467:level=disabled", "a broken knob is unity")

    def test_the_command_carries_the_chain_and_still_copies_the_picture(self):
        cmd = self.ns["sfx_gain_command"](Path("/samples/x/clip.mp4"), 0.0, {"i": -30.0, "tp": -3.0})
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "copy")
        self.assertEqual(cmd[cmd.index("-af") + 1], "volume=14.00dB,alimiter=limit=0.4467:attack=5:release=120:level=disabled")
        self.assertEqual(cmd[-1], "pipe:1")
        cmd = self.ns["sfx_gain_command"](Path("/samples/x/clip.mp4"), -4.5)
        self.assertTrue(any(c.startswith("volume=-4.50dB,alimiter=") for c in cmd), "the nas-gain test's contract holds")

    def test_the_stream_names_its_road_and_counts_the_squeezed(self):
        src = APP[APP.index("async def sfx_gain_stream("):]
        src = src[:src.index("\ndef sfx_gain_cleanup")]
        self.assertIn("heard: dict[str, Any] | None = None) -> Response | None:", src)
        self.assertIn("cmd = sfx_gain_command(path, db, heard)", src)
        self.assertIn('out["X-Pine-Gain-How"] = _how', src)
        self.assertIn('_counts["squeezed"] = int(_counts.get("squeezed") or 0) + 1', src)
        route = APP[APP.index('@app.get("/sfx/{sfx_key}")'):]
        route = route[:route.index("\n@app.", 10)]
        self.assertIn('await sfx_gain_stream(raw, float(_gain["db"]), headers, _gain)', route)
        self.assertIn('"squeezed": int(_SFX_VIDEO_LEVEL.get("squeezed") or 0)', APP)


if __name__ == "__main__":
    unittest.main()
