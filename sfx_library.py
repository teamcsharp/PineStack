"""[sfx-library] THE SFX GUY'S DATABASE, AS A TABLE ANYONE CAN SEARCH.

"I want to be able to view the database and thumbnails of clips and review the
information he is storing in a table where i can see clips, the tags,
information and tables associated with an entry and edit, expand, review,
delete and export." And: "at the top put a search bar, I want to type anything
and have it be looked up by the database showing suggestions in the window ...
search for anything that is used as a tag in the database and search by clip
name, folder, source, identified media tag, and any parameter that is used in
the database."                                        - the operator, 2026-09-30

Two stores answer, and neither is copied:
  the vector section (sfx_vectors.Store): name, folder, source (root),
      rel_path, video, seconds, said (transcript), seen_desc (what the vision
      pass saw), aired, last_aired, embedded/tagged, facet tags, clips_fts;
  the clip book (data/sfx_clips.db): playable, bytes, mtime, seen_at,
      said_at, seen_desc_at, deck_cycle - merged in for the rows shown.

THE QUERY. Free words go to the full-text index (name, said, seen_desc, tags)
and to name / folder / source / path. A `field:value` token narrows by one
parameter: tag:, <facet>:, folder:, source:, name:, path:, seen:, said:, id:,
video:yes|no, embedded:, tagged:, aired:N|>N|<N, seconds:N|>N|<N|A-B.
Values may be "quoted". The suggestions offer exactly these tokens.

A TAG THE OPERATOR WRITES is facet_tags.how = 'operator': the keeper's
re-tagging and a change of the clip's text keep it (sfx_vectors.py).

Pure functions take the vector store's connection and run on its own worker
thread (the runtime's rt.run); install() adds the routes.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import shlex
import time
from pathlib import Path
from typing import Any, Iterable

ANCHOR_FACETS = ("action", "situation", "emotional", "intent", "theme", "metaphor", "visual")
OPERATOR = "operator"
TEXT_FIELDS = {"name": "c.name", "folder": "c.folder", "source": "c.root", "path": "c.rel_path",
               "seen": "c.seen_desc", "said": "c.said", "id": "c.sid", "sid": "c.sid"}
NUM_FIELDS = {"aired": "c.aired", "seconds": "c.seconds"}
BOOL_FIELDS = {"video": "c.video", "embedded": "c.embedded_at", "tagged": "c.tagged_at"}
FIELD_HELP = [
    ("tag:", "any tag, in any facet"), ("folder:", "the clip's folder"), ("source:", "the library it came from"),
    ("name:", "the clip's file name"), ("seen:", "what the vision pass saw in its frames"),
    ("said:", "the words in its sound"), ("path:", "its path inside the library"),
    ("video:yes", "only clips with a picture"), ("video:no", "only sound clips"),
    ("seconds:<5", "shorter than five seconds"), ("aired:0", "never aired"), ("aired:>3", "aired more than 3 times"),
    ("embedded:no", "not embedded yet"), ("tagged:no", "not tagged yet"), ("id:", "the clip's id"),
] + [(f + ":", "a " + f + " tag") for f in ANCHOR_FACETS]
SORTS = {"name": "c.name collate nocase", "folder": "c.folder collate nocase, c.name collate nocase",
         "seconds": "c.seconds", "aired": "c.aired desc, c.name collate nocase",
         "recent": "coalesce(c.last_aired,0) desc", "updated": "coalesce(c.updated,0) desc"}
_WORD = re.compile(r"[a-z0-9']+")
TAGS_TTL_S = 300.0
_TAGS: dict[str, Any] = {"at": 0.0, "con": None, "counts": {}}


def ensure_indexes(con: Any) -> None:
    """Measured on the live section (168,966 clips, ~2.4 M tag rows): a tag
    search scanned every tag row (9.2 s) and the plain list sorted every name
    (3.2 s). These make both index walks. Idempotent; run once at install."""
    con.execute("create index if not exists facet_tags_tag on facet_tags(tag, sid)")
    con.execute("create index if not exists clips_name_nocase on clips(name collate nocase)")
    con.execute("create index if not exists clips_folder_nocase on clips(folder collate nocase)")
    con.commit()


def tag_counts(con: Any, fresh: bool = False) -> dict[tuple[str, str], int]:
    """(facet, tag) -> clips, from the covering index; held TAGS_TTL_S. The
    tag set is small (the anchors and the operator's own), the rows are not."""
    now = time.time()
    if (fresh or _TAGS["con"] is not con or now - float(_TAGS["at"]) > TAGS_TTL_S):
        _TAGS["counts"] = {(f, t): int(n) for f, t, n in con.execute(
            "select facet, tag, count(*) from facet_tags group by facet, tag")}
        _TAGS["at"] = now
        _TAGS["con"] = con
    return _TAGS["counts"]


def _tags_like(con: Any, value: str, facet: str = "") -> list[str]:
    v = str(value or "").lower()
    return sorted({t for (f, t) in tag_counts(con) if v in t.lower() and (not facet or f == facet)})


# ------------------------------------------------------------------ the query

def parse(q: str) -> tuple[str, list[tuple[str, str]]]:
    """'dog tag:funny seconds:<5 "big crash"' -> ('dog big crash', [(tag, funny), (seconds, <5)])"""
    text = str(q or "").strip()
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    free: list[str] = []
    filters: list[tuple[str, str]] = []
    known = set(TEXT_FIELDS) | set(NUM_FIELDS) | set(BOOL_FIELDS) | {"tag"} | set(ANCHOR_FACETS)
    for p in parts:
        if ":" in p:
            field, value = p.split(":", 1)
            field = field.strip().lower()
            if field in known and value.strip():
                filters.append((field, value.strip()))
                continue
        free.append(p)
    return " ".join(free).strip(), filters


def _fts_expr(text: str) -> str:
    """Words as an FTS5 prefix query that cannot be a syntax error."""
    words = _WORD.findall(str(text or "").lower())
    return " ".join('"%s"*' % w for w in words[:12])


def _num_clause(col: str, value: str) -> tuple[str, list[Any]]:
    v = value.replace(" ", "")
    m = re.match(r"^(-?\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)$", v)
    if m:
        return "%s between ? and ?" % col, [float(m.group(1)), float(m.group(2))]
    m = re.match(r"^(<=|>=|<|>|=)?(-?\d+(?:\.\d+)?)$", v)
    if not m:
        return "", []
    op = m.group(1) or "="
    return "coalesce(%s,0) %s ?" % (col, op), [float(m.group(2))]


def _where(text: str, filters: list[tuple[str, str]], con: Any = None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if text:
        expr = _fts_expr(text)
        like = "%" + text + "%"
        one = ("c.name like ? or c.folder like ? or c.root like ? or c.rel_path like ?")
        if expr:
            clauses.append("(c.sid in (select sid from clips_fts where clips_fts match ?) or %s)" % one)
            args += [expr, like, like, like, like]
        else:
            clauses.append("(%s)" % one)
            args += [like, like, like, like]
    for field, value in filters:
        if field in TEXT_FIELDS:
            if field in ("id", "sid"):
                clauses.append("c.sid like ?")
                args.append(value + "%")
            else:
                clauses.append("%s like ?" % TEXT_FIELDS[field])
                args.append("%" + value + "%")
        elif field in NUM_FIELDS:
            c, a = _num_clause(NUM_FIELDS[field], value)
            if c:
                clauses.append(c)
                args += a
        elif field in BOOL_FIELDS:
            yes = value.lower() in ("1", "yes", "true", "y", "on")
            col = BOOL_FIELDS[field]
            if field == "video":
                clauses.append("%s = ?" % col)
                args.append(1 if yes else 0)
            else:
                clauses.append("%s is %s null" % (col, "not" if yes else ""))
        elif field == "tag" or field in ANCHOR_FACETS:
            facet = "" if field == "tag" else field
            names = _tags_like(con, value, facet) if con is not None else []
            if not names:
                clauses.append("0")                     # no such tag: nothing matches
                continue
            marks = ",".join("?" * len(names))
            if facet:
                clauses.append("c.sid in (select sid from facet_tags where tag in (%s) and facet = ?)" % marks)
                args += names + [facet]
            else:
                clauses.append("c.sid in (select sid from facet_tags where tag in (%s))" % marks)
                args += names
    return (" where " + " and ".join(clauses)) if clauses else "", args


def search(con: Any, q: str = "", sort: str = "name", limit: int = 60, offset: int = 0) -> dict[str, Any]:
    text, filters = parse(q)
    where, args = _where(text, filters, con)
    order = SORTS.get(sort, SORTS["name"])
    total = con.execute("select count(*) from clips c" + where, args).fetchone()[0]
    rows = con.execute(
        "select c.sid, c.name, c.folder, c.root, c.rel_path, c.video, c.seconds, c.said, c.seen_desc, "
        "c.aired, c.last_aired, c.embedded_at, c.tagged_at, c.updated from clips c" + where
        + " order by " + order + " limit ? offset ?",
        args + [max(1, min(500, int(limit))), max(0, int(offset))]).fetchall()
    out = []
    for r in rows:
        out.append({"sid": r[0], "name": r[1], "folder": r[2], "source": r[3], "path": r[4],
                    "video": bool(r[5]), "seconds": r[6], "said": r[7] or "", "seen": r[8] or "",
                    "aired": r[9] or 0, "last_aired": r[10], "embedded": bool(r[11]), "tagged": bool(r[12]),
                    "updated": r[13], "tags": []})
    by = {o["sid"]: o for o in out}
    if by:
        marks = ",".join("?" * len(by))
        for sid, facet, tag, w, how in con.execute(
                "select sid, facet, tag, weight, how from facet_tags where sid in (%s) order by weight desc" % marks,
                list(by)):
            by[sid]["tags"].append({"facet": facet, "tag": tag, "weight": round(float(w), 3), "how": how or ""})
    return {"q": q, "text": text, "filters": [{"field": f, "value": v} for f, v in filters],
            "total": int(total), "offset": int(offset), "rows": out}


def suggest(con: Any, typed: str, most: int = 6) -> list[dict[str, Any]]:
    """What the last word typed could be, grouped: fields, tags, folders,
    sources, clips, seen words. Each carries the token it puts in the bar."""
    raw = str(typed or "").strip()
    field = ""
    word = raw
    if ":" in raw:
        field, word = raw.split(":", 1)
        field = field.strip().lower()
    word = word.strip().strip('"')
    like = "%" + word + "%"
    out: list[dict[str, Any]] = []

    def tok(f: str, v: str) -> str:
        v = str(v)
        return '%s:"%s"' % (f, v) if re.search(r"\s", v) else "%s:%s" % (f, v)

    if not field:
        for token, what in FIELD_HELP:
            if word and token.lower().startswith(word.lower()):
                out.append({"group": "parameter", "label": token, "detail": what, "token": token})
        out = out[:most]
    if field in ("", "tag") or field in ANCHOR_FACETS:
        w = word.lower()
        hits = [(n, f, t) for (f, t), n in tag_counts(con).items()
                if (not w or w in t.lower()) and (field not in ANCHOR_FACETS or f == field)]
        hits.sort(key=lambda h: (not h[2].lower().startswith(w), -h[0]))
        for n, facet, tag in hits[:most]:
            out.append({"group": "tag", "label": tag, "detail": "%s tag - %d clip%s" % (facet, n, "" if n == 1 else "s"),
                        "token": tok(facet if field in ANCHOR_FACETS else "tag", tag)})
    if field in ("", "folder"):
        for folder, n in con.execute("select folder, count(*) n from clips where folder like ? and folder <> '' "
                                     "group by folder order by n desc limit ?", (like, most)):
            out.append({"group": "folder", "label": folder, "detail": "%d clip%s" % (n, "" if n == 1 else "s"),
                        "token": tok("folder", folder)})
    if field in ("", "source"):
        for root, n in con.execute("select root, count(*) n from clips where root like ? group by root "
                                   "order by n desc limit ?", (like, most)):
            out.append({"group": "source", "label": root, "detail": "%d clip%s" % (n, "" if n == 1 else "s"),
                        "token": tok("source", root)})
    if field in ("", "name", "id", "sid"):
        col = "sid" if field in ("id", "sid") else "name"
        for sid, name, folder in con.execute("select sid, name, folder from clips where %s like ? "
                                             "order by length(name) limit ?" % col,
                                             ((word + "%") if col == "sid" else like, most)):
            out.append({"group": "clip", "label": name or sid, "detail": folder or "", "sid": sid,
                        "token": tok("id", sid)})
    if word and field in ("", "seen"):
        seen: dict[str, int] = {}
        for (desc,) in con.execute("select seen_desc from clips where seen_desc like ? limit 400", (like,)):
            for piece in str(desc or "").split(","):
                p = " ".join(piece.split()).strip(" .").lower()
                if p and word.lower() in p and len(p) <= 60:
                    seen[p] = seen.get(p, 0) + 1
        for p, n in sorted(seen.items(), key=lambda kv: -kv[1])[:most]:
            out.append({"group": "seen", "label": p, "detail": "seen in %d clip%s" % (n, "" if n == 1 else "s"),
                        "token": tok("seen", p)})
    if word and field in ("", "said"):
        n = con.execute("select count(*) from clips where said like ?", (like,)).fetchone()[0]
        if n:
            out.append({"group": "said", "label": 'said "%s"' % word, "detail": "%d clip%s" % (n, "" if n == 1 else "s"),
                        "token": tok("said", word)})
    return out


# ------------------------------------------------------------------ edits

def _fts_tags(con: Any, sid: str) -> None:
    tags = " ".join(t for (t,) in con.execute("select tag from facet_tags where sid=?", (sid,)))
    con.execute("update clips_fts set tags=? where sid=?", (tags, sid))


def tag_add(con: Any, sid: str, facet: str, tag: str) -> bool:
    facet = str(facet or "").strip().lower() or "visual"
    tag = " ".join(str(tag or "").split())[:60]
    if not tag or not con.execute("select 1 from clips where sid=?", (sid,)).fetchone():
        return False
    con.execute("insert or replace into facet_tags(sid, facet, tag, weight, how) values(?,?,?,?,?)",
                (sid, facet, tag, 1.0, OPERATOR))
    _fts_tags(con, sid)
    con.commit()
    _TAGS["at"] = 0.0                                  # a new tag is searchable at once
    return True


def tag_remove(con: Any, sid: str, facet: str, tag: str) -> bool:
    cur = con.execute("delete from facet_tags where sid=? and facet=? and tag=?", (sid, facet, tag))
    _fts_tags(con, sid)
    con.commit()
    _TAGS["at"] = 0.0
    return cur.rowcount > 0


# ------------------------------------------------------------------ export

EXPORT_COLUMNS = ("sid", "name", "folder", "source", "path", "video", "seconds", "aired", "last_aired",
                  "playable", "bytes", "banned", "weight", "tags", "seen", "said")


def export_text(rows: Iterable[dict[str, Any]], fmt: str = "csv") -> str:
    rows = list(rows)
    if fmt == "json":
        return json.dumps(rows, indent=1, default=str)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EXPORT_COLUMNS)
    for r in rows:
        tags = "; ".join("%s:%s" % (t.get("facet"), t.get("tag")) for t in (r.get("tags") or []))
        w.writerow([r.get(k) if k != "tags" else tags for k in EXPORT_COLUMNS])
    return buf.getvalue()


# ------------------------------------------------------------- is it still there

def file_state(path: Any, roots: Iterable[Any] = ()) -> str:
    """'here', 'gone' or 'unreachable' for a clip's file on the share.

    [sfx-gone] "the sfx database unable to play videos" - the operator,
    2026-10-01. The clip book said playable for a file the share no longer
    held, so the table offered a player that could only ever get a 404 (a
    <video> reads it as a black box at 0:00). 'gone' is only said when the
    library root the file lives under answers: an unmounted share is
    'unreachable', never a reason to stand a clip down."""
    if not path:
        return "unreachable"
    p = Path(str(path))
    try:
        if p.is_file():
            return "here"
    except OSError:
        return "unreachable"
    for root in roots:
        if not root:
            continue
        try:
            r = Path(str(root))
            if p.is_relative_to(r):
                return "gone" if r.is_dir() and any(r.iterdir()) else "unreachable"
        except OSError:
            return "unreachable"
    try:
        return "gone" if p.parent.parent.is_dir() else "unreachable"
    except OSError:
        return "unreachable"


# ------------------------------------------------------------------ the routes

def install(app: Any, namespace: dict[str, Any]) -> None:
    from fastapi import Header, HTTPException, Request

    globals()["Request"] = Request

    def ns(name: str) -> Any:
        return namespace.get(name)

    def runtime():
        get = ns("_sfx_vectors")
        rt = get() if callable(get) else None
        if rt is None:
            raise HTTPException(503, "the SFX Guy's vector section is not open")
        return rt

    def book_rows(sids: list[str]) -> dict[str, dict[str, Any]]:
        """The clip book's own columns for these clips (read-only connection)."""
        out: dict[str, dict[str, Any]] = {}
        reader = ns("sfx_db_reader")
        if not sids or not callable(reader):
            return out
        try:
            con = reader()
            cols = [r[1] for r in con.execute("PRAGMA table_info(clips)")]
            want = [c for c in ("sid", "path", "playable", "bytes", "mtime", "seen_at", "said_at", "seen_desc_at",
                                "deck_cycle") if c in cols]
            marks = ",".join("?" * len(sids))
            for row in con.execute("select %s from clips where sid in (%s)" % (",".join(want), marks), sids):
                d = dict(zip(want, row))
                out[str(d.get("sid"))] = d
        except Exception:  # noqa: BLE001
            pass
        return out

    def dress(rows: list[dict[str, Any]], look: bool = True) -> None:
        """Blocking (sqlite, and one stat per clip when look): off the loop."""
        sign = ns("media_sign")
        bans = set()
        weights: dict[str, float] = {}
        try:
            bans = set(ns("sfx_bans")() or ())
        except Exception:  # noqa: BLE001
            pass
        try:
            weights = dict(ns("sfx_weights")() or {})
        except Exception:  # noqa: BLE001
            pass
        book = book_rows([r["sid"] for r in rows])
        reach = ns("sfx_reachable")
        if look and callable(reach) and not reach():
            look = False                    # [sfx-reach] no look for gone files on a share that is away
        for r in rows:
            b = book.get(r["sid"]) or {}
            r["playable"] = bool(b.get("playable")) if b else None
            r["missing"] = False
            if look and b.get("path") and file_state(b["path"], roots()) == "gone":
                # [sfx-gone] the book lists it, the share does not hold it:
                # say so, and stand it down the way the /sfx route does
                r["missing"] = True
                r["playable"] = False
                gone(r["sid"], b["path"])
            r["bytes"] = b.get("bytes")
            r["seen_at"] = b.get("seen_desc_at")
            r["said_at"] = b.get("said_at")
            r["banned"] = r["sid"] in bans
            r["weight"] = float(weights.get(r["sid"], 1.0))
            t = sign(r["sid"]) if callable(sign) else ""
            r["media"] = "" if r["missing"] else "/sfx/%s?t=%s" % (r["sid"], t)
            r["poster"] = ("/api/sfx/poster/%s?t=%s" % (r["sid"], t)) if r.get("video") and not r["missing"] else ""

    def roots() -> list[Any]:
        return [ns("SFX_ROOT"), ns("SFX_LOCAL_ROOT")]

    def gone(sid: str, path: Any) -> None:
        quarantine = ns("sfx_quarantine")
        if callable(quarantine):
            try:
                quarantine(sid, "the file is gone from the share (seen by the SFX database)", path,
                           "the SFX database")
            except Exception:  # noqa: BLE001
                pass

    # [sfx-vision-idle] the keeper that studies his clips while the station rests
    try:
        from sfx_vision_idle import install as install_vision_idle
        install_vision_idle(app, namespace)
    except Exception as exc:  # noqa: BLE001
        print("sfx vision idle did not install: %s: %s" % (type(exc).__name__, exc))

    @app.on_event("startup")
    async def sfx_library_indexes():
        try:
            rt = runtime()
            await rt.run(ensure_indexes, rt.store.con)
            await rt.run(tag_counts, rt.store.con, True)
        except Exception as exc:  # noqa: BLE001
            print("sfx library indexes: %s: %s" % (type(exc).__name__, exc))

    @app.get("/api/sfx/library")
    async def sfx_library_search(q: str = "", sort: str = "name", limit: int = 60, offset: int = 0,
                                 authorization: str | None = Header(default=None)):
        ns("require_read_auth")(authorization)
        rt = runtime()
        got = await rt.run(search, rt.store.con, q, sort, limit, offset)
        await asyncio.to_thread(dress, got["rows"])
        got["sorts"] = list(SORTS)
        got["facets"] = list(ANCHOR_FACETS)
        return got

    @app.get("/api/sfx/library/suggest")
    async def sfx_library_suggest(q: str = "", authorization: str | None = Header(default=None)):
        ns("require_read_auth")(authorization)
        rt = runtime()
        return {"q": q, "items": await rt.run(suggest, rt.store.con, q)}

    @app.get("/api/sfx/library/clip/{sid}")
    async def sfx_library_clip(sid: str, authorization: str | None = Header(default=None)):
        ns("require_read_auth")(authorization)
        rt = runtime()
        got = await rt.run(rt.store.clip, sid)
        if not got:
            raise HTTPException(404, "no clip %s in the database" % sid)
        tags = []
        for facet, items in (got.get("facets") or {}).items():
            for tag, w in items:
                tags.append({"facet": facet, "tag": tag, "weight": w})
        hows = await rt.run(lambda: dict(((f, t), h) for f, t, h in rt.store.con.execute(
            "select facet, tag, how from facet_tags where sid=?", (sid,))))
        for t in tags:
            t["how"] = hows.get((t["facet"], t["tag"]), "")
        row = {"sid": sid, "name": got.get("name"), "folder": got.get("folder"), "source": got.get("root"),
               "path": got.get("rel_path"), "file": got.get("path"), "video": got.get("video"),
               "seconds": got.get("seconds"), "said": got.get("said") or "", "seen": got.get("seen_desc") or "",
               "aired": got.get("aired") or 0, "last_aired": got.get("last_aired"),
               "embedded": got.get("embedded"), "tagged": got.get("tagged"), "tags": tags,
               "dialogue": got.get("dialogue") or []}
        await asyncio.to_thread(dress, [row])
        book = await asyncio.to_thread(lambda: book_rows([sid]).get(sid) or {})
        row["book"] = {k: v for k, v in book.items() if k not in ("sid",)}
        frames = ns("sfx_frames_of")
        if callable(frames):
            try:
                row["frames"] = frames(sid)
            except Exception:  # noqa: BLE001
                row["frames"] = []
        return row

    @app.post("/api/sfx/library/clip/{sid}")
    async def sfx_library_edit(sid: str, request: Request, authorization: str | None = Header(default=None)):
        """Edit an entry: what was seen, what was said, its tags. The words go
        to the clip book (the keeper carries them to the vectors and the matcher
        is rebuilt); a tag goes straight to the section as the operator's."""
        ns("require_auth")(authorization)
        body = await request.json()
        rt = runtime()
        did: list[str] = []
        texts = {k: body[k] for k in ("seen", "said") if isinstance(body.get(k), str)}
        if texts:
            path = ns("sfx_by_id")(sid)
            if path is None:
                raise HTTPException(404, "no clip %s in the clip book" % sid)
            writer, lock = ns("sfx_db")(), ns("_SFX_DB_LOCK")
            now = time.time()

            def write():
                with lock:
                    if "seen" in texts:
                        writer.execute("UPDATE clips SET seen_desc=?, seen_desc_at=? WHERE path=?",
                                       (texts["seen"][:600], now, str(path)))
                    if "said" in texts:
                        writer.execute("UPDATE clips SET said=?, said_at=? WHERE path=?",
                                       (texts["said"][:4000], now, str(path)))
                    writer.commit()
            await asyncio.to_thread(write)
            did += sorted(texts)
            kick = ns("sfx_match_kick")
            if callable(kick):
                kick()
        for t in body.get("tags_add") or []:
            if await rt.run(tag_add, rt.store.con, sid, str(t.get("facet") or ""), str(t.get("tag") or "")):
                did.append("tag +%s" % t.get("tag"))
        for t in body.get("tags_remove") or []:
            if await rt.run(tag_remove, rt.store.con, sid, str(t.get("facet") or ""), str(t.get("tag") or "")):
                did.append("tag -%s" % t.get("tag"))
        return {"sid": sid, "did": did}

    @app.post("/api/sfx/library/export")
    async def sfx_library_export(request: Request, authorization: str | None = Header(default=None)):
        """What the search shows, as CSV or JSON, into the recordings folder
        through the courier (the desk carries it to the share)."""
        ns("require_auth")(authorization)
        body = await request.json()
        fmt = "json" if str(body.get("format") or "csv").lower() == "json" else "csv"
        rt = runtime()
        got = await rt.run(search, rt.store.con, str(body.get("q") or ""), str(body.get("sort") or "name"),
                           5000, 0)
        # no stat per row: five thousand of them over the share is minutes
        await asyncio.to_thread(dress, got["rows"], False)
        text = export_text(got["rows"], fmt)
        out_dir = Path(ns("data_path")("exports"))
        out_dir.mkdir(parents=True, exist_ok=True)
        name = "sfx-database-%s.%s" % (time.strftime("%Y%m%d-%H%M%S"), fmt)
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        where = ""
        try:
            dest = ns("export_desk_dir")()
            if dest:
                ns("courier_add")(path, dest, "sfx-database", name=name)
                where = dest
        except Exception:  # noqa: BLE001
            where = ""
        return {"ok": True, "rows": len(got["rows"]), "file": name, "where": where or str(out_dir),
                "say": "%d clip%s written to %s" % (len(got["rows"]), "" if len(got["rows"]) == 1 else "s",
                                                   where or "the station's exports folder")}
