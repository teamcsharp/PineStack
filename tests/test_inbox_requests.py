import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class PineInboxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pending = dict(app._PINE_CONVERSATIONS)
        app._PINE_CONVERSATIONS.clear()

    def tearDown(self):
        app._PINE_CONVERSATIONS.clear()
        app._PINE_CONVERSATIONS.update(self.pending)

    async def test_two_turn_request_is_filed_exactly_and_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (mock.patch.object(app, "PINE_REQUESTS_PATH", root / "inbox.md"),
                  mock.patch.object(app, "PINE_SEQ_PATH", root / "seq")):
                reply = await app.pine_conversation([{"role": "user", "content":
                    "I would like to file a Pine Box request."}], "alice")
                self.assertEqual(reply["state"], "awaiting_request")
                self.assertEqual(app.pine_read(), [])
                body = "The host should finish conversations with callers."
                filed = await app.pine_conversation([
                    {"role": "user", "content": body}], "alice")
                self.assertEqual(filed["state"], "submitted")
                self.assertEqual(app.pine_read()[0]["text"], body)
                self.assertIsNone(await app.pine_conversation([
                    {"role": "user", "content": "Thank you."}], "alice"))
                self.assertEqual(len(app.pine_read()), 1)

    async def test_pending_request_does_not_capture_other_listener(self):
        await app.pine_conversation([{"role": "user", "content":
            "File a Pine Box request"}], "alice")
        with mock.patch.object(app, "pine_append", new=mock.AsyncMock()) as save:
            result = await app.pine_conversation([
                {"role": "user", "content": "What time is it?"}], "bob")
        self.assertIsNone(result)
        save.assert_not_awaited()

    async def test_full_history_and_inline_body_both_file_requests(self):
        save = mock.AsyncMock(side_effect=lambda text: {"id": 18, "text": text})
        with mock.patch.object(app, "pine_append", new=save):
            result = await app.pine_conversation([
                {"role": "user", "content": "File a Pine Box request"},
                {"role": "assistant", "content": app.PINE_REQUEST_QUESTION},
                {"role": "user", "content": "Keep the talk going."}])
            self.assertEqual(result["submitted"]["text"], "Keep the talk going.")
            inline = await app.pine_conversation([{"role": "user", "content":
                "Please file a Pine Box request: Add more caller topics."}])
            self.assertEqual(inline["submitted"]["text"], "Add more caller topics.")

    async def test_cancel_and_expiry_do_not_create_requests(self):
        with (mock.patch.object(app, "pine_append", new=mock.AsyncMock()) as save,
              mock.patch.object(app.time, "time", return_value=1000.0)):
            await app.pine_conversation([{"role": "user", "content":
                "File a Pine Box request"}], "alice")
            cancelled = await app.pine_conversation([
                {"role": "user", "content": "Never mind."}], "alice")
            self.assertEqual(cancelled["state"], "cancelled")
            app._PINE_CONVERSATIONS["alice"] = 999.0
            self.assertIsNone(await app.pine_conversation([
                {"role": "user", "content": "Is the radio on?"}], "alice"))
            save.assert_not_awaited()

    async def test_discussing_inbox_does_not_file_or_start_request(self):
        self.assertIsNone(await app.pine_conversation([{"role": "user", "content":
            "Explain how I would file a Pine Box request."}], "alice"))
        self.assertEqual(app._PINE_CONVERSATIONS, {})

    def test_hourly_paper_requires_active_unpaused_station_and_toggle(self):
        with (mock.patch.dict(app._RADIO, {"on": True}),
              mock.patch.object(app, "radio_paused", return_value=False),
              mock.patch.object(app, "dj_settings", return_value={"paper_hourly": True})):
            self.assertTrue(app.paper_hourly_enabled())
            with mock.patch.dict(app._RADIO, {"on": False}):
                self.assertFalse(app.paper_hourly_enabled())
            with mock.patch.object(app, "radio_paused", return_value=True):
                self.assertFalse(app.paper_hourly_enabled())
            with mock.patch.object(app, "dj_settings", return_value={"paper_hourly": False}):
                self.assertFalse(app.paper_hourly_enabled())

    def test_reader_preserves_original_article_order_and_removes_navigation(self):
        article = """<html><head><meta property="og:title" content="A complete story">
          <meta name="author" content="A Reporter"></head><body>
          <nav><p>This navigation sentence is long enough to look like real prose.</p></nav>
          <article><h1>A complete story</h1>
          <p>The opening paragraph explains the original news event with its full factual details.</p>
          <h2>A second section</h2>
          <p>The middle paragraph quotes the evidence and provides additional context for the story.</p>
          <p>The final paragraph concludes the original article without losing its final sentence.</p>
          <blockquote>A witness explains precisely what they saw at the time of the event.</blockquote>
          </article></body></html>"""
        row = app.newsread_extract(article, "https://example.org/story")
        self.assertEqual(row["title"], "A complete story")
        self.assertEqual(row["byline"], "A Reporter")
        self.assertEqual([b["k"] for b in row["blocks"]], ["p", "h", "p", "p", "q"])
        self.assertIn("final sentence", row["blocks"][3]["t"])
        self.assertNotIn("navigation", " ".join(row["paragraphs"]))


if __name__ == "__main__":
    unittest.main()
