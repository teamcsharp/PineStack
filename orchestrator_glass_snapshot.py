"""Bounded, read-only telemetry work for the orchestra popup.

One refresh per key runs on a private executor. HTTP readers receive live
core state immediately and either the latest measured detail or an explicit
pending/error status; a ledger census cannot occupy the shared station pool.
"""
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor


class SnapshotReads:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="orch-glass")
        self.lock = threading.Lock()
        self.cache = {}
        self.pending = {}

    def _finish(self, key, future):
        try:
            value = dict(future.result())
        except Exception as exc:
            value = {"why": "Station measurements could not be read (%s)" % type(exc).__name__}
        with self.lock:
            self.cache[key] = (time.monotonic(), time.time(), value)
            if self.pending.get(key) is future:
                self.pending.pop(key, None)

    async def read(self, key, build, ttl=12, budget=0.25):
        with self.lock:
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < ttl:
                return dict(cached[2], snapshot_at=cached[1], refreshing=False)
            future = self.pending.get(key)
            if future is None:
                future = self.pool.submit(build)
                self.pending[key] = future
                new = True
            else:
                new = False
        # Register outside the lock: a completed future calls back immediately.
        if new:
            future.add_done_callback(lambda done: self._finish(key, done))
        end = asyncio.get_running_loop().time() + max(0, budget)
        while not future.done() and asyncio.get_running_loop().time() < end:
            await asyncio.sleep(min(0.025, max(0, end - asyncio.get_running_loop().time())))
        with self.lock:
            cached = self.cache.get(key)
            refreshing = key in self.pending
        if cached:
            return dict(cached[2], snapshot_at=cached[1], refreshing=refreshing)
        return {"refreshing": True,
                "why": "Station measurements are being collected; live controls remain available."}


_reads = SnapshotReads()
read_snapshot = _reads.read
