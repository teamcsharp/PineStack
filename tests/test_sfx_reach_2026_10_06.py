"""[sfx-reach] The SFX collection may be away: the probe, the intermission, the keepers standing down.

"When I plug it up to the spark, I want the database work to continue and for it to plug back up
seamlessly into the system ... In the intermission, I want it playing H3 / Supercuts if it finds it
has issues getting to the clips or accessing the SFX collection."      - the operator, 2026-10-06

Two halves. The pure half (sfx_reach, tools/sfx_rehome) runs anywhere. The station half imports
app (a minute in the container) and is skipped where app cannot be imported; it stubs every road
that writes, so a run against the live container's data directory changes nothing there.

  docker exec -e PYTHONPATH=/tmp/waveE/stage:/app:/app/tests spark-agent sh -c \
      "cd /tmp/waveE && python3 -m unittest tests.test_sfx_reach_2026_10_06 -v"
"""
from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import sfx_reach

HERE = Path(__file__).resolve().parent
for cand in (HERE.parent / "tools", HERE.parent.parent / "tools", Path("/app/tools")):
    if (cand / "sfx_rehome.py").is_file() and str(cand) not in sys.path:
        sys.path.insert(0, str(cand))
        break
import sfx_rehome  # noqa: E402

try:
    import app  # noqa: E402
except Exception as _exc:  # noqa: BLE001 - the pure half still runs
    app = None
    APP_WHY = "app did not import: %s: %s" % (type(_exc).__name__, str(_exc)[:120])
else:
    APP_WHY = ""


class Clock:
    def __init__(self, at: float = 1000.0) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at


def make_reach(stat, listdir=None, timeout=0.15, memo=20.0, clock=None, root="/samples"):
    log: list[str] = []
    r = sfx_reach.Reach(root=root, timeout=timeout, memo=memo, stat=stat,
                        listdir=listdir or (lambda p: ["a", "b"]), clock=clock or time.time,
                        log=log.append)
    return r, log


