"""[lone-line-now] A line that plays on its own gives the Script view its place.

09-29: the manager's memo was heard for 20 s while /api/dj said stream_now =
null - the Script view's ON AIR mark had nowhere to stand.

Run (never against the live data): SPARK_AGENT_DATA_DIR=/tmp/x/data \
    PYTHONPATH=tests:. python3 -m unittest tests.test_lone_line_now
"""
import inspect
import time
import unittest
from unittest import mock

import app

MEMO = {"id": "memo1", "who": "manager", "name": "the manager upstairs", "kind": "manager",
        "text": "The stench from this booth has migrated up to the third floor.", "seconds": 0.0,
        "voice": "vl_x"}


class LoneLine(unittest.TestCase):
    def setUp(self):
        self.stream = {}
        patches = [mock.patch.object(app, "_STREAM_NOW", self.stream),
                   mock.patch.dict(app._RADIO, {"chat": [dict(MEMO)]})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_a_memo_playing_alone_is_published_and_given_back_when_it_ends(self):
        now = time.time()
        self.assertTrue(app._lone_line_now("memo1", {"line": "memo1"}, now - 3.0, {"duration": 19.5}))
        self.assertEqual([r["id"] for r in self.stream["rows"]], ["memo1"])
        self.assertAlmostEqual(self.stream["at"], now - 3.0, delta=0.01)
        self.assertEqual(self.stream["length"], 19.5)
        self.assertEqual(self.stream["rows"][0]["kind"], "manager")
        app._lone_line_end("memo1")
        self.assertEqual(self.stream, {})

    def test_without_a_length_the_words_decide(self):
        self.assertTrue(app._lone_line_now("memo1", {}, time.time()))
        self.assertAlmostEqual(self.stream["length"], max(2.0, len(MEMO["text"]) / 14.0), places=3)

    def test_a_sting_under_a_sounding_round_never_takes_its_place(self):
        now = time.time()
        app._stream_now_set([{"id": "r1", "from": 0.0, "until": 30.0}], 30.0, stamp=False)
        self.stream["at"] = now - 5.0
        app._RADIO["chat"].append({"id": "st1", "kind": "sfx", "text": "boom"})
        self.assertFalse(app._lone_line_now("st1", {"line": "st1"}, now))
        self.assertEqual([r["id"] for r in self.stream["rows"]], ["r1"])
        app._lone_line_end("st1")
        self.assertEqual([r["id"] for r in self.stream["rows"]], ["r1"], "another line's end changes nothing")

    def test_a_round_that_has_finished_does_not_block(self):
        app._stream_now_set([{"id": "r1", "from": 0.0, "until": 3.0}], 3.0, stamp=False)
        self.stream["at"] = time.time() - 60.0
        self.assertTrue(app._lone_line_now("memo1", {}, time.time()))

    def test_an_unknown_line_is_not_published(self):
        self.assertFalse(app._lone_line_now("nope", {}, time.time()))
        self.assertFalse(app._lone_line_now("", {}, time.time()))
        self.assertEqual(self.stream, {})

    def test_the_ack_wires_both_ends(self):
        src = inspect.getsource(app.page_playback_ack)
        self.assertIn("_lone_line_now(str(clip.get(\"line\")), clip, now - position, body)", src)
        self.assertIn("_lone_line_end(", src)


if __name__ == "__main__":
    unittest.main()
