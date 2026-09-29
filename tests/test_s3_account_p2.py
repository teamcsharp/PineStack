"""[s3-account-p2] Phase 2 accountability fixes, each proven against the old code.

- system3_origin: a line republished by boot recovery keeps its origin (System
  3's line register, then the ledger's own record from before the restart);
  nothing known stays rogue; an observation with a COUNT of lines is no crash.
- app.py [s3-account-wall]: the endless set's rotation pick notes its dice on
  the clip (read back, never re-derived) - tested on the functions' own source,
  extracted with ast; app is NOT imported.
- line_story [s3-account-keys]: why_line resolves rec:/wall:/live: origin keys.
Temp files only; nothing reads or writes the station's data dir.
"""
import ast
import json
import sqlite3
import tempfile
import time
import unittest
import zlib
from pathlib import Path

import line_story
import system3_origin as so

ROOT = Path(so.__file__).resolve().parent
NOW = time.time()


def pack(v):
    return zlib.compress(json.dumps(v).encode("utf-8"))


def fake_system3(path, lines=True):
    db = sqlite3.connect(str(path))
    db.executescript("""CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
        seq INTEGER, kind TEXT NOT NULL, family TEXT, turn_id TEXT, at REAL NOT NULL, body BLOB NOT NULL);""")
    body = {"event_id": "c1:0001", "family": "ES", "turn_id": "c1:t00",
            "stages": [{"stage": "item", "selected": "delight", "selected_index": 2, "of": 5}],
            "rng": {"u": 0.44, "dice": 44}, "selected": {"id": "delight", "label": "delight"}}
    db.execute("INSERT INTO events(conversation_id,seq,kind,family,turn_id,at,body) VALUES(?,?,?,?,?,?,?)",
               ("c1", 1, "decision", "ES", "c1:t00", NOW, pack(body)))
    # an observation whose "lines" is a COUNT (it crashed the replay)
    db.execute("INSERT INTO events(conversation_id,seq,kind,family,turn_id,at,body) VALUES(?,?,?,?,?,?,?)",
               ("c1", 2, "observation", "LINE", "c1:t00", NOW, pack({"family": "LINE", "lines": 3})))
    if lines:
        db.execute("""CREATE TABLE lines(line_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, turn_id TEXT,
            block INTEGER, ord INTEGER, sid TEXT, who TEXT, text TEXT, at REAL NOT NULL)""")
        db.execute("INSERT INTO lines VALUES(?,?,?,?,?,?,?,?,?)",
                   ("reg1", "c1", "c1:t00", 1, 0, "", "dj", "a line", NOW))
    db.commit()
    db.close()


def row(lid, **kw):
    out = {"id": lid, "ts": int(NOW), "air_at": NOW - 200, "who": "dj", "kind": "interject",
           "round": "interject", "text": "a line", "aired": "published",
           "origin_path": "page_recovery_chat_rows<page_recovery_start<_radio_worker<run<run"}
    out.update(kw)
    return out


