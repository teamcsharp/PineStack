"""Cross-draft evidence for System 3, with no disk work on the air path.

Random draws use a frozen, config-scoped snapshot. Evidence is written on a
bounded private lane; a prepared script is never a success. Only matching
committed copy and continuous audible coverage of every required turn earns
one success. Incomplete attribution remains diagnostic evidence only.
"""
from __future__ import annotations

import collections
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import threading
import time

VERSION = 1
FAMILIES = frozenset(("CTS", "ES", "RS", "IRS", "FL"))
NODE_FAILURES = frozenset(("closing", "coherence", "budget"))
OPERATIONS = ("repair", "rewrite", "reroll", "rebuild")
MIN_FAILURES = 3
WEIGHT_FLOOR = 0.25
WEIGHT_CEILING = 1.25
WINDOW = 30 * 86400
MAX_EVIDENCE = 20000
MAX_PLANS = 2000
MAX_SNAPSHOT = 1024


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")).hexdigest()


def copy_digest(text):
    # Chunk joins may change whitespace, but must preserve all spoken words.
    return _hash(" ".join(str(text or "").split()))


def decision_context(conv, ctx):
    """Compute the unchanged context once for an entire candidate wheel."""
    prior = []
    for event in conv.get("decision_events") or []:
        selected = event.get("selected") or {}
        if (event.get("turn_id") == ctx["turn_id"] and event.get("family") in FAMILIES
                and selected.get("id") and not (event.get("meta") or {}).get("prior_revision")):
            prior.append([event["family"], selected.get("table"),
                          selected.get("category"), selected["id"]])
    return [VERSION, conv.get("config_hash"), (conv.get("inputs") or {}).get("road"),
            ctx.get("phase"), bool(ctx.get("closes")), ctx.get("speaker"), prior[-6:]]


def combination(conv, ctx, family, spec, context=None):
    """IDs of this candidate and preceding choices on this turn; no raw copy."""
    if family not in FAMILIES or not ctx.get("turn_id"):
        return None
    prefix = context if context is not None else decision_context(conv, ctx)
    return _hash(prefix + [[family, spec.get("table"), spec.get("category"), spec.get("id")]])


def candidate_feedback(conv, ctx, family, spec, context=None):
    snapshot = (conv.get("inputs") or {}).get("shared_learning") or {}
    if (snapshot.get("version") != VERSION
            or snapshot.get("config_hash") != conv.get("config_hash")):
        return None
    key = combination(conv, ctx, family, spec, context)
    if not key:
        return None
    value = float((snapshot.get("weights") or {}).get(key, 1.0))
    if not math.isfinite(value):
        value = 1.0
    return {"combination": key, "multiplier": max(WEIGHT_FLOOR, min(WEIGHT_CEILING, value)),
            "revision": snapshot.get("revision", 0), "version": VERSION}


def turn_features(conv):
    """One full conditional combination per turn, rather than every node."""
    found = {}
    for event in conv.get("decision_events") or []:
        meta = event.get("meta") or {}
        evidence = meta.get("shared_learning") or {}
        if (event.get("turn_id") and evidence.get("combination") and event.get("rng")
                and not meta.get("prior_revision")
                and meta.get("authority") not in ("operator", "fixed")):
            found[event["turn_id"]] = evidence["combination"]
    return found


def _identity(conv):
    identity = conv.get("identity") or {}
    cid = str(identity.get("conversation_id") or "")
    revision = int(identity.get("revision") or 1)
    digest = str(identity.get("script_digest") or "")
    return cid, revision, _hash([cid, revision, digest])


