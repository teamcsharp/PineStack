import tempfile
import unittest
from pathlib import Path

from parody_stinger_queue import ParodyQueue


class ParodyQueueContractTests(unittest.TestCase):
    def test_fifo_survives_reopen_and_one_dispatch_at_a_time(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "jobs.sqlite3"
            queue = ParodyQueue(path)
            first = queue.add({"source": "one", "prompt": "First"})
            second = queue.add({"source": "two", "prompt": "Second"})
            queue = ParodyQueue(path)
            self.assertEqual(queue.next()["id"], first["id"])
            self.assertEqual(queue.claim(first["id"])["source"], "one")
            self.assertIsNone(queue.claim(second["id"]))
            queue.update(first["id"], "running", prompt_id="render-one")
            self.assertIsNone(queue.claim(second["id"]))
            queue.update(first["id"], "done")
            self.assertEqual(queue.claim(second["id"])["source"], "two")

    def test_uncertain_submission_does_not_replay_after_restart(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "jobs.sqlite3"
            queue = ParodyQueue(path)
            item = queue.add({"source": "one", "prompt": "First"})
            queue.claim(item["id"])
            queue = ParodyQueue(path)
            self.assertEqual(queue.get(item["id"])["status"], "paused")
            self.assertIsNone(queue.next())


if __name__ == "__main__":
    unittest.main()
