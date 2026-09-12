"""Durable, occurrence-scoped diagnostics. This module never grades or plays work."""
from __future__ import annotations

from contextlib import closing, contextmanager
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import threading
import time
import uuid


class LabConflictError(ValueError):
    """A request identity or inspected revision no longer matches."""


class LabLeaseError(LabConflictError):
    """The caller no longer owns this diagnostic operation."""


def _integer(value, name, low=1, high=2**63 - 1):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}")
    return value


def _identity(value, name, maximum=200):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{name} must be a nonempty string of at most {maximum} characters")
    return value


class RejectionLabStore:
    """SQLite receipts for chat, independent prompt traces, and trial proposals.

    Expensive work is performed by the caller, outside all store locks. A
    completed request is replayable; only an explicit expired-lease reclaim
    can acquire a new owner. Ordinary reads and restarts never launch work.
    """

    def __init__(self, path, *, now=None, max_record_bytes=2 * 1024 * 1024):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now or time.time
        self.max_record_bytes = _integer(max_record_bytes, "max_record_bytes", 1024, 16 * 1024 * 1024)
        self._lock = threading.RLock()
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS lab_operations (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                    review_id TEXT NOT NULL, event_seq INTEGER NOT NULL,
                    kind TEXT NOT NULL, request_id TEXT NOT NULL,
                    payload TEXT NOT NULL, request_hash TEXT NOT NULL,
                    status TEXT NOT NULL, lease_token TEXT NOT NULL,
                    lease_until REAL NOT NULL, attempt INTEGER NOT NULL,
                    at REAL NOT NULL, updated_at REAL NOT NULL,
                    result TEXT NOT NULL, error TEXT NOT NULL, completion_hash TEXT NOT NULL,
                    trial_id TEXT,
                    UNIQUE(review_id,event_seq,kind,request_id));
                CREATE TABLE IF NOT EXISTS lab_messages (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                    review_id TEXT NOT NULL, event_seq INTEGER NOT NULL,
                    operation_id TEXT NOT NULL REFERENCES lab_operations(id),
                    at REAL NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS lab_message_scope ON lab_messages(review_id,event_seq,seq);
                CREATE TABLE IF NOT EXISTS lab_trials (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                    review_id TEXT NOT NULL, event_seq INTEGER NOT NULL,
                    operation_id TEXT NOT NULL UNIQUE REFERENCES lab_operations(id),
                    at REAL NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS lab_trial_scope ON lab_trials(review_id,event_seq,seq);
                CREATE TABLE IF NOT EXISTS lab_traces (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT NOT NULL,
                    operation_id TEXT REFERENCES lab_operations(id),
                    at REAL NOT NULL, record TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS lab_trace_order ON lab_traces(trace_id,seq);
                CREATE TABLE IF NOT EXISTS lab_settings (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), body TEXT NOT NULL);
            """)
            if "trial_id" not in {row["name"] for row in db.execute("PRAGMA table_info(lab_operations)")}:
                db.execute("ALTER TABLE lab_operations ADD COLUMN trial_id TEXT")
            db.execute("INSERT OR IGNORE INTO lab_settings VALUES (1,?)", (self._json({
                "revision": 1, "enabled": False, "crystal_instruction": "", "updated_at": self._stamp(),
            }),))

    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def _write(self):
        with self._lock, closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _stamp(self):
        value = float(self._now())
        if not math.isfinite(value):
            raise ValueError("clock must return a finite timestamp")
        return value

    def _json(self, value):
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Lab data must be losslessly JSON compatible") from exc
        if len(encoded.encode("utf-8")) > self.max_record_bytes:
            raise ValueError("Lab record exceeds the byte limit; no text was truncated or stored")
        return encoded

    @staticmethod
    def _hash(encoded):
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _scope(self, review_id, event_seq):
        return _identity(review_id, "review_id"), _integer(event_seq, "event_seq")

    def _messages(self, values):
        if not isinstance(values, (list, tuple)) or len(values) > 100:
            raise ValueError("messages must contain at most 100 records")
        out = []
        for row in values:
            if not isinstance(row, dict) or row.get("role") not in {"user", "assistant", "system", "tool"}:
                raise ValueError("Each message needs a known role")
            if not isinstance(row.get("content"), str):
                raise ValueError("Message content must be a complete string")
            if set(row) & {"seq", "id", "review_id", "event_seq", "operation_id", "at"}:
                raise ValueError("Message fields cannot replace their durable scope")
            out.append(self._json(row))
        return out

    def _insert_messages(self, db, operation, records, stamp):
        for record in records:
            db.execute("INSERT INTO lab_messages(id,review_id,event_seq,operation_id,at,body) VALUES (?,?,?,?,?,?)",
                       (uuid.uuid4().hex, operation["review_id"], operation["event_seq"], operation["id"], stamp, record))

    def _operation(self, row):
        if row is None:
            return None
        item = dict(row)
        for key in ("payload", "result", "error"):
            item[key] = json.loads(item[key])
        for key in ("lease_token", "request_hash", "completion_hash"):
            item.pop(key, None)
        item["lease_expired"] = item["status"] == "pending" and item["lease_until"] <= self._stamp()
        return item

    @staticmethod
    def _content_row(row):
        item = dict(row)
        body = json.loads(item.pop("body"))
        return {**body, **item}

    @staticmethod
    def _trace_row(row):
        item = dict(row)
        item["record"] = json.loads(item["record"])
        return item

    def begin(self, review_id, event_seq, kind, request_id, payload, *, messages=(),
              lease_seconds=300, reclaim_expired=False):
        review_id, event_seq = self._scope(review_id, event_seq)
        kind = _identity(kind, "kind", 80)
        request_id = _identity(request_id, "request_id", 200)
        _integer(lease_seconds, "lease_seconds", 1, 3600)
        if not isinstance(reclaim_expired, bool) or not isinstance(payload, dict):
            raise ValueError("payload must be an object and reclaim_expired a boolean")
        encoded = self._json(payload)
        initial_messages = self._messages(messages)
        request_hash = self._hash(self._json({"payload": payload, "messages": [json.loads(row) for row in initial_messages]}))
        stamp, owner = self._stamp(), uuid.uuid4().hex
        with self._write() as db:
            row = db.execute("SELECT * FROM lab_operations WHERE review_id=? AND event_seq=? AND kind=? AND request_id=?",
                             (review_id, event_seq, kind, request_id)).fetchone()
            if row:
                if row["request_hash"] != request_hash:
                    raise LabConflictError("This request ID already belongs to different diagnostic input")
                claim = row["status"] == "pending" and reclaim_expired and row["lease_until"] <= stamp
                if claim:
                    db.execute("UPDATE lab_operations SET lease_token=?,lease_until=?,attempt=attempt+1,updated_at=? WHERE id=?",
                               (owner, stamp + lease_seconds, stamp, row["id"]))
                    row = db.execute("SELECT * FROM lab_operations WHERE id=?", (row["id"],)).fetchone()
                return {"claimed": claim, "lease_token": owner if claim else None, "operation": self._operation(row)}
            operation_id = uuid.uuid4().hex
            db.execute("""INSERT INTO lab_operations(id,review_id,event_seq,kind,request_id,payload,request_hash,
                status,lease_token,lease_until,attempt,at,updated_at,result,error,completion_hash)
                VALUES (?,?,?,?,?,?,?,'pending',?,?,1,?,?,'null','null','')""",
                (operation_id, review_id, event_seq, kind, request_id, encoded, request_hash,
                 owner, stamp + lease_seconds, stamp, stamp))
            row = db.execute("SELECT * FROM lab_operations WHERE id=?", (operation_id,)).fetchone()
            self._insert_messages(db, row, initial_messages, stamp)
            return {"claimed": True, "lease_token": owner, "operation": self._operation(row)}

    def _owned(self, db, operation_id, lease_token):
        _identity(operation_id, "operation_id")
        _identity(lease_token, "lease_token")
        row = db.execute("SELECT * FROM lab_operations WHERE id=?", (operation_id,)).fetchone()
        if row is None:
            raise KeyError("No such lab operation")
        if row["lease_token"] != lease_token:
            raise LabLeaseError("Another owner holds this diagnostic operation")
        if row["status"] != "pending" or row["lease_until"] <= self._stamp():
            raise LabLeaseError("This diagnostic operation is no longer active")
        return row

    def renew(self, operation_id, lease_token, *, lease_seconds=300):
        _integer(lease_seconds, "lease_seconds", 1, 3600)
        with self._write() as db:
            self._owned(db, operation_id, lease_token)
            stamp = self._stamp()
            db.execute("UPDATE lab_operations SET lease_until=?,updated_at=? WHERE id=?",
                       (stamp + lease_seconds, stamp, operation_id))
            return self._operation(db.execute("SELECT * FROM lab_operations WHERE id=?", (operation_id,)).fetchone())

    def finish(self, operation_id, lease_token, *, result, messages=(), trial=None, traces=()):
        encoded_result = self._json(result)
        final_messages = self._messages(messages)
        if trial is not None:
            if (not isinstance(trial, dict) or not isinstance(trial.get("baseline"), dict)
                    or not trial["baseline"] or not isinstance(trial.get("candidate"), str)
                    or not trial["candidate"].strip() or not isinstance(trial.get("evaluation"), dict)
                    or not isinstance(trial.get("provenance"), dict) or not trial["provenance"]):
                raise ValueError("A trial needs baseline, complete candidate, evaluation and provenance")
            if set(trial) & {"seq", "id", "review_id", "event_seq", "operation_id", "at"}:
                raise ValueError("Trial fields cannot replace their durable scope")
        encoded_trial = self._json(trial) if trial is not None else None
        if not isinstance(traces, (list, tuple)) or len(traces) > 100:
            raise ValueError("traces must contain at most 100 records")
        trace_records = []
        for trace in traces:
            if not isinstance(trace, dict) or not isinstance(trace.get("record"), dict):
                raise ValueError("Each trace needs trace_id and a full record object")
            trace_records.append((_identity(trace.get("trace_id"), "trace_id"), self._json(trace["record"])))
        completion = self._hash(self._json({"result": result, "messages": [json.loads(row) for row in final_messages],
                                           "trial": trial, "traces": list(traces)}))
        with self._write() as db:
            prior = db.execute("SELECT * FROM lab_operations WHERE id=?", (operation_id,)).fetchone()
            if prior and prior["status"] == "completed" and prior["lease_token"] == lease_token:
                if prior["completion_hash"] != completion:
                    raise LabConflictError("A completed diagnostic receipt is immutable")
                return self._operation(prior)
            row = self._owned(db, operation_id, lease_token)
            stamp = self._stamp()
            self._insert_messages(db, row, final_messages, stamp)
            trial_id = None
            if encoded_trial is not None:
                trial_id = uuid.uuid4().hex
                db.execute("INSERT INTO lab_trials(id,review_id,event_seq,operation_id,at,body) VALUES (?,?,?,?,?,?)",
                           (trial_id, row["review_id"], row["event_seq"], operation_id, stamp, encoded_trial))
            for trace_id, record in trace_records:
                db.execute("INSERT INTO lab_traces(trace_id,operation_id,at,record) VALUES (?,?,?,?)",
                           (trace_id, operation_id, stamp, record))
            db.execute("UPDATE lab_operations SET status='completed',updated_at=?,result=?,error='null',completion_hash=?,trial_id=? WHERE id=?",
                       (stamp, encoded_result, completion, trial_id, operation_id))
            return self._operation(db.execute("SELECT * FROM lab_operations WHERE id=?", (operation_id,)).fetchone())

    def fail(self, operation_id, lease_token, error, *, result=None):
        encoded = self._json(error)
        encoded_result = self._json(result)
        with self._write() as db:
            prior = db.execute("SELECT * FROM lab_operations WHERE id=?", (operation_id,)).fetchone()
            if prior and prior["status"] == "failed" and prior["lease_token"] == lease_token:
                if prior["error"] != encoded or prior["result"] != encoded_result:
                    raise LabConflictError("A failed diagnostic receipt is immutable")
                return self._operation(prior)
            self._owned(db, operation_id, lease_token)
            db.execute("UPDATE lab_operations SET status='failed',updated_at=?,error=?,result=? WHERE id=?",
                       (self._stamp(), encoded, encoded_result, operation_id))
            return self._operation(db.execute("SELECT * FROM lab_operations WHERE id=?", (operation_id,)).fetchone())

    def find_request(self, review_id, event_seq, kind, request_id):
        """Read an exact scoped receipt, independently of history pagination."""
        review_id, event_seq = self._scope(review_id, event_seq)
        kind = _identity(kind, "kind", 80)
        request_id = _identity(request_id, "request_id", 200)
        with self._lock, closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM lab_operations WHERE review_id=? AND event_seq=? AND kind=? AND request_id=?",
                (review_id, event_seq, kind, request_id)).fetchone()
            return self._operation(row)

    def get_operation(self, operation_id):
        _identity(operation_id, "operation_id")
        with self._lock, closing(self._connect()) as db:
            return self._operation(db.execute("SELECT * FROM lab_operations WHERE id=?", (operation_id,)).fetchone())

    def get_trial(self, trial_id):
        _identity(trial_id, "trial_id")
        with self._lock, closing(self._connect()) as db:
            row = db.execute("SELECT * FROM lab_trials WHERE id=?", (trial_id,)).fetchone()
            return self._content_row(row) if row else None

    def append_trace(self, trace_id, record):
        _identity(trace_id, "trace_id")
        if not isinstance(record, dict):
            raise ValueError("Trace record must be a full JSON object")
        encoded = self._json(record)
        with self._write() as db:
            seq = db.execute("INSERT INTO lab_traces(trace_id,operation_id,at,record) VALUES (?,NULL,?,?)",
                             (trace_id, self._stamp(), encoded)).lastrowid
            return self._trace_row(db.execute("SELECT * FROM lab_traces WHERE seq=?", (seq,)).fetchone())

    def _page(self, db, table, where, params, before, limit, convert):
        _integer(before, "before", 0)
        _integer(limit, "limit", 1, 200)
        db.execute("BEGIN")  # Counts and page rows share one read snapshot.
        total = db.execute(f"SELECT count(*) FROM {table} WHERE {where}", params).fetchone()[0]
        rows = db.execute(f"SELECT * FROM {table} WHERE {where} AND (?=0 OR seq<?) ORDER BY seq DESC LIMIT ?",
                          [*params, before, before, limit + 1]).fetchall()
        selected = rows[:limit]
        return {"items": [convert(row) for row in reversed(selected)], "total": total,
                "has_more": len(rows) > limit,
                "next_before": selected[-1]["seq"] if len(rows) > limit else None}

    def history(self, review_id, event_seq, kind="messages", *, before=0, limit=50):
        review_id, event_seq = self._scope(review_id, event_seq)
        choices = {"messages": ("lab_messages", self._content_row),
                   "trials": ("lab_trials", self._content_row),
                   "operations": ("lab_operations", self._operation)}
        if kind not in choices:
            raise ValueError("history kind must be messages, trials or operations")
        table, convert = choices[kind]
        with self._lock, closing(self._connect()) as db:
            return self._page(db, table, "review_id=? AND event_seq=?", [review_id, event_seq], before, limit, convert)

    def trace_history(self, trace_id, *, before=0, limit=50):
        _identity(trace_id, "trace_id")
        with self._lock, closing(self._connect()) as db:
            return self._page(db, "lab_traces", "trace_id=?", [trace_id], before, limit, self._trace_row)

    def settings(self):
        with self._lock, closing(self._connect()) as db:
            return json.loads(db.execute("SELECT body FROM lab_settings WHERE singleton=1").fetchone()[0])

    def update_settings(self, expected_revision, crystal_instruction, enabled):
        _integer(expected_revision, "expected_revision")
        if not isinstance(crystal_instruction, str) or len(crystal_instruction) > 4000:
            raise ValueError("crystal_instruction must be a string of at most 4000 characters")
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        with self._write() as db:
            previous = json.loads(db.execute("SELECT body FROM lab_settings WHERE singleton=1").fetchone()[0])
            if previous["revision"] != expected_revision:
                raise LabConflictError("The instruction changed; reload it before applying another edit")
            if previous["enabled"] == enabled and previous["crystal_instruction"] == crystal_instruction:
                return previous
            result = {"revision": expected_revision + 1, "enabled": enabled,
                      "crystal_instruction": crystal_instruction, "updated_at": self._stamp()}
            db.execute("UPDATE lab_settings SET body=? WHERE singleton=1", (self._json(result),))
            return result
