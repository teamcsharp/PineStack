"""phrase_trace - where a phrase said on air comes from, and what a ban needs.

[#1230 / #1239 / #1241] The operator searches a word in the Script view's
"on the air" popup and asks three things of it: WHERE the phrase is written
(a persona, a prompt, a crystal shard, a caller theme, a banked round, a code
template), a way to REMOVE it from every one of those places, and a promise
that it is NEVER SAID AGAIN.

This module is the pure half: matching, snippets, JSON/text/code walkers,
grouping by layer, and the sentence-level strip a phrase ban uses at the
mouth. It imports nothing from the station; app.py wires the live stores in
(`phrase_trace_walk`, `phrase_ban_apply`) and owns every lock and write.

Everything here is meant to run on a thread with a memo in front of it: the
stores it walks are big (the prepared shelf is 30 MB on disk), and nothing
that walks them may run on the event loop (memory: event-loop-starvation-
watchdog, loop-profile-and-desk-locks).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterable

# The four layers the popup shows, in the order it shows them.
LAYERS: tuple[tuple[str, str, str], ...] = (
    ("prompts", "Prompts",
     "the personas, the prompt book, the road templates and the code that writes them"),
    ("crystal", "The crystal",
     "the crystals, their notes, the rhyme families and the documents the minds were built from"),
    ("topics", "Topics",
     "the caller themes, the plotlines, the topic bank and the caller stories"),
    ("scripts", "Scripts",
     "banked rounds, gold bars, the response bank, the pantry, the call log and what was already said"),
)

# What "kills it" means for a source. `code` and `file` have no runtime
# action - the ban covers them at the mouth and the writer is told.
KILLS: dict[str, str] = {
    "strip": "remove the phrase from this text",
    "drop": "remove this entry",
    "deactivate": "switch this off",
    "retire": "retire this round to the desk",
    "forget": "strike it from the said-lines memory",
    "no_rerun": "never re-air this call",
    "code": "built into the code - the ban covers it at the mouth",
    "file": "a document on disk - the ban covers it at the mouth",
    "": "",
}

SNIPPET_WIDTH = 150


def normalize(needle: Any) -> str:
    return " ".join(str(needle or "").lower().split())


_PAT_MEMO: dict[str, re.Pattern[str]] = {}


def pattern(needle: Any) -> re.Pattern[str] | None:
    """The phrase as a regex: word-bounded at both ends (lookarounds, so a
    phrase inside quotes or after a dash still matches), whitespace-tolerant
    between its words, and lenient about a short suffix so "explore" finds
    "explored" and "dimming light" finds "dimming lights"."""
    n = normalize(needle)
    if len(n) < 2:
        return None
    got = _PAT_MEMO.get(n)
    if got is None:
        body = r"\s+".join(re.escape(w) for w in n.split())
        got = re.compile(r"(?<![a-z0-9])" + body + r"[a-z]{0,3}(?![a-z0-9])",
                         re.IGNORECASE)
        if len(_PAT_MEMO) > 512:
            _PAT_MEMO.clear()
        _PAT_MEMO[n] = got
    return got


def hits(needle: Any, text: Any) -> int:
    pat = pattern(needle)
    if pat is None or not text:
        return 0
    return len(pat.findall(str(text)))


def snippet(text: Any, needle: Any, width: int = SNIPPET_WIDTH) -> str:
    """A window of the text around its first hit, ellipsised."""
    t = " ".join(str(text or "").split())
    if not t:
        return ""
    pat = pattern(needle)
    m = pat.search(t) if pat else None
    if not m:
        return t[:width] + ("…" if len(t) > width else "")
    half = max(20, (width - (m.end() - m.start())) // 2)
    start = max(0, m.start() - half)
    end = min(len(t), m.end() + half)
    out = t[start:end]
    if start > 0:
        out = "…" + out
    if end < len(t):
        out = out + "…"
    return out


def source_id(store: str, key: Any) -> str:
    raw = f"{store}|{key}"
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:16]


def make_source(layer: str, store: str, key: Any, text: Any, needle: Any,
                kill: str = "", count: int | None = None, **meta: Any) -> dict[str, Any]:
    """One place the phrase is written. `key` is what the kill needs to find
    it again (a JSON path, an id, a def name); `meta` is what the operator
    sees beside it (who, file, line, label, road)."""
    n = hits(needle, text) if count is None else int(count)
    row = {"id": source_id(store, key), "layer": layer, "store": store,
           "key": key if isinstance(key, (list, dict)) else str(key),
           "count": max(1, n), "snippet": snippet(text, needle),
           "kill": kill if kill in KILLS else "", "kill_label": KILLS.get(kill, "")}
    for k, v in meta.items():
        if v not in (None, ""):
            row[k] = v
    return row


# --- walkers ---------------------------------------------------------------

def walk_strings(obj: Any, path: list[Any] | None = None, depth: int = 0,
                 most: int = 60000) -> Iterable[tuple[list[Any], str]]:
    """Every string leaf with the path that reaches it. Bounded in depth and
    count so a status-adjacent helper can never hang the station."""
    path = path or []
    if depth > 12:
        return
    stack: list[tuple[Any, list[Any], int]] = [(obj, path, depth)]
    seen = 0
    while stack and seen < most:
        cur, p, d = stack.pop()
        if isinstance(cur, str):
            seen += 1
            yield p, cur
        elif isinstance(cur, dict):
            if d > 12:
                continue
            for k, v in cur.items():
                stack.append((v, p + [str(k)], d + 1))
        elif isinstance(cur, (list, tuple)):
            if d > 12:
                continue
            for i, v in enumerate(cur):
                stack.append((v, p + [i], d + 1))


def path_text(path: list[Any]) -> str:
    out = "$"
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else f".{p}"
    return out


def parent_of(obj: Any, path: list[Any]) -> Any:
    cur = obj
    for p in path[:-1]:
        try:
            cur = cur[p]
        except Exception:  # noqa: BLE001
            return None
    return cur


def json_sources(needle: Any, data: Any, layer: str, store: str, kill: str = "",
                 most: int = 40, label: Callable[[list[Any], Any], str] | None = None,
                 **meta: Any) -> list[dict[str, Any]]:
    """Every string in a parsed JSON document that carries the phrase, one
    source per leaf. `label(path, parent)` names the entry for the operator
    (a theme's name, a prompt's title); the JSON path is the key."""
    out: list[dict[str, Any]] = []
    pat = pattern(needle)
    if pat is None:
        return out
    for path, text in walk_strings(data):
        if not pat.search(text):
            continue
        name = ""
        if label is not None:
            try:
                name = str(label(path, parent_of(data, path)) or "")
            except Exception:  # noqa: BLE001
                name = ""
        out.append(make_source(layer, store, path, text, needle, kill,
                               label=name or path_text(path), **meta))
        if len(out) >= most:
            break
    return out


def text_sources(needle: Any, items: Iterable[dict[str, Any]], layer: str, store: str,
                 kill: str = "", most: int = 80) -> list[dict[str, Any]]:
    """Sources out of an in-memory store. Each item: {key, text, ...meta}."""
    out: list[dict[str, Any]] = []
    pat = pattern(needle)
    if pat is None:
        return out
    for it in items:
        text = it.get("text")
        if not text or not pat.search(str(text)):
            continue
        meta = {k: v for k, v in it.items() if k not in ("key", "text")}
        out.append(make_source(layer, store, it.get("key"), text, needle, kill, **meta))
        if len(out) >= most:
            break
    return out


_DEF_RE = re.compile(r"^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_ASSIGN_RE = re.compile(r"^([A-Z_][A-Z0-9_]{2,})\s*[:=]")


def _code_index(text: str) -> list[tuple[int, str]]:
    """(line, name) of every top-level def and CONSTANT, in order."""
    out: list[tuple[int, str]] = []
    for i, line in enumerate(text.split("\n"), 1):
        m = _DEF_RE.match(line)
        if m:
            out.append((i, m.group(1)))
            continue
        m = _ASSIGN_RE.match(line)
        if m:
            out.append((i, m.group(1)))
    return out


def _enclosing(index: list[tuple[int, str]], line: int) -> str:
    name = ""
    for at, nm in index:
        if at > line:
            break
        name = nm
    return name


def code_sources(needle: Any, files: Iterable[str | Path], memo: dict[str, Any],
                 layer: str = "prompts", most: int = 40, most_per_def: int = 6) -> list[dict[str, Any]]:
    """The phrase written into the code itself: a template, a default
    persona, a fixed deck of furniture. Grouped by the enclosing def or
    constant so a deck of eight objects reads as one source, not eight.
    Comment-only lines are skipped: a comment quoting the phrase is not a
    place it is written FROM."""
    pat = pattern(needle)
    out: list[dict[str, Any]] = []
    if pat is None:
        return out
    n = normalize(needle)
    for f in files:
        p = Path(f)
        try:
            st = p.stat()
        except OSError:
            continue
        sig = (st.st_mtime_ns, st.st_size)
        slot = memo.setdefault(str(p), {"sig": None, "index": [], "text": "", "hits": {}})
        if slot["sig"] != sig:
            try:
                slot["text"] = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            slot["index"] = _code_index(slot["text"])
            slot["hits"] = {}
            slot["sig"] = sig
        found = slot["hits"].get(n)
        if found is None:
            found = []
            for i, line in enumerate(slot["text"].split("\n"), 1):
                if line.lstrip().startswith("#"):
                    continue
                if pat.search(line):
                    found.append((i, line.strip()))
            if len(slot["hits"]) > 64:
                slot["hits"] = {}
            slot["hits"][n] = found
        by_def: dict[str, dict[str, Any]] = {}
        for line_no, line in found:
            name = _enclosing(slot["index"], line_no) or "(module)"
            row = by_def.setdefault(name, {"count": 0, "line": line_no, "lines": []})
            row["count"] += 1
            if len(row["lines"]) < most_per_def:
                row["lines"].append({"line": line_no, "text": line[:200]})
        for name, row in by_def.items():
            src = make_source(layer, "code", f"{p.name}:{name}", row["lines"][0]["text"], needle,
                              "code", count=row["count"], file=p.name, line=row["line"],
                              label=f"{p.name}: {name} (line {row['line']})",
                              lines=row["lines"])
            out.append(src)
            if len(out) >= most:
                return out
    return out


# --- files -----------------------------------------------------------------

def file_json(path: str | Path, memo: dict[str, Any]) -> Any:
    """A parsed JSON file, re-read only when it changes."""
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return None
    sig = (st.st_mtime_ns, st.st_size)
    slot = memo.setdefault("json:" + str(p), {"sig": None, "value": None})
    if slot["sig"] == sig:
        return slot["value"]
    try:
        slot["value"] = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        slot["value"] = None
    slot["sig"] = sig
    return slot["value"]


def file_text(path: str | Path, memo: dict[str, Any], cap: int = 4_000_000) -> str:
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return ""
    sig = (st.st_mtime_ns, st.st_size)
    slot = memo.setdefault("text:" + str(p), {"sig": None, "value": ""})
    if slot["sig"] == sig:
        return slot["value"]
    try:
        if st.st_size > cap:
            slot["value"] = ""
        else:
            slot["value"] = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        slot["value"] = ""
    slot["sig"] = sig
    return slot["value"]


def text_files(root: str | Path, suffixes: tuple[str, ...] = (".md", ".txt", ".json"),
               most: int = 2000, skip_over: int = 4_000_000) -> list[Path]:
    """Every readable document under a directory, bounded, vectors skipped."""
    out: list[Path] = []
    r = Path(root)
    if not r.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(r):
        dirnames[:] = [d for d in dirnames if not d.startswith("_")]
        for fn in filenames:
            if not fn.lower().endswith(suffixes) or fn.startswith("vectors"):
                continue
            p = Path(dirpath) / fn
            try:
                if p.stat().st_size > skip_over:
                    continue
            except OSError:
                continue
            out.append(p)
            if len(out) >= most:
                return out
    return out


def document_sources(needle: Any, files: Iterable[Path], memo: dict[str, Any], layer: str,
                     store: str, base: str | Path = "", most: int = 40) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pat = pattern(needle)
    if pat is None:
        return out
    for p in files:
        text = file_text(p, memo)
        if not text or not pat.search(text):
            continue
        try:
            rel = str(p.relative_to(base)) if base else p.name
        except Exception:  # noqa: BLE001
            rel = p.name
        out.append(make_source(layer, store, rel, text, needle, "file", file=rel, label=rel))
        if len(out) >= most:
            break
    return out


# --- the strip a ban uses ---------------------------------------------------

# A sentence, OR a bar. The rhyme pass writes "bar one / bar two / bar
# three" on one physical line with no sentence punctuation at all, so a
# split that only knows about full stops would take the whole line for
# one banned bar. The slash is only ever consulted on a line that
# carries the phrase - every other line is returned untouched.
_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+|\s+/\s+")


def strip_sentences(text: Any, needle: Any) -> tuple[str, int]:
    """Drop every sentence that carries the phrase; keep the rest of the line.

    A word ban blanks the word and leaves a hole; a PHRASE ban leaving "The
    is the part I cannot shake" on the air is worse than the phrase. The
    sentence goes, the line keeps its other sentences, and a line that was
    nothing but the phrase comes back empty - which the mouth already treats
    as "not said" (english_only returns "" the same way)."""
    pat = pattern(needle)
    raw = str(text or "")
    if pat is None or not raw or not pat.search(raw):
        return raw, 0
    removed = 0
    out_lines: list[str] = []
    for line in raw.split("\n"):
        if not pat.search(line):
            out_lines.append(line)
            continue
        kept: list[str] = []
        for sent in _SENT_SPLIT.split(line):
            if pat.search(sent):
                removed += 1
                continue
            kept.append(sent)
        out_lines.append(" ".join(s for s in kept if s.strip()))
    return "\n".join(out_lines).strip(), removed


def strip_phrase(text: Any, needle: Any) -> str:
    """The phrase itself removed, holes tidied - for a text that must keep
    its shape (a persona, a theme, a prompt)."""
    pat = pattern(needle)
    raw = str(text or "")
    if pat is None or not raw:
        return raw
    out = pat.sub("", raw)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r"([,;:]\s*){2,}", ", ", out)
    return out.strip()


# --- grouping ---------------------------------------------------------------

def group(sources: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The layers in their fixed order, each with its sources by weight."""
    by: dict[str, list[dict[str, Any]]] = {k: [] for k, _l, _d in LAYERS}
    for s in sources:
        by.setdefault(str(s.get("layer") or "scripts"), []).append(s)
    out = []
    for key, label, blurb in LAYERS:
        rows = sorted(by.get(key) or [], key=lambda r: (-int(r.get("count") or 0), str(r.get("store"))))
        out.append({"layer": key, "label": label, "blurb": blurb, "count": len(rows),
                    "airings": sum(int(r.get("count") or 0) for r in rows), "sources": rows})
    return out