class Origin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.s3 = self.dir / "system3.sqlite3"
        fake_system3(self.s3)
        self.db = self.dir / "origin.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def ledger(self, s3=None):
        return so.OriginLedger(self.db, self.dir / "reports", s3 or self.s3)

    def test_observation_with_a_count_of_lines_is_no_crash(self):
        conv = {"exists": True, "any": 1, "turn": [], "round": [],
                "observations": [{"family": "LINE", "lines": 3, "turn_id": "c1:t00"}]}
        rec = so.build(row("x1"), None, {"conversation_id": "c1", "turn_id": "c1:t00"}, conv)
        self.assertEqual(rec["compact"]["verdict"], "rolled")

    def test_a_republished_line_reads_system3s_line_register(self):
        led = self.ledger()
        led.tick([row("reg1", recovery=True)], now=NOW)
        got = led.get("reg1")
        self.assertEqual(got["verdict"], "rolled", got["why"])
        self.assertEqual(got["system3"]["conversation_id"], "c1")
        self.assertIn("republished", got)
        self.assertEqual(led.untraced(NOW - 3600)["count"], 0)
        led.close()

    def test_a_restart_never_downgrades_a_traced_record(self):
        before = self.ledger()
        before.tick([row("pg1", aired="published", system3={"conversation_id": "c1", "turn_id": "c1:t00"})], now=NOW)
        self.assertEqual(before.get("pg1")["verdict"], "rolled")
        before.close()
        after = so.OriginLedger(self.db, self.dir / "reports", self.dir / "none.sqlite3")   # the process after the restart
        after.tick([row("pg1", recovery=True)], now=NOW)
        got = after.get("pg1")
        self.assertEqual(got["verdict"], "rolled", got["why"])
        self.assertEqual(got["system3"].get("via"), "its origin record from before the restart")
        after.close()

    def test_a_forced_record_keeps_its_named_reason(self):
        before = self.ledger()
        before.tick([row("em1", kind="emergency_host", origin_path="continuity_air<x")], now=NOW)
        self.assertEqual(before.get("em1")["verdict"], "forced")
        before.close()
        after = so.OriginLedger(self.db, self.dir / "reports", self.dir / "none.sqlite3")
        after.tick([row("em1", kind="interject", recovery=True)], now=NOW)
        got = after.get("em1")
        self.assertEqual(got["verdict"], "forced", got["why"])
        self.assertEqual(got["forced"]["how"], "its origin record from before the restart")
        after.close()

    def test_a_replay_of_a_heard_line_reads_the_line_it_replays(self):
        led = self.ledger()
        led.tick([row("new9", recovery=True, recovered_from="reg1")], now=NOW)
        got = led.get("new9")
        self.assertEqual(got["verdict"], "rolled", got["why"])
        self.assertIn("the line it replays, reg1", got["system3"]["via"])
        self.assertEqual(got["recovered_from"], "reg1")
        led.close()

    def test_nothing_known_stays_rogue_and_alarms(self):
        led = self.ledger()
        led.tick([row("zz9", recovery=True)], now=NOW)
        led.tick([row("zz9", recovery=True)], now=NOW + 200)          # the settle window gone
        got = led.get("zz9")
        self.assertEqual(got["verdict"], "rogue")
        self.assertEqual(got["producer"], "page_recovery_chat_rows")
        self.assertIn("page_recovery_start", got["rogue"]["path"])
        self.assertEqual(led.untraced(NOW - 3600)["count"], 1)
        led.close()

    def test_an_older_store_without_a_line_register_is_no_error(self):
        old = self.dir / "old.sqlite3"
        fake_system3(old, lines=False)
        led = self.ledger(old)
        led.tick([row("reg1", recovery=True)], now=NOW)
        self.assertEqual(led.metrics["errors"], 0, led.metrics["last_error"])
        self.assertEqual(led.get("reg1")["verdict"], "rogue")
        led.close()


_APP = {}


def app_functions(*names):
    """The named top-level functions of app.py, by their own source (parsed once)."""
    if not _APP:
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        for n in ast.parse(src).body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _APP[n.name] = ast.get_source_segment(src, n)
    got = {k: _APP[k] for k in names if k in _APP}
    missing = set(names) - set(got)
    if missing:
        raise AssertionError("app.py has no %s" % sorted(missing))
    return got


class FakeCon:
    def __init__(self, count, path):
        self.count, self.path, self.offset = count, path, None

    def execute(self, sql, args):
        if sql.startswith("SELECT COUNT"):
            return self
        self.offset = args[-1]
        self._row = {"path": self.path, "seconds": 7.0}
        return self

    def fetchone(self):
        if self.offset is None:
            return {"n": self.count}
        return self._row


class Wall(unittest.TestCase):
    def ns(self, u, recorded_u):
        import threading
        from pathlib import Path as P
        noted = []
        con = FakeCon(40, "/sfx/tv/show/clip-9.mp4")
        ns = {"Path": P, "Any": object, "time": time, "_SFX_VIDEO_ROTATION_LOCK": threading.Lock(),
              "_SFX_VIDEO_ROTATION": {}, "sfx_db_reader": lambda: con, "sfx_video_rotation_cycle": lambda: 3,
              "dj_settings": lambda: {}, "sfx_pin_prefix": lambda: "", "sfx_video_recent_folders": lambda: [],
              "s3_roll": lambda key, label="": u,
              "system3_last_roll": lambda key: ({"key": key, "u": recorded_u, "dice": 36} if recorded_u is not None else None),
              "_sfx_roll_note": lambda *a: noted.append(a)}
        for name, code in app_functions("_sfx_wall_roll_note", "sfx_db_pick_rotation_row").items():
            exec(compile(code, "app.py:" + name, "exec"), ns)          # noqa: S102
        return ns, noted, con

    def test_the_sets_pick_carries_its_dice(self):
        ns, noted, con = self.ns(0.355, 0.355)
        got = ns["sfx_db_pick_rotation_row"](True)
        self.assertEqual(str(got[0]), "/sfx/tv/show/clip-9.mp4")
        self.assertEqual(con.offset, 14)
        self.assertEqual(len(noted), 1)
        path, road, cat, clip, tries = noted[0]
        self.assertEqual((road, cat["label"], clip["index"], clip["of"], clip["dice"]), ("wall", "show", 15, 40, 36))

    def test_the_stations_own_random_notes_nothing(self):
        ns, noted, _con = self.ns(0.5, None)                 # System 3 off: no record
        self.assertIsNotNone(ns["sfx_db_pick_rotation_row"](True))
        self.assertEqual(noted, [])
        ns, noted, _con = self.ns(0.5, 0.25)                 # a stale record from another draw
        ns["sfx_db_pick_rotation_row"](True)
        self.assertEqual(noted, [])


