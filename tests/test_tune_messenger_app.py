"""[tune-messenger] The Messenger's road on the public listener door, through app.py.

Imports app, so it runs in the container (tests/ on the path, for the shared
fixtures in test_tune_messenger.py):

    docker exec -w /app -e PYTHONPATH=/app:/app/tests spark-agent \
        python -m unittest tests.test_tune_messenger_app -v

The door is PublicListenerGate wrapped round the real app, exactly as the
second uvicorn serves it: deny by default, Authorization stripped. No
lifespan runs (the TestClient is not entered), so no station starts."""
import unittest
from unittest import mock

from fastapi.responses import Response
from fastapi.testclient import TestClient

import app
import tune_messenger as tm
from test_tune_messenger import CID, SECRETS, UNAIRED, FakeStore, conversation

TOKEN = "tune-token"
CLIP = {"ts": 1790581100000, "broadcast_ms": 1790581107000, "url": "/media/x.wav?t=y", "speech": True,
        "stream": {"length": 12.0, "rows": [
            {"id": "line0000aired", "from": 0.0, "until": 4.0},
            {"id": "line0001board", "from": 4.0, "until": 7.5},
            {"id": "line0002aired", "from": 7.5, "until": 12.0}]}}


class FakeRuntime:
    ready = True

    def __init__(self, store):
        self.store = store

    async def read(self, fn, *args):
        return fn(*args)


