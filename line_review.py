"""Durable editorial decisions; recording and playback remain owned by the app."""
from __future__ import annotations

from contextlib import closing, contextmanager
from contextvars import ContextVar
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid


class ReviewConflictError(ValueError):
    """The operator inspected an older revision of this decision."""


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)
    except (TypeError, ValueError) as exc:
        raise ValueError("Review data must be JSON compatible") from exc


def _gate(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
        raise ValueError("gate must be a nonempty string of at most 200 characters")
    return value.strip()


def _inputs(gate, source, candidate, reasons, context, technical):
    gate = _gate(gate)
    if not isinstance(source, str) or not isinstance(candidate, str):
        raise ValueError("source and candidate must be strings")
    if not isinstance(technical, bool):
        raise ValueError("technical must be a boolean")
    if context is not None and not isinstance(context, dict):
        raise ValueError("context must be an object")
    if isinstance(reasons, str):
        reasons = [reasons]
    if reasons is not None and not isinstance(reasons, (list, tuple)):
        raise ValueError("reasons must be a list of strings")
    unique = []
    for reason in reasons or []:
        if not isinstance(reason, str):
            raise ValueError("each reason must be a string")
        reason = reason.strip()
        if reason and reason not in unique:
            unique.append(reason)
    return gate, source, candidate, unique, context or {}, technical


def _fingerprint(gate, source, candidate, context):
    # The grader normalizes whitespace; preserve case and every content word.
    # Speaker/marker are display metadata. Only the explicit who binds approval.
    scope = [gate, " ".join(source.split()), " ".join(candidate.split()),
             str(context.get("kind") or ""), str(context.get("who") or "")]
    return hashlib.sha256(_json(scope).encode("utf-8")).hexdigest()


def _integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}")
    return value


# #1088: a refusal the machine already handled is a NOTE, not a request for
# the operator. A rewrite refused on one pass and asked again, a draft the
# trimmer shortened, and a technical failure (no audio, an engine down) are
# recorded for the learner and the evidence trail but never sit in the
# operator's queue; only a line that actually left the work (a cut, a hold
# before the recording) is pending. Measured before this: 4,852 pending rows,
# 175 of the latest 200 were rewrite_rejected intermediates.
INFORMATIONAL_DISPOSITIONS = ("rewrite_rejected", "trim", "trimmed")
TRIAGE_VERSION = 1


def _initial_status(disposition, technical):
    if technical or str(disposition or "") in INFORMATIONAL_DISPOSITIONS:
        return "noted"
    return "pending"


class LineReviewStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._instance_scope = ContextVar('review_instance_scope', default=())
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS review_policy (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS line_reviews (
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                    gate TEXT NOT NULL, source TEXT NOT NULL, candidate TEXT NOT NULL,
                    reasons TEXT NOT NULL, context TEXT NOT NULL, evaluation TEXT NOT NULL,
                    technical INTEGER NOT NULL, disposition TEXT NOT NULL,
                    review_status TEXT NOT NULL, revision INTEGER NOT NULL,
                    occurrences INTEGER NOT NULL, first_at REAL NOT NULL, last_at REAL NOT NULL,
                    latest_seq INTEGER NOT NULL, decision TEXT NOT NULL, effect TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS reviews_cursor ON line_reviews(latest_seq DESC);
                CREATE INDEX IF NOT EXISTS reviews_status ON line_reviews(review_status, latest_seq DESC);
                CREATE INDEX IF NOT EXISTS reviews_gate ON line_reviews(gate, review_status, latest_seq DESC);
                CREATE INDEX IF NOT EXISTS reviews_triage ON line_reviews(review_status, technical, disposition, latest_seq DESC);
                CREATE TABLE IF NOT EXISTS review_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, review_id TEXT NOT NULL,
                    at REAL NOT NULL, body TEXT NOT NULL,
                    FOREIGN KEY(review_id) REFERENCES line_reviews(id));
                CREATE INDEX IF NOT EXISTS review_occurrences ON review_events(review_id,seq DESC);
                CREATE TABLE IF NOT EXISTS review_decisions (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, review_id TEXT NOT NULL,
                    at REAL NOT NULL, body TEXT NOT NULL,
                    FOREIGN KEY(review_id) REFERENCES line_reviews(id));
                CREATE TABLE IF NOT EXISTS review_batches (
                    request_id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS review_instances (
                    id TEXT PRIMARY KEY, review_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS review_replacements (
                    request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, body TEXT NOT NULL);
            """)
            default = {"enabled": True, "max_faults": 0, "disabled_gates": [],
                       "revision": 1, "version": 1, "updated_at": time.time()}
            db.execute("INSERT OR IGNORE INTO review_policy VALUES (1,?)", (_json(default),))
            self._policy = json.loads(db.execute("SELECT body FROM review_policy WHERE singleton=1").fetchone()[0])
            # #1088: once, the backlog of machine-handled refusals leaves the
            # operator's queue (the triage index above makes this a scan of
            # the pending rows only).
            if int(self._policy.get("triage_version") or 0) < TRIAGE_VERSION:
                placeholders = ",".join("?" for _ in INFORMATIONAL_DISPOSITIONS)
                db.execute("UPDATE line_reviews SET review_status='noted' WHERE review_status='pending' "
                           "AND (technical=1 OR disposition IN (" + placeholders + "))",
                           tuple(INFORMATIONAL_DISPOSITIONS))
                self._policy["triage_version"] = TRIAGE_VERSION
                db.execute("UPDATE review_policy SET body=? WHERE singleton=1", (_json(self._policy),))
                db.commit()
            self._approved = {row['fingerprint'] for row in db.execute(
                "SELECT fingerprint,decision FROM line_reviews WHERE review_status='allowed' AND technical=0")
                if json.loads(row['decision']).get('scope') != 'instance'}
            self._instances = {row['id']: json.loads(row['body']) for row in
                               db.execute('SELECT id,body FROM review_instances')}
        self._occurrence_cache = {}
        self._reference_cache = {}
        self._refresh_preferences()

    def _refresh_preferences(self):
        """Small, literal examples; no inferred rule or acceptance-policy edit."""
        with closing(self._connect()) as db:
            rows = db.execute("""SELECT * FROM line_reviews WHERE technical=0
                AND review_status IN ('allowed','kept')
                AND COALESCE(json_extract(decision,'$.scope'),'') != 'instance'
                ORDER BY json_extract(decision,'$.at') DESC LIMIT 24""").fetchall()
        self._preferences = []
        for raw in rows:
            row = self._row(raw)
            decision = row['decision']
            if decision.get('action') not in ('allow', 'keep'):
                continue
            self._preferences.append({
                'review_id': row['id'], 'gate': row['gate'],
                'kind': str(row['context'].get('kind') or ''),
                'action': decision['action'], 'at': decision.get('at'),
                'source': row['source'][:320], 'candidate': row['candidate'][:320],
                'excerpted': len(row['source']) > 320 or len(row['candidate']) > 320,
                'reasons': [reason[:160] for reason in row['reasons'][:4]],
                'note': str(decision.get('note') or '')[:320]})

    def preference_examples(self, kind='', gate='', limit=3):
        _integer(limit, 'limit', 1, 6)
        with self._lock:
            examples = [row for row in self._preferences
                        if (not kind or row['kind'] == kind) and (not gate or row['gate'] == gate)]
            return copy.deepcopy(examples[:limit])

    def find_occurrence(self, gate, source, candidate, context):
        """Backfill only a unique exact parent/turn, never a nearby text match."""
        fingerprint = _fingerprint(gate, source, candidate, context)
        parent = ' '.join(str(context.get('script_plain') or context.get('script') or '').split())
        if not parent or not context.get('turn') or not context.get('marker'):
            return None
        identity = {key: context.get('entry', {}).get(key) for key in
                    ('sid', 'at', 'caller_voice', 'caller_name', 'caller2_voice', 'caller2_name')
                    if context.get('entry', {}).get(key) not in (None, '')}
        cache_key = _json([fingerprint, parent, context['turn'], context['marker'], identity])
        with self._lock:
            if cache_key in self._occurrence_cache:
                return copy.deepcopy(self._occurrence_cache[cache_key])
            with closing(self._connect()) as db:
                rows = db.execute("""SELECT e.seq,e.review_id,e.body FROM review_events e
                    JOIN line_reviews r ON r.id=e.review_id WHERE r.fingerprint=?""", (fingerprint,)).fetchall()
            found = []
            for row in rows:
                evidence = json.loads(row['body']); prior = evidence.get('context') or {}
                if (' '.join(str(prior.get('script_plain') or prior.get('script') or '').split()) != parent
                        or prior.get('turn') != context['turn'] or prior.get('marker') != context['marker']
                        or any((prior.get('entry') or {}).get(key) != value for key, value in identity.items())):
                    continue
                if evidence.get('disposition') == 'cut':
                    found.append({'review_id': row['review_id'], 'review_seq': row['seq']})
            result = found[0] if len(found) == 1 else None
            if len(self._occurrence_cache) >= 2048:
                self._occurrence_cache.clear()
            self._occurrence_cache[cache_key] = result
            return copy.deepcopy(result)

    def occurrence_reference(self, review_id, event_seq):
        """Small cached LCD metadata; full evidence is fetched only on tap."""
        key = (str(review_id), event_seq)
        with self._lock:
            if key not in self._reference_cache:
                row = self.get(review_id, event_seq=event_seq)
                value = ({name: row[name] for name in
                          ('id', 'event_seq', 'gate', 'reasons', 'technical', 'occurrence_current')}
                         if row else None)
                if len(self._reference_cache) >= 2048:
                    self._reference_cache.clear()
                self._reference_cache[key] = value
            return copy.deepcopy(self._reference_cache[key])

    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def _write(self):
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def policy(self, patch=None):
        if patch is None:
            # #1070: the read is on the readiness hot path (every
            # crystal_tint_holds call) and must not queue behind a queue
            # page or an evidence read that a worker thread is holding the
            # store lock for; the policy dict is replaced whole on write,
            # so a copy of the current object is a consistent read.
            return copy.deepcopy(self._policy)
        with self._lock:
            if not isinstance(patch, dict):
                raise ValueError("policy patch must be an object")
            if set(patch) - {"enabled", "max_faults", "disabled_gates", "expected_revision"}:
                raise ValueError("unknown policy field")
            with self._write() as db:
                current = json.loads(db.execute("SELECT body FROM review_policy WHERE singleton=1").fetchone()[0])
                expected = patch.get("expected_revision")
                if expected is not None:
                    _integer(expected, "expected_revision", 1, 2**63-1)
                    if expected != current["revision"]:
                        raise ReviewConflictError("Acceptance policy changed; reload it before editing")
                new = copy.deepcopy(current)
                if "enabled" in patch:
                    if not isinstance(patch["enabled"], bool):
                        raise ValueError("enabled must be a boolean")
                    new["enabled"] = patch["enabled"]
                if "max_faults" in patch:
                    new["max_faults"] = _integer(patch["max_faults"], "max_faults", 0, 10)
                if "disabled_gates" in patch:
                    if not isinstance(patch["disabled_gates"], list):
                        raise ValueError("disabled_gates must be a list")
                    new["disabled_gates"] = sorted({_gate(gate) for gate in patch["disabled_gates"]})
                if any(new[key] != current[key] for key in ("enabled", "max_faults", "disabled_gates")):
                    new.update(revision=current["revision"] + 1, updated_at=time.time())
                    db.execute("UPDATE review_policy SET body=? WHERE singleton=1", (_json(new),))
            self._policy = new
            return copy.deepcopy(new)

    def evaluate(self, gate, source, candidate, reasons, context=None, technical=False):
        gate, source, candidate, reasons, context, technical = _inputs(
            gate, source, candidate, reasons, context, technical)
        fingerprint = _fingerprint(gate, source, candidate, context)
        # No database operation on the writing/recording hot path.
        with self._lock:
            policy = self._policy
            instance = any(self._instances.get(key, {}).get('fingerprint') == fingerprint
                           and self._instances[key].get('review_status') == 'allowed'
                           and not self._instances[key].get('technical')
                           for key in self._instance_scope.get())
            approved = (fingerprint in self._approved or instance) and not technical
            if technical:
                allowed, reason = False, "technical"
            elif approved:
                allowed, reason = True, "instance_approved" if instance else "operator_approved"
            elif not policy["enabled"]:
                allowed, reason = True, "rejections_disabled"
            elif gate in policy["disabled_gates"]:
                allowed, reason = True, "gate_disabled"
            elif len(reasons) <= policy["max_faults"]:
                allowed, reason = True, "no_flags" if not reasons else "within_fault_tolerance"
            else:
                allowed, reason = False, "editorial_rejection"
            return {"allowed": allowed, "reason": reason, "gate": gate,
                    "policy_revision": policy["revision"], "operator_approved": approved,
                    "technical": technical, "reasons": reasons, "fault_count": len(reasons),
                    "max_faults": policy["max_faults"], "machine_rejected": technical or bool(reasons)}

    @contextmanager
    def instance_scope(self, review_ids):
        """An exact grant follows only the stored entry being recovered."""
        ids = tuple(dict.fromkeys((*self._instance_scope.get(), *review_ids)))
        token = self._instance_scope.set(ids)
        try:
            yield
        finally:
            self._instance_scope.reset(token)

    def scoped_instances(self):
        with self._lock:
            return tuple(key for key in self._instance_scope.get()
                         if self._instances.get(key, {}).get('review_status') == 'allowed')

    def pending_instances(self):
        with self._lock:
            return [copy.deepcopy(row) for row in self._instances.values()
                    if row.get('review_status') == 'allowed' and
                    row.get('effect', {}).get('status') not in ('recorded', 'completed', 'kept', 'held')]

    def instances_for(self, review_id):
        with self._lock:
            return [copy.deepcopy(row) for row in self._instances.values()
                    if row.get('original_review_id') == review_id]

    def approve_current(self, request_id):
        """Atomically approve this pending snapshot once, with retry identity."""
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 128 or not request_id.isascii():
            raise ValueError('request_id must be an ASCII string of 8 to 128 characters')
        with self._lock:
            return self._approve_current_locked(request_id)

    def approve_replacement(self, review_id, event_seq, expected_revision,
                            request_id, trial_id, candidate, evaluation):
        with self._lock:
            return self._approve_replacement_locked(review_id, event_seq, expected_revision,
                request_id, trial_id, candidate, evaluation)

    def _approve_replacement_locked(self, review_id, event_seq, expected_revision,
                                    request_id, trial_id, candidate, evaluation):
        """Grant only the tested wording for one retained occurrence.

        The app validates the trial against the current settings. This store
        provides atomic identity, evidence and retry semantics; it never asks
        a model, records a voice or invents a rejected-line event.
        """
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 128 or not request_id.isascii():
            raise ValueError('request_id must be an ASCII string of 8 to 128 characters')
        if not isinstance(trial_id, str) or not trial_id.strip() or len(trial_id) > 200:
            raise ValueError('trial_id must identify the tested candidate')
        if not isinstance(review_id, str) or not review_id or len(review_id) > 200:
            raise ValueError('review_id must identify a retained rejection')
        _integer(event_seq, 'event_seq', 1, 2**63-1)
        _integer(expected_revision, 'expected_revision', 1, 2**63-1)
        if not isinstance(candidate, str) or not candidate.strip() or not any(ch.isalnum() for ch in candidate):
            raise ValueError('candidate must contain tested wording')
        if not isinstance(evaluation, dict) or evaluation.get('ok') is not True or evaluation.get('technical'):
            raise ValueError('an accepted nontechnical trial evaluation is required')
        payload = {'review_id': review_id, 'event_seq': event_seq, 'expected_revision': expected_revision,
                   'trial_id': trial_id, 'candidate': candidate, 'evaluation': evaluation}
        payload = json.loads(_json(payload))
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                           separators=(',', ':')).encode('utf-8')).hexdigest()
        with self._lock, self._write() as db:
            prior = db.execute('SELECT payload_hash,body FROM review_replacements WHERE request_id=?',
                               (request_id,)).fetchone()
            if prior:
                if prior['payload_hash'] != digest:
                    raise ReviewConflictError('This replacement request ID already belongs to different tested wording')
                result = json.loads(prior['body'])
                result['changed'] = False
                return result
            row = self._row(db.execute('SELECT * FROM line_reviews WHERE id=?', (review_id,)).fetchone())
            if row is None:
                raise KeyError('No such line review')
            if row['latest_seq'] != event_seq or row['revision'] != expected_revision:
                raise ReviewConflictError('The rejected occurrence changed; reload and test its current evidence')
            if (row['review_status'] not in ('pending', 'kept') or any(
                    grant.get('original_review_id') == review_id and grant.get('review_status') == 'allowed'
                    for grant in self._instances.values())):
                raise ReviewConflictError('This line already has approved/recovering work; review/withdraw that decision before applying a different rewrite.')
            if row['technical'] or not row['source'].strip():
                raise ValueError('A technical rejection or missing original cannot receive a wording replacement')
            stamp = time.time()
            instance_id = 'once-' + uuid.uuid4().hex
            decision = {'action': 'allow', 'scope': 'instance', 'mode': 'replacement',
                        'instance_id': instance_id, 'request_id': request_id,
                        'trial_id': trial_id, 'event_seq': event_seq, 'at': stamp, 'by': 'operator',
                        'note': 'Apply this tested replacement wording to this occurrence only.'}
            effect = {'action': 'allow', 'status': 'awaiting_recovery',
                      'say': 'Tested replacement accepted for this occurrence only; writing and recording recovery is pending.'}
            instance = {**copy.deepcopy(row), 'id': instance_id, 'original_review_id': review_id,
                        'candidate': candidate, 'evaluation': payload['evaluation'],
                        'fingerprint': _fingerprint(row['gate'], row['source'], candidate, row['context']),
                        'review_status': 'allowed', 'revision': row['revision'] + 1,
                        'decision': decision, 'effect': effect}
            db.execute('INSERT INTO review_instances VALUES (?,?,?)', (instance_id, review_id, _json(instance)))
            db.execute("UPDATE line_reviews SET review_status='allowed',revision=revision+1,decision=?,effect=? WHERE id=?",
                       (_json(decision), _json(effect), review_id))
            db.execute('INSERT INTO review_decisions(review_id,at,body) VALUES (?,?,?)',
                       (review_id, stamp, _json(decision)))
            updated = self._row(db.execute('SELECT * FROM line_reviews WHERE id=?', (review_id,)).fetchone())
            result = {'row': updated, 'instance': instance, 'instance_id': instance_id, 'changed': True}
            db.execute('INSERT INTO review_replacements VALUES (?,?,?)', (request_id, digest, _json(result)))
        # Commit before publishing hot-path permissions.
        with self._lock:
            self._instances[instance_id] = copy.deepcopy(instance)
            self._approved.discard(row['fingerprint'])
            self._refresh_preferences()
        return copy.deepcopy(result)

    def _approve_current_locked(self, request_id):
        with self._lock, self._write() as db:
            prior = db.execute('SELECT body FROM review_batches WHERE request_id=?', (request_id,)).fetchone()
            if prior:
                return json.loads(prior[0])
            rows = db.execute("SELECT * FROM line_reviews WHERE review_status='pending' ORDER BY latest_seq").fetchall()
            head = db.execute('SELECT COALESCE(max(seq),0) FROM review_events').fetchone()[0]
            result = {'ok': True, 'batch_id': request_id, 'through_cursor': head,
                      'snapshot_count': len(rows), 'approved': 0, 'queued': 0,
                      'awaiting_recovery': 0, 'needs_context': 0, 'skipped': 0,
                      'skip_reasons': {}, 'items': []}
            made = {}
            for raw in rows:
                row = self._row(raw)
                reason = ('technical' if row['technical'] else
                          'missing_text' if not (row['source'].strip() or row['candidate'].strip()) else '')
                if reason:
                    result['skipped'] += 1
                    result['skip_reasons'][reason] = result['skip_reasons'].get(reason, 0) + 1
                    result['items'].append({'id': row['id'], 'status': 'skipped', 'reason': reason})
                    continue
                grant_id = 'once-' + uuid.uuid4().hex
                decision = {'action': 'allow', 'scope': 'instance', 'instance_id': grant_id,
                            'batch_id': request_id, 'event_seq': row['latest_seq'],
                            'note': 'Approved once with the current waiting batch.',
                            'at': time.time(), 'by': 'operator'}
                effect = {'action': 'allow', 'status': 'awaiting_recovery',
                          'say': 'Approved for this occurrence only; waiting for writing and recording recovery.'}
                snapshot = {**copy.deepcopy(row), 'id': grant_id, 'original_review_id': row['id'],
                            'review_status': 'allowed', 'revision': row['revision'] + 1,
                            'decision': decision, 'effect': effect}
                db.execute('INSERT INTO review_instances VALUES (?,?,?)', (grant_id, row['id'], _json(snapshot)))
                db.execute("UPDATE line_reviews SET review_status='allowed',revision=revision+1,decision=?,effect=? WHERE id=?",
                           (_json(decision), _json(effect), row['id']))
                db.execute('INSERT INTO review_decisions(review_id,at,body) VALUES (?,?,?)',
                           (row['id'], decision['at'], _json(decision)))
                made[grant_id] = snapshot
                result['approved'] += 1
                result['awaiting_recovery'] += 1
                result['items'].append({'id': row['id'], 'instance_id': grant_id, 'status': 'approved_once'})
            result['remaining_pending'] = db.execute("SELECT count(*) FROM line_reviews WHERE review_status='pending'").fetchone()[0]
            result['policy'] = copy.deepcopy(self._policy)
            db.execute('INSERT INTO review_batches VALUES (?,?)', (request_id, _json(result)))
        # Publish hot-path grants only after the durable transaction commits.
        with self._lock:
            self._instances.update(made)
        return result

    @staticmethod
    def _row(row):
        if row is None:
            return None
        item = dict(row)
        for key in ("reasons", "context", "evaluation", "decision", "effect"):
            item[key] = json.loads(item[key])
        item["technical"] = bool(item["technical"])
        item.update(version=1, seq=item["latest_seq"], event_seq=item["latest_seq"], at=item["last_at"])
        return item

    @staticmethod
    def _summary(row):
        item = LineReviewStore._row(row)
        context = item["context"]
        return {key: item[key] for key in (
            "id", "gate", "seq", "event_seq", "at", "first_at", "last_at", "revision",
            "occurrences", "technical", "disposition", "review_status", "effect")} | {
                "kind": str(context.get("kind") or ""),
                "who": str(context.get("who") or context.get("speaker") or context.get("marker") or ""),
                "source_preview": item["source"][:220], "candidate_preview": item["candidate"][:260],
                "reasons": item["reasons"][:8], "fault_count": len(item["reasons"]),
                "has_more_reasons": len(item["reasons"]) > 8,
                "instance_id": item['decision'].get('instance_id')}

    # #1070: a queue page used to SELECT * - every row carries its complete
    # context and evaluation documents (the whole parent script among them),
    # tens of kilobytes each, and the panel and the LCD poll the page. The
    # summary needs a preview and a handful of fields, so the page reads only
    # those and lets SQLite pick the context fields out of the JSON itself.
    SUMMARY_COLUMNS = ("id,gate,latest_seq,first_at,last_at,revision,occurrences,technical,"
                       "disposition,review_status,effect,reasons,decision,"
                       "substr(source,1,220) AS source,substr(candidate,1,260) AS candidate,"
                       "json_extract(context,'$.kind','$.who','$.speaker','$.marker') AS context_fields")
    SUMMARY_COLUMNS_R = ("r.id AS id,r.gate AS gate,r.latest_seq AS latest_seq,r.first_at AS first_at,"
                         "r.last_at AS last_at,r.revision AS revision,r.occurrences AS occurrences,"
                         "r.technical AS technical,r.disposition AS disposition,"
                         "r.review_status AS review_status,r.effect AS effect,r.reasons AS reasons,"
                         "r.decision AS decision,substr(r.source,1,220) AS source,"
                         "substr(r.candidate,1,260) AS candidate,"
                         "json_extract(r.context,'$.kind','$.who','$.speaker','$.marker') AS context_fields")

    @staticmethod
    def _summary_slim(row):
        """The same summary as _summary, from the slim page columns."""
        fields = json.loads(row["context_fields"]) if row["context_fields"] else [None] * 4
        kind, who, speaker, marker = (list(fields) + [None] * 4)[:4]
        reasons = json.loads(row["reasons"])
        decision = json.loads(row["decision"])
        return {"id": row["id"], "gate": row["gate"], "seq": row["latest_seq"], "event_seq": row["latest_seq"],
                "at": row["last_at"], "first_at": row["first_at"], "last_at": row["last_at"],
                "revision": row["revision"], "occurrences": row["occurrences"],
                "technical": bool(row["technical"]), "disposition": row["disposition"],
                "review_status": row["review_status"], "effect": json.loads(row["effect"]),
                "kind": str(kind or ""), "who": str(who or speaker or marker or ""),
                "source_preview": str(row["source"] or "")[:220],
                "candidate_preview": str(row["candidate"] or "")[:260],
                "reasons": reasons[:8], "fault_count": len(reasons), "has_more_reasons": len(reasons) > 8,
                "instance_id": decision.get("instance_id")}

    def record(self, gate, source, candidate='', reasons=None, context=None,
               evaluation=None, technical=False, disposition='cut'):
        gate, source, candidate, reasons, context, technical = _inputs(
            gate, source, candidate, reasons, context, technical)
        if evaluation is not None and not isinstance(evaluation, dict):
            raise ValueError("evaluation must be an object")
        if not isinstance(disposition, str) or not disposition.strip():
            raise ValueError("disposition must be a nonempty string")
        fingerprint = _fingerprint(gate, source, candidate, context)
        stamp = time.time()
        evidence = {"gate": gate, "source": source, "candidate": candidate, "reasons": reasons,
                    "context": context, "evaluation": evaluation or {}, "technical": technical,
                    "disposition": disposition, "at": stamp}
        body = _json(evidence)  # Snapshot full evidence before entering the transaction.
        snapshot = json.loads(body)
        with self._lock:
            with self._write() as db:
                old = db.execute("SELECT * FROM line_reviews WHERE fingerprint=?", (fingerprint,)).fetchone()
                if old is None:
                    review_id = uuid.uuid4().hex
                    db.execute("INSERT INTO line_reviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                        review_id, fingerprint, gate, source, candidate, _json(reasons), _json(snapshot["context"]),
                        _json(snapshot["evaluation"]), int(technical), disposition,
                        _initial_status(disposition, technical), 1, 1,
                        stamp, stamp, 0, "{}", "{}"))
                else:
                    review_id = old["id"]
                    technical = technical or bool(old["technical"])
                    once = json.loads(old['decision']).get('scope') == 'instance'
                    status = "pending" if once or (technical and old["review_status"] == "allowed") else old["review_status"]
                    # #1088: a note becomes a request only when the line actually leaves the work.
                    if old["review_status"] == "noted" and _initial_status(disposition, technical) == "pending":
                        status = "pending"
                    if once:
                        db.execute("UPDATE line_reviews SET decision='{}',effect='{}' WHERE id=?", (review_id,))
                    db.execute("""UPDATE line_reviews SET source=?,candidate=?,reasons=?,context=?,evaluation=?,
                        technical=?,disposition=?,review_status=?,revision=revision+1,occurrences=occurrences+1,last_at=? WHERE id=?""", (
                        source, candidate, _json(reasons), _json(snapshot["context"]), _json(snapshot["evaluation"]),
                        int(technical), disposition, status, stamp, review_id))
                seq = db.execute("INSERT INTO review_events(review_id,at,body) VALUES (?,?,?)",
                                 (review_id, stamp, body)).lastrowid
                db.execute("UPDATE line_reviews SET latest_seq=? WHERE id=?", (seq, review_id))
                item = self._row(db.execute("SELECT * FROM line_reviews WHERE id=?", (review_id,)).fetchone())
            if item["technical"]:
                self._approved.discard(fingerprint)
                self._preferences = [row for row in self._preferences if row['review_id'] != item['id']]
            self._occurrence_cache = {key: value for key, value in self._occurrence_cache.items()
                                      if fingerprint not in key}
            self._reference_cache = {key: value for key, value in self._reference_cache.items()
                                     if key[0] != item['id']}
            return item

    def get(self, review_id, *, before=0, limit=100, event_seq=0):
        _integer(before, "before", 0, 2**63-1)
        _integer(limit, "limit", 1, 200)
        _integer(event_seq, "event_seq", 0, 2**63-1)
        with self._lock, closing(self._connect()) as db:
            if str(review_id) in self._instances:
                return copy.deepcopy(self._instances[str(review_id)])
            item = self._row(db.execute("SELECT * FROM line_reviews WHERE id=?", (str(review_id),)).fetchone())
            if item is None:
                return None
            if event_seq:
                event = db.execute('SELECT body FROM review_events WHERE review_id=? AND seq=?',
                                   (item['id'], event_seq)).fetchone()
                if event is None:
                    return None
                item.update(json.loads(event['body']))
                item.update(event_seq=event_seq, seq=event_seq,
                            occurrence_current=event_seq == item['latest_seq'])
                # LCD evidence reads need one complete occurrence, not another
                # hundred complete parent scripts in the history payload.
                item['history'] = []
                item['history_has_more'] = bool(item['occurrences'] > 1)
                return item
            events = db.execute("SELECT * FROM review_events WHERE review_id=? AND (?=0 OR seq<?) ORDER BY seq DESC LIMIT ?",
                                (item["id"], before, before, limit + 1)).fetchall()
            item["history"] = [{"seq": row["seq"], **json.loads(row["body"])} for row in events[:limit]]
            item["history_has_more"] = len(events) > limit
            item["history_next_before"] = events[limit-1]["seq"] if len(events) > limit else None
            item["decisions"] = [json.loads(row[0]) for row in db.execute(
                "SELECT body FROM review_decisions WHERE review_id=? ORDER BY seq DESC LIMIT 100", (item["id"],))]
            return item

    def summaries(self, after=0, before=0, limit=50, status='pending', gate=''):
        _integer(after, "after", 0, 2**63-1); _integer(before, "before", 0, 2**63-1)
        _integer(limit, "limit", 1, 200)
        if status not in ("", "all", "pending", "allowed", "kept", "noted"):
            raise ValueError("status must be pending, allowed, kept, noted, or all")
        if gate:
            gate = _gate(gate)
        clauses, params = [], []
        if status not in ("", "all"):
            clauses.append("review_status=?"); params.append(status)
        if gate:
            clauses.append("gate=?"); params.append(gate)
        base = " AND ".join(clauses) or "1=1"
        with self._lock, closing(self._connect()) as db:
            total = db.execute("SELECT count(*) FROM line_reviews WHERE " + base, params).fetchone()[0]
            unreviewed = db.execute("SELECT count(*) FROM line_reviews WHERE review_status='pending'").fetchone()[0]
            # #1088: what the operator's attention is actually owed - pending
            # cuts that are not technical - beside the machine's own notes.
            attention = db.execute("SELECT count(*) FROM line_reviews WHERE review_status='pending' AND technical=0").fetchone()[0]
            noted = db.execute("SELECT count(*) FROM line_reviews WHERE review_status='noted'").fetchone()[0]
            rows = db.execute("SELECT " + self.SUMMARY_COLUMNS + " FROM line_reviews WHERE " + base +
                " AND latest_seq>? AND (?=0 OR latest_seq<?) ORDER BY latest_seq DESC LIMIT ?",
                params + [after, before, before, limit + 1]).fetchall()
            latest = db.execute("SELECT COALESCE(max(seq),0) FROM review_events").fetchone()[0]
            events = []
            # Zero is a valid cursor for a client that connected before the
            # first cut. Bootstrap suppression belongs to the UI, not the feed.
            # #1070: the occurrence body is the complete evidence document;
            # only its previews and a few fields are needed here.
            # #1088: the feed follows the status asked for, so a client
            # watching the pending queue is not woken by the machine's notes.
            status_filter = "" if status in ("", "all") else status
            event_rows = db.execute("SELECT e.seq AS occurrence_seq,e.at AS occurrence_at,"
                "json_extract(e.body,'$.source','$.candidate','$.reasons','$.disposition','$.technical',"
                "'$.context.kind','$.context.who','$.context.speaker','$.context.marker') AS occurrence_fields,"
                + self.SUMMARY_COLUMNS_R +
                """ FROM review_events e JOIN line_reviews r ON r.id=e.review_id
                WHERE e.seq>? AND (?='' OR r.gate=?) AND (?='' OR r.review_status=?) ORDER BY e.seq LIMIT ?""",
                (after, gate, gate, status_filter, status_filter, limit + 1)).fetchall()
            for row in event_rows[:limit]:
                summary = self._summary_slim(row)
                fields = json.loads(row["occurrence_fields"]) if row["occurrence_fields"] else [None] * 9
                (source, candidate, reasons, disposition, technical,
                 kind, who, speaker, marker) = (list(fields) + [None] * 9)[:9]
                reasons = list(reasons or [])
                summary.update(seq=row["occurrence_seq"], event_seq=row["occurrence_seq"], at=row["occurrence_at"],
                               source_preview=str(source or "")[:220], candidate_preview=str(candidate or "")[:260],
                               reasons=reasons[:8], fault_count=len(reasons),
                               has_more_reasons=len(reasons) > 8,
                               disposition=disposition, technical=bool(technical),
                               kind=str(kind or ""),
                               who=str(who or speaker or marker or ""))
                events.append(summary)
            return {"items": [self._summary_slim(row) for row in rows[:limit]], "events": events,
                    "latest_cursor": latest, "next_after": events[-1]["seq"] if events else after,
                    "events_has_more": len(event_rows) > limit, "unreviewed": unreviewed, "total": total,
                    "attention": attention, "noted": noted,
                    "has_more": len(rows) > limit,
                    "next_before": rows[limit-1]["latest_seq"] if len(rows) > limit else None,
                    "policy": copy.deepcopy(self._policy)}

    def decide(self, review_id, action, note='', expected_revision=None, expected_event_seq=None):
        if action not in ("allow", "keep"):
            raise ValueError("action must be allow or keep")
        if not isinstance(note, str):
            raise ValueError("note must be a string")
        if expected_revision is not None:
            _integer(expected_revision, "expected_revision", 1, 2**63-1)
        if expected_event_seq is not None:
            _integer(expected_event_seq, 'expected_event_seq', 1, 2**63-1)
        with self._lock:
            with self._write() as db:
                item = self._row(db.execute("SELECT * FROM line_reviews WHERE id=?", (str(review_id),)).fetchone())
                if item is None:
                    raise KeyError("No such line review")
                if expected_event_seq is not None and expected_event_seq != item['latest_seq']:
                    raise ReviewConflictError('This cut has a newer occurrence; reload its evidence before deciding')
                if action == "allow" and item["technical"]:
                    raise ValueError("A technical failure cannot be approved as playable content")
                prior = item["decision"]
                if prior.get("scope") != 'instance' and prior.get("action") == action and prior.get("note") == note:
                    return {"row": item, "effect": item["effect"], "changed": False}
                if expected_revision is not None and expected_revision != item["revision"]:
                    raise ReviewConflictError("This review changed; reload it before deciding")
                decision = {"action": action, "note": note, "at": time.time(), "by": "operator"}
                # Editing the explanation is a new review revision, not a new
                # recovery request. Keep completed/queued work and its receipts.
                effect = (copy.deepcopy(item["effect"]) if prior.get("action") == action and prior.get('scope') != 'instance' else
                          {"action": action, "status": "awaiting_recovery" if action == "allow" else "kept",
                           "gate": item["gate"], "policy_revision": self._policy["revision"]})
                db.execute("UPDATE line_reviews SET review_status=?,revision=revision+1,decision=?,effect=? WHERE id=?",
                           ("allowed" if action == "allow" else "kept", _json(decision), _json(effect), item["id"]))
                db.execute("INSERT INTO review_decisions(review_id,at,body) VALUES (?,?,?)",
                           (item["id"], decision["at"], _json(decision)))
                item = self._row(db.execute("SELECT * FROM line_reviews WHERE id=?", (item["id"],)).fetchone())
                revoked = {}
                if action == 'keep':
                    for key, grant in self._instances.items():
                        if grant.get('original_review_id') == item['id']:
                            changed = {**copy.deepcopy(grant), 'review_status': 'kept',
                                       'effect': {'status': 'kept', 'say': 'One-time approval withdrawn.'}}
                            db.execute('UPDATE review_instances SET body=? WHERE id=?', (_json(changed), key))
                            revoked[key] = changed
            self._instances.update(revoked)
            if action == "allow":
                self._approved.add(item["fingerprint"])
            else:
                self._approved.discard(item["fingerprint"])
            self._refresh_preferences()
            return {"row": item, "effect": effect, "changed": True}

    def track_effect(self, review_id, effectdict):
        if not isinstance(effectdict, dict):
            raise ValueError("effect must be an object")
        with self._lock:
            if review_id in self._instances:
                grant = copy.deepcopy(self._instances[review_id])
                if grant['review_status'] == 'kept' and effectdict.get('status') != 'kept':
                    return grant
                grant['effect'] = {**grant['effect'], **effectdict, 'updated_at': time.time()}
                grant['revision'] += 1
                with self._write() as db:
                    db.execute('UPDATE review_instances SET body=? WHERE id=?', (_json(grant), review_id))
                    base = db.execute('SELECT decision FROM line_reviews WHERE id=?', (grant['original_review_id'],)).fetchone()
                    if base and json.loads(base[0]).get('instance_id') == review_id:
                        db.execute('UPDATE line_reviews SET effect=?,revision=revision+1 WHERE id=?',
                                   (_json(grant['effect']), grant['original_review_id']))
                self._instances[review_id] = grant
                return copy.deepcopy(grant)
            return self._track_effect_regular(review_id, effectdict)

    def _track_effect_regular(self, review_id, effectdict):
        with self._lock, self._write() as db:
            row = db.execute("SELECT * FROM line_reviews WHERE id=?", (str(review_id),)).fetchone()
            if row is None:
                raise KeyError("No such line review")
            effect = {**json.loads(row["effect"]), **effectdict, "updated_at": time.time()}
            db.execute("UPDATE line_reviews SET effect=?,revision=revision+1 WHERE id=?", (_json(effect), row["id"]))
            return self._row(db.execute("SELECT * FROM line_reviews WHERE id=?", (row["id"],)).fetchone())
