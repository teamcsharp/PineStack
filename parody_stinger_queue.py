"""Durable, serial staging for Workshop parody stingers."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


# An H3 request is an owed production, not a best-effort submission.  Jobs
# therefore remain retryable until a completed gallery render proves delivery.
TERMINAL = ("done", "cancelled")


class ParodyQueue:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, body TEXT NOT NULL, status TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '', prompt_id TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '', created REAL NOT NULL,
                updated REAL NOT NULL, started REAL, finished REAL,
                retry_at REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0
            )""")
            columns = {str(row["name"]) for row in
                       db.execute("PRAGMA table_info(jobs)").fetchall()}
            if "retry_at" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN retry_at REAL NOT NULL DEFAULT 0")
            if "attempts" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
            # Earlier versions stranded jobs after a network hiccup or a
            # restart during submission. A running render keeps its prompt id
            # and is inspected before it is retried by the worker.
            now = time.time()
            db.execute("""UPDATE jobs SET status='queued', reason=?, retry_at=?, updated=?
                          WHERE status IN ('dispatching', 'paused', 'failed')""",
                       ("Recovering an unfinished H3 request", now, now))

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
            db.execute("""INSERT INTO jobs
                          (id,body,status,created,updated,retry_at,attempts)
                          VALUES (?,?,?,?,?,?,?)""",
                       (identifier, json.dumps(body), "queued", now, now, now, 0))
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
            row = db.execute("""SELECT * FROM jobs
                              WHERE status='queued' AND retry_at<=?
                              ORDER BY created LIMIT 1""", (time.time(),)).fetchone()
        return self.public(row)

    def claim(self, identifier: str):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute("SELECT 1 FROM jobs WHERE status IN ('running','dispatching') "
                                "LIMIT 1").fetchone()
            if active:
                return None
            row = db.execute("""SELECT * FROM jobs
                              WHERE id=? AND status='queued' AND retry_at<=?""",
                             (identifier, time.time())).fetchone()
            if row is None:
                return None
            db.execute("""UPDATE jobs SET status='dispatching',updated=?,
                          attempts=attempts+1 WHERE id=?""",
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
                finished=CASE WHEN ?='done' THEN ? ELSE finished END
                WHERE id=? AND status!='cancelled'""",
                       (status, reason[:500], prompt_id, prompt_id, model, model,
                        now, status, now, status, now, identifier))

    def note(self, identifier: str, reason: str):
        with self.connect() as db:
            db.execute("UPDATE jobs SET reason=?,updated=? WHERE id=? AND status='queued'",
                       (reason[:500], time.time(), identifier))

    def retry(self, identifier: str, reason: str, delay_s: float = 15.0):
        """Return an unsuccessful attempt to FIFO without losing the request."""
        now = time.time()
        with self.connect() as db:
            db.execute("""UPDATE jobs SET status='queued',reason=?,prompt_id='',model='',
                          updated=?,retry_at=? WHERE id=? AND status!='cancelled'""",
                       (reason[:500], now, now + max(0.0, float(delay_s)), identifier))

    def cancel(self, identifier: str, reason: str = "Cancelled by operator"):
        """Stop a queued or stuck production without allowing a late worker to revive it."""
        now = time.time()
        with self.connect() as db:
            db.execute("""UPDATE jobs SET status='cancelled',reason=?,updated=?,finished=?,
                          retry_at=0 WHERE id=? AND status NOT IN ('done','cancelled')""",
                       (reason[:500], now, now, identifier))
        return self.get(identifier)

    def replace_body(self, identifier: str, body: dict):
        """Persist a late-bound reference clip chosen by the worker."""
        with self.connect() as db:
            db.execute("UPDATE jobs SET body=?,updated=? WHERE id=?",
                       (json.dumps(body), time.time(), identifier))
