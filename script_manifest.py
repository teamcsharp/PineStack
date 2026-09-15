"""Manifests for recorded speech: what was written, who performed it, exactly
where each line was cut, what the finished conversation is, and what was
admitted to the broadcast.

Pure data and pure validation. This module imports nothing from the station:
no `app`, no runtime store, no clock the caller cannot pass in, no disk.
Durability lives next door in `manifest_store.py`.

Implements boundary 1 of `docs/notes/speaker-recording-and-script-assembly.md`.

Two boundaries are kept separate, deliberately:

    freezing a production script authorizes RECORDING
    committing a broadcast sequence authorizes PLAYBACK

A candidate can be abandoned or replaced between them without moving a line
already admitted to the reader.

--------------------------------------------------------------------------
PUBLIC SURFACE
--------------------------------------------------------------------------

Every validator returns the same *result* shape, never a bare bool:

    {"ok": bool,
     "refusals": [{"code": str, "reason": str, "where": dict}, ...],
     "reasons": [str, ...],          # the readable reasons, in order
     "reason": str,                  # the first reason, or ""
     ...validator-specific extras}

Constructors return plain JSON-serializable dicts and raise `ManifestError`
(a ValueError) with a readable message when the input cannot become a record
at all. Refusals a caller is expected to handle come back as results.

Identity and evidence helpers
  audio_digest(data: bytes) -> str                      "sha256:<64 hex>"
  is_audio_digest(value) -> bool
  words_of(text) -> [str, ...]
  content_cache_key(text, voice, engine) -> str         sha1 hex; the station's
      pantry key (app.py:13618). Optional content REUSE only - it cannot tell
      two differently performed occurrences of the same words apart. Never
      use it as manifest identity.
  text_coverage(expected: str, heard: str) -> dict
      {"coverage": float 0..1, "expected": int, "heard": int, "matched": int,
       "missing": [word...], "repeated": [word...], "extra": [word...]}
  occurrence_id(revision, ordinal, actor, text) -> str  "occ-<20 hex>"
  performance_digest(line, cast_entry) -> str           "pc-<20 hex>"
  script_revision(conversation_id, cast, lines) -> str  "rev-<20 hex>"

Constructors (all return dicts; all raise ManifestError on malformed input)
  script_line(actor, text, *, pronunciations=(), instructions="",
              context_before="", context_after="", chunks=()) -> dict
  frozen_script(conversation_id, cast, lines, *, created_at=None,
                notes="") -> dict
      cast: {actor: {"voice": str, "engine": str, "config": dict,
                     "display": str}}
      lines: ordered [script_line(...)...]; ordinals are assigned 1..N from
      that order and an occurrence id is minted for every utterance, so two
      occurrences of identical words are distinct records.
  revise_script(script, *, lines=None, cast=None, conversation_id=None,
                notes=None, created_at=None) -> dict
      Any change produces a NEW revision. Never mutates its argument.
  performer_session(session_id, script, actor, *, assignments=None,
                    engine=None, voice=None, engine_config=None,
                    state="open", accepted=None, created_at=None) -> dict
  master_recording(take_id, *, session_id, revision, actor, audio_sha256,
                   sample_rate, frame_count, media_ref, channels=1,
                   mode="segmented", created_at=None) -> dict
  line_cut(cut_id, *, occurrence_id, ordinal, take_id, master_sha256,
           sample_rate, start_sample, end_sample, boundary_method,
           verification=None, state="pending", created_at=None) -> dict
  cue_entry(*, occurrence_id, ordinal, cut_id, cue_start_sample,
            speech_start_sample, speech_end_sample, cue_end_sample,
            source_frames=0) -> dict
  finished_conversation(assembly_id, *, revision, cuts, mix, final_sha256,
                        final_sample_rate, final_frame_count, cue_map,
                        cue_source="measured", cue_map_revision=None,
                        created_at=None) -> dict
  broadcast_admission(admission_id, *, assembly, playback_occurrence_id=None,
                      start_position=1, sequence_positions=None,
                      admitted_at=None) -> dict

Validators (result shape above)
  validate_frozen_script(script) -> result
      extras: {"revision": str, "sequence": [occurrence_id...]}
  validate_session(session, script, *, cuts=None) -> result
      extras: {"accepted": int, "remaining": [occurrence_id...]}
  validate_master(master, *, session=None, script=None) -> result
      extras: {"seconds": float}
  verify_master_bytes(master, data: bytes) -> result
      extras: {"digest": str}
  validate_cut(cut, *, master, script, min_coverage=0.98) -> result
      extras: {"coverage": float|None, "missing": [...], "repeated": [...],
               "frames": int, "seconds": float}
  validate_cut_set(cuts, *, script, masters=None, occurrences=None,
                   min_coverage=0.98) -> result
      extras: {"accepted": {occurrence_id: cut_id}, "missing": [...],
               "duplicates": {occurrence_id: [cut_id, ...]}}
  validate_assembly(assembly, *, script, cuts_by_id, masters=None,
                    min_coverage=0.98) -> result
      extras: {"sequence": [occurrence_id...], "frames": int,
               "seconds": float}
  validate_admission(admission, *, assembly, script, cuts_by_id=None,
                     masters=None, used_playback_occurrences=()) -> result
      extras: {"positions": {occurrence_id: int}}
  validate_playback_receipt(admission, receipt, *, assembly=None,
                            now_ms=None, max_age_ms=None) -> result
      extras: {"occurrence_id": str|None, "ordinal": int|None,
               "position_samples": int|None}

Sequence, reuse and pinning
  script_sequence(script) -> [occurrence_id...]
  script_line_by_occurrence(script, occurrence_id) -> dict|None
  cue_sequence(assembly) -> [occurrence_id...]
  cue_lookup(assembly, position_samples) -> result
      extras: {"occurrence_id": str|None, "ordinal": int|None,
               "speaking": bool}
  carry_over(old_script, new_script, cuts_by_occurrence) -> result
      cuts_by_occurrence: {occurrence_id: cut_id}
      extras: {"carried": {new_occurrence_id: cut_id},
               "dropped": [{"occurrence_id","ordinal","reason","changed"}]}
  pin_index(admissions, assemblies_by_id, cuts_by_id) -> dict
      {"takes": {take_id: [pin...]}, "cuts": {cut_id: [pin...]},
       "assemblies": {assembly_id: [pin...]},
       "revisions": {revision: [pin...]}}
      pin = {"admission_id","playback_occurrence_id","assembly_id",
             "occurrence_id","cut_id","take_id"}
  check_overwrite(kind, identifier, existing, replacement, pins) -> result
      kind in ("script","session","master","cut","assembly","admission").
      Identical content is always allowed; different content over a record
      pinned by an admitted broadcast occurrence is refused.

--------------------------------------------------------------------------
REFUSAL CODES
--------------------------------------------------------------------------
Every one carries a sentence a person can read. The full list lives in
`docs/notes/manifests-implemented-2026-09-15.md`.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import time
import unicodedata
import uuid
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = 1

SESSION_STATES = ("open", "recording", "interrupted", "complete", "abandoned")
CUT_STATES = ("pending", "accepted", "rejected")
MASTER_MODES = ("continuous", "segmented")

# A boundary the renderer itself reported, an alignment against the known
# script, or a human edit. Silence alone cannot establish which line was
# spoken (app.py:32685 records that experiment failing), so it is not here.
BOUNDARY_METHODS = ("renderer_boundary", "alignment", "manual")
AMBIGUOUS_BOUNDARY_METHODS = ("silence", "silence_split", "estimate",
                              "estimated", "guess", "threshold", "")

# The stream path rescales estimated cue windows to fit the finished duration
# (app.py:83945). A rescaled cue map is not evidence of where a line is.
CUE_SOURCES = ("measured",)
REFUSED_CUE_SOURCES = ("estimated", "estimate", "rescaled", "scaled",
                       "guessed", "approximate")

DEFAULT_MIN_COVERAGE = 0.98

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)*", re.UNICODE)


class ManifestError(ValueError):
    """Input that cannot become a record at all. The message is readable."""


# --------------------------------------------------------------------------
# small pure helpers
# --------------------------------------------------------------------------

def _text(value: Any, field: str, *, required: bool = True) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ManifestError("%s must be text, not %s" % (field, type(value).__name__))
    out = value.strip()
    if required and not out:
        raise ManifestError("%s must not be empty" % field)
    return out


def _whole(value: Any, field: str, *, low: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError("%s must be a whole number of samples, not %r"
                            % (field, value))
    if value < low:
        raise ManifestError("%s must be at least %d, not %d" % (field, low, value))
    return int(value)


def _mapping(value: Any, field: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ManifestError("%s must be a mapping, not %s"
                            % (field, type(value).__name__))
    return dict(value)


def _listed(value: Any, field: str) -> list:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ManifestError("%s must be a list" % field)
    return list(value)


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(",", ":"), default=str)


def _digest_of(prefix: str, payload: Any, size: int = 20) -> str:
    raw = _stable(payload).encode("utf-8", "surrogatepass")
    return prefix + hashlib.sha256(raw).hexdigest()[:size]


def _now(at: Any = None) -> float:
    return float(at) if at is not None else float(time.time())


def _norm_text(text: Any) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).replace("’", "'")


def words_of(text: Any) -> list[str]:
    """The comparable words of a line: NFKC, curly quotes folded, casefolded."""
    return [w.casefold() for w in _WORD.findall(_norm_text(text))]


def _refuse(code: str, reason: str, **where: Any) -> dict:
    return {"code": str(code), "reason": str(reason),
            "where": {k: v for k, v in where.items() if v is not None}}


def _result(refusals: Iterable[dict] | None, **extra: Any) -> dict:
    rows = [r for r in (refusals or []) if r]
    out: dict[str, Any] = {
        "ok": not rows,
        "refusals": rows,
        "reasons": [r["reason"] for r in rows],
        "reason": rows[0]["reason"] if rows else "",
    }
    out.update(extra)
    return out


# --------------------------------------------------------------------------
# identity and evidence
# --------------------------------------------------------------------------

def audio_digest(data: bytes) -> str:
    """The immutable audio hash of some bytes: "sha256:<64 hex>"."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ManifestError("audio_digest needs bytes, not %s" % type(data).__name__)
    return "sha256:" + hashlib.sha256(bytes(data)).hexdigest()


