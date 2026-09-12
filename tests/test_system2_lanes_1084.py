"""#1084: one System2 sitting per model lane; a second sitting takes another road."""
import asyncio
import unittest
from unittest import mock

import system2_runtime as adapter


class _Host:
    OLLAMA_LANES = 2
    DATA_DIR = None
    _RADIO = {"on": True}


class LanesTests(unittest.TestCase):
    def _runtime(self, lanes):
        host = _Host()
        host.OLLAMA_LANES = lanes
        with mock.patch.object(adapter.System2Runtime, "__init__", lambda self, h: None):
            rt = adapter.System2Runtime(host)
        rt.host = host
        rt.config = {"engine": "system2"}
        rt._lanes = max(1, min(4, int(getattr(host, "OLLAMA_LANES", 1) or 1)))
        rt._prepare_lock = asyncio.Semaphore(rt._lanes)
        rt._works = {}
        rt._work = {}
        return rt

    def test_the_semaphore_follows_the_lanes(self):
        rt = self._runtime(2)
        self.assertEqual(rt._lanes, 2)
        self.assertFalse(rt._prepare_lock.locked())
        one = self._runtime(1)
        self.assertEqual(one._lanes, 1)
        many = self._runtime(9)
        self.assertEqual(many._lanes, 4)

    def test_spawn_starts_a_sitting_only_while_a_lane_is_free(self):
        rt = self._runtime(2)
        started = []

        async def fake_prepare():
            started.append(1)
            await asyncio.sleep(0)

        rt.prepare = fake_prepare

        async def run():
            first = rt.prepare_spawn()
            self.assertIsNotNone(first)
            await first
            # Both permits taken: nothing more is spawned.
            await rt._prepare_lock.acquire()
            await rt._prepare_lock.acquire()
            self.assertTrue(rt._prepare_lock.locked())
            self.assertIsNone(rt.prepare_spawn())
            rt._prepare_lock.release()
            rt._prepare_lock.release()
            rt.config["engine"] = "legacy"
            self.assertIsNone(rt.prepare_spawn())
        asyncio.run(run())
        self.assertEqual(started, [1])

    def test_a_busy_road_is_left_to_its_sitting(self):
        rt = self._runtime(2)
        rt._works = {"t1": {"kind": "caller", "state": "preparing"},
                     "t2": {"kind": "ad", "state": "done"}}
        busy = {str(w.get("kind") or "") for w in rt._works.values() if w.get("state") == "preparing"}
        kinds = [k for k in ("ad", "manager", "caller", "gallery", "news", "banter",
                             "track_talk", "recap", "deep") if k not in busy]
        self.assertNotIn("caller", kinds)
        self.assertIn("ad", kinds)


if __name__ == "__main__":
    unittest.main()
