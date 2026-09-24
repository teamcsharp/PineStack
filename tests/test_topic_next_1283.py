import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

import app


class Request:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return dict(self.payload)


class NextBanterScenario(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "banter_topics.json"
        self.path_patch = mock.patch.object(app, "BOMBSHELL_PATH", self.path)
        self.path_patch.start()
        self.was_queue = list(app._SWITCH_QUEUE)
        app._SWITCH_QUEUE.clear()

    def tearDown(self):
        app._SWITCH_QUEUE[:] = self.was_queue
        self.path_patch.stop()
        self.tmp.cleanup()

    def add(self, payload):
        with mock.patch.object(app, "require_auth"), \
                mock.patch.object(app, "note_action"), \
                mock.patch.object(app, "pipeline_log"):
            return asyncio.run(app.dj_topics_add(Request(payload)))

    def test_plain_addition_is_saved_but_not_queued(self):
        row = self.add({"text": "the phones have started answering themselves"})
        self.assertTrue(row["id"])
        self.assertNotIn("queued", row)
        self.assertEqual(app._SWITCH_QUEUE, [])
        self.assertEqual(app.read_bombshells()[0]["id"], row["id"])

    def test_next_addition_owns_the_front_of_the_switchboard(self):
        app._SWITCH_QUEUE.append({"id": "already-waiting", "premise": "later"})
        with mock.patch.object(app, "bombshell_shape_for",
                               return_value="the argument"), \
                mock.patch.object(app, "bombshell_angle",
                                  side_effect=lambda text, shape: f"ANGLE:{shape}:{text}"):
            row = self.add({"text": "the producer has hidden the studio clock",
                            "kind": "topic", "next": True})
        self.assertTrue(row["queued"])
        self.assertEqual(row["queue_position"], 1)
        queued = app._SWITCH_QUEUE[0]
        self.assertEqual(queued["topic_id"], row["id"])
        self.assertEqual(queued["round"], "bombshell")
        self.assertEqual(queued["premise"],
                         "ANGLE:the argument:the producer has hidden the studio clock")
        self.assertEqual(app._SWITCH_QUEUE[1]["id"], "already-waiting")

    def test_usage_is_recorded_when_taken_not_when_enqueued(self):
        with mock.patch.object(app, "bombshell_shape_for", return_value="cold drop"), \
                mock.patch.object(app, "bombshell_angle", return_value="the exact premise"):
            row = self.add({"text": "somebody swapped the callers", "next": True})
        self.assertEqual(app.read_bombshells()[0]["used"], 0)
        with mock.patch.object(app, "interject_mark"):
            taken = app.switchboard_take()
        self.assertEqual(taken["topic_id"], row["id"])
        self.assertEqual(taken["premise"], "the exact premise")
        saved = app.read_bombshells()[0]
        self.assertEqual(saved["used"], 1)
        self.assertIn("cold drop", saved["shapes"])

    def test_saved_topic_can_be_queued_without_rewriting_or_using_it(self):
        row = self.add({"text": "the engineer left a mystery tape"})
        with mock.patch.object(app, "require_auth"), \
                mock.patch.object(app, "note_action"), \
                mock.patch.object(app, "pipeline_log"), \
                mock.patch.object(app, "bombshell_shape_for", return_value="reveal"), \
                mock.patch.object(app, "bombshell_angle", return_value="queued premise"):
            result = asyncio.run(app.dj_topics_queue(row["id"]))
        self.assertTrue(result["queued"])
        self.assertEqual(result["topic"]["id"], row["id"])
        self.assertEqual(app._SWITCH_QUEUE[0]["topic_id"], row["id"])
        self.assertEqual(app.read_bombshells()[0]["used"], 0)

    def test_a_failed_database_write_is_reported(self):
        with mock.patch.object(app, "write_bombshells", return_value=False):
            with self.assertRaises(HTTPException) as raised:
                self.add({"text": "this must not claim it was saved"})
        self.assertEqual(raised.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
