"""[public-door] The listener door, through app.py.

Imports app, so it runs in the container (tests/ on the path for the shared
fixtures in test_public_door_projection.py), one module at a time, niced:

    docker exec -w /app spark-agent sh -c "SPARK_AGENT_DATA_DIR=/tmp/pubdoor_data \
        PYTHONPATH=/app:/app/tests nice -n 19 timeout 600 \
        python -m unittest tests.test_public_door_projection_app"

The door is PublicListenerGate wrapped round the real app, exactly as the
second uvicorn serves it; the house is the app itself (port 8096). No lifespan
runs (the TestClient is never entered), so no station starts. The tune-in
check, the state and the booth's voice are stand-ins: no real token, no real
state, no model is asked anything."""
import copy
import importlib.util
import inspect
import json
import re
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app
from test_public_door_projection import (FORBIDDEN_KEYS, PAGE_READS, SECRETS, full_state, read_path,
                                         walk_keys)

TOKEN = "door-test-listen"
FULL = "door-test-full"
TOOL = Path(__file__).resolve().parent.parent / "tools" / "public_door_projection_patch.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("public_door_projection_patch", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Door(unittest.TestCase):
    def setUp(self):
        self.state = full_state()
        self.spoken = []

        async def speak(*args, **kwargs):
            self.spoken.append(kwargs.get("extra") or "")
            return "Welcome to the station, Pat."

        async def ad_render(goal, *args, **kwargs):
            return ("Request completed.",
                    {"clip": {"id": "0123456789abcdef", "name": "SAMPLE-NAME-MARKER", "seconds": 9.5,
                              "video": True, "match": "/samples/FOLDER-MARKER"},
                     "queue_id": "q1", "queue_ids": ["q1"], "parts": 1, "status": "queued",
                     "model": "h3", "spoken_copy": "COPY-MARKER"})

        self.stream = {"running": True, "listeners": 2, "mp3_listeners": 1, "hls_active": 1, "bitrate": 64,
                       "rates": [48, 64], "hls_rates": ["64k"], "join_burst_s": 30.0, "title": "Ocean",
                       "artist": "Someone", "up_seconds": 100.0, "produced_seconds": 99.8,
                       "hls": {"lane_dir": "/app/data/hls_spool/64k", "spool": "/app/data/hls_spool",
                               "lanes": [{"error": "LANE-ERROR-MARKER"}]},
                       "hls_listeners": [{"token_tail": "TOKEN-TAIL-MARKER", "addr": "203.0.113.7",
                                          "road": "funnel"}],
                       "listener_rows": [{"id": "10.89.1.5:5555", "sent_kb": 1.0}],
                       "recent_sessions": [{"id": "100.64.0.9:1", "ended": "12:00:00"}],
                       "frames_dropped": 3}
        self.stack = [
            mock.patch.object(app, "listen_ok", lambda t: t in (TOKEN, FULL)),
            mock.patch.object(app, "token_scope", lambda t: {TOKEN: "listen", FULL: "full"}.get(t, "")),
            mock.patch.object(app, "LOCK_READS", False),
            mock.patch.object(app, "dj_state", lambda: copy.deepcopy(self.state)),
            mock.patch.object(app, "seen_note", lambda *a, **k: None),
            mock.patch.object(app, "_radio_listeners", lambda *a, **k: 4),
            mock.patch.object(app, "dj_speak", speak),
            mock.patch.object(app, "voice_ad_render", ad_render),
            mock.patch.object(app.STATION_STREAM, "state", lambda: copy.deepcopy(self.stream)),
        ]
        for p in self.stack:
            p.start()
        self.door = TestClient(app.PublicListenerGate(app.app))
        self.house = TestClient(app.app)

    def tearDown(self):
        for p in reversed(self.stack):
            p.stop()

    def clean(self, body: Any, where: str) -> None:
        blob = json.dumps(body, ensure_ascii=False)
        for secret in SECRETS + ("SAMPLE-NAME-MARKER", "FOLDER-MARKER", "COPY-MARKER", "TOKEN-TAIL-MARKER",
                                 "LANE-ERROR-MARKER", "203.0.113.7", "hls_spool"):
            self.assertNotIn(secret, blob, where)
        keys = {p.rsplit(".", 1)[-1] for p in walk_keys(body)}
        self.assertFalse(keys & FORBIDDEN_KEYS, "%s: %s" % (where, sorted(keys & FORBIDDEN_KEYS)))

    # --- /api/dj -------------------------------------------------------------
    def test_the_door_answers_the_listeners_cut_lean_or_not(self):
        want = app.dj_state_public(full_state())
        for path in ("/api/dj?lean=1&listener=abc&t=" + TOKEN, "/api/dj?t=" + TOKEN,
                     "/api/dj?lean=0&t=" + TOKEN):
            got = self.door.get(path)
            self.assertEqual(got.status_code, 200, path)
            self.assertEqual(got.json(), json.loads(json.dumps(want)), path)
            self.clean(got.json(), path)
            self.assertLess(len(got.content), 12000, path)

    def test_every_field_the_page_reads_comes_through_the_door(self):
        body = self.door.get("/api/dj?lean=1&listener=abc&t=" + TOKEN).json()
        tail = dict(self.state, chat=self.state["chat"][-app.DJ_LEAN_CHAT:])
        for path, where in PAGE_READS.items():
            self.assertEqual(read_path(body, path), read_path(json.loads(json.dumps(tail)), path),
                             "%s (read in %s)" % (path, where))

    def test_no_tune_in_token_no_state_through_the_door(self):
        self.assertEqual(self.door.get("/api/dj?lean=1").status_code, 401)
        self.assertEqual(self.door.get("/api/dj?lean=1&t=nope").status_code, 401)
        self.assertEqual(self.door.get("/api/dj", headers={"Authorization": "Bearer " + str(app.SPARK_AGENT_API_KEY)})
                         .status_code, 401, "the door strips the key: only a token opens it")

    def test_the_house_is_byte_for_byte_the_route_it_was(self):
        """The unpatched route, rebuilt by reversing this tool's two edits on
        the route's own source, answers the house exactly as the patched one."""
        tool = load_tool()
        src = inspect.getsource(app.dj_status)
        old = src.replace(tool.ROUTE_SIG_NEW, tool.ROUTE_SIG_OLD).replace(tool.ROUTE_TAIL_NEW, tool.ROUTE_TAIL_OLD)
        self.assertNotEqual(old, src)
        self.assertNotIn("public", old)
        ns = dict(vars(app))
        ns["app"] = FastAPI()
        exec(compile(old, "the route before [public-door]", "exec"), ns)   # noqa: S102
        before = TestClient(ns["app"])
        for path in ("/api/dj", "/api/dj?lean=1", "/api/dj?lean=1&listener=abc", "/api/dj?lean=yes",
                     "/api/dj?t=" + TOKEN, "/api/dj?lean=1&t=nope"):
            a, b = self.house.get(path), before.get(path)
            self.assertEqual((a.status_code, a.headers.get("content-type")), (b.status_code, b.headers.get("content-type")), path)
            self.assertEqual(a.content, b.content, path)
        self.assertEqual(len(self.house.get("/api/dj").json()["chat"]), 240)
        self.assertIn("STANDING ORDERS FROM THE OPERATOR", self.house.get("/api/dj?lean=1").text)

    # --- the mark is the door's alone ------------------------------------------
    def test_the_gate_drops_a_mark_the_caller_sent(self):
        seen = []

        async def inner(scope, receive, send):
            seen.append(list(scope["headers"]))
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        TestClient(app.PublicListenerGate(inner)).get(
            "/api/dj", headers={"X-Pinebox-Public": "0", "Authorization": "Bearer k"})
        marks = [v for k, v in seen[0] if k.lower() == b"x-pinebox-public"]
        self.assertEqual(marks, [b"1"])
        self.assertFalse([k for k, _ in seen[0] if k.lower() == b"authorization"])

    def test_a_spoofed_mark_changes_nothing_behind_the_door(self):
        spoof = {"x-pinebox-public": "0"}
        got = self.door.get("/api/dj?lean=1&t=" + TOKEN, headers=spoof)
        self.assertEqual(got.json(), json.loads(json.dumps(app.dj_state_public(full_state()))))
        self.assertEqual(self.door.get("/api/dj?lean=1", headers=spoof).status_code, 401)
        # the camera's #1354d refusal: measured open with this one header
        cam = self.door.get("/api/pinelink/frame.jpg", headers=spoof)
        self.assertEqual(cam.status_code, 403)
        self.assertEqual(cam.json().get("detail"), "a tune-in link is required here")
        # a full-scope link is never the studio through the door (#687)
        title = re.compile(r"<title>(.*?)</title>", re.S)
        radio, panel = title.search(app.RADIO_PAGE_HTML).group(1), title.search(app.CONTROL_PANEL_HTML).group(1)
        self.assertNotEqual(radio, panel)
        page = self.door.get("/tune/" + FULL, headers=spoof)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(title.search(page.text).group(1), radio)
        self.assertIn("const AWAY = true;", page.text)
        house = self.house.get("/tune/" + FULL)
        self.assertEqual(title.search(house.text).group(1), panel, "the house still opens the studio")

    # --- the other answers that carried the house -------------------------------
    def test_join_answers_the_welcome_through_the_door(self):
        body = {"listener": "abc", "name": "Pat"}
        got = self.door.post("/api/dj/join?t=" + TOKEN, json=body)
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json(), {"welcome": "Welcome to the station, Pat.", "listeners": 4})
        house = self.house.post("/api/dj/join?t=" + TOKEN, json=body).json()
        self.assertEqual(house["welcome"], "Welcome to the station, Pat.")
        self.assertEqual(len(house["chat"]), 240, "the house keeps the whole state")

    def test_stream_state_names_no_listener_through_the_door(self):
        got = self.door.get("/api/stream/state?t=" + TOKEN)
        self.assertEqual(got.status_code, 200)
        self.assertEqual(set(got.json()), set(app.STREAM_PUBLIC_KEYS) & set(self.stream))
        self.clean(got.json(), "/api/stream/state")
        self.assertEqual(self.door.get("/api/stream/state").status_code, 401)
        self.assertEqual(self.house.get("/api/stream/state?t=" + TOKEN).json(), self.stream)

    def test_ads_answer_the_message_through_the_door(self):
        got = self.door.post("/api/listener/ads?t=" + TOKEN, json={"prompt": "a pine cone that sings"})
        self.assertEqual(got.json(), {"ok": True, "message": "Request completed."})
        house = self.house.post("/api/listener/ads?t=" + TOKEN, json={"prompt": "a pine cone that sings"}).json()
        self.assertEqual(house["ad"]["clip"]["name"], "SAMPLE-NAME-MARKER")

    def test_no_json_answer_on_the_door_carries_the_house(self):
        paths = ["/healthz", "/api/dj", "/api/dj?lean=1", "/api/dj/voice?since=0", "/api/dj/reacts",
                 "/api/dj/video?since=0&lag=30", "/api/radio/clock?listener=abc", "/api/stream/state",
                 "/api/pinelink/mine", "/api/listener/upload/status?name=x.mp4", "/manifest.webmanifest"]
        allowed = app._public_allows
        for path in paths:
            self.assertTrue(allowed("GET", path.split("?")[0]), path)
            got = self.door.get(path + ("&" if "?" in path else "?") + "t=" + TOKEN)
            self.assertLess(got.status_code, 500, path)
            if "json" in (got.headers.get("content-type") or ""):
                self.clean(got.json(), path)
                self.assertNotIn("STANDING ORDERS", got.text, path)
                self.assertNotIn('"persona', got.text, path)

    def test_the_allowlist_is_unchanged(self):
        for path in ("/api/dj", "/api/stream/state", "/api/system3/public/lines", "/icons/pineicons.css",
                     "/tune/x", "/car-diag.js", "/api/system3/public/messenger", "/tune-messenger/system3.js"):
            self.assertTrue(app._public_allows("GET", path), path)
        for path in ("/api/dj/join", "/api/listener/ads"):
            self.assertTrue(app._public_allows("POST", path), path)
        for path in ("/api/dj/state", "/api/settings", "/api/system3/conversations", "/spark"):
            self.assertFalse(app._public_allows("GET", path), path)


