"""System2's host adapter: durable planning, off-air preparation and script review.

The independent planner owns selection. Existing writer, Crystal, voice and
transport services remain the station's resource providers, never its clock.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import contextvars
import copy
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid

from system2 import System2Store, System2Conflict, text_hash, _candidate as validate_candidate
from system2_media import System2Media

# #1320: A LANE OF ITS OWN, DELIBERATELY NOT THE DEFAULT EXECUTOR.
#
# events_tick() runs once a second forever, and its first act is to take
# the store lock. s2_events is empty almost always - measured 0 rows, and
# the query itself times at 0.000s - so the poll does no work whatsoever;
# it only queues behind whichever writer currently holds the lock. The
# pulse caught the event loop waiting on exactly that line for 31.0s of
# an 85.4s stalled window (36%), the largest single blocker on the meter.
#
# Awaiting it is the cure, but NOT on asyncio's default pool: #1311c is
# the standing lesson here - a long job on the shared ThreadPoolExecutor
# starves every other to_thread in the process, and this box already runs
# that pool up to twenty threads deep (the loop was measured starved of
# the GIL underneath them). One dedicated worker instead. It can block on
# the store lock for as long as the store likes; nothing else waits
# behind it, and the loop never waits at all.
_STORE_POOL = ThreadPoolExecutor(max_workers=1,
                                 thread_name_prefix="system2-store")


WORK = contextvars.ContextVar("system2_work", default=None)


def current_work():
    return WORK.get()


def stamp_entry(entry):
    work = WORK.get()
    if work is None:
        return
    entry.setdefault("system2_slot", work["slot_id"])
    entry.setdefault("system2_job", work["job_id"])
    entry["system2_trace_id"] = work["trace_id"]
    trace_ids = entry.setdefault("system2_trace_ids", [])
    if work["trace_id"] not in trace_ids:
        trace_ids.append(work["trace_id"])
    if work.get("guest"):
        entry["system2_guest"] = copy.deepcopy(work["guest"])
        entry["third_voice"] = work["guest"]["voice"]


def settings_for_work(settings):
    work = WORK.get()
    if not work:
        return settings
    out = dict(settings)
    guest = work.get("guest")
    if guest:
        out.update(third_name=guest["name"], third_voice=guest["voice"],
                   third_persona=str(guest.get("who") or "") + "\n" + str(guest.get("why") or ""))
    template = work.get("template") or {}
    seconds = min(90.0, max(15.0, float(template.get("seconds") or 90)))
    for field in ("target_seconds", "debt_seconds"):
        value = float(template.get(field) or 0)
        if value > 0:
            seconds = min(seconds, value)
    turns = 11 if work.get("kind") == "caller" else max(4, min(12, int(work.get("generation_turns") or 6)))
    # Keep assembly/lead and one four-second board clip per host pair free.
    # 170wpm is an estimate; 25% headroom anticipates the later rhyme rewrite.
    overhead = 8 + 4 * (turns // 2)
    words = max(1, int(max(0, seconds - overhead) * (170 / 60) / 1.25))
    high = max(8, min(35, words // turns))
    low = max(6, min(20, int(high * .7)))
    ceiling = int(settings.get("reply_max_chars") or 6000)
    chars = min(ceiling, max(360, turns * high * 7 + turns * 4))
    out.update(banter_max_lines=turns, banter_min_lines=min(turns, int(settings.get("banter_min_lines") or turns)),
               system2_budget={"seconds": seconds, "turns": turns, "words_low": low,
                               "words_high": high, "max_chars": chars,
                               "source_chars": min(220, max(80, chars // 6)),
                               "estimated": True, "reserved_seconds": overhead})
    return out


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    default=str).encode()).hexdigest()


class System2Runtime:
    RECAP_LEAD_FLOOR_SECONDS = 420.0
    RECAP_LEAD_MAX_SECONDS = 900.0
    RETENTION_INTERVAL_SECONDS = 6 * 3600
    RETENTION_MAX_AGE_SECONDS = 7 * 86400
    RETENTION_REPEAT_SECONDS = 2 * 3600
    RETENTION_BATCH_ROWS = 2000
    RETENTION_LIMITS = {
        "hours": 96,
        "jobs": 4000,
        "reservations": 2000,
        "receipts": 8000,
        "heard": 20000,
        "events": 2000,
        "absent_candidates": 500,
    }
    RETENTION_COMPACT_MIN_BYTES = 64 * 1024 * 1024
    RETENTION_COMPACT_FREE_RATIO = .20

    def __init__(self, host):
        self.host = host
        self.store = System2Store(host.DATA_DIR / "system2.sqlite3")
        self.media = System2Media(host)
        self.config_path = host.DATA_DIR / "system2-config.json"
        # #1070: legacy_keepers - the pantry and larder keepers keep writing
        # while System2 is on (one serial tint lane cannot spare a writer);
        # fallback - the legacy chain serves an occurrence System2 has
        # nothing verified for, instead of the slot going silent.
        # #1069/#1070: the station runs System2 by default THROUGH the saved
        # system2-config.json (written by POST /api/system2/settings); the
        # code default stays legacy so a bare runtime in a test host does
        # not start preparing and dispatching against a fixture.
        self.config = {"engine": "legacy", "horizon_hours": 2,
                       "repeat_seconds": 3600, "generation_turns": 6,
                       "legacy_keepers": True, "fallback": True}
        try:
            self.config.update(json.loads(self.config_path.read_text("utf-8")))
        except (OSError, ValueError):
            pass
        self._files = {}
        self._rows = {}
        self._candidates = []
        self._clock_seen = None        # #1224: last published occurrence
        self._plans = []
        self._refresh_lock = asyncio.Lock()
        # #1084: one preparation per model lane. With OLLAMA_LANES=2 a
        # second job on a DIFFERENT road runs beside the first; the brief
        # and the prep context are task-local (host._ALT_BRIEF/_PREP_CONTEXT
        # by task id), so two sittings do not read each other's segment.
        self._lanes = max(1, min(4, int(getattr(host, "OLLAMA_LANES", 1) or 1)))
        self._prepare_lock = asyncio.Semaphore(self._lanes)
        self._dispatch_lock = asyncio.Lock()
        self._last_refresh = 0.0
        self._errors = []
        self._work = {}
        self._works = {}
        self._dispatched = {}
        self._record_slots = set()
        self._event_plans = []
        self._refused = {}
        self._retention_guard = threading.Lock()
        self._retention_last = {
            "last_run_at": 0.0, "duration_seconds": 0.0,
            "selected": {}, "deleted": {}, "skipped_changed": 0,
            "archive": None, "compaction": None, "error": "",
        }
        self._retention_observed = {}

    @property
    def enabled(self):
        return self.config.get("engine") == "system2"

    def content_gate_enabled(self, gate):
        policy = getattr(self.host, "content_gate_enabled", None)
        if callable(policy):
            return bool(policy(gate))
        return gate == "tint" and bool(self.host.dialogue_tint_required())

    @property
    def owns_preparation(self):
        """#1070: do the legacy pantry and larder keepers stand down?
        Only when the operator turns legacy_keepers off; by default every
        writer keeps writing and System2 plans over the common inventory."""
        return self.enabled and not bool(self.config.get("legacy_keepers", True))

    def fallback_due(self):
        """#1070: may the legacy chain serve the running occurrence?

        Only when System2 is on and fallback is allowed, the running slot is
        dialogue, every verified performance staged for it has already been
        dispatched (or none is staged), and nothing of System2's own is on
        the air. The legacy chain reads the same clock through
        schedule_take, so what it serves belongs to this entry; the slot's
        unmet debt stays recorded as debt."""
        if not self.enabled or not bool(self.config.get("fallback", True)):
            return False
        now = time.time()
        slot = next((s for hour in self._plans for s in hour.get("slots", [])
                     if s["start"] <= now < s["deadline"]), None)
        if not slot or slot.get("non_dialogue"):
            return False
        if any(self.recap_matches(slot, a["candidate"])
               and (slot["id"], a["candidate"]["id"]) not in self._dispatched
               for a in slot.get("allocations", [])):
            return False
        h = self.host
        try:
            if h._SPEAKING[0] or h._floor_busy():
                return False
        except Exception:
            return False
        return True

    def configure(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Expected settings object")
        unknown = set(payload) - {"engine", "horizon_hours", "generation_turns", "legacy_keepers", "fallback"}
        if unknown:
            raise ValueError("Unknown System2 settings: " + ", ".join(sorted(unknown)))
        new = dict(self.config)
        if "engine" in payload:
            if payload["engine"] not in ("legacy", "system2"):
                raise ValueError("engine must be legacy or system2")
            new["engine"] = payload["engine"]
        for key in ("legacy_keepers", "fallback"):
            if key in payload:
                if not isinstance(payload[key], bool):
                    raise ValueError(f"{key} must be a boolean")
                new[key] = payload[key]
        for key, low, high in (("horizon_hours", 1, 6), ("generation_turns", 4, 12)):
            if key in payload:
                value = payload[key]
                if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                    raise ValueError(f"{key} must be an integer from {low} to {high}")
                new[key] = value
        new["repeat_seconds"] = 3600
        temp = self.config_path.with_suffix(".tmp")
        temp.write_text(json.dumps(new, indent=2) + "\n", "utf-8")
        temp.replace(self.config_path)
        self.config = new
        self._last_refresh = 0
        return dict(new)

    def error(self, stage, exc):
        row = {"at": time.time(), "stage": stage,
               "error": type(exc).__name__, "message": str(exc)[:500]}
        self._errors.append(row)
        self._errors = self._errors[-30:]
        self.host.pipeline_log("system2", stage + ": " + row["message"])

    def refuse(self, slot, candidate, why):
        """#1074: say why an allocation was not delivered - once a minute per
        allocation and reason. The release reason on the reservation was the
        only record and it named no stage: twenty-two releases tonight, all
        "Transport refused the recording". A transient refusal is still
        offered again on the next dispatch, as the store's contract says."""
        key = (slot["id"], candidate["id"])
        last = self._refused.get(key) or {}
        if time.time() - float(last.get("said") or 0) >= 60 or last.get("why") != why:
            self.host.pipeline_log("system2", "%s for %s waits: %s"
                                   % (candidate["id"], slot.get("label") or slot["id"], why))
            self._refused[key] = {"said": time.time(), "why": why}
        if len(self._refused) > 500:
            for old in sorted(self._refused, key=lambda k: self._refused[k]["said"])[:250]:
                self._refused.pop(old, None)

    def media_proof(self, clip):
        """Hash actual bytes once per file revision; never use a filename as proof."""
        try:
            return self.media.proof(clip)
        except (OSError, ValueError, AttributeError):
            return None

    def candidate(self, kind, row, identity=None):
        h = self.host
        identity = identity or h.alt_sid(kind, row)
        resolved = self.media.resolve(kind, row)
        entry = resolved["entry"] or h.dialogue_entry(row) or row
        takes = resolved["takes"]
        lines = []
        complete = bool(resolved["ready"] and takes)
        raw_takes = takes or entry.get("takes") or []
        for i, take in enumerate(raw_takes):
            clip = take.get("clip") or (h._PANTRY.get(str(take.get("key") or "")) or {}).get("clip") or {}
            proof = self.media_proof(clip)
            if not proof or proof["seconds"] <= 0:
                complete = False
            lines.append({"id": str(take.get("i", i)), "text": str(take.get("text") or ""),
                          "who": str(take.get("who") or ""), "voice": str(take.get("voice") or ""),
                          "key": str(take.get("key") or ""), "audio": copy.deepcopy(clip),
                          **(proof or {}), "trace_id": str(entry.get("system2_trace_id") or "")})
        # #1074: a round mid-sitting can carry two takes with the same script
        # index (a re-cut, or a line larder_prepare could not place, stamped
        # 999). The store refuses duplicate line IDs, and one such row took the
        # whole refresh down with it - eight times in five minutes tonight.
        # The recorded position stays on the line; the ID becomes its order.
        if len({x["id"] for x in lines}) != len(lines):
            for position, line in enumerate(lines):
                line["take_index"], line["id"] = line["id"], str(position)
        if not lines:
            for i, (who, text) in enumerate(h.banter_turns(str(entry.get("script") or ""),
                    str(entry.get("caller_name") or ""), str(entry.get("caller2_name") or ""))):
                lines.append({"id": str(i), "who": who, "text": text,
                              "trace_id": str(entry.get("system2_trace_id") or "")})
        reason = []
        viable = bool(resolved["ready"] or kind != "track_talk" and h.dialogue_row_viable(kind, row))
        if not viable: reason.append("Current source, voice or segment contract needs attention")
        if (kind != "track_talk" and self.content_gate_enabled("tint")
                and not h.dialogue_tint_ready(kind, row)):
            reason.append("Tint is incomplete; accepted turns are retained")
        if not complete: reason.append("The complete ordered script does not yet have verified recordings")
        expires = 0
        if kind == "news" and self.content_gate_enabled("freshness"):
            expires = float(entry.get("prep_news_at") or entry.get("at") or 0) + h.NEWS_PREP_LIFE
        if self.content_gate_enabled("freshness"):
            try:
                # #1068: every road's stock expires, on the host's one clock.
                expires = float(h.stock_expires_at(kind, row) or 0)
            except Exception:
                pass
        if expires and expires < time.time():
            # #1074: the store refuses an expired row silently (candidate_expired);
            # the status page showed it as ready. Say it, and say it here.
            reason.append("Past its expiry; the planner no longer offers it")
            viable = False
        result = {"id": identity, "kind": kind, "seconds": sum(float(x.get("seconds") or 0) for x in lines),
                  "ready": complete,
                  "eligible": viable, "expires_at": expires,
                  "repeat_guard": self.content_gate_enabled("repetition"),
                  "script": str(entry.get("script") or entry.get("text") or ""),
                  "source_id": digest(entry.get("script_plain") or entry.get("script") or ""),
                  "lines": lines, "audio_hashes": [x["audio_hash"] for x in lines if x.get("audio_hash")],
                  "source": copy.deepcopy({k: entry[k] for k in ("script_plain", "script_tinted", "tint",
                      "tint_report", "desk", "swaths", "prep_news_stories", "prep_gallery", "caller_name",
                      "system2_trace_id", "system2_trace_ids", "system2_job", "system2_slot", "tint_retry_budget",
                      "system2_guest", "system2_source_evidence", "system2_authoring_budget",
                      "system2_topic_review", "topic_contract", "topic_id", "topic_shape",
                      "topic", "premise", "angle") if k in entry}),
                  "why": reason, "created_at": float(entry.get("at") or row.get("at") or 0)}
        if entry.get("system2_slot") and (kind == "recap" or self.binding_live(entry["system2_slot"])):
            result["slot_id"] = entry["system2_slot"]        # recaps never change their observed hour
        if kind == "track_talk":
            result.update(track_id=resolved.get("track_id") or row.get("track_id"), part=resolved.get("part") or row.get("part"))
        self._rows[identity] = (kind, row)
        return result

    def binding_live(self, slot_id):
        """#1390: IS THE OCCURRENCE THIS ROW WAS WRITTEN FOR STILL AHEAD?

        A sitting stamps its rows with the slot it was commissioned for
        (system2_slot), and the planner honours that pin absolutely:
        _slot_matches refuses the row for every other slot, and prepare()
        skips it for every other job. Right while the slot is ahead - the
        scene was written to its brief. Wrong forever after: when the slot
        passes unfilled (a stalled loop, a refused transport, a restart)
        the row stays pinned to an occurrence that can never be filled
        again, and so does every half-made row the sitting left behind,
        because prepare() will not pick those up for any other job either.

        Measured on the live store, 2026-09-14 12:03: 39 finished, verified
        rounds and 234 half-made ones bound to slots of PAST hours - nine
        callers, eight memos and three gallery rounds ready to air - while
        the running hour read '12 of 18 slots carry nothing', every caller
        slot refusing 297 rows as slot_binding, and the unbound pool of that
        road holding ONE. The hour was empty because its own output was
        locked in the past.

        So a binding is honoured only while its slot's deadline is ahead.
        The in-memory plan is asked first (it carries the real deadline); a
        slot the plan no longer holds is judged by the hour in its id; an
        event occurrence, or an id of a shape we do not know, keeps its
        binding - the require_slot_binding jobs check it themselves."""
        sid = str(slot_id or "")
        if not sid:
            return False
        now = time.time()
        for hour in list(self._plans) + list(self._event_plans):
            for slot in hour.get("slots", []):
                if str(slot.get("id") or "") == sid:
                    return float(slot.get("deadline") or 0) > now
        if sid.startswith("event-"):
            return True
        try:
            start = int(sid.split(":", 1)[0].split("-", 1)[1]) / 1000.0
        except (ValueError, IndexError):
            return True
        return now < start + 3600

    def inventory(self):
        self._rows = {}
        candidates = []
        seen = set()
        # #1171: ...and NOT the roads the host says cannot be prepared.
        # `recap` and `deep` were appended here by hand; both read the
        # stretch of show that just happened, both are named in
        # CANNOT_PREPARE with that reason, and nothing anywhere takes
        # either of them off a shelf. See the note in the patch.
        for kind in tuple(self.host.ALT_PREP_KINDS):
            if kind == "track_talk":
                for identity, row in self.media.inventory_track_talk():
                    self._offer(candidates, seen, kind, row, identity)
                continue
            for row in self.host.alt_candidates(kind):
                self._offer(candidates, seen, kind, row)
        return candidates

    def _offer(self, candidates, seen, kind, row, identity=None):
        """#1074: one malformed row is named and skipped, never allowed to veto
        the plan. sync_candidates validates the batch as a whole, so a single
        ValueError there left the planner without a refresh, the preparer
        without a claim and the dispatcher without a slot until the row
        happened to change. A skipped row reads as absent from the inventory,
        which is what it is until it can be described."""
        try:
            # #1390: the validated (normalised) row is what is kept, so the
            # store does not normalise it all over again - see sync_candidates.
            offered = validate_candidate(self.candidate(kind, row, identity))
            if offered["id"] in seen:
                raise ValueError("duplicate candidate id " + offered["id"])
        except Exception as exc:
            self.error("inventory:" + kind, exc)
            return
        seen.add(offered["id"])
        candidates.append(offered)

    def templates(self, hour):
        h = self.host
        settings = h.schedule_read()
        key = h._sched_hour_key(hour)
        preset, rows, overridden = h.schedule_hour_slots(settings, key)
        out = []
        for index, slot in enumerate(rows):
            if slot.get("enabled", True) is False:
                continue
            kind = str(slot.get("kind") or "banter")
            road = str(h.SCHED_PREP_KIND.get(kind) or kind)
            seconds = max(15, float(slot.get("minutes") or 3) * 60)
            brief = h.schedule_prompt_for(settings, slot)
            template_id = str(slot.get("id") or f"slot-{index}")
            occurrence = "hour-" + str(int(float(hour) * 1000)) + ":" + template_id
            choice = h.script_choice(occurrence) if hasattr(h, "script_choice") else {}
            out.append({**copy.deepcopy(slot), "id": template_id,
                        "kind": road, "slot_kind": kind, "seconds": seconds,
                        "label": str(slot.get("label") or h.SCHEDULE_KIND_NAMES.get(kind) or kind),
                        "prompt": h._schedule_clause(preset, slot, brief),
                        "hour_key": key, "preset": preset,
                        "target_seconds": 0 if kind == "record" else seconds,
                        "non_dialogue": kind == "record",
                        "preferred_candidate_id": str(choice.get("candidate") or "")})
            if road == "recap":
                out[-1]["require_slot_binding"] = True
            if road == "track_talk":
                out[-1].update(coverage_mode="one_performance", target_performances=1,
                               target_seconds=min(15.0, seconds), allocation_mode="current")
        return out

    def recap_lead_seconds(self):
        """Leave room for a complete observed-hour scene, including voice work."""
        lead = self.RECAP_LEAD_FLOOR_SECONDS
        stat = getattr(self.host, "task_stat", None)
        if callable(stat):
            try:
                for kind in ("recap", "banter"):
                    row = stat(kind) or {}
                    if row.get("measured"):
                        p90 = float(row.get("p90") or 0)
                        if math.isfinite(p90) and p90 > 0:
                            lead = max(lead, p90 * 1.25 + 90.0)
                            break
            except (TypeError, ValueError):
                pass
        return min(self.RECAP_LEAD_MAX_SECONDS, lead)

    @staticmethod
    def recap_matches(slot, candidate, entry=None):
        if slot.get("kind") != "recap":
            return True
        source = candidate.get("source") or {}
        sid = slot.get("id")
        return (candidate.get("slot_id") == sid
                and isinstance(source, dict) and source.get("system2_slot") == sid
                and (entry is None or entry.get("system2_slot") == sid))

    REFRESH_SECONDS = 60.0   # #1070: was 15; each refresh decodes every candidate body twice

    async def refresh(self, force=False, want_status=True):
        # #1070: status() deep-copies every plan (about a megabyte) and the
        # UI polls it; build it in a worker thread so the air clock is not
        # the one paying for the copy, and skip it when the caller only
        # wants the refresh itself.
        if not force and time.time() - self._last_refresh < self.REFRESH_SECONDS:
            return await asyncio.to_thread(self.status) if want_status else None
        async with self._refresh_lock:
            if not force and time.time() - self._last_refresh < self.REFRESH_SECONDS:
                return await asyncio.to_thread(self.status) if want_status else None
            candidates = await asyncio.to_thread(self.inventory)
            # #1074: the sync normalises and re-serialises every candidate
            # (220 tonight, twelve megabytes of JSON) and rewrites the table in
            # one fsynced transaction; on the air loop that is a multi-second
            # stall of the class the host watchdog restarts the station for.
            # The store is lock-protected; every other store call in this
            # refresh already runs in a worker thread.
            await asyncio.to_thread(self.store.sync_candidates, candidates, replace=True,
                                    normalized=True)                       # #1390
            self._candidates = candidates
            first = self.host._sched_hour_epoch(self.host._sched_hour_key())
            plans = []
            for offset in range(int(self.config["horizon_hours"])):
                hour = first + offset * 3600
                templates = self.templates(hour)
                # #1408: the revision is digested WITHOUT the prompt. The brief
                # embeds the battle's round counter ("THE BATTLE (#1090) ...
                # Round 17321."), which advances as the show goes, so the
                # digest changed on every refresh: s2_hours showed the 12:00
                # hour at revision 60 and the 13:00 hour at 42, one per
                # minute. Each bump made plan_hour drop every allocation and
                # rebuild it, replace every prepare job - so every sitting
                # ended in "Preparation job ownership changed" (three in ten
                # minutes today, one per sitting) - and raise System2Conflict
                # whenever a System2 round was on the air. A finished round
                # does not stop fitting a slot because its brief was reworded;
                # the stored slot still carries the current prompt (plan_hour
                # rebuilds slots from the templates every pass), only the
                # revision stops churning.
                plan = await asyncio.to_thread(self.store.plan_hour, hour, templates,
                                               config_revision=digest(
                                                   [{k: v for k, v in t.items() if k != "prompt"}
                                                    for t in templates]))
                plans.append(plan)
            events = await asyncio.to_thread(                      # #1224
                self.store.events, states=["pending", "working"], limit=100)
            event_plans = []
            for event in events:
                if event["kind"] == "music_request" or event["deadline"] <= time.time():
                    continue
                payload = event["payload"]
                at = float(payload["air_at"])
                template = {"id": "scene", "kind": "caller" if event["kind"] == "call_in" else "banter",
                    "slot_kind": event["kind"], "label": payload.get("label") or event["kind"].replace("_", " "),
                    "seconds": float(event["deadline"]) - at, "target_seconds": float(payload["seconds"]),
                    "coverage_mode": "one_performance", "target_performances": 1,
                    "event_id": event["id"], "event": copy.deepcopy(payload),
                    "prompt": str(payload.get("brief") or ""), "offset": 0,
                    "require_slot_binding": True}
                plan = await asyncio.to_thread(self.store.plan_hour, at, [template],
                    config_revision=digest(template), plan_id="event-" + event["id"])
                event_plans.append(plan)
            await asyncio.to_thread(lambda: [self.include_drafts(plan) for plan in plans + event_plans])
            self._plans = plans
            self._event_plans = event_plans
            self._last_refresh = time.time()
        return await asyncio.to_thread(self.status) if want_status else None

    def include_drafts(self, hour):
        slots = hour.get("slots", [])
        # #1070: one decode of the candidate table for the hour, not one per slot.
        by_slot = self.store.candidates_by_slot([slot["id"] for slot in slots])
        for slot in slots:
            staged = {item["candidate"]["id"] for item in slot.get("allocations", [])}
            slot["drafts"] = [row for row in by_slot.get(slot["id"], []) if row["id"] not in staged]
        return hour

    def scripts(self, hour_id):
        result = self.store.scripts(hour_id)
        if result:
            for slot in result["slots"]:
                staged = {row["id"] for row in slot["performances"]}
                slot["drafts"] = [row for row in self.store.candidates_for_slot(slot["slot_id"]) if row["id"] not in staged]
        return result

    @staticmethod
    def _retention_json(raw):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}

    def _retention_select(self, db, *, now, max_age_seconds, limits, batch_rows):
        """Select one dependency-safe retention batch from a single snapshot.

        The archive write happens outside the database lock. The exact same
        selection is therefore repeated in the deletion transaction and every
        body is compared byte-for-byte before deletion.
        """
        cutoff = now - max_age_seconds
        terminal_jobs = {"completed", "satisfied", "expired"}
        terminal_reservations = {"completed", "released"}
        terminal_events = {"completed", "expired"}

        hours = [dict(row) for row in db.execute(
            "SELECT id,start FROM s2_hours ORDER BY start DESC,id")]
        slots = [dict(row) for row in db.execute(
            "SELECT id,hour_id FROM s2_slots ORDER BY rowid DESC")]
        jobs = [dict(row) for row in db.execute(
            "SELECT id,slot_id,state,deadline,"
            " COALESCE(json_extract(body,'$.finished_at'),deadline,0) AS stamp,body"
            " FROM s2_jobs ORDER BY deadline DESC,id")]
        reservations = [dict(row) for row in db.execute(
            "SELECT id,slot_id,candidate_id,state,"
            " COALESCE(json_extract(body,'$.completed_at'),"
            " json_extract(body,'$.released_at'),json_extract(body,'$.reserved_at'),0) AS stamp"
            " FROM s2_reservations ORDER BY stamp DESC,id")]
        events = [dict(row) for row in db.execute(
            "SELECT id,state,deadline,"
            " COALESCE(json_extract(body,'$.completed_at'),"
            " json_extract(body,'$.expired_at'),json_extract(body,'$.released_at'),deadline,0) AS stamp"
            " FROM s2_events ORDER BY stamp DESC,id")]

        slot_hour = {row["id"]: row["hour_id"] for row in slots}
        protected_hours = {
            row["id"] for row in hours
            if row["start"] > now or row["start"] <= now < row["start"] + 3600
        }
        protected_hours.update(
            str(hour.get("id") or "")
            for hour in list(self._plans) + list(self._event_plans)
            if hour.get("id"))
        unfinished_jobs = {row["id"] for row in jobs if row["state"] not in terminal_jobs}
        active_reservations = {
            row["id"] for row in reservations
            if row["state"] not in terminal_reservations
        }
        active_events = {row["id"] for row in events if row["state"] not in terminal_events}
        protected_slots = {
            row["slot_id"] for row in jobs if row["id"] in unfinished_jobs
        } | {
            row["slot_id"] for row in reservations if row["id"] in active_reservations
        }
        protected_hours.update(
            slot_hour[slot_id] for slot_id in protected_slots if slot_id in slot_hour)
        protected_hours.update("event-" + identity for identity in active_events)
        protected_slots.update(
            row["id"] for row in slots if row["hour_id"] in protected_hours)

        selected = {table: set() for table in (
            "s2_heard", "s2_receipts", "s2_reservations", "s2_jobs",
            "s2_candidates", "s2_events", "s2_slots", "s2_hours")}

        kept_hours = 0
        for row in hours:
            if row["id"] in protected_hours:
                continue
            old = row["start"] + 3600 < cutoff
            if old or kept_hours >= limits["hours"]:
                selected["s2_hours"].add(row["id"])
            else:
                kept_hours += 1
        selected["s2_slots"].update(
            row["id"] for row in slots
            if row["hour_id"] in selected["s2_hours"] and row["id"] not in protected_slots)

        protected_jobs = unfinished_jobs | {
            row["id"] for row in jobs if row["slot_id"] in protected_slots
        }
        kept = 0
        for row in sorted(jobs, key=lambda item: (float(item["stamp"] or 0), item["id"]), reverse=True):
            if row["state"] not in terminal_jobs or row["id"] in protected_jobs:
                continue
            forced = row["slot_id"] in selected["s2_slots"]
            if forced or float(row["stamp"] or 0) < cutoff or kept >= limits["jobs"]:
                selected["s2_jobs"].add(row["id"])
            else:
                kept += 1

        protected_reservations = active_reservations | {
            row["id"] for row in reservations if row["slot_id"] in protected_slots
        }
        kept = 0
        for row in sorted(reservations, key=lambda item: (float(item["stamp"] or 0), item["id"]), reverse=True):
            if row["state"] not in terminal_reservations or row["id"] in protected_reservations:
                continue
            forced = row["slot_id"] in selected["s2_slots"]
            if forced or float(row["stamp"] or 0) < cutoff or kept >= limits["reservations"]:
                selected["s2_reservations"].add(row["id"])
            else:
                kept += 1

        kept = 0
        for row in sorted(events, key=lambda item: (float(item["stamp"] or 0), item["id"]), reverse=True):
            if row["state"] not in terminal_events or row["id"] in active_events:
                continue
            if float(row["stamp"] or 0) < cutoff or kept >= limits["events"]:
                selected["s2_events"].add(row["id"])
            else:
                kept += 1

        reservation_ids = {row["id"] for row in reservations}
        receipts = [dict(row) for row in db.execute(
            "SELECT id,at,reservation_id FROM s2_receipts ORDER BY at DESC,id")]
        kept = 0
        for row in receipts:
            reservation_id = str(row["reservation_id"] or "")
            if reservation_id in protected_reservations:
                continue
            if reservation_id and reservation_id in reservation_ids:
                if reservation_id in selected["s2_reservations"]:
                    selected["s2_receipts"].add(row["id"])
                continue
            if float(row["at"] or 0) < cutoff or kept >= limits["receipts"]:
                selected["s2_receipts"].add(row["id"])
            else:
                kept += 1

        repeat_cutoff = now - self.RETENTION_REPEAT_SECONDS
        heard = [dict(row) for row in db.execute(
            "SELECT fingerprint,at,reservation_id,receipt_id FROM s2_heard"
            " ORDER BY at DESC,fingerprint")]
        kept = 0
        for row in heard:
            if (str(row["reservation_id"] or "") in protected_reservations
                    or float(row["at"] or 0) >= repeat_cutoff):
                continue
            if float(row["at"] or 0) < repeat_cutoff or kept >= limits["heard"]:
                selected["s2_heard"].add(row["fingerprint"])
            else:
                kept += 1

        retained_candidate_ids = {
            row["candidate_id"] for row in reservations
            if row["id"] not in selected["s2_reservations"]
        }
        for row in db.execute(
                "SELECT s.id AS slot_id,json_extract(a.value,'$.candidate.id') AS candidate_id"
                " FROM s2_slots s,json_each(s.body,'$.allocations') a"):
            if row["slot_id"] not in selected["s2_slots"] and row["candidate_id"]:
                retained_candidate_ids.add(row["candidate_id"])
        unfinished_references = set()
        for row in jobs:
            if row["id"] not in unfinished_jobs:
                continue
            stack = [self._retention_json(row["body"])]
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)
                elif isinstance(value, str):
                    unfinished_references.add(value)
        inventory_ids = {str(row.get("id") or "") for row in self._candidates}
        candidates = [dict(row) for row in db.execute(
            "SELECT id,json_extract(body,'$.slot_id') AS slot_id,"
            " COALESCE(json_extract(body,'$.source.system2_job'),"
            " json_extract(body,'$.system2_job'),'') AS job_id,"
            " COALESCE(json_extract(body,'$.created_at'),0) AS stamp,"
            " json_extract(body,'$.blocked_reasons[0]') AS first_block"
            " FROM s2_candidates ORDER BY stamp DESC,id")]
        kept = 0
        for row in candidates:
            if row["first_block"] != "absent_from_current_inventory":
                continue
            protected = (row["id"] in inventory_ids or row["id"] in retained_candidate_ids
                         or row["id"] in unfinished_references
                         or str(row["job_id"] or "") in unfinished_jobs
                         or str(row["slot_id"] or "") in protected_slots)
            if protected:
                continue
            if float(row["stamp"] or 0) < cutoff or kept >= limits["absent_candidates"]:
                selected["s2_candidates"].add(row["id"])
            else:
                kept += 1

        # Leaves precede their parents. If a large backlog hits the batch
        # ceiling, no slot/hour can be removed before all selected children
        # from this snapshot have already fit in the durable archive.
        order = ("s2_heard", "s2_receipts", "s2_reservations", "s2_jobs",
                 "s2_candidates", "s2_events", "s2_slots", "s2_hours")
        entries = []
        for table in order:
            for identity in sorted(selected[table]):
                if len(entries) >= batch_rows:
                    return entries
                if table == "s2_heard":
                    row = db.execute(
                        "SELECT fingerprint,at,reservation_id,receipt_id FROM s2_heard"
                        " WHERE fingerprint=?", (identity,)).fetchone()
                    if row:
                        entries.append({"table": table, "key": identity,
                                        "record": dict(row)})
                    continue
                row = db.execute("SELECT body FROM " + table + " WHERE id=?",
                                 (identity,)).fetchone()
                if row:
                    entries.append({"table": table, "key": identity,
                                    "raw_body": row[0]})
        return entries

    def _write_retention_archive(self, entries, *, now, policy):
        directory = self.host.DATA_DIR / "system2-audit"
        directory.mkdir(parents=True, exist_ok=True)
        batch = "%d-%s" % (int(now * 1000), uuid.uuid4().hex)
        path = directory / ("retention-" + batch + ".jsonl.gz")
        temp = path.with_suffix(path.suffix + ".tmp")
        header = {"type": "system2_retention", "version": 1, "batch": batch,
                  "archived_at": now, "policy": policy, "rows": len(entries)}
        with gzip.open(temp, "wt", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(header, ensure_ascii=False, sort_keys=True) + "\n")
            for entry in entries:
                output.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        # Windows requires a writable descriptor for FlushFileBuffers, which
        # is what os.fsync delegates to. The archive contents are already
        # complete; r+b only supplies the descriptor mode needed to flush it.
        with temp.open("r+b") as durable:
            os.fsync(durable.fileno())
        temp.replace(path)
        checksum = hashlib.sha256()
        with path.open("rb") as saved:
            for chunk in iter(lambda: saved.read(1024 * 1024), b""):
                checksum.update(chunk)
        return {"path": str(path), "rows": len(entries), "bytes": path.stat().st_size,
                "sha256": checksum.hexdigest(), "batch": batch}

    def _retention_observe(self):
        tables = ("s2_hours", "s2_slots", "s2_jobs", "s2_candidates",
                  "s2_reservations", "s2_receipts", "s2_heard", "s2_events")
        # WAL readers do not need the store-wide writer lock. Status polling
        # must not queue behind a long planner transaction merely to count.
        db = self.store._connect()
        try:
            db.execute("BEGIN")
            rows = {table.removeprefix("s2_"): int(db.execute(
                "SELECT count(*) FROM " + table).fetchone()[0]) for table in tables}
            page_size = int(db.execute("PRAGMA page_size").fetchone()[0])
            page_count = int(db.execute("PRAGMA page_count").fetchone()[0])
            free_pages = int(db.execute("PRAGMA freelist_count").fetchone()[0])
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
        path = self.store.path
        archive_dir = self.host.DATA_DIR / "system2-audit"
        archives = list(archive_dir.glob("retention-*.jsonl.gz")) if archive_dir.is_dir() else []
        return {"rows": rows, "database_bytes": path.stat().st_size if path.exists() else 0,
                "wal_bytes": path.with_name(path.name + "-wal").stat().st_size
                if path.with_name(path.name + "-wal").exists() else 0,
                "page_size": page_size, "page_count": page_count,
                "free_pages": free_pages,
                "free_ratio": round(free_pages / max(1, page_count), 6),
                "archive_files": len(archives),
                "archive_bytes": sum(item.stat().st_size for item in archives)}

    def _retention_compact(self, *, deleted, force=False):
        result = {"attempted": False, "ran": False, "reason": "no rows deleted"}
        if not deleted and not force:
            return result
        with self.store._lock:
            db = self.store._connect()
            try:
                page_size = int(db.execute("PRAGMA page_size").fetchone()[0])
                before_pages = int(db.execute("PRAGMA page_count").fetchone()[0])
                before_free = int(db.execute("PRAGMA freelist_count").fetchone()[0])
                before_bytes = before_pages * page_size
                free_ratio = before_free / max(1, before_pages)
                result.update(attempted=True, before_pages=before_pages,
                              before_free_pages=before_free,
                              before_bytes=before_bytes,
                              free_ratio=round(free_ratio, 6))
                should_run = force or (before_bytes >= self.RETENTION_COMPACT_MIN_BYTES
                                       and free_ratio >= self.RETENTION_COMPACT_FREE_RATIO)
                station_active = (bool(self.host._RADIO.get("on"))
                                  and not self.host.radio_paused())
                if should_run and station_active and not force:
                    result["reason"] = "station active; physical compaction deferred"
                elif should_run:
                    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    db.execute("VACUUM")
                    result.update(ran=True, reason="fragmentation threshold reached")
                else:
                    result["reason"] = "below size or fragmentation threshold"
                result.update(after_pages=int(db.execute("PRAGMA page_count").fetchone()[0]),
                              after_free_pages=int(db.execute("PRAGMA freelist_count").fetchone()[0]))
                result["after_bytes"] = result["after_pages"] * page_size
            finally:
                db.close()
        return result

    def run_retention(self, *, now=None, max_age_seconds=None, limits=None,
                      batch_rows=None, compact=True, force_compact=False):
        """Archive and prune one bounded System2 persistence batch."""
        if not self._retention_guard.acquire(blocking=False):
            return {**copy.deepcopy(self._retention_last), "busy": True}
        started = time.monotonic()
        when = time.time() if now is None else float(now)
        age = self.RETENTION_MAX_AGE_SECONDS if max_age_seconds is None else float(max_age_seconds)
        policy_limits = dict(self.RETENTION_LIMITS)
        if limits:
            unknown = set(limits) - set(policy_limits)
            if unknown:
                self._retention_guard.release()
                raise ValueError("Unknown retention limits: " + ", ".join(sorted(unknown)))
            policy_limits.update({key: int(value) for key, value in limits.items()})
        if age < self.RETENTION_REPEAT_SECONDS or any(value < 0 for value in policy_limits.values()):
            self._retention_guard.release()
            raise ValueError("Retention age and row limits must preserve the repeat window and be nonnegative")
        batch = self.RETENTION_BATCH_ROWS if batch_rows is None else int(batch_rows)
        if batch < 1:
            self._retention_guard.release()
            raise ValueError("Retention batch_rows must be positive")
        policy = {"max_age_seconds": age, "batch_rows": batch,
                  "repeat_seconds": self.RETENTION_REPEAT_SECONDS,
                  "limits": policy_limits}
        try:
            # A stable WAL snapshot is enough for archive selection and does
            # not exclude writers. The later BEGIN IMMEDIATE transaction
            # repeats this selection before deleting exact unchanged bodies.
            db = self.store._connect()
            try:
                db.execute("BEGIN")
                entries = self._retention_select(
                    db, now=when, max_age_seconds=age,
                    limits=policy_limits, batch_rows=batch)
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()
            archive = self._write_retention_archive(entries, now=when, policy=policy) if entries else None
            deleted = {}
            skipped = 0
            if entries:
                with self.store._tx() as db:
                    eligible = {(entry["table"], entry["key"]): entry for entry in
                                self._retention_select(
                                    db, now=when, max_age_seconds=age,
                                    limits=policy_limits, batch_rows=batch)}
                    for entry in entries:
                        table, identity = entry["table"], entry["key"]
                        current = eligible.get((table, identity))
                        if current != entry:
                            skipped += 1
                            continue
                        if table == "s2_heard":
                            record = entry["record"]
                            changed = db.execute(
                                "DELETE FROM s2_heard WHERE fingerprint=? AND at=?"
                                " AND COALESCE(reservation_id,'')=COALESCE(?,'')"
                                " AND COALESCE(receipt_id,'')=COALESCE(?,'')",
                                (record["fingerprint"], record["at"],
                                 record["reservation_id"], record["receipt_id"])).rowcount
                        else:
                            changed = db.execute(
                                "DELETE FROM " + table + " WHERE id=? AND body=?",
                                (identity, entry["raw_body"])).rowcount
                        if changed:
                            name = table.removeprefix("s2_")
                            deleted[name] = deleted.get(name, 0) + changed
                        else:
                            skipped += 1
            deleted_total = sum(deleted.values())
            compaction = (self._retention_compact(deleted=deleted_total, force=force_compact)
                          if compact else {"attempted": False, "ran": False,
                                           "reason": "disabled for this run"})
            self._retention_observed = self._retention_observe()
            selected = {}
            for entry in entries:
                name = entry["table"].removeprefix("s2_")
                selected[name] = selected.get(name, 0) + 1
            self._retention_last = {
                "last_run_at": when,
                "duration_seconds": round(time.monotonic() - started, 6),
                "selected": selected, "deleted": deleted,
                "selected_total": len(entries), "batch_full": len(entries) >= batch,
                "deleted_total": deleted_total, "skipped_changed": skipped,
                "archive": archive, "compaction": compaction, "error": "",
            }
            return copy.deepcopy(self._retention_last)
        except Exception as exc:
            self._retention_last = {
                **copy.deepcopy(self._retention_last), "last_run_at": when,
                "duration_seconds": round(time.monotonic() - started, 6),
                "error": type(exc).__name__ + ": " + str(exc),
            }
            raise
        finally:
            self._retention_guard.release()

    def retention_status(self):
        """Return the last worker-produced census without touching SQLite.

        ``status()`` is used by the live assembly view on the event loop. A
        fresh count of the hundreds-of-megabytes store here would recreate the
        exact synchronous status-poll stall retention is meant to remove.
        ``run_retention`` refreshes this snapshot on its dedicated worker.
        """
        return {
            "policy": {"interval_seconds": self.RETENTION_INTERVAL_SECONDS,
                       "max_age_seconds": self.RETENTION_MAX_AGE_SECONDS,
                       "batch_rows": self.RETENTION_BATCH_ROWS,
                       "repeat_seconds": self.RETENTION_REPEAT_SECONDS,
                       "limits": dict(self.RETENTION_LIMITS),
                       "archive_directory": str(self.host.DATA_DIR / "system2-audit")},
            "last": copy.deepcopy(self._retention_last),
            "observed": (copy.deepcopy(self._retention_observed)
                         if self._retention_observed else
                         {"pending": True,
                          "say": "the retention worker has not sampled the store yet"}),
            "next_due_at": (float(self._retention_last.get("last_run_at") or 0)
                            + self.RETENTION_INTERVAL_SECONDS),
            "busy": self._retention_guard.locked(),
        }

    def status(self, copy_plans=True):
        # #1070: copy_plans=False hands the live plan lists to a caller that
        # only serialises them at once (json.dumps holds the GIL for its whole
        # run, so no other thread can change a plan underneath it); every
        # other caller gets its own copy as before.
        plans = copy.deepcopy(self._plans) if copy_plans else self._plans
        event_plans = copy.deepcopy(self._event_plans) if copy_plans else self._event_plans
        return {"version": 1, "config": dict(self.config), "enabled": self.enabled,
                "at": time.time(), "refreshed_at": self._last_refresh,
                "hours": plans,
                "work": {k: copy.deepcopy(v) for k, v in self._work.items() if k not in ("calls", "template")},
                # #1084: every sitting in progress, one per free lane.
                "works": [{k: copy.deepcopy(v) for k, v in w.items() if k not in ("calls", "template")}
                          for w in self._works.values()],
                "lanes": self._lanes,
                "errors": list(self._errors[-10:]),
                "inventory": {"candidates": len(self._candidates),
                              "ready": sum(x["ready"] for x in self._candidates)},
                "paused": self.host.radio_paused(), "on": bool(self.host._RADIO.get("on")),
                "repeat_seconds": 3600, "events": self.store.events(limit=100),
                "jobs": self.store.jobs(states=["pending", "working"], limit=100),
                "event_plans": event_plans,
                "retention": self.retention_status()}

    def trace(self, candidate_id, line_id=""):
        candidate = next((x for x in self._candidates if x["id"] == candidate_id), None)
        if candidate is None:
            for hour in self._plans + self._event_plans:
                for slot in hour.get("slots", []):
                    for allocation in slot.get("allocations", []):
                        if allocation["candidate"]["id"] == candidate_id:
                            candidate = allocation["candidate"]
        if candidate is None:
            candidate = self.store.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError("No retained candidate with that ID")
        source = copy.deepcopy(candidate.get("source") or {})
        trace_ids = source.get("system2_trace_ids") or [source.get("system2_trace_id")]
        calls, builds = [], []
        for trace_id in trace_ids:
            if not trace_id:
                continue
            path = self.host.DATA_DIR / "system2-traces" / (str(trace_id) + ".json")
            if path.is_file():
                build = json.loads(path.read_text("utf-8"))
                calls.extend(build.get("calls", []))
                builds.append({k: v for k, v in build.items() if k != "calls"})
        selected = [x for x in candidate.get("lines", []) if not line_id or x["id"] == line_id]
        if line_id and not selected:
            raise KeyError("No line with that ID")
        return {"candidate_id": candidate_id, "line_id": line_id, "lines": selected,
                "source": source, "calls": calls, "builds": builds,
                "provenance": "Captured requests and responses" if calls else "Retained historical entry",
                "limitations": [] if calls else ["Exact wire calls were not retained for this historical entry. The stored desk attribution may be approximate."]}

    def save_trace(self, work):
        directory = self.host.DATA_DIR / "system2-traces"
        directory.mkdir(exist_ok=True)
        path = directory / (work["trace_id"] + ".json")
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(work, ensure_ascii=False, indent=2, default=str) + "\n", "utf-8")
        temp.replace(path)

    async def prepare(self):
        """One bounded producer finishes useful work before commissioning more.

        No global cache-full or old commitment-sheet gate can veto this job.
        The actual model and voice providers still enforce shared admission.
        """
        if not self.enabled or self._prepare_lock.locked() or not self.host._RADIO.get("on"):
            return
        h = self.host
        async with self._prepare_lock:
            await self.refresh()
            # #1084: a second sitting takes a road nobody is already on.
            busy = {str(w.get("kind") or "") for w in self._works.values()
                    if w.get("state") == "preparing"}
            # Recap is deliberately claimed here: its guard below waits for
            # the measured preparation window before the slot. Deep
            # remains live-only because it has no scheduled shelf consumer.
            _cannot = set(getattr(self.host, "CANNOT_PREPARE", {}) or {})
            kinds = [k for k in ("ad", "manager", "caller", "gallery", "news",
                                 "banter", "track_talk", "recap")
                     if k not in busy and k not in _cannot]
            if not kinds:
                return
            # #1074: a 900 s lease renewed every 300 s (was 1800/600). The
            # renewer keeps a long sitting alive either way; what the shorter
            # lease bounds is the time a slot stays unclaimable when an
            # attempt dies without completing (see reclaim_jobs for restarts).
            # Keep the next hour first. Only evergreen ad/gallery work may
            # use spare on-air capacity farther out; news stays near its slot.
            lookahead = 3600
            if h.radio_paused():
                lookahead = int(self.config["horizon_hours"]) * 3600
            job = await asyncio.to_thread(                         # #1224
                self.store.claim_job, "system2-preparer", kinds=kinds,
                lease_seconds=900, lookahead_seconds=lookahead)
            if not job and not h.radio_paused() and self.config["horizon_hours"] > 1:
                job = await asyncio.to_thread(
                    self.store.claim_job, "system2-preparer",
                    kinds=[k for k in ("ad", "gallery") if k in kinds],
                    lease_seconds=900,
                    lookahead_seconds=int(self.config["horizon_hours"]) * 3600)
            if not job:
                return
            kind = job["kind"]
            work = {"trace_id": uuid.uuid4().hex, "job_id": job["id"], "slot_id": job["slot_id"],
                    "kind": kind, "started": time.time(), "state": "preparing", "calls": [],
                    "template": copy.deepcopy(job["template"]),
                    "generation_turns": int(self.config["generation_turns"])}
            self._work = work
            self._works[work["trace_id"]] = work
            token = WORK.set(work)
            changed = False

            async def renew():
                # #1070: a scene that waits on the tint lane can outlive the
                # 1800 s lease; without renewal its result was discarded as
                # stale when it finally arrived. Renew every ten minutes
                # while the work is live; a lost lease ends the renewer.
                while True:
                    await asyncio.sleep(300)
                    try:
                        await asyncio.to_thread(                   # #1224
                            self.store.renew_job, job["id"],
                            "system2-preparer", job["token"],
                            lease_seconds=900)
                    except System2Conflict:
                        return
            renewer = asyncio.create_task(renew())
            try:
                h.prep_context_set(kind)
                brief = str(job["template"].get("prompt") or "")
                # A recap describes observed events so far. It cannot be
                # truthfully written as a completed hour in advance.
                if kind == "recap" and float(job["template"]["start"]) - time.time() > self.recap_lead_seconds():
                    work["why"] = "Recap waits for its measured observed-hour preparation window"
                    self.store.complete_job(job["id"], "system2-preparer", job["token"], success=False, retry_after=60)
                    return
                h.alt_brief_set(brief + "\nSYSTEM2 PRODUCTION: Write one complete compact scene with a clear opening, substantive exchange, and close. "
                    "This scene fills part of the named segment; additional distinct scenes may follow. "
                    "Use the source's concrete details. Do not pad with greetings, repeated slogans or unrelated rhyme words. "
                    "Keep each turn to one or two short speakable sentences. Finish the thought within its own turn.")
                budget = settings_for_work({}).get("system2_budget") or {}
                minimum_scene = float(budget.get("reserved_seconds") or 0) + int(budget.get("turns") or 1) * 6 * 60 / 170
                available = min(float(job["template"].get("debt_seconds") or job["template"].get("target_seconds") or 90),
                                float(job["hard_deadline"]) - time.time())
                if kind not in ("track_talk", "ad", "station_id") and available < minimum_scene:
                    work.update(state="waiting", why="Remaining time cannot fit a complete scene; no padded or truncated scene will be commissioned",
                                available_seconds=available, minimum_estimated_scene_seconds=minimum_scene)
                    self.store.complete_job(job["id"], "system2-preparer", job["token"], success=False, retry_after=120,
                                            result={"why": work["why"], "available_seconds": available})
                    return
                rows = [row for row in h.alt_candidates(kind) if h.dialogue_row_viable(kind, row)
                        and not h.dialogue_row_ready(kind, row)]
                useful = []
                for row in rows:
                    entry = h.dialogue_entry(row)
                    if not entry or entry.get("tinting") or entry.get("preparing"):
                        continue
                    bound = entry.get("system2_slot")
                    if bound and bound != job["slot_id"] and self.binding_live(bound):
                        continue                    # #1390: a stale pin does not hold
                    if (kind == "recap" or job["template"].get("require_slot_binding")) and bound != job["slot_id"]:
                        continue
                    if self.content_gate_enabled("tint") and not h.tint_retry_due(entry, kind):
                        continue
                    # A long legacy scene cannot satisfy a shorter occurrence.
                    # Keep its accepted work for a slot where it can fit.
                    remaining = min(float(job["template"].get("seconds") or 90),
                                    float(job["template"].get("debt_seconds") or job["template"].get("target_seconds") or 90),
                                    max(0, float(job["hard_deadline"]) - time.time()))
                    script = str(entry.get("script_tinted") or entry.get("script") or "")
                    estimate = len(script.split()) * 60 / 170
                    if estimate + 8 > remaining:
                        continue
                    useful.append(row)
                useful.sort(key=lambda row: (-int((h.dialogue_entry(row) or {}).get("made") or 0),
                                             float(row.get("at") or 0)))
                event = job["template"].get("event") or {}
                if event:
                    work["action"] = "Prepare the operator's requested event"
                    pile = []
                    caller_name = str(event.get("caller_name") or "") if kind == "caller" else ""
                    caller_voice = await h.caller_line_voice(caller_name) if caller_name else ""
                    guest = None
                    if event.get("guest_id"):
                        guest = next((x for x in h.read_guests() if x.get("id") == event["guest_id"]), None)
                        if guest is None:
                            raise ValueError("The requested guest no longer exists")
                        guest = dict(guest)
                        guest["voice"] = str(guest.get("voice") or "") or await h.caller_line_voice(guest["name"])
                        if not guest["voice"]:
                            raise ValueError("The guest needs an available voice before recording")
                        work["guest"] = guest
                    angle = brief + ("\nGuest dossier: " + json.dumps(guest, ensure_ascii=False) +
                        "\nD is the studio guest. Give D at least two substantive turns in this scene, responding directly to the hosts; do not merely describe the guest." if guest else "")
                    if event.get("plot_id"):
                        prior = [x for x in self.store.events(limit=500) if x["payload"].get("plot_id") == event["plot_id"]
                                 and x.get("result", {}).get("heard")]
                        angle += "\nPreviously heard plot beats: " + json.dumps([x["payload"].get("brief") for x in prior], ensure_ascii=False)
                    if useful:
                        row = useful[0]
                        entry = h.dialogue_entry(row)
                        if not self.binding_live(entry.get("system2_slot")):
                            entry.pop("system2_slot", None)   # #1390: re-pin to this occurrence
                        stamp_entry(entry)
                        work["candidate_id"] = h.alt_sid(kind, row)
                        changed = bool(await h.larder_prepare(entry))
                    else:
                        await h.dj_banter(None, angle=angle, bank=True, bank_to=pile,
                            lines=max(11 if caller_name else 4, self.config["generation_turns"]),
                            caller_name=caller_name, caller_voice=caller_voice,
                            render_stream=True, whole=bool(caller_name))
                        for entry in pile:
                            if (guest and self.content_gate_enabled("segment_brief")
                                    and not any(marker == "D" for marker, _text in h.banter_turns(entry.get("script") or ""))):
                                entry.update(off_brief=True, system2_event_error="The guest has no speaking turn; the scene cannot fulfill this guest event")
                            entry.update(prep_kind=kind, system2_slot=job["slot_id"], system2_trace_id=work["trace_id"])
                            await h.larder_prepare(entry)
                            if kind == "banter":
                                h._LARDER.append(entry)
                            else:
                                h.shelf_put(kind, {"entry": entry, "seconds": float(entry.get("seconds") or 0)})
                        changed = bool(pile)
                elif useful:
                    row = useful[0]
                    entry = h.dialogue_entry(row)
                    if not self.binding_live(entry.get("system2_slot")):
                        entry.pop("system2_slot", None)       # #1390: re-pin to this occurrence
                    stamp_entry(entry)
                    work["action"] = "Finish retained tint and recordings"
                    work["candidate_id"] = h.alt_sid(kind, row)
                    entry["system2_trace_id"] = work["trace_id"]
                    changed = bool(await h.larder_prepare(entry))
                elif kind in ("recap", "deep"):
                    pile = []
                    hour_start = h._sched_hour_epoch(job["template"].get("hour_key") or h._sched_hour_key())
                    history = [{k: row.get(k) for k in ("artist", "title", "at")} for row in list(h._RADIO.get("history") or [])
                               if float(row.get("at") or 0) >= hour_start][-12:]
                    observed = [{k: row.get(k) for k in ("text", "who", "kind", "air_at")} for row in list(h._RADIO.get("chat") or [])
                                if row.get("aired") in ("box", "stream", "both") and float(row.get("air_at") or 0) >= hour_start][-30:]
                    work["observed_hour"] = {"records": history, "dialogue": observed, "as_of": time.time()}
                    await h.dj_banter(None, angle=brief + "\nRecap only these observed events SO FAR; do not invent the remaining minutes.\n" +
                                      json.dumps(work["observed_hour"], ensure_ascii=False),
                                      bank=True, bank_to=pile, lines=self.config["generation_turns"], render_stream=True)
                    for entry in pile:
                        entry.update(prep_kind=kind, system2_slot=job["slot_id"], system2_trace_id=work["trace_id"])
                        await h.larder_prepare(entry)
                        h.shelf_put(kind, {"entry": entry, "seconds": float(entry.get("seconds") or 0)})
                    changed = bool(pile)
                else:
                    work["action"] = "Write a new scene for this slot"
                    road = h.alt_prep_road(kind)
                    if road is not None:
                        changed = bool(await h.prep_measure(kind, road))
                fresh = []
                for row in h.alt_candidates(kind):
                    identity = h.alt_sid(kind, row)
                    entry = h.dialogue_entry(row) or row
                    if entry.get("system2_trace_id") == work["trace_id"] or identity == work.get("candidate_id"):
                        if self.content_gate_enabled("segment_brief"):
                            reviewer = getattr(h, "dialogue_topic_review", None)
                            if callable(reviewer):
                                review = reviewer(str(entry.get("script") or ""), brief)
                                entry["system2_topic_review"] = review
                                entry["topic_contract"] = str(review.get("topic") or "")
                                if review.get("checked") and not review.get("ok"):
                                    entry["off_brief"] = True
                                    entry["system2_event_error"] = (
                                        "Topic continuity failed: "
                                        + "; ".join(review.get("faults") or []))[:700]
                                    work.setdefault("topic_rejected", []).append({
                                        "candidate": identity,
                                        "topic": review.get("topic"),
                                        "score": review.get("score"),
                                        "faults": review.get("faults")})
                        candidate = await asyncio.to_thread(self.candidate, kind, row)
                        if kind == "recap" and self.recap_matches(job["template"], candidate, entry):
                            if candidate["ready"] and candidate["eligible"] and candidate["seconds"] > 0:
                                # The shelf's stored seconds must come from verified takes.
                                row["seconds"] = entry["seconds"] = candidate["seconds"]
                        fresh.append(candidate)
                # #1074: an attempt that made no model call (the tint lane
                # refused every ask) rests two minutes, not thirty seconds -
                # the same row was re-claimed twice a minute with a full
                # refresh each time and nothing to show for it.
                self.media.checkpoint_preparation(pantry=True, larder=kind == "banter")
                self.store.complete_job(job["id"], "system2-preparer", job["token"], candidates=fresh,
                                         success=changed,
                                         retry_after=(120 if not changed and not work.get("calls") else 30))
                work.update(state="ready" if any(x["ready"] for x in fresh) else "retained" if fresh else "waiting",
                             candidate_ids=[x["id"] for x in fresh], changed=changed)
            except asyncio.CancelledError:
                work["state"] = "interrupted"
                try:
                    self.store.complete_job(job["id"], "system2-preparer", job["token"], success=False, retry_after=0)
                except System2Conflict:
                    pass
                raise
            except Exception as exc:
                work.update(state="error", error=str(exc)[:500])
                self.error("prepare:" + kind, exc)
                try:
                    self.store.complete_job(job["id"], "system2-preparer", job["token"], success=False, retry_after=60)
                except System2Conflict:
                    pass
            finally:
                renewer.cancel()
                work["finished"] = time.time()
                self.save_trace(work)
                self._works.pop(work["trace_id"], None)
                WORK.reset(token)
                h.alt_brief_clear()
                h.prep_context_clear()
                self._last_refresh = 0

    def prepare_spawn(self):
        """#1084: start one more sitting when a lane is free. The prepare
        loop used to await one job at a time, so the second lane was left
        to the legacy keepers; now each sitting is its own task."""
        if not self.enabled or self._prepare_lock.locked():
            return None
        return asyncio.create_task(self.prepare(), name="system2:prepare")

    def _publish_clock(self, slot):
        """Publish one System2 occurrence without touching legacy persistence."""
        radio = self.host._RADIO
        if not slot:
            radio.update(sched_kind="", sched_prompt="", sched_slot={}, sched_pos={}, sched_first=False)
            return {}
        selected = {**copy.deepcopy(slot), "id": slot["template_id"], "kind": slot["kind"],
                    "system2_slot_id": slot["id"], "occurrence": slot["id"], "engine": "system2"}
        radio.update(sched_kind=slot["kind"], sched_prompt=slot.get("prompt", ""), sched_slot=selected,
            sched_pos={"slot_id": slot["template_id"], "started": slot["start"], "occurrence": slot["id"],
                       "hour": slot.get("hour_key"), "index": slot["ordinal"], "preset": "system2",
                       "deadline": slot["deadline"]}, sched_first=False)
        return copy.deepcopy(selected)

    def current_clock(self):
        """Wall-clock slot, or a due event with a currently owned reservation.

        Polling cannot claim an event, start work, or advance the legacy clock.
        An unready/merely queued event does not displace the configured hour.
        """
        if not self.enabled:
            return {}
        now = time.time()
        active_events = [slot for hour in self._event_plans for slot in hour["slots"]
                         if slot["start"] <= now < slot["deadline"]]
        if active_events:
            reservations = self.store.reservations(states=["reserved", "playing", "suspended"], limit=1000)
            for slot in active_events:
                event = self.store.get_event(slot["event_id"])
                if not event or event["state"] != "working" or event.get("lease_until", 0) <= now:
                    continue
                if any(r["slot_id"] == slot["id"] and r["revision"] == slot["revision"]
                       and r.get("owner") == event.get("owner")
                       and (r["state"] != "reserved" or r.get("lease_until", 0) > now)
                       for r in reservations):
                    return self._publish_clock(slot)
        current = next((slot for hour in self._plans for slot in hour["slots"]
                        if slot["start"] <= now < slot["deadline"]), None)
        return self._publish_clock(current)

    def current_slot_brief(self):
        """#1224: the running occurrence, WITHOUT the deep copies.

        _publish_clock deep-copies the slot twice - and a slot carries
        its prompt and every allocation, and an allocation carries the
        whole candidate. _ready_slot_window asks this question on every
        cupboard check for every road, and reads four fields of the
        answer. Measured: `outside app.py` (which is copy.py) was 115s
        of a 185s freeze in ten minutes.

        The _RADIO side effect is kept, but paid only when the
        occurrence actually changes rather than on every read. An active
        event slot falls through to the full road - events are rare and
        need the reservation check.
        """
        if not self.enabled:
            return {}
        now = time.time()
        if any(slot["start"] <= now < slot["deadline"]
               for hour in self._event_plans for slot in hour["slots"]):
            return self.current_clock()
        slot = next((s for hour in self._plans for s in hour["slots"]
                     if s["start"] <= now < s["deadline"]), None)
        ident = (slot or {}).get("id") or ""
        if ident != self._clock_seen:
            self._clock_seen = ident
            self._publish_clock(slot)
        if not slot:
            return {}
        return {"occurrence": slot["id"], "id": slot["template_id"],
                "kind": slot["kind"], "deadline": slot["deadline"],
                "start": slot["start"], "revision": slot.get("revision")}

    def _track_position(self):
        """Actual record clock; short links belong only to its opening or ending."""
        h = self.host
        track = h._RADIO.get("now") or {}
        try:
            started = float(h._RADIO.get("started") or 0)
            length = float(track.get("seconds") or 0)
            at = time.time()
            if not track.get("id") or not all(math.isfinite(x) for x in (started, length, at)):
                return None
            if started <= 0 or length <= 0 or not started <= at < started + length:
                return None
            if not h.now_really_playing(slack=2.0):
                return None
            elapsed = at - started
            window = min(45.0, length / 2)
            if elapsed < window:
                part, deadline = "intro", started + window
            elif length - elapsed <= window:
                part, deadline = "outro", started + length
            else:
                return None
            return {"track_id": str(track["id"]), "started": started, "part": part,
                    "position_seconds": elapsed, "at": at, "deadline": deadline}
        except (ValueError, TypeError, AttributeError):
            return None

    async def dispatch(self):
        if not self.enabled or not self.host._RADIO.get("on") or self.host.radio_paused() or self._dispatch_lock.locked():
            return False
        h = self.host
        async with self._dispatch_lock:
            await self.refresh()
            now = time.time()
            event_slots = [slot for hour in self._event_plans for slot in hour["slots"]
                           if slot["start"] <= now < slot["deadline"] and slot["allocations"]]
            slots = event_slots + [slot for hour in self._plans for slot in hour["slots"] if slot["start"] <= now < slot["deadline"]]
            if not slots:
                return False
            slot = slots[0]
            track_position = None
            if slot["kind"] == "track_talk":
                track_position = self._track_position()
                if not track_position:
                    return False
                matching = [c for c in self._candidates if c.get("kind") == "track_talk"
                    and c.get("track_id") == track_position["track_id"] and c.get("part") == track_position["part"]
                    and c.get("ready") and c.get("eligible")
                    and now + c["seconds"] <= min(slot["deadline"], track_position["deadline"])]
                selected = None
                for candidate in sorted(matching, key=lambda c: (c["seconds"], c["id"])):
                    try:
                        selected = await asyncio.to_thread(    # #1224
                            self.store.allocate_current, slot["id"],
                            candidate["id"],
                            expected_revision=slot["revision"])
                        break
                    except System2Conflict:
                        continue
                if selected is None:
                    return False
                slot.update(selected)
            # Publish the same clock to transport deadline checks and panels.
            self._publish_clock(slot)
            if slot.get("non_dialogue"):
                if slot["id"] not in self._record_slots:
                    h._schedule_pin_record()
                    self._record_slots.add(slot["id"])
                    if h.track_may_cut("System2 record entry"):
                        h.dj_skip()
                return False
            for allocation in slot["allocations"]:
                candidate = allocation["candidate"]
                if not self.recap_matches(slot, candidate):
                    self.refuse(slot, candidate, "Recap belongs to another observed hour")
                    continue
                if (slot["id"], candidate["id"]) in self._dispatched:
                    continue
                live = self._rows.get(candidate["id"])
                if live is None:
                    continue
                kind, row = live
                if not self.recap_matches(slot, candidate, h.dialogue_entry(row) or row):
                    self.refuse(slot, candidate, "Recap shelf row belongs to another observed hour")
                    continue
                resolved = await asyncio.to_thread(self.media.resolve, kind, row)
                takes = resolved["takes"]
                if not resolved["ready"]:
                    self.refuse(slot, candidate, "; ".join(resolved.get("why") or ["the recording is not ready"]))
                    continue
                # #1074: the air road's own fit test, asked BEFORE a reservation
                # is written rather than discovered after one. Same arithmetic
                # as the assembled stream pays: every clip, the beat between
                # clips, the box tail, the broadcast lead and the page's air.
                # Not for an event slot: current_clock() publishes an event
                # occurrence only once its reservation is owned, which is
                # after this point, so the road's window would not match yet.
                if kind != "track_talk" and not slot.get("event_id"):
                    try:
                        beat = max(h.CONCAT_BEAT) if getattr(h, "CONCAT_BEAT", None) else 0.0
                        tail = max(0.0, float(os.getenv("BOX_TAIL_MS", "900"))) / 1000.0
                        length = float(resolved.get("seconds") or 0) + max(0, len(takes) - 1) * beat + tail
                        fits = h._ready_round_fits(kind, takes, {"occurrence": slot["id"], "slot_id": slot["template_id"],
                                                                "kind": kind, "deadline": slot["deadline"]}, seconds=length)
                    except Exception:
                        fits = True
                    if not fits:
                        self.refuse(slot, candidate, "the complete recording (%.0fs) no longer fits the running occurrence before %s"
                                    % (length, time.strftime("%H:%M:%S", time.localtime(slot["deadline"]))))
                        continue
                # Admission is checked again after assembly and immediately
                # before publication by can_handoff below.
                try:
                    # #1400: OFF THE LOOP. reserve() is a write - BEGIN
                    # IMMEDIATE, an INSERT and a commit that fsyncs - and until
                    # the request_id index it also decoded 99 MB of reservation
                    # bodies first; py-spy found the main thread inside it in a
                    # fifth of its samples. #1325's rule, one road over: a
                    # receipt is not worth the event loop, and neither is a
                    # reservation.
                    reservation = await asyncio.to_thread(
                        self.store.reserve, slot["id"], candidate["id"], "system2-air",
                        expected_revision=slot["revision"], lease_seconds=300,
                        request_id=uuid.uuid4().hex)
                except System2Conflict:
                    continue
                proof = {"reservation_id": reservation["id"], "owner": "system2-air", "token": reservation["token"],
                         "slot_id": slot["id"], "candidate_id": candidate["id"]}
                if slot.get("event_id"):
                    event = self.store.claim_event("system2-air", event_id=slot["event_id"], lease_seconds=1800)
                    if not event:
                        self.store.release(reservation["id"], "system2-air", token=reservation["token"], reason="Event is no longer due")
                        continue
                    proof.update(event_id=event["id"], event_token=event["token"])
                entry = copy.deepcopy(resolved["entry"])
                entry.update(prep_kind=kind, _system2=proof,
                             _ready_slot={"occurrence": slot["id"], "slot_id": slot["template_id"],
                                          "kind": kind, "deadline": slot["deadline"]})
                if kind == "track_talk":
                    entry["_system2_track_position"] = copy.deepcopy(track_position)
                    entry["_ready_slot"]["deadline"] = min(slot["deadline"], track_position["deadline"])
                handed = False

                def _no(why):
                    # [#1191] THE REASON, ON THE HOST'S REGISTER. app.py's
                    # _burst_refusal_why reads _HANDOFF_NO when it is fresh;
                    # this check answered a bare False for six different
                    # reasons and Segment 11032 (2026-09-16 08:36:30Z) was
                    # withdrawn as "the caller's own check said no".
                    try:
                        h._HANDOFF_NO.update({"at": time.time(), "why": str(why)[:220]})
                    except Exception:  # noqa: BLE001
                        pass
                    return False

                def _grace():
                    # [#1191] THE AIR ROAD'S OWN ALLOWANCE, handed to the
                    # store. #1166: "a finished segment may run past the
                    # fold rather than not run at all" - app.py measures
                    # that with segment_overrun() and the store measured
                    # nothing, which is the 3.50 s that lost Segment 11032.
                    # Same function, same moment, so they cannot disagree.
                    try:
                        return max(0.0, min(300.0, float(
                            h.segment_overrun(float(slot.get("deadline") or 0), kind))))
                    except Exception:  # noqa: BLE001
                        return 0.0

                def validate():
                    if not self.enabled:
                        return _no("System2 is switched off")
                    if h.radio_paused() or not h._RADIO.get("on"):
                        return _no("the station is paused" if h.radio_paused() else "the station is off")
                    if kind == "track_talk":
                        current_position = self._track_position()
                        if not current_position or any(current_position[key] != track_position[key] for key in ("track_id", "started", "part")):
                            return _no("the record moved on - this talk was written for %s (%s)"
                                       % (str(track_position.get("track_id") or "?")[:24],
                                          str(track_position.get("part") or "?")))
                        if time.time() + resolved["seconds"] > min(slot["deadline"], current_position["deadline"]):
                            return _no("the talk runs %ds and its record has %ds left"
                                       % (int(resolved["seconds"]),
                                          int(max(0.0, min(slot["deadline"], current_position["deadline"]) - time.time()))))
                    current = self.media.resolve(kind, row)
                    if not current["ready"]:
                        return _no("the recording is no longer ready: "
                                   + "; ".join(current.get("why") or ["no reason given"])[:120])
                    if self.media.signature(current) != self.media.signature(resolved):
                        return _no("the recording changed between staging and delivery "
                                   "(a take's text, voice, key or audio hash differs)")
                    allow = _grace()
                    got = self.store.validate_reservation(
                        proof["reservation_id"], proof["owner"], token=proof["token"], grace=allow)
                    if got["allowed"]:
                        return True
                    reason = str(got.get("reason") or "not allowed")
                    res = got.get("reservation") or {}
                    held = int(time.time() - float(res.get("reserved_at") or time.time()))
                    lease = int(float(res.get("lease_until") or 0) - float(res.get("reserved_at") or 0))
                    if reason == "reservation_lease_expired":
                        # [#1191] A WAIT MUST NOT COST THE ROUND. The lease
                        # ran out while the round waited for the floor and
                        # for the page's sold air - a wait the station
                        # imposed. Renew (same id, same token) and go on.
                        try:
                            renewed = self.store.renew_reservation(
                                proof["reservation_id"], proof["owner"],
                                token=proof["token"], lease_seconds=300)
                        except Exception as exc:  # noqa: BLE001
                            renewed = {"renewed": False,
                                       "reason": type(exc).__name__ + ": " + str(exc)[:80]}
                        if renewed.get("renewed"):
                            try:
                                h.pipeline_log("system2", "the %ds reservation lease had run out %ds "
                                               "after it was taken; renewed at the hand-over and the "
                                               "round goes out (#1191)" % (lease, held))
                            except Exception:  # noqa: BLE001
                                pass
                            return True
                        reason = ("reservation_lease_expired and it could not be renewed: "
                                  + str(renewed.get("reason") or "?"))
                    left = float(slot.get("deadline") or 0) - time.time()
                    if reason == "measured_duration_misses_deadline":
                        # [#1191] IN NUMBERS, because this is the one that
                        # threw away written and rendered work: the round's
                        # own length against the room left, and the grace
                        # the air road already allowed it.
                        return _no("the %s round runs %.1fs, its entry has %.1fs left and %.0fs of grace, "
                                   "so it overruns by %.1fs - it fitted with %.0fs to spare when it was "
                                   "reserved %ds ago and the wait since is what cost it"
                                   % (kind, float(resolved.get("seconds") or 0), max(0.0, left), allow,
                                      max(0.0, float(resolved.get("seconds") or 0) - left - allow),
                                      max(0.0, float(slot.get("deadline") or 0)
                                          - float(res.get("reserved_at") or 0)
                                          - float(resolved.get("seconds") or 0)),
                                      held))
                    return _no("System2's reservation is no longer valid (%s) - reserved %ds ago with a "
                               "%ds lease, the entry has %ds left" % (reason, held, lease, int(max(0.0, left))))

                def handoff():
                    nonlocal handed
                    if handed:
                        return
                    # [#1191] the same allowance validate() was given, or
                    # mark_dispatched raises System2Conflict THROUGH the
                    # hand-over for a deadline validate() had accepted.
                    self.store.mark_dispatched(proof["reservation_id"], proof["owner"],
                                               token=proof["token"], grace=_grace())
                    self._dispatched[(slot["id"], candidate["id"])] = proof
                    handed = True

                h._READY_SHELF_BUSY.add(id(row))
                failed = False
                try:
                    said = await self.media.deliver(resolved, handoff, validate, entry_overrides=entry)
                    failed = not bool(said)
                    return bool(said)
                finally:
                    h._READY_SHELF_BUSY.discard(id(row))
                    if not handed or failed:
                        self.refuse(slot, candidate, self.media.last_refusal or "the transport refused the recording")
                        self.store.release(proof["reservation_id"], proof["owner"], token=proof["token"],
                                           reason="Transport refused the recording: " + str(self.media.last_refusal or "")[:160])
                        self._dispatched.pop((slot["id"], candidate["id"]), None)
                        if proof.get("event_id"):
                            self.store.release_event(proof["event_id"], proof["owner"], proof["event_token"],
                                                     reason="Transport refused the recording", retry_after=1)
            return False

    def acknowledge(self, entry):
        proof = entry.get("_system2") or {}
        if not proof:
            return
        result = self.store.ack(proof["reservation_id"], proof["owner"], proof["reservation_id"] + ":complete",
                                token=proof["token"], completed=True, audible=True)
        if not result.get("changed"):
            return
        if proof.get("event_id"):
            self.store.finish_event(proof["event_id"], proof["owner"], proof["event_token"],
                                    result={"heard": True, "reservation_id": proof["reservation_id"]})
        live = self._rows.get(proof["candidate_id"])
        if live:
            kind, row = live
            row["aired_at"] = time.time()
            row["aired"] = int(row.get("aired") or 0) + 1
            row["taken_at"] = time.time()
            self.host._pantry_save(True)
        self._last_refresh = 0

    def acknowledge_line(self, clip, row, receipt_id):
        proof = (clip.get("ready_round") or {}).get("_system2") or {}
        text = str(row.get("remember_text") or row.get("text") or "")
        if text:
            self.store.record_external(text, receipt_id=receipt_id, reservation_id=proof.get("reservation_id", ""))

    # #1191: how much of a finished round may already have been heard
    # before the whole thing is held back. See repeat_allowed.
    STALE_SHARE_ALLOWED = 0.5

    def repeat_allowed(self, texts, entry=None):
        """#1191: ONE STALE LINE MAY NOT VETO A WHOLE FINISHED ROUND.

        `can_play` fingerprints every line and refuses the set if ANY of
        them was heard inside the repeat window. For a round that is
        written, tinted and RECORDED, that is a very blunt instrument: a
        memo from upstairs opens with the booth's stock framing ("the
        manager is paging us again..."), and the moment that one line
        goes out anywhere - in banter, in a different memo - every
        manager round carrying it is held back for an hour.

        Measured on the live station: the manager last aired at 04:52,
        three lines, while 26 recorded rounds sat reachable and the air's
        own door said it would take one. Asking for one by hand produced
        exactly this refusal.

        So the question asked is how much of the round is stale rather
        than whether any of it is. A round that is mostly fresh goes out
        and the repeated line rides along; a round that is mostly a
        repeat is still refused, which is the thing the gate is for."""
        if not self.content_gate_enabled("repetition"):
            return True
        proof = (entry or {}).get("_system2") or {}
        reservation = proof.get("reservation_id", "")
        verdict = self.store.can_play(texts, reservation_id=reservation)
        if verdict["allowed"]:
            return True
        lines = [t for t in ([texts] if isinstance(texts, str) else list(texts))
                 if isinstance(t, str) and t.strip()]
        if verdict["reason"] != "heard_within_one_hour" or len(lines) < 2:
            self.host.pipeline_log("system2", "Playback waits for unique dialogue: " + verdict["reason"])
            return False
        stale = 0
        for line in lines:
            try:
                if not self.store.can_play([line], reservation_id=reservation)["allowed"]:
                    stale += 1
            except Exception:
                stale += 1
        if stale and stale <= int(len(lines) * self.STALE_SHARE_ALLOWED):
            self.host.pipeline_log(
                "system2",
                "%d of %d lines were heard recently - the rest of the round is "
                "fresh, so it airs rather than being held back whole (#1191)"
                % (stale, len(lines)))
            return True
        self.host.pipeline_log(
            "system2",
            "Playback waits for unique dialogue: %s (%d of %d lines already heard)"
            % (verdict["reason"], stale, len(lines)))
        return False

    def queue_event(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Expected an event object")
        kind = str(payload.get("kind") or "")
        if kind not in ("call_in", "station_event", "guest", "music_request", "plotline"):
            raise ValueError("Choose call_in, station_event, guest, music_request or plotline")
        identity = str(payload.get("request_id") or uuid.uuid4().hex)
        now = time.time()
        existing = next((event for event in self.store.events(limit=1000) if event["request_id"] == identity), None)
        at = float(payload.get("air_at") or (existing or {}).get("payload", {}).get("air_at") or now)
        seconds = float(payload.get("seconds") or 90)
        if (not existing and not now - 5 <= at <= now + 7 * 86400) or not 15 <= seconds <= 600:
            raise ValueError("Event time must be within seven days; duration must be 15–600 seconds")
        brief = str(payload.get("brief") or "").strip()
        if kind != "music_request" and not 1 <= len(brief) <= 6000:
            raise ValueError("A brief of up to 6000 characters is required")
        timing = str((existing or {}).get("payload", {}).get("timing") or
                     ("scheduled" if payload.get("air_at") else "asap"))
        body = {"air_at": at, "seconds": seconds, "brief": brief, "timing": timing,
                "label": str(payload.get("label") or "")[:100]}
        if kind == "call_in":
            body["caller_name"] = str(payload.get("caller_name") or "Caller").strip()[:60]
        if kind == "guest":
            guest_id = str(payload.get("guest_id") or "")
            if not any(x.get("id") == guest_id for x in self.host.read_guests()):
                raise ValueError("Choose a saved guest")
            body["guest_id"] = guest_id
        if kind == "music_request":
            track = self.host.music_track(str(payload.get("track_id") or ""))
            if not track:
                raise ValueError("Choose a track present in the music library")
            body["track_id"] = str(track["id"])
        if kind == "plotline":
            body["plot_id"] = str(payload.get("plot_id") or identity)[:100]
        # ASAP means the next complete scene boundary after preparation. Its
        # preparation window is explicit; requested duration remains the scene
        # budget. A fixed scheduled time retains its original hard deadline.
        window = max(900, seconds) if timing == "asap" else seconds
        event = self.store.enqueue_event(kind, body, request_id=identity, due_at=at,
                                        deadline=at + window, priority=int(payload.get("priority") or 0))
        self._last_refresh = 0
        return event

    async def events_tick(self):
        if not self.enabled:
            return
        # #1320: the poll itself waits in its own thread (see _STORE_POOL).
        # Identical query, identical rows, identical order - the only
        # change is that the event loop is free while it happens.
        #
        # The claim/finish writes below stay on the loop on purpose: they
        # run only when a pending music_request actually exists, which is
        # rare (s2_events measured empty), so they are not what the meter
        # was catching and moving them would widen the patch for nothing.
        pending = await asyncio.get_running_loop().run_in_executor(
            _STORE_POOL,
            lambda: self.store.events(states=["pending"], limit=100))
        for event in pending:
            if event["kind"] != "music_request":
                continue
            claimed = self.store.claim_event("system2-events", event_id=event["id"])
            if not claimed:
                continue
            track = self.host.music_track(event["payload"]["track_id"])
            if track:
                queue = self.host._RADIO.setdefault("requests", [])
                if not any(x.get("system2_event_id") == event["id"] for x in queue):
                    queue.append({**dict(track), "system2_event_id": event["id"]})
            self.store.finish_event(event["id"], "system2-events", claimed["token"],
                                    result={"queued": bool(track), "heard": False,
                                            "why": "Queued for the next record boundary" if track else "Track is no longer in the library"})


def capture_model_request(messages, options, model, stage="model", response=None):
    """Called at the actual provider boundary; no guessed shell commands."""
    work = WORK.get()
    if work is None:
        return
    work.setdefault("calls", []).append({"at": time.time(), "stage": stage,
        "model": model, "messages": copy.deepcopy(messages), "options": copy.deepcopy(options),
        "response": response, "transport": "Ollama HTTP request"})


class _Host:
    def __init__(self, namespace):
        object.__setattr__(self, "namespace", namespace)

    def __getattr__(self, name):
        try:
            return self.namespace[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def install(app, namespace):
    from fastapi import Header, HTTPException, Request
    from fastapi.responses import FileResponse, HTMLResponse, Response

    # Local annotations are resolved by FastAPI against module globals.
    globals()["Request"] = Request
    host = _Host(namespace)
    holder = {}

    def runtime():
        if "runtime" not in holder:
            holder["runtime"] = System2Runtime(host)
        return holder["runtime"]

    namespace["_system2"] = runtime

    @app.on_event("startup")
    async def start_system2():
        # #1074: whatever the last run was preparing when it stopped is this
        # run's to finish, not a 30-minute hole in the plan.
        try:
            lost = runtime().store.reclaim_jobs("system2-preparer")
            if lost:
                host.pipeline_log("system2", "(#1074) %d preparation job(s) the last run left working are pending again: %s"
                                  % (len(lost), ", ".join(lost)[:400]))
        except Exception as exc:
            runtime().error("startup", exc)
        # 2026-09-10: and the RESERVATIONS the last run left on air. One of
        # those, stuck in 'playing' under a dead lease, forbids its hour
        # from ever being planned again - thirteen had accumulated over two
        # days and the hour on air had one, so plan_hour raised on every
        # refresh and the whole running order read "unplanned" while the
        # shelf held hundreds of finished rounds.
        try:
            freed = runtime().store.reclaim_reservations("system2-air")
            if freed:
                host.pipeline_log("system2", "%d reservation(s) the last run left playing under a dead lease "
                                  "were released - their hours can be planned again: %s"
                                  % (len(freed), ", ".join(freed)[:400]))
        except Exception as exc:
            runtime().error("startup", exc)

        async def plan_loop():
            await asyncio.sleep(8)
            while True:
                try:
                    await runtime().refresh()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    runtime().error("planning", exc)
                await asyncio.sleep(15)

        async def prepare_loop():
            await asyncio.sleep(10)
            sittings = set()
            while True:
                try:
                    # #1084: one sitting per free lane, each its own task;
                    # a sitting's own exception is recorded by the task.
                    task = runtime().prepare_spawn()
                    if task is not None:
                        sittings.add(task)
                        task.add_done_callback(sittings.discard)
                        task.add_done_callback(lambda t: (
                            runtime().error("worker", t.exception())
                            if not t.cancelled() and t.exception() else None))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    runtime().error("worker", exc)
                await asyncio.sleep(3)

        async def event_loop():
            while True:
                try:
                    await runtime().events_tick()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    runtime().error("events", exc)
                await asyncio.sleep(1)

        async def retention_loop():
            # Let the first inventory/plan refresh establish the protected
            # horizon before considering any historical row for retention.
            await asyncio.sleep(90)
            while True:
                try:
                    await asyncio.to_thread(runtime().run_retention)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    runtime().error("retention", exc)
                await asyncio.sleep(runtime().RETENTION_INTERVAL_SECONDS)

        holder["tasks"] = [
            asyncio.create_task(plan_loop(), name="system2:plan"),
            asyncio.create_task(prepare_loop(), name="system2:prepare-loop"),
            asyncio.create_task(event_loop(), name="system2:events"),
            asyncio.create_task(retention_loop(), name="system2:retention"),
        ]

    @app.on_event("shutdown")
    async def stop_system2():
        for task in holder.get("tasks", []):
            task.cancel()
        await asyncio.gather(*holder.get("tasks", []), return_exceptions=True)

    @app.get("/api/system2/status")
    async def status(authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        await runtime().refresh(want_status=False)
        # #1070: a megabyte of nested plans is serialised in one C call in a
        # worker thread rather than walked field by field on the event loop,
        # straight from the live plans (no copy first).
        body = await asyncio.to_thread(lambda: json.dumps(runtime().status(copy_plans=False), default=str))
        return Response(content=body, media_type="application/json")

    @app.post("/api/system2/settings")
    async def configure(request: Request, authorization: str | None = Header(default=None)):
        host.require_auth(authorization)
        try:
            runtime().configure(await request.json())
            return await runtime().refresh(force=True)
        except (ValueError, System2Conflict) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/system2/events")
    async def events(request: Request, authorization: str | None = Header(default=None)):
        host.require_auth(authorization)
        try:
            return runtime().queue_event(await request.json())
        except (ValueError, TypeError, System2Conflict) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/system2/script")
    async def script(hour: str, slot: str = "", authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        result = runtime().scripts(hour)
        if not result:
            raise HTTPException(404, "No retained hour")
        if slot:
            result["slots"] = [row for row in result["slots"] if row["slot_id"] == slot]
        return result

    @app.get("/api/system2/hours")
    async def hours(authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        return {"hours": [{"id": row["id"], "start": row["start"]} for row in runtime().store.hours(limit=168)
                          if not row["id"].startswith("event-")]}

    @app.get("/api/system2/hour")
    async def hour(hour: str, authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        result = runtime().store.get_hour(hour)
        if not result:
            raise HTTPException(404, "No retained hour")
        return runtime().include_drafts(result)

    @app.get("/api/system2/binding")
    async def binding(hour: str = "", authorization: str | None = Header(default=None)):
        """#1222: why each slot of an hour is bound, or is not."""
        host.require_read_auth(authorization)
        rt = runtime()
        identity = hour
        if not identity:
            now = time.time()
            for row in rt.store.hours(limit=24):
                if float(row["start"]) <= now < float(row["start"]) + 3600:
                    identity = row["id"]
                    break
        if not identity:
            raise HTTPException(404, "No hour on air")
        live = next((h["slots"] for h in rt._plans
                     if str(h.get("id")) == identity), None)
        got = await asyncio.to_thread(rt.store.explain_hour, identity, live)
        if not got:
            raise HTTPException(404, "No retained hour")
        empty = [s for s in got["slots"] if not s["allocations"]]
        stuck = [s for s in empty if s["room_seconds"] <= 0]
        got["say"] = (
            "%d of %d slot(s) carry nothing. %d of those are past their "
            "deadline and can never be filled. %d candidate(s) in the "
            "catalogue."
            % (len(empty), len(got["slots"]), len(stuck), got["candidates"]))
        return got

    @app.get("/api/system2/line")
    async def line(candidate: str, line: str = "", authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        try:
            return runtime().trace(candidate, line)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/system2/download")
    async def download(hour: str = "", slot: str = "", candidate: str = "", line: str = "",
                       format: str = "txt", authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        try:
            if candidate:
                data = runtime().trace(candidate, line)
                body = "\n\n".join(f"{x.get('who') or x.get('voice') or 'Speaker'}: {x['text']}" for x in data["lines"])
            else:
                data = runtime().scripts(hour)
                if not data:
                    raise KeyError("No retained hour")
                if slot:
                    data["slots"] = [x for x in data["slots"] if x["slot_id"] == slot]
                sections = []
                for section in data["slots"]:
                    sections.append(time.strftime("%H:%M", time.localtime(section["start"])) + " " + section["kind"])
                    for performance in section["performances"]:
                        sections.append(performance["script"])
                    if not section["performances"]:
                        sections.append("No complete performance has been staged for this segment.")
                    for draft in section.get("drafts", []):
                        sections.append("DRAFT — not staged\n" + draft.get("script", ""))
                body = "\n\n".join(sections)
            if format == "json":
                body = json.dumps(data, indent=2, ensure_ascii=False)
            elif format != "txt":
                raise ValueError("format must be txt or json")
            return Response(body + "\n", media_type="application/json" if format == "json" else "text/plain",
                headers={"Content-Disposition": f'attachment; filename="pinebox-system2-script.{format}"'})
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/system2/{name}")
    async def asset(name: str):
        if name not in ("system2.js", "system2.css"):
            raise HTTPException(404, "Unknown asset")
        return FileResponse(Path(__file__).parent / "frontend" / name)

    @app.get("/system2")
    async def page():
        return HTMLResponse('''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Pine Box System2</title>
<link rel="stylesheet" href="/system2/system2.css"><body><main id="system2"></main>
<script type="module">import {mount} from '/system2/system2.js'; mount(document.querySelector('#system2'));</script></body></html>''')

    return runtime
