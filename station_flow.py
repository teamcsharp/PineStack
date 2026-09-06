"""Persistent, inspectable station events without disk work on the audio loop."""
from __future__ import annotations

import json
import math
import queue
import re
import sqlite3
import threading
import time
import uuid
from collections import deque
from contextlib import closing
from pathlib import Path


NODE_SPEC = [
    ("schedule", "Running order", "calendar", "source", "The scheduled road, caller profile, topic and station contract."),
    ("speakerbox", "Speakerbox", "archive", "source", "Retrieved source material that gives the conversation something to discuss."),
    ("pivots", "Caller pivots", "shuffle", "source", "Random Speakerbox scraps introduce follow-up topics inside a complete call."),
    ("draft", "Dialogue draft", "pen", "write", "The original words, cast, prompt and model response."),
    ("conversation", "Conversation judge", "check", "judge", "Checks speaker exchanges, topic development, continuity and a resolved ending."),
    ("crystal", "DOOM crystal", "gem", "tint", "Random contiguous lyric chunks supply rhetorical and lexical references."),
    ("rewrite", "Rhetorical rewrite", "wand", "tint", "Reworks eligible dialogue before recording, at the requested strength and coverage."),
    ("tint_judge", "Tint judge", "scale", "judge", "Evaluates meaning, rhyme, transformation and prohibited source phrase copying."),
    ("repair", "Repair / retry", "wrench", "feedback", "Failed work returns for correction; unfinished material remains owed."),
    ("tts", "Voice recording", "mic", "audio", "Records the exact approved words with the assigned actor and voice effects."),
    ("pantry", "Prepared shelf", "layers", "audio", "Accepted scripts and matching audio wait in order for their broadcast slot."),
    ("publish", "Audio published", "upload", "playback", "A transport delivery exists; publication alone does not prove playback."),
    ("received", "Received", "download", "playback", "An identified listener has received the audio delivery."),
    ("canplay", "Can play", "volume", "playback", "The browser has buffered enough audio to begin playback."),
    ("playing", "Audible playback", "radio", "playback", "An audible playing acknowledgment and advancing media position confirm speech."),
    ("ended", "Playback ended", "flag", "playback", "The listener reports completion of the audio delivery."),
    ("error", "Delivery failure", "alert", "feedback", "Autoplay, stale queues, transport and device faults are retained with listener details."),
    ("watchdog", "Talk watchdog", "pulse", "feedback", "Measures acknowledged speech gaps and requests prepared cover when the target is missed."),
    ("reflection", "Reflection", "brain", "feedback", "The station reviews outcomes and adapts subsequent writing and preparation."),
    ("repeat", "Repetition judge", "repeat", "judge", "Checks repeated lines and phrases against the acknowledged broadcast history."),
    ("gazette", "Gazette desks", "news", "paper", "Source material, the station and gallery become newspaper stories."),
    ("paper_tint", "Paragraph tint", "gem", "paper", "Each eligible paragraph records attempts, evaluated changes and coverage."),
    ("edition", "Published edition", "book", "paper", "The edition carries per-story tint badges and an honest edition coverage result."),
]
EDGE_SPEC = [
    ("schedule", "speakerbox", "retrieve", False),
    ("speakerbox", "pivots", "random follow-ups", False),
    ("speakerbox", "draft", "subject / evidence", False),
    ("pivots", "draft", "develop caller exchange", False),
    ("draft", "conversation", "check complete arc", False),
    ("conversation", "crystal", "accepted dialogue", False),
    ("conversation", "repair", "failed contract", True),
    ("crystal", "rewrite", "reference chunks", False),
    ("rewrite", "tint_judge", "evaluate each line", False),
    ("tint_judge", "repair", "failed evaluation", True),
    ("repair", "draft", "repair conversation", True),
    ("repair", "rewrite", "repair tint", True),
    ("tint_judge", "tts", "approved wording", False),
    ("tts", "pantry", "matching audio", False),
    ("pantry", "repeat", "select in order", False),
    ("repeat", "publish", "accepted for delivery", False),
    ("repeat", "draft", "needs fresh material", True),
    ("publish", "received", "delivery ID", False),
    ("received", "canplay", "audio buffered", False),
    ("canplay", "playing", "audible progress", False),
    ("playing", "ended", "finished", False),
    ("publish", "playing", "verified box delivery", False),
    ("received", "error", "transport failed", True),
    ("canplay", "error", "playback failed", True),
    ("playing", "error", "interrupted", True),
    ("error", "repair", "delivery retry", True),
    ("playing", "watchdog", "acknowledged speech", True),
    ("watchdog", "pantry", "prepared cover", True),
    ("ended", "reflection", "broadcast outcome", True),
    ("reflection", "schedule", "next choices", True),
    ("reflection", "draft", "writing lessons", True),
    ("speakerbox", "gazette", "sources", False),
    ("reflection", "gazette", "station history", False),
    ("gazette", "paper_tint", "eligible paragraphs", False),
    ("crystal", "paper_tint", "rhetorical references", False),
    ("paper_tint", "edition", "coverage verdict", False),
    ("edition", "speakerbox", "next-hour discussion", True),
]


