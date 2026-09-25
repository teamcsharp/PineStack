import concurrent.futures
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from system2 import (ALLOCATION_TRANSITION_SECONDS, System2Conflict,
                     System2Store, _candidate, text_hash)


def candidate(identity, kind='news', seconds=30, **kwargs):
    text = 'Exact retained words for ' + identity + '.'
    audio = hashlib.sha256(('measured audio ' + identity).encode()).hexdigest()
    return {'id': identity, 'kind': kind, 'seconds': seconds, 'ready': True, 'eligible': True,
        'source_id': 'source-' + identity, 'script': text, 'audio_hashes': [audio],
        'lines': [{'id': '0', 'text': text, 'voice': 'actual-voice', 'seconds': seconds,
                   'audio_hash': audio, 'trace': {'review_id': 'review-' + identity, 'event_seq': 42}}], **kwargs}


class System2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'system2.sqlite3'
        self.now = 10000.0
        self.store = System2Store(self.path, now=lambda: self.now)

    def plan(self, candidates=(), templates=None, start=None, **kwargs):
        return self.store.plan_hour(self.now if start is None else start,
            templates or [{'id': 'n', 'kind': 'news', 'seconds': 120}], candidates, **kwargs)

    def dispatched(self, **kwargs):
        value = candidate('news-one', **kwargs)
        hour = self.plan([value]); slot = hour['slots'][0]
        reservation = self.store.reserve(slot['id'], value['id'], 'player')
        self.store.mark_dispatched(reservation['id'], 'player')
        return hour, reservation, value

    def test_completed_audio_is_coverage_not_ready_stock_or_double_charged_time(self):
        value = candidate('first', seconds=30)
        templates = [{'id': 'n', 'kind': 'news', 'seconds': 120, 'target_seconds': 90}]
        hour = self.plan([value], templates)
        reservation = self.store.reserve(hour['slots'][0]['id'], value['id'], 'air')
        self.store.mark_dispatched(reservation['id'], 'air')
        playing = self.store.get_hour(hour['id'])
        self.assertEqual(playing['ready_seconds'], 0)
        self.assertEqual(playing['in_flight_seconds'], 30)
        self.now += 30
        self.store.ack(reservation['id'], 'air', 'finished', completed=True)
        after = self.plan([candidate('second', seconds=60)], templates, start=10000)
        self.assertEqual(after['allocated_seconds'], 90)
        self.assertEqual(after['ready_seconds'], 60)
        self.assertEqual(after['coverage_seconds'], 90)
        self.assertEqual(after['debt_seconds'], 0)
        self.assertEqual(after['slots'][0]['heard_seconds'], 30)
        self.assertEqual(after['slots'][0]['allocations'][1]['planned_start'],
                         10030 + ALLOCATION_TRANSITION_SECONDS)

    def test_air_seconds_default_keeps_existing_proof_and_rejects_understated_runway(self):
        original = _candidate(candidate('proof', seconds=30))
        explicit_default = _candidate(candidate('proof', seconds=30, air_seconds=30))
        longer = _candidate(candidate('proof', seconds=30, air_seconds=34))
        self.assertEqual(original['air_seconds'], 30)
        self.assertEqual(original['signature'], explicit_default['signature'])
        self.assertNotEqual(original['signature'], longer['signature'])
        for bad in (29, float('nan'), '34'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                _candidate(candidate('invalid', seconds=30, air_seconds=bad))

    def test_air_occupancy_and_transition_prevent_false_ready_news(self):
        template = [{'id': 'n', 'kind': 'news', 'seconds': 180}]
        first = candidate('first', seconds=91, air_seconds=94)
        second = candidate('second', seconds=88, air_seconds=91)
        hour = self.plan([first, second], template)
        slot = hour['slots'][0]
        self.assertEqual(len(slot['allocations']), 1)
        self.assertEqual(slot['ready_seconds'], 91)
        self.assertEqual(slot['ready_air_seconds'], 94)
        self.assertEqual(slot['coverage_seconds'], 91)
        self.assertEqual(slot['allocated_air_seconds'], 94)
        self.assertEqual(slot['debt_seconds'], 89)
        self.assertEqual(slot['status'], 'needs_preparation')
        why = self.store.explain_hour(hour['id'])['slots'][0]
        self.assertGreaterEqual(why['refused'].get('too_long', 0), 1)
        self.assertLess(why['room_seconds'], second['air_seconds'])

    def test_transition_margin_is_reserved_between_default_duration_takes(self):
        template = [{'id': 'n', 'kind': 'news', 'seconds': 180}]
        fits = self.plan([candidate('a', seconds=90), candidate('b', seconds=87)], template)
        self.assertEqual(len(fits['slots'][0]['allocations']), 2)
        self.assertEqual(fits['slots'][0]['allocations'][1]['planned_start'],
                         self.now + 90 + ALLOCATION_TRANSITION_SECONDS)
        too_tight = self.plan([candidate('c', seconds=90), candidate('d', seconds=88)],
                              template, start=self.now + 300)
        self.assertEqual(len(too_tight['slots'][0]['allocations']), 1)
        self.assertEqual(too_tight['slots'][0]['status'], 'needs_preparation')

    def test_claimed_job_reports_live_air_room_separately_from_speech_debt(self):
        template = [{'id': 'n', 'kind': 'news', 'seconds': 180}]
        hour = self.plan([candidate('first', seconds=91, air_seconds=94)], template)
        slot = hour['slots'][0]
        self.assertEqual(slot['debt_seconds'], 89)
        self.assertEqual(slot['air_room_seconds'], 83)
        self.now += 20
        job = self.store.claim_job('writer')
        self.assertEqual(job['target_ready_seconds'], 89)
        self.assertEqual(job['air_room_seconds'], 63)
        self.assertEqual(job['template']['air_room_seconds'], 63)
        self.assertEqual(job['template']['ready_seconds'], 91)

    def test_imminent_partial_scene_precedes_later_empty_segment(self):
        templates = [{'id': 'news', 'kind': 'news', 'seconds': 180},
                     {'id': 'caller', 'kind': 'caller', 'seconds': 180}]
        hour = self.plan([candidate('short-news', seconds=25)], templates,
                         start=self.now + 300)
        self.assertGreater(hour['slots'][0]['debt_seconds'], 0)
        self.assertFalse(hour['slots'][0]['coverage_seconds'] == 0)
        self.assertEqual(hour['slots'][1]['coverage_seconds'], 0)
        job = self.store.claim_job('writer')
        self.assertEqual(job['kind'], 'news')
        self.assertFalse(job['coverage_missing'])

    def test_late_start_drops_unhanded_tail_but_preserves_heard_first_take(self):
        template = [{'id': 'n', 'kind': 'news', 'seconds': 180}]
        first = candidate('heard-first', seconds=91, air_seconds=94)
        second = candidate('unhanded-second', seconds=80, air_seconds=82)
        hour = self.plan([first, second], template)
        slot = hour['slots'][0]
        self.assertEqual(len(slot['allocations']), 2)
        reservation = self.store.reserve(slot['id'], first['id'], 'air')
        self.now += 74
        self.store.mark_dispatched(reservation['id'], 'air')
        self.now += 91
        self.store.ack(reservation['id'], 'air', 'heard-first', completed=True)
        after = self.plan([first, second], template, start=10000)
        slot = after['slots'][0]
        self.assertEqual([a['candidate']['id'] for a in slot['allocations']], [first['id']])
        self.assertEqual(slot['allocations'][0]['state'], 'completed')
        self.assertEqual(slot['heard_seconds'], 91)
        self.assertEqual(slot['coverage_seconds'], 91)
        self.assertEqual(slot['debt_seconds'], 89)
        self.assertEqual(self.store.get_reservation(reservation['id'])['state'], 'completed')

    def test_handoff_checks_air_seconds_not_only_measured_speech(self):
        template = [{'id': 'n', 'kind': 'news', 'seconds': 100}]
        value = candidate('runway', seconds=90, air_seconds=100)
        hour = self.plan([value], template)
        reservation = self.store.reserve(hour['slots'][0]['id'], value['id'], 'air')
        self.assertEqual(reservation['actual_seconds'], 90)
        self.assertEqual(reservation['air_seconds'], 100)
        self.now += 5
        self.assertEqual(self.store.validate_reservation(reservation['id'], 'air')['reason'],
                         'measured_duration_misses_deadline')
        with self.assertRaises(System2Conflict):
            self.store.mark_dispatched(reservation['id'], 'air')

    def test_measured_dispatch_updates_speech_without_losing_air_overhead(self):
        template = [{'id': 'n', 'kind': 'news', 'seconds': 120}]
        value = candidate('measured', seconds=90, air_seconds=95)
        hour = self.plan([value], template)
        reservation = self.store.reserve(hour['slots'][0]['id'], value['id'], 'air')
        self.assertTrue(self.store.validate_reservation(reservation['id'], 'air', seconds=92)['allowed'])
        dispatched = self.store.mark_dispatched(reservation['id'], 'air', seconds=92)
        self.assertEqual(dispatched['actual_seconds'], 92)
        self.assertEqual(dispatched['air_seconds'], 97)
        self.now += 24
        self.assertEqual(self.store.validate_reservation(reservation['id'], 'air', seconds=92)['reason'],
                         'measured_duration_misses_deadline')

    def test_expired_reservation_does_not_keep_invalid_candidate_ready(self):
        original = candidate('gone'); hour = self.plan([original])
        self.store.reserve(hour['slots'][0]['id'], 'gone', 'owner', lease_seconds=1)
        self.now += 2
        after = self.plan([{**original, 'ready': False}], start=10000)
        self.assertEqual(after['ready_seconds'], 0)
        self.assertEqual(after['slots'][0]['allocations'], [])
        self.assertEqual(self.store.claim_job('writer')['coverage_missing'], True)

    def test_different_candidates_cannot_get_concurrent_active_ownership_of_one_slot(self):
        hour = self.plan([candidate('first'), candidate('second')]); slot = hour['slots'][0]
        self.store.reserve(slot['id'], 'first', 'one')
        with self.assertRaises(System2Conflict): self.store.reserve(slot['id'], 'second', 'two')

    def test_event_due_time_expiry_pass_and_default_retry_keep_original_occurrence(self):
        future = self.store.enqueue_event('guest', {'name': 'Guest'}, request_id='future', due_at=self.now + 40)
        expired = self.store.enqueue_event('call', {}, request_id='expired', deadline=self.now + 1)
        self.now += 2
        self.assertIsNone(self.store.claim_event('ingress'))
        self.assertEqual(self.store.get_event(expired['id'])['state'], 'expired')
        self.assertEqual(self.store.get_event(future['id'])['state'], 'pending')
        duplicate = self.store.enqueue_event('guest', {'name': 'Guest'}, request_id='future', due_at=10040)
        self.assertEqual(duplicate['deadline'], 13600)
        self.now = 10040
        claimed = self.store.claim_event('ingress')
        self.assertEqual(claimed['id'], future['id'])
        self.assertEqual(len(self.store.events(states=['expired'])), 1)
        with self.assertRaises(ValueError):
            self.store.enqueue_event('bad', {}, request_id='bad', due_at=10050, deadline=10049)

    def test_replan_preserves_failed_attempt_diagnostics_and_candidate_binding(self):
        hour = self.plan(); job = self.store.claim_job('writer')
        with self.assertRaises(ValueError):
            self.store.complete_job(job['id'], 'writer', job['token'], candidates=[candidate('wrong-slot', slot_id='other')])
        self.store.complete_job(job['id'], 'writer', job['token'], success=False,
                                result={'deferred': True, 'reason': 'model queue full'}, retry_after=90)
        self.plan(start=10000)
        self.plan(start=10000)
        saved = self.store.get_job(job['id'])
        self.assertEqual(saved['retry_at'], 10090)
        self.assertEqual(saved['last_attempt']['result']['reason'], 'model queue full')
        self.assertEqual(saved['last_attempt']['owner'], 'writer')
        self.assertEqual(len(self.store.jobs(states=['pending'])), 1)

    def test_microplan_identity_and_exact_event_claim_do_not_steal_base_hour(self):
        base = self.plan([candidate('base')])
        event = self.store.enqueue_event('guest', {}, request_id='guest')
        urgent = self.store.enqueue_event('caller', {}, request_id='urgent', deadline=self.now + 10)
        micro = self.plan([candidate('guest', kind='caller')],
            [{'id': 'guest', 'kind': 'caller', 'seconds': 60}], plan_id='event-' + event['id'])
        self.assertNotEqual(micro['id'], base['id'])
        self.assertEqual(self.store.get_hour(base['id'])['slots'][0]['allocations'][0]['candidate']['id'], 'base')
        claimed = self.store.claim_event('event-air', event_id=event['id'])
        self.assertEqual(claimed['id'], event['id'])
        self.assertEqual(self.store.get_event(urgent['id'])['state'], 'pending')

    def test_event_requires_its_actual_script_and_release_does_not_extend_deadline(self):
        event = self.store.enqueue_event('guest', {'brief': 'The actual named guest'}, request_id='bound', deadline=10100)
        plan_id = 'event-' + event['id']
        templates = [{'id': 'scene', 'kind': 'news', 'seconds': 60, 'require_slot_binding': True}]
        plan = self.plan([candidate('generic')], templates, plan_id=plan_id)
        self.assertEqual(plan['slots'][0]['allocations'], [])
        plan = self.plan([candidate('specific', slot_id=plan_id + ':scene')], templates, plan_id=plan_id)
        self.assertEqual(plan['slots'][0]['allocations'][0]['candidate']['id'], 'specific')
        claimed = self.store.claim_event('air', event_id=event['id'])
        with self.assertRaises(System2Conflict): self.store.release_event(event['id'], 'wrong', claimed['token'])
        self.store.release_event(event['id'], 'air', claimed['token'], reason='Transport busy', retry_after=10)
        self.assertIsNone(self.store.claim_event('air', event_id=event['id']))
        self.now += 10
        retried = self.store.claim_event('air', event_id=event['id'])
        self.assertEqual(retried['attempts'], 2)
        self.assertNotEqual(retried['token'], claimed['token'])
        self.assertEqual(retried['deadline'], 10100)
        with self.assertRaises(System2Conflict): self.store.release_event(event['id'], 'air', claimed['token'])
        self.store.release_event(event['id'], 'air', retried['token'], retry_after=100)
        self.assertEqual(self.store.get_event(event['id'])['state'], 'expired')

    def test_partial_writing_progress_yields_to_other_missing_segments_without_losing_work(self):
        templates = [{'id': 'caller', 'kind': 'caller', 'seconds': 120},
                     {'id': 'news', 'kind': 'news', 'seconds': 120},
                     {'id': 'gallery', 'kind': 'gallery', 'seconds': 120}]
        self.plan([], templates)
        first = self.store.claim_job('writer')
        self.assertEqual(first['kind'], 'caller')
        partial = candidate('retained-call', kind='caller', ready=False, slot_id=first['slot_id'])
        result = self.store.complete_job(first['id'], 'writer', first['token'], success=True,
                                         candidates=[partial], retry_after=30)
        self.assertEqual(result['job']['state'], 'progress')
        self.assertFalse(result['job']['ready_output'])
        self.plan([], templates, start=10000)
        next_job = self.store.claim_job('writer')
        self.assertEqual(next_job['kind'], 'news')
        self.assertEqual(self.store.get_job(first['id'])['retry_at'], 10030)
        self.now += 31
        retried = self.store.claim_job('other-writer')
        self.assertEqual(retried['slot_id'], first['slot_id'])
        self.store.complete_job(retried['id'], 'other-writer', retried['token'], success=True,
                                candidates=[{**partial, 'ready': True}])
        final = self.plan([], templates, start=10000)
        self.assertEqual(final['slots'][0]['allocations'][0]['candidate']['id'], partial['id'])
        self.assertEqual(self.store.get_job(first['id'])['retry_at'], 0)

    def test_one_performance_counts_real_short_link_without_inventing_full_slot_audio(self):
        template = [{'id': 'link', 'kind': 'track_talk', 'seconds': 180,
                     'target_seconds': 15, 'coverage_mode': 'one_performance'}]
        hour = self.plan([candidate('link-a', kind='track_talk', seconds=12),
                          candidate('link-b', kind='track_talk', seconds=9)], template)
        slot = hour['slots'][0]
        self.assertEqual(len(slot['allocations']), 1)
        self.assertEqual(slot['ready_seconds'], 12)
        self.assertEqual(slot['debt_seconds'], 0)
        self.assertEqual(slot['target_performances'], 1)
        self.assertEqual(slot['heard_seconds'], 0)
        selected = slot['allocations'][0]['candidate']['id']
        reservation = self.store.reserve(slot['id'], selected, 'air')
        self.store.mark_dispatched(reservation['id'], 'air')
        self.now += 12
        self.store.ack(reservation['id'], 'air', 'link-audible', completed=True)
        actual = self.store.get_hour(hour['id'])['slots'][0]
        self.assertEqual(actual['heard_seconds'], 12)
        self.assertEqual(actual['heard_performances'], 1)
        self.assertEqual(actual['status'], 'complete')
        self.assertEqual(actual['ready_seconds'], 0)

    def test_whole_performance_with_small_residual_is_ready_but_reports_debt(self):
        template = [{'id': 'bulletin', 'kind': 'news', 'seconds': 120}]
        hour = self.plan([candidate('almost-full', seconds=107)], template)
        slot = hour['slots'][0]
        self.assertEqual(slot['debt_seconds'], 13)
        self.assertEqual(slot['status'], 'ready')
        self.assertEqual(self.store.get_job(slot['id'] + ':prepare')['state'], 'satisfied')

        short = self.plan([candidate('too-short', seconds=90)], template,
                          start=self.now + 300)
        self.assertEqual(short['slots'][0]['status'], 'needs_preparation')
        self.assertEqual(short['slots'][0]['debt_seconds'], 30)

    def test_current_record_binding_replaces_only_unowned_allocation_without_revision_change(self):
        template = [{'id': 'link', 'kind': 'track_talk', 'seconds': 180,
                     'target_seconds': 15, 'coverage_mode': 'one_performance'}]
        first = candidate('a-old-link', kind='track_talk', seconds=12)
        current = candidate('b-current-link', kind='track_talk', seconds=12)
        hour = self.plan([first, current], template)
        slot = self.store.allocate_current(hour['slots'][0]['id'], current['id'], expected_revision=hour['revision'])
        self.assertEqual(slot['revision'], hour['revision'])
        self.assertEqual(slot['allocations'][0]['candidate']['id'], current['id'])
        self.assertEqual(self.store.get_candidate(current['id'])['script'], current['script'])
        planned = self.plan([], template, start=10000)
        self.assertEqual(planned['slots'][0]['allocations'][0]['candidate']['id'], current['id'])
        self.store.reserve(slot['id'], current['id'], 'air')
        with self.assertRaises(System2Conflict): self.store.allocate_current(slot['id'], first['id'])

    def test_current_allocation_cannot_steal_future_or_expired_or_changed_work(self):
        current = self.plan([], [{'id': 'here', 'kind': 'news', 'seconds': 60}])
        future = self.plan([candidate('future')], [{'id': 'there', 'kind': 'news', 'seconds': 60}], start=10200)
        with self.assertRaises(System2Conflict): self.store.allocate_current(current['slots'][0]['id'], 'future')
        self.store.sync_candidates([candidate('changed', ready=False), candidate('too-long', seconds=120)])
        for identity in ('changed', 'too-long'):
            with self.assertRaises(System2Conflict): self.store.allocate_current(current['slots'][0]['id'], identity)
        with self.assertRaises(System2Conflict): self.store.allocate_current(future['slots'][0]['id'], 'future')
        self.now = 10061
        with self.assertRaises(System2Conflict): self.store.allocate_current(current['slots'][0]['id'], 'future')

    def test_dynamic_record_slots_wait_for_actual_binding_and_expose_only_their_drafts(self):
        template = [{'id': 'link', 'kind': 'track_talk', 'seconds': 180, 'target_seconds': 15,
                     'coverage_mode': 'one_performance', 'allocation_mode': 'current'}]
        current = candidate('actual', kind='track_talk', seconds=12)
        hour = self.plan([current], template)
        slot_id = hour['slots'][0]['id']
        self.assertEqual(hour['slots'][0]['allocations'], [])
        self.assertEqual(hour['debt_seconds'], 15)
        draft = candidate('draft', kind='track_talk', ready=False, slot_id=slot_id)
        other = candidate('other-draft', kind='track_talk', ready=False, slot_id='another')
        self.store.sync_candidates([current, draft, other])
        self.assertEqual([r['id'] for r in self.store.candidates_for_slot(slot_id)], ['draft'])
        assigned = self.store.allocate_current(slot_id, current['id'])
        self.assertEqual(assigned['ready_seconds'], 12)
        self.assertEqual(assigned['debt_seconds'], 0)

    def test_all_occurrences_remain_and_only_exact_eligible_stock_covers_each(self):
        templates = [{'id': 'early', 'kind': 'news', 'seconds': 60},
                     {'id': 'call', 'kind': 'caller', 'seconds': 60},
                     {'id': 'late', 'kind': 'news', 'seconds': 60}]
        hour = self.plan([candidate('one'), candidate('two'), candidate('bad', 'caller', ready=False)], templates)
        self.assertEqual([s['template_id'] for s in hour['slots']], ['early', 'call', 'late'])
        self.assertEqual([len(s['allocations']) for s in hour['slots']], [1, 0, 1])
        self.assertFalse(hour['all_segments_present'])
        self.assertEqual(hour['ready_seconds'], 60)
        self.assertEqual(hour['debt_seconds'], 120)

    def test_alias_text_and_audio_are_not_allocated_twice(self):
        one = candidate('one'); two = candidate('two', script=one['script'], lines=copy.deepcopy(one['lines']))
        hour = self.plan([one, two], [{'id': 'a', 'kind': 'news', 'seconds': 60}, {'id': 'b', 'kind': 'news', 'seconds': 60}])
        self.assertEqual(sum(len(s['allocations']) for s in hour['slots']), 1)

    def test_template_and_occurrence_candidate_bindings_cannot_be_stolen(self):
        templates = [{'id': 'a', 'kind': 'news', 'seconds': 60}, {'id': 'b', 'kind': 'news', 'seconds': 60}]
        hour = self.plan([candidate('for-b', template_id='b'), candidate('wrong-hour', hour_id='not-this-hour')], templates)
        self.assertFalse(hour['slots'][0]['allocations'])
        self.assertEqual(hour['slots'][1]['allocations'][0]['candidate']['id'], 'for-b')
        hour = self.plan([candidate('third')], [{'id': 'a', 'kind': 'news', 'seconds': 60, 'candidate_ids': ['for-b']}])
        self.assertEqual([a['candidate']['id'] for a in hour['slots'][0]['allocations']], [])

    def test_every_configured_slot_is_reported_when_hour_is_over_capacity(self):
        hour = self.plan([], [{'id': str(i), 'kind': 'news', 'seconds': 2000} for i in range(3)])
        self.assertEqual(len(hour['slots']), 3)
        self.assertEqual(hour['over_capacity_seconds'], 2400)
        self.assertEqual(hour['slots'][-1]['status'], 'outside_hour_capacity')

    def test_durable_full_script_trace_and_measured_duration_survive_restart(self):
        value = candidate('full', script='Case preserved. ' * 500)
        value['lines'][0]['text'] = value['script']
        hour = self.plan([value])
        reopened = System2Store(self.path, now=lambda: self.now)
        saved = reopened.scripts(hour['id'])['slots'][0]['performances'][0]
        self.assertEqual(saved['script'], value['script'])
        self.assertEqual(saved['lines'][0]['trace'], value['lines'][0]['trace'])
        self.assertEqual(saved['seconds'], 30)

    def test_actual_proof_change_or_disappearing_media_blocks_reserved_handoff(self):
        value = candidate('proof'); hour = self.plan([value]); slot = hour['slots'][0]
        reservation = self.store.reserve(slot['id'], 'proof', 'owner')
        self.store.sync_candidates([{**value, 'ready': False}])
        self.assertFalse(self.store.validate_reservation(reservation['id'], 'owner')['allowed'])
        with self.assertRaises(System2Conflict): self.store.mark_dispatched(reservation['id'], 'owner')
        self.store.sync_candidates([value]); self.assertTrue(self.store.validate_reservation(reservation['id'], 'owner')['allowed'])
        self.store.sync_candidates([{**value, 'script': 'Different original.'}])
        self.assertEqual(self.store.validate_reservation(reservation['id'], 'owner')['reason'], 'candidate_proof_changed')

    def test_actual_assembled_duration_and_late_clock_are_checked_before_dispatch(self):
        value = candidate('duration'); hour = self.plan([value]); row = self.store.reserve(hour['slots'][0]['id'], value['id'], 'o')
        self.now += 100
        self.assertFalse(self.store.validate_reservation(row['id'], 'o')['allowed'])
        with self.assertRaises(System2Conflict): self.store.mark_dispatched(row['id'], 'o', seconds=30)
        self.assertTrue(self.store.validate_reservation(row['id'], 'o', seconds=15)['allowed'])

    def test_reservation_claim_is_atomic_across_two_store_instances(self):
        hour = self.plan([candidate('one')]); slot = hour['slots'][0]['id']
        other = System2Store(self.path, now=lambda: self.now)
        def claim(store, who):
            try: return store.reserve(slot, 'one', who)
            except System2Conflict: return None
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda x: claim(*x), [(self.store, 'a'), (other, 'b')]))
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_stale_plan_job_and_reserved_performance_cannot_publish(self):
        hour = self.plan([candidate('one')]); slot = hour['slots'][0]['id']
        reservation = self.store.reserve(slot, 'one', 'o'); job = self.store.claim_job('writer')
        updated = self.plan([], [{'id': 'n', 'kind': 'news', 'seconds': 150}], expected_revision=hour['revision'])
        self.assertEqual(updated['revision'], hour['revision'] + 1)
        with self.assertRaises(System2Conflict): self.store.mark_dispatched(reservation['id'], 'o')
        with self.assertRaises(System2Conflict): self.store.complete_job(job['id'], 'writer', job['token'])

    def test_generation_first_fills_absent_kind_then_tops_up_earlier_covered_slot(self):
        templates = [{'id': 'n', 'kind': 'news', 'seconds': 120}, {'id': 'c', 'kind': 'caller', 'seconds': 120}]
        hour = self.plan([candidate('one')], templates)
        job = self.store.claim_job('writer')
        self.assertEqual(job['kind'], 'caller'); self.assertEqual(job['target_ready_seconds'], 120)
        self.assertEqual(job['template']['id'], hour['slots'][1]['id'])
        self.assertIsNone(job['estimated_deadline_fit'])

    def test_failed_job_retry_wait_and_live_lease_survive_replanning(self):
        templates = [{'id': 'n', 'kind': 'news', 'seconds': 120}]
        self.plan([], templates); job = self.store.claim_job('writer', lease_seconds=60)
        self.plan([], templates); self.assertIsNone(self.store.claim_job('another'))
        self.store.complete_job(job['id'], 'writer', job['token'], success=False, retry_after=30)
        self.plan([], templates); self.assertIsNone(self.store.claim_job('writer'))
        self.now += 31
        self.assertIsNotNone(self.store.claim_job('writer'))

    def test_expired_jobs_and_outside_lookahead_receive_no_generation_claim(self):
        self.plan([], start=self.now - 500)
        self.plan([], start=self.now + 7200)
        self.assertIsNone(self.store.claim_job('writer'))

    def test_jobs_return_actual_deficit_cost_and_reject_wrong_kind_completion(self):
        self.plan([candidate('one')], [{'id': 'n', 'kind': 'news', 'seconds': 120, 'prep_cost_per_second': 2, 'prompt': 'Exact slot prompt'}])
        job = self.store.claim_job('writer')
        self.assertEqual(job['target_ready_seconds'], 90); self.assertEqual(job['estimated_work_seconds'], 180)
        self.assertEqual(job['template']['prompt'], 'Exact slot prompt')
        with self.assertRaises(ValueError): self.store.complete_job(job['id'], 'writer', job['token'], candidates=[candidate('wrong', 'caller')])

    def test_unpublished_reservation_and_lease_timeout_do_not_create_heard_proof(self):
        value = candidate('one'); hour = self.plan([value]); row = self.store.reserve(hour['slots'][0]['id'], 'one', 'o', lease_seconds=2)
        with self.assertRaises(System2Conflict): self.store.ack(row['id'], 'o', 'fake', completed=True)
        self.now += 3
        with self.assertRaises(System2Conflict): self.store.mark_dispatched(row['id'], 'o')
        self.assertTrue(self.store.can_play([value['script']])['allowed'])

    def test_line_and_full_ack_credit_once_across_page_and_box(self):
        hour, row, value = self.dispatched()
        a = self.store.ack(row['id'], 'player', 'page-line', line_id=0)
        b = self.store.ack(row['id'], 'player', 'box-line', line_id='0')
        self.assertTrue(a['changed']); self.assertFalse(b['changed'])
        self.store.ack(row['id'], 'player', 'page-end', completed=True)
        duplicate = self.store.ack(row['id'], 'player', 'box-end', completed=True)
        self.assertFalse(duplicate['changed'])
        self.assertEqual(self.store.get_hour(hour['id'])['slots'][0]['heard_seconds'], 30)
        self.assertFalse(self.store.can_play([value['script']])['allowed'])
        self.now += 3600
        self.assertTrue(self.store.can_play([value['script']])['allowed'])

    def test_intentional_muted_delivery_is_not_heard_but_independent_audible_route_counts(self):
        hour, row, _ = self.dispatched()
        self.store.ack(row['id'], 'player', 'muted-box', completed=True, audible=False)
        self.assertEqual(self.store.get_hour(hour['id'])['slots'][0]['heard_seconds'], 0)
        result = self.store.ack(row['id'], 'player', 'audible-page', completed=True)
        self.assertTrue(result['changed'])
        self.assertEqual(self.store.get_hour(hour['id'])['slots'][0]['heard_seconds'], 30)

    def test_repeat_protection_is_durable_and_punctuation_cannot_evade_it(self):
        self.store.record_external('Hello there, listener!', receipt_id='trusted-ack', seconds=2)
        self.assertFalse(System2Store(self.path, now=lambda:self.now).can_play(['HELLO there listener.'])['allowed'])
        duplicate = self.store.record_external('Hello there, listener!', receipt_id='trusted-ack', seconds=2)
        self.assertFalse(duplicate['changed'])
        with self.assertRaises(System2Conflict): self.store.record_external('Different words.', receipt_id='trusted-ack', seconds=2)
        self.now += 3600
        self.assertTrue(self.store.can_play(['Hello there listener'])['allowed'])

    def test_external_receipt_can_share_exact_owned_reservation_without_false_repeat(self):
        _, row, value = self.dispatched()
        self.store.record_external(value['script'], value['audio_hashes'][0], receipt_id='line-proof', reservation_id=row['id'])
        self.assertTrue(self.store.can_play([value['script']], reservation_id=row['id'])['allowed'])
        self.assertFalse(self.store.can_play([value['script']])['allowed'])
        result = self.store.ack(row['id'], 'player', 'whole-proof', completed=True)
        self.assertFalse(result['receipt']['repeat_violation'])

    def test_repeat_during_dispatch_is_reported_without_erasing_actual_receipt(self):
        _, row, value = self.dispatched()
        self.store.record_external(value['script'], receipt_id='other-actual-reply')
        result = self.store.ack(row['id'], 'player', 'actual-complete', completed=True)
        self.assertTrue(result['receipt']['repeat_violation'])
        self.assertEqual(result['reservation']['heard_seconds'], 30)

    def test_interrupt_resume_preserves_position_and_never_releases_unknown_playout(self):
        _, row, value = self.dispatched()
        self.store.suspend(row['id'], 'player', position_seconds=12, reason='live caller')
        reopened = System2Store(self.path, now=lambda:self.now)
        resumed = reopened.resume(row['id'], 'player')
        self.assertTrue(resumed['allowed']); self.assertEqual(resumed['seek_seconds'], 12)
        with self.assertRaises(System2Conflict): reopened.release(row['id'], 'other')
        self.now += 5000
        self.assertFalse(reopened.can_play([value['script']])['allowed'])
        self.assertFalse(reopened.validate_reservation(row['id'], 'player')['allowed'])

    def test_repeated_plans_cannot_double_book_same_performance_inside_one_hour_guard(self):
        value = candidate('one'); first = self.plan([value], start=10000)
        second = self.plan([value], start=10060)
        self.assertEqual(first['ready_seconds'], 30)
        self.assertEqual(second['ready_seconds'], 0)

    def test_event_ingress_is_idempotent_durable_owned_and_priority_ordered(self):
        event = self.store.enqueue_event('caller', {'source': 'Exact call', 'trace': 5}, request_id='call-1')
        self.now += 1
        self.assertEqual(self.store.enqueue_event('caller', {'source': 'Exact call', 'trace': 5}, request_id='call-1')['id'], event['id'])
        with self.assertRaises(System2Conflict): self.store.enqueue_event('caller', {'source': 'Other'}, request_id='call-1')
        urgent = self.store.enqueue_event('request', {'track_id': 'exact'}, request_id='request-1', deadline=self.now+20, priority=10)
        claimed = System2Store(self.path, now=lambda:self.now).claim_event('ingress')
        self.assertEqual(claimed['id'], urgent['id'])
        with self.assertRaises(System2Conflict): self.store.finish_event(claimed['id'], 'wrong', claimed['token'], result={})
        done = self.store.finish_event(claimed['id'], 'ingress', claimed['token'], result={'queued': True})
        self.assertEqual(done['state'], 'completed')

    def test_negative_inputs_never_manufacture_readiness_or_receipts(self):
        for fields in ({'seconds': float('nan')}, {'seconds': -1}, {'audio_hashes': ['filename.wav']}, {'lines': 'not-lines'}):
            with self.assertRaises(ValueError): self.plan([candidate('invalid', **fields)])
        hour = self.plan([candidate('not-attested', ready='true')])
        self.assertEqual(hour['ready_seconds'], 0)
        with self.assertRaises(ValueError): self.store.record_external('heard', receipt_id='future', at=self.now+10)


if __name__ == '__main__': unittest.main()
