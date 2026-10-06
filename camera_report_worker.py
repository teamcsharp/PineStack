"""Serialize authenticated camera reports without using the bulk work pool."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
import time


class StaleReportError(ValueError):
    pass


@dataclass(frozen=True)
class Receipt:
    sequence: int
    at: float


class OrderedReports:
    def __init__(self, max_age: float = 20.0, capacity: int = 8,
                 clock=time.time, monotonic=time.monotonic):
        self.max_age = max_age
        self._clock = clock
        self._monotonic = monotonic
        self._counter = 0
        self._committed = 0
        self._counter_lock = Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="camera-report")
        self._slots = None
        self.capacity = max(1, int(capacity))

    def receive(self) -> Receipt:
        # Call immediately after authentication, before awaiting the body.
        with self._counter_lock:
            self._counter += 1
            return Receipt(self._counter, self._monotonic())

    async def run(self, receipt, build, write, state, reply):
        if self._slots is None:
            self._slots = asyncio.Semaphore(self.capacity)
        async with self._slots:
            return await asyncio.get_running_loop().run_in_executor(
                self._pool, self._commit, receipt, build, write, state, reply)

    def _commit(self, receipt, build, write, state, reply):
        if receipt.sequence <= self._committed:
            raise StaleReportError("a newer camera report was already committed; retry")
        if self._monotonic() - receipt.at >= self.max_age:
            raise StaleReportError("the camera report waited too long to remain authoritative; retry")
        # Validation and the file timestamp belong to this worker execution,
        # not a request waiting in a different executor's queue.
        report = build(self._clock())
        write(report)
        self._committed = receipt.sequence
        current = state()
        # Completion time makes any slow write/read visible to freshness gates.
        return reply(current, report, self._clock())

    def close(self):
        self._pool.shutdown(wait=False)
