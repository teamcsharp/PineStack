"""Real model adapter keeps rap structure and separates rewriting from draft heat."""
from contextlib import ExitStack
import unittest
from unittest import mock

import app


class CrystalModelOutputTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        values = {'load_settings': lambda: {'model': 'fixture', 'temperature': 1.2,
                      'top_p': .9, 'max_tokens': 4000, 'num_ctx': 2048},
                  'dj_settings': lambda: {'reply_max_chars': 6000}, 'writing_profile': lambda: {},
                  'surplus': lambda: 1., 'box_depth': lambda: 1., 'model_ctx': lambda: 2048,
                  'round_mark': mock.Mock(), 'pipeline_log': mock.Mock(), 'airlog_model_call': mock.Mock(),
                  'task_note': mock.Mock(), 'line_review_guidance': lambda *args: '', '_MODEL_CALLS': [],
                  'line_review_permits': mock.Mock(return_value=False), 'line_review_capture': mock.Mock()}
        for name, value in values.items():
            self.stack.enter_context(mock.patch.object(app, name, value))
        self.call = self.stack.enter_context(mock.patch.object(app, 'call_ollama', new=mock.AsyncMock()))

    async def test_complete_unpunctuated_bars_and_numbered_rows_reach_the_crystal_parser(self):
        for text in ('The copper plate is bright / the station waits tonight',
                     '1: The copper plate is bright / the station waits tonight\n5: The light is clear / the copper hums here'):
            self.call.return_value = {'message': {'content': text}, 'done_reason': 'stop'}
            result = await app.ask_model('Return the requested bars.', limit=600, mark={'kind': 'tint round'})
            self.assertEqual(result, text)
        app.line_review_permits.assert_not_called()
        app.line_review_capture.assert_not_called()

    async def test_prose_fragment_rule_remains_on_the_original_drafting_path(self):
        self.call.return_value = {'message': {'content': 'An unfinished original draft'}}
        self.assertEqual(await app.ask_model('Write dialogue.', mark={'kind': 'caller'}), '')
        self.assertEqual(app.line_review_permits.call_args.args[0], 'draft_fragment')

    async def test_structured_dialogue_preserves_complete_speaker_lines(self):
        text = ('A: The first host finishes the thought.\n'
                'B: The second host answers it directly!\n'
                'C: The caller is cut off before finishing')
        self.call.return_value = {'message': {'content': text},
                                  'done_reason': 'stop'}
        got = await app.ask_model('Write the call.', limit=600,
                                  mark={'kind': 'caller'},
                                  result_contract='structured_turns')
        self.assertEqual(got, ('A: The first host finishes the thought.\n'
                               'B: The second host answers it directly!'))
        self.assertEqual(app.line_review_permits.call_args.args[0],
                         'draft_trimming')

    async def test_structured_dialogue_stops_at_a_complete_turn_boundary(self):
        first = 'A: A complete first turn lands here.'
        text = first + '\nB: A second complete turn lands over there.'
        self.call.return_value = {'message': {'content': text},
                                  'done_reason': 'stop'}
        got = await app.ask_model('Write the call.', limit=len(first),
                                  mark={'kind': 'caller'},
                                  result_contract='structured_turns')
        self.assertEqual(got, first)

    async def test_overflow_and_token_exhaustion_retain_full_evidence_without_delivering_a_prefix(self):
        text = 'A: A complete first sentence.\nB: A tail that the budget interrupted'
        for limit, reason in ((30, 'stop'), (300, 'length')):
            self.call.return_value = {'message': {'content': text}, 'done_reason': reason}
            self.assertEqual(await app.ask_model('Rewrite.', limit=limit,
                mark={'kind': 'tint round', 'tint_before': 'Original dialogue.'}), '')
            receipt = app.line_review_capture.call_args
            self.assertEqual(receipt.args[:3], ('tint_output', 'Original dialogue.', text))
            self.assertTrue(receipt.kwargs['technical'])

    async def test_tint_temperature_and_budget_do_not_inherit_background_creative_heat(self):
        self.call.return_value = {'message': {'content': 'A concise bar ends here'}}
        with mock.patch.dict(app._ROUND_MARK, {app._mark_key(): {'heat': 1.0}}):
            await app.ask_model('Repair wording.', limit=600, spice=.25, mark={'kind': 'tint turn'})
        self.assertEqual(self.call.call_args.kwargs['temperature'], .25)
        self.assertEqual(self.call.call_args.kwargs['max_tokens'], 364)
        self.assertEqual(self.call.call_args.kwargs['purpose'], 'station:tint turn')


if __name__ == '__main__':
    unittest.main()