def find_source(layers: Iterable[dict[str, Any]], sid: str) -> dict[str, Any] | None:
    for layer in layers:
        for s in layer.get("sources") or []:
            if str(s.get("id")) == str(sid):
                return s
    return None


class Memo:
    """A small (key -> value) memo with a TTL, for a walk that must not run
    twice for one operator tapping twice."""

    def __init__(self, ttl: float = 30.0, most: int = 32):
        self.ttl, self.most = float(ttl), int(most)
        self.rows: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        got = self.rows.get(key)
        if not got:
            return None
        at, value = got
        if time.time() - at > self.ttl:
            self.rows.pop(key, None)
            return None
        return value

    def put(self, key: str, value: Any) -> Any:
        if len(self.rows) >= self.most:
            oldest = min(self.rows.items(), key=lambda kv: kv[1][0])[0]
            self.rows.pop(oldest, None)
        self.rows[key] = (time.time(), value)
        return value

    def drop(self, key: str | None = None) -> None:
        if key is None:
            self.rows.clear()
        else:
            self.rows.pop(key, None)


def confirm_text(phrase: str, scripts: int, sources: int) -> str:
    """The confirm sheet's sentence, built in one place so the popup and the
    station say the same thing."""
    bits = ["block it from being spoken"]
    if scripts:
        bits.append(f"retire {scripts} scripted line{'s' if scripts != 1 else ''}")
    if sources:
        bits.append(f"remove {sources} source{'s' if sources != 1 else ''}")
    if len(bits) > 1:
        body = ", ".join(bits[:-1]) + ", and " + bits[-1]
    else:
        body = bits[0]
    return f"Never say “{phrase}” again: {body}?"


