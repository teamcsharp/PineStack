import asyncio
import copy
import tempfile
import time
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import dynamic_segments_runtime as dynamic
import segment_prompts


class FakeResolver:
    def __init__(self):
        self.calls = []
    async def resolve_async(self, *texts, **kw):
        self.calls.append((texts, kw))
        return {'source': {'title': 'An Actual Title', 'book_id': 'actual'},
                'values': {'book': 'An Actual Title', 'bookchapter': '7',
                    'booksegment': 'Exact source contains {gazette} and {sfxclip}.',
                    'booktopic': 'a source topic', 'booksentence': 'Exact source sentence.',
                    'booksentences': 'Exact source sentence.', 'stationname': 'Pine Box FM'},
                'rolls': [{'key': 'book.title', 'index': 1}]}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = {name: getattr(segment_prompts, name) for name in
            ('_HOST', '_PATH', '_BOOK', '_READ', '_MEMO', '_RIDES', '_RECENT')}
        self.addCleanup(self.restore)
        segment_prompts._HOST = {}
        segment_prompts._PATH = Path(self.tmp.name) / 'segment_prompts.json'
        segment_prompts._BOOK = {'kinds': {}, 'uses': [], 'at': 0.0}
        segment_prompts._READ = [False]
        segment_prompts._MEMO, segment_prompts._RIDES, segment_prompts._RECENT = {}, {}, []
        self.rows = [{'id': 'ordinary-hour', 'kind': 'banter', 'minutes': 60, 'enabled': True}]
        self.resolver = FakeResolver()
        from contextvars import ContextVar
        class BookRuntime:
            weighted = object()
            preview_weighted = object()
        self.g = {'DATA_DIR': Path(self.tmp.name), 'PRODUCED_ADS_DIR': Path(self.tmp.name) / 'ads',
            '_LARDER': [], '_SHELF': {}, '_RADIO': {'sched_slot': {}, 'sched_pos': {}},
            'schedule_read': lambda: {'presets': {'current': self.rows}},
            'schedule_hour_slots': lambda store=None, key='', when=None: ('current', copy.deepcopy(self.rows), False),
            'dialogue_row_ready': lambda kind, row: bool(row.get('made')),
            'require_auth': lambda key: None, 'require_read_auth': lambda key: None,
            'book_resolver': lambda: self.resolver, 'BOOK_PROMPT_RUNTIME': BookRuntime(),
            'book_prompt_context': ContextVar('fake-book-context', default=None),
            'banter_turns': lambda text: [(line[0], line[3:]) for line in text.splitlines() if line[:3] in ('A: ', 'B: ')],
            'alt_brief_now': lambda: '', 'alt_brief_set': lambda value: None,
            'segment_prepare_contract': lambda road: {'chain_order': len(self.g['_LARDER'])},
            'pipeline_log': lambda *a, **kw: None,
            'dj_settings': lambda: {'host_name': 'Dill', 'cohost_name': 'Skip', 'station_name': 'Pine Box FM'}}
        self.app = FastAPI()
        self.rt = dynamic.install(self.app, self.g)
        self.client = TestClient(self.app)

    def restore(self):
        for name, value in self.old.items():
            setattr(segment_prompts, name, value)

    def due(self):
        return {'kind': 'book_time', 'slot_id': 'book-15', 'due_at': 100,
                'slot': {'id': 'book-15', 'kind': 'book_time', 'minutes': 7.5},
                'owns_seconds': 450, 'road': 'banter', 'commit_id': 'book-15@100'}

    def test_activation_starts_next_hour_without_changing_current_clock_or_queues(self):
        before = copy.deepcopy(self.g['_RADIO'])
        current = self.rt.hour_key()
        original = self.g['schedule_hour_slots'](key=current)
        reply = self.client.post('/api/dynamic-segments/activate', json={})
        self.assertEqual(reply.status_code, 200, reply.text)
        data = reply.json()
        self.assertGreater(data['effective_hour'], current)
        self.assertEqual(self.g['_RADIO'], before)
        self.assertEqual(self.g['schedule_hour_slots'](key=current), original)
        future = self.g['schedule_hour_slots'](key=data['effective_hour'])
        self.assertTrue(future[2])
        self.assertEqual(next(row['minutes'] for row in future[1] if row['kind'] == 'sfx_supercut'), 1.25)
        self.assertEqual(sum(row['minutes'] for row in future[1]), 60)
        self.assertEqual([row['kind'] for row in future[1] if row['kind'] != 'banter'],
                         ['book_time', 'book_time', 'sfx_supercut'])
        restored = dynamic.DynamicSegments(self.g)
        self.assertEqual(restored.plan_for(data['effective_hour']), self.rt.plan_for(data['effective_hour']))

    def test_saved_clock_positions_are_applied_and_overlaps_rejected(self):
        chosen = segment_prompts.entry_view('book_time')['alternatives'][0]
        segment_prompts.patch_alternative('book_time', chosen['id'], {'config': {
            'target_seconds': 300, 'starts_at_minutes': [12, 40]}})
        windows = self.rt.windows()
        self.assertEqual(windows[:2], [(12, 5, 'book_time'), (40, 5, 'book_time')])
        segment_prompts.patch_alternative('book_time', chosen['id'], {'config': {
            'target_seconds': 600, 'starts_at_minutes': [54, 55]}})
        reply = self.client.post('/api/dynamic-segments/activate', json={})
        self.assertEqual(reply.status_code, 400)
        self.assertFalse(self.rt.plans)
        status = self.client.get('/api/dynamic-segments')
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json()['schedule']['windows_error'])
        self.assertIn('book_time', status.json()['kinds'])

    def test_preview_coherently_resolves_both_fields_without_spending_live_dice(self):
        reply = self.client.post('/api/dynamic-segments/book_time/preview', json={
            'text': 'Discuss {book}.', 'generation_prompt': 'Read {bookchapter}: {booksegment}',
            'config': {'book_binding': 'An Actual Title'}})
        self.assertEqual(reply.status_code, 200, reply.text)
        data = reply.json()
        self.assertEqual(data['source']['book_id'], 'actual')
        self.assertIn('An Actual Title', data['system_prompt'])
        self.assertIn('{gazette}', data['generation_prompt'], 'source braces remain source text')
        self.assertEqual(len(self.resolver.calls), 1)
        self.assertEqual(self.resolver.calls[0][1]['weighted'], self.g['BOOK_PROMPT_RUNTIME'].preview_weighted)
        self.assertFalse(self.resolver.calls[0][1]['persist'])
        self.assertFalse(self.resolver.calls[0][1]['scheduled'])
        self.assertFalse(segment_prompts._MEMO)

    def test_book_preview_resolves_configured_station_before_literal_source_in_both_fields(self):
        from types import SimpleNamespace
        station = 'Chicken Tendo Little Pine Box FM Station'
        self.g['dj_settings'] = lambda: {'station_name':station}
        mode = SimpleNamespace(active=False, selected_id='operator-preview', select=lambda *args: self.fail('preview must not select or activate Book Mode'))
        self.g['BOOK_MODE'] = mode
        literal = 'The printed label says {stationname}, {sentence}, and {gazette}.'
        async def resolve(*texts, **kw):
            self.resolver.calls.append((texts, kw))
            return {'source':{'book_id':'actual', 'title':'An Actual Title'},
                'values':{'book':'An Actual Title', 'booksegment':literal,
                          'booksentence':literal, 'booksentences':literal}}
        self.resolver.resolve_async = resolve
        before = copy.deepcopy((self.g['_RADIO'], self.g['_LARDER'], segment_prompts._MEMO))
        reply = self.client.post('/api/dynamic-segments/book_time/preview', json={
            'text':'Welcome to Book Time on {stationname}. Discuss {book}: "{booksegment}".',
            'generation_prompt':'On {stationname}, quote "{booksentence}".',
            'config':{'book_binding':'actual'}})
        self.assertEqual(reply.status_code, 200, reply.text)
        pair = reply.json()
        self.assertIn('Welcome to Book Time on '+station, pair['system_prompt'])
        self.assertIn('On '+station+', quote', pair['generation_prompt'])
        for field in ('system_prompt','generation_prompt','text'):
            self.assertIn(literal, pair[field], 'braces printed by the book remain literal evidence')
        self.assertFalse(self.resolver.calls[0][1]['persist'])
        self.assertFalse(self.resolver.calls[0][1]['scheduled'])
        self.assertIs(self.resolver.calls[0][1]['weighted'], self.g['BOOK_PROMPT_RUNTIME'].preview_weighted)
        self.assertEqual((self.g['_RADIO'], self.g['_LARDER'], segment_prompts._MEMO), before)
        self.assertFalse(mode.active); self.assertEqual(mode.selected_id, 'operator-preview')

    def test_inventory_and_admission_refuse_generic_or_wrong_occurrence_books(self):
        due = self.due()
        book = {'dynamic_kind': 'book_time', 'dynamic_occurrence': 'book-15@100', 'made': True}
        wrong = dict(book, dynamic_occurrence='book-45@100')
        self.assertTrue(self.rt.inventory_match(due, {'row': book}))
        self.assertFalse(self.rt.inventory_match(due, {'row': {'made': True}}))
        self.assertFalse(self.rt.inventory_match(due, {'row': wrong}))
        self.assertFalse(self.rt.inventory_match({'kind': 'banter'}, {'row': book}))
        token = self.rt.admission.set(due)
        self.assertTrue(self.g['dialogue_row_ready']('banter', book))
        self.assertFalse(self.g['dialogue_row_ready']('banter', wrong))
        self.assertFalse(self.g['dialogue_row_ready']('banter', {'made': True}))
        self.rt.admission.reset(token)
        self.assertTrue(self.g['dialogue_row_ready']('banter', book), 'off-air record-room inspection remains possible')

    def test_book_preparation_binds_receipt_before_planning_and_keeps_source_tokens_until_model_wire(self):
        seen = []
        async def banter(*a, **kw):
            seen.append((kw, self.g['book_prompt_context'].get()))
            kw['bank_to'].append({'script': 'A: Welcome to Book Time on Pine Box FM. An Actual Title. I am Dill.\nB: I am Skip. Let us discuss it.',
                'made': False})
        self.g['dj_banter'] = banter
        result = asyncio.run(self.rt.prepare_book(self.due()))
        self.assertTrue(result)
        args, context = seen[0]
        self.assertIn('{booksegment}', args['angle'])
        self.assertNotIn('Exact source contains', args['angle'])
        self.assertEqual(context['book_roulette']['source']['book_id'], 'actual')
        self.assertEqual(self.g['_LARDER'][-1]['book_roulette'], context['book_roulette'])
        self.assertEqual(self.g['_LARDER'][-1]['book_prompt_occurrence'], context['occurrence'])
        row = self.g['_LARDER'][0]
        self.assertEqual(row['dynamic_kind'], 'book_time')
        self.assertEqual(row['dynamic_occurrence'], 'book-15@100')
        self.assertIsNone(self.g['book_prompt_context'].get(), 'source context is reset after preparation')

    def test_measured_shortfall_adds_discussion_before_existing_close(self):
        row = {'dynamic_kind': 'book_time', 'dynamic_occurrence': 'book-15@100',
            'book_phase': 'closing', 'book_source': {'title': 'An Actual Title'},
            'book_station': 'Pine Box FM', 'made': True,
            'script': 'A: A final thought.\nB: Thanks for Book Time on Pine Box FM. Back to the music.',
            'takes': [{'who': 'dj', 'seconds': 30}, {'who': 'cohost', 'seconds': 30}]}
        opening = dict(row, book_phase='opening', script='A: Welcome to Book Time on Pine Box FM. An Actual Title. I am Dill.\nB: I am Skip. A source idea.')
        self.g['_LARDER'].extend([opening, row])
        seen = []
        async def banter(*a, **kw):
            seen.append(kw['angle'])
            kw['bank_to'].append({'script': 'A: Let us develop the same idea.\nB: Yes, and another example.', 'made': False})
        self.g['dj_banter'] = banter
        self.assertTrue(asyncio.run(self.rt.prepare_book(self.due())))
        self.assertIn('Do not introduce yourselves, welcome listeners or close', seen[0])
        self.assertEqual(self.g['_LARDER'][-1]['book_phase'], 'discussion')
        self.assertEqual(row['book_phase'], 'closing', 'frozen closing is retained once')

    def test_supercut_marks_action_only_after_existing_transport_accepts_source_audio(self):
        due = {'kind': 'sfx_supercut', 'slot_id': 'sfx-58', 'due_at': 100,
            'slot': {'id': 'sfx-58', 'kind': 'sfx_supercut', 'minutes': 1}}
        source = Path(self.tmp.name) / 'clip.wav'
        source.write_bytes(b'prepared source-only body')
        async def prepare(*a):
            return {'ok': True, 'clip': source.name, 'path': str(source), 'seconds': 45,
                'body_frames': 1080000, 'sample_rate': 24000, 'recorded_text': 'Pine Box FM',
                'source_plan': {'id': 'source-plan', 'complete': True, 'source_only': True,
                    'clips': [{'sid': 'station-tag'}], 'structure': {'opening': True, 'sell': True,
                    'closing': True, 'station_identity_verified': True}}}
        self.g['sfx_supercut_prepare'] = prepare
        row = asyncio.run(self.rt.prepare_supercut(due))
        self.assertIsNotNone(row)
        self.assertEqual(row['coverage']['wall_target_seconds'], 60)
        self.assertEqual(row['coverage']['content_budget_seconds'], 45)
        self.assertEqual(row['coverage']['source_audio_seconds'], 45)
        self.assertEqual((self.g['PRODUCED_ADS_DIR'] / source.name).read_bytes(), source.read_bytes())
        self.g['_RADIO'].update(sched_slot=due['slot'], sched_pos={'started': 100, 'occurrence': 'actual-sfx'})
        accepted = []
        self.g['_schedule_action_pending'] = lambda *a: True
        self.g['_schedule_action_complete'] = lambda *a: accepted.append(a)
        async def refuse(row, on_handoff=None):
            return False
        self.g['_air_produced_ad'] = refuse
        self.assertFalse(asyncio.run(self.rt.dispatch('sfx_supercut')))
        self.assertFalse(accepted)
        async def handoff(row, on_handoff=None):
            on_handoff()
            return True
        self.g['_air_produced_ad'] = handoff
        self.assertTrue(asyncio.run(self.rt.dispatch('sfx_supercut')))
        self.assertEqual(accepted, [('sfx_supercut', 'actual-sfx')])
        self.assertTrue(row['dynamic_handed_off'])

    def test_overlong_discussion_is_reauthored_before_air_without_changing_the_closing(self):
        source = {'title': 'An Actual Title'}
        opening = {'dynamic_kind': 'book_time', 'dynamic_occurrence': 'book-15@100',
            'book_phase': 'opening', 'book_source': source, 'made': True,
            'script': 'A: Welcome to Book Time on Pine Box FM. An Actual Title. I am Dill.\nB: I am Skip. Here is the section.',
            'takes': [{'who': 'dj', 'seconds': 100}, {'who': 'cohost', 'seconds': 100}]}
        discussion = dict(opening, book_phase='discussion', script='A: Discuss it.\nB: An example.',
                          sid='discussion-one', takes=[{'who': 'dj', 'seconds': 120}, {'who': 'cohost', 'seconds': 120}])
        closing = dict(opening, book_phase='closing', script='A: Thanks for Book Time on Pine Box FM.\nB: Back to the music.',
                       takes=[{'who': 'dj', 'seconds': 50}, {'who': 'cohost', 'seconds': 50}])
        self.g['_LARDER'].extend([opening, discussion, closing])
        self.assertFalse(self.rt.book_coverage(self.due())['fits_content_budget'])
        seen = []
        async def write(*a, **kw):
            seen.append(kw['angle'])
            kw['bank_to'].append({'script': 'A: Concise source discussion.\nB: Same source facts.', 'made': False})
        self.g['dj_banter'] = write
        self.assertTrue(asyncio.run(self.rt.prepare_book(self.due())))
        self.assertIn('Re-author the overlong discussion as a concise', seen[0])
        self.assertTrue(discussion['dynamic_superseded'])
        self.assertNotIn('dynamic_superseded', closing)
        self.assertEqual(self.g['_LARDER'][-1]['duration_replaces'], 'discussion-one')
        self.assertEqual(self.rt.last['book-15@100']['duration_repairs'], 1)

    def test_content_budget_reserves_transport_overhead_without_crediting_it_as_voice(self):
        self.g['dynamic_book_content_budget'] = lambda due: {'content_budget_seconds': 430}
        coverage = self.rt.book_coverage(self.due())
        self.assertEqual(coverage['wall_target_seconds'], 450)
        self.assertEqual(coverage['content_budget_seconds'], 430)
        self.assertEqual(coverage['reserved_overhead_seconds'], 20)
        self.assertEqual(coverage['playable_seconds'], 0)
        self.assertEqual(coverage['target_seconds'], 430)
        self.assertFalse(coverage['ready'])

    def test_restart_restores_real_recorded_authority_before_wrong_pin_and_prompt_memo(self):
        import hashlib
        from types import SimpleNamespace
        import book_roulette
        passage = 'The river supplied the entire garden. Every visitor shared the harvest.'
        source = {'book_id': 'canonical', 'title': 'River Gardens', 'author': 'Ada Reader',
            'chapter': 'The River Garden', 'content_hash': hashlib.sha256(passage.encode()).hexdigest()[:20]}
        receipt = {'version': 2, 'at': 10, 'source': source, 'values': {'book': 'River Gardens',
            'bookchapter': 'The River Garden', 'booksegment': passage, 'booktopic': 'The River Garden',
            'booksentence': 'The river supplied the entire garden.', 'booksentences': passage}}
        original = {'sid': 'real-recorded-part', 'dynamic_kind': 'book_time', 'dynamic_occurrence': 'book-15@100',
            'book_roulette': copy.deepcopy(receipt), 'book_source': copy.deepcopy(source), 'book_phase': 'opening',
            'book_station': 'Pine Box FM', 'made': True, 'takes': [{'who':'dj', 'seconds':58.83}],
            'script': 'A: Welcome to Book Time on Pine Box FM. River Gardens. I am Dill.\nB: I am Skip. The river supplied the entire garden.'}
        self.g['_LARDER'].append(original)
        before = copy.deepcopy(original)
        resolver = book_roulette.BookRoulette(SimpleNamespace(data=Path(self.tmp.name) / 'real-books', catalog={}))
        key = segment_prompts.memo_key('book_time', 'book-15', 'book-15@100')
        wrong = copy.deepcopy(receipt); wrong['source'] = {'book_id': 'wrong', 'title': 'Wrong Book'}
        resolver.state['receipts'][key] = wrong
        segment_prompts._MEMO[key] = {'kind':'book_time', 'book_source': wrong['source'], 'text':'Wrong Book'}
        self.g['book_resolver'] = lambda: resolver
        real_govern = segment_prompts.govern
        observed = []
        def govern(*args, **kw):
            observed.append((resolver.source_for(key), copy.deepcopy(segment_prompts._MEMO.get(key))))
            return real_govern(*args, **kw)
        async def write(*args, **kw):
            observed.append(self.g['book_prompt_context'].get())
            kw['bank_to'].append({'script': 'A: The river supplied the entire garden.\nB: Sharing harvests changes this argument.', 'made': False})
        self.g['dj_banter'] = write
        from unittest.mock import patch
        with patch.object(segment_prompts, 'govern', govern):
            self.assertTrue(asyncio.run(self.rt.prepare_book(self.due())))
        self.assertEqual(observed[0][0], receipt)
        self.assertIsNone(observed[0][1], 'only the stale unfulfilled occurrence memo is discarded')
        self.assertEqual(observed[1]['book_roulette'], receipt)
        self.assertEqual(self.g['_LARDER'][-1]['book_source'], source)
        self.assertEqual(original, before, 'the recorded script, receipt and audio evidence stay untouched')
        self.assertIsNone(self.g['book_prompt_context'].get())
        self.assertEqual(book_roulette.BookRoulette(resolver.mode).source_for(key), receipt)

    def test_mixed_source_parts_are_withheld_preserved_and_reauthored_from_first_receipt(self):
        source = {'book_id': 'actual', 'title': 'An Actual Title', 'content_hash': 'canonical-hash'}
        receipt = {'at': 10, 'source': source, 'values': {'book': 'An Actual Title',
            'booksentence': 'Exact source sentence.'}}
        opening = {'sid': 'first-real-part', 'dynamic_kind': 'book_time', 'dynamic_occurrence':'book-15@100',
            'book_phase': 'opening', 'book_source': source, 'book_roulette': receipt, 'book_station':'Pine Box FM',
            'script':'A: Welcome to Book Time on Pine Box FM. An Actual Title. I am Dill.\nB: I am Skip. Exact source sentence.',
            'made':True, 'takes':[{'who':'dj', 'seconds':60}]}
        wrong_source = {'book_id':'wrong', 'title':'Wrong Book', 'content_hash':'wrong-hash'}
        conflicting = {'sid': 'wrong-recorded-part', 'dynamic_kind':'book_time', 'dynamic_occurrence':'book-15@100',
            'book_phase':'discussion', 'book_source':wrong_source,
            'book_roulette':{'at':20, 'source':wrong_source, 'values':{'book':'Wrong Book','booksentence':'The wrong book quote.'}},
            'script':'A: The wrong book quote.\nB: It changes our opinion.', 'made':True,
            'takes':[{'who':'dj', 'seconds':370, 'key':'original-wav-key'}]}
        self.g['_LARDER'].extend([opening, conflicting]); original = copy.deepcopy(conflicting)
        coverage = self.rt.book_coverage(self.due())
        self.assertFalse(coverage['ready'])
        self.assertFalse(coverage['book_source_coherence']['valid'])
        self.assertEqual(coverage['playable_seconds'], 60)
        seen = []
        async def write(*args, **kw):
            seen.append(self.g['book_prompt_context'].get())
            kw['bank_to'].append({'script':'A: Exact source sentence.\nB: The real source offers another perspective.', 'made':False})
        self.g['dj_banter'] = write
        self.assertTrue(asyncio.run(self.rt.prepare_book(self.due())))
        self.assertEqual(seen[0]['book_roulette'], receipt)
        self.assertTrue(conflicting['dynamic_superseded'])
        self.assertIn('dynamic_source_rejected', conflicting)
        for field in ('script','takes','book_source','book_roulette'):
            self.assertEqual(conflicting[field], original[field])
        self.assertNotIn(conflicting, self.rt.book_rows('book-15@100'))
        self.assertEqual(self.g['_LARDER'][-1]['book_source'], source)
        self.assertEqual(len(self.resolver.calls), 0, 'existing production must never draw another book')
        self.assertTrue(self.rt.book_coverage(self.due())['book_source_coherence']['valid'])

    def test_recording_retry_uses_the_saved_source_before_any_new_writing(self):
        saved = {'source': {'title': 'An Actual Title'}, 'values': {'book': 'An Actual Title'}}
        row = {'dynamic_kind': 'book_time', 'dynamic_occurrence': 'book-15@100',
               'book_roulette': saved, 'book_config': {'book_binding': 'actual'},
               'book_prompt_occurrence': 'saved-context', 'made': False,
               'script': 'A: Welcome to Book Time on Pine Box FM. An Actual Title. I am Dill.\nB: I am Skip. A section.',
               'book_source': saved['source'], 'book_phase': 'opening'}
        self.g['_LARDER'].append(row)
        seen = []
        async def record(part):
            seen.append(self.g['book_prompt_context'].get())
            part['made'] = True
            part['takes'] = [{'who': 'dj', 'seconds': 25}, {'who': 'cohost', 'seconds': 25}]
            return True
        async def never_write(*a, **kw):
            raise AssertionError('recording retry must not write another round')
        self.g['larder_prepare'] = record
        self.g['dj_banter'] = never_write
        self.assertTrue(asyncio.run(self.rt.prepare_book(self.due())))
        self.assertEqual(seen[0]['book_roulette'], saved)
        self.assertEqual(seen[0]['occurrence'], 'saved-context')
        self.assertEqual(len(self.g['_LARDER']), 1)
        self.assertIsNone(self.g['book_prompt_context'].get())

    def test_premature_closing_is_retained_for_review_and_repaired_before_recording(self):
        seen = []
        async def write(*a, **kw):
            seen.append(kw['angle'])
            if len(seen) == 1:
                script = 'A: Welcome to Book Time on Pine Box FM. An Actual Title. I am Dill.\nB: I am Skip. Thanks for Book Time on Pine Box FM. Back to the music.'
            else:
                script = 'A: Welcome to Book Time on Pine Box FM. An Actual Title. I am Dill.\nB: I am Skip. Let us begin the source discussion.'
            kw['bank_to'].append({'script': script, 'made': False})
        self.g['dj_banter'] = write
        self.assertTrue(asyncio.run(self.rt.prepare_book(self.due())))
        rejected = self.g['_LARDER'][0]
        self.assertTrue(rejected['dynamic_superseded'])
        self.assertTrue(rejected['handoff_unavailable'])
        self.assertFalse(self.rt.book_rows('book-15@100'))
        self.assertEqual(self.rt.book_coverage(self.due())['playable_seconds'], 0)
        self.assertTrue(asyncio.run(self.rt.prepare_book(self.due())))
        self.assertIn('Correct the rejected phase', seen[1])
        self.assertTrue(rejected['phase_repaired_by'])
        self.assertEqual(len(self.rt.book_rows('book-15@100')), 1)
        self.assertEqual(self.g['_LARDER'][-1]['book_prompts']['phase'], seen[1].split('\n')[-1])

    def test_wrong_phase_and_duplicate_welcomes_never_count_toward_readiness(self):
        source = {'title': 'An Actual Title'}
        opening = {'dynamic_kind': 'book_time', 'dynamic_occurrence': 'book-15@100',
            'book_phase': 'opening', 'book_source': source, 'book_station': 'Pine Box FM', 'made': True,
            'script': 'A: Welcome to Book Time on Pine Box FM. An Actual Title. I am Dill.\nB: I am Skip. Discussion.',
            'takes': [{'who': 'dj', 'seconds': 120}, {'who': 'cohost', 'seconds': 120}]}
        closing = dict(opening, book_phase='closing',
            script='A: Thanks for Book Time on Pine Box FM.\nB: Back to the music.',
            takes=[{'who': 'dj', 'seconds': 105}, {'who': 'cohost', 'seconds': 105}])
        opening['book_roulette'] = {'source': source, 'values': {'booksentence': 'Exact source sentence.'}}
        opening['script'] += ' Exact source sentence.'
        body = ' '.join(['source discussion'] * 18)
        opening['script'] += '\n' + '\n'.join(('A: ' if i % 2 == 0 else 'B: ') + body for i in range(18))
        closing['script'] = '\n'.join(('A: ' if i % 2 == 0 else 'B: ') + body for i in range(18)) + '\n' + closing['script']
        opening['takes'] = [{'who': 'dj' if i % 2 == 0 else 'cohost', 'seconds': 12} for i in range(20)]
        closing['takes'] = [{'who': 'dj' if i % 2 == 0 else 'cohost', 'seconds': 10.5} for i in range(20)]
        self.assertTrue(self.rt.book_coverage(self.due(), [opening, closing])['ready'])
        wrong = dict(opening, book_phase='discussion')
        coverage = self.rt.book_coverage(self.due(), [wrong, closing])
        self.assertFalse(coverage['ready'])
        self.assertFalse(coverage['book_structure']['valid'])
        self.assertEqual(coverage['playable_seconds'], 210)
        duplicate = dict(opening)
        coverage = self.rt.book_coverage(self.due(), [opening, duplicate, closing])
        self.assertFalse(coverage['ready'])
        self.assertEqual(coverage['book_structure']['opening_count'], 1)

    def test_tint_rewrite_with_premature_closing_is_rejected_before_voice(self):
        row = {'dynamic_kind': 'book_time', 'dynamic_occurrence': 'book-15@100',
            'book_phase': 'discussion', 'book_source': {'title': 'An Actual Title'},
            'book_station': 'Pine Box FM', 'script': 'A: Continue the discussion.\nB: An example.'}
        async def tint(entry, kind, *a, **kw):
            entry['script'] += '\nA: Thanks for Book Time on Pine Box FM. Back to the music.'
            return True
        self.g['ensure_entry_tinted'] = tint
        # Reinstall into a detached namespace to exercise the actual installed boundary.
        self.g.pop('DYNAMIC_SEGMENTS_RUNTIME')
        runtime = dynamic.install(FastAPI(), self.g)
        self.assertFalse(asyncio.run(self.g['ensure_entry_tinted'](row, 'banter', critical=True)))
        self.assertTrue(row['dynamic_superseded'])
        self.assertTrue(row['handoff_unavailable'])
        self.assertIn('Discussion', row['dynamic_phase_rejected']['why'])

    def test_opening_self_introductions_follow_frozen_roles_and_common_forms(self):
        row = {'book_phase': 'opening', 'book_source': {'title': 'An Actual Title'},
               'book_station': 'Pine Box FM', 'book_cast': {'A': 'Dill', 'B': 'Skip'}}
        for first, second in (("I'm Dill", 'I am Skip'), ('This is Dill', "I'm Skip"),
                              ('My name is Dill', 'This is Skip')):
            row['script'] = 'A: Welcome to Book Time on Pine Box FM. An Actual Title. ' + first + '.\nB: ' + second + '.'
            self.assertFalse(self.rt.phase_error(row))
        row['script'] = "B: Welcome to Book Time on Pine Box FM. An Actual Title. I'm Dill, and with me is Skip.\nA: I'm Skip."
        self.assertIn('wrong host', self.rt.phase_error(row))
        row['script'] = "A: Welcome to Book Time on Pine Box FM. An Actual Title. I'm Dill.\nB: Let us discuss it."
        self.assertIn('Both hosts', self.rt.phase_error(row))
        row['book_cast'] = {'A': 'DJ Cedar', 'B': 'Booth Echo'}
        row['script'] = "A: Welcome to Book Time on Pine Box FM. An Actual Title. I'm DJ Cedar.\nB: This is Booth Echo."
        self.assertFalse(self.rt.phase_error(row), 'stored cast names take precedence over later current settings')

    def test_existing_system3_conversation_cast_is_used_without_reinterpreting_voices(self):
        class Store:
            def conversation(self, cid, with_events=True):
                return {'inputs': {'names': {'A': 'Frozen Host', 'B': 'Frozen Cohost'}}}
        class System3:
            store = Store()
            recent = {}
        self.g['_system3'] = lambda: System3()
        row = {'book_phase': 'opening', 'book_source': {'title': 'An Actual Title'},
            'book_station': 'Pine Box FM', 'system3': {'conversation_id': 'actual-plan'},
            'book_cast': {'A': 'Old Snapshot', 'B': 'Old Other'},
            'script': 'A: Welcome to Book Time on Pine Box FM. An Actual Title. I am Frozen Host.\nB: This is Frozen Cohost.'}
        self.assertFalse(self.rt.phase_error(row))
        self.assertEqual(self.rt.host_cast(row), {'A': 'Frozen Host', 'B': 'Frozen Cohost'})

    def test_quote_evidence_requires_actual_recorded_receipt_text_not_topic_or_title(self):
        receipt = {'source': {'title': 'An Actual Title'}, 'values': {
            'booksentence': 'The river belongs to everyone.',
            'booksentences': 'The river belongs to everyone. No bridge can own the current.',
            'booktopic': 'The river and ownership', 'book': 'An Actual Title'}}
        row = {'script': 'A: An Actual Title.\nB: The river and ownership.', 'made': True, 'book_roulette': receipt}
        self.assertFalse(self.rt.quote_evidence([row])['written'])
        row['script'] = 'A: As the author says, “The river belongs to everyone.”\nB: What does that mean?'
        self.assertTrue(self.rt.quote_evidence([row])['recorded'])
        row['made'] = False
        self.assertTrue(self.rt.quote_evidence([row])['written'])
        self.assertFalse(self.rt.quote_evidence([row])['recorded'])
        row['script'] = 'A: The river belongs to everybody.\nB: That is my paraphrase.'
        self.assertFalse(self.rt.quote_evidence([row])['written'])
        receipt['values']['booksentence'] = 'an exact bounded excerpt without a full stop'
        row['script'] = 'A: Read this: "an exact bounded excerpt without a full stop".'
        self.assertTrue(self.rt.quote_evidence([row])['written'])

    def test_frozen_reference_section_is_deferred_without_rebinding_or_rewriting(self):
        row = {'dynamic_kind': 'book_time', 'dynamic_occurrence': 'book-15@100',
            'book_source': {'title': 'An Actual Title', 'chapter': 'Index', 'member': 'index_split_014.html'},
            'book_phase': 'opening', 'made': True, 'script': 'A: Historical frozen words.'}
        self.g['_LARDER'].append(row)
        before = copy.deepcopy(row)
        async def never_write(*a, **kw):
            raise AssertionError('a frozen reference-section occurrence must not be rebound')
        self.g['dj_banter'] = never_write
        self.assertFalse(asyncio.run(self.rt.prepare_book(self.due())))
        self.assertEqual(row, before)
        self.assertEqual(self.rt.last['book-15@100']['state'], 'deferred')
        self.assertFalse(self.rt.book_coverage(self.due())['discussion_source_allowed'])

    def test_recorded_wrong_identity_is_repaired_for_the_same_frozen_source(self):
        source = {'title': 'An Actual Title', 'book_id': 'actual', 'chapter': '7'}
        row = {'dynamic_kind': 'book_time', 'dynamic_occurrence': 'book-15@100',
            'book_phase': 'opening', 'book_source': source, 'book_cast': {'A': 'Dill', 'B': 'Skip'},
            'book_station': 'Pine Box FM', 'made': True,
            'script': "B: Welcome to Book Time on Pine Box FM. An Actual Title. I'm Dill.\nA: I'm Skip.",
            'takes': [{'who': 'cohost', 'key': 'original-b.wav', 'seconds': 20},
                      {'who': 'dj', 'key': 'original-a.wav', 'seconds': 20}]}
        self.g['_LARDER'].append(row)
        original_audio = copy.deepcopy(row['takes'])
        seen = []
        async def correct(*a, **kw):
            seen.append(kw['angle'])
            kw['bank_to'].append({'script': 'A: Welcome to Book Time on Pine Box FM. An Actual Title. I am Dill.\nB: This is Skip.', 'made': False})
        self.g['dj_banter'] = correct
        self.assertTrue(asyncio.run(self.rt.prepare_book(self.due())))
        self.assertTrue(row['dynamic_superseded'])
        self.assertEqual(row['takes'], original_audio)
        self.assertEqual(row['book_source'], source)
        self.assertTrue(row['phase_repaired_by'])
        self.assertIn('A is Dill; B is Skip', seen[0])
        self.assertIn('wrong host', seen[0])
        active = self.rt.book_rows('book-15@100')
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]['book_source']['book_id'], 'actual')

    def test_completed_episode_without_quote_is_withheld_and_reauthors_discussion(self):
        source = {'title': 'An Actual Title', 'book_id': 'actual'}
        receipt = {'source': source, 'values': {'booksentence': 'Exact source sentence.'}}
        opening = {'dynamic_kind': 'book_time', 'dynamic_occurrence': 'book-15@100',
            'book_phase': 'opening', 'book_source': source, 'book_roulette': receipt,
            'book_station': 'Pine Box FM', 'book_cast': {'A': 'Dill', 'B': 'Skip'}, 'made': True,
            'script': 'A: Welcome to Book Time on Pine Box FM. An Actual Title. I am Dill.\nB: This is Skip.',
            'takes': [{'who': 'dj', 'seconds': 50}, {'who': 'cohost', 'seconds': 50}]}
        discussion = dict(opening, book_phase='discussion', sid='unquoted-discussion',
            script='\n'.join(('A: ' if i % 2 == 0 else 'B: ') + ' '.join(['a source idea'] * 12) for i in range(30)),
            takes=[{'who': 'dj' if i % 2 == 0 else 'cohost', 'key': 'kept-original.wav', 'seconds': 250 / 30} for i in range(30)])
        closing = dict(opening, book_phase='closing', script='A: Thanks for Book Time on Pine Box FM.\nB: Back to the music.',
            takes=[{'who': 'dj', 'seconds': 50}, {'who': 'cohost', 'seconds': 50}])
        self.g['_LARDER'].extend([opening, discussion, closing])
        coverage = self.rt.book_coverage(self.due())
        self.assertTrue(coverage['book_structure']['complete'])
        self.assertEqual(coverage['playable_seconds'], 450)
        self.assertFalse(coverage['book_quote']['recorded'])
        self.assertFalse(coverage['ready'])
        before_audio = copy.deepcopy(discussion['takes'])
        seen = []
        async def repair(*a, **kw):
            seen.append(kw['angle'])
            kw['bank_to'].append({'script': 'A: As this book says, "Exact source sentence."\nB: Let us discuss its meaning.', 'made': False})
        self.g['dj_banter'] = repair
        self.assertTrue(asyncio.run(self.rt.prepare_book(self.due())))
        self.assertIn('completed episode is missing its source quote', seen[0])
        self.assertTrue(discussion['dynamic_superseded'])
        self.assertEqual(discussion['takes'], before_audio)
        self.assertNotIn('dynamic_superseded', opening)
        self.assertNotIn('dynamic_superseded', closing)
        self.assertEqual(self.rt.last['book-15@100']['quotation_repairs'], 1)
        self.assertEqual(self.g['_LARDER'][-1]['book_repair_type'], 'quotation')
        self.assertTrue(self.g['_LARDER'][-1]['book_repair_accepted'])
        self.rt.last['book-15@100']['quotation_repairs'] = 2
        async def pending_record(part):
            return False
        self.g['larder_prepare'] = pending_record
        self.assertFalse(asyncio.run(self.rt.prepare_book(self.due())))
        self.assertEqual(self.rt.last['book-15@100']['quotation_repairs'], 2, 'recording retries preserve bounded counters')
        self.assertTrue(self.rt.book_coverage(self.due())['book_quote']['written'])
        self.assertFalse(self.rt.book_coverage(self.due())['ready'], 'repair must be recorded before it can air')

    def test_supercut_wall_has_dispatch_reserve_without_changing_source_audio_target(self):
        self.assertEqual(self.rt.windows()[-1], (58, 1.25, 'sfx_supercut'))
        chosen = segment_prompts.entry_view('sfx_supercut')['alternatives'][0]
        segment_prompts.patch_alternative('sfx_supercut', chosen['id'], {'config': {'target_seconds': 60, 'starts_at_minutes': [58]}})
        self.assertEqual(self.rt.windows()[-1], (58, 1.5, 'sfx_supercut'))
        segment_prompts.patch_alternative('sfx_supercut', chosen['id'], {'config': {'target_seconds': 30, 'starts_at_minutes': [58]}})
        self.assertEqual(self.rt.windows()[-1], (58, 1, 'sfx_supercut'))

    def test_prepare_endpoint_enqueues_without_starting_a_concurrent_writer(self):
        queued = []
        self.g['dynamic_system2_request_prepare'] = lambda kind: queued.append(kind) or {'worker': 'existing'}
        reply = self.client.post('/api/dynamic-segments/book_time/prepare', json={})
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(reply.json()['state'], 'queued')
        self.assertEqual(queued, ['book_time'])
        self.assertFalse(self.g['_LARDER'])
        self.assertFalse(self.resolver.calls)
        status = self.client.get('/api/dynamic-segments').json()
        self.assertEqual(status['requests']['book_time']['state'], 'queued')
        self.assertIn('pending', status)

    def test_invalid_json_types_and_unknown_kinds_return_clear_errors(self):
        self.assertEqual(self.client.post('/api/dynamic-segments/activate', json=[]).status_code, 400)
        self.assertEqual(self.client.post('/api/dynamic-segments/book_time/preview', json=[]).status_code, 400)
        self.assertEqual(self.client.post('/api/dynamic-segments/unknown/preview', json={}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
