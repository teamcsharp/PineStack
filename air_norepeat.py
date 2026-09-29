"""[no-repeat-24h] NOTHING AIRS TWICE INSIDE A DAY.

The operator, 2026-09-29: "No repeats within 24 hours" of dialogue lines (any
seat, re-airs of banked turns under NEW ids included), SFX clips and music
records. A banked round may still air its first time; its lines just cannot
replay. When nothing new is ready the gap is a ROLLED record, then ROLLED
SFX - never a re-aired line.

This module is the station's one memory of what went out, keyed by a stable
fingerprint that a new line id cannot escape:

  line    the line's words, normalised (line_repeat.normalize: case,
          punctuation and spacing gone), hashed. A line under
          `min_words` words ("Yeah.", "Go on.") is conversation glue, not a
          line, and is not keyed - the dial is on the book.
  sfx     the clip's id (the clip book's sid, sfx_id(path)), else its path.
  record  the track id.

`note()` is written where a thing goes out; `used()` is asked by the
selectors BEFORE they roll (so a refusal is rare) and by the last gate
before air; `refuse()` records every refusal - why, which road, which key -
in a ring and on disk (data/norepeat_refusals.jsonl). Nothing here is
silent and nothing here allows a repeat: a road refused is sent to its next
rolled option by its caller.

Pure and thread-safe; no app imports. The book persists (a restart must not
hand the station its whole day back - the #1225 lesson) and seeds itself
from the station's ledgers the first time it has no file.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any, Callable, Iterable

try:                                     # the station's own normaliser
    import line_repeat as _line_repeat
except Exception:  # noqa: BLE001 - a bare test tree
    _line_repeat = None

KINDS = ("line", "sfx", "record")
WINDOW_S = float(os.getenv("NOREPEAT_WINDOW_S", "86400"))
MIN_WORDS = int(os.getenv("NOREPEAT_MIN_WORDS", "4"))
SAVE_EVERY_S = 30.0
SAVE_EVERY_NOTES = 200
REFUSALS_KEPT = 400
REFUSALS_FILE_MOST = 4 * 1024 * 1024     # the ledger is rotated past this
_SAVE_LOCK = threading.Lock()


def normalize(text: Any) -> str:
    if _line_repeat is not None:
        try:
            return str(_line_repeat.normalize(text) or "")
        except Exception:  # noqa: BLE001
            pass
    s = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in str(text or ""))
    return " ".join(s.split())


def line_key(text: Any, min_words: int | None = None) -> str:
    """The fingerprint of a spoken line: its normalised words, hashed. ""
    for a line too short to be a line (see MIN_WORDS)."""
    words = normalize(text)
    least = MIN_WORDS if min_words is None else int(min_words)
    if not words or len(words.split()) < max(1, least):
        return ""
    return hashlib.sha1(words.encode("utf-8")).hexdigest()[:20]


_SENTENCE_END = "….!?;"


def sentence_keys(text: Any, min_words: int | None = None) -> list[str]:
    """The keys of each whole sentence of a line. A turn is aired in CHUNKS
    (sentence-capped), so the air log holds chunks while a round holds whole
    turns: keying sentences is what lets the two meet whatever the cut."""
    out, cur = [], []
    for ch in str(text or ""):
        cur.append(ch)
        if ch in _SENTENCE_END:
            k = line_key("".join(cur), min_words)
            if k:
                out.append(k)
            cur = []
    k = line_key("".join(cur), min_words)
    if k:
        out.append(k)
    return list(dict.fromkeys(out))


def sfx_key(ident: Any) -> str:
    s = str(ident or "").strip()
    return s[:200] if s else ""


def record_key(track_id: Any) -> str:
    s = str(track_id or "").strip()
    return s[:80] if s else ""


class Book:
    """{kind: {key: [at, road, ref]}} inside the window, on disk."""

    def __init__(self, path: Any, refusals_path: Any = None, window: float = WINDOW_S,
                 min_words: int = MIN_WORDS, clock: Callable[[], float] = time.time,
                 seed: Callable[[], Iterable[tuple[str, str, float, str, str]]] | None = None) -> None:
        self.path = Path(path)
        self.refusals_path = Path(refusals_path) if refusals_path else None
        self.window = float(window)
        self.min_words = int(min_words)
        self.clock = clock
        self.seed = seed
        self.lock = threading.RLock()
        self.rows: dict[str, dict[str, list[Any]]] = {k: {} for k in KINDS}
        self.loaded = False
        self.dirty = 0
        self.saved_at = 0.0
        self.refusals: deque[dict[str, Any]] = deque(maxlen=REFUSALS_KEPT)
        self.counts: Counter[str] = Counter()

    # --- the book -------------------------------------------------------------
    def load(self) -> None:
        with self.lock:
            if self.loaded:
                return
            self.loaded = True
            got: Any = None
            try:
                got = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                got = None
            now = self.clock()
            if isinstance(got, dict):
                for kind in KINDS:
                    for key, row in (got.get(kind) or {}).items():
                        try:
                            if now - float(row[0]) < self.window:
                                self.rows[kind][str(key)] = [float(row[0]), str(row[1] or ""), str(row[2] or "")]
                        except (TypeError, ValueError, IndexError):
                            continue
                return
            # no book yet: the station's own ledgers say what went out today
            if self.seed is not None:
                try:
                    for kind, key, at, road, ref in self.seed():
                        if kind in self.rows and key and now - float(at) < self.window:
                            old = self.rows[kind].get(key)
                            if old is None or float(old[0]) < float(at):
                                self.rows[kind][key] = [float(at), str(road or "seeded"), str(ref or "")]
                except Exception:  # noqa: BLE001 - a seed that fails is a blank memory, as before
                    pass
                self.dirty += 1

    def prune(self) -> int:
        now = self.clock()
        gone = 0
        with self.lock:
            for kind in KINDS:
                old = [k for k, r in self.rows[kind].items() if now - float(r[0]) >= self.window]
                for k in old:
                    del self.rows[kind][k]
                gone += len(old)
        return gone

    def save(self, force: bool = False) -> bool:
        self.load()                      # never write a blank book over a full one
        now = self.clock()
        with self.lock:
            if not force and (not self.dirty or (self.dirty < SAVE_EVERY_NOTES
                                                  and now - self.saved_at < SAVE_EVERY_S)):
                return False
            self.prune()
            snap = {"v": 1, "window": self.window, "saved": now,
                    **{k: dict(v) for k, v in self.rows.items()}}
            self.dirty = 0
            self.saved_at = now
        with _SAVE_LOCK:                 # one writer of the file at a time
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(self.path.suffix + ".tmp")
                tmp.write_text(json.dumps(snap), encoding="utf-8")
                tmp.replace(self.path)
                return True
            except OSError:
                return False             # a book that will not write is still a memory

    def save_due(self) -> bool:
        with self.lock:
            return bool(self.dirty) and (self.dirty >= SAVE_EVERY_NOTES
                                         or self.clock() - self.saved_at >= SAVE_EVERY_S)

    # --- the questions --------------------------------------------------------
    def key(self, kind: str, thing: Any) -> str:
        if kind == "line":
            return line_key(thing, self.min_words)
        if kind == "sfx":
            return sfx_key(thing)
        return record_key(thing)

    def last(self, kind: str, key: str) -> dict[str, Any] | None:
        """The airing inside the window that holds `key` back, or None."""
        if not key:
            return None
        self.load()
        with self.lock:
            row = self.rows.get(kind, {}).get(key)
        if not row:
            return None
        age = self.clock() - float(row[0])
        if age >= self.window:
            return None
        return {"at": float(row[0]), "road": row[1], "ref": row[2], "age": age}

    def used(self, kind: str, key: str) -> bool:
        return self.last(kind, key) is not None

    def text_seen(self, text: Any) -> dict[str, Any] | None:
        """The airing that makes this line a repeat, or None. A repeat is the
        whole line's words heard inside the window, or EVERY keyed sentence of
        it heard (a replayed turn re-cut into different chunks, a chunk of a
        turn heard whole). One stock sentence inside a new line is not a
        repeat of a line - the phrase gates own that question."""
        whole = line_key(text, self.min_words)
        got = self.last("line", whole) if whole else None
        if got:
            return dict(got, key=whole)
        parts = sentence_keys(text, self.min_words)
        if not parts:
            return None
        seen = [self.last("line", k) for k in parts]
        if all(seen):
            last = max(seen, key=lambda r: float(r["at"]))
            return dict(last, key=parts[0])
        return None

    def used_text(self, text: Any) -> bool:
        return self.text_seen(text) is not None

    def fresh(self, kind: str, items: Iterable[Any], keyfn: Callable[[Any], Any] | None = None) -> list[Any]:
        """The items not heard inside the window (order kept). The selectors
        ask this BEFORE they roll, so the roll is among what may air."""
        out = []
        for it in items:
            k = self.key(kind, keyfn(it) if keyfn else it)
            if not k or not self.used(kind, k):
                out.append(it)
        return out

    def note(self, kind: str, key: str, road: str = "", ref: str = "", at: float | None = None) -> None:
        if kind not in self.rows or not key:
            return
        self.load()
        when = float(at if at is not None else self.clock())
        with self.lock:
            old = self.rows[kind].get(key)
            if old is None or float(old[0]) <= when:
                self.rows[kind][key] = [when, str(road or "")[:40], str(ref or "")[:80]]
                self.dirty += 1
                self.counts["noted:" + kind] += 1

    def note_text(self, text: Any, road: str = "", ref: str = "", at: float | None = None) -> str:
        """Note a line that went out: its whole words and each sentence."""
        k = line_key(text, self.min_words)
        if k:
            self.note("line", k, road, ref, at)
        for part in sentence_keys(text, self.min_words):
            if part != k:
                self.note("line", part, road, ref, at)
        return k

    # --- refusals: recorded, never silent ---------------------------------------
    def refuse(self, kind: str, key: str, road: str, why: str = "", text: Any = "",
               ref: str = "", stage: str = "gate") -> dict[str, Any]:
        seen = self.last(kind, key) or {}
        row = {"at": round(self.clock(), 3), "kind": kind, "key": key, "road": str(road or "")[:40],
               "stage": str(stage or "")[:24], "ref": str(ref or "")[:80],
               "why": str(why or ("already on air %d min ago (%s)" % (int(float(seen.get("age") or 0) / 60),
                                                                   seen.get("road") or "?")))[:200],
               "text": " ".join(str(text or "").split())[:140],
               "first_road": seen.get("road"), "first_at": seen.get("at")}
        with self.lock:
            self.refusals.append(row)
            self.counts["refused:%s:%s" % (kind, row["road"])] += 1
        if self.refusals_path is not None:
            try:
                p = self.refusals_path
                if p.exists() and p.stat().st_size > REFUSALS_FILE_MOST:
                    p.replace(p.with_suffix(p.suffix + ".1"))
                with p.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row) + "\n")
            except OSError:
                pass
        return row

    def state(self, most: int = 40) -> dict[str, Any]:
        self.load()
        with self.lock:
            by_road: Counter[str] = Counter()
            for r in self.refusals:
                by_road["%s:%s" % (r["kind"], r["road"])] += 1
            return {"window_h": round(self.window / 3600.0, 2), "min_words": self.min_words,
                    "held": {k: len(v) for k, v in self.rows.items()},
                    "counts": dict(self.counts), "refusals_by_road": dict(by_road),
                    "refusals": list(self.refusals)[-int(most):]}


def seed_rows(air_log: Any = None, music_log: Any = None, sfx_history: Any = None,
              since: float = 0.0, aired: tuple[str, ...] = ("box", "stream", "both", "page"),
              quiet: frozenset[str] = frozenset({"marker", "chat", "image_analysis", "song_analysis", "hangup"}),
              min_words: int = MIN_WORDS, register_db: Any = None):
    """(kind, key, at, road, ref) off the station's ledgers - the book's first
    memory. Each ledger is read line by line; a missing one is skipped.
    `register_db`: System 3's store (system3.sqlite3), whose `lines` table
    keeps every aired line a day and more - read-only - so a first start
    remembers the whole window even when the air log holds less."""
    if register_db:
        try:
            import sqlite3
            con = sqlite3.connect("file:%s?mode=ro" % register_db, uri=True, timeout=5)
            try:
                for line_id, who, text, at in con.execute(
                        "SELECT line_id, who, text, at FROM lines WHERE at >= ?", (float(since),)):
                    if who == "board":
                        continue
                    for k in dict.fromkeys([line_key(text, min_words)] + sentence_keys(text, min_words)):
                        if k:
                            yield "line", k, float(at), "register", str(line_id or "")
            finally:
                con.close()
        except Exception:  # noqa: BLE001 - a store that cannot be read is skipped
            pass
    def _lines(path: Any):
        if not path:
            return
        try:
            with Path(path).open("r", encoding="utf-8") as fh:
                for ln in fh:
                    try:
                        row = json.loads(ln)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        yield row
        except OSError:
            return

    for r in _lines(air_log):
        at = float(r.get("air_at") or r.get("ts") or 0)
        if at < since or str(r.get("aired") or "") not in aired:
            continue
        kind = str(r.get("kind") or "")
        if kind in quiet or r.get("who") in ("analysis",):
            continue
        if kind == "sfx" or r.get("who") == "board":
            continue                     # the clip ledgers below key clips by id
        for k in dict.fromkeys([line_key(r.get("text"), min_words)] + sentence_keys(r.get("text"), min_words)):
            if k:
                yield "line", k, at, kind or "air", str(r.get("id") or "")
    for r in _lines(music_log):
        at = float(r.get("at") or 0)
        if at >= since and not r.get("stop") and r.get("id"):
            yield "record", record_key(r.get("id")), at, str((r.get("s3") or {}).get("lane") or "rotation"), ""
    for r in _lines(sfx_history):
        at = float(r.get("ts") or 0)
        if at >= since and r.get("id"):
            yield "sfx", sfx_key(r.get("id")), at, str(r.get("who") or "sfx"), str(r.get("name") or "")[:80]