class Door(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore({CID: conversation()})
        self.rt = FakeRuntime(self.store)
        self.stack = [
            mock.patch.dict(app.__dict__, {"_system3": lambda: self.rt}),
            mock.patch.object(app, "listen_ok", lambda t: t == TOKEN),
            mock.patch.object(app, "media_sign", lambda key: "a" * 32),
            mock.patch.object(app, "_TUNE_MSG", tm.PublicMessenger()),
            mock.patch.dict(app._RADIO, {"voice_clips": [CLIP], "chat": []}),
        ]
        for p in self.stack:
            p.start()
        self.door = TestClient(app.PublicListenerGate(app.app))
        self.house = TestClient(app.app)

    def tearDown(self):
        for p in reversed(self.stack):
            p.stop()

    def test_the_allowlist(self):
        allows = app._public_allows
        for path in ("/api/system3/public/messenger", "/tune-messenger/tune-messenger.js",
                     "/tune-messenger/system3.js", "/tune-messenger/system3.css",
                     "/tune-messenger/system3-message-tile.js", "/tune-messenger/system3-message-tile.css",
                     "/api/system3/public/poster/1bd9a68416e24e85"):
            self.assertTrue(allows("GET", path), path)
            self.assertFalse(allows("POST", path), "GET only: " + path)
            self.assertFalse(allows("PUT", path), path)
        self.assertTrue(allows("HEAD", "/api/system3/public/messenger"))
        for path in ("/tune-messenger/other.js", "/tune-messenger/", "/api/system3/conversations",
                     "/api/system3/conversation/" + CID, "/api/system3/events", "/api/system3/line",
                     "/api/system3/settings", "/api/system3/config", "/api/segment/inspect",
                     "/api/sfx/poster/1bd9a68416e24e85", "/api/prompt-history", "/system3",
                     "/api/system3/public/messengerx"):
            self.assertFalse(allows("GET", path), "still denied: " + path)
        for path in ("/api/system3/public/lines", "/car-diag.js", "/api/dj", "/stream.m3u8"):
            self.assertTrue(allows("GET", path), "the door's old surface is unchanged: " + path)

    def test_the_road_needs_the_tune_in_token(self):
        self.assertEqual(self.door.get("/api/system3/public/messenger").status_code, 401)
        keyed = self.door.get("/api/system3/public/messenger",
                              headers={"Authorization": "Bearer %s" % app.SPARK_AGENT_API_KEY})
        self.assertEqual(keyed.status_code, 401, "the door strips the key: only a tune-in token opens it")
        self.assertEqual(self.door.post("/api/system3/public/messenger", params={"t": TOKEN}).status_code, 404)
        got = self.door.get("/api/system3/public/messenger", params={"t": TOKEN})
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.headers.get("cache-control"), "no-store")
        data = got.json()
        self.assertEqual([o["conversation_id"] for o in data["order"]], [CID])
        conv = data["convs"][CID]["conv"]
        turns = {t["turn_id"]: t for t in conv["turns"]}
        self.assertEqual(turns[CID + ":t00"]["text"], "The words of turn zero,", "the message on the air")
        self.assertEqual(turns[CID + ":t00.1"]["text"], "on the air now.", "the sting splits the turn")
        blob = got.text
        for word in UNAIRED + SECRETS:
            self.assertNotIn(word, blob, word)
        poster = next(x for x in conv["lines"] if x["line_id"] == "line0001board")["poster"]
        self.assertTrue(poster.startswith("/api/system3/public/poster/1bd9a68416e24e85?t="))

    def test_the_operator_door_still_answers_the_key(self):
        got = self.house.get("/api/system3/public/messenger",
                             headers={"Authorization": "Bearer %s" % app.SPARK_AGENT_API_KEY})
        self.assertEqual(got.status_code, 200)

    def test_everything_else_is_still_denied_at_the_door(self):
        for path in ("/api/system3/conversation/" + CID, "/api/system3/events", "/api/system3/conversations",
                     "/api/segment/inspect", "/system3/system3.js"):
            got = self.door.get(path, params={"t": TOKEN})
            self.assertEqual(got.status_code, 404, path)
            self.assertIn("listener door", got.text)

    def test_many_listeners_one_build(self):
        for _ in range(30):
            self.assertEqual(self.door.get("/api/system3/public/messenger", params={"t": TOKEN}).status_code, 200)
        self.assertEqual(self.store.reads, 1, "thirty polls inside the TTL read the store once")
        rev = self.door.get("/api/system3/public/messenger", params={"t": TOKEN}).json()["convs"][CID]["rev"]
        held = self.door.get("/api/system3/public/messenger", params={"t": TOKEN, "have": "%s:%s" % (CID, rev)})
        self.assertEqual(held.json()["convs"][CID], {"rev": rev})
        self.assertLess(len(held.content), 600, "a page that holds the round is sent its revision only")

    def test_off_when_system3_is_not_ready(self):
        self.rt.ready = False
        data = self.door.get("/api/system3/public/messenger", params={"t": TOKEN}).json()
        self.assertEqual((data["off"], data["order"]), (True, []))
        self.assertEqual(self.store.reads, 0)

    def test_the_poster_road_answers_only_the_clips_own_signature(self):
        sid = "1bd9a68416e24e85"
        with mock.patch.object(app, "sfx_poster_api",
                               mock.AsyncMock(return_value=Response(b"JPEG", media_type="image/jpeg"))) as poster:
            self.assertEqual(self.door.get("/api/system3/public/poster/" + sid).status_code, 404)
            self.assertEqual(self.door.get("/api/system3/public/poster/" + sid, params={"t": "b" * 32}).status_code, 404)
            self.assertEqual(self.door.get("/api/system3/public/poster/not-a-sid", params={"t": "a" * 32}).status_code, 404)
            poster.assert_not_called()
            got = self.door.get("/api/system3/public/poster/" + sid, params={"t": "a" * 32})
            self.assertEqual((got.status_code, got.content), (200, b"JPEG"))

    def test_the_messenger_and_shared_tile_files(self):
        got = self.door.get("/tune-messenger/system3.js", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.headers.get("content-encoding"), "gzip")
        self.assertIn("mountEmbedded", got.text)
        again = self.door.get("/tune-messenger/system3.js",
                              headers={"Accept-Encoding": "gzip", "If-None-Match": got.headers["etag"]})
        self.assertEqual(again.status_code, 304)
        self.assertEqual(self.door.get("/tune-messenger/tune-messenger.js").status_code, 200)
        self.assertEqual(self.door.get("/tune-messenger/system3.css").status_code, 200)
        for name, marker in (("system3-message-tile.js", "createRenderer"),
                             ("system3-message-tile.css", ".sp-rr-sub")):
            route = "/tune-messenger/" + name
            shared = self.door.get(route)
            self.assertEqual(shared.status_code, 200, route)
            self.assertIn(marker, shared.text)
            cached = self.door.get(route, headers={"If-None-Match": shared.headers["etag"]})
            self.assertEqual(cached.status_code, 304, route)
        self.assertEqual(self.house.get("/tune-messenger/app.py").status_code, 404)
        self.assertEqual(self.door.get("/tune-messenger/app.py").status_code, 404)
        self.assertIn('<script src="/tune-messenger/tune-messenger.js" defer></script>', app.RADIO_PAGE_HTML)


if __name__ == "__main__":
    unittest.main()