def is_audio_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_DIGEST.fullmatch(value))


def content_cache_key(text: str, voice: str, engine: str) -> str:
    """The station's pantry key (app.py:13618), reproduced exactly.

    It hashes engine, voice and text, so two occurrences of identical words
    collide. Keep it for optional content reuse; manifest identity is
    `occurrence_id`, which cannot collide that way.
    """
    raw = "%s\x00%s\x00%s" % (engine, voice, str(text or "").strip())
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()


def text_coverage(expected: str, heard: str) -> dict:
    """Word evidence that a recording contains the scripted line.

    Returns {"coverage", "expected", "heard", "matched", "missing",
    "repeated", "extra"}. `missing` is scripted speech the transcript does not
    contain; `repeated` is heard speech that duplicates scripted words;
    `extra` is heard speech that is not in the script at all. A timestamp on
    every input word is not this evidence: this compares what was asked for
    with what was heard.
    """
    want = words_of(expected)
    got = words_of(heard)
    if not want:
        return {"coverage": 0.0, "expected": 0, "heard": len(got), "matched": 0,
                "missing": [], "repeated": [], "extra": got}
    match = difflib.SequenceMatcher(a=want, b=got, autojunk=False)
    matched = 0
    missing: list[str] = []
    surplus: list[str] = []
    for tag, i1, i2, j1, j2 in match.get_opcodes():
        if tag == "equal":
            matched += i2 - i1
        elif tag == "delete":
            missing.extend(want[i1:i2])
        elif tag == "insert":
            surplus.extend(got[j1:j2])
        else:
            missing.extend(want[i1:i2])
            surplus.extend(got[j1:j2])
    known = set(want)
    return {"coverage": matched / float(len(want)), "expected": len(want),
            "heard": len(got), "matched": matched, "missing": missing,
            "repeated": [w for w in surplus if w in known],
            "extra": [w for w in surplus if w not in known]}


def occurrence_id(revision: str, ordinal: int, actor: str, text: str) -> str:
    """The ordered identity of one utterance inside one revision.

    The ordinal is part of the identity, so two occurrences of identical
    words spoken by the same actor are different records.
    """
    return _digest_of("occ-", ["occurrence", str(revision), int(ordinal),
                               str(actor), _norm_text(text)])


def performance_digest(line: Mapping, cast_entry: Mapping) -> str:
    """Everything a performer must reproduce, minus the line's position.

    Exact spoken text, actor, voice, engine, engine configuration,
    pronunciation changes, performance instructions, surrounding context and
    the render chunks a displayed line maps to. Completed audio is reusable
    across revisions only when this digest is unchanged.
    """
    entry = dict(cast_entry or {})
    return _digest_of("pc-", {
        "actor": str(line.get("actor") or ""),
        "text": str(line.get("text") or ""),
        "pronunciations": sorted(_stable(p) for p in (line.get("pronunciations") or [])),
        "instructions": str(line.get("instructions") or ""),
        "context_before": str(line.get("context_before") or ""),
        "context_after": str(line.get("context_after") or ""),
        "chunks": list(line.get("chunks") or []),
        "voice": str(entry.get("voice") or ""),
        "engine": str(entry.get("engine") or ""),
        "config": entry.get("config") or {},
    })


def script_revision(conversation_id: str, cast: Mapping,
                    lines: Sequence[Mapping]) -> str:
    """A content-derived revision. Any change to the contract changes it."""
    return _digest_of("rev-", {
        "conversation": str(conversation_id),
        "cast": {str(k): {"voice": str(dict(v).get("voice") or ""),
                          "engine": str(dict(v).get("engine") or ""),
                          "config": dict(v).get("config") or {}}
                 for k, v in dict(cast or {}).items()},
        "lines": [{"ordinal": i + 1,
                   "actor": str(row.get("actor") or ""),
                   "text": str(row.get("text") or ""),
                   "pronunciations": list(row.get("pronunciations") or []),
                   "instructions": str(row.get("instructions") or ""),
                   "context_before": str(row.get("context_before") or ""),
                   "context_after": str(row.get("context_after") or ""),
                   "chunks": list(row.get("chunks") or [])}
                  for i, row in enumerate(lines or [])],
    })


# --------------------------------------------------------------------------
# 1. the frozen script
# --------------------------------------------------------------------------

def script_line(actor: str, text: str, *, pronunciations: Iterable = (),
                instructions: str = "", context_before: str = "",
                context_after: str = "", chunks: Iterable = ()) -> dict:
    """One utterance, before freezing.

    Ordinals and occurrence ids are minted by `frozen_script` from list
    order, never supplied here.
    """
    return {"actor": _text(actor, "actor"),
            "text": _text(text, "text"),
            "pronunciations": [dict(p) if isinstance(p, Mapping) else {"say": str(p)}
                               for p in (pronunciations or [])],
            "instructions": _text(instructions, "instructions", required=False),
            "context_before": _text(context_before, "context_before", required=False),
            "context_after": _text(context_after, "context_after", required=False),
            "chunks": [str(c) for c in (chunks or [])]}


def _cast_entry(actor: str, value: Any) -> dict:
    row = _mapping(value, "cast[%s]" % actor)
    return {"voice": _text(row.get("voice"), "cast[%s].voice" % actor),
            "engine": _text(row.get("engine"), "cast[%s].engine" % actor),
            "config": _mapping(row.get("config"), "cast[%s].config" % actor),
            "display": _text(row.get("display") or actor,
                             "cast[%s].display" % actor, required=False)}


def frozen_script(conversation_id: str, cast: Mapping, lines: Sequence[Mapping],
                  *, created_at: float | None = None, notes: str = "") -> dict:
    """Freeze the performance contract. This authorizes recording, nothing else.

    Returns {"kind": "frozen_script", "schema", "revision", "conversation_id",
    "created_at", "notes", "cast", "lines", "sequence", "frozen": True}. Each
    line carries occurrence_id, ordinal (1..N), actor, text, pronunciations,
    instructions, context, chunks and performance_digest.
    """
    conversation = _text(conversation_id, "conversation_id")
    rows = _listed(lines, "lines")
    if not rows:
        raise ManifestError("a frozen script needs at least one line")
    people = {str(k): _cast_entry(str(k), v)
              for k, v in _mapping(cast, "cast").items()}
    if not people:
        raise ManifestError("a frozen script needs a cast")
    prepared: list[dict] = []
    for index, row in enumerate(rows):
        row = _mapping(row, "lines[%d]" % index)
        if row.get("ordinal") is not None and int(row["ordinal"]) != index + 1:
            raise ManifestError(
                "lines[%d] carries ordinal %s but freezing assigns %d from reading "
                "order" % (index, row["ordinal"], index + 1))
        prepared.append(script_line(
            row.get("actor"), row.get("text"),
            pronunciations=row.get("pronunciations") or (),
            instructions=row.get("instructions") or "",
            context_before=row.get("context_before") or "",
            context_after=row.get("context_after") or "",
            chunks=row.get("chunks") or ()))
    for index, row in enumerate(prepared):
        if row["actor"] not in people:
            raise ManifestError("lines[%d] is spoken by %r, who is not in the cast"
                                % (index, row["actor"]))
    revision = script_revision(conversation, people, prepared)
    out_lines = []
    for index, row in enumerate(prepared):
        ordinal = index + 1
        out_lines.append(dict(
            row, ordinal=ordinal,
            occurrence_id=occurrence_id(revision, ordinal, row["actor"], row["text"]),
            performance_digest=performance_digest(row, people[row["actor"]])))
    return {"kind": "frozen_script", "schema": SCHEMA, "revision": revision,
            "conversation_id": conversation, "created_at": _now(created_at),
            "notes": _text(notes, "notes", required=False), "cast": people,
            "lines": out_lines,
            "sequence": [r["occurrence_id"] for r in out_lines],
            "frozen": True}


def revise_script(script: Mapping, *, lines: Sequence[Mapping] | None = None,
                  cast: Mapping | None = None, conversation_id: str | None = None,
                  notes: str | None = None, created_at: float | None = None) -> dict:
    """A changed script is a NEW revision, never an edit of the old one."""
    base = _mapping(script, "script")
    return frozen_script(
        conversation_id if conversation_id is not None else base.get("conversation_id"),
        cast if cast is not None else base.get("cast"),
        lines if lines is not None else base.get("lines"),
        created_at=created_at,
        notes=notes if notes is not None else base.get("notes") or "")


