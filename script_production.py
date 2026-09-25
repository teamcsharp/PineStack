"""script_production.py - the producer that actually runs the production flow.

`docs/notes/speaker-recording-and-script-assembly.md` describes one road:

    Finalized conversation and cast
        -> Frozen production script with ordered line identities
        -> One recording session per performer
        -> Speaker masters + verified line cuts
        -> Assembly in original script order
        -> Finished audio + exact line cue sheet
        -> Ready candidate selection / replacement
        -> Atomic commitment to the broadcast sequence
        -> One playback controller

Five modules were built for the boundaries of that road - `script_manifest`,
`manifest_store`, `speaker_session`, `line_alignment`, `conversation_assembly`
- and `broadcast_admission` was built for its far end and is deployed. What
did not exist was a PRODUCER: nothing froze a script, nothing opened a
performer session, nothing recorded a master, nothing cut a line, nothing
assembled. This is that producer.

WHICH CAPABILITY THIS IMPLEMENTS
--------------------------------
The note is explicit and this module obeys it to the letter:

    "A session implemented with bounded engine segments is an alternative:
     retain boundaries at synthesis time and save a speaker master with its
     cut map. This avoids guessing cuts, but is still segmented synthesis
     and must be described that way. It does not establish the prosody or
     speed benefits of a single continuous performance."

The station renders every scripted chunk with its own call to the engine and
welds the results. One render call produces one file, and that file IS one
scripted line - so the boundary is RETAINED FROM SYNTHESIS, not recovered
from the audio afterwards. That is why the default road is:

    road            = line_alignment.MODE_SEGMENTED  ("segmented_synthesis")
    master.mode     = "segmented"
    boundary_method = "renderer_boundary"

and never `"alignment"`, never a silence threshold, never an estimate. No
surface in this module calls the default road a continuous performance, and
`Production.road` carries the identity into the ledger, the cue map, the
manifests and the incident references.

The continuous-take road is implemented too - `ROAD_CONTINUOUS` - and is OFF.
It records one master per performer, asks a word-level recogniser for
evidence, and hands that evidence to `line_alignment.align_script`, which
either returns per-occurrence cuts in integer samples or refuses by name. It
is a genuinely different capability with its own identity, and it is not
enabled by the same word that enables the segmented road: the mode file has
to name it, and a caller that cannot reach the recogniser is refused with
`alignment_unavailable` rather than quietly falling back.

THE SWITCH
----------
`<data>/script_production/mode`, re-read at most once every three seconds -
the same idea as `<data>/broadcast_admission/mode`, so turning this on or off
is a one-word write and never a restart of a station that is broadcasting.

    off                     the default; nothing is produced at all
    shadow                  produce everything, then THROW IT AWAY and air
                            exactly what would have aired anyway, recording
                            what the two roads disagreed about
    on                      the assembled artifact's cue map is carried to
                            air and admitted through the deployed gate
    shadow continuous       the continuous-take road instead of segmented
    shadow budget=45        seconds one round's production may spend
    shadow every=300        seconds between two productions
    shadow lines=40         the most lines a round may have to be produced

`off` is not merely "do nothing": `ScriptProducer.produce` refuses with
`production_off` and writes nothing, so a caller that forgets to check is
still safe.

WHAT SHADOW MEASURES
--------------------
`compare_windows` puts the assembled cue map beside the arithmetic the stream
path uses today - each clip measured on disk, `seg_real_seconds` guessing what
the mixer's tail trim will take off, and the whole span then rescaled by
`made/ours` to fit the finished duration (`app.py:83945` onward). Both are
computed from the same strips and the same mixer, so the difference between
them is the error the rescale is absorbing, per line, in seconds. That
difference is written to the ledger for every round.

PURITY
------
No `app.py` import, no HTTP client of its own, no live store. The station's
facts arrive as arguments and its lookups arrive as callables. The one
network call this module can make - the recogniser, on the continuous road -
is injected as `align=`; with no injection that road refuses.
"""
from __future__ import annotations

import array
import hashlib
import json
import math
import os
import tempfile
import time
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import conversation_assembly as ca
import line_alignment as la
import manifest_store as ms
import script_manifest as sm
import segment_contract as sc
import speaker_session as ss

__all__ = [
    "MODE_OFF", "MODE_SHADOW", "MODE_ON", "MODES",
    "ROAD_SEGMENTED", "ROAD_CONTINUOUS",
    "BOUNDARY_RENDERER", "BOUNDARY_ALIGNMENT",
    "REFUSALS",
    "Settings", "ProductionSwitch", "ProductionLedger", "words_between",
    "RoundLine", "RoundSource", "Production", "ScriptProducer",
    "round_source", "compare_windows", "estimated_windows", "references",
    "measured_round_supply",
]

SCHEMA = 1

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ON = "on"
MODES = (MODE_OFF, MODE_SHADOW, MODE_ON)

# The two capabilities, spelled as `line_alignment` spells them so one
# vocabulary crosses every module.
ROAD_SEGMENTED = la.MODE_SEGMENTED          # "segmented_synthesis"
ROAD_CONTINUOUS = la.MODE_CONTINUOUS        # "continuous_take"
ROADS = (ROAD_SEGMENTED, ROAD_CONTINUOUS)

BOUNDARY_RENDERER = "renderer_boundary"
BOUNDARY_ALIGNMENT = "alignment"

# --- the estimator's constants, mirrored from app.py -----------------------
# `conversation_assembly.py` mirrors the MIXER; this mirrors the ARITHMETIC
# the stream path does around it, because the whole point of shadow mode is
# to put the two side by side. Each is named beside the app.py symbol it
# copies so drift is one grep, and `MirrorTests` in the suite reads app.py as
# text and fails if any of them has moved.
CONCAT_TAIL = 0.9                 # app.py: CONCAT_TAIL
CONCAT_KEEP = 0.06                # app.py: CONCAT_KEEP
SEG_TRIM_DB = -50.0               # app.py: SEG_TRIM_DB
SEG_TRIM_LOOK = 4.0               # app.py: SEG_TRIM_LOOK

# --- what one engine request may actually PERFORM -------------------------
# Measured, not assumed: `docs/notes/continuous-take-bench-2026-09-15.md`.
# The XTTS clone server is `_synthesize(text[:1000], ...)` at
# `reachy-gateway/voice_clone_server.py:371` - it TRUNCATES IN THE SERVER,
# returns HTTP 200 and returns clean audio, and nothing upstream can see it.
# Three real rounds asked 1,531 / 1,663 / 1,602 characters and got 62.6% /
# 59.7% / 66.1% of their text back as sound. A third to two fifths of each
# performance was never spoken and no error was raised anywhere.
#
# The station's own road is safe from this today because `voice_render_any`
# splits above VOICE_MAX_CHARS (800), which is under the ceiling. Nothing in
# THIS module ever calls an engine - the segmented road consumes files the
# station already rendered, and the continuous road consumes a master its
# caller supplies. These numbers are here so that a part which CANNOT have
# been performed whole is refused by name instead of being trusted.
ENGINE_REQUEST_CAPS: dict[str, int] = {
    "xtts": 1000,     # voice_clone_server.py:371, silent truncation
    "f5": 280,        # app.py:12454 - past ~300 the alignment slides
}
DEFAULT_REQUEST_CAP = 800             # app.py: VOICE_MAX_CHARS

DEFAULT_BUDGET_S = 90.0
DEFAULT_EVERY_S = 180.0
DEFAULT_MAX_LINES = 72
LEDGER_KEEP = 4000


# --------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------
# Every reason this producer can decline to hand over a conversation. The
# wrapped modules keep their own vocabularies; where one of them refuses, its
# code is carried through verbatim under `detail["codes"]` so an operator
# reading the ledger sees the module's own sentence and not a paraphrase.
REFUSALS: dict[str, str] = {
    "production_off": "the production switch is off",
    "production_busy": "another production is already running for this round",
    "too_soon": "the interval between productions has not elapsed",
    "round_too_long": "this round has more lines than the switch allows",
    "round_incomplete": "a scripted line has no finished audio behind it",
    "no_lines": "the round has no speakable line in it",
    "no_cast": "no seat in this round has both a voice and an engine",
    "media_missing": "a take's audio is not on disk",
    "media_unreadable": "a take's audio could not be read as a 16-bit wav",
    "script_refused": "the frozen script was refused by the manifest store",
    "session_refused": "a performer session was refused by the manifest store",
    "session_incomplete": "a performer session has no verified take for a line "
                          "it is assigned",
    "master_refused": "a speaker master was refused by the manifest store",
    "cut_refused": "a line cut was refused; it needs a retake or another "
                   "complete ready candidate",
    "pinned_take_overwrite": "new work would overwrite a take pinned by an "
                             "admitted broadcast occurrence",
    "assembly_refused": "the assembler refused to build this conversation",
    "assembly_record_refused": "the finished conversation record was refused",
    "assembly_unverified": "the assembler did not verify its own artifact",
    "admission_refused": "the admission record was refused",
    "sequence_mismatch": "the finished cue sequence is not the frozen script "
                         "sequence",
    "alignment_unavailable": "the continuous-take road has no recogniser to "
                             "ask for evidence",
    "continuous_master_missing": "the continuous-take road needs one whole "
                                 "performance per performer and none was "
                                 "supplied",
    "request_cap_exceeded": "this part is longer than the engine will perform "
                            "in one request, and that engine truncates "
                            "silently",
    "alignment_refused": "the aligner refused to place a line in the master",
    "budget_exceeded": "production ran past the budget it was given",
    "production_error": "production raised",
}


