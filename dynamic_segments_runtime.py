"""Dynamic content at the station's existing preparation and air doors."""
from __future__ import annotations

import asyncio
import copy
import json
import math
import re
import uuid
import shutil
import time
from contextvars import ContextVar
from pathlib import Path
from threading import RLock
from typing import Any

import book_roulette
import dynamic_segments
import segment_prompts
from segment_contract import (book_time_bookends, build_segment_contract,
                              evaluate_segment_contract, estimated_speech_seconds)


class DynamicSegments:
    def __init__(self, g: dict[str, Any]):
        self.g = g
        self.path = Path(g['DATA_DIR']) / 'dynamic_segments_schedule.json'
        self.lock = RLock()
        self.admission = ContextVar('dynamic_stock_admission', default=None)
        self.original = {}
        self.busy = set()
        self.last = {}
        self.requests = {}
        self.coverage_cache = {}
        self.cast_cache = {}
        self.plans = []
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            for row in raw.get('plans', []):
                if isinstance(row, dict) and self.hour_epoch(row.get('effective_hour', '')) >= 0:
                    self.plans.append(row)
        except (OSError, ValueError, TypeError):
            pass

    def call(self, name, *args, default=None, **kw):
        fn = self.g.get(name)
        return fn(*args, **kw) if callable(fn) else default

    def log(self, message, error=''):
        self.call('pipeline_log', 'lookahead', message, extra=str(error)[:500])

    def hour_key(self, at=None):
        return time.strftime('%Y-%m-%dT%H', time.localtime(time.time() if at is None else at))

    def hour_epoch(self, key):
        try:
            return time.mktime(time.strptime(str(key), '%Y-%m-%dT%H'))
        except (ValueError, TypeError, OverflowError):
            return -1

    def plan_for(self, hour):
        matching = [row for row in self.plans if str(row.get('effective_hour') or '') <= str(hour)]
        return max(matching, key=lambda row: (str(row['effective_hour']), float(row.get('at') or 0))) if matching else None

    def sfx_air_overhead(self):
        explicit = self.call('dynamic_sfx_playback_overhead')
        if explicit is not None:
            return max(1.0, float(explicit))
        # Match System2's produced candidate air cost and final deadline guard.
        import os
        tail = max(0.0, float(os.getenv('BOX_TAIL_MS', '900'))) / 1000
        lead = max(0.0, float(self.g.get('VOICE_BROADCAST_LEAD_MS') or 0)) / 1000
        return tail + lead + 6.0

    def windows(self):
        rows = {}
        for kind in dynamic_segments.TEMPLATES:
            peek = segment_prompts.dial_preview(kind) or {}
            rows[kind] = peek.get('config') or dynamic_segments.template(kind)['config']
        book = max(300.0, min(600.0, float(rows['book_time'].get('target_seconds') or 390)))
        sfx = max(30.0, min(60.0, float(rows['sfx_supercut'].get('target_seconds') or 45)))
        # The preset controls actual source audio. Dispatch reserve absorbs
        # the existing guard and a bounded wait for the current clip to finish.
        sfx_wall = max(60.0, min(90.0, sfx + 30.0))
        book_starts = rows['book_time'].get('starts_at_minutes') or [15, 45]
        sfx_starts = rows['sfx_supercut'].get('starts_at_minutes') or [58]
        if len(book_starts) != 2 or len(sfx_starts) != 1:
            raise ValueError('Book Time needs two hourly starts; the supercut needs one')
        windows = [(float(at), book / 60.0, 'book_time') for at in book_starts]
        windows += [(float(at), sfx_wall / 60.0, 'sfx_supercut') for at in sfx_starts]
        dynamic_segments.overlay_hour([{'id': 'hour', 'kind': 'banter', 'minutes': 60}], windows)
        return windows

    def activate(self, enabled=True):
        now = time.time()
        current = self.hour_key(now)
        effective = self.hour_key(self.hour_epoch(current) + 3600.0 + 1)
        row = {'effective_hour': effective, 'enabled': bool(enabled),
               'windows': [list(window) for window in self.windows()], 'at': now}
        # Validate against a detached hour before committing a recurring plan.
        store = self.call('schedule_read', default={})
        original = self.original.get('schedule_hour_slots')
        if original:
            _preset, slots, _override = original(store, effective)
            dynamic_segments.overlay_hour(slots, row['windows'])
        with self.lock:
            self.plans.append(row)
            self.plans = sorted(self.plans, key=lambda item: (item['effective_hour'], item['at']))[-100:]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps({'plans': self.plans}, indent=1), encoding='utf-8')
            tmp.replace(self.path)
        for name in ('_INVENTORY_PLAN', '_COMMITS'):
            memo = self.g.get(name)
            if isinstance(memo, dict):
                memo['at'] = 0.0
        return {'ok': True, **row, 'preserved_current_hour': current,
                'schedule': self.schedule_view()}

    def schedule_view(self):
        current = self.hour_key()
        view = {'plans': copy.deepcopy(self.plans[-12:]), 'current_hour': current,
                'current': copy.deepcopy(self.plan_for(current)),
                'next': copy.deepcopy(self.plan_for(self.hour_key(self.hour_epoch(current) + 3601)))}
        try:
            view['windows'] = self.windows()
        except (ValueError, TypeError) as exc:
            view.update(windows=[], windows_error=str(exc))
        return view

    def source_entry(self, row):
        if not isinstance(row, dict):
            return {}
        return row.get('entry') if isinstance(row.get('entry'), dict) else row

    def occurrence(self, due=None):
        due = due or {}
        slot = due.get('slot') or due
        if due.get('dynamic_occurrence'):
            return str(due['dynamic_occurrence'])
        ident = str(due.get('slot_id') or slot.get('id') or '')
        at = float(due.get('due_at') or due.get('started') or 0)
        if ident and at:
            return f'{ident}@{int(at)}'
        return str(due.get('occurrence') or due.get('commit_id') or '')

    def active(self):
        radio = self.g.get('_RADIO') or {}
        slot = dict(radio.get('sched_slot') or {})
        pos = radio.get('sched_pos') or {}
        return {'kind': slot.get('kind'), 'slot': slot,
                'slot_id': slot.get('id'), 'due_at': pos.get('started'),
                'occurrence': pos.get('occurrence')}

    def inventory_match(self, due, item):
        entry = self.source_entry(item.get('row') or item.get('entry') or {})
        kind = str(due.get('kind') or '')
        stored = str(entry.get('dynamic_kind') or '')
        if entry.get('dynamic_handed_off') or entry.get('dynamic_superseded'):
            return False
        if kind in dynamic_segments.TEMPLATES:
            return stored == kind and str(entry.get('dynamic_occurrence') or '') == self.occurrence(due)
        return not stored

    def admission_matches(self, row, request=None):
        request = request if request is not None else self.admission.get()
        if request is None:
            return True
        entry = self.source_entry(row)
        stored = str(entry.get('dynamic_kind') or '')
        if request.get('named'):
            return True
        if entry.get('dynamic_handed_off') or entry.get('dynamic_superseded'):
            return False
        if request.get('kind') == 'book_time':
            return stored == 'book_time' and str(entry.get('dynamic_occurrence') or '') == self.occurrence(request)
        return not stored

    def book_rows(self, occurrence):
        return [row for row in list(self.g.get('_LARDER') or [])
                if self.source_entry(row).get('dynamic_kind') == 'book_time'
                and self.source_entry(row).get('dynamic_occurrence') == occurrence
                and not self.source_entry(row).get('dynamic_superseded')]

    @staticmethod
    def book_source_key(source):
        return json.dumps(source or {}, sort_keys=True, ensure_ascii=False, default=str)

    def book_authority(self, occurrence):
        """Earliest real persisted part owns the occurrence, including retained rejects."""
        candidates = []
        for index, row in enumerate(list(self.g.get('_LARDER') or [])):
            entry = self.source_entry(row)
            receipt = entry.get('book_roulette')
            if (entry.get('dynamic_kind') != 'book_time' or entry.get('dynamic_occurrence') != occurrence
                    or not isinstance(receipt, dict) or not isinstance(receipt.get('source'), dict)
                    or not isinstance(receipt.get('values'), dict)
                    or not (entry.get('script') or entry.get('script_plain') or entry.get('takes'))):
                continue
            source = receipt['source']
            if not source or self.book_source_key(entry.get('book_source') or source) != self.book_source_key(source):
                continue
            try:
                at = float(receipt.get('at') or entry.get('at') or 0) or float('inf')
            except (TypeError, ValueError):
                at = float('inf')
            candidates.append((at, index, entry))
        return min(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else {}

    def book_coherent_rows(self, occurrence, rows):
        authority = self.book_authority(occurrence)
        source = (authority.get('book_roulette') or {}).get('source')
        if not source and rows:
            source = self.source_entry(rows[0]).get('book_source') or {}
        expected = self.book_source_key(source)
        kept, errors = [], []
        for row in rows:
            entry = self.source_entry(row)
            actual = entry.get('book_source') or {}
            receipt = entry.get('book_roulette') or {}
            receipt_source = receipt.get('source') if isinstance(receipt, dict) else None
            if source and (self.book_source_key(actual) != expected or
                    (receipt_source and self.book_source_key(receipt_source) != expected)):
                errors.append({'id': str(entry.get('sid') or ''), 'why': 'Part source differs from the frozen occurrence',
                    'source': copy.deepcopy(actual)})
            else:
                kept.append(row)
        return kept, {'valid': not errors, 'source': copy.deepcopy(source or {}), 'errors': errors}

    def reject_book_source(self, row, canonical):
        entry = self.source_entry(row)
        entry.update(dynamic_superseded=True, dynamic_source_rejected={
            'why': 'Part source differs from the earliest persisted Book Time source',
            'canonical_source': copy.deepcopy(canonical), 'at': time.time()},
            handoff_unavailable={'why': 'Book Time source mismatch; retained for review', 'at': time.time()})

    def supply(self, row):
        entry = self.source_entry(row)
        takes = list(entry.get('takes') or [])
        ready = bool(self.original['dialogue_row_ready']('banter', row))
        script = str(entry.get('script') or entry.get('script_plain') or '')
        source = entry.get('book_source') or {}
        evidence = book_time_bookends(script, title=str(source.get('title') or ''),
                                     station=str(entry.get('book_station') or ''))
        for side in evidence.values():
            side['recorded'] = bool(side['written'] and ready)
        roles = [take.get('who') for take in takes]
        if not roles:
            roles = ['dj' if marker == 'A' else 'cohost' if marker == 'B' else marker
                     for marker, _text in self.call('banter_turns', script, default=[])]
        seconds = sum(float(take.get('seconds') or 0) for take in takes) if ready else 0.0
        return {'scripted_seconds': estimated_speech_seconds(script),
                'recorded_seconds': seconds, 'playable_seconds': seconds,
                'roles': roles, 'turns': len(self.call('banter_turns', script, default=[])),
                'events': max(1, len(takes)), 'bookends': evidence}

    def host_cast(self, row=None):
        entry = self.source_entry(row or {})
        saved = entry.get('book_cast') or {}
        stamp = entry.get('system3') or {}
        names = stamp.get('names') or (stamp.get('inputs') or {}).get('names') or {}
        cid = str(stamp.get('conversation_id') or '')
        if cid and not (names.get('A') and names.get('B')):
            names = self.cast_cache.get(cid) or {}
            if not names:
                try:
                    owner = self.call('_system3')
                    conv = (getattr(owner, 'recent', {}) or {}).get(cid)
                    if not conv and getattr(owner, 'store', None):
                        conv = owner.store.conversation(cid, with_events=False)
                    names = ((conv or {}).get('inputs') or {}).get('names') or {}
                    if names.get('A') and names.get('B'):
                        self.cast_cache[cid] = dict(names)
                        if len(self.cast_cache) > 200:
                            self.cast_cache.pop(next(iter(self.cast_cache)))
                except Exception:
                    names = {}
        if names.get('A') and names.get('B'):
            return {seat: str(names[seat]) for seat in ('A', 'B')}
        if saved.get('A') and saved.get('B'):
            return {seat: str(saved[seat]) for seat in ('A', 'B')}
        dj = self.call('dj_settings', default={}) or {}
        return {seat: str(dj.get(key) or '').strip() for seat, key in
                (('A', 'host_name'), ('B', 'cohost_name')) if str(dj.get(key) or '').strip()}

    def introduction_error(self, row):
        cast = self.host_cast(row)
        if not (cast.get('A') and cast.get('B')):
            return 'Opening cannot verify the actual A/B host identities'
        script = str(self.source_entry(row).get('script') or '')
        turns = self.call('banter_turns', script, default=[])
        own = {seat: False for seat in ('A', 'B')}
        for seat, text in turns:
            if seat not in own:
                continue
            normalized = ' '.join(str(text).replace('’', "'").split()).casefold()
            for claimed_seat, name in cast.items():
                pattern = (r"\b(?:i(?:'m| am)|my name is|this is|it(?:'s| is))\s+"
                           + re.escape(name.casefold()) + r"(?!\w)|(?<!\w)"
                           + re.escape(name.casefold()) + r"\s+(?:here|at the mic|speaking)\b")
                if re.search(pattern, normalized):
                    if claimed_seat != seat:
                        return f'{seat} introduces the wrong host; its actual actor is {cast[seat]}'
                    own[seat] = True
        missing = [cast[seat] for seat in ('A', 'B') if not own[seat]]
        return 'Both hosts must introduce themselves in their own roles: ' + ', '.join(missing) if missing else ''

    @staticmethod
    def quote_normal(text):
        return ' '.join(str(text or '').replace('“', '"').replace('”', '"')
                        .replace('’', "'").replace('‘', "'").split()).casefold().strip('"')

    def quote_evidence(self, rows):
        matches = []
        for row in rows:
            entry = self.source_entry(row)
            receipt = entry.get('book_roulette') or {}
            values = receipt.get('values') or {}
            candidates = [values.get('booksentence'), values.get('booksentences')]
            for field in ('booksentences', 'booksegment'):
                candidates += [text for text in book_roulette._split(str(values.get(field) or ''))
                    if book_roulette._complete(text) and 2 <= book_roulette._words(text) <= book_roulette.MAX_QUOTE_WORDS]
            texts = self.call('banter_turns', str(entry.get('script') or ''), default=[])
            spoken = self.quote_normal(' '.join(text for _seat, text in texts))
            for candidate in candidates:
                normalized = self.quote_normal(candidate)
                if not normalized or not 2 <= len(normalized.split()) <= book_roulette.MAX_QUOTES_WORDS:
                    continue
                if re.search(r'(?<!\w)' + re.escape(normalized) + r'(?!\w)', spoken):
                    matches.append({'id': str(entry.get('sid') or ''), 'text': str(candidate),
                        'recorded': bool(self.original['dialogue_row_ready']('banter', row)),
                        'source': copy.deepcopy(receipt.get('source') or entry.get('book_source') or {})})
                    break
        return {'written': bool(matches), 'recorded': any(item['recorded'] for item in matches), 'matches': matches}

    def phase_error(self, row, prior=()):
        entry = self.source_entry(row)
        script = str(entry.get('script') or entry.get('script_plain') or '')
        words = ' '.join(re.sub(r'[^\w\s]', ' ', script.casefold()).split())
        intro = len(re.findall(r'\bwelcome\b.{0,80}?\bbook time\b', words))
        outro = len(re.findall(r'(?:\b(?:thank|thanks|thank you)\b.{0,100}?\bbook time\b|'
            r'\b(?:that ends|that wraps|that s|that is|end of)\b.{0,70}?\bbook time\b)', words))
        evidence = book_time_bookends(script, title=str((entry.get('book_source') or {}).get('title') or ''),
                                     station=str(entry.get('book_station') or ''))
        phase = entry.get('book_phase')
        if phase == 'opening':
            # [book-opening] The brief asks BOTH hosts to welcome the listener, and
            # they do: host, then co-host. Counting that as a fault (intro != 1)
            # turned away 26 of 27 written openings on 10-05 and blocked every
            # episode. One welcome per episode is kept below, by `prior`.
            if intro < 1 or not evidence['intro']['written'] or outro:
                return 'Opening must welcome listeners to Book Time by title and station, and must not close'
            identity_error = self.introduction_error(row)
            if identity_error:
                return identity_error
            if any(book_time_bookends(str(self.source_entry(x).get('script') or ''))['intro']['written'] for x in prior):
                return 'The episode already has its one welcome'
        elif phase == 'closing':
            if intro or outro != 1 or not evidence['outro']['written']:
                return 'Closing must contain one actual Book Time sign-off and no welcome'
            if any(book_time_bookends(str(self.source_entry(x).get('script') or ''))['outro']['written'] for x in prior):
                return 'The episode already has its one closing'
        elif phase == 'discussion':
            if intro or outro:
                return 'Discussion must not welcome listeners or close Book Time'
        else:
            return 'The book part has no valid opening, discussion or closing phase'
        return ''

    def book_structure(self, rows):
        valid, errors = [], []
        for row in rows:
            why = self.phase_error(row, valid)
            if why:
                errors.append({'id': str(self.source_entry(row).get('sid') or ''), 'why': why})
            else:
                valid.append(row)
        opening = sum(self.source_entry(row).get('book_phase') == 'opening' for row in valid)
        closing = sum(self.source_entry(row).get('book_phase') == 'closing' for row in valid)
        return valid, {'valid': not errors, 'complete': not errors and opening == 1 and closing == 1,
                       'opening_count': opening, 'closing_count': closing, 'errors': errors}

    def reject_phase(self, row, why):
        entry = self.source_entry(row)
        entry.update(dynamic_superseded=True, dynamic_phase_rejected={'why': why,
            'phase': entry.get('book_phase'), 'at': time.time()},
            handoff_unavailable={'why': 'Book Time phase rejected: ' + why, 'at': time.time()})
        entry.setdefault('dynamic_rejection_id', str(entry.get('sid') or '') or uuid.uuid4().hex)
        # [book-opening] every refusal is in the one ledger, where it can be seen
        ledger = self.g.get('FLOW_LEDGER')
        if ledger is not None:
            try:
                ledger.note('round:book_phase', str(entry.get('book_phase') or '') + ': ' + str(why), passed=False,
                            road='banter', text=str(entry.get('script') or entry.get('script_plain') or ''),
                            ref=str(entry.get('sid') or entry.get('dynamic_rejection_id') or ''))
            except Exception:   # noqa: BLE001 - a ledger that cannot write never stops the episode
                pass

    def readmit_phases(self, occurrence, rows):
        """[book-opening] A SECOND LOOK AT WHAT AN EARLIER RULE TURNED AWAY.

        A part stays on the shelf when it is turned away, and three of them
        block the occurrence. When the rule that turned them away changes,
        those parts are still there and still good, and the occurrence is
        still blocked - until the next hour writes a new one. So each retained
        part of this occurrence is read again under the rule as it stands. One
        that passes goes back into its episode; the other attempts at the same
        phase are marked as answered by it, which is what unblocks the
        occurrence. A part that still fails stays exactly as it was.
        Returns how many came back."""
        back = 0
        for row in list(self.g.get('_LARDER') or []):
            entry = self.source_entry(row)
            verdict = entry.get('dynamic_phase_rejected')
            if (entry.get('dynamic_kind') != 'book_time' or entry.get('dynamic_occurrence') != occurrence
                    or not isinstance(verdict, dict) or entry.get('phase_repaired_by')
                    or entry.get('dynamic_handed_off') or entry.get('dynamic_source_rejected')):
                continue
            if self.phase_error(row, rows):
                continue
            entry.pop('dynamic_phase_rejected', None)
            entry.pop('dynamic_superseded', None)
            held = entry.get('handoff_unavailable')
            if isinstance(held, dict) and str(held.get('why') or '').startswith('Book Time phase rejected:'):
                entry.pop('handoff_unavailable', None)
            entry['phase_readmitted'] = {'was': str(verdict.get('why') or ''), 'at': time.time()}
            rows.append(row)
            back += 1
            answered_by = str(entry.get('sid') or '') or str(entry.get('dynamic_rejection_id') or '') or uuid.uuid4().hex
            for other in list(self.g.get('_LARDER') or []):
                bad = self.source_entry(other)
                if (bad is not entry and bad.get('dynamic_occurrence') == occurrence
                        and isinstance(bad.get('dynamic_phase_rejected'), dict)
                        and bad.get('book_phase') == entry.get('book_phase') and not bad.get('phase_repaired_by')):
                    bad['phase_repaired_by'] = answered_by
            self.log('Book Time took back a part an earlier rule turned away',
                     str(entry.get('book_phase') or '') + ': ' + str(verdict.get('why') or ''))
        return back

    def content_budget(self, due):
        slot = due.get('slot') or {}
        wall = float(slot.get('minutes') or float(due.get('owns_seconds') or 450) / 60) * 60
        internal = slot.get('dynamic_config') or {}
        value = due.get('content_budget_seconds', internal.get('content_budget_seconds'))
        helper = self.g.get('dynamic_book_content_budget')
        if callable(helper):
            supplied = helper(due)
            if isinstance(supplied, dict):
                value = supplied.get('content_budget_seconds', value)
            elif supplied is not None:
                value = supplied
        body = wall if value is None else max(0.0, min(wall, float(value)))
        return {'wall_target_seconds': wall, 'content_budget_seconds': body,
                'reserved_overhead_seconds': max(0.0, wall - body)}

    def book_coverage(self, due, rows=None):
        slot = dict(due.get('slot') or {})
        budget = self.content_budget(due)
        slot.update(kind='book_time', road='banter', owns_seconds=budget['content_budget_seconds'])
        contract = build_segment_contract(slot)
        rows = self.book_rows(self.occurrence(due)) if rows is None else rows
        signature = tuple((id(row), row.get('made'), row.get('chunks'), row.get('partial'),
            hash(str(row.get('script') or row.get('script_plain') or '')), row.get('book_phase'), row.get('dynamic_superseded'),
            tuple((take.get('key'), take.get('seconds'), take.get('who')) for take in row.get('takes', [])))
            for row in rows)
        key = (self.occurrence(due), budget['content_budget_seconds'], signature)
        cached = self.coverage_cache.get(key)
        if cached and time.time() - cached[0] < 3:
            return copy.deepcopy(cached[1])
        coherent_rows, coherence = self.book_coherent_rows(self.occurrence(due), rows)
        valid_rows, structure = self.book_structure(coherent_rows)
        coverage = {**evaluate_segment_contract(contract, [self.supply(row) for row in valid_rows]), **budget}
        coverage['book_structure'] = structure
        coverage['book_source_coherence'] = coherence
        coverage['book_quote'] = self.quote_evidence(valid_rows)
        coverage['discussion_source_allowed'] = all(book_roulette.discussion_source_allowed(
            self.source_entry(row).get('book_source') or {}) for row in rows)
        coverage['overlong_seconds'] = max(0.0, coverage['playable_seconds'] - budget['content_budget_seconds'])
        coverage['fits_content_budget'] = coverage['overlong_seconds'] <= .5
        coverage['ready'] = bool(coverage['ready'] and coverage['fits_content_budget'] and structure['complete']
            and coverage['book_quote']['recorded'] and coverage['discussion_source_allowed'] and coherence['valid'])
        self.coverage_cache[key] = (time.time(), copy.deepcopy(coverage))
        if len(self.coverage_cache) > 240:
            self.coverage_cache.pop(next(iter(self.coverage_cache)))
        return coverage

    async def prepare_book(self, due):
        occurrence = self.occurrence(due)
        if not occurrence or occurrence in self.busy:
            return False
        writing = self.g.setdefault('_LARDER_WRITING', [False])
        if writing[0]:
            return False
        self.busy.add(occurrence)
        writing[0] = True
        old_brief = self.call('alt_brief_now', default='')
        context_var = self.g.get('book_prompt_context')
        context_token = None
        build_var = self.g.get('_SEGMENT_BUILD_CONTEXT')
        build_token = None
        try:
            slot = dict(due.get('slot') or {})
            slot.setdefault('id', str(due.get('slot_id') or ''))
            slot.update(kind='book_time', label='Book Time')
            key = segment_prompts.memo_key('book_time', slot['id'], occurrence)
            seed = str(dynamic_segments.BOOK_TIME['text'])
            resolver = self.call('book_resolver')
            if resolver is None:
                raise RuntimeError('the book source resolver is unavailable')
            authority = self.book_authority(occurrence)
            result = copy.deepcopy(authority.get('book_roulette') or {})
            all_parts = [row for row in list(self.g.get('_LARDER') or [])
                if self.source_entry(row).get('dynamic_kind') == 'book_time'
                and self.source_entry(row).get('dynamic_occurrence') == occurrence]
            if result:
                restore = getattr(resolver, 'restore_receipt', None)
                if callable(restore):
                    result = await asyncio.to_thread(restore, key, result)
                # A fulfilled transport body is immutable, even if older state
                # files need their receipt restored for provenance.
                if any(self.source_entry(row).get('dynamic_handed_off') for row in all_parts):
                    return False
                held = segment_prompts.occurrence_view('book_time', key) or {}
                if held.get('book_source') and self.book_source_key(held['book_source']) != self.book_source_key(result['source']):
                    segment_prompts._MEMO.pop(key, None)  # this unfulfilled occurrence only
                if context_var:
                    context_token = context_var.set({'kind': 'book_time', 'occurrence': key,
                        'config': copy.deepcopy(authority.get('book_config') or {}), 'book_roulette': result})
                active, coherence = self.book_coherent_rows(occurrence, self.book_rows(occurrence))
                if not coherence['valid']:
                    active_ids = {id(row) for row in active}
                    for row in self.book_rows(occurrence):
                        if id(row) not in active_ids:
                            self.reject_book_source(row, result['source'])
                    self.call('_larder_save')
                    self.coverage_cache.clear()
            # The potentially cold source extraction is kept off the air loop.
            words = await asyncio.to_thread(segment_prompts.govern, 'book_time', seed, key)
            chosen = segment_prompts.occurrence_view('book_time', key) or {}
            config = chosen.get('config') or dynamic_segments.template('book_time')['config']
            runtime = self.g.get('BOOK_PROMPT_RUNTIME')
            if not result:
                result = await resolver.resolve_async(words, occurrence=key, scheduled=True,
                    booktime=True, weighted=getattr(runtime, 'weighted', None),
                    binding=str(config.get('book_binding') or ''), context={'stationname': self.station()})
            else:
                config = {**config, 'book_binding': result['source'].get('book_id') or ''}
            if not result.get('source'):
                raise RuntimeError('there is no readable library source for this segment')
            frozen = [self.source_entry(row).get('book_source') or {} for row in self.book_rows(occurrence)]
            if not all(book_roulette.discussion_source_allowed(source) for source in frozen + [result['source']]):
                self.last[occurrence] = {'state': 'deferred', 'why': 'Frozen source is an index, contents or other reference section; it stays preserved for review',
                    'source': result['source'], 'coverage': self.book_coverage(due)}
                return False
            # Keep source placeholders until the final model-wire expansion.
            # Exact book text can contain other station command braces.
            selected = next((row for row in (segment_prompts.entry('book_time') or {}).get('alternatives', [])
                             if row.get('id') == chosen.get('alt')), None)
            fields = {'system': str(chosen.get('system_prompt') or (selected or {}).get('text') or seed),
                'generation': str(chosen.get('generation_prompt') or (selected or {}).get('generation_prompt') or '')}
            if chosen.get('book_source'):
                # A host with an early book hook must not expose its inserted
                # source to later station command processors.
                fields = {'system': str((selected or {}).get('text') or seed),
                          'generation': str((selected or {}).get('generation_prompt') or '')}
            words = fields['system'] + '\n\nGENERATION PROMPT:\n' + fields['generation']
            context = {'kind': 'book_time', 'occurrence': key, 'config': config, 'book_roulette': result,
                       'book_prompts': fields, 'book_cast': self.host_cast()}
            if context_var:
                if context_token is None:
                    context_token = context_var.set(context)
                else:
                    context_var.set(context)
            rows = self.book_rows(occurrence)
            if any(row.get('dynamic_handed_off') for row in rows):
                return False  # once transport owns the episode, its body stays frozen
            kept = []
            for row in rows:
                why = self.phase_error(row, kept)
                if why:
                    self.reject_phase(row, why)
                else:
                    kept.append(row)
            if len(kept) != len(rows):
                self.call('_larder_save')
                self.coverage_cache.clear()
            rows = kept
            if self.readmit_phases(occurrence, rows):      # [book-opening] a second look
                self.call('_larder_save')
                self.coverage_cache.clear()
                rows = self.book_rows(occurrence)
            rejected = [self.source_entry(row) for row in self.g.get('_LARDER', [])
                if self.source_entry(row).get('dynamic_occurrence') == occurrence
                and self.source_entry(row).get('dynamic_phase_rejected')]
            phase_retry = next((row for row in rejected if not row.get('phase_repaired_by')), None)
            if phase_retry and sum(row.get('book_phase') == phase_retry.get('book_phase') for row in rejected) >= 3:
                self.last[occurrence] = {'state': 'blocked', 'why': 'Book Time phase failed after three bounded attempts',
                    'phase': phase_retry.get('book_phase'), 'coverage': self.book_coverage(due, rows)}
                return False
            # Retry retained tint/voice work before asking the writer for more
            # words. A failed engine visit must not create an infill loop.
            prepare_existing = self.g.get('larder_prepare')
            ready = self.original.get('dialogue_row_ready')
            tint = self.g.get('dialogue_tint_ready')
            pending = next((row for row in rows if (ready and not ready('banter', row))
                or (callable(tint) and not tint('banter', row))), None)
            if pending is not None and callable(prepare_existing):
                saved = self.source_entry(pending)
                retry_context = {'kind': 'book_time', 'occurrence': saved.get('book_prompt_occurrence') or key,
                    'config': saved.get('book_config') or config,
                    'book_roulette': saved.get('book_roulette') or result,
                    'book_prompts': saved.get('book_prompts') or fields, 'book_phase': saved.get('book_phase'),
                    'book_cast': self.host_cast(saved)}
                retry_token = context_var.set(retry_context) if context_var else None
                try:
                    changed = bool(await prepare_existing(pending))
                finally:
                    if context_var and retry_token is not None:
                        context_var.reset(retry_token)
                self.coverage_cache.clear()
                self.last[occurrence] = {**self.last.get(occurrence, {}), 'state': 'recording' if changed else 'waiting',
                    'source': retry_context['book_roulette']['source'], 'coverage': self.book_coverage(due, rows)}
                return changed
            coverage = self.book_coverage(due, rows)
            if coverage['ready']:
                return False
            supplies = [self.supply(row) for row in rows]
            prepared = sum(item['scripted_seconds'] for item in supplies)
            target = self.content_budget(due)['content_budget_seconds']
            all_recorded = bool(rows) and all(item['recorded_seconds'] > 0 for item in supplies)
            covered = sum(item['recorded_seconds'] for item in supplies) if all_recorded else prepared
            remainder = max(0.0, target - covered)
            has_intro = any(self.supply(row)['bookends']['intro']['written'] for row in rows)
            has_outro = any(self.supply(row)['bookends']['outro']['written'] for row in rows)
            replace = None
            quote_repair = False
            prior_repairs = [self.source_entry(row) for row in self.g.get('_LARDER', [])
                if self.source_entry(row).get('dynamic_occurrence') == occurrence
                and self.source_entry(row).get('book_repair_accepted')]
            quotation_repairs = max(int(self.last.get(occurrence, {}).get('quotation_repairs') or 0),
                sum(row.get('book_repair_type') == 'quotation' for row in prior_repairs))
            repairs = max(int(self.last.get(occurrence, {}).get('duration_repairs') or 0),
                sum(row.get('book_repair_type') == 'duration' for row in prior_repairs))
            if phase_retry:
                phase = str(phase_retry.get('book_phase') or 'discussion')
                chunk = min(135.0, max(60.0, estimated_speech_seconds(str(phase_retry.get('script') or ''))))
            elif (all_recorded and covered >= target - .5 and coverage.get('overlong_seconds', 0) <= .5
                    and coverage['book_structure']['complete'] and not coverage['book_quote']['written']):
                candidates = [row for row in rows if row.get('book_phase') == 'discussion']
                if not candidates or quotation_repairs >= 3:
                    self.last[occurrence] = {'state': 'blocked', 'why': 'The completed discussion has no exact bound source quotation',
                        'quotation_repairs': quotation_repairs, 'coverage': coverage}
                    return False
                replace = max(candidates, key=lambda row: self.supply(row)['recorded_seconds'])
                chunk = min(135.0, max(30.0, self.supply(replace)['recorded_seconds']))
                phase, quote_repair = 'discussion', True
            elif all_recorded and coverage.get('overlong_seconds', 0) > .5:
                candidates = [row for row in rows if row.get('book_phase') == 'discussion']
                if not candidates or repairs >= 2:
                    self.last[occurrence] = {'state': 'blocked', 'duration_repairs': repairs,
                        'why': 'Measured audio exceeds the wall budget after bounded duration repairs', 'coverage': coverage}
                    return False
                replace = max(candidates, key=lambda row: self.supply(row)['recorded_seconds'])
                chunk = max(30.0, self.supply(replace)['recorded_seconds'] - coverage['overlong_seconds'] - .5)
                phase = 'discussion'
            else:
                # Short measured takes earn discussion before the frozen closing.
                phase = 'opening' if not has_intro else 'discussion' if has_outro else 'closing' if remainder <= 135 else 'discussion'
                chunk = min(135.0, max(60.0, remainder))
            phase_words = {'opening': 'This is the OPENING only. Both hosts introduce themselves and welcome listeners to Book Time. Name the title and chapter. Begin discussion and leave it open; do not close or thank listeners yet.',
                'discussion': 'Continue the SAME title and passage. Answer the last exchange below, advance its argument, and use a brief exact quote. Do not introduce yourselves, welcome listeners or close Book Time.',
                'closing': 'This is the FINAL CLOSING round. Finish the discussion, give both hosts a takeaway, thank listeners explicitly for Book Time on {stationname}, and hand back to the music. Do not repeat the welcome.'}[phase]
            if phase == 'opening':
                cast = self.host_cast(phase_retry) if phase_retry else self.host_cast()
                phase_words += ' Actor identity: A is ' + cast.get('A', 'the actual host') + '; B is ' + cast.get('B', 'the actual co-host') + '. Each must introduce their own name in their own turn; never swap the names.'
            if not coverage['book_quote']['written'] and phase in ('discussion', 'closing'):
                phase_words += ' Read the entire exact bounded {booksentence} once, attributed to the selected book; keep its quoted words intact.'
            if quote_repair:
                phase_words += ' The completed episode is missing its source quote. Read the entire exact bounded {booksentence}, attributed to this book, and discuss its words without paraphrasing the quoted portion.'
            prior_rows = [row for row in rows if row.get('book_phase') != 'closing'] if has_outro else rows
            if replace is not None:
                prior_rows = prior_rows[:prior_rows.index(replace)] if replace in prior_rows else prior_rows
                phase_words += (f' Re-author this discussion as a {chunk:.0f} second source exchange.' if quote_repair else f' Re-author the overlong discussion as a concise {chunk:.0f} second exchange; preserve the same source and facts.')
            tail = self.call('segment_continuation_text', prior_rows[-1], default='') if prior_rows else ''
            marker = self.call('book_context_marker', 'book_time', key, config, default='')
            production = f'Write about {math.ceil(chunk * 170 / 60 * 1.08)} spoken words for this {chunk:.0f} second round.'
            if phase_retry:
                phase_words += ' Correct the rejected phase: ' + str(phase_retry['dynamic_phase_rejected']['why'])
            fields.update(phase=phase_words, continuation=tail, production=production)
            context['book_prompts'] = fields
            context['book_phase'] = phase
            context['book_cast'] = self.host_cast(phase_retry) if phase_retry else self.host_cast()
            if context_var:
                context_var.set(context)
            brief = marker + '\n' + words + '\n' + production + '\n' + tail + '\n' + phase_words
            self.call('alt_brief_set', brief)
            contract = self.call('segment_prepare_contract', 'banter', default={}) or {}
            contract.update(dynamic_kind='book_time', dynamic_occurrence=occurrence,
                book_source=result['source'], book_roulette=result, book_phase=phase,
                book_config=config, book_prompt_occurrence=key, book_prompts=fields, book_cast=context['book_cast'],
                book_station=self.station(), segment_subject=str(result['source'].get('title') or ''))
            if build_var:
                build_token = build_var.set(contract)
            new = []
            await self.g['dj_banter'](None, bank=True, bank_to=new, render_stream=True,
                angle=brief, own_material=True, road='banter', lines=max(8, math.ceil(chunk / 15)))
            accepted = []
            for row in new:
                self.tag(row, contract)
                why = self.phase_error(row, rows + accepted)
                if why:
                    self.reject_phase(row, why)
                else:
                    accepted.append(row)
                    if phase_retry:
                        row['phase_replaces'] = phase_retry['dynamic_rejection_id']
                        for bad in rejected:
                            if bad.get('book_phase') == phase_retry.get('book_phase') and not bad.get('phase_repaired_by'):
                                bad['phase_repaired_by'] = str(row.get('sid') or '') or uuid.uuid4().hex
                if replace is not None:
                    row['book_repair_type'] = 'quotation' if quote_repair else 'duration'
                    row['book_repair_accepted'] = row in accepted
                    row['chain_order'] = int(replace.get('chain_order') or 0)
                    row['duration_replaces'] = str(replace.get('sid') or '')
                self.g.setdefault('_LARDER', []).append(row)
            if accepted and replace is not None:
                replace['dynamic_superseded'] = True
                if quote_repair:
                    quotation_repairs += 1
                else:
                    repairs += 1
            if new:
                self.call('_larder_save')
                for name in ('_INVENTORY_PLAN', '_COMMITS'):
                    if isinstance(self.g.get(name), dict):
                        self.g[name]['at'] = 0
            self.last[occurrence] = {'state': 'prepared' if accepted else 'retrying' if new else 'waiting', 'phase': phase,
                'duration_repairs': repairs, 'quotation_repairs': quotation_repairs,
                'source': result['source'], 'coverage': self.book_coverage(due)}
            return bool(new)
        except Exception as exc:
            self.last[occurrence] = {'state': 'blocked', 'why': str(exc)[:300]}
            self.log('Book Time source preparation waits', exc)
            return False
        finally:
            self.call('alt_brief_set', old_brief)
            if build_var and build_token is not None:
                build_var.reset(build_token)
            if context_var and context_token is not None:
                context_var.reset(context_token)
            self.busy.discard(occurrence)
            writing[0] = False

    def station(self):
        runtime = self.g.get('BOOK_PROMPT_RUNTIME')
        if runtime and callable(getattr(runtime, 'station', None)):
            return str(runtime.station() or 'Pine Box FM')
        settings = self.call('dj_settings', default={}) or {}
        return str(settings.get('station_name') or settings.get('station') or 'Pine Box FM')

    def tag(self, row, contract):
        if not isinstance(row, dict) or contract.get('dynamic_kind') != 'book_time':
            return row
        for holder in (row, self.source_entry(row)):
            for key in ('dynamic_kind', 'dynamic_occurrence', 'book_source', 'book_roulette', 'book_config',
                        'book_prompt_occurrence', 'book_prompts', 'book_phase', 'book_station'):
                holder[key] = copy.deepcopy(contract.get(key))
            holder['reusable'] = False
            holder['book_cast'] = self.host_cast(holder)
        return row

    async def prepare_supercut(self, due):
        occurrence = self.occurrence(due)
        if not occurrence or occurrence in self.busy:
            return None
        held = next((row for row in self.g.get('_SHELF', {}).get('sfx_supercut', [])
                     if row.get('dynamic_occurrence') == occurrence), None)
        if held:
            return held
        self.busy.add(occurrence)
        try:
            slot = dict(due.get('slot') or {})
            campaigns = self.g.get('SUPERCUT_CAMPAIGNS')
            campaign = None
            if campaigns is not None:
                campaign_at = float(due.get('due_at') or slot.get('start') or
                    self.hour_epoch(str(due.get('hour') or self.hour_key())))
                campaign = await campaigns.ensure(campaign_at, occurrence=occurrence)
                if campaign and not campaign.get('script'):
                    self.last[occurrence] = {'state': 'waiting_for_script',
                        'why': campaign.get('why') or 'The hourly product script waits for the station writer',
                        'campaign_id': campaign['id']}
                    return None
            if campaign:
                slot['dynamic_config'] = copy.deepcopy(campaign['config'])
                slot['dynamic_config'].update(item=campaign['product'], sponsor=campaign['sponsor'],
                    station=campaign['station'], campaign=campaign, context=campaign['script'][:1200])
                words = str(campaign.get('resolved_system_prompt') or campaign['system_prompt']) + '\n' + str(campaign['script'])
            else:
                key = segment_prompts.memo_key('sfx_supercut', slot.get('id'), occurrence)
                words = await asyncio.to_thread(segment_prompts.govern, 'sfx_supercut', dynamic_segments.SFX_SUPERCUT['text'], key)
                chosen = segment_prompts.occurrence_view('sfx_supercut', key) or {}
                slot['dynamic_config'] = dict(chosen.get('config') or slot.get('dynamic_config') or dynamic_segments.SFX_SUPERCUT['config'])
            target = max(30.0, min(60.0, float(slot['dynamic_config'].get('target_seconds') or 45)))
            wall = float(slot.get('minutes') or 1) * 60
            slot['dynamic_config']['target_seconds'] = target
            prepared = await self.g['sfx_supercut_prepare'](slot, words, occurrence)
            if not prepared or not prepared.get('ok'):
                return None
            contract = build_segment_contract({'kind': 'sfx_supercut', 'owns_seconds': target})
            coverage = evaluate_segment_contract(contract, [{'playable_seconds': prepared.get('seconds'),
                'body_frames': prepared.get('body_frames'), 'sample_rate': prepared.get('sample_rate', 24000),
                'source_plan': prepared.get('source_plan')}])
            coverage.update(wall_target_seconds=wall, content_budget_seconds=target,
                reserved_overhead_seconds=max(0.0, wall - target),
                source_audio_seconds=coverage['playable_seconds'])
            if not coverage['ready']:
                raise ValueError('the source-only audio does not meet the complete segment contract')
            if coverage['playable_seconds'] + self.sfx_air_overhead() > wall + .01:
                raise ValueError('the source-only audio and its handoff guard exceed the scheduled wall window')
            destination = Path(self.g['PRODUCED_ADS_DIR']) / str(prepared['clip'])
            await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copy2, prepared['path'], destination)
            row = dict(prepared, audio=destination.name, dynamic_kind='sfx_supercut',
                dynamic_occurrence=occurrence, at=time.time(), product=slot['dynamic_config'].get('item') or 'Pine Box FM',
                text=str(prepared.get('recorded_text') or 'Pine Box FM station supercut'),
                system3={'mode': 'source_only', 'producer': 'sfx_supercut', 'source_plan': prepared.get('source_plan', {}).get('id')},
                coverage=coverage, sid='supercut-' + str(prepared.get('source_plan', {}).get('id') or occurrence))
            self.g.setdefault('_SHELF', {}).setdefault('sfx_supercut', []).append(row)
            self.call('_shelf_save')
            self.last[occurrence] = {'state': 'ready', 'coverage': coverage}
            return row
        except Exception as exc:
            self.last[occurrence] = {'state': 'blocked', 'why': str(exc)[:300]}
            self.log('The source-only supercut waits', exc)
            return None
        finally:
            self.busy.discard(occurrence)

    async def dispatch(self, kind, track=None, dj=None, occurrence=None):
        due = self.active()
        occurrence = occurrence or due.get('occurrence') or self.call('_schedule_dispatch_occurrence', default='')
        key = self.occurrence(due)
        if due.get('kind') != kind or not key:
            return False
        if kind == 'book_time':
            rows = self.book_rows(key)
            # The entire segment must be ready before the first part claims it.
            # Once accepted, remaining parts carry their frozen source and order.
            if not self.book_coverage(due, rows)['ready'] and not self.last.get(key, {}).get('started'):
                return False
            candidates = [row for row in rows if not row.get('dynamic_handed_off')]
            candidates.sort(key=lambda row: ({'opening': 0, 'discussion': 1, 'closing': 2}.get(row.get('book_phase'), 1),
                int(row.get('chain_order') or 0), float(row.get('at') or 0)))
            if not candidates:
                return True
            def accepted():
                candidates[0]['dynamic_handed_off'] = True
                self.last.setdefault(key, {})['started'] = True
            said = await self.g['_ready_shelf_air']('banter', track, pick=candidates[0], on_handoff=accepted)
            return bool(said)
        if kind == 'sfx_supercut':
            if not self.call('_schedule_action_pending', kind, occurrence, default=True):
                return True
            row = next((row for row in self.g.get('_SHELF', {}).get('sfx_supercut', [])
                        if row.get('dynamic_occurrence') == key), None)
            if not row:
                return False
            # Use the finished produced-audio admission/receipt door. Its source-
            # only guard skips newly written or synthesized response chapters.
            def accepted():
                self.call('_schedule_action_complete', kind, occurrence)
                row['dynamic_handed_off'] = True
            return bool(await self.g['_air_produced_ad'](row, on_handoff=accepted))
        return False

    def status(self):
        upcoming = self.call('coord_upcoming', 7200, measure=False, default=[]) or []
        pending = []
        for due in upcoming:
            kind = due.get('kind')
            if kind not in dynamic_segments.TEMPLATES:
                continue
            occurrence = self.occurrence(due)
            rows = self.book_rows(occurrence) if kind == 'book_time' else []
            source = self.source_entry(rows[0]).get('book_source') if rows else None
            pending.append({'kind': kind, 'occurrence': occurrence, 'due_at': due.get('due_at'),
                'slot_id': due.get('slot_id'), 'source': copy.deepcopy(source),
                'coverage': self.book_coverage(due, rows) if kind == 'book_time' else
                            copy.deepcopy(self.last.get(occurrence, {}).get('coverage')),
                'state': self.last.get(occurrence, {}).get('state', 'waiting'),
                'why': self.last.get(occurrence, {}).get('why', '')})
            if len(pending) >= 12:
                break
        mode = self.g.get('BOOK_MODE')
        return {'kinds': {kind: segment_prompts.entry_view(kind) for kind in dynamic_segments.TEMPLATES},
                'schedule': self.schedule_view(), 'active': self.active(), 'pending': pending,
                'requests': copy.deepcopy(self.requests),
                'availability': {'library_titles': len(getattr(mode, 'catalog', {}) or {}),
                                 'book_resolver': bool(self.g.get('book_resolver')),
                                 'source_supercut': bool(self.g.get('sfx_supercut_prepare'))},
                'preparation': copy.deepcopy(dict(list(self.last.items())[-20:])),
                'templates': {kind: dynamic_segments.template(kind) for kind in dynamic_segments.TEMPLATES}}

    async def worker(self):
        while True:
            try:
                demand = await asyncio.to_thread(self.call, 'schedule_demand_entries', 1.0, default=[])
                upcoming = await asyncio.to_thread(self.call, 'coord_upcoming', 3600, measure=False, default=[])
                for one in upcoming:
                    if one.get('kind') == 'sfx_supercut' and not any(self.occurrence(row) == self.occurrence(one) for row in demand):
                        demand.append(one)
                for due in demand:
                    if due.get('kind') == 'book_time' and self.requests.get('book_time'):
                        system2 = self.call('_system2')
                        if not getattr(system2, 'enabled', False) and not self.g.get('_LARDER_WRITING', [False])[0]:
                            await self.prepare_book(due)
                            break
                for due in demand:
                    if (not getattr(self.call('_system2'), 'enabled', False)
                            and due.get('kind') == 'book_time'
                            and float(due.get('starts_in', due.get('in_seconds', 0)) or 0) <= 1200):
                        rows = self.book_rows(self.occurrence(due))
                        if rows and all(self.original['dialogue_row_ready']('banter', row) for row in rows) and not self.book_coverage(due, rows)['ready']:
                            if not self.g.get('_LARDER_WRITING', [False])[0]:
                                await self.prepare_book(due)
                                break
                for due in demand:
                    if due.get('kind') == 'sfx_supercut' and float(due.get('starts_in') or 0) <= 1200:
                        await self.prepare_supercut(due)
                        break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.log('Dynamic segment preparation waits', exc)
            await asyncio.sleep(30)


