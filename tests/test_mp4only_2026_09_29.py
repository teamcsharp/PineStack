# -*- coding: utf-8 -*-
"""[mp4only] the picture-share switch at 100 is MP4 ONLY on every road, a
sounding MP4 keeps its air on the page cursor, and a clip no player can open
is quarantined. Runs the shipped source of the new functions against stubs,
in the style of test_air_receivers_2026_09_29.py."""
import ast
import io
import json
import os
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = str(os.environ.get("AIR_APP_SRC") or ROOT / "app.py")
S = io.open(SRC, encoding="utf-8").read()
TREE = ast.parse(S)
LINES = S.split("\n")
DISPLAY = io.open(str(ROOT / "sfx_display.py"), encoding="utf-8").read()


def fn(name):
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            start = n.lineno - 1
            if n.decorator_list:
                start = n.decorator_list[0].lineno - 1
            return "\n".join(LINES[start:n.end_lineno])
    raise AssertionError("no function " + name)


def const(name):
    for n in TREE.body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(getattr(t, "id", "") == name for t in targets):
                return "\n".join(LINES[n.lineno - 1:n.end_lineno])
    raise AssertionError("no constant " + name)


VIDEO = {".mp4", ".mov", ".m4v", ".webm"}


def core_ns(share=100, tmp=None):
    tmp = tmp or tempfile.mkdtemp()
    stood, updates = [], []

    class _Con:
        def execute(self, sql, args=()):
            updates.append((sql, args))

            class _C:
                rowcount = 7
            return _C()

        def commit(self):
            pass

    ns = {"Any": object, "Path": Path, "re": re, "json": json, "time": time,
          "RLock": threading.RLock, "_SFX_DB_LOCK": threading.RLock(),
          "sfx_db": lambda: _Con(),
          "sfx_db_stand_down": lambda sids: stood.extend(sids) or len(sids),
          "sfx_video_share": lambda: ns["_share"], "_share": share,
          "sfx_is_video": lambda p: Path(str(p)).suffix.lower() in VIDEO,
          "sfx_id": lambda p: ("%016x" % (abs(hash(str(p))) % (1 << 64)))[:16],
          "sfx_by_id": lambda sid: ns["_paths"].get(sid), "_paths": {},
          "data_path": lambda *parts: Path(tmp, *parts),
          "SFX_ROOT": Path("/"), "SFX_LOCAL_ROOT": Path("/"),
          "pipeline_log": lambda *a, **k: ns["_log"].append(a), "_log": []}
    for c in ("_MP4ONLY", "_SFX_QUARANTINED", "_SFX_GONE_FOLDERS",
              "_SFX_QUARANTINE_LOADED", "_SFX_QUARANTINE_LOCK",
              "_SFX_RECEIPT_STRIKES", "_SFX_UNDECODABLE_RE"):
        exec(const(c), ns)
    for f in ("sfx_mp4_only", "_sfx_quarantine_path", "_sfx_quarantine_load",
              "sfx_quarantined", "sfx_quarantine", "sfx_clip_refusal",
              "mp4only_note", "sfx_quarantine_receipts"):
        exec(fn(f), ns)
    return ns, stood, updates, tmp


