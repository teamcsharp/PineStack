"""The director's room (2026-09-10).

    "I need an hourly script of each segment able to be reviewed where I can
     give notes and pointers that dictate how the next segment is generated
     of that type. I want full directorial capabilities with assisting the
     scripting process and see how a segment is planned in advance."

THE SHAPE. A note is direction, and direction is a standing thing: you tell
a room "let the caller finish a thought before Skip cuts in" ONCE and it
governs every call from then on. So the book holds two kinds of note, and
they differ in kind rather than in degree:

  * a STANDING note is written against a segment KIND. Every future segment
    of that kind carries it, in the order the notes were given, until it is
    retired. This is the direction sheet.
  * a ONE-SHOT note is written against a single OCCURRENCE - this hour's
    05:47 call and no other. It is spent the moment that occurrence is
    written, and it outranks the standing sheet for that one segment.

Both reach the writing through `director_clause()`, which is appended inside
`_schedule_clause` - the one place every scheduled round already passes
through, System2's per-slot prompt included - so a note governs the System2
road and the legacy road without either of them knowing this file exists.

WHY NOT THE ENTRY'S OWN `notes` FIELD. It exists, and the clause already
carries it, but it is a property of the SHEET: editing it rewrites the
running order for every hour, there is exactly one of it, it keeps no
history, and retiring a note means deleting the evidence that it was ever
given. Direction has to accumulate and has to be auditable - "which note was
in force when this segment was written" is the first question the operator
asks when a segment comes out wrong.

NOTHING HERE MAY TAKE THE AIR. Every read fails soft to "no direction", so a
missing or corrupt book leaves the station writing exactly as it did before
this shipped.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import Any

# How many standing notes one kind may carry into a prompt. A direction
# sheet is a handful of pointers, not a manifesto: past this the model stops
# obeying any of them and the segment gets worse, not better.
DIRECTOR_STANDING_MOST = 8
DIRECTOR_NOTE_CHARS = 600
# Notes kept per kind on disk, retired ones included, so the record of what
# was asked for outlives the retiring of it.
DIRECTOR_KEEP = 200

_LOCK = RLock()
_MEM: dict[str, Any] | None = None
_PATH: Path | None = None


def director_path(data_dir: Any = None) -> Path:
    """Where the book lives. The host sets the directory once at import."""
    global _PATH
    if _PATH is None or data_dir is not None:
        base = Path(data_dir) if data_dir is not None else Path("data")
        _PATH = base / "director_notes.json"
    return _PATH


def _blank() -> dict[str, Any]:
    return {"version": 1, "notes": [], "at": time.time()}


def director_read() -> dict[str, Any]:
    global _MEM
    with _LOCK:
        if _MEM is None:
            try:
                _MEM = json.loads(
                    director_path().read_text(encoding="utf-8")) or _blank()
            except Exception:                      # noqa: BLE001
                _MEM = _blank()
            if not isinstance(_MEM.get("notes"), list):
                _MEM["notes"] = []
        return _MEM


def director_write(rows: dict[str, Any]) -> None:
    global _MEM
    with _LOCK:
        _MEM = rows
        rows["at"] = time.time()
        try:
            path = director_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(rows, indent=1, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(str(tmp), str(path))
        except Exception:                          # noqa: BLE001
            pass                    # the book is direction, not the show


def director_notes(kind: str = "", scope: str = "",
                   live_only: bool = True) -> list[dict[str, Any]]:
    """The book, oldest first, so a sheet reads in the order it was given."""
    out = []
    for row in list(director_read().get("notes") or []):
        if not isinstance(row, dict):
            continue
        if kind and str(row.get("kind") or "") != str(kind):
            continue
        if scope and str(row.get("scope") or "") != str(scope):
            continue
        if live_only and (row.get("retired_at") or row.get("spent_at")):
            continue
        out.append(row)
    out.sort(key=lambda r: float(r.get("at") or 0))
    return out


def director_add(kind: str, text: str, scope: str = "standing",
                 slot_id: str = "", occurrence: str = "",
                 who: str = "operator") -> dict[str, Any]:
    """Write one note into the book.

    `scope` is "standing" - every future segment of this kind - or "next",
    the named occurrence only, spent when that occurrence is written."""
    said = " ".join(str(text or "").split())[:DIRECTOR_NOTE_CHARS]
    if not said:
        raise ValueError("a note with no words in it is not direction")
    scope = "next" if str(scope) == "next" else "standing"
    row = {"id": uuid.uuid4().hex[:12],
           "kind": str(kind or "")[:40],
           "scope": scope,
           "text": said,
           "slot_id": str(slot_id or "")[:60],
           "occurrence": str(occurrence or "")[:80],
           "who": str(who or "operator")[:40],
           "at": time.time(),
           "used": 0,
           "last_used": 0.0}
    book = director_read()
    book.setdefault("notes", []).append(row)
    # Bounded per kind, retired notes included - the record of what was
    # asked for is the point, but it is not an archive.
    same = [r for r in book["notes"] if str(r.get("kind") or "") == row["kind"]]
    if len(same) > DIRECTOR_KEEP:
        drop = {id(r) for r in same[:len(same) - DIRECTOR_KEEP]}
        book["notes"] = [r for r in book["notes"] if id(r) not in drop]
    director_write(book)
    return row


def director_retire(note_id: str) -> bool:
    book = director_read()
    for row in book.get("notes") or []:
        if str(row.get("id") or "") == str(note_id):
            if row.get("retired_at"):
                return False
            row["retired_at"] = time.time()
            director_write(book)
            return True
    return False


def director_restore(note_id: str) -> bool:
    book = director_read()
    for row in book.get("notes") or []:
        if str(row.get("id") or "") == str(note_id):
            if not row.get("retired_at"):
                return False
            row.pop("retired_at", None)
            director_write(book)
            return True
    return False


def _wants(row: dict[str, Any], slot_id: str, occurrence: str) -> bool:
    """Is this one-shot note addressed to this occurrence?"""
    want_occ = str(row.get("occurrence") or "")
    want_slot = str(row.get("slot_id") or "")
    if want_occ:
        return want_occ == str(occurrence or "")
    if want_slot:
        return want_slot == str(slot_id or "")
    return True                     # written against the kind's next one


def director_spend(kind: str, slot_id: str = "", occurrence: str = "") -> int:
    """Mark the one-shot notes for this occurrence as used.

    Called when a segment of this kind is actually WRITTEN, never when one
    is read - a panel poll must not spend the operator's direction."""
    book = director_read()
    now = time.time()
    spent = 0
    for row in book.get("notes") or []:
        if str(row.get("scope") or "") != "next":
            continue
        if row.get("spent_at") or row.get("retired_at"):
            continue
        if str(row.get("kind") or "") != str(kind or ""):
            continue
        if not _wants(row, slot_id, occurrence):
            continue
        row["spent_at"] = now
        row["used"] = int(row.get("used") or 0) + 1
        row["last_used"] = now
        spent += 1
    if spent:
        director_write(book)
    return spent


