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
            lines = self.db.execute("SELECT line_id, turn_id, block, ord, sid, who, text, at FROM lines "
                                    "WHERE conversation_id=? ORDER BY block, ord", (cid,)).fetchall()
        conv["decision_events"] = []
        conv["observations_air"] = []
        for rid, kind, blob in evs:
            ev = _unpack(blob)
            ev["cursor"] = rid
            (conv["decision_events"] if kind == "decision" else conv["observations_air"]).append(ev)
        conv["decision_events"].sort(key=lambda e: e.get("seq", 0))
        conv["lines"] = [{"line_id": a, "turn_id": b, "block": c, "ord": d, "sid": e, "who": f,
                          "text": g, "at": h} for a, b, c, d, e, f, g, h in lines]
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
            row = self.db.execute("SELECT line_id, conversation_id, turn_id, block, ord, sid, who, text, at "
                                  "FROM lines WHERE line_id=?", (line_id,)).fetchone()
        if not row:
            return None
        keys = ("line_id", "conversation_id", "turn_id", "block", "ord", "sid", "who", "text", "at")
        return dict(zip(keys, row))

    def counts(self):
        with self.lock:
            conv = self.db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            evs = self.db.execute("SELECT COUNT(*), COALESCE(MAX(id),0) FROM events").fetchone()
            lines = self.db.execute("SELECT COUNT(*) FROM lines").fetchone()[0]
            modes = dict(self.db.execute("SELECT mode, COUNT(*) FROM conversations GROUP BY mode").fetchall())
            verdicts = dict(self.db.execute("SELECT COALESCE(verdict,'unbound'), COUNT(*) FROM conversations "
                                            "WHERE created>? GROUP BY verdict", (time.time() - 86400,)).fetchall())
        size = self.path.stat().st_size if self.path.exists() else 0
        return {"conversations": conv, "events": evs[0], "head": evs[1], "lines": lines,
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
        return len(ids)

    def close(self):
        with self.lock:
            self.db.close()
