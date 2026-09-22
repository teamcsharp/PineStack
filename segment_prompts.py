"""segment_prompts - THE SEGMENT PROMPT BOOK (#1195 / #1245).

Repo path: spark-agent/segment_prompts.py (a sibling of app.py, imported by it).

"Every segment needs a system prompt that I'm able to edit ... I want to be
able to make and store alternative system prompts that are able to be
dialed back and forth and randomised between the segments" (#1245), and
"type in - speaker box - and basically trigger this to use a random chunk
of speaker box text" (#1195).

ONE SMALL STORE beside the schedule, data/segment_prompts.json:

    {"kinds": {"banter": {"mode": "random",        fixed:<id> | cycle | random
                          "alternatives": [{"id": "sa-..", "name": "..",
                                            "text": "..", "weight": 1,
                                            "on": true, "at": .., "used": 0,
                                            "used_at": 0.0}],
                          "cursor": 0, "last": "sa-..", "at": ..}},
     "uses": [.. the last 300 picks, oldest first ..],
     "at": ..}

WHERE IT SPEAKS.  govern() is called from ONE place - _schedule_clause in
app.py, the choke point every scheduled round passes through: the
torrent's schedule_take() and System2's templates() both build their
prompt there, so the book governs both engines without either knowing
it exists.  Precedence inside the clause: a timed application (#906,
"use it for the next segment") first, then the alternative this kind's
mode dials, then whatever the old per-kind variant shelf holds.  The
COMMANDS are expanded in whichever text wins, so "- speaker box -" typed
into the panel's old prompt desk works exactly as it does here.

MEMOISED PER OCCURRENCE.  schedule_take() is read by the panel poll and
the coordinator as well as by the show, so a draw made on every call
would be a draw made by whoever happened to be looking (the #1091/#1093
lesson).  One key per (kind, entry, occurrence): the same segment always
gets the same words, and the next segment of that kind gets the next
draw - which is what "randomised between the segments" means.

THE HOST installs the module with its own globals - install(globals(),
DATA_DIR), the way system2_runtime holds `self.host` - and everything
this file needs from the station is read through that dict AT CALL TIME:
the chunk ledger, the speakbox shelf, the modifiers, the plotline, _RADIO.
Nothing here may take the show off air: every public function answers a
harmless default on any fault.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import Any

MARK = "[#1195]"

_HOST: dict[str, Any] = {}
_PATH: Path | None = None
_LOCK = RLock()
_BOOK: dict[str, Any] = {"kinds": {}, "uses": [], "at": 0.0}
_READ = [False]

FIXED = "fixed:"
MODES = ("cycle", "random")
ALT_MOST = 24                 # alternatives a kind may hold
TEXT_MOST = 4000
NAME_MOST = 80
USES_KEEP = 300               # picks remembered in the book
WEIGHT_MAX = 9
CHUNK_LINES = 4               # consecutive gem lines in one passage
CHUNK_CHARS = 420
RANDOM_MOST = 6               # {{speakbox:random:N}} ceiling
MEMO_MOST = 240               # occurrence records held in memory
RIDES_MOST = 240
NEEDLE_CHARS = 140
RECENT_CHUNKS = 60            # passages this desk will not hand out twice running

_MEMO: dict[str, dict[str, Any]] = {}     # occurrence key -> pick record
_RIDES: dict[str, dict[str, Any]] = {}    # round sid -> compact pick
_RECENT: list[str] = []                   # chunk keys handed out lately

_SPEAKER = re.compile(r"-\s*speaker\s*box\s*-", re.I)
_BRACE = re.compile(r"\{\{\s*([A-Za-z_]+)\s*(?::\s*([^}]*?))?\s*\}\}")
_DOCISH = re.compile(r"\.(md|txt|markdown)$", re.I)

GRAMMAR: tuple[dict[str, str], ...] = (
    {"cmd": "- speaker box -",
     "says": "one random passage out of the speaker box, drawn when the "
             "segment is written"},
    {"cmd": "{{speakbox}}", "says": "the same as - speaker box -"},
    {"cmd": "{{speakbox:doc.md}}",
     "says": "a passage from that one document"},
    {"cmd": "{{speakbox:random:3}}",
     "says": "three passages from three different documents (up to six)"},
    {"cmd": "{{topic}}",
     "says": "the topic on the table - the standing topic, else tonight's "
             "theme"},
    {"cmd": "{{caller}}", "says": "the name of the next caller on the shelf"},
    {"cmd": "{{plot}}", "says": "the storyline's act that is due now"},
)


# --- the host --------------------------------------------------------------

def install(host: dict[str, Any], data_dir: Any = None) -> None:
    """Hand the book the station's globals (a LIVE dict - functions defined
    after this call are still found at call time) and where data lives."""
    global _HOST
    _HOST = host if isinstance(host, dict) else {}
    if data_dir is not None:
        path(data_dir)


def _h(name: str, default: Any = None) -> Any:
    try:
        return _HOST.get(name, default)
    except Exception:  # noqa: BLE001
        return default


def path(data_dir: Any = None) -> Path:
    global _PATH
    if _PATH is None or data_dir is not None:
        base = Path(str(data_dir)) if data_dir is not None else Path("data")
        _PATH = base / "segment_prompts.json"
    return _PATH


# --- the store (pattern A: read once, held, written atomically) ----------------

def kind_key(kind: Any) -> str:
    return str(kind or "").strip().lower()[:40]


def _alt_row(raw: Any) -> dict[str, Any]:
    """One alternative, scrubbed.  {} when there are no words in it."""
    try:
        row = raw if isinstance(raw, dict) else {}
        text = str(row.get("text") or "")[:TEXT_MOST]
        if not text.strip():
            return {}
        try:
            weight = max(1, min(WEIGHT_MAX, int(row.get("weight") or 1)))
        except (TypeError, ValueError):
            weight = 1

        def _num(key: str) -> float:
            try:
                return float(row.get(key) or 0)
            except (TypeError, ValueError):
                return 0.0
        on = row.get("on")
        return {
            "id": (str(row.get("id") or "").strip()[:64]
                   or "sa-" + uuid.uuid4().hex[:10]),
            "name": str(row.get("name") or "Untitled").strip()[:NAME_MOST]
                    or "Untitled",
            "text": text,
            "weight": weight,
            "on": True if on is None else bool(on),
            "at": round(_num("at") or time.time(), 3),
            "used": max(0, int(_num("used"))),
            "used_at": round(_num("used_at"), 3),
        }
    except Exception:  # noqa: BLE001
        return {}


def _mode_ok(mode: Any, alts: list[dict[str, Any]]) -> str:
    got = str(mode or "").strip().lower()[:80]
    if got in MODES:
        return got
    if got.startswith(FIXED) and any(a["id"] == got[len(FIXED):] for a in alts):
        return got
    return FIXED + alts[0]["id"] if alts else ""


def _entry_row(raw: Any) -> dict[str, Any]:
    try:
        row = raw if isinstance(raw, dict) else {}
        alts: list[dict[str, Any]] = []
        for one in (row.get("alternatives") or []):
            got = _alt_row(one)
            if got and all(got["id"] != a["id"] for a in alts):
                alts.append(got)
        alts = alts[:ALT_MOST]
        if not alts:
            return {}
        try:
            cursor = max(0, int(row.get("cursor") or 0))
        except (TypeError, ValueError):
            cursor = 0
        try:
            at = float(row.get("at") or 0) or time.time()
        except (TypeError, ValueError):
            at = time.time()
        return {"mode": _mode_ok(row.get("mode"), alts),
                "alternatives": alts,
                "cursor": cursor % len(alts),
                "last": str(row.get("last") or "")[:64],
                "at": round(at, 3)}
    except Exception:  # noqa: BLE001
        return {}


def read(fresh: bool = False) -> dict[str, Any]:
    """The book - off disk once, held in memory after that."""
    if _READ[0] and not fresh:
        return _BOOK
    with _LOCK:
        if _READ[0] and not fresh:
            return _BOOK
        kinds: dict[str, Any] = {}
        uses: list[dict[str, Any]] = []
        p = path()
        try:
            if p.exists():
                got = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(got, dict):
                    for key, blob in (got.get("kinds") or {}).items():
                        row = _entry_row(blob)
                        if row:
                            kinds[kind_key(key)] = row
                    uses = [u for u in (got.get("uses") or [])
                            if isinstance(u, dict)][-USES_KEEP:]
        except Exception:  # noqa: BLE001
            # An unreadable book is never clobbered blank: it is set aside
            # under a dated name, and the station carries on with an empty
            # one.  Nothing on air depends on this file existing.
            try:
                p.replace(p.with_name(p.name + ".broken-%d" % int(time.time())))
            except Exception:  # noqa: BLE001
                pass
            kinds, uses = {}, []
        _BOOK["kinds"] = kinds
        _BOOK["uses"] = uses
        _READ[0] = True
        return _BOOK


def write() -> None:
    """Atomically; a write that will not land leaves the book standing in
    memory rather than throwing, because the caller may be the air path."""
    with _LOCK:
        try:
            del _BOOK["uses"][:-USES_KEEP]
            _BOOK["at"] = round(time.time(), 3)
            p = path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({"kinds": _BOOK["kinds"],
                                       "uses": _BOOK["uses"],
                                       "at": _BOOK["at"]}, indent=1),
                           encoding="utf-8")
            tmp.replace(p)
        except Exception:  # noqa: BLE001
            pass


def entry(kind: Any) -> dict[str, Any] | None:
    """The kind's entry, or None when nothing has been saved for it."""
    try:
        return read()["kinds"].get(kind_key(kind))
    except Exception:  # noqa: BLE001
        return None


