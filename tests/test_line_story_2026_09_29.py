"""[msgid] The message code: line_story's resolver and life story on small
fixture stores, the 8-hex minting helper, the /api/why door, and the edit
tools' contract.

    docker exec -w /app -e PYTHONPATH=tests:. spark-agent python3 -m unittest tests.test_line_story_2026_09_29
"""
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

import line_story as ls
import system3_origin as so

HERE = Path(__file__).resolve().parent.parent
T0 = 1790674095.394
SPOKEN = "c69e1e19c3584596964a62047cc91aaa"


def jl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def fixture(d: Path) -> None:
    sfx = lambda i, at, text, key, **kw: dict({"id": i, "ts": int(at), "air_at": at, "who": "board", "kind": "sfx",
                                              "round": "banter", "text": text, "aired": "page", "seconds": 2.69,
                                              "sfx": key, "url": "/sfx/%s?t=x" % key}, **kw)
    older = [sfx("aa%04d" % n, T0 - 4000 + n, "filler %d" % n, "f%015d" % n) for n in range(300)]
    jl(d / "air_log.jsonl", older + [
        sfx("3c4782", T0, "25 dental plan in", "873f0dea47cd7ee8", match_why="matched 'dental'"),
        sfx("e4c9cf", T0 + 0.457, "15 clip-9", "3d5652632c25bbb5"),
        {"id": SPOKEN, "ts": int(T0) + 20, "air_at": T0 + 20, "who": "cohost", "kind": "call", "round": "banter",
         "text": "Dental plan!", "aired": "page", "voice": "vl_1", "engine": "xtts", "seconds": 3.1},
        {"id": SPOKEN, "ts": int(T0) + 20, "air_at": T0 + 20, "who": "cohost", "kind": "call", "round": "banter",
         "text": "Dental plan!", "aired": "stream", "voice": "vl_1", "engine": "xtts", "seconds": 3.1,
         "heard_ack_at": T0 + 24, "heard_ack_by": "page"},
        sfx(SPOKEN + "-punct-1", T0 + 21, "\U0001f50a 26 clip-40", "aaaa000000000001"),
    ])
    jl(d / "sfx_history.jsonl", [
        {"ts": int(T0), "id": "647ca68d39aba513", "name": "160 to know that as.mp4", "who": "gap"},
        {"ts": int(T0), "id": "873f0dea47cd7ee8", "name": "25 dental plan in.mp3", "who": "gap"},
        {"ts": int(T0), "id": "3d5652632c25bbb5", "name": "15 clip-9.mp3", "who": "gap"},
    ])
    jl(d / "script_ledger.jsonl", [
        {"block": 37651, "ord": 0, "at": T0 + 5.6, "line_id": "3c4782", "who": "board", "kind": "sfx",
         "text": "25 dental plan in", "scripted": False, "system_prompts": {"host": "long"},
         "segment": {"id": "hour-x:hour-09", "label": "Ad read", "hour": "2026-09-29T04"},
         "system3": {"conversation_id": "605763d25c724bc1", "turn_id": "605763d25c724bc1:t00",
                     "road": "interject", "sfx_roll": {"road": "match"}}},
        {"block": 37629, "ord": 0, "at": T0 + 1, "line_id": SPOKEN, "who": "cohost", "kind": "call",
         "text": "Dental plan!", "scripted": True},
    ])
    jl(d / "screenplay_lines.jsonl", [
        {"id": SPOKEN, "at": T0 + 1, "who": "cohost", "kind": "call", "round": "banter", "queued_at": T0 + 1,
         "voice": {"engine": "xtts"}, "wrote": {"at": T0 - 10, "model": "gemma4:e2b", "kind": "round", "ms": 2400}},
    ])
    s3 = sqlite3.connect(str(d / "system3.sqlite3"))
    s3.executescript("""
        CREATE TABLE lines(line_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, turn_id TEXT,
                           block INTEGER, ord INTEGER, sid TEXT, who TEXT, text TEXT, at REAL NOT NULL);
        CREATE TABLE conversations(id TEXT PRIMARY KEY, created REAL NOT NULL, updated REAL NOT NULL,
                           road TEXT, mode TEXT, status TEXT, trace_id TEXT, slot_id TEXT, seed TEXT,
                           config_hash TEXT, verdict TEXT, score REAL, summary TEXT NOT NULL);""")
    s3.execute("INSERT INTO lines VALUES (?,?,?,?,?,?,?,?,?)",
               ("3c4782", "605763d25c724bc1", "605763d25c724bc1:t00", 37651, 0, "", "board", "25 dental plan in",
                T0 + 5.6))
    s3.execute("INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
               ("605763d25c724bc1", T0, T0, "interject", "active", "planned", "", "", "1fef", "", None, None,
                json.dumps({"topic": "the board punctuates outside a round", "turns": 5})))
    s3.commit()
    s3.close()
    led = so.OriginLedger(d / "system3_origin.sqlite3")
    rec = {"schema": so.SCHEMA, "line_id": "3c4782", "air_at": T0, "road": "board clip", "verdict": "rolled",
           "why": "System 3 node with 4 roll(s)", "kind": "sfx", "who": "board", "text": "25 dental plan in",
           "producer": "dj_sting", "path": "dj_sting<sfx_fill_gap<cover_the_gap", "tables": [], "system3": {}}
    led.db.execute("INSERT INTO origin(line_id, air_at, day, road, verdict, kind, who, producer, why, settled, "
                   "compact, updated) VALUES (?,?,?,?,?,?,?,?,?,1,?,?)",
                   ("3c4782", T0, "2026-09-29", "board clip", "rolled", "sfx", "board", "dj_sting", rec["why"],
                    so._pack(rec), T0))
    led.db.commit()
    led.close()
    sf = sqlite3.connect(str(d / "station_flow.sqlite3"))
    sf.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
    for i, (node, summ, extra) in enumerate((
            ("publish", "Audio ready for page delivery", {"details": {"clip": {"line": "3c4782"}}}),
            ("ended", "pb9bg3qano: ended", {}))):
        sf.execute("INSERT INTO events VALUES (?,?)", (i + 1, json.dumps(dict(
            {"id": i + 1, "at": T0 + 0.05 + 9 * i, "node": node, "status": node, "summary": summ,
             "trace_id": "0f7cb0852de54cb5", "from": "repeat"}, **extra))))
    sf.commit()
    sf.close()
    jl(d / "sfx_display_receipts.jsonl", [
        {"kind": "beat", "rx": T0 - 30, "player": "pinetab", "at": T0 - 30, "tv_on": True, "wall_on": False,
         "hidden": False, "screen_on": True}])
    (d / "line_votes.json").write_text(json.dumps({SPOKEN: {"vote": "up", "at": T0 + 60}}))


