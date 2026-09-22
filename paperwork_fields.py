"""paperwork_fields - the pure half of PUT /api/paperwork/field (#1231).

"in Any text field, allow me to tap on it and type inside of it and begin
making edits there."

The inspector ("How this line came to be") draws the station's stores as
read-only boxes. This module turns an edited box back into a change on the
store it was drawn from, WITHOUT touching the station: app.py owns the
stores and their locks, this owns the parsing and the merge, so both halves
can be tested off a temp directory (tests/test_paperwork_fields_1231.py).

Nothing here reads a file, a clock or a global. Every function either returns
the change or raises ValueError with the sentence the operator will read on
the strip under the box.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

# scene_inputs() shows this many topics, each cut to this many characters,
# and the sheet cuts the whole box at DETAIL_MOST. The merge below matches
# the operator's lines to the bank BY POSITION against exactly that view, so
# the three numbers are the contract between the box and the bank.
TOPIC_SHOWN = 12
TOPIC_TEXT_MOST = 160
TOPIC_MOST = 400            # add_bombshell's own cap on a topic's text
DETAIL_MOST = 1600          # scene_inputs' put(): detail[:1600]

_USED_TAIL = re.compile(r"\s*\(used\)\s*$", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*•]\s*)?")
_TURN_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _'.-]{0,24}?)\s*:\s*(.*)$")


def norm(s: Any) -> str:
    return " ".join(str(s or "").split())


# --- the topic bank -------------------------------------------------------

def topic_block(rows: list[dict[str, Any]]) -> str:
    """The box exactly as scene_inputs draws it (one source of truth: app.py
    calls this for the card, and merge_topic_block() re-draws it to check the
    bank has not moved under the operator)."""
    return "\n".join("- " + str(r.get("text") or "")[:TOPIC_TEXT_MOST]
                     + (" (used)" if r.get("used") else "")
                     for r in rows[:TOPIC_SHOWN])


def topic_lines(block: str, shown: int) -> list[str]:
    """One entry per line of the box, bullets and the (used) flag stripped.
    Blank lines are KEPT up to the count shown - a blank line is how a topic
    is taken out - and only the editor's trailing blanks past that are
    dropped."""
    out: list[str] = []
    text = str(block or "").replace("\r\n", "\n").replace("\r", "\n")
    for raw in text.split("\n"):
        out.append(_USED_TAIL.sub("", _BULLET.sub("", raw, count=1)).strip())
    while len(out) > shown and out and not out[-1]:
        out.pop()
    return out


def merge_topic_block(rows: list[dict[str, Any]], was_block: str,
                      new_block: str, now: int,
                      mint: Callable[[], str]) -> tuple[list[dict[str, Any]],
                                                        list[dict[str, Any]]]:
    """Apply an edited box to the bank.

    rows       the bank as stored (every row, not only the shown ones)
    was_block  the box as it was drawn for the operator (may be cut at
               DETAIL_MOST by the sheet)
    new_block  what the operator typed
    Returns (rows, changes). Each change is {"op", "id", "text"} with op in
    reword / remove / add. The (used) count, the id and the added stamp of a
    reworded topic are kept: only its words change.

    Matched BY POSITION against the shown rows, so the bank must not have
    moved since the box was drawn: the current drawing must equal was_block
    (allowing for the sheet's cut). A shorter list is refused rather than
    guessed at - a topic is taken out by blanking its line."""
    rows = [dict(r) if isinstance(r, dict) else r for r in rows]
    current = topic_block(rows)
    was = str(was_block or "")
    if was and was != current[:len(was)]:
        raise ValueError("the bank has changed since this box was drawn - "
                         "close the inspector and open it again")
    was_lines = topic_lines(was if was else current[:DETAIL_MOST], TOPIC_SHOWN)
    # The sheet's cut can leave fewer than TOPIC_SHOWN lines on screen; the
    # operator can only have edited the lines they were shown.
    visible = min(TOPIC_SHOWN, len(was_lines), len(rows))
    shown = [r for r in rows[:visible] if isinstance(r, dict)]
    new_lines = topic_lines(new_block, len(shown))
    if len(new_lines) < len(shown):
        raise ValueError("to take a topic out, blank its line rather than "
                         "deleting it - the list is matched line by line, "
                         "and %d of the %d shown are missing"
                         % (len(shown) - len(new_lines), len(shown)))
    changes: list[dict[str, Any]] = []
    gone: set[int] = set()
    for at, row in enumerate(shown):
        new = new_lines[at]
        old = was_lines[at] if at < len(was_lines) else ""
        if new == old:
            continue
        if not new:
            gone.add(id(row))
            changes.append({"op": "remove", "id": row.get("id"),
                            "text": str(row.get("text") or "")})
            continue
        row["text"] = new[:TOPIC_MOST]
        row["edited"] = int(now)
        changes.append({"op": "reword", "id": row.get("id"),
                        "text": row["text"]})
    added: list[dict[str, Any]] = []
    for new in new_lines[len(shown):]:
        if not new:
            continue
        row = {"id": mint(), "text": new[:TOPIC_MOST], "kind": "topic",
               "added": int(now), "used": 0}
        added.append(row)
        changes.append({"op": "add", "id": row["id"], "text": row["text"]})
    kept = [r for r in rows if not (isinstance(r, dict) and id(r) in gone)]
    # New ones go to the FRONT, the way add_bombshell files them, so the
    # operator sees the topic they just planted at the top of the box.
    return added + kept, changes


# --- the director's weather -----------------------------------------------

_CLEAR_WORDS = ("", "no macro set", "none", "clear", "-", "—", "calm",
                "nothing", "no macro")


def parse_mood(value: str, macros: Any, dims: Any) -> dict[str, Any]:
    """The weather box, read back.

    Two shapes are accepted, the two the card shows:
      the value line   'dj: flustered, cohost: nervous' - one speaker per
                       entry, the macro from MACRO_STATES; the whole map is
                       REPLACED by what is typed, so dropping a speaker
                       clears that speaker. Any of the clear words empties it.
      the whole of it  a JSON object {speaker: {dim: 0..1, ...}} - the raw
                       emotion dims, merged per speaker; a speaker mapped to
                       a string is taken as a macro.
    Returns {"clear": True} | {"macros": {...}, "dims": {...}, "replace"}."""
    allowed = sorted(str(m) for m in (macros or ()))
    dim_names = tuple(str(d) for d in (dims or ()))
    text = str(value or "").strip()
    if text.lower() in _CLEAR_WORDS:
        return {"clear": True}
    if text.startswith("{"):
        try:
            got = json.loads(text)
        except ValueError as exc:
            raise ValueError("that is not JSON: %s" % str(exc)[:80]) from exc
        if not isinstance(got, dict):
            raise ValueError("the weather is an object keyed by speaker")
        out_m: dict[str, str] = {}
        out_d: dict[str, dict[str, float]] = {}
        for who, state in got.items():
            who = str(who).strip()[:24]
            if not who:
                continue
            if isinstance(state, str):
                out_m[who] = _macro(state, allowed)
            elif isinstance(state, dict):
                row: dict[str, float] = {}
                for dim, val in state.items():
                    if str(dim) not in dim_names:
                        continue
                    try:
                        row[str(dim)] = max(0.0, min(1.0, float(val)))
                    except (TypeError, ValueError):
                        continue
                out_d[who] = row
            else:
                raise ValueError("%s: a macro name or a dims object" % who)
        return {"macros": out_m, "dims": out_d, "replace": False}
    out: dict[str, str] = {}
    for piece in re.split(r"[,;\n]+", text):
        piece = piece.strip()
        if not piece:
            continue
        if ":" in piece:
            who, macro = piece.split(":", 1)
        elif "=" in piece:
            who, macro = piece.split("=", 1)
        else:
            raise ValueError("say who: 'dj: flustered, cohost: nervous' - "
                             "the macros are %s" % ", ".join(allowed))
        who = who.strip()[:24]
        if not who:
            raise ValueError("a speaker is missing before ':'")
        out[who] = _macro(macro, allowed)
    return {"macros": out, "dims": {}, "replace": True}


def _macro(name: str, allowed: list[str]) -> str:
    m = str(name or "").strip().lower()
    if m in _CLEAR_WORDS:
        return ""
    if m not in allowed:
        raise ValueError("no macro called '%s' - the weather can be %s, or "
                         "'none' to clear" % (m[:24], ", ".join(allowed)))
    return m


# --- the theme and the guest ----------------------------------------------

def split_theme(value: str) -> tuple[str, str | None]:
    """The theme box is the theme's text plus, when it cites one, a last
    line 'report: <doc>'. Back out: (text, doc) - doc is None when no
    report line was typed (leave it as it is), '' when it was typed empty
    (let them roam the shelf)."""
    doc: str | None = None
    body: list[str] = []
    for line in str(value or "").replace("\r", "").split("\n"):
        if line.strip().lower().startswith("report:"):
            doc = line.split(":", 1)[1].strip()
            continue
        body.append(line)
    return norm(" ".join(body)), doc


def split_guest(value: str) -> tuple[str, str]:
    """The guest box is 'who they are' then 'why they came', joined by a
    newline. The first non-empty line is who; everything after is why."""
    lines = [ln.strip() for ln in str(value or "").replace("\r", "").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    if not lines:
        raise ValueError("say who the guest is on the first line, and why "
                         "they came on the lines after")
    return lines[0], norm(" ".join(lines[1:]))


# --- the round's own turns --------------------------------------------------

def locate_turn(turns: list[Any], said: str, hint: Any = None,
                spoken: Callable[[str], str] | None = None) -> int:
    """Which turn of a script a heard line is. Matched on the WORDS, never
    on a position alone: the chat row's turn index counts rendered chunks,
    which is not one-to-one with the script's turns (director_edit_turn says
    the same). The hint only breaks a tie between identical turns."""
    want = norm(said)
    if not want or not turns:
        return -1
    texts = [norm(t[1] if isinstance(t, (tuple, list)) else
                  (t.get("text") if isinstance(t, dict) else t))
             for t in turns]
    hits = [i for i, t in enumerate(texts) if t == want]
    if not hits and spoken is not None:
        try:
            hits = [i for i, t in enumerate(texts) if norm(spoken(t)) == want]
        except Exception:  # noqa: BLE001
            hits = []
    if not hits and len(want) >= 24:
        hits = [i for i, t in enumerate(texts)
                if t and (want in t or (len(t) >= 24 and t in want))]
    if not hits:
        return -1
    try:
        h = int(hint)
        if h in hits:
            return h
    except (TypeError, ValueError):
        pass
    return hits[0]


def script_single_change(was_turns: list[Any], new_turns: list[Any]
                         ) -> tuple[int, str, str] | None:
    """The one turn that differs between the script as shown and the script
    as typed - (index, was, now) - or None when nothing changed. More than
    one changed turn, a turn added or dropped, or a speaker swapped is
    refused: the writers room re-records ONE line per edit, and that is the
    whole economy of editing a recorded round."""
    def pair(t: Any) -> tuple[str, str]:
        if isinstance(t, (tuple, list)) and len(t) >= 2:
            return str(t[0] or "").strip().upper()[:1], norm(t[1])
        if isinstance(t, dict):
            return (str(t.get("seat") or t.get("marker") or "").strip().upper()[:1],
                    norm(t.get("text")))
        return "", norm(t)
    was = [pair(t) for t in was_turns]
    new = [pair(t) for t in new_turns]
    if not was:
        raise ValueError("the script as shown has no turns to compare against")
    if len(was) != len(new):
        raise ValueError("one line at a time: the script has %d turns and "
                         "you typed %d - a turn is added or dropped in the "
                         "writers room, not here" % (len(was), len(new)))
    diffs = [i for i in range(len(was)) if was[i][1] != new[i][1]
             or (was[i][0] and new[i][0] and was[i][0] != new[i][0])]
    if not diffs:
        return None
    if len(diffs) > 1:
        raise ValueError("one line at a time - %d turns changed. Only the "
                         "changed line re-records, so change one, save, "
                         "then the next" % len(diffs))
    i = diffs[0]
    if was[i][0] and new[i][0] and was[i][0] != new[i][0]:
        raise ValueError("a turn keeps its seat here - change the words, "
                         "not the speaker")
    return i, was[i][1], new[i][1]


def split_turns(text: str) -> list[tuple[str, str]]:
    """A plain 'A: ... / B: ...' split for callers that have no banter_turns
    - one turn per labelled line, an unlabelled line continues the turn
    before it."""
    out: list[tuple[str, str]] = []
    for raw in str(text or "").replace("\r", "").split("\n"):
        if not raw.strip():
            continue
        m = _TURN_LINE.match(raw)
        if m and m.group(2).strip():
            out.append((m.group(1).strip(), m.group(2).strip()))
        elif out:
            out[-1] = (out[-1][0], norm(out[-1][1] + " " + raw))
        else:
            out.append(("", raw.strip()))
    return out
