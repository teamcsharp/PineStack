"""Actual cleanup and whole-only retry lifecycle, without models or station writes."""
import asyncio
import copy
import hashlib
import json
import unittest
from contextlib import ExitStack
from unittest import mock

import app
from crystal_prompts import PROMPT_VERSION, round_prompt


def prompt_rows(prompt):
    for line in prompt.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, list) and value and isinstance(value[0], dict) and 'requested' in value[0]:
            return value
    raise AssertionError('No original turn records in prompt')


class ExplicitBarTests(unittest.TestCase):
    def test_short_requested_rhyme_landings_survive_actual_speech_cleanup(self):
        for raw in ('I stay near / Have no fear', 'Just a test / Take a rest'):
            with self.subTest(raw=raw):
                made = app._tint_out_clean(raw)
                self.assertNotIn('/', made)
                self.assertIn('; ', made)
                self.assertTrue(app.rap_rhyme_evidence(raw)['ok'])
                self.assertTrue(app.rap_rhyme_evidence(made)['ok'])
                self.assertEqual(app._rap_words(raw), app._rap_words(made))

    def test_ordinary_short_comma_prose_does_not_gain_invented_bar_boundaries(self):
        text = 'I stay near, Have no fear'
        self.assertEqual(app._tint_out_clean(text), text)
        self.assertFalse(app.rap_rhyme_evidence(text)['ok'])
        self.assertFalse(app.rap_rhyme_evidence(app._tint_out_clean('The red gate / Seven copper plates'))['ok'])

    def test_question_and_negation_words_and_bar_punctuation_survive(self):
        raw = "Why did you leave? / I cannot grieve."
        self.assertEqual(app._tint_out_clean(raw), 'Why did you leave? I cannot grieve.')
        self.assertTrue(app.rap_rhyme_evidence(app._tint_out_clean(raw))['ok'])


class WholeResumeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.turns = [('A', 'Keep the red gate safe tonight.'), ('B', 'Keep the blue road clear tonight.')]
        self.good = ['Keep the red gate safe tonight; hold it in the light.',
                     'Keep the blue road clear tonight; leave its path in sight.']
        self.bad = 'The blue road disappears beneath a new invented sun.'
        self.source = '\n'.join(f'{m}: {s}' for m, s in self.turns)
        self.chunks = [{'text': 'A complete retained style sample.'}]
        self.writer = mock.AsyncMock(side_effect=AssertionError('Unexpected model call'))
        self.grade = mock.Mock(side_effect=self.evaluate)
        self.learning_notes = []
        def note(ticket, original, candidate, evaluation, row=None):
            self.learning_notes.append((copy.deepcopy(ticket), original, candidate, copy.deepcopy(evaluation)))
            if row is not None:
                row['attempt_id'] = ticket['attempt_id']
        replacements = {
            '_LAB_RUNTIME': mock.Mock(), 'crystal_active': lambda: [{'name': 'fixture'}],
            'crystal_stanzas': lambda *_: self.chunks, 'crystal_world_prompt': lambda: 'world',
            'crystal_vocab_warm': mock.AsyncMock(), 'crystal_coverage_target': lambda: 100,
            'crystal_force': lambda: .88, 'crystal_grade_strict': lambda: False,
            'crystal_acceptance_mode': lambda: 'fluid', 'crystal_tint_holds': lambda: True,
            'tint_model_for': lambda *_: 'fixture-model', 'tint_fast_model': lambda: 'fixture-model',
            'tint_should_stop': lambda *_: '', 'surplus': lambda: 0,
            'dj_settings': lambda: {**app.DEFAULT_DJ, 'reply_max_chars': 6000},
            'crystal_operator_refinement': lambda *_: 'Keep the original concrete facts.',
            'ask_model': self.writer, 'tint_evaluate': self.grade,
            'crystal_learning_note': note,
            'tint_seen': mock.Mock(), '_tint_output_note': mock.Mock(),
            '_tint_flow': mock.Mock(), 'pipeline_log': mock.Mock(),
            'line_review_capture': mock.Mock(return_value={'id': 'retained-review', 'event_seq': 12}),
            'tint_spend_note': mock.Mock(),
            'trail_note': mock.Mock(), 'chunk_answer': mock.Mock(),
            'voice_render_any': mock.AsyncMock(side_effect=AssertionError('No audio')),
        }
        for name, value in replacements.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    def evaluate(self, source, candidate, chunks, answering='', force=.88, kind=''):
        ok = candidate in self.good
        return {'ok': ok, 'version': 6, 'machine_ok': ok,
                'faults': [] if ok else ['Keep the original blue road and its safety request.'],
                'semantic': {'ok': ok}, 'rhyme': {'rap': {'ok': ok}}}

    def progress(self, candidates=None):
        candidates = self.good[:1] + [self.bad] if candidates is None else candidates
        return {'source': hashlib.sha1(self.source.encode()).hexdigest(), 'world': 'world',
                'chunks': copy.deepcopy(self.chunks), 'turns': [
                    {'marker': marker, 'source': hashlib.sha1(source.encode()).hexdigest(),
                     'text': candidate if candidate in self.good else '',
                     'rejected_candidate': candidate, 'selected': True,
                     'evaluation': {'ok': True, 'version': 1, 'faults': ['STALE REPORT']}}
                    for (marker, source), candidate in zip(self.turns, candidates)]}

    async def resume(self, progress, ceiling=6000):
        return await app._crystal_whole_resume(self.turns, progress, 'world', self.chunks,
            'gallery', 'fixture-model', set(range(len(self.turns))), ceiling,
            operator_instruction='Keep the original concrete facts.')

    async def full(self, progress=None):
        return await app.crystal_tint.__wrapped__(self.source, 'gallery', whole_only=True,
                                                progress=progress)

    async def test_actual_whole_only_keeps_accepted_neighbour_and_repairs_exact_failed_id(self):
        self.writer.side_effect = ['2: ' + self.good[1]]
        original = self.progress()
        unchanged = copy.deepcopy(original)
        report = await self.full(original)
        self.assertTrue(report['ok'], report['why'])
        self.assertEqual(report['script'], '\n'.join(f'{m}: {s}' for (m, _), s in zip(self.turns, self.good)))
        self.assertEqual(original, unchanged)
        self.writer.assert_awaited_once()
        args, kwargs = self.writer.call_args
        records = prompt_rows(args[0])
        self.assertEqual(records[0]['accepted_turn'], {'text': self.good[0], 'immutable': True})
        self.assertFalse(records[0]['requested'])
        self.assertEqual(records[1]['rejected_attempt']['candidate'], self.bad)
        self.assertEqual(records[1]['rejected_attempt']['evaluation']['faults'],
                         ['Keep the original blue road and its safety request.'])
        self.assertNotIn('STALE REPORT', args[0])
        self.assertEqual(kwargs['mark']['turn_ids'], [2])
        self.assertEqual(kwargs['mark']['prompt_version'], PROMPT_VERSION)
        self.assertTrue(report['progress']['turns'][1]['attempt_id'])
        self.assertTrue(any(c.args[3] == self.good[0] for c in self.grade.call_args_list if c.args[0] == self.turns[1][1]))
        self.writer.reset_mock()
        self.writer.side_effect = AssertionError('Accepted progress must not be regenerated')
        notes_before = len(self.learning_notes)
        again = await self.full(report['progress'])
        self.assertTrue(again['ok'])
        self.writer.assert_not_awaited()
        self.assertEqual(again['script'], report['script'])
        self.assertEqual(len(self.learning_notes), notes_before, 'Cached regrading is not new training evidence')

    async def test_single_unmarked_turn_repair_carries_candidate_and_fresh_faults(self):
        self.source = self.turns[1][1]
        self.turns = [('', self.source)]
        progress = self.progress([self.bad])
        self.writer.side_effect = [self.good[1]]
        report = await self.full(progress)
        self.assertTrue(report['ok'], report['why'])
        self.assertEqual(report['script'], self.good[1])
        prompt = self.writer.call_args.args[0]
        self.assertIn(json.dumps(self.bad), prompt)
        self.assertIn('Keep the original blue road and its safety request.', prompt)
        self.assertNotIn('original numeric ID', prompt)
        self.assertNotIn('STALE REPORT', prompt)

    async def test_changed_source_position_or_actor_is_not_reused(self):
        for key, value in [('marker', 'C'), ('source', 'another-source')]:
            with self.subTest(key=key):
                progress = self.progress()
                progress['turns'][0][key] = value
                self.assertIsNone(await self.resume(progress))
        self.writer.assert_not_awaited()

    async def test_stale_ok_and_changed_context_regrade_without_losing_exact_candidates(self):
        progress = self.progress()
        progress['context_signature'] = 'old-profile'
        self.writer.side_effect = [app.WritingDeferred('writer busy')]
        with self.assertRaises(app.WritingDeferred):
            await self.resume(progress)
        self.assertTrue(progress['context_changed'])
        self.assertFalse(progress['turns'][1]['evaluation']['ok'])
        self.assertEqual(progress['turns'][1]['rejected_candidate'], self.bad)
        self.assertNotEqual(progress['context_signature'], 'old-profile')
        self.assertNotIn('repair_next', progress)

    async def test_actual_whole_only_deferral_retains_all_words_and_accepted_proof(self):
        self.writer.side_effect = app.WritingDeferred('writer busy')
        report = await self.full(self.progress())
        self.assertTrue(report['deferred'])
        self.assertEqual(report['progress']['turns'][0]['text'], self.good[0])
        self.assertEqual(report['progress']['turns'][1]['rejected_candidate'], self.bad)
        self.assertFalse(report['progress']['turns'][1]['evaluation']['ok'])

    async def test_cancelled_attempt_preserves_callers_durable_progress_and_propagates(self):
        entered = asyncio.Event()
        async def waiting(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        self.writer.side_effect = waiting
        progress = self.progress()
        before = copy.deepcopy(progress)
        task = asyncio.create_task(self.full(progress))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(progress, before)
        app.voice_render_any.assert_not_awaited()

    async def test_malformed_group_never_replaces_an_accepted_neighbour_or_old_attempt(self):
        for reply in ['1: Changed the wrong actor and original line.',
                      '2: ' + self.good[1] + '\n2: A duplicate line cannot replace the record.',
                      '1: An unrequested replacement.\n2: ' + self.good[1], '']:
            with self.subTest(reply=reply):
                self.writer.reset_mock()
                self.writer.side_effect = [reply]
                report = await self.full(self.progress())
                self.assertFalse(report['ok'])
                self.assertEqual(report['progress']['turns'][0]['text'], self.good[0])
                self.assertEqual(report['progress']['turns'][1]['rejected_candidate'], self.bad)
                app.line_review_capture.assert_called()
                self.writer.assert_awaited_once()

    async def test_one_bounded_group_per_visit_rotates_without_starving_later_failures(self):
        self.turns = [('A', ('Original fact number ' + str(i) + '. ') * 12) for i in range(3)]
        self.source = '\n'.join(f'{m}: {s}' for m, s in self.turns)
        progress = self.progress(['Unsuccessful retained candidate.'] * 3)
        self.writer.side_effect = ['1: Still a failed first candidate.',
                                   '2: Still a failed second candidate.',
                                   '3: Still a failed third candidate.']
        # 2026-09-09: 1100, not 900. The ceiling here is chosen so that
        # EXACTLY ONE of these turns fits a visit - that is what the rotation
        # is being tested for - and budget_plan's expansion estimate rose with
        # the bar length rule, so 900 now fits none of them and the road under
        # test is never reached. The scenario is the same one, sized for the
        # estimate it is measured against.
        for i in range(3):
            before = self.writer.await_count
            await self.resume(progress, ceiling=1100)
            self.assertEqual(self.writer.await_count, before + 1)
            self.assertEqual(self.writer.call_args.kwargs['mark']['turn_ids'], [i + 1])
            self.assertLessEqual(self.writer.call_args.kwargs['limit'], 1100)
        self.assertEqual(progress['repair_next'], 0)

    async def test_untouched_failures_do_not_rejournal_but_each_fresh_attempt_still_learns(self):
        self.turns = [('A', ('Original red gate safety request. ' * 8).strip()),
                      ('B', ('Original blue road safety request. ' * 8).strip())]
        self.source = '\n'.join(f'{m}: {s}' for m, s in self.turns)
        progress = self.progress(['A retained failed gate attempt.', 'A retained failed road attempt.'])
        self.writer.side_effect = ['1: A retained failed gate attempt.', '2: A retained failed road attempt.']
        with mock.patch.object(app, 'dj_settings', return_value={**app.DEFAULT_DJ, 'reply_max_chars': 900}):
            first = await self.full(progress)
            self.assertFalse(first['ok'])
            self.assertEqual(app.line_review_capture.call_count, 2)
            ids = [row['review_id'] for row in first['progress']['turns']]
            digests = [row['review_candidate_digest'] for row in first['progress']['turns']]
            second = await self.full(first['progress'])
        self.assertFalse(second['ok'])
        self.assertEqual(app.line_review_capture.call_count, 2, 'Unchanged evidence keeps its existing review')
        self.assertEqual([row['review_id'] for row in second['progress']['turns']], ids)
        self.assertEqual([row['review_candidate_digest'] for row in second['progress']['turns']], digests)
        self.assertEqual(len(self.learning_notes), 2, 'Two real model attempts remain two quality outcomes')
        self.assertNotEqual(self.learning_notes[0][0]['attempt_id'], self.learning_notes[1][0]['attempt_id'])


if __name__ == '__main__':
    unittest.main()
