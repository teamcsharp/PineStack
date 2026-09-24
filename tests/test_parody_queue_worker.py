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


if __name__ == "__main__":
    unittest.main()
