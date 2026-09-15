"""The admission gate and the one playout controller.

    "Choose a ready replacement before it enters the committed script,
     then play it in order."

That sentence is the whole boundary. Planning may change its mind as often
as it likes; the admitted reading order may not change at all. This module
is the line between the two, and it is the only thing in the station that
is allowed to say a broadcast occurrence exists.

What it refuses to confuse (docs/sequential-script-playout-audit-2026-09-14.md):

  * A CONTENT id is not a PLAYBACK OCCURRENCE id. Playing the same sting
    twice is two occurrences with two positions in the script, and the
    second one is not a redraw of the first.
  * Announcing intent is not starting audio, and starting audio is not
    sound leaving a speaker. `_play_on_box` returning a player name means
    Home Assistant accepted a command. That is an ACCEPTANCE, recorded as
    one - never as `delivered`.
  * A ledger that tolerates its own failure is a record of what happened.
    It is not an instruction. This is the instruction: nothing may be
    dispatched that was not committed first, and a committed position is
    never rewritten - not by a failure, not by a retry, not by an hour
    rolling over, not by a restart.

The station is on air while this lands, so the controller ships in
OBSERVE mode: every verdict is computed and written down, and every
verdict is then allowed anyway. The caller measures a real day of
refusals before any of them is made to bite. See
docs/notes/admission-and-playout-2026-09-15.md for that procedure.

Nothing here imports app.py, touches a live store, opens a socket or
renders audio. It is given a directory and a clock and it is told things.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterable

SCHEMA_VERSION = 1

# ------------------------------------------------------------ vocabulary

ADMITTED = "admitted"          # committed; the reader owns this position
DISPATCHING = "dispatching"    # handed to a transport, no verdict yet
FINISHED = "finished"          # a terminal outcome has been recorded
WITHDRAWN = "withdrawn"        # never dispatched; the POSITION still stands

# Terminal outcomes. `delivered` is the only one that claims a listener
# heard it, and it must carry evidence that says how that was established.
DELIVERED = "delivered"        # audible evidence exists
ACCEPTED = "accepted"          # the command was acknowledged; audibility unproven
BLOCKED = "blocked"            # the transport declined before sending
INTERRUPTED = "interrupted"    # it started and was cut short
UNCERTAIN = "uncertain"        # no receipt of any kind came back
FAILED = "failed"              # an error on the way out
OUTCOMES = (DELIVERED, ACCEPTED, BLOCKED, INTERRUPTED, UNCERTAIN, FAILED)

LANES = ("speech", "sfx", "advert", "rescue", "music", "station", "reply")

# Why a dispatch would be refused. These names are the observe-mode census:
# whatever the caller reads off /api/admission before turning enforcement
# on is counted under exactly these.
UNADMITTED = "unadmitted"                    # nothing was committed for this audio
OUT_OF_ORDER = "out_of_order"                # committed, but not the reader's next
STALE_GENERATION = "stale_generation"        # a message from a previous player
DUPLICATE_DISPATCH = "duplicate_dispatch"    # this occurrence already went out
SLOT_PENDING = "slot_pending"                # a reserved slot in front is unfilled
WITHDRAWN_OCCURRENCE = "withdrawn"           # it was pulled before dispatch

MODE_OBSERVE = "observe"
MODE_ENFORCE = "enforce"


class AdmissionError(Exception):
    """A refusal the caller asked to be told about rather than merely counted."""


# --------------------------------------------------------- the adapter
#
# THREE OTHER MODULES ARE BEING WRITTEN BESIDE THIS ONE and none of them
# existed when this was compiled: script_manifest/manifest_store (record
# shapes and the durable store), speaker_session/line_alignment (accepted
# cuts) and conversation_assembly (finished audio plus its cue map).
#
# So nothing below reaches for a field by one name and dies when it is
# spelled another way. Every name this module reads is listed HERE, in one
# place, against the table in docs/notes/speaker-recording-and-script-
# assembly.md section 3. When those modules land, delete the aliases that
# turned out to be wrong; do not scatter `.get("or_this")` through the
# controller.


class Contracts:
    """The only place this module knows what a record is called."""

    ASSEMBLY_ID = ("assembly_id", "id")
    SCRIPT_REVISION = ("script_revision", "revision")
    # `final_sha256` from script_manifest.finished_conversation is
    # PREFIXED - "sha256:<64 hex>" - while conversation_assembly's
    # `final_audio_hash` is bare. `bare_digest` below is the only place
    # that difference is allowed to matter.
    AUDIO_HASH = ("final_audio_hash", "final_sha256", "audio_hash", "hash")
    CUE_MAP = ("final_cue_map", "cue_map", "cues", "rows")
    CUE_MAP_REVISION = ("cue_map_revision", "cue_revision", "cue_map_version")
    MEDIA = ("media", "final_media", "path", "url", "file")
    SECONDS = ("seconds", "duration_s", "length")
    SAMPLE_RATE = ("sample_rate", "final_sample_rate", "rate")
    FRAME_COUNT = ("frame_count", "final_frame_count", "frames")
    MIX = ("mix", "mix_settings")
    SESSION_ID = ("session_id", "performer_session", "performer_session_id")
    TAKE_ID = ("take_id", "master_take_id")

    # One cue = one spoken line occurrence inside the finished audio.
    CUE_ID = ("occurrence_id", "line_occurrence_id", "line_id", "id")
    CUE_ORDINAL = ("ordinal", "ord", "turn", "index")
    # `start_seconds` / `cue_end_seconds` / `speech_end_seconds` are what
    # conversation_assembly.py actually emits; the rest are the burst path's
    # own spellings and the feed's. Checked against that module on the day
    # it landed, not guessed.
    CUE_START = ("start_seconds", "start_s", "from", "from_s", "start",
                 "clip_from")
    CUE_END = ("cue_end_seconds", "end_s", "until", "until_s", "end",
               "clip_until")
    # "Retain separate speech-end and cue-end positions so an inserted
    # pause does not falsely start the next line." A burst row carries the
    # seam beat as `clip_tail`/`tail`; speech ends that much before the cue.
    CUE_SPEECH_END = ("speech_end_seconds", "speech_end_s",
                      "speech_until_s", "speech_end")
    CUE_TAIL = ("clip_tail", "tail", "tail_s")
    CUE_START_SAMPLE = ("cue_start_sample", "start_sample", "from_sample")
    CUE_END_SAMPLE = ("cue_end_sample", "end_sample", "until_sample")
    CUE_SPEECH_END_SAMPLE = ("speech_end_sample",)
    CUE_TEXT = ("text", "line_text", "spoken_text")
    CUE_WHO = ("who", "speaker", "actor")
    CUE_NAME = ("name", "actor_name")
    CUE_KIND = ("kind", "type")
    CUE_CUT = ("cut_id", "accepted_cut", "accepted_cut_id")

    @staticmethod
    def pick(record: Any, names: Iterable[str], default: Any = None) -> Any:
        if not isinstance(record, dict):
            return default
        for name in names:
            value = record.get(name)
            if value is not None and value != "":
                return value
        return default

    @staticmethod
    def number(record: Any, names: Iterable[str],
               default: float | None = None) -> float | None:
        value = Contracts.pick(record, names)
        try:
            out = float(value)
        except (TypeError, ValueError):
            return default
        if out != out or out in (float("inf"), float("-inf")):
            return default
        return out

    @staticmethod
    def bare_digest(value: Any) -> str:
        """A hex digest, however it was spelled.

        script_manifest writes "sha256:<64 hex>"; conversation_assembly
        writes the bare hex. Comparing the two literally would refuse a
        perfectly good assembly for a colon."""
        text = str(value or "").strip().lower()
        if ":" in text:
            text = text.rsplit(":", 1)[-1]
        return text

    @classmethod
    def raw_cues(cls, assembly: Any) -> list[dict[str, Any]]:
        cues = cls.pick(assembly, cls.CUE_MAP, [])
        if isinstance(cues, dict):                 # a map keyed by id
            cues = [dict(value, **({} if cls.pick(value, cls.CUE_ID) else {"id": key}))
                    for key, value in cues.items()]
        return [c for c in (cues or []) if isinstance(c, dict)]


def media_key(path: str) -> str:
    """The station's own name for a clip: the basename, query stripped.

    `_played_out_key` in app.py draws the same line, and the renderer's
    `soundingFile()` compares against exactly this - the last segment of
    `currentSrc` with its `?t=` cut off. Keying the gate on anything else
    would mean the view and the controller were naming different things."""
    raw = str(path or "").split("?")[0].replace("\\", "/")
    return raw.rsplit("/", 1)[-1]


def audio_key(path: str, sig: str = "") -> str:
    return media_key(path) + ("#" + str(sig) if sig else "")


# --------------------------------------------------------- audio identity

HASH_FULL = "sha256-full"
HASH_SPAN = "sha256-head-tail-size"
FULL_HASH_MAX = 8 * 1024 * 1024
SPAN_BYTES = 1024 * 1024


def audio_identity(path: str, *, resolve: Callable[[str], Any] | None = None,
                   full_hash_max_bytes: int = FULL_HASH_MAX) -> dict[str, Any]:
    """The exact identity of the bytes that are about to be broadcast.

    A whole-file sha256 of every welded round, on the live event loop, is a
    cost this station has already been measured being killed by - so a file
    over the cap is identified by its size plus its first and last mebibyte
    and THE METHOD IS WRITTEN DOWN. A hash whose method is not recorded is
    not evidence, and a hash that silently changes method between two
    records is worse than no hash at all."""
    out: dict[str, Any] = {"media": media_key(path), "path": str(path or ""),
                           "available": False, "bytes": 0, "hash": "",
                           "hash_method": "", "mtime_ns": 0}
    target = None
    try:
        target = resolve(path) if resolve else Path(str(path or "").split("?")[0])
    except Exception:  # noqa: BLE001
        target = None
    if not target:
        return out
    target = Path(target)
    try:
        info = target.stat()
    except OSError:
        return out
    if not target.is_file() or info.st_size <= 0:
        return out
    out.update(available=True, bytes=int(info.st_size),
               mtime_ns=int(getattr(info, "st_mtime_ns", 0) or 0),
               file=str(target))
    digest = hashlib.sha256()
    try:
        with open(target, "rb") as handle:
            if info.st_size <= full_hash_max_bytes:
                for block in iter(lambda: handle.read(1024 * 256), b""):
                    digest.update(block)
                out["hash_method"] = HASH_FULL
            else:
                digest.update(str(info.st_size).encode("ascii"))
                digest.update(handle.read(SPAN_BYTES))
                handle.seek(max(0, info.st_size - SPAN_BYTES))
                digest.update(handle.read(SPAN_BYTES))
                out["hash_method"] = HASH_SPAN
    except OSError:
        out.update(available=False, hash_method="")
        return out
    out["hash"] = digest.hexdigest()
    return out


def audio_seconds_hint(path: str, resolve: Callable[[str], Any] | None = None) -> float:
    """A length for a plain wav, read off its own header. No mutagen, no
    ffprobe, no import of the station. Anything else returns 0.0 and the
    caller says so rather than guessing."""
    try:
        target = resolve(path) if resolve else Path(str(path or "").split("?")[0])
        if not target:
            return 0.0
        target = Path(target)
        with open(target, "rb") as handle:
            head = handle.read(64)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            return 0.0
        size = target.stat().st_size
        rate = int.from_bytes(head[24:28], "little")
        byte_rate = int.from_bytes(head[28:32], "little")
        if byte_rate <= 0 or rate <= 0:
            return 0.0
        return max(0.0, (size - 44) / float(byte_rate))
    except Exception:  # noqa: BLE001
        return 0.0


# ------------------------------------------------------------- candidates


def candidate(*, lane: str, producer: str, assembly: dict[str, Any] | None = None,
              path: str = "", sig: str = "", seconds: float = 0.0,
              text: str = "", kind: str = "", label: str = "",
              reply: bool = False, meta: dict[str, Any] | None = None,
              candidate_id: str = "") -> dict[str, Any]:
    """A producer's SUBMISSION. It is not a broadcast and it carries no position."""
    return {"candidate_id": str(candidate_id or uuid.uuid4().hex[:20]),
            "lane": str(lane or "speech"), "producer": str(producer or "")[:120],
            "assembly": dict(assembly or {}),
            "path": str(path or ""), "sig": str(sig or ""),
            "seconds": float(seconds or 0.0), "text": str(text or "")[:400],
            "kind": str(kind or ""), "label": str(label or "")[:120],
            "reply": bool(reply), "meta": dict(meta or {})}


