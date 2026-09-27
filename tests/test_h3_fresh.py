"""[h3-fresh] The hourly stinger never takes the same clip or picture twice:
the helpers are exec'd out of app.py's own text with a stub clip book, and
drawn from until the book runs out. Pure: no station."""
import importlib.util
import json
import random
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location("h3_fresh_patch", ROOT / "tools" / "h3_fresh_patch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Fresh(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        m = re.search(r"\n_H3_FRESH_FILE = .*?(?=\nasync def h3_hourly_render)", text, re.S)
        self.assertIsNotNone(m, "the helpers are in app.py")
        db = sqlite3.connect(":memory:", check_same_thread=False)
        db.execute("CREATE TABLE clips(sid TEXT, name TEXT, seconds REAL, folder TEXT, playable INT, video INT, said TEXT)")
        rows = [("%016x" % i, "clip %d" % i, 4.0 + i, "f", 1, 1, "somebody talking") for i in range(12)]
        rows += [("%016x" % 100, "silent", 20.0, "f", 1, 1, ""), ("%016x" % 101, "short", 2.0, "f", 1, 1, "talk talk"),
                 ("%016x" % 102, "audio", 20.0, "f", 1, 0, "talk talk")]
        db.executemany("INSERT INTO clips VALUES(?,?,?,?,?,?,?)", rows)
        self.logs = []
        self.ns = {"DATA_DIR": self.dir, "RLock": threading.RLock, "json": json, "time": time, "random": random,
                   "Any": object, "pipeline_log": lambda lane, text: self.logs.append(text),
                   "sfx_db_reader": lambda: db, "_SFX_DB_LOCK": threading.Lock()}
        exec(m.group(0), self.ns)  # noqa: S102 - the station's own helpers, out of its own file

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_never_the_same_clip_twice_until_the_book_runs_out(self):
        seen = []
        for _ in range(12):
            clip = self.ns["h3_hourly_fresh_clip"]()
            self.assertTrue(clip.get("id") and clip.get("video"))
            seen.append(clip["id"])
        self.assertEqual(len(set(seen)), 12, "twelve draws, twelve different clips")
        self.assertNotIn("%016x" % 100, seen, "a clip with nobody talking is not a reference")
        self.assertNotIn("%016x" % 101, seen, "nor a clip under three seconds")
        self.assertNotIn("%016x" % 102, seen, "nor a sound without a picture")
        again = self.ns["h3_hourly_fresh_clip"]()
        self.assertEqual(again["id"], seen[0], "run out, the one used longest ago goes again")
        self.assertTrue(any("used once" in line for line in self.logs))
        ledger = json.loads((self.dir / "h3_hourly_used.json").read_text(encoding="utf-8"))
        self.assertEqual(len(ledger), 12)

    def test_the_ledger_survives_a_restart(self):
        first = self.ns["h3_hourly_fresh_clip"]()["id"]
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        m = re.search(r"\n_H3_FRESH_FILE = .*?(?=\nasync def h3_hourly_render)", text, re.S)
        ns2 = dict(self.ns)
        exec(m.group(0), ns2)  # noqa: S102 - a fresh process reading the same ledger
        for _ in range(11):
            self.assertNotEqual(ns2["h3_hourly_fresh_clip"]()["id"], first)

    def test_pictures_too_and_a_window_that_fits_the_reference_road(self):
        images = ["a.png", "b.png", "c.jpg"]
        got = [self.ns["h3_hourly_fresh_image"](images) for _ in range(3)]
        self.assertEqual(sorted(got), sorted(images))
        for seconds in (3.0, 9.5, 10.0, 600.0):
            start, end = self.ns["h3_hourly_window"]({"seconds": seconds})
            self.assertTrue(0 <= start < end <= seconds)
            self.assertTrue(2.2 <= end - start <= 15.0, (seconds, start, end))

    def test_every_edit_is_in_app_py(self):
        mod = _tool()
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)))


if __name__ == "__main__":
    unittest.main()
