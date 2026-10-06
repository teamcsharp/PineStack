"""One-click station repair coordination, independent of the station application.

Callbacks retain ownership of service repairs and System 3's bounded, durable
recovery queue.  This coordinator never changes a conversation or records a
queue admission as proof that a listener heard dialogue.
"""
from __future__ import annotations

import asyncio
import copy
import inspect
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable
import uuid


class StationTroubleshooter:
    """Run diagnosed repairs and follow real dialogue playback evidence.

    ``diagnose()`` returns a report with optional ``actions``: dictionaries
    containing ``step``, ``reason``, and ``restart``. Only these diagnosed
    completed actions are executed once. Deferred/failed actions may retry
    within a bounded budget. ``repair(step)`` owns the actual repair.
    ``request_recovery(job_id)`` admits failed drafts to the existing recovery
    worker and may wake it; it must preserve that worker's pass/cooldown rules.
    ``observe()`` returns ``heard_at``, ``ready``, ``pending``, optional
    ``blocked``/``reasons``, ``next_retry_at``, and ``automatic_recovery``.
    Callbacks can be synchronous or asynchronous.

    Set ``persist_path`` inside the station's data directory. Call
    ``resume_pending()`` after startup to resume an interrupted verification.
    A restart checkpoint is saved before the corresponding callback runs.
    """

    def __init__(self, *, diagnose: Callable, repair: Callable,
                 request_recovery: Callable, observe: Callable,
                 persist_path: Path | str | None = None,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable = asyncio.sleep,
                 verify_seconds: float = 180.0, poll_seconds: float = 4.0,
                 callback_timeout: float = 90.0, max_actions: int = 4,
                 persistence_timeout: float = 10.0, sustain_seconds: float = 0.0,
                 minimum_receipts: int = 1, max_quiet_seconds: float = 30.0,
                 rediagnose_seconds: float = 30.0,
                 repair_retry_seconds: float = 30.0, repair_attempts: int = 3) -> None:
        self.diagnose = diagnose
        self.repair = repair
        self.request_recovery = request_recovery
        self.observe = observe
        self.persist_path = Path(persist_path) if persist_path is not None else None
        self.clock = clock
        self.sleep = sleep
        self.verify_seconds = max(0.0, float(verify_seconds))
        self.poll_seconds = max(0.01, float(poll_seconds))
        self.callback_timeout = max(0.01, float(callback_timeout))
        self.max_actions = max(0, int(max_actions))
        self.persistence_timeout = max(0.01, float(persistence_timeout))
        self.sustain_seconds = max(0.0, float(sustain_seconds))
        self.minimum_receipts = max(1, int(minimum_receipts))
        self.max_quiet_seconds = max(1.0, float(max_quiet_seconds))
        self.rediagnose_seconds = max(self.poll_seconds, float(rediagnose_seconds))
        self.repair_retry_seconds = max(self.poll_seconds, float(repair_retry_seconds))
        self.repair_attempts = max(1, int(repair_attempts))
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._persist_task: asyncio.Task | None = None
        self._persist_revision = 0
        self._persist_written_revision = 0
        self._persist_error: str | None = None
        self._load()

    def _load(self) -> None:
        if self.persist_path is None:
            return
        try:
            data = json.loads(self.persist_path.read_text(encoding="utf-8"))
            for row in data.get("jobs", [])[-16:]:
                if isinstance(row, dict) and row.get("id") and row.get("started_at"):
                    self._jobs[str(row["id"])] = row
        except (OSError, ValueError, TypeError, AttributeError):
            # An unreadable old report does not disable station recovery.
            return

    def _save(self) -> None:
        """Coalesce writes without making the broadcast loop wait for disk."""
        if self.persist_path is None:
            return
        with self._lock:
            self._persist_revision += 1
            self._schedule_persistence()

    def _schedule_persistence(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._persist_task is None or self._persist_task.done():
            self._persist_task = loop.create_task(self._persist_loop())

    def _write_snapshot(self, data: dict) -> None:
        """Runs on a worker thread; the data directory may be a slow share."""
        path = self.persist_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    async def _persist_loop(self) -> None:
        while True:
            with self._lock:
                revision = self._persist_revision
                if self._persist_written_revision >= revision:
                    return
                data = {"version": 1,
                        "jobs": copy.deepcopy(list(self._jobs.values())[-16:])}
            try:
                await asyncio.to_thread(self._write_snapshot, data)
            except Exception as exc:
                with self._lock:
                    self._persist_error = str(exc)
                return
            with self._lock:
                self._persist_written_revision = revision
                self._persist_error = None

    async def flush(self) -> None:
        """Require the current checkpoint to reach disk before a restart."""
        if self.persist_path is None:
            return
        with self._lock:
            revision = self._persist_revision
            self._schedule_persistence()
            task = self._persist_task
        if task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(task), self.persistence_timeout)
            except TimeoutError as exc:
                raise RuntimeError("the station recovery checkpoint timed out") from exc
        with self._lock:
            if self._persist_written_revision < revision:
                raise RuntimeError("the station recovery checkpoint could not be saved: "
                                   + str(self._persist_error or "write incomplete"))

    def _update(self, job: dict, **fields: Any) -> None:
        with self._lock:
            job.update(fields)
            job["updated_at"] = self.clock()
            self._save()

    def _note(self, job: dict, phase: str, text: str, **fields: Any) -> None:
        with self._lock:
            job.setdefault("transcript", []).append(
                {"at": self.clock(), "phase": phase, "text": str(text), **fields})
            job["transcript"] = job["transcript"][-100:]
            self._update(job, phase=phase)

    def status(self, job_id: str | None = None) -> dict:
        with self._lock:
            job = (self._jobs.get(str(job_id)) if job_id is not None
                   else next(reversed(self._jobs.values()), None))
            return copy.deepcopy(job) if job else {"status": "idle", "running": False}

    def start(self, *, allow_restarts: bool = True) -> dict:
        loop = asyncio.get_running_loop()
        with self._lock:
            for job in reversed(list(self._jobs.values())):
                task = self._tasks.get(job["id"])
                if task is not None and not task.done():
                    return copy.deepcopy(job)
            # Interrupted persisted jobs are continued instead of starting
            # another set of repairs or spending another model pass.
            unfinished = next((j for j in reversed(list(self._jobs.values()))
                               if j.get("running")), None)
            if unfinished is not None:
                self._tasks[unfinished["id"]] = loop.create_task(
                    self._run(unfinished, resumed=True))
                return copy.deepcopy(unfinished)
            now = self.clock()
            job = {"id": uuid.uuid4().hex, "status": "running", "running": True,
                   "phase": "diagnosing", "started_at": now, "updated_at": now,
                   "allow_restarts": bool(allow_restarts), "transcript": [],
                   "completed_actions": [], "attempted_actions": [], "recovery_requested": False,
                   "verified": False, "changed": False}
            self._jobs[job["id"]] = job
            if len(self._jobs) > 16:
                self._jobs.pop(next(iter(self._jobs)))
            self._save()
            self._tasks[job["id"]] = loop.create_task(self._run(job))
            return copy.deepcopy(job)

    def resume_pending(self) -> list[dict]:
        """Continue persisted interrupted work after station startup."""
        loop = asyncio.get_running_loop()
        resumed = []
        with self._lock:
            for job in self._jobs.values():
                task = self._tasks.get(job["id"])
                if job.get("running") and (task is None or task.done()):
                    self._tasks[job["id"]] = loop.create_task(self._run(job, resumed=True))
                    resumed.append(copy.deepcopy(job))
        return resumed

    async def wait(self, job_id: str) -> dict:
        """Useful for tests and callers that explicitly need a final report."""
        task = self._tasks.get(str(job_id))
        if task is not None:
            await asyncio.shield(task)
        try:
            await self.flush()
        except RuntimeError as exc:
            job = self._jobs.get(str(job_id))
            if job is not None:
                self._update(job, persistence_error=str(exc))
        return self.status(job_id)

    async def _call(self, callback: Callable, *args: Any) -> dict:
        value = callback(*args)
        if inspect.isawaitable(value):
            value = await asyncio.wait_for(value, self.callback_timeout)
        if not isinstance(value, dict):
            raise TypeError("station troubleshooting callbacks must return a report")
        return value

    @staticmethod
    def _view(observed: dict) -> dict:
        fields = ("heard_at", "ready", "pending", "blocked", "reasons",
                  "next_retry_at", "automatic_recovery", "writer_busy",
                  "recording_busy", "cause", "why", "recovery", "held_source",
                  "oldest_pending_seconds", "banter_ready", "speech_quiet_seconds")
        fields += ("production_health", "maintenance", "page_speech_active",
                   "page_reserved_seconds", "listeners_present", "unheard_ready",
                   "incomplete_recordings", "reserve_target", "voice_feed_health")
        return {key: copy.deepcopy(observed[key]) for key in fields if key in observed}

    @staticmethod
    def _number(value: Any) -> float:
        try:
            return float(value or 0)
        except (ValueError, TypeError):
            return 0.0

    async def _repair_actions(self, job: dict, diagnosis: dict) -> None:
        actions = diagnosis.get("actions") or []
        seen: set[str] = set(job.get("attempted_actions") or job.get("completed_actions") or [])
        states = job.setdefault("action_results", {})
        for action in actions:
            if not isinstance(action, dict):
                continue
            step = str(action.get("step") or "").strip()
            state = states.get(step) or {}
            if not step or step in job.get("completed_actions", []):
                continue
            # A saved intent without an outcome may already have restarted a
            # service. Never repeat it after an interruption without evidence.
            if step in seen and not state.get("retryable"):
                continue
            if state.get("attempts", 0) >= self.repair_attempts or self.clock() < state.get("retry_at", 0):
                continue
            if step not in seen and len(seen) >= self.max_actions:
                self._note(job, "repairing", "Additional diagnosed repairs remain for the existing station worker.")
                break
            if action.get("restart") and not job["allow_restarts"]:
                self._note(job, "repairing", "A diagnosed service restart was deferred by the selected setting.", step=step)
                continue
            seen.add(step)
            state = {"attempts": int(state.get("attempts", 0)) + 1, "retryable": False}
            states[step] = state
            reason = str(action.get("reason") or "The diagnosis requires this repair.")
            # Save intent before a service restart can end this process.
            self._update(job, attempted_actions=list(seen),
                         restart_checkpoint=(step if action.get("restart") else None))
            self._note(job, "repairing", reason, step=step)
            if action.get("restart"):
                # Never restart a service without a durable record of the
                # attempt: otherwise startup could restart it repeatedly.
                if self.persist_path is None:
                    raise RuntimeError("persistent job storage is required before a service restart")
                await self.flush()
            try:
                result = await self._call(self.repair, step)
                finished = bool(result.get("ok") and not result.get("pending"))
                state.update(retryable=not finished, retry_at=self.clock() + self.repair_retry_seconds,
                             ok=bool(result.get("ok")), pending=bool(result.get("pending")))
                done = list(job["completed_actions"]) + ([step] if finished else [])
                self._update(job, completed_actions=done,
                             changed=job["changed"] or bool(result.get("changed")),
                             restart_checkpoint=None)
                lines = result.get("lines") or []
                self._note(job, "repairing", str(result.get("why")
                                                 or ("; ".join(map(str, lines[-8:])))
                                                 or ("Repair completed." if result.get("ok")
                                                     else "Repair remains unresolved.")),
                           step=step, ok=bool(result.get("ok")))
            except Exception as exc:
                state.update(retryable=True, retry_at=self.clock() + self.repair_retry_seconds,
                             error=type(exc).__name__)
                self._note(job, "repairing", "The diagnosed repair could not finish: " + str(exc), step=step)

    async def _run(self, job: dict, *, resumed: bool = False) -> None:
        try:
            if resumed:
                self._note(job, "resuming", "Resuming the saved station check after interruption.")
            self._note(job, "diagnosing", "Checking dialogue production, delivery, and affected services.")
            diagnosis = await self._call(self.diagnose)
            self._update(job, diagnosis=self._view(diagnosis))
            self._note(job, "diagnosing", str(diagnosis.get("why")
                                             or diagnosis.get("cause")
                                             or "Station diagnosis completed."))
            if diagnosis.get("blocked"):
                reasons = diagnosis["blocked"]
                if isinstance(reasons, str):
                    reasons = [reasons]
                report = "; ".join(str(reason) for reason in reasons[:6])
                self._note(job, "blocked", report)
                self._update(job, status="blocked", running=False, verified=False,
                             observation=self._view(diagnosis), finished_at=self.clock(), report=report)
                return
            await self._repair_actions(job, diagnosis)
            if not job.get("recovery_requested"):
                self._note(job, "recovering", "Admitting rejected drafts to repair, rewrite, reroll, and rebuild under the existing retry limits.")
                try:
                    result = await self._call(self.request_recovery, job["id"])
                except Exception as exc:
                    # A broken writer must not prevent delivery verification
                    # or the independent follow-up repair ladder.
                    result = {"ok": False, "why": "Draft recovery could not finish: " + str(exc)}
                    self._update(job, recovery_error=type(exc).__name__)
                # Repeated request after an interrupted callback is safe: the
                # owning queue deduplicates drafts, not the troubleshooting job.
                self._update(job, recovery_requested=True, recovery_request=self._view(result),
                             changed=job["changed"] or bool(result.get("changed")))
                self._note(job, "recovering", str(result.get("why")
                                                 or "The recovery worker has been requested; playback is still being checked."))
            self._update(job, verify_deadline=self.clock() + self.verify_seconds)
            receipts = []
            next_diagnosis = self.clock() + self.rediagnose_seconds
            baseline_pending = self._number(diagnosis.get("pending"))
            self._note(job, "verifying", "Checking sustained DJ speech delivery; queued words and a single playback receipt do not prove sustained flow." if self.sustain_seconds else "Waiting for a new DJ dialogue playback receipt; queued or prepared words are still pending.")
            max_polls = int(self.verify_seconds / self.poll_seconds) + 2
            for _ in range(max_polls):
                observed = await self._call(self.observe)
                view = self._view(observed)
                self._update(job, observation=view)
                heard = self._number(observed.get("heard_at"))
                now = self.clock()
                if receipts and now - heard > self.max_quiet_seconds:
                    receipts = []
                if heard > float(job["started_at"]) and (not receipts or heard > receipts[-1]):
                    receipts.append(heard)
                sustained = bool(receipts and now - receipts[0] >= self.sustain_seconds
                                 and now - heard <= self.max_quiet_seconds
                                 and len(receipts) >= self.minimum_receipts)
                if not self.sustain_seconds:
                    sustained = heard > float(job["started_at"])
                self._update(job, flow_proof={"receipts": len(receipts), "window_seconds": round(max(0, now - receipts[0]), 1) if receipts else 0,
                                             "required_seconds": self.sustain_seconds, "pending_at_start": baseline_pending,
                                             "pending_now": observed.get("pending", 0)})
                if sustained:
                    production = observed.get("production_health") or {}
                    pending = self._number(observed.get("pending"))
                    degraded = bool(pending or production.get("state") == "degraded" or job.get("recovery_error"))
                    report = "Sustained DJ dialogue playback is verified." if self.sustain_seconds else "DJ dialogue playback is verified."
                    if degraded:
                        report += " Production still needs repair: %d draft(s) remain; reserve and recording maintenance continue independently." % pending
                    self._note(job, "complete", "Sustained DJ speech playback was verified." if self.sustain_seconds else "New DJ dialogue playback was verified after this check started.")
                    self._update(job, status="success", running=False, verified=True,
                                 playback_status="verified", production_status="pending" if degraded else "healthy",
                                 finished_at=self.clock(), report=report)
                    return
                if self.clock() >= float(job["verify_deadline"]):
                    break
                if now >= next_diagnosis and now - heard > self.max_quiet_seconds:
                    self._note(job, "diagnosing", "Speech is still absent; checking for newly diagnosable delivery or service faults.")
                    refreshed = await self._call(self.diagnose)
                    self._update(job, diagnosis=self._view(refreshed))
                    await self._repair_actions(job, refreshed)
                    next_diagnosis = self.clock() + self.rediagnose_seconds
                    self._note(job, "verifying", "Continuing the same saved check after the follow-up diagnosis.")
                await self.sleep(min(self.poll_seconds,
                                     max(0.0, float(job["verify_deadline"]) - self.clock())))
            observed = job.get("observation") or {}
            pending = self._number(observed.get("pending")) > 0
            ready = self._number(observed.get("ready")) > 0
            automatic = bool(observed.get("automatic_recovery"))
            reasons = observed.get("blocked") or observed.get("reasons") or []
            if isinstance(reasons, str):
                reasons = [reasons]
            if ready:
                report = "Dialogue is prepared; new DJ playback has not been verified yet."
            elif pending or automatic:
                report = "Dialogue recovery is still pending; eligible retries continue in the station worker."
            else:
                report = "New DJ playback could not be verified; the remaining diagnosis needs attention."
            if reasons:
                report += " " + "; ".join(str(reason) for reason in reasons[:6])
            if self._number(observed.get("next_retry_at")) > self.clock():
                report += " The next recovery variation is waiting for its cooldown."
            self._note(job, "pending" if (pending or ready or automatic) else "blocked", report)
            self._update(job, status="pending" if (pending or ready or automatic) else "blocked",
                         running=False, verified=False, finished_at=self.clock(), report=report)
        except asyncio.CancelledError:
            # Persist running=True so an ordinary service restart can resume.
            self._note(job, "interrupted", "The station check was interrupted and will resume on startup.")
            raise
        except Exception as exc:
            report = "Station troubleshooting could not finish: " + str(exc)
            self._note(job, "blocked", report)
            self._update(job, status="blocked", running=False, verified=False,
                         finished_at=self.clock(), report=report)
