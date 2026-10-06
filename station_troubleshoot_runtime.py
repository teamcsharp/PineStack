"""Connect the one-click repair coordinator to the station's existing owners."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from station_troubleshoot import StationTroubleshooter
from dialogue_delivery_recovery import delivery_evidence, recover_dialogue_delivery
from station_json import voice_feed_health


class StationTroubleshootRuntime:
    def __init__(self, namespace: dict[str, Any]):
        self.ns = namespace
        self.manager = None
        self._loading = asyncio.Lock()
        self._last_automatic_at = 0.0
        self._last_maintenance_at = 0.0
        self._maintenance_lock = asyncio.Lock()
        self.maintenance_status = {"runs": 0, "last_error": ""}
        self._lifecycle_tasks = []
        self.watchdog_status = {"running": False, "last_error": ""}

    async def get_manager(self):
        async with self._loading:
            if self.manager is None:
                path = self.ns["data_path"]("station_troubleshoot.json")
                self.manager = await asyncio.to_thread(
                    StationTroubleshooter, diagnose=self.diagnose, repair=self.repair,
                    request_recovery=self.request_recovery, observe=self.observe,
                    persist_path=path, sustain_seconds=30, minimum_receipts=3,
                    max_quiet_seconds=30)
        return self.manager

    def _snapshot(self):
        n, now = self.ns, time.time()
        radio = n.get("_RADIO") or {}
        paused = bool(n["radio_paused"]())
        candidates = [("banter", entry) for entry in list(n.get("_LARDER") or [])]
        for kind, shelf in list((n.get("_SHELF") or {}).items()):
            if kind != "track_talk":
                candidates.extend((str(kind), row) for row in list(shelf))
        ready = sum(bool(n["dialogue_row_ready"](kind, row)) for kind, row in candidates)
        queued = list(n.get("_DIALOGUE_RECOVERY") or [])
        queued = [item for item in queued if n["row_unaired"](item.get("entry") or {})]
        reasons, waits, recovery = [], [], []
        for item in queued:
            state = (item.get("entry") or {}).get("dialogue_recovery") or {}
            wait = max(float(state.get("cooldown_until") or 0), float(item.get("ready_at") or 0))
            waits.append(wait)
            if state.get("last_reason"):
                reasons.append(str(state["last_reason"])[:300])
            recovery.append({"id": item.get("id"), "kind": item.get("kind"),
                             "operation": (state.get("current_attempt") or {}).get("operation"),
                             "pass": state.get("pass", 1), "attempt": state.get("attempt", 0),
                             "total_attempts": state.get("total_attempts", 0),
                             "style_level": state.get("style_level", 0), "next_retry_at": wait})
        status = n["tint_recovery_status"]()
        if status.get("why"):
            reasons.append(str(status["why"])[:300])
        booths = n["recording_booths"]()
        settings = n.get("dj_settings", lambda: {})()
        reserve_target = max(1, int(settings.get("dialogue_reserve_target") or 4))
        incomplete = n.get("cupboard_incomplete_rows", lambda: [])()
        owed_recordings = sum(self._recording_eligible(n, kind, row) for kind, row in incomplete)
        unheard_ready = sum(bool(n["row_unaired"](row) and n["dialogue_row_ready"](kind, row))
                            for kind, row in candidates)
        blocked = []
        if not radio.get("on"):
            blocked.append("The station is switched off. Start the station to hear dialogue.")
        elif paused:
            blocked.append("The station is paused. Resume it to hear dialogue.")
        workers = n.get("_RADIO_WORKERS") or {}
        worker = workers.get("tint_recovery") or {}
        task = worker.get("task")
        working = bool(task is not None and not task.done())
        gate = n.get("_OLLAMA_GATE")
        triage = n["broadcast_triangulate"]()
        return {**delivery_evidence(n, now), "silence_watchdog": dict(self.watchdog_status),
                "heard_at": float((n.get("_DIALOGUE_HEARD") or [0])[0] or 0),
                "ready": ready, "pending": len(queued), "blocked": blocked,
                "reserve_target": reserve_target, "unheard_ready": unheard_ready,
                "incomplete_recordings": owed_recordings, "maintenance": dict(self.maintenance_status),
                "voice_feed_health": voice_feed_health(),
                "banter_ready": sum(bool(n["dialogue_row_ready"]("banter", entry)) for entry in list(n.get("_LARDER") or [])),
                "oldest_pending_seconds": max((max(0, now - float(item.get("queued_at") or now)) for item in queued), default=0),
                "held_source": sum(bool(__import__("dialogue_recovery").needs_source((item.get("entry") or {}).get("dialogue_recovery") or {})) for item in queued),
                "speech_quiet_seconds": max(0, now - float((n.get("_DIALOGUE_HEARD") or [0])[0]
                    or float(n.get("_BUILD_MS") or now * 1000) / 1000)),
                "reasons": list(dict.fromkeys(reasons))[:8],
                "next_retry_at": min(waits) if waits and all(wait > now for wait in waits) else 0,
                "automatic_recovery": bool(radio.get("on") and working),
                "writer_busy": bool((n.get("_LARDER_WRITING") or [False])[0]
                                    or gate is not None and gate.locked()),
                "recording_busy": bool(booths.get("live") or booths.get("preparing")
                                       or any((booths.get("engines") or {}).values())),
                "cause": triage.get("cause"), "why": str(triage.get("why") or ""),
                "recovery": recovery[:12], "on": bool(radio.get("on")), "paused": paused,
                "render_waiting": len(n.get("_RENDER_BACKLOG") or []),
                "delivery_waiting": len(n.get("_BOX_HOLD") or []),
                "uptime": max(0, now - float(n.get("_BUILD_MS") or now * 1000) / 1000),
                "synth_tried": float((n.get("_SYNTH_TRIED") or [0])[0] or 0),
                "synth_done": float((n.get("_LAST_SYNTH") or [0])[0] or 0),
                "workers_present": len(workers), "cure": str(triage.get("cure") or "")}

    async def observe(self):
        # Stock readiness can stat media on the share. It never owns the loop.
        view = await asyncio.to_thread(self._snapshot)
        issues = []
        if view["banter_ready"] < view["reserve_target"]:
            issues.append("conversation_reserve_low")
        if view["pending"]:
            issues.append("draft_recovery_pending")
        if view["incomplete_recordings"]:
            issues.append("recordings_owed")
        if view["page_reserved_seconds"] > 180:
            issues.append("speech_queue_delayed")
        if view["voice_feed_health"]["state"] == "degraded":
            issues.append("voice_feed_encoding_fault")
        view["production_health"] = {"state": "degraded" if issues else "healthy", "issues": issues,
                                      "drafts_pending": view["pending"], "recordings_owed": view["incomplete_recordings"],
                                      "conversation_ready": view["banter_ready"], "conversation_target": view["reserve_target"]}
        # An old queued clip is expected while earlier speech advances. It
        # cannot justify a destructive reload or a claim of station silence.
        if view["page_speech_active"] and view["speech_quiet_seconds"] < 30:
            view.update(cause="healthy", why="DJ speech is advancing on a listening player.", cure="")
        return view

    @staticmethod
    def _recording_eligible(n, kind, row):
        entry = n.get("dialogue_entry", lambda r: r)(row) or row
        holders = (row, entry)
        # The manual finishing button can clear off-brief flags; automatic
        # maintenance must never do that or disturb a producer's active row.
        if any(h.get(k) for h in holders for k in
               ("off_brief", "review_cancel_pending", "preparing", "tinting", "handoff_unavailable", "dialogue_recovery_pending")):
            return False
        viable = n.get("dialogue_row_viable")
        tinted = n.get("dialogue_tint_ready")
        return bool(callable(viable) and viable(kind, row)
                    and callable(tinted) and tinted(kind, row))

    async def maintain(self, view=None):
        """Keep a small reserve and finish approved recordings before silence.

        One existing production/delivery job per pass; each owner retains its
        admission, System 3 plan, retry limits, and durable queue. Maintenance
        never resets advancing audio or stacks an unlimited cupboard feed.
        """
        if self._maintenance_lock.locked():
            return False
        async with self._maintenance_lock:
            view = view or await self.observe()
            if view["blocked"]:
                return False
            self.maintenance_status.update(at=time.time(), runs=self.maintenance_status["runs"] + 1)
            actions, errors = [], []
            if view["incomplete_recordings"]:
                try:
                    result = await self.repair("finish_recordings")
                    actions.append({"step": "finish_recordings", **result})
                except Exception as exc:
                    errors.append("finish_recordings: " + type(exc).__name__)
            # A playing performance retains its place; cupboard stock is a
            # fallback for a real speech gap with a short delivery queue.
            stock_due = (view["listeners_present"] and not view["page_speech_active"]
                         and view["speech_quiet_seconds"] >= 30 and view["unheard_ready"]
                         and view["page_reserved_seconds"] < 90)
            bank_due = (view["banter_ready"] < view["reserve_target"] and not view["writer_busy"]
                        and not view["recording_busy"])
            step = "cupboard_supply" if stock_due else "bank" if bank_due else ""
            if step:
                try:
                    complete, result = await self.ns["_BROADCAST_RECOVERY_JOBS"].run(
                        "station-maintenance-" + step, lambda: self.repair(step), 8.0)
                    actions.append({"step": step, "pending": not complete,
                                    "changed": bool(complete and isinstance(result, dict) and result.get("changed"))})
                    if complete and isinstance(result, dict):
                        actions[-1]["pending"] = bool(result.get("pending"))
                except Exception as exc:
                    errors.append(step + ": " + type(exc).__name__)
            self.maintenance_status.update(actions=actions, last_error="; ".join(errors))
            return bool(actions)

    async def diagnose(self):
        n, now = self.ns, time.time()
        view = await self.observe()
        actions = []
        if view["blocked"]:
            return dict(view, actions=actions, why=view["blocked"][0])
        cure = view.get("cure")
        if view["speech_quiet_seconds"] >= 30:
            view["cause"] = "dialogue_flow_starved"
            view["why"] = "DJ speech delivery has stopped; recent music or queued dialogue cannot mark the station healthy."
        transport_wedged = (view["listeners_present"] > 0 and not view["page_speech_active"]
                            and view["speech_quiet_seconds"] >= 60
                            and view["unstarted_oldest_seconds"] >= 60)
        if transport_wedged:
            view["cause"] = "unheard_dialogue_reservations"
            view["why"] = "Approved speech has no advancing listener receipt; refreshed reservations cannot prove playback."
            actions.append({"step": "delivery_reset", "reason": view["why"], "restart": False})
        previous_reset = view.get("delivery_recovery") or {}
        if (transport_wedged and previous_reset.get("republished")
                and now - float(previous_reset.get("at") or 0) >= 90
                and view["heard_at"] <= float(previous_reset.get("at") or 0)):
            actions.append({"step": "reload_pages", "restart": True,
                            "reason": "Fresh speech delivery still has no listener progress after 90 seconds; reload the stalled player."})
        delivery_cures = {"handover", "release", "reload", "reload_pages", "terminals",
                          "playout_linear", "floor", "stream", "relieve", "rebind"}
        if cure in delivery_cures and view.get("cause") != "healthy" and not transport_wedged:
            actions.append({"step": cure, "reason": view.get("why"),
                            "restart": cure in ("reload", "reload_pages", "stream")})
        if view["delivery_waiting"] and not view["recording_busy"]:
            actions.append({"step": "drain", "reason": "Produced dialogue is waiting for delivery.", "restart": False})
        if view["ready"] and (view.get("cause") in ("nothing_to_play", "quiet_unexplained")
                              or n["dialogue_quiet_for"]() >= n.get("DIALOGUE_QUIET_ALARM", 300)):
            actions.append({"step": "stock", "reason": "Approved dialogue is ready but has not been heard.", "restart": False})
        if (view["ready"] and not view["banter_ready"] and not view["writer_busy"]
                and view["speech_quiet_seconds"] >= 30):
            actions.append({"step": "bank", "reason": "The conversation reserve is empty; other prepared segments cannot replace linked DJ dialogue.", "restart": False})
        if view["incomplete_recordings"]:
            actions.append({"step": "finish_recordings", "reason": "Approved cupboard words still need recording; queue them with the existing recording owner.", "restart": False})
        # A failed writing service needs its own cure, rather than sending
        # new wording repeatedly to an unavailable endpoint. An active
        # admitted writer keeps ownership of its current model request.
        if n.get("OLLAMA_URL") and view["banter_ready"] < view["reserve_target"] and not view["writer_busy"]:
            failures = 0
            for _ in range(2):
                try:
                    async with httpx.AsyncClient(timeout=6) as client:
                        response = await client.get(str(n["OLLAMA_URL"]).rstrip("/") + "/api/tags")
                        response.raise_for_status()
                    break
                except Exception:
                    failures += 1
            if failures == 2:
                actions.append({"step": "writer_service", "reason": "The dialogue writing service failed both health checks.", "restart": True})
        stalled_synth = ((view["render_waiting"] or view["incomplete_recordings"]) and view["synth_tried"]
                         and now - view["synth_done"] > 300 and not view["recording_busy"])
        if stalled_synth:
            engine = str(n["host_clone_engine"]())
            probe = n.get("xtts_health" if engine == "xtts" else "f5_health")
            try:
                health = await asyncio.wait_for(probe(), 8)
                healthy = bool(health.get("ready"))
            except Exception:
                healthy = False
            if not healthy and engine in ("xtts", "f5"):
                actions.append({"step": "voice:" + engine,
                                "reason": "The selected voice engine is not completing queued dialogue.", "restart": True})
        rt_fn = n.get("_system3")
        rt = rt_fn() if callable(rt_fn) else None
        if (view["uptime"] > 120 and not view["recording_busy"]
                and (not view["workers_present"] or rt is not None and not rt.ready)):
            actions.append({"step": "restart_station", "reason": "The station's dialogue workers or planning store did not load.", "restart": True})
        return dict(view, actions=actions)

    async def repair(self, step):
        n = self.ns
        if step == "finish_recordings":
            if (await self.observe())["blocked"]:
                return {"ok": False, "changed": False, "pending": True}
            def enqueue():
                queued = n["cupboard_finish_ids"]()
                added = 0
                for kind, row in n["cupboard_incomplete_rows"]():
                    if added >= 4:
                        break
                    if n["retire_id"](kind, row) in queued or not self._recording_eligible(n, kind, row):
                        continue
                    added += bool(n["cupboard_finish_add"](kind, row, "the station troubleshooter resumed approved recording").get("ok"))
                return added
            added = await asyncio.to_thread(enqueue)
            return {"ok": True, "changed": bool(added), "added": added,
                    "lines": ["Queued %d approved incomplete round(s); source and editorial gates remain in force." % added]}
        if step == "cupboard_supply":
            view = await self.observe()
            if view["blocked"] or view["page_speech_active"] or not view["listeners_present"] or view["page_reserved_seconds"] >= 90:
                return {"ok": True, "changed": False, "pending": True,
                        "lines": ["The advancing performance or existing speech queue retains the air."]}
            # Mark one eligible unheard round as owed; the ordinary consumer
            # owns its complete performance and all existing admission gates.
            def pick():
                candidates = [("banter", r) for r in list(n.get("_LARDER") or [])]
                candidates += [(str(k), r) for k, rows in list((n.get("_SHELF") or {}).items()) for r in list(rows) if k != "track_talk"]
                candidates = [(k, r) for k, r in candidates if n["row_unaired"](r) and n["dialogue_row_ready"](k, r)
                              and id(r) not in n.get("_READY_SHELF_BUSY", set())]
                conversation_roads = {"banter", "manager", "gallery", "caller", "news", "recap"}
                return min(candidates, key=lambda pair: (pair[0] not in conversation_roads,
                    float(pair[1].get("at") or pair[1].get("made_at") or time.time())), default=None)
            chosen = await asyncio.to_thread(pick)
            if chosen is None:
                return {"ok": False, "changed": False, "pending": True, "lines": ["No eligible unheard cupboard recording is available."]}
            kind, row = chosen
            # Recheck after the worker-thread read before changing live state.
            if not n["row_unaired"](row) or not n["dialogue_row_ready"](kind, row):
                return {"ok": True, "changed": False, "pending": True}
            n["record_follow_cue"](kind, row)
            result = await n["unheard_stock_air"](force=True)
            return {"ok": bool(result), "changed": bool(result), "pending": not bool(result),
                    "lines": ["An approved unheard cupboard performance was handed over." if result else "The cupboard performance remains owed; its consumer has not accepted the handoff yet."]}
        if step == "delivery_reset":
            return await recover_dialogue_delivery(n)
        if step == "writer_service":
            if (await self.observe())["writer_busy"]:
                return {"ok": False, "changed": False, "lines": ["An admitted writer is active; its service restart will wait."]}
            # Use the existing host supervisor's per-service signal, and put
            # its filesystem write on a worker so audio remains responsive.
            await asyncio.to_thread(Path(n["HOSTSVC_KICK_PATH"]).write_text, "ollama", encoding="utf-8")
            return {"ok": True, "changed": True,
                    "lines": ["Asked the host supervisor to restart only the dialogue writing service."]}
        if step.startswith("voice:"):
            engine = step.split(":", 1)[1]
            if engine not in ("xtts", "f5"):
                raise ValueError("Unknown diagnosed voice service")
            booths = n["recording_booths"]()
            if booths.get("live") or booths.get("preparing") or any((booths.get("engines") or {}).values()):
                return {"ok": False, "changed": False, "lines": ["A recording is in progress; the voice service will wait."]}
            ok = await n["_director_post"]("/director/engine/" + engine + "/deploy")
            return {"ok": bool(ok), "changed": bool(ok), "lines": [
                "Asked the selected voice service to load." if ok else "The selected voice service could not load yet."]}
        if step == "restart_station":
            view = await self.observe()
            if view["recording_busy"] or view["page_speech_active"] or view["writer_busy"]:
                return {"ok": False, "changed": False, "pending": True, "lines": ["Playback, recording or writing is in progress; the station restart will wait."]}
            stamp = Path(n["AIR_RESTART_STAMP"])
            def reserve_restart():
                now = time.time()
                try:
                    previous = float(stamp.read_text(encoding="utf-8").strip())
                except (OSError, ValueError):
                    previous = 0
                if now - previous < float(n.get("AIR_RESTART_REST", 3600)):
                    return False
                stamp.parent.mkdir(parents=True, exist_ok=True)
                stamp.write_text(str(now), encoding="utf-8")
                return True
            if not await asyncio.to_thread(reserve_restart):
                return {"ok": False, "changed": False, "lines": ["A recent station restart is still in its recovery window."]}
            return await n["broadcast_step"]("restart")
        return await n["broadcast_step"](step)

    async def watch_once(self):
        view = await self.observe()
        now = time.time()
        self.watchdog_status.update(checked_at=now, quiet_seconds=view["speech_quiet_seconds"])
        if not view["blocked"] and now - self._last_maintenance_at >= 60:
            self._last_maintenance_at = now
            try:
                await self.maintain(view)
            except Exception as exc:
                self.maintenance_status["last_error"] = type(exc).__name__
        if (view["blocked"] or not view["listeners_present"] or view["page_speech_active"]
                or view["speech_quiet_seconds"] < 60):
            return False
        # Model work cannot excuse a stuck finished delivery. Reuse the same
        # coordinator so manual clicks and the watchdog never duplicate jobs.
        if now-self._last_automatic_at < 240:
            return False
        manager = await self.get_manager()
        if manager.status().get("running"):
            return False
        report = manager.start(allow_restarts=True)
        self._last_automatic_at = now
        self.watchdog_status.update(last_started_at=now, job_id=report["id"], last_error="")
        return True

    async def watch(self):
        self.watchdog_status["running"] = True
        try:
            while True:
                try:
                    await asyncio.wait_for(self.watch_once(), timeout=30)
                except Exception as exc:
                    self.watchdog_status["last_error"] = type(exc).__name__
                await asyncio.sleep(15)
        finally:
            self.watchdog_status["running"] = False

    async def request_recovery(self, job_id):
        n = self.ns
        view = await self.observe()
        if view["blocked"]:
            return {"ok": False, "changed": False, "why": view["blocked"][0]}
        await n["_s3_recover_larder_candidates"]()
        row = (n.get("_RADIO_WORKERS") or {}).get("tint_recovery") or {}
        task = row.get("task")
        if task is None or task.done():
            n["radio_worker_start"]("tint_recovery", n["tint_recovery_clock"])
        if (n.get("_TINT_RECOVERY_STATE") or {}).get("running"):
            return {"ok": True, "pending": True, "why": "The dialogue recovery worker is already repairing a draft."}
        if not view.get("banter_ready") and not view["writer_busy"]:
            complete, result = await n["_BROADCAST_RECOVERY_JOBS"].run(
                "station-fresh-dialogue", lambda: n["broadcast_step"]("bank"), 8.0)
            return {"ok": True, "changed": bool(complete and result), "pending": True,
                    "why": "Fresh linked dialogue takes priority while the reserve is empty; rejected drafts remain queued for spare capacity."}
        if n.get("_DIALOGUE_RECOVERY"):
            complete, result = await n["_BROADCAST_RECOVERY_JOBS"].run(
                "station-dialogue-recovery", n["tint_recovery_step"], 20.0)
            status = await self.observe()
            return {"ok": True, "changed": bool(complete and result), "pending": bool(status["pending"]),
                    "why": "Fresh dialogue variations were requested; each pass keeps its retry and cooldown limits.",
                    "next_retry_at": status["next_retry_at"], "recovery": status["recovery"]}
        if not view["ready"] and not view["writer_busy"]:
            return await n["broadcast_step"]("bank")
        return {"ok": True, "pending": bool(view["writer_busy"]),
                "why": "The current writer or approved dialogue can continue without another duplicate request."}


def install(app, namespace):
    from fastapi import Header, HTTPException, Request
    globals()["Request"] = Request
    runtime = StationTroubleshootRuntime(namespace)
    namespace["_station_troubleshoot_runtime"] = lambda: runtime

    @app.post("/api/station/troubleshoot")
    async def start(request: Request, authorization: str | None = Header(default=None)):
        namespace["require_auth"](authorization)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(400, "A station troubleshooting request must be an object")
        if payload.get("fix", True) is False:
            return await runtime.diagnose()
        manager = await runtime.get_manager()
        return manager.start(allow_restarts=bool(payload.get("allow_restarts", True)))

    @app.get("/api/station/troubleshoot/{job_id}")
    async def status(job_id: str, authorization: str | None = Header(default=None)):
        namespace["require_read_auth"](authorization)
        manager = await runtime.get_manager()
        result = manager.status(job_id)
        if not result.get("id"):
            raise HTTPException(404, "That station check is no longer in the saved report")
        return result

    @app.on_event("startup")
    async def resume():
        manager = await runtime.get_manager()
        async def continue_saved():
            # The station's existing startup restores its saved on/off state
            # and planning store asynchronously. Resume reports after that
            # restoration, rather than diagnosing the default boot state.
            try:
                saved = await asyncio.to_thread(
                    Path(namespace["RADIO_ON_PATH"]).read_text, encoding="utf-8")
                want_on = bool(json.loads(saved).get("on"))
            except (KeyError, OSError, ValueError):
                want_on = False
            if want_on:
                for _ in range(90):
                    getter = namespace.get("_system3")
                    rt = getter() if callable(getter) else None
                    if (namespace.get("_RADIO") or {}).get("on") and (rt is None or rt.ready):
                        break
                    await asyncio.sleep(1)
            manager.resume_pending()
            await runtime.watch()
        runtime._lifecycle_tasks.append(asyncio.create_task(continue_saved(), name="station-troubleshoot-watchdog"))

    @app.on_event("shutdown")
    async def stop():
        tasks = list(runtime._lifecycle_tasks)
        if runtime.manager is not None:
            tasks.extend(runtime.manager._tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if runtime.manager is not None:
            await runtime.manager.flush()

    return runtime
