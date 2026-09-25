import asyncio
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from system2 import System2Conflict, System2Store
from system2_runtime import System2Runtime
from tests.test_system2_runtime import Host


def candidate(identity, slot_id, seconds=60, *, script=None):
    speech = script or 'A recorded future performance from ' + identity + '.'
    audio = hashlib.sha256(('recording:' + identity).encode()).hexdigest()
    return {'id': identity, 'kind': 'caller', 'slot_id': slot_id,
            'source': {'system2_slot': slot_id}, 'seconds': seconds,
            'ready': True, 'eligible': True, 'script': 'C: ' + speech,
            'audio_hashes': [audio],
            'lines': [{'id': '0', 'text': speech, 'seconds': seconds,
                       'audio_hash': audio}]}


class FutureReviewSwapTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.now = 10000.0
        self.store = System2Store(Path(tmp.name) / 'store.sqlite3', now=lambda: self.now)
        self.start = self.now + 300
        self.slot_id = 'hour-%d:call' % int(self.start * 1000)
        self.template = [{'id': 'call', 'kind': 'caller', 'seconds': 120,
                          'target_seconds': 60, 'coverage_mode': 'one_performance'}]
        self.old = candidate('old', self.slot_id)
        self.hour = self.store.plan_hour(self.start, self.template, [self.old])
        self.original = copy.deepcopy(self.hour['slots'][0]['allocations'][0])

    def swap(self, new=None, **kwargs):
        return self.store.replace_future_allocation(
            self.slot_id, 'old', new or candidate('new', self.slot_id),
            expected_revision=kwargs.get('revision', self.hour['revision']),
            expected_signature=kwargs.get('signature', self.original['candidate']['signature']))

    def assert_old_untouched(self):
        slot = self.store.get_hour(self.hour['id'])['slots'][0]
        self.assertEqual(slot['allocations'][0]['candidate'], self.original['candidate'])
        self.assertIsNotNone(self.store.get_candidate('old'))

    def test_success_survives_replan_and_reserves_at_airtime(self):
        swapped = self.swap()
        self.assertEqual(swapped['allocations'][0]['candidate']['id'], 'new')
        self.assertIsNotNone(self.store.get_candidate('old'))
        replanned = self.store.plan_hour(self.start, self.template,
                                         [self.old, candidate('new', self.slot_id)])
        self.assertEqual(replanned['slots'][0]['allocations'][0]['candidate']['id'], 'new')
        self.now = self.start
        reservation = self.store.reserve(self.slot_id, 'new', 'system2-air',
                                         expected_revision=self.hour['revision'])
        self.assertEqual(reservation['candidate_id'], 'new')

    def test_duration_replan_does_not_book_superseded_take_again(self):
        self.store.plan_hour(self.start, [{'id': 'call', 'kind': 'caller',
                                           'seconds': 120, 'target_seconds': 120}],
                             [self.old], config_revision='duration')
        hour = self.store.get_hour(self.hour['id'])
        old = hour['slots'][0]['allocations'][0]['candidate']
        self.store.replace_future_allocation(
            self.slot_id, 'old', candidate('new', self.slot_id),
            expected_revision=hour['revision'], expected_signature=old['signature'])
        replanned = self.store.plan_hour(self.start,
            [{'id': 'call', 'kind': 'caller', 'seconds': 120, 'target_seconds': 120}],
            [self.old, candidate('new', self.slot_id)], config_revision='duration')
        ids = [a['candidate']['id'] for a in replanned['slots'][0]['allocations']]
        self.assertEqual(ids, ['new'])

    def test_missing_replacement_proof_restores_old_take_on_refresh(self):
        self.swap()
        missing = candidate('new', self.slot_id)
        missing['ready'] = False
        replanned = self.store.plan_hour(self.start, self.template,
                                         [self.old, missing])
        slot = replanned['slots'][0]
        self.assertEqual([a['candidate']['id'] for a in slot['allocations']], ['old'])
        self.assertEqual(slot['review_superseded_ids'], [])

    def test_longer_replacement_shifts_following_take_without_reordering(self):
        first = candidate('old', self.slot_id, 50)
        second = candidate('second', self.slot_id, 50)
        hour = self.store.plan_hour(self.start,
            [{'id': 'call', 'kind': 'caller', 'seconds': 120, 'target_seconds': 100}],
            [first, second], config_revision='two-performances')
        slot = hour['slots'][0]
        self.assertEqual(len(slot['allocations']), 2)
        old = slot['allocations'][0]['candidate']
        changed = self.store.replace_future_allocation(
            self.slot_id, old['id'], candidate('new', self.slot_id, 60),
            expected_revision=slot['revision'], expected_signature=old['signature'])
        self.assertEqual([a['candidate']['id'] for a in changed['allocations']],
                         ['new', 'second'])
        self.assertEqual(changed['allocations'][1]['planned_start'],
                         changed['allocations'][0]['planned_start'] + 60)

    def test_shorter_or_overlong_take_cannot_replace_coverage(self):
        for length in (59, 121):
            with self.subTest(length=length), self.assertRaises(System2Conflict):
                self.swap(candidate('new-%d' % length, self.slot_id, length))
            self.assert_old_untouched()

    def test_missing_recording_cannot_replace_coverage(self):
        new = candidate('new', self.slot_id)
        new['lines'][0].pop('audio_hash')
        with self.assertRaises(System2Conflict):
            self.swap(new)
        self.assert_old_untouched()

    def test_held_or_changed_allocation_cannot_be_swapped(self):
        self.store.reserve(self.slot_id, 'old', 'another-owner')
        with self.assertRaises(System2Conflict):
            self.swap()
        self.assert_old_untouched()

    def test_revision_and_signature_are_compare_and_swap_guards(self):
        with self.assertRaises(System2Conflict):
            self.swap(revision=self.hour['revision'] + 1)
        with self.assertRaises(System2Conflict):
            self.swap(signature='stale')
        self.assert_old_untouched()

    def test_repeat_and_wrong_slot_binding_are_rejected(self):
        new = candidate('new', self.slot_id)
        self.store.record_external(new['lines'][0]['text'], new['audio_hashes'][0],
                                   receipt_id='recently-heard', at=self.now)
        with self.assertRaises(System2Conflict):
            self.swap(new)
        with self.assertRaises(System2Conflict):
            self.swap(candidate('wrong', 'another-slot'))
        self.assert_old_untouched()


class RuntimeReviewVetoTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_review_never_publishes_or_swaps(self):
        runtime = object.__new__(System2Runtime)
        runtime._dispatch_lock = asyncio.Lock()
        runtime._refresh_lock = asyncio.Lock()
        runtime.FUTURE_SWAP_LOCK_WAIT = .01
        runtime._rows = {}
        runtime.candidate = mock.Mock(return_value=candidate('new', 'future:call'))
        runtime.store = mock.Mock()
        published = []
        with self.assertRaises(System2Conflict):
            await runtime.replace_future_allocation(
                'future:call', 'old', 'old-signature', 1, 'caller', {},
                lambda: published.append(True), lambda: published.pop(),
                lambda _candidate: False)
        self.assertEqual(published, [])
        runtime.store.replace_future_allocation.assert_not_called()

    async def test_stalled_air_dispatch_defers_without_publishing(self):
        runtime = object.__new__(System2Runtime)
        runtime._dispatch_lock = asyncio.Lock()
        runtime._refresh_lock = asyncio.Lock()
        runtime.FUTURE_SWAP_LOCK_WAIT = .01
        runtime.candidate = mock.Mock()
        runtime.store = mock.Mock()
        published = []
        await runtime._dispatch_lock.acquire()
        try:
            with self.assertRaisesRegex(System2Conflict, 'Air dispatch is busy'):
                await runtime.replace_future_allocation(
                    'future:call', 'old', 'sig', 1, 'caller', {},
                    lambda: published.append(True), lambda: published.pop(),
                    lambda _candidate: True)
        finally:
            runtime._dispatch_lock.release()
        self.assertEqual(published, [])
        runtime.candidate.assert_not_called()
        runtime.store.replace_future_allocation.assert_not_called()


class RuntimePromotionDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.now = 10000.0
        timer = mock.patch('system2_runtime.time.time', side_effect=lambda: self.now)
        timer.start()
        self.addCleanup(timer.stop)
        self.host = Host(tmp.name, lambda: self.now)
        self.host.templates = [{'id': 'call', 'kind': 'caller', 'minutes': 2}]
        self.runtime = System2Runtime(self.host)
        self.runtime.store.now = lambda: self.now
        self.runtime.config.update(engine='system2', horizon_hours=2)

    async def test_recorded_shadow_survives_refresh_and_dispatches(self):
        slot_id = 'hour-13600000:call'
        old = self.host.add('old', kind='caller', system2_slot=slot_id)
        await self.runtime.refresh(force=True, want_status=False)
        slot = self.runtime.store.get_hour('hour-13600000')['slots'][0]
        original = slot['allocations'][0]['candidate']
        new = self.host.add('new', kind='caller', system2_slot=slot_id)
        self.host.rows['caller'].remove(new)
        await self.runtime.replace_future_allocation(
            slot_id, 'old', original['signature'], slot['revision'], 'caller', new,
            lambda: self.host.rows['caller'].append(new),
            lambda: self.host.rows['caller'].remove(new),
            lambda candidate: candidate['ready'] and candidate['eligible'])
        self.assertIn(old, self.host.rows['caller'])
        planned = self.runtime.store.get_hour('hour-13600000')['slots'][0]
        self.assertEqual([a['candidate']['id'] for a in planned['allocations']], ['new'])
        self.now = 13600.0
        await self.runtime.refresh(force=True, want_status=False)
        self.assertTrue(await self.runtime.dispatch())
        self.assertEqual(self.host.aired[-1]['script'], new['script'])

    async def test_changed_old_source_refuses_promotion_before_publish(self):
        slot_id = 'hour-13600000:call'
        old = self.host.add('old', kind='caller', system2_slot=slot_id)
        await self.runtime.refresh(force=True, want_status=False)
        slot = self.runtime.store.get_hour('hour-13600000')['slots'][0]
        signature = slot['allocations'][0]['candidate']['signature']
        new = self.host.add('new', kind='caller', system2_slot=slot_id)
        self.host.rows['caller'].remove(new)
        old['script'] = 'A: Words changed without recording.'
        with self.assertRaises(System2Conflict):
            await self.runtime.replace_future_allocation(
                slot_id, 'old', signature, slot['revision'], 'caller', new,
                lambda: self.host.rows['caller'].append(new),
                lambda: self.host.rows['caller'].remove(new),
                lambda candidate: candidate['ready'] and candidate['eligible'])
        self.assertNotIn(new, self.host.rows['caller'])
        self.assertEqual(self.runtime.store.get_hour('hour-13600000')['slots'][0]
                         ['allocations'][0]['candidate']['id'], 'old')