def script_sequence(script: Mapping) -> list[str]:
    """The frozen reading order, as occurrence ids."""
    return [str(r.get("occurrence_id") or "")
            for r in (_mapping(script, "script").get("lines") or [])]


def script_line_by_occurrence(script: Mapping, occurrence: str) -> dict | None:
    """The frozen line an occurrence id names, or None."""
    for row in (_mapping(script, "script").get("lines") or []):
        if row.get("occurrence_id") == occurrence:
            return dict(row)
    return None


def validate_frozen_script(script: Mapping) -> dict:
    """Re-derive the revision and every occurrence id from the content."""
    refusals: list[dict] = []
    try:
        base = _mapping(script, "script")
    except ManifestError as err:
        return _result([_refuse("script_malformed", str(err))],
                       revision="", sequence=[])
    if base.get("kind") != "frozen_script":
        return _result([_refuse("script_malformed",
                                "this record is not a frozen script")],
                       revision=base.get("revision"), sequence=[])
    rows = base.get("lines") or []
    cast = base.get("cast") or {}
    if not rows:
        refusals.append(_refuse("script_empty",
                                "a frozen script with no lines authorizes no "
                                "recording"))
    if not cast:
        refusals.append(_refuse("script_no_cast",
                                "a frozen script with no cast names nobody to "
                                "perform it"))
    seen: set[str] = set()
    for index, row in enumerate(rows):
        where = {"ordinal": row.get("ordinal"),
                 "occurrence_id": row.get("occurrence_id")}
        if row.get("ordinal") != index + 1:
            refusals.append(_refuse(
                "script_ordinal_gap",
                "line %d carries ordinal %r; the reading order must be 1..N with no "
                "gaps" % (index + 1, row.get("ordinal")), **where))
        if not str(row.get("text") or "").strip():
            refusals.append(_refuse("script_empty_line",
                                    "line %d has no spoken text" % (index + 1),
                                    **where))
        if row.get("actor") not in cast:
            refusals.append(_refuse(
                "script_unknown_actor",
                "line %d is spoken by %r, who is not in the cast"
                % (index + 1, row.get("actor")), **where))
        ident = str(row.get("occurrence_id") or "")
        if ident in seen:
            refusals.append(_refuse(
                "script_duplicate_occurrence",
                "occurrence %s appears twice; two occurrences of the same words must "
                "have different ids" % ident, **where))
        seen.add(ident)
        expected = occurrence_id(base.get("revision"), index + 1,
                                 row.get("actor"), row.get("text"))
        if ident and ident != expected:
            refusals.append(_refuse(
                "script_occurrence_mismatch",
                "line %d's occurrence id does not match its own revision, actor and "
                "text; the record has been edited in place" % (index + 1), **where))
    if rows and cast:
        try:
            expected_revision = script_revision(base.get("conversation_id"), cast, rows)
        except Exception as err:  # noqa: BLE001
            expected_revision = ""
            refusals.append(_refuse("script_malformed",
                                    "the script content cannot be digested: %s" % err))
        if expected_revision and expected_revision != base.get("revision"):
            refusals.append(_refuse(
                "script_revision_mismatch",
                "the stored revision %r does not describe this content; a script "
                "change must create a new revision" % base.get("revision")))
    if list(base.get("sequence") or []) != [r.get("occurrence_id") for r in rows]:
        refusals.append(_refuse("script_sequence_mismatch",
                                "the stored sequence is not the line order"))
    return _result(refusals, revision=base.get("revision"),
                   sequence=[r.get("occurrence_id") for r in rows])


# --------------------------------------------------------------------------
# 2. the performer session
# --------------------------------------------------------------------------

def performer_session(session_id: str, script: Mapping, actor: str, *,
                      assignments: Sequence[str] | None = None,
                      engine: str | None = None, voice: str | None = None,
                      engine_config: Mapping | None = None,
                      state: str = "open", accepted: Mapping | None = None,
                      created_at: float | None = None) -> dict:
    """One performer's whole part of one frozen revision.

    `assignments` defaults to every occurrence this actor speaks, in reading
    order. `accepted` maps occurrence_id -> cut_id. Returns a record of kind
    "performer_session" carrying session_id, revision, actor, voice, engine,
    engine_config, assignments, state, accepted, created_at, updated_at.
    """
    base = _mapping(script, "script")
    who = _text(actor, "actor")
    cast = _mapping(base.get("cast"), "script.cast")
    if who not in cast:
        raise ManifestError("%r is not in the cast of revision %s"
                            % (who, base.get("revision")))
    entry = cast[who]
    mine = [r["occurrence_id"] for r in (base.get("lines") or [])
            if r.get("actor") == who]
    picked = [str(a) for a in assignments] if assignments is not None else mine
    if not picked:
        raise ManifestError("%r has no lines in revision %s"
                            % (who, base.get("revision")))
    if state not in SESSION_STATES:
        raise ManifestError("unknown session state %r; expected one of %s"
                            % (state, ", ".join(SESSION_STATES)))
    return {"kind": "performer_session", "schema": SCHEMA,
            "session_id": _text(session_id, "session_id"),
            "revision": _text(base.get("revision"), "script.revision"),
            "conversation_id": base.get("conversation_id"),
            "actor": who,
            "voice": _text(voice or entry.get("voice"), "voice"),
            "engine": _text(engine or entry.get("engine"), "engine"),
            "engine_config": _mapping(engine_config if engine_config is not None
                                      else entry.get("config"), "engine_config"),
            "assignments": picked,
            "state": state,
            "accepted": {str(k): str(v)
                         for k, v in _mapping(accepted, "accepted").items()},
            "created_at": _now(created_at),
            "updated_at": _now(created_at)}


def validate_session(session: Mapping, script: Mapping, *,
                     cuts: Mapping | None = None) -> dict:
    """Assignments, actor identity, engine contract and completeness.

    `cuts` is an optional {cut_id: cut} map; when given, every accepted entry
    must point at an accepted cut of that same occurrence.
    """
    refusals: list[dict] = []
    row = _mapping(session, "session")
    base = _mapping(script, "script")
    if row.get("kind") != "performer_session":
        return _result([_refuse("session_malformed",
                                "this record is not a performer session")],
                       accepted=0, remaining=[])
    if row.get("revision") != base.get("revision"):
        return _result([_refuse(
            "session_revision_mismatch",
            "session %s was recorded against revision %s but was checked against %s"
            % (row.get("session_id"), row.get("revision"), base.get("revision")))],
            accepted=0, remaining=list(row.get("assignments") or []))
    cast = _mapping(base.get("cast"), "cast")
    actor = row.get("actor")
    entry = cast.get(actor)
    if entry is None:
        refusals.append(_refuse("session_unknown_actor",
                                "%r is not in the cast of revision %s"
                                % (actor, base.get("revision"))))
    elif row.get("voice") != entry.get("voice") or row.get("engine") != entry.get("engine"):
        refusals.append(_refuse(
            "session_contract_mismatch",
            "session %s records %s with voice %r on %r, but the frozen cast says "
            "voice %r on %r" % (row.get("session_id"), actor, row.get("voice"),
                                row.get("engine"), entry.get("voice"),
                                entry.get("engine"))))
    if row.get("state") not in SESSION_STATES:
        refusals.append(_refuse("session_unknown_state",
                                "unknown session state %r" % row.get("state")))
    by_id = {r.get("occurrence_id"): r for r in (base.get("lines") or [])}
    order = {ident: i for i, ident in enumerate(script_sequence(base))}
    picked = [str(a) for a in (row.get("assignments") or [])]
    if not picked:
        refusals.append(_refuse("session_no_assignments",
                                "session %s has no assigned lines"
                                % row.get("session_id")))
    seen: set[str] = set()
    last = -1
    for ident in picked:
        line = by_id.get(ident)
        if line is None:
            refusals.append(_refuse(
                "session_unknown_occurrence",
                "session %s is assigned %s, which is not a line of revision %s"
                % (row.get("session_id"), ident, base.get("revision")),
                occurrence_id=ident))
            continue
        if line.get("actor") != actor:
            refusals.append(_refuse(
                "session_wrong_actor",
                "session %s for %s is assigned %s, which %s speaks"
                % (row.get("session_id"), actor, ident, line.get("actor")),
                occurrence_id=ident))
        if ident in seen:
            refusals.append(_refuse("session_duplicate_assignment",
                                    "session %s is assigned %s twice"
                                    % (row.get("session_id"), ident),
                                    occurrence_id=ident))
        seen.add(ident)
        place = order.get(ident, -1)
        if place < last:
            refusals.append(_refuse(
                "session_assignments_unordered",
                "session %s lists %s out of the frozen reading order"
                % (row.get("session_id"), ident), occurrence_id=ident))
        last = max(last, place)
    accepted = _mapping(row.get("accepted"), "accepted")
    for ident, cut_id in accepted.items():
        if ident not in seen:
            refusals.append(_refuse(
                "session_accepted_unassigned",
                "session %s accepted a take for %s, which it was never assigned"
                % (row.get("session_id"), ident), occurrence_id=ident))
        if cuts is None:
            continue
        cut = _mapping(cuts, "cuts").get(cut_id)
        if cut is None:
            refusals.append(_refuse(
                "session_accepted_missing_cut",
                "session %s accepted cut %s for %s, but no such cut record exists"
                % (row.get("session_id"), cut_id, ident),
                occurrence_id=ident, cut_id=cut_id))
            continue
        if cut.get("occurrence_id") != ident:
            refusals.append(_refuse(
                "session_accepted_wrong_cut",
                "session %s accepted cut %s for %s, but that cut is a cut of %s"
                % (row.get("session_id"), cut_id, ident, cut.get("occurrence_id")),
                occurrence_id=ident, cut_id=cut_id))
        if cut.get("state") != "accepted":
            refusals.append(_refuse(
                "session_accepted_unaccepted_cut",
                "session %s counts cut %s as done, but that cut is %r"
                % (row.get("session_id"), cut_id, cut.get("state")),
                occurrence_id=ident, cut_id=cut_id))
    remaining = [ident for ident in picked if ident not in accepted]
    if row.get("state") == "complete" and remaining:
        refusals.append(_refuse(
            "session_incomplete",
            "session %s is marked complete but %d of %d lines have no accepted take: "
            "%s" % (row.get("session_id"), len(remaining), len(picked),
                    ", ".join(remaining[:6]))))
    return _result(refusals, accepted=len(accepted), remaining=remaining)


