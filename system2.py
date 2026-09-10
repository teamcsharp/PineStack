"""Independent station planner with durable ownership and measured delivery receipts.

Adapters attest readiness, media availability and duration. This module never
generates, renders or plays anything; absent evidence remains explicit debt.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid


VERSION = 1
REPEAT_SECONDS = 3600.0
ACTIVE = ('reserved', 'playing', 'suspended')


class System2Conflict(ValueError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(str(value).encode('utf-8')).hexdigest()


def text_hash(text):
    """Punctuation/case changes cannot disguise replay of the same spoken words."""
    words = re.findall(r'[^\W_]+', str(text or '').casefold())
    return _hash(' '.join(words)) if words else ''


def _number(value, name, minimum=0.0, maximum=1e12):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(name + ' must be a finite number')
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(name + ' is out of range')
    return float(value)


def _name(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(name + ' must be a nonempty identifier')
    return value


def _candidate(row):
    if not isinstance(row, dict):
        raise ValueError('candidate must be an object')
    row = copy.deepcopy(row)
    row['id'] = _name(row.get('id'), 'candidate id')
    row['kind'] = _name(row.get('kind'), 'candidate kind')
    row['seconds'] = _number(row.get('seconds', 0), 'candidate seconds', 0, 3600)
    row['expires_at'] = _number(row.get('expires_at', 0), 'expires_at')
    row['ready'] = row.get('ready') is True
    row['eligible'] = row.get('eligible') is True
    row['repeat_guard'] = row.get('repeat_guard', True) is not False
    lines = row.get('lines') or []
    if not isinstance(lines, list) or any(not isinstance(line, dict) for line in lines):
        raise ValueError('candidate lines must be ordered objects')
    line_ids = []
    words = []
    for i, line in enumerate(lines):
        line['id'] = str(line.get('id') or i)
        line_ids.append(line['id'])
        if not isinstance(line.get('text', ''), str):
            raise ValueError('line text must be a string')
        if line.get('text'):
            words.append(text_hash(line['text']))
        if line.get('seconds') is not None:
            line['seconds'] = _number(line['seconds'], 'line seconds', 0, row['seconds'])
    if len(set(line_ids)) != len(line_ids):
        raise ValueError('line IDs must be unique in their recorded order')
    script = row.get('script') or '\n'.join(str(line.get('text') or '') for line in lines)
    if not isinstance(script, str):
        raise ValueError('script must be a string')
    row['script'] = script
    row['lines'] = lines
    if script:
        words.append(text_hash(script))
    audio = row.get('audio_hashes') or []
    if not isinstance(audio, list):
        raise ValueError('audio_hashes must be a list of measured SHA256 hashes')
    audio = list(audio) + [line['audio_hash'] for line in lines if line.get('audio_hash')]
    if any(not isinstance(value, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', value) for value in audio):
        raise ValueError('audio fingerprints must be measured SHA256 hashes')
    row['audio_hashes'] = sorted(set(value.lower() for value in audio))
    row['text_hashes'] = sorted(set(word for word in words if word))
    row['fingerprints'] = (['a:' + value for value in row['audio_hashes']] +
                           ['t:' + value for value in row['text_hashes']]) if row['repeat_guard'] else []
    missing = []
    if not row['ready']: missing.append('adapter_not_ready')
    if not row['eligible']: missing.append('adapter_ineligible')
    if row['seconds'] <= 0: missing.append('duration_missing')
    if not row['audio_hashes']: missing.append('audio_evidence_missing')
    if row['repeat_guard'] and not row['text_hashes']: missing.append('spoken_text_missing')
    row['blocked_reasons'] = missing
    row['signature'] = _hash(_json({k: row.get(k) for k in
        ('id', 'kind', 'seconds', 'script', 'lines', 'audio_hashes', 'text_hashes', 'source_id', 'repeat_guard',
         'slot_id', 'template_id', 'hour_id')}))
    if len(_json(row)) > 2_000_000:
        raise ValueError('candidate evidence exceeds the bounded record size')
    return row


class System2Store:
    def __init__(self, path, *, now=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.now = now
        self._lock = threading.RLock()
        with closing(self._connect()) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS s2_hours(id TEXT PRIMARY KEY,start REAL,revision INTEGER,config TEXT,body TEXT);
                CREATE TABLE IF NOT EXISTS s2_candidates(id TEXT PRIMARY KEY,kind TEXT,body TEXT);
                CREATE TABLE IF NOT EXISTS s2_slots(id TEXT PRIMARY KEY,hour_id TEXT,ordinal INTEGER,body TEXT);
                CREATE INDEX IF NOT EXISTS s2_slot_hour ON s2_slots(hour_id,ordinal);
                CREATE TABLE IF NOT EXISTS s2_jobs(id TEXT PRIMARY KEY,slot_id TEXT,state TEXT,deadline REAL,body TEXT);
                CREATE INDEX IF NOT EXISTS s2_job_deadline ON s2_jobs(state,deadline);
                CREATE TABLE IF NOT EXISTS s2_reservations(id TEXT PRIMARY KEY,slot_id TEXT,candidate_id TEXT,state TEXT,body TEXT);
                CREATE INDEX IF NOT EXISTS s2_reserved_candidate ON s2_reservations(candidate_id,state);
                CREATE TABLE IF NOT EXISTS s2_receipts(id TEXT PRIMARY KEY,at REAL,reservation_id TEXT,body TEXT);
                CREATE TABLE IF NOT EXISTS s2_heard(fingerprint TEXT PRIMARY KEY,at REAL,reservation_id TEXT,receipt_id TEXT);
                CREATE TABLE IF NOT EXISTS s2_events(id TEXT PRIMARY KEY,request_id TEXT UNIQUE,state TEXT,deadline REAL,priority INTEGER,body TEXT);
            ''')

    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=15000')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        return db

    @contextmanager
    def _tx(self):
        with self._lock, closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _get(db, table, identity):
        row = db.execute('SELECT body FROM ' + table + ' WHERE id=?', (identity,)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _save(db, table, row, columns=()):
        fields = ('id',) + tuple(columns) + ('body',)
        values = [row.get(key) for key in fields[:-1]] + [_json(row)]
        db.execute('INSERT INTO ' + table + '(' + ','.join(fields) + ') VALUES(' +
                   ','.join('?' for _ in fields) + ') ON CONFLICT(id) DO UPDATE SET ' +
                   ','.join(key + '=excluded.' + key for key in fields[1:]), values)

    def sync_candidates(self, candidates, *, replace=False):
        normalized = [_candidate(row) for row in candidates]
        if len({row['id'] for row in normalized}) != len(normalized):
            raise ValueError('candidate IDs must be unique')
        with self._tx() as db:
            self._sync(db, normalized, replace)
        return {'candidates': len(normalized)}

    def _sync(self, db, rows, replace=False):
        if replace:
            keep = {row['id'] for row in rows}
            for raw in db.execute('SELECT id,body FROM s2_candidates').fetchall():
                if raw['id'] not in keep:
                    old = json.loads(raw['body']); old.update(ready=False, eligible=False,
                        blocked_reasons=['absent_from_current_inventory'])
                    self._save(db, 's2_candidates', old, ('kind',))
        for row in rows:
            self._save(db, 's2_candidates', row, ('kind',))

    def _repeat_reason(self, db, candidate, when, own=''):
        for fingerprint in candidate['fingerprints']:
            heard = db.execute('SELECT at,reservation_id FROM s2_heard WHERE fingerprint=?', (fingerprint,)).fetchone()
            if heard and (not own or heard['reservation_id'] != own) and when - heard['at'] < REPEAT_SECONDS:
                return 'heard_within_one_hour'
        return ''

    def _eligible(self, db, candidate, when, *, own=''):
        if candidate['blocked_reasons']:
            return candidate['blocked_reasons'][0]
        if candidate['expires_at'] and when + candidate['seconds'] > candidate['expires_at']:
            return 'candidate_expired'
        repeat = self._repeat_reason(db, candidate, when, own)
        if repeat:
            return repeat
        for raw in db.execute("SELECT body FROM s2_reservations WHERE state IN ('reserved','playing','suspended')"):
            reserved = json.loads(raw[0])
            if reserved['id'] == own: continue
            if reserved['state'] == 'reserved' and reserved['lease_until'] <= self.now(): continue
            if (reserved['candidate_id'] == candidate['id'] or
                    set(reserved['candidate']['fingerprints']) & set(candidate['fingerprints'])):
                return 'reserved_by_another_owner'
        return ''

    @staticmethod
    def _slot_matches(candidate, slot):
        if candidate['kind'] != slot['kind']: return False
        if slot.get('require_slot_binding') and candidate.get('slot_id') != slot['id']: return False
        for field in ('slot_id', 'template_id', 'hour_id'):
            target = slot['id'] if field == 'slot_id' else slot.get(field)
            if candidate.get(field) and candidate[field] != target: return False
        allowed = slot.get('candidate_ids')
        return allowed is None or candidate['id'] in allowed

    def _allocation_metrics(self, db, slot, allocation):
        candidate = allocation['candidate']
        current = self._get(db, 's2_candidates', candidate['id'])
        held = [json.loads(raw[0]) for raw in db.execute(
            "SELECT body FROM s2_reservations WHERE slot_id=? AND candidate_id=? AND state IN ('reserved','playing','suspended','completed')",
            (slot['id'], candidate['id']))]
        held = [row for row in held if row['revision'] == slot['revision'] and
                (row['state'] != 'reserved' or row['lease_until'] > self.now())]
        held.sort(key=lambda row: row.get('reserved_at', 0), reverse=True)
        reservation = next((row for row in held if row['state'] != 'reserved'), held[0] if held else None)
        if reservation and reservation['state'] in ('playing', 'suspended', 'completed'):
            state = reservation['state']
            remaining = 0 if state == 'completed' else max(0, reservation['actual_seconds'] -
                (reservation['position_seconds'] if state == 'suspended' else
                 max(reservation['position_seconds'], self.now() - reservation.get('resumed_at', reservation['dispatched_at']) +
                     (reservation['position_seconds'] if reservation.get('resumed_at') else 0))))
            return {'state': state, 'coverage': reservation['actual_seconds'], 'ready': 0,
                    'remaining': remaining, 'retain': True, 'reservation_id': reservation['id']}
        own = reservation['id'] if reservation else ''
        valid = bool(current and current['signature'] == candidate['signature'] and self._slot_matches(current, slot)
                     and not self._eligible(db, current, max(self.now(), slot['start']), own=own)
                     and max(self.now(), slot['start']) + current['seconds'] <= slot['deadline'])
        return {'state': 'reserved' if reservation and valid else 'ready' if valid else 'unavailable',
                'coverage': candidate['seconds'] if valid else 0, 'ready': candidate['seconds'] if valid else 0,
                'remaining': candidate['seconds'] if valid else 0, 'retain': valid,
                'reservation_id': own}

    def _slot_totals(self, db, slot):
        metrics = [self._allocation_metrics(db, slot, a) for a in slot['allocations']]
        for allocation, value in zip(slot['allocations'], metrics):
            allocation['state'] = value['state']
            allocation['reservation_id'] = value['reservation_id']
        slot['allocated_seconds'] = round(sum(a['candidate']['seconds'] for a in slot['allocations']), 6)
        slot['ready_seconds'] = round(sum(m['ready'] for m in metrics), 6)
        slot['coverage_seconds'] = round(sum(m['coverage'] for m in metrics), 6)
        slot['in_flight_seconds'] = round(sum(m['remaining'] for m in metrics if m['state'] in ('playing', 'suspended')), 6)
        slot['coverage_performances'] = sum(m['coverage'] > 0 for m in metrics)
        if slot.get('coverage_mode') == 'one_performance':
            slot['target_performances'] = 1
            slot['performance_debt'] = max(0, 1 - slot['coverage_performances'])
            slot['debt_seconds'] = slot['target_seconds'] if slot['performance_debt'] else 0
            completed = [self._get(db, 's2_reservations', m['reservation_id']) for m in metrics if m['state'] == 'completed']
            slot['heard_performances'] = sum(r['heard_seconds'] >= r['actual_seconds'] for r in completed)
        else:
            slot['debt_seconds'] = round(max(0, slot['target_seconds'] - slot['coverage_seconds']), 6)
        return metrics

    def plan_hour(self, hour_start, templates, candidates=(), *, config_revision='', expected_revision=None, plan_id=None):
        hour_start = _number(hour_start, 'hour_start')
        if not isinstance(templates, list) or not templates or len(templates) > 200:
            raise ValueError('one through 200 configured templates are required')
        enabled = []
        offset = 0.0
        for index, template in enumerate(templates):
            if not isinstance(template, dict): raise ValueError('template must be an object')
            if template.get('enabled', True) is False: continue
            row = copy.deepcopy(template)
            row['id'] = str(row.get('id') or index)
            row['kind'] = _name(row.get('kind'), 'slot kind')
            if row.get('candidate_ids') is not None and (not isinstance(row['candidate_ids'], list) or
                    any(not isinstance(value, str) or not value for value in row['candidate_ids'])):
                raise ValueError('candidate_ids must list exact allowed candidate IDs')
            row['seconds'] = _number(row.get('seconds'), 'slot seconds', .001, 3600)
            row['offset'] = _number(row.get('offset', offset), 'slot offset', 0, 720000)
            if row['offset'] < offset: raise ValueError('configured slots overlap or change order')
            row['target_seconds'] = _number(row.get('target_seconds', row['seconds']), 'target_seconds', 0, row['seconds'])
            if row.get('coverage_mode', 'duration') not in ('duration', 'one_performance'):
                raise ValueError('coverage_mode must be duration or one_performance')
            if row.get('coverage_mode') == 'one_performance' and row['target_seconds'] <= 0:
                raise ValueError('one_performance needs a positive preparation budget')
            if row.get('allocation_mode', 'automatic') not in ('automatic', 'current'):
                raise ValueError('allocation_mode must be automatic or current')
            if row.get('prep_cost_per_second') is not None:
                row['prep_cost_per_second'] = _number(row['prep_cost_per_second'], 'prep_cost_per_second', 0, 1000)
            enabled.append(row); offset = row['offset'] + row['seconds']
        if not enabled: raise ValueError('no configured enabled slots')
        if len({r['id'] for r in enabled}) != len(enabled): raise ValueError('template IDs must be unique')
        normalized = [_candidate(row) for row in candidates]
        if len({row['id'] for row in normalized}) != len(normalized): raise ValueError('duplicate candidate IDs')
        config = _hash(_json([config_revision, enabled]))
        hour_id = _name(plan_id, 'plan_id') if plan_id is not None else 'hour-' + str(int(hour_start * 1000))
        with self._tx() as db:
            old = self._get(db, 's2_hours', hour_id)
            revision = old['revision'] if old else 0
            if expected_revision is not None and expected_revision != revision:
                raise System2Conflict('Hour changed; inspect its current revision.')
            changed = not old or old['config'] != config or old['start'] != hour_start
            if changed and old:
                # 2026-09-10: ...AND WHOSE LEASE IS STILL ALIVE. A
                # reservation stuck in 'playing' is not an active
                # performance, it is a corpse, and this guard let one block
                # its hour from ever being planned again.
                #
                # Found on a station the operator reported as full of dead
                # air: THIRTEEN reservations in 'playing', every one of them
                # past its lease, the oldest from two days earlier. The hour
                # on air had one. So plan_hour raised on every refresh,
                # /api/system2/status answered 500, the director's room
                # showed all twenty entries "unplanned", and nothing was
                # allocated to anything - while the shelf held hundreds of
                # finished rounds. The station played music and waited.
                #
                # #1074 fixed exactly this shape for JOBS ("a restart leaves
                # the job it was working on 'working' under a lease nobody
                # will renew") and reservations were left with the same
                # wound. A live lease still blocks - that is the rule this
                # guard is for, and it is right.
                occupied = db.execute(
                    "SELECT r.id FROM s2_reservations r JOIN s2_slots s ON s.id=r.slot_id"
                    " WHERE s.hour_id=? AND r.state IN ('playing','suspended')"
                    " AND COALESCE(json_extract(r.body,'$.lease_until'), 0) > ?"
                    " LIMIT 1", (hour_id, self.now())).fetchone()
                if occupied: raise System2Conflict('An active performance must finish or remain on its original plan.')
            if changed: revision += 1
            self._sync(db, normalized)
            catalogue = [json.loads(raw[0]) for raw in db.execute('SELECT body FROM s2_candidates')]
            bookings = []
            for raw in db.execute('SELECT body FROM s2_slots WHERE hour_id<>?', (hour_id,)):
                other = json.loads(raw[0])
                for allocation in other.get('allocations') or []:
                    at = allocation['planned_start']
                    candidate = allocation['candidate']
                    if at + candidate['seconds'] + REPEAT_SECONDS > self.now():
                        bookings.append((at, candidate))
            slots = []
            for i, template in enumerate(enabled):
                identity = hour_id + ':' + template['id']
                previous = self._get(db, 's2_slots', identity) if not changed else None
                slots.append({**template, 'id': identity, 'template_id': template['id'], 'hour_id': hour_id,
                    'ordinal': i, 'revision': revision, 'start': hour_start + template['offset'],
                    'deadline': min(hour_start + 3600, hour_start + template['offset'] + template['seconds']),
                    'allocations': copy.deepcopy((previous or {}).get('allocations') or []),
                    'heard_seconds': float((previous or {}).get('heard_seconds') or 0),
                    'delivered_seconds': float((previous or {}).get('delivered_seconds') or 0)})
            # Keep live ownership; revoke an unowned allocation when its actual proof changes.
            used, fingerprints = set(), set()
            for slot in slots:
                retained = []
                for allocation in slot['allocations']:
                    if self._allocation_metrics(db, slot, allocation)['retain']:
                        retained.append(allocation); used.add(allocation['candidate']['id']); fingerprints.update(allocation['candidate']['fingerprints'])
                slot['allocations'] = retained
            # One ready candidate for each occurrence before filling earlier slots further.
            for first_only in (True, False):
                for slot in slots:
                    if slot.get('allocation_mode') == 'current': continue
                    while True:
                        metrics = self._slot_totals(db, slot)
                        held = sum(m['remaining'] for m in metrics)
                        need = slot['debt_seconds']
                        room = slot['deadline'] - max(slot['start'], self.now()) - held
                        if need <= .001 or room <= 0 or (first_only and slot['allocations']): break
                        choices = [c for c in catalogue if self._slot_matches(c, slot) and c['id'] not in used
                            and not (set(c['fingerprints']) & fingerprints) and c['seconds'] <= room
                            and not any((booked['id'] == c['id'] or set(booked['fingerprints']) & set(c['fingerprints']))
                                and abs(max(slot['start'], self.now()) + held - at) < REPEAT_SECONDS + max(booked['seconds'], c['seconds'])
                                for at, booked in bookings)
                            and not self._eligible(db, c, max(slot['start'], self.now()) + held)]
                        if not choices: break
                        # Prefer the smallest whole performance that fills the debt; otherwise the largest fit.
                        candidate = min(choices, key=lambda c: (c['seconds'] < need, abs(c['seconds'] - need), c['id']))
                        slot['allocations'].append({'candidate': copy.deepcopy(candidate), 'planned_start': max(slot['start'], self.now()) + held})
                        used.add(candidate['id']); fingerprints.update(candidate['fingerprints'])
                        if first_only: break
            for slot in slots:
                self._slot_totals(db, slot)
                slot['status'] = ('outside_hour_capacity' if slot['start'] >= hour_start + 3600 else
                    'complete' if (slot.get('heard_performances', 0) >= 1 if slot.get('coverage_mode') == 'one_performance'
                                   else slot['heard_seconds'] >= slot['target_seconds']) else
                    'ready' if slot['debt_seconds'] <= .001 else 'needs_preparation')
                self._save(db, 's2_slots', slot, ('hour_id', 'ordinal'))
                self._job_for_slot(db, slot)
            valid = {slot['id'] for slot in slots}
            for raw in db.execute('SELECT id FROM s2_slots WHERE hour_id=?', (hour_id,)).fetchall():
                if raw['id'] not in valid: db.execute('DELETE FROM s2_slots WHERE id=?', (raw['id'],))
            hour = {'id': hour_id, 'start': hour_start, 'revision': revision, 'config': config,
                'config_revision': str(config_revision), 'updated_at': self.now(), 'version': VERSION,
                'templates': copy.deepcopy(enabled),
                'configured_slots': len(slots), 'configured_seconds': offset,
                'over_capacity_seconds': max(0, offset - 3600)}
            self._save(db, 's2_hours', hour, ('start', 'revision', 'config'))
            return self._hour(db, hour_id)

    def _job_for_slot(self, db, slot):
        identity = slot['id'] + ':prepare'
        old = self._get(db, 's2_jobs', identity)
        debt = slot['debt_seconds']
        if old and old['revision'] == slot['revision'] and old['state'] == 'working' and old.get('lease_until', 0) > self.now():
            return
        job = {'id': identity, 'slot_id': slot['id'], 'hour_id': slot['hour_id'], 'kind': slot['kind'],
            'revision': slot['revision'], 'deadline': slot['start'], 'hard_deadline': slot['deadline'],
            'target_ready_seconds': debt, 'slot_target_seconds': slot['target_seconds'],
            'slot_ready_seconds': slot['ready_seconds'], 'coverage_missing': slot['coverage_seconds'] <= .001,
            'estimated_work_seconds': debt * slot['prep_cost_per_second'] if slot.get('prep_cost_per_second') is not None else None,
            'state': 'pending' if debt > .001 and slot['deadline'] > self.now() else 'satisfied' if debt <= .001 else 'expired',
            'attempts': int((old or {}).get('attempts') or 0),
            'retry_at': float((old or {}).get('retry_at') or 0) if old and old['revision'] == slot['revision'] else 0}
        if old and old['revision'] == slot['revision'] and old.get('attempts'):
            job['last_attempt'] = {key: copy.deepcopy(old[key]) for key in
                ('owner', 'token', 'claimed_at', 'lease_until', 'finished_at', 'state', 'result') if key in old}
            if not job['last_attempt'].get('owner') and old.get('last_attempt'):
                job['last_attempt'] = copy.deepcopy(old['last_attempt'])
        self._save(db, 's2_jobs', job, ('slot_id', 'state', 'deadline'))

    def _hour(self, db, identity):
        hour = self._get(db, 's2_hours', identity)
        if hour is None: return None
        hour['slots'] = [json.loads(r[0]) for r in db.execute('SELECT body FROM s2_slots WHERE hour_id=? ORDER BY ordinal', (identity,))]
        for slot in hour['slots']:
            self._slot_totals(db, slot)
        hour['ready_seconds'] = sum(s['ready_seconds'] for s in hour['slots'])
        hour['allocated_seconds'] = sum(s.get('allocated_seconds', s['ready_seconds']) for s in hour['slots'])
        hour['coverage_seconds'] = sum(s.get('coverage_seconds', s['ready_seconds']) for s in hour['slots'])
        hour['in_flight_seconds'] = sum(s.get('in_flight_seconds', 0) for s in hour['slots'])
        hour['debt_seconds'] = sum(s['debt_seconds'] for s in hour['slots'])
        hour['all_segments_present'] = all(s.get('coverage_seconds', s['ready_seconds']) > .001 or s['target_seconds'] == 0 for s in hour['slots'])
        return hour

    def get_hour(self, identity):
        with self._lock, closing(self._connect()) as db:
            return self._hour(db, identity)

    def hours(self, *, before=1e12, limit=24):
        _number(before, 'before')
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 168: raise ValueError('limit must be 1 through 168')
        with self._lock, closing(self._connect()) as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM s2_hours WHERE start<? ORDER BY start DESC LIMIT ?', (before, limit))]

    def _records(self, table, *, states=None, limit=200):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError('limit must be 1 through 1000')
        if states is not None and (not isinstance(states, (list, tuple, set)) or any(not isinstance(v, str) for v in states)):
            raise ValueError('states must be a collection of names')
        with self._lock, closing(self._connect()) as db:
            where = (' WHERE state IN (' + ','.join('?' for _ in states) + ')') if states else ''
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM ' + table + where +
                ' ORDER BY rowid DESC LIMIT ?', tuple(states or ()) + (limit,))]

    def jobs(self, *, states=None, limit=200):
        return self._records('s2_jobs', states=states, limit=limit)

    def events(self, *, states=None, limit=200):
        return self._records('s2_events', states=states, limit=limit)

    def reservations(self, *, states=None, limit=200):
        return self._records('s2_reservations', states=states, limit=limit)

    def get_reservation(self, identity):
        with self._lock, closing(self._connect()) as db:
            return self._get(db, 's2_reservations', identity)

    def get_job(self, identity):
        with self._lock, closing(self._connect()) as db:
            return self._get(db, 's2_jobs', identity)

    def get_event(self, identity):
        with self._lock, closing(self._connect()) as db:
            return self._get(db, 's2_events', identity)

    def get_candidate(self, identity):
        with self._lock, closing(self._connect()) as db:
            return self._get(db, 's2_candidates', identity)

    def candidates_for_slot(self, slot_id):
        with self._lock, closing(self._connect()) as db:
            slot = self._get(db, 's2_slots', slot_id)
            if not slot: return []
            rows = [json.loads(raw[0]) for raw in db.execute('SELECT body FROM s2_candidates WHERE kind=?', (slot['kind'],))]
            return [row for row in rows if row.get('slot_id') == slot_id and self._slot_matches(row, slot)]

    def candidates_by_slot(self, slot_ids):
        """#1070: the bound drafts of a whole hour in one decode of the candidate
        table. candidates_for_slot asked per slot decoded every body of the kind
        forty times a refresh; the C decoder holds the GIL, and the air clock on
        the main thread lost most of those contests."""
        ids = [str(s) for s in slot_ids]
        out = {sid: [] for sid in ids}
        with self._lock, closing(self._connect()) as db:
            slots = {}
            for sid in ids:
                slot = self._get(db, 's2_slots', sid)
                if slot: slots[sid] = slot
            kinds = sorted({slot['kind'] for slot in slots.values()})
            if not kinds: return out
            marks = ','.join('?' * len(kinds))
            for raw in db.execute('SELECT body FROM s2_candidates WHERE kind IN (%s)' % marks, tuple(kinds)):
                row = json.loads(raw[0])
                slot = slots.get(row.get('slot_id'))
                if slot and self._slot_matches(row, slot):
                    out[slot['id']].append(row)
        return out

    def allocate_current(self, slot_id, candidate_id, *, expected_revision=None):
        """Bind actual current media without stealing owned or future planned work."""
        with self._tx() as db:
            slot = self._get(db, 's2_slots', slot_id)
            if not slot: raise ValueError('Unknown configured slot')
            if expected_revision is not None and expected_revision != slot['revision']:
                raise System2Conflict('Slot revision changed.')
            if not slot['start'] <= self.now() < slot['deadline']:
                raise System2Conflict('Only the current occurrence can select its actual media.')
            for raw in db.execute("SELECT body FROM s2_reservations WHERE slot_id=? AND state IN ('reserved','playing','suspended','completed')", (slot_id,)):
                row = json.loads(raw[0])
                if row['revision'] == slot['revision'] and (row['state'] != 'reserved' or row['lease_until'] > self.now()):
                    raise System2Conflict('An owned or completed performance cannot be replaced.')
            candidate = self._get(db, 's2_candidates', candidate_id)
            if not candidate or not self._slot_matches(candidate, slot):
                raise System2Conflict('Candidate kind or occurrence does not match.')
            reason = self._eligible(db, candidate, self.now())
            if reason: raise System2Conflict(reason)
            if self.now() + candidate['seconds'] > slot['deadline']:
                raise System2Conflict('Complete measured performance no longer fits the slot.')
            for raw in db.execute('SELECT body FROM s2_slots WHERE id<>?', (slot_id,)):
                other = json.loads(raw[0])
                if other['deadline'] <= self.now(): continue
                if any(a['candidate']['id'] == candidate_id or set(a['candidate']['fingerprints']) & set(candidate['fingerprints'])
                       for a in other.get('allocations', [])):
                    raise System2Conflict('Candidate is allocated to another current or future occurrence.')
            slot['allocations'] = [{'candidate': copy.deepcopy(candidate), 'planned_start': self.now()}]
            self._slot_totals(db, slot)
            slot['status'] = 'ready' if slot['debt_seconds'] <= .001 else 'needs_preparation'
            self._save(db, 's2_slots', slot, ('hour_id', 'ordinal'))
            self._job_for_slot(db, slot)
            return slot

    def scripts(self, hour_id):
        hour = self.get_hour(hour_id)
        if not hour: return None
        return {'hour_id': hour_id, 'revision': hour['revision'], 'slots': [
            {'slot_id': slot['id'], 'kind': slot['kind'], 'start': slot['start'], 'deadline': slot['deadline'],
             'performances': [copy.deepcopy(a['candidate']) for a in slot['allocations']]} for slot in hour['slots']]}

    def claim_job(self, owner, *, kinds=None, lease_seconds=300, lookahead_seconds=3600):
        _name(owner, 'owner'); _number(lease_seconds, 'lease_seconds', 1, 3600)
        _number(lookahead_seconds, 'lookahead_seconds', 0, 86400)
        if kinds is not None and (not isinstance(kinds, (list, tuple, set)) or any(not isinstance(k, str) for k in kinds)):
            raise ValueError('kinds must be a collection of exact kinds')
        with self._tx() as db:
            choices = []
            for raw in db.execute("SELECT body FROM s2_jobs WHERE state IN ('pending','working')"):
                job = json.loads(raw[0]); slot = self._get(db, 's2_slots', job['slot_id'])
                if not slot or slot['revision'] != job['revision']: continue
                if job['hard_deadline'] <= self.now() or job.get('retry_at', 0) > self.now(): continue
                if job['deadline'] > self.now() + lookahead_seconds: continue
                if kinds is not None and job['kind'] not in kinds: continue
                if job['state'] == 'working' and job.get('lease_until', 0) > self.now(): continue
                choices.append(job)
            if not choices: return None
            # Within the active horizon, ensure each segment exists before topping one up.
            job = min(choices, key=lambda j: (not j['coverage_missing'], j['deadline'],
                j['estimated_work_seconds'] if j['estimated_work_seconds'] is not None else float('inf'), j['id']))
            job.update(state='working', owner=owner, token=uuid.uuid4().hex,
                       lease_until=self.now() + lease_seconds, claimed_at=self.now(), attempts=job['attempts'] + 1)
            slot = self._get(db, 's2_slots', job['slot_id'])
            job['template'] = {k: copy.deepcopy(v) for k, v in slot.items()
                               if k not in {'allocations', 'heard_seconds', 'delivered_seconds'}}
            job['available_until_deadline_seconds'] = max(0.0, job['deadline'] - self.now())
            job['estimated_deadline_fit'] = (None if job['estimated_work_seconds'] is None else
                job['estimated_work_seconds'] <= job['available_until_deadline_seconds'])
            self._save(db, 's2_jobs', job, ('slot_id', 'state', 'deadline'))
            return job

    def complete_job(self, job_id, owner, token, *, candidates=(), success=True, retry_after=30, result=None):
        normalized = [_candidate(row) for row in candidates]
        _number(retry_after, 'retry_after', 0, 3600)
        if result is not None and not isinstance(result, dict): raise ValueError('job result must be an object')
        with self._tx() as db:
            job = self._get(db, 's2_jobs', job_id)
            if not job or job.get('owner') != owner or job.get('token') != token:
                raise System2Conflict('Preparation job ownership changed.')
            slot = self._get(db, 's2_slots', job['slot_id'])
            if not slot or slot['revision'] != job['revision'] or job.get('lease_until', 0) <= self.now():
                raise System2Conflict('Preparation job is stale; retained work must be reoffered to the current plan.')
            if job['state'] != 'working': return {'changed': False, 'job': job, 'replan_needed': True}
            if any(not self._slot_matches(row, slot) for row in normalized): raise ValueError('Prepared candidate kind or occurrence does not match its job.')
            self._sync(db, normalized)
            made_ready = any(not row['blocked_reasons'] for row in normalized)
            job.update(state='completed' if success and made_ready else 'progress' if success else 'pending',
                       finished_at=self.now(), ready_output=made_ready,
                       retry_at=0 if success and made_ready else self.now() + retry_after)
            if result is not None: job['result'] = copy.deepcopy(result)
            self._save(db, 's2_jobs', job, ('slot_id', 'state', 'deadline'))
            return {'changed': True, 'job': job, 'replan_needed': True}

    def renew_job(self, job_id, owner, token, *, lease_seconds=300):
        _number(lease_seconds, 'lease_seconds', 1, 3600)
        with self._tx() as db:
            row = self._get(db, 's2_jobs', job_id)
            slot = self._get(db, 's2_slots', row['slot_id']) if row else None
            if (not row or row['state'] != 'working' or row.get('owner') != owner or row.get('token') != token
                    or row.get('lease_until', 0) <= self.now() or not slot or slot['revision'] != row['revision']):
                raise System2Conflict('Preparation job ownership or plan changed.')
            row['lease_until'] = self.now() + lease_seconds
            self._save(db, 's2_jobs', row, ('slot_id', 'state', 'deadline'))
            return row

    def reclaim_reservations(self, owner):
        """#1074's cure, applied to reservations as well as jobs.

        A round that was on air when the process died leaves its
        reservation in 'playing' under a lease nobody will renew. Nothing
        ever cleared those, so they accumulated - thirteen of them over two
        days on the station this was written for - and each one silently
        forbade its hour from ever being re-planned. Released on start,
        with the reason recorded, because an owner is one process per store
        and on its start every reservation it still holds is its own lost
        work."""
        _name(owner, 'owner')
        freed = []
        with self._tx() as db:
            rows = db.execute(
                "SELECT id, body FROM s2_reservations WHERE state IN ('playing','suspended')"
            ).fetchall()
            for row in rows:
                try:
                    body = json.loads(row[1])
                except Exception:
                    body = {}
                if float(body.get('lease_until') or 0) > self.now():
                    continue            # still live; leave it alone
                body['state'] = 'released'
                body['released_at'] = self.now()
                body['release_reason'] = (
                    'the process that was airing this did not finish; its lease expired')
                db.execute("UPDATE s2_reservations SET state='released', body=? WHERE id=?",
                           (_json(body), row[0]))
                freed.append(row[0])
        return freed

    def reclaim_jobs(self, owner):
        """#1074: hand a restarted owner its own unfinished jobs back.

        A restart leaves the job it was working on 'working' under a lease
        nobody will renew, and claim_job skips that slot for the rest of the
        lease. Tonight five restarts in seventy minutes (deploys and the host
        watchdog) left four slots' jobs orphaned for 1800 s each - one of
        them for the whole of its occurrence. The owner is one process per
        store, so on its start every job it still holds is its own lost work:
        it is pending again at once, attempts and last result kept."""
        _name(owner, 'owner')
        reclaimed = []
        with self._tx() as db:
            for raw in db.execute("SELECT body FROM s2_jobs WHERE state='working'").fetchall():
                job = json.loads(raw[0])
                if job.get('owner') != owner:
                    continue
                job.update(state='pending', lease_until=0, retry_at=0, reclaimed_at=self.now(),
                           reclaim_reason='the owner restarted before this attempt completed')
                self._save(db, 's2_jobs', job, ('slot_id', 'state', 'deadline'))
                reclaimed.append(job['id'])
        return reclaimed

    def reserve(self, slot_id, candidate_id, owner, *, expected_revision=None, lease_seconds=120, request_id=None):
        _name(owner, 'owner'); _number(lease_seconds, 'lease_seconds', 1, 3600)
        if request_id is not None: _name(request_id, 'request_id')
        with self._tx() as db:
            if request_id:
                for raw in db.execute('SELECT body FROM s2_reservations'):
                    held = json.loads(raw[0])
                    if held.get('request_id') == request_id:
                        if (held['slot_id'], held['candidate_id'], held['owner']) != (slot_id, candidate_id, owner):
                            raise System2Conflict('Reservation request ID belongs to different work.')
                        return held
            slot = self._get(db, 's2_slots', slot_id)
            if not slot: raise ValueError('Unknown configured slot')
            if expected_revision is not None and slot['revision'] != expected_revision: raise System2Conflict('Slot revision changed.')
            allocation = next((a for a in slot['allocations'] if a['candidate']['id'] == candidate_id), None)
            if not allocation: raise System2Conflict('Candidate is not allocated to this slot.')
            candidate = self._get(db, 's2_candidates', candidate_id)
            if not candidate or candidate['signature'] != allocation['candidate']['signature']:
                raise System2Conflict('Candidate wording, media or duration changed; replan.')
            if not self._slot_matches(candidate, slot): raise System2Conflict('Candidate belongs to another configured occurrence.')
            for raw in db.execute("SELECT body FROM s2_reservations WHERE slot_id=? AND state IN ('reserved','playing','suspended')", (slot_id,)):
                occupied = json.loads(raw[0])
                if occupied['state'] != 'reserved' or occupied['lease_until'] > self.now():
                    raise System2Conflict('This slot already has an owned active performance.')
            if db.execute("SELECT 1 FROM s2_reservations WHERE slot_id=? AND candidate_id=? AND state IN ('completed','playing','suspended')", (slot_id, candidate_id)).fetchone():
                raise System2Conflict('This allocated performance is already dispatched or complete.')
            reason = self._eligible(db, candidate, max(self.now(), slot['start']))
            if reason: raise System2Conflict(reason)
            if max(self.now(), slot['start']) + candidate['seconds'] > slot['deadline']:
                raise System2Conflict('Complete measured performance no longer fits the slot.')
            row = {'id': uuid.uuid4().hex, 'slot_id': slot_id, 'hour_id': slot['hour_id'], 'candidate_id': candidate_id,
                'revision': slot['revision'], 'owner': owner, 'token': uuid.uuid4().hex, 'request_id': request_id,
                'state': 'reserved', 'lease_until': self.now() + lease_seconds, 'reserved_at': self.now(),
                'candidate': copy.deepcopy(candidate), 'actual_seconds': candidate['seconds'], 'position_seconds': 0,
                'heard_lines': [], 'heard_seconds': 0.0, 'delivered_seconds': 0.0, 'receipts': []}
            self._save(db, 's2_reservations', row, ('slot_id', 'candidate_id', 'state'))
            self._slot_totals(db, slot)
            self._save(db, 's2_slots', slot, ('hour_id', 'ordinal'))
            return row

    def _owned(self, db, identity, owner, token=None):
        row = self._get(db, 's2_reservations', identity)
        if not row or row['owner'] != owner or (token is not None and row['token'] != token):
            raise System2Conflict('Reservation ownership changed.')
        return row

    def _validate(self, db, row, seconds=None):
        slot = self._get(db, 's2_slots', row['slot_id'])
        if row['state'] not in ACTIVE: return 'reservation_not_active'
        if not slot or slot['revision'] != row['revision']: return 'slot_revision_changed'
        if row['state'] == 'reserved' and row['lease_until'] <= self.now(): return 'reservation_lease_expired'
        candidate = self._get(db, 's2_candidates', row['candidate_id'])
        if not candidate or candidate['signature'] != row['candidate']['signature']: return 'candidate_proof_changed'
        if not self._slot_matches(candidate, slot): return 'candidate_target_changed'
        reason = self._eligible(db, candidate, self.now(), own=row['id'])
        if reason: return reason
        duration = row['actual_seconds'] if seconds is None else _number(seconds, 'actual seconds', .001, 3600)
        if self.now() + duration - row['position_seconds'] > slot['deadline']: return 'measured_duration_misses_deadline'
        return ''

    def validate_reservation(self, reservation_id, owner, *, token=None, seconds=None):
        with self._lock, closing(self._connect()) as db:
            row = self._owned(db, reservation_id, owner, token)
            reason = self._validate(db, row, seconds)
            return {'allowed': not reason, 'reason': reason, 'reservation': row}

    def mark_dispatched(self, reservation_id, owner, *, token=None, seconds=None):
        with self._tx() as db:
            row = self._owned(db, reservation_id, owner, token)
            if row['state'] == 'playing': return row
            if row['state'] != 'reserved': raise System2Conflict('Only a fresh owned reservation can be dispatched.')
            reason = self._validate(db, row, seconds)
            slot = self._get(db, 's2_slots', row['slot_id'])
            if self.now() < slot['start']: reason = 'slot_has_not_started'
            if reason: raise System2Conflict(reason)
            row.update(state='playing', dispatched_at=self.now(), actual_seconds=seconds if seconds is not None else row['actual_seconds'])
            # A dispatch with no receipt is uncertain, never an automatically replayable lease.
            row['lease_until'] = self.now() + row['actual_seconds'] + 120
            self._save(db, 's2_reservations', row, ('slot_id', 'candidate_id', 'state'))
            return row

    def can_play(self, texts=(), audio_hashes=(), *, at=None, reservation_id=''):
        if isinstance(texts, str): texts = [texts]
        if isinstance(audio_hashes, str): audio_hashes = [audio_hashes]
        if any(not isinstance(value, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', value) for value in audio_hashes):
            raise ValueError('audio fingerprints must be measured SHA256 hashes')
        when = self.now() if at is None else _number(at, 'at')
        fingerprints = ['t:' + text_hash(text) for text in texts if text_hash(text)] + ['a:' + value.lower() for value in audio_hashes]
        with self._lock, closing(self._connect()) as db:
            reason = self._repeat_reason(db, {'fingerprints': fingerprints}, when, reservation_id)
            if not reason:
                for raw in db.execute("SELECT body FROM s2_reservations WHERE state IN ('reserved','playing','suspended')"):
                    held = json.loads(raw[0])
                    if held['id'] == reservation_id: continue
                    if held['state'] == 'reserved' and held['lease_until'] <= self.now(): continue
                    if set(fingerprints) & set(held['candidate']['fingerprints']):
                        reason = 'reserved_by_another_owner'; break
            return {'allowed': not reason, 'reason': reason, 'repeat_seconds': REPEAT_SECONDS}

    def _heard(self, db, fingerprints, at, reservation_id, receipt_id):
        for value in fingerprints:
            db.execute('INSERT INTO s2_heard VALUES(?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET at=excluded.at,reservation_id=excluded.reservation_id,receipt_id=excluded.receipt_id WHERE excluded.at>s2_heard.at',
                       (value, at, reservation_id, receipt_id))

    def record_external(self, text, audio_hash='', *, receipt_id, at=None, seconds=0, reservation_id=''):
        _name(receipt_id, 'receipt_id'); _number(seconds, 'seconds', 0, 3600)
        if not isinstance(text, str) or not text.strip(): raise ValueError('Audible words are required.')
        if audio_hash and not re.fullmatch(r'[a-fA-F0-9]{64}', audio_hash): raise ValueError('audio_hash must be measured SHA256')
        at = self.now() if at is None else _number(at, 'at', 0, self.now() + 5)
        row = {'id': receipt_id, 'at': at, 'reservation_id': reservation_id, 'source': 'external_audible_receipt',
               'text': text, 'audio_hash': audio_hash.lower(), 'seconds': seconds}
        with self._tx() as db:
            old = self._get(db, 's2_receipts', receipt_id)
            if old:
                if any(old.get(k) != row[k] for k in ('reservation_id', 'text', 'audio_hash', 'seconds')):
                    raise System2Conflict('Receipt ID describes different audio.')
                return {'changed': False, 'receipt': old}
            fingerprints = ['t:' + text_hash(text)] + (['a:' + audio_hash.lower()] if audio_hash else [])
            row['repeat_violation'] = bool(self._repeat_reason(db, {'fingerprints': fingerprints}, at, reservation_id))
            self._save(db, 's2_receipts', row, ('at', 'reservation_id'))
            self._heard(db, fingerprints, at, reservation_id, receipt_id)
            return {'changed': True, 'receipt': row}

    def ack(self, reservation_id, owner, receipt_id, *, token=None, line_id=None, completed=False, audible=True, at=None):
        _name(receipt_id, 'receipt_id')
        line_id = str(line_id) if line_id is not None else None
        at = self.now() if at is None else _number(at, 'at', 0, self.now() + 5)
        if line_id is None and not completed: raise ValueError('A measured line or completed-performance receipt is required.')
        if line_id is not None and completed: raise ValueError('Use a separate full-performance completion receipt.')
        with self._tx() as db:
            row = self._owned(db, reservation_id, owner, token)
            if row['state'] not in ('playing', 'suspended', 'completed'): raise System2Conflict('Unpublished work cannot receive an audible receipt.')
            if at < row['dispatched_at']: raise ValueError('Receipt predates dispatch.')
            prior = self._get(db, 's2_receipts', receipt_id)
            if prior:
                if (prior.get('reservation_id'), prior.get('line_id'), prior.get('completed'), prior.get('audible')) != (reservation_id, line_id, bool(completed), bool(audible)):
                    raise System2Conflict('Receipt ID describes a different performance position.')
                return {'changed': False, 'reservation': row, 'receipt': prior}
            line = None
            if line_id is not None:
                line = next((l for l in row['candidate']['lines'] if l['id'] == str(line_id)), None)
                if line is None: raise ValueError('Unknown exact recorded line ID')
                line_id = str(line_id)
            duplicate = (line_id in row['heard_lines'] if line_id is not None else
                         row['state'] == 'completed' and (not audible or row['heard_seconds'] >= row['actual_seconds']))
            receipt = {'id': receipt_id, 'at': at, 'reservation_id': reservation_id, 'line_id': line_id,
                'completed': bool(completed), 'audible': bool(audible), 'duplicate_position': duplicate}
            fingerprints = (['t:' + text_hash(line['text'])] + (['a:' + line['audio_hash'].lower()] if line.get('audio_hash') else [])
                            if line else row['candidate']['fingerprints'])
            receipt['repeat_violation'] = bool(audible and not duplicate and self._repeat_reason(db, {'fingerprints': fingerprints}, at, reservation_id))
            before_heard, before_delivered = row['heard_seconds'], row['delivered_seconds']
            if not duplicate:
                if audible:
                    self._heard(db, fingerprints, at, reservation_id, receipt_id)
                    if line_id is not None:
                        row['heard_lines'].append(line_id)
                        row['heard_seconds'] = min(row['actual_seconds'], row['heard_seconds'] + float(line.get('seconds') or 0))
                if completed:
                    row.update(state='completed', completed_at=at, position_seconds=row['actual_seconds'], delivered_seconds=row['actual_seconds'])
                    if audible:
                        row['heard_seconds'] = row['actual_seconds']
                        row['heard_lines'] = [l['id'] for l in row['candidate']['lines']]
                row['receipts'].append(receipt_id)
            slot = self._get(db, 's2_slots', row['slot_id'])
            self._save(db, 's2_reservations', row, ('slot_id', 'candidate_id', 'state'))
            if slot and slot['revision'] == row['revision']:
                slot['heard_seconds'] += row['heard_seconds'] - before_heard
                slot['delivered_seconds'] += row['delivered_seconds'] - before_delivered
                self._slot_totals(db, slot)
                if (slot.get('heard_performances', 0) >= 1 if slot.get('coverage_mode') == 'one_performance'
                        else slot['heard_seconds'] >= slot['target_seconds']): slot['status'] = 'complete'
                self._save(db, 's2_slots', slot, ('hour_id', 'ordinal'))
            self._save(db, 's2_receipts', receipt, ('at', 'reservation_id'))
            self._save(db, 's2_reservations', row, ('slot_id', 'candidate_id', 'state'))
            return {'changed': not duplicate, 'reservation': row, 'receipt': receipt}

    def suspend(self, reservation_id, owner, *, position_seconds, reason, token=None, event_id=None):
        _name(reason, 'reason')
        with self._tx() as db:
            row = self._owned(db, reservation_id, owner, token)
            if row['state'] not in ('playing', 'suspended'): raise System2Conflict('Only dispatched work can be suspended.')
            _number(position_seconds, 'position_seconds', row['position_seconds'], row['actual_seconds'])
            row.update(state='suspended', position_seconds=position_seconds, suspended_at=self.now(),
                       suspension_reason=reason, interrupt_event_id=event_id)
            self._save(db, 's2_reservations', row, ('slot_id', 'candidate_id', 'state'))
            return row

    def resume(self, reservation_id, owner, *, token=None):
        with self._tx() as db:
            row = self._owned(db, reservation_id, owner, token)
            if row['state'] != 'suspended': raise System2Conflict('Only suspended work can resume.')
            reason = self._validate(db, row)
            if reason: return {'allowed': False, 'reason': reason, 'reservation': row}
            row.update(state='playing', resumed_at=self.now())
            self._save(db, 's2_reservations', row, ('slot_id', 'candidate_id', 'state'))
            return {'allowed': True, 'reason': '', 'seek_seconds': row['position_seconds'], 'reservation': row}

    def release(self, reservation_id, owner, *, token=None, reason='cancelled'):
        with self._tx() as db:
            row = self._owned(db, reservation_id, owner, token)
            if row['state'] in ('completed', 'released'): return {'changed': False, 'reservation': row}
            row.update(state='released', released_at=self.now(), release_reason=reason)
            self._save(db, 's2_reservations', row, ('slot_id', 'candidate_id', 'state'))
            return {'changed': True, 'reservation': row}

    def enqueue_event(self, kind, payload, *, request_id, deadline=None, due_at=None, priority=0):
        _name(kind, 'event kind'); _name(request_id, 'request_id')
        if not isinstance(payload, dict): raise ValueError('event payload must be an object')
        if isinstance(priority, bool) or not isinstance(priority, int) or not -100 <= priority <= 100: raise ValueError('event priority is out of range')
        requested_deadline = deadline
        deadline = self.now() + 3600 if deadline is None else _number(deadline, 'deadline')
        if requested_deadline is not None: requested_deadline = deadline
        requested_due = due_at
        due_at = self.now() if due_at is None else _number(due_at, 'due_at')
        if requested_due is not None: requested_due = due_at
        if due_at > deadline: raise ValueError('event due_at must not follow its deadline')
        fingerprint = _hash(_json([kind, payload, requested_deadline, requested_due, priority]))
        with self._tx() as db:
            saved = db.execute('SELECT body FROM s2_events WHERE request_id=?', (request_id,)).fetchone()
            if saved:
                row = json.loads(saved[0])
                if row['fingerprint'] != fingerprint: raise System2Conflict('Ingress request ID has different content.')
                return row
            row = {'id': uuid.uuid4().hex, 'request_id': request_id, 'kind': kind, 'payload': copy.deepcopy(payload),
                   'deadline': deadline, 'due_at': due_at, 'priority': priority, 'state': 'pending', 'received_at': self.now(), 'fingerprint': fingerprint}
            self._save(db, 's2_events', row, ('request_id', 'state', 'deadline', 'priority'))
            return row

    def claim_event(self, owner, *, lease_seconds=120, event_id=None):
        _name(owner, 'owner'); _number(lease_seconds, 'lease_seconds', 1, 3600)
        if event_id is not None: _name(event_id, 'event_id')
        with self._tx() as db:
            rows = db.execute("SELECT body FROM s2_events WHERE state IN ('pending','working') ORDER BY deadline,priority DESC,id").fetchall()
            for raw in rows:
                row = json.loads(raw[0])
                if row['deadline'] <= self.now():
                    row.update(state='expired', expired_at=self.now(), reason='Event deadline passed before completion')
                    self._save(db, 's2_events', row, ('request_id', 'state', 'deadline', 'priority'))
            for raw in rows:
                row = json.loads(raw[0])
                if row['deadline'] <= self.now(): continue
                if event_id is not None and row['id'] != event_id: continue
                if row.get('due_at', 0) > self.now(): continue
                if row['state'] == 'working' and row.get('lease_until', 0) > self.now(): continue
                row.update(state='working', owner=owner, token=uuid.uuid4().hex, lease_until=self.now() + lease_seconds)
                row['attempts'] = int(row.get('attempts') or 0) + 1
                self._save(db, 's2_events', row, ('request_id', 'state', 'deadline', 'priority'))
                return row
        return None

    def release_event(self, event_id, owner, token, *, reason='Not published', retry_after=0):
        _name(reason, 'reason'); _number(retry_after, 'retry_after', 0, 3600)
        with self._tx() as db:
            row = self._get(db, 's2_events', event_id)
            if not row or row.get('owner') != owner or row.get('token') != token:
                raise System2Conflict('Ingress ownership changed.')
            if row['state'] != 'working': return {'changed': False, 'event': row}
            row.update(state='pending' if row['deadline'] > self.now() + retry_after else 'expired',
                       released_at=self.now(), release_reason=reason, lease_until=0)
            row['due_at'] = max(row.get('due_at', 0), self.now() + retry_after)
            self._save(db, 's2_events', row, ('request_id', 'state', 'deadline', 'priority'))
            return {'changed': True, 'event': row}

    def finish_event(self, event_id, owner, token, *, result):
        if not isinstance(result, dict): raise ValueError('event result must be an object')
        with self._tx() as db:
            row = self._get(db, 's2_events', event_id)
            if not row or row.get('owner') != owner or row.get('token') != token: raise System2Conflict('Ingress ownership changed.')
            if row['state'] == 'completed': return row
            if row['state'] != 'working' or row['deadline'] <= self.now(): raise System2Conflict('Ingress event expired or is no longer working.')
            if row.get('lease_until', 0) <= self.now(): raise System2Conflict('Ingress lease expired.')
            row.update(state='completed', result=copy.deepcopy(result), completed_at=self.now())
            self._save(db, 's2_events', row, ('request_id', 'state', 'deadline', 'priority'))
            return row