class Mp4OnlyFilter(unittest.TestCase):
    def test_switch_refuses_mp3_only_at_100(self):
        ns, *_ = core_ns(100)
        self.assertEqual(ns["sfx_clip_refusal"]("/s/a/clip.mp3"), "mp4-only")
        self.assertEqual(ns["sfx_clip_refusal"]("/s/a/clip.MP4"), "")
        ns["_share"] = 80
        self.assertEqual(ns["sfx_clip_refusal"]("/s/a/clip.mp3"), "")

    def test_quarantine_is_durable_and_refused(self):
        ns, stood, _u, tmp = core_ns(100)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "bad.mp4")
            p.write_bytes(b"x")
            sid = ns["sfx_id"](p)
            self.assertEqual(ns["sfx_clip_refusal"](p, True), "")
            self.assertTrue(ns["sfx_quarantine"](sid, "ffmpeg: invalid data", p, "t"))
            self.assertEqual(stood, [sid])
            self.assertEqual(ns["sfx_clip_refusal"](p), "undecodable")
            again, *_ = core_ns(100, tmp)          # a restart reads the list
            again["sfx_id"] = ns["sfx_id"]
            self.assertEqual(again["sfx_clip_refusal"](p), "undecodable")

    def test_missing_file_and_gone_folder(self):
        ns, stood, updates, _t = core_ns(100)
        gone = "/nowhere/patrice/599 clip-9.mp4"
        self.assertEqual(ns["sfx_clip_refusal"](gone, True), "undecodable")
        self.assertIn("/nowhere/patrice", ns["_SFX_GONE_FOLDERS"])
        self.assertTrue(any("path >= ?" in sql and args[0] == "/nowhere/patrice/"
                            for sql, args in updates))
        # a sibling never reaches a stat again
        self.assertEqual(ns["sfx_clip_refusal"]("/nowhere/patrice/other.mp4"),
                         "undecodable")

    def test_receipts_decode_error_now_not_supported_needs_two(self):
        ns, stood, _u, _t = core_ns(100)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "odd.mp4")
            p.write_bytes(b"x")
            sid = "0123456789abcdef"
            ns["_paths"][sid] = p
            row = {"url": "/sfx/%s?t=x" % sid, "error_code": 4, "error": "not supported"}
            self.assertEqual(ns["sfx_quarantine_receipts"]({"player": "desk", "rows": [row]}), 0)
            self.assertEqual(ns["sfx_quarantine_receipts"]({"player": "pinetab", "rows": [row]}), 1)
            self.assertIn(sid, ns["_SFX_QUARANTINED"])
            sid3 = "fedcba9876543210"
            ns["_paths"][sid3] = p
            self.assertEqual(ns["sfx_quarantine_receipts"](
                {"player": "desk", "rows": [{"sfx": sid3, "error_code": 3}]}), 1)
            # 404 (file gone) quarantines on the first report
            sid4 = "00000000000000aa"
            ns["_paths"][sid4] = Path(d, "gone.mp4")
            self.assertEqual(ns["sfx_quarantine_receipts"](
                {"player": "desk", "rows": [{"sfx": sid4, "error_code": 4}]}), 1)


class GapRoad(unittest.TestCase):
    def ns(self, share, videos):
        ns, *_ = core_ns(share)
        picks = list(videos)
        ns.update({
            "sfx_match_on": lambda strict=False: False, "sfx_match_ready": lambda: False,
            "sfx_match_sting_pick": lambda *a, **k: None,
            "sfx_bans": lambda: set(), "sting_recent": lambda n: False,
            "sfx_video_on_cooldown": lambda k: False, "sfx_short": lambda p: True,
            "sfx_is_silent": lambda p: False, "_sfx_any_video": lambda: None,
            "_sfx_any_audio": lambda: Path("/s/a/boom.mp3")})

        def pick(video=True, tries=6):
            self.assertTrue(video, "the MP4-only road asked the book for audio")
            return picks.pop(0) if picks else None
        ns["sfx_db_pick"] = pick
        exec(fn("_sfx_any"), ns)
        return ns

    def test_mp4_only_draws_a_picture(self):
        ns = self.ns(100, [Path("/s/v/a.mp4")])
        self.assertEqual(ns["_sfx_any"](), Path("/s/v/a.mp4"))

    def test_nothing_is_flagged_never_mp3(self):
        ns = self.ns(100, [])
        self.assertIsNone(ns["_sfx_any"]())
        self.assertEqual(ns["_MP4ONLY"]["left_empty"], 1)
        self.assertEqual(ns["_MP4ONLY"]["by_road"]["gap"]["left_empty"], 1)

    def test_dial_below_100_and_ad_bed_keep_audio(self):
        self.assertEqual(self.ns(80, [])["_sfx_any"](), Path("/s/a/boom.mp3"))
        self.assertEqual(self.ns(100, [])["_sfx_any"](mix=True), Path("/s/a/boom.mp3"))