# --------------------------------------------------------------------------
# 3. masters and line cuts
# --------------------------------------------------------------------------

def master_recording(take_id: str, *, session_id: str, revision: str, actor: str,
                     audio_sha256: str, sample_rate: int, frame_count: int,
                     media_ref: str, channels: int = 1, mode: str = "segmented",
                     created_at: float | None = None) -> dict:
    """One speaker master: immutable hash, explicit sample rate, frame count.

    `mode` is explicit and never inferred: "continuous" means one performance,
    "segmented" means boundaries retained from bounded engine segments. A
    regrouped set of independent render calls is "segmented".
    """
    if mode not in MASTER_MODES:
        raise ManifestError("unknown master mode %r; expected one of %s"
                            % (mode, ", ".join(MASTER_MODES)))
    if not is_audio_digest(audio_sha256):
        raise ManifestError("audio_sha256 must look like sha256:<64 hex>, not %r"
                            % (audio_sha256,))
    return {"kind": "master_recording", "schema": SCHEMA,
            "take_id": _text(take_id, "take_id"),
            "session_id": _text(session_id, "session_id"),
            "revision": _text(revision, "revision"),
            "actor": _text(actor, "actor"),
            "audio_sha256": audio_sha256,
            "sample_rate": _whole(sample_rate, "sample_rate", low=1),
            "frame_count": _whole(frame_count, "frame_count", low=1),
            "channels": _whole(channels, "channels", low=1),
            "media_ref": _text(media_ref, "media_ref"),
            "mode": mode,
            "created_at": _now(created_at)}


def validate_master(master: Mapping, *, session: Mapping | None = None,
                    script: Mapping | None = None) -> dict:
    """A master must carry its own hash, rate, length, media and mode."""
    refusals: list[dict] = []
    row = _mapping(master, "master")
    if row.get("kind") != "master_recording":
        return _result([_refuse("master_malformed",
                                "this record is not a master recording")],
                       seconds=0.0)
    rate = row.get("sample_rate")
    frames = row.get("frame_count")
    if not isinstance(rate, int) or isinstance(rate, bool) or rate <= 0:
        refusals.append(_refuse(
            "master_no_sample_rate",
            "take %s has no usable sample rate (%r); sample positions mean nothing "
            "without one" % (row.get("take_id"), rate)))
    if not isinstance(frames, int) or isinstance(frames, bool) or frames <= 0:
        refusals.append(_refuse("master_no_frames",
                                "take %s has no frame count (%r)"
                                % (row.get("take_id"), frames)))
    if not is_audio_digest(row.get("audio_sha256")):
        refusals.append(_refuse("master_no_hash",
                                "take %s has no immutable audio hash"
                                % row.get("take_id")))
    if not str(row.get("media_ref") or "").strip():
        refusals.append(_refuse("master_no_media",
                                "take %s does not say where its audio is"
                                % row.get("take_id")))
    if row.get("mode") not in MASTER_MODES:
        refusals.append(_refuse(
            "master_unknown_mode",
            "take %s does not say whether it is a continuous or a segmented "
            "performance" % row.get("take_id")))
    if session is not None:
        sess = _mapping(session, "session")
        if row.get("session_id") != sess.get("session_id"):
            refusals.append(_refuse(
                "master_wrong_session",
                "take %s belongs to session %s, not %s"
                % (row.get("take_id"), row.get("session_id"),
                   sess.get("session_id"))))
        if row.get("actor") != sess.get("actor"):
            refusals.append(_refuse(
                "master_actor_mismatch",
                "take %s is credited to %r but session %s records %r"
                % (row.get("take_id"), row.get("actor"), sess.get("session_id"),
                   sess.get("actor"))))
        if row.get("revision") != sess.get("revision"):
            refusals.append(_refuse(
                "master_revision_mismatch",
                "take %s was recorded against revision %s but its session is %s"
                % (row.get("take_id"), row.get("revision"), sess.get("revision"))))
    if script is not None:
        base = _mapping(script, "script")
        if row.get("revision") != base.get("revision"):
            refusals.append(_refuse(
                "master_revision_mismatch",
                "take %s was recorded against revision %s, not %s"
                % (row.get("take_id"), row.get("revision"), base.get("revision"))))
        if row.get("actor") not in (base.get("cast") or {}):
            refusals.append(_refuse(
                "master_unknown_actor",
                "take %s is credited to %r, who is not in the cast"
                % (row.get("take_id"), row.get("actor"))))
    seconds = 0.0
    if isinstance(rate, int) and not isinstance(rate, bool) and rate > 0 \
            and isinstance(frames, int) and not isinstance(frames, bool):
        seconds = frames / float(rate)
    return _result(refusals, seconds=seconds)


def verify_master_bytes(master: Mapping, data: bytes) -> dict:
    """Re-hash the audio. A changed or corrupt master is refused by name."""
    row = _mapping(master, "master")
    try:
        digest = audio_digest(data)
    except ManifestError as err:
        return _result([_refuse("master_unreadable", str(err),
                                take_id=row.get("take_id"))], digest="")
    if digest != row.get("audio_sha256"):
        return _result([_refuse(
            "master_hash_mismatch",
            "take %s no longer hashes to its recorded audio: the manifest says %s, "
            "the bytes say %s. Every cut of this take is now unverified."
            % (row.get("take_id"), row.get("audio_sha256"), digest),
            take_id=row.get("take_id"))], digest=digest)
    return _result([], digest=digest)


def line_cut(cut_id: str, *, occurrence_id: str, ordinal: int, take_id: str,
             master_sha256: str, sample_rate: int, start_sample: int,
             end_sample: int, boundary_method: str,
             verification: Mapping | None = None, state: str = "pending",
             created_at: float | None = None) -> dict:
    """One scripted line's exact span inside one master, in integer samples.

    `verification` may carry {"transcript": str, "actor": str,
    "ambiguous": bool, "notes": str}.
    """
    if state not in CUT_STATES:
        raise ManifestError("unknown cut state %r; expected one of %s"
                            % (state, ", ".join(CUT_STATES)))
    if not is_audio_digest(master_sha256):
        raise ManifestError("master_sha256 must look like sha256:<64 hex>, not %r"
                            % (master_sha256,))
    start = _whole(start_sample, "start_sample", low=0)
    end = _whole(end_sample, "end_sample", low=0)
    if end <= start:
        raise ManifestError("a cut must end after it starts (%d..%d)" % (start, end))
    return {"kind": "line_cut", "schema": SCHEMA,
            "cut_id": _text(cut_id, "cut_id"),
            "occurrence_id": _text(occurrence_id, "occurrence_id"),
            "ordinal": _whole(ordinal, "ordinal", low=1),
            "take_id": _text(take_id, "take_id"),
            "master_sha256": master_sha256,
            "sample_rate": _whole(sample_rate, "sample_rate", low=1),
            "start_sample": start, "end_sample": end,
            "boundary_method": _text(boundary_method, "boundary_method",
                                     required=False),
            "verification": _mapping(verification, "verification"),
            "state": state, "created_at": _now(created_at)}


