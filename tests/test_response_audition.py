import asyncio
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app
from response_bank import ResponseBank


class ResponseAuditionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.bank = ResponseBank(root / "bank.json", root)
        (root / "host.wav").write_bytes(b"stored host recording")
        (root / "cohost.wav").write_bytes(b"stored cohost recording")
        self.bank.put("host", "xtts", "I'm listening.", "listening",
                      {"path": "/media/host.wav", "seconds": 1.0})
        self.bank.put("other", "xtts", "Go on.", "listening",
                      {"path": "/media/cohost.wav", "seconds": 2.0})
        self.lines = [{"who": "dj", "response_id": self.bank.key("host", "xtts", "I'm listening.")},
                      {"who": "cohost", "response_id": self.bank.key("other", "xtts", "Go on.")}]
        self.stack.enter_context(mock.patch.object(app, "_RESPONSES", self.bank))
        self.stack.enter_context(mock.patch.object(app, "_RADIO", {"chat": []}))
        for name, value in {"radio_paused": False, "voice_engine_for": "xtts",
                            "booth_actor_name": "presenter"}.items():
            self.stack.enter_context(mock.patch.object(app, name, return_value=value))
        self.stack.enter_context(mock.patch.object(app, "require_auth"))
        self.stack.enter_context(mock.patch.object(app, "session_voices", return_value={"dj": "host", "cohost": "other"}))
        self.stack.enter_context(mock.patch.object(app, "_floor_take", return_value=True))
        self.stack.enter_context(mock.patch.object(app, "_floor_drop"))

    async def test_exact_real_ready_rows_publish_in_their_own_voices_with_sample_offsets(self):
        with (mock.patch.object(app, "_response_audition_build", return_value=(b"pcm wav", [1.0, 2.0])) as build,
              mock.patch.object(app, "_store_media", return_value={"path": "/media/joined.wav", "sig": "signed"}),
              mock.patch.object(app, "page_feed_append", return_value="delivery") as publish,
              mock.patch.object(app, "page_delivery_apply")):
            result = await app.response_bank_play_api({"lines": self.lines}, "auth")
        app.require_auth.assert_called_once_with("auth")
        self.assertEqual([p["voice"] for p in build.call_args.args[0]], ["host", "other"])
        rows = publish.call_args.args[0]["stream"]["rows"]
        self.assertEqual([(r["text"], r["who"], r["from"], r["until"]) for r in rows],
            [("I'm listening.", "dj", 0.0, 1.0), ("Go on.", "cohost", 1.0, 3.0)])
        self.assertEqual(result["state"], "published")
        self.assertEqual(result["seconds"], 3.0)
        app._floor_drop.assert_called_once_with(True)

    async def test_wrong_presenter_or_unready_id_never_reaches_mixer_or_feed(self):
        for lines in ([{**self.lines[0], "who": "cohost"}, self.lines[1]],
                      [{**self.lines[0], "response_id": "not-recorded"}, self.lines[1]]):
            with (mock.patch.object(app, "_response_audition_build") as build,
                  mock.patch.object(app, "page_feed_append") as publish):
                with self.assertRaises(app.HTTPException) as failed:
                    await app.response_bank_play_api({"lines": lines}, "auth")
                self.assertEqual(failed.exception.status_code, 409)
                build.assert_not_called()
                publish.assert_not_called()

    async def test_arbitrary_words_and_excessive_batches_are_rejected(self):
        for body in ({"lines": [{**self.lines[0], "text": "unauthorized words"}, self.lines[1]]},
                     {"lines": self.lines * 4}):
            with self.assertRaises(app.HTTPException) as failed:
                await app.response_bank_play_api(body, "auth")
            self.assertEqual(failed.exception.status_code, 400)

    async def test_cast_change_during_assembly_cannot_publish_wrong_voice(self):
        with (mock.patch.object(app, "session_voices", side_effect=[{"dj": "host", "cohost": "other"},
                {"dj": "new-host", "cohost": "other"}]),
              mock.patch.object(app, "_response_audition_build", return_value=(b"pcm wav", [1.0, 2.0])),
              mock.patch.object(app, "page_feed_append") as publish):
            with self.assertRaises(app.HTTPException) as failed:
                await app.response_bank_play_api({"lines": self.lines}, "auth")
            self.assertEqual(failed.exception.status_code, 409)
            publish.assert_not_called()
        app._floor_drop.assert_called_once_with(True)

    async def test_busy_floor_expires_without_publishing_or_releasing_another_round(self):
        cancelled = asyncio.Event()

        async def occupied(label):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        with (mock.patch.object(app, "_floor_take", side_effect=occupied),
              mock.patch.object(app, "RESPONSE_AUDITION_FLOOR_WAIT", .01),
              mock.patch.object(app, "_response_audition_build") as build,
              mock.patch.object(app, "page_feed_append") as publish):
            with self.assertRaises(app.HTTPException) as failed:
                await app.response_bank_play_api({"lines": self.lines}, "auth")
            self.assertEqual(failed.exception.status_code, 409)
            self.assertTrue(cancelled.is_set())
            build.assert_not_called()
            publish.assert_not_called()
            app._floor_drop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