class MatcherOrigin(unittest.TestCase):
    def test_removed_by_mp4_only_in_origin(self):
        ns, *_ = core_ns(100)
        seen = {}

        class _Cand:
            score = 3.0

        class _M:
            @staticmethod
            def peers(c, f):
                return c

            @staticmethod
            def explain(c):
                return "matched"

        c1, c2 = _Cand(), _Cand()
        by = {id(c1): (Path("/s/a/x.mp3"), 1.0, c1), id(c2): (Path("/s/v/y.mp4"), 1.0, c2)}
        ns.update({
            "sfx_match_on": lambda s=False: True, "sfx_match_ready": lambda: True,
            "sfx_match_heard": lambda at=0: {"line": "a line said", "context": ""},
            "sfx_match_floor": lambda s: 0.0, "sfx_match_score": lambda *a, **k: [c1, c2],
            "_sfx_match": _M, "sfx_match_rows": lambda t: [by[id(c)] for c in t], "sfx_bans": lambda: set(),
            "sfx_weights": lambda: {}, "sting_recent": lambda n: False,
            "sfx_video_on_cooldown": lambda k: False, "sting_keep": lambda n: 24,
            "unrepeated": lambda pool, key, keep=0, director=None: pool[0] if pool else None,
            "_S3ClipDice": lambda *a: None, "_sfx_roll_note": lambda *a, **k: None,
            "_s3_sfx_rolled": lambda *a: None, "_SFX_MATCH_LAST": {}, "_SFX_MATCH": {},
            "_origin_match_note": lambda *a: seen.update(removed=a[-1]),
            "sfx_match_note": lambda *a: None})
        exec(fn("sfx_match_sting_pick"), ns)
        got = ns["sfx_match_sting_pick"]("a line said")
        self.assertEqual(got[0], Path("/s/v/y.mp4"))
        self.assertEqual(seen["removed"]["mp4-only"], 1)
        self.assertEqual(seen["removed"]["the picture share"], 0)


class OneClipAtATime(unittest.TestCase):
    def repair(self, video_row, state="published"):
        now = time.time()
        ns = {"time": time, "Any": object, "VOICE_BROADCAST_LEAD_MS": 1000,
              "page_voice_audible_recent": lambda within=20.0: True,
              "PAGED_ANNOUNCE_EARLY": 45.0, "VOICE_KEEP_OFFER_S": 120.0,
              "_RADIO": {"voice_clips": [video_row]}, "_PAGE_RESERVATION_UPDATES": {},
              "_PAGE_DELIVERIES": {video_row["delivery_id"]: {"state": state}},
              "_PAGE_AIR_UNTIL": [0.0], "playout_tell": lambda *a, **k: None,
              "page_recovery_read": lambda: [], "page_recovery_write": lambda r: None,
              "station_flow_event": lambda *a, **k: None, "_clip_seconds": lambda p: 0.0}
        exec(fn("page_clip_seconds"), ns)
        exec(fn("page_reservation_repair"), ns)
        ns["page_reservation_repair"]()
        return ns["_PAGE_AIR_UNTIL"][0] - now

    def row(self, **extra):
        return {"url": "/sfx/aa", "video": True, "seconds": 12.0, "delivery_id": "v1",
                "broadcast_ms": int((time.time() + 2) * 1000), **extra}

    def test_a_sounding_mp4_holds_the_cursor(self):
        self.assertGreaterEqual(self.repair(self.row()), 13.5)

    def test_silent_picture_ended_and_endless_hold_nothing(self):
        self.assertLess(self.repair(self.row(silent_picture=True)), 2.0)
        self.assertLess(self.repair(self.row(endless=True)), 2.0)
        self.assertLess(self.repair(self.row(), state="ended"), 2.0)


