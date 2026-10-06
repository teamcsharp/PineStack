"""Native due dynamic dispatch uses existing reservation and transport gates."""
import asyncio
import copy
import linecache
from types import SimpleNamespace
import unittest
from unittest import mock

import tests.test_dynamic_segments_system2 as fixtures
import system2_runtime as core
import dynamic_segments_system2 as bridge


class DueDynamicDispatchTests(unittest.IsolatedAsyncioTestCase):
    add_book = fixtures.DynamicSystem2Tests.add_book
    complete_book = fixtures.DynamicSystem2Tests.complete_book
    add_supercut = fixtures.DynamicSystem2Tests.add_supercut

    def setUp(self):
        # Use temporary WAV/SQLite fixtures with the installed main modules.
        fixtures.DynamicSystem2Tests.setUp(self)

    async def asyncTearDown(self):
        await self.adapter.stop_dispatch()

    async def ready_book(self):
        self.complete_book()
        await self.rt.refresh(force=True, want_status=False)
        self.slot = self.rt._plans[0]['slots'][0]
        self.assertEqual(self.adapter.due_dispatch_slot()['id'], self.slot['id'])

    async def wait_for(self, predicate):
        async def waiting():
            while not predicate():
                await asyncio.sleep(.005)
        await asyncio.wait_for(waiting(), timeout=2)

    async def test_parked_generic_writer_does_not_prevent_one_native_handoff_and_ack(self):
        await self.ready_book()
        release = asyncio.Event()
        generic = asyncio.create_task(release.wait(), name='isolated-generic-model-wait')
        try:
            self.adapter.start_dispatch()
            await self.wait_for(lambda: len(self.host.aired) == 1)
            await self.wait_for(lambda: bool(self.rt._dispatched))
            self.assertFalse(generic.done())
            self.assertFalse(await self.adapter.dispatch_due())
            self.assertEqual(len(self.host.aired), 1)
            owned = [r for r in self.rt.store.reservations() if r['slot_id'] == self.slot['id']]
            self.assertEqual(len(owned), 1)
            self.assertEqual(owned[0]['state'], 'playing')
            self.assertEqual(owned[0]['heard_seconds'], 0)
            self.rt.acknowledge(self.host.aired[0])
            owned = [r for r in self.rt.store.reservations() if r['slot_id'] == self.slot['id']]
            self.assertEqual(owned[0]['state'], 'completed')
            self.assertEqual(owned[0]['heard_seconds'], owned[0]['actual_seconds'])
            self.host.dj_banter.assert_not_called()
        finally:
            release.set()
            await generic

    async def test_source_only_supercut_uses_existing_native_reservation_and_handoff(self):
        self.host.templates[3]['minutes'] = 1.25
        self.rt._plans = [self.rt.store.plan_hour(10800, self.rt.templates(10800))]
        row, slot = self.add_supercut()
        self.now = slot['start'] + .1
        await self.rt.refresh(force=True, want_status=False)
        received = []
        async def air(resolved, on_handoff, can_handoff, entry_overrides=None):
            self.assertEqual(resolved['media_kind'], 'produced')
            self.assertTrue(resolved['entry']['source_plan']['source_only'])
            self.assertTrue(can_handoff())
            received.append(copy.deepcopy(entry_overrides))
            on_handoff()
            return True
        self.adapter.original['deliver'] = mock.AsyncMock(side_effect=air)
        self.assertTrue(await self.adapter.dispatch_due())
        self.assertEqual(len(received), 1)
        self.assertTrue(row['dynamic_handed_off'])
        self.assertFalse(await self.adapter.dispatch_due())
        owned = [r for r in self.rt.store.reservations() if r['slot_id'] == slot['id']]
        self.assertEqual(len(owned), 1)
        self.assertEqual(owned[0]['state'], 'playing')
        self.host.dj_banter.assert_not_called()

    async def test_cached_precheck_excludes_off_paused_unready_refused_and_wrong_source(self):
        await self.ready_book()
        self.rt.dispatch = mock.AsyncMock(return_value=False)
        plan = copy.deepcopy(self.rt._plans)
        candidates = copy.deepcopy(self.rt._candidates)
        cases = ['off', 'paused', 'legacy', 'slot_disabled', 'future', 'expired',
                 'ordinary', 'unallocated', 'unavailable', 'not_ready', 'ineligible',
                 'blocked', 'wrong_occurrence', 'wrong_slot', 'missing_candidate']
        for case in cases:
            with self.subTest(case=case):
                self.rt._plans = copy.deepcopy(plan)
                self.rt._candidates = copy.deepcopy(candidates)
                self.now = 10801
                self.host._RADIO['on'] = True
                self.host.paused = False
                self.rt.config['engine'] = 'system2'
                slot = self.rt._plans[0]['slots'][0]
                candidate_id = slot['allocations'][0]['candidate']['id']
                candidate = next(row for row in self.rt._candidates if row['id'] == candidate_id)
                if case == 'off': self.host._RADIO['on'] = False
                elif case == 'paused': self.host.paused = True
                elif case == 'legacy': self.rt.config['engine'] = 'legacy'
                elif case == 'slot_disabled': slot['enabled'] = False
                elif case == 'future': self.now = slot['start'] - 1
                elif case == 'expired': self.now = slot['deadline']
                elif case == 'ordinary': slot['dynamic_kind'] = ''
                elif case == 'unallocated': slot['allocations'] = []
                elif case == 'unavailable': slot['allocations'][0]['state'] = 'unavailable'
                elif case == 'not_ready': candidate['ready'] = False
                elif case == 'ineligible': candidate['eligible'] = False
                elif case == 'blocked': candidate['blocked_reasons'] = ['exact source was refused']
                elif case == 'wrong_occurrence': candidate['source']['dynamic_occurrence'] = 'another'
                elif case == 'wrong_slot': candidate['slot_id'] = 'another'
                elif case == 'missing_candidate': self.rt._candidates = []
                self.assertFalse(await self.adapter.dispatch_due())
        self.rt.dispatch.assert_not_awaited()

    async def test_complete_audio_must_fit_before_independent_dispatch_is_called(self):
        await self.ready_book()
        self.rt.dispatch = mock.AsyncMock(return_value=False)
        slot = self.adapter.due_dispatch_slot()
        candidate_id = slot['allocations'][0]['candidate']['id']
        candidate = next(row for row in self.rt._candidates if row['id'] == candidate_id)
        self.now = slot['deadline'] - candidate['air_seconds'] + .01
        self.assertFalse(await self.adapter.dispatch_due())
        self.rt.dispatch.assert_not_awaited()

    async def test_existing_native_owner_lock_excludes_a_concurrent_tick(self):
        await self.ready_book()
        self.rt.dispatch = mock.AsyncMock(return_value=False)
        await self.rt._dispatch_lock.acquire()
        try:
            self.assertFalse(await self.adapter.dispatch_due())
            self.rt.dispatch.assert_not_awaited()
        finally:
            self.rt._dispatch_lock.release()

    async def test_event_priority_is_not_served_by_additional_dynamic_clock(self):
        await self.ready_book()
        self.rt.dispatch = mock.AsyncMock(return_value=False)
        self.rt._event_plans = [{'slots': [{'id': 'ordinary-event', 'kind': 'news',
            'start': self.now - 1, 'deadline': self.now + 60, 'allocations': [{}]}]}]
        self.assertFalse(await self.adapter.dispatch_due())
        self.rt.dispatch.assert_not_awaited()

    async def test_cache_precheck_never_reads_sql_or_rebuilds_inventory(self):
        await self.ready_book()
        with (mock.patch.object(self.rt.store, '_tx', side_effect=AssertionError('No SQL polling')),
              mock.patch.object(self.rt, 'inventory', side_effect=AssertionError('No inventory polling'))):
            self.assertEqual(self.adapter.due_dispatch_slot()['id'], self.slot['id'])

    async def test_refresh_crossing_into_an_ordinary_slot_cannot_reserve_or_handoff(self):
        await self.ready_book()
        async def crossing(*args, **kwargs):
            self.now = self.rt._plans[0]['slots'][1]['start'] + 1
        self.rt.refresh = mock.AsyncMock(side_effect=crossing)
        self.assertFalse(await self.adapter.dispatch_due())
        self.assertEqual(self.rt.store.reservations(), [])
        self.assertEqual(self.host.aired, [])

    async def test_refresh_changing_requested_kind_or_event_priority_cannot_handoff(self):
        await self.ready_book()
        baseline = copy.deepcopy(self.rt._plans)
        for change in ['ordinary_same_id', 'event_priority', 'disabled']:
            with self.subTest(change=change):
                self.rt._plans = copy.deepcopy(baseline)
                self.rt._event_plans = []
                async def crossing(*args, **kwargs):
                    if change == 'ordinary_same_id': self.rt._plans[0]['slots'][0]['dynamic_kind'] = ''
                    elif change == 'disabled': self.rt._plans[0]['slots'][0]['enabled'] = False
                    else: self.rt._event_plans = [{'slots': [{'id': 'event-first', 'kind': 'news',
                        'start': self.now - 1, 'deadline': self.now + 60, 'allocations': [{}]}]}]
                self.rt.refresh = mock.AsyncMock(side_effect=crossing)
                self.assertFalse(await self.adapter.dispatch_due())
                self.assertEqual(self.rt.store.reservations(), [])
                self.assertEqual(self.host.aired, [])

    async def test_refresh_crossing_pause_off_or_disabled_cannot_reserve_or_handoff(self):
        await self.ready_book()
        for state in ['paused', 'off', 'legacy']:
            with self.subTest(state=state):
                self.host.paused = False
                self.host._RADIO['on'] = True
                self.rt.config['engine'] = 'system2'
                async def crossing(*args, **kwargs):
                    if state == 'paused': self.host.paused = True
                    elif state == 'off': self.host._RADIO['on'] = False
                    else: self.rt.config['engine'] = 'legacy'
                self.rt.refresh = mock.AsyncMock(side_effect=crossing)
                self.assertFalse(await self.adapter.dispatch_due())
                self.assertEqual(self.rt.store.reservations(), [])
                self.assertEqual(self.host.aired, [])

    async def test_transport_refusal_preserves_source_stock_and_never_marks_handoff(self):
        await self.ready_book()
        self.adapter.original['deliver'] = mock.AsyncMock(return_value=False)
        self.assertFalse(await self.adapter.dispatch_due())
        self.assertTrue(all(not row.get('dynamic_handed_off') for row in self.host._LARDER))
        self.assertEqual(self.rt._dispatched, {})
        self.assertTrue(all(r['state'] == 'released' for r in self.rt.store.reservations()))

    async def test_lifecycle_registers_and_starts_one_named_task_and_stops_cleanly(self):
        callbacks = {'startup': [], 'shutdown': []}
        def event(name):
            def register(fn): callbacks[name].append(fn); return fn
            return register
        app = SimpleNamespace(on_event=event)
        namespace = {'_system2': lambda:self.rt, 'DYNAMIC_SEGMENTS_RUNTIME': self.dynamic}
        self.assertIs(bridge.install(app, namespace), self.adapter)
        self.assertIs(bridge.install(app, namespace), self.adapter)
        self.assertEqual([len(callbacks[k]) for k in callbacks], [1, 1])
        await callbacks['startup'][0]()
        first = self.adapter.dispatch_task
        await callbacks['startup'][0]()
        self.assertIs(first, self.adapter.dispatch_task)
        self.assertEqual(first.get_name(), 'system2:dynamic-air')
        await callbacks['shutdown'][0]()
        self.assertTrue(first.done())
        self.assertIsNone(self.adapter.dispatch_task)

    async def test_shutdown_releases_only_unhanded_native_attempt_without_audio(self):
        await self.ready_book()
        entered = asyncio.Event()
        async def unhanded(resolved, on_handoff, can_handoff, entry_overrides=None):
            entered.set()
            await asyncio.Event().wait()
        self.adapter.original['deliver'] = mock.AsyncMock(side_effect=unhanded)
        self.adapter.start_dispatch()
        await asyncio.wait_for(entered.wait(), 2)
        await self.adapter.stop_dispatch()
        self.assertFalse(self.rt._dispatch_lock.locked())
        self.assertEqual(self.host.aired, [])
        self.assertTrue(all(not row.get('dynamic_handed_off') for row in self.host._LARDER))
        self.assertTrue(all(r['state'] == 'released' for r in self.rt.store.reservations()))


    async def test_shutdown_preserves_published_child_at_final_delivery_await(self):
        await self.ready_book()
        published = asyncio.Event()
        finish = asyncio.Event()
        interrupted = []
        async def transport(resolved, on_handoff, can_handoff, entry_overrides=None):
            self.assertTrue(can_handoff())
            on_handoff()
            published.set()
            try:
                await finish.wait()
            except asyncio.CancelledError:
                interrupted.append(True)
                raise
            return True
        self.adapter.original['deliver'] = mock.AsyncMock(side_effect=transport)
        original_wait = asyncio.wait
        async def deadline_wait(tasks, *, timeout=None, **kwargs):
            # Reproduce the native deadline wait ending after publication,
            # while its independently owned transport is still completing.
            return await original_wait(tasks, timeout=.01 if timeout and timeout > 5 else timeout, **kwargs)
        def at_final_await():
            coro = self.adapter.dispatch_task.get_coro()
            for _ in range(20):
                frame = getattr(coro, 'cr_frame', None)
                if frame and frame.f_code.co_name == 'dispatch':
                    return 'said = await' in linecache.getline(frame.f_code.co_filename, frame.f_lineno)
                coro = getattr(coro, 'cr_await', None)
                if coro is None: break
            return False
        try:
            with mock.patch.object(core.asyncio, 'wait', side_effect=deadline_wait):
                self.adapter.start_dispatch()
                await asyncio.wait_for(published.wait(), 2)
                await self.wait_for(at_final_await)
                self.assertTrue(self.rt._dispatched)
                await self.adapter.stop_dispatch()
            self.assertEqual(interrupted, [])
            self.assertTrue(all(r['state'] == 'playing' for r in self.rt.store.reservations()))
            finish.set()
            await self.wait_for(lambda: all(row.get('dynamic_handed_off') for row in self.host._LARDER))
            self.assertEqual(interrupted, [])
        finally:
            finish.set()


if __name__ == '__main__':
    unittest.main(verbosity=2)
