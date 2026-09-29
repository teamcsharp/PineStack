"""[sfxseen] SFX display receipts: the store, the join to the script's SFX
rows, the reasons, the routes, and the line id on every picture.

    docker exec -w /app -e PYTHONPATH=tests:. spark-agent python3 -m unittest tests.test_sfx_display_2026_09_29
"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import sfx_display as sd

T0 = 1790669000.0


def air(i, at, text, **extra):
    row = {"id": i, "ts": int(at) - 5, "air_at": at, "who": "board", "kind": "sfx",
           "text": text, "aired": "page", "seconds": 4.0}
    row.update(extra)
    return row


def rc(_player="pinetab", **kw):
    kw.setdefault("player", _player)
    row = {"kind": "receipt", "rid": kw.pop("rid", "r%d" % int(time.time() * 1e6)), "surface": "tube",
           "outcome": "shown", "shown_s": 4.1, "first_frame_ms": (T0 + 0.18) * 1000,
           "first_frame_lag_ms": 180, "first_frame_via": "rvfc", "requested_ms": T0 * 1000,
           "rect": {"x": 703, "y": 35, "w": 355, "h": 201}, "unoccluded": 1}
    row.update(kw)
    return row


class NormaliseTests(unittest.TestCase):
    def test_a_receipt_is_whitelisted_clamped_and_moved_onto_the_station_clock(self):
        got = sd.normalise(rc("pinetab", url="/sfx/abcdef1234?t=SECRETSIG", evil="x" * 9999,
                              surface="bogus", requested_ms=1000.0),
                           "pinetab", skew_ms=500.0, rx=T0)
        self.assertEqual(got["url"], "/sfx/abcdef1234")            # no signature kept
        self.assertEqual(got["sfx"], "abcdef1234")
        self.assertEqual(got["surface"], "none")
        self.assertNotIn("evil", got)
        self.assertAlmostEqual(got["requested"], 1.5)               # (1000 + 500) ms
        self.assertEqual(got["player"], "pinetab")

    def test_unknown_kinds_are_refused(self):
        self.assertIsNone(sd.normalise({"kind": "shell"}, "p", 0, T0))
        self.assertIsNone(sd.normalise("nope", "p", 0, T0))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / sd.STORE_NAME

    def test_append_and_read_with_skew(self):
        st = sd.ReceiptStore(self.path)
        got = st.append({"player": "pinetab", "sent_ms": (T0 - 2) * 1000,
                         "rows": [rc("pinetab", requested_ms=(T0 - 3) * 1000), {"kind": "bad"}]}, now=T0)
        self.assertEqual((got["accepted"], got["refused"]), (1, 1))
        self.assertEqual(got["skew_ms"], 2000)
        rows = st.read(T0 - 60, T0 + 60)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["requested"], T0 - 1, places=2)

    def test_prune_keeps_seven_days_and_the_byte_bound(self):
        st = sd.ReceiptStore(self.path, max_bytes=4000)
        old = {"kind": "beat", "rx": T0 - 8 * 86400, "player": "desk"}
        with self.path.open("w") as fh:
            fh.write(json.dumps(old) + "\n")
            for i in range(200):
                fh.write(json.dumps({"kind": "beat", "rx": T0 - 10 + i * 0.01, "player": "desk", "n": i}) + "\n")
        st.prune(now=T0)
        text = self.path.read_text()
        self.assertNotIn('"rx": %s' % (T0 - 8 * 86400), text)
        self.assertLessEqual(len(text.encode()), 4000)
        last = json.loads(text.splitlines()[-1])
        self.assertEqual(last["n"], 199)                           # the newest rows win

    def test_the_store_is_named_so_the_clean_slate_classifies_it_keep(self):
        self.assertEqual(sd.STORE_NAME, "sfx_display_receipts.jsonl")
        self.assertEqual(sd.KEEP_S, 7 * 86400)


class ScriptRowsTests(unittest.TestCase):
    def test_reads_the_window_from_the_end_and_keeps_board_rows_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "air_log.jsonl"
            with p.open("w") as fh:
                for i in range(3000):
                    fh.write(json.dumps(air("old%d" % i, T0 - 20000 + i, "old")) + "\n")
                fh.write(json.dumps({"id": "dj1", "air_at": T0 + 1, "ts": T0, "who": "lukas", "kind": "chat",
                                     "text": "talk"}) + "\n")
                fh.write(json.dumps(air("s1", T0 + 2, "95 clip", sfx="aaaaaaaa11")) + "\n")
                fh.write(json.dumps(air("s1", T0 + 2, "95 clip", sfx="aaaaaaaa11", heard_ack_at=T0 + 2.1)) + "\n")
            rows = sd.script_rows(p, T0 - 60, T0 + 60, chunk=4096)
        self.assertEqual([r["id"] for r in rows], ["s1"])
        self.assertTrue(rows[0].get("heard_ack_at"))               # the later write wins


class AuditTests(unittest.TestCase):
    def audit(self, rows, receipts):
        norm = []
        for r in receipts:
            got = sd.normalise(r, r.get("player", "pinetab"), 0.0, T0 + 5)
            norm.append(got)
        return sd.audit(rows, norm, T0 - 60, T0 + 600)

    def test_a_receipt_joins_its_row_by_line_id_and_reads_as_the_operator_asked(self):
        rows = [air("e78120", T0, "75 going all right", sfx="5e23b476f94cbad9", video=True,
                    heard_ack_at=T0 + 0.2, heard_ack_by="page")]
        rep = self.audit(rows, [rc("pinetab", line="e78120", player="pinetab")])
        row = rep["rows"][0]
        self.assertEqual(row["played"]["state"], "heard")
        d = row["displays"]["pinetab"]
        self.assertEqual(d["outcome"], "shown")
        self.assertEqual(d["sentence"], "Displayed on PineTab: web tube 355x201, 4.1 s, first frame +180 ms")
        self.assertEqual(rep["summary"]["players"]["pinetab"]["displayed"], 1)

    def test_delivery_id_and_the_fuzzy_sfx_time_match_join_older_clients(self):
        rows = [air("a1", T0, "clip one", sfx="aaaaaaaa11", video=True, delivery_id="dv1"),
                air("a2", T0 + 60, "clip two", sfx="bbbbbbbb22", video=True)]
        recs = [rc("pinetab", delivery_id="dv1", player="pinetab"),
                rc("desk", url="/sfx/bbbbbbbb22?t=s", due_ms=(T0 + 61) * 1000, player="desk",
                   outcome="not_shown", shown_s=0, first_frame_ms=0, reason="occluded by div#pineLock.lk-screen",
                   unoccluded=0),
                rc("desk", url="/sfx/bbbbbbbb22?t=s", due_ms=(T0 + 300) * 1000, player="desk")]  # too far
        rep = self.audit(rows, recs)
        a1, a2 = rep["rows"]
        self.assertEqual(a1["displays"]["pinetab"]["outcome"], "shown")
        self.assertEqual(a2["displays"]["desk"]["outcome"], "not_shown")
        self.assertIn("occluded", a2["displays"]["desk"]["sentence"])
        why = rep["summary"]["players"]["desk"]["not_displayed_by_reason"]
        self.assertEqual(why.get("occluded by div#pineLock.lk-screen"), 1)
        self.assertIn("no receipt", a1["displays"]["desk"]["reason"])        # the desk said nothing of a1
        self.assertEqual(sum(rep["unscripted"].values()), 1)

    def test_a_punct_row_without_sfx_joins_by_its_text(self):
        rows = [air("x-punct-1", T0, "\U0001f50a 908 of mind if you")]
        rep = self.audit(rows, [rc("pinetab", sting="\U0001f50a 908 of mind if you", due_ms=(T0 + 0.5) * 1000,
                                   silent=True, player="pinetab")])
        self.assertEqual(rep["rows"][0]["displays"]["pinetab"]["outcome"], "shown")

    def test_reasons_when_no_receipt_came_from_the_heartbeat(self):
        rows = [air("v1", T0, "clip", sfx="cccccccc33", video=True),
                air("v2", T0 + 30, "a bang", sfx="dddddddd44")]      # no video key = a sound
        beats = [{"kind": "beat", "player": "pinetab", "at_ms": (T0 + 10) * 1000, "tv_on": True,
                  "screen_on": False, "player_": 1}]
        rep = self.audit(rows, beats)
        self.assertEqual(rep["rows"][0]["displays"]["pinetab"]["reason"], "display off")
        self.assertEqual(rep["rows"][1]["displays"]["pinetab"]["surface"], "audio_only")
        self.assertEqual(rep["summary"]["picture_rows"], 1)

    def test_reactions_during_and_after(self):
        rows = [air("r1", T0, "clip", sfx="eeeeeeee55", video=True)]
        recs = [rc("pinetab", line="r1", rid="RID1", player="pinetab",
                   interactions=[{"what": "radial", "at_ms": (T0 + 1) * 1000}]),
                {"kind": "interaction", "what": "replay", "at_ms": (T0 + 20) * 1000, "rid": "RID1",
                 "player": "pinetab", "line": "r1"}]
        rep = self.audit(rows, recs)
        whats = [(x["what"], x["during"]) for x in rep["rows"][0]["reactions"]]
        self.assertEqual(whats, [("radial", True), ("replay", False)])
        self.assertEqual(rep["summary"]["reactions"], 2)

    def test_the_text_page_prints(self):
        rows = [air("t1", T0, "clip", sfx="ffffffff66", video=True, heard_ack_at=T0)]
        rep = self.audit(rows, [rc("pinetab", line="t1", player="pinetab")])
        text = sd.format_text(rep)
        self.assertIn("script SFX rows 1", text)
        self.assertIn("Displayed on PineTab", text)


class RouteTests(unittest.TestCase):
    def test_the_routes_accept_a_batch_and_answer_the_audit(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except Exception:  # noqa: BLE001
            self.skipTest("fastapi test client not available")
        with tempfile.TemporaryDirectory() as d:
            now = time.time()
            air_log = Path(d) / "air_log.jsonl"
            air_log.write_text(json.dumps(air("L1", now - 30, "clip", sfx="abababab12", video=True)) + "\n")
            calls = []
            ns = {"data_path": lambda name: Path(d) / name, "AIR_LOG_PATH": air_log,
                  "require_read_auth": lambda a: calls.append(("read", a)),
                  "require_auth": lambda a: calls.append(("write", a)), "_RADIO": {"chat": []}}
            app = FastAPI()
            store = sd.install(app, ns)
            self.assertIs(ns["_SFX_DISPLAY_STORE"], store)
            c = TestClient(app)
            got = c.post("/api/sfx/display-receipts", headers={"Authorization": "Bearer k"},
                         json={"player": "pinetab", "sent_ms": now * 1000,
                               "rows": [rc("pinetab", line="L1", player="pinetab")]}).json()
            self.assertEqual(got["accepted"], 1)
            rep = c.get("/api/sfx/display-audit?hours=1").json()
            self.assertEqual(rep["rows"][0]["displays"]["pinetab"]["outcome"], "shown")
            one = c.get("/api/sfx/display-audit?line=L1").json()
            self.assertEqual(len(one["rows"]), 1)
            page = c.get("/api/sfx/display-audit?hours=1&text=1").text
            self.assertIn("Displayed on PineTab", page)
            self.assertIn(("write", "Bearer k"), calls)                   # the POST needs the key
            self.assertIn(("read", None), calls)


class StationStampTests(unittest.TestCase):
    """The line id rides every picture the sets are handed (app.py)."""

    @classmethod
    def setUpClass(cls):
        cls.src = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")

    def test_the_patch_is_in(self):
        for needle in ('import sfx_display as _sfx_display',
                       'rung["line"] = str(clip.get("line"))[:80]',
                       '"line": str(row.get("id") or ""),     # [sfxseen]',
                       '_sting_row.setdefault("id", uuid.uuid4().hex[:6])',
                       '"line": str(_sting_row.get("id") or ""),   # [sfxseen]'):
            self.assertIn(needle, self.src)

    def test_page_picture_append_carries_the_line(self):
        import app
        radio = {"voice_clips": []}
        with mock.patch.object(app, "_RADIO", radio):
            rung = app.page_picture_append({"url": "/sfx/abc?t=s", "id": "abc", "line": "row-punct-1",
                                             "seconds": 2, "silent_picture": True})
        self.assertEqual(rung["line"], "row-punct-1")
        with mock.patch.object(app, "_RADIO", {"voice_clips": []}):
            rung = app.page_picture_append({"url": "/sfx/abc?t=s", "id": "abc", "seconds": 2})
        self.assertNotIn("line", rung)

    def test_the_cadence_picture_names_its_row(self):
        import app
        got = []
        with mock.patch.object(app, "page_picture_append", lambda clip, at_ms=0: got.append(clip)), \
                mock.patch.object(app, "media_sign", lambda k: "sig"):
            app._sfx_cadence_pictures([{"id": "abc-punct-1", "sfx_video_id": "k1", "text": "t",
                                        "sfx_video_seconds": 2.0, "from": 1.0}], T0)
        self.assertEqual(got[0]["line"], "abc-punct-1")

    def test_the_routes_are_installed_on_the_station(self):
        import app
        paths = {getattr(r, "path", "") for r in app.app.routes}
        self.assertIn("/api/sfx/display-receipts", paths)
        self.assertIn("/api/sfx/display-audit", paths)


if __name__ == "__main__":
    unittest.main()