def clean_detail(value, depth=0):
    """Bound detail size and redact credential fields before it leaves memory."""
    if depth > 7:
        return "[nested detail omitted]"
    if isinstance(value, dict):
        return {str(k)[:100]: ("[redacted]" if re.search(
            r"password|secret|authorization|api[_-]?key|access[_-]?token|^sig$", str(k), re.I)
            else clean_detail(v, depth + 1)) for k, v in list(value.items())[:80]}
    if isinstance(value, (list, tuple, set)):
        return [clean_detail(v, depth + 1) for v in list(value)[:120]]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    text = re.sub(r"([?&](?:t|token|key|sig)=)[^\s&#]+", r"\1[redacted]", text)
    text = re.sub(r"Bearer\s+[^\s]+", "Bearer [redacted]", text, flags=re.I)
    return text[:12000] + ("… [truncated]" if len(text) > 12000 else "")


class FlowJournal:
    def __init__(self, path: Path, keep=5000):
        self.path = Path(path)
        self.session = uuid.uuid4().hex[:12]
        self.lock = threading.RLock()
        self.events = deque(maxlen=keep)
        self.pending = queue.Queue(maxsize=10000)
        self.latest = {}
        self.sequence = 0
        self.worker = None
        self.error = ""
        self.unwritten = 0

    def record(self, node, status, summary, details=None, trace_id="",
               parent_id=None, from_node=""):
        if node not in {row[0] for row in NODE_SPEC}:
            node = "reflection"
        with self.lock:
            self.sequence = max(self.sequence + 1, time.time_ns() // 1000)
            event = {"id": self.sequence, "at": time.time(), "node": node,
                     "status": str(status), "summary": str(summary)[:500],
                     "trace_id": str(trace_id)[:160], "parent_id": parent_id,
                     "from": str(from_node), "session": self.session,
                     "details": clean_detail(details or {})}
            self.events.append(event)
            prior = self.latest.get(node) or {}
            self.latest[node] = {"status": event["status"], "last_at": event["at"],
                                 "count": int(prior.get("count") or 0) + 1,
                                 "details": event["details"], "event_id": event["id"]}
            try:
                self.pending.put_nowait(event)
            except queue.Full:
                self.unwritten += 1
                self.error = "Journal writer backlog is full; recent events remain in memory."
            if not self.worker or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._write, daemon=True,
                                                name="station-flow-journal")
                self.worker.start()
            return event

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(self.path), timeout=10)
        db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        return db

    def _write(self):
        while True:
            event = self.pending.get()
            try:
                with closing(self._connect()) as db:
                    db.execute("INSERT OR IGNORE INTO events VALUES (?, ?)",
                               (event["id"], json.dumps(event, ensure_ascii=False)))
                    db.commit()
                self.error = ""
            except Exception as exc:
                self.unwritten += 1
                self.error = f"Journal persistence failed: {type(exc).__name__}"
            finally:
                self.pending.task_done()

    def read(self, after=0, before=0, limit=300):
        limit = max(1, min(1000, int(limit)))
        after, before = max(0, int(after)), max(0, int(before))
        with self.lock:
            memory = list(self.events)
            latest = dict(self.latest)
        stored = []
        first = memory[0]["id"] if memory else 0
        if self.path.is_file():
            try:
                with closing(self._connect()) as db:
                    first = db.execute("SELECT MIN(id) FROM events").fetchone()[0] or first
                    if before:
                        found = db.execute("SELECT body FROM events WHERE id < ? ORDER BY id DESC LIMIT ?",
                                           (before, limit + 1))
                    elif after:
                        found = db.execute("SELECT body FROM events WHERE id > ? ORDER BY id LIMIT ?",
                                           (after, limit + 1))
                    else:
                        found = db.execute("SELECT body FROM events ORDER BY id DESC LIMIT ?", (limit + 1,))
                    stored = [json.loads(row[0]) for row in found]
            except Exception as exc:
                self.error = f"Journal history unavailable: {type(exc).__name__}"
        merged = {row["id"]: row for row in stored + memory
                  if (not after or row["id"] > after)
                  and (not before or row["id"] < before)}
        rows = sorted(merged.values(), key=lambda row: row["id"])
        truncated = bool(after and not before and len(rows) > limit)
        rows = rows[:limit] if after and not before else rows[-limit:]
        nodes = [{"id": n, "label": label, "icon": icon, "lane": lane,
                  "description": description, **latest.get(n, {
                      "status": "idle", "last_at": 0, "count": 0, "details": {}})}
                 for n, label, icon, lane, description in NODE_SPEC]
        return {"now": time.time(), "session": self.session,
                "cursor": rows[-1]["id"] if rows else after, "oldest": first,
                "truncated": truncated, "history_more": bool(rows and first and first < rows[0]["id"]),
                "events": rows, "nodes": nodes,
                "edges": [{"id": f"{a}:{b}", "from": a, "to": b, "label": label,
                           "feedback": feedback} for a, b, label, feedback in EDGE_SPEC],
                "journal": {"error": self.error, "unwritten": self.unwritten,
                            "pending": self.pending.qsize()}}

    def index_embedding(self, event_id, vector, model):
        """Attach a neural retrieval vector to an already persisted outcome."""
        values = [float(v) for v in vector]
        if not values or not all(math.isfinite(v) for v in values):
            return False
        with closing(self._connect()) as db:
            db.execute("CREATE TABLE IF NOT EXISTS embeddings "
                       "(event_id INTEGER PRIMARY KEY, model TEXT, vector TEXT)")
            db.execute("INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?)",
                       (int(event_id), str(model), json.dumps(values)))
            db.commit()
        return True

    def recall(self, query="", vector=None, model="", limit=10):
        """Retrieve broadcast outcomes with evidence, using cosine or words.

        Only measured hour outcomes enter this memory. Pipeline narration and
        source documents cannot masquerade as a previous broadcast result.
        """
        limit = max(1, min(50, int(limit)))
        with self.lock:
            memory = list(self.events)
        rows, vectors = {}, {}
        if self.path.is_file():
            with closing(self._connect()) as db:
                found = db.execute("SELECT body FROM events WHERE "
                    "json_extract(body, '$.details.broadcast_outcome') = 1 "
                    "ORDER BY id DESC LIMIT 4000")
                rows.update((row["id"], row) for row in
                            (json.loads(one[0]) for one in found))
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE "
                                    "type='table' AND name='embeddings'").fetchone()
                if exists:
                    vectors = {int(eid): json.loads(raw) for eid, raw in db.execute(
                        "SELECT event_id, vector FROM embeddings WHERE model = ?",
                        (str(model),))}
        rows.update((r["id"], r) for r in memory
                    if (r.get("details") or {}).get("broadcast_outcome"))
        tokens = set(re.findall(r"[\w]+", str(query).lower()))
        qnorm = math.sqrt(sum(float(v) ** 2 for v in (vector or [])))
        scored = []
        for row in rows.values():
            terms = set(re.findall(r"[\w]+", json.dumps(row).lower()))
            overlap = len(tokens & terms) / max(1, len(tokens))
            embedding = vectors.get(row["id"]) or []
            mode, score = "lexical", overlap
            if qnorm and len(embedding) == len(vector):
                enorm = math.sqrt(sum(float(v) ** 2 for v in embedding))
                if enorm:
                    score = sum(float(a) * float(b) for a, b in zip(
                        vector, embedding)) / (qnorm * enorm)
                    mode = "neural"
            if not tokens or overlap or (mode == "neural" and score > 0.2):
                scored.append({**row, "relevance": round(score, 5),
                               "indexed": bool(embedding),
                               "retrieval": mode if tokens else "recent"})
        scored.sort(key=lambda r: (r["relevance"], r["id"]), reverse=True)
        return {"query": str(query)[:500], "outcomes": scored[:limit],
                "stored_outcomes": len(rows), "indexed_outcomes": len(vectors),
                "embedding_model": str(model), "journal_error": self.error}