class Case042815(unittest.TestCase):
    """2026-09-29 04:28:15 (fixture, times relative to T=1790674095): the gap
    filler published "160 to know that as.mp4", "25 dental plan in.mp3" and
    "15 clip-9.mp3" in one second. On the tube "553 according to my.mp4"
    (delivery 8000c8b5, stamped 102.19, 7.1 s) was booked; dental was
    stamped 102.45 (now + 7.0 lead) - inside it - because the cursor skipped
    the MP4."""

    def test_the_mp3_waits_behind_the_booked_mp4(self):
        T = time.time()
        ns = {"time": time, "Any": object, "VOICE_BROADCAST_LEAD_MS": 7000,
              "page_voice_audible_recent": lambda within=20.0: True,
              "PAGED_ANNOUNCE_EARLY": 45.0, "VOICE_KEEP_OFFER_S": 120.0,
              "_RADIO": {"voice_clips": [
                  {"url": "/sfx/0d5b269b6245b602", "video": True, "seconds": 7.1,
                   "delivery_id": "8000c8b5ca364825", "line": "5d433a",
                   "broadcast_ms": int((T + 7.19) * 1000)}]},
              "_PAGE_RESERVATION_UPDATES": {},
              "_PAGE_DELIVERIES": {"8000c8b5ca364825": {"state": "published"}},
              "_PAGE_AIR_UNTIL": [0.0], "playout_tell": lambda *a, **k: None,
              "page_recovery_read": lambda: [], "page_recovery_write": lambda r: None,
              "station_flow_event": lambda *a, **k: None, "_clip_seconds": lambda p: 0.0}
        exec(fn("page_clip_seconds"), ns)
        exec(fn("page_reservation_repair"), ns)
        ns["page_reservation_repair"]()
        dental_at = max(T + 7.0, ns["_PAGE_AIR_UNTIL"][0])   # page_feed_append's stamp
        self.assertGreaterEqual(dental_at, T + 7.19 + 7.1 - 0.01)

    def test_the_switch_refuses_both_mp3s(self):
        ns, *_ = core_ns(100)
        for name in ("/samples/samples_grabbed/simp/25 dental plan in.mp3",
                     "/samples/samples_grabbed/deadwood/15 clip-9.mp3"):
            self.assertEqual(ns["sfx_clip_refusal"](name), "mp4-only")
        self.assertEqual(ns["sfx_clip_refusal"](
            "/samples/samples_grabbed/x/160 to know that as.mp4"), "")

    def test_published_until_a_player_says_heard(self):
        chat = [{"id": "3c4782", "aired": "published", "text": "25 dental plan in"}]
        ns = {"_RADIO": {"chat": chat}, "HEARD_STAMP": "heard_ack_at",
              "HEARD_STAMP_BY": "heard_ack_by"}
        exec(fn("_sting_heard"), ns)
        self.assertNotIn("heard_ack_at", chat[0])
        self.assertTrue(ns["_sting_heard"]("3c4782", "0f7cb0852de54cb5", 1790674102.45))
        self.assertEqual(chat[0]["aired"], "page")
        self.assertEqual(chat[0]["heard_ack_at"], 1790674102.45)
        ns["_sting_heard"]("3c4782", "0f7cb0852de54cb5", 1790674200.0)
        self.assertEqual(chat[0]["heard_ack_at"], 1790674102.45)   # first hearing wins
        pub = fn("dj_sting")
        self.assertIn('"page" if _sting_row.get("aired") == "page" else "published"', pub)
        self.assertNotIn('_sting_row["aired"] = "box" if to_box else "page"\n', pub)
        ack = fn("page_playback_ack")
        self.assertIn("_sting_heard(str(clip.get(\"line\")), delivery_id, now - position)", ack)


class ScratchFilesStayOut(unittest.TestCase):
    def test_a_file_outside_the_library_is_never_quarantined(self):
        ns, stood, _u, tmp = core_ns(100)
        ns["SFX_ROOT"], ns["SFX_LOCAL_ROOT"] = Path("/samples"), Path("/app/data/samples")
        self.assertFalse(ns["sfx_quarantine"]("aa" * 8, "ffmpeg: invalid data", "/tmp/x/Gee.mp3", "t"))
        self.assertFalse(Path(tmp, "sfx_quarantine.jsonl").exists())
        self.assertEqual(stood, [])


class Wiring(unittest.TestCase):
    def test_every_road_asks(self):
        sting = fn("dj_sting")
        gate = sting.index("[mp4only-gate]")
        self.assertLess(sting.index("sample = await asyncio.to_thread(_sfx_any)"), gate)
        self.assertLess(gate, sting.index('if sample is None:\n        return ""'))
        self.assertIn("[mp4only-due]", fn("sting_due"))
        self.assertIn("video_order = ((True,) if sfx_mp4_only()", fn("_sfx_cadence_additions_inner"))
        self.assertIn("[mp4only-flow]", fn("schedule_flow_sfx_pick"))
        self.assertIn("[mp4only-gone]", fn("sfx_file"))
        self.assertIn("[mp4only-decode]", S)
        self.assertEqual(S.count("_sfx_any, True)   # [mp4only-admix]"), 2)
        self.assertIn('namespace.get("sfx_quarantine_receipts")', DISPLAY)
        self.assertIn('@app.get("/api/sfx/mp4-only")', S)


if __name__ == "__main__":
    unittest.main()
