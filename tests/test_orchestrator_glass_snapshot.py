import asyncio
import threading
import time
import unittest
from orchestrator_glass_snapshot import SnapshotReads


class SnapshotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.reads = SnapshotReads()
        self.release = threading.Event()

    def tearDown(self):
        self.release.set()
        self.reads.pool.shutdown(wait=True)

    async def test_slow_scan_is_bounded_and_shared(self):
        calls = []
        def build():
            calls.append(1)
            self.release.wait(2)
            return {"rooms": [{"name": "real room", "ready": 7}]}
        start = time.monotonic()
        first, second = await asyncio.gather(
            self.reads.read("details", build, budget=.03),
            self.reads.read("details", build, budget=.03))
        self.assertLess(time.monotonic()-start,.3)
        self.assertEqual(len(calls),1)
        self.assertNotIn("rooms",first)
        self.assertTrue(first["refreshing"])
        self.release.set()
        for _ in range(50):
            got = await self.reads.read("details", build, budget=.01)
            if not got["refreshing"]: break
            await asyncio.sleep(.01)
        self.assertEqual(got["rooms"][0]["ready"],7)
        self.assertEqual(len(calls),1)
        self.assertGreater(got["snapshot_at"],0)
        self.assertFalse(second.get("rooms"))

    async def test_cold_history_does_not_block_live_detail(self):
        def history():
            self.release.wait(2)
            return {"rolls": 42}
        slow, detail = await asyncio.gather(
            self.reads.read("history",history,budget=.03),
            self.reads.read("details",lambda:{"asks":[{"id":"real ask"}]},budget=.03))
        self.assertTrue(slow["refreshing"])
        self.assertEqual(detail["asks"][0]["id"],"real ask")

    async def test_refresh_preserves_measured_values(self):
        await self.reads.read("details",lambda:{"rooms":[{"ready":7}]},budget=.1)
        def refresh():
            self.release.wait(2)
            return {"rooms":[{"ready":9}]}
        stale = await self.reads.read("details",refresh,ttl=0,budget=.01)
        self.assertEqual(stale["rooms"][0]["ready"],7)
        self.assertTrue(stale["refreshing"])
        self.release.set()
        await asyncio.sleep(.03)
        fresh = await self.reads.read("details",refresh,budget=.1)
        self.assertEqual(fresh["rooms"][0]["ready"],9)
        self.assertFalse(fresh["refreshing"])

    async def test_failed_measurement_is_not_a_zero(self):
        def fail(): raise OSError("fixture")
        got = await self.reads.read("details",fail,budget=.1)
        self.assertIn("OSError",got["why"])
        self.assertNotIn("rooms",got)
        self.assertNotIn("waste",got)
        self.assertFalse(got["refreshing"])


if __name__ == "__main__": unittest.main()