def validate_cut(cut: Mapping, *, master: Mapping, script: Mapping,
                 min_coverage: float = DEFAULT_MIN_COVERAGE) -> dict:
    """Source bounds, text coverage, actor identity and boundary certainty."""
    refusals: list[dict] = []
    row = _mapping(cut, "cut")
    if row.get("kind") != "line_cut":
        return _result([_refuse("cut_malformed", "this record is not a line cut")],
                       coverage=None, missing=[], repeated=[], frames=0, seconds=0.0)
    take = _mapping(master, "master")
    base = _mapping(script, "script")
    ident = row.get("occurrence_id")
    where = {"cut_id": row.get("cut_id"), "occurrence_id": ident}
    line = script_line_by_occurrence(base, ident)
    if line is None:
        refusals.append(_refuse(
            "cut_unknown_occurrence",
            "cut %s claims occurrence %s, which is not a line of revision %s"
            % (row.get("cut_id"), ident, base.get("revision")), **where))
    elif row.get("ordinal") != line.get("ordinal"):
        refusals.append(_refuse(
            "cut_ordinal_mismatch",
            "cut %s says line %r but occurrence %s is line %r of the frozen script"
            % (row.get("cut_id"), row.get("ordinal"), ident, line.get("ordinal")),
            **where))
    if row.get("state") not in CUT_STATES:
        refusals.append(_refuse("cut_unknown_state",
                                "cut %s has unknown state %r"
                                % (row.get("cut_id"), row.get("state")), **where))
    if row.get("take_id") != take.get("take_id"):
        refusals.append(_refuse(
            "cut_wrong_master",
            "cut %s was cut from take %s, not take %s"
            % (row.get("cut_id"), row.get("take_id"), take.get("take_id")), **where))
    if row.get("master_sha256") != take.get("audio_sha256"):
        refusals.append(_refuse(
            "cut_master_mismatch",
            "cut %s was made against audio %s but take %s now holds %s; the master "
            "changed under the cut"
            % (row.get("cut_id"), row.get("master_sha256"), take.get("take_id"),
               take.get("audio_sha256")), **where))
    rate = row.get("sample_rate")
    if rate != take.get("sample_rate"):
        refusals.append(_refuse(
            "cut_sample_rate_mismatch",
            "cut %s counts samples at %r Hz but take %s is %r Hz; its positions point "
            "somewhere else" % (row.get("cut_id"), rate, take.get("take_id"),
                                take.get("sample_rate")), **where))
    start, end = row.get("start_sample"), row.get("end_sample")
    ints = all(isinstance(v, int) and not isinstance(v, bool) for v in (start, end))
    if not ints:
        refusals.append(_refuse(
            "cut_not_integer_samples",
            "cut %s does not use integer sample positions (%r..%r)"
            % (row.get("cut_id"), start, end), **where))
    else:
        if start < 0 or end <= start:
            refusals.append(_refuse(
                "cut_empty_span",
                "cut %s spans %d..%d, which is not audio"
                % (row.get("cut_id"), start, end), **where))
        frames = take.get("frame_count")
        if isinstance(frames, int) and not isinstance(frames, bool) and end > frames:
            refusals.append(_refuse(
                "cut_out_of_bounds",
                "cut %s ends at sample %d but take %s is only %d samples long"
                % (row.get("cut_id"), end, take.get("take_id"), frames), **where))
    method = str(row.get("boundary_method") or "")
    checks = _mapping(row.get("verification"), "verification")
    if method in AMBIGUOUS_BOUNDARY_METHODS or method not in BOUNDARY_METHODS:
        refusals.append(_refuse(
            "cut_boundary_ambiguous",
            "cut %s was bounded by %r; silence, thresholds and estimates cannot "
            "establish which line was spoken. Use a renderer boundary, an alignment "
            "against the script, or a human edit."
            % (row.get("cut_id"), method or "nothing"), **where))
    if checks.get("ambiguous"):
        refusals.append(_refuse(
            "cut_boundary_ambiguous",
            "cut %s was reported as an ambiguous boundary: %s"
            % (row.get("cut_id"), checks.get("notes") or "no reason given"), **where))
    heard_actor = checks.get("actor")
    if line is not None and heard_actor and heard_actor != line.get("actor"):
        refusals.append(_refuse(
            "cut_actor_mismatch",
            "cut %s was verified as %r speaking, but occurrence %s is %r's line"
            % (row.get("cut_id"), heard_actor, ident, line.get("actor")), **where))
    if line is not None and take.get("actor") and take.get("actor") != line.get("actor"):
        refusals.append(_refuse(
            "cut_actor_mismatch",
            "cut %s comes from %r's take but occurrence %s is %r's line"
            % (row.get("cut_id"), take.get("actor"), ident, line.get("actor")),
            **where))
    coverage = None
    missing: list[str] = []
    repeated: list[str] = []
    transcript = checks.get("transcript")
    if line is not None and isinstance(transcript, str) and transcript.strip():
        got = text_coverage(line.get("text"), transcript)
        coverage = got["coverage"]
        missing = got["missing"]
        repeated = got["repeated"]
        if missing:
            refusals.append(_refuse(
                "cut_words_missing",
                "cut %s does not contain %d scripted word(s): %s"
                % (row.get("cut_id"), len(missing), ", ".join(missing[:8])), **where))
        if repeated:
            refusals.append(_refuse(
                "cut_words_repeated",
                "cut %s contains repeated speech (%s); a retake overlapping the line "
                "is not the line"
                % (row.get("cut_id"), ", ".join(repeated[:8])), **where))
        if got["extra"]:
            refusals.append(_refuse(
                "cut_words_extra",
                "cut %s contains %d word(s) that are not in the script: %s"
                % (row.get("cut_id"), len(got["extra"]), ", ".join(got["extra"][:8])),
                **where))
        if coverage < float(min_coverage):
            refusals.append(_refuse(
                "cut_text_coverage",
                "cut %s covers %.1f%% of its scripted words; %.1f%% is required"
                % (row.get("cut_id"), 100.0 * coverage, 100.0 * float(min_coverage)),
                **where))
    elif method != "renderer_boundary":
        refusals.append(_refuse(
            "cut_no_text_evidence",
            "cut %s was bounded by %r and carries no transcript; nothing shows the "
            "audio contains the scripted words" % (row.get("cut_id"), method), **where))
    frames = (end - start) if ints else 0
    seconds = (frames / float(rate)) if isinstance(rate, int) \
        and not isinstance(rate, bool) and rate > 0 else 0.0
    return _result(refusals, coverage=coverage, missing=missing, repeated=repeated,
                   frames=max(0, frames), seconds=seconds)


def validate_cut_set(cuts: Sequence[Mapping], *, script: Mapping,
                     masters: Mapping | None = None,
                     occurrences: Sequence[str] | None = None,
                     min_coverage: float = DEFAULT_MIN_COVERAGE) -> dict:
    """Exactly one accepted cut for each required occurrence, and no overlaps.

    `masters` is {take_id: master}; when given, every accepted cut is fully
    validated against its master. `occurrences` defaults to the whole script.
    """
    refusals: list[dict] = []
    rows = [_mapping(c, "cut") for c in (cuts or [])]
    base = _mapping(script, "script")
    takes = _mapping(masters, "masters") if masters is not None else None
    needed = list(occurrences) if occurrences is not None else script_sequence(base)
    seen_ids: set[str] = set()
    accepted: dict[str, str] = {}
    duplicates: dict[str, list[str]] = {}
    for row in rows:
        cut_id = str(row.get("cut_id") or "")
        if cut_id in seen_ids:
            refusals.append(_refuse("cut_duplicate_id",
                                    "cut id %s is used by two different records"
                                    % cut_id, cut_id=cut_id))
        seen_ids.add(cut_id)
        if row.get("state") != "accepted":
            continue
        ident = str(row.get("occurrence_id") or "")
        if ident in accepted:
            duplicates.setdefault(ident, [accepted[ident]]).append(cut_id)
            refusals.append(_refuse(
                "cut_duplicate_accepted",
                "occurrence %s has two accepted cuts (%s and %s); exactly one take may "
                "be accepted for a line" % (ident, accepted[ident], cut_id),
                occurrence_id=ident, cut_id=cut_id))
            continue
        accepted[ident] = cut_id
        if takes is None:
            continue
        take = takes.get(row.get("take_id"))
        if take is None:
            refusals.append(_refuse(
                "cut_master_missing",
                "cut %s names take %s, which has no master record"
                % (cut_id, row.get("take_id")), cut_id=cut_id, occurrence_id=ident))
        else:
            refusals.extend(validate_cut(row, master=take, script=base,
                                         min_coverage=min_coverage)["refusals"])
    missing = [ident for ident in needed if ident not in accepted]
    for ident in missing:
        line = script_line_by_occurrence(base, ident)
        refusals.append(_refuse(
            "cut_missing_for_occurrence",
            "line %s (occurrence %s) has no accepted cut; a failed cut needs a retake "
            "or another complete ready candidate"
            % (line.get("ordinal") if line else "?", ident), occurrence_id=ident))
    # Overlapping accepted cuts inside one master are an ambiguous boundary.
    by_take: dict[str, list[Mapping]] = {}
    for row in rows:
        if row.get("state") == "accepted":
            by_take.setdefault(str(row.get("take_id") or ""), []).append(row)
    for take_id, group in by_take.items():
        ordered = sorted(group, key=lambda r: (r.get("start_sample") or 0,
                                               r.get("end_sample") or 0))
        for first, second in zip(ordered, ordered[1:]):
            if (second.get("start_sample") or 0) < (first.get("end_sample") or 0):
                refusals.append(_refuse(
                    "cut_overlap_ambiguous",
                    "cuts %s (%s..%s) and %s (%s..%s) overlap inside take %s; one "
                    "sample cannot belong to two lines"
                    % (first.get("cut_id"), first.get("start_sample"),
                       first.get("end_sample"), second.get("cut_id"),
                       second.get("start_sample"), second.get("end_sample"), take_id),
                    cut_id=second.get("cut_id")))
    return _result(refusals, accepted=accepted, missing=missing,
                   duplicates=duplicates)