# --- removing a source: the writers behind a ticked "kills it" -------------
#
# A trace names a source by (store, JSON path). The kill has to find that
# leaf again in a document that may have moved under it, so every writer
# below re-reads the leaf and refuses when the phrase is no longer there.
# Nothing here touches disk: app.py owns the lock, the backup and the write.

def leaf_at(data: Any, path: Iterable[Any]) -> Any:
    cur = data
    for p in path:
        try:
            cur = cur[p]
        except Exception:  # noqa: BLE001
            return None
    return cur


def set_at(data: Any, path: list[Any], value: Any) -> bool:
    parent = parent_of(data, path)
    if parent is None or not path:
        return False
    key = path[-1]
    try:
        parent[key] = value
        return True
    except Exception:  # noqa: BLE001
        return False


def drop_at(data: Any, path: list[Any]) -> tuple[bool, str]:
    """Remove the ENTRY the leaf belongs to - the list item that contains
    it, or, when nothing on the way was a list, the key itself."""
    cut = -1
    for i, seg in enumerate(path):
        if isinstance(seg, int):
            cut = i
    if cut >= 0:
        parent = leaf_at(data, path[:cut])
        idx = path[cut]
        if isinstance(parent, list) and isinstance(idx, int) and 0 <= idx < len(parent):
            parent.pop(idx)
            return True, "the entry was removed"
        return False, "the entry has moved since the trace"
    parent = parent_of(data, path)
    if isinstance(parent, dict) and path and path[-1] in parent:
        parent.pop(path[-1])
        return True, "the entry was removed"
    return False, "the entry has moved since the trace"


