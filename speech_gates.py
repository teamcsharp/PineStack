"""[speech-gates] Every gate that refuses the station's speech, in one place the
operator edits.

"what station speech gate? where is the panel for that? i need to be able to
edit any gate for speech by the station" (the operator, 2026-10-01).

The editorial gates (profile, repetition, language, line quality and the rest)
were already switchable - /api/orchestrator/content-gates, master off by
default. What was not: the thresholds written into the code that refuse a line
whatever those switches say - nothing twice inside a day, the rerun check's
overlap, the advert copy check, System 3's copy gate, the hourly video's
whole-sentence rules, call novelty, the re-air copy ratio, the English check.
They are listed here with their road, what they refuse, their default and a
safe range; the operator's values are kept in data/speech_gates.json and set
on the running station (apply), so a change takes effect on the next line and
survives a restart. Pure: no station imports; app.py hands in the namespaces.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

# A param: key, label, what it means, type, default, lowest, highest, target.
# A target is "module.ATTR" or "app.OBJ.attr" ("app" is app.py's namespace).
GATES: tuple[dict[str, Any], ...] = (
    {"id": "h3_sentence", "road": "Hourly H3 video dialogue",
     "name": "Whole sentences only",
     "says": "The last check a line passes before the hourly video's people say it: every sentence whole, "
             "plain and speakable.",
     "params": (
         ("min_words", "Fewest words in a sentence", "A sentence shorter than this is a fragment "
          "(\"Buy it today!\" is 3).", "int", 4, 1, 12, "h3_speak.MIN_WORDS"),
         ("max_words", "Most words in a sentence", "Longer than this is too long for one breath.",
          "int", 24, 8, 60, "h3_speak.MAX_WORDS"),
     ),
     "rules_target": "h3_speak.OFF",
     "rules": (
         ("url", "A web address"), ("file", "A file name"), ("status", "A status line (\"analysis complete\")"),
         ("speaker", "A speaker label (\"Ash: ...\")"), ("titles", "Clip titles glued together"),
         ("markup", "Markup or an annotation"), ("nonascii", "Not plain English characters"),
         ("fragment", "Fewer words than the least"), ("too_long", "More words than the most"),
         ("no_end", "No sentence end"), ("abbrev", "Cut at an abbreviation"),
         ("mid_sentence", "Starts mid-sentence"), ("numbers", "Numbers, not words"),
         ("title", "Title Case (a title, not a sentence)"), ("stutter", "A stutter (a word three times)"),
     )},
    {"id": "norepeat", "road": "Every line, record and SFX clip",
     "name": "Nothing airs twice inside a day",
     "says": "A line (any seat, a banked turn re-aired under a new id included), a clip or a record already "
             "heard inside the window is refused.",
     "params": (
         ("hours", "Window, hours (0 = off)", "How long a line, clip or record stays unsayable after it airs.",
          "float", 24.0, 0.0, 168.0, "app.NOREPEAT_HOURS"),
         ("min_words", "Fewest words to count as a line", "Shorter lines (\"Yeah.\") are never refused.",
          "int", 4, 1, 20, "app.NOREPEAT.min_words"),
     )},
    {"id": "rerun", "road": "Rounds: banter, calls, deep rounds",
     "name": "Rerun check (said before)",
     "says": "A turn that overlaps a line already said is swapped for Speaker Box material or dropped.",
     "params": (
         ("jaccard", "Near-identical overlap", "Share of 4-word runs two lines have in common to be the same "
          "line (higher = fewer refusals).", "float", 0.62, 0.3, 1.0, "app.RERUN_JACCARD"),
         ("contain", "Containment", "Share of the shorter line found inside the other.", "float", 0.85, 0.3,
          1.0, "app.RERUN_CONTAIN"),
         ("breaker", "Breaker: stand down above this block rate", "When more of the last 40 turns than this "
          "are blocked, the fuzzy checks stand down.", "float", 0.35, 0.05, 1.0, "app.BLOCK_RATE_CAP"),
         ("worn_lines", "Worn phrase: lines a 5-word run may appear in", "A phrase already in this many lines "
          "is worn out.", "int", 12, 2, 200, "app.PHRASE_ACROSS_LINES"),
     )},
    {"id": "ad_repeat", "road": "Adverts",
     "name": "Advert copy check",
     "says": "A fresh advert too close to one already in the ad book is rewritten (three tries).",
     "params": (
         ("jaccard", "Overlap", "Share of 4-word runs in common.", "float", 0.50, 0.2, 1.0, "app.AD_REPEAT_JACCARD"),
         ("contain", "Containment", "Share of the shorter advert inside the other.", "float", 0.70, 0.2, 1.0,
          "app.AD_REPEAT_CONTAIN"),
     )},
    {"id": "s3_copy", "road": "System 3 writing (every road)",
     "name": "System 3 copy gate",
     "says": "A written turn that copies a line already said, or reads its subject or a Speaker Box passage "
             "out word for word, is re-written, then dropped.",
     "params": (
         ("similar", "Same line at this similarity", "difflib ratio to an earlier line.", "float", 0.9, 0.5, 1.0,
          "system3.GATE_SIMILAR"),
         ("echo_run", "Words in a row copied", "This many words in a row from an earlier line is a copy.",
          "int", 12, 4, 40, "system3.GATE_ECHO_RUN"),
         ("echo_share", "Share of the turn copied", "A run of six or more this much of the turn.", "float", 0.6,
          0.2, 1.0, "system3.GATE_ECHO_SHARE"),
         ("min_words", "Shorter than this is an interjection", "Never a copy (\"Yeah.\").", "int", 3, 1, 12,
          "system3.GATE_MIN_WORDS"),
         ("source_run", "Words in a row read out of the subject", "", "int", 14, 4, 60, "system3.GATE_SOURCE_RUN"),
         ("passage_run", "Words in a row read out of a Speaker Box passage", "", "int", 8, 3, 60,
          "system3.GATE_PASSAGE_RUN"),
     )},
    {"id": "s3_echo", "road": "Single lines (adverts, IDs, replies, memos)",
     "name": "Running-order echo",
     "says": "A line that reads the running order's direction back is withheld.",
     "params": (
         ("min_words", "Words in a row that count as an echo", "", "int", 4, 2, 20, "system3.ECHO_MIN_WORDS"),
     )},
    {"id": "call_novelty", "road": "Callers",
     "name": "Call novelty",
     "says": "A call too like one of the last 240 is flagged (advisory unless the call gate is on air).",
     "params": (
         ("similarity", "Most similarity to an earlier call", "", "float", 0.48, 0.1, 1.0,
          "app.CALL_NOVELTY_MAX_SIMILARITY"),
     )},
    {"id": "reair_copy", "road": "Banked rounds (re-air)",
     "name": "Re-air copy check",
     "says": "A banked turn more than this similar to an earlier turn is retired.",
     "params": (
         ("ratio", "Similarity that is a copy", "", "float", 0.9, 0.5, 1.0, "reair_gate.COPY_RATIO"),
         ("min_chars", "Shorter turns are never copies", "Characters.", "int", 12, 1, 200, "reair_gate.COPY_MIN_CHARS"),
     )},
    {"id": "english", "road": "Every line (when the language gate is on)",
     "name": "English check",
     "says": "A line of eight or more words with more accented letters than this share is not English.",
     "params": (
         ("accents", "Most accented-letter share", "", "float", 0.04, 0.0, 1.0, "app.ENGLISH_DIACRITIC_MAX"),
     )},
)

_LOCK = threading.RLock()
_STATE: dict[str, Any] = {"path": None, "values": {}, "rules_off": {}, "at": 0.0,
                          "boot": {}}     # target -> the value the station booted with (its env, its code)


def _param(gate: dict[str, Any], key: str) -> tuple | None:
    return next((p for p in gate["params"] if p[0] == key), None)


def gate(gid: str) -> dict[str, Any] | None:
    return next((g for g in GATES if g["id"] == gid), None)


def clamp(p: tuple, value: Any) -> Any:
    _k, _l, _s, kind, _d, lo, hi, _t = p
    if kind == "int":
        v = int(round(float(value)))
    else:
        v = round(float(value), 4)
    return max(lo, min(hi, v))


def load(path: Any) -> dict[str, Any]:
    with _LOCK:
        _STATE["path"] = Path(path)
        try:
            got = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            got = {}
        _STATE["values"] = {k: v for k, v in (got.get("values") or {}).items() if isinstance(k, str)}
        _STATE["rules_off"] = {k: list(v) for k, v in (got.get("rules_off") or {}).items() if isinstance(v, list)}
        _STATE["at"] = float(got.get("at") or 0)
        return dict(_STATE)


def _save() -> None:
    path = _STATE.get("path")
    if not path:
        return
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps({"values": _STATE["values"], "rules_off": _STATE["rules_off"],
                               "at": _STATE["at"]}, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _resolve(target: str, app_ns: dict[str, Any]) -> tuple[Any, str]:
    """(the object that holds it, the attribute) for "module.ATTR" / "app.OBJ.attr"."""
    parts = target.split(".")
    head, rest = parts[0], parts[1:]
    if head == "app":
        if len(rest) == 1:
            return app_ns, rest[0]
        holder = app_ns.get(rest[0])
        for name in rest[1:-1]:
            holder = getattr(holder, name)
        return holder, rest[-1]
    holder = sys.modules.get(head)
    if holder is None:
        raise KeyError(head)
    for name in rest[:-1]:
        holder = getattr(holder, name)
    return holder, rest[-1]


def _get(holder: Any, attr: str) -> Any:
    return holder.get(attr) if isinstance(holder, dict) else getattr(holder, attr)


def _set(holder: Any, attr: str, value: Any) -> None:
    if isinstance(holder, dict):
        holder[attr] = value
    else:
        setattr(holder, attr, value)


def apply(app_ns: dict[str, Any]) -> dict[str, str]:
    """Every stored value onto the running station; the gates' rules switched
    off. {target: why} for each one that could not be set."""
    missed: dict[str, str] = {}
    with _LOCK:
        for g in GATES:
            for p in g["params"]:
                full = "%s.%s" % (g["id"], p[0])
                try:
                    holder, attr = _resolve(p[7], app_ns)
                    if p[7] not in _STATE["boot"]:
                        _STATE["boot"][p[7]] = _get(holder, attr)
                    _set(holder, attr, clamp(p, _STATE["values"][full]) if full in _STATE["values"]
                         else _STATE["boot"][p[7]])
                except Exception as exc:  # noqa: BLE001
                    missed[p[7]] = type(exc).__name__
            if g.get("rules_target"):
                try:
                    holder, attr = _resolve(g["rules_target"], app_ns)
                    off = _get(holder, attr)
                    off.clear()
                    off.update(_STATE["rules_off"].get(g["id"]) or [])
                except Exception as exc:  # noqa: BLE001
                    missed[g["rules_target"]] = type(exc).__name__
    return missed


def change(app_ns: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """One edit: {gate, key, value} | {gate, rule, on} | {gate, reset: true}."""
    g = gate(str(body.get("gate") or ""))
    if g is None:
        raise KeyError("no such gate")
    with _LOCK:
        if body.get("reset"):
            for p in g["params"]:
                _STATE["values"].pop("%s.%s" % (g["id"], p[0]), None)
            _STATE["rules_off"].pop(g["id"], None)
        elif body.get("rule") is not None:
            rule = str(body["rule"])
            if not any(r[0] == rule for r in g.get("rules") or ()):
                raise KeyError("no such rule")
            off = set(_STATE["rules_off"].get(g["id"]) or [])
            (off.discard if body.get("on") else off.add)(rule)
            _STATE["rules_off"][g["id"]] = sorted(off)
        else:
            p = _param(g, str(body.get("key") or ""))
            if p is None:
                raise KeyError("no such setting")
            value = clamp(p, body.get("value"))
            full = "%s.%s" % (g["id"], p[0])
            if value == _STATE["boot"].get(p[7], p[4]):
                _STATE["values"].pop(full, None)
            else:
                _STATE["values"][full] = value
        _STATE["at"] = round(time.time(), 3)
        _save()
    apply(app_ns)
    return view(app_ns)


def view(app_ns: dict[str, Any], stats: Callable[[str], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Every gate with its settings as they stand on the running station."""
    out = []
    for g in GATES:
        params = []
        for p in g["params"]:
            try:
                holder, attr = _resolve(p[7], app_ns)
                live = _get(holder, attr)
            except Exception:  # noqa: BLE001
                live = None
            base = _STATE["boot"].get(p[7], p[4])
            params.append({"key": p[0], "label": p[1], "says": p[2], "type": p[3], "default": base,
                           "min": p[5], "max": p[6], "value": live, "changed": live is not None and live != base})
        off = set(_STATE["rules_off"].get(g["id"]) or [])
        row = {"id": g["id"], "road": g["road"], "name": g["name"], "says": g["says"], "params": params,
               "rules": [{"id": r[0], "label": r[1], "on": r[0] not in off} for r in g.get("rules") or ()]}
        if stats:
            try:
                row["stats"] = stats(g["id"]) or {}
            except Exception:  # noqa: BLE001
                row["stats"] = {}
        out.append(row)
    return {"gates": out, "at": _STATE["at"]}
