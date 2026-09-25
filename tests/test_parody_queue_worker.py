import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
from parody_stinger_queue import ParodyQueue


class ParodyQueueWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_engine_waits_then_dispatches_fifo_and_completes(self):
        with tempfile.TemporaryDirectory() as root:
            queue = ParodyQueue(Path(root) / "queue.sqlite3")
            first = queue.add({"mode": "reference", "purpose": "parody_stinger",
                               "source": "clip-a", "prompt": "First"})
            second = queue.add({"mode": "reference", "purpose": "parody_stinger",
                                "source": "clip-b", "prompt": "Second"})
            busy = {"up": True, "observed": True, "busy": True, "available_gb": 70}
            idle = {**busy, "busy": False}
            with (mock.patch.object(app, "comfy_idle_live", new=mock.AsyncMock(
                      side_effect=[busy, idle, idle, idle, idle])),
                  mock.patch.object(app, "render_admission", return_value=(True, "", 70)),
                  mock.patch.object(app, "_comfy_workshop_render_payload", new=mock.AsyncMock(
                      side_effect=[{"prompt_id": "render-a", "model": "h3"},
                                   {"prompt_id": "render-b", "model": "h3"}])),
                  mock.patch.object(app, "workshop_generation", return_value={"status": "done"})):
                await app._parody_stinger_step(queue, "")
                self.assertEqual(queue.get(first["id"])["status"], "queued")
                self.assertEqual(queue.get(second["id"])["status"], "queued")
                await app._parody_stinger_step(queue, "")
                self.assertEqual(queue.get(first["id"])["status"], "running")
                self.assertEqual(queue.get(second["id"])["status"], "queued")
                await app._parody_stinger_step(queue, "")
                self.assertEqual(queue.get(first["id"])["status"], "done")
                await app._parody_stinger_step(queue, "")
                self.assertEqual(queue.get(second["id"])["status"], "running")

    async def test_failed_generation_is_retried_not_discarded(self):
        with tempfile.TemporaryDirectory() as root:
            queue = ParodyQueue(Path(root) / "queue.sqlite3")
            item = queue.add({"mode": "reference", "purpose": "voice_ad",
                              "source": "clip-a", "prompt": "First"})
            queue.claim(item["id"])
            queue.update(item["id"], "running", prompt_id="render-a")
            with mock.patch.object(app, "workshop_generation", return_value={
                "status": "failed", "error": "out of memory",
            }):
                await app._parody_stinger_step(queue, "")
            recovered = queue.get(item["id"])
            self.assertEqual(recovered["status"], "queued")
            self.assertIn("memory", recovered["reason"])
            self.assertGreater(float(recovered["retry_at"]), 0)

    async def test_missing_video_reference_keeps_the_ad_request(self):
        with tempfile.TemporaryDirectory() as root:
            queue = ParodyQueue(Path(root) / "queue.sqlite3")
            with (mock.patch.object(app, "voice_ad_person_clip", return_value={}),
                  mock.patch.object(app, "_parody_stinger_queue", return_value=queue),
                  mock.patch.object(app, "_RADIO", {"on": False})):
                message, job = await app.voice_ad_render("say welcome to Pine Box")
            self.assertEqual(message, "Request completed.")
            stored = queue.get(job["queue_id"])
            self.assertEqual(stored["status"], "queued")
            self.assertEqual(stored["source"], "")


if __name__ == "__main__":
    unittest.main()