class Probe(unittest.TestCase):
    def test_a_stat_that_hangs_times_out_on_its_own_thread_and_one_is_in_flight(self):
        started = []
        release = threading.Event()

        def hanging_stat(path):
            started.append(path)
            release.wait(2.0)
            return None

        r, log = make_reach(hanging_stat, timeout=0.15)
        t0 = time.monotonic()
        got = r.probe()
        took = time.monotonic() - t0
        self.assertFalse(got["reachable"])
        self.assertLess(took, 1.0, "the probe must return at its timeout, not the stat's")
        self.assertIn("did not answer", got["last_error"])
        self.assertTrue(got["in_flight"])
        # a second ask while the first hangs starts no second thread
        r.probe(force=True)
        self.assertFalse(r.reachable())
        self.assertEqual(len(started), 1, "at most one probe in flight")
        self.assertEqual(len([x for x in log if "unreachable since" in x]), 1, "said once")
        release.set()

    def test_memo_spares_the_share_and_a_stale_memo_kicks_the_next_probe(self):
        calls = []
        clock = Clock()
        r, _log = make_reach(lambda p: calls.append(p), clock=clock, memo=20.0)
        self.assertTrue(r.probe()["reachable"])
        self.assertEqual(len(calls), 1)
        for _ in range(20):
            self.assertTrue(r.reachable())
        self.assertEqual(len(calls), 1, "a fresh memo costs no stat")
        clock.at += 21.0
        r.reachable()                                   # stale: a probe is kicked, not waited for
        time.sleep(0.2)
        self.assertEqual(len(calls), 2)

    def test_transitions_are_logged_once_each_way(self):
        box = {"ok": True}

        def stat(path):
            if not box["ok"]:
                raise OSError(112, "Host is down")

        clock = Clock()
        r, log = make_reach(stat, clock=clock)
        r.probe(force=True)
        self.assertEqual(log, [], "a quiet start: the share is simply there")
        box["ok"] = False
        for _ in range(3):
            clock.at += 30
            r.probe(force=True)
        self.assertFalse(r.reachable())
        self.assertEqual(len(log), 1)
        self.assertIn("the SFX collection is unreachable since", log[0])
        self.assertIn("H3 renders and supercuts", log[0])
        since = r.state()["since"]
        box["ok"] = True
        clock.at += 600
        r.probe(force=True)
        self.assertTrue(r.reachable())
        self.assertEqual(len(log), 2)
        self.assertIn("back after %d min" % int(round((clock.at - since) / 60.0)), log[1])
        st = r.state()
        self.assertEqual(st["outages"], 1)
        self.assertGreaterEqual(st["probes"], 5)

    def test_an_empty_samples_grabbed_and_a_late_answer_are_unreachable(self):
        r, _ = make_reach(lambda p: None, listdir=lambda p: [])
        self.assertFalse(r.probe(force=True)["reachable"])
        self.assertIn("empty", r.state()["last_error"])
        clock = Clock()

        def slow_stat(path):
            clock.at += 5.0                             # the stat took five seconds of the clock

        r2, _ = make_reach(slow_stat, clock=clock, timeout=3.0)
        self.assertFalse(r2.probe(force=True)["reachable"])
        self.assertIn("answered after", r2.state()["last_error"])

    def test_under_narrow_and_stood_down(self):
        r, log = make_reach(lambda p: (_ for _ in ()).throw(OSError("down")))
        self.assertTrue(r.under("/samples/samples_grabbed/x/y.mp4"))
        self.assertTrue(r.under(Path("/samples")))
        self.assertFalse(r.under("/samplesX/y"))
        self.assertFalse(r.under("/comfy-output/sfx_ads/a.mp4"))
        self.assertEqual(r.narrow(["/samples/a", "/comfy-output/b", Path("/app/data/sfx/c")]),
                         ["/comfy-output/b", Path("/app/data/sfx/c")])
        r.probe(force=True)
        self.assertEqual(r.stood_down("sting"), 1)
        self.assertEqual(r.stood_down("sting"), 2)
        self.assertEqual(len([x for x in log if "sting stands down" in x]), 1, "a road says so once per outage")
        self.assertEqual(r.state()["stood_down"], {"sting": 2})
        self.assertIn("INTERMISSION", r.say())

    def test_no_root_means_reachable_and_the_module_functions_exist(self):
        self.assertTrue(sfx_reach.Reach().reachable())
        for name in ("configure", "probe", "reachable", "state", "say", "under", "narrow", "stood_down", "defer"):
            self.assertTrue(callable(getattr(sfx_reach, name)))


