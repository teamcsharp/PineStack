"""[ads-fresh] No ad ever generates from a used video: the station's own
voice_ad_person_clip and the ledger helpers are exec'd out of app.py with a
stub ranking and clip book, and drawn from until both run dry. Pure."""
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


class _P:
    def __init__(self, sid):
        self.sid = sid
        self.stem = "clip-" + sid


class AdsFresh(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        helpers = re.search(r"\n_H3_FRESH_FILE = .*?(?=\nasync def h3_hourly_render)", text, re.S)
        take = re.search(r"\ndef h3_ad_source_used\(.*?(?=\ndef voice_ad_person_clip)", text, re.S)
        picker = re.search(r"\ndef voice_ad_person_clip\(.*?(?=\n\n\n)", text, re.S)
        self.assertTrue(helpers and take and picker, "the helpers and the picker are in app.py")
        db = sqlite3.connect(":memory:", check_same_thread=False)
        db.execute("CREATE TABLE clips(sid TEXT, name TEXT, seconds REAL, folder TEXT, playable INT, video INT, said TEXT, seen_at REAL)")
        db.executemany("INSERT INTO clips VALUES(?,?,?,?,?,?,?,?)",
                       [("%016x" % (100 + i), "book %d" % i, 6.0, "f", 1, 1, "someone talking", i) for i in range(5)])
        ranked = [(_P("%016x" % i), 5.0, type("C", (), {"folder": "ranked"})()) for i in range(10)]
        self.ns = {"DATA_DIR": self.dir, "RLock": threading.RLock, "json": json, "time": time, "random": random,
                   "Any": object, "pipeline_log": lambda lane, t: None, "sfx_db_reader": lambda: db,
                   "_SFX_DB_LOCK": threading.Lock(), "sfx_match_score": lambda *a, **k: ranked,
                   "sfx_match_rows": lambda r, most=48: list(r), "sfx_is_video": lambda p: True,
                   "sfx_id": lambda p: p.sid, "sfx_db_pick_short_video": lambda s: None,
                   "sfx_db_pick_row": lambda v: None}
        for block in (helpers, take, picker):
            exec(block.group(0), self.ns)  # noqa: S102 - the station's own code, out of its own file

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_an_ad_never_takes_a_used_clip(self):
        got = [self.ns["voice_ad_person_clip"]("a sponsor read")["id"] for _ in range(15)]
        self.assertEqual(len(set(got)), 15, "fifteen ads, fifteen different clips")
        self.assertEqual(sorted(got[:10]), ["%016x" % i for i in range(10)], "the ranking first, while it has fresh clips")
        self.assertTrue(all(g.startswith("00000000000000") for g in got[10:]) and set(got[10:]) == {"%016x" % (100 + i) for i in range(5)},
                        "then fresh clips from the whole book")

    def test_a_hand_picked_source_is_written_down(self):
        self.ns["h3_ad_source_used"]("clip:%016x" % 3)
        self.ns["h3_ad_source_used"]("clip:%016x" % 3)
        ledger = json.loads((self.dir / "h3_hourly_used.json").read_text(encoding="utf-8"))
        self.assertEqual(list(ledger), ["clip:%016x" % 3])
        got = {self.ns["voice_ad_person_clip"]("x")["id"] for _ in range(9)}
        self.assertNotIn("%016x" % 3, got, "the hand-picked clip is never an automatic pick afterwards")

    def test_every_edit_is_in_app_py(self):
        spec = importlib.util.spec_from_file_location("ads_fresh_patch", ROOT / "tools" / "ads_fresh_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)))


if __name__ == "__main__":
    unittest.main()