def has_alternatives(kind: Any) -> bool:
    """True when at least one alternative is switched ON for this kind -
    the question schedule_take() asks before it bothers building a clause."""
    try:
        row = entry(kind)
        return bool(row and any(a.get("on") for a in row["alternatives"]))
    except Exception:  # noqa: BLE001
        return False


def mode_says(row: dict[str, Any] | None) -> str:
    if not row:
        return "nothing saved for this kind yet"
    alts = [a for a in row.get("alternatives") or []]
    on = [a for a in alts if a.get("on")]
    mode = str(row.get("mode") or "")
    if mode.startswith(FIXED):
        want = mode[len(FIXED):]
        one = next((a for a in alts if a["id"] == want), None)
        return ("fixed on “%s”" % (one["name"] if one else want)
                + ("" if (one and one.get("on")) else
                   " - which is switched off, so the first one that is on "
                   "speaks instead"))
    if mode == "cycle":
        return "cycling through the %d that are on, in turn" % len(on)
    return ("random over the %d that are on, weighted, never the same one "
            "twice running" % len(on))


def entry_view(kind: Any) -> dict[str, Any]:
    """The kind's shelf as the editor wants it - every alternative, the
    mode, and which one the mode would dial NEXT (with no side effects)."""
    key = kind_key(kind)
    row = entry(key)
    if not row:
        return {"kind": key, "mode": "", "alternatives": [], "on": 0,
                "next": None, "says": mode_says(None)}
    peek = _dial(json.loads(json.dumps(row)), advance=False)
    return {"kind": key, "mode": row["mode"],
            "alternatives": [dict(a) for a in row["alternatives"]],
            "on": sum(1 for a in row["alternatives"] if a.get("on")),
            "next": ({"id": peek["id"], "name": peek["name"]}
                     if peek else None),
            "cursor": row.get("cursor", 0), "last": row.get("last", ""),
            "says": mode_says(row)}


