import asyncio
import ast
from types import SimpleNamespace
import copy
from contextvars import ContextVar
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import wave

import dynamic_segments_system2 as bridge
import system2_runtime
import system3_runtime
import handoff_preparation
import book_prompt_runtime
import tests.test_book_roulette as book_fixtures

spec = importlib.util.spec_from_file_location('dynamic_s2_host_fixture', Path(__file__).with_name('test_system2_runtime.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class Dynamic:
    def __init__(self, host):
        self.host = host
        self.g = host.__dict__
        self.g['_SHELF'] = {'sfx_supercut': []}
        self.g['book_prompt_context'] = ContextVar('isolated_book_context', default=None)
        self.last, self.requests = {}, {}
        self.coverage_ready = True
        self.prepared = []
        self.write_unrecorded = False

    @staticmethod
    def source_entry(row): return row.get('entry', row)
    @staticmethod
    def occurrence(due): return str(due['slot_id']) + '@' + str(int(due['due_at']))
    def book_rows(self, occurrence):
        return [r for r in self.host._LARDER if r.get('dynamic_kind') == 'book_time' and r.get('dynamic_occurrence') == occurrence]
    def book_coverage(self, due, rows=None):
        rows = self.book_rows(self.occurrence(due)) if rows is None else rows
        phases = {r.get('book_phase') for r in rows}
        return {'ready': self.coverage_ready and phases >= {'opening', 'discussion', 'closing'},
                'measured_voice_seconds': len(rows) * 7}
    def call(self, name, *args, default=None):
        fn = self.g.get(name)
        return fn(*args) if callable(fn) else default
    async def prepare_book(self, due):
        self.prepared.append((copy.deepcopy(due), copy.deepcopy(system2_runtime.current_work())))
        for phase in ('closing', 'discussion', 'opening'):
            self.host.add('new-'+phase, kind='banter', ready=not self.write_unrecorded, dynamic_kind='book_time',
                dynamic_occurrence=self.occurrence(due), book_source={'id': 'actual-book', 'title': 'Actual Title'}, book_phase=phase)
        self.last[self.occurrence(due)] = {'coverage': self.book_coverage(due)}
        return True
    async def prepare_supercut(self, due):
        self.prepared.append((copy.deepcopy(due), copy.deepcopy(system2_runtime.current_work())))
        return None


class DynamicSystem2Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.now = 10801.0
        timer = mock.patch.object(system2_runtime.time, 'time', side_effect=lambda: self.now)
        timer.start(); self.addCleanup(timer.stop)
        self.host = fixture.Host(self.tmp.name, lambda: self.now)
        self.host._sched_hour_key = lambda hour=None: str(int((self.now if hour is None else hour)//3600*3600))
        self.host.SCHED_PREP_KIND.update(book_time='banter', sfx_supercut='ad')
        self.host.templates = [{'id': 'book-one', 'kind': 'book_time', 'minutes': 1},
                               {'id': 'ordinary', 'kind': 'banter', 'minutes': 1},
                               {'id': 'book-two', 'kind': 'book_time', 'minutes': 1},
                               {'id': 'promo', 'kind': 'sfx_supercut', 'minutes': 1}]
        self.rt = system2_runtime.System2Runtime(self.host)
        self.rt.store.now = lambda: self.now
        self.rt.config.update(engine='system2', horizon_hours=1)
        self.host.prep_has_assigned_work = mock.Mock(return_value=False)
        self.dynamic = Dynamic(self.host)
        self.adapter = bridge.DynamicSystem2(self.rt, self.dynamic).attach()
        templates = self.rt.templates(10800)
        plan = self.rt.store.plan_hour(10800, templates)
        self.rt._plans = [plan]
        self.slot = plan['slots'][0]
        self.due = self.adapter.due(self.slot)
        self.occ = self.dynamic.occurrence(self.due)

    def add_book(self, phase, identity=None, **extra):
        return self.host.add(identity or phase, kind='banter', dynamic_kind='book_time',
             dynamic_occurrence=self.occ, book_source={'id': 'actual-book', 'title': 'Actual Title'},
             book_phase=phase, **extra)

    def complete_book(self):
        return [self.add_book(phase) for phase in ('closing', 'discussion', 'opening')]

    def add_supercut(self, frames=8000*45):
        name = 'a'*32 + '.wav'
        with wave.open(str(self.host.PRODUCED_ADS_DIR/name), 'wb') as out:
            out.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            out.writeframes(b'\x09\x00' * frames)
        slot = self.rt._plans[0]['slots'][3]
        row = {'sid': 'source-promo', 'dynamic_kind': 'sfx_supercut',
               'dynamic_occurrence': self.dynamic.occurrence(self.adapter.due(slot)),
               'audio': name, 'source_only': True, 'source_plan': {'source_only': True, 'complete': True,
                     'clips': [{'sid': 'original', 'from_s0': 0, 'until_s': 45}]},
               'body_frames': frames, 'sample_rate': 8000, 'seconds': 45,
               'coverage': {'ready': True}, 'recorded_text': 'Actual station audio.'}
        self.dynamic.g['_SHELF']['sfx_supercut'].append(row)
        return row, slot

    async def test_templates_keep_exact_occurrence_binding_and_public_dynamic_clock(self):
        templates = self.rt.templates(10800)
        self.assertEqual([r['kind'] for r in templates], ['banter','banter','banter','ad'])
        for index in (0,2,3):
            self.assertTrue(templates[index]['require_slot_binding'])
            self.assertEqual(templates[index]['coverage_mode'], 'one_performance')
        self.assertEqual(self.rt._publish_clock(self.slot)['kind'], 'book_time')
        self.assertEqual(self.host._RADIO['sched_kind'], 'book_time')
        self.assertEqual(self.rt.current_slot_brief()['kind'], 'book_time')
        self.assertFalse(self.rt.fallback_due())
        self.assertEqual(self.due['slot_id'], 'book-one')
        self.assertEqual(self.occ, 'book-one@10800')

    async def test_budget_reserves_transport_inside_wall_without_fake_voice(self):
        budget = self.adapter.budget({'slot': {'minutes': 7.5}})
        self.assertEqual(budget['wall_target_seconds'], 450)
        self.assertEqual(budget['content_budget_seconds'], 430)
        self.assertEqual(budget['reserved_overhead_seconds'], 20)
        self.host.VOICE_BROADCAST_LEAD_MS = 30000
        smaller = self.adapter.budget({'slot': {'minutes': 7.5}})
        self.assertLess(smaller['content_budget_seconds'], 430)

    async def test_observed_short_take_count_reserves_actual_playback_overhead(self):
        self.host.VOICE_BROADCAST_LEAD_MS = 7000
        self.complete_book()
        closing = next(row for row in self.host._LARDER if row['book_phase']=='closing')
        closing['takes'] *= 12
        for row in self.host._LARDER:
            if row['book_phase']!='closing': row['takes'] *= 12
        due = {**self.due,'slot':{**self.due['slot'],'minutes':7.5}}
        budget = self.adapter.budget(due)
        observed = sum(len(row['takes']) for row in self.host._LARDER)
        self.assertEqual(observed,72)
        self.assertAlmostEqual(budget['reserved_overhead_seconds'],self.adapter.overhead(observed))
        self.assertLess(budget['content_budget_seconds'],430)
        self.assertEqual(budget['wall_target_seconds'],450)

    async def test_individual_parts_and_generic_banter_cannot_fill_book_slot(self):
        self.add_book('opening')
        self.host.add('generic', kind='banter')
        candidates = self.rt.inventory()
        bundle = next(c for c in candidates if c['source'].get('dynamic_kind'))
        self.assertFalse(bundle['ready'])
        self.assertFalse(bundle['eligible'])
        generic = next(c for c in candidates if c['id']=='generic')
        self.assertFalse(self.rt.store._slot_matches(generic, self.slot))
        self.assertNotIn('opening', [c['id'] for c in candidates])
        self.assertFalse(self.rt.media.resolve('banter', self.host._LARDER[0])['ready'])

    async def test_full_bundle_is_phase_ordered_measured_and_pinned_to_one_book(self):
        self.complete_book()
        candidate = next(c for c in self.rt.inventory() if c['source'].get('dynamic_kind'))
        self.assertTrue(candidate['ready'])
        self.assertEqual(candidate['seconds'], 21)
        self.assertAlmostEqual(candidate['air_seconds'], 27.8)
        self.assertEqual(candidate['slot_id'], self.slot['id'])
        self.assertEqual([x['book_phase'] for x in candidate['lines']], ['opening']*2+['discussion']*2+['closing']*2)
        self.assertEqual([x['id'] for x in candidate['lines']], list(map(str,range(6))))
        self.assertTrue(all(x['audio_hash'] for x in candidate['lines']))
        self.assertFalse(self.rt.store._slot_matches(candidate, self.rt._plans[0]['slots'][2]))
        self.host._LARDER[1]['book_source'] = {'id': 'different-title'}
        self.assertIsNone(self.adapter.book_bundle(self.due))

    async def test_full_coverage_and_current_audio_required_before_first_handoff(self):
        self.complete_book()
        self.dynamic.coverage_ready = False
        self.assertFalse(self.rt.inventory()[0]['ready'])
        self.dynamic.coverage_ready = True
        bundle = self.adapter.book_bundle(self.due)
        self.assertTrue(self.rt.media.resolve('banter', bundle)['ready'])
        clip = self.host._LARDER[0]['takes'][0]['clip']['path'].split('/')[-1]
        (self.host.VOICE_MEDIA_DIR/clip).unlink()
        self.assertFalse(self.rt.media.resolve('banter', bundle)['ready'])

    async def test_overlong_whole_bundle_is_refused_without_audio_truncation(self):
        self.complete_book()
        for i in range(8): self.add_book('discussion', 'extra'+str(i))
        row = self.adapter.book_bundle(self.due)
        resolved = self.rt.media.resolve('banter', row)
        self.assertFalse(resolved['ready'])
        self.assertIn('overhead exceeds', resolved['why'][0])

    async def test_unstamped_source_stock_binds_directly_without_inventory_or_row_rewrite(self):
        row,slot=self.add_supercut()
        self.assertNotIn('system2_slot',row)
        before=copy.deepcopy(row)
        candidate=self.rt.candidate('ad',row,row['sid'])
        self.assertTrue(candidate['ready'])
        self.assertEqual(candidate['slot_id'],slot['id'])
        self.assertEqual(row,before)
        self.rt.inventory()
        self.assertEqual(row,before)
        templates=self.rt.templates(10800)
        plan=self.rt.store.plan_hour(10800,templates,[candidate])
        bound=next(s for s in plan['slots'] if s['id']==slot['id'])
        self.assertEqual(bound['coverage_performances'],1)

    async def test_source_binding_refuses_stale_wrong_ambiguous_and_mismatched_plan_occurrences(self):
        row,slot=self.add_supercut()
        row['source_plan']['occurrence']=row['dynamic_occurrence']+'-another'
        self.assertFalse(self.rt.candidate('ad',row,row['sid'])['ready'])
        row['source_plan'].pop('occurrence')
        row['system2_slot']='another-native-slot'
        self.assertFalse(self.rt.candidate('ad',row,row['sid'])['ready'])
        row.pop('system2_slot')
        self.rt._plans[0]['slots'].append(copy.deepcopy(slot))
        self.assertFalse(self.rt.candidate('ad',row,row['sid'])['ready'])
        self.rt._plans[0]['slots'].pop()
        self.now=slot['deadline']+1
        self.assertFalse(self.rt.candidate('ad',row,row['sid'])['ready'])
        self.assertNotIn('system2_slot',row)

    async def test_one_source_performance_covers_75_second_wall_without_filling_speech(self):
        self.host.templates[3]['minutes']=1.25
        templates=self.rt.templates(10800)
        self.rt._plans=[self.rt.store.plan_hour(10800,templates)]
        row,slot=self.add_supercut()
        row['coverage'].update(target_seconds=45,content_budget_seconds=45,wall_target_seconds=75)
        candidate=next(candidate for candidate in self.rt.inventory()
                       if candidate['source'].get('dynamic_kind')=='sfx_supercut')
        self.assertEqual(candidate['slot_id'],slot['id'])
        self.assertTrue(candidate['ready'])
        self.assertEqual(candidate['seconds'],45)
        self.assertLessEqual(candidate['air_seconds'],75)
        plan=self.rt.store.plan_hour(10800,templates,[candidate])
        resolved=next(s for s in plan['slots'] if s['id']==slot['id'])
        self.assertEqual(resolved['target_seconds'],75)
        self.assertEqual(resolved['coverage_mode'],'one_performance')
        self.assertEqual(resolved['ready_seconds'],45)
        self.assertEqual(resolved['coverage_performances'],1)
        self.assertEqual(resolved['performance_debt'],0)
        self.assertEqual(len(resolved['allocations']),1)
        self.assertEqual(resolved['allocations'][0]['candidate']['source']['coverage']['target_seconds'],45)
        own=next(j for j in self.rt.store.jobs() if j['slot_id']==slot['id'])
        self.assertFalse(own['coverage_missing'])
        self.assertEqual(len(row['source_plan']['clips']),1)
        self.host.dj_banter.assert_not_called()

    async def test_supercut_has_original_audio_proof_and_never_a_new_voice(self):
        row, slot = self.add_supercut()
        candidates = self.rt.inventory()
        candidate = next(c for c in candidates if c['source'].get('dynamic_kind')=='sfx_supercut')
        self.assertTrue(candidate['ready'])
        self.assertEqual(candidate['seconds'], 45)
        self.assertEqual(candidate['slot_id'], slot['id'])
        self.assertEqual(candidate['lines'][0]['voice'], 'source-clips')
        self.assertEqual(candidate['lines'][0]['path'], '/ads-audio/'+row['audio'])
        self.assertEqual(self.rt.media.resolve('ad', row)['media_kind'], 'produced')
        row['body_frames'] += 1000
        self.assertFalse(self.rt.media.resolve('ad', row)['ready'])
        row['body_frames'] -= 1000
        row['source_plan']['source_only'] = False
        self.assertFalse(self.rt.media.resolve('ad', row)['ready'])
        self.host.dj_banter.assert_not_called()

    async def test_handoff_consumes_source_only_after_accepted_transport(self):
        self.complete_book()
        bundle = self.adapter.book_bundle(self.due)
        resolved = self.rt.media.resolve('banter', bundle)
        hook = mock.Mock()
        self.adapter.original['deliver'] = mock.AsyncMock(return_value=False)
        self.assertFalse(await self.adapter.deliver(resolved, hook, lambda:True, entry_overrides={}))
        self.assertTrue(all(not r.get('dynamic_handed_off') for r in self.host._LARDER))
        async def accepted(resolved, on_handoff, can_handoff, entry_overrides=None): on_handoff(); return True
        self.adapter.original['deliver'] = mock.AsyncMock(side_effect=accepted)
        self.assertTrue(await self.adapter.deliver(resolved, hook, lambda:True, entry_overrides={}))
        self.assertEqual(hook.call_count, 1)
        self.assertTrue(all(r.get('dynamic_handed_off') for r in self.host._LARDER))

    async def test_dynamic_preparation_uses_existing_job_lease_and_work_context(self):
        self.adapter.requested['book_time'] = self.slot['id']
        self.assertIsNone(await self.rt._claim_preparation(['banter'], 3600))
        self.assertEqual(len(self.dynamic.prepared), 1)
        due, work = self.dynamic.prepared[0]
        self.assertEqual(due['slot_id'], 'book-one')
        self.assertEqual(due['due_at'], 10800)
        self.assertEqual(work['dynamic_kind'], 'book_time')
        self.assertEqual(work['slot_id'], self.slot['id'])
        self.assertTrue(all(r.get('system2_slot')==self.slot['id'] for r in self.host._LARDER))
        self.assertIsNone(system2_runtime.current_work())
        jobs = self.rt.store.jobs()
        claimed = next(j for j in jobs if j['slot_id']==self.slot['id'])
        self.assertEqual(claimed['state'], 'completed')
        self.host.alt_prep_road.assert_not_called()
        self.host.dj_banter.assert_not_called()

    async def test_real_core_dispatch_uses_atomic_bundle_and_tracks_only_actual_handoff(self):
        self.complete_book()
        self.rt._last_refresh = 0
        await self.rt.refresh(force=True, want_status=False)
        self.assertTrue(await self.rt.dispatch())
        self.assertEqual(len(self.host.aired), 1)
        heard = self.host.aired[0]
        self.assertEqual(heard['dynamic_kind'], 'book_time')
        self.assertEqual(len(heard['takes']), 6)
        self.assertTrue(all(r.get('dynamic_handed_off') for r in self.host._LARDER))
        reservations = self.rt.store.reservations()
        own = next(r for r in reservations if r['slot_id']==self.slot['id'])
        self.assertEqual(own['state'], 'playing')
        self.assertEqual(own['heard_seconds'], 0)
        self.rt.acknowledge(heard)
        own = next(r for r in self.rt.store.reservations() if r['slot_id']==self.slot['id'])
        self.assertEqual(own['state'], 'completed')
        self.assertEqual(own['heard_seconds'], own['actual_seconds'])
        self.host.dj_banter.assert_not_called()

    async def test_stored_receipt_is_restored_for_later_media_and_air_only(self):
        self.complete_book()
        receipt = {'source': {'id': 'actual-book'}, 'booksentence': 'Actual source words'}
        for row in self.host._LARDER:
            row.update(book_roulette=receipt, book_config={'book_binding':'actual-book'},
                       book_prompt_occurrence='book_time:canonical-memo')
        bundle = self.adapter.book_bundle(self.due)
        self.assertEqual(bundle['book_roulette'], receipt)
        variable = self.dynamic.g['book_prompt_context']
        seen = []
        original = self.adapter.original['resolve']
        def checking(kind, row):
            seen.append(copy.deepcopy(variable.get()))
            return original(kind, row)
        self.adapter.original['resolve'] = checking
        resolved = self.rt.media.resolve('banter', bundle)
        self.assertTrue(resolved['ready'])
        self.assertTrue(all(r['book_roulette']==receipt for r in seen))
        self.assertIsNone(variable.get())
        async def checking_air(resolved, on_handoff, can_handoff, entry_overrides=None):
            self.assertEqual(variable.get()['occurrence'],'book_time:canonical-memo')
            on_handoff(); return True
        self.adapter.original['deliver'] = checking_air
        self.assertTrue(await self.rt.media.deliver(resolved, mock.Mock(), lambda:True))
        self.assertIsNone(variable.get())

    async def test_new_book_scripts_visit_recording_before_becoming_ready(self):
        self.dynamic.write_unrecorded = True
        self.adapter.requested['book_time'] = self.slot['id']
        self.assertIsNone(await self.rt._claim_preparation(['banter'],3600))
        self.assertEqual(self.host.larder_prepare.call_count, 3)
        self.assertTrue(all(r.get('ready') for r in self.host._LARDER))
        self.assertEqual(self.host.alt_candidates('banter'), [])
        own = next(job for job in self.rt.store.jobs() if job['slot_id']==self.slot['id'])
        self.assertEqual(own['state'], 'completed')

    async def test_original_system3_bindings_and_review_receipts_survive_assembly(self):
        self.complete_book()
        original_ids = []
        for row in self.host._LARDER:
            cid = 'original-conversation-'+row['book_phase']
            ids = {str(i): cid+':'+str(i) for i in range(2)}
            original_ids += list(ids.values())
            row.update(system3={'mode':'active','conversation_id':cid,'turns':ids,'planned_turns':2},
                turn_dice={key:{'s3':{'turn_id':value}} for key,value in ids.items()},
                turn_source={'0':'original library passage'},
                handoff_receipt={'version':1,'status':'ready','final_digest':handoff_preparation.text_digest(row['script'])})
        finder = system3_runtime.System3Runtime.__new__(system3_runtime.System3Runtime)
        finder.host = self.host
        finder.turns_cache = {}
        finder.fail = mock.Mock()
        self.dynamic.g['system3_turn_id_for'] = finder.turn_id_for
        self.dynamic.g['_s3_active'] = lambda:True
        resolved = self.rt.media.resolve('banter',self.adapter.book_bundle(self.due))
        self.assertTrue(resolved['ready'],resolved['why'])
        entry = resolved['entry']
        self.assertEqual(set(entry['system3']['turns'].values()),set(original_ids))
        self.assertEqual(entry['system3']['assembly'],'ordered_recorded_parts')
        self.assertEqual(len(entry['system3_components']),3)
        self.assertTrue(handoff_preparation.receipt_matches_script(entry))
        self.assertEqual(entry['lines'],6)
        self.assertEqual(entry['chunks'],6)
        self.assertEqual(entry['made'],6)
        self.assertTrue(entry['frozen'])
        self.assertTrue(entry['render_stream'])
        for take in resolved['takes']:
            self.assertIn(finder.turn_id_for(entry,take['text'],take['who']),original_ids)
        self.host._LARDER[0]['handoff_receipt']['final_digest']='changed'
        self.assertFalse(self.rt.media.resolve('banter',self.adapter.book_bundle(self.due))['ready'])

    async def test_actual_prepared_air_function_reaches_recorded_stream_with_complete_fields(self):
        self.complete_book()
        resolved = self.rt.media.resolve('banter',self.adapter.book_bundle(self.due))
        app_source = Path(__file__).resolve().parents[1].joinpath('app.py').read_text(encoding='utf-8-sig')
        source = 'async def _banter_air('+app_source.split('async def _banter_air(',1)[1].split('\n\n# How the pair take a call.',1)[0]
        speak = mock.AsyncMock(return_value=[])
        env = {'Any':object,'copy':copy,'asyncio':asyncio,'time':system2_runtime.time,
            '_s3_active':lambda:False,'script_has_forgotten_line':lambda *a:False,
            '_system2_repeat_rows_async':mock.AsyncMock(return_value=True),
            'airlog_round_hint':mock.Mock(),'screenplay_round_open':mock.Mock(return_value={}),
            '_GALLERY_PENDING':[],'dialogue_audio_ready':lambda *a:True,
            '_script_repeats':lambda *a:[],'pipeline_log':mock.Mock(),'weather_apply':mock.Mock(),
            'banter_turns':self.host.banter_turns,'talk_is_incessant':lambda:False,
            'speak_turns':speak,'_turn_source_map':lambda e:e.get('turn_source',{}),
            '_turn_dice_map':lambda e:e.get('turn_dice',{}),'dj_settings':lambda:{},
            'screenplay_round_stamp':mock.Mock(),'round_air_mark':mock.Mock(),
            '_call_scenario_air_target':mock.Mock(return_value=None),'chain_resume_soon':mock.Mock(),
            'sfx_punctuate':mock.Mock(),'_RADIO':self.host._RADIO}
        exec(compile(ast.parse(source),'actual-app-banter-air','exec'),env)
        await env['_banter_air'](resolved['entry'],None,ready_takes=resolved['takes'],
                                on_handoff=mock.Mock(),can_handoff=lambda:True)
        speak.assert_awaited_once()
        self.assertEqual(speak.call_args.args[2],6)
        self.assertTrue(speak.call_args.kwargs['render_stream'])
        self.assertTrue(speak.call_args.kwargs['recorded'])
        self.assertEqual(len(speak.call_args.kwargs['ready_takes']),6)

    async def test_late_deadline_refuses_new_book_writing(self):
        self.now = self.slot['deadline']-10
        self.adapter.requested['book_time'] = self.slot['id']
        self.assertIsNone(await self.rt._claim_preparation(['banter'],3600))
        self.assertEqual(self.dynamic.prepared,[])
        own = next(job for job in self.rt.store.jobs() if job['slot_id']==self.slot['id'])
        self.assertEqual(own['state'],'pending')
        self.assertIn('Too little time',own['result']['why'])

    async def test_only_actual_verified_book_protocol_and_source_can_recur(self):
        books = book_fixtures.BookRouletteTests()
        with mock.patch('zipfile.time.localtime',return_value=(2026,10,4,0,0,0,6,277,0)):
            books.setUp()
        self.addCleanup(books.tearDown)
        guard = book_prompt_runtime.BookPromptRuntime({'BOOK_MODE':books.mode,
            'dj_settings':lambda:{'station_name':'Pine Box FM','host_name':'Host','cohost_name':'Partner'}})
        receipt = await guard.resolver().resolve_async('{book:River Gardens} {booksegment} {booksentence}',
            weighted=books.pick, occurrence='actual-library-recurrence-proof')
        self.dynamic.g.update(book_prompt_context=guard.context, book_repeat_material=guard.repeat_material,
                              norepeat_text_used=lambda text:False)
        self.host.content_gate_enabled = lambda gate:gate in ('tint','repetition')
        self.complete_book()
        quote = receipt['values']['booksentence']
        welcome = 'Welcome to Book Time on Pine Box FM.'
        closing = 'Thank you for Book Time on Pine Box FM.'
        for row in self.host._LARDER:
            row.update(book_source=receipt['source'], book_roulette=receipt,
                book_config={}, book_prompt_occurrence='actual-library-recurrence-proof')
            if row['book_phase']=='opening': row['takes'][0]['text']=welcome
            if row['book_phase']=='discussion': row['takes'][0]['text']=quote
            if row['book_phase']=='closing': row['takes'][0]['text']=closing
            row['script']='\n'.join(('A' if i==0 else 'B')+': '+take['text'] for i,take in enumerate(row['takes']))
        self.rt.store.record_external(welcome,receipt_id='old-required-welcome')
        self.rt.store.record_external(quote,receipt_id='old-real-source-quote')
        row = self.adapter.book_bundle(self.due)
        candidate = self.rt.candidate('banter',row,row['id'])
        self.assertTrue(candidate['ready'])
        self.assertTrue(candidate['eligible'],candidate['why'])
        self.assertFalse(candidate['repeat_guard'])
        self.assertTrue(candidate['audio_hashes'])
        self.assertEqual(candidate['lines'][0]['text'],welcome)
        entry = self.rt.media.resolve('banter',row)['entry']
        self.assertTrue(self.rt.repeat_allowed([line['text'] for line in candidate['lines']],entry))
        ordinary = self.host.add('ordinary-repeat-proof',kind='banter')
        self.assertTrue(self.rt.candidate('banter',ordinary)['repeat_guard'])
        discussion = next(part for part in self.host._LARDER if part.get('book_phase')=='discussion')
        reaction = 'This repeated opinion stays.'
        discussion['takes'][0]['text']='"'+quote+'" '+reaction
        discussion['script']='A: '+discussion['takes'][0]['text']+'\nB: '+discussion['takes'][1]['text']
        self.dynamic.g['norepeat_text_used'] = lambda text:reaction in text
        blocked = self.rt.candidate('banter',self.adapter.book_bundle(self.due),row['id'])
        self.assertFalse(blocked['eligible'])
        live_entry = self.rt.media.resolve('banter',self.adapter.book_bundle(self.due))['entry']
        self.assertFalse(self.rt.repeat_allowed([discussion['takes'][0]['text']],live_entry))
        self.assertIsNone(guard.context.get())

    async def test_writer_priority_yields_next_legacy_intake_without_preempting_active_owner(self):
        self.dynamic.g['_LARDER_WRITING']=[True]
        job={'slot_id':self.slot['id'],'revision':self.slot['revision'],
             'hard_deadline':self.now+200,'template':self.slot}
        work={}
        wait=asyncio.create_task(self.adapter.wait_for_book_writer(job,work,wait_seconds=.15))
        await asyncio.sleep(.02)
        self.assertTrue(self.dynamic.g['_LARDER_WRITING'][0])
        self.assertTrue(self.host.prep_has_assigned_work('banter'))
        self.assertFalse(self.host.prep_has_assigned_work('news'))
        self.assertEqual(self.dynamic.prepared,[])
        self.dynamic.g['_LARDER_WRITING'][0]=False  # only the current owner releases it
        self.assertTrue(await wait)
        self.assertFalse(self.dynamic.g['_LARDER_WRITING'][0])
        self.adapter.release_writer_ticket(self.occ)
        self.assertFalse(self.host.prep_has_assigned_work('banter'))

    async def test_writer_ticket_timeout_preserves_owner_and_expires_without_global_hold(self):
        self.dynamic.g['_LARDER_WRITING']=[True]
        job={'slot_id':self.slot['id'],'revision':self.slot['revision'],
             'hard_deadline':self.now+200,'template':self.slot}
        self.assertFalse(await self.adapter.wait_for_book_writer(job,{},wait_seconds=.01))
        self.assertTrue(self.dynamic.g['_LARDER_WRITING'][0])
        self.assertTrue(self.host.prep_has_assigned_work('banter'))
        self.now+=131
        self.assertFalse(self.host.prep_has_assigned_work('banter'))
        self.assertIsNone(self.adapter.writer_ticket)
        self.assertTrue(self.dynamic.g['_LARDER_WRITING'][0])

    async def test_real_native_job_waits_for_current_owner_then_releases_one_turn_priority(self):
        self.dynamic.g['_LARDER_WRITING']=[True]
        self.adapter.requested['book_time']=self.slot['id']
        task=asyncio.create_task(self.rt._claim_preparation(['banter'],3600))
        for _ in range(150):
            if self.adapter.writer_ticket or task.done():
                break
            await asyncio.sleep(.02)
        self.assertTrue(self.dynamic.g['_LARDER_WRITING'][0])
        self.assertEqual(self.dynamic.prepared,[])
        self.assertTrue(self.host.prep_has_assigned_work('banter'))
        self.dynamic.g['_LARDER_WRITING'][0]=False
        await task
        self.assertEqual(len(self.dynamic.prepared),1)
        self.assertIsNone(self.adapter.writer_ticket)
        claimed=next(j for j in self.rt.store.jobs() if j['slot_id']==self.slot['id'])
        self.assertEqual(claimed['state'],'completed')
        self.assertFalse(self.host.prep_has_assigned_work('banter'))

    async def test_ordinary_preparation_retains_existing_producer(self):
        self.adapter.original['_claim_preparation'] = mock.AsyncMock(return_value={'kind':'news','template':{}})
        job = await self.rt._claim_preparation(['news'],3600)
        self.assertEqual(job['kind'], 'news')
        self.assertEqual(self.dynamic.prepared, [])

    async def test_explicit_request_wakes_worker_and_targets_first_future_book(self):
        self.rt.refresh = mock.AsyncMock()
        self.rt.prepare_spawn = mock.Mock(return_value=None)
        result = await self.adapter.request_prepare('book_time')
        self.assertEqual(result['state'], 'queued')
        self.assertEqual(result['slot_id'], self.rt._plans[0]['slots'][2]['id'])
        self.assertEqual(self.dynamic.prepared, [])
        self.rt.prepare_spawn.assert_called_once()
        self.host.dj_banter.assert_not_called()

if __name__ == '__main__': unittest.main()
