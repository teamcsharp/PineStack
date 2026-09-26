"""Durable, serial staging for Workshop parody stingers."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


TERMINAL = ("done", "failed", "paused", "cancelled")


class ParodyQueue:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, body TEXT NOT NULL, status TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '', prompt_id TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '', created REAL NOT NULL,
                updated REAL NOT NULL, started REAL, finished REAL
            )""")
            columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(jobs)")}
            if "retry_at" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN retry_at REAL NOT NULL DEFAULT 0")
            if "attempts" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
            # Submission may have reached Comfy before a server crash. Never
            # submit that uncertain request a second time automatically.
            db.execute("UPDATE jobs SET status='paused', reason=? WHERE status='dispatching'",
                       ("Server restarted during submission; check the gallery before retrying",))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def public(row):
        if row is None:
            return None
        item = dict(row)
        body = json.loads(item.pop("body"))
        item["direction"] = str(body.get("prompt") or "")[-180:]
        item["source"] = str(body.get("source") or "")
        item["trim_in_s"] = body.get("trim_in_s")
        item["trim_out_s"] = body.get("trim_out_s")
        item["frames"] = body.get("frames")
        return item

    def add(self, body: dict):
        now = time.time()
        identifier = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO jobs (id,body,status,created,updated) VALUES (?,?,?,?,?)",
                       (identifier, json.dumps(body), "queued", now, now))
        return self.get(identifier)

    def get(self, identifier: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
        return self.public(row)

    def list(self, limit: int = 30):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT ?",
                              (max(1, min(limit, 100)),)).fetchall()
            waiting_ids = [row["id"] for row in db.execute(
                "SELECT id FROM jobs WHERE status='queued' ORDER BY created")]
        jobs = [self.public(row) for row in rows]
        positions = {identifier: index for index, identifier in enumerate(waiting_ids, 1)}
        for job in jobs:
            if job["id"] in positions:
                job["position"] = positions[job["id"]]
        return jobs

    def active(self):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE status IN ('running','dispatching') "
                             "ORDER BY created LIMIT 1").fetchone()
        return self.public(row)

    def next(self):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE status='queued' "
                             "AND COALESCE(retry_at,0)<=? ORDER BY created LIMIT 1",
                             (time.time(),)).fetchone()
        return self.public(row)

    def claim(self, identifier: str):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute("SELECT 1 FROM jobs WHERE status IN ('running','dispatching') "
                                "LIMIT 1").fetchone()
            if active:
                return None
            row = db.execute("SELECT * FROM jobs WHERE id=? AND status='queued' "
                             "AND COALESCE(retry_at,0)<=?",
                             (identifier, time.time())).fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET status='dispatching',updated=? WHERE id=?",
                       (time.time(), identifier))
            return json.loads(row["body"])

    def update(self, identifier: str, status: str, reason: str = "",
               prompt_id: str = "", model: str = ""):
        if status not in ("queued", "dispatching", "running", *TERMINAL):
            raise ValueError("Unknown queue status")
        now = time.time()
        with self.connect() as db:
            db.execute("""UPDATE jobs SET status=?,reason=?,prompt_id=CASE WHEN ?!='' THEN ? ELSE prompt_id END,
                model=CASE WHEN ?!='' THEN ? ELSE model END,updated=?,
                started=CASE WHEN ?='running' THEN ? ELSE started END,
                finished=CASE WHEN ? IN ('done','failed','cancelled') THEN ? ELSE finished END
                WHERE id=?""", (status, reason[:500], prompt_id, prompt_id, model, model,
                                 now, status, now, status, now, identifier))

    def cancel(self, identifier: str):
        """Atomically retire queued work so a worker cannot claim it later."""
        now = time.time()
        with self.connect() as db:
            db.execute("""UPDATE jobs SET status='cancelled', reason=?, updated=?, finished=?
                WHERE id=? AND status NOT IN ('done','cancelled')""",
                       ("Cancelled by operator", now, now, identifier))
        return self.get(identifier)

    def retry(self, identifier: str, reason: str, delay: float = 0):
        """Return retained work to FIFO after an optional bounded delay."""
        now = time.time()
        retry_at = now + max(0.0, min(float(delay or 0), 3600.0))
        with self.connect() as db:
            db.execute("""UPDATE jobs SET status='queued', reason=?, prompt_id='', model='',
                updated=?, started=NULL, finished=NULL, retry_at=?, attempts=attempts+1
                WHERE id=? AND status NOT IN ('done','cancelled')""",
                       (str(reason or "")[:500], now, retry_at, identifier))
        return self.get(identifier)

    def replace_body(self, identifier: str, body: dict):
        """Persist a rebound source without changing the job's FIFO identity."""
        if not isinstance(body, dict):
            raise ValueError("Queue body must be an object")
        with self.connect() as db:
            db.execute("""UPDATE jobs SET body=?, updated=?
                WHERE id=? AND status NOT IN ('done','cancelled')""",
                       (json.dumps(body), time.time(), identifier))
        return self.get(identifier)

    def note(self, identifier: str, reason: str):
        with self.connect() as db:
            db.execute("UPDATE jobs SET reason=?,updated=? WHERE id=? AND status='queued'",
                       (reason[:500], time.time(), identifier))