def apply_kill(data: Any, path: list[Any], kill: str, needle: Any) -> tuple[bool, str]:
    """One ticked source, removed. False means nothing was changed - which
    is the honest answer when the document has moved on."""
    leaf = leaf_at(data, path)
    if not isinstance(leaf, str) or not hits(needle, leaf):
        return False, "the phrase is no longer at that place"
    if kill == "strip":
        out = strip_phrase(leaf, needle)
        if out == leaf:
            return False, "nothing to strip"
        if not out.strip():
            return drop_at(data, path)
        return (True, "the phrase was taken out of the text") if set_at(data, path, out) \
            else (False, "that text could not be written back")
    if kill in ("drop", "forget", "no_rerun"):
        return drop_at(data, path)
    if kill == "deactivate":
        parent = parent_of(data, path)
        if isinstance(parent, dict):
            parent["active"] = False
            parent["off_reason"] = "a phrase in it was banned"
            return True, "it was switched off"
        return drop_at(data, path)
    return False, KILLS.get(kill) or "there is nothing to remove here"


def kill_order(sources: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drops shift every later index in the same document, so the deepest
    path in a store goes first."""
    def weight(s: dict[str, Any]) -> tuple:
        key = s.get("key")
        key = key if isinstance(key, list) else []
        return (str(s.get("store") or ""),
                tuple(p if isinstance(p, int) else 0 for p in key),
                tuple(str(p) for p in key))
    return sorted(sources, key=weight, reverse=True)