# --------------------------------------------------------------------------
# 4. the finished conversation
# --------------------------------------------------------------------------

def cue_entry(*, occurrence_id: str, ordinal: int, cut_id: str,
              cue_start_sample: int, speech_start_sample: int,
              speech_end_sample: int, cue_end_sample: int,
              source_frames: int = 0) -> dict:
    """One line's place in the FINAL mix, in final samples.

    Speech and cue ends are separate so an inserted pause does not falsely
    start the next line. `source_frames` is the cut's own length, so a
    duration-changing effect is visible rather than assumed.
    """
    return {"occurrence_id": _text(occurrence_id, "occurrence_id"),
            "ordinal": _whole(ordinal, "ordinal", low=1),
            "cut_id": _text(cut_id, "cut_id"),
            "cue_start_sample": _whole(cue_start_sample, "cue_start_sample"),
            "speech_start_sample": _whole(speech_start_sample, "speech_start_sample"),
            "speech_end_sample": _whole(speech_end_sample, "speech_end_sample"),
            "cue_end_sample": _whole(cue_end_sample, "cue_end_sample"),
            "source_frames": _whole(source_frames, "source_frames")}


def finished_conversation(assembly_id: str, *, revision: str,
                          cuts: Sequence[str], mix: Mapping,
                          final_sha256: str, final_sample_rate: int,
                          final_frame_count: int, cue_map: Sequence[Mapping],
                          cue_source: str = "measured",
                          cue_map_revision: str | None = None,
                          created_at: float | None = None) -> dict:
    """The assembled conversation and its exact cue map.

    `cuts` is the ordered list of cut ids in frozen reading order. `cue_map`
    is the ordered list of `cue_entry` records measured from the actual edited
    sample counts. A cue_map_revision is derived from that content when one is
    not supplied.
    """
    if not is_audio_digest(final_sha256):
        raise ManifestError("final_sha256 must look like sha256:<64 hex>, not %r"
                            % (final_sha256,))
    rows = [dict(_mapping(c, "cue_map[]")) for c in _listed(cue_map, "cue_map")]
    if not rows:
        raise ManifestError("a finished conversation needs a cue map")
    record = {"kind": "finished_conversation", "schema": SCHEMA,
              "assembly_id": _text(assembly_id, "assembly_id"),
              "revision": _text(revision, "revision"),
              "cuts": [str(c) for c in _listed(cuts, "cuts")],
              "mix": _mapping(mix, "mix"),
              "final_sha256": final_sha256,
              "final_sample_rate": _whole(final_sample_rate, "final_sample_rate",
                                          low=1),
              "final_frame_count": _whole(final_frame_count, "final_frame_count",
                                          low=1),
              "cue_map": rows,
              "cue_source": _text(cue_source, "cue_source"),
              "created_at": _now(created_at)}
    record["cue_map_revision"] = cue_map_revision or _digest_of(
        "cue-", {"assembly": record["assembly_id"], "final": final_sha256,
                 "cue_map": rows, "source": record["cue_source"]}, 16)
    return record


def cue_sequence(assembly: Mapping) -> list[str]:
    """The order the finished audio actually speaks its lines in."""
    return [str(r.get("occurrence_id") or "")
            for r in (_mapping(assembly, "assembly").get("cue_map") or [])]


def cue_lookup(assembly: Mapping, position_samples: int) -> dict:
    """Which occurrence is sounding at a final-mix sample position."""
    base = _mapping(assembly, "assembly")
    frames = base.get("final_frame_count")
    if not isinstance(position_samples, int) or isinstance(position_samples, bool):
        return _result([_refuse("cue_position_invalid",
                                "a playhead position must be a whole number of "
                                "samples, not %r" % (position_samples,))],
                       occurrence_id=None, ordinal=None, speaking=False)
    if position_samples < 0 or (isinstance(frames, int) and position_samples > frames):
        return _result([_refuse(
            "cue_position_out_of_range",
            "position %d is outside assembly %s, which is %r samples long"
            % (position_samples, base.get("assembly_id"), frames))],
            occurrence_id=None, ordinal=None, speaking=False)
    for row in (base.get("cue_map") or []):
        start = int(row.get("cue_start_sample") or 0)
        stop = int(row.get("cue_end_sample") or 0)
        if start <= position_samples < stop:
            speaking = (int(row.get("speech_start_sample") or 0) <= position_samples
                        < int(row.get("speech_end_sample") or 0))
            return _result([], occurrence_id=row.get("occurrence_id"),
                           ordinal=row.get("ordinal"), speaking=speaking)
    return _result([_refuse("cue_position_unmapped",
                            "position %d in assembly %s falls between cues; no line "
                            "is scheduled there"
                            % (position_samples, base.get("assembly_id")))],
                   occurrence_id=None, ordinal=None, speaking=False)


def validate_assembly(assembly: Mapping, *, script: Mapping,
                      cuts_by_id: Mapping, masters: Mapping | None = None,
                      min_coverage: float = DEFAULT_MIN_COVERAGE) -> dict:
    """The complete artifact: frozen order, one accepted cut each, real cues."""
    refusals: list[dict] = []
    base = _mapping(assembly, "assembly")
    frozen = _mapping(script, "script")
    known = _mapping(cuts_by_id, "cuts_by_id")
    if base.get("kind") != "finished_conversation":
        return _result([_refuse("assembly_malformed",
                                "this record is not a finished conversation")],
                       sequence=[], frames=0, seconds=0.0)
    if base.get("revision") != frozen.get("revision"):
        refusals.append(_refuse(
            "assembly_revision_mismatch",
            "assembly %s was built from revision %s but was checked against %s"
            % (base.get("assembly_id"), base.get("revision"),
               frozen.get("revision"))))
    source = str(base.get("cue_source") or "").lower()
    if source in REFUSED_CUE_SOURCES:
        refusals.append(_refuse(
            "cue_map_estimated",
            "assembly %s carries %r cue positions; estimated windows rescaled to fit "
            "the finished duration are not where the lines are. Cue positions must be "
            "measured from the actual edited sample counts."
            % (base.get("assembly_id"), base.get("cue_source"))))
    elif base.get("cue_source") not in CUE_SOURCES:
        refusals.append(_refuse(
            "cue_map_estimated",
            "assembly %s does not say how its cue positions were obtained (%r)"
            % (base.get("assembly_id"), base.get("cue_source"))))
    mix = _mapping(base.get("mix"), "mix")
    rate = base.get("final_sample_rate")
    if mix.get("sample_rate") is not None and mix.get("sample_rate") != rate:
        refusals.append(_refuse(
            "mix_sample_rate_mismatch",
            "assembly %s mixes at %r Hz but its final audio is %r Hz"
            % (base.get("assembly_id"), mix.get("sample_rate"), rate)))
    if not is_audio_digest(base.get("final_sha256")):
        refusals.append(_refuse("assembly_no_hash",
                                "assembly %s has no final audio hash"
                                % base.get("assembly_id")))
    wanted = script_sequence(frozen)
    cue_rows = list(base.get("cue_map") or [])
    got_sequence = cue_sequence(base)
    if got_sequence != wanted:
        refusals.append(_refuse(
            "assembly_sequence_mismatch",
            "assembly %s speaks %d line(s) in an order that is not the frozen script: "
            "expected %s, got %s"
            % (base.get("assembly_id"), len(got_sequence),
               " ".join(wanted[:4]) + ("..." if len(wanted) > 4 else ""),
               " ".join(got_sequence[:4]) + ("..." if len(got_sequence) > 4 else ""))))
    referenced = [str(c) for c in (base.get("cuts") or [])]
    if referenced != [str(r.get("cut_id") or "") for r in cue_rows]:
        refusals.append(_refuse(
            "assembly_cut_list_mismatch",
            "assembly %s's ordered cut list is not the cut list of its own cue map"
            % base.get("assembly_id")))
    picked: list[Mapping] = []
    for cut_id in referenced:
        cut = known.get(cut_id)
        if cut is None:
            refusals.append(_refuse(
                "assembly_cut_missing",
                "assembly %s references cut %s, which has no record"
                % (base.get("assembly_id"), cut_id), cut_id=cut_id))
        else:
            picked.append(cut)
    if picked:
        refusals.extend(validate_cut_set(picked, script=frozen, masters=masters,
                                         occurrences=wanted,
                                         min_coverage=min_coverage)["refusals"])
    elif wanted:
        refusals.append(_refuse(
            "assembly_incomplete",
            "assembly %s has no usable cuts for the %d line(s) of revision %s"
            % (base.get("assembly_id"), len(wanted), frozen.get("revision"))))
    frames = base.get("final_frame_count")
    previous_end = -1
    effects_change_duration = bool(mix.get("changes_duration")) or any(
        bool(dict(e).get("changes_duration"))
        for e in (mix.get("effects") or []) if isinstance(e, Mapping))
    unchanged_spans = 0
    for index, row in enumerate(cue_rows):
        where = {"occurrence_id": row.get("occurrence_id"),
                 "cut_id": row.get("cut_id")}
        values = [row.get(k) for k in ("cue_start_sample", "speech_start_sample",
                                       "speech_end_sample", "cue_end_sample")]
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in values):
            refusals.append(_refuse(
                "cue_not_integer_samples",
                "cue %d of assembly %s does not use integer sample positions (%r)"
                % (index + 1, base.get("assembly_id"), values), **where))
            continue
        cue_start, speech_start, speech_end, cue_end = values
        if not (cue_start <= speech_start < speech_end <= cue_end):
            refusals.append(_refuse(
                "cue_span_invalid",
                "cue %d of assembly %s spans cue %d..%d with speech %d..%d, which is "
                "not a line followed by its pause"
                % (index + 1, base.get("assembly_id"), cue_start, cue_end,
                   speech_start, speech_end), **where))
        if isinstance(frames, int) and cue_end > frames:
            refusals.append(_refuse(
                "cue_out_of_range",
                "cue %d of assembly %s ends at sample %d but the finished audio is %d "
                "samples long"
                % (index + 1, base.get("assembly_id"), cue_end, frames), **where))
        if cue_start < previous_end:
            refusals.append(_refuse(
                "cue_overlap",
                "cue %d of assembly %s starts at %d, before cue %d ended at %d; strict "
                "sequential assembly has a single active spoken line"
                % (index + 1, base.get("assembly_id"), cue_start, index, previous_end),
                **where))
        previous_end = max(previous_end, cue_end)
        source_frames = row.get("source_frames")
        if isinstance(source_frames, int) and source_frames > 0 \
                and (speech_end - speech_start) == source_frames:
            unchanged_spans += 1
    if effects_change_duration and cue_rows and unchanged_spans == len(cue_rows):
        refusals.append(_refuse(
            "cue_map_stale_for_effects",
            "assembly %s applies duration-changing processing but every cue still "
            "spans its unedited source length; a source master offset is not a final "
            "mix offset" % base.get("assembly_id")))
    seconds = 0.0
    if isinstance(frames, int) and isinstance(rate, int) and rate > 0:
        seconds = frames / float(rate)
    return _result(refusals, sequence=got_sequence,
                   frames=frames if isinstance(frames, int) else 0, seconds=seconds)