def book_view() -> dict[str, Any]:
    book = read()
    return {"kinds": {k: entry_view(k) for k in sorted(book["kinds"])},
            "uses": list(book["uses"])[-60:][::-1],
            "grammar": [dict(g) for g in GRAMMAR],
            "at": book.get("at", 0.0)}


def _forget(kind: str) -> None:
    """An edit re-resolves the segment on air: the occurrence records for
    this kind are dropped so the next clause build reads the new shelf."""
    for key in [k for k, r in _MEMO.items() if r.get("kind") == kind]:
        _MEMO.pop(key, None)
    try:
        radio = _h("_RADIO")
        if isinstance(radio, dict):
            radio["sched_prompt"] = ""      # the entry re-reads on the next round
    except Exception:  # noqa: BLE001
        pass


def put_alternative(kind: Any, raw: Any) -> dict[str, Any]:
    """Save one alternative under its name, or rewrite the one its `id`
    names.  The first alternative a kind ever gets becomes its fixed
    choice, so saving never changes the mode underneath the operator."""
    key = kind_key(kind)
    if not key:
        raise ValueError("name the kind of segment")
    row = _alt_row(raw)
    if not row:
        raise ValueError("there are no words in it")
    with _LOCK:
        book = read()
        cur = book["kinds"].get(key) or {"mode": "", "alternatives": [],
                                         "cursor": 0, "last": "", "at": 0.0}
        alts = list(cur.get("alternatives") or [])
        want = str((raw if isinstance(raw, dict) else {}).get("id")
                   or "").strip()[:64]
        found = next((a for a in alts if want and a["id"] == want), None)
        if found is not None:
            row["id"] = found["id"]
            row["at"] = found.get("at") or row["at"]
            row["used"] = int(found.get("used") or 0)
            row["used_at"] = float(found.get("used_at") or 0)
            alts[alts.index(found)] = row
        else:
            if len(alts) >= ALT_MOST:
                raise ValueError("this kind already holds %d alternatives - "
                                 "delete one first" % ALT_MOST)
            alts.append(row)
        cur["alternatives"] = alts
        cur["mode"] = _mode_ok(cur.get("mode"), alts)
        cur["at"] = round(time.time(), 3)
        book["kinds"][key] = _entry_row(cur) or cur
        write()
    _forget(key)
    return dict(row)