def welded_round_candidate(*, path: str, sig: str, rows: Iterable[dict[str, Any]],
                           length: float, producer: str, lane: str = "speech",
                           script_revision: str = "", assembly_id: str = "",
                           label: str = "",
                           meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """An EXISTING welded round, given an authoritative cue sheet.

        "Existing welded round files are useful: they already preserve
         internal audio order. Retain those files and give them an
         authoritative cue sheet rather than rebuilding voice generation."

    `rows` is the burst path's own per-turn timeline - the very numbers the
    booth marker is already driven off, AFTER the loudness-pass correction
    has been applied to them. They are not re-derived here and not
    re-scaled here. This records them, in order, as the cue map of the file
    that is about to air."""
    cues: list[dict[str, Any]] = []
    for ordinal, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue
        start = Contracts.number(row, Contracts.CUE_START, None)
        end = Contracts.number(row, Contracts.CUE_END, None)
        tail = Contracts.number(row, Contracts.CUE_TAIL, 0.0) or 0.0
        cue: dict[str, Any] = {
            "occurrence_id": str(Contracts.pick(row, Contracts.CUE_ID, "") or ""),
            "ordinal": ordinal,
            "start_s": start, "end_s": end,
            "who": str(Contracts.pick(row, Contracts.CUE_WHO, "") or ""),
            "name": str(Contracts.pick(row, Contracts.CUE_NAME, "") or ""),
            "kind": str(Contracts.pick(row, Contracts.CUE_KIND, "") or ""),
            "text": str(Contracts.pick(row, Contracts.CUE_TEXT, "") or "")[:400]}
        speech_end = Contracts.number(row, Contracts.CUE_SPEECH_END, None)
        if speech_end is None and end is not None:
            # The window ends on the seam beat the mixer glued on. Speech
            # ended before it, and that difference is the one thing that
            # stops an inserted pause starting the next line early.
            speech_end = max(float(start or 0.0), float(end) - float(tail or 0.0))
        cue["speech_end_s"] = speech_end
        cues.append(cue)
    assembly = {"assembly_id": str(assembly_id or ("welded-" + media_key(path))),
                "script_revision": str(script_revision or ""),
                "media": str(path or ""), "seconds": float(length or 0.0),
                "cue_map": cues, "cue_map_revision": "welded-round-1",
                "source": "existing welded round file"}
    return candidate(lane=lane, producer=producer, assembly=assembly,
                     path=path, sig=sig, seconds=float(length or 0.0),
                     label=label, meta=meta)


# --------------------------------------------------------------- verdicts


class Verdict:
    """What the gate decided, and what it WOULD have decided.

    In observe mode `allow` is true and `would_refuse` carries the truth.
    Nothing downstream may read `allow` as "this was in order"."""

    __slots__ = ("allow", "reason", "occurrence_id", "position", "lane",
                 "enforced", "would_refuse", "mode", "generation", "detail")

    def __init__(self, *, allow: bool, reason: str = "", occurrence_id: str = "",
                 position: int = -1, lane: str = "", enforced: bool = False,
                 would_refuse: bool = False, mode: str = MODE_OBSERVE,
                 generation: int = 0, detail: dict[str, Any] | None = None):
        self.allow = bool(allow)
        self.reason = str(reason or "")
        self.occurrence_id = str(occurrence_id or "")
        self.position = int(position)
        self.lane = str(lane or "")
        self.enforced = bool(enforced)
        self.would_refuse = bool(would_refuse)
        self.mode = str(mode)
        self.generation = int(generation)
        self.detail = dict(detail or {})

    def __bool__(self) -> bool:
        return self.allow

    def as_dict(self) -> dict[str, Any]:
        return {"allow": self.allow, "reason": self.reason,
                "occurrence_id": self.occurrence_id, "position": self.position,
                "lane": self.lane, "enforced": self.enforced,
                "would_refuse": self.would_refuse, "mode": self.mode,
                "generation": self.generation, "detail": self.detail}

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return "Verdict(%s)" % json.dumps(self.as_dict(), sort_keys=True)


# ------------------------------------------------------------- the store


class AdmissionStore:
    """Durable, atomic, recoverable. One append-only ledger and a snapshot.

    An admission is ONE line, written and flushed before the caller is told
    it happened. A crash mid-line leaves a partial last line, which `load`
    DISCARDS - so the admission never happened, rather than half-happened.
    That is the whole recovery story for "crashes around admission"."""

    LEDGER = "ledger.jsonl"
    STATE = "state.json"

    def __init__(self, root: Any, *, durable: bool = True,
                 checkpoint_every: int = 64, keep_events: int = 20000):
        self.root = Path(root)
        self.durable = bool(durable)
        self.checkpoint_every = max(1, int(checkpoint_every))
        self.keep_events = max(200, int(keep_events))
        self.lock = RLock()
        self._since_checkpoint = 0
        self.seq = 0

    @property
    def ledger_path(self) -> Path:
        return self.root / self.LEDGER

    @property
    def state_path(self) -> Path:
        return self.root / self.STATE

    def append(self, event: dict[str, Any]) -> int:
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            self.seq += 1
            event = dict(event, seq=self.seq)
            line = json.dumps(event, ensure_ascii=False, allow_nan=False,
                              separators=(",", ":")) + "\n"
            with open(self.ledger_path, "a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                if self.durable:
                    try:
                        os.fsync(handle.fileno())
                    except OSError:
                        pass
            self._since_checkpoint += 1
            return self.seq

    def write_state(self, state: dict[str, Any]) -> None:
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            payload = dict(state, seq=self.seq, schema_version=SCHEMA_VERSION)
            temporary = self.state_path.with_name(
                self.state_path.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                temporary.write_text(
                    json.dumps(payload, ensure_ascii=False, allow_nan=False,
                               separators=(",", ":")), encoding="utf-8")
                temporary.replace(self.state_path)
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            self._since_checkpoint = 0

    def due_for_checkpoint(self) -> bool:
        return self._since_checkpoint >= self.checkpoint_every

    def load(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """The snapshot, then every ledger line written after it.

        A torn final line is DROPPED, not repaired. Anything else would be
        inventing a commitment the station never made."""
        state: dict[str, Any] = {}
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
            state = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            state = {}
        floor = int(state.get("seq") or 0)
        events: list[dict[str, Any]] = []
        highest = floor
        try:
            raw = self.ledger_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            raw = ""
        lines = raw.split("\n")
        if lines and lines[-1] == "":
            lines.pop()                      # the file ended cleanly
        else:
            lines = lines[:-1] if lines else []   # a torn tail: drop it
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue                     # a torn line in the middle: skip
            if not isinstance(event, dict):
                continue
            seq = int(event.get("seq") or 0)
            highest = max(highest, seq)
            if seq > floor:
                events.append(event)
        with self.lock:
            self.seq = highest
        return state, events

    def compact(self, state: dict[str, Any]) -> None:
        """Snapshot, then start a fresh ledger. The snapshot is written FIRST."""
        with self.lock:
            self.write_state(state)
            try:
                self.ledger_path.unlink(missing_ok=True)
            except OSError:
                pass


# -------------------------------------------------------- the controller


class PlayoutController:
    """ONE controller owns dispatch and advancement.

    Producers, watchdogs and scheduling clocks SUBMIT CANDIDATES. They do
    not start broadcast audio. That sentence is the reason this class has a
    `gate` at all: the two transports ask it, every time, and the answer is
    either an occurrence that was committed first or a refusal with a name.
    """

    def __init__(self, store: AdmissionStore, *,
                 clock: Callable[[], float] = time.time,
                 mode: str = MODE_OBSERVE, enforce_lanes: Iterable[str] = (),
                 enforce_order: bool = False,
                 exempt_lanes: Iterable[str] = ("reply",),
                 resolve_audio: Callable[[str], Any] | None = None,
                 new_id: Callable[[], str] | None = None,
                 keep_occurrences: int = 400, keep_refusals: int = 400,
                 log: Callable[[str, dict[str, Any]], None] | None = None):
        self.store = store
        self.clock = clock
        self.mode = MODE_ENFORCE if str(mode) == MODE_ENFORCE else MODE_OBSERVE
        self.enforce_lanes = set(str(lane) for lane in (enforce_lanes or ()))
        self.enforce_order = bool(enforce_order)
        self.exempt_lanes = set(str(lane) for lane in (exempt_lanes or ()))
        self.resolve_audio = resolve_audio
        self.new_id = new_id or (lambda: uuid.uuid4().hex[:20])
        self.keep_occurrences = max(20, int(keep_occurrences))
        self.keep_refusals = max(20, int(keep_refusals))
        self.log = log
        self.lock = RLock()

        self._generation = 0
        self._next_position = 1
        self._reader_position = 0
        self._occurrences: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []            # occurrence ids, by position
        self._candidates: dict[str, dict[str, Any]] = {}
        self._reservations: dict[str, dict[str, Any]] = {}
        self._refusals: list[dict[str, Any]] = []
        self._counts: dict[str, int] = {}
        self._started = float(clock())

    # ------------------------------------------------------------ opening

    @classmethod
    def open(cls, root: Any, **kwargs: Any) -> "PlayoutController":
        durable = bool(kwargs.pop("durable", True))
        checkpoint_every = int(kwargs.pop("checkpoint_every", 64))
        store = AdmissionStore(root, durable=durable,
                               checkpoint_every=checkpoint_every)
        controller = cls(store, **kwargs)
        controller.resume()
        return controller

    def resume(self) -> dict[str, Any]:
        """Rebuild from the snapshot and the ledger, then BUMP the generation.

            "A route change or restart needs an ownership generation so
             late messages from the previous player cannot advance the
             current broadcast."

        A restart is exactly such a change: whatever was in flight when the
        process died belongs to the player that died with it. Its receipts
        are refused from here on, by name, and counted."""
        state, events = self.store.load()
        with self.lock:
            self._apply_state(state)
            for event in events:
                self._apply_event(event)
            in_flight = [oid for oid in self._order
                         if (self._occurrences.get(oid) or {}).get("state") == DISPATCHING]
            self._generation += 1
            for oid in in_flight:
                # It was handed to a transport by a player that no longer
                # exists. Its position stands; its delivery is UNCERTAIN.
                self._finish(oid, UNCERTAIN,
                             {"source": "restart",
                              "note": "the process restarted while this occurrence "
                                      "was in flight; no receipt survived it"},
                             record=True)
            self._record({"type": "resumed", "at": self.clock(),
                          "generation": self._generation,
                          "recovered": len(events), "in_flight": in_flight})
            self.checkpoint()
            return self.stats()

    # --------------------------------------------------------- ownership

    @property
    def generation(self) -> int:
        return self._generation

    def bump_generation(self, reason: str) -> int:
        """A route change, a device swap, a restart: the owner has moved."""
        with self.lock:
            self._generation += 1
            for oid in list(self._order):
                row = self._occurrences.get(oid) or {}
                if row.get("state") == DISPATCHING:
                    self._finish(oid, UNCERTAIN,
                                 {"source": "generation",
                                  "reason": str(reason)[:200],
                                  "note": "ownership moved while this was in flight"},
                                 record=True)
            self._record({"type": "generation", "at": self.clock(),
                          "generation": self._generation,
                          "reason": str(reason)[:200]})
            self._checkpoint_if_due()
            return self._generation

    def _generation_ok(self, generation: int | None) -> bool:
        return generation is None or int(generation) == self._generation

    # -------------------------------------------------------- submission

    def submit(self, cand: dict[str, Any]) -> str:
        """A producer offering material. NOTHING is committed here."""
        with self.lock:
            row = dict(cand)
            row.setdefault("candidate_id", self.new_id())
            row["submitted_at"] = self.clock()
            row["state"] = "submitted"
            self._candidates[str(row["candidate_id"])] = row
            if len(self._candidates) > self.keep_occurrences * 2:
                for key in list(self._candidates):
                    if self._candidates[key].get("state") != "submitted":
                        self._candidates.pop(key, None)
            self._record({"type": "submitted", "at": row["submitted_at"],
                          "candidate_id": row["candidate_id"],
                          "lane": row.get("lane"), "producer": row.get("producer")})
            return str(row["candidate_id"])

    def withdraw_candidate(self, candidate_id: str, reason: str) -> None:
        with self.lock:
            row = self._candidates.get(str(candidate_id))
            if not row:
                return
            row["state"] = "withdrawn"
            row["withdrawn_why"] = str(reason)[:240]
            self._record({"type": "candidate_withdrawn", "at": self.clock(),
                          "candidate_id": str(candidate_id),
                          "reason": row["withdrawn_why"]})

    # ------------------------------------------------------- verification

    def verify(self, cand: dict[str, Any]) -> dict[str, Any]:
        """Is this READY? Audio present, cue offsets known and ordered.

        Called before anything is committed, never during playback. A
        candidate that fails here is not admitted at all; the caller hands
        `admit` a replacement, and the reason is recorded."""
        assembly = cand.get("assembly") if isinstance(cand.get("assembly"), dict) else {}
        path = str(cand.get("path")
                   or Contracts.pick(assembly, Contracts.MEDIA, "") or "")
        problems: list[str] = []
        identity = audio_identity(path, resolve=self.resolve_audio)
        if not identity.get("available"):
            problems.append("the final audio is not available at "
                            + (media_key(path) or "(no path)"))
        declared = Contracts.bare_digest(
            Contracts.pick(assembly, Contracts.AUDIO_HASH, ""))
        # ONLY A LIKE-FOR-LIKE HASH CAN DISAGREE.
        #
        # conversation_assembly.py declares a full sha256 of the finished
        # bytes. Above the cap this module identifies a file by its size
        # plus its first and last mebibyte, and comparing THAT to a full
        # digest would refuse every long conversation on air - a false
        # refusal that drops a whole round. A hash that cannot be checked
        # is reported as unchecked, never as wrong.
        if declared and identity.get("hash"):
            if identity.get("hash_method") == HASH_FULL:
                if declared != identity.get("hash"):
                    # The assembler pinned a hash and the bytes on disk are
                    # not it. Something rewrote a take an assembly owns.
                    problems.append("the final audio hash does not match "
                                    "the assembly's")
            else:
                identity["declared_hash"] = declared
                identity["declared_hash_checked"] = False
        seconds = Contracts.number(assembly, Contracts.SECONDS, None)
        if seconds is None:
            # script_manifest.finished_conversation carries no `seconds`: it
            # carries the frame count and the rate, which are the exact
            # numbers and not a rounded one. Derive rather than fall back.
            frames = Contracts.number(assembly, Contracts.FRAME_COUNT, None)
            rate = Contracts.number(assembly, Contracts.SAMPLE_RATE, None)
            if frames is not None and rate:
                seconds = frames / rate
        if seconds is None:
            seconds = float(cand.get("seconds") or 0.0)
        cues = self._normalise_cues(assembly, seconds, problems)
        return {"ok": not problems, "problems": problems, "audio": identity,
                "cues": cues, "seconds": float(seconds or 0.0),
                "assembly_id": str(Contracts.pick(assembly, Contracts.ASSEMBLY_ID, "") or ""),
                "script_revision": str(Contracts.pick(assembly, Contracts.SCRIPT_REVISION, "") or ""),
                "cue_map_revision": str(Contracts.pick(assembly, Contracts.CUE_MAP_REVISION, "") or ""),
                "performer_session": str(Contracts.pick(assembly, Contracts.SESSION_ID, "") or ""),
                "take_id": str(Contracts.pick(assembly, Contracts.TAKE_ID, "") or "")}

    def _normalise_cues(self, assembly: dict[str, Any], seconds: float | None,
                        problems: list[str]) -> list[dict[str, Any]]:
        raw = Contracts.raw_cues(assembly)
        if not raw:
            problems.append("the ordered line/cue offsets are not known")
            return []
        rate = Contracts.number(assembly, Contracts.SAMPLE_RATE, None)
        out: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        previous_end = -1.0
        for index, row in enumerate(raw):
            start = Contracts.number(row, Contracts.CUE_START, None)
            end = Contracts.number(row, Contracts.CUE_END, None)
            if start is None or end is None:
                # Sample positions are the note's preferred identity: accept
                # them when a rate is declared, and refuse to guess one.
                start_sample = Contracts.number(row, Contracts.CUE_START_SAMPLE, None)
                end_sample = Contracts.number(row, Contracts.CUE_END_SAMPLE, None)
                if start_sample is not None and end_sample is not None and rate:
                    start, end = start_sample / rate, end_sample / rate
            if start is None or end is None:
                problems.append("cue %d has no usable window" % index)
                continue
            if end <= start:
                problems.append("cue %d ends at or before it starts" % index)
                continue
            if start < previous_end - 1e-6:
                problems.append("cue %d starts before cue %d ends" % (index, index - 1))
            previous_end = end
            if seconds and end > float(seconds) + 1.5:
                problems.append("cue %d runs past the end of the audio" % index)
            identity = str(Contracts.pick(row, Contracts.CUE_ID, "") or "")
            if not identity:
                problems.append("cue %d has no line occurrence id" % index)
            elif identity in seen_ids:
                problems.append("cue %d repeats the line occurrence id %s"
                                % (index, identity))
            else:
                seen_ids.add(identity)
            speech_end = Contracts.number(row, Contracts.CUE_SPEECH_END, None)
            if speech_end is None:
                sample = Contracts.number(row, Contracts.CUE_SPEECH_END_SAMPLE,
                                          None)
                if sample is not None and rate:
                    speech_end = sample / rate
            if speech_end is None:
                tail = Contracts.number(row, Contracts.CUE_TAIL, 0.0) or 0.0
                speech_end = max(start, end - tail)
            ordinal = Contracts.number(row, Contracts.CUE_ORDINAL, None)
            out.append({"line_id": identity,
                        "ordinal": int(ordinal) if ordinal is not None else index,
                        "start_s": round(float(start), 4),
                        "speech_end_s": round(float(min(max(speech_end, start), end)), 4),
                        "end_s": round(float(end), 4),
                        "who": str(Contracts.pick(row, Contracts.CUE_WHO, "") or "")[:60],
                        "name": str(Contracts.pick(row, Contracts.CUE_NAME, "") or "")[:60],
                        "kind": str(Contracts.pick(row, Contracts.CUE_KIND, "") or "")[:40],
                        "cut_id": str(Contracts.pick(row, Contracts.CUE_CUT, "") or "")[:80],
                        "text": str(Contracts.pick(row, Contracts.CUE_TEXT, "") or "")[:400]})
        return out

    # ------------------------------------------------------------ admission

    def admit(self, cand: dict[str, Any] | str | None = None, *,
              alternatives: Iterable[dict[str, Any]] = (),
              reservation: str = "", origin: str = "producer",
              at_position: int | None = None) -> dict[str, Any]:
        """COMMIT, atomically: one playback occurrence id, ordered sequence
        positions, the exact audio identity and the cue sheet - together.

        A replacement is chosen HERE, before anything enters the committed
        script, and its reason is written down. After this returns, the
        positions it took belong to the reader and nothing moves them."""
        with self.lock:
            first = self._as_candidate(cand)
            tried: list[dict[str, Any]] = []
            chosen = None
            checked = None
            for offered in [first] + [c for c in (alternatives or []) if c]:
                if offered is None:
                    continue
                result = self.verify(offered)
                if result["ok"]:
                    chosen, checked = offered, result
                    break
                tried.append({"candidate_id": str(offered.get("candidate_id") or ""),
                              "producer": str(offered.get("producer") or ""),
                              "problems": list(result["problems"])[:6]})
            if chosen is None or checked is None:
                self._count("admission_refused")
                self._record({"type": "admission_refused", "at": self.clock(),
                              "tried": tried[:3]})
                raise AdmissionError("no ready candidate: " + json.dumps(tried[:3]))
            replacement = None
            if tried:
                replacement = {"of": tried[0].get("candidate_id"),
                               "producer": tried[0].get("producer"),
                               "reason": "; ".join(tried[0].get("problems") or [])[:400]}

            cues = checked["cues"]
            span = max(1, len(cues))
            if reservation:
                held = self._reservations.get(str(reservation))
                if not held or held.get("filled") or held.get("released"):
                    raise AdmissionError("that reservation is not open")
                start_position = int(held["position"])
                held["filled"] = True
                if span > 1:
                    # A reservation holds ONE slot. Material wider than the
                    # slot takes a fresh run at the end of the order, which
                    # never disturbs a position already read.
                    start_position = self._take_positions(span)
                    held["redirected_to"] = start_position
            elif at_position is not None:
                start_position = int(at_position)
                self._next_position = max(self._next_position, start_position + span)
            else:
                start_position = self._take_positions(span)

            occurrence_id = self.new_id()
            now = self.clock()
            cue_rows = []
            for index, cue in enumerate(cues):
                cue_rows.append(dict(cue, position=start_position + index,
                                     occurrence_id=occurrence_id))
            record = {
                "occurrence_id": occurrence_id,
                "position": start_position,
                "positions": [start_position, start_position + span - 1],
                "state": ADMITTED, "outcome": "",
                "lane": str(chosen.get("lane") or "speech"),
                "producer": str(chosen.get("producer") or "")[:120],
                "origin": str(origin or "producer"),
                "candidate_id": str(chosen.get("candidate_id") or ""),
                "admitted_at": now, "generation": self._generation,
                "audio": {"media": checked["audio"].get("media", ""),
                          "path": str(chosen.get("path")
                                      or checked["audio"].get("path", "")),
                          "sig": str(chosen.get("sig") or ""),
                          "hash": checked["audio"].get("hash", ""),
                          "hash_method": checked["audio"].get("hash_method", ""),
                          "bytes": checked["audio"].get("bytes", 0),
                          "seconds": round(float(checked["seconds"] or 0.0), 3)},
                "assembly_id": checked["assembly_id"],
                "script_revision": checked["script_revision"],
                "cue_map_revision": checked["cue_map_revision"],
                "performer_session": checked["performer_session"],
                "take_id": checked["take_id"],
                "label": str(chosen.get("label") or "")[:120],
                "kind": str(chosen.get("kind") or "")[:40],
                "cues": cue_rows,
                "replacement": replacement,
                "delivery": {}, "acks": [],
            }
            # ONE ledger line, flushed, before the caller is told. Everything
            # in `record` is committed together or none of it is.
            self._record({"type": "admitted", "at": now, "occurrence": record})
            self._occurrences[occurrence_id] = record
            self._insert_in_order(occurrence_id)
            self._count("admitted")
            if reservation:
                self._record({"type": "reservation_filled", "at": now,
                              "reservation_id": str(reservation),
                              "occurrence_id": occurrence_id})
            self._trim()
            self._checkpoint_if_due()
            return record

    def admit_interruption(self, cand: dict[str, Any], *,
                           alternatives: Iterable[dict[str, Any]] = (),
                           origin: str = "interruption") -> dict[str, Any]:
        """A live interruption, admitted at a FUTURE SAFE BOUNDARY.

            "A live interruption can be admitted at a future safe
             boundary; it must not rewrite positions already committed to
             the reader."

        So it goes after everything the reader has been handed and after
        anything currently in flight. It does not jump the queue and it
        does not renumber it."""
        with self.lock:
            return self.admit(cand, alternatives=alternatives, origin=origin)

    def reserve_position(self, *, lane: str = "sfx", reason: str = "",
                         producer: str = "") -> dict[str, Any]:
        """Decide a random SFX's SLOT before admitting the affected material.

        The position is taken now; the audio is chosen later. Until it is
        filled or released the reader will not advance past it, which is
        what makes the slot real rather than a hope."""
        with self.lock:
            position = self._take_positions(1)
            rid = self.new_id()
            row = {"reservation_id": rid, "position": position, "lane": str(lane),
                   "reason": str(reason)[:240], "producer": str(producer)[:120],
                   "at": self.clock(), "filled": False, "released": False}
            self._reservations[rid] = row
            self._record({"type": "reserved", "at": row["at"], "reservation": row})
            return row

    def release_reservation(self, reservation_id: str, reason: str) -> None:
        with self.lock:
            row = self._reservations.get(str(reservation_id))
            if not row or row.get("filled") or row.get("released"):
                return
            row["released"] = True
            row["released_why"] = str(reason)[:240]
            self._record({"type": "reservation_released", "at": self.clock(),
                          "reservation_id": str(reservation_id),
                          "reason": row["released_why"]})

    def withdraw(self, occurrence_id: str, reason: str) -> bool:
        """Pull an admitted occurrence BEFORE it is dispatched. Its POSITION
        stands: the script keeps the hole, marked, rather than renumbering
        every line after it."""
        with self.lock:
            row = self._occurrences.get(str(occurrence_id))
            if not row or row.get("state") != ADMITTED:
                return False
            row["state"] = WITHDRAWN
            row["withdrawn_why"] = str(reason)[:240]
            self._record({"type": "withdrawn", "at": self.clock(),
                          "occurrence_id": str(occurrence_id),
                          "reason": row["withdrawn_why"]})
            return True

    # ---------------------------------------------------------- the gate

    def gate(self, *, lane: str = "speech", path: str = "", sig: str = "",
             producer: str = "", reply: bool = False, kind: str = "",
             text: str = "", seconds: float = 0.0,
             generation: int | None = None,
             assembly: dict[str, Any] | None = None,
             meta: dict[str, Any] | None = None) -> Verdict:
        """THE question both transports must ask: was this committed first?

        In observe mode the answer is always yes and the truth is written
        down beside it. In enforce mode a refusal is returned, and both
        transports already have a road for that: `_play_on_box` returns ""
        (the box-declined contract every caller handles) and
        `page_feed_append` returns "" (no delivery id)."""
        with self.lock:
            lane = str(lane or "speech")
            enforcing = self._enforcing(lane, reply=reply)
            if reply or lane in self.exempt_lanes:
                # An assistant ANSWERING YOU is not broadcast. #647 draws
                # that boundary already and the pause is deliberately
                # narrower than the FM switch; the gate keeps it there.
                return Verdict(allow=True, reason="exempt", lane=lane,
                               mode=self.mode, generation=self._generation)
            if not self._generation_ok(generation):
                return self._refuse(STALE_GENERATION, lane, enforcing,
                                    {"producer": producer, "media": media_key(path),
                                     "saw": generation, "current": self._generation})

            found = self._claim(path, sig)
            if found is None:
                detail = {"producer": producer, "media": media_key(path),
                          "sig": str(sig or ""), "kind": kind,
                          "text": str(text or "")[:120]}
                verdict = self._refuse(UNADMITTED, lane, enforcing, detail)
                if not verdict.allow:
                    return verdict
                # OBSERVE MODE, and the audio is going out regardless. The
                # script must still be able to show it, so the dispatch is
                # recorded as an occurrence of its own with `origin` saying
                # exactly what it is: something nobody committed. That is
                # not a second gate - it is the census.
                record = self._observe_admit(lane=lane, path=path, sig=sig,
                                             producer=producer, kind=kind,
                                             text=text, seconds=seconds,
                                             assembly=assembly, meta=meta)
                if record is None:
                    return verdict
                self._begin(record["occurrence_id"])
                return Verdict(allow=True, reason=UNADMITTED,
                               occurrence_id=record["occurrence_id"],
                               position=record["position"], lane=lane,
                               enforced=False, would_refuse=True, mode=self.mode,
                               generation=self._generation, detail=detail)

            row = found
            oid = str(row["occurrence_id"])
            if row.get("state") != ADMITTED:
                return self._refuse(DUPLICATE_DISPATCH, lane, enforcing,
                                    {"occurrence_id": oid, "state": row.get("state")})
            # A refusal that was computed but not enforced MUST reach the
            # caller. An earlier cut returned a clean verdict after writing
            # the refusal to the ledger, so the transport was told "this was
            # in order" about a dispatch the controller had just recorded as
            # out of order - the observe-mode census and the live answer
            # disagreeing, which is the exact failure this module exists to
            # stop. `soft` carries every unenforced refusal out with it.
            soft: list[Verdict] = []
            blocking = self._blocking_reservation(int(row["position"]))
            if blocking is not None:
                verdict = self._refuse(SLOT_PENDING, lane, enforcing,
                                       {"occurrence_id": oid,
                                        "reservation_id": blocking["reservation_id"],
                                        "position": blocking["position"]})
                if not verdict.allow:
                    return verdict
                soft.append(verdict)
            ahead = self._earlier_unfinished(int(row["position"]))
            if ahead:
                verdict = self._refuse(OUT_OF_ORDER, lane,
                                       enforcing and self.enforce_order,
                                       {"occurrence_id": oid,
                                        "position": row["position"],
                                        "waiting_on": ahead[:4]})
                if not verdict.allow:
                    return verdict
                soft.append(verdict)
            self._begin(oid)
            self._count("dispatched")
            if soft:
                first = soft[0]
                detail = dict(first.detail)
                detail["also"] = [v.reason for v in soft[1:]]
                return Verdict(allow=True, reason=first.reason, occurrence_id=oid,
                               position=int(row["position"]), lane=lane,
                               enforced=False, would_refuse=True, mode=self.mode,
                               generation=self._generation, detail=detail)
            return Verdict(allow=True, reason="admitted", occurrence_id=oid,
                           position=int(row["position"]), lane=lane,
                           mode=self.mode, generation=self._generation)

    def _enforcing(self, lane: str, *, reply: bool = False) -> bool:
        if reply or lane in self.exempt_lanes:
            return False
        if self.mode != MODE_ENFORCE:
            return False
        return (not self.enforce_lanes) or (lane in self.enforce_lanes)

    def _refuse(self, reason: str, lane: str, enforcing: bool,
                detail: dict[str, Any]) -> Verdict:
        row = {"at": self.clock(), "reason": reason, "lane": lane,
               "enforced": bool(enforcing), "mode": self.mode,
               "generation": self._generation, "detail": detail}
        self._refusals.append(row)
        del self._refusals[:-self.keep_refusals]
        self._count("refusal:" + reason)
        if not enforcing:
            self._count("would_refuse:" + reason)
        self._record({"type": "refusal", **row})
        return Verdict(allow=not enforcing, reason=reason, lane=lane,
                       enforced=bool(enforcing), would_refuse=not enforcing,
                       mode=self.mode, generation=self._generation, detail=detail)

    def _observe_admit(self, **kw: Any) -> dict[str, Any] | None:
        """Record an unadmitted dispatch so the script keeps a full sequence."""
        assembly = kw.get("assembly") if isinstance(kw.get("assembly"), dict) else None
        path = str(kw.get("path") or "")
        cand = candidate(lane=str(kw.get("lane") or "speech"),
                         producer=str(kw.get("producer") or ""),
                         assembly=assembly or {}, path=path,
                         sig=str(kw.get("sig") or ""),
                         seconds=float(kw.get("seconds") or 0.0),
                         text=str(kw.get("text") or ""),
                         kind=str(kw.get("kind") or ""),
                         meta=kw.get("meta") or {})
        if not assembly:
            # No cue map exists for it. ONE cue covering the whole file is
            # the honest shape: the view can light the clip but must not
            # pretend to know where inside it a line begins.
            seconds = float(kw.get("seconds") or 0.0)
            if seconds <= 0:
                seconds = float(audio_seconds_hint(path, self.resolve_audio) or 0.0)
            cand["assembly"] = {
                "assembly_id": "observed-" + media_key(path),
                "media": path, "seconds": max(seconds, 0.05),
                "cue_map_revision": "observed-dispatch-1",
                "cue_map": [{"occurrence_id": "observed:" + media_key(path),
                             "ordinal": 0, "start_s": 0.0,
                             "end_s": max(seconds, 0.05),
                             "text": str(kw.get("text") or "")[:400],
                             "kind": str(kw.get("kind") or "")}]}
        try:
            return self.admit(cand, origin="observed_dispatch")
        except AdmissionError:
            # Even the observed shape would not verify (the file is gone).
            # It is counted and nothing is committed: an occurrence that
            # cannot name its audio is not an occurrence.
            self._count("observe_admit_failed")
            return None

    # -------------------------------------------------- dispatch lifecycle

    def begin(self, occurrence_id: str, *,
              generation: int | None = None) -> Verdict:
        """Explicit dispatch of an occurrence the caller already holds."""
        with self.lock:
            row = self._occurrences.get(str(occurrence_id))
            lane = str((row or {}).get("lane") or "")
            if not self._generation_ok(generation):
                return self._refuse(STALE_GENERATION, lane, self._enforcing(lane),
                                    {"occurrence_id": occurrence_id,
                                     "saw": generation, "current": self._generation})
            if not row:
                return self._refuse(UNADMITTED, lane, self._enforcing(lane),
                                    {"occurrence_id": occurrence_id})
            if row.get("state") == WITHDRAWN:
                return self._refuse(WITHDRAWN_OCCURRENCE, lane,
                                    self._enforcing(lane),
                                    {"occurrence_id": occurrence_id})
            if row.get("state") != ADMITTED:
                return self._refuse(DUPLICATE_DISPATCH, lane, self._enforcing(lane),
                                    {"occurrence_id": occurrence_id,
                                     "state": row.get("state")})
            self._begin(str(occurrence_id))
            return Verdict(allow=True, reason="admitted",
                           occurrence_id=str(occurrence_id),
                           position=int(row["position"]), lane=lane,
                           mode=self.mode, generation=self._generation)

    def _begin(self, occurrence_id: str) -> None:
        row = self._occurrences.get(occurrence_id)
        if not row:
            return
        row["state"] = DISPATCHING
        row["dispatched_at"] = self.clock()
        row["dispatch_generation"] = self._generation
        self._reader_position = max(self._reader_position, int(row["position"]))
        self._record({"type": "dispatched", "at": row["dispatched_at"],
                      "occurrence_id": occurrence_id, "position": row["position"],
                      "generation": self._generation})
        self._checkpoint_if_due()

    def record_delivery(self, occurrence_id: str, outcome: str, *,
                        evidence: dict[str, Any] | None = None,
                        generation: int | None = None) -> bool:
        """What actually became of it.

            "Do not equate a command acknowledgment with proof that sound
             reached a speaker."

        So `accepted` and `delivered` are two different words here, and the
        transports are wired to the first one. `delivered` is reserved for
        evidence that names how audibility was established."""
        with self.lock:
            row = self._occurrences.get(str(occurrence_id))
            if not row:
                return False
            lane = str(row.get("lane") or "")
            if not self._generation_ok(generation):
                self._refuse(STALE_GENERATION, lane, self._enforcing(lane),
                             {"occurrence_id": occurrence_id, "outcome": outcome,
                              "saw": generation, "current": self._generation})
                return False
            if row.get("state") == FINISHED:
                # A duplicate or delayed acknowledgment. The FIRST verdict
                # stands; the repeat is recorded beside it, never over it.
                late = row.setdefault("late_receipts", [])
                late.append({"at": self.clock(), "outcome": str(outcome),
                             "evidence": dict(evidence or {})})
                del late[:-8]
                self._count("late_receipt")
                self._record({"type": "late_receipt", "at": self.clock(),
                              "occurrence_id": str(occurrence_id),
                              "outcome": str(outcome)})
                return False
            self._finish(str(occurrence_id), str(outcome), dict(evidence or {}),
                         record=True)
            return True

    def _finish(self, occurrence_id: str, outcome: str,
                evidence: dict[str, Any], *, record: bool) -> None:
        row = self._occurrences.get(occurrence_id)
        if not row:
            return
        if outcome not in OUTCOMES:
            outcome = UNCERTAIN
        row["state"] = FINISHED
        row["outcome"] = outcome
        row["finished_at"] = self.clock()
        row["delivery"] = {"outcome": outcome, "at": row["finished_at"],
                           "generation": self._generation,
                           "audible_confirmed": evidence.get("audible_confirmed"),
                           "evidence": {k: v for k, v in dict(evidence).items()
                                        if k != "audible_confirmed"}}
        self._count("outcome:" + outcome)
        if record:
            self._record({"type": "delivery", "at": row["finished_at"],
                          "occurrence_id": occurrence_id, "outcome": outcome,
                          "generation": self._generation,
                          "evidence": row["delivery"]["evidence"],
                          "audible_confirmed": evidence.get("audible_confirmed")})
            self._checkpoint_if_due()

    def acknowledge(self, occurrence_id: str, *, listener: str = "",
                    event: str = "", position_s: float | None = None,
                    generation: int | None = None) -> bool:
        """A player receipt. Bounded, and never a delivery verdict on its own."""
        with self.lock:
            row = self._occurrences.get(str(occurrence_id))
            if not row:
                return False
            if not self._generation_ok(generation):
                self._count("stale_ack")
                return False
            acks = row.setdefault("acks", [])
            acks.append({"at": self.clock(), "listener": str(listener)[:80],
                         "event": str(event)[:40],
                         "position_s": (None if position_s is None
                                        else round(float(position_s), 3))})
            del acks[:-24]
            return True

    # ------------------------------------------------------- advancement

    def next_occurrence(self) -> dict[str, Any] | None:
        """The reader's next line: the lowest admitted position that is not
        behind an unfilled reservation or an unfinished earlier occurrence."""
        with self.lock:
            for oid in self._order:
                row = self._occurrences.get(oid) or {}
                state = row.get("state")
                if state == DISPATCHING:
                    return None                 # one at a time, in order
                if state != ADMITTED:
                    continue
                if self._blocking_reservation(int(row["position"])) is not None:
                    return None
                return row
            return None

    def advance(self, *, generation: int | None = None) -> dict[str, Any] | None:
        """Move the reader on. The controller owns this; nothing else calls it."""
        with self.lock:
            if not self._generation_ok(generation):
                self._count("stale_advance")
                return None
            nxt = self.next_occurrence()
            if nxt is not None:
                self._reader_position = max(self._reader_position,
                                            int(nxt["position"]))
            return nxt

    def ready_buffer(self, count: int = 8) -> list[dict[str, Any]]:
        """Selection happens AHEAD of the reader: what is committed and waiting."""
        with self.lock:
            out = []
            for oid in self._order:
                row = self._occurrences.get(oid) or {}
                if row.get("state") == ADMITTED:
                    out.append(row)
                if len(out) >= max(1, int(count)):
                    break
            return out

    def reconcile(self, *, media: str = "", position_s: float | None = None,
                  generation: int | None = None) -> dict[str, Any]:
        """Resume from a trustworthy checkpoint before advancing.

        Given what the PLAYER says it is actually sounding, say whether the
        controller agrees and which occurrence that is. An uncertain
        delivery is settled here rather than guessed at."""
        with self.lock:
            key = media_key(media)
            if not self._generation_ok(generation):
                return {"agreed": False, "reason": STALE_GENERATION,
                        "generation": self._generation}
            in_flight = [self._occurrences[o] for o in self._order
                         if (self._occurrences.get(o) or {}).get("state") == DISPATCHING]
            match = None
            for oid in reversed(self._order):
                row = self._occurrences.get(oid) or {}
                if key and str((row.get("audio") or {}).get("media") or "") == key:
                    match = row
                    break
            if match is None:
                return {"agreed": False,
                        "reason": "the player is sounding audio no admitted "
                                  "occurrence names",
                        "media": key,
                        "in_flight": [r["occurrence_id"] for r in in_flight],
                        "generation": self._generation}
            cue = None
            if position_s is not None:
                cue = self.cue_at(str(match["occurrence_id"]), float(position_s))
            agreed = bool(in_flight
                          and in_flight[0]["occurrence_id"] == match["occurrence_id"])
            if not agreed and match.get("state") == DISPATCHING:
                agreed = True
            return {"agreed": agreed, "occurrence_id": match["occurrence_id"],
                    "position": match["position"], "state": match.get("state"),
                    "media": key, "cue": cue, "generation": self._generation,
                    "in_flight": [r["occurrence_id"] for r in in_flight]}

    def cue_at(self, occurrence_id: str, position_s: float) -> dict[str, Any] | None:
        """Map an actual player offset through the committed cue sheet."""
        row = self._occurrences.get(str(occurrence_id))
        if not row:
            return None
        for cue in row.get("cues") or []:
            if float(cue["start_s"]) <= float(position_s) < float(cue["end_s"]):
                return dict(cue)
        return None

    # ------------------------------------------------------------ reading

    def cue_map(self, *, limit: int = 60) -> dict[str, Any]:
        """The committed sequence, as the Script view reads it."""
        with self.lock:
            ids = self._order[-max(1, int(limit)):]
            current = None
            for oid in reversed(self._order):
                row = self._occurrences.get(oid) or {}
                if row.get("state") == DISPATCHING:
                    current = {"occurrence_id": oid, "position": row.get("position"),
                               "media": (row.get("audio") or {}).get("media", ""),
                               "started_at": row.get("dispatched_at"),
                               "seconds": (row.get("audio") or {}).get("seconds", 0)}
                    break
            return {"schema_version": SCHEMA_VERSION,
                    "generation": self._generation, "mode": self.mode,
                    "enforce_lanes": sorted(self.enforce_lanes),
                    "enforce_order": self.enforce_order,
                    "reader_position": self._reader_position,
                    "next_position": self._next_position,
                    "current": current,
                    "occurrences": [self._public(self._occurrences[o]) for o in ids],
                    "reservations": [dict(r) for r in self._reservations.values()
                                     if not r.get("filled") and not r.get("released")],
                    "counts": dict(self._counts),
                    "refusals": [dict(r) for r in self._refusals[-12:]]}

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        out = {k: row[k] for k in ("occurrence_id", "position", "positions", "state",
                                   "outcome", "lane", "producer", "origin",
                                   "assembly_id", "script_revision",
                                   "cue_map_revision", "performer_session",
                                   "take_id", "label", "kind", "admitted_at",
                                   "generation")
               if k in row}
        out["audio"] = dict(row.get("audio") or {})
        out["cues"] = [dict(c) for c in (row.get("cues") or [])]
        out["replacement"] = row.get("replacement")
        out["dispatched_at"] = row.get("dispatched_at")
        out["delivery"] = dict(row.get("delivery") or {})
        if row.get("withdrawn_why"):
            out["withdrawn_why"] = row["withdrawn_why"]
        return out

    def occurrence(self, occurrence_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self._occurrences.get(str(occurrence_id))
            return self._public(row) if row else None

    def references(self, occurrence_id: str = "") -> dict[str, Any]:
        """The incident reference set section 5 of the recording note asks for.

            "Extend the existing incident capture with references to the
             relevant script revision, performer session, accepted cut,
             assembly and playback occurrence."

        An unavailable reference is reported as ABSENT, explicitly - never
        filled in with a plausible-looking value."""
        with self.lock:
            row = None
            if occurrence_id:
                row = self._occurrences.get(str(occurrence_id))
            if row is None:
                for oid in reversed(self._order):
                    held = self._occurrences.get(oid) or {}
                    if held.get("state") in (DISPATCHING, FINISHED):
                        row = held
                        break
            if row is None:
                return {"available": False,
                        "why": "no occurrence has been dispatched under this generation",
                        "ownership_generation": self._generation}
            cuts = [c.get("cut_id") for c in (row.get("cues") or []) if c.get("cut_id")]
            return {"available": True,
                    "playback_occurrence_id": row.get("occurrence_id"),
                    "position": row.get("position"),
                    "positions": row.get("positions"),
                    "script_revision": row.get("script_revision") or None,
                    "performer_session": row.get("performer_session") or None,
                    "assembly_id": row.get("assembly_id") or None,
                    "cue_map_revision": row.get("cue_map_revision") or None,
                    "accepted_cuts": cuts[:24] or None,
                    "take_id": row.get("take_id") or None,
                    "audio_hash": (row.get("audio") or {}).get("hash") or None,
                    "audio_hash_method": (row.get("audio") or {}).get("hash_method") or None,
                    "ownership_generation": self._generation,
                    "origin": row.get("origin"),
                    "replacement": row.get("replacement")}

    def refusals(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(r) for r in self._refusals[-max(1, int(limit)):]]

    def stats(self) -> dict[str, Any]:
        with self.lock:
            states: dict[str, int] = {}
            for oid in self._order:
                state = str((self._occurrences.get(oid) or {}).get("state") or "?")
                states[state] = states.get(state, 0) + 1
            return {"schema_version": SCHEMA_VERSION, "mode": self.mode,
                    "enforce_lanes": sorted(self.enforce_lanes),
                    "enforce_order": self.enforce_order,
                    "generation": self._generation,
                    "reader_position": self._reader_position,
                    "next_position": self._next_position,
                    "occurrences": len(self._order), "states": states,
                    "counts": dict(self._counts),
                    "open_reservations": sum(1 for r in self._reservations.values()
                                             if not r.get("filled")
                                             and not r.get("released")),
                    "started_at": self._started, "seq": self.store.seq}

    # ----------------------------------------------------------- internals

    def _as_candidate(self, cand: dict[str, Any] | str | None) -> dict[str, Any] | None:
        if cand is None:
            return None
        if isinstance(cand, str):
            held = self._candidates.get(cand)
            return dict(held) if held else None
        key = str(cand.get("candidate_id") or "")
        if key and key in self._candidates:
            merged = dict(self._candidates[key])
            merged.update(cand)
            return merged
        return dict(cand)

    def _take_positions(self, span: int) -> int:
        start = self._next_position
        self._next_position += max(1, int(span))
        return start

    def _insert_in_order(self, occurrence_id: str) -> None:
        position = int(self._occurrences[occurrence_id]["position"])
        index = len(self._order)
        while index > 0 and int(
                self._occurrences[self._order[index - 1]]["position"]) > position:
            index -= 1
        self._order.insert(index, occurrence_id)

    def _claim(self, path: str, sig: str) -> dict[str, Any] | None:
        """The EARLIEST admitted occurrence for this audio.

        A reusable sample admitted twice has two occurrences; the first
        dispatch claims the first one and the second dispatch claims the
        second. Matching on content alone would light one line twice and
        leave the other dark for ever."""
        want_keyed = audio_key(path, sig)
        want_media = media_key(path)
        if not want_media:
            return None
        fallback = None
        for oid in self._order:
            row = self._occurrences.get(oid) or {}
            if row.get("state") != ADMITTED:
                continue
            audio = row.get("audio") or {}
            mine = media_key(str(audio.get("path") or audio.get("media") or ""))
            if mine != want_media:
                continue
            mine_sig = str(audio.get("sig") or "")
            if sig and mine_sig and audio_key(mine, mine_sig) == want_keyed:
                return row
            if fallback is None:
                fallback = row
        return fallback

    def _earlier_unfinished(self, position: int) -> list[str]:
        out = []
        for oid in self._order:
            row = self._occurrences.get(oid) or {}
            if int(row.get("position") or 0) >= int(position):
                break
            if row.get("state") == ADMITTED:
                out.append(oid)
        return out

    def _blocking_reservation(self, position: int) -> dict[str, Any] | None:
        for row in self._reservations.values():
            if row.get("filled") or row.get("released"):
                continue
            if int(row.get("position") or 0) < int(position):
                return row
        return None

    def _count(self, key: str) -> None:
        self._counts[key] = int(self._counts.get(key, 0)) + 1

    def _record(self, event: dict[str, Any]) -> None:
        self.store.append(event)
        if self.log:
            try:
                self.log(str(event.get("type") or ""), event)
            except Exception:  # noqa: BLE001
                pass

    def _trim(self) -> None:
        """Bound the in-memory picture. Positions are NOT reused and the
        ledger keeps the full history; this only forgets old rows."""
        while len(self._order) > self.keep_occurrences:
            oid = self._order[0]
            row = self._occurrences.get(oid) or {}
            if row.get("state") in (ADMITTED, DISPATCHING):
                break                          # never forget live work
            self._order.pop(0)
            self._occurrences.pop(oid, None)

    def _checkpoint_if_due(self) -> None:
        if self.store.due_for_checkpoint():
            self.checkpoint()

    def checkpoint(self) -> None:
        with self.lock:
            self.store.write_state(self._snapshot())

    def _snapshot(self) -> dict[str, Any]:
        return {"generation": self._generation,
                "next_position": self._next_position,
                "reader_position": self._reader_position,
                "counts": dict(self._counts),
                "order": list(self._order),
                "occurrences": {o: self._occurrences[o] for o in self._order},
                "reservations": {k: v for k, v in self._reservations.items()
                                 if not v.get("filled") and not v.get("released")},
                "refusals": self._refusals[-self.keep_refusals:]}

    def _apply_state(self, state: dict[str, Any]) -> None:
        if not isinstance(state, dict) or not state:
            return
        self._generation = int(state.get("generation") or 0)
        self._next_position = int(state.get("next_position") or 1)
        self._reader_position = int(state.get("reader_position") or 0)
        self._counts = {str(k): int(v) for k, v in (state.get("counts") or {}).items()}
        occurrences = state.get("occurrences") or {}
        self._occurrences = {str(k): dict(v) for k, v in occurrences.items()
                             if isinstance(v, dict)}
        self._order = [o for o in (state.get("order") or []) if o in self._occurrences]
        self._reservations = {str(k): dict(v)
                              for k, v in (state.get("reservations") or {}).items()
                              if isinstance(v, dict)}
        self._refusals = [dict(r) for r in (state.get("refusals") or [])
                          if isinstance(r, dict)]

    def _apply_event(self, event: dict[str, Any]) -> None:
        kind = str(event.get("type") or "")
        if kind == "admitted":
            record = event.get("occurrence")
            if isinstance(record, dict) and record.get("occurrence_id"):
                oid = str(record["occurrence_id"])
                self._occurrences[oid] = dict(record)
                if oid not in self._order:
                    self._insert_in_order(oid)
                span = record.get("positions") or [record.get("position"), record.get("position")]
                try:
                    self._next_position = max(self._next_position, int(span[1]) + 1)
                except (TypeError, ValueError, IndexError):
                    pass
        elif kind == "dispatched":
            row = self._occurrences.get(str(event.get("occurrence_id")))
            if row:
                row["state"] = DISPATCHING
                row["dispatched_at"] = event.get("at")
                self._reader_position = max(self._reader_position,
                                            int(event.get("position") or 0))
        elif kind == "delivery":
            row = self._occurrences.get(str(event.get("occurrence_id")))
            if row:
                row["state"] = FINISHED
                row["outcome"] = str(event.get("outcome") or UNCERTAIN)
                row["finished_at"] = event.get("at")
                row["delivery"] = {"outcome": row["outcome"], "at": event.get("at"),
                                   "generation": event.get("generation"),
                                   "audible_confirmed": event.get("audible_confirmed"),
                                   "evidence": dict(event.get("evidence") or {})}
        elif kind == "withdrawn":
            row = self._occurrences.get(str(event.get("occurrence_id")))
            if row:
                row["state"] = WITHDRAWN
                row["withdrawn_why"] = str(event.get("reason") or "")
        elif kind in ("generation", "resumed"):
            self._generation = max(self._generation, int(event.get("generation") or 0))
        elif kind == "reserved":
            row = event.get("reservation")
            if isinstance(row, dict) and row.get("reservation_id"):
                self._reservations[str(row["reservation_id"])] = dict(row)
                self._next_position = max(self._next_position,
                                          int(row.get("position") or 0) + 1)
        elif kind == "reservation_filled":
            row = self._reservations.get(str(event.get("reservation_id")))
            if row:
                row["filled"] = True
        elif kind == "reservation_released":
            row = self._reservations.get(str(event.get("reservation_id")))
            if row:
                row["released"] = True
        elif kind == "refusal":
            self._refusals.append({k: v for k, v in event.items() if k != "type"})
            del self._refusals[:-self.keep_refusals]