class Codes(unittest.TestCase):
    def test_code_of(self):
        self.assertEqual(ls.code_of("3c4782"), "3c4782")
        self.assertEqual(ls.code_of("1a2b3c4d"), "1a2b3c4d")
        self.assertEqual(ls.code_of(SPOKEN), "c69e1e19")
        self.assertEqual(ls.code_of(SPOKEN + "-punct-2"), "c69e1e19-p2")

    def test_parse_and_match(self):
        self.assertEqual(ls.parse("#3C4782")["prefix"], "3c4782")
        self.assertEqual(ls.parse("c69e1e19-p1"), {"prefix": "c69e1e19", "punct": "1"})
        for bad in ("3c47", "hello", "#zz4782", ""):
            self.assertIsNone(ls.parse(bad), bad)
        w = ls.parse("c69e1e19")
        self.assertTrue(ls.matches(SPOKEN, w))
        self.assertFalse(ls.matches(SPOKEN + "-punct-1", w))       # the welded cue is its own message
        self.assertTrue(ls.matches(SPOKEN + "-punct-1", ls.parse("c69e1e19-p1")))


class Story(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.d = Path(cls.tmp.name)
        fixture(cls.d)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_resolve(self):
        for q in ("3c4782", "#3c4782"):
            r = ls.resolve(self.d, q)
            self.assertEqual([m["id"] for m in r["matches"]], ["3c4782"])
            self.assertIn("air_log", r["matches"][0]["found_in"])
            self.assertIn("origin", r["matches"][0]["found_in"])
        self.assertEqual([m["id"] for m in ls.resolve(self.d, "#c69e1e19")["matches"]], [SPOKEN])
        self.assertEqual([m["id"] for m in ls.resolve(self.d, "c69e1e19-p1")["matches"]], [SPOKEN + "-punct-1"])
        self.assertFalse(ls.resolve(self.d, "#ffffff")["matches"])

    def test_the_dental_plan_story(self):
        s = ls.story(self.d, "#3c4782", now=T0 + 3600)
        self.assertEqual(s["id"], "3c4782")
        st = s["stages"]
        self.assertTrue(st["planned"] and st["rendered"] and st["published"])
        self.assertFalse(st["heard"])
        self.assertEqual(st["page_players"], {"pb9bg3qano": "ended"})
        self.assertEqual(s["sfx_history"]["who"], "gap")
        self.assertEqual(s["origin"]["producer"], "dj_sting")
        self.assertEqual(s["system3"]["conversation"]["road"], "interject")
        self.assertEqual(s["collision"]["same_second"], 2)
        self.assertEqual(s["collision"]["fired_by"], ["gap"])
        self.assertIn("160 to know that as.mp4", s["collision"]["items"])
        self.assertIn("e4c9cf", s["collision"]["items"])
        only = [n for n in s["neighbours"] if n.get("only_in")]
        self.assertEqual([n["text"] for n in only], ["160 to know that as.mp4"])
        self.assertIn("stopped between published and heard", s["verdict"])
        self.assertIn("COLLISION", s["verdict"])
        self.assertIn("NOT planned ahead: 'gap' fired it", s["verdict"])
        self.assertIn("no display receipt", s["verdict"])
        ats = [e["at"] for e in s["events"]]
        self.assertEqual(ats, sorted(ats))
        self.assertTrue(any("AFTER it aired" in e["what"] for e in s["events"]))
        text = ls.format_text(s)
        self.assertIn("VERDICT:", text)
        self.assertIn(">>", text)

    def test_a_heard_spoken_line(self):
        s = ls.story(self.d, "c69e1e19", now=T0 + 3600)
        self.assertEqual(s["id"], SPOKEN)
        self.assertTrue(s["stages"]["heard"])
        self.assertEqual(s["air"]["versions"], 2)
        self.assertEqual(s["written"]["model"], "gemma4:e2b")
        self.assertEqual(s["reactions"][0]["what"], "vote up")
        self.assertIn("completed its life", s["verdict"])

    def test_unknown(self):
        s = ls.story(self.d, "abcdef12")
        self.assertNotIn("id", s)
        self.assertIn("No store knows", s["verdict"])

    def test_read_only(self):
        # sqlite's own -wal/-shm index files may appear beside a WAL database a
        # mode=ro reader opens (the live ones always exist); no store changes
        snap = lambda: {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in self.d.iterdir()
                        if not p.name.endswith(("-wal", "-shm"))}
        before = snap()
        ls.story(self.d, "3c4782")
        ls.resolve(self.d, "c69e1e19")
        self.assertEqual(before, snap())

    def test_the_door(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        ns = {"data_path": lambda name: str(self.d / name), "_RADIO": {"chat": []},
              "require_read_auth": lambda a: None}
        ls.install(app, ns)
        c = TestClient(app)
        got = c.get("/api/why/3c4782?brief=1").json()
        self.assertEqual(got["matches"][0]["id"], "3c4782")
        got = c.get("/api/why/3c4782").json()
        self.assertEqual(got["collision"]["same_second"], 2)
        self.assertIn("VERDICT", c.get("/api/why/3c4782?text=1").text)
        self.assertEqual(c.get("/api/why/nothex").status_code, 400)


def load_tool(name):
    for base in (HERE / "tools", Path(__file__).resolve().parent.parent / "tools"):
        p = base / name
        if p.exists():
            sys.path.insert(0, str(base))
            spec = importlib.util.spec_from_file_location(name[:-3], p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise unittest.SkipTest("%s is not here" % name)


class Mint(unittest.TestCase):
    def test_eight_hex_and_never_a_held_code(self):
        tool = load_tool("edit_msgid_app.py")
        ns = {"uuid": uuid, "_RADIO": {"chat": [{"id": "aaaaaaaa"}]}, "_AIRLOG_INDEX": {"bbbbbbbb": {}}}
        exec(tool.HELPER, ns)
        seq = iter(["aaaaaaaa" + "0" * 24, "bbbbbbbb" + "0" * 24, "cccccccc" + "0" * 24])
        with mock.patch.object(uuid, "uuid4", lambda: mock.Mock(hex=next(seq))):
            self.assertEqual(ns["_mint_line_id"](), "cccccccc")
        code = ns["_mint_line_id"]()
        self.assertRegex(code, r"^[0-9a-f]{8}$")


class Tools(unittest.TestCase):
    """Every edit tool: exit 1 on a file without its anchors, 0 then 2 on one
    with them (idempotent), the marker left behind, CRLF kept CRLF."""

    def test_contract(self):
        for name in ("edit_msgid_app.py", "edit_msgid_lineactions.py", "edit_msgid_scriptpage.py",
                     "edit_msgid_index.py", "edit_msgid_viewassets.py"):
            tool = load_tool(name)
            with tempfile.TemporaryDirectory() as t:
                p = Path(t) / "target"
                p.write_bytes(b"nothing here\n")
                self.assertEqual(tool.run(tool.EDITS, ["--check", str(p)]), 1, name)
                body = "head\n" + "".join("x\n" + e.anchor + "y\n" for e in tool.EDITS) + "tail\n"
                p.write_bytes(body.replace("\n", "\r\n").encode())
                self.assertEqual(tool.run(tool.EDITS, ["--check", str(p)]), 0, name)
                self.assertEqual(tool.run(tool.EDITS, ["--apply", str(p)]), 0, name)
                out = p.read_bytes().decode()
                self.assertIn("[msgid]", out)
                self.assertNotIn("\n", out.replace("\r\n", ""), name + " left a bare LF")
                self.assertEqual(tool.run(tool.EDITS, ["--apply", str(p)]), 2, name)
                self.assertEqual(tool.run(tool.EDITS, ["--check", str(p)]), 2, name)


if __name__ == "__main__":
    unittest.main()
