"""Contextual segment checks and schedule preparation contracts.

The station already has a running-order planner, reserve, recording rooms and
read-ahead bank. This module gives those rooms one JSON-safe description of
what a scheduled segment owes and one measurement of whether they supplied it.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any


_WORDS = re.compile(r"[^\W_]+(?:'[^\W_]+)*", re.UNICODE)
_GENERIC = frozenset('a an the our your this that live station service services product products server running on own one of for voice cloning clone'.split())
_SALE = re.compile(r'\b(?:sign\s+up|subscribe|place\s+(?:an|your)\s+order|order\s+now|pay\s+(?:through|at)|get\s+yours|book\s+now|purchase|enro[l]{1,2})\b', re.I)
_NEGATIVE = re.compile(r"\b(?:not|never|avoid|cannot|can't|don't|won't|shouldn't|mustn't|without)\b", re.I)


ROLE_ALIASES = {
    "a": "dj", "host": "dj", "dj": "dj",
    "b": "cohost", "co-host": "cohost", "cohost": "cohost",
    "c": "caller", "caller": "caller",
    "d": "third", "guest": "third", "third": "third",
    "e": "caller2", "caller2": "caller2", "second caller": "caller2",
    "manager": "manager", "upstairs": "manager",
}

# Seats, not display names. This vocabulary matches round_line_plan and the
# performer sessions already used by the recording room.
REQUIRED_ROLES = {
    "banter": ("dj", "cohost"),
    "caller": ("dj", "cohost", "caller"),
    "banter_caller": ("dj", "cohost", "caller"),
    "gallery": ("dj", "cohost"),
    # A scheduled manager memo is read and discussed by the booth pair;
    # the manager's own recorded page is a separate insertion road.
    "manager": ("dj", "cohost"),
    "upstairs": ("manager", "dj", "cohost"),
    "guest": ("dj", "cohost", "third"),
    # Either booth seat can introduce and send off a record when the other
    # chair is away. The pair of bookends is checked as turns below.
    "track_talk": (),
}

DIALOGUE_ROADS = frozenset({"banter", "caller", "banter_caller", "gallery",
                            "manager", "upstairs", "guest"})

# Track talk carries a record between two authored links. A record itself is
# scheduled material but does not require generated dialogue.
SPEECH_SHARE = {"record": 0.0, "music": 0.0, "track_talk": 0.0}

CONTRACT_SCHEMA = 1
WORDS_PER_MINUTE = 170.0
AVERAGE_TURN_SECONDS = 15.0
EVENT_SECONDS = 90.0
ROLE_TURN_SECONDS = 8.0
EVENT_BEAT_SECONDS = 12.0
WORD_ESTIMATE_TOLERANCE_SECONDS = 5.0


def _normal(text):
    return unicodedata.normalize('NFKC', str(text or '')).replace('’', "'").casefold()


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return number if math.isfinite(number) else float(fallback)


def normalize_role(value: Any) -> str:
    """Return the station seat represented by a marker or display label."""
    text = re.sub(r"\s+", " ", _normal(value).strip())
    return ROLE_ALIASES.get(text, text)


def _segment_seconds(slot: Mapping[str, Any], explicit: Any = None) -> float:
    if explicit is not None:
        return max(0.0, _number(explicit))
    for key in ("owns_seconds", "target_seconds", "planned_seconds", "seconds"):
        if slot.get(key) is not None:
            return max(0.0, _number(slot.get(key)))
    return max(0.0, _number(slot.get("minutes")) * 60.0)


def build_segment_contract(slot: Mapping[str, Any], *, target_seconds: Any = None,
                           now: Any = None) -> dict[str, Any]:
    """Turn an existing running-order row into an enforceable contract.

    A segment may satisfy this with several rounds. ``target_seconds`` is the
    portion assigned to one item within that segment, when needed.
    """
    if not isinstance(slot, Mapping):
        raise TypeError("slot must be a mapping")
    road = str(slot.get("road") or slot.get("kind") or "").strip()
    kind = str(slot.get("kind") or road).strip()
    target = _segment_seconds(slot, target_seconds)
    share = min(1.0, max(0.0, _number(SPEECH_SHARE.get(road, 1.0), 1.0)))
    speech_seconds = target * share
    words = int(math.ceil(speech_seconds * WORDS_PER_MINUTE / 60.0))
    speech_floor = speech_seconds * 0.9
    required_roles = list(REQUIRED_ROLES.get(road, ()))
    if road == "track_talk" and target > 0:
        min_turns, min_events = 2, 2
    elif road in ("record", "music") or target <= 0:
        min_turns, min_events = 0, 0
    elif road in DIALOGUE_ROADS:
        min_turns = max(len(required_roles), int(math.ceil(
            speech_seconds / AVERAGE_TURN_SECONDS)))
        min_events = max(1, int(math.ceil(target / EVENT_SECONDS)))
    else:
        min_turns, min_events = 1, 1
    starts_in = max(0.0, _number(slot.get("in_seconds", slot.get("starts_in"))))
    prep_lead = min(6 * 3600.0, max(
        300.0, target * 2.0 + len(required_roles) * 90.0 + min_events * 45.0))
    commit_id = str(slot.get("commit_id") or slot.get("id") or "")
    return {
        "schema": CONTRACT_SCHEMA,
        "segment_id": commit_id,
        "commit_id": commit_id,
        "kind": kind,
        "road": road,
        "label": str(slot.get("label") or road),
        "starts_in_seconds": round(starts_in, 3),
        "target_seconds": round(target, 3),
        "minimum_seconds": round(max(0.0, target - 1.0), 3),
        "speech_seconds": round(speech_seconds, 3),
        "minimum_speech_seconds": round(speech_floor, 3),
        "required_roles": required_roles,
        "required_role_groups": [["dj", "cohost"]] if road == "track_talk" else [],
        "required_bookends": ["intro", "outro"] if road == "track_talk" else [],
        "minimum_turns": min_turns,
        "minimum_events": min_events,
        "word_target": words,
        "word_range": [max(0, int(words * 0.9)), int(math.ceil(words * 1.1))],
        "prepare_lead_seconds": round(prep_lead, 3),
        "prepare_by_in_seconds": round(starts_in - prep_lead, 3),
        "elastic_seconds": round(min(30.0, target * 0.15), 3),
        "created_at": _number(now, 0.0),
    }


def _supply_rows(supplies: Iterable[Mapping[str, Any]] | None) -> list[Mapping[str, Any]]:
    return [row for row in (supplies or ()) if isinstance(row, Mapping)]


def estimated_speech_seconds(text: Any) -> float:
    '''Estimate authored speech from full text, never from clip allocation.'''
    return len(_WORDS.findall(str(text or ''))) * 60.0 / WORDS_PER_MINUTE


def evaluate_segment_contract(contract: Mapping[str, Any],
                              supplies: Iterable[Mapping[str, Any]] | None,
                              *, insertions: Iterable[Mapping[str, Any]] | None = None
                              ) -> dict[str, Any]:
    """Measure scripts, speech recordings, playable bodies and insertions.

    For track talk, ``bookends`` maps intro/outro to written/recorded flags.
    ``recorded_seconds`` counts voice takes; the record belongs in
    ``playable_seconds`` only.
    """
    if not isinstance(contract, Mapping):
        raise TypeError("contract must be a mapping")
    rows = _supply_rows(supplies)
    inserted = _supply_rows(insertions)
    target = max(0.0, _number(contract.get("target_seconds")))
    minimum = max(0.0, _number(contract.get("minimum_seconds"), target))

    def total(name: str, source: list[Mapping[str, Any]]) -> float:
        return sum(max(0.0, _number(row.get(name))) for row in source)

    def duration(row: Mapping[str, Any], seconds_key: str,
                 frames_key: str) -> float:
        if frames_key in row and "sample_rate" in row:
            rate = _number(row.get("sample_rate"))
            measured = max(0.0, _number(row.get(frames_key)) / rate) if rate > 0 else 0.0
            if seconds_key in row:
                return min(measured, max(0.0, _number(row.get(seconds_key))))
            return measured
        return max(0.0, _number(row.get(seconds_key)))

    scripted = total("scripted_seconds", rows + inserted)
    recorded = sum(duration(row, "recorded_seconds", "speech_frames")
                   for row in rows + inserted)
    playable = sum(duration(row, "playable_seconds", "body_frames")
                   for row in rows)
    inserted_seconds = sum(
        duration(row, "playable_seconds", "body_frames")
        if "playable_seconds" in row or "body_frames" in row
        else max(0.0, _number(row.get("seconds"))) for row in inserted)
    supplied = playable + inserted_seconds
    roles = {normalize_role(role) for row in rows + inserted
             for role in (row.get("roles") or ()) if normalize_role(role)}
    turns = sum(max(0, int(_number(row.get("turns")))) for row in rows + inserted)
    events = sum(max(0, int(_number(row.get("events", row.get("event_count")))))
                 for row in rows + inserted)
    required_roles = [normalize_role(role)
                      for role in (contract.get("required_roles") or ())]
    missing_roles = [role for role in required_roles if role and role not in roles]
    for group in (contract.get("required_role_groups") or ()):
        choices = [normalize_role(role) for role in group]
        if choices and not any(role in roles for role in choices):
            missing_roles.append(" or ".join(choices))
    missing_turns = max(0, int(_number(contract.get("minimum_turns"))) - turns)
    missing_events = max(0, int(_number(contract.get("minimum_events"))) - events)
    required_bookends = list(contract.get("required_bookends") or ())
    bookends: dict[str, dict[str, bool]] = {}
    for row in rows + inserted:
        sides = row.get("bookends")
        if not isinstance(sides, Mapping):
            continue
        for side, evidence in sides.items():
            if not isinstance(evidence, Mapping):
                continue
            state = bookends.setdefault(str(side), {"written": False, "recorded": False})
            state["written"] |= bool(evidence.get("written") or
                                     str(evidence.get("text") or "").strip())
            state["recorded"] |= bool(evidence.get("recorded"))
    missing_bookends = [side for side in required_bookends
                        if not bookends.get(side, {}).get("written")]
    missing_recorded_bookends = [side for side in required_bookends
                                 if not bookends.get(side, {}).get("recorded")]
    duration_short = max(0.0, minimum - supplied)
    speech_target = max(0.0, _number(contract.get("speech_seconds"), target))
    speech_floor = max(0.0, _number(contract.get("minimum_speech_seconds"), speech_target))
    script_floor = max(0.0, speech_floor - (
        WORD_ESTIMATE_TOLERANCE_SECONDS if recorded >= speech_floor - 1.0 else 0.0))
    script_short = max(0.0, script_floor - scripted,
                       len(missing_bookends) * ROLE_TURN_SECONDS)
    recording_short = max(0.0, speech_floor - recorded,
                          len(missing_recorded_bookends) * ROLE_TURN_SECONDS)
    writing_structure_short = max(len(missing_roles) * ROLE_TURN_SECONDS,
                                  min(missing_turns, 3) * ROLE_TURN_SECONDS,
                                  missing_events * EVENT_BEAT_SECONDS,
                                  len(missing_bookends) * ROLE_TURN_SECONDS)
    structural_short = max(len(missing_roles) * ROLE_TURN_SECONDS,
                           min(missing_turns, 3) * ROLE_TURN_SECONDS,
                           missing_events * EVENT_BEAT_SECONDS,
                           len(missing_bookends) * ROLE_TURN_SECONDS,
                           len(missing_recorded_bookends) * ROLE_TURN_SECONDS)
    short = max(duration_short, structural_short, script_short, recording_short)
    return {
        "target_seconds": round(target, 3),
        "minimum_seconds": round(minimum, 3),
        "scripted_seconds": round(scripted, 3),
        "recorded_seconds": round(recorded, 3),
        "playable_seconds": round(playable, 3),
        "inserted_seconds": round(inserted_seconds, 3),
        "covered_seconds": round(min(target, supplied), 3),
        "short_seconds": round(short, 3),
        "duration_short_seconds": round(duration_short, 3),
        "script_short_seconds": round(script_short, 3),
        "writing_structure_short_seconds": round(writing_structure_short, 3),
        "recording_short_seconds": round(recording_short, 3),
        "overrun_seconds": round(max(0.0, supplied - target), 3),
        "roles": sorted(roles),
        "missing_roles": missing_roles,
        "turns": turns,
        "missing_turns": missing_turns,
        "events": events,
        "missing_events": missing_events,
        "missing_bookends": missing_bookends,
        "missing_recorded_bookends": missing_recorded_bookends,
        "ready": bool(short <= 1.0 and not missing_roles
                      and missing_turns == 0 and missing_events == 0
                      and not missing_bookends and not missing_recorded_bookends),
        "basis": "measured playable seconds plus acknowledged insertions",
    }


def preparation_tasks(contract: Mapping[str, Any], coverage: Mapping[str, Any]
                      ) -> list[dict[str, Any]]:
    """Express one obligation at each existing production room."""
    target = max(0.0, _number(contract.get("target_seconds")))
    speech_target = max(0.0, _number(contract.get("speech_seconds"), target))
    speech_floor = max(0.0, _number(contract.get("minimum_speech_seconds"), speech_target))
    speech_optional = str(contract.get("road") or "") in ("record", "music")
    scripted = max(0.0, _number(coverage.get("scripted_seconds")))
    recorded = max(0.0, _number(coverage.get("recorded_seconds")))
    script_floor = max(0.0, speech_floor - (
        WORD_ESTIMATE_TOLERANCE_SECONDS if recorded >= speech_floor - 1.0 else 0.0))
    playable = max(0.0, _number(coverage.get("playable_seconds"))
                   + _number(coverage.get("inserted_seconds")))
    role_ok = not coverage.get("missing_roles")
    events_ok = (int(_number(coverage.get("missing_events"))) == 0
                 and not coverage.get("missing_bookends"))
    turns_ok = int(_number(coverage.get("missing_turns"))) == 0
    recorded_bookends_ok = not coverage.get("missing_recorded_bookends")
    writing_owed = max(0.0, script_floor - scripted,
                       len(coverage.get("missing_bookends") or ()) * ROLE_TURN_SECONDS,
                       _number(coverage.get("writing_structure_short_seconds")))
    recording_owed = max(0.0, speech_floor - recorded,
                         len(coverage.get("missing_recorded_bookends") or ())
                         * ROLE_TURN_SECONDS)
    tasks = [
        ("schedule", target > 0, max(0.0, target)),
        ("writing", speech_optional or (scripted >= max(0.0, script_floor - 1.0)
         and role_ok and events_ok and turns_ok),
         0.0 if speech_optional else writing_owed),
        ("recording", speech_optional or (recorded >= max(0.0, speech_floor - 1.0)
         and recorded_bookends_ok),
         0.0 if speech_optional else recording_owed),
        ("assembly", playable >= max(0.0, target - 1.0),
         max(0.0, target - playable)),
        ("pantry", bool(coverage.get("ready")),
         max(0.0, _number(coverage.get("short_seconds")))),
    ]
    return [{
        "room": room,
        "state": "ready" if ready else "owed",
        "ready": bool(ready),
        "want_seconds": round(want, 3),
        "segment_id": str(contract.get("segment_id") or ""),
        "prepare_by_in_seconds": round(_number(
            contract.get("prepare_by_in_seconds")), 3),
    } for room, ready, want in tasks]


def ad_sale_evidence(script: str, product: str = '') -> dict:
    """Recognize an expected product with an affirmative sale instruction.

    The known product's short leading identity must be present. Generic product
    descriptions, an unrelated product, a name alone, or a negated sale do not
    gain permission from this supplemental check. Existing ad-quality and
    source-fidelity checks remain the caller's responsibility.
    """
    if not isinstance(script, str) or not isinstance(product, str):
        raise TypeError('script and product must be strings')
    prefix = re.split(r'[,;:\n—–]|\s+-\s+', product.strip(), maxsplit=1)[0]
    terms = [word for word in _WORDS.findall(_normal(prefix)) if word not in _GENERIC]
    terms = list(dict.fromkeys(terms))
    # A long descriptive clause is not an identified product name. Do not
    # infer one by accepting an arbitrary content word from its description.
    if len(_WORDS.findall(prefix)) > 8:
        terms = []
    text = _normal(script)
    words = set(_WORDS.findall(text))
    matched = [term for term in terms if term in words]
    actions = []
    if terms and len(matched) == len(terms):
        for match in _SALE.finditer(text):
            clause_start = max(text.rfind(char, 0, match.start()) for char in '.!?;/\n') + 1
            before = ' '.join(_WORDS.findall(text[clause_start:match.start()])[-8:])
            if _NEGATIVE.search(before):
                continue
            actions.append(match.group())
    return {'ok': bool(actions), 'identity_terms': terms, 'matched_identity': matched,
            'sale_actions': list(dict.fromkeys(actions)),
            'basis': 'Expected product identity plus affirmative sale action',
            'limitations': 'This recognizes sale wording; it does not prove price accuracy, source fidelity or overall ad quality.'}
