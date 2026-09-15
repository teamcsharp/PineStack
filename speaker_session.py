"""speaker_session.py - one performer, one script revision, one session.

Section 2 of `docs/notes/speaker-recording-and-script-assembly.md`:

    "Each session records its actor, script revision, ordered assignments,
    renderer configuration, current state and accepted takes. Resume from
    verified work after interruption. An engine capacity limit can constrain
    execution without losing session identity or treating an incomplete
    performance as ready.

    A whole-conversation job should finish useful conversations rather than
    leave every candidate partly recorded."

Every one of those sentences is a rule with code behind it here:

  * identity      - a session is (revision, actor, renderer fingerprint). A
                    capacity stall changes its STATE, never its identity.
  * resume        - `resume_session` reloads a record and keeps only takes
                    that are still verified against the current revision and
                    renderer. Everything else is dropped rather than trusted.
  * readiness     - `readiness()` is the only way to ask, it returns reasons
                    as well as a boolean, and being blocked on capacity can
                    never make it True. Exactly one accepted take per
                    required occurrence, or not ready.
  * completeness  - `allocate()` spends a budget on conversations it can
                    FINISH, in that order, instead of starting all of them.

This module is pure: no station imports, no HTTP, no third-party packages,
and it touches no live store. Persistence goes through the manifest-store
adapter below.

The manifest store
------------------
`manifest_store.py` / `script_manifest.py` are being written in parallel and
`docs/notes/manifests-implemented-2026-09-15.md` did not exist when this was
written. So the dependency is a PROTOCOL (`ManifestStore`) plus an adapter
(`ManifestAdapter`) that maps this module's call names onto whatever the real
store ends up calling them. Reconciling the two should be editing one dict,
not editing this module.

The calls assumed, and what each is assumed to mean:

    load_script(revision)                  -> the frozen script record, or None
    save_session(record)                   -> session_id; upsert by record["session_id"]
    load_session(session_id)               -> the session record, or None
    list_sessions(revision=, actor=)       -> session records, filtered
    save_master(record)                    -> take_id; the master recording row
    load_master(take_id)                   -> the master row, or None
    save_cut(record)                       -> cut id; one accepted line cut
    list_cuts(revision, occurrence_ids=()) -> accepted cut rows
    pinned_occurrences(revision)           -> occurrence ids an admitted
                                              broadcast has pinned; a session
                                              may never overwrite these

Record shapes are plain JSON-safe dicts; `PerformerSession.to_record()` and
`AcceptedTake.to_record()` produce them and the `from_record` classmethods
consume them, so the store never needs to know these classes exist.

Public surface
--------------
    SESSION_STATES, MODE_CONTINUOUS, MODE_SEGMENTED
    RendererConfig, Assignment, AcceptedTake, Capacity
    PerformerSession, Readiness, RenderRequest, RenderPlan
    ConversationJob, Allocation, allocate, finish_first_order
    ManifestStore (Protocol), ManifestAdapter, InMemoryManifestStore
    new_session, resume_session, persist_session
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from line_alignment import MODE_CONTINUOUS, MODE_SEGMENTED

__all__ = [
    "MODE_CONTINUOUS", "MODE_SEGMENTED", "SESSION_STATES",
    "Allocation", "Assignment", "AcceptedTake", "Capacity", "ConversationJob",
    "InMemoryManifestStore", "ManifestAdapter", "ManifestStore",
    "PerformerSession", "Readiness", "RenderPlan", "RenderRequest",
    "allocate", "finish_first_order", "new_session", "persist_session",
    "resume_session",
]

# open      - identity exists, nothing recorded yet
# recording - work is being executed against it
# blocked   - capacity (or a refusal) stopped it short of complete; it is NOT
#             ready and it has NOT lost its identity. This state is the whole
#             reason the note separates the two ideas.
# complete  - every required occurrence has exactly one verified take
# failed    - something about it can never complete under this revision
# abandoned - the operator or a revision change retired it
SESSION_STATES = ("open", "recording", "blocked", "complete", "failed",
                  "abandoned")


def _now() -> float:
    return time.time()


def _digest(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


# --- the performance contract ---------------------------------------------

@dataclass(frozen=True)
class RendererConfig:
    """What the audio was made with. Two takes are interchangeable only when
    their renderer fingerprints agree - the note's "completed audio is
    reusable only when its full performance contract remains compatible".

    `mode` is carried here and copied onto every take, because a session made
    of bounded engine segments and a session made of one continuous take are
    different artifacts and the manifest must never lose which one it holds.
    """
    engine: str
    voice: str
    mode: str
    sample_rate: int = 24000
    # The largest text this engine will actually PERFORM in one request. Not
    # a policy choice: the XTTS adapter truncates at 1000 characters and the
    # F5 path garbles past ~300, so this is a measured property of the road.
    max_request_chars: int = 800
    speech_rate: float = 1.0
    reference_sha1: str = ""
    fx: Mapping[str, float] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        if self.mode not in (MODE_CONTINUOUS, MODE_SEGMENTED):
            raise ValueError(
                f"renderer mode must be {MODE_CONTINUOUS} or "
                f"{MODE_SEGMENTED}, not {self.mode!r}")
        if int(self.sample_rate) <= 0:
            raise ValueError("a renderer needs a positive sample rate")
        if int(self.max_request_chars) <= 0:
            raise ValueError("a renderer needs a positive request cap")

    @property
    def fingerprint(self) -> str:
        """Everything that changes how the words come out. `notes` is not in
        it; a comment must not invalidate an hour of recorded audio."""
        return _digest({
            "engine": self.engine, "voice": self.voice, "mode": self.mode,
            "sample_rate": int(self.sample_rate),
            "speech_rate": round(float(self.speech_rate), 4),
            "reference_sha1": self.reference_sha1,
            "fx": {k: round(float(v), 4) for k, v in sorted(
                (self.fx or {}).items())},
        })

    def to_record(self) -> dict[str, Any]:
        return {"engine": self.engine, "voice": self.voice, "mode": self.mode,
                "sample_rate": int(self.sample_rate),
                "max_request_chars": int(self.max_request_chars),
                "speech_rate": float(self.speech_rate),
                "reference_sha1": self.reference_sha1,
                "fx": dict(self.fx or {}), "notes": self.notes,
                "fingerprint": self.fingerprint}

    @classmethod
    def from_record(cls, row: Mapping[str, Any]) -> "RendererConfig":
        return cls(
            engine=str(row.get("engine") or ""),
            voice=str(row.get("voice") or ""),
            mode=str(row.get("mode") or MODE_SEGMENTED),
            sample_rate=int(row.get("sample_rate") or 24000),
            max_request_chars=int(row.get("max_request_chars") or 800),
            speech_rate=float(row.get("speech_rate") or 1.0),
            reference_sha1=str(row.get("reference_sha1") or ""),
            fx=dict(row.get("fx") or {}),
            notes=str(row.get("notes") or ""))


@dataclass(frozen=True)
class Assignment:
    """One occurrence this performer owes. `conversation_id` is here so the
    scheduler can tell which conversation a line would finish - that is the
    difference between finishing useful work and half-recording everything."""
    occurrence_id: str
    ordinal: int
    speaker: str
    text: str
    conversation_id: str = ""

    def __post_init__(self) -> None:
        if not str(self.occurrence_id or "").strip():
            raise ValueError("an Assignment needs an occurrence_id")

    @property
    def chars(self) -> int:
        return len(self.text or "")

    def to_record(self) -> dict[str, Any]:
        return {"occurrence_id": self.occurrence_id, "ordinal": self.ordinal,
                "speaker": self.speaker, "text": self.text,
                "conversation_id": self.conversation_id}

    @classmethod
    def from_record(cls, row: Mapping[str, Any]) -> "Assignment":
        return cls(str(row.get("occurrence_id") or ""),
                   int(row.get("ordinal") or 0),
                   str(row.get("speaker") or ""),
                   str(row.get("text") or ""),
                   str(row.get("conversation_id") or ""))


@dataclass(frozen=True)
class AcceptedTake:
    """An accepted cut of a master, pinned to the contract it was made under.

    It carries `revision` and `renderer_fingerprint` so a resume can check
    compatibility without loading anything else, and `boundary_method` /
    `verification` because the note requires every cut to say how its edges
    were found and what proved them. A take with `verification["verdict"]`
    anything other than "verified" is evidence, not an accepted take."""
    occurrence_id: str
    ordinal: int
    take_id: str
    master_hash: str
    sample_rate: int
    start_sample: int
    end_sample: int
    boundary_method: str
    verification: Mapping[str, Any]
    mode: str
    revision: str
    renderer_fingerprint: str
    media_ref: str = ""
    accepted_at: float = field(default_factory=_now)

    @property
    def frames(self) -> int:
        return int(self.end_sample) - int(self.start_sample)

    @property
    def seconds(self) -> float:
        return self.frames / float(self.sample_rate or 1)

    @property
    def verified(self) -> bool:
        return (self.frames > 0
                and int(self.sample_rate) > 0
                and bool(self.master_hash)
                and bool(self.boundary_method)
                and str((self.verification or {}).get("verdict") or "")
                == "verified")

    def to_record(self) -> dict[str, Any]:
        return {
            "occurrence_id": self.occurrence_id, "ordinal": int(self.ordinal),
            "take_id": self.take_id, "master_hash": self.master_hash,
            "sample_rate": int(self.sample_rate),
            "start_sample": int(self.start_sample),
            "end_sample": int(self.end_sample),
            "frames": self.frames, "seconds": round(self.seconds, 4),
            "boundary_method": self.boundary_method,
            "verification": dict(self.verification or {}),
            "mode": self.mode, "revision": self.revision,
            "renderer_fingerprint": self.renderer_fingerprint,
            "media_ref": self.media_ref,
            "accepted_at": float(self.accepted_at),
        }

    @classmethod
    def from_record(cls, row: Mapping[str, Any]) -> "AcceptedTake":
        return cls(
            occurrence_id=str(row.get("occurrence_id") or ""),
            ordinal=int(row.get("ordinal") or 0),
            take_id=str(row.get("take_id") or ""),
            master_hash=str(row.get("master_hash") or ""),
            sample_rate=int(row.get("sample_rate") or 0),
            start_sample=int(row.get("start_sample") or 0),
            end_sample=int(row.get("end_sample") or 0),
            boundary_method=str(row.get("boundary_method") or ""),
            verification=dict(row.get("verification") or {}),
            mode=str(row.get("mode") or ""),
            revision=str(row.get("revision") or ""),
            renderer_fingerprint=str(row.get("renderer_fingerprint") or ""),
            media_ref=str(row.get("media_ref") or ""),
            accepted_at=float(row.get("accepted_at") or 0.0))

    @classmethod
    def from_line_cut(cls, cut: Any, *, take_id: str, revision: str,
                      renderer_fingerprint: str, media_ref: str = ""
                      ) -> "AcceptedTake":
        """Build one straight off a `line_alignment.LineCut`, so the aligner's
        evidence is what gets persisted rather than a retyped summary."""
        return cls(
            occurrence_id=cut.occurrence_id, ordinal=int(cut.ordinal),
            take_id=take_id, master_hash=str(getattr(cut, "master_hash", "")),
            sample_rate=int(cut.sample_rate),
            start_sample=int(cut.start_sample),
            end_sample=int(cut.end_sample),
            boundary_method=str(cut.boundary_method),
            verification=dict(cut.verification or {}),
            mode=str(cut.mode), revision=revision,
            renderer_fingerprint=renderer_fingerprint, media_ref=media_ref)


# --- capacity --------------------------------------------------------------

@dataclass(frozen=True)
class Capacity:
    """What the engine will let us do in this pass.

    None anywhere means "not limited by that". A capacity that runs out
    produces `blocked`, never `complete` and never `failed`: the session is
    exactly as valid as it was, it simply has not finished."""
    max_request_chars: int | None = None
    max_requests: int | None = None
    max_chars: int | None = None
    max_seconds: float | None = None
    label: str = ""

    def request_cap(self, renderer: RendererConfig) -> int:
        """The binding cap is the SMALLER of what the engine will perform and
        what this pass is willing to spend."""
        engine_cap = int(renderer.max_request_chars)
        if self.max_request_chars is None:
            return engine_cap
        return min(engine_cap, int(self.max_request_chars))


UNLIMITED = Capacity()


# --- plans -----------------------------------------------------------------

@dataclass(frozen=True)
class RenderRequest:
    """One call to the engine. In continuous mode it holds as many whole
    occurrences as fit under the cap; in segmented mode the same, and a piece
    longer than the cap is split with its boundary RETAINED (`piece` /
    `pieces` say so) rather than handed over to be split silently."""
    request_id: str
    session_id: str
    index: int
    occurrence_ids: tuple[str, ...]
    text: str
    mode: str
    piece: int = 0
    pieces: int = 1

    @property
    def chars(self) -> int:
        return len(self.text)

    @property
    def is_split(self) -> bool:
        return self.pieces > 1


@dataclass(frozen=True)
class RenderPlan:
    """What this pass can execute, what it cannot reach yet, and what no
    capacity will ever reach. `refusals` is the third one: an occurrence
    longer than the engine will perform is not a scheduling problem."""
    requests: tuple[RenderRequest, ...] = ()
    deferred: tuple[str, ...] = ()
    refusals: tuple[tuple[str, str], ...] = ()

    @property
    def chars(self) -> int:
        return sum(r.chars for r in self.requests)

    @property
    def covered(self) -> tuple[str, ...]:
        seen: list[str] = []
        for request in self.requests:
            for oid in request.occurrence_ids:
                if oid not in seen:
                    seen.append(oid)
        return tuple(seen)


@dataclass(frozen=True)
class Readiness:
    ready: bool
    reasons: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.ready


# --- the session -----------------------------------------------------------

class PerformerSession:
    """One actor's recording session against one frozen script revision."""

    def __init__(self, session_id: str, revision: str, actor: str,
                 renderer: RendererConfig,
                 assignments: Sequence[Assignment],
                 state: str = "open",
                 takes: Mapping[str, AcceptedTake] | None = None,
                 capacity: Capacity | None = None,
                 history: Sequence[Mapping[str, Any]] | None = None,
                 created_at: float | None = None,
                 updated_at: float | None = None) -> None:
        if state not in SESSION_STATES:
            raise ValueError(f"unknown session state {state!r}")
        if not str(session_id or "").strip():
            raise ValueError("a session needs an id")
        if not str(revision or "").strip():
            raise ValueError("a session needs a script revision")
        self.session_id = str(session_id)
        self.revision = str(revision)
        self.actor = str(actor)
        self.renderer = renderer
        # Ordered assignments: reading order is the session's order, and it
        # is fixed here so nothing downstream can infer order from completion.
        self.assignments: tuple[Assignment, ...] = tuple(
            sorted(assignments, key=lambda a: (a.ordinal, a.occurrence_id)))
        seen: set[str] = set()
        for item in self.assignments:
            if item.occurrence_id in seen:
                raise ValueError(
                    f"occurrence {item.occurrence_id} assigned twice - two "
                    "occurrences of the same words are two ids, not one")
            seen.add(item.occurrence_id)
        self.state = state
        self.takes: dict[str, AcceptedTake] = dict(takes or {})
        self.capacity = capacity or UNLIMITED
        self.history: list[dict[str, Any]] = [dict(h) for h in (history or ())]
        self.created_at = float(created_at if created_at is not None else _now())
        self.updated_at = float(updated_at if updated_at is not None else _now())

    # -- identity ----------------------------------------------------------
    @property
    def identity(self) -> tuple[str, str, str]:
        """(revision, actor, renderer fingerprint). Capacity is not in it."""
        return (self.revision, self.actor, self.renderer.fingerprint)

    @property
    def required_ids(self) -> tuple[str, ...]:
        return tuple(a.occurrence_id for a in self.assignments)

    @property
    def conversations(self) -> tuple[str, ...]:
        out: list[str] = []
        for item in self.assignments:
            if item.conversation_id and item.conversation_id not in out:
                out.append(item.conversation_id)
        return tuple(out)

    def outstanding(self) -> tuple[Assignment, ...]:
        """Assignments with no compatible verified take - in reading order."""
        return tuple(a for a in self.assignments
                     if not self._holds(a.occurrence_id))

    def outstanding_chars(self) -> int:
        return sum(a.chars for a in self.outstanding())

    def _holds(self, occurrence_id: str) -> bool:
        take = self.takes.get(occurrence_id)
        return bool(take and take.verified
                    and take.revision == self.revision
                    and take.renderer_fingerprint
                    == self.renderer.fingerprint)

    def note(self, what: str, detail: str = "") -> None:
        self.history.append({"at": _now(), "what": what, "detail": detail})
        self.history = self.history[-64:]
        self.updated_at = _now()

    # -- execution ---------------------------------------------------------
    def plan(self, capacity: Capacity | None = None) -> RenderPlan:
        """Group the outstanding work into engine requests under a capacity.

        Reading order is preserved and an occurrence is never merged with one
        that is not adjacent to it in this session, because a request's audio
        has to be cuttable back into consecutive lines.

        In continuous mode an occurrence longer than the request cap is
        REFUSED rather than split: splitting it is precisely what makes the
        result segmented synthesis, and calling that a continuous take is the
        thing the note forbids."""
        cap_source = capacity or self.capacity
        cap = cap_source.request_cap(self.renderer)
        requests: list[RenderRequest] = []
        deferred: list[str] = []
        refusals: list[tuple[str, str]] = []
        spent_chars = 0
        batch: list[Assignment] = []
        exhausted = False

        def budget_left(extra: int) -> bool:
            if cap_source.max_requests is not None \
                    and len(requests) >= int(cap_source.max_requests):
                return False
            if cap_source.max_chars is not None \
                    and spent_chars + extra > int(cap_source.max_chars):
                return False
            return True

        def flush() -> None:
            nonlocal batch, spent_chars
            if not batch:
                return
            text = " ".join(a.text.strip() for a in batch if a.text.strip())
            requests.append(RenderRequest(
                request_id=f"{self.session_id}-r{len(requests):03d}",
                session_id=self.session_id, index=len(requests),
                occurrence_ids=tuple(a.occurrence_id for a in batch),
                text=text, mode=self.renderer.mode))
            spent_chars += len(text)
            batch = []

        for item in self.outstanding():
            if exhausted:
                deferred.append(item.occurrence_id)
                continue
            if item.chars > cap:
                if self.renderer.mode == MODE_CONTINUOUS:
                    refusals.append((
                        item.occurrence_id,
                        f"{item.chars} characters is past the "
                        f"{cap}-character request cap for "
                        f"{self.renderer.engine}; a continuous take cannot be "
                        "made of it, and splitting it would be segmented "
                        "synthesis under another name"))
                    continue
                flush()
                pieces = _split_text(item.text, cap)
                if not budget_left(sum(len(p) for p in pieces)):
                    deferred.append(item.occurrence_id)
                    exhausted = True
                    continue
                for number, piece in enumerate(pieces):
                    requests.append(RenderRequest(
                        request_id=(f"{self.session_id}-r{len(requests):03d}"),
                        session_id=self.session_id, index=len(requests),
                        occurrence_ids=(item.occurrence_id,), text=piece,
                        mode=MODE_SEGMENTED, piece=number,
                        pieces=len(pieces)))
                    spent_chars += len(piece)
                continue
            pending = sum(len(a.text.strip()) + 1 for a in batch)
            if batch and pending + item.chars > cap:
                flush()
            if not budget_left(item.chars):
                if batch:
                    flush()
                deferred.append(item.occurrence_id)
                exhausted = True
                continue
            batch.append(item)
        flush()
        # Whatever the walk above could not reach is deferred, not lost.
        covered = set()
        for request in requests:
            covered.update(request.occurrence_ids)
        refused = {oid for oid, _ in refusals}
        for item in self.outstanding():
            oid = item.occurrence_id
            if oid not in covered and oid not in refused and oid not in deferred:
                deferred.append(oid)
        return RenderPlan(tuple(requests), tuple(deferred), tuple(refusals))

    def accept(self, take: AcceptedTake) -> AcceptedTake:
        """Record one verified take. Raises rather than quietly storing junk -
        an unverified take that lands in `takes` is a line that could go on
        air unproven, which is the failure this whole module is against."""
        if take.occurrence_id not in self.required_ids:
            raise ValueError(
                f"{take.occurrence_id} is not assigned to session "
                f"{self.session_id}")
        if take.revision != self.revision:
            raise ValueError(
                f"take is for revision {take.revision!r}, session is "
                f"{self.revision!r}")
        if take.renderer_fingerprint != self.renderer.fingerprint:
            raise ValueError(
                "take was made with a different renderer configuration")
        if take.mode != self.renderer.mode:
            raise ValueError(
                f"take mode {take.mode!r} is not the session's "
                f"{self.renderer.mode!r}")
        if not take.verified:
            raise ValueError(
                f"take for {take.occurrence_id} is not verified: "
                f"{dict(take.verification or {}).get('verdict') or 'no verdict'}")
        self.takes[take.occurrence_id] = take
        self.state = "recording"
        self.note("accepted", take.occurrence_id)
        self._settle()
        return take

    def discard(self, occurrence_id: str, why: str = "") -> bool:
        """Drop a take (a retake, a failed cut). A discard can move a complete
        session back to `recording`; it can never leave it reading ready."""
        if occurrence_id not in self.takes:
            return False
        self.takes.pop(occurrence_id, None)
        self.note("discarded", f"{occurrence_id}: {why}"[:200])
        self._settle()
        return True

    def block(self, why: str) -> None:
        """Capacity (or an engine outage) stopped this pass. Identity intact."""
        if self.state in ("complete", "failed", "abandoned"):
            return
        self.state = "blocked"
        self.note("blocked", why[:200])

    def fail(self, why: str) -> None:
        self.state = "failed"
        self.note("failed", why[:200])

    def abandon(self, why: str) -> None:
        self.state = "abandoned"
        self.note("abandoned", why[:200])

    def _settle(self) -> None:
        if self.state in ("failed", "abandoned"):
            return
        self.state = "complete" if not self.outstanding() else (
            "recording" if self.takes else "open")
        self.updated_at = _now()

    # -- readiness ---------------------------------------------------------
    def readiness(self) -> Readiness:
        """The only way to ask whether this performance may be used.

        Being `blocked` can never answer True - that is the note's "an engine
        capacity limit can constrain execution without ... treating an
        incomplete performance as ready", stated as code."""
        reasons: list[str] = []
        missing: list[str] = []
        if not self.assignments:
            reasons.append("the session has no assignments")
        for item in self.assignments:
            take = self.takes.get(item.occurrence_id)
            if take is None:
                missing.append(item.occurrence_id)
                reasons.append(
                    f"occurrence {item.occurrence_id} (line {item.ordinal}) "
                    "has no take")
                continue
            if take.revision != self.revision:
                missing.append(item.occurrence_id)
                reasons.append(
                    f"occurrence {item.occurrence_id} was recorded against "
                    f"revision {take.revision}, not {self.revision}")
                continue
            if take.renderer_fingerprint != self.renderer.fingerprint:
                missing.append(item.occurrence_id)
                reasons.append(
                    f"occurrence {item.occurrence_id} was recorded with a "
                    "different renderer configuration")
                continue
            if take.mode != self.renderer.mode:
                missing.append(item.occurrence_id)
                reasons.append(
                    f"occurrence {item.occurrence_id} is a {take.mode} take in "
                    f"a {self.renderer.mode} session")
                continue
            if not take.verified:
                missing.append(item.occurrence_id)
                reasons.append(
                    f"occurrence {item.occurrence_id} has an unverified take "
                    f"({dict(take.verification or {}).get('verdict') or 'no verdict'})")
        stray = [oid for oid in self.takes if oid not in set(self.required_ids)]
        for oid in sorted(stray):
            reasons.append(f"take {oid} belongs to no assignment in this session")
        ordinals = [item.ordinal for item in self.assignments]
        if ordinals != sorted(ordinals) or len(set(ordinals)) != len(ordinals):
            reasons.append("the assignments are not a clean ascending order")
        if self.state in ("failed", "abandoned"):
            reasons.append(f"the session is {self.state}")
        if self.state == "blocked" and not reasons:
            # Defensive: a blocked session with every take in hand is really
            # complete, and _settle should have said so. Say it out loud
            # rather than advertising readiness from a blocked state.
            self._settle()
            if self.state != "complete":
                reasons.append("the session is blocked")
        return Readiness(not reasons, tuple(reasons), tuple(missing))

    def ordered_takes(self) -> tuple[AcceptedTake, ...]:
        """Accepted takes in SCRIPT order - never completion order. The note's
        four-line exchange (A records 1 and 3, B records 2 and 4) comes out of
        here as 1, 3 for A and 2, 4 for B, and the assembler interleaves by
        ordinal."""
        out = []
        for item in self.assignments:
            take = self.takes.get(item.occurrence_id)
            if take is not None:
                out.append(take)
        return tuple(out)

    # -- persistence -------------------------------------------------------
    def to_record(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "revision": self.revision,
            "actor": self.actor,
            "renderer": self.renderer.to_record(),
            "renderer_fingerprint": self.renderer.fingerprint,
            "mode": self.renderer.mode,
            "assignments": [a.to_record() for a in self.assignments],
            "state": self.state,
            "takes": [t.to_record() for t in self.ordered_takes()],
            "capacity": {
                "max_request_chars": self.capacity.max_request_chars,
                "max_requests": self.capacity.max_requests,
                "max_chars": self.capacity.max_chars,
                "max_seconds": self.capacity.max_seconds,
                "label": self.capacity.label,
            },
            "history": list(self.history),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "conversations": list(self.conversations),
            "outstanding": [a.occurrence_id for a in self.outstanding()],
            "ready": bool(self.readiness()),
        }

    @classmethod
    def from_record(cls, row: Mapping[str, Any]) -> "PerformerSession":
        capacity_row = dict(row.get("capacity") or {})
        return cls(
            session_id=str(row.get("session_id") or ""),
            revision=str(row.get("revision") or ""),
            actor=str(row.get("actor") or ""),
            renderer=RendererConfig.from_record(row.get("renderer") or {}),
            assignments=[Assignment.from_record(a)
                         for a in (row.get("assignments") or ())],
            state=str(row.get("state") or "open"),
            takes={str(t.get("occurrence_id")): AcceptedTake.from_record(t)
                   for t in (row.get("takes") or ())},
            capacity=Capacity(
                max_request_chars=capacity_row.get("max_request_chars"),
                max_requests=capacity_row.get("max_requests"),
                max_chars=capacity_row.get("max_chars"),
                max_seconds=capacity_row.get("max_seconds"),
                label=str(capacity_row.get("label") or "")),
            history=row.get("history") or (),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"))


def _split_text(text: str, cap: int) -> list[str]:
    """Split on whitespace at the cap, keeping whole words. Only ever used in
    segmented mode, and the caller keeps the piece boundaries."""
    words = str(text or "").split()
    pieces: list[str] = []
    current: list[str] = []
    length = 0
    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and length + extra > cap:
            pieces.append(" ".join(current))
            current, length = [word], len(word)
            continue
        current.append(word)
        length += extra
    if current:
        pieces.append(" ".join(current))
    return pieces or [str(text or "")]


# --- the manifest store ----------------------------------------------------

@runtime_checkable
class ManifestStore(Protocol):
    """The surface this module needs. `manifest_store.py` is being written in
    parallel; if it names these differently, wrap it in `ManifestAdapter`
    rather than changing anything above."""

    def load_script(self, revision: str) -> Mapping[str, Any] | None: ...
    def save_session(self, record: Mapping[str, Any]) -> str: ...
    def load_session(self, session_id: str) -> Mapping[str, Any] | None: ...
    def list_sessions(self, revision: str = "", actor: str = ""
                      ) -> Sequence[Mapping[str, Any]]: ...
    def save_master(self, record: Mapping[str, Any]) -> str: ...
    def load_master(self, take_id: str) -> Mapping[str, Any] | None: ...
    def save_cut(self, record: Mapping[str, Any]) -> str: ...
    def list_cuts(self, revision: str, occurrence_ids: Sequence[str] = ()
                  ) -> Sequence[Mapping[str, Any]]: ...
    def pinned_occurrences(self, revision: str) -> Sequence[str]: ...


#: The one place to edit when the real store lands. Key: the name this module
#: calls. Value: the name on the real store object.
DEFAULT_METHOD_MAP: dict[str, str] = {
    "load_script": "load_script",
    "save_session": "save_session",
    "load_session": "load_session",
    "list_sessions": "list_sessions",
    "save_master": "save_master",
    "load_master": "load_master",
    "save_cut": "save_cut",
    "list_cuts": "list_cuts",
    "pinned_occurrences": "pinned_occurrences",
}


class ManifestAdapter:
    """Thin adapter onto whatever `manifest_store.py` actually exposes.

    Unknown calls raise `NotImplementedError` naming the call and the store,
    so a mismatch is a loud line in a log rather than a session that silently
    never persists."""

    def __init__(self, store: Any,
                 method_map: Mapping[str, str] | None = None) -> None:
        self._store = store
        self._map = dict(DEFAULT_METHOD_MAP)
        self._map.update(dict(method_map or {}))

    def supports(self, call: str) -> bool:
        return callable(getattr(self._store, self._map.get(call, call), None))

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        attr = self._map.get(name, name)
        fn = getattr(self._store, attr, None)
        if not callable(fn):
            raise NotImplementedError(
                f"the manifest store {type(self._store).__name__} has no "
                f"{attr!r} for speaker_session's {name!r} - map it in "
                "DEFAULT_METHOD_MAP or pass method_map=")
        return fn(*args, **kwargs)

    def load_script(self, revision: str) -> Mapping[str, Any] | None:
        return self._call("load_script", revision)

    def save_session(self, record: Mapping[str, Any]) -> str:
        return self._call("save_session", record)

    def load_session(self, session_id: str) -> Mapping[str, Any] | None:
        return self._call("load_session", session_id)

    def list_sessions(self, revision: str = "", actor: str = ""
                      ) -> Sequence[Mapping[str, Any]]:
        return self._call("list_sessions", revision, actor)

    def save_master(self, record: Mapping[str, Any]) -> str:
        return self._call("save_master", record)

    def load_master(self, take_id: str) -> Mapping[str, Any] | None:
        return self._call("load_master", take_id)

    def save_cut(self, record: Mapping[str, Any]) -> str:
        return self._call("save_cut", record)

    def list_cuts(self, revision: str, occurrence_ids: Sequence[str] = ()
                  ) -> Sequence[Mapping[str, Any]]:
        return self._call("list_cuts", revision, occurrence_ids)

    def pinned_occurrences(self, revision: str) -> Sequence[str]:
        if not self.supports("pinned_occurrences"):
            return ()
        return self._call("pinned_occurrences", revision)


class InMemoryManifestStore:
    """A complete, honest implementation of the protocol with no disk behind
    it. Tests use it; so does anything that wants to dry-run a session."""

    def __init__(self) -> None:
        self.scripts: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.masters: dict[str, dict[str, Any]] = {}
        self.cuts: dict[str, dict[str, Any]] = {}
        self.pinned: dict[str, list[str]] = {}

    def put_script(self, record: Mapping[str, Any]) -> str:
        revision = str(record.get("revision") or "")
        self.scripts[revision] = dict(record)
        return revision

    def load_script(self, revision: str) -> Mapping[str, Any] | None:
        return self.scripts.get(str(revision))

    def save_session(self, record: Mapping[str, Any]) -> str:
        session_id = str(record.get("session_id") or "")
        if not session_id:
            raise ValueError("a session record needs a session_id")
        self.sessions[session_id] = json.loads(json.dumps(record, default=str))
        return session_id

    def load_session(self, session_id: str) -> Mapping[str, Any] | None:
        row = self.sessions.get(str(session_id))
        return json.loads(json.dumps(row)) if row is not None else None

    def list_sessions(self, revision: str = "", actor: str = ""
                      ) -> Sequence[Mapping[str, Any]]:
        return [dict(row) for row in self.sessions.values()
                if (not revision or row.get("revision") == revision)
                and (not actor or row.get("actor") == actor)]

    def save_master(self, record: Mapping[str, Any]) -> str:
        take_id = str(record.get("take_id") or "")
        if not take_id:
            raise ValueError("a master record needs a take_id")
        self.masters[take_id] = dict(record)
        return take_id

    def load_master(self, take_id: str) -> Mapping[str, Any] | None:
        return self.masters.get(str(take_id))

    def save_cut(self, record: Mapping[str, Any]) -> str:
        key = f"{record.get('revision')}::{record.get('occurrence_id')}"
        self.cuts[key] = dict(record)
        return key

    def list_cuts(self, revision: str, occurrence_ids: Sequence[str] = ()
                  ) -> Sequence[Mapping[str, Any]]:
        wanted = set(occurrence_ids or ())
        return [dict(row) for key, row in self.cuts.items()
                if key.startswith(f"{revision}::")
                and (not wanted or row.get("occurrence_id") in wanted)]

    def pinned_occurrences(self, revision: str) -> Sequence[str]:
        return list(self.pinned.get(str(revision)) or ())


# --- lifecycle -------------------------------------------------------------

def new_session(revision: str, actor: str, renderer: RendererConfig,
                assignments: Sequence[Assignment],
                capacity: Capacity | None = None,
                session_id: str = "") -> PerformerSession:
    return PerformerSession(
        session_id=session_id or f"ps_{uuid.uuid4().hex[:12]}",
        revision=revision, actor=actor, renderer=renderer,
        assignments=assignments, capacity=capacity or UNLIMITED)


def persist_session(store: Any, session: PerformerSession) -> str:
    adapter = store if isinstance(store, ManifestAdapter) else ManifestAdapter(store)
    return adapter.save_session(session.to_record())


def resume_session(store: Any, session_id: str,
                   assignments: Sequence[Assignment] | None = None,
                   renderer: RendererConfig | None = None,
                   revision: str = "") -> tuple[PerformerSession | None,
                                                tuple[str, ...]]:
    """Reload a session and keep only the work that is still verified.

    Returns (session, dropped_reasons). A take is dropped when its revision
    or renderer no longer matches, when its mode is not the session's, or
    when it is not verified - the note's "resume from verified work", read
    strictly. Dropping is not a failure: the occurrence simply goes back on
    the outstanding list and is recorded again.

    `assignments` / `renderer` / `revision` let a caller re-state the current
    contract. Where they differ from the stored record, the CALLER wins and
    the mismatched takes are dropped, because the frozen script is the
    authority and a stored session is only a memory of one."""
    adapter = store if isinstance(store, ManifestAdapter) else ManifestAdapter(store)
    row = adapter.load_session(session_id)
    if not row:
        return None, (f"no stored session {session_id}",)
    session = PerformerSession.from_record(row)
    dropped: list[str] = []
    if revision and revision != session.revision:
        dropped.append(
            f"stored revision {session.revision} replaced by {revision}")
        session.revision = revision
    if renderer is not None and renderer.fingerprint != session.renderer.fingerprint:
        dropped.append("renderer configuration changed since the last pass")
        session.renderer = renderer
    elif renderer is not None:
        session.renderer = renderer
    if assignments is not None:
        session.assignments = tuple(
            sorted(assignments, key=lambda a: (a.ordinal, a.occurrence_id)))
    required = set(session.required_ids)
    for oid, take in list(session.takes.items()):
        why = ""
        if oid not in required:
            why = "no longer assigned to this session"
        elif take.revision != session.revision:
            why = f"recorded against revision {take.revision}"
        elif take.renderer_fingerprint != session.renderer.fingerprint:
            why = "recorded with a different renderer configuration"
        elif take.mode != session.renderer.mode:
            why = f"is a {take.mode} take in a {session.renderer.mode} session"
        elif not take.verified:
            why = ("unverified: "
                   + (str(dict(take.verification or {}).get("verdict"))
                      or "no verdict"))
        if why:
            session.takes.pop(oid, None)
            dropped.append(f"{oid}: {why}")
    pinned = set(adapter.pinned_occurrences(session.revision) or ())
    held = pinned & set(session.takes)
    if held:
        session.note("pinned", ", ".join(sorted(held)))
    if session.state not in ("failed", "abandoned"):
        session._settle()                      # noqa: SLF001 - our own object
    if dropped:
        session.note("resumed", f"dropped {len(dropped)} take(s)")
    else:
        session.note("resumed", "every stored take still verifies")
    return session, tuple(dropped)


# --- finishing conversations, not starting all of them ---------------------

@dataclass(frozen=True)
class ConversationJob:
    """One conversation and every performer session it needs. A conversation
    is useful only when ALL of its sessions are ready - which is why the
    scheduler below counts a conversation's work, never a session's."""
    conversation_id: str
    sessions: tuple[PerformerSession, ...]

    @property
    def outstanding_chars(self) -> int:
        return sum(s.outstanding_chars() for s in self.sessions)

    @property
    def outstanding_lines(self) -> int:
        return sum(len(s.outstanding()) for s in self.sessions)

    @property
    def ready(self) -> bool:
        return bool(self.sessions) and all(bool(s.readiness())
                                           for s in self.sessions)


@dataclass(frozen=True)
class Allocation:
    """What a pass decided to do. `started` conversations are the ones the
    budget can finish; `untouched` are deliberately not begun."""
    finish: tuple[str, ...] = ()
    untouched: tuple[str, ...] = ()
    plans: Mapping[str, RenderPlan] = field(default_factory=dict)
    spent_chars: int = 0
    note: str = ""


def finish_first_order(jobs: Sequence[ConversationJob]
                       ) -> tuple[ConversationJob, ...]:
    """Closest to finished first.

    Cheapest-to-complete, then fewest lines left, then id for determinism.
    Already-ready conversations sort first and cost nothing, so a pass that
    re-runs is stable."""
    return tuple(sorted(
        jobs, key=lambda j: (j.outstanding_chars, j.outstanding_lines,
                             j.conversation_id)))


def allocate(jobs: Sequence[ConversationJob], capacity: Capacity,
             partial_when_idle: bool = True) -> Allocation:
    """Spend a budget on conversations it can FINISH.

    The note: "A whole-conversation job should finish useful conversations
    rather than leave every candidate partly recorded." So the budget is
    committed a whole conversation at a time; a conversation that will not fit
    is left untouched for the next pass rather than started and stranded.

    `partial_when_idle` covers the one case where refusing to start is worse
    than starting: nothing fits at all. Then the cheapest conversation is
    begun anyway, its sessions go `blocked`, and the next pass resumes them -
    which is exactly what blocked is for. A conversation bigger than any
    budget would otherwise never be recorded at all."""
    order = finish_first_order(jobs)
    budget = capacity.max_chars
    spent = 0
    finish: list[str] = []
    untouched: list[str] = []
    plans: dict[str, RenderPlan] = {}
    for job in order:
        if job.outstanding_chars == 0:
            continue
        cost = job.outstanding_chars
        if budget is not None and spent + cost > int(budget):
            untouched.append(job.conversation_id)
            continue
        for session in job.sessions:
            if session.outstanding():
                plans[session.session_id] = session.plan(capacity)
        finish.append(job.conversation_id)
        spent += cost
    note = f"{len(finish)} conversation(s) inside the budget"
    if not finish and untouched and partial_when_idle:
        job = order[0] if order else None
        if job is not None:
            for session in job.sessions:
                if session.outstanding():
                    plans[session.session_id] = session.plan(capacity)
                    session.block(
                        "started under a budget too small to finish this "
                        "conversation in one pass")
            untouched = [c for c in untouched if c != job.conversation_id]
            note = (f"nothing fitted; started {job.conversation_id} anyway and "
                    "blocked it for the next pass")
            spent = int(budget or 0)
            return Allocation(tuple(), tuple(untouched), plans, spent, note)
    return Allocation(tuple(finish), tuple(untouched), plans, spent, note)
