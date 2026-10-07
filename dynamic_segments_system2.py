"""Source-bound dynamic segments through System2's existing production and air doors.

Only the installed runtime instance is adapted. Its durable leases, reservations,
verified audio hashes and audible receipts continue to own scheduling debt.
"""
from __future__ import annotations
import asyncio
import copy
import hashlib
import json
import math
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
import system2_runtime
import handoff_preparation

KINDS = {'book_time': 'banter', 'sfx_supercut': 'ad'}
PHASES = {'opening': 0, 'discussion': 1, 'closing': 2}


def finite(value, default=0.0):
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError, OverflowError):
        return default


class DynamicSystem2:
    def __init__(self, runtime, dynamic):
        self.runtime, self.dynamic = runtime, dynamic
        self.original = {}
        self.requested = {}
        self.tasks = set()
        self.writer_ticket = None
        self.dispatch_task = None
        self.dispatch_stopping = False
        self.dispatch_lifecycle_registered = False

    def due(self, slot):
        template = str(slot.get('template_id') or slot.get('id') or '')
        kind = str(slot.get('dynamic_kind') or slot.get('slot_kind') or slot.get('kind') or '')
        wall = finite(slot.get('seconds'), finite(slot.get('minutes')) * 60)
        return {'kind': kind, 'slot_id': template, 'slot': {**copy.deepcopy(slot),
                'id': template, 'kind': kind, 'minutes': wall / 60},
                'due_at': finite(slot.get('start')), 'owns_seconds': wall,
                'road': KINDS.get(kind, kind), 'commit_id': str(slot.get('id') or '')}

    def budget(self, due):
        slot = due.get('slot') or {}
        wall = finite(slot.get('minutes')) * 60 or finite(due.get('owns_seconds'), 450)
        h = self.runtime.host
        beat = max(getattr(h, 'CONCAT_BEAT', (.07, .18)))
        lead = max(0.0, finite(getattr(h, 'VOICE_BROADCAST_LEAD_MS', 0))) / 1000
        tail = max(0.0, finite(os.getenv('BOX_TAIL_MS', '900'))) / 1000
        # Reserve for a 30-turn complete discussion; the final bundle is checked
        # again against its actual ordered take count, including every gap.
        expected_turns = max(30, math.ceil(wall / 15))
        if due.get('slot_id') and due.get('due_at'):
            rows = self.dynamic.book_rows(self.dynamic.occurrence(due))
            observed = sum(len(self.dynamic.source_entry(row).get('takes') or []) for row in rows)
            closing = any(self.dynamic.source_entry(row).get('book_phase') == 'closing' for row in rows)
            upcoming = 0 if closing else int(self.runtime.config.get('generation_turns') or 9)
            expected_turns = max(expected_turns, observed + upcoming)
        overhead = max(20.0, lead + tail + 5 + (expected_turns - 1) * beat)
        explicit = (slot.get('dynamic_config') or {}).get('content_budget_seconds')
        content = min(max(0.0, wall - overhead), finite(explicit, wall - overhead))
        return {'wall_target_seconds': wall, 'content_budget_seconds': content,
                'reserved_overhead_seconds': wall - content}

    def templates(self, hour):
        out = self.original['templates'](hour)
        for slot in out:
            kind = str(slot.get('slot_kind') or '')
            if kind in KINDS:
                slot.update(kind=KINDS[kind], dynamic_kind=kind,
                    require_slot_binding=True, coverage_mode='one_performance',
                    allocation_mode='automatic', preferred_candidate_id='')
        return out

    def source_key(self, entry):
        source = entry.get('book_source') or {}
        return str(source.get('id') or source.get('book_id') or source.get('key')
                   or source.get('path') or source.get('title') or '')

    @contextmanager
    def book_context(self, entry):
        variable = self.dynamic.g.get('book_prompt_context')
        receipt = entry.get('book_roulette')
        token = None
        if variable is not None and isinstance(receipt, dict) and receipt.get('source'):
            token = variable.set({'kind': 'book_time',
                'occurrence': str(entry.get('book_prompt_occurrence') or entry.get('dynamic_occurrence') or ''),
                'config': copy.deepcopy(entry.get('book_config') or {}), 'book_roulette': receipt,
                'book_prompts': copy.deepcopy(entry.get('book_prompts') or {}),
                'book_cast': copy.deepcopy(entry.get('book_cast') or {}),
                'book_phase': ('complete' if entry.get('_dynamic_bundle') and
                    (entry.get('coverage') or {}).get('ready') else entry.get('book_phase'))})
        try:
            yield
        finally:
            if token is not None:
                variable.reset(token)

    def book_bundle(self, due):
        occ = self.dynamic.occurrence(due)
        rows = self.dynamic.book_rows(occ)
        rows.sort(key=lambda row: (PHASES.get(self.dynamic.source_entry(row).get('book_phase'), 1),
            int(self.dynamic.source_entry(row).get('chain_order') or 0),
            finite(self.dynamic.source_entry(row).get('at'))))
        source_keys = {self.source_key(self.dynamic.source_entry(row)) for row in rows}
        source_receipts = {json.dumps(self.dynamic.source_entry(row).get('book_source') or {}, sort_keys=True, default=str) for row in rows}
        if not rows or len(source_keys) != 1 or len(source_receipts) != 1 or not next(iter(source_keys)):
            return None
        if any(self.dynamic.source_entry(row).get('dynamic_handed_off') for row in rows):
            return None
        entry = {'id': 'book-bundle-' + hashlib.sha256(occ.encode()).hexdigest()[:24],
            '_dynamic_bundle': True, 'dynamic_kind': 'book_time', 'dynamic_occurrence': occ,
            'book_source': copy.deepcopy(self.dynamic.source_entry(rows[0]).get('book_source')),
            'system2_slot': str(due.get('commit_id') or ''), 'dynamic_due': copy.deepcopy(due),
            'at': min(finite(self.dynamic.source_entry(row).get('at')) for row in rows),
            'reusable': False, 'ready': True}
        for field in ('book_roulette', 'book_config', 'book_prompt_occurrence', 'book_station', 'book_prompts', 'book_cast'):
            entry[field] = copy.deepcopy(self.dynamic.source_entry(rows[0]).get(field))
        return entry

    def resolve(self, kind, row):
        entry = self.dynamic.source_entry(row)
        dynamic_kind = str(entry.get('dynamic_kind') or '')
        if dynamic_kind not in KINDS:
            return self.original['resolve'](kind, row)
        result = {'ready': False, 'why': [], 'kind': str(kind), 'source_row': row,
                  'entry': copy.deepcopy(entry), 'takes': [], 'media_kind': 'round'}
        try:
            if entry.get('dynamic_handed_off'):
                raise ValueError('This exact dynamic occurrence has already been handed off')
            if dynamic_kind == 'book_time':
                if not entry.get('_dynamic_bundle'):
                    raise ValueError('Individual Book Time parts cannot fill generic conversation slots')
                due = entry['dynamic_due']
                fresh = self.book_bundle(due)
                if not fresh or fresh['book_source'] != entry['book_source']:
                    raise ValueError('The book source or occurrence changed')
                rows = self.dynamic.book_rows(entry['dynamic_occurrence'])
                rows.sort(key=lambda part: (PHASES.get(self.dynamic.source_entry(part).get('book_phase'), 1),
                    int(self.dynamic.source_entry(part).get('chain_order') or 0),
                    finite(self.dynamic.source_entry(part).get('at'))))
                coverage = self.dynamic.book_coverage(due, rows)
                if not coverage.get('ready'):
                    raise ValueError('The entire source-bound book discussion is not recorded and ready')
                takes, scripts, parts = [], [], []
                for part in rows:
                    with self.book_context(self.dynamic.source_entry(part)):
                        resolved = self.original['resolve']('banter', part)
                    if not resolved.get('ready') or not resolved.get('takes'):
                        raise ValueError('A required book part has no verified recording')
                    if (self.runtime.content_gate_enabled('tint') and
                            not self.runtime.host.dialogue_tint_ready('banter', part)):
                        raise ValueError('A required book part has incomplete tint')
                    parts.append(resolved['entry'])
                    scripts.append(str(resolved['entry'].get('script') or resolved['entry'].get('script_plain') or ''))
                    for take in resolved['takes']:
                        takes.append({**copy.deepcopy(take), 'i': len(takes),
                            'book_phase': self.dynamic.source_entry(part).get('book_phase')})
                seconds = sum(finite(take.get('seconds')) for take in takes)
                wall = self.budget(due)['wall_target_seconds']
                if seconds + self.overhead(len(takes)) > wall + .001:
                    raise ValueError('Complete book audio plus playback overhead exceeds its wall window')
                result['entry'].update(script='\n'.join(scripts), script_plain='\n'.join(scripts),
                    takes=copy.deepcopy(takes), coverage=copy.deepcopy(coverage),
                    lines=sum(len(self.runtime.host.banter_turns(script)) for script in scripts),
                    chunks=len(takes), made=len(takes), keys=[take['key'] for take in takes],
                    prepared=True, partial=False, frozen=True, render_stream=True, freshened=True)
                self.assemble_bindings(result['entry'], parts)
            else:
                plan = entry.get('source_plan') or {}
                if not entry.get('source_only') or not plan.get('source_only') or not plan.get('complete'):
                    raise ValueError('Supercut requires a complete source-only audio plan')
                if not (entry.get('coverage') or {}).get('ready'):
                    raise ValueError('Supercut source structure and measured duration are not ready')
                name = str(entry.get('audio') or '')
                if not name or Path(name).name != name:
                    raise ValueError('Supercut needs an owned produced-audio filename')
                proof = self.runtime.media.proof({'path': '/ads-audio/' + name})
                expected = finite(entry.get('body_frames')) / finite(entry.get('sample_rate'), 24000)
                if not expected or abs(proof['seconds'] - expected) > .02:
                    raise ValueError('Supercut measured frames do not match its current original audio')
                text = str(entry.get('recorded_text') or entry.get('text') or '')
                takes = [{'i': 0, 'text': text, 'who': 'drop', 'voice': 'source-clips',
                    'key': name, 'clip': {k: proof[k] for k in ('path', 'sig', 'seconds', 'bytes')}, **proof}]
                result['media_kind'] = 'produced'
                result['entry'].update(text=text, script=text)
            result.update(ready=True, takes=takes, seconds=sum(finite(x.get('seconds')) for x in takes))
        except Exception as exc:
            result['why'] = [str(exc)]
        return result

    def assemble_bindings(self, entry, parts):
        active = [part for part in parts if (part.get('system3') or {}).get('mode') == 'active']
        policy = self.dynamic.g.get('_s3_active')
        if not active:
            if callable(policy) and policy():
                raise ValueError('System3 is active and the book parts have no recorded roulette bindings')
            return
        if len(active) != len(parts):
            raise ValueError('A Book Time assembly cannot mix bound and unbound recorded conversations')
        ids, dice, sources, components, conversations, dropped = {}, {}, {}, [], [], []
        offset, planned = 0, 0
        finder = self.dynamic.g.get('system3_turn_id_for')
        for part in parts:
            stamp = part['system3']
            if not handoff_preparation.receipt_matches_script(part):
                raise ValueError('A book part lacks its reviewed final-script handoff receipt')
            n = len(self.runtime.host.banter_turns(str(part.get('script') or '')))
            original_ids = stamp.get('turns') or {}
            original_dice = part.get('turn_dice') or {}
            if callable(finder):
                for take in part.get('takes') or []:
                    with self.book_context(part):
                        tid = finder(part, take.get('text'), take.get('who'))
                    if not tid or str(tid) not in original_ids.values():
                        raise ValueError('Prepared book audio includes a take outside its original roulette binding')
            for key, tid in original_ids.items():
                index = int(key)
                if 0 <= index < n:
                    ids[str(offset+index)] = str(tid)
            for field, target in (('turn_dice', dice), ('turn_source', sources)):
                for key, value in (part.get(field) or {}).items():
                    index = int(key)
                    if 0 <= index < n:
                        target[str(offset+index)] = copy.deepcopy(value)
            conversations.append(str(stamp.get('conversation_id') or ''))
            dropped.extend(str(tid) for tid in (stamp.get('gate') or {}).get('dropped_ids') or [])
            planned += int(stamp.get('planned_turns') or n)
            components.append({'system3': copy.deepcopy(stamp),
                'handoff_receipt': copy.deepcopy(part['handoff_receipt']),
                'source_id': str(part.get('id') or part.get('sid') or ''), 'script_turn_offset': offset,
                'script_digest': handoff_preparation.text_digest(part.get('script'))})
            offset += n
        entry.update(turn_dice=dice, turn_source=sources,
            system3={'mode':'active', 'conversation_id': conversations[0],
                'conversation_ids': conversations, 'assembly':'ordered_recorded_parts',
                'assembly_id': entry['id'], 'turns': ids, 'planned_turns': planned,
                'gate': {'dropped_ids': dropped}}, system3_components=components)
        # This receipt proves lossless concatenation of already reviewed parts.
        # It neither invents a model review nor adds any conversation/turn IDs.
        entry['handoff_receipt'] = {'version':1, 'status':'ready', 'changed':False,
            'assembly':'ordered_recorded_parts', 'components':copy.deepcopy(components),
            'final_digest':handoff_preparation.text_digest(entry['script'])}
        withheld = self.dynamic.g.get('s3_binding_withheld')
        if callable(withheld):
            why = withheld(entry)
            if why:
                raise ValueError('The assembled original roulette bindings cannot pass the booth: '+str(why))

    def overhead(self, takes):
        h = self.runtime.host
        return (max(0, takes - 1) * max(getattr(h, 'CONCAT_BEAT', (.07, .18)))
            + max(0.0, finite(os.getenv('BOX_TAIL_MS', '900'))) / 1000 + 5
            + max(0.0, finite(getattr(h, 'VOICE_BROADCAST_LEAD_MS', 0))) / 1000)

    def repeat_materials(self, texts, entry):
        helper = self.dynamic.g.get('book_repeat_material')
        owner = getattr(helper, '__self__', None)
        validate = getattr(owner, '_validated_book', None)
        if (entry.get('dynamic_kind') != 'book_time' or not entry.get('_dynamic_bundle')
                or not (entry.get('coverage') or {}).get('ready')
                or not callable(helper) or not callable(validate)):
            return list(texts), False, False
        with self.book_context(entry):
            if not validate():
                return list(texts), False, False
            materials, exempt = [], False
            used = self.dynamic.g.get('norepeat_text_used')
            repeated = False
            for text in texts:
                filtered = str(helper(text) or '')
                exempt = exempt or filtered != str(text or '')
                if filtered.strip():
                    materials.append(filtered)
                    # A quote removed from a mixed line must not hide the
                    # opinion beside it from the station's sentence ledger.
                    sentences = re.split(r'(?<=[.!?])\s+', filtered.strip())
                    for sentence in sentences:
                        if sentence.strip():
                            materials.append(sentence)
                            if callable(used) and used(sentence):
                                repeated = True
            return list(dict.fromkeys(materials)), exempt, repeated

    def repeat_allowed(self, texts, entry=None):
        entry = entry or {}
        if isinstance(texts, str):
            texts = [texts]
        if entry.get('dynamic_kind') != 'book_time':
            return self.original['repeat_allowed'](texts, entry)
        materials, _exempt, repeated = self.repeat_materials(texts, entry)
        if repeated:
            self.runtime.host.pipeline_log('system2', 'Book Time waits: ordinary discussion has already been heard')
            return False
        with self.book_context(entry):
            return self.original['repeat_allowed'](materials, entry)

    def exact_source_slot(self, entry):
        kind = str(entry.get('dynamic_kind') or '')
        occurrence = str(entry.get('dynamic_occurrence') or '')
        plan_occurrence = str((entry.get('source_plan') or {}).get('occurrence') or '')
        if not occurrence or (plan_occurrence and plan_occurrence != occurrence):
            return None, 'The source plan and stock do not share an exact scheduled occurrence'
        matches = [slot for hour in self.runtime._plans for slot in hour.get('slots', [])
            if str(slot.get('dynamic_kind') or slot.get('slot_kind') or '') == kind
            and finite(slot.get('deadline')) > time.time()
            and self.dynamic.occurrence(self.due(slot)) == occurrence]
        if len(matches) != 1:
            return None, 'The source occurrence has no sole unexpired native System2 slot'
        slot = matches[0]
        prior = str(entry.get('system2_slot') or '')
        if prior and prior != str(slot['id']):
            return None, 'The stored source binding names another native occurrence'
        return slot, ''

    def candidate(self, kind, row, identity=None):
        entry = self.dynamic.source_entry(row)
        if entry.get('dynamic_kind') not in KINDS:
            return self.original['candidate'](kind, row, identity)
        resolved = self.resolve(kind, row)
        lines = [{**copy.deepcopy(take), 'id': str(index), 'audio': copy.deepcopy(take.get('clip') or {})}
                 for index, take in enumerate(resolved['takes'])]
        seconds = sum(finite(line.get('seconds')) for line in lines)
        dynamic_kind = entry['dynamic_kind']
        bound_slot, binding_error = self.exact_source_slot(entry)
        ready = bool(resolved['ready'] and bound_slot is not None)
        air = seconds + self.overhead(len(lines))
        identity = identity or str(entry.get('id') or entry.get('sid'))
        text = str(resolved['entry'].get('script') or resolved['entry'].get('text') or '')
        result = {'id': identity, 'kind': KINDS[dynamic_kind], 'seconds': seconds,
            'air_seconds': air, 'ready': ready, 'eligible': ready,
            'expires_at': 0, 'repeat_guard': self.runtime.content_gate_enabled('repetition'),
            'script': text, 'source_id': hashlib.sha256(text.encode()).hexdigest(),
            'lines': lines, 'audio_hashes': [x['audio_hash'] for x in lines if x.get('audio_hash')],
            'source': {key: copy.deepcopy(resolved['entry'].get(key)) for key in
                       ('dynamic_kind', 'dynamic_occurrence', 'book_source', 'coverage', 'source_plan', 'source_only')},
            'slot_id': str(bound_slot['id']) if bound_slot else '',
            'why': list(resolved['why']) + ([binding_error] if binding_error else []),
            'created_at': finite(entry.get('at'))}
        if resolved['ready'] and dynamic_kind == 'book_time' and result['repeat_guard']:
            materials, exempt, repeated = self.repeat_materials(
                [line.get('text') or '' for line in lines], resolved['entry'])
            verdict = self.runtime.store.can_play(materials)
            if repeated or not verdict['allowed']:
                result.update(eligible=False)
                result['why'].append('The remaining ordinary book discussion repeats heard material')
            elif exempt:
                # Exact occurrence binding plus attested full-source coverage
                # owns this one episode. Protocol and exact quotes may recur;
                # every nonexempt discussion sentence was independently checked.
                result['repeat_guard'] = False
                result['source']['repeat_policy'] = 'attested_book_protocol_and_exact_source_only'
        self.runtime._rows[identity] = (KINDS[dynamic_kind], row)
        return result

    def inventory(self):
        rt = self.runtime
        rt._rows = {}
        candidates, seen = [], set()
        for kind in tuple(rt.host.ALT_PREP_KINDS):
            if kind == 'track_talk':
                for identity, row in rt.media.inventory_track_talk():
                    rt._offer(candidates, seen, kind, row, identity)
            else:
                for row in rt.host.alt_candidates(kind):
                    if self.dynamic.source_entry(row).get('dynamic_kind') in KINDS:
                        continue
                    rt._offer(candidates, seen, kind, row)
        slots = [slot for hour in rt._plans for slot in hour.get('slots', [])
                 if slot.get('dynamic_kind') in KINDS and finite(slot.get('deadline')) > time.time()]
        for slot in slots:
            due = self.due(slot)
            if due['kind'] == 'book_time':
                row = self.book_bundle(due)
            else:
                row = next((row for row in self.dynamic.g.get('_SHELF', {}).get('sfx_supercut', [])
                    if row.get('dynamic_occurrence') == self.dynamic.occurrence(due)
                    and not row.get('dynamic_handed_off')), None)
            if row:
                rt._offer(candidates, seen, KINDS[due['kind']], row, row.get('id') or row.get('sid'))
        return candidates

    def requested_job(self, kinds, lookahead):
        # Same durable ownership checks as System2Store.claim_job, restricted
        # to an operator-requested occurrence. Ordinary jobs retain their order.
        store = self.runtime.store
        with store._tx() as db:
            now = store.now()
            for raw in db.execute("SELECT body FROM s2_jobs WHERE state IN ('pending','working')"):
                job = json.loads(raw[0])
                if job.get('slot_id') not in self.requested.values() or job.get('kind') not in kinds:
                    continue
                slot = store._get(db, 's2_slots', job['slot_id'])
                if not slot or slot['revision'] != job['revision']:
                    continue
                if job['hard_deadline'] <= now or job.get('retry_at', 0) > now:
                    continue
                if job['deadline'] > now + lookahead:
                    continue
                if job['state'] == 'working' and job.get('lease_until', 0) > now:
                    continue
                job.update(state='working', owner='system2-preparer', token=uuid.uuid4().hex,
                    lease_until=now + 900, claimed_at=now, attempts=job['attempts'] + 1)
                store._slot_totals(db, slot)
                job['air_room_seconds'] = slot['air_room_seconds']
                job['template'] = {k: copy.deepcopy(v) for k, v in slot.items()
                                   if k not in {'allocations', 'heard_seconds', 'delivered_seconds'}}
                job['available_until_deadline_seconds'] = max(0, job['deadline'] - now)
                job['estimated_deadline_fit'] = (None if job['estimated_work_seconds'] is None else
                    job['estimated_work_seconds'] <= job['available_until_deadline_seconds'])
                store._save(db, 's2_jobs', job, ('slot_id', 'state', 'deadline'))
                return job
        return None

    async def claim(self, kinds, lookahead):
        if self.runtime.stood_down():
            return None   # [kitchen-hour] System 3 owns the kitchen
        requested_horizon = max(lookahead, int(self.runtime.config.get('horizon_hours') or 1)*3600)
        job = await asyncio.to_thread(self.requested_job, kinds, requested_horizon) if self.requested else None
        if not job:
            job = await self.original['_claim_preparation'](kinds, lookahead)
        if job and job.get('template', {}).get('dynamic_kind') in KINDS:
            await self.prepare_job(job)
            return None
        return job

    def writer_ticket_active(self):
        ticket = self.writer_ticket
        if not ticket:
            return False
        now = time.time()
        slot = next((slot for hour in self.runtime._plans for slot in hour.get('slots', [])
                     if slot.get('id') == ticket['slot_id']), None)
        last = self.dynamic.last.get(ticket['occurrence'], {})
        if (not self.runtime.enabled or self.runtime.stood_down() or now >= ticket['expires_at'] or now >= ticket['hard_deadline']
                or not slot or slot.get('revision') != ticket['revision']
                or (last.get('coverage') or {}).get('ready')
                or last.get('state') in {'deferred', 'invalid'}):
            self.writer_ticket = None
            return False
        return True

    def assigned_work(self, kind):
        # The legacy keeper already yields its next intake at this hook. Its
        # current owner keeps the guard and completes its existing model work.
        if str(kind) == 'banter' and self.writer_ticket_active():
            return True
        return self.original['prep_has_assigned_work'](kind)

    async def wait_for_book_writer(self, job, work, *, wait_seconds=30.0):
        if self.runtime.stood_down():
            return False   # [kitchen-hour] no ticket under System 3
        writing = self.dynamic.g.setdefault('_LARDER_WRITING', [False])
        if not writing[0]:
            return True
        due = self.due(job['template'])
        now = time.time()
        self.writer_ticket = {'slot_id': job['slot_id'], 'revision': job['revision'],
            'occurrence': self.dynamic.occurrence(due), 'hard_deadline': finite(job['hard_deadline']),
            'created_at': now, 'expires_at': min(now + 130.0, finite(job['hard_deadline']))}
        limit = asyncio.get_running_loop().time() + max(0.0, min(30.0, wait_seconds))
        work.update(writer_wait='Waiting for the current shared writer; the next legacy banter intake yields',
                    writer_priority_expires_at=self.writer_ticket['expires_at'])
        while writing[0]:
            if not self.writer_ticket_active() or asyncio.get_running_loop().time() >= limit:
                return False
            await asyncio.sleep(min(.1, max(.001, limit-asyncio.get_running_loop().time())))
        work['writer_wait'] = 'The current owner finished; the native book turn may acquire the shared guard'
        return True

    def release_writer_ticket(self, occurrence):
        if self.writer_ticket and self.writer_ticket['occurrence'] == occurrence:
            self.writer_ticket = None

    async def prepare_job(self, job):
        if self.runtime.stood_down():
            return None   # [kitchen-hour]
        rt, h = self.runtime, self.runtime.host
        due = self.due(job['template'])
        kind = due['kind']
        work = {'trace_id': uuid.uuid4().hex, 'job_id': job['id'], 'slot_id': job['slot_id'],
                'kind': job['kind'], 'dynamic_kind': kind, 'started': time.time(), 'state': 'preparing',
                'calls': [], 'template': copy.deepcopy(job['template']),
                'generation_turns': int(rt.config['generation_turns'])}
        rt._work = work
        rt._works[work['trace_id']] = work
        token = system2_runtime.WORK.set(work)
        async def renew():
            while True:
                await asyncio.sleep(300)
                await asyncio.to_thread(rt.store.renew_job, job['id'], 'system2-preparer', job['token'], lease_seconds=900)
        renewer = asyncio.create_task(renew())
        changed = False
        book_turn_attempted = False
        try:
            h.prep_context_set(job['kind'])
            if kind == 'book_time':
                body = self.budget(due)['content_budget_seconds']
                minimum_available = min(135.0, body) + self.overhead(int(work['generation_turns']))
                available = finite(job.get('hard_deadline')) - time.time()
                if available < minimum_available:
                    work.update(state='waiting', why='Too little time remains for a complete recorded book part',
                        available_seconds=available, minimum_available_seconds=minimum_available)
                    await asyncio.to_thread(rt.store.complete_job, job['id'], 'system2-preparer', job['token'],
                        success=False, retry_after=120, result={'why':work['why']})
                    return
            if kind == 'book_time':
                if not await self.wait_for_book_writer(job, work):
                    work.update(state='waiting', why='The current shared writer retains ownership; a bounded native book priority ticket yields the next legacy intake')
                    await asyncio.to_thread(rt.store.complete_job, job['id'], 'system2-preparer', job['token'],
                        success=False, retry_after=90, result={'why': work['why'],
                            'writer_priority_expires_at': (self.writer_ticket or {}).get('expires_at')})
                    return
                book_turn_attempted = True
                before = {id(row) for row in self.dynamic.book_rows(self.dynamic.occurrence(due))}
                changed = bool(await self.dynamic.prepare_book(due))
                # bank_to writes a retained script; render_stream controls how
                # it will air, not whether its voices have been recorded.
                # The dynamic helper retries one retained part on later jobs;
                # only newly authored parts visit recording here.
                for part in self.dynamic.book_rows(self.dynamic.occurrence(due)):
                    if id(part) not in before and not h.dialogue_row_ready('banter', part):
                        with self.book_context(self.dynamic.source_entry(part)):
                            changed = bool(await h.larder_prepare(self.dynamic.source_entry(part))) or changed
                cache = getattr(self.dynamic, 'coverage_cache', None)
                if isinstance(cache, dict):
                    cache.clear()
                current = self.dynamic.book_coverage(due)
                self.dynamic.last.setdefault(self.dynamic.occurrence(due), {})['coverage'] = current
                for row in self.dynamic.book_rows(self.dynamic.occurrence(due)):
                    self.dynamic.source_entry(row).update(system2_slot=job['slot_id'],
                        system2_job=job['id'], system2_trace_id=work['trace_id'])
                row = self.book_bundle(due)
            else:
                row = await self.dynamic.prepare_supercut(due)
                changed = bool(row)
                if row:
                    row.update(system2_slot=job['slot_id'], system2_job=job['id'], system2_trace_id=work['trace_id'])
            fresh = [self.candidate(job['kind'], row, row.get('id') or row.get('sid'))] if row else []
            rt.media.checkpoint_preparation(pantry=True, larder=kind == 'book_time')
            await asyncio.to_thread(rt.store.complete_job, job['id'], 'system2-preparer', job['token'],
                candidates=fresh, success=changed, retry_after=30 if changed else 90,
                result={'dynamic_kind': kind, 'dynamic_occurrence': self.dynamic.occurrence(due),
                        'coverage': copy.deepcopy(self.dynamic.last.get(self.dynamic.occurrence(due), {}).get('coverage'))})
            work.update(state='ready' if any(x['ready'] for x in fresh) else 'retained' if changed else 'waiting',
                        candidate_ids=[x['id'] for x in fresh], changed=changed)
        except asyncio.CancelledError:
            work['state'] = 'interrupted'
            try:
                await asyncio.to_thread(rt.store.complete_job, job['id'], 'system2-preparer', job['token'], success=False, retry_after=0)
            except system2_runtime.System2Conflict:
                pass
            raise
        except Exception as exc:
            work.update(state='error', error=str(exc)[:500])
            rt.error('prepare:' + kind, exc)
            try:
                await asyncio.to_thread(rt.store.complete_job, job['id'], 'system2-preparer', job['token'], success=False, retry_after=90)
            except system2_runtime.System2Conflict:
                pass
        finally:
            if kind == 'book_time' and (changed or work.get('state') in {'error', 'interrupted'}
                    or (book_turn_attempted and self.dynamic.last.get(self.dynamic.occurrence(due), {}).get('state') in {'deferred', 'invalid', 'blocked'})):
                self.release_writer_ticket(self.dynamic.occurrence(due))
            renewer.cancel()
            work['finished'] = time.time()
            rt.save_trace(work)
            rt._works.pop(work['trace_id'], None)
            system2_runtime.WORK.reset(token)
            h.prep_context_clear()
            rt._last_refresh = 0

    def publish(self, slot):
        selected = self.original['_publish_clock'](slot)
        if slot and slot.get('dynamic_kind') in KINDS:
            kind = slot['dynamic_kind']
            selected['kind'] = kind
            self.runtime.host._RADIO['sched_slot']['kind'] = kind
            self.runtime.host._RADIO['sched_kind'] = kind
        return selected

    def brief(self):
        result = self.original['current_slot_brief']()
        slot = next((slot for hour in self.runtime._plans for slot in hour.get('slots', [])
                     if slot.get('id') == result.get('occurrence')), None)
        if slot and slot.get('dynamic_kind') in KINDS:
            result['kind'] = slot['dynamic_kind']
        return result

    def fallback(self):
        now = time.time()
        if any(slot.get('dynamic_kind') in KINDS and slot['start'] <= now < slot['deadline']
               for hour in self.runtime._plans for slot in hour.get('slots', [])):
            return False
        return self.original['fallback_due']()

    def due_dispatch_slot(self):
        """A cached exact allocation may wake native air without a model wait."""
        rt, host = self.runtime, self.runtime.host
        if (not rt.enabled or not host._RADIO.get('on') or host.radio_paused()
                or rt._dispatch_lock.locked()):
            return None
        now = time.time()
        # Native events retain their existing priority. This extra clock
        # never chooses an ordinary/event slot or bypasses that selection.
        if any(slot.get('allocations') and finite(slot.get('start')) <= now < finite(slot.get('deadline'))
                for hour in (getattr(rt, '_event_plans', ()) or ())
                for slot in hour.get('slots', ())):
            return None
        slot = next((slot for hour in (getattr(rt, '_plans', ()) or ())
            for slot in hour.get('slots', ())
            if finite(slot.get('start')) <= now < finite(slot.get('deadline'))), None)
        if not slot or slot.get('dynamic_kind') not in KINDS or not slot.get('enabled', True):
            return None
        occurrence = self.dynamic.occurrence(self.due(slot))
        candidates = {str(row.get('id')): row for row in (getattr(rt, '_candidates', ()) or ())
                      if isinstance(row, dict)}
        for allocation in slot.get('allocations', ()):
            if allocation.get('state') not in (None, '', 'ready'):
                continue
            saved = allocation.get('candidate') or {}
            candidate = candidates.get(str(saved.get('id')))
            if not candidate:
                continue
            source = candidate.get('source') or {}
            air = finite(candidate.get('air_seconds'), finite(candidate.get('seconds')))
            if (candidate.get('ready') and candidate.get('eligible')
                    and not candidate.get('blocked_reasons')
                    and candidate.get('slot_id') == slot.get('id')
                    and source.get('dynamic_kind') == slot['dynamic_kind']
                    and source.get('dynamic_occurrence') == occurrence
                    and (slot['id'], candidate['id']) not in rt._dispatched
                    and air > 0 and now + air <= finite(slot.get('deadline'))):
                return slot
        return None

    async def dispatch_due(self):
        slot = self.due_dispatch_slot()
        if not slot:
            return False
        # Fresh resolution, fit, reservations, publication and receipts stay
        # under the native director. The exact ID fences slow clock refreshes.
        return await self.runtime.dispatch(only_slot_id=slot['id'])

    async def dispatch_loop(self):
        while not self.dispatch_stopping:
            try:
                await self.dispatch_due()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.runtime.error('dispatch:dynamic', exc)
            await asyncio.sleep(.5)

    def start_dispatch(self):
        if self.dispatch_task is not None and not self.dispatch_task.done():
            return self.dispatch_task
        self.dispatch_stopping = False
        self.dispatch_task = asyncio.create_task(self.dispatch_loop(), name='system2:dynamic-air')
        return self.dispatch_task

    async def stop_dispatch(self):
        self.dispatch_stopping = True
        task, self.dispatch_task = self.dispatch_task, None
        if task is not None:
            task.cancel()
            # Native dispatch cancels only unhanded work; published transport
            # retains its existing completion/ACK owner.
            await asyncio.gather(task, return_exceptions=True)

    async def deliver(self, resolved, on_handoff, can_handoff, entry_overrides=None):
        entry = entry_overrides or {}
        dynamic_kind = resolved.get('entry', {}).get('dynamic_kind')
        if dynamic_kind not in KINDS:
            return await self.original['deliver'](resolved, on_handoff, can_handoff, entry_overrides=entry_overrides)
        accepted_handoff = False
        def accepted():
            nonlocal accepted_handoff
            on_handoff()
            accepted_handoff = True
        with self.book_context(resolved.get('entry') or {}):
            said = await self.original['deliver'](resolved, accepted, can_handoff, entry_overrides=entry_overrides)
        # A known transport refusal must retain the source asset for retry.
        # System2 handles attempted/ambiguous delivery under its own reservation.
        if said and accepted_handoff:
            source = resolved['source_row']
            occ = self.dynamic.source_entry(source).get('dynamic_occurrence')
            if dynamic_kind == 'book_time':
                for row in self.dynamic.book_rows(occ):
                    self.dynamic.source_entry(row)['dynamic_handed_off'] = True
                self.dynamic.last.setdefault(occ, {})['started'] = True
                self.dynamic.call('_larder_save')
            else:
                source['dynamic_handed_off'] = True
                self.dynamic.call('_schedule_action_complete', 'sfx_supercut', (entry.get('_system2') or {}).get('slot_id'))
                self.dynamic.call('_shelf_save')
            self.dynamic.last.setdefault(occ, {})['state'] = 'handed_off'
            self.requested.pop(dynamic_kind, None)
        return said

    async def request_prepare(self, kind):
        if kind not in KINDS:
            raise ValueError('Unknown dynamic segment')
        if not self.runtime.enabled:
            return {'engine': 'legacy', 'state': 'queued'}
        await self.runtime.refresh(force=True, want_status=False)
        now = time.time()
        slots = sorted((slot for hour in self.runtime._plans for slot in hour.get('slots', [])
                        if slot.get('dynamic_kind') == kind and finite(slot.get('start')) >= now),
                       key=lambda slot: finite(slot.get('start')))
        if not slots:
            return {'engine': 'system2', 'state': 'waiting_for_scheduled_occurrence'}
        self.requested[kind] = slots[0]['id']
        # Wake the established production semaphore. A request does not write
        # dialogue itself and never starts or publishes playback.
        task = self.runtime.prepare_spawn()
        if task:
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        return {'engine': 'system2', 'state': 'queued', 'slot_id': slots[0]['id'],
                'dynamic_occurrence': self.dynamic.occurrence(self.due(slots[0]))}

    def regular_rows(self, kind):
        return [row for row in self.original['alt_candidates'](kind)
                if self.dynamic.source_entry(row).get('dynamic_kind') not in KINDS]

    def attach(self):
        rt = self.runtime
        for name, replacement in (('templates', self.templates), ('candidate', self.candidate),
                ('inventory', self.inventory), ('_claim_preparation', self.claim),
                ('_publish_clock', self.publish), ('current_slot_brief', self.brief),
                ('fallback_due', self.fallback), ('repeat_allowed', self.repeat_allowed)):
            self.original[name] = getattr(rt, name)
            setattr(rt, name, replacement)
        assigned = self.dynamic.g.get('prep_has_assigned_work')
        if callable(assigned):
            self.original['prep_has_assigned_work'] = assigned
            self.dynamic.g['prep_has_assigned_work'] = self.assigned_work
        self.original['alt_candidates'] = rt.host.alt_candidates
        rt.host.alt_candidates = self.regular_rows
        self.original['resolve'] = rt.media.resolve
        self.original['deliver'] = rt.media.deliver
        rt.media.resolve, rt.media.deliver = self.resolve, self.deliver
        rt._dynamic_segments_adapter = self
        return self


def install(app, namespace):
    factory = namespace.get('_system2')
    dynamic = namespace.get('DYNAMIC_SEGMENTS_RUNTIME')
    if not callable(factory) or dynamic is None:
        raise RuntimeError('Install dynamic System2 after the System2 and dynamic source runtimes')
    runtime = factory()
    adapter = getattr(runtime, '_dynamic_segments_adapter', None) or DynamicSystem2(runtime, dynamic).attach()
    namespace['DYNAMIC_SEGMENTS_SYSTEM2'] = adapter
    namespace['dynamic_book_content_budget'] = adapter.budget
    namespace['dynamic_sfx_playback_overhead'] = lambda: adapter.overhead(1) + 1.0
    namespace['dynamic_system2_request_prepare'] = adapter.request_prepare
    if not adapter.dispatch_lifecycle_registered:
        @app.on_event('startup')
        async def start_dynamic_system2_air():
            adapter.start_dispatch()

        @app.on_event('shutdown')
        async def stop_dynamic_system2_air():
            await adapter.stop_dispatch()

        adapter.dispatch_lifecycle_registered = True
    return adapter
