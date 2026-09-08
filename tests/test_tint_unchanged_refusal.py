"""#1075: a refused rewrite hands the source back UNPROVED.

Measured on the Gazette press (2026-09-08): crystal_line graded the source
against itself after every refusal, filing a second ledger row with the plain
words as the candidate and, because plain prose rhymes by accident (34% of an
edition's paragraphs) while fluid acceptance waives "not transformed", logging
"tinted (280->280 chars)" on paragraphs the paper then refused.
"""
import copy
import time
import unittest
from contextlib import ExitStack
from unittest import mock

import app


class Refinement(str):
    def __new__(cls, text, profile, revision, strategies):
        value = super().__new__(cls, text)
        value.learning_profile = profile
        value.learning_selection = {'learning_revision': revision, 'strategy_ids': list(strategies)}
        return value


SOURCE = ('Later, at 4:00 AM, Junebug called live from the apartment stairwell. '
          'Skip inquired about her request concerning stolen garbage.')


class UnchangedTurnTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.recorded = {}
        def outcome(row):
            self.recorded[row['attempt_id']] = copy.deepcopy(row)
            return {'recorded': True, 'changed': False}
        store = mock.Mock(); store.outcome.side_effect = outcome
        for name, value in {
            '_PROMPT_LEARNING': store, '_LAB_RUNTIME': mock.Mock(),
            '_PROMPT_LEARNING_ERRORS': {'count': 0, 'last_error': ''},
            'pipeline_log': mock.Mock(), 'round_mark': mock.Mock(),
            'box_depth': lambda: 0, 'writing_profile': lambda: {},
            'line_review_guidance': lambda *_: '', 'station_flow_event': mock.Mock(),
            'line_review_capture': mock.Mock(),
        }.items():
            self.stack.enter_context(mock.patch.object(app, name, value))
        token = app._CRYSTAL_LEARNING_WIRE.set(None)
        self.addCleanup(app._CRYSTAL_LEARNING_WIRE.reset, token)
        preview = app._REJECTION_LAB_PREVIEW.set(False)
        self.addCleanup(app._REJECTION_LAB_PREVIEW.reset, preview)

    def accidental_pass(self):
        # What the grader says about a plain line that rhymes by accident under
        # fluid acceptance: ok, with "not transformed" waived to an advisory.
        return {'ok': True, 'machine_ok': False, 'version': 9, 'grade': 'meaning',
                'semantic': {'ok': True}, 'rhyme': {'ok': True, 'required': True, 'rap': {'ok': True}},
                'editorial': {'ok': True, 'accepted_with_advisories': True},
                'faults': [], 'advisory': ['rhetoric was not materially transformed']}

    async def test_a_turn_handed_back_twice_is_a_refusal_not_a_graded_bar(self):
        with (mock.patch.object(app, 'ask_model', side_effect=[SOURCE, SOURCE]) as model,
              mock.patch.object(app, 'crystal_operator_refinement', return_value=Refinement('Guidance', 'p', 3, ['recipe'])),
              mock.patch.object(app, 'crystal_force', return_value=.88),
              mock.patch.object(app, 'tint_evaluate', side_effect=lambda *_a, **_k: self.accidental_pass()),
              mock.patch.object(app, 'line_review_permits', return_value=False),
              mock.patch.object(app, 'tint_seen'), mock.patch.object(app, '_tint_flow'),
              mock.patch.object(app, '_tint_output_note') as noted):
            result = await app.crystal_turn.__wrapped__(SOURCE, 'world', [], kind='paper', model='fixture-model')
        self.assertEqual(model.await_count, 2)
        self.assertIsInstance(result, app.CrystalTurnFailure)
        self.assertEqual(str(result), SOURCE)
        self.assertIn('unchanged after a second ask', result.evaluation['faults'][0])
        noted.assert_not_called()