def director_touch(kind: str) -> None:
    """Count the standing notes as having governed one more segment."""
    book = director_read()
    now = time.time()
    touched = False
    for row in book.get("notes") or []:
        if (str(row.get("scope") or "") == "standing"
                and str(row.get("kind") or "") == str(kind or "")
                and not row.get("retired_at")):
            row["used"] = int(row.get("used") or 0) + 1
            row["last_used"] = now
            touched = True
    if touched:
        director_write(book)


def director_clause(kind: str, slot_id: str = "",
                    occurrence: str = "") -> str:
    """The direction for this segment, dressed as the instruction it is.

    Standing notes first, in the order they were given, then anything
    written for this one occurrence - which speaks LAST because the
    narrower, more recent instruction wins, the same rule #766 applies to a
    caller's own document against the station-wide lock."""
    try:
        kind = str(kind or "")
        if not kind:
            return ""
        standing = director_notes(kind, "standing")[-DIRECTOR_STANDING_MOST:]
        one_shot = [r for r in director_notes(kind, "next")
                    if _wants(r, slot_id, occurrence)]
        if not standing and not one_shot:
            return ""
        out = ["\n\nTHE DIRECTOR'S NOTES on this segment. These are standing "
               "instructions from the person who runs this station, given "
               "after hearing previous segments of this kind go out. They "
               "are about HOW to do this segment, they outrank your own "
               "habits, and they are never to be read aloud, referred to, "
               "or acknowledged on air:"]
        for at, row in enumerate(standing, 1):
            out.append(f"\n  {at}. {row.get('text')}")
        for row in one_shot:
            out.append("\n  AND FOR THIS ONE SEGMENT ONLY, which outranks "
                       "the notes above wherever they disagree: "
                       + str(row.get("text") or ""))
        return "".join(out)
    except Exception:                              # noqa: BLE001
        return ""             # direction is never a reason to lose a round


def director_sheet() -> dict[str, Any]:
    """The whole book, by kind, for the room's left-hand column."""
    book = director_read()
    by_kind: dict[str, dict[str, Any]] = {}
    for row in book.get("notes") or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "")
        cell = by_kind.setdefault(kind, {"kind": kind, "standing": [],
                                         "next": [], "retired": [],
                                         "spent": []})
        if row.get("retired_at"):
            cell["retired"].append(row)
        elif str(row.get("scope") or "") == "next":
            (cell["spent"] if row.get("spent_at") else cell["next"]).append(row)
        else:
            cell["standing"].append(row)
    for cell in by_kind.values():
        for key in ("standing", "next", "retired", "spent"):
            cell[key].sort(key=lambda r: float(r.get("at") or 0))
            del cell[key][:-40]
    return {"kinds": by_kind, "at": book.get("at")}
