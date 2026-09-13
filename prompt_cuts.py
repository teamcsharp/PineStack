"""WHAT THE PROMPTS ARE NO LONGER ALLOWED TO CARRY.

"For each of these sections, I want to see what data is being given to the
 system prompt from these, and I want an X that allows me to actually remove
 this data from being part of the data chunking that's being added in there.
 So I want the ability to be able to clean this stuff up as well. So going
 forward, I can maybe remove some of this stuff from being weight on the
 system prompt, maybe simplifying things a little bit."

A STANDING DECISION, SO IT LIVES ON THE STATION. The X is pressed in a flow
chart on somebody's desktop while looking at one line, but what it means is
"never put this in a prompt again". It has to outlive that window, that
desktop, and the forty-eight hours the line's own paperwork survives.

KEYED BY THE PASSAGE, NOT BY THE LINE OR THE POSITION. A cut is {kind, mark}
where mark fingerprints the text. The name is stored beside it so the file
can be read by a person, but it is NOT part of the match, and that is a
correction rather than a shortcut:

  THE NAME IS NOT THE SAME WORD ON BOTH SIDES. A crystal shard is `kind` in
  the provenance the X is pressed against and `crystal` where the prompt is
  assembled. Requiring the name to match would have produced a cut that is
  recorded, displayed, and silently never applied - which is the worst way
  for this to fail, because it looks like it worked.

  THE NAME ALONE WOULD BE TOO BLUNT ANYWAY - cutting every future swath out
  of a document is a much bigger decision than the one being made.

  AND THE FINGERPRINT IS ALREADY THE PASSAGE. Two different passages
  colliding inside one kind is not a thing worth designing around.

ONLY THE FIRST 160 CHARACTERS ARE FINGERPRINTED, for the same reason. The
station keeps its influence rings truncated - a crystal shard is stored at
240 characters, a material bullet at 240 - while the assembler has the whole
thing. Fingerprinting all of it would mean the two sides hash different
strings for the same passage and never match. A bounded prefix is what both
sides can agree on, and it is the same trick the codebase's own
chunk_key(file, text) plays with text[:120].

THE FINGERPRINT IS FNV-1a AND MUST AGREE WITH THE BROWSER. script-flow.js
computes the same mark before it ever reaches here, so the two
implementations have to produce the same string for the same passage or a cut
made in the window would never match anything the station assembles. Two
details make that true rather than nearly true:

  UTF-16 CODE UNITS, because that is what JavaScript's charCodeAt hands back
  and what its .length counts. Iterating Python's code points instead would
  agree on ASCII and diverge on the first emoji or accented character.

  THE SHIFT SUM IS THE FNV PRIME. The browser writes the multiply as
  (a<<1)+(a<<4)+(a<<7)+(a<<8)+(a<<24) plus a, which modulo 2**32 is exactly
  a * 0x01000193. Written here as the multiply it actually is.

WHITESPACE IS COLLAPSED AND CASE DROPPED before fingerprinting, so a passage
that comes back reflowed or re-cased still matches the cut made against it.

NOTHING HERE EVER RAISES INTO THE WRITING PATH. A prompt being assembled must
not fail because an exclusion file is malformed - the worst this may do is
decline to exclude something.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Iterable, List, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
STORE = os.path.join(DATA_DIR, "prompt_cuts.json")

_LOCK = threading.Lock()
_CACHE: Optional[List[Dict[str, Any]]] = None
_CACHE_AT = 0.0

# Re-read at most this often. The writing path asks constantly and this is a
# tiny file, but a disk read per chunk per round is still a disk read per
# chunk per round.
_FRESH_FOR = 5.0

KINDS = ("document", "material", "request", "crystal", "vector",
         "character", "station")


# How much of a passage is fingerprinted. Short enough that every truncated
# copy the station keeps still contains it whole - the influence rings cut at
# 240 - and long enough that no two real passages share it.
MARK_CHARS = 160


def fingerprint(text: str) -> str:
    """FNV-1a over UTF-16 code units, plus the length - see the module note.

    Must stay byte-identical with fingerprint() in script-flow.js.
    """
    flat = " ".join(str(text or "").split()).strip().lower()[:MARK_CHARS]
    units = flat.encode("utf-16-le", "surrogatepass")
    a = 0x811C9DC5
    for i in range(0, len(units), 2):
        a ^= units[i] | (units[i + 1] << 8)
        # The browser's shift sum is this multiply, modulo 2**32.
        a = (a * 0x01000193) & 0xFFFFFFFF
    return "%08x-%d" % (a, len(units) // 2)


def _read() -> List[Dict[str, Any]]:
    try:
        with open(STORE, "r", encoding="utf-8") as fh:
            got = json.load(fh)
    except FileNotFoundError:
        return []
    except Exception:
        # A malformed store must not take the writing path down with it.
        return []
    if isinstance(got, dict):
        got = got.get("cuts", [])
    if not isinstance(got, list):
        return []
    out = []
    for one in got:
        if isinstance(one, dict) and one.get("kind") and one.get("mark"):
            out.append(one)
    return out


def _write(cuts: List[Dict[str, Any]]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"cuts": cuts}, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def all_cuts(fresh: bool = False) -> List[Dict[str, Any]]:
    """Everything currently cut. Cheap enough to call from the writing path."""
    global _CACHE, _CACHE_AT
    with _LOCK:
        now = time.time()
        if fresh or _CACHE is None or (now - _CACHE_AT) > _FRESH_FOR:
            _CACHE = _read()
            _CACHE_AT = now
        return list(_CACHE)


def _forget_cache() -> None:
    global _CACHE, _CACHE_AT
    _CACHE = None
    _CACHE_AT = 0.0


def add_many(kind: str, name: str, texts: Iterable[str],
             why: str = "") -> Dict[str, Any]:
    """Cut several passages at once, each on its own fingerprint.

    THIS IS WHAT A DOCUMENT SWATH NEEDS. A swath is assembled fresh every
    round out of whichever consecutive lines are still unused, so the joined
    passage on screen will almost never recur - cutting it whole would record
    something that never matches again. What recurs is the LINE, so one click
    on a swath cuts each of its lines.
    """
    last: Dict[str, Any] = {"ok": True, "cuts": all_cuts(fresh=True)}
    for one in texts:
        line = str(one or "").strip()
        if len(line) < 12:
            continue
        last = add(kind, name, "", line, why)
        if not last.get("ok"):
            return last
    return last


def add(kind: str, name: str, mark: str = "", text: str = "",
        why: str = "") -> Dict[str, Any]:
    """Cut a passage out of every future prompt."""
    kind = str(kind or "").strip()
    if kind not in KINDS:
        return {"ok": False, "why": "that is not a kind of prompt weight: %s" % kind}
    name = str(name or "").strip()
    mark = str(mark or "").strip() or fingerprint(text)
    if not mark:
        return {"ok": False, "why": "there is nothing to cut"}
    with _LOCK:
        cuts = _read()
        for one in cuts:
            if one.get("kind") == kind and one.get("mark") == mark:
                _forget_cache()
                return {"ok": True, "already": True, "cuts": cuts}
        cuts.append({
            "kind": kind,
            "name": name,
            "mark": mark,
            # A LINE OF IT IS KEPT so the list is readable by a person later.
            # Whoever reads this file a month from now needs to know what
            # they cut, and a fingerprint tells them nothing at all.
            "sample": " ".join(str(text or "").split())[:400],
            "why": str(why or "")[:200],
            "at": int(time.time()),
        })
        _write(cuts)
        _forget_cache()
        return {"ok": True, "cuts": cuts}


def remove(kind: str, name: str, mark: str) -> Dict[str, Any]:
    """Put a passage back. Every cut is reversible - see the flow chart.

    `name` is accepted and ignored, for the same reason it is not matched on
    when cutting: the two sides do not always call a chunk the same thing.
    """
    with _LOCK:
        cuts = _read()
        kept = [one for one in cuts
                if not (one.get("kind") == kind and one.get("mark") == mark)]
        if len(kept) == len(cuts):
            return {"ok": True, "missing": True, "cuts": cuts}
        _write(kept)
        _forget_cache()
        return {"ok": True, "cuts": kept}


def is_cut(kind: str, name: str, text: str) -> bool:
    """Has this passage been cut? Asked on the writing path, so it never raises.

    `name` is accepted for call-site readability and deliberately not matched
    on - see the module note on why requiring it would make every crystal cut
    silently ineffective.
    """
    try:
        cuts = all_cuts()
        if not cuts:
            return False
        mark = fingerprint(text)
        for one in cuts:
            if one.get("kind") == kind and one.get("mark") == mark:
                return True
        return False
    except Exception:
        # Declining to exclude is the safe failure: the prompt is a little
        # heavier than asked for, rather than the round not being written.
        return False


def sift(kind: str, items: Iterable[Any], name_of=None, text_of=None) -> List[Any]:
    """Drop the cut ones out of a list of chunks, keeping the rest in order.

    `name_of` and `text_of` pull the two halves of the key out of whatever
    shape the caller's chunks happen to be, so this does not need to know.
    """
    try:
        cuts = all_cuts()
        if not cuts:
            return list(items)
        out = []
        for one in items:
            name = name_of(one) if name_of else ""
            text = text_of(one) if text_of else (one if isinstance(one, str) else "")
            if not is_cut(kind, name, text):
                out.append(one)
        return out
    except Exception:
        return list(items)
