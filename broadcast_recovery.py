"""Listener progress and conservative automatic broadcast recovery decisions.

No disk, station imports, or clocks: callers provide an observed server time.
A browser saying ``playing`` is not evidence that its media position advanced.
"""
from __future__ import annotations

from collections import OrderedDict
import asyncio
import math


class RecoveryJobs:
    """Keep bounded repair requests from cancelling or duplicating production."""

    def __init__(self):
        self.tasks = {}

    async def run(self, key, factory, timeout):
        task = self.tasks.get(key)
        if task is None or task.done():
            task = asyncio.create_task(factory())
            self.tasks[key] = task

            def finished(done):
                if self.tasks.get(key) is done:
                    self.tasks.pop(key, None)
                # A timed-out caller may never return; retrieve failures so a
                # failed background repair cannot become an unhandled task.
                if not done.cancelled():
                    done.exception()

            task.add_done_callback(finished)
        try:
            return True, await asyncio.wait_for(asyncio.shield(task), timeout)
        except asyncio.TimeoutError as exc:
            if task.done():
                # A producer's own timeout is a failed job, whereas our
                # response deadline leaves a live producer to finish.
                try:
                    return True, task.result()
                except asyncio.TimeoutError:
                    raise RuntimeError("%s recovery production timed out" % key) from exc
            return False, None

    def pending(self):
        return [key for key, task in self.tasks.items() if not task.done()]


class AudioProgress:
    def __init__(self, limit: int = 512):
        self.samples = OrderedDict()
        self.limit = limit
        self.last_heard = 0.0
        self.last_speech = 0.0
        self.first_audible_report = 0.0

    def observe(self, *, listener: str, source: str, media: str, position: float,
                sequence: int, at: float, audible: float, playing: bool,
                speech: bool = False, monitor: bool = False) -> bool:
        values = (position, at, audible)
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("non-finite audio progress")
        key = (listener, source)
        previous = self.samples.get(key) or {}
        if sequence and sequence <= int(previous.get("sequence") or 0):
            return False
        # A new file/session, a seek, or a first sample establishes a baseline.
        # Only a subsequent moving position proves sound is still advancing.
        progressed = bool(playing and audible > 0 and previous
                          and previous.get("media") == media
                          and previous.get("playing")
                          and 0 <= at - previous["at"] <= 15
                          and position > previous["position"] + 0.02)
        same_media = previous.get("media") == media
        expected_since = float(previous.get("expected_since") or at) if (
            same_media and previous.get("playing") and previous.get("audible", 0) > 0
        ) else at
        sample = {"media": media, "position": position, "sequence": sequence,
                  "at": at, "audible": audible, "playing": bool(playing),
                  "monitor": bool(monitor), "expected_since": expected_since,
                  "progress_at": at if progressed else float(
                      previous.get("progress_at") or 0) if same_media else 0.0}
        if playing and audible > 0 and not self.first_audible_report:
            self.first_audible_report = at
        self.samples[key] = sample
        self.samples.move_to_end(key)
        while len(self.samples) > self.limit:
            self.samples.popitem(last=False)
        if progressed:
            self.last_heard = max(self.last_heard, at)
            if speech:
                self.last_speech = max(self.last_speech, at)
        return progressed

    def snapshot(self, now: float) -> dict:
        monitored = [r for r in self.samples.values()
                     if r["monitor"] and 0 <= now - r["at"] <= 15]
        active = [r for r in monitored if r["playing"] and r["audible"] > 0]
        # Fresh heartbeats at one unchanged audible position are a real wedge.
        # An old/disconnected client and an intentionally paused/muted one aren't.
        frozen = [r for r in active
                  if now - max(r["progress_at"], r["expected_since"]) >= 90]
        quiet_from = self.last_heard or self.first_audible_report
        return {"last_heard": self.last_heard,
                "quiet": max(0, now - quiet_from) if quiet_from else -1.0,
                "reporting": len(monitored), "active_receivers": len(active),
                "intentional_silence": bool(monitored and not active),
                "media_stalled": bool(frozen and len(frozen) == len(active))}


def recovery_gate(e: dict) -> dict:
    """Permit disruption only for a silent, listening, demonstrably wedged mix."""
    quiet = float(e.get("quiet", -1))
    reason = ""
    if e.get("paused") or e.get("on") is False:
        reason = "the station is paused or off"
    elif quiet < 0:
        reason = "no audible progress has been observed yet"
    elif quiet < 90:
        reason = "audible broadcast media is still advancing"
    elif int(e.get("listeners") or 0) <= 0:
        reason = "there are no current listeners"
    elif e.get("intentional_silence"):
        reason = "the reporting receivers are paused or muted"
    elif int(e.get("future_waiting") or 0) and not int(e.get("waiting") or 0):
        reason = "accepted audio is waiting for its scheduled moment"
    confirmed = bool(e.get("page_wedged") or e.get("media_stalled"))
    return {"allow": not reason, "destructive": not reason and confirmed,
            "reason": reason, "max_rung": None if confirmed else 0}