# --------------------------------------------------------------------------
# 5. broadcast admission
# --------------------------------------------------------------------------

def broadcast_admission(admission_id: str, *, assembly: Mapping,
                        playback_occurrence_id: str | None = None,
                        start_position: int = 1,
                        sequence_positions: Sequence[Mapping] | None = None,
                        admitted_at: float | None = None) -> dict:
    """Commit one finished conversation to the reading order.

    A fresh playback occurrence is minted each time, so the same assembly
    aired twice is two occurrences in the script. Sequence positions default
    to `start_position`, incrementing by one along the cue map.
    """
    base = _mapping(assembly, "assembly")
    occurrence = _text(playback_occurrence_id or ("play-" + uuid.uuid4().hex[:16]),
                       "playback_occurrence_id")
    if sequence_positions is None:
        positions = []
        place = _whole(start_position, "start_position", low=0)
        for row in (base.get("cue_map") or []):
            positions.append({"occurrence_id": row.get("occurrence_id"),
                              "ordinal": row.get("ordinal"),
                              "position": place,
                              "playback_line_id": "%s:%s" % (occurrence,
                                                             row.get("ordinal"))})
            place += 1
    else:
        positions = [dict(_mapping(p, "sequence_positions[]"))
                     for p in sequence_positions]
    if not positions:
        raise ManifestError("an admission needs at least one sequence position")
    return {"kind": "broadcast_admission", "schema": SCHEMA,
            "admission_id": _text(admission_id, "admission_id"),
            "playback_occurrence_id": occurrence,
            "assembly_id": _text(base.get("assembly_id"), "assembly.assembly_id"),
            "revision": _text(base.get("revision"), "assembly.revision"),
            "final_sha256": _text(base.get("final_sha256"),
                                  "assembly.final_sha256"),
            "cue_map_revision": _text(base.get("cue_map_revision"),
                                      "assembly.cue_map_revision"),
            "sequence_positions": positions,
            "admitted_at": _now(admitted_at),
            "state": "admitted"}


def validate_admission(admission: Mapping, *, assembly: Mapping, script: Mapping,
                       cuts_by_id: Mapping | None = None,
                       masters: Mapping | None = None,
                       used_playback_occurrences: Iterable[str] = ()) -> dict:
    """The admission gate. No incomplete conversation may pass it."""
    refusals: list[dict] = []
    row = _mapping(admission, "admission")
    base = _mapping(assembly, "assembly")
    if row.get("kind") != "broadcast_admission":
        return _result([_refuse("admission_malformed",
                                "this record is not a broadcast admission")],
                       positions={})
    if row.get("assembly_id") != base.get("assembly_id"):
        refusals.append(_refuse(
            "admission_wrong_assembly",
            "admission %s commits assembly %s but was checked against %s"
            % (row.get("admission_id"), row.get("assembly_id"),
               base.get("assembly_id"))))
    if row.get("final_sha256") != base.get("final_sha256"):
        refusals.append(_refuse(
            "admission_audio_mismatch",
            "admission %s pins audio %s but assembly %s now holds %s; the finished "
            "file changed after it was committed"
            % (row.get("admission_id"), row.get("final_sha256"),
               base.get("assembly_id"), base.get("final_sha256"))))
    if row.get("cue_map_revision") != base.get("cue_map_revision"):
        refusals.append(_refuse(
            "admission_cue_revision_mismatch",
            "admission %s pins cue map %s but assembly %s now holds %s"
            % (row.get("admission_id"), row.get("cue_map_revision"),
               base.get("assembly_id"), base.get("cue_map_revision"))))
    if not str(row.get("playback_occurrence_id") or "").strip():
        refusals.append(_refuse(
            "admission_no_occurrence",
            "admission %s has no playback occurrence id; a reused sample's content id "
            "is not a playback occurrence" % row.get("admission_id")))
    if row.get("playback_occurrence_id") in set(used_playback_occurrences or ()):
        refusals.append(_refuse(
            "admission_occurrence_reused",
            "playback occurrence %s has already been admitted; playing the same audio "
            "twice makes two occurrences" % row.get("playback_occurrence_id")))
    if cuts_by_id is None:
        refusals.append(_refuse(
            "admission_unverifiable",
            "admission %s cannot be checked without the accepted cut records of "
            "assembly %s" % (row.get("admission_id"), base.get("assembly_id"))))
    else:
        got = validate_assembly(base, script=script, cuts_by_id=cuts_by_id,
                                masters=masters)
        if not got["ok"]:
            refusals.append(_refuse(
                "admission_incomplete_assembly",
                "assembly %s is not a complete verified conversation, so it may not "
                "be admitted: %s" % (base.get("assembly_id"), got["reasons"][0]),
                detail=got["reasons"]))
            refusals.extend(got["refusals"])
    cue_rows = list(base.get("cue_map") or [])
    positions = list(row.get("sequence_positions") or [])
    if len(positions) != len(cue_rows):
        refusals.append(_refuse(
            "admission_sequence_incomplete",
            "admission %s commits %d position(s) for a conversation of %d line(s); an "
            "incomplete conversation may not be admitted"
            % (row.get("admission_id"), len(positions), len(cue_rows))))
    mapped: dict[str, int] = {}
    last: int | None = None
    for index, place in enumerate(positions):
        place = _mapping(place, "sequence_positions[]")
        cue = cue_rows[index] if index < len(cue_rows) else {}
        if cue and place.get("occurrence_id") != cue.get("occurrence_id"):
            refusals.append(_refuse(
                "admission_sequence_order",
                "admission %s puts %s at sequence place %r, where the cue map has %s"
                % (row.get("admission_id"), place.get("occurrence_id"),
                   place.get("position"), cue.get("occurrence_id")),
                occurrence_id=place.get("occurrence_id")))
        number = place.get("position")
        if not isinstance(number, int) or isinstance(number, bool):
            refusals.append(_refuse(
                "admission_sequence_invalid",
                "admission %s gives %s a sequence position of %r"
                % (row.get("admission_id"), place.get("occurrence_id"), number),
                occurrence_id=place.get("occurrence_id")))
            continue
        if last is not None and number != last + 1:
            refusals.append(_refuse(
                "admission_sequence_gap",
                "admission %s jumps from sequence position %d to %d; committed "
                "positions are contiguous" % (row.get("admission_id"), last, number),
                occurrence_id=place.get("occurrence_id")))
        last = number
        mapped[str(place.get("occurrence_id") or "")] = number
    return _result(refusals, positions=mapped)


