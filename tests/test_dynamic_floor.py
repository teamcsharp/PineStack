import copy
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import dynamic_floor


class DynamicFloorTests(unittest.TestCase):
    def setUp(self):
        self.candidate = {'id': 'sc-source', 'ready': True, 'eligible': True,
            'slot_id': 'hour:supercut', 'source': {'dynamic_kind': 'sfx_supercut',
                'dynamic_occurrence': 'supercut@1000'}}
        self.slot = {'id': 'hour:supercut', 'template_id': 'supercut',
            'dynamic_kind': 'sfx_supercut', 'start': 1000, 'deadline': 1075,
            'allocations': [{'candidate': {'id': 'sc-source'}}]}
        self.runtime = types.SimpleNamespace(enabled=True,
            _plans=[{'slots': [self.slot]}], _candidates=[self.candidate])
        self.namespace = {'_system2': lambda: self.runtime,
            'VOICE_BROADCAST_LEAD_MS': 7000, '_PAGE_AIR_UNTIL': [0]}
        self.floor = dynamic_floor.DynamicFloor(self.namespace)
        self.clock = patch.object(dynamic_floor.time, 'time', return_value=990)
        self.clock.start(); self.addCleanup(self.clock.stop)

    def test_ready_allocated_supercut_keeps_a_new_legacy_clip_from_crossing_its_start(self):
        self.assertFalse(self.floor.yield_now({}, seconds=1))
        self.assertTrue(self.floor.yield_now({}, seconds=5))
        self.assertEqual(self.floor.last['candidate_id'], 'sc-source')

    def test_due_book_performance_yields_only_verified_native_allocation(self):
        self.slot.update(dynamic_kind='book_time', start=980, deadline=1430)
        self.candidate['source'].update(dynamic_kind='book_time', dynamic_occurrence='supercut@980')
        self.assertTrue(self.floor.yield_now({'prep_kind': 'caller'}))
        self.slot['allocations'] = []
        self.assertFalse(self.floor.yield_now({'prep_kind': 'caller'}))

    def test_missing_unready_or_unbound_candidate_cannot_stop_ordinary_speech(self):
        for field, value in [('ready', False), ('eligible', False), ('slot_id', 'other')]:
            with self.subTest(field=field):
                before = copy.deepcopy(self.candidate)
                self.candidate[field] = value
                self.assertFalse(self.floor.yield_now({}, seconds=90))
                self.candidate.clear(); self.candidate.update(before)
        self.runtime._candidates = []
        self.assertFalse(self.floor.yield_now({}, seconds=90))

    def test_generic_ad_or_other_occurrence_cannot_claim_the_dynamic_boundary(self):
        for source in ({'dynamic_kind': 'ad'},
            {'dynamic_kind': 'sfx_supercut', 'dynamic_occurrence': 'supercut@2000'}):
            self.candidate['source'] = source
            self.assertFalse(self.floor.yield_now({}, seconds=90))

    def test_native_owner_manual_whole_and_same_occurrence_finish_their_contract(self):
        self.assertFalse(self.floor.yield_now({'_system2': {'reservation_id': 'owned'}}, seconds=90))
        self.assertFalse(self.floor.yield_now({}, seconds=90, by_hand=True))
        self.assertFalse(self.floor.yield_now({}, seconds=90, whole=True))
        self.assertFalse(self.floor.yield_now({'system2_slot': 'hour:supercut'}, seconds=90))
        self.assertFalse(self.floor.yield_now({'dynamic_occurrence': 'supercut@1000'}, seconds=90))

    def test_published_audio_is_read_without_cancellation_or_debt_changes(self):
        before = copy.deepcopy((self.runtime._plans, self.runtime._candidates))
        self.namespace['_PAGE_AIR_UNTIL'][0] = 1001
        self.assertTrue(self.floor.yield_now({}, seconds=0))
        self.assertEqual((self.runtime._plans, self.runtime._candidates), before)
        self.assertEqual(self.namespace['_PAGE_AIR_UNTIL'], [1001])

    def test_missed_slot_and_disabled_engine_never_interrupt_or_replay(self):
        self.slot['deadline'] = 989
        self.assertFalse(self.floor.yield_now({}, seconds=90))
        self.slot['deadline'] = 1075
        self.runtime.enabled = False
        self.assertFalse(self.floor.yield_now({}, seconds=90))

    def test_install_is_idempotent_and_uses_no_new_dispatch_task(self):
        first = dynamic_floor.install(None, self.namespace)
        self.assertIs(dynamic_floor.install(None, self.namespace), first)
        self.assertEqual(set(self.namespace) - {'_system2', 'VOICE_BROADCAST_LEAD_MS', '_PAGE_AIR_UNTIL'},
                         {'DYNAMIC_FLOOR_RUNTIME', 'dynamic_floor_yield', 'dynamic_floor_wait_allowed', 'dynamic_floor_render_wait'})

    def test_malformed_cached_metadata_fails_open_for_ordinary_air(self):
        self.assertTrue(self.floor.yield_now({'_ready_slot': 'bad'}, seconds=90))
        self.slot['allocations'] = ['bad', {'candidate': 'bad'}, None]
        self.assertFalse(self.floor.yield_now({}, seconds=90))
        self.runtime._plans = [{'slots': 1}]
        self.assertFalse(self.floor.yield_now({}, seconds=90))
        self.runtime._candidates = 1
        self.assertFalse(self.floor.yield_now({}, seconds=90))
        self.runtime._plans = ['bad', None, {'slots': [None, 'bad']}]
        self.assertFalse(self.floor.yield_now({}, seconds=90))
        def unavailable():
            raise RuntimeError('initializing')
        self.namespace['_system2'] = unavailable
        self.assertFalse(self.floor.yield_now({}, seconds=90))

    def test_real_native_store_allocation_is_recognized_without_store_reads_on_air(self):
        import tempfile
        from system2 import System2Store
        with tempfile.TemporaryDirectory() as directory:
            store = System2Store(Path(directory) / 'native.sqlite3', now=lambda: 990)
            candidate = {**copy.deepcopy(self.candidate), 'kind': 'ad', 'seconds': 44.883,
                'air_seconds': 57.783, 'repeat_guard': False, 'script': 'Verified station mashup.',
                'lines': [{'id': '0', 'text': 'Verified station mashup.', 'seconds': 44.883,
                           'audio_hash': 'a' * 64}], 'audio_hashes': ['a' * 64]}
            hour = store.plan_hour(1000, [{'id': 'supercut', 'kind': 'ad', 'seconds': 75,
                'target_seconds': 45, 'dynamic_kind': 'sfx_supercut',
                'require_slot_binding': True, 'coverage_mode': 'one_performance'}],
                [candidate], plan_id='hour')
            self.assertEqual(hour['slots'][0]['allocations'][0]['candidate']['id'], 'sc-source')
            self.runtime._plans = [hour]
            self.runtime._candidates = [candidate]
            with patch.object(store, '_connect', side_effect=AssertionError('no SQLite on air')):
                self.assertTrue(self.floor.yield_now({}, seconds=5))

    def test_unhanded_native_dynamic_wait_requires_remaining_audio_fit(self):
        self.candidate['air_seconds'] = 58
        meta = {'dynamic_kind':'sfx_supercut', 'dynamic_occurrence':'supercut@1000',
            '_system2':{'reservation_id':'native-owned', 'candidate_id':'sc-source', 'slot_id':'hour:supercut'},
            '_ready_slot':{'occurrence':'hour:supercut', 'deadline':1075}}
        with patch.object(dynamic_floor.time, 'time', return_value=1001):
            self.assertTrue(self.floor.wait_allowed(meta, seconds=44))
        with patch.object(dynamic_floor.time, 'time', return_value=1030):
            self.assertFalse(self.floor.wait_allowed(meta, seconds=44))
            meta['_system2']['awaiting_ack'] = True
            self.assertTrue(self.floor.wait_allowed(meta, seconds=44), 'accepted audible work finishes its contract')
            meta['_system2']['awaiting_ack'] = False
            meta['_dynamic_floor_started'] = True
            self.assertTrue(self.floor.wait_allowed(meta, seconds=44), 'a local proven publication remains authoritative when copied proof predates the ACK flag')
        self.assertEqual(self.namespace['_PAGE_AIR_UNTIL'], [0])

    def test_other_queued_native_work_yields_only_to_verified_ready_dynamic_allocation(self):
        meta = {'_system2':{'reservation_id':'older-native', 'candidate_id':'older', 'slot_id':'hour:older'},
            '_ready_slot':{'occurrence':'hour:older', 'deadline':985}}
        self.assertFalse(self.floor.wait_allowed(meta, seconds=15))
        self.slot['allocations'] = []
        self.assertTrue(self.floor.wait_allowed(meta, seconds=15), 'ordinary overrun policy remains unchanged without a competing ready dynamic allocation')
        self.slot['allocations'] = [{'candidate':{'id':'sc-source'}}]
        self.assertTrue(self.floor.wait_allowed(meta, seconds=15, by_hand=True))
        self.assertTrue(self.floor.wait_allowed(meta, seconds=15, whole=True))

    def test_silent_unpublished_render_returns_without_cancelling_published_audio(self):
        import asyncio
        async def exercise():
            clock = [990.0]; stopped = asyncio.Event()
            async def pending():
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
            async def advance():
                await asyncio.sleep(.01); clock[0] = 1001
            self.namespace['_PAGE_AIR_UNTIL'][0] = 998
            with patch.object(dynamic_floor.time, 'time', side_effect=lambda:clock[0]):
                changer = asyncio.create_task(advance())
                finished, result = await self.floor.wait_render(pending(), {})
                await changer
            self.assertFalse(finished); self.assertIsNone(result)
            self.assertTrue(stopped.is_set())
            self.assertEqual(self.namespace['_PAGE_AIR_UNTIL'], [998])
        asyncio.run(exercise())

    def test_actual_floor_acquisition_withdraws_only_its_waiter_and_keeps_owner(self):
        import asyncio
        source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
        start = source.index('async def _floor_take('); end = source.index('\ndef _floor_stage', start)
        namespace = {'asyncio':asyncio, 'time':dynamic_floor.time, '_floor_busy':lambda:True}
        exec(compile('from __future__ import annotations\n'+source[start:end], 'actual-floor-acquire', 'exec'), namespace)
        async def exercise():
            lock = asyncio.Lock(); await lock.acquire()
            other = object(); owner = {'task':other, 'at':980, 'label':'published original audio'}
            namespace.update(_FLOOR_LOCK=lock, _FLOOR_OWNER=owner)
            permit = [True]
            async def invalidate():
                await asyncio.sleep(.01); permit[0] = False
            changer = asyncio.create_task(invalidate())
            self.assertIsNone(await namespace['_floor_take']('unpublished waiter', can_wait=lambda:permit[0]))
            await changer
            self.assertTrue(lock.locked()); self.assertIs(owner['task'],other)
            lock.release()
            self.assertTrue(await namespace['_floor_take']('new actual owner', can_wait=lambda:True))
            self.assertIs(owner['task'], asyncio.current_task(), 'lock ownership remains on the speech task, not a timer helper')
            self.assertFalse(await namespace['_floor_take']('reentrant unchanged'))
            lock.release()
        asyncio.run(exercise())

    def test_actual_floorless_function_with_new_boundary_checks_compiles(self):
        source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
        start = source.index('async def _speak_turns_floorless(')
        end = source.index('\ndef ', start + 1)
        function = source[start:end]
        compile('from __future__ import annotations\n' + function, 'actual-floorless-app-slice', 'exec')
        self.assertEqual(function.count('dynamic_floor_yield('), 4)
        self.assertIn('await _paged_settle(_paged_until)', function)
        self.assertEqual(function.count('_render_wait('), 2)
        wrapper_start = source.index('async def speak_turns(')
        wrapper_end = source.index('\n_WITHDRAWN_LAST:', wrapper_start)
        wrapper = source[wrapper_start:wrapper_end]
        compile('from __future__ import annotations\n'+wrapper, 'actual-speak-floor-wrapper', 'exec')
        self.assertIn('can_wait=_can_wait', wrapper)
        self.assertIn('if _owned is None:', wrapper)


if __name__ == '__main__':
    unittest.main()