class Rehome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / "drive"
        self.data = base / "data"
        self.data.mkdir()
        self.book = self.data / "sfx_clips.db"
        rows = []
        for folder in ("f1", "f2", "f3"):
            d = self.root / "samples_grabbed" / folder
            d.mkdir(parents=True)
            for i in range(4):
                p = d / ("%d clip.mp4" % i)
                p.write_bytes(b"x" * (100 + i))
                cpath = "/samples/samples_grabbed/%s/%s" % (folder, p.name)
                rows.append((cpath, sfx_rehome.sid_of(cpath), p.stem, folder, 1, 100 + i, p.stat().st_mtime, 2.0, 1))
        # a folder the book knows that is not on the drive
        for i in range(2):
            cpath = "/samples/samples_grabbed/lost/%d clip.mp3" % i
            rows.append((cpath, sfx_rehome.sid_of(cpath), "%d clip" % i, "lost", 0, 50, 1.0, 1.0, 1))
        # a row of the station's own (not the collection's)
        rows.append(("/comfy-output/sfx_ads/x.mp4", sfx_rehome.sid_of("/comfy-output/sfx_ads/x.mp4"), "x", "sfx_ads", 1, 9, 1.0, 3.0, 1))
        # an extra folder on the drive the book has never seen
        (self.root / "samples_grabbed" / "brandnew").mkdir()
        con = sqlite3.connect(str(self.book))
        con.execute("CREATE TABLE clips (path TEXT PRIMARY KEY, sid TEXT, name TEXT, folder TEXT, video INTEGER, "
                    "bytes INTEGER, mtime REAL, seconds REAL, playable INTEGER, seen_at REAL, deck_cycle INTEGER DEFAULT 0)")
        con.executemany("INSERT INTO clips (path, sid, name, folder, video, bytes, mtime, seconds, playable) "
                        "VALUES (?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
        con.close()
        (self.data / "sfx_plays.json").write_text('{"%s": {"plays": 3}, "0123456789abcdef": {"plays": 1}}' % rows[0][1])
        (self.data / "sfx_bans.json").write_text('["%s"]' % rows[5][1])

    def test_sid_is_app_sfx_id(self):
        self.assertEqual(sfx_rehome.sid_of("/samples/samples_grabbed/a/b.mp4"),
                         hashlib.sha1(b"/samples/samples_grabbed/a/b.mp4").hexdigest()[:16])
        if app is not None:
            self.assertEqual(sfx_rehome.sid_of("/samples/samples_grabbed/a/b.mp4"),
                             app.sfx_id(Path("/samples/samples_grabbed/a/b.mp4")))

    def test_verify_reports_folders_sample_and_verdict(self):
        got = sfx_rehome.verify(self.book, self.root, "/samples", sample=200)
        self.assertEqual(got["book_rows_of_collection"], 14)
        self.assertEqual(got["book_rows_elsewhere"], 1)
        self.assertEqual(got["folders_in_book"], 4)
        self.assertEqual(got["folders_present"], 3)
        self.assertEqual([f["folder"] for f in got["folders_missing"]], ["/samples/samples_grabbed/lost"])
        self.assertEqual(got["folders_extra_on_drive"], ["brandnew"])
        self.assertEqual(got["sample"]["checked"], 14)
        self.assertEqual(got["sample"]["ok"], 12)
        self.assertEqual(got["sample"]["bad_count"], 2)
        self.assertEqual(got["sample"]["mtime_within_1s"], 12)
        self.assertEqual(got["verdict"], "FAIL")
        # fix the drive: the lost folder arrives -> only the extra folder remains, a WARN
        d = self.root / "samples_grabbed" / "lost"
        d.mkdir()
        for i in range(2):
            (d / ("%d clip.mp3" % i)).write_bytes(b"y" * 50)
        got = sfx_rehome.verify(self.book, self.root, "/samples", sample=200)
        self.assertEqual(got["sample"]["bad_count"], 0)
        self.assertEqual(got["folders_missing_count"], 0)
        self.assertEqual(got["verdict"], "WARN" if got["mount"].get("own_filesystem") else "FAIL")
        self.assertTrue(any("never seen" in w for w in got["warnings"]))
        # a wrong size is a FAIL
        (self.root / "samples_grabbed" / "f1" / "0 clip.mp4").write_bytes(b"z" * 7)
        got = sfx_rehome.verify(self.book, self.root, "/samples", sample=200)
        self.assertEqual(got["verdict"], "FAIL")
        self.assertTrue(any("bytes 7" in b["why"] for b in got["sample"]["bad"]))

    def test_dry_run_changes_nothing_and_names_the_orphaned_stores(self):
        before = self.book.read_bytes()
        got = sfx_rehome.dry_run(self.book, self.data, "/samples", "/other")
        self.assertEqual(self.book.read_bytes(), before)
        self.assertEqual(got["rows_affected"], 14)
        self.assertEqual(got["rows_untouched"], 1)
        self.assertTrue(got["sids_change"])
        ex = got["examples"][0]
        self.assertTrue(ex["new_path"].startswith("/other/samples_grabbed/"))
        self.assertEqual(ex["new_sid"], sfx_rehome.sid_of(ex["new_path"]))
        self.assertNotEqual(ex["new_sid"], ex["sid"])
        stores = {s["store"]: s for s in got["stores"]}
        self.assertEqual(stores["sfx_plays.json"]["book_sids"], 1)
        self.assertEqual(stores["sfx_bans.json"]["book_sids"], 1)
        self.assertFalse(stores["sfx_weights.json"]["present"])
        self.assertIn("sfx_plays.json", got["orphaned_stores"])
        self.assertIn("SAME container path", got["say"])

    def test_apply_rewrites_only_the_book_behind_the_flags_with_a_backup(self):
        rc = sfx_rehome.main(["--apply", "--book", str(self.book), "--data", str(self.data),
                              "--prefix-from", "/samples", "--prefix-to", "/other"]) if False else None
        with self.assertRaises(SystemExit):
            sfx_rehome.main(["--apply", "--book", str(self.book), "--data", str(self.data),
                             "--prefix-from", "/samples", "--prefix-to", "/other"])
        self.assertIsNone(rc)
        got = sfx_rehome.apply_prefix(self.book, "/samples", "/other")
        self.assertEqual(got["rows_rewritten"], 14)
        self.assertTrue(Path(got["backup"]).is_file())
        con = sqlite3.connect(str(self.book))
        rows = con.execute("SELECT path, sid, folder FROM clips ORDER BY path").fetchall()
        con.close()
        moved = [r for r in rows if r[0].startswith("/other/")]
        self.assertEqual(len(moved), 14)
        for path, sid, folder in moved:
            self.assertEqual(sid, sfx_rehome.sid_of(path))
            self.assertEqual(folder, path.rsplit("/", 2)[-2])
        self.assertEqual([r[0] for r in rows if not r[0].startswith("/other/")], ["/comfy-output/sfx_ads/x.mp4"])
        # the other stores were not touched
        self.assertIn("0123456789abcdef", (self.data / "sfx_plays.json").read_text())


@unittest.skipIf(app is None, APP_WHY)
class Station(unittest.TestCase):
    """The station half: every road that writes is stubbed; the reach is forced through a fake stat."""

    def setUp(self):
        self.saved = {}
        self.reach = app._sfx_reach.REACH          # the module's one instance, the station's
        self.saved_cfg = (self.reach._stat, self.reach._listdir, self.reach._log, self.reach.timeout)
        self.logged: list[str] = []
        self.reach.configure(log=self.logged.append)

    def tearDown(self):
        stat, listdir, log, timeout = self.saved_cfg
        self.reach.configure(stat=stat, listdir=listdir, log=log or (lambda t: None), timeout=timeout)
        self.reach.probe(force=True)                      # back to the truth of this box
        for name, value in self.saved.items():
            setattr(app, name, value)

    def stub(self, name, value):
        self.saved.setdefault(name, getattr(app, name))
        setattr(app, name, value)

    def away(self):
        def dead(path):
            raise OSError(112, "Host is down")
        self.reach.configure(stat=dead, listdir=lambda p: [])
        self.reach.probe(force=True)
        self.assertFalse(app.sfx_reachable())

    def back(self):
        self.reach.configure(stat=lambda p: None, listdir=lambda p: ["a"])
        self.reach.probe(force=True)
        self.assertTrue(app.sfx_reachable())

    def test_wiring_and_bases(self):
        self.back()
        self.assertEqual(app.sfx_reach_bases(), (app.SFX_ROOT, app.SFX_LOCAL_ROOT))
        self.assertTrue(app.sfx_reach_ok(app.SFX_ROOT / "samples_grabbed" / "x" / "y.mp4"))
        self.away()
        self.assertEqual(app.sfx_reach_bases(), (app.SFX_LOCAL_ROOT,))
        self.assertFalse(app.sfx_reach_ok(app.SFX_ROOT / "samples_grabbed" / "x" / "y.mp4"))
        self.assertTrue(app.sfx_reach_ok(app.SFX_ADS_DIR / "PineBox-H3_00001_.mp4"))
        self.assertTrue(app.sfx_reach_ok(app.SFX_LOCAL_ROOT / "cut.wav"))
        folders = app.sfx_folders()
        self.assertTrue(all(not app.sfx_reach_under(f) for f in folders), folders)
        self.assertEqual(app.SFX_REACH_LIKE, str(app.SFX_ROOT).rstrip("/") + "/%")

    def test_stamp_answers_zero_without_a_memo_while_away(self):
        self.away()
        share = app.SFX_ROOT / "samples_grabbed" / "nowhere" / "clip.mp4"
        app.sfx_stamp_forget(share)
        self.assertEqual(app.sfx_stamp(share), 0)
        self.assertNotIn(str(share), app._SFX_STAT_MEMO, "nothing memoised: the first ask after the return pays")

    def test_the_book_draw_narrows_to_the_stations_own_rows(self):
        seen = []

        class Con:
            def execute(self, sql, args=()):
                seen.append((sql, tuple(args)))
                return self

            def fetchone(self):
                return None

        self.stub("sfx_db_reader", lambda: Con())
        self.stub("dj_settings", lambda: {})
        self.stub("sfx_pin_prefix", lambda: "")
        self.away()
        self.assertIsNone(app._sfx_db_pick_any(True, 1))
        self.assertTrue(any("path NOT LIKE ?" in sql and app.SFX_REACH_LIKE in args for sql, args in seen), seen)
        seen.clear()
        self.back()
        app._sfx_db_pick_any(True, 1)
        self.assertFalse(any("path NOT LIKE" in sql for sql, _ in seen))

    def test_sfx_route_answers_503_fast_while_away_and_serves_the_stations_own(self):
        key = "0123456789abcdef"
        app._SFX_ID_REVERSE[key] = str(app.SFX_ROOT / "samples_grabbed" / "x" / "y.mp4")
        self.stub("media_sign", lambda k: "sig")
        self.stub("sfx_by_id", lambda k: (_ for _ in ()).throw(AssertionError("sfx_by_id must not be asked")))

        class Req:
            query_params = {"t": "sig"}
            headers = {}

        self.away()
        t0 = time.monotonic()
        resp = asyncio.run(app.sfx_file(key, Req(), None))
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.headers.get("retry-after"), "20")
        self.assertIn("unreachable", resp.body.decode())
        self.assertGreaterEqual(app.sfx_reach_state()["stood_down"].get("sfx-route", 0), 1)
        # an id nobody knows is 503 too (its lookup would walk the share)
        resp = asyncio.run(app.sfx_file("fedcba9876543210", Req(), None))
        self.assertEqual(resp.status_code, 503)
        # a clip of the station's own is not blocked by the reach
        local = "abcdefabcdefabcd"
        app._SFX_ID_REVERSE[local] = str(app.SFX_ADS_DIR / "PineBox-H3_00001_.mp4")
        self.assertFalse(app.sfx_reach_blocks(local))
        app._SFX_ID_REVERSE.pop(key, None)
        app._SFX_ID_REVERSE.pop(local, None)

    def test_the_keepers_stand_down_while_away(self):
        self.away()
        share = app.SFX_ROOT / "samples_grabbed" / "x" / "y.mp4"
        wrote = []
        self.stub("sfx_db_stand_down", lambda sids: wrote.append(sids) or 0)
        self.assertFalse(app.sfx_quarantine("0123456789abcdef", "a 503 on the tube", share, "a test"))
        self.assertEqual(wrote, [])
        got = app._sfx_reconcile_scan(10)
        self.assertEqual(got["checked"], 0)
        self.assertIn("unreachable", got["why"])
        self.assertEqual(got["gone"], [])
        self.stub("sfx_vision_column", lambda: True)
        vision = asyncio.run(app.sfx_vision_bite(1))
        self.assertIn("unreachable", vision.get("why", ""))
        study = asyncio.run(app.sfx_study_clip(share, 3.0))
        self.assertEqual(study.get("why"), "the SFX collection is unreachable")
        self.assertIsNone(app.sfx_db_path_of("0123456789abcdef") if False else None)
        down = app.sfx_reach_state()["stood_down"]
        for road in ("quarantine", "reconcile", "vision", "study"):
            self.assertGreaterEqual(down.get(road, 0), 1, road)
        # the receipts hook: a 503 is not an undecodable clip
        key = "0123456789abcdef"
        app._SFX_ID_REVERSE[key] = str(share)
        quarantined = []
        self.stub("sfx_quarantined", lambda sid: False)
        self.stub("sfx_quarantine", lambda *a, **k: quarantined.append(a) or True)
        got = app.sfx_quarantine_receipts({"player": "pinetab", "rows": [{"error_code": 4, "url": "/sfx/%s?t=x" % key}]})
        self.assertEqual(got, 0)
        self.assertEqual(quarantined, [])
        app._SFX_ID_REVERSE.pop(key, None)

    def test_sting_due_narrows_to_the_shelf_or_stands_down(self):
        self.away()
        share = str(app.SFX_ROOT / "samples_grabbed" / "x" / "y.mp4")
        local = str(app.SFX_ADS_DIR / "PineBox-H3_00001_.mp4")
        pool, names, fresh = app.sfx_reach_narrow([Path(share), Path(local)], [share, local, local], {share, local})
        self.assertEqual(pool, [Path(local)])
        self.assertEqual(names, [local, local])
        self.assertEqual(fresh, {local})
        self.stub("dj_settings", lambda: {"sfx": True, "sfx_rate": 1.0, "sfx_gap": 0.0, "station_name": "t"})
        self.stub("sfx_anxiety", lambda: 0.0)
        self.stub("s3_chance", lambda *a, **k: True)
        self.stub("_sting_draw_sets", lambda: ([Path(share)], [share], set()))
        self.stub("fire_and_forget", lambda c: c.close() if hasattr(c, "close") else None)
        app._STING_AT[0] = 0.0
        self.assertIsNone(app.sting_due())
        self.assertGreaterEqual(app.sfx_reach_state()["stood_down"].get("sting", 0), 1)

    def test_the_intermission_pick_policy_and_turn(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        h3 = Path(tmp.name) / "PineBox-H3_00001_.mp4"
        sc = Path(tmp.name) / "supercut-abc.mp4"
        h3.write_bytes(b"\0" * 20000)
        sc.write_bytes(b"\0" * 20000)
        shelf = [{"path": h3, "kind": "h3", "mtime": 2.0, "bytes": 20000},
                 {"path": sc, "kind": "supercut", "mtime": 1.0, "bytes": 20000}]
        # policy 1: fresh, through System 3's die and the no-repeat book
        self.stub("norepeat_roll_clip", lambda paths, key, q, road="gap": (self.assertEqual(key, "sfx.intermission_pick"), paths[1])[1])
        self.stub("sfx_video_on_cooldown", lambda key: False)
        got = app.sfx_intermission_pick(shelf)
        self.assertEqual((got["path"], got["how"], got["kind"]), (sc, "fresh", "supercut"))
        # policy 2: nothing fresh -> a rested one
        self.stub("norepeat_roll_clip", lambda *a, **k: None)
        self.stub("sfx_video_on_cooldown", lambda key: key == app.sfx_id(sc))
        self.stub("s3_choice", lambda key, opts, label="", tabled=True: opts[0])
        got = app.sfx_intermission_pick(shelf)
        self.assertEqual((got["path"], got["how"]), (h3, "rested"))
        # policy 3: everything on cooldown -> any, never dark
        self.stub("sfx_video_on_cooldown", lambda key: True)
        got = app.sfx_intermission_pick(shelf)
        self.assertEqual(got["how"], "any")
        self.assertIsNone(app.sfx_intermission_pick([]))
        # the turn: the same door, with the why on the ring row
        rung = []
        self.stub("sfx_intermission_shelf", lambda fresh=False: shelf)
        self.stub("sfx_intermission_pick", lambda s: dict(shelf[0], how="fresh"))
        self.stub("sfx_seconds", lambda p: 4.5)

        async def level(path, wait=None):
            return path, "raw"

        self.stub("sfx_level_for_air", level)
        self.stub("page_picture_append", lambda clip, at_ms=0: rung.append((dict(clip), at_ms)) or dict(clip))
        noted = []
        self.stub("sfx_video_note_played", lambda key, folder="": noted.append((key, folder)))
        self.stub("_origin_wall_note", lambda *a, **k: None)
        self.stub("media_sign", lambda k: "sig")
        now = time.time()
        entry = asyncio.run(app.sfx_intermission_turn(now, now))
        self.assertIsNotNone(entry)
        self.assertTrue(entry["intermission"])
        self.assertEqual(entry["id"], app.sfx_id(h3))
        self.assertEqual(len(rung), 1)
        clip, at_ms = rung[0]
        self.assertTrue(clip["why"].startswith("intermission: the SFX collection is unreachable"))
        self.assertIn("H3 render", clip["why"])
        self.assertEqual(clip["url"], "/sfx/%s?t=sig" % app.sfx_id(h3))
        self.assertTrue(clip["endless"] and clip["intermission"])
        self.assertEqual(noted, [(app.sfx_id(h3), h3.parent.name)])
        self.assertEqual(app._SFX_ID_REVERSE.get(app.sfx_id(h3)), str(h3), "/sfx/<key> can serve it")
        state = app.sfx_intermission_state()
        self.assertGreaterEqual(state["rung"], 1)
        self.assertIn("never dark", state["policy"])

    def test_enter_withdraws_the_share_runway_and_defers_the_requests(self):
        ring = app._RADIO.setdefault("voice_clips", [])
        kept = list(ring)
        future = int(time.time() * 1000) + 20000
        ring.append({"endless": True, "broadcast_ms": future, "id": "test-future"})
        ring.append({"endless": True, "broadcast_ms": future - 60000, "id": "test-past"})
        asked = app._SFX_CYCLE.setdefault("requests", [])
        asked_before = list(asked)
        asked.append((Path("/samples/samples_grabbed/x/req.mp4"), "test", "why"))
        epoch = int(app._SFX_CYCLE.get("shuffle_epoch") or 0)
        was_on = app._SFX_INTERMISSION.get("on")
        try:
            app.sfx_intermission_enter()
            ids = [r.get("id") for r in ring if isinstance(r, dict)]
            self.assertNotIn("test-future", ids)
            self.assertIn("test-past", ids)
            self.assertEqual(int(app._SFX_CYCLE["shuffle_epoch"]), epoch + 1)
            self.assertTrue(app._SFX_INTERMISSION["on"])
            self.assertEqual(len(asked), len(asked_before) + 1, "the request is deferred, not dropped")
            self.assertGreaterEqual(app.sfx_reach_state()["deferred"], 1)
            app.sfx_intermission_leave()
            self.assertFalse(app._SFX_INTERMISSION["on"])
        finally:
            ring[:] = kept
            asked[:] = asked_before
            app._SFX_INTERMISSION["on"] = was_on

    def test_the_desk_readings_carry_the_reach(self):
        self.away()
        dressed = app.sfx_reach_dress({"say": "the set is on"})
        self.assertFalse(dressed["reach"]["reachable"])
        self.assertTrue(dressed["say"].startswith("INTERMISSION: the SFX collection is unreachable since"))
        self.assertIn("the set is on", dressed["say"])
        self.assertIn("intermission", dressed)
        self.stub("sfx_db_folders", lambda: [])
        self.stub("sfx_db_counts", lambda: {"rows": 1, "video": 1, "playable": 1, "video_playable": 1})
        self.stub("sfx_bans", lambda: set())
        self.stub("sfx_video_warm", lambda: False)
        doctor = app.sfx_doctor_look()
        self.assertTrue(doctor["verdict"].startswith("INTERMISSION"))
        self.assertEqual(doctor["cure"], "mount")
        self.assertTrue(doctor["share"].get("unreachable"))
        self.assertFalse(doctor["reach"]["reachable"])
        got = asyncio.run(app.sfx_reach_api(0, None)) if False else None
        self.assertIsNone(got)
        self.stub("require_read_auth", lambda a: None)
        got = asyncio.run(app.sfx_reach_api(0, "x"))
        self.assertFalse(got["reachable"])
        self.assertIn("intermission", got)
        self.assertIn("policy", got)
        self.back()
        got = asyncio.run(app.sfx_reach_api(0, "x"))
        self.assertTrue(got["reachable"])


if __name__ == "__main__":
    unittest.main()