def validate_playback_receipt(admission: Mapping, receipt: Mapping, *,
                              assembly: Mapping | None = None,
                              now_ms: float | None = None,
                              max_age_ms: float | None = None) -> dict:
    """Is this player receipt about the occurrence we actually admitted?

    A receipt from a previous airing, a different file, an older cue map or a
    position outside the audio is refused by name. The extras name the line
    the receipt actually points at.
    """
    refusals: list[dict] = []
    row = _mapping(admission, "admission")
    got = _mapping(receipt, "receipt")
    occurrence = got.get("playback_occurrence_id")
    if occurrence != row.get("playback_occurrence_id"):
        refusals.append(_refuse(
            "receipt_wrong_occurrence",
            "this receipt is from playback occurrence %r; the admitted occurrence is "
            "%r. It is a late message from a previous player and must not advance the "
            "broadcast." % (occurrence, row.get("playback_occurrence_id"))))
    if got.get("assembly_id") is not None \
            and got.get("assembly_id") != row.get("assembly_id"):
        refusals.append(_refuse(
            "receipt_wrong_assembly",
            "this receipt is about assembly %r, not the admitted %r"
            % (got.get("assembly_id"), row.get("assembly_id"))))
    if got.get("final_sha256") is not None \
            and got.get("final_sha256") != row.get("final_sha256"):
        refusals.append(_refuse(
            "receipt_wrong_audio",
            "this receipt is about audio %r; the admitted audio is %r. The player is "
            "on a different file."
            % (got.get("final_sha256"), row.get("final_sha256"))))
    if got.get("cue_map_revision") is not None \
            and got.get("cue_map_revision") != row.get("cue_map_revision"):
        refusals.append(_refuse(
            "receipt_stale_cue_map",
            "this receipt maps positions through cue map %r; the admitted cue map is "
            "%r" % (got.get("cue_map_revision"), row.get("cue_map_revision"))))
    if max_age_ms is not None:
        at = got.get("at_ms")
        if not isinstance(at, (int, float)) or isinstance(at, bool):
            refusals.append(_refuse(
                "receipt_undated",
                "this receipt has no observation time, so its freshness cannot be "
                "established"))
        else:
            age = float(now_ms if now_ms is not None
                        else time.time() * 1000.0) - float(at)
            if age > float(max_age_ms):
                refusals.append(_refuse(
                    "receipt_expired",
                    "this receipt is %.1f s old; anything older than %.1f s is not "
                    "evidence of the current playhead"
                    % (age / 1000.0, float(max_age_ms) / 1000.0)))
    ident = None
    ordinal = None
    position = got.get("position_samples")
    if assembly is not None and isinstance(position, int) \
            and not isinstance(position, bool):
        found = cue_lookup(assembly, position)
        refusals.extend(found["refusals"])
        ident = found.get("occurrence_id")
        ordinal = found.get("ordinal")
    return _result(refusals, occurrence_id=ident, ordinal=ordinal,
                   position_samples=position if isinstance(position, int)
                   and not isinstance(position, bool) else None)


# --------------------------------------------------------------------------
# reuse across revisions, and pins
# --------------------------------------------------------------------------

def _changed_fields(old_line: Mapping, old_cast: Mapping,
                    new_line: Mapping, new_cast: Mapping) -> list[str]:
    changed: list[str] = []
    for field in ("text", "instructions", "context_before", "context_after"):
        if str(old_line.get(field) or "") != str(new_line.get(field) or ""):
            changed.append(field)
    if list(old_line.get("chunks") or []) != list(new_line.get("chunks") or []):
        changed.append("chunks")
    if _stable(old_line.get("pronunciations") or []) != \
            _stable(new_line.get("pronunciations") or []):
        changed.append("pronunciations")
    if str(old_line.get("actor") or "") != str(new_line.get("actor") or ""):
        changed.append("actor")
    for field in ("voice", "engine"):
        if str(dict(old_cast or {}).get(field) or "") != \
                str(dict(new_cast or {}).get(field) or ""):
            changed.append(field)
    if _stable(dict(old_cast or {}).get("config") or {}) != \
            _stable(dict(new_cast or {}).get("config") or {}):
        changed.append("engine config")
    return changed


def carry_over(old_script: Mapping, new_script: Mapping,
               cuts_by_occurrence: Mapping) -> dict:
    """Which completed audio survives a revision, and why the rest does not.

    Completed audio is reusable only when the full performance contract is
    unchanged. Repeated wording is matched in reading order within its own
    contract, never by text hash. `cuts_by_occurrence` maps an occurrence id
    of the OLD revision to the cut id of its accepted take. Returns extras
    {"carried": {new_occurrence_id: cut_id}, "dropped": [...]}. Dropped lines
    are refusals, so `ok` is False whenever anything must be re-recorded.
    """
    old = _mapping(old_script, "old_script")
    new = _mapping(new_script, "new_script")
    have = _mapping(cuts_by_occurrence, "cuts_by_occurrence")
    pools: dict[str, list[Mapping]] = {}
    for line in (old.get("lines") or []):
        pools.setdefault(str(line.get("performance_digest") or ""), []).append(line)
    carried: dict[str, str] = {}
    dropped: list[dict] = []
    refusals: list[dict] = []
    for line in (new.get("lines") or []):
        digest = str(line.get("performance_digest") or "")
        pool = pools.get(digest) or []
        source = None
        while pool:
            candidate = pool.pop(0)
            if have.get(candidate.get("occurrence_id")):
                source = candidate
                break
        if source is not None:
            carried[str(line.get("occurrence_id"))] = \
                str(have[source["occurrence_id"]])
            continue
        old_line = None
        for row in (old.get("lines") or []):
            if row.get("ordinal") == line.get("ordinal"):
                old_line = row
                break
        if old_line is None:
            reason = ("line %s (%r) is new in revision %s and has never been recorded"
                      % (line.get("ordinal"), line.get("actor"), new.get("revision")))
            changed = ["new line"]
        else:
            changed = _changed_fields(
                old_line, (old.get("cast") or {}).get(old_line.get("actor")) or {},
                line, (new.get("cast") or {}).get(line.get("actor")) or {})
            if changed:
                reason = ("line %s cannot reuse its audio: %s changed between "
                          "revision %s and %s"
                          % (line.get("ordinal"), ", ".join(changed),
                             old.get("revision"), new.get("revision")))
            else:
                reason = ("line %s has no completed audio in revision %s to carry "
                          "over" % (line.get("ordinal"), old.get("revision")))
                changed = ["never recorded"]
        dropped.append({"occurrence_id": line.get("occurrence_id"),
                        "ordinal": line.get("ordinal"), "reason": reason,
                        "changed": changed})
        refusals.append(_refuse("contract_changed", reason,
                                occurrence_id=line.get("occurrence_id")))
    return _result(refusals, carried=carried, dropped=dropped)


def pin_index(admissions: Sequence[Mapping], assemblies_by_id: Mapping,
              cuts_by_id: Mapping) -> dict:
    """What an admitted broadcast occurrence holds down.

    Returns {"takes", "cuts", "assemblies", "revisions"}, each mapping an id
    to the list of pins holding it. New work must never overwrite any of them.
    """
    out: dict[str, dict[str, list[dict]]] = {"takes": {}, "cuts": {},
                                             "assemblies": {}, "revisions": {}}
    known_assemblies = _mapping(assemblies_by_id, "assemblies_by_id")
    known_cuts = _mapping(cuts_by_id, "cuts_by_id")
    for admission in (admissions or []):
        row = _mapping(admission, "admission")
        if row.get("state") not in (None, "admitted", "playing", "played"):
            continue
        assembly = known_assemblies.get(row.get("assembly_id")) or {}
        pin_base = {"admission_id": row.get("admission_id"),
                    "playback_occurrence_id": row.get("playback_occurrence_id"),
                    "assembly_id": row.get("assembly_id")}
        out["assemblies"].setdefault(str(row.get("assembly_id") or ""),
                                     []).append(dict(pin_base))
        out["revisions"].setdefault(str(row.get("revision") or ""),
                                    []).append(dict(pin_base))
        for cue in (dict(assembly).get("cue_map") or []):
            cut = known_cuts.get(cue.get("cut_id")) or {}
            pin = dict(pin_base, occurrence_id=cue.get("occurrence_id"),
                       cut_id=cue.get("cut_id"), take_id=dict(cut).get("take_id"))
            out["cuts"].setdefault(str(cue.get("cut_id") or ""), []).append(pin)
            if dict(cut).get("take_id"):
                out["takes"].setdefault(str(dict(cut)["take_id"]), []).append(pin)
    return out


_PIN_BUCKET = {"master": "takes", "cut": "cuts", "assembly": "assemblies",
               "script": "revisions", "session": "", "admission": ""}


def check_overwrite(kind: str, identifier: str, existing: Mapping | None,
                    replacement: Mapping, pins: Mapping) -> dict:
    """May this record be written over what is already stored?

    Identical content is always allowed. Different content over a record an
    admitted broadcast occurrence is holding is refused. Extras: {"unchanged":
    bool} and, on refusal, {"pins": [pin...]}.
    """
    if existing is None:
        return _result([], unchanged=False)
    if _stable(existing) == _stable(replacement):
        return _result([], unchanged=True)
    bucket = _PIN_BUCKET.get(str(kind), "")
    held = list((_mapping(pins, "pins").get(bucket) or {}).get(str(identifier)) or []) \
        if bucket else []
    if not held:
        return _result([], unchanged=False)
    first = dict(held[0])
    return _result([_refuse(
        "pinned_take_overwrite",
        "%s %s is pinned by admitted broadcast occurrence %s (admission %s); new work "
        "must never overwrite it. Record a new %s instead."
        % (kind, identifier, first.get("playback_occurrence_id"),
           first.get("admission_id"), kind),
        kind=kind, identifier=identifier)], unchanged=False, pins=held)