class SharedDialogueLearning:
    def __init__(self, path, max_pending=256):
        self.path = Path(path)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="system3-learning")
        self.lock = threading.RLock()
        self.capacity = threading.BoundedSemaphore(max_pending)
        self.pending = 0
        self.db = None
        self.ready = False
        self.weights = {}
        self.strategies = {}
        self.revision = 0
        self.last_prune = 0.0
        self.metrics = {"dropped": 0, "errors": 0, "last_error": "",
                        "failures": {}, "audible_successes": 0, "prepared": 0,
                        "adjusted_combinations": 0, "attributed_failures": 0}

    def load(self):
        # Called on the dedicated worker, including during host boot.
        self.db = sqlite3.connect(str(self.path), timeout=2)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=2000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS evidence (
                key TEXT PRIMARY KEY, cid TEXT, config TEXT, road TEXT, feature TEXT,
                kind TEXT, category TEXT, operation TEXT, at REAL);
            CREATE INDEX IF NOT EXISTS evidence_at ON evidence(at);
            CREATE TABLE IF NOT EXISTS plans (
                scope TEXT PRIMARY KEY, cid TEXT, revision INTEGER, data TEXT,
                active INTEGER, won INTEGER DEFAULT 0, at REAL);
            CREATE INDEX IF NOT EXISTS plans_cid ON plans(cid, active);
            CREATE TABLE IF NOT EXISTS lines (
                id TEXT PRIMARY KEY, scope TEXT, turn_id TEXT, valid INTEGER,
                duration REAL DEFAULT 0, ranges TEXT DEFAULT '[]', complete INTEGER DEFAULT 0);
            CREATE INDEX IF NOT EXISTS lines_scope ON lines(scope, turn_id);
        """)
        self._prune()
        self._refresh()
        with self.lock:
            self.ready = True

    def start(self):
        return self._submit(self.load, boot=True)

    def _submit(self, function, *args, boot=False):
        if not boot and not self.ready:
            return False
        if not self.capacity.acquire(blocking=False):
            with self.lock:
                self.metrics["dropped"] += 1
            return False
        with self.lock:
            self.pending += 1

        def job():
            try:
                function(*args)
            except Exception as exc:
                if self.db is not None:
                    self.db.rollback()
                with self.lock:
                    self.metrics["errors"] += 1
                    # Exception class only; database errors may contain user data.
                    self.metrics["last_error"] = type(exc).__name__
            finally:
                with self.lock:
                    self.pending -= 1
                self.capacity.release()
        try:
            self.pool.submit(job)
        except RuntimeError:
            with self.lock:
                self.pending -= 1
                self.metrics["dropped"] += 1
            self.capacity.release()
            return False
        return True

    def snapshot(self, config_hash, road):
        with self.lock:
            weights = dict(self.weights.get((str(config_hash), str(road)), {}))
            revision = self.revision
        return {"version": VERSION, "revision": revision,
                "config_hash": config_hash, "weights": weights}

    def status(self):
        with self.lock:
            return {**copy.deepcopy(self.metrics), "ready": self.ready, "version": VERSION,
                    "revision": self.revision, "pending_writes": self.pending,
                    "window_days": WINDOW // 86400, "minimum_independent_failures": MIN_FAILURES,
                    "weight_floor": WEIGHT_FLOOR, "weight_ceiling": WEIGHT_CEILING,
                    "success_requires": "reviewed, matching committed copy, every required line audibly covered",
                    "node_failure_categories": sorted(NODE_FAILURES),
                    "recovery_strategies": copy.deepcopy(self.strategies)}

    def preferred_operation(self, road, category, cid, serial):
        with self.lock:
            records = copy.deepcopy(self.strategies.get(str(road) + ":" + category, {}))
        if not any(r["failures"] + r["successes"] >= MIN_FAILURES for r in records.values()):
            return None
        # Explore an under-tested operation 20% of the time; otherwise follow
        # observed delivery success. No extra draw enters the planner streams.
        explore = int(_hash([cid, serial, category])[:8], 16) / 0xffffffff < 0.2
        def rank(op):
            r = records.get(op, {"failures": 0, "successes": 0})
            total = r["failures"] + r["successes"]
            return (-total if explore else (r["successes"] + 1) / (total + 2))
        return max(OPERATIONS, key=rank)

    def failure(self, conv, category, failed_turn_ids=(), operation="initial"):
        if conv.get("mode") != "active":
            return False
        cid, revision, scope = _identity(conv)
        if not cid:
            return False
        features = turn_features(conv)
        # Closing has one known target. Other creative errors require an
        # explicit validator turn identity; broad refusal text cannot blame dice.
        ids = set(str(t) for t in failed_turn_ids if t)
        if category == "closing" and conv.get("turns"):
            ids = {str(conv["turns"][-1].get("turn_id") or "")}
        targets = sorted({features[t] for t in ids if t in features}) if category in NODE_FAILURES else []
        payload = {"cid": cid, "scope": scope, "revision": revision,
                   "config": str(conv.get("config_hash") or ""),
                   "road": str((conv.get("inputs") or {}).get("road") or ""),
                   "category": category, "operation": str(operation), "features": targets}
        return self._submit(self._failure, payload)

    def _insert(self, cid, config, road, feature, kind, category, operation):
        key = _hash([cid, config, feature, kind, category, operation])
        cur = self.db.execute("INSERT OR IGNORE INTO evidence VALUES (?,?,?,?,?,?,?,?,?)",
                              (key, cid, config, road, feature, kind, category, operation, time.time()))
        return cur.rowcount > 0

    def _failure(self, p):
        self.db.execute("UPDATE plans SET active=0 WHERE scope=?", (p["scope"],))
        self._insert(p["cid"], p["config"], p["road"], "", "failure", p["category"], p["operation"])
        for key in p["features"]:
            # Operation and failure category must not multiply a conversation's
            # vote against the same combination.
            self._insert(p["cid"], p["config"], p["road"], key, "node_failure", "", "")
        self.db.commit()
        self._prune()
        self._refresh()

    def prepared(self, conv):
        if conv.get("mode") != "active" or not conv.get("turns"):
            return False
        cid, revision, scope = _identity(conv)
        if not cid:
            return False
        turns = conv["turns"]
        roles = (conv.get("inputs") or {}).get("roles") or {}
        if any(not str(t.get("text") or "").strip() for t in turns):
            return False
        variant = conv.get("dialogue_recovery_variant") or {}
        feedback = variant.get("failure_feedback") or {}
        data = {"cid": cid, "scope": scope, "revision": revision,
                "config": str(conv.get("config_hash") or ""),
                "road": str((conv.get("inputs") or {}).get("road") or ""),
                "features": sorted(set(turn_features(conv).values())),
                "turns": {t["turn_id"]: {"digest": copy_digest(t["text"]),
                                         "speaker": str(roles.get(t.get("speaker")) or
                                                        t.get("speaker") or "")} for t in turns},
                "operation": variant.get("operation") or "initial",
                "category": feedback.get("category") or "none"}
        return self._submit(self._prepared, data)

    def _prepared(self, data):
        self.db.execute("UPDATE plans SET active=0 WHERE cid=? AND scope<>?", (data["cid"], data["scope"]))
        # Repeated preparation cannot erase earlier playback coverage or revive
        # a rejected scope. A new script digest/revision creates a fresh scope.
        self.db.execute("INSERT OR IGNORE INTO plans(scope,cid,revision,data,active,at) VALUES (?,?,?,?,1,?)",
                        (data["scope"], data["cid"], data["revision"], json.dumps(data), time.time()))
        self.db.commit()
        self._prune()
        self._refresh()

    def committed(self, rows):
        slim = []
        for row in rows or []:
            s3 = row.get("system3") if isinstance(row.get("system3"), dict) else {}
            if not s3.get("conversation_id"):
                s3 = (row.get("dice") or {}).get("s3") or {}
            if s3.get("conversation_id") and s3.get("turn_id") and row.get("line_id") and not s3.get("gold"):
                slim.append({"id": str(row["line_id"]), "cid": str(s3["conversation_id"]),
                             "turn_id": str(s3["turn_id"]), "revision": s3.get("revision"),
                             "text": str(row.get("text") or ""), "who": str(row.get("who") or "")})
        return self._submit(self._committed, slim) if slim else False

    def _committed(self, rows):
        groups = collections.defaultdict(list)
        for row in rows:
            groups[row["cid"]].append(row)
        for cid, lines in groups.items():
            got = self.db.execute("SELECT scope,revision,data FROM plans WHERE cid=? AND active=1", (cid,)).fetchone()
            if not got:
                continue
            scope, revision, raw = got
            data = json.loads(raw)
            turns = collections.defaultdict(list)
            for line in lines:
                if line["revision"] is not None and int(line["revision"]) != revision:
                    continue
                turns[line["turn_id"]].append(line)
            for tid, chunks in turns.items():
                expected = data["turns"].get(tid)
                if not expected:
                    continue
                valid = (all(x["who"] == expected["speaker"] for x in chunks)
                         and copy_digest(" ".join(x["text"] for x in chunks)) == expected["digest"])
                # Incomplete cross-block chunks remain uncredited: uncertainty
                # cannot create wins. The station normally commits a full round.
                for line in chunks:
                    self.db.execute("INSERT OR IGNORE INTO lines(id,scope,turn_id,valid) VALUES (?,?,?,?)",
                                    (line["id"], scope, tid, int(valid)))
        self.db.commit()

    def playback(self, rows, position, previous, seconds=0):
        if not (math.isfinite(position) and math.isfinite(previous) and position > previous >= 0):
            return False
        intervals = []
        for row in rows or []:
            lid = str(row.get("id") or row.get("line_id") or "")
            if "from" in row and "until" in row:
                start, end = float(row.get("from") or 0), float(row.get("until") or 0)
            elif len(rows) == 1:
                start, end = 0.0, float(seconds or 0)
            else:
                continue
            if (not lid or not math.isfinite(start) or not math.isfinite(end) or end <= start):
                continue
            left, right = max(start, previous), min(end, position)
            if right > left:
                intervals.append((lid, end - start, left - start, right - start))
        return self._submit(self._playback, intervals) if intervals else False

    def _playback(self, intervals):
        scopes = set()
        for lid, duration, start, end in intervals:
            row = self.db.execute("SELECT scope,duration,ranges,complete,valid FROM lines WHERE id=?", (lid,)).fetchone()
            if not row or row[3] or not row[4]:
                continue
            scope, old_duration, raw, _complete, _valid = row
            if old_duration and abs(old_duration - duration) > max(0.05, duration * .01):
                continue
            spans = sorted(json.loads(raw) + [[start, end]])
            merged = []
            for a, b in spans:
                if merged and a <= merged[-1][1] + .005:
                    merged[-1][1] = max(merged[-1][1], b)
                else:
                    merged.append([a, b])
            # Cap pathological fragmented receipts conservatively; never fill gaps.
            merged = sorted(merged, key=lambda x: x[1] - x[0], reverse=True)[:32]
            covered = sum(b - a for a, b in merged)
            complete = covered >= duration * .99 and max(b for a, b in merged) >= duration - .05
            self.db.execute("UPDATE lines SET duration=?,ranges=?,complete=? WHERE id=?",
                            (duration, json.dumps(merged), int(complete), lid))
            scopes.add(scope)
        changed = False
        for scope in scopes:
            row = self.db.execute("SELECT data,won FROM plans WHERE scope=? AND active=1", (scope,)).fetchone()
            if not row or row[1]:
                continue
            data = json.loads(row[0])
            lines = self.db.execute("SELECT turn_id,valid,complete FROM lines WHERE scope=?", (scope,)).fetchall()
            if (not lines or {r[0] for r in lines} != set(data["turns"])
                    or not all(r[1] and r[2] for r in lines)):
                continue
            self.db.execute("UPDATE plans SET won=1 WHERE scope=?", (scope,))
            changed |= self._insert(data["cid"], data["config"], data["road"], "", "success",
                                    data["category"], data["operation"])
            for key in data["features"]:
                self._insert(data["cid"], data["config"], data["road"], key, "node_success", "", "")
        self.db.commit()
        if changed:
            self._refresh()

    def _prune(self):
        now = time.time()
        if now - self.last_prune < 3600:
            return
        self.db.execute("DELETE FROM evidence WHERE at<?", (now - WINDOW,))
        self.db.execute("DELETE FROM evidence WHERE rowid NOT IN (SELECT rowid FROM evidence ORDER BY at DESC LIMIT ?)", (MAX_EVIDENCE,))
        self.db.execute("DELETE FROM plans WHERE at<? OR scope NOT IN (SELECT scope FROM plans ORDER BY at DESC LIMIT ?)",
                        (now - WINDOW, MAX_PLANS))
        self.db.execute("DELETE FROM lines WHERE scope NOT IN (SELECT scope FROM plans)")
        self.db.commit()
        self.last_prune = now

    def _refresh(self):
        weights = collections.defaultdict(dict)
        records = self.db.execute("""SELECT config,road,feature,
            COUNT(DISTINCT CASE WHEN kind='node_failure' THEN cid END),
            COUNT(DISTINCT CASE WHEN kind='node_success' THEN cid END),MAX(at)
            FROM evidence WHERE feature<>'' GROUP BY config,road,feature ORDER BY MAX(at) DESC""").fetchall()
        attributed = 0
        for config, road, key, failures, wins, _at in records:
            attributed += failures
            if failures >= MIN_FAILURES:
                multiplier = max(WEIGHT_FLOOR, min(1.0, (wins + 3) / (failures + 3)))
            elif wins >= MIN_FAILURES and not failures:
                multiplier = min(WEIGHT_CEILING, 1 + .25 * wins / (wins + 3))
            else:
                continue
            bucket = weights[(config, road)]
            if multiplier != 1 and len(bucket) < MAX_SNAPSHOT:
                bucket[key] = round(multiplier, 6)
        strategies = collections.defaultdict(dict)
        for road, category, operation, failures, wins in self.db.execute("""SELECT road,category,operation,
            COUNT(DISTINCT CASE WHEN kind='failure' THEN cid END),
            COUNT(DISTINCT CASE WHEN kind='success' THEN cid END)
            FROM evidence WHERE kind IN ('failure','success') AND operation IN ('repair','rewrite','reroll','rebuild')
            GROUP BY road,category,operation"""):
            strategies[road + ":" + category][operation] = {"failures": failures, "successes": wins}
        failures = dict(self.db.execute("SELECT category,COUNT(*) FROM evidence WHERE kind='failure' GROUP BY category"))
        successes = self.db.execute("SELECT COUNT(DISTINCT cid) FROM evidence WHERE kind='success'").fetchone()[0]
        prepared = self.db.execute("SELECT COUNT(*) FROM plans WHERE active=1 AND won=0").fetchone()[0]
        revision = self.db.execute("SELECT COALESCE(MAX(rowid),0) FROM evidence").fetchone()[0]
        with self.lock:
            self.weights = dict(weights)
            self.strategies = dict(strategies)
            self.revision = revision
            self.metrics.update(failures=failures, audible_successes=successes, prepared=prepared,
                                adjusted_combinations=sum(len(x) for x in weights.values()),
                                attributed_failures=attributed)

    def flush(self):
        """A test/operator barrier; never used by a station audio callback."""
        self.pool.submit(lambda: None).result(timeout=10)

    def close(self):
        if self.db is not None:
            self.pool.submit(self.db.close).result(timeout=10)
        self.pool.shutdown(wait=True)
