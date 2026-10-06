"""[sfx-reach] IS THE SFX COLLECTION THERE? One question, asked carefully.

"When I plug it up to the spark, I want the database work to continue and
for it to plug back up seamlessly into the system ... In the intermission,
I want it playing H3 / Supercuts if it finds it has issues getting to the
clips or accessing the SFX collection."          - the operator, 2026-10-06

The collection lives on a CIFS share (today the NAS; soon a drive on the
Spark). Two things this station learned about that share the hard way
(memory: "a CIFS walk ate the thread pool", "the stat that went deaf"):

  - ONE os.stat() on a dead mount can block for minutes, and a stat on the
    event loop is dead air; a stat on the shared worker pool is a worker
    gone until the mount answers;
  - a dead share asked by twenty roads at once is twenty hung threads.

So the question is asked HERE and nowhere else: one os.stat() of
<root>/samples_grabbed and one listdir of it, on a daemon thread of its own,
bounded by PROBE_TIMEOUT_S, at most one in flight, the answer memoised
MEMO_S. Everything that wants to know reads the memo (`reachable()`, never
blocks); a stale memo kicks the next probe without waiting for it.

THE POLICY. The collection is REACHABLE when a probe answers inside the
timeout. A probe that fails, or answers late, makes it UNREACHABLE: a share
that takes four seconds to answer a stat is, for this station, a share that
is away - every draw against it would be the stall the two memories above
describe. An EMPTY samples_grabbed is unreachable too: that is what the
folder under an unmounted path, or a stale Docker bind, looks like.
Transitions are logged ONCE each way through the station's pipeline log.

Pure where it can be: no station imports, the clock, the stat and the
listdir are injectable, so the probe is testable with a stat that hangs.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

PROBE_TIMEOUT_S = float(os.getenv("SFX_REACH_TIMEOUT_S", "3"))
MEMO_S = float(os.getenv("SFX_REACH_MEMO_S", "20"))
PROBE_DIR = "samples_grabbed"
INTERMISSION_SAY = "the intermission plays H3 renders and supercuts"


def _hhmm(at: float) -> str:
    try:
        return time.strftime("%H:%M", time.localtime(float(at)))
    except (TypeError, ValueError, OSError, OverflowError):
        return "?"


class Reach:
    """The reachability of one root. One instance per collection."""

    def __init__(self, root: Any = None, timeout: float = PROBE_TIMEOUT_S, memo: float = MEMO_S,
                 stat: Callable[[str], Any] = os.stat, listdir: Callable[[str], Any] = os.listdir,
                 clock: Callable[[], float] = time.time, log: Callable[[str], Any] | None = None) -> None:
        self.root: Path | None = Path(str(root)) if root else None
        self.timeout = float(timeout)
        self.memo = float(memo)
        self._stat = stat
        self._listdir = listdir
        self._clock = clock
        self._log = log
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._thread_at = 0.0
        self._job = 0
        self._state: dict[str, Any] = {
            "reachable": True, "known": False, "since": 0.0, "last_ok": 0.0,
            "last_error": "", "probes": 0, "timeouts": 0, "outages": 0,
            "checked_at": 0.0, "probe_ms": 0.0, "stood_down": {}, "deferred": 0,
        }
        self._said: set[str] = set()          # roads logged this outage

    # ------------------------------------------------------------ settings

    def configure(self, root: Any = None, log: Callable[[str], Any] | None = None,
                  timeout: float | None = None, memo: float | None = None,
                  stat: Callable[[str], Any] | None = None, listdir: Callable[[str], Any] | None = None,
                  clock: Callable[[], float] | None = None) -> "Reach":
        with self._lock:
            if root is not None:
                self.root = Path(str(root))
            if log is not None:
                self._log = log
            if timeout is not None:
                self.timeout = float(timeout)
            if memo is not None:
                self.memo = float(memo)
            if stat is not None:
                self._stat = stat
            if listdir is not None:
                self._listdir = listdir
            if clock is not None:
                self._clock = clock
        return self

    # -------------------------------------------------------------- reading

    def state(self) -> dict[str, Any]:
        with self._lock:
            out = dict(self._state)
            out["stood_down"] = dict(self._state["stood_down"])
            out["root"] = str(self.root) if self.root else ""
            out["timeout_s"] = self.timeout
            out["memo_s"] = self.memo
            out["in_flight"] = bool(self._thread is not None and self._thread.is_alive())
            now = self._clock()
            out["age_s"] = round(max(0.0, now - float(out["checked_at"] or now)), 1) if out["known"] else None
            if not out["reachable"] and out["since"]:
                out["away_s"] = round(max(0.0, now - float(out["since"])), 1)
            out["say"] = self.say()
            return out

    def say(self) -> str:
        with self._lock:
            st = self._state
            if not self.root:
                return "no SFX collection root is configured"
            if not st["known"]:
                return "the SFX collection has not been probed yet"
            if st["reachable"]:
                return "the SFX collection is reachable (probe %.0f ms)" % float(st["probe_ms"] or 0)
            away = max(0.0, self._clock() - float(st["since"] or self._clock()))
            return ("INTERMISSION: the SFX collection is unreachable since %s (%d min) - %s%s"
                    % (_hhmm(st["since"]), int(away // 60), INTERMISSION_SAY,
                       (" - " + str(st["last_error"])[:120]) if st.get("last_error") else ""))

    def reachable(self) -> bool:
        """The memo's answer, never a wait. A stale memo starts the next probe
        on its own thread; a probe that has hung past the timeout counts as
        a miss at once, so a dead share is seen inside timeout + memo."""
        if not self.root:
            return True
        with self._lock:
            now = self._clock()
            if self._thread is not None and self._thread.is_alive():
                if now - self._thread_at > self.timeout and self._state["checked_at"] < self._thread_at:
                    self._timeout_settle(now)
            elif not self._fresh(now):
                self._start(now)
            return bool(self._state["reachable"])

    def probe(self, force: bool = False) -> dict[str, Any]:
        """A fresh answer, waited for up to the timeout. BLOCKING - a worker's
        or a test's, never the event loop's."""
        if not self.root:
            return self.state()
        with self._lock:
            now = self._clock()
            if self._fresh(now) and not force:
                return self.state()
            t = self._start(now)
            started = self._thread_at
        t.join(self.timeout)
        if t.is_alive():
            with self._lock:
                if self._state["checked_at"] < started:
                    self._timeout_settle(self._clock())
        return self.state()

    # ------------------------------------------------------------- helpers

    def under(self, path: Any) -> bool:
        """Is this path inside the collection? A string test only: a path
        under a dead mount must never be touched to answer that."""
        if not self.root or path is None:
            return False
        root = str(self.root).replace("\\", "/").rstrip("/")
        text = str(path).replace("\\", "/")
        return text == root or text.startswith(root + "/")

    def narrow(self, paths: Any) -> list[Any]:
        """The paths that are NOT the collection's - the station's own shelf."""
        return [p for p in (paths or []) if not self.under(p)]

    def stood_down(self, road: str) -> int:
        """A road declined to touch the share: counted per road, said once per
        road per outage."""
        road = str(road or "road")[:40]
        with self._lock:
            n = int(self._state["stood_down"].get(road) or 0) + 1
            self._state["stood_down"][road] = n
            first = road not in self._said
            self._said.add(road)
        if first and not self._state["reachable"]:
            self._say("[sfx-reach] %s stands down while the SFX collection is unreachable - it resumes when the share answers" % road)
        return n

    def defer(self) -> int:
        with self._lock:
            self._state["deferred"] = int(self._state["deferred"]) + 1
            return int(self._state["deferred"])

    # ------------------------------------------------------------ the probe

    def _fresh(self, now: float) -> bool:
        st = self._state
        return bool(st["known"] and now - float(st["checked_at"]) < self.memo)

    def _start(self, now: float) -> threading.Thread:
        """The thread in flight, or a new one. Lock held by the caller."""
        if self._thread is not None and self._thread.is_alive():
            return self._thread
        self._job += 1
        job = self._job
        t = threading.Thread(target=self._run, args=(job,), name="sfx-reach-probe", daemon=True)
        self._thread = t
        self._thread_at = now
        t.start()
        return t

    def _run(self, job: int) -> None:
        root = self.root
        if root is None:
            return
        target = str(root / PROBE_DIR)
        t0 = self._clock()
        ok, err = False, ""
        try:
            self._stat(target)
            names = self._listdir(target)
            if not names:
                err = "%s is empty - not mounted, or a bind under a later mount" % target
            else:
                ok = True
        except Exception as exc:  # noqa: BLE001 - the error IS the answer
            err = "%s: %s" % (type(exc).__name__, str(exc)[:140])
        elapsed = max(0.0, self._clock() - t0)
        with self._lock:
            if job != self._job:
                return                       # superseded (a reconfigure); its answer is nobody's
            self._settle(ok, err, elapsed)

    def _settle(self, ok: bool, err: str, elapsed: float) -> None:
        """Lock held. A late answer is a miss: the share is there but not for this station."""
        now = self._clock()
        st = self._state
        st["probes"] = int(st["probes"]) + 1
        st["checked_at"] = now
        st["probe_ms"] = round(elapsed * 1000.0, 1)
        late = elapsed > self.timeout
        if ok and not late:
            st["last_ok"] = now
            st["last_error"] = ""
            self._flip(True, now)
        else:
            if ok and late:
                err = "answered after %.1f s (the limit is %.1f s)" % (elapsed, self.timeout)
            st["last_error"] = str(err)[:200]
            self._flip(False, now)

    def _timeout_settle(self, now: float) -> None:
        """Lock held. The thread is still out there: that is the answer for now."""
        st = self._state
        st["timeouts"] = int(st["timeouts"]) + 1
        st["checked_at"] = now
        st["last_error"] = "the probe did not answer in %.1f s" % self.timeout
        self._flip(False, now)

    def _flip(self, reachable: bool, now: float) -> None:
        st = self._state
        was_known = bool(st["known"])
        was = bool(st["reachable"])
        st["known"] = True
        if was_known and was == reachable:
            return
        if not was_known and reachable:
            st["reachable"] = True
            st["since"] = now
            return                           # a quiet start: the share is simply there
        st["reachable"] = reachable
        if reachable:
            away = max(0.0, now - float(st["since"] or now))
            st["since"] = now
            self._said.clear()
            self._say("the SFX collection is back after %d min - the set returns to the book, the keepers resume"
                      % int(round(away / 60.0)))
        else:
            st["since"] = now
            st["outages"] = int(st["outages"]) + 1
            self._said.clear()
            self._say("the SFX collection is unreachable since %s - %s (%s)"
                      % (_hhmm(now), INTERMISSION_SAY, str(st.get("last_error") or "")[:120]))

    def _say(self, text: str) -> None:
        log = self._log
        if log is None:
            return
        try:
            log(text)
        except Exception:  # noqa: BLE001 - a log that fails must not fail the probe
            pass


# ---------------------------------------------------------------- the station's one

REACH = Reach()


def configure(**kw: Any) -> Reach:
    return REACH.configure(**kw)


def probe(force: bool = False) -> dict[str, Any]:
    return REACH.probe(force)


def reachable() -> bool:
    return REACH.reachable()


def state() -> dict[str, Any]:
    return REACH.state()


def say() -> str:
    return REACH.say()


def under(path: Any) -> bool:
    return REACH.under(path)


def narrow(paths: Any) -> list[Any]:
    return REACH.narrow(paths)


def stood_down(road: str) -> int:
    return REACH.stood_down(road)


def defer() -> int:
    return REACH.defer()
