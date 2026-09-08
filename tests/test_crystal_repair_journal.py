"""Real batched repair bookkeeping retains evidence without deferred recapture."""
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
from line_review import LineReviewStore


class CrystalRepairJournalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = LineReviewStore(Path(self.temp.name) / 'reviews.sqlite3')
        self.source = 'The red gate stands beside the road.'
        self.old = 'The old failed candidate carried the wrong facts.'
        self.new = 'The new failed candidate still lost the red gate.'
        self.good = 'The red gate waits by the road, steady under its load.'
        self.turns = [('A', self.source)]
        self.rows = [{'marker': 'A', 'source': hashlib.sha1(self.source.encode()).hexdigest(),
                      'text': '', 'rejected_candidate': self.old, 'selected': True}]
        self.grade = mock.Mock(side_effect=self.evaluation)
        self.writer = mock.AsyncMock(side_effect=AssertionError('No unmocked model calls'))
        for name, value in {'_LINE_REVIEW': self.store, '_LINE_REVIEW_CONTEXT': mock.Mock(),
                'station_flow_event': mock.Mock(), 'tint_should_stop': lambda *_: False,
                'crystal_force': lambda: .88, 'tint_evaluate': self.grade,
                'ask_model': self.writer, 'tint_seen': mock.Mock(), 'pipeline_log': mock.Mock(),
                '_LAB_RUNTIME': mock.Mock()}.items():
            patch = mock.patch.object(app, name, value)
            patch.start(); self.addCleanup(patch.stop)
        app._LINE_REVIEW_CONTEXT.get.return_value = {}
        app._LAB_RUNTIME.current_id.return_value = ''

    def evaluation(self, source, candidate, *args):
        ok = candidate == self.good
        return {'ok': ok, 'version': 4, 'strength': .88, 'machine_ok': ok,
                'faults': [] if ok else ['semantic preservation failed'],
                'semantic': {'ok': ok, 'missing': [] if ok else ['red', 'gate'], 'entities': True}}

    async def repair(self, rows, passes=2):
        return await app._crystal_round_repass(self.turns, rows, 'Keep the meaning and rhyme.',
            'A fictional rap world', [], None, 'fixture-model', kind='banter', passes=passes)

    async def test_retained_candidate_is_recorded_exactly_as_editorial_not_empty_technical(self):
        self.writer.side_effect = app.WritingDeferred('fixture admission full')
        with self.assertRaises(app.WritingDeferred) as caught:
            await self.repair(self.rows)
        reviewed = self.store.summaries(status='all')['items']
        self.assertEqual(len(reviewed), 1)
        row = self.store.get(reviewed[0]['id'])
        self.assertEqual(row['candidate'], self.old)
        self.assertFalse(row['technical'])
        self.assertEqual(caught.exception.turns[0]['rejected_candidate'], self.old)
        self.assertEqual(caught.exception.turns[0]['source'], self.rows[0]['source'])

    async def test_repeated_admission_deferral_preserves_progress_without_repeated_events(self):
        self.writer.side_effect = app.WritingDeferred('fixture admission full')
        pending = copy.deepcopy(self.rows)
        cursors = []
        for _ in range(4):
            with self.assertRaises(app.WritingDeferred) as caught:
                await self.repair(pending)
            pending = copy.deepcopy(caught.exception.turns)
            cursors.append(self.store.summaries(status='all')['latest_cursor'])
        self.assertEqual(cursors, [1, 1, 1, 1])
        reviewed = self.store.summaries(status='all')['items']
        self.assertEqual(reviewed[0]['occurrences'], 1)
        self.assertEqual(pending[0]['rejected_candidate'], self.old)
        self.assertFalse(pending[0]['evaluation']['ok'])

    async def test_new_failed_repair_is_retained_and_next_attempt_grades_those_words(self):
        self.writer.side_effect = ['1: ' + self.new, app.WritingDeferred('fixture admission full')]
        with self.assertRaises(app.WritingDeferred) as caught:
            await self.repair(self.rows)
        candidates = [call.args[1] for call in self.grade.call_args_list]
        self.assertEqual(candidates[:3], [self.old, self.new, self.new])
        pending = caught.exception.turns
        self.assertEqual(pending[0]['rejected_candidate'], self.new)
        self.assertFalse(pending[0]['evaluation']['ok'])
        rows = [self.store.get(r['id']) for r in self.store.summaries(status='all')['items']]
        self.assertEqual({r['candidate'] for r in rows}, {self.old, self.new})
        self.assertTrue(all(not r['technical'] for r in rows))
        self.assertEqual(sum(r['occurrences'] for r in rows), 2)

    async def test_successful_repair_is_not_recaptured_or_rewritten_on_the_next_visit(self):
        self.writer.side_effect = ['1: ' + self.good]
        made, batched = await self.repair(self.rows)
        self.assertTrue(batched)
        self.assertEqual(made[0]['text'], self.good)
        self.assertTrue(made[0]['evaluation']['ok'])
        cursor = self.store.summaries(status='all')['latest_cursor']
        self.writer.reset_mock()
        self.writer.side_effect = AssertionError('Accepted progress must not revisit the model')
        again, did_write = await self.repair(copy.deepcopy(made))
        self.assertFalse(did_write)
        self.writer.assert_not_awaited()
        self.assertEqual(again[0]['text'], self.good)
        self.assertEqual(self.store.summaries(status='all')['latest_cursor'], cursor)


if __name__ == '__main__':
    unittest.main()
