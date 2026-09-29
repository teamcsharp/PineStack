"""[msgid] WHY THIS LINE: one message's life story, read off every store.

"Each message a unique hex code identifier so that way I can point them out
specifically to you and ask questions about them and you're able to check into
specific messages and their past and see how they ended up the way that they
ended up." (operator, 2026-09-29)

A message is keyed by its line id everywhere: air_log `id` == script_ledger
`line_id` == System 3 `lines.line_id` == origin `line_id` == station_flow
`details.clip.line` == display receipt `line`. The ids come in three shapes -
6 hex (board SFX, desk rows; minted by _ensure_chat_ids before [msgid]), 8 hex
(everything minted since, _mint_line_id), 32 hex (spoken lines) and
`<32hex>-punct-N` (a cadence cue welded to a line). The operator sees a CODE:
code_of() below; resolve() takes the code, the full id or any hex prefix >= 6.

story() walks the stores in the order a line lives - planned, written,
rendered, published, heard, seen, reacted to - and stops saying things when the
record runs out. Read-only on every store: files are read from the END (the
append order is the time order), sqlite is opened mode=ro.

    GET /api/why/{code}            the story (JSON); ?text=1 plain text
    GET /api/why/{code}?brief=1    just the matches (the find box's resolver)
    docker exec spark-agent python3 tools/why_line.py 3c4782 [--json]
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

SCHEMA = "line.story/1"
CODE = re.compile(r"^#?\s*([0-9a-f]{6,32})(?:-p(?:unct-)?(\d{1,3}))?$")
PUNCT = re.compile(r"^(.*)-punct-(\d+)$")
NEAR_S = 5.0                      # neighbours on air within this
SAME_S = 1.0                      # "the same second"
PAST_S = 900.0                    # a row this much older than the target ends a scan
CHUNK = 1 << 20

WHO_WORDS = {
    "gap": "the dead-air filler (sfx_fill_gap / cover_the_gap)",
    "board": "the board's cue (a scripted sting)",
    "record": "a record's own cue",
}
KEEP_WORDS = ("withdrawn", "withdrawn_why", "held", "gate", "gated", "gates", "rejected",
              "reject_why", "strike", "strikes", "copy_of", "reair", "repeat_of", "deleted",
              "cut_why", "validate", "flags")


# ------------------------------------------------------------------ codes

def code_of(line_id: Any) -> str:
    """The short code the operator sees and says: 6/8 hex as they are, a
    longer hex id by its first 8, a welded cue as `<first8>-pN`."""
    s = str(line_id or "").strip().lower()
    m = PUNCT.match(s)
    if m:
        return "%s-p%s" % (code_of(m.group(1)), m.group(2))
    if re.fullmatch(r"[0-9a-f]{9,}", s):
        return s[:8]
    return s


def parse(query: Any) -> dict[str, Any] | None:
    """'#3c4782', '3c4782', a full 32-hex id, '1a2b3c4d-p1' -> {prefix, punct}."""
    q = str(query or "").strip().lower().replace(" ", "")
    m = CODE.match(q)
    if not m:
        return None
    return {"prefix": m.group(1), "punct": m.group(2) or ""}


def matches(line_id: str, want: dict[str, Any]) -> bool:
    s = str(line_id or "").lower()
    m = PUNCT.match(s)
    if want["punct"]:
        return bool(m) and m.group(1).startswith(want["prefix"]) and m.group(2) == want["punct"]
    return not m and s.startswith(want["prefix"])


# ------------------------------------------------------------------ readers

def rev_lines(path: Any, chunk: int = CHUNK) -> Iterator[bytes]:
    """The file's lines, newest first: a tail window that widens a megabyte at
    a time only while the caller keeps asking."""
    p = Path(path)
    try:
        fh = p.open("rb")
    except OSError:
        return
    with fh:
        fh.seek(0, os.SEEK_END)
        pos, tail = fh.tell(), b""
        while pos > 0:
            step = min(chunk, pos)
            pos -= step
            fh.seek(pos)
            parts = (fh.read(step) + tail).split(b"\n")
            tail = parts[0] if pos > 0 else b""
            for raw in reversed(parts[1:] if pos > 0 else parts):
                if raw.strip():
                    yield raw


def _at(r: dict[str, Any]) -> float:
    for k in ("air_at", "at", "ts", "rx"):
        try:
            v = float(r.get(k) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v:
            return v
    return 0.0


def scan_ids(path: Any, needle: str, key: str, want: dict[str, Any] | None = None,
             exact: str = "", past_s: float = PAST_S) -> list[dict[str, Any]]:
    """Rows whose `key` matches, newest first. Lines are tested for the needle
    as bytes before any JSON is parsed; once a hit is found the scan runs on
    only until the rows are `past_s` older than the oldest hit (the upserts of
    one line land together), or to the head of the file when nothing is."""
    nb = needle.encode()
    out: list[dict[str, Any]] = []
    oldest = None                     # the oldest hit's time
    for raw in rev_lines(path):
        if nb not in raw:
            if oldest is not None:
                try:
                    t = _at(json.loads(raw))
                except Exception:  # noqa: BLE001
                    t = 0.0
                if t and t < oldest - past_s:
                    break
            continue
        try:
            r = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        v = str(r.get(key) or "")
        if (exact and v == exact) or (not exact and want and matches(v, want)):
            out.append(r)
            a = _at(r)
            if a:
                oldest = a if oldest is None else min(oldest, a)
    return out


def scan_time(path: Any, since: float, until: float, pred: Callable[[dict], bool] | None = None,
              tkey: str = "ts") -> list[dict[str, Any]]:
    """Rows stamped in [since, until], newest first, stopping once 200 rows in
    a row are older than the window (the air log is appended in time order)."""
    out, older = [], 0
    for raw in rev_lines(path):
        try:
            r = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        try:
            t = float(r.get(tkey) or 0) or _at(r)
        except (TypeError, ValueError):
            t = _at(r)
        if t and t < since - 60:
            older += 1
            if older > 200:
                break
            continue
        older = 0
        a = _at(r)
        if since <= a <= until and (pred is None or pred(r)):
            out.append(r)
    return out


def ro(path: Any) -> sqlite3.Connection | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        c = sqlite3.connect("file:%s?mode=ro" % p, uri=True, timeout=5, check_same_thread=False)
        c.execute("SELECT 1")
        return c
    except sqlite3.Error:
        return None


def read_json(path: Any, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def when(at: Any, date: bool = False) -> str:
    try:
        a = float(at or 0)
    except (TypeError, ValueError):
        return ""
    if a <= 0:
        return ""
    if a > 1e12:
        a /= 1000.0
    return time.strftime("%Y-%m-%d %H:%M:%S" if date else "%H:%M:%S", time.localtime(a)) \
        + (".%03d" % int(round((a % 1) * 1000)) if not date and a % 1 else "")


# ------------------------------------------------------------------ resolve

def resolve(data: Any, query: Any, ring: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """Every message the code can name, newest first: {id, code, at, text,
    kind, who, found_in}. More than one means the code recurred (a 6-hex code
    across days, or a prefix too short) - the caller shows them all."""
    data = Path(data)
    want = parse(query)
    if not want:
        return {"query": str(query or ""), "ok": False, "why": "not a message code (6-32 hex, optional #)",
                "matches": []}
    found: dict[str, dict[str, Any]] = {}

    def note(lid: str, where: str, row: dict[str, Any]) -> None:
        if not lid or not matches(lid, want):
            return
        c = found.setdefault(lid, {"id": lid, "code": code_of(lid), "at": 0.0, "text": "",
                                   "kind": "", "who": "", "found_in": []})
        if where not in c["found_in"]:
            c["found_in"].append(where)
        c["at"] = c["at"] or _at(row)
        for k in ("text", "kind", "who"):
            c[k] = c[k] or str(row.get(k) or "")[:200]

    for r in ring or ():
        note(str(r.get("id") or ""), "the ring", r)
    for r in scan_ids(data / "air_log.jsonl", want["prefix"], "id", want):
        note(str(r.get("id") or ""), "air_log", r)
    for r in scan_ids(data / "script_ledger.jsonl", want["prefix"], "line_id", want):
        note(str(r.get("line_id") or ""), "script_ledger", r)
    if not found:
        for r in scan_ids(data / "screenplay_lines.jsonl", want["prefix"], "id", want):
            note(str(r.get("id") or ""), "screenplay_lines", r)
    for db, sql, where in (
            ("system3_origin.sqlite3", "SELECT line_id, air_at, '', kind, who FROM origin WHERE line_id LIKE ? LIMIT 50",
             "origin"),
            ("system3.sqlite3", "SELECT line_id, at, text, '', who FROM lines WHERE line_id LIKE ? LIMIT 50",
             "system3 lines")):
        c = ro(data / db)
        if c is None:
            continue
        try:
            for lid, at, text, kind, who in c.execute(sql, (want["prefix"] + "%",)):
                note(str(lid), where, {"at": at, "text": text, "kind": kind, "who": who})
        except sqlite3.Error:
            pass
        finally:
            c.close()
    rows = sorted(found.values(), key=lambda m: -float(m.get("at") or 0))
    return {"query": str(query or ""), "ok": bool(rows), "prefix": want["prefix"], "matches": rows,
            "why": "" if rows else "no store knows a message with that code"}


# ------------------------------------------------------------------ the story

def _origin(data: Path, lid: str) -> dict[str, Any] | None:
    try:
        import system3_origin as so
    except Exception:  # noqa: BLE001
        return None
    c = ro(data / "system3_origin.sqlite3")
    if c is None:
        return None
    led = so.OriginLedger(data / "system3_origin.sqlite3")
    led._db = c                       # the module's own reader, on a read-only handle
    try:
        return led.get(lid)
    except Exception:  # noqa: BLE001
        return None
    finally:
        c.close()


def _s3(data: Path, lid: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    c = ro(data / "system3.sqlite3")
    if c is None:
        return out
    try:
        r = c.execute("SELECT conversation_id, turn_id, block, ord, sid, who, text, at FROM lines WHERE line_id=?",
                      (lid,)).fetchone()
        if r:
            out["line"] = dict(zip(("conversation_id", "turn_id", "block", "ord", "sid", "who", "text", "at"), r))
            cv = c.execute("SELECT road, mode, status, seed, verdict, summary, created FROM conversations WHERE id=?",
                           (r[0],)).fetchone()
            if cv:
                summ = {}
                try:
                    summ = json.loads(cv[5] or "{}")
                except Exception:  # noqa: BLE001
                    pass
                out["conversation"] = {"id": r[0], "road": cv[0], "mode": cv[1], "status": cv[2], "seed": cv[3],
                                       "verdict": cv[4], "created": cv[6], "topic": summ.get("topic"),
                                       "turns": summ.get("turns"), "events": summ.get("events")}
    except sqlite3.Error as exc:
        out["error"] = str(exc)
    finally:
        c.close()
    return out


def _flow(data: Path, lid: str) -> list[dict[str, Any]]:
    """station_flow's pipeline events for this line, and every later event on
    the same trace (publish, then whatever acknowledged it)."""
    c = ro(data / "station_flow.sqlite3")
    if c is None:
        return []
    out: list[dict[str, Any]] = []
    try:
        traces = set()
        for (body,) in c.execute("SELECT body FROM events WHERE body LIKE ? ORDER BY id DESC LIMIT 20",
                                 ('%"line": "' + lid + '"%',)):
            try:
                b = json.loads(body)
            except Exception:  # noqa: BLE001
                continue
            traces.add(str(b.get("trace_id") or ""))
            out.append(b)
        for t in [t for t in traces if t][:4]:
            for (body,) in c.execute("SELECT body FROM events WHERE body LIKE ? ORDER BY id LIMIT 40",
                                     ('%"trace_id": "' + t + '"%',)):
                try:
                    b = json.loads(body)
                except Exception:  # noqa: BLE001
                    continue
                if all(b.get("id") != o.get("id") for o in out):
                    out.append(b)
    except sqlite3.Error:
        pass
    finally:
        c.close()
    return sorted(out, key=lambda b: float(b.get("at") or 0))


def _reviews(data: Path, text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    c = ro(data / "line_review.sqlite3")
    if c is None:
        return []
    try:
        rows = c.execute("SELECT id, gate, source, disposition, review_status, decision, first_at, last_at, "
                         "occurrences FROM line_reviews WHERE candidate=? LIMIT 10", (text,)).fetchall()
        return [dict(zip(("id", "gate", "source", "disposition", "review_status", "decision", "first_at",
                          "last_at", "occurrences"), r)) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        c.close()


def story(data: Any, query: Any, ring: Iterable[dict[str, Any]] = (), now: float | None = None) -> dict[str, Any]:
    data = Path(data)
    now = time.time() if now is None else float(now)
    ring = list(ring or ())
    res = resolve(data, query, ring)
    out: dict[str, Any] = {"schema": SCHEMA, "query": str(query or ""), "matches": res["matches"],
                           "events": [], "stages": {}}
    if not res["matches"]:
        out["verdict"] = "No store knows a message %s: %s." % (str(query or ""), res.get("why"))
        return out
    lid = res["matches"][0]["id"]
    out["id"], out["code"] = lid, code_of(lid)
    ev = out["events"]

    def add(at: Any, stage: str, what: str, **detail: Any) -> None:
        ev.append({"at": float(at or 0), "stage": stage, "what": what,
                   **{k: v for k, v in detail.items() if v not in (None, "", [], {})}})

    # -- the air rows (every rewrite of this id), newest first
    air = [r for r in ring if str(r.get("id")) == lid]
    air += scan_ids(data / "air_log.jsonl", lid, "id", exact=lid)
    row = dict(air[0]) if air else {}
    if air:
        for r in air[1:]:
            for k, v in r.items():
                row.setdefault(k, v)
    text = str(row.get("text") or res["matches"][0].get("text") or "")
    out["text"] = text
    out["air"] = {k: row.get(k) for k in ("ts", "air_at", "who", "name", "kind", "round", "aired", "match_why",
                                          "heard_ack_at", "heard_ack_by", "sid", "voice", "engine", "seconds",
                                          "sfx", "sfx_dir", "url", "caller", "source") if row.get(k) not in (None, "")}
    for k in KEEP_WORDS:
        if row.get(k) not in (None, "", [], {}, False):
            out["air"][k] = row.get(k)
    out["air"]["versions"] = len(air)

    # -- planned: the script ledger and its reservation
    led = scan_ids(data / "script_ledger.jsonl", lid, "line_id", exact=lid)
    sl = dict(led[0]) if led else {}
    sl.pop("system_prompts", None)
    out["script"] = sl
    for raw in rev_lines(data / "script_ledger_reserved.jsonl"):
        if lid.encode() in raw:
            try:
                r = json.loads(raw)
                add(r.get("at"), "planned", "block %s reserved (ord %s of %d)" % (
                    r.get("block"), (r.get("ords") or [None])[list(r.get("ids") or []).index(lid)]
                    if lid in (r.get("ids") or []) else "?", len(r.get("ids") or [])))
            except Exception:  # noqa: BLE001
                pass
            break
    if sl:
        seg = sl.get("segment") or {}
        s3 = sl.get("system3") or {}
        late = float(sl.get("at") or 0) - float(row.get("air_at") or row.get("ts") or 0) if row else 0.0
        add(sl.get("at"), "planned", "script ledger: block %s ord %s%s" % (
            sl.get("block"), sl.get("ord"),
            (" - written %.1f s AFTER it aired (the keeper's catch-up: it was not in the script beforehand)" % late)
            if late > 1.0 and not sl.get("scripted") else ""),
            segment="%s (%s, hour %s)" % (seg.get("label") or seg.get("kind") or "", seg.get("id") or "",
                                          seg.get("hour") or "") if seg else "",
            round=sl.get("round"), cue=sl.get("cue"), scripted=sl.get("scripted"),
            system3={k: s3.get(k) for k in ("conversation_id", "turn_id", "road", "mode", "seed") if s3.get(k)},
            sfx_roll=s3.get("sfx_roll"), rolls=s3.get("rolls") or s3.get("line_rolls"))

    # -- System 3: the line row, its conversation, the origin record
    s3db = _s3(data, lid)
    out["system3"] = s3db
    if s3db.get("conversation"):
        cv = s3db["conversation"]
        add(cv.get("created"), "planned", "System 3 conversation %s on the %s road (%s, %s)" % (
            cv.get("id"), cv.get("road"), cv.get("mode"), cv.get("status")),
            topic=cv.get("topic"), seed=cv.get("seed"), turns=cv.get("turns"))
    org = _origin(data, lid)
    if org:
        out["origin"] = {k: org.get(k) for k in ("verdict", "why", "road", "producer", "path", "tables", "store",
                                                 "forced", "rogue", "settled", "retention")}
        rolls = [{"table": d.get("table"), "picked": d.get("picked"), "dice": d.get("dice"), "of": d.get("of")}
                 for d in (org.get("turn_decisions") or [])]
        out["origin"]["turn_rolls"] = rolls
        add(org.get("air_at"), "planned", "origin: %s - %s" % (org.get("verdict"), org.get("why") or ""),
            producer=org.get("producer"), path=org.get("path"),
            forced=org.get("forced"), rogue=org.get("rogue"),
            tables=["%s: %s" % (t.get("table"), t.get("label")) for t in (org.get("tables") or [])],
            turn_rolls=["%s: %s" % (r["table"], str(r["picked"])[:60]) for r in rolls])

    # -- written and rendered
    sp = scan_ids(data / "screenplay_lines.jsonl", lid, "id", exact=lid)
    if sp:
        s = sp[0]
        w = s.get("wrote") or {}
        out["written"] = {"model": w.get("model"), "kind": w.get("kind"), "ms": w.get("ms"), "temp": w.get("temp"),
                          "queued_at": s.get("queued_at"), "voice": s.get("voice"), "perf": s.get("perf")}
        if w:
            add(w.get("at"), "written", "written by %s (%s, %s ms)" % (w.get("model"), w.get("kind"), w.get("ms")),
                temp=w.get("temp"), armed=w.get("armed"))
        add(s.get("queued_at") or s.get("at"), "rendered", "queued for the air (%s)" % (s.get("round") or s.get("kind")),
            voice=s.get("voice"), perf=s.get("perf"))
    for raw in rev_lines(data / "screenplay_rounds.jsonl"):
        if lid.encode() in raw:
            try:
                r = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            if lid in (r.get("lines") or []):
                out["round"] = {k: r.get(k) for k in ("at", "until", "kind", "caller", "source", "banked_at",
                                                      "frozen", "stream")}
                add(r.get("banked_at") or r.get("at"), "rendered", "in a %s round of %d lines" % (
                    r.get("kind"), len(r.get("lines") or [])), source=r.get("source"))
                break
    if row.get("voice") or row.get("engine") or row.get("seconds"):
        add(row.get("ts"), "rendered", "%s%s %.2f s" % (
            ("voice %s " % row["voice"]) if row.get("voice") else "",
            ("on %s" % row["engine"]) if row.get("engine") else ("SFX clip %s/%s" % (row.get("sfx_dir") or "?",
                                                                                   row.get("sfx") or "?")),
            float(row.get("seconds") or 0)))

    # -- the gates
    gates: list[dict[str, Any]] = []
    for raw in rev_lines(data / "withdrawn_rounds.jsonl"):
        if lid.encode() in raw:
            try:
                r = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            gates.append({"gate": "withdrawn round", "at": r.get("at"), "verdict": r.get("why"), "sid": r.get("sid")})
            add(r.get("at"), "gate", "WITHDRAWN with its round %s: %s" % (r.get("sid"), r.get("why")))
            break
    for rv in _reviews(data, text):
        gates.append({"gate": rv.get("gate"), "at": rv.get("last_at"), "verdict": rv.get("disposition")
                      or rv.get("review_status"), "review": rv.get("id")})
        add(rv.get("first_at"), "gate", "line review gate %s: %s" % (rv.get("gate"), rv.get("disposition")
                                                                      or rv.get("review_status")))
    for k in KEEP_WORDS:
        if row.get(k) not in (None, "", [], {}, False):
            gates.append({"gate": k, "verdict": row.get(k)})
    sid = str(row.get("sid") or "")
    if sid:
        for raw in rev_lines(data / "airings.jsonl"):
            if sid.encode() in raw:
                try:
                    r = json.loads(raw)
                except Exception:  # noqa: BLE001
                    continue
                if r.get("sid") == sid:
                    gates.append({"gate": "airings (the round)", "at": r.get("at"),
                                  "verdict": "heard" if r.get("heard") else "not heard",
                                  "aired": r.get("aired"), "ghosts": r.get("ghosts")})
                    break
    out["gates"] = gates

    at = float(row.get("air_at") or row.get("ts") or res["matches"][0].get("at") or 0)

    # -- published: the pipeline log, then the row's own state
    flow = _flow(data, lid)
    out["flow"] = [{"at": b.get("at"), "node": b.get("node"), "status": b.get("status"),
                    "summary": b.get("summary"), "from": b.get("from"), "trace_id": b.get("trace_id")}
                   for b in flow]
    for b in flow:
        add(b.get("at"), "published", "%s: %s - %s" % (b.get("node"), b.get("status"), b.get("summary")),
            trace=b.get("trace_id"), via=b.get("from"))
    if row:
        add(at, "published", "on air at %s, aired=%s" % (when(at), row.get("aired") or "?"),
            match_why=row.get("match_why"), round=row.get("round"))

    # -- the SFX history: who fired it
    hist: list[dict[str, Any]] = []
    if at:
        hist = scan_time(data / "sfx_history.jsonl", at - NEAR_S - 1, at + NEAR_S + 1)
        mine = [h for h in hist if row.get("sfx") and h.get("id") == row.get("sfx") and abs(float(h.get("ts") or 0) - at) <= 2]
        if mine:
            h = mine[0]
            out["sfx_history"] = {"ts": h.get("ts"), "name": h.get("name"), "who": h.get("who"),
                                  "who_is": WHO_WORDS.get(str(h.get("who")), "")}
            add(float(h.get("ts") or 0) + 0.0001, "published", "sfx_history: %s fired by '%s' - %s" % (
                h.get("name"), h.get("who"), WHO_WORDS.get(str(h.get("who")), "")))

    # -- heard, and seen (the display receipts: sfx_display's own join)
    try:
        import sfx_display as sd
        played = sd._played(row) if row else {"state": "not-aired"}
    except Exception:  # noqa: BLE001
        sd, played = None, {"state": "unknown"}
    out["heard"] = played
    if played.get("state") == "heard":
        add(played.get("at"), "heard", "HEARD (acknowledged%s)" % (" by " + played["by"] if played.get("by") else ""))
    elif row:
        add(at + 0.001, "heard", "no heard acknowledgement on the air row (%s)" % (
            "aired=page: handed to the page road, awaiting a player's ACK" if played.get("aired") == "page"
            else played.get("state")))
    if sd is not None and row and (str(row.get("kind")) == "sfx" or str(row.get("who")) == "board"):
        try:
            store = sd.ReceiptStore(data / sd.STORE_NAME)
            rep = sd.audit([row], store.read(at - 120, at + 600), at - 120, at + 600, line=lid)
            item = (rep.get("rows") or [{}])[0]
            out["display"] = {"displayed": item.get("displayed"), "video": item.get("video"),
                              "displays": item.get("displays"), "reactions": item.get("reactions"),
                              "players": rep.get("players")}
            for p, d in (item.get("displays") or {}).items():
                add(at + 0.002, "seen", d.get("sentence") or "%s: %s" % (p, d.get("outcome")),
                    receipts=d.get("receipts"))
            if not item.get("displays"):
                add(at + 0.002, "seen", "no display receipt from any player")
        except Exception as exc:  # noqa: BLE001
            out["display"] = {"error": str(exc)[:200]}

    # -- the operator's reactions
    reactions: list[dict[str, Any]] = []
    v = (read_json(data / "line_votes.json", {}) or {}).get(lid)
    if isinstance(v, dict):
        reactions.append({"what": "vote " + str(v.get("vote")), "at": v.get("at")})
    sfx = str(row.get("sfx") or "")
    for d in read_json(data / "sfx_deleted.json", []) or []:
        if isinstance(d, dict) and ((sfx and d.get("id") == sfx) or lid in (d.get("lines") or [])):
            reactions.append({"what": "SFX deleted from the library (%s)" % d.get("name"), "at": d.get("at")})
    if sfx and sfx in (read_json(data / "sfx_bans.json", []) or []):
        reactions.append({"what": "SFX banned", "at": None})
    for raw in rev_lines(data / "word_cause_edits.jsonl"):
        if lid.encode() in raw:
            try:
                r = json.loads(raw)
                reactions.append({"what": "edit %s %s" % (r.get("method"), r.get("endpoint")), "at": r.get("at")})
            except Exception:  # noqa: BLE001
                pass
    for r in (out.get("display") or {}).get("reactions") or []:
        reactions.append({"what": "%s on %s" % (r.get("what"), r.get("player")), "at": r.get("at")})
    out["reactions"] = reactions
    for r in reactions:
        add(r.get("at") or now, "reacted", r["what"])

    # -- the neighbours: everything on air within NEAR_S
    near: list[dict[str, Any]] = []
    if at:
        rows = {}
        for r in scan_time(data / "air_log.jsonl", at - NEAR_S, at + NEAR_S):
            rows.setdefault(str(r.get("id")), r)
        for r in ring:
            a = float(r.get("air_at") or r.get("ts") or 0)
            if abs(a - at) <= NEAR_S:
                rows.setdefault(str(r.get("id")), r)
        for r in rows.values():
            a = float(r.get("air_at") or r.get("ts") or 0)
            h = next((x for x in hist if r.get("sfx") and x.get("id") == r.get("sfx")
                      and abs(float(x.get("ts") or 0) - a) <= 2), None)
            near.append({"id": str(r.get("id")), "code": code_of(r.get("id")), "at": a, "dt": round(a - at, 3),
                         "kind": r.get("kind"), "who": r.get("who"), "text": str(r.get("text") or "")[:80],
                         "aired": r.get("aired"), "heard": bool(r.get("heard_ack_at")),
                         "fired_by": (h or {}).get("who"), "self": str(r.get("id")) == lid})
        on_air = [(str(r.get("sfx") or ""), float(r.get("air_at") or r.get("ts") or 0)) for r in rows.values()]
        for h in hist:
            a = float(h.get("ts") or 0)
            if abs(a - at) > NEAR_S + 0.999:
                continue
            if any(k and k == h.get("id") and abs(t - a) <= 2 for k, t in on_air):
                continue
            near.append({"id": "", "code": "", "at": a, "dt": round(a - at, 3), "kind": "sfx",
                         "who": "", "text": str(h.get("name") or ""), "aired": "", "heard": False,
                         "fired_by": h.get("who"), "self": False, "only_in": "sfx_history (no air-log row)"})
        near.sort(key=lambda n: (n["at"], n["id"]))
    out["neighbours"] = near
    same = [n for n in near if not n["self"] and abs(n["dt"]) <= SAME_S]
    out["collision"] = {"same_second": len(same), "items": [n.get("code") or n.get("text") for n in same],
                        "fired_by": sorted({str(n.get("fired_by")) for n in same if n.get("fired_by")})}

    ev.sort(key=lambda e: e["at"])
    out["stages"] = _stages(out, row, sl, played)
    out["verdict"] = verdict(out)
    return out


def _stages(out: dict[str, Any], row: dict[str, Any], sl: dict[str, Any], played: dict[str, Any]) -> dict[str, Any]:
    disp = out.get("display") or {}
    pages: dict[str, str] = {}
    for f in out.get("flow") or []:
        m = re.match(r"^(\S+): (received|canplay|playing|ended|error|stalled)", str(f.get("summary") or ""))
        if m:
            pages[m.group(1)] = m.group(2)
    return {
        "page_players": pages,
        "picture": None if disp.get("video") is False else disp.get("video"),
        "planned": bool(sl or (out.get("system3") or {}).get("line") or out.get("origin")),
        "rendered": bool(row.get("seconds") or row.get("url") or row.get("voice") or out.get("written")),
        "published": bool(row.get("aired") and row.get("aired") not in ("withdrawn", "dropped", "cut", "never")),
        "heard": played.get("state") == "heard",
        "seen": bool(disp.get("displayed")) if disp else None,
    }


def verdict(s: dict[str, Any]) -> str:
    st = s.get("stages") or {}
    a = s.get("air") or {}
    sl = s.get("script") or {}
    org = s.get("origin") or {}
    at = a.get("air_at") or a.get("ts")
    parts = []
    code = "#" + str(s.get("code") or "")
    what = "'%s' (%s %s)" % (str(s.get("text") or "")[:60], a.get("who") or "?", a.get("kind") or "?")
    late = (float(sl.get("at") or 0) - float(at or 0)) if (sl and at) else 0.0
    if st.get("planned") and late > 1.0 and not sl.get("scripted"):
        cv = (s.get("system3") or {}).get("conversation") or {}
        who = (s.get("sfx_history") or {}).get("who")
        parts.append("%s %s was NOT planned ahead: %s fired it, System 3 rolled it at that instant%s, and "
                     "the keeper filed it in script block %s %.1f s after it aired%s" % (
                         code, what, ("'%s'" % who) if who else ("'%s'" % org.get("producer") if org.get("producer")
                                                                  else "a road"),
                         (" (%s road, conversation %s)" % (cv.get("road"), cv.get("id"))) if cv else "",
                         sl.get("block", "?"), late,
                         (", origin %s via %s" % (org.get("verdict"), org.get("producer")))
                         if org.get("verdict") else ""))
    elif st.get("planned"):
        cv = (s.get("system3") or {}).get("conversation") or {}
        parts.append("%s %s was PLANNED in script block %s%s%s" % (
            code, what, sl.get("block", "?"),
            (" by System 3's %s road (conversation %s)" % (cv.get("road"), cv.get("id"))) if cv else "",
            (", origin %s via %s" % (org.get("verdict"), org.get("producer"))) if org.get("verdict") else ""))
    else:
        parts.append("%s %s has no script-ledger or System 3 plan on record" % (code, what))
    parts.append("RENDERED" + (" (%.2f s)" % float(a.get("seconds") or 0) if a.get("seconds") else "")
                 if st.get("rendered") else "no render on record")
    if st.get("published"):
        who = (s.get("sfx_history") or {}).get("who")
        parts.append("PUBLISHED at %s as aired=%s%s" % (when(at, True), a.get("aired"),
                                                         (", fired by '%s' - %s" % (who, WHO_WORDS.get(who, "")))
                                                         if who else ""))
    else:
        parts.append("never published (aired=%s)" % (a.get("aired") or "none"))
    pages = st.get("page_players") or {}
    ran = ", ".join("%s reached '%s'" % (k, v) for k, v in pages.items())
    if st.get("heard"):
        parts.append("HEARD")
    elif st.get("published"):
        parts.append("never HEARD: the air row carries no heard acknowledgement" + (
            " (the pipeline log shows page client %s - a page ran it, but no hearing was confirmed)" % ran
            if ran else ", and no player reported it at all"))
    if st.get("seen") is True:
        parts.append("SEEN on a screen")
    elif st.get("seen") is False:
        parts.append("never SEEN: no display receipt" + (
            " (an audio-only clip: there was no picture to show)" if st.get("picture") is None
            and (s.get("display") or {}).get("video") is False else ""))
    stop = ("planned" if not st.get("planned") else "rendered" if not st.get("rendered")
            else "published" if not st.get("published") else "heard" if not st.get("heard") else "")
    tail = (" It stopped between %s and %s." % ({"planned": "(nothing)", "rendered": "planned",
                                                  "published": "rendered", "heard": "published"}[stop], stop)
            if stop else " It completed its life.")
    col = s.get("collision") or {}
    if col.get("same_second"):
        tail += " COLLISION: %d other item(s) went out within %.0f s of it (%s)%s." % (
            col["same_second"], SAME_S, ", ".join(str(x) for x in col["items"][:6]),
            (", fired by " + "/".join(col["fired_by"])) if col.get("fired_by") else "")
    if len(s.get("matches") or []) > 1:
        tail += " NOTE: the code %s names %d messages; this is the newest (--all lists them)." % (
            code, len(s["matches"]))
    return "; ".join(parts) + "." + tail


# ------------------------------------------------------------------ text

def format_text(s: dict[str, Any]) -> str:
    L = []
    if not s.get("id"):
        return "WHY %s\n  %s" % (s.get("query"), s.get("verdict"))
    a = s.get("air") or {}
    L.append("WHY #%s  (id %s)" % (s.get("code"), s.get("id")))
    L.append("  \"%s\"  %s/%s  round=%s" % (s.get("text"), a.get("who"), a.get("kind"), a.get("round") or "-"))
    if len(s.get("matches") or []) > 1:
        L.append("  the code names %d messages:" % len(s["matches"]))
        for m in s["matches"]:
            L.append("    %s  %s  %s" % (m["id"], when(m.get("at"), True), m.get("text", "")[:50]))
    L.append("")
    L.append("LIFE, in order:")
    for e in s.get("events") or []:
        L.append("  %-12s %-9s %s" % (when(e["at"]) or "-", e["stage"], e["what"]))
        for k, v in e.items():
            if k in ("at", "stage", "what"):
                continue
            L.append("  %-12s %-9s   %s: %s" % ("", "", k, json.dumps(v, default=str)[:300]
                                               if not isinstance(v, str) else v[:300]))
    if s.get("gates"):
        L.append("")
        L.append("GATES:")
        for g in s["gates"]:
            L.append("  %s -> %s" % (g.get("gate"), g.get("verdict")))
    else:
        L.append("")
        L.append("GATES: none on record (no withdrawal, review, strike or copy flag)")
    L.append("")
    L.append("NEIGHBOURS on air within +/-%.0f s:" % NEAR_S)
    for n in s.get("neighbours") or []:
        L.append("  %s %+7.3f s  %-14s %-6s %-5s %-24s aired=%-6s heard=%s fired_by=%s%s" % (
            ">>" if n["self"] else "  ", n["dt"], ("#" + n["code"]) if n["code"] else "-",
            n.get("who") or "", n.get("kind") or "", n.get("text", "")[:24], n.get("aired") or "-",
            "yes" if n.get("heard") else "no", n.get("fired_by") or "-",
            ("  [" + n["only_in"] + "]") if n.get("only_in") else ""))
    L.append("")
    L.append("VERDICT: " + str(s.get("verdict")))
    return "\n".join(L)


# ------------------------------------------------------------------ the door

def install(app: Any, namespace: dict[str, Any]) -> None:
    from fastapi import Header, HTTPException

    data_path = namespace["data_path"]
    data = Path(data_path("air_log.jsonl")).parent

    def _ring() -> list[dict[str, Any]]:
        radio = namespace.get("_RADIO") or {}
        return [dict(e) for e in list(radio.get("chat") or [])[-400:] if isinstance(e, dict)]

    @app.get("/api/why/{code}")
    async def line_story_api(code: str, brief: int = 0, text: int = 0,
                             authorization: str | None = Header(default=None)) -> Any:
        fn = namespace.get("require_read_auth")
        if callable(fn):
            fn(authorization)
        if not parse(code):
            raise HTTPException(status_code=400, detail="a message code is 6-32 hex, e.g. #3c4782")
        import asyncio
        ring = _ring()
        if int(brief or 0):
            return await asyncio.to_thread(resolve, data, code, ring)
        s = await asyncio.to_thread(story, data, code, ring)
        if int(text or 0):
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(format_text(s))
        return s
