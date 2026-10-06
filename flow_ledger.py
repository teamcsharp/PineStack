"""[s3-flow-open] The flow ledger: every wedge that asked System 3 instead of
refusing, in one place.

"If the rejection system is off, why is there still rejection occurring? I want
to be able to see and approve each and every rejection." (the operator, #1570,
2026-10-05)

The content gates (the "rejection system") were off, and lines were still being
refused by wedges those switches never covered: a final handoff that could not
shape a round, a conversation the booth called incomplete, a recovery draft
held for a rewrite. Each of those now asks System 3 (app.s3_flow), and each
answer - passed or held, which wedge, why, on which road, the words - is a row
here: a ring in memory for the panel and a JSONL file for the record.

Pure: no station imports. A note() is a list append under a lock; the file is
written by one daemon thread, a few seconds behind, so nothing on the event
loop ever waits for the disk.
"""
from __future__ import annotations

import collections
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

ROTATE_BYTES = 16 * 1024 * 1024     # one generation is kept beside the live file
FLUSH_EVERY = 5.0


class Ledger:
    def __init__(self, path: Any, keep: int = 800, autoflush: bool = True) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._ring: collections.deque[dict[str, Any]] = collections.deque(maxlen=max(10, int(keep)))
        self._pending: list[dict[str, Any]] = []
        self._counts: dict[str, dict[str, Any]] = {}
        self._seq = 0
        self._thread: threading.Thread | None = None
        self._autoflush = bool(autoflush)

    # -- writes ---------------------------------------------------------------
    def note(self, gate: str, why: str = "", passed: bool = True, road: str = "",
             text: str = "", ref: str = "", at: float | None = None, who: str = "") -> dict[str, Any]:
        """One answer: `gate` asked, and the dialogue `passed` or was refused.
        `who` is the seat whose line it was, so an approval can say it in that voice."""
        now = float(at) if at else time.time()
        row = {"at": round(now, 3), "gate": str(gate)[:60], "passed": bool(passed),
               "why": " ".join(str(why or "").split())[:300], "road": str(road or "")[:40],
               "text": " ".join(str(text or "").split())[:600], "ref": str(ref or "")[:80]}
        if who:
            row["who"] = str(who)[:24]
        with self._lock:
            self._seq += 1
            row["n"] = self._seq
            self._ring.append(row)
            self._pending.append(row)
            c = self._counts.setdefault(row["gate"], {"passed": 0, "held": 0, "last_at": 0.0, "last_why": ""})
            c["passed" if row["passed"] else "held"] += 1
            c["last_at"], c["last_why"] = row["at"], row["why"]
            start = self._autoflush and self._thread is None
            if start:
                self._thread = threading.Thread(target=self._run, name="flow-ledger", daemon=True)
        if start:
            self._thread.start()
        return row

    def flush(self) -> int:
        """Write what is pending. Returns the rows written (0 on a disk error -
        they stay pending and the next pass tries again)."""
        with self._lock:
            rows, self._pending = self._pending, []
        if not rows:
            return 0
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                if self.path.stat().st_size > ROTATE_BYTES:
                    os.replace(self.path, self.path.with_suffix(self.path.suffix + ".1"))
            except OSError:
                pass
            with open(self.path, "a", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            return len(rows)
        except OSError:
            with self._lock:
                self._pending = rows + self._pending
                del self._pending[:-5000]           # a dead disk does not grow the process
            return 0

    def _run(self) -> None:
        while True:
            time.sleep(FLUSH_EVERY)
            try:
                self.flush()
            except Exception:  # noqa: BLE001 - the ledger never takes the station down
                pass

    # -- reads ----------------------------------------------------------------
    def recent(self, limit: int = 100, gate: str = "", passed: bool | None = None) -> list[dict[str, Any]]:
        """The latest rows, newest first, optionally one wedge or one answer."""
        with self._lock:
            rows = list(self._ring)
        out = []
        for row in reversed(rows):
            if gate and row["gate"] != gate:
                continue
            if passed is not None and row["passed"] != bool(passed):
                continue
            out.append(dict(row))
            if len(out) >= max(1, int(limit)):
                break
        return out

    def find(self, n: int) -> dict[str, Any] | None:
        """The row numbered `n`, while the ring still holds it (a copy)."""
        with self._lock:
            for row in self._ring:
                if row.get("n") == int(n):
                    return dict(row)
        return None

    def mark(self, n: int, **fields: Any) -> dict[str, Any] | None:
        """Write the operator's decision onto row `n` (the ring and the file's next lines)."""
        with self._lock:
            for row in self._ring:
                if row.get("n") == int(n):
                    row.update(fields)
                    self._pending.append({"at": round(time.time(), 3), "n": row["n"], "gate": row["gate"],
                                          "decision": dict(fields)})
                    return dict(row)
        return None

    def counts(self) -> dict[str, dict[str, Any]]:
        """{wedge: {passed, held, last_at, last_why}} since the station started."""
        with self._lock:
            return {k: dict(v) for k, v in sorted(self._counts.items())}
