"""[nas-gain] a video's level is a number kept on the Spark; the video stays on the NAS."""
import __future__
import json
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text(encoding="utf-8")


def section():
    a = APP.index("# --- [nas-gain] A VIDEO'S LEVEL IS A NUMBER")
    b = APP.index('@app.on_event("startup")\nasync def _sfx_gain_start', a)
    return APP[a:b]


class Gain(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "share").mkdir()
        (self.dir / "lv").mkdir()
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("CREATE TABLE clips (sid TEXT, path TEXT)")
        self.ns = {"Any": Any, "Path": Path, "json": json, "time": time, "RLock": threading.RLock, "shutil": shutil,
                   "DATA_DIR": self.dir, "SFX_TARGET_LUFS": -20.0, "SFX_TP_DB": -6.0, "SFX_LEVEL_TRANSIENT_LU": 3.0,
                   "SFX_LEVELLED": self.dir / "lv", "SFX_VIDEO_LEVEL_MARK": "lu1", "_SFX_DB_LOCK": threading.RLock(),
                   "sfx_db_reader": lambda: self.db, "sfx_id": lambda p: "id_" + p.stem,
                   "sfx_loudness": lambda p: {"i": -30.0, "tp": -12.0, "peak": -12.0},
                   "_sfx_ffmpeg": lambda: "ffmpeg"}   # [sfx-even] the stream command names the box's ffmpeg ([talk-steady]); it lives outside this section
        exec(compile(section(), "app.py", "exec", flags=__future__.annotations.compiler_flag, dont_inherit=True), self.ns)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_measured_in_place_only_a_number_kept(self):
        clip = self.dir / "share" / "a.mp4"
        clip.write_bytes(b"x")
        self.assertIsNone(self.ns["sfx_gain_known"](clip))
        got = self.ns["sfx_gain_measure"](clip)
        self.assertEqual(got["db"], 9.0, "lift bounded by the peak: -12 + 9 = -3, the ceiling plus the limiter's 3")
        self.assertEqual(self.ns["sfx_gain_known"](clip)["db"], 9.0)
        self.assertEqual(sorted(p.name for p in (self.dir / "share").iterdir()), ["a.mp4"], "nothing written beside it")
        self.assertEqual(list((self.dir / "lv").iterdir()), [], "no copy on the Spark")
        self.assertEqual(self.ns["sfx_gain_db"]({"i": -10.0, "tp": -1.0}), -10.0)

    def test_old_copies_go_only_when_the_original_is_on_the_share(self):
        here = self.dir / "share" / "b.mp4"
        here.write_bytes(b"x")
        self.db.execute("INSERT INTO clips VALUES ('id_b', ?)", (str(here),))
        self.db.execute("INSERT INTO clips VALUES ('id_c', ?)", (str(self.dir / "share" / "gone.mp4"),))
        (self.dir / "lv" / "id_b-lu1-123.mp4").write_bytes(b"y" * 2048)
        (self.dir / "lv" / "id_b-lu1-123.mp4.lu").write_text("{}")
        (self.dir / "lv" / "id_c-lu1-9.mp4").write_bytes(b"z")
        (self.dir / "lv" / "id_d-v4-v1-5.wav").write_bytes(b"w")
        got = self.ns["sfx_gain_cleanup"]()
        self.assertEqual((got["deleted"], got["kept"]), (1, 1))
        self.assertEqual(sorted(p.name for p in (self.dir / "lv").iterdir()), ["id_c-lu1-9.mp4", "id_d-v4-v1-5.wav"])
        self.assertTrue(here.exists(), "the original is never touched")

    def test_stream_command_copies_the_picture(self):
        cmd = self.ns["sfx_gain_command"](Path("/samples/x/clip.mp4"), -4.5)
        self.assertIn("/samples/x/clip.mp4", cmd)
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "copy")
        self.assertTrue(any(c.startswith("volume=-4.50dB,alimiter=") for c in cmd))
        self.assertEqual(cmd[-1], "pipe:1")
        self.assertIsNone(self.ns["sfx_gain_command"](Path("clip.avi"), 2.0))

    def test_wired(self):
        self.assertIn("_streamed = await sfx_gain_stream(raw, float(_gain[\"db\"]), headers, _gain)", APP)   # [sfx-even] the measurement rides along
        self.assertIn("return path if sfx_gain_known(path) is not None else None", APP)


if __name__ == "__main__":
    unittest.main()
