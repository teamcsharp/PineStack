"""LCD cuts retain exact evidence; editorial examples never become new policy."""
import copy
import hashlib
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import httpx
import app
from line_review import LineReviewStore, ReviewConflictError
import test_tint_round_pass as tint_fixture


class LcdRejectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = LineReviewStore(Path(self.temp.name) / 'reviews.sqlite3')
        self.entry = {'script': 'A: The gate is red.\nB: The room is cold.',
                      'prep_kind': 'banter', 'at': 100, 'sid': 'one-round'}
        self.entry['script_plain'] = self.entry['script']
        self.source, self.candidate = 'The gate is red.', 'The red gate waits beside the freight.'
        self.context = {'kind': 'banter', 'stage': 'turn_cut', 'turn': 1, 'marker': 'A',
                        'script_plain': self.entry['script'], 'entry': copy.deepcopy(self.entry)}
        replacements = {
            '_LINE_REVIEW': self.store, '_LARDER': [], '_SHELF': {},
            '_CUPBOARD_MEMO': {'at': 0., 'value': None}, '_RADIO': {}, '_PREP_NOW': {},
            '_TINT_JUDGE_RING': [], '_TINT_OUTPUT_READY': {}, '_TINT_RECOVERY_STATE': {},
            '_TINT_SEEN': {},
            'SPARK_AGENT_API_KEY': 'lcd-review-test', 'LOCK_READS': True, 'station_flow_event': mock.Mock(),
            'line_review_recover': mock.Mock(return_value={'status': 'queued'}),
            'line_review_keep': mock.Mock(return_value={'status': 'kept'}),
            'line_review_clear_operator_proofs': mock.Mock(),
            'radio_paused': lambda: True, 'writing_room_state': lambda: {},
            'crystal_active': lambda: [], 'crystal_tint_holds': lambda: True,
            'crystal_grade_strict': lambda: True, 'tint_coverage': lambda: {},
            'dialogue_row_ready': lambda *_: True,
            'call_ollama': mock.AsyncMock(side_effect=AssertionError('No external writer in LCD tests')),
        }
        for name, value in replacements.items():
            patch = mock.patch.object(app, name, value)
            patch.start(); self.addCleanup(patch.stop)

    def cut(self, **changes):
        return self.store.record('tint', self.source, self.candidate, ['meaning drift'],
                                 context={**self.context, **changes})

    def progress(self, row=None):
        result = {'marker': 'A', 'source': hashlib.sha1(self.source.encode()).hexdigest(),
                  'text': '', 'cut': True, 'rejected_source': self.source,
                  'rejected_candidate': self.candidate,
                  'evaluation': {'ok': False, 'faults': ['meaning drift']}}
        if row:
            result.update(review_id=row['id'], review_seq=row['event_seq'])
        return result

    async def request(self, method, path, body=None, authenticated=True):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url='http://test') as client:
            return await client.request(method, path, json=body,
                headers={'Authorization': 'Bearer lcd-review-test'} if authenticated else {})

    async def test_exact_occurrence_full_evidence_and_authenticated_decisions(self):
        self.source *= 120; self.candidate *= 120
        row = self.cut()
        endpoint = '/api/orchestrator/rejections/' + row['id']
        evidence = endpoint + '?event_seq=' + str(row['event_seq'])
        denied = await self.request('GET', evidence, authenticated=False)
        self.assertIn(denied.status_code, (401, 403))
        response = await self.request('GET', evidence)
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()
        self.assertEqual(item['source'], self.source)
        self.assertEqual(item['candidate'], self.candidate)
        self.assertEqual(item['context']['entry']['sid'], 'one-round')
        self.assertTrue(item['occurrence_current'])
        self.assertFalse(item['read_only'])
        self.assertEqual(item['system_path']['observed']['gate'], 'tint')
        self.assertEqual(item['system_path']['observed']['stage'], 'turn_cut')
        self.assertIn('not a claim', item['system_path']['note'])
        self.assertEqual(item['history'], [])
        self.assertIn('Acceptance thresholds', item['preference']['say'])
        response = await self.request('POST', endpoint, {'action': 'allow',
            'expected_revision': item['revision'], 'expected_event_seq': item['event_seq']})
        self.assertEqual(response.status_code, 200, response.text)
        app.line_review_recover.assert_called_once()
        self.assertEqual(response.json()['effect']['preference']['count'], 1)
        item = response.json()['row']
        response = await self.request('POST', endpoint, {'action': 'keep',
            'expected_revision': item['revision'], 'expected_event_seq': item['event_seq']})
        self.assertEqual(response.status_code, 200, response.text)
        app.line_review_keep.assert_called_once()
        self.assertEqual(self.store.policy()['max_faults'], 0)

    async def test_recurrence_is_readable_but_cannot_vote_on_another_parent(self):
        first = self.cut()
        later = self.cut(script_plain='A: The gate is red.\nB: A different ending.',
                         entry={**self.entry, 'sid': 'different-round'})
        self.assertEqual(first['id'], later['id'])
        endpoint = '/api/orchestrator/rejections/' + first['id']
        response = await self.request('GET', endpoint + '?event_seq=' + str(first['event_seq']))
        self.assertFalse(response.json()['occurrence_current'])
        self.assertTrue(response.json()['read_only'])
        self.assertEqual(response.json()['context']['entry']['sid'], 'one-round')
        response = await self.request('POST', endpoint, {'action': 'allow',
            'expected_revision': later['revision'], 'expected_event_seq': first['event_seq']})
        self.assertEqual(response.status_code, 409, response.text)
        app.line_review_recover.assert_not_called()
        self.assertEqual(self.store.get(first['id'])['review_status'], 'pending')
        response = await self.request('GET', endpoint + '?event_seq=999999')
        self.assertEqual(response.status_code, 404)

    async def test_technical_cut_stays_inspectable_without_recovery_or_preferences(self):
        row = self.store.record('recording_requirement', 'The complete original line.', '',
            ['missing recording'], context={'kind': 'banter'}, technical=True)
        endpoint = '/api/orchestrator/rejections/' + row['id']
        read = await self.request('GET', endpoint + '?event_seq=' + str(row['event_seq']))
        self.assertTrue(read.json()['technical'])
        response = await self.request('POST', endpoint, {'action': 'allow',
            'expected_revision': row['revision'], 'expected_event_seq': row['event_seq']})
        self.assertEqual(response.status_code, 400)
        app.line_review_recover.assert_not_called()
        self.assertEqual(self.store.preference_examples(), [])

    def test_cupboard_retains_cut_between_complete_round_lines_and_caches_refs(self):
        row = self.cut()
        cut = self.progress(row)
        other = {'marker': 'B', 'text': 'The room is cold.', 'evaluation': {'ok': True}}
        self.entry['tint'] = app._tint_paper({'ok': True, 'coverage': {'met': True, 'version': 4, 'cut': 1},
                                            'progress': {'turns': [cut, other]}})
        self.entry['script'] = 'B: The room is cold.'
        app._LARDER.append(self.entry)
        result = app.cupboard_state()
        lines = result['rounds'][0]['lines']
        self.assertEqual([line['mark'] for line in lines], ['cut', 'bar'])
        self.assertEqual(lines[0]['review_id'], row['id'])
        self.assertEqual(lines[0]['review_seq'], row['event_seq'])
        with mock.patch.object(self.store, '_connect', side_effect=AssertionError('No SQL on cached cupboard refs')):
            self.assertEqual(app.cupboard_cut_review('banter', self.entry, cut, 0)['review_id'], row['id'])

    def test_legacy_lookup_is_exact_unique_and_rejects_wrong_parent_or_caller(self):
        row = self.cut()
        self.assertEqual(app.cupboard_cut_review('banter', self.entry, self.progress(), 0)['review_id'], row['id'])
        wrong = {**self.entry, 'sid': 'someone-else'}
        self.assertEqual(app.cupboard_cut_review('banter', wrong, self.progress(), 0)['review_state'], 'unavailable')
        wrong = {**self.entry, 'script_plain': self.entry['script_plain'].replace('cold', 'warm')}
        self.assertEqual(app.cupboard_cut_review('banter', wrong, self.progress(), 0)['review_state'], 'unavailable')
        self.cut()  # same text AND same parent twice cannot identify which older occurrence this is
        self.assertEqual(app.cupboard_cut_review('banter', self.entry, self.progress(), 0)['review_state'], 'unavailable')

    def test_preferences_are_bounded_scoped_literal_restart_persistent_and_not_policy(self):
        policy = self.store.policy()
        first = self.cut()
        self.store.decide(first['id'], 'allow', 'This rhyme keeps the meaning.')
        keep = self.store.record('tint', 'Different source', 'Different candidate', ['copy'], context={'kind': 'caller'})
        self.store.decide(keep['id'], 'keep', 'This copies the quoted passage.')
        technical = self.store.record('recording_requirement', 'No audio', reasons=['missing'], technical=True)
        self.store.decide(technical['id'], 'keep')
        once = self.store.record('tint', 'One time only', 'One time candidate', ['style'], context={'kind': 'banter'})
        self.store.approve_current('test-once-request')
        self.assertEqual(self.store.policy(), policy)
        examples = self.store.preference_examples(kind='banter')
        self.assertEqual([r['review_id'] for r in examples], [first['id']])
        self.assertNotIn(once['id'], [r['review_id'] for r in self.store.preference_examples()])
        self.assertEqual(LineReviewStore(self.store.path).preference_examples(), self.store.preference_examples())
        with mock.patch.object(self.store, '_connect', side_effect=AssertionError('No SQL on prompt hot path')):
            guide = app.line_review_guidance('banter', 'tint')
        self.assertIn('accepted the wording', guide)
        self.assertIn('Do not recite', guide)
        self.assertIn(first['id'], guide)
        self.assertFalse(self.store.evaluate('tint', 'Future original', 'Future candidate', ['style'])['allowed'])
        self.assertFalse(self.store.evaluate('tint', self.source, self.candidate, ['missing'], technical=True)['allowed'])

    async def test_writer_receives_preferences_separately_from_current_tint_material(self):
        self.store.decide(self.cut()['id'], 'allow', 'Keep that meaning.')
        settings = {'model': 'test', 'max_tokens': 50, 'temperature': .5, 'top_p': .9, 'num_ctx': 2048}
        with ExitStack() as stack:
            for name, value in {'load_settings': lambda: settings, 'dj_settings': lambda: {'reply_max_chars': 6000},
                'writing_profile': lambda: {}, 'box_depth': lambda: 0., 'model_ctx': lambda: 2048,
                'round_mark': mock.Mock(), 'pipeline_log': mock.Mock(), '_ROUND_MARK': {}}.items():
                stack.enter_context(mock.patch.object(app, name, value))
            call = stack.enter_context(mock.patch.object(app, 'call_ollama', new=mock.AsyncMock(side_effect=RuntimeError('captured'))))
            with self.assertRaisesRegex(RuntimeError, 'captured'):
                await app.ask_model('Return ONLY this current rewritten line.', mark={'kind': 'tint round'})
        messages = call.call_args.kwargs['messages']
        self.assertEqual([m['role'] for m in messages], ['system', 'user'])
        self.assertIn('OPERATOR WORDING PREFERENCES', messages[0]['content'])
        self.assertEqual(messages[1]['content'], 'Return ONLY this current rewritten line.')

    async def test_actual_turn_cut_saves_the_exact_record_pointer(self):
        fixture = tint_fixture.TintRoundPassTests()
        units = [('A', fixture.SOURCE), ('B', fixture.SOURCE)]
        script = '\n'.join(f'{m}: {s}' for m, s in units)
        first = [{'marker': m, 'source': hashlib.sha1(s.encode()).hexdigest(),
                  'text': fixture.TINTED if i == 0 else fixture.BAD} for i, (m, s) in enumerate(units)]
        with ExitStack() as stack:
            for patch in fixture.tint_patches(True, first, [fixture.BAD] * 3):
                stack.enter_context(patch)
            stack.enter_context(mock.patch.object(app, 'banter_turns', return_value=units))
            stack.enter_context(mock.patch.object(app, 'ask_model', new=mock.AsyncMock(side_effect=AssertionError('No live writer'))))
            stack.enter_context(mock.patch.object(app, 'tint_evaluate', side_effect=lambda _s, candidate, *a, **k:
                {'ok': candidate == fixture.TINTED, 'faults': [] if candidate == fixture.TINTED else ['meaning drift']}))
            report = await app.crystal_tint(script, 'banter', critical=True)
        cut = report['progress']['turns'][1]
        self.assertTrue(cut['cut'])
        row = self.store.get(cut['review_id'], event_seq=cut['review_seq'])
        self.assertEqual(row['context']['turn'], 2)
        self.assertEqual(row['context']['marker'], 'B')
        self.assertEqual(row['context']['script_plain'], script)
        self.assertEqual(row['disposition'], 'cut')


if __name__ == '__main__':
    unittest.main()
