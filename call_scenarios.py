"""Pure, six-beat caller scenario planning; no station or store imports.

The dramatic cues complement app.py's call_beat_sheet phone protocol. They
are not a second turn order and do not render or schedule a call. A conclusion
report is lexical, advisory evidence only. A separate receipt check verifies
what a listener actually heard.
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from caller_topic import topic_subject

BEATS = ("motive", "evidence", "probe", "friction", "reframe", "landing")
CATALOG_VERSION = 1
MAX_CATALOG_BYTES = 128 * 1024
MAX_SCENARIOS = 32
HEAT_TOLERANCE = 0.25

# Four paths per beat yield 4,096 dramatic paths before conclusion choice.
# Cues describe conversational moves, not facts to invent about the caller.
DEFAULT_PATH_MAP = {
    "motive": (
        ("explain", "seek an explanation for the subject", 3),
        ("be_heard", "ask the hosts to take the subject seriously", 2),
        ("next_step", "seek a practical next step", 2),
        ("challenge", "challenge an earlier reading of the subject", 1),
    ),
    "evidence": (
        ("specific", "name one concrete detail already in the source", 3),
        ("sequence", "put the known details in time order", 2),
        ("contrast", "contrast two details the caller actually gave", 2),
        ("witness", "explain who observed the known detail", 1),
    ),
    "probe": (
        ("repeat", "a host repeats the caller's exact detail in a question", 3),
        ("what_next", "a host asks what happened next", 2),
        ("meaning", "a host asks why that detail matters to the caller", 2),
        ("alternative", "a host tests another reading without asserting it", 1),
    ),
    "friction": (
        ("boundary", "test the caller's stated boundary respectfully", 3),
        ("cost", "ask what the caller stands to lose or gain", 2),
        ("doubt", "let the caller answer a specific doubt", 2),
        ("disagree", "let a host disagree about the known facts, then listen", 1),
    ),
    "reframe": (
        ("callback", "return to the opening detail with new understanding", 3),
        ("revise", "let the caller revise their first interpretation", 2),
        ("connect", "connect the caller's two stated concerns", 2),
        ("limit", "name what the conversation still cannot establish", 1),
    ),
    "landing": (
        ("choice", "the caller states their own next choice", 3),
        ("limit", "the caller states an honest limit to the answer", 2),
        ("request", "the caller makes a concrete request of the hosts", 2),
        ("leave_open", "the caller leaves an open question deliberately", 1),
    ),
}

# These frames add a conversational shape to an existing case or topic. They
# supply no new event, prize, culprit or promised action. The case book and
# storyline retain authority over what actually happens.
BUILTIN_SCENARIOS = (
    {
        "id": "quiet-detail", "weight": 1.3,
        "premise": "a small detail matters more to the caller than it first sounds",
        "want": "have the detail taken seriously",
        "stance": "careful and specific", "register": "plainspoken",
        "boundary": "do not claim more than the caller knows", "heat": 0.12,
        "conclusion_pool": [
            {"id": "heard", "text": "feel that the hosts heard the point",
             "proof_phrases": ["you heard me", "I feel heard"], "weight": 2},
            {"id": "enough", "text": "say that being listened to is enough for now",
             "proof_phrases": ["enough for now", "that's enough for me"]},
        ],
    },
    {
        "id": "gentle-misreading", "weight": 1.0,
        "premise": "the caller and hosts may have read one detail differently",
        "want": "test the reading without losing face",
        "stance": "curious, not defensive", "register": "warm and unhurried",
        "boundary": "do not invent a motive or a missing fact", "heat": 0.28,
        "conclusion_pool": [
            {"id": "reconsider", "text": "allow that the first reading may change",
             "proof_phrases": ["I may be wrong", "I read it differently"]},
            {"id": "clarity", "text": "name what is clearer after the conversation",
             "proof_phrases": ["that makes sense", "I see it now"]},
        ],
    },
    {
        "id": "playful-challenge", "weight": 0.9,
        "premise": "the caller enjoys pressing the hosts on their own words",
        "want": "make the hosts answer the actual point",
        "stance": "wry and alert", "register": "quick but good-natured",
        "boundary": "a joke must not erase the caller's real point", "heat": 0.43,
        "conclusion_pool": [
            {"id": "laugh", "text": "laugh with the hosts without surrendering the point",
             "proof_phrases": ["I can laugh", "we can laugh"]},
            {"id": "point", "text": "say the point still stands after the joke",
             "proof_phrases": ["point still stands", "I still mean it"]},
        ],
    },
    {
        "id": "reluctant-disclosure", "weight": 0.9,
        "premise": "the caller has been reluctant to say the subject aloud",
        "want": "finish saying it in their own words",
        "stance": "guarded, then steadier", "register": "intimate and direct",
        "boundary": "the hosts must not turn uncertainty into certainty", "heat": 0.52,
        "conclusion_pool": [
            {"id": "said", "text": "be glad to have finally said it",
             "proof_phrases": ["glad I said it", "I needed to say it"]},
            {"id": "uncertain", "text": "keep an honest uncertainty without retreating",
             "proof_phrases": ["I still don't know", "I am not sure yet"]},
        ],
    },
    {
        "id": "public-friction", "weight": 1.1,
        "premise": "the caller wants the effect on people acknowledged",
        "want": "make the stakes audible to the hosts",
        "stance": "firm and prepared", "register": "direct, not theatrical",
        "boundary": "no promise or accusation beyond the case evidence", "heat": 0.72,
        "conclusion_pool": [
            {"id": "record", "text": "be satisfied that the point is on the record",
             "proof_phrases": ["on the record", "said it out loud"]},
            {"id": "recognition", "text": "hear the hosts recognize the real stakes",
             "proof_phrases": ["you understand why", "you see why"]},
        ],
    },
    {
        "id": "earned-disagreement", "weight": 0.8,
        "premise": "the caller and hosts disagree even after listening carefully",
        "want": "leave the disagreement honestly stated",
        "stance": "unyielding but responsive", "register": "heated and articulate",
        "boundary": "do not manufacture agreement to end the call", "heat": 0.9,
        "conclusion_pool": [
            {"id": "disagree", "text": "accept that they still disagree",
             "proof_phrases": ["we still disagree", "agree to disagree"]},
            {"id": "respect", "text": "acknowledge being heard despite disagreement",
             "proof_phrases": ["you heard my point", "I heard your answer"]},
        ],
    },
)

_WORD = re.compile(r"[a-z0-9]+", re.I)


def _text(value: Any, field: str, *, limit: int = 240, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = " ".join(value.split())
    if required and not value:
        raise ValueError(f"{field} is required")
    if len(value) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return value


def _weight(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be between 0 and 100")
    try:
        weight = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be between 0 and 100") from exc
    if not math.isfinite(weight) or not 0 < weight <= 100:
        raise ValueError(f"{field} must be between 0 and 100")
    return weight


def _options(scenario: Mapping[str, Any], beat: str) -> list[dict[str, Any]]:
    overrides = scenario.get("path_map", {})
    if not isinstance(overrides, Mapping):
        raise ValueError("path_map must be a mapping")
    unknown = set(overrides) - set(BEATS)
    if unknown:
        raise ValueError("unknown beat: " + ", ".join(sorted(map(str, unknown))))
    raw = overrides.get(beat)
    if raw is None:
        return [{"id": identity, "cue": cue, "weight": float(weight)}
                for identity, cue, weight in DEFAULT_PATH_MAP[beat]]
    if not isinstance(raw, (list, tuple)) or not 1 <= len(raw) <= 16:
        raise ValueError(f"path_map.{beat} needs 1 to 16 options")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(raw):
        if not isinstance(row, Mapping):
            raise ValueError(f"path_map.{beat}[{index}] must be a mapping")
        identity = _text(row.get("id"), f"path_map.{beat}[{index}].id", limit=60)
        if identity in seen:
            raise ValueError(f"duplicate path id in {beat}: {identity}")
        seen.add(identity)
        out.append({
            "id": identity,
            "cue": _text(row.get("cue"), f"path_map.{beat}[{index}].cue", limit=140),
            "weight": _weight(row.get("weight", 1), f"path_map.{beat}[{index}].weight"),
        })
    return out


def _conclusions(scenario: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = scenario.get("conclusion_pool")
    if not isinstance(raw, (list, tuple)) or not 1 <= len(raw) <= 32:
        raise ValueError("conclusion_pool needs 1 to 32 conclusions")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(raw):
        if not isinstance(row, Mapping):
            raise ValueError(f"conclusion_pool[{index}] must be a mapping")
        identity = _text(row.get("id"), f"conclusion_pool[{index}].id", limit=60)
        if identity in seen:
            raise ValueError(f"duplicate conclusion id: {identity}")
        seen.add(identity)
        phrases = row.get("proof_phrases")
        if not isinstance(phrases, (list, tuple)) or not 1 <= len(phrases) <= 8:
            raise ValueError(f"conclusion_pool[{index}].proof_phrases needs 1 to 8 phrases")
        clean = []
        for phrase in phrases:
            text = _text(phrase, f"conclusion_pool[{index}].proof_phrases", limit=100)
            if len(_WORD.findall(text)) < 2:
                raise ValueError("a proof phrase needs at least two words")
            clean.append(text)
        out.append({
            "id": identity,
            "text": _text(row.get("text"), f"conclusion_pool[{index}].text", limit=240),
            "proof_phrases": clean,
            "weight": _weight(row.get("weight", 1), f"conclusion_pool[{index}].weight"),
        })
    return out


def _scenario_record(scenario: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(scenario, Mapping):
        raise ValueError("scenario must be a mapping")
    allowed = {"id", "premise", "want", "stance", "register", "boundary",
               "heat", "system_prompt", "conclusion_pool", "path_map",
               "weight", "enabled", "notes"}
    unknown = set(scenario) - allowed
    if unknown:
        raise ValueError("unknown scenario field: " + ", ".join(sorted(map(str, unknown))))
    heat_value = scenario.get("heat", 0.5)
    if isinstance(heat_value, bool):
        raise ValueError("heat must be between 0 and 1")
    try:
        heat = float(heat_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("heat must be between 0 and 1") from exc
    if not math.isfinite(heat) or not 0 <= heat <= 1:
        raise ValueError("heat must be between 0 and 1")
    enabled = scenario.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false")
    overrides = scenario.get("path_map", {})
    if not isinstance(overrides, Mapping):
        raise ValueError("path_map must be a mapping")
    paths = {beat: _options(scenario, beat) for beat in BEATS if beat in overrides}
    # Validate unknown beat keys even when none of the six known keys occurs.
    if set(overrides) - set(BEATS):
        raise ValueError("path_map contains an unknown beat")
    return {
        "id": _text(scenario.get("id"), "id", limit=80),
        "premise": _text(scenario.get("premise"), "premise"),
        "want": _text(scenario.get("want"), "want"),
        "stance": _text(scenario.get("stance"), "stance", limit=120),
        "register": _text(scenario.get("register"), "register", limit=120),
        "boundary": _text(scenario.get("boundary"), "boundary", limit=160),
        "heat": heat,
        "system_prompt": _text(scenario.get("system_prompt", ""),
                               "system_prompt", limit=500, required=False),
        "conclusion_pool": _conclusions(scenario), "path_map": paths,
        "weight": _weight(scenario.get("weight", 1), "weight"),
        "enabled": enabled,
        "notes": _text(scenario.get("notes", ""), "notes", limit=500,
                       required=False),
    }


def _catalog_record(catalog: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(catalog, Mapping):
        raise ValueError("catalog must be a mapping")
    unknown = set(catalog) - {"schema_version", "scenarios", "notes",
                              "source", "fallback_reason"}
    if unknown:
        raise ValueError("unknown catalog field: " + ", ".join(sorted(map(str, unknown))))
    if type(catalog.get("schema_version")) is not int or catalog["schema_version"] != CATALOG_VERSION:
        raise ValueError("unsupported scenario catalog version")
    raw = catalog.get("scenarios")
    if not isinstance(raw, (list, tuple)) or not 1 <= len(raw) <= MAX_SCENARIOS:
        raise ValueError(f"catalog needs 1 to {MAX_SCENARIOS} scenarios")
    scenarios = [_scenario_record(row) for row in raw]
    ids = [row["id"] for row in scenarios]
    if len(set(ids)) != len(ids):
        raise ValueError("scenario ids must be unique")
    return {"schema_version": CATALOG_VERSION, "scenarios": scenarios,
            "notes": _text(catalog.get("notes", ""), "catalog notes",
                           limit=500, required=False)}


def _builtin_catalog(reason: str) -> dict[str, Any]:
    catalog = _catalog_record({"schema_version": CATALOG_VERSION,
                               "scenarios": BUILTIN_SCENARIOS})
    return {**catalog, "source": "builtin", "fallback_reason": reason}


def load_scenario_catalog(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read a bounded JSON catalog; fall back in memory without writing.

    ``source`` is ``file`` or ``builtin``. ``fallback_reason`` distinguishes
    a missing file from an invalid or unreadable one for operator reporting.
    An explicit catalog with every scenario disabled stays disabled.
    """
    target = Path(path)
    try:
        with target.open("rb") as stream:
            raw = stream.read(MAX_CATALOG_BYTES + 1)
    except FileNotFoundError:
        return _builtin_catalog("missing")
    except OSError:
        return _builtin_catalog("unreadable")
    if len(raw) > MAX_CATALOG_BYTES:
        return _builtin_catalog("oversize")
    try:
        catalog = _catalog_record(json.loads(raw.decode("utf-8")))
    except (UnicodeError, ValueError, TypeError):
        return _builtin_catalog("invalid")
    return {**catalog, "source": "file", "fallback_reason": ""}