class LinkThatRanOut(unittest.TestCase):
    """A dead link gets a page that says so; the page can ask; the panel's
    list keeps what ran out, apart and marked."""

    LIVE = "1790999999.abc123.def456"

    def setUp(self):
        live = {self.LIVE: "listen", TOKEN: "listen"}
        self.stack = [
            mock.patch.object(app, "listen_ok", lambda t: t in live),
            mock.patch.object(app, "token_scope", lambda t: live.get(t, "")),
            mock.patch.object(app, "LOCK_READS", False),
        ]
        for p in self.stack:
            p.start()
        self.door = TestClient(app.PublicListenerGate(app.app))
        self.house = TestClient(app.app)

    def tearDown(self):
        for p in reversed(self.stack):
            p.stop()

    def test_a_dead_link_gets_a_page_that_says_so(self):
        dead = "1700000000.feed01.0badc0de"
        for client, where in ((self.door, "door"), (self.house, "house")):
            got = client.get("/tune/" + dead)
            self.assertEqual(got.status_code, 403, where)
            self.assertIn("text/html", got.headers.get("content-type", ""), where)
            self.assertIn(app.LINK_GONE_SAY, got.text, where)
            self.assertEqual(got.headers.get("cache-control"), "no-store", where)
            for leak in (dead, "detail", "revoked", "feed01"):
                self.assertNotIn(leak, got.text, where + ": " + leak)
        live = self.door.get("/tune/" + self.LIVE)
        self.assertEqual(live.status_code, 200)
        self.assertIn('id="patter"', live.text)

    def test_the_page_can_ask_whether_its_link_is_alive(self):
        self.assertTrue(app._public_allows("GET", "/api/listen/link"))
        self.assertFalse(app._public_allows("POST", "/api/listen/link"))
        got = self.door.get("/api/listen/link?t=" + self.LIVE)
        self.assertEqual((got.status_code, got.json()), (200, {"live": True, "expires": 1790999999}))
        self.assertEqual(self.door.get("/api/listen/link?t=" + TOKEN).json(), {"live": True, "expires": 0})
        for path in ("/api/listen/link?t=1700000000.feed01.0badc0de", "/api/listen/link"):
            got = self.door.get(path)
            self.assertEqual(got.status_code, 403, path)
            self.assertEqual(got.json(), {"live": False, "say": app.LINK_GONE_SAY}, path)
        self.assertEqual(self.door.post("/api/listen/link?t=" + self.LIVE).status_code, 404)

    def test_the_share_list_keeps_what_ran_out_apart_and_marked(self):
        now = time.time()
        rows = {"links": {
            "live1": {"label": "the car", "expires": now + 5 * 86400, "scope": "listen",
                      "url": "https://lilspark.example/tune/%d.live1.aa" % int(now + 5 * 86400)},
            "old1": {"label": "a listener", "expires": now - 6 * 86400, "scope": "listen",
                     "url": "https://lilspark.example/tune/%d.old1.bb" % int(now - 6 * 86400)},
            "old2": {"label": "the radio", "expires": now - 3600, "scope": "full",
                     "url": "https://lilspark.example/tune/%d.old2.cc.full" % int(now - 3600)}},
            "revoked": []}
        with mock.patch.object(app, "require_auth", lambda authorization: None), \
                mock.patch.object(app, "read_shares", lambda: copy.deepcopy(rows)), \
                mock.patch.object(app, "remote_access", lambda: {"urls": []}), \
                mock.patch.object(app, "link_road", lambda url, net: {"road": "funnel", "say": "x", "public": True}):
            got = self.house.get("/api/share").json()
        self.assertEqual([r["tag"] for r in got["links"]], ["live1"], "`links` stays live-only")
        self.assertEqual([r["tag"] for r in got["expired"]], ["old2", "old1"], "newest first")
        old1 = got["expired"][1]
        self.assertTrue(old1["expired"])
        self.assertEqual(old1["label"], "a listener")
        self.assertAlmostEqual(old1["hours_ago"], 144.0, delta=0.2)
        self.assertEqual(got["expired"][0]["scope"], "full")
        self.assertNotIn("url", old1, "a dead link is not handed out again")
        self.assertFalse(app._public_allows("GET", "/api/share"), "the list is the house's alone")


if __name__ == "__main__":
    unittest.main()