def patch_alternative(kind: Any, aid: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Change a switch, a weight, a name or the words of one alternative."""
    key = kind_key(kind)
    row = entry(key)
    want = str(aid or "").strip()[:64]
    found = next((a for a in (row or {}).get("alternatives") or []
                  if a["id"] == want), None)
    if not row or found is None:
        raise KeyError("no alternative %r on the %s shelf" % (want, key or "?"))
    merged = dict(found)
    for name in ("name", "text", "weight", "on"):
        if name in (fields or {}):
            merged[name] = fields[name]
    merged["id"] = found["id"]
    return put_alternative(key, merged)


def drop_alternative(kind: Any, aid: str) -> bool:
    """Take one off the shelf.  The last one going takes the kind's entry
    with it, so the old variant shelf and the seed govern again."""
    key = kind_key(kind)
    want = str(aid or "").strip()[:64]
    with _LOCK:
        book = read()
        row = book["kinds"].get(key)
        if not row:
            return False
        alts = [a for a in row["alternatives"] if a["id"] != want]
        if len(alts) == len(row["alternatives"]):
            return False
        if not alts:
            book["kinds"].pop(key, None)
        else:
            row["alternatives"] = alts
            row["mode"] = _mode_ok(row.get("mode"), alts)
            row["cursor"] = int(row.get("cursor") or 0) % len(alts)
            if row.get("last") == want:
                row["last"] = ""
            row["at"] = round(time.time(), 3)
        write()
    _forget(key)
    return True


def set_mode(kind: Any, mode: Any) -> str:
    """fixed:<id> | cycle | random.  A kind with nothing saved has no mode."""
    key = kind_key(kind)
    with _LOCK:
        book = read()
        row = book["kinds"].get(key)
        if not row:
            raise KeyError("nothing is saved for %s yet - save an alternative "
                           "first" % (key or "?"))
        got = _mode_ok(mode, row["alternatives"])
        if got != str(mode or "").strip().lower()[:80]:
            raise ValueError("mode must be cycle, random, or fixed:<the id of "
                             "an alternative on this shelf>")
        row["mode"] = got
        row["at"] = round(time.time(), 3)
        write()
    _forget(key)
    return got


# --- the dial --------------------------------------------------------------

def _dial(row: dict[str, Any], advance: bool = True) -> dict[str, Any] | None:
    """Which alternative speaks, by the kind's mode.  `advance` moves the
    cycle pointer and remembers the pick; the editor's preview passes
    False and sees what would come next without spending it."""
    alts = [a for a in (row.get("alternatives") or []) if a.get("on")]
    if not alts:
        return None
    mode = str(row.get("mode") or "")
    if mode.startswith(FIXED):
        want = mode[len(FIXED):]
        pick = next((a for a in alts if a["id"] == want), alts[0])
    elif mode == "cycle":
        cur = int(row.get("cursor") or 0) % len(alts)
        pick = alts[cur]
        if advance:
            row["cursor"] = (cur + 1) % len(alts)
    else:
        pool = alts
        last = str(row.get("last") or "")
        if len(alts) > 1 and last:
            # Never the same one twice running: "randomised between the
            # segments" is only audible when consecutive segments differ.
            pool = [a for a in alts if a["id"] != last] or alts
        pick = random.choices(
            pool, weights=[max(1, int(a.get("weight") or 1)) for a in pool],
            k=1)[0]
    if advance:
        row["last"] = pick["id"]
        pick["used"] = int(pick.get("used") or 0) + 1
        pick["used_at"] = round(time.time(), 3)
    return pick


def dial_preview(kind: Any) -> dict[str, Any] | None:
    """The alternative the mode would hand the NEXT segment of this kind,
    with nothing spent - what the editor shows in the box."""
    row = entry(kind)
    if not row:
        return None
    try:
        pick = _dial(json.loads(json.dumps(row)), advance=False)
    except Exception:  # noqa: BLE001
        return None
    if not pick:
        return None
    on = sum(1 for a in row["alternatives"] if a.get("on"))
    return {"id": pick["id"], "name": pick["name"], "text": pick["text"],
            "mode": row["mode"], "of": on,
            "says": ("the “%s” alternative in the segment prompt "
                     "book - %s" % (pick["name"], mode_says(row)))}


# --- the commands ----------------------------------------------------------

def _ledger_rows() -> list[dict[str, Any]]:
    """Every passage the chunk ledger holds - the existing speaker box
    chunk store (#1042), in memory, no disk read on the air path."""
    try:
        lock = _h("_CHUNK_LOCK")
        all_ = _h("_chunk_all")
        if not callable(all_):
            return []
        if lock is not None:
            with lock:
                rows = list(all_().values())
        else:
            rows = list(all_().values())
        return [r for r in rows if isinstance(r, dict)
                and str(r.get("text") or "").strip() and r.get("file")]
    except Exception:  # noqa: BLE001
        return []


def _remember_chunk(key: str) -> None:
    if not key:
        return
    if key in _RECENT:
        _RECENT.remove(key)
    _RECENT.append(key)
    del _RECENT[:-RECENT_CHUNKS]


def _doc_matches(name: str, want: str) -> bool:
    a = str(name or "").strip().lower()
    b = str(want or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    return _DOCISH.sub("", a) == _DOCISH.sub("", b)


def _chunk_from_document(doc: str, kind: str, stamp: bool) -> dict[str, Any] | None:
    """A passage read off a document itself - the cached gems when the
    harvest has been, the document's own lines when it has not.  Only
    reached when the ledger holds nothing for the ask."""
    try:
        files_of = _h("speakbox_all") if doc else _h("speakbox_files")
        files = list(files_of("")) if callable(files_of) else []
        if doc:
            files = [p for p in files if _doc_matches(getattr(p, "name", ""), doc)]
        if not files:
            return None
        picked = random.choice(files)
        gems = _h("speakbox_gems")
        lines = list(gems(picked, "")) if callable(gems) else []
        if not lines:
            body_of, lines_of = _h("speakbox_body"), _h("speakbox_lines")
            if callable(body_of) and callable(lines_of):
                lines = list(lines_of(body_of(picked)))
        lines = [str(x) for x in lines if str(x or "").strip()]
        if not lines:
            return None
        start = random.randrange(len(lines))
        text = " ".join(lines[start:start + CHUNK_LINES])[:CHUNK_CHARS].strip()
        if not text:
            return None
        if stamp:
            serve = _h("chunk_serve")
            if callable(serve):
                serve("prompt", text, file=picked.name, road=kind)
        return {"doc": picked.name, "text": text, "from": "document"}
    except Exception:  # noqa: BLE001
        return None


def _chunk(doc: str, kind: str, avoid: list[str], stamp: bool) -> dict[str, Any] | None:
    """One passage: from the named document, or from anywhere on the shelf
    but not a document already drawn in this expansion.  Rested longest
    leads, the operator's favourites lead more, and nothing this desk
    handed out lately comes straight back."""
    rows = _ledger_rows()
    now = time.time()
    if doc:
        pool = [r for r in rows if _doc_matches(str(r.get("file") or ""), doc)]
        if not pool:
            return _chunk_from_document(doc, kind, stamp)
    else:
        pool = [r for r in rows if str(r.get("file") or "") not in avoid] or rows
        if not pool:
            return _chunk_from_document("", kind, stamp)
    fresh = [r for r in pool if str(r.get("key") or "") not in _RECENT] or pool
    try:
        weights = [1.0 + min(24.0, (now - float(r.get("last") or 0)) / 3600.0)
                   + (3.0 if r.get("liked") else 0.0) for r in fresh]
        row = random.choices(fresh, weights=weights, k=1)[0]
    except Exception:  # noqa: BLE001
        row = random.choice(fresh)
    text = " ".join(str(row.get("text") or "").split())[:CHUNK_CHARS].strip()
    if not text:
        return None
    _remember_chunk(str(row.get("key") or ""))
    if stamp:
        try:
            serve = _h("chunk_serve")
            if callable(serve):
                serve("prompt", text, file=str(row.get("file") or ""),
                      mind=str(row.get("mind") or ""), road=kind)
        except Exception:  # noqa: BLE001
            pass
    return {"doc": str(row.get("file") or ""), "text": text,
            "key": str(row.get("key") or ""), "from": "ledger"}


def _render(chunk: dict[str, Any]) -> str:
    return "“%s” (speaker box: %s)" % (chunk["text"], chunk["doc"])


def _topic() -> str:
    try:
        standing = _h("modifiers_standing")
        rows = list(standing()) if callable(standing) else []
        names = [str(r.get("name") or "") for r in rows
                 if str(r.get("kind") or "") == "topic" and r.get("name")]
        if names:
            return ", ".join(names[:3])
    except Exception:  # noqa: BLE001
        pass
    try:
        theme = _h("theme_owns_air")
        got = theme() if callable(theme) else {}
        return str((got or {}).get("name") or (got or {}).get("text") or "")[:200]
    except Exception:  # noqa: BLE001
        return ""


def _caller() -> str:
    try:
        shelf = _h("_SHELF") or {}
        for row in list(shelf.get("caller") or []):
            if not isinstance(row, dict):
                continue
            ent = row.get("entry") if isinstance(row.get("entry"), dict) else row
            name = str(ent.get("caller_name") or row.get("caller_name") or "")
            if name.strip():
                return name.strip()[:80]
    except Exception:  # noqa: BLE001
        pass
    return ""


def _plot() -> str:
    try:
        owns, act_now = _h("plot_owns_air"), _h("plot_act_now")
        plt = owns() if callable(owns) else {}
        if not plt:
            return ""
        act, at, of = act_now(plt) if callable(act_now) else ("", 0, 0)
        title = str(plt.get("title") or "the storyline")
        if act:
            return "%s - act %d of %d: %s" % (title, at, of, str(act)[:400])
        return title
    except Exception:  # noqa: BLE001
        return ""


def expand(text: str, kind: str, stamp: bool = True) -> tuple[str, list[dict[str, Any]]]:
    """The grammar, applied.  Returns the text with every command replaced
    and one record per command saying what it became - or why it did not
    (a `miss`), because an instruction that quietly vanished is the kind
    of fault nobody hears until the show is wrong."""
    text = str(text or "")
    if not text or ("{{" not in text and not _SPEAKER.search(text)):
        return text, []
    kind = kind_key(kind)
    expansions: list[dict[str, Any]] = []
    drawn: list[str] = []

    def _record(cmd: str, arg: str, got: str, doc: str = "", miss: str = "") -> None:
        expansions.append({"cmd": cmd, "arg": arg, "doc": doc,
                           "chars": len(got), "head": got[:160],
                           **({"miss": miss} if miss else {})})

    def _speak(arg: str) -> str:
        arg = str(arg or "").strip()
        low = arg.lower()
        if low.startswith("random"):
            try:
                n = int(low.split(":", 1)[1]) if ":" in low else 1
            except (TypeError, ValueError):
                n = 1
            n = max(1, min(RANDOM_MOST, n))
            parts: list[str] = []
            for _ in range(n):
                got = _chunk("", kind, drawn, stamp)
                if not got:
                    break
                drawn.append(got["doc"])
                parts.append(_render(got))
                _record("speakbox", arg, got["text"], got["doc"])
            if not parts:
                _record("speakbox", arg, "", miss="the speaker box had nothing to hand out")
            return "\n".join(parts)
        got = _chunk(arg, kind, drawn, stamp)
        if not got:
            _record("speakbox", arg, "", miss=(
                "no document called %s in the speaker box" % arg if arg
                else "the speaker box had nothing to hand out"))
            return ""
        drawn.append(got["doc"])
        _record("speakbox", arg, got["text"], got["doc"])
        return _render(got)

    def _sub(match: re.Match[str]) -> str:
        name = str(match.group(1) or "").lower()
        arg = str(match.group(2) or "")
        if name in ("speakbox", "speakerbox", "speaker_box"):
            return _speak(arg)
        if name == "topic":
            got = _topic()
            _record("topic", arg, got, miss="" if got else "no topic is standing")
            return got
        if name == "caller":
            got = _caller()
            _record("caller", arg, got, miss="" if got else "no caller is on the shelf")
            return got
        if name == "plot":
            got = _plot()
            _record("plot", arg, got, miss="" if got else "no storyline owns the air")
            return got
        return match.group(0)            # not a command of ours: left as typed

    try:
        out = _SPEAKER.sub(lambda m: _speak(""), text)
        out = _BRACE.sub(_sub, out)
    except Exception:  # noqa: BLE001
        return text, expansions
    return out, expansions


# --- the one road the writing room takes --------------------------------------

def memo_key(kind: Any, slot_id: Any = "", occurrence: Any = "") -> str:
    occ = str(occurrence or "").strip()
    if not occ:
        occ = "t%d" % int(time.time() // 600)   # no clock: ten-minute buckets
    return "%s|%s|%s" % (kind_key(kind), str(slot_id or "")[:48], occ[:64])


def _needle(text: str) -> str:
    flat = " ".join(str(text or "").split())
    return flat[:NEEDLE_CHARS]


def _compact(rec: dict[str, Any], words: bool = True) -> dict[str, Any]:
    out = {"kind": rec.get("kind", ""), "alt": rec.get("alt", ""),
           "name": rec.get("name", ""), "mode": rec.get("mode", ""),
           "of": rec.get("of", 0), "source": rec.get("source", ""),
           "at": rec.get("at", 0.0),
           "expanded": [dict(e) for e in (rec.get("expanded") or [])][:8]}
    if words:
        out["instruction"] = str(rec.get("text") or "")[:600]
    return out


def govern(kind: Any, text: str, key: str, dial: bool = True,
           stamp: bool = True) -> str:
    """THE ENTRY POINT.  The standing instruction this occurrence writes
    with: an alternative if the kind's mode dials one, else `text` as
    handed in; then the commands expanded.  Memoised on `key` so the
    poll cannot re-roll a segment; an operator edit clears the memo."""
    kind = kind_key(kind)
    text = str(text or "")
    if not kind:
        return text
    finger = hashlib.sha1(("%d|%s" % (int(bool(dial)), text)).encode("utf-8")).hexdigest()
    held = _MEMO.get(key) if stamp else None
    if held and held.get("input") == finger:
        return str(held.get("text") or "")
    row = entry(kind) if dial else None
    pick = None
    source = "shelf" if text.strip() else "none"
    if row:
        try:
            with _LOCK:
                pick = _dial(row, advance=stamp)
                if pick and stamp:
                    write()                 # the pointer, the tally
        except Exception:  # noqa: BLE001
            pick = None
        if pick:
            text = str(pick.get("text") or "")
            source = "alternative"
    out, expansions = expand(text, kind, stamp=stamp)
    if not pick and not expansions:
        return out                          # nothing happened: no paperwork
    rec = {"at": round(time.time(), 3), "kind": kind, "key": key,
           "alt": str(pick["id"]) if pick else "",
           "name": str(pick["name"]) if pick else "",
           "mode": str(row.get("mode") or "") if row else "",
           "of": (sum(1 for a in row["alternatives"] if a.get("on"))
                  if row else 0),
           "source": source, "expanded": expansions,
           "needle": _needle(out), "text": out, "input": finger}
    if stamp:
        _MEMO[key] = rec
        while len(_MEMO) > MEMO_MOST:
            _MEMO.pop(next(iter(_MEMO)), None)
        try:
            with _LOCK:
                read()["uses"].append(_compact(rec, words=False) | {"key": key})
                write()
        except Exception:  # noqa: BLE001
            pass
    return out


def find_in(prompt: str) -> dict[str, Any] | None:
    """Which pick is inside this prompt - the reverse lookup the model-call
    ring and the provenance card use.  Newest first, by the instruction's
    own opening words; a prompt that carries none answers None."""
    try:
        hay = " ".join(str(prompt or "").split())
        if not hay:
            return None
        for rec in reversed(list(_MEMO.values())):
            needle = str(rec.get("needle") or "")
            if len(needle) >= 12 and needle in hay:
                return _compact(rec)
    except Exception:  # noqa: BLE001
        pass
    return None


def now_for(kind: Any) -> dict[str, Any] | None:
    """The pick governing the entry ON AIR for this kind - the occurrence
    the clock is standing on first, else the newest record of the kind."""
    key = kind_key(kind)
    try:
        radio = _h("_RADIO") or {}
        pos = radio.get("sched_pos") or {}
        want = memo_key(key, pos.get("slot_id") or "", pos.get("occurrence") or "")
        rec = _MEMO.get(want)
        if rec:
            return _compact(rec)
        for rec in reversed(list(_MEMO.values())):
            if rec.get("kind") == key:
                return _compact(rec)
    except Exception:  # noqa: BLE001
        pass
    return None


def ride(sid: str, brief: str = "", kind: str = "") -> dict[str, Any] | None:
    """Record which pick shaped the round called `sid` - asked where the
    sid is minted.  A prepared round names its own brief and is matched
    through it; a live round is the occurrence on air."""
    try:
        sid = str(sid or "")
        if not sid:
            return None
        rec = find_in(brief) if brief else None
        if not rec:
            radio = _h("_RADIO") or {}
            rec = now_for(kind or str(radio.get("sched_kind") or ""))
        if not rec:
            return None
        _RIDES[sid] = rec
        while len(_RIDES) > RIDES_MOST:
            _RIDES.pop(next(iter(_RIDES)), None)
        return rec
    except Exception:  # noqa: BLE001
        return None


def for_sid(sid: str) -> dict[str, Any] | None:
    """The ledger's stamp for a round: small, an id list rather than the
    words, the way `mods` rides (#1169)."""
    try:
        rec = _RIDES.get(str(sid or ""))
        if not rec:
            return None
        return {"alt": rec.get("alt", ""), "name": rec.get("name", ""),
                "mode": rec.get("mode", ""), "of": rec.get("of", 0),
                "source": rec.get("source", ""),
                "docs": [str(e.get("doc") or "") for e in (rec.get("expanded") or [])
                         if e.get("doc")][:6],
                "cmds": [str(e.get("cmd") or "") for e in (rec.get("expanded") or [])][:8]}
    except Exception:  # noqa: BLE001
        return None


def uses_for(kind: Any = "", most: int = 20) -> list[dict[str, Any]]:
    key = kind_key(kind)
    try:
        rows = [u for u in read()["uses"] if not key or u.get("kind") == key]
        return list(rows)[-max(1, int(most)):][::-1]
    except Exception:  # noqa: BLE001
        return []


# --- what a "kind" is, when the ledger names a document --------------------------

def is_doc(kind: Any) -> bool:
    """A ledger round named after a speaker box document - `fmn1.md` - is
    a SEED, not a road (#1245)."""
    return bool(_DOCISH.search(str(kind or "").strip()))


def road_of(kind: Any, known: Any = None, fallback: str = "banter") -> str:
    """The road a prompt for this `kind` is keyed on.  A known road is
    itself; a document name is the road of the newest ledger round that
    carried it as its `source`, else the booth (`banter`), which is what
    an unnamed conversation is."""
    key = kind_key(kind)
    roads = tuple(known or ()) or tuple(_h("SCHEDULE_KIND_NAMES") or ())
    if not key:
        return fallback
    if key in roads or not is_doc(key):
        return key
    try:
        rows_of = _h("script_ledger_rows")
        rows = list(rows_of()) if callable(rows_of) else []
        for row in reversed(rows):
            if _doc_matches(str(row.get("source") or ""), key):
                got = kind_key(row.get("round"))
                if got and not is_doc(got):
                    return got
    except Exception:  # noqa: BLE001
        pass
    return fallback


def seed_for(kind: Any, label: str = "", blurb: str = "", want: str = "") -> str:
    """The last resort, so the box is never empty: a plain instruction
    built from what the station already says this kind is."""
    key = kind_key(kind)
    name = str(label or key or "this").strip()
    about = " ".join(str(blurb or want or "").split())
    about = re.sub(r"\s*\([a-z_0-9]+\)\s*$", "", about).rstrip(". ")
    out = "This is the “%s” segment." % name
    if about:
        out += " %s." % about[:400]
    out += (" Do the segment's job in your own voices - talk to each other, "
            "answer what was just said, and hand back to the music when it "
            "is done.")
    return out


def grammar() -> list[dict[str, str]]:
    return [dict(g) for g in GRAMMAR]