class Recovery(unittest.TestCase):
    def ns(self, chat):
        applied = []
        ns = {"Any": object, "time": time, "_RADIO": {"chat": chat},
              "line_heard_at": lambda r: float(r.get("heard_ack_at") or 0),
              "page_delivery_apply": lambda r, d: applied.append(d)}
        for name, code in app_functions("_page_delivery_rows", "page_recovery_chat_rows").items():
            exec(compile(code, "app.py:" + name, "exec"), ns)          # noqa: S102
        return ns

    def test_the_republished_row_keeps_the_deliverys_stamp(self):
        chat = []
        ns = self.ns(chat)
        stamp = {"conversation_id": "bb939c0c2ee54d6f", "turn_id": "bb939c0c2ee54d6f:t00", "road": "upstairs"}
        clip = {"row_id": "pg1", "who": "manager", "kind": "manager", "text": "a page", "url": "/upstairs-audio/f0.mp3",
                "broadcast_ms": NOW * 1000, "seconds": 50.0, "system3": stamp}
        ns["page_recovery_chat_rows"](clip, "d1")
        self.assertEqual(chat[-1]["id"], "pg1")
        self.assertEqual(chat[-1]["system3"], stamp)
        self.assertTrue(chat[-1]["recovery"])

    def test_a_replay_names_the_line_it_replays(self):
        chat = []
        ns = self.ns(chat)
        clip = {"row_id": "new9", "recovered_from_row_id": "old9", "who": "dj", "kind": "interject",
                "text": "a line", "url": "/media/x.wav", "broadcast_ms": NOW * 1000, "seconds": 3.0}
        ns["page_recovery_chat_rows"](clip, "d2")
        self.assertEqual(chat[-1]["recovered_from"], "old9")
        self.assertNotIn("system3", chat[-1])

    def test_the_upstairs_page_clip_carries_the_pages_stamp(self):
        src = app_functions("_dj_upstairs_page_floorless")["_dj_upstairs_page_floorless"]
        clip = src[src.index("page_clip = {"):]
        clip = clip[:clip.index("\n        }\n")]
        self.assertIn('"system3": dict(made["system3"])', clip)


class WhyKeys(unittest.TestCase):
    def test_origin_keys_parse_exactly(self):
        self.assertEqual(line_story.parse("rec:2f820e539fcb6441:1790673001"),
                         {"prefix": "rec:2f820e539fcb6441:1790673001", "punct": "", "exact": True})
        self.assertIsNotNone(line_story.parse("wall:ab12cd:1790673001"))
        self.assertIsNone(line_story.parse("rec:"))
        self.assertIsNone(line_story.parse("hello"))
        self.assertEqual(line_story.parse("#3c4782")["prefix"], "3c4782")          # hex codes unchanged
        want = line_story.parse("rec:t1:100")
        self.assertTrue(line_story.matches("rec:t1:100", want))
        self.assertFalse(line_story.matches("rec:t1:1000", want))

    def test_a_record_spin_has_a_story(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            (data / "air_log.jsonl").write_text("", encoding="utf-8")
            (data / "script_ledger.jsonl").write_text("", encoding="utf-8")
            led = so.OriginLedger(data / "system3_origin.sqlite3")
            led.tick([{"id": "rec:t1:100", "kind": "record", "who": "record", "text": "A Song",
                       "air_at": NOW - 300, "aired": "stream", "s3_spin": {"lane": "rotation", "roll": {"dice": 12}}}],
                     now=NOW)
            led.close()
            res = line_story.resolve(data, "rec:t1:100")
            self.assertEqual([m["id"] for m in res["matches"]], ["rec:t1:100"])
            s = line_story.story(data, "rec:t1:100")
            self.assertEqual(s.get("id"), "rec:t1:100")


if __name__ == "__main__":
    unittest.main()