def save_scenario_catalog(path: str | os.PathLike[str],
                          catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Validate, fsync and atomically replace a catalog in an existing dir.

    Failed validation or replacement leaves the original bytes untouched.
    The caller owns the path and may save the dict returned by ``load``.
    """
    clean = _catalog_record(catalog)
    payload = (json.dumps(clean, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")) + "\n").encode("utf-8")
    if len(payload) > MAX_CATALOG_BYTES:
        raise ValueError("scenario catalog exceeds size limit")
    target = Path(path)
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.",
                                            suffix=".tmp", dir=target.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {**clean, "source": "file", "fallback_reason": ""}


def select_call_scenario(catalog: Mapping[str, Any], *, rng: Any = None,
                         target_heat: float | None = None) -> dict[str, Any] | None:
    """Weighted draw from enabled scenarios; optionally honor case heat.

    ``target_heat`` uses the 0..1 scale. A catalog with no compatible enabled
    row yields None, so an existing case is not forced into the wrong tone.
    """
    clean = _catalog_record(catalog)
    available = [row for row in clean["scenarios"] if row["enabled"]]
    if target_heat is not None:
        if (isinstance(target_heat, bool) or not isinstance(target_heat, (int, float))
                or not math.isfinite(target_heat) or not 0 <= target_heat <= 1):
            raise ValueError("target_heat must be between 0 and 1")
        available = [row for row in available
                     if abs(row["heat"] - target_heat) <= HEAT_TOLERANCE]
    if not available:
        return None
    return _draw(available, rng if rng is not None else random)


def _draw(options: Sequence[dict[str, Any]], rng: Any) -> dict[str, Any]:
    value = rng.random()
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value < 1:
        raise ValueError("rng.random() must return a number in [0, 1)")
    target = value * sum(option["weight"] for option in options)
    for option in options:
        target -= option["weight"]
        if target < 0:
            return dict(option)
    return dict(options[-1])  # floating-point rounding at the final boundary


def call_path_draw(scenario: Mapping[str, Any], *, caller_name: str = "",
                   topic: str = "", case_outcome: str = "",
                   rng: Any = None) -> dict[str, Any]:
    """Draw one path per beat and one conclusion, without IO or model calls.

    ``path_map`` may override any of the six default beats. The returned
    structure is JSON-safe and can be retained with a caller's other metadata.
    The caller supplies a seeded ``random.Random`` when reproducibility is
    required; otherwise the station's usual random stream is used.
    """
    clean = _scenario_record(scenario)
    subject = _text(topic_subject(topic) or topic_subject(clean["premise"]), "subject")
    name = _text(caller_name, "caller_name", limit=100, required=False)
    outcome = _text(case_outcome, "case_outcome", limit=400, required=False)
    choices = {beat: _options(clean, beat) for beat in BEATS}
    source = rng if rng is not None else random
    beats = [{"beat": beat, **_draw(choices[beat], source)} for beat in BEATS]
    conclusion = _draw(clean["conclusion_pool"], source)
    return {
        "scenario_id": clean["id"], "caller_name": name, "subject": subject,
        "premise": clean["premise"], "want": clean["want"],
        "stance": clean["stance"], "register": clean["register"],
        "boundary": clean["boundary"], "heat": clean["heat"],
        "system_prompt": clean["system_prompt"], "beats": beats,
        "conclusion": conclusion, "case_outcome": outcome,
    }


def call_scenario_clause(plan: Mapping[str, Any]) -> str:
    """One compact dramatic direction to fold into the existing call sheet.

    The caller protocol still owns the turn count, speakers and sign-off.
    These are directions for its middle, not six extra lines to write.
    """
    beats = plan.get("beats") if isinstance(plan, Mapping) else None
    conclusion = plan.get("conclusion") if isinstance(plan, Mapping) else None
    if (not isinstance(beats, (list, tuple)) or len(beats) != len(BEATS)
            or not isinstance(conclusion, Mapping)):
        raise ValueError("plan needs six beats and a conclusion")
    cues = []
    for expected, beat in zip(BEATS, beats):
        if not isinstance(beat, Mapping) or beat.get("beat") != expected:
            raise ValueError("plan beats are out of order")
        cues.append(_text(beat.get("cue"), f"{expected} cue", limit=140))
    subject = _text(plan.get("subject"), "subject")
    premise = _text(plan.get("premise"), "premise")
    want = _text(plan.get("want"), "want")
    stance = _text(plan.get("stance"), "stance", limit=120)
    register = _text(plan.get("register"), "register", limit=120)
    boundary = _text(plan.get("boundary"), "boundary", limit=160)
    heat = plan.get("heat")
    if isinstance(heat, bool) or not isinstance(heat, (int, float)) or not 0 <= heat <= 1:
        raise ValueError("plan heat must be between 0 and 1")
    landing = _text(conclusion.get("text"), "conclusion text")
    outcome = _text(plan.get("case_outcome", ""), "case_outcome",
                    limit=400, required=False)
    extra = _text(plan.get("system_prompt", ""), "system_prompt",
                  limit=500, required=False)
    return (
        "SCENARIO DIRECTION, within the existing phone running order, not extra "
        "turns: The subject is " + subject + "; premise: " + premise
        + ". The caller wants to " + want + "; their stance is " + stance
        + "; register: " + register + "; heat: " + format(heat, ".2g")
        + "/1; boundary: " + boundary
        + ". In sequence: " + "; ".join(cues) + ". Emotional landing: "
        + landing + ". This is not a new event or procedural ending. "
        + ("The existing case outcome remains binding: " + outcome + ". "
           if outcome else "Any existing case or storyline outcome remains binding. ")
        + "Use only known facts; keep the caller's resolution second to last "
        "and the host sign-off last."
        + (" Additional direction: " + extra if extra else "")
    )


def _words(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def _turn_text(turn: Any) -> str:
    if isinstance(turn, str):
        return turn
    if isinstance(turn, (list, tuple)) and len(turn) == 2 and isinstance(turn[1], str):
        return turn[1]  # app.py banter_turns() shape: (speaker, text)
    raise ValueError("each turn must be text or a (speaker, text) pair")


def call_conclusion_report(plan: Mapping[str, Any], turns: Sequence[Any], *,
                           source: str = "draft") -> dict[str, Any]:
    """Check draft turns only; a string label cannot prove playback."""
    if source != "draft":
        raise ValueError("use call_aired_conclusion_report for aired receipts")
    if isinstance(turns, (str, bytes)) or not isinstance(turns, Sequence):
        raise ValueError("turns must be a sequence of individual turns")
    conclusion = plan.get("conclusion") if isinstance(plan, Mapping) else None
    if not isinstance(conclusion, Mapping):
        raise ValueError("plan has no drawn conclusion")
    phrases = conclusion.get("proof_phrases")
    if not isinstance(phrases, (list, tuple)) or not phrases:
        raise ValueError("drawn conclusion has no proof phrases")
    tail = [_turn_text(turn) for turn in turns[-3:]]
    spoken_turns = [_words(turn) for turn in tail]
    matched = ""
    for phrase in phrases:
        wanted = _words(_text(phrase, "proof phrase", limit=100))
        if any(words[at:at + len(wanted)] == wanted
               for words in spoken_turns
               for at in range(len(words) - len(wanted) + 1)):
            matched = phrase
            break
    found = bool(matched)
    return {
        "scenario_id": str(plan.get("scenario_id") or ""),
        "conclusion_id": str(conclusion.get("id") or ""),
        "source": source, "tail_turns": len(tail), "matched": found,
        "matched_phrase": matched, "aired_verified": False,
        "soft_faults": [] if found else ["drawn conclusion not stated in the last three turns"],
    }


def call_aired_conclusion_report(plan: Mapping[str, Any],
                                 receipts: Sequence[Mapping[str, Any]], *,
                                 sid: str,
                                 expected_lines: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Check the final caller utterance against durable air-log hearing receipts.

    ``expected_lines`` are the final call burst's ordered script rows (only
    line_id, who, kind and turn are read). They identify the terminal three
    *utterances*, including all chunks of each. Their draft text is ignored.
    ``receipts`` must be airlog_rows rows, not a script or publication event.
    A page hearing stamp is the sole positive evidence of audible playback.
    ``not_aired`` means no selected tail line has such a stamp, not proof of
    silence; ``insufficient_evidence`` means the tail cannot be adjudicated.
    ``missed`` is a lexical advisory, never a procedural call outcome.
    """
    if not isinstance(plan, Mapping) or not isinstance(plan.get("conclusion"), Mapping):
        raise ValueError("plan has no drawn conclusion")
    conclusion = plan["conclusion"]
    phrases = conclusion.get("proof_phrases")
    if not isinstance(phrases, (list, tuple)) or not phrases:
        raise ValueError("drawn conclusion has no proof phrases")
    wanted = [(_text(p, "proof phrase", limit=100), _words(p)) for p in phrases]
    caller_name = _text(plan.get("caller_name"), "caller_name", limit=100)
    if not isinstance(sid, str) or not sid or len(sid) > 48:
        raise ValueError("sid must identify one call round")
    if (isinstance(expected_lines, (str, bytes)) or not isinstance(expected_lines, Sequence)
            or len(expected_lines) > 512):
        raise ValueError("expected_lines must be a bounded sequence")
    if (isinstance(receipts, (str, bytes)) or not isinstance(receipts, Sequence)
            or len(receipts) > 10000):
        raise ValueError("receipts must be a bounded sequence")

    lines: list[tuple[str, str, int]] = []
    ids: set[str] = set()
    for row in expected_lines:
        if not isinstance(row, Mapping):
            raise ValueError("expected line must be a mapping")
        if row.get("kind") != "dialogue":
            continue
        line_id, who, turn = row.get("line_id"), row.get("who"), row.get("turn")
        if (not isinstance(line_id, str) or not line_id or len(line_id) > 100
                or line_id in ids or who not in ("dj", "cohost", "third", "caller", "caller2")
                or isinstance(turn, bool) or not isinstance(turn, int) or turn < 0):
            raise ValueError("expected dialogue needs unique line IDs, seats and turns")
        ids.add(line_id)
        lines.append((line_id, who, turn))

    groups: list[list[tuple[str, str, int]]] = []
    for line in lines:
        if not groups or groups[-1][0][1:] != line[1:]:
            groups.append([])
        groups[-1].append(line)
    if (len(groups) < 3 or groups[-2][0][1] != "caller"
            or groups[-1][0][1] not in ("dj", "cohost", "third")):
        raise ValueError("expected lines need a caller resolution and host sign-off")
    tail = [line for group in groups[-3:] for line in group]
    tail_ids = {line[0] for line in tail}
    found: dict[str, Mapping[str, Any]] = {}
    conflict = False
    for row in receipts:
        if not isinstance(row, Mapping):
            raise ValueError("receipt must be a mapping")
        if row.get("sid") != sid or row.get("id") not in tail_ids:
            continue
        line_id = row["id"]
        if line_id in found and dict(found[line_id]) != dict(row):
            conflict = True
        found[line_id] = row

    base = {"scenario_id": str(plan.get("scenario_id") or ""),
            "conclusion_id": str(conclusion.get("id") or ""),
            "sid": sid, "source": "air_log_page_ack",
            "expected_line_ids": [line[0] for line in tail],
            "heard_line_ids": [], "matched": False, "matched_phrase": "",
            "aired_verified": False, "soft_faults": []}
    heard = []
    for line_id, _, _ in tail:
        row = found.get(line_id)
        if row is None or row.get("heard_ack_by") != "page":
            continue
        stamp = row.get("heard_ack_at")
        if (isinstance(stamp, (int, float)) and not isinstance(stamp, bool)
                and math.isfinite(stamp) and stamp > 0):
            heard.append(line_id)
    base["heard_line_ids"] = heard
    if not heard:
        return {**base, "status": "not_aired",
                "soft_faults": ["no selected call tail line has a page hearing receipt"]}
    if conflict or len(heard) != len(tail):
        return {**base, "status": "insufficient_evidence",
                "soft_faults": ["the selected call tail has missing or conflicting hearing receipts"]}

    previous_stamp = 0.0
    for line_id, who, turn in tail:
        row = found[line_id]
        stamp = float(row["heard_ack_at"])
        names = [str(row[key]) for key in ("name", "caller") if row.get(key)]
        if (row.get("round") != "caller" or row.get("who") != who
                or row.get("turn") != turn or stamp < previous_stamp
                or not isinstance(row.get("text"), str)
                or not row["text"]
                or (who == "caller" and (not names or any(
                    name.casefold() != caller_name.casefold() for name in names)))):
            return {**base, "status": "insufficient_evidence",
                    "soft_faults": ["call receipt identity, order or text is incomplete"]}
        previous_stamp = stamp

    caller_words = _words(" ".join(found[line_id]["text"] for line_id, _, _ in groups[-2]))
    matched_phrase = ""
    for phrase, phrase_words in wanted:
        if any(caller_words[at:at + len(phrase_words)] == phrase_words
               for at in range(len(caller_words) - len(phrase_words) + 1)):
            matched_phrase = phrase
            break
    if matched_phrase:
        return {**base, "status": "matched", "matched": True,
                "matched_phrase": matched_phrase, "aired_verified": True}
    if any(len(found[line_id]["text"]) >= 600 for line_id, _, _ in groups[-2]):
        return {**base, "status": "insufficient_evidence",
                "soft_faults": ["caller receipt text may be truncated"]}
    return {**base, "status": "missed",
            "soft_faults": ["drawn conclusion not stated in the aired caller resolution"]}
