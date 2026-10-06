"""Keep slow shelf reads and repeated repair work away from live playout."""
from concurrent.futures import ThreadPoolExecutor
import copy
import threading
import time


class ShelfSnapshots:
    """At most one refresh per shelf, on a bounded pool; readers never wait."""
    def __init__(self, workers=2, clock=time.monotonic):
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="station-shelf")
        self.clock = clock
        self.lock = threading.RLock()
        self.rows = {}

    def get(self, key, loader, ttl=30, default=None):
        with self.lock:
            row = self.rows.setdefault(key, {"value": default, "at": -float("inf"), "pending": False})
            value = row["value"]
            if not row["pending"] and self.clock() - row["at"] >= ttl:
                row["pending"] = True
                self.pool.submit(self._refresh, key, loader)
            # Lists/dictionaries are replaced atomically by the loader. Caller
            # mutations must not edit the shared snapshot.
            return copy.copy(value)

    def _refresh(self, key, loader):
        try:
            value = loader()
        except Exception:
            with self.lock:
                row = self.rows[key]
                row.update(at=self.clock(), pending=False)
            return
        with self.lock:
            self.rows[key].update(value=value, at=self.clock(), pending=False)

    def close(self):
        self.pool.shutdown(wait=True)


SHELVES = ShelfSnapshots()


def recovery_yield(reserve_seconds, writer_busy, jobs=(), banter_ready=None):
    """A thin reserve belongs to fresh writing; repair can use idle capacity."""
    fresh = writer_busy or any(j.get("category") == "station" and j.get("state") in ("active", "waiting") for j in jobs)
    return fresh and (float(reserve_seconds or 0) < 90 or banter_ready is False)


def segment_budget(requested, caller=False, whole=False):
    """Size a new linked segment before planning; never truncate final words."""
    requested = max(2, int(requested or 0))
    if caller or whole:
        return requested
    return min(requested, 6)
