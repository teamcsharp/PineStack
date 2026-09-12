"""Production ask_model integration with fake transport, no live model or audio."""
import asyncio
import copy
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


class CrystalLearningExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.recorded = {}
        def outcome(row):
            if row['attempt_id'] in self.recorded:
                return {'recorded': False, 'reason': 'duplicate'}
            self.recorded[row['attempt_id']] = copy.deepcopy(row)
            return {'recorded': True, 'changed': False}
        self.store = mock.Mock(); self.store.outcome.side_effect = outcome
        for name, value in {
            '_PROMPT_LEARNING': self.store, '_LAB_RUNTIME': mock.Mock(),
            '_PROMPT_LEARNING_ERRORS': {'count': 0, 'last_error': ''},
            'pipeline_log': mock.Mock(), 'round_mark': mock.Mock(),
            'box_depth': lambda: 0, 'writing_profile': lambda: {},
            'line_review_guidance': lambda *_: '', 'station_flow_event': mock.Mock(),
            'line_review_capture': mock.Mock(),
            # 2026-09-09: the ledger cases here count the FIRST-PASS ladder's
            # asks and its lineage. The one revision pass runs on a bar the
            # grader has already accepted and is deliberately never noted to
            # this ledger, because an outcome measured from an accepted start
            # is not comparable with a first attempt or a repair; it is proved
            # in test_crystal_revision instead. Left on here it would only add
            # a third model call to every count.
            'crystal_revision_skip': lambda kind='': 'these cases isolate the first-pass ladder',
        }.items():
            self.stack.enter_context(mock.patch.object(app, name, value))
        token = app._CRYSTAL_LEARNING_WIRE.set(None)
        self.addCleanup(app._CRYSTAL_LEARNING_WIRE.reset, token)
        preview = app._REJECTION_LAB_PREVIEW.set(False)
        self.addCleanup(app._REJECTION_LAB_PREVIEW.reset, preview)

    def report(self):
        # Actual meaning-grade shape: rap passed while old spelling proof did not.
        return {'ok': True, 'machine_ok': True, 'version': 6, 'grade': 'meaning',
                'semantic': {'ok': True, 'contract_version': 1},
                'rhyme': {'ok': False, 'required': True, 'rap': {'ok': True}},
                'editorial': {'ok': True}, 'faults': []}

    async def ask(self, text, refinement, model, prior=None):
        return await app.crystal_learning_ask(text, learning_kind='caller',
            learning_parent='A: Complete original parent.\nB: Complete original answer.',
            learning_refinement=refinement, learning_stage='repair' if prior else 'first',
            learning_prior=prior, model=model, limit=300, mark={'kind': 'tint turn'})

    async def test_actual_model_profile_strategy_and_prior_are_pinned_without_cross_task_leakage(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def transport(**kwargs):
            calls.append((kwargs['model'], copy.deepcopy(app._CRYSTAL_LEARNING_WIRE.get())))
            if kwargs['model'] == 'first-actual-model':
                entered.set(); await release.wait()
            return {'message': {'content': 'I stay near / Have no fear'}, 'done_reason': 'stop'}
        first = Refinement('First exact guidance', 'profile-one', 12, ['rhyme-recipe'])
        second = Refinement('Second exact guidance', 'profile-two', 13, ['meaning-recipe'])
        with mock.patch.object(app, 'call_ollama', side_effect=transport):
            job = asyncio.create_task(self.ask('first prompt', first, 'first-actual-model', {4: 'earlier-attempt:4'}))
            await entered.wait()
            first.learning_profile = 'changed-during-request'
            first.learning_selection['strategy_ids'].append('NOT-IN-THE-SENT-PROMPT')
            other = await self.ask('second prompt', second, 'second-actual-model')
            await app.ask_model('ordinary unrelated turn', model='ordinary-model', limit=300,
                                mark={'kind': 'tint turn'})
            release.set(); made = await job
        one, two = made.learning_ticket(4), other.learning_ticket(0)
        self.assertEqual(one['model'], 'first-actual-model')
        self.assertEqual(one['profile'], 'profile-one')
        self.assertEqual(one['strategy_ids'], ['rhyme-recipe'])
        self.assertEqual(one['learning_revision'], 12)
        self.assertEqual(one['prior_attempt_id'], 'earlier-attempt:4')
        self.assertTrue(one['attempt_id'].endswith(':4'))
        self.assertEqual(two['model'], 'second-actual-model')
        self.assertEqual(two['profile'], 'profile-two')
        self.assertEqual(two['strategy_ids'], ['meaning-recipe'])
        self.assertNotEqual(one['attempt_id'], two['attempt_id'])
        self.assertIsNone(calls[-1][1])
        self.assertIsNone(app._CRYSTAL_LEARNING_WIRE.get())
        app.crystal_learning_note(one, 'I remain nearby.', 'I stay near; Have no fear', self.report())
        app.crystal_learning_note(one, 'I remain nearby.', 'I stay near; Have no fear', self.report())
        self.assertEqual(len(self.recorded), 1)
        measured = self.recorded[one['attempt_id']]
        self.assertTrue(measured['rhyme_ok'])
        self.assertTrue(measured['effective_ok'])
        self.assertEqual(measured['strategy_ids'], ['rhyme-recipe'])

    async def test_preview_empty_and_unmeasured_technical_outputs_never_enter_quality_results(self):
        refinement = Refinement('Guidance', 'profile', 1, ['recipe'])
        with mock.patch.object(app, 'call_ollama', return_value={'message': {'content': 'A complete response.'}}):
            token = app._REJECTION_LAB_PREVIEW.set(True)
            try:
                preview = await self.ask('preview', refinement, 'fixture-model')
            finally:
                app._REJECTION_LAB_PREVIEW.reset(token)
            app.crystal_learning_note(preview.learning_ticket(), 'source words', 'candidate words', self.report())
            actual = await self.ask('actual', refinement, 'fixture-model')
        app.crystal_learning_note(actual.learning_ticket(), 'source words', '', self.report())
        app.crystal_learning_note(actual.learning_ticket(), 'source words', 'incomplete output',
                                  {'ok': False, 'technical': True, 'faults': ['token budget']})
        self.assertEqual(self.recorded, {})
        self.store.outcome.assert_not_called()

    async def test_admission_deferral_and_cancelled_transport_restore_task_scope_without_outcome(self):
        refinement = Refinement('Guidance', 'profile', 1, ['recipe'])
        with mock.patch.object(app, 'call_ollama', return_value={'deferred': True, 'reason': 'fixture queue full'}):
            with self.assertRaises(app.WritingDeferred):
                await self.ask('deferred', refinement, 'fixture-model')
        self.assertIsNone(app._CRYSTAL_LEARNING_WIRE.get())
        entered = asyncio.Event()
        async def pending(**kwargs):
            entered.set(); await asyncio.Event().wait()
        with mock.patch.object(app, 'call_ollama', side_effect=pending):
            task = asyncio.create_task(self.ask('cancelled', refinement, 'fixture-model'))
            await entered.wait(); task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNone(app._CRYSTAL_LEARNING_WIRE.get())
        self.assertEqual(self.recorded, {})

    def test_failed_caller_contract_cannot_be_counted_as_a_successful_repair(self):
        ticket = {'attempt_id': 'real-generated-attempt:0', 'profile': 'p', 'model': 'm'}
        report = self.report()
        report['semantic']['call_contract'] = {'ok': False, 'faults': ['Caller identity changed']}
        app.crystal_learning_note(ticket, 'Original caller identity.', 'Different caller identity.', report)
        self.assertFalse(self.recorded[ticket['attempt_id']]['semantic_ok'])
        self.assertFalse(self.recorded[ticket['attempt_id']]['effective_ok'])
        self.assertFalse(self.recorded[ticket['attempt_id']]['machine_ok'])

    def test_learning_conflict_retains_inspectable_identity_without_stalling(self):
        from prompt_learning import PromptLearningConflictError
        self.store.outcome.side_effect = PromptLearningConflictError('Repair link belongs to different source work')
        ticket = {'attempt_id': 'fresh:0', 'prior_attempt_id': 'earlier:0', 'kind': 'caller'}
        row = {}
        app.crystal_learning_note(ticket, 'Original complete words.', 'Generated complete words.', self.report(), row=row)
        self.assertEqual(app._PROMPT_LEARNING_ERRORS['count'], 1)
        detail = app._PROMPT_LEARNING_ERRORS['last_detail']
        self.assertEqual(detail['stage'], 'outcome')
        self.assertEqual(detail['attempt_id'], 'fresh:0')
        self.assertEqual(detail['prior_attempt_id'], 'earlier:0')
        self.assertIn('different source work', detail['message'])
        self.assertNotIn('attempt_id', row)
        app._LAB_RUNTIME.record.assert_called_with('learning_error', detail)

        self.store.observe.side_effect = PromptLearningConflictError('The same occurrence has different immutable evidence')
        app.prompt_learning_observe({'id': 'review-one', 'event_seq': 42})
        self.assertEqual(app._PROMPT_LEARNING_ERRORS['count'], 2)
        self.assertEqual(app._PROMPT_LEARNING_ERRORS['last_detail']['stage'], 'observe')
        self.assertEqual(app._PROMPT_LEARNING_ERRORS['last_detail']['event_seq'], 42)

    def test_factual_guard_failure_is_measured_as_meaning_failure_but_style_advisory_is_not(self):
        report = self.report()
        report['editorial'] = {'ok': False, 'guard_evidence': [{'code': 'attempt_became_asserted_action'}]}
        app.crystal_learning_note({'attempt_id': 'unsupported-action:0'},
            'We try to cross.', 'We cross.', report)
        measured = self.recorded['unsupported-action:0']
        self.assertFalse(measured['semantic_ok'])
        self.assertFalse(measured['effective_ok'])
        self.assertIn('anchors', measured['faults'])
        style = self.report()
        style.update(machine_ok=False, machine_faults=['rhetoric was not materially transformed'])
        style['editorial'] = {'ok': True, 'accepted_with_advisories': True, 'guard_evidence': []}
        app.crystal_learning_note({'attempt_id': 'style-only:0'}, 'Original source.', 'Faithful rhymed source.', style)
        self.assertTrue(self.recorded['style-only:0']['semantic_ok'])
        self.assertTrue(self.recorded['style-only:0']['effective_ok'])

    async def test_actual_turn_repair_records_both_fresh_attempts_with_lineage(self):
        source = 'Keep the red gate safe tonight.'
        bad = 'The new blue road disappears beneath the sun.'
        good = 'Keep the red gate safe tonight; hold it in the light.'
        def grade(original, candidate, *args, **kwargs):
            report = self.report()
            if candidate == bad:
                report.update(ok=False, machine_ok=False, faults=['semantic preservation failed'])
                report['semantic']['ok'] = False
                report['editorial']['ok'] = False
            return report
        with (mock.patch.object(app, 'ask_model', side_effect=[bad, good]) as model,
              mock.patch.object(app, 'crystal_operator_refinement', return_value=Refinement('Guidance', 'p', 3, ['recipe'])),
              mock.patch.object(app, 'crystal_force', return_value=.88),
              mock.patch.object(app, 'tint_evaluate', side_effect=grade),
              mock.patch.object(app, 'line_review_permits', return_value=False),
              mock.patch.object(app, 'tint_seen'), mock.patch.object(app, '_tint_flow'),
              mock.patch.object(app, '_tint_output_note')):
            result = await app.crystal_turn.__wrapped__(source, 'world', [], kind='banter', model='fixture-model')
        self.assertEqual(str(result), good)
        self.assertEqual(model.await_count, 2)
        rows = list(self.recorded.values())
        self.assertEqual(len(rows), 2)
        self.assertEqual([row['candidate'] for row in rows], [bad, good])
        self.assertFalse(rows[0]['effective_ok'])
        self.assertTrue(rows[1]['effective_ok'])
        self.assertEqual(rows[1]['prior_attempt_id'], rows[0]['attempt_id'])
        self.assertEqual(result.attempt_id, rows[1]['attempt_id'])

    async def test_actual_caller_precheck_failure_records_full_grade_then_successful_repair(self):
        source = 'I am Mara calling from the red gate tonight.'
        bad = 'I am someone else calling from a different place.'
        good = 'Mara calls from the red gate tonight; the same red gate is in sight.'
        def caller(before, after):
            return {'ok': bad not in after, 'faults': ['Caller identity changed'] if bad in after else []}
        with (mock.patch.object(app, 'ask_model', side_effect=[bad, good]) as model,
              mock.patch.object(app, 'crystal_operator_refinement', return_value=Refinement('Guidance', 'p', 3, ['recipe'])),
              mock.patch.object(app, 'crystal_force', return_value=.88),
              mock.patch.object(app, 'tint_evaluate', side_effect=lambda *_args, **_kwargs: self.report()),
              mock.patch.object(app, 'call_tint_report', side_effect=caller),
              mock.patch.object(app, 'line_review_permits', return_value=False),
              mock.patch.object(app, 'tint_seen'), mock.patch.object(app, '_tint_flow'),
              mock.patch.object(app, '_tint_output_note')):
            result = await app.crystal_turn.__wrapped__(source, 'world', [], kind='caller', model='fixture-model')
        self.assertEqual(str(result), good)
        self.assertEqual(model.await_count, 2)
        rows = list(self.recorded.values())
        self.assertEqual(len(rows), 2)
        self.assertFalse(rows[0]['semantic_ok'])
        self.assertFalse(rows[0]['effective_ok'])
        self.assertTrue(rows[1]['effective_ok'])
        self.assertEqual(rows[1]['prior_attempt_id'], rows[0]['attempt_id'])


if __name__ == '__main__':
    unittest.main()
