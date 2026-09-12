import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
import app


class InboxDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_streaming_chat_collects_and_files_unicode_request_exactly(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (mock.patch.object(app, "PINE_REQUESTS_PATH", root / "inbox.md"),
                  mock.patch.object(app, "PINE_SEQ_PATH", root / "seq"),
                  mock.patch.object(app, "_PINE_CONVERSATIONS", {}),
                  mock.patch.object(app, "require_auth"), mock.patch.object(app, "log_turn"),
                  mock.patch.object(app, "generate_answer", new=mock.AsyncMock()) as model):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url="http://test") as client:
                    first = await client.post("/v1/chat/completions", json={"stream": True,
                        "conversation_id": "alice", "messages": [{"role": "user", "content":
                        "I would like to file a Pine Box request."}]})
                    self.assertEqual(first.status_code, 200)
                    self.assertIn("text/event-stream", first.headers["content-type"])
                    chunks = [json.loads(line[6:]) for line in first.text.splitlines()
                              if line.startswith("data: {")]
                    self.assertEqual(chunks[0]["choices"][0]["delta"]["content"], app.PINE_REQUEST_QUESTION)
                    self.assertIn("data: [DONE]", first.text)
                    body = "Keep cafés — and callers — in the newspaper."
                    submitted = await client.post("/v1/chat/completions", json={
                        "conversation_id": "alice", "messages": [{"role": "user", "content": body}]})
                    self.assertEqual(submitted.json()["spark_agent"]["pine_request"]["state"], "submitted")
                    self.assertEqual(app.pine_read()[0]["text"], body)
                    model.assert_not_awaited()

    async def test_completion_archives_original_and_evidence_and_keeps_other_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (mock.patch.object(app, "PINE_REQUESTS_PATH", root / "inbox.md"),
                  mock.patch.object(app, "PINE_COMPLETED_PATH", root / "completed.md"),
                  mock.patch.object(app, "PINE_SEQ_PATH", root / "seq")):
                first = await app.pine_append("Request one — original text")
                other = await app.pine_append("Request two")
                self.assertEqual((await app.pine_complete(first["id"], "Implemented; 7 checks passed."))["id"], first["id"])
                archive = app.PINE_COMPLETED_PATH.read_text(encoding="utf-8")
                self.assertIn("Request one — original text", archive)
                self.assertIn("Implemented; 7 checks passed.", archive)
                self.assertEqual([r["id"] for r in app.pine_read()], [other["id"]])
                self.assertIsNone(await app.pine_complete(first["id"], "retry"))
                self.assertEqual(app.PINE_COMPLETED_PATH.read_text(encoding="utf-8"), archive)


if __name__ == "__main__":
    unittest.main()
