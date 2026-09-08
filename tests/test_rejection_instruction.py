"""Explicit instruction reaches real turn, whole-round and repair prompts."""
import asyncio
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import app as station
from rejection_lab import RejectionLabStore


class CrystalInstructionTests(unittest.IsolatedAsyncioTestCase):
    INSTRUCTION = 'Keep each original question and its concrete nouns; rhyme around those facts.'
    SOURCE = ('A: The station needs a copper plate before midnight.\n'
              'B: The gallery needs a wooden frame before sunrise.')
    INITIAL_REPLY = ('A: The station holds a different thought beneath the moon.\n'
                     'B: The gallery changes what it meant this afternoon.')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RejectionLabStore(Path(self.temp.name) / 'instructions.sqlite3')
        self.store.update_settings(1, self.INSTRUCTION, False)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        replacements = {
            '_REJECTION_LAB': self.store, '_LAB_RUNTIME': mock.Mock(),
            'crystal_active': mock.Mock(return_value=[{'name': 'fixture'}]),
            'crystal_stanzas': mock.Mock(return_value=[{'text': 'A complete fixture style passage.'}]),
            'crystal_world_prompt': mock.Mock(return_value='Fixture rhyme world'),
            'crystal_vocab_warm': mock.AsyncMock(),
            'crystal_coverage_target': mock.Mock(return_value=100),
            'crystal_force': mock.Mock(return_value=.88),
            'crystal_grade_strict': mock.Mock(return_value=True),
            'crystal_tint_holds': mock.Mock(return_value=True),
            'tint_model_for': mock.Mock(return_value='fixture-tint-model'),
            'tint_fast_model': mock.Mock(return_value='fixture-tint-model'),
            'tint_should_stop': mock.Mock(return_value=''),
            'surplus': mock.Mock(return_value=0),
            'dj_settings': mock.Mock(return_value={**station.DEFAULT_DJ, 'reply_max_chars': 6000}),
            'tint_evaluate': mock.Mock(return_value={'ok': False, 'faults': ['meaning drift'],
                'machine_ok': False, 'machine_faults': ['meaning drift']}),
            'tint_seen': mock.Mock(), 'task_note': mock.Mock(),
            '_tint_flow': mock.Mock(), 'pipeline_log': mock.Mock(),
            'line_review_capture': mock.Mock(), 'tint_spend_note': mock.Mock(),
            'trail_note': mock.Mock(), 'chunk_answer': mock.Mock(),
            'voice_render_any': mock.AsyncMock(side_effect=AssertionError('No audio in prompt tests')),
        }
        for name, value in replacements.items():
            self.stack.enter_context(mock.patch.object(station, name, value))

    def enabled(self, enabled):
        before = self.store.settings()
        self.store.update_settings(before['revision'], self.INSTRUCTION, enabled)
        return self.store.settings()

    def assert_instruction(self, prompts, enabled, settings):
        self.assertTrue(prompts)
        for prompt in prompts:
            if enabled:
                self.assertEqual(prompt.count(self.INSTRUCTION), 1)
                self.assertIn('instruction revision ' + str(settings['revision']), prompt)
            else:
                self.assertNotIn(self.INSTRUCTION, prompt)
                self.assertNotIn('OPERATOR CRYSTAL REFINEMENT', prompt)
        self.assertEqual(self.store.settings(), settings, 'Generating prompts cannot change operator settings')
        station.voice_render_any.assert_not_awaited()

    async def test_instruction_reaches_actual_individual_turn_prompt_only_when_enabled(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                settings = self.enabled(enabled)
                prompts = []
                async def model(prompt, *args, **kwargs):
                    prompts.append(prompt)
                    raise asyncio.CancelledError
                with mock.patch.object(station, 'ask_model', side_effect=model):
                    with self.assertRaises(asyncio.CancelledError):
                        await station.crystal_turn.__wrapped__(
                            'The station needs a copper plate before midnight.', 'Fixture rhyme world',
                            [{'text': 'A complete fixture style passage.'}], kind='gallery', model='fixture-tint-model')
                self.assertEqual(len(prompts), 1)
                self.assertIn('ORIGINAL SOURCE', prompts[0])
                self.assertIn('The station needs a copper plate before midnight.', prompts[0])
                self.assertIn('SOURCE CONTRACT', prompts[0])
                self.assertIn("bars separated by ' / '", prompts[0])
                self.assert_instruction(prompts, enabled, settings)

    async def test_instruction_reaches_actual_whole_first_pass_and_failed_line_repair(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                settings = self.enabled(enabled)
                prompts = []
                async def model(prompt, *args, **kwargs):
                    prompts.append(prompt)
                    if len(prompts) == 1:
                        return self.INITIAL_REPLY
                    raise asyncio.CancelledError
                with mock.patch.object(station, 'ask_model', side_effect=model):
                    with self.assertRaises(asyncio.CancelledError):
                        # Neither model-facing whole-round helper is mocked.
                        await station.crystal_tint.__wrapped__(self.SOURCE, kind='gallery')
                self.assertEqual(len(prompts), 2)
                self.assertIn('original speaker marker', prompts[0])
                for _marker, source in station.banter_turns(self.SOURCE):
                    self.assertIn(source, prompts[0])
                self.assertIn('original numeric ID', prompts[1])
                self.assertIn('rejected_attempt', prompts[1])
                for _marker, candidate in station.banter_turns(self.INITIAL_REPLY):
                    self.assertIn(candidate, prompts[1])
                self.assertIn('meaning drift', prompts[1])
                self.assert_instruction(prompts, enabled, settings)

    async def test_instruction_also_reaches_the_direct_whole_only_prompt_without_changing_settings(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                settings = self.enabled(enabled)
                prompts = []
                async def model(prompt, *args, **kwargs):
                    prompts.append(prompt)
                    raise asyncio.CancelledError
                with mock.patch.object(station, 'ask_model', side_effect=model):
                    with self.assertRaises(asyncio.CancelledError):
                        await station.crystal_tint.__wrapped__(self.SOURCE, kind='gallery', whole_only=True)
                self.assertEqual(len(prompts), 1)
                for _marker, source in station.banter_turns(self.SOURCE):
                    self.assertIn(source, prompts[0])
                self.assert_instruction(prompts, enabled, settings)


if __name__ == '__main__':
    unittest.main()
