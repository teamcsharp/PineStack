"""Actual refusal, prompt, API and readiness paths with isolated persistence."""
import asyncio
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from fastapi import FastAPI, HTTPException
import httpx

import app as station
from line_review import LineReviewStore
from prompt_learning import PromptLearningStore
from rejection_lab import RejectionLabStore
from rejection_lab_runtime import LabRuntime
from rejection_workbench import install


class LearningIntegrationTests(unittest.IsolatedAsyncioTestCase):
    # A faithful rhyme: the source's own words, reordered, landing the very
    # rhyme the source already landed. 2026-09-08: a proved END rhyme the
    # source LACKED now counts as the transformation (the operator's own
    # edits were refused for it), so the source here rhymes already - the
    # raw grade still calls the reorder untransformed, and fluid acceptance
    # still waives that.
    SOURCE = 'The signal stays bright / as we hold the line at night.'
    CANDIDATE = 'We hold the line at night / while the signal stays bright.'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.learning = PromptLearningStore(root / 'learning.sqlite3')
        self.reviews = LineReviewStore(root / 'reviews.sqlite3')
        self.lab_store = RejectionLabStore(root / 'lab.sqlite3')
        self.runtime = LabRuntime(self.lab_store)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        changes = {
            '_PROMPT_LEARNING': self.learning, '_LINE_REVIEW': self.reviews,
            '_REJECTION_LAB': self.lab_store, '_LAB_RUNTIME': self.runtime,
            '_PROMPT_LEARNING_ERRORS': {'count': 0, 'last_error': ''},
            '_TINT_JUDGE_RING': [], '_TINT_OUTPUT_READY': {},
            'crystal_force': mock.Mock(return_value=.88),
            'crystal_grade_strict': mock.Mock(return_value=False),
            'crystal_tint_holds': mock.Mock(return_value=True),
            'crystal_coverage_target': mock.Mock(return_value=100),
            'dialogue_tint_required': mock.Mock(return_value=True),
            '_crystal_vocab': mock.Mock(return_value=frozenset()),
            'dj_settings': mock.Mock(return_value={**station.DEFAULT_DJ, 'reply_max_chars': 6500}),
            'station_flow_event': mock.Mock(),
            'line_review_recover': mock.Mock(return_value={'status': 'queued'}),
            'call_ollama': mock.AsyncMock(side_effect=AssertionError('No live model')),
            'voice_render_any': mock.AsyncMock(side_effect=AssertionError('No recording')),
        }
        for name, value in changes.items():
            self.stack.enter_context(mock.patch.object(station, name, value))
        self.host = dict(vars(station))
        def auth(value):
            if value != 'Bearer fixture-key':
                raise HTTPException(401, 'Authentication required')
        self.host.update(require_auth=auth, require_read_auth=auth,
            api_orch_logic=mock.AsyncMock(return_value={'pipeline': {'ready': 1}}),
            recording_room=mock.Mock(return_value={'active': 0}),
            writing_room_state=mock.Mock(return_value={'active': 0}))
        self.api = FastAPI()
        self.workbench = install(self.api, self.host)
        self.addAsyncCleanup(self.stop_tasks)

    async def stop_tasks(self):
        tasks = list(self.workbench.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def request(self, method='GET', path='/api/orchestrator/prompt-learning', body=None, auth=True):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.api), base_url='http://fixture') as client:
            return await client.request(method, path, json=body,
                headers={'Authorization': 'Bearer fixture-key'} if auth else {})

    def seed(self):
        rows = []
        for index in range(3):
            source = f'The relay needs {12 + index} watts tonight.'
            candidate = f'The relay needs {24 + index} watts tonight, keeping the signal bright.'
            grade = station.tint_evaluate(source, candidate, [], force=.88, kind='gallery')
            rows.append(station.line_review_capture('tint', source, candidate, grade['faults'],
                context={'kind': 'gallery', 'stage': 'turn_rewrite',
                         'script_plain': f'A: Original parent conversation {index % 2}.'},
                evaluation=grade, disposition='rewrite_rejected'))
        return rows

    async def activate(self):
        response = await self.request('POST', body={
            'expected_revision': self.learning.settings()['revision'], 'enabled': True, 'mode': 'fluid'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['status']

    async def test_readers_are_authenticated_and_cannot_activate_learning_or_change_policy(self):
        settings, policy = self.learning.settings(), self.reviews.policy()
        for method, path, body in (
            ('GET', '/api/orchestrator/prompt-learning', None),
            ('POST', '/api/orchestrator/prompt-learning', {'expected_revision': 1, 'enabled': True}),
            ('POST', '/api/orchestrator/prompt-learning/rollback', {'expected_revision': 1, 'revision': 1}),
            ('POST', '/api/orchestrator/prompt-learning/refresh', {'expected_revision': 1}),
        ):
            response = await self.request(method, path, body, auth=False)
            self.assertEqual(response.status_code, 401, response.text)
        result = await self.request()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['status']['mode'], 'strict')
        self.assertEqual(settings, self.learning.settings())
        self.assertEqual(policy, self.reviews.policy())
        station.call_ollama.assert_not_awaited()
        station.voice_render_any.assert_not_awaited()

    async def test_real_declines_activate_evidence_guidance_and_preview_reads_do_not_train(self):
        rows = self.seed()
        self.assertFalse(self.learning.settings()['enabled'])
        status = await self.activate()
        self.assertIn('quantities', [hint['pattern'] for hint in status['hints']])
        prompt = station.crystal_operator_refinement(.88, 'gallery')
        self.assertIn('quantity', prompt)
        self.assertIn('learning revision', prompt)
        self.assertIn('FLUID ACCEPTANCE', prompt)
        before = self.learning.status()
        for _ in range(3):
            self.workbench.grade(rows[0], rows[0]['candidate'])
        self.assertEqual(before, self.learning.status())
        self.assertEqual(self.reviews.summaries(status='all')['total'], 3)
        self.assertEqual(station._PROMPT_LEARNING_ERRORS['count'], 0)

    async def test_fluid_accepts_faithful_rhyme_without_faking_the_raw_grade(self):
        strict = station.tint_evaluate(self.SOURCE, self.CANDIDATE, [], force=.88)
        self.assertFalse(strict['ok'], strict)
        self.assertIn('rhetoric was not materially transformed', strict['machine_faults'])
        await self.activate()
        fluid = station.tint_evaluate(self.SOURCE, self.CANDIDATE, [], force=.88)
        self.assertTrue(fluid['ok'], fluid)
        self.assertFalse(fluid['machine_ok'])
        self.assertEqual(fluid['machine_faults'], strict['machine_faults'])
        self.assertTrue(fluid['editorial']['accepted_with_advisories'])
        self.assertEqual(fluid['faults'], [])
        self.assertTrue(fluid['rhyme']['rap']['ok'])
        self.assertEqual(self.reviews.summaries(status='all')['total'], 0)

    async def test_fluid_still_rejects_changed_quantity_and_unrhymed_plain_words(self):
        await self.activate()
        for source, candidate in (
            ('The relay needs 12 watts tonight.', 'The relay needs 24 watts tonight, keeping the signal bright.'),
            ('Please describe the painting.', 'Please describe the painting.'),
        ):
            with self.subTest(candidate=candidate):
                grade = station.tint_evaluate(source, candidate, [], force=.88)
                self.assertFalse(grade['ok'], grade)
                self.assertTrue(grade['editorial']['blocking_faults'])

    async def test_strict_restore_rechecks_style_exceptions_in_live_and_persisted_readiness(self):
        await self.activate()
        grade = station.tint_evaluate(self.SOURCE, self.CANDIDATE, [], force=.88)
        self.assertTrue(grade['ok'], grade)
        station._tint_output_note(self.CANDIDATE, grade)
        coverage = {'coverage': {'met': True, 'target': 100, 'strength': .88, 'version': 4},
                    'evaluation': {'turns': [grade]}}
        self.assertTrue(station.tint_output_ready(self.CANDIDATE))
        self.assertTrue(station.tint_coverage_ready(coverage))
        # Direct restored settings simulate a restart: stale persisted proof
        # must be rejected even without the API's live-cache clearing.
        self.learning.update(self.learning.settings()['revision'], mode='strict')
        self.assertFalse(station.tint_output_ready(self.CANDIDATE))
        self.assertFalse(station.tint_coverage_ready(coverage))

    async def test_stale_updates_rollback_and_resume_are_durable_and_do_not_approve_lines(self):
        rows = self.seed()
        await self.activate()
        current = self.learning.settings()['revision']
        stale = await self.request('POST', body={'expected_revision': 1, 'mode': 'strict'})
        self.assertEqual(stale.status_code, 409)
        rolled = await self.request('POST', '/api/orchestrator/prompt-learning/rollback',
            {'expected_revision': current, 'revision': 1})
        self.assertEqual(rolled.status_code, 200, rolled.text)
        state = rolled.json()['status']
        self.assertTrue(state['automation_paused'])
        self.assertEqual(state['mode'], 'strict')
        resumed = await self.request('POST', body={
            'expected_revision': state['revision'], 'enabled': True, 'mode': 'fluid', 'resume': True})
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertFalse(resumed.json()['status']['automation_paused'])
        self.assertTrue(resumed.json()['status']['hints'])
        self.assertEqual(PromptLearningStore(self.learning.path).settings(), self.learning.settings())
        for row in rows:
            # #1088: an intermediate refusal is a note, a cut is pending; neither is approved.
            self.assertIn(self.reviews.get(row['id'])['review_status'], ('pending', 'noted'))
        station.line_review_recover.assert_not_called()

    async def test_recent_refresh_seeds_actual_pinned_rows_without_votes_or_models(self):
        rows = self.seed()
        # A fresh learning file stands in for a newly installed backend.
        fresh = PromptLearningStore(Path(self.temp.name) / 'fresh.sqlite3')
        self.stack.enter_context(mock.patch.object(station, '_PROMPT_LEARNING', fresh))
        self.host['_PROMPT_LEARNING'] = fresh
        response = await self.request('POST', '/api/orchestrator/prompt-learning/refresh', {'expected_revision': 1})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['observed'], 3)
        self.assertEqual(response.json()['errors']['count'], 0)
        self.assertTrue(response.json()['status']['patterns'])
        self.assertEqual(fresh.settings()['revision'], 1)
        self.assertEqual(self.reviews.summaries(status='all')['total'], len(rows))
        station.call_ollama.assert_not_awaited()
        station.line_review_recover.assert_not_called()

    async def test_trial_uses_current_fluid_permission_and_learning_changes_invalidate_apply(self):
        original_grade = station.tint_evaluate(self.SOURCE, self.CANDIDATE, [], force=.88)
        row = self.reviews.record('tint', self.SOURCE, self.CANDIDATE, original_grade['faults'],
            context={'kind': 'gallery', 'stage': 'turn_rewrite'}, evaluation=original_grade)
        await self.activate()
        identity = {'event_seq': row['event_seq'], 'expected_revision': row['revision']}
        result = await self.request('POST', f'/api/orchestrator/rejections/{row["id"]}/try',
            {**identity, 'request_id': 'fluid-preview', 'candidate': self.CANDIDATE})
        self.assertEqual(result.status_code, 200, result.text)
        await asyncio.gather(*list(self.workbench.tasks))
        operation = self.lab_store.get_operation(result.json()['operation']['id'])
        self.assertEqual(operation['status'], 'completed', operation)
        trial = self.lab_store.get_trial(operation['trial_id'])
        self.assertTrue(trial['evaluation']['ok'], trial)
        self.assertFalse(trial['evaluation']['tint']['machine_ok'])
        self.assertEqual(trial['baseline']['learning_revision'], self.learning.settings()['revision'])
        self.learning.update(self.learning.settings()['revision'], enabled=False)
        result = await self.request('POST', f'/api/orchestrator/rejections/{row["id"]}/apply',
            {**identity, 'request_id': 'stale-apply', 'trial_id': trial['id']})
        self.assertEqual(result.status_code, 200, result.text)
        await asyncio.gather(*list(self.workbench.tasks))
        operation = self.lab_store.get_operation(result.json()['operation']['id'])
        self.assertEqual(operation['status'], 'failed')
        self.assertIn('changed', operation['error'])
        self.assertEqual(self.reviews.get(row['id'])['review_status'], 'pending')
        station.call_ollama.assert_not_awaited()
        station.line_review_recover.assert_not_called()

    async def test_generated_trial_uses_same_actual_guidance_as_production(self):
        self.seed()
        await self.activate()
        row = self.reviews.record('tint', self.SOURCE, self.CANDIDATE,
            ['rhetoric was not materially transformed'],
            context={'kind': 'gallery', 'stage': 'turn_rewrite', 'chunks': []})
        station.call_ollama.side_effect = None
        station.call_ollama.return_value = {'message': {'content': self.CANDIDATE}}
        result = await self.request('POST', f'/api/orchestrator/rejections/{row["id"]}/try',
            {'event_seq': row['event_seq'], 'expected_revision': row['revision'],
             'request_id': 'generated-preview', 'candidate': ''})
        self.assertEqual(result.status_code, 200, result.text)
        await asyncio.gather(*list(self.workbench.tasks))
        operation = self.lab_store.get_operation(result.json()['operation']['id'])
        self.assertEqual(operation['status'], 'completed', operation)
        messages = station.call_ollama.call_args.kwargs['messages']
        prompt = '\n'.join(message['content'] for message in messages)
        self.assertIn(station.crystal_operator_refinement(.88, 'gallery').strip(), prompt)
        self.assertIn(self.SOURCE, prompt)
        self.assertIn('SOURCE CONTRACT', prompt)
        self.assertEqual(prompt.count('ORCHESTRATOR FLUID ACCEPTANCE'), 1)
        station.line_review_recover.assert_not_called()


if __name__ == '__main__':
    unittest.main()
