"""Explicit tested replacements grant one exact occurrence, never future text."""
import copy
import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from line_review import LineReviewStore, ReviewConflictError


class ReviewReplacementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = LineReviewStore(Path(self.temp.name) / 'reviews.sqlite3')
        self.context = {'kind': 'caller', 'marker': 'C', 'turn': 2,
                        'script_plain': 'A: Hello.\nC: The gate is red.',
                        'entry': {'sid': 'original-call', 'caller_voice': 'original-voice',
                                  'caller_name': 'Original caller'}}
        self.row = self.store.record('tint', 'The gate is red.', 'An unrelated reply.',
                                     ['semantic preservation failed'], context=self.context)
        self.candidate = 'The gate is red; its shade stays red.'
        self.evaluation = {'ok': True, 'machine_ok': True, 'faults': [], 'version': 4,
                           'semantic': {'ok': True}, 'rhyme': {'ok': True}}

    def apply(self, **overrides):
        args = {'review_id': self.row['id'], 'event_seq': self.row['event_seq'],
                'expected_revision': self.row['revision'], 'request_id': 'replace-request-one',
                'trial_id': 'trial-one', 'candidate': self.candidate, 'evaluation': self.evaluation}
        args.update(overrides)
        return self.store.approve_replacement(**args)

    def evaluate(self, candidate, **extra):
        return self.store.evaluate('tint', self.row['source'], candidate, ['style'],
                                    context={'kind': 'caller'}, **extra)

    def test_exact_replacement_has_immutable_evidence_without_global_or_fake_event(self):
        original = self.store.get(self.row['id'])
        policy = self.store.policy()
        result = self.apply()
        grant = result['instance']
        self.assertTrue(result['changed'])
        self.assertEqual(grant['candidate'], self.candidate)
        self.assertEqual(grant['context'], self.context)
        self.assertEqual(grant['evaluation'], self.evaluation)
        self.assertEqual(grant['source'], self.row['source'])
        self.assertEqual(grant['decision']['scope'], 'instance')
        self.assertEqual(grant['decision']['mode'], 'replacement')
        self.assertEqual(grant['decision']['trial_id'], 'trial-one')
        self.assertNotEqual(grant['fingerprint'], self.row['fingerprint'])
        self.assertEqual(result['row']['candidate'], original['candidate'])
        self.assertEqual(self.store.summaries()['latest_cursor'], original['latest_seq'])
        self.assertEqual(self.store.policy(), policy)
        self.assertEqual(self.store.preference_examples(), [])
        self.assertFalse(self.evaluate(self.candidate)['allowed'])
        with self.store.instance_scope([result['instance_id']]):
            self.assertTrue(self.evaluate(self.candidate)['allowed'])
            self.assertFalse(self.evaluate(self.row['candidate'])['allowed'])
            self.assertFalse(self.evaluate(self.candidate, technical=True)['allowed'])
            self.assertFalse(self.store.evaluate('tint', self.row['source'], self.candidate, ['style'],
                             context={'kind': 'banter'})['allowed'])
        grant['context']['entry']['caller_voice'] = 'mutated-caller'
        self.assertEqual(self.store.get(result['instance_id'])['context'], self.context)

    def test_retry_precedes_stale_check_but_changed_payload_conflicts(self):
        first = self.apply()
        self.store.track_effect(first['instance_id'], {'status': 'queued', 'queue_id': 'one-row'})
        again = self.apply()
        self.assertFalse(again['changed'])
        self.assertEqual(again['instance_id'], first['instance_id'])
        self.assertEqual(len(self.store.instances_for(self.row['id'])), 1)
        self.assertEqual(self.store.get(first['instance_id'])['effect']['status'], 'queued')
        for overrides in ({'candidate': 'Different tested wording.'}, {'trial_id': 'different-trial'},
                          {'expected_revision': 999}, {'evaluation': {**self.evaluation, 'version': 5}}):
            with self.subTest(overrides=overrides), self.assertRaises(ReviewConflictError):
                self.apply(**overrides)

    def test_stale_occurrence_or_revision_writes_nothing(self):
        for overrides in ({'event_seq': self.row['event_seq'] + 1}, {'expected_revision': self.row['revision'] + 1}):
            with self.subTest(overrides=overrides), self.assertRaises(ReviewConflictError):
                self.apply(**overrides)
        newer = self.store.record('tint', self.row['source'], self.row['candidate'], ['meaning'],
                                   context={**self.context, 'turn': 4})
        with self.assertRaises(ReviewConflictError):
            self.apply(expected_revision=newer['revision'])
        self.assertEqual(self.store.instances_for(self.row['id']), [])
        self.assertEqual(self.store.get(self.row['id'])['review_status'], 'pending')

    def test_technical_missing_text_unaccepted_grade_and_invalid_inputs_are_rejected(self):
        for overrides in ({'candidate': ''}, {'candidate': '!!!'}, {'evaluation': {'ok': False}},
                          {'evaluation': {'ok': True, 'technical': True}}, {'trial_id': ''},
                          {'event_seq': True}, {'expected_revision': 0}, {'request_id': ''}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.apply(**overrides)
        for source, technical in (('', False), ('Original words.', True)):
            row = self.store.record('tint', source, 'Rejected wording.', ['missing'], technical=technical)
            with self.assertRaises(ValueError):
                self.apply(review_id=row['id'], event_seq=row['event_seq'], expected_revision=row['revision'])
        self.assertEqual(self.store.pending_instances(), [])

    def test_restart_resumes_grant_and_keep_revokes_it_without_resurrecting_on_retry(self):
        made = self.apply(); instance_id = made['instance_id']
        self.store = LineReviewStore(self.store.path)
        self.assertIn(instance_id, [r['id'] for r in self.store.pending_instances()])
        self.assertFalse(self.evaluate(self.candidate)['allowed'])
        with self.store.instance_scope([instance_id]):
            self.assertTrue(self.evaluate(self.candidate)['allowed'])
        current = self.store.get(self.row['id'])
        self.store.decide(self.row['id'], 'keep', expected_revision=current['revision'])
        self.assertEqual(self.store.pending_instances(), [])
        with self.store.instance_scope([instance_id]):
            self.assertFalse(self.evaluate(self.candidate)['allowed'])
        self.assertFalse(self.apply()['changed'])
        self.assertEqual(self.store.get(instance_id)['review_status'], 'kept')

    def test_concurrent_retry_commits_one_grant(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.apply(), range(12)))
        self.assertEqual(sum(row['changed'] for row in results), 1)
        self.assertEqual(len({row['instance_id'] for row in results}), 1)
        self.assertEqual(len(self.store.instances_for(self.row['id'])), 1)

    def test_existing_approved_work_requires_explicit_withdrawal(self):
        current = self.store.decide(self.row['id'], 'allow')['row']
        with self.assertRaisesRegex(ReviewConflictError, 'already has approved/recovering work'):
            self.apply(expected_revision=current['revision'])
        kept = self.store.decide(self.row['id'], 'keep')['row']
        made = self.apply(expected_revision=kept['revision'])
        self.store.track_effect(made['instance_id'], {'status': 'recorded'})
        # A later identical cut reopens the base record, while the original
        # recording still owns its grant. No silent replacement of that work.
        future = self.store.record('tint', self.row['source'], self.row['candidate'], ['meaning'], context=self.context)
        self.assertEqual(future['review_status'], 'pending')
        with self.assertRaisesRegex(ReviewConflictError, 'already has approved/recovering work'):
            self.apply(event_seq=future['event_seq'], expected_revision=future['revision'], request_id='another-request')
        self.assertEqual(len(self.store.instances_for(self.row['id'])), 1)

    def test_future_occurrence_and_bulk_approval_do_not_receive_replacement_candidate(self):
        made = self.apply()
        future = self.store.record('tint', self.row['source'], self.row['candidate'], ['meaning'], context=self.context)
        self.assertEqual(future['review_status'], 'pending')
        self.assertFalse(self.evaluate(self.candidate)['allowed'])
        bulk = self.store.approve_current('later-bulk-request')
        self.assertEqual(bulk['approved'], 1)
        bulk_id = bulk['items'][0]['instance_id']
        with self.store.instance_scope([bulk_id]):
            self.assertFalse(self.evaluate(self.candidate)['allowed'])
            self.assertTrue(self.evaluate(self.row['candidate'])['allowed'])
        with self.store.instance_scope([made['instance_id']]):
            self.assertTrue(self.evaluate(self.candidate)['allowed'])


if __name__ == '__main__':
    unittest.main()