def refuse(code: str, reason: str = "", **detail: Any) -> dict:
    """One refusal, in the shape every other module here uses."""
    return {"code": str(code),
            "reason": str(reason or REFUSALS.get(code) or code),
            "detail": dict(detail)}


# --------------------------------------------------------------------------
# the switch
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    """What the mode file says, right now."""
    mode: str = MODE_OFF
    road: str = ROAD_SEGMENTED
    budget_s: float = DEFAULT_BUDGET_S
    every_s: float = DEFAULT_EVERY_S
    max_lines: int = DEFAULT_MAX_LINES
    text: str = ""

    @property
    def off(self) -> bool:
        return self.mode == MODE_OFF

    @property
    def airs(self) -> bool:
        """Does the result of production reach the air?"""
        return self.mode == MODE_ON

    def as_dict(self) -> dict:
        return {"mode": self.mode, "road": self.road,
                "budget_s": self.budget_s, "every_s": self.every_s,
                "max_lines": self.max_lines, "text": self.text}


class ProductionSwitch:
    """`<data>/script_production/mode`, re-read at most every three seconds.

    The admission gate's own switch works this way and the reason is the same:
    the station is on air, and the way to turn a new road off has to be a
    one-word write that takes effect in seconds, not a restart.

    A missing, empty or unreadable file means OFF. So does a word this does
    not recognise: an operator's typo must never be read as permission.
    """

    def __init__(self, root: str | Path, *, env: Mapping[str, str] | None = None,
                 ttl: float = 3.0, clock: Callable[[], float] = time.time):
        self.root = Path(root)
        self.path = self.root / "mode"
        self.ttl = float(ttl)
        self.clock = clock
        self._env = dict(os.environ if env is None else env)
        self._read_at = 0.0
        self._cached = Settings()

    def _text(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            return ""

    def settings(self) -> Settings:
        now = float(self.clock())
        if self._read_at and (now - self._read_at) < self.ttl:
            return self._cached
        text = self._text()
        if not text:
            text = str(self._env.get("SPARK_AGENT_SCRIPT_PRODUCTION", "")).strip()
        self._read_at = now
        self._cached = parse_settings(text)
        return self._cached

    def mode(self) -> str:
        return self.settings().mode

    def write(self, text: str) -> None:
        """Used by tests and by an operator tool; never by the producer."""
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
        tmp.write_text(str(text).strip() + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        self._read_at = 0.0


def parse_settings(text: str) -> Settings:
    """One to five whitespace-separated words into a Settings.

    Unrecognised words are ignored rather than obeyed, and a file that names
    no mode at all is OFF.
    """
    raw = str(text or "").strip()
    mode = MODE_OFF
    road = ROAD_SEGMENTED
    budget = DEFAULT_BUDGET_S
    every = DEFAULT_EVERY_S
    lines = DEFAULT_MAX_LINES
    for word in raw.replace(",", " ").split():
        low = word.strip().lower()
        if low in MODES:
            mode = low
        elif low in ("continuous", "continuous_take", ROAD_CONTINUOUS):
            road = ROAD_CONTINUOUS
        elif low in ("segmented", "segmented_synthesis", ROAD_SEGMENTED):
            road = ROAD_SEGMENTED
        elif low.startswith("budget="):
            budget = _positive(low.split("=", 1)[1], DEFAULT_BUDGET_S)
        elif low.startswith("every="):
            every = _positive(low.split("=", 1)[1], DEFAULT_EVERY_S)
        elif low.startswith("lines="):
            lines = int(_positive(low.split("=", 1)[1], DEFAULT_MAX_LINES))
    return Settings(mode=mode, road=road, budget_s=budget, every_s=every,
                    max_lines=max(1, lines), text=raw)


def _positive(value: Any, fallback: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    if out != out or out <= 0 or out in (float("inf"), float("-inf")):
        return float(fallback)
    return out


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------

class ProductionLedger:
    """Append-only, bounded, and the only place shadow's measurements live.

    One line per production attempt - refusals included, because a road that
    only records its successes cannot be compared with the road it is trying
    to replace. `report()` is what `/api/script/production` and the incident
    capture read.
    """

    def __init__(self, root: str | Path, *, keep: int = LEDGER_KEEP):
        self.root = Path(root)
        self.path = self.root / "rounds.jsonl"
        self.keep = int(keep)

    def record(self, row: Mapping[str, Any]) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            line = json.dumps(dict(row), ensure_ascii=False, default=str)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            self._trim()
        except (OSError, ValueError, TypeError):
            # A ledger that cannot be written must never cost the air a beat.
            pass

    def _trim(self) -> None:
        try:
            if not self.path.is_file():
                return
            with self.path.open("r", encoding="utf-8") as handle:
                rows = handle.readlines()
            if len(rows) <= self.keep + 200:
                return
            tmp = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
            tmp.write_text("".join(rows[-self.keep:]), encoding="utf-8")
            os.replace(tmp, self.path)
        except (OSError, ValueError):
            pass

    def rows(self, limit: int = 0) -> list[dict]:
        out: list[dict] = []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        got = json.loads(line)
                    except ValueError:
                        continue          # a torn final line is dropped, never guessed
                    if isinstance(got, dict):
                        out.append(got)
        except OSError:
            return []
        if limit and limit > 0:
            return out[-limit:]
        return out

    def report(self, limit: int = 0) -> dict:
        """What shadow measured, in the shape a report can be written from."""
        rows = self.rows(limit)
        out: dict[str, Any] = {
            "schema": SCHEMA, "rounds": len(rows),
            "complete": 0, "refused": 0, "aired": 0,
            "by_mode": {}, "by_road": {}, "refusals": {},
            "cost_seconds": {"total": 0.0, "mean": 0.0, "max": 0.0},
            "lines": 0,
            "disagreement": {"rounds": 0, "lines": 0, "mean_abs_s": 0.0,
                             "max_abs_s": 0.0, "head_mean_s": 0.0,
                             "tail_mean_s": 0.0, "worst": None},
            "last": rows[-1] if rows else None,
        }
        costs: list[float] = []
        deltas: list[float] = []
        heads: list[float] = []
        tails: list[float] = []
        worst: tuple[float, Any] = (0.0, None)
        for row in rows:
            mode = str(row.get("mode") or "")
            road = str(row.get("road") or "")
            out["by_mode"][mode] = int(out["by_mode"].get(mode, 0)) + 1
            out["by_road"][road] = int(out["by_road"].get(road, 0)) + 1
            if row.get("ok"):
                out["complete"] += 1
            else:
                out["refused"] += 1
                for code in (row.get("refusal_codes") or []):
                    key = str(code)
                    out["refusals"][key] = int(out["refusals"].get(key, 0)) + 1
            if row.get("aired"):
                out["aired"] += 1
            out["lines"] += int(row.get("lines") or 0)
            cost = float(row.get("cost_seconds") or 0.0)
            if cost > 0:
                costs.append(cost)
            cmp_row = row.get("disagreement") or {}
            if cmp_row.get("lines"):
                out["disagreement"]["rounds"] += 1
                out["disagreement"]["lines"] += int(cmp_row.get("lines") or 0)
                deltas.append(float(cmp_row.get("mean_abs_s") or 0.0))
                heads.append(float(cmp_row.get("head_delta_s") or 0.0))
                tails.append(float(cmp_row.get("tail_delta_s") or 0.0))
                if float(cmp_row.get("max_abs_s") or 0.0) > worst[0]:
                    worst = (float(cmp_row.get("max_abs_s") or 0.0),
                             {"assembly_id": row.get("assembly_id"),
                              "revision": row.get("revision"),
                              "max_abs_s": cmp_row.get("max_abs_s"),
                              "at": row.get("at")})
        if costs:
            out["cost_seconds"] = {"total": round(sum(costs), 2),
                                   "mean": round(sum(costs) / len(costs), 2),
                                   "max": round(max(costs), 2)}
        if deltas:
            out["disagreement"]["mean_abs_s"] = round(sum(deltas) / len(deltas), 4)
            out["disagreement"]["max_abs_s"] = round(worst[0], 4)
            out["disagreement"]["worst"] = worst[1]
        if heads:
            out["disagreement"]["head_mean_s"] = round(sum(heads) / len(heads), 4)
        if tails:
            out["disagreement"]["tail_mean_s"] = round(sum(tails) / len(tails), 4)
        return out


# --------------------------------------------------------------------------
# what a round looks like on the way in
# --------------------------------------------------------------------------

@dataclass
class RoundLine:
    """One scripted utterance, as the station actually renders it.

    `media` is the finished audio of THIS line and nothing else - the station
    asked the engine for exactly this text and got exactly this file back.
    That is what makes `boundary_method="renderer_boundary"` a fact rather
    than a claim.

    `turn` and `chunk` keep the note's "relationship between a displayed line
    and any internal render chunks": several of these can belong to one
    displayed turn, and they say which.
    """
    actor: str
    text: str
    media: str
    seconds: float = 0.0
    turn: int = -1
    chunk: int = 0
    cache_key: str = ""
    instructions: str = ""
    pronunciations: tuple = ()


@dataclass
class RoundSource:
    """A finalized conversation and its cast, ready to be frozen."""
    conversation_id: str
    lines: list[RoundLine]
    cast: dict[str, dict]
    media_root: Path
    label: str = ""
    kind: str = ""
    notes: str = ""
    # actor -> ONE whole performance of that actor's part, for the
    # continuous-take road. Empty on the road this station actually takes:
    # nothing here renders, and no such master exists unless a caller made
    # one and handed it over.
    parts: dict = field(default_factory=dict)

    def actors(self) -> list[str]:
        seen: list[str] = []
        for line in self.lines:
            if line.actor not in seen:
                seen.append(line.actor)
        return seen


def measured_round_supply(source: RoundSource,
                          cue_map: Mapping[str, Any]) -> dict[str, Any]:
    """Contract supply from verified mix frames, excluding the final pad."""
    if str(cue_map.get("derivation") or "") != "measured":
        raise ValueError("a measured cue map is required for playable duration")
    rate = int(cue_map.get("sample_rate") or 0)
    if rate <= 0:
        raise ValueError("the cue map has no sample rate")
    cues = [cue for cue in (cue_map.get("cues") or [])
            if str(cue.get("kind") or "line") == "line"]
    if len(cues) != len(source.lines):
        raise ValueError("the cue map does not cover every scripted line")
    body_frames = max(0, int(cue_map.get("body_frames") or 0))
    speech_frames = sum(max(0, int(cue.get("speech_end_sample") or 0)
                            - int(cue.get("speech_start_sample",
                                          cue.get("start_sample")) or 0))
                        for cue in cues)
    known_turns = {line.turn for line in source.lines if line.turn >= 0}
    unknown_turns = sum(1 for line in source.lines if line.turn < 0)
    turns = len(known_turns) + unknown_turns
    return {
        "scripted_seconds": round(sum(sc.estimated_speech_seconds(line.text)
                                      for line in source.lines), 3),
        "recorded_seconds": round(speech_frames / rate, 3),
        "playable_seconds": round(body_frames / rate, 3),
        "body_frames": body_frames,
        "speech_frames": speech_frames,
        "sample_rate": rate,
        "roles": sorted({sc.normalize_role(line.actor) for line in source.lines}),
        "turns": turns,
        "events": turns,
        "lines": len(source.lines),
        "measured": True,
    }


def round_source(conversation_id: str,
                 plan: Sequence[Sequence[Any]],
                 voices: Mapping[str, str],
                 *,
                 engine_for: Callable[[str], str],
                 clip_for: Callable[[str, str, str], Mapping[str, Any] | None],
                 media_root: str | Path,
                 line_plan: Sequence[Mapping[str, Any]] = (),
                 cache_key_for: Callable[[str, str, str], str] | None = None,
                 config_for: Callable[[str, str, str], Mapping[str, Any]] | None = None,
                 instructions_for: Callable[[str, str], str] | None = None,
                 parts: Mapping[str, str] | None = None,
                 label: str = "", kind: str = "") -> tuple[RoundSource, list[dict]]:
    """Build a `RoundSource` from the station's own round plan.

    `plan` is `_round_chunks`'s answer - the exact (text, voice, who) the
    engine was asked for, in SCRIPT order - which is the only order that may
    decide the output. Grouping by performer happens after this and cannot
    reach it.

    Returns (source, refusals). A line whose audio is not on disk produces a
    `round_incomplete` refusal and the caller must not produce: "No incomplete
    conversation may be admitted."
    """
    root = Path(media_root)
    rows: list[RoundLine] = []
    cast: dict[str, dict] = {}
    refusals: list[dict] = []
    turn_of: dict[int, int] = {}
    chunk_of: dict[str, int] = {}
    turns = {int(r.get("at", -1)): r for r in (line_plan or [])
             if isinstance(r, Mapping)}
    has_ranges = any("line_from" in row and "line_to" in row
                     for row in turns.values())
    for turn in turns.values():
        start = int(turn.get("line_from", -1))
        end = int(turn.get("line_to", -1))
        for line_index in range(max(0, start), max(0, end)):
            turn_of[line_index] = int(turn.get("at", -1))
    for ordinal, row in enumerate(plan or []):
        try:
            text, voice, who = str(row[0]), str(row[1]), str(row[2])
        except (IndexError, TypeError, ValueError):
            refusals.append(refuse("no_lines", "a plan row is not (text, voice, who)",
                                   ordinal=ordinal))
            continue
        if not text or not voice or not who:
            refusals.append(refuse(
                "round_incomplete",
                "line %d has no text, no voice or no seat" % (ordinal + 1),
                ordinal=ordinal + 1))
            continue
        engine = str(engine_for(voice) or "")
        if not engine:
            refusals.append(refuse(
                "no_cast", "no engine is configured for voice %r" % voice,
                ordinal=ordinal + 1, actor=who, voice=voice))
            continue
        key = str(cache_key_for(text, voice, engine)) if cache_key_for else \
            sm.content_cache_key(text, voice, engine)
        clip = clip_for(text, voice, engine) or {}
        media = str(dict(clip).get("path") or "")
        if not media:
            refusals.append(refuse(
                "round_incomplete",
                "line %d (%s) has no finished audio; a conversation is "
                "produced whole or not at all" % (ordinal + 1, who),
                ordinal=ordinal + 1, actor=who, cache_key=key))
            continue
        name = media.rsplit("/", 1)[-1].split("?", 1)[0]
        path = Path(media)
        if not path.is_absolute() or not path.is_file():
            path = root / name
        if not path.is_file():
            refusals.append(refuse(
                "media_missing", "line %d names %s, which is not on disk"
                % (ordinal + 1, name), ordinal=ordinal + 1, media=name))
            continue
        turn = turn_of.get(ordinal, -1)
        chunk = chunk_of.get(text + "\x00" + who, 0)
        got = turns.get(ordinal) if turn < 0 and not has_ranges else None
        if isinstance(got, Mapping):
            turn = int(got.get("at", -1))
        rows.append(RoundLine(
            actor=who, text=text, media=str(path),
            seconds=float(dict(clip).get("seconds") or 0.0),
            turn=turn, chunk=chunk, cache_key=key,
            instructions=(str(instructions_for(who, voice))
                          if instructions_for else "")))
        chunk_of[text + "\x00" + who] = chunk + 1
        if who not in cast:
            config: dict[str, Any] = {}
            if config_for:
                try:
                    config = dict(config_for(who, voice, engine) or {})
                except Exception:  # noqa: BLE001
                    config = {}
            cast[who] = {"voice": voice, "engine": engine, "config": config,
                         "display": who}
        elif cast[who]["voice"] != voice or cast[who]["engine"] != engine:
            # One performer, one voice, one engine. A seat that changed mid
            # round is not one performance and must not be recorded as one.
            refusals.append(refuse(
                "no_cast",
                "%s is cast as %s/%s but line %d asks for %s/%s"
                % (who, cast[who]["voice"], cast[who]["engine"], ordinal + 1,
                   voice, engine),
                actor=who, ordinal=ordinal + 1))
    if not rows:
        refusals.append(refuse("no_lines"))
    # Surrounding dialogue, "where the renderer supports it", and always
    # identifying exactly whose words are to be spoken.
    for index, line in enumerate(rows):
        before = rows[index - 1] if index else None
        after = rows[index + 1] if index + 1 < len(rows) else None
        line.pronunciations = ()
        line.instructions = line.instructions or ""
        setattr(line, "context_before",
                ("%s: %s" % (before.actor, before.text)) if before else "")
        setattr(line, "context_after",
                ("%s: %s" % (after.actor, after.text)) if after else "")
    source = RoundSource(conversation_id=str(conversation_id),
                         lines=rows, cast=cast, media_root=root,
                         label=str(label or ""), kind=str(kind or ""),
                         parts={str(k): str(v)
                                for k, v in dict(parts or {}).items()})
    return source, refusals


# --------------------------------------------------------------------------
# reading audio
# --------------------------------------------------------------------------

def words_between(words: Sequence[Any], start_sample: int, end_sample: int,
                  sample_rate: int) -> str:
    """The recogniser's words that fall inside one cut, as text.

    A word counts when its midpoint is inside the span, so a word straddling
    an edge belongs to exactly one cut and never to both.
    """
    if sample_rate <= 0:
        return ""
    low = float(start_sample) / float(sample_rate)
    high = float(end_sample) / float(sample_rate)
    out: list[str] = []
    for word in (words or []):
        begin = float(getattr(word, "start", 0.0))
        finish = float(getattr(word, "end", begin))
        middle = (begin + finish) / 2.0
        if low <= middle < high:
            out.append(str(getattr(word, "word", "")))
    return " ".join(w for w in out if w)


def wav_facts(path: str | Path) -> dict:
    """Sample rate, frame count, channels and sha256 of one wav.

    `script_manifest` wants a prefixed digest and an explicit rate and length
    for every master; this is the one place bytes are read to supply them.
    """
    target = Path(path)
    raw = target.read_bytes()
    with wave.open(str(target), "rb") as handle:
        rate = int(handle.getframerate() or 0)
        frames = int(handle.getnframes() or 0)
        channels = int(handle.getnchannels() or 1)
        width = int(handle.getsampwidth() or 0)
    if width != 2:
        raise ValueError("%s is %d-bit; the station's masters are 16-bit"
                         % (target.name, width * 8))
    if rate <= 0 or frames <= 0:
        raise ValueError("%s reports %d frames at %d Hz" % (target.name, frames, rate))
    return {"sample_rate": rate, "frame_count": frames, "channels": channels,
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw), "seconds": frames / float(rate)}


def wav_tail_silence(path: str | Path) -> float:
    """Mirror of `app.py:_wav_tail_silence` - RMS over 20 ms windows at
    SEG_TRIM_DB, walking backwards. Used ONLY by the estimator, never to
    decide a cut: "silence alone cannot establish which line was spoken"."""
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate() or 24000
            if handle.getsampwidth() != 2:
                return -1.0
            chans = handle.getnchannels() or 1
            frames = handle.getnframes()
            if frames <= 0:
                return -1.0
            look = min(frames, int(rate * SEG_TRIM_LOOK))
            handle.setpos(frames - look)
            raw = handle.readframes(look)
    except (OSError, wave.Error, ValueError, EOFError):
        return -1.0
    buf = array.array("h")
    buf.frombytes(raw[:len(raw) - (len(raw) % 2)])
    if chans > 1:
        buf = buf[::chans]
    if not buf:
        return -1.0
    step = max(1, int(rate * 0.02))
    floor = 32768.0 * (10 ** (SEG_TRIM_DB / 20.0))
    quiet, at = 0, len(buf)
    while at - step >= 0:
        window = buf[at - step:at]
        total = 0
        for sample in window:
            total += sample * sample
        if math.sqrt(total / len(window)) > floor:
            break
        quiet += step
        at -= step
    return quiet / float(rate)


# --------------------------------------------------------------------------
# the estimate this replaces
# --------------------------------------------------------------------------

def concat_real_seconds(measured: float, beat: float) -> float:
    """Mirror of `app.py:concat_real_seconds`."""
    return max(0.25, measured - CONCAT_TAIL + CONCAT_KEEP + max(0.0, beat))


def seg_real_seconds(measured: float, beat: float, tail: float) -> float:
    """Mirror of `app.py:seg_real_seconds` (#1205)."""
    if tail is None or tail < 0:
        return concat_real_seconds(measured, beat)
    return max(0.05, float(measured) - max(0.0, float(tail) - CONCAT_KEEP)
               + max(0.0, float(beat)))


def estimated_windows(paths: Sequence[str | Path], beats: Sequence[float],
                      total_seconds: float,
                      *, tails: Sequence[float] | None = None) -> list[dict]:
    """The stream path's own arithmetic, reproduced (`app.py:83945` onward).

    Each clip is measured as it sits on disk, `seg_real_seconds` guesses what
    the mixer's tail trim will take off it, the windows are summed - and then
    the whole span is rescaled by `made / ours` to fit the finished duration,
    because the sum never lands.

    This exists so shadow mode can subtract one road from the other. It is
    NOT a fallback and nothing here is ever admitted.
    """
    rows: list[dict] = []
    measured: list[float] = []
    read_tails: list[float] = []
    for index, path in enumerate(paths):
        try:
            facts = wav_facts(path)
            measured.append(float(facts["seconds"]))
        except (OSError, ValueError, wave.Error, EOFError):
            measured.append(0.0)
        if tails is not None:
            read_tails.append(float(tails[index]) if index < len(tails) else -1.0)
        else:
            read_tails.append(wav_tail_silence(path))
    offset = 0.0
    for index, secs in enumerate(measured):
        beat = float(beats[index]) if index < len(beats) else 0.0
        real = seg_real_seconds(secs, beat, read_tails[index])
        rows.append({"ordinal": index + 1, "from": offset, "until": offset + real,
                     "beat": beat, "disk_seconds": secs,
                     "tail_seconds": read_tails[index]})
        offset += real
    made = float(total_seconds) - ca.box_tail_ms() / 1000.0
    ours = offset
    scale = (made / ours) if (rows and ours > 0.5 and made > 0.5) else 1.0
    for row in rows:
        row["scale"] = scale
        row["from"] *= scale
        row["until"] *= scale
    return rows


def compare_windows(cue_map: Mapping[str, Any],
                    estimates: Sequence[Mapping[str, Any]]) -> dict:
    """What the two roads disagree about, per line, in seconds.

    Positive means the estimate is LATE - it puts the line further into the
    file than the measured cue map does.

    `head_delta_s` and `tail_delta_s` are the first and last line's
    disagreement kept apart on purpose. A rescale is a multiplication, so if
    the error it was absorbing were really a scale the two would have the
    same sign and grow together. A constant delay - the limiter's 5 ms attack
    lookahead is 120 samples at 24 kHz - shows up as one sign at the head and
    the other at the tail, and no tuning of the factor fixes that. This pair
    of numbers is the evidence either way.
    """
    cues = [c for c in (dict(cue_map).get("cues") or [])
            if isinstance(c, Mapping) and str(c.get("kind") or "line") == "line"]
    rows = list(estimates or [])
    out: dict[str, Any] = {"lines": 0, "mean_abs_s": 0.0, "max_abs_s": 0.0,
                           "head_delta_s": 0.0, "tail_delta_s": 0.0,
                           "scale": (float(rows[0].get("scale") or 1.0)
                                     if rows else 1.0),
                           "per_line": [], "paired_by": "ordinal",
                           "comparable": False}
    if not cues or not rows:
        out["why"] = ("nothing to compare: %d measured cue(s), %d estimated "
                      "window(s)" % (len(cues), len(rows)))
        return out
    if len(cues) != len(rows):
        # Two lists of the same shape wrongly paired is a silent fault
        # (#1330). Different lengths are not a pairing problem, they are a
        # refusal to compare at all.
        out["why"] = ("the roads describe different numbers of lines: %d "
                      "measured, %d estimated" % (len(cues), len(rows)))
        return out
    deltas: list[float] = []
    for index, (cue, row) in enumerate(zip(cues, rows)):
        start_cue = float(cue.get("start_seconds") or 0.0)
        start_est = float(row.get("from") or 0.0)
        delta = start_est - start_cue
        deltas.append(delta)
        out["per_line"].append({
            "ordinal": int(cue.get("ordinal") or index + 1),
            "occurrence_id": str(cue.get("occurrence_id") or ""),
            "measured_start_s": round(start_cue, 4),
            "estimated_start_s": round(start_est, 4),
            "delta_s": round(delta, 4),
            "measured_end_s": round(float(cue.get("cue_end_seconds") or 0.0), 4),
            "estimated_end_s": round(float(row.get("until") or 0.0), 4)})
    out["lines"] = len(deltas)
    out["comparable"] = True
    out["mean_abs_s"] = round(sum(abs(d) for d in deltas) / len(deltas), 4)
    out["max_abs_s"] = round(max(abs(d) for d in deltas), 4)
    out["head_delta_s"] = round(deltas[0], 4)
    out["tail_delta_s"] = round(deltas[-1], 4)
    out["same_sign"] = bool(deltas[0] * deltas[-1] > 0)
    return out


# --------------------------------------------------------------------------
# the result
# --------------------------------------------------------------------------

@dataclass
class Production:
    """What one production attempt produced, refused, and cost."""
    ok: bool = False
    mode: str = MODE_OFF
    road: str = ROAD_SEGMENTED
    conversation_id: str = ""
    revision: str = ""
    sessions: dict = field(default_factory=dict)
    masters: list = field(default_factory=list)
    cuts: list = field(default_factory=list)
    accepted_cuts: dict = field(default_factory=dict)
    assembly_id: str = ""
    assembly_record: dict = field(default_factory=dict)
    cue_map: dict = field(default_factory=dict)
    admission: dict = field(default_factory=dict)
    playback_occurrence_id: str = ""
    media: str = ""
    seconds: float = 0.0
    supply: dict = field(default_factory=dict)
    refusals: list = field(default_factory=list)
    disagreement: dict = field(default_factory=dict)
    cost_seconds: float = 0.0
    step_seconds: dict = field(default_factory=dict)
    aired: bool = False
    dropped: list = field(default_factory=list)
    at: float = 0.0

    @property
    def reasons(self) -> list[str]:
        return [str(r.get("reason") or r.get("code")) for r in self.refusals]

    @property
    def codes(self) -> list[str]:
        return [str(r.get("code")) for r in self.refusals]

    def refusal(self) -> str:
        return self.codes[0] if self.refusals else ""

    def ledger_row(self) -> dict:
        return {"at": self.at or time.time(), "schema": SCHEMA,
                "mode": self.mode, "road": self.road,
                "conversation_id": self.conversation_id,
                "revision": self.revision, "assembly_id": self.assembly_id,
                "playback_occurrence_id": self.playback_occurrence_id,
                "ok": bool(self.ok), "aired": bool(self.aired),
                "lines": len(self.cuts),
                "sessions": sorted(self.sessions),
                "seconds": round(float(self.seconds), 3),
                "cost_seconds": round(float(self.cost_seconds), 3),
                "step_seconds": {k: round(float(v), 3)
                                 for k, v in dict(self.step_seconds).items()},
                "refusal": self.refusal(),
                "refusal_codes": self.codes,
                "refusal_reasons": self.reasons[:6],
                "dropped": list(self.dropped)[:12],
                "disagreement": dict(self.disagreement)}

    def references(self) -> dict:
        return references(self)


def references(result: "Production | None", *, mode: str = "",
               extra: Mapping[str, Any] | None = None) -> dict:
    """The incident reference set, per section 5 of the note.

        "Extend the existing incident capture with references to the relevant
         script revision, performer session, accepted cut, assembly and
         playback occurrence... An unavailable reference must be reported
         explicitly."

    Every field is present. A reference this producer does not have is `None`
    with `available: false` and a sentence saying why - never filled in with
    something plausible.
    """
    out: dict[str, Any] = {"schema": SCHEMA, "available": False,
                           "mode": str(mode or MODE_OFF),
                           "road": None, "script_revision": None,
                           "conversation_id": None, "performer_sessions": None,
                           "accepted_cuts": None, "assembly_id": None,
                           "cue_map_revision": None, "final_audio_hash": None,
                           "playback_occurrence_id": None, "media": None,
                           "refusal": None, "why": ""}
    if result is None:
        out["why"] = ("no production has run for this material; the script "
                      "production switch is off or this road did not produce it")
        out.update(dict(extra or {}))
        return out
    out["mode"] = str(mode or result.mode)
    out["road"] = result.road
    out["available"] = True
    out["conversation_id"] = result.conversation_id or None
    out["script_revision"] = result.revision or None
    out["performer_sessions"] = sorted(result.sessions) or None
    out["accepted_cuts"] = (dict(result.accepted_cuts) or None)
    out["assembly_id"] = result.assembly_id or None
    out["cue_map_revision"] = (result.assembly_record.get("cue_map_revision")
                               or result.cue_map.get("cue_map_revision") or None)
    out["final_audio_hash"] = (result.cue_map.get("final_audio_hash")
                               or result.assembly_record.get("final_sha256") or None)
    out["playback_occurrence_id"] = result.playback_occurrence_id or None
    out["media"] = result.media or None
    out["refusal"] = result.refusal() or None
    if not result.ok:
        out["why"] = ("production refused: "
                      + "; ".join(result.reasons[:3] or ["no reason recorded"]))
    elif not result.aired:
        out["why"] = ("produced and verified, then discarded - this round "
                      "aired on the existing road (shadow)")
    out.update(dict(extra or {}))
    return out


# --------------------------------------------------------------------------
# the producer
# --------------------------------------------------------------------------

class ScriptProducer:
    """The six steps, in order, with a refusal at every boundary.

    BLOCKING. It reads audio and runs ffmpeg. A caller on an event loop must
    run `produce` in a thread, or the station stops talking while it works.
    """

    def __init__(self, data_root: str | Path, media_root: str | Path, *,
                 store: Any = None, switch: ProductionSwitch | None = None,
                 ledger: ProductionLedger | None = None,
                 align: Callable[..., Mapping[str, Any]] | None = None,
                 clock: Callable[[], float] = time.time,
                 note: Callable[[str, str], None] | None = None):
        self.data_root = Path(data_root)
        self.root = self.data_root / "script_production"
        self.media_root = Path(media_root)
        self.store = store if store is not None else \
            ms.ManifestStore(self.data_root / "manifests")
        self.switch = switch or ProductionSwitch(self.root, clock=clock)
        self.ledger = ledger or ProductionLedger(self.root)
        self.align = align
        self.clock = clock
        self.note = note or (lambda where, what: None)
        self._last_at = 0.0
        self._busy = False

    # -- gates ------------------------------------------------------------

    def settings(self) -> Settings:
        return self.switch.settings()

    def due(self, settings: Settings | None = None) -> bool:
        """Is another production allowed yet? Cheap; call it before building
        a source, because building one reads the pantry."""
        got = settings or self.settings()
        if got.off:
            return False
        if self._busy:
            return False
        return (self.clock() - self._last_at) >= got.every_s

    # -- the whole road ---------------------------------------------------

    def produce(self, source: RoundSource, *,
                settings: Settings | None = None,
                beats: Sequence[float] | None = None,
                compare: bool = True,
                keep_audio: bool | None = None,
                start_position: int = 1) -> Production:
        """Freeze, record, cut, assemble, verify, admit - or refuse by name."""
        got = settings or self.settings()
        started = self.clock()
        out = Production(mode=got.mode, road=got.road, at=started,
                         conversation_id=source.conversation_id)
        if got.off:
            out.refusals.append(refuse("production_off"))
            return out
        if self._busy:
            out.refusals.append(refuse("production_busy"))
            return out
        if len(source.lines) > got.max_lines:
            out.refusals.append(refuse(
                "round_too_long",
                "this round has %d lines and the switch allows %d"
                % (len(source.lines), got.max_lines),
                lines=len(source.lines), allowed=got.max_lines))
            self.ledger.record(out.ledger_row())
            return out
        self._busy = True
        try:
            self._produce(source, got, out, beats=beats, compare=compare,
                          keep_audio=(got.airs if keep_audio is None
                                      else bool(keep_audio)),
                          start_position=start_position)
        except Exception as exc:  # noqa: BLE001
            out.ok = False
            out.refusals.append(refuse(
                "production_error", "production raised %s: %s"
                % (type(exc).__name__, exc)))
        finally:
            self._busy = False
            self._last_at = self.clock()
            out.cost_seconds = self._last_at - started
            if out.cost_seconds > got.budget_s and out.ok:
                # Recorded, not undone: the work is done and the artifact is
                # good. What the budget buys is the NEXT round's refusal, so
                # a road that is too slow for this station says so in the
                # ledger instead of quietly eating the engine.
                out.refusals.append(refuse(
                    "budget_exceeded",
                    "production took %.1fs against a %.1fs budget"
                    % (out.cost_seconds, got.budget_s),
                    seconds=round(out.cost_seconds, 2), budget=got.budget_s))
            self.ledger.record(out.ledger_row())
        return out

    # -- the steps --------------------------------------------------------

    def _produce(self, source: RoundSource, settings: Settings,
                 out: Production, *, beats: Sequence[float] | None,
                 compare: bool, keep_audio: bool, start_position: int) -> None:
        mark = self.clock()

        # 1 -------------------------------------------------- freeze
        script = self.freeze(source, out)
        if script is None:
            return
        out.step_seconds["freeze"] = self.clock() - mark
        mark = self.clock()

        # 2 --------------------------------- sessions, masters and cuts
        masters, cuts = self.record_session(source, script, out,
                                            road=settings.road)
        if out.refusals:
            # "A failed cut requires a retake or another complete ready
            # candidate before commitment." Nothing part-recorded goes on.
            return
        out.step_seconds["record"] = self.clock() - mark
        mark = self.clock()

        # 3 ------------------------------------------------ assemble
        made = self.assemble(script, masters, cuts, out, beats=beats)
        if made is None:
            return
        out.step_seconds["assemble"] = self.clock() - mark
        mark = self.clock()
        try:
            out.supply = measured_round_supply(source, made.cue_map)
            # 4 ------------------------------------- record and admit
            record = self.finish(script, made, out)
            if record is None:
                return
            if compare:
                out.disagreement = self.measure_disagreement(
                    source, made,
                    beats=(made.record.get("mix") or {}).get("beats"))
            out.step_seconds["verify"] = self.clock() - mark
            mark = self.clock()
            if keep_audio:
                out.media = self.keep(made)
                out.aired = True
            admission = self.admit(record, out, start_position=start_position)
            if admission is None:
                return
            out.step_seconds["admit"] = self.clock() - mark
            out.ok = True
        finally:
            made.close()

    # -- 1. freeze the performance contract --------------------------------

    def freeze(self, source: RoundSource, out: Production) -> dict | None:
        """Revision, ordered occurrence ids, exact spoken text, cast,
        pronunciations and performance instructions - before recording.

        A script change makes a new revision by construction: the revision is
        derived from the content, so an edited round cannot reuse the old
        one's audio without saying so.
        """
        if not source.lines:
            out.refusals.append(refuse("no_lines"))
            return None
        if not source.cast:
            out.refusals.append(refuse("no_cast"))
            return None
        lines = [{"actor": line.actor, "text": line.text,
                  "pronunciations": list(line.pronunciations or ()),
                  "instructions": line.instructions or "",
                  "context_before": getattr(line, "context_before", ""),
                  "context_after": getattr(line, "context_after", ""),
                  # The relationship between a displayed line and the render
                  # chunks it became, kept where the performance digest can
                  # see it: change the chunking and the contract changes.
                  "chunks": ["turn:%d" % line.turn, "chunk:%d" % line.chunk,
                             "cache:%s" % line.cache_key]}
                 for line in source.lines]
        try:
            script = sm.frozen_script(source.conversation_id, source.cast, lines,
                                      notes=source.notes or source.label)
        except sm.ManifestError as exc:
            out.refusals.append(refuse("script_refused", str(exc)))
            return None
        # A resumed sitting rebuilds the same content-addressed revision.
        # `created_at` is deliberately outside that digest, so generating a
        # fresh timestamp made an otherwise identical, already-admitted
        # script look like an attempt to mutate pinned broadcast history.
        # Keep the original provenance stamp; the store will still reject
        # any other difference under this immutable revision.
        existing = self.store.load_script(str(script["revision"]))
        if existing is not None and existing.get("created_at") is not None:
            script["created_at"] = existing["created_at"]
        stored = self.store.put_script(script)
        if not stored.get("ok"):
            out.refusals.append(refuse(
                "script_refused",
                "; ".join(stored.get("reasons") or ["the store gave no reason"]),
                codes=[r.get("code") for r in (stored.get("refusals") or [])]))
            return None
        out.revision = str(script["revision"])
        return script

    # -- 2. own and persist performer sessions -----------------------------

    def record_session(self, source: RoundSource, script: Mapping,
                       out: Production, *, road: str = ROAD_SEGMENTED
                       ) -> tuple[list[dict], list[dict]]:
        """One session per performer, one master per take, one cut per line.

        The identity is deterministic - `(revision, actor)` - so an
        interrupted sitting resumes into the SAME session rather than opening
        a second one beside it. Recovery is `manifest_store.resume_session`,
        which keeps only the takes that still verify against this revision
        and this master, and returns everything else as dropped work with a
        reason.
        """
        revision = str(script["revision"])
        by_actor: dict[str, list[tuple[int, RoundLine, dict]]] = {}
        for index, line in enumerate(source.lines):
            entry = dict(script["lines"][index])
            by_actor.setdefault(line.actor, []).append((index + 1, line, entry))
        masters: list[dict] = []
        cuts: list[dict] = []
        pins = self.store.pins(revision) or {}
        for actor, rows in by_actor.items():
            session_id = self.session_id(revision, actor)
            resumed = self.store.resume_session(session_id, revision,
                                                commit=False)
            already: dict[str, str] = {}
            if resumed.get("ok"):
                already = dict((resumed.get("session") or {}).get("accepted") or {})
                for dropped in (resumed.get("dropped") or []):
                    out.dropped.append(dropped if isinstance(dropped, str)
                                       else json.dumps(dropped, default=str)[:200])
            live = self.live_session(script, actor, rows, road=road)
            pairs = (self.continuous_part(source, script, actor, rows,
                                          session_id=session_id, out=out)
                     if road == ROAD_CONTINUOUS
                     else self.segmented_part(script, actor, rows,
                                              session_id=session_id, out=out))
            accepted: dict[str, str] = {}
            for master, cut, entry in pairs:
                occurrence = str(entry["occurrence_id"])
                take_id = str(master["take_id"])
                guard = sm.check_overwrite(
                    "master", take_id,
                    self.store.load("master", revision, take_id), master, pins)
                if not guard["ok"]:
                    # "Before replacing any recorded work, take store.pins()
                    # and call check_overwrite... a producer that builds
                    # candidates should check before it spends the time."
                    out.refusals.append(refuse(
                        "pinned_take_overwrite", str(guard.get("reason") or ""),
                        occurrence_id=occurrence, take_id=take_id))
                    continue
                kept = self.store.put_master(master)
                if not kept.get("ok"):
                    out.refusals.append(refuse(
                        "master_refused",
                        "; ".join(kept.get("reasons") or ["no reason"]),
                        take_id=take_id, occurrence_id=occurrence,
                        codes=[r.get("code") for r in (kept.get("refusals") or [])]))
                    continue
                if not any(m["take_id"] == take_id for m in masters):
                    masters.append(master)
                stored = self.store.put_cut(cut)
                if not stored.get("ok") or cut.get("state") != "accepted":
                    out.refusals.append(refuse(
                        "cut_refused",
                        "; ".join(stored.get("reasons")
                                  or ["the cut was not accepted"]),
                        cut_id=str(cut["cut_id"]),
                        ordinal=int(entry["ordinal"]),
                        occurrence_id=occurrence,
                        codes=[r.get("code") for r in (stored.get("refusals") or [])]))
                    continue
                cuts.append(cut)
                accepted[occurrence] = str(cut["cut_id"])
                live.accept(self.accepted_take(cut, master, live, entry))
            merged = dict(already)
            merged.update(accepted)
            # `script_manifest.SESSION_STATES` is ("open", "recording",
            # "interrupted", "complete", "abandoned"). `speaker_session` has
            # a sixth, "blocked", and the two vocabularies are NOT the same
            # one. The durable record is script_manifest's, so it uses
            # script_manifest's words: an incomplete sitting is "recording",
            # which is what `manifest_store.resume_session` writes too.
            session = sm.performer_session(
                session_id, script, actor, accepted=merged,
                state=("complete" if len(merged) == len(rows)
                       else "recording"))
            kept = self.store.put_session(session)
            if not kept.get("ok"):
                out.refusals.append(refuse(
                    "session_refused",
                    "; ".join(kept.get("reasons") or ["no reason"]),
                    session_id=session_id, actor=actor,
                    codes=[r.get("code") for r in (kept.get("refusals") or [])]))
                continue
            ready = live.readiness()
            if not ready:
                out.refusals.append(refuse(
                    "session_incomplete",
                    "%s's session is not ready: %s"
                    % (actor, "; ".join(list(ready.reasons)[:3]) or "no reason"),
                    session_id=session_id, actor=actor,
                    state=live.state))
            out.sessions[actor] = {"session_id": session_id,
                                   "state": str(session.get("state")),
                                   "accepted": len(merged),
                                   "assigned": len(rows),
                                   "ready": bool(ready)}
        out.masters = masters
        out.cuts = cuts
        out.accepted_cuts = {str(c["occurrence_id"]): str(c["cut_id"]) for c in cuts}
        return masters, cuts

    def live_session(self, script: Mapping, actor: str,
                     rows: Sequence[tuple[int, RoundLine, Mapping]],
                     *, road: str) -> ss.PerformerSession:
        """`speaker_session.PerformerSession` as the in-flight readiness judge.

        The DURABLE session record is `script_manifest.performer_session`
        through `manifest_store`, because `manifest_store.resume_session` is
        the recovery road and it validates that shape. This object is the
        thing that answers "is this performer's part complete, and if not,
        why not" with reasons rather than a bare boolean, and it carries the
        segmented/continuous mode identity into the judgement.
        """
        cast = dict(script.get("cast") or {}).get(actor) or {}
        config = dict(cast.get("config") or {})
        renderer = ss.RendererConfig(
            engine=str(cast.get("engine") or ""),
            voice=str(cast.get("voice") or ""),
            mode=road,
            sample_rate=int(config.get("sample_rate") or 24000),
            max_request_chars=int(config.get("max_request_chars") or 800),
            notes=str(config.get("notes") or ""))
        assignments = tuple(
            ss.Assignment(occurrence_id=str(entry["occurrence_id"]),
                          ordinal=int(ordinal), speaker=actor,
                          text=str(line.text),
                          conversation_id=str(script.get("conversation_id") or ""))
            for ordinal, line, entry in rows)
        return ss.new_session(str(script["revision"]), actor, renderer,
                              assignments,
                              session_id=self.session_id(str(script["revision"]),
                                                         actor))

    def accepted_take(self, cut: Mapping, master: Mapping,
                      session: ss.PerformerSession,
                      entry: Mapping) -> ss.AcceptedTake:
        return ss.AcceptedTake(
            occurrence_id=str(cut["occurrence_id"]),
            ordinal=int(cut["ordinal"]),
            take_id=str(cut["take_id"]),
            master_hash=str(master["audio_sha256"]),
            sample_rate=int(master["sample_rate"]),
            start_sample=int(cut["start_sample"]),
            end_sample=int(cut["end_sample"]),
            boundary_method=str(cut["boundary_method"]),
            verification=dict(cut.get("verification") or {}),
            mode=session.renderer.mode,
            revision=str(master["revision"]),
            renderer_fingerprint=session.renderer.fingerprint,
            media_ref=str(master["media_ref"]))

    # -- 3. save exact cut manifests ---------------------------------------

    def segmented_part(self, script: Mapping, actor: str,
                       rows: Sequence[tuple[int, RoundLine, Mapping]],
                       *, session_id: str, out: Production
                       ) -> list[tuple[dict, dict, Mapping]]:
        """THE ROAD THIS STATION ACTUALLY TAKES, and the honest name for it.

        One engine call per scripted line, regrouped by performer. Each call
        produced one file and the renderer was asked for exactly one line, so
        the file's own edges ARE that line's edges - a boundary RETAINED FROM
        SYNTHESIS, not recovered from the audio afterwards. That is
        `renderer_boundary`; the master's mode is `segmented`; and no surface
        anywhere calls this a continuous performance.

        The bench settles why this is the shipped road rather than a stopgap
        (`docs/notes/continuous-take-bench-2026-09-15.md`): on an uncontended
        box the continuous take was 21% SLOWER - 128.6 s of wall clock for
        220.9 s of audio against 106.7 s for 213.7 s - with an identical
        read-back character error rate, 0.034 median on both roads, and zero
        retries on either. "Larger requests are faster" would have been
        false, which is exactly why the note forbade claiming it unmeasured.

        The pad on the end is deliberately INSIDE the cut. `BOX_TAIL_MS` is
        glued onto every rendered take so the box loops silence rather than
        the last syllable, and the mixer's own per-input leg trims it back to
        `CONCAT_KEEP` on the way in. Trimming it here as well would take the
        audio somewhere this station's mixer has never taken it - a different
        sound, not a tidier one.
        """
        revision = str(script["revision"])
        out_rows: list[tuple[dict, dict, Mapping]] = []
        for ordinal, line, entry in rows:
            occurrence = str(entry["occurrence_id"])
            take_id = self.take_id(revision, occurrence)
            try:
                facts = wav_facts(line.media)
            except (OSError, ValueError, wave.Error, EOFError) as exc:
                out.refusals.append(refuse(
                    "media_unreadable",
                    "line %d (%s) could not be read as a master: %s"
                    % (ordinal, actor, exc),
                    ordinal=ordinal, actor=actor, media=line.media))
                continue
            master = sm.master_recording(
                take_id, session_id=session_id, revision=revision,
                actor=actor, audio_sha256=facts["sha256"],
                sample_rate=facts["sample_rate"],
                frame_count=facts["frame_count"],
                channels=facts["channels"], media_ref=str(line.media),
                # EXPLICIT, AND NEVER INFERRED.
                mode="segmented")
            out_rows.append((master, self.renderer_cut(entry, master), entry))
        return out_rows

    def continuous_part(self, source: RoundSource, script: Mapping, actor: str,
                        rows: Sequence[tuple[int, RoundLine, Mapping]],
                        *, session_id: str, out: Production
                        ) -> list[tuple[dict, dict, Mapping]]:
        """THE SECOND CAPABILITY, WITH ITS OWN IDENTITY, AND IT IS OFF.

        One whole performance per performer, cut by aligning a recogniser's
        word sequence against the frozen script. It needs three things this
        station does not have by default, and it refuses by name for each
        rather than degrading into the segmented road under another label:

          * A MASTER. Nothing in this module renders. `source.parts[actor]`
            must carry one whole performance of that actor's part, made by
            somebody who meant to make one.
          * A PART THE ENGINE COULD ACTUALLY HAVE PERFORMED WHOLE. The XTTS
            clone server is `_synthesize(text[:1000], ...)` - it truncates
            INSIDE the server, returns HTTP 200 and clean audio, and three
            measured rounds lost 34% to 40% of their words with no error
            raised anywhere. A part longer than that ceiling cannot be a
            whole performance of itself, so it is refused here instead of
            being trusted. The F5 road slides past about 280 characters for
            the same practical reason.
          * A RECOGNISER. `align=` supplies it, and word timing is EVIDENCE,
            never proof: `line_alignment` refuses missing, repeated and
            mismatched speech, and a refusal from it is a refusal here. The
            bench found three of six refusals were the recogniser's fault
            rather than the matcher's (the lab was on `WHISPER_MODEL=base`),
            which is another reason the shipped road does not depend on it.
        """
        revision = str(script["revision"])
        media = str(dict(source.parts or {}).get(actor) or "")
        if not media:
            out.refusals.append(refuse(
                "continuous_master_missing",
                "%s has no whole performance to cut; this road does not "
                "render one, and it will not pass a pile of per-line renders "
                "off as a continuous take" % actor, actor=actor))
            return []
        cast = dict(script.get("cast") or {}).get(actor) or {}
        engine = str(cast.get("engine") or "")
        cap = int(ENGINE_REQUEST_CAPS.get(engine, DEFAULT_REQUEST_CAP))
        chars = sum(len(str(entry["text"])) for _o, _l, entry in rows)
        if chars > cap:
            out.refusals.append(refuse(
                "request_cap_exceeded",
                "%s's part is %d characters and %s performs at most %d in one "
                "request, silently: a master of this part cannot be a whole "
                "performance of it"
                % (actor, chars, engine or "this engine", cap),
                actor=actor, chars=chars, cap=cap, engine=engine))
            return []
        if self.align is None:
            out.refusals.append(refuse(
                "alignment_unavailable",
                "the continuous-take road needs a word-level recogniser and "
                "none was supplied; it does not fall back to the segmented "
                "road under another name", actor=actor))
            return []
        try:
            facts = wav_facts(media)
        except (OSError, ValueError, wave.Error, EOFError) as exc:
            out.refusals.append(refuse(
                "media_unreadable",
                "%s's master could not be read: %s" % (actor, exc),
                actor=actor, media=media))
            return []
        take_id = self.take_id(revision, "part:" + actor)
        master = sm.master_recording(
            take_id, session_id=session_id, revision=revision, actor=actor,
            audio_sha256=facts["sha256"], sample_rate=facts["sample_rate"],
            frame_count=facts["frame_count"], channels=facts["channels"],
            media_ref=str(media), mode="continuous")
        lines = [la.ScriptLine(occurrence_id=str(entry["occurrence_id"]),
                               ordinal=int(entry["ordinal"]),
                               speaker=str(entry["actor"]),
                               text=str(entry["text"]))
                 for _o, _l, entry in rows]
        try:
            heard = self.align(media=str(media),
                               script=[{"occurrence_id": line.occurrence_id,
                                        "ordinal": line.ordinal,
                                        "actor": line.speaker,
                                        "text": line.text} for line in lines],
                               sample_rate=int(facts["sample_rate"]),
                               frame_count=int(facts["frame_count"]))
        except Exception as exc:  # noqa: BLE001
            out.refusals.append(refuse(
                "alignment_unavailable",
                "the recogniser could not be reached: %s: %s"
                % (type(exc).__name__, exc), actor=actor))
            return []
        result = la.align_script(
            lines, la.from_whisper_words((heard or {}).get("words") or []),
            sample_rate=int(facts["sample_rate"]),
            master_frames=int(facts["frame_count"]),
            mode=ROAD_CONTINUOUS, master_hash=str(facts["sha256"]),
            actor=actor)
        for bad in (result.refusals or []):
            out.refusals.append(refuse(
                "alignment_refused", str(bad), actor=actor,
                code=str(getattr(bad, "code", "") or ""),
                occurrence_id=str(getattr(bad, "occurrence_id", "") or "")))
        by_occurrence = {str(entry["occurrence_id"]): entry
                         for _o, _l, entry in rows}
        spoken = la.from_whisper_words((heard or {}).get("words") or [])
        out_rows: list[tuple[dict, dict, Mapping]] = []
        for got in (result.cuts or []):
            entry = by_occurrence.get(str(got.occurrence_id))
            if entry is None:
                continue
            # THE EVIDENCE FOR THIS CUT IS WHAT WAS HEARD INSIDE THIS CUT.
            # Handing the whole master's transcript to every line would read
            # as repeated speech the moment a round says the same thing
            # twice - and this station's rounds do - refusing a perfectly
            # good cut for a fault that belongs to the evidence, not the
            # audio.
            transcript = words_between(spoken, got.start_sample,
                                       got.end_sample,
                                       int(facts["sample_rate"]))
            out_rows.append((master, sm.line_cut(
                self.cut_id(revision, str(got.occurrence_id)),
                occurrence_id=str(got.occurrence_id),
                ordinal=int(entry["ordinal"]), take_id=take_id,
                master_sha256=str(facts["sha256"]),
                sample_rate=int(facts["sample_rate"]),
                start_sample=int(got.start_sample),
                end_sample=int(got.end_sample),
                boundary_method=BOUNDARY_ALIGNMENT,
                verification=dict(
                    dict(got.verification or {}),
                    actor=str(entry["actor"]), ambiguous=False,
                    verdict="verified", synthesis=ROAD_CONTINUOUS,
                    transcript=transcript,
                    # `line_alignment` spells its own boundary as a "+"-joined
                    # list of the methods that placed each edge. That is
                    # evidence about HOW, and it is kept; the manifest's
                    # `boundary_method` vocabulary is the three words
                    # script_manifest accepts, and this is `alignment`.
                    aligner_boundary=str(got.boundary_method or ""),
                    notes="aligned against the frozen script"),
                state="accepted"), entry))
        return out_rows

    def renderer_cut(self, entry: Mapping, master: Mapping) -> dict:
        """One line's exact span inside its own master: the whole of it."""
        occurrence = str(entry["occurrence_id"])
        cut_id = self.cut_id(str(master["revision"]), occurrence)
        return sm.line_cut(
            cut_id, occurrence_id=occurrence, ordinal=int(entry["ordinal"]),
            take_id=str(master["take_id"]),
            master_sha256=str(master["audio_sha256"]),
            sample_rate=int(master["sample_rate"]),
            start_sample=0, end_sample=int(master["frame_count"]),
            boundary_method=BOUNDARY_RENDERER,
            verification={"actor": str(entry["actor"]),
                          "ambiguous": False,
                          "verdict": "verified",
                          "synthesis": ROAD_SEGMENTED,
                          "notes": ("the renderer was asked for exactly this "
                                    "line and returned exactly this file; the "
                                    "boundary is the file's own edges, "
                                    "retained from synthesis, and no silence "
                                    "threshold was consulted")},
            state="accepted")

    # -- 4. assemble and validate before admitting -------------------------

    def assemble(self, script: Mapping, masters: Sequence[Mapping],
                 cuts: Sequence[Mapping], out: Production,
                 *, beats: Sequence[float] | None = None) -> Any:
        """Original script order, a measured cue map, verified before it is
        advertised. Anything that cannot be proved raises, and a refusal here
        means "retake, or choose another complete ready candidate" - never
        "retry the same inputs"."""
        try:
            made = ca.assemble_conversation(
                script, masters, cuts, beats=beats,
                media_root=self.media_root,
                assembly_id=self.assembly_id(str(script["revision"])))
        except ca.AssemblyRefused as refused:
            out.refusals.append(refuse(
                "assembly_refused", str(refused.reason) + ": " + str(refused),
                code=str(refused.reason),
                facts={k: v for k, v in (getattr(refused, "facts", {}) or {}).items()
                       if isinstance(v, (str, int, float, bool))}))
            return None
        except Exception as exc:  # noqa: BLE001
            out.refusals.append(refuse(
                "assembly_refused", "%s: %s" % (type(exc).__name__, exc)))
            return None
        verdict = dict(made.cue_map.get("verified") or {})
        if verdict and verdict.get("ok") is False:
            out.refusals.append(refuse(
                "assembly_unverified",
                "; ".join(str(r) for r in (verdict.get("reasons") or []))[:400]))
            made.close()
            return None
        out.assembly_id = str(made.assembly_id)
        out.cue_map = dict(made.cue_map)
        out.seconds = float(made.seconds)
        frozen = list(script.get("sequence") or [])
        spoken = [str(c.get("occurrence_id"))
                  for c in (made.cue_map.get("cues") or [])
                  if str(c.get("kind") or "line") == "line"]
        if spoken != frozen:
            out.refusals.append(refuse(
                "sequence_mismatch",
                "the finished audio speaks %d line(s) and the frozen script "
                "has %d, or they are in a different order"
                % (len(spoken), len(frozen))))
            made.close()
            return None
        return made

    def finish(self, script: Mapping, made: Any, out: Production) -> dict | None:
        """The "Finished conversation" row of the note's table, stored."""
        try:
            record = sm.finished_conversation(
                **ca.finished_conversation_kwargs(made))
        except (sm.ManifestError, ValueError, TypeError) as exc:
            out.refusals.append(refuse("assembly_record_refused", str(exc)))
            return None
        kept = self.store.put_assembly(record)
        if not kept.get("ok"):
            out.refusals.append(refuse(
                "assembly_record_refused",
                "; ".join(kept.get("reasons") or ["no reason"]),
                codes=[r.get("code") for r in (kept.get("refusals") or [])]))
            return None
        out.assembly_record = dict(record)
        return record

    def admit(self, record: Mapping, out: Production, *,
              start_position: int = 1) -> dict | None:
        """Atomic commitment: occurrence id, ordered positions, exact audio
        identity and cue map revision, together. This is the manifest half of
        admission; the deployed `broadcast_admission` controller is the other
        half and is handed the same cue map at the transport."""
        try:
            admission = sm.broadcast_admission(
                self.admission_id(str(record["assembly_id"])),
                assembly=record, start_position=int(start_position))
        except (sm.ManifestError, ValueError, TypeError) as exc:
            out.refusals.append(refuse("admission_refused", str(exc)))
            return None
        kept = self.store.put_admission(admission)
        if not kept.get("ok"):
            out.refusals.append(refuse(
                "admission_refused",
                "; ".join(kept.get("reasons") or ["no reason"]),
                codes=[r.get("code") for r in (kept.get("refusals") or [])]))
            return None
        out.admission = dict(admission)
        out.playback_occurrence_id = str(admission["playback_occurrence_id"])
        return admission

    # -- keeping, or not keeping, the audio --------------------------------

    def keep(self, made: Any) -> str:
        """Write the finished conversation where the station's media lives.

        Content-addressed the way every other clip on this station is - the
        first 32 hex of its own audio hash - so the same conversation
        assembled twice is one file, and `MEDIA_KEY_SHAPE` recognises it.

        Called only when the switch says `on`. In `shadow` the artifact is
        measured and then dropped on the floor, which is the whole point:
        the new road is proved on a live station without one second of air
        depending on it.
        """
        digest = str(made.cue_map.get("final_audio_hash") or "")
        name = (digest[:32] if len(digest) >= 32 else uuid.uuid4().hex) + ".wav"
        self.media_root.mkdir(parents=True, exist_ok=True)
        target = self.media_root / name
        if not target.is_file():
            made.write_audio(target)
        return str(target)

    # -- the shadow measurement --------------------------------------------

    def measure_disagreement(self, source: RoundSource, made: Any,
                             *, beats: Sequence[float] | None = None) -> dict:
        """The assembled cue positions against the rescaled estimates."""
        try:
            paths = [line.media for line in source.lines]
            rows = estimated_windows(paths, list(beats or []), float(made.seconds))
            got = compare_windows(made.cue_map, rows)
            got["mix_latency_frames"] = int(made.cue_map.get("mix_latency_frames") or 0)
            got["mix_residual_frames"] = int(made.cue_map.get("mix_residual_frames") or 0)
            got["latency_measured"] = bool(made.cue_map.get("latency_measured"))
            return got
        except Exception as exc:  # noqa: BLE001
            return {"lines": 0, "comparable": False,
                    "why": "the comparison raised %s: %s"
                           % (type(exc).__name__, exc)}

    # -- identities ---------------------------------------------------------
    # All deterministic. An interrupted sitting resumes into the same session
    # and re-derives the same take and cut ids, so a retry is a retry and not
    # a second pile of records beside the first.

    @staticmethod
    def _short(prefix: str, *parts: Any, size: int = 20) -> str:
        blob = "\x00".join(str(p) for p in parts).encode("utf-8")
        return prefix + hashlib.sha256(blob).hexdigest()[:size]

    def session_id(self, revision: str, actor: str) -> str:
        return self._short("ses-", "session", revision, actor)

    def take_id(self, revision: str, occurrence_id: str) -> str:
        return self._short("take-", "take", revision, occurrence_id)

    def cut_id(self, revision: str, occurrence_id: str) -> str:
        return self._short("cut-", "cut", revision, occurrence_id)

    def assembly_id(self, revision: str) -> str:
        return self._short("asm-", "assembly", revision)

    def admission_id(self, assembly_id: str) -> str:
        # NOT derived from the assembly alone: the same assembly aired twice
        # is two admissions with two playback occurrences, which is the
        # audit's reusable-sample rule.
        return "adm-" + uuid.uuid4().hex[:20]

    # -- what the round carries forward ------------------------------------

    def round_payload(self, result: Production) -> dict:
        """What the orchestrator writes onto the round entry.

        In `on` this is what the air road reads: `cue_map` is the measured
        timeline and `production` is the reference set the admission gate and
        the incident capture pick up. In `shadow` the cue map is deliberately
        absent - the round airs exactly as it would have.
        """
        payload: dict[str, Any] = {"production": references(result,
                                                            mode=result.mode)}
        payload["production"]["cost_seconds"] = round(result.cost_seconds, 2)
        # THE SUMMARY, NOT THE ROWS. The round entry is deep-copied onto
        # the page feed as `ready_round`, and that payload is polled; the
        # per-line comparison is twenty rows of six numbers and it belongs in
        # the ledger, where the report reads it, not on every poll.
        payload["production"]["disagreement"] = {
            k: v for k, v in dict(result.disagreement).items()
            if k != "per_line"}
        if result.ok and result.supply:
            payload["production"]["supply"] = dict(result.supply)
        if result.aired and result.cue_map:
            cue_map = dict(result.cue_map)
            # THE BEATS TRAVEL WITH THE MAP. `conversation_assembly` keeps
            # the drawn seam beats on its `record`, not on its cue map, and
            # the air road has to re-mix this round with the SAME beats or
            # the file it builds is not the file that was measured (#778's
            # rule one step earlier). Merged here, at the one place the map
            # is handed over, so a reader has the whole contract in one
            # object rather than two.
            cue_map["mix"] = dict(result.assembly_record.get("mix")
                                  or result.cue_map.get("mix") or {})
            payload["cue_map"] = cue_map
        return payload

    def occurrence_map(self, source: RoundSource, result: Production) -> list[dict]:
        """Ordinal -> the identities that line carries, for the takes on the
        round entry. Matched by ORDINAL against the frozen script this very
        producer just minted from the same list, never by text."""
        out: list[dict] = []
        cues = {int(c.get("ordinal") or -1): c
                for c in (result.cue_map.get("cues") or [])
                if str(c.get("kind") or "line") == "line"}
        for index, line in enumerate(source.lines):
            cue = cues.get(index + 1) or {}
            occurrence = str(cue.get("occurrence_id") or "")
            out.append({
                "ordinal": index + 1,
                "occurrence_id": occurrence,
                "cut_id": str(cue.get("cut_id")
                              or result.accepted_cuts.get(occurrence) or ""),
                "take_id": str((cue.get("source") or {}).get("take_id") or ""),
                "actor": line.actor})
        return out


# --------------------------------------------------------------------------
# a read-only view, for the diagnostics route and the incident capture
# --------------------------------------------------------------------------

def state(data_root: str | Path, *, limit: int = 12) -> dict:
    """What the producer is doing, without running it."""
    root = Path(data_root) / "script_production"
    switch = ProductionSwitch(root)
    ledger = ProductionLedger(root)
    settings = switch.settings()
    report = ledger.report()
    return {"schema": SCHEMA, "available": True,
            "switch": settings.as_dict(),
            "mode": settings.mode, "road": settings.road,
            "report": report,
            "recent": ledger.rows(limit)[-limit:],
            "refusal_vocabulary": sorted(REFUSALS),
            "roads": {ROAD_SEGMENTED: "one engine call per scripted line, the "
                                      "boundary retained from synthesis "
                                      "(renderer_boundary)",
                      ROAD_CONTINUOUS: "one performance per performer, cut by "
                                       "alignment against the frozen script "
                                       "(alignment); off by default"}}