class RefusedLineTests(unittest.IsolatedAsyncioTestCase):
    async def test_crystal_line_never_grades_the_source_against_itself(self):
        failure = app.CrystalTurnFailure(
            SOURCE, 'Later at four in the morn Junebug called from the stairwell',
            {'ok': False, 'faults': ['no rhyme evidence - the bar does not land a rhyme']})
        report = {}
        app._TINT_SEEN.update({'hour': float(int(time.time() // 3600)), 'offered': 0.0,
                               'tinted': 0.0, 'refused': 0.0, 'rounds': 0.0})
        with (mock.patch.object(app, 'crystal_tint_two_pass', return_value=True),
              mock.patch.object(app, 'crystal_active', return_value=[{'name': 'DOOM', 'strength': 88}]),
              mock.patch.object(app, 'tint_should_stop', return_value=''),
              mock.patch.object(app, 'surplus', return_value=0.0),
              mock.patch.object(app, 'dj_settings', return_value={'crystal_tint_chunks': 5, 'crystal_tint_chars': 900}),
              mock.patch.object(app, 'crystal_stanzas', return_value=[{'text': 'a style passage', 'file': 'x'}]),
              mock.patch.object(app, 'crystal_world_prompt', return_value='world'),
              mock.patch.object(app, 'crystal_vocab_warm', new=mock.AsyncMock(return_value=None)),
              mock.patch.object(app, 'crystal_turn', new=mock.AsyncMock(return_value=failure)),
              mock.patch.object(app, 'line_review_capture') as captured,
              mock.patch.object(app, 'tint_evaluate') as graded,
              mock.patch.object(app, 'pipeline_log') as logged):
            got = await app.crystal_line(SOURCE, 'the the-phones desk of the gazette', 1,
                                         kind='paper', report=report)
        self.assertEqual(got, SOURCE)
        graded.assert_not_called()          # the source is not a candidate
        captured.assert_not_called()        # crystal_turn already filed the refusal: no duplicate row
        self.assertFalse(app.tint_output_ready(SOURCE))
        self.assertFalse(report['ok'])
        self.assertEqual(report['candidate'], 'Later at four in the morn Junebug called from the stairwell')
        self.assertEqual(report['faults'], ['no rhyme evidence - the bar does not land a rhyme'])
        self.assertEqual(app.tint_coverage()['refused'], 1)
        self.assertEqual(app.tint_coverage()['tinted'], 0)
        self.assertTrue(any('(#1075)' in str(call.args[1]) for call in logged.call_args_list))

    async def test_sentence_by_sentence_refusal_names_the_sentence(self):
        parts = ['Later, at 4:00 AM, Junebug called live.', 'Skip inquired about her request.']
        failure = app.CrystalTurnFailure(parts[1], 'Skip asked about the thing', {'ok': False, 'faults': ['semantic preservation failed']})
        async def turn(text, *_a, **_k):
            return app.CrystalTurnText('Later at 4:00 AM Junebug called live / on the line, alive', 'x:0') if text == parts[0] else failure
        report = {}
        with (mock.patch.object(app, 'crystal_tint_two_pass', return_value=True),
              mock.patch.object(app, 'crystal_active', return_value=[{'name': 'DOOM', 'strength': 88}]),
              mock.patch.object(app, 'tint_should_stop', return_value=''),
              mock.patch.object(app, 'surplus', return_value=0.0),
              mock.patch.object(app, 'dj_settings', return_value={'crystal_tint_chunks': 5, 'crystal_tint_chars': 900}),
              mock.patch.object(app, 'crystal_stanzas', return_value=[{'text': 'a style passage', 'file': 'x'}]),
              mock.patch.object(app, 'crystal_world_prompt', return_value='world'),
              mock.patch.object(app, 'crystal_vocab_warm', new=mock.AsyncMock(return_value=None)),
              mock.patch.object(app, 'crystal_turn', side_effect=turn),
              mock.patch.object(app, 'tint_output_ready', return_value=True),
              mock.patch.object(app, 'line_review_capture') as captured,
              mock.patch.object(app, 'tint_evaluate') as graded,
              mock.patch.object(app, 'pipeline_log')):
            got = await app.crystal_line(' '.join(parts), 'a memo', 5, kind='manager', report=report)
        self.assertEqual(got, ' '.join(parts))
        graded.assert_not_called()
        captured.assert_not_called()
        self.assertEqual((report['part'], report['parts']), (2, 2))
        self.assertEqual(report['faults'], ['semantic preservation failed'])


if __name__ == '__main__':
    unittest.main()