def install(app, g):
    if g.get('DYNAMIC_SEGMENTS_RUNTIME'):
        return g['DYNAMIC_SEGMENTS_RUNTIME']
    runtime = DynamicSegments(g)
    g['DYNAMIC_SEGMENTS_RUNTIME'] = runtime
    g['dynamic_inventory_match'] = runtime.inventory_match
    g['dynamic_segment_dispatch'] = runtime.dispatch
    segment_prompts.install(g, g['DATA_DIR'])
    dynamic_segments.ensure_defaults(segment_prompts)
    for name in ('schedule_hour_slots', 'dialogue_row_ready', 'dj_banter', '_ready_shelf_air', 'alt_bank_banter', 'segment_chain_stamp', 'dialogue_stock_items', 'commitment_inventory_plan', 'ensure_entry_tinted'):
        if callable(g.get(name)):
            runtime.original[name] = g[name]
    if 'schedule_hour_slots' in runtime.original:
        def hour_slots(store=None, key='', when=None):
            preset, rows, override = runtime.original['schedule_hour_slots'](store, key, when)
            resolved_key = str(key or runtime.hour_key(when))
            plan = runtime.plan_for(resolved_key)
            if plan and plan.get('enabled'):
                rows = dynamic_segments.overlay_hour(rows, plan['windows'])
                return preset, rows, True
            return preset, rows, override
        g['schedule_hour_slots'] = hour_slots
    if 'dialogue_row_ready' in runtime.original:
        def ready(kind, row, *a, **kw):
            return runtime.admission_matches(row) and runtime.original['dialogue_row_ready'](kind, row, *a, **kw)
        g['dialogue_row_ready'] = ready
    for name in ('dj_banter', '_ready_shelf_air'):
        if name not in runtime.original:
            continue
        def wrap(original):
            async def air(*a, **kw):
                if kw.get('bank'):
                    return await original(*a, **kw)
                request = runtime.active()
                request['named'] = bool(kw.get('named'))
                token = runtime.admission.set(request)
                try:
                    return await original(*a, **kw)
                finally:
                    runtime.admission.reset(token)
            return air
        g[name] = wrap(runtime.original[name])
    if 'ensure_entry_tinted' in runtime.original:
        async def tinted(entry, kind, *a, **kw):
            result = await runtime.original['ensure_entry_tinted'](entry, kind, *a, **kw)
            if result and runtime.source_entry(entry).get('dynamic_kind') == 'book_time':
                why = runtime.phase_error(entry)
                if why:
                    runtime.reject_phase(entry, why)
                    runtime.coverage_cache.clear()
                    runtime.call('_larder_save')
                    return False
            return result
        g['ensure_entry_tinted'] = tinted
    if 'segment_chain_stamp' in runtime.original:
        def stamp(row, contract):
            result = runtime.original['segment_chain_stamp'](row, contract)
            return runtime.tag(result, contract)
        g['segment_chain_stamp'] = stamp
    if 'alt_bank_banter' in runtime.original:
        async def bank():
            inventory = await asyncio.to_thread(runtime.call, 'commitment_inventory_plan', fresh=True, default={})
            due = next((row for row in inventory.get('slots', []) if row.get('road') == 'banter'
                        and float(row.get('short_seconds') or 0) > 1), None)
            if due and due.get('kind') == 'book_time':
                return await runtime.prepare_book(due)
            return await runtime.original['alt_bank_banter']()
        g['alt_bank_banter'] = bank
    if 'dialogue_stock_items' in runtime.original:
        def stock(kind, *a, **kw):
            if kind != 'sfx_supercut':
                return runtime.original['dialogue_stock_items'](kind, *a, **kw)
            return [{'id': row.get('sid'), 'kind': kind, 'row': row, 'entry': row,
                     'ready': bool(row.get('coverage', {}).get('ready')),
                     'seconds': float(row.get('seconds') or 0), 'audio_seconds': float(row.get('seconds') or 0),
                     'projected_seconds': float(row.get('seconds') or 0), 'remaining_tasks': 0,
                     'lines': 0, 'ready_lines': 0, 'available': 0.0}
                    for row in g.get('_SHELF', {}).get(kind, []) if not row.get('dynamic_handed_off')]
        g['dialogue_stock_items'] = stock
    if 'commitment_inventory_plan' in runtime.original:
        def inventory(*a, **kw):
            result = runtime.original['commitment_inventory_plan'](*a, **kw)
            result = dict(result, slots=[dict(row) for row in result.get('slots', [])],
                          roads={kind: dict(row) for kind, row in result.get('roads', {}).items()})
            for due in result['slots']:
                if due.get('kind') != 'book_time':
                    continue
                coverage = runtime.book_coverage(due)
                due['book_coverage'] = coverage
                due['ready_seconds'] = min(float(due.get('owns_seconds') or 0), coverage['playable_seconds']) if coverage['ready'] else 0.0
                writing_owed = max(coverage['script_short_seconds'], coverage['writing_structure_short_seconds'])
                due['short_seconds'] = max(0.0, writing_owed)
                due['planned_seconds'] = max(0.0, float(due.get('owns_seconds') or 0) - writing_owed)
                due['recording_seconds'] = max(0.0, float(due.get('owns_seconds') or 0) - coverage['recorded_seconds'])
            for road, row in result['roads'].items():
                owned = [due for due in result['slots'] if due.get('road') == road]
                for key in ('owed_seconds', 'ready_seconds', 'planned_seconds', 'short_seconds'):
                    source = 'owns_seconds' if key == 'owed_seconds' else key
                    row[key] = round(sum(float(due.get(source) or 0) for due in owned), 1)
            for key in ('owed_seconds', 'ready_seconds', 'planned_seconds', 'short_seconds'):
                source = 'owns_seconds' if key == 'owed_seconds' else key
                result[key] = round(sum(float(due.get(source) or 0) for due in result['slots']), 1)
            return result
        g['commitment_inventory_plan'] = inventory
    from fastapi import Header, HTTPException, Request
    globals().update(Request=Request)
    @app.get('/api/dynamic-segments')
    async def status(authorization: str | None = Header(default=None)):
        g['require_read_auth'](authorization)
        return await asyncio.to_thread(runtime.status)
    @app.post('/api/dynamic-segments/activate')
    async def activate(request: Request, authorization: str | None = Header(default=None)):
        g['require_auth'](authorization)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, 'Expected an object')
        try:
            return await asyncio.to_thread(runtime.activate, bool(body.get('enabled', True)))
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
    @app.post('/api/dynamic-segments/{kind}/prepare')
    async def request_prepare(kind: str, request: Request, authorization: str | None = Header(default=None)):
        g['require_auth'](authorization)
        if kind not in dynamic_segments.TEMPLATES:
            raise HTTPException(404, 'unknown dynamic segment kind')
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, 'Expected an object')
        runtime.requests[kind] = {'requested_at': time.time(), 'state': 'queued',
                                  'occurrence': str(body.get('occurrence') or '')[:180]}
        enqueue = g.get('dynamic_system2_request_prepare')
        if callable(enqueue):
            result = enqueue(kind)
            if hasattr(result, '__await__'):
                result = await result
            runtime.requests[kind]['production'] = result
        for memo in (g.get('_INVENTORY_PLAN'), g.get('_COMMITS')):
            if isinstance(memo, dict):
                memo['at'] = 0
        return {'ok': True, 'kind': kind, 'state': 'queued',
                'request': copy.deepcopy(runtime.requests[kind])}
    @app.post('/api/dynamic-segments/{kind}/preview')
    async def preview(kind: str, request: Request, authorization: str | None = Header(default=None)):
        g['require_read_auth'](authorization)
        if kind not in dynamic_segments.TEMPLATES:
            raise HTTPException(404, 'unknown dynamic segment kind')
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, 'Expected an object')
        pair = await asyncio.to_thread(segment_prompts.expand_pair,
            str(body.get('text') or '')[:4000], str(body.get('generation_prompt') or '')[:4000],
            kind, key='preview', stamp=False, config=body.get('config'))
        if kind == 'book_time' or book_roulette.TOKEN.search(pair['text']):
            book_runtime = g.get('BOOK_PROMPT_RUNTIME')
            resolver = runtime.call('book_resolver')
            if resolver is None:
                raise HTTPException(409, 'The station book library has not started')
            config = pair['config']
            try:
                result = await resolver.resolve_async(pair['system_prompt'], pair['generation_prompt'],
                    weighted=book_runtime.preview_weighted, persist=False, scheduled=False,
                    binding=str(config.get('book_binding') or ''), booktime=kind == 'book_time',
                    context={'stationname': runtime.station()})
                station = runtime.station()
                for field in ('system_prompt', 'generation_prompt', 'text'):
                    # Resolve authored station tokens before inserting source.
                    # A book may literally print {stationname} in its quotation.
                    authored = re.sub(r'(?<!\{)\{stationname\}(?!\})', lambda _match: station, pair[field])
                    pair[field] = book_roulette.expand(authored, result, booktime=kind == 'book_time')
                pair.update(source=result.get('source'), rolls=result.get('rolls'))
            except Exception as exc:
                raise HTTPException(409, str(exc)[:300]) from exc
        return pair
    @app.on_event('startup')
    async def start():
        runtime.task = asyncio.create_task(runtime.worker(), name='dynamic-source-supercut')
    @app.on_event('shutdown')
    async def stop():
        task = getattr(runtime, 'task', None)
        if task:
            task.cancel()
    return runtime
