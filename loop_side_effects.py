"""Ordered disk side effects without waiting on their locks in the HTTP loop."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Callable


class OrderedSideEffects:
    """One worker and a bounded work queue; scalar keyed jobs coalesce.

    Enqueue waiters retain accepted jobs when the queue fills. They never
    block the event loop or discard a reservation. A failed job stays at the
    head and retries, so its reservation cannot be released before commit.
    """
    def __init__(self, capacity: int = 32, name: str = "video-receipts"):
        self.capacity = max(1, int(capacity))
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)
        self._lock = Lock()
        self._pending: set[str] = set()
        self._version = 0
        self._queue = None
        self._consumer = None
        self._enqueuers: set[asyncio.Task] = set()
        self.error = ""

    def pending(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def checkpoint(self) -> int | None:
        """Capture an idle epoch before a generation reset waits for disk."""
        with self._lock:
            return None if self._pending else self._version

    def changed(self, checkpoint: int) -> bool:
        with self._lock:
            return bool(self._pending) or self._version != checkpoint

    def submit(self, key: str, work: Callable[[], None], reserve: Callable[[], None]) -> bool:
        loop = asyncio.get_running_loop()
        with self._lock:
            if key in self._pending:
                return False
            self._pending.add(key)
            self._version += 1
        try:
            reserve()
            if self._queue is None:
                self._queue = asyncio.Queue(maxsize=self.capacity)
            if self._consumer is None or self._consumer.done():
                self._consumer = loop.create_task(self._consume())
            task = loop.create_task(self._queue.put((key, work)))
            self._enqueuers.add(task)
            task.add_done_callback(self._enqueuers.discard)
            return True
        except BaseException:
            with self._lock:
                self._pending.discard(key)
            raise

    async def _consume(self):
        loop = asyncio.get_running_loop()
        while True:
            key, work = await self._queue.get()
            delay = 0.25
            while True:
                try:
                    await loop.run_in_executor(self._pool, work)
                    self.error = ""
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self.error = str(error)[:160]
                    await asyncio.sleep(delay)
                    delay = min(5.0, delay * 2)
            with self._lock:
                self._pending.discard(key)
            self._queue.task_done()

    async def drain(self):
        if self._enqueuers:
            await asyncio.gather(*tuple(self._enqueuers))
        if self._queue is not None:
            await self._queue.join()

    async def close(self):
        await self.drain()
        if self._consumer:
            self._consumer.cancel()
            try:
                await self._consumer
            except asyncio.CancelledError:
                pass
        self._pool.shutdown(wait=False)
