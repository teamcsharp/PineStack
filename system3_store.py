"""System 3's durable ledger: data/system3.sqlite3.

The ONE authoritative source for System 3 state and decisions (blueprint
section 6: "define one authoritative System 3 event/state source").
FlowJournal may carry observational copies; this is the record.

    settings      current operator settings (mode, roads, controls, ...)
    configs       every config version ever used, by hash, so an old
                  conversation stays interpretable after the tables change
    conversations the aggregate, compressed, plus the columns lists need
    events        every decision event, and every observation made later
                  (door outcome, SFX at air, script commit), one row each,
                  with a global autoincrement id - the incremental cursor
                  the live Rolodex polls
    lines         script-ledger line id -> conversation/turn, written when a
                  round is committed: the join from a spoken line back to
                  the decisions that produced it

Every method is synchronous and is only ever called from the runtime's
own single-thread executor, never from the event loop.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import zlib
from pathlib import Path

import system3


def _pack(value):
    return zlib.compress(json.dumps(value, separators=(",", ":"), default=str).encode("utf-8"), 6)


def _unpack(blob):
    if blob is None:
        return None
    return json.loads(zlib.decompress(blob).decode("utf-8"))


class System3Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=15)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA busy_timeout=15000")
        with self.db:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS configs(hash TEXT PRIMARY KEY, created REAL NOT NULL, note TEXT, body BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS conversations(
                id TEXT PRIMARY KEY, created REAL NOT NULL, updated REAL NOT NULL,
                road TEXT, mode TEXT, status TEXT, trace_id TEXT, slot_id TEXT,
                seed TEXT, config_hash TEXT, verdict TEXT, score REAL,
                summary TEXT NOT NULL, body BLOB NOT NULL);
            CREATE INDEX IF NOT EXISTS conv_created ON conversations(created);
            CREATE INDEX IF NOT EXISTS conv_trace ON conversations(trace_id);
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
                seq INTEGER, kind TEXT NOT NULL, family TEXT, turn_id TEXT, at REAL NOT NULL,
                body BLOB NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS events_decision ON events(conversation_id, seq) WHERE kind='decision';
            CREATE INDEX IF NOT EXISTS events_conv ON events(conversation_id, id);
            CREATE TABLE IF NOT EXISTS lines(
                line_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, turn_id TEXT,
                block INTEGER, ord INTEGER, sid TEXT, who TEXT, text TEXT, at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS lines_conv ON lines(conversation_id);
            CREATE TABLE IF NOT EXISTS segments(
                id TEXT PRIMARY KEY, kind TEXT, label TEXT, start REAL, ends REAL,
                first_block INTEGER, last_block INTEGER, first_at REAL, last_at REAL,
                lines INTEGER NOT NULL DEFAULT 0, body TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS segments_last ON segments(last_at);
            CREATE INDEX IF NOT EXISTS segments_first ON segments(first_block);
            CREATE TABLE IF NOT EXISTS segment_blocks(
                block INTEGER PRIMARY KEY, segment_id TEXT NOT NULL, at REAL NOT NULL,
                sid TEXT, round TEXT, lines INTEGER NOT NULL DEFAULT 0,
                line_ids TEXT NOT NULL, conversations TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS segment_blocks_seg ON segment_blocks(segment_id, block);
            """)

    # --- settings and config ------------------------------------------------
    def settings(self):
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key='settings'").fetchone()
        return system3.normalise_settings(json.loads(row[0]) if row else {})

    def save_settings(self, value):
        value = system3.normalise_settings(value)
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES('settings',?,?)",
                            (json.dumps(value), time.time()))
        return value

    def config(self):
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key='config'").fetchone()
            if row:
                got = self.db.execute("SELECT body FROM configs WHERE hash=?", (row[0],)).fetchone()
                if got:
                    return _unpack(got[0])
        cfg = system3.default_config()
        self.save_config(cfg, note="default")
        return cfg

    def save_config(self, config, note=""):
        h = system3.config_hash(config)
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO configs VALUES(?,?,?,?)",
                            (h, time.time(), str(note or "")[:200], _pack(config)))
            self.db.execute("INSERT OR REPLACE INTO settings VALUES('config',?,?)", (h, time.time()))
        return h

    def config_by_hash(self, h):
        with self.lock:
            row = self.db.execute("SELECT body FROM configs WHERE hash=?", (h,)).fetchone()
        return _unpack(row[0]) if row else None

    def config_versions(self, limit=50):
        with self.lock:
            rows = self.db.execute("SELECT hash, created, note FROM configs ORDER BY created DESC LIMIT ?",
                                   (int(limit),)).fetchall()
        return [{"hash": h, "created": c, "note": n} for h, c, n in rows]

    # --- conversations ----------------------------------------------------------
    def save_conversation(self, conv):
        """Upsert the aggregate and insert any decision event not yet held.
        The aggregate is stored without its events; they live in `events`."""
        body = dict(conv)
        events = body.pop("decision_events", [])
        summ = system3.summary(conv)
        ident = conv["identity"]
        val = conv.get("validation") or {}
        now = time.time()
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO conversations(id,created,updated,road,mode,status,trace_id,slot_id,seed,"
                "config_hash,verdict,score,summary,body) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET updated=excluded.updated, mode=excluded.mode, "
                "status=excluded.status, verdict=excluded.verdict, score=excluded.score, "
                "summary=excluded.summary, body=excluded.body",
                (ident["conversation_id"], float(conv.get("created") or now), now, ident["road_kind"],
                 conv.get("mode"), conv.get("status"), ident["trace_id"], ident.get("system2_slot_id"),
                 conv.get("seed"), conv.get("config_hash"), val.get("verdict"), val.get("score"),
                 json.dumps(summ), _pack(body)))
            have = {r[0] for r in self.db.execute(
                "SELECT seq FROM events WHERE conversation_id=? AND kind='decision'", (ident["conversation_id"],))}
            rows = [(e["conversation_id"], e["seq"], "decision", e["family"], e.get("turn_id"),
                     float(e.get("at") or now), _pack(e)) for e in events if e["seq"] not in have]
            if rows:
                self.db.executemany("INSERT OR IGNORE INTO events(conversation_id,seq,kind,family,turn_id,at,body) "
                                    "VALUES(?,?,?,?,?,?,?)", rows)
        return len(rows)

    def add_observation(self, conversation_id, family, body, turn_id=""):
        body = dict(body)
        body.setdefault("at", time.time())
        body["kind"] = "observation"
        body["family"] = family
        body["conversation_id"] = conversation_id
        with self.lock, self.db:
            cur = self.db.execute("INSERT INTO events(conversation_id,seq,kind,family,turn_id,at,body) "
                                  "VALUES(?,?,?,?,?,?,?)",
                                  (conversation_id, None, "observation", family, turn_id or body.get("turn_id"),
                                   float(body["at"]), _pack(body)))
            return cur.lastrowid

    def add_lines(self, rows):
        with self.lock, self.db:
            self.db.executemany("INSERT OR REPLACE INTO lines VALUES(?,?,?,?,?,?,?,?,?)",
                                [(r["line_id"], r["conversation_id"], r.get("turn_id"), r.get("block"),
                                  r.get("ord"), r.get("sid"), r.get("who"), str(r.get("text") or "")[:2000],
                                  float(r.get("at") or time.time())) for r in rows if r.get("line_id")])

    def conversations(self, limit=50, road="", before=0.0, mode=""):
        sql = "SELECT summary FROM conversations WHERE 1=1"
        args = []
        if road:
            sql += " AND road=?"
            args.append(road)
        if mode:
            sql += " AND mode=?"
            args.append(mode)
        if before:
            sql += " AND created<?"
            args.append(float(before))
        sql += " ORDER BY created DESC LIMIT ?"
        args.append(max(1, min(500, int(limit))))
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute(sql, args).fetchall()]

    def conversation(self, cid, with_events=True):
        with self.lock:
            row = self.db.execute("SELECT body FROM conversations WHERE id=?", (cid,)).fetchone()
            if not row:
                return None
            conv = _unpack(row[0])
            if with_events:
                evs = self.db.execute("SELECT id, kind, body FROM events WHERE conversation_id=? ORDER BY id",
                                      (cid,)).fetchall()
            else:
                evs = []
            # [s3-segment] each line with the scheduled segment its block went out in
            lines = self.db.execute("SELECT l.line_id, l.turn_id, l.block, l.ord, l.sid, l.who, l.text, l.at, "
                                    "b.segment_id FROM lines l LEFT JOIN segment_blocks b ON b.block = l.block "
                                    "WHERE l.conversation_id=? ORDER BY l.block, l.ord", (cid,)).fetchall()
        conv["decision_events"] = []
        conv["observations_air"] = []
        for rid, kind, blob in evs:
            ev = _unpack(blob)
            ev["cursor"] = rid
            (conv["decision_events"] if kind == "decision" else conv["observations_air"]).append(ev)
        conv["decision_events"].sort(key=lambda e: e.get("seq", 0))
        conv["lines"] = [{"line_id": a, "turn_id": b, "block": c, "ord": d, "sid": e, "who": f,
                          "text": g, "at": h, "segment": i} for a, b, c, d, e, f, g, h, i in lines]
        return conv

    def events_after(self, cursor=0, limit=200, conversation_id=""):
        sql = "SELECT id, kind, body FROM events WHERE id>?"
        args = [int(cursor)]
        if conversation_id:
            sql += " AND conversation_id=?"
            args.append(conversation_id)
        sql += " ORDER BY id LIMIT ?"
        args.append(max(1, min(1000, int(limit))))
        with self.lock:
            rows = self.db.execute(sql, args).fetchall()
            last = self.db.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
        out = []
        for rid, kind, blob in rows:
            ev = _unpack(blob)
            ev["cursor"] = rid
            ev["kind"] = kind
            out.append(ev)
        return {"events": out, "cursor": out[-1]["cursor"] if out else int(cursor), "head": last}

    def line(self, line_id):
        with self.lock:
            row = self.db.execute("SELECT l.line_id, l.conversation_id, l.turn_id, l.block, l.ord, l.sid, l.who, "
                                  "l.text, l.at, b.segment_id FROM lines l "
                                  "LEFT JOIN segment_blocks b ON b.block = l.block "      # [s3-segment]
                                  "WHERE l.line_id=?", (line_id,)).fetchone()
        if not row:
            return None
        keys = ("line_id", "conversation_id", "turn_id", "block", "ord", "sid", "who", "text", "at", "segment")
        return dict(zip(keys, row))

    # --- [s3-segment] the segment register -------------------------------------
    def note_segment_block(self, segment, block, at, sid="", round_kind="", line_ids=None,
                           conversations=None):
        """One block of the script, written while `segment` owned the air: its
        lines and, by conversation, the lines each System 3 conversation has in
        it. A block committed in two parts (a numbered line heard after its
        neighbour) is merged; a block keeps the segment it was first filed in."""
        seg_id = str((segment or {}).get("id") or "")
        if not seg_id:
            return None
        block = int(block)
        at = float(at or time.time())
        lids = [str(x) for x in (line_ids or []) if x]
        convs = {str(k): [str(x) for x in (v or []) if x] for k, v in (conversations or {}).items() if k}
        with self.lock, self.db:
            got = self.db.execute("SELECT segment_id, line_ids, conversations, at FROM segment_blocks WHERE block=?",
                                  (block,)).fetchone()
            if got:
                seg_id = got[0]
                had = json.loads(got[1] or "[]")
                lids = had + [x for x in lids if x not in had]
                old = json.loads(got[2] or "{}")
                for cid, ids in convs.items():
                    old[cid] = old.get(cid, []) + [x for x in ids if x not in old.get(cid, [])]
                convs = old
                at = min(at, float(got[3] or at))
            self.db.execute("INSERT OR REPLACE INTO segment_blocks(block, segment_id, at, sid, round, lines, line_ids, "
                            "conversations) VALUES(?,?,?,?,?,?,?,?)",
                            (block, seg_id, at, str(sid or ""), str(round_kind or ""), len(lids),
                             json.dumps(lids), json.dumps(convs)))
            if got and got[0] != str(segment.get("id") or ""):
                body = self.db.execute("SELECT body FROM segments WHERE id=?", (seg_id,)).fetchone()
                segment = json.loads(body[0]) if body else dict(segment, id=seg_id)
            self.db.execute(
                "INSERT INTO segments(id, kind, label, start, ends, first_block, last_block, first_at, last_at, lines, body) "
                "VALUES(?,?,?,?,?,?,?,?,?,0,?) ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, label=excluded.label, "
                "start=excluded.start, ends=excluded.ends, first_block=MIN(first_block, excluded.first_block), "
                "last_block=MAX(last_block, excluded.last_block), first_at=MIN(first_at, excluded.first_at), "
                "last_at=MAX(last_at, excluded.last_at), body=excluded.body",
                (seg_id, str(segment.get("kind") or ""), str(segment.get("label") or ""),
                 float(segment.get("start") or 0), float(segment.get("ends") or 0), block, block, at, at,
                 json.dumps(segment)))
            self.db.execute("UPDATE segments SET lines=(SELECT COALESCE(SUM(lines), 0) FROM segment_blocks "
                            "WHERE segment_id=?) WHERE id=?", (seg_id, seg_id))
        return seg_id

    @staticmethod
    def _segment_row(row):
        sid_, first_block, last_block, first_at, last_at, lines, body = row
        seg = json.loads(body or "{}")
        seg.update({"id": sid_, "first_block": first_block, "last_block": last_block,
                    "first_at": first_at, "last_at": last_at, "lines": int(lines or 0)})
        return seg

    def _segment_blocks(self, seg_id):
        rows = self.db.execute("SELECT block, at, sid, round, lines, line_ids, conversations FROM segment_blocks "
                               "WHERE segment_id=? ORDER BY block", (seg_id,)).fetchall()
        return [{"block": b, "at": a, "sid": s, "round": r, "lines": int(n or 0),
                 "line_ids": json.loads(li or "[]"), "conversations": json.loads(cv or "{}")}
                for b, a, s, r, n, li, cv in rows]

    @staticmethod
    def _segment_conversations(blocks):
        """The conversations of a segment in the order they entered its script,
        with the blocks and lines each has in it."""
        out = {}
        for b in blocks:
            for cid, ids in (b.get("conversations") or {}).items():
                got = out.setdefault(cid, {"conversation_id": cid, "first_block": b["block"], "first_at": b["at"],
                                           "blocks": [], "line_ids": []})
                got["blocks"].append(b["block"])
                got["line_ids"].extend(x for x in ids if x not in got["line_ids"])
        return list(out.values())

    def segments_since(self, since=0.0, limit=40, until=0.0):
        """The segments the script went through since `since` (and before `until`),
        in the script's own order, each with its conversations."""
        sql = ("SELECT id, first_block, last_block, first_at, last_at, lines, body FROM segments "
               "WHERE last_at>=?")
        args = [float(since or 0)]
        if until:
            sql += " AND first_at<=?"
            args.append(float(until))
        sql += " ORDER BY first_block DESC LIMIT ?"
        args.append(max(1, min(500, int(limit or 40))))
        with self.lock:
            rows = self.db.execute(sql, args).fetchall()
            out = []
            for row in reversed(rows):
                seg = self._segment_row(row)
                blocks = self._segment_blocks(seg["id"])
                seg["blocks"] = len(blocks)
                seg["conversations"] = self._segment_conversations(blocks)
                out.append(seg)
        return out

    def segment_record(self, seg_id):
        """One segment: its entry, every block it holds (lines and conversations),
        and the segments either side of it in the script."""
        with self.lock:
            row = self.db.execute("SELECT id, first_block, last_block, first_at, last_at, lines, body FROM segments "
                                  "WHERE id=?", (str(seg_id),)).fetchone()
            if not row:
                return None
            seg = self._segment_row(row)
            blocks = self._segment_blocks(seg["id"])
            prev = self.db.execute("SELECT id, first_block, last_block, first_at, last_at, lines, body FROM segments "
                                   "WHERE first_block<? ORDER BY first_block DESC LIMIT 1",
                                   (seg["first_block"],)).fetchone()
            nxt = self.db.execute("SELECT id, first_block, last_block, first_at, last_at, lines, body FROM segments "
                                  "WHERE first_block>? ORDER BY first_block LIMIT 1", (seg["first_block"],)).fetchone()
        return {"segment": seg, "blocks": blocks, "conversations": self._segment_conversations(blocks),
                "previous": self._segment_row(prev) if prev else None,
                "next": self._segment_row(nxt) if nxt else None}

    def summaries(self, ids):
        """conversation id -> its list row, for the ids still held."""
        ids = [str(x) for x in dict.fromkeys(ids or []) if x]
        out = {}
        with self.lock:
            for i in range(0, len(ids), 400):
                chunk = ids[i:i + 400]
                for cid, summ in self.db.execute("SELECT id, summary FROM conversations WHERE id IN (%s)"
                                                 % ",".join("?" * len(chunk)), chunk):
                    out[cid] = json.loads(summ)
        return out

    def prepared_for(self, slot_id, since=0.0, limit=40):
        """The conversations System2 had written FOR this slot (its job's slot)."""
        with self.lock:
            rows = self.db.execute("SELECT summary FROM conversations WHERE created>? AND slot_id=? "
                                   "ORDER BY created LIMIT ?", (float(since or 0), str(slot_id),
                                                                max(1, min(200, int(limit))))).fetchall()
        return [json.loads(r[0]) for r in rows]

    def counts(self):
        with self.lock:
            conv = self.db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            evs = self.db.execute("SELECT COUNT(*), COALESCE(MAX(id),0) FROM events").fetchone()
            lines = self.db.execute("SELECT COUNT(*) FROM lines").fetchone()[0]
            segs = self.db.execute("SELECT COUNT(*) FROM segments").fetchone()[0]   # [s3-segment]
            modes = dict(self.db.execute("SELECT mode, COUNT(*) FROM conversations GROUP BY mode").fetchall())
            verdicts = dict(self.db.execute("SELECT COALESCE(verdict,'unbound'), COUNT(*) FROM conversations "
                                            "WHERE created>? GROUP BY verdict", (time.time() - 86400,)).fetchall())
        size = self.path.stat().st_size if self.path.exists() else 0
        return {"conversations": conv, "events": evs[0], "head": evs[1], "lines": lines, "segments": segs,
                "modes": modes, "verdicts_24h": verdicts, "bytes": size}

    def retention(self, max_age_days=7.0, max_conversations=30000):
        """Old conversations go, with their events and lines. The config
        versions they referenced stay: they are small and they are what
        makes any surviving export interpretable."""
        cut = time.time() - float(max_age_days) * 86400
        with self.lock, self.db:
            ids = [r[0] for r in self.db.execute("SELECT id FROM conversations WHERE created<?", (cut,))]
            extra = self.db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] - int(max_conversations)
            if extra > 0:
                ids += [r[0] for r in self.db.execute(
                    "SELECT id FROM conversations ORDER BY created LIMIT ?", (extra,))]
            ids = list(dict.fromkeys(ids))
            for i in range(0, len(ids), 400):
                chunk = ids[i:i + 400]
                marks = ",".join("?" * len(chunk))
                self.db.execute("DELETE FROM events WHERE conversation_id IN (%s)" % marks, chunk)
                self.db.execute("DELETE FROM lines WHERE conversation_id IN (%s)" % marks, chunk)
                self.db.execute("DELETE FROM conversations WHERE id IN (%s)" % marks, chunk)
        with self.lock, self.db:                                    # [s3-segment] the register ages too
            self.db.execute("DELETE FROM segment_blocks WHERE at<?", (cut,))
            self.db.execute("DELETE FROM segments WHERE last_at<?", (cut,))
        return len(ids)

    def close(self):
        with self.lock:
            self.db.close()
