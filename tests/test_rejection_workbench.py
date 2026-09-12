"""Durable diagnostic APIs, isolated from all live station/model/media state."""
import asyncio
from contextlib import ExitStack
from contextvars import ContextVar
import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from fastapi import FastAPI, HTTPException
import httpx

from line_review import LineReviewStore
from rejection_lab import RejectionLabStore
from rejection_lab_runtime import LabRuntime
from rejection_workbench import BASE, install


class WorkbenchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RejectionLabStore(Path(self.temp.name) / 'lab.sqlite3')
        self.reviews = LineReviewStore(Path(self.temp.name) / 'reviews.sqlite3')
        self.preview = ContextVar('isolated_test_preview', default=False)
        self.runtime = LabRuntime(self.store)
        self.source = 'The red door creaks at night.'
        self.candidate = 'The red door creaks at night / its hinges wake the light.'
        self.row = self.record()

        def auth(value):
            if value != 'Bearer fixture-key':
                raise HTTPException(401, 'Authentication required')

        self.host = {
            '_REJECTION_LAB': self.store, '_LINE_REVIEW': self.reviews,
            '_LAB_RUNTIME': self.runtime, '_REJECTION_LAB_PREVIEW': self.preview,
            'require_auth': auth, 'require_read_auth': auth,
            'api_orch_logic': mock.AsyncMock(return_value={'pipeline': {'waiting': 95, 'ready': 48}}),
            'recording_room': mock.Mock(return_value={'active': 0}),
            'writing_room_state': mock.Mock(return_value={'active': 1}),
            'crystal_grade_strict': mock.Mock(return_value=True),
            'crystal_tint_holds': mock.Mock(return_value=True),
            'crystal_force': mock.Mock(return_value=.88),
            'crystal_coverage_target': mock.Mock(return_value=100),
            'tint_evaluate': mock.Mock(side_effect=self.grade),
            'call_tint_report': mock.Mock(return_value={'ok': True}),
            '_looks_meta': mock.Mock(return_value=False),
            'call_ollama': mock.AsyncMock(return_value={'message': {'content': 'The observed fault concerns meaning. Try preserving the door.'}}),
            'tint_model_for': mock.Mock(return_value='fixture-tint-model'),
            'load_settings': mock.Mock(return_value={'model': 'fixture-discussion-model'}),
            'model_ctx': mock.Mock(return_value=8192),
            '_tint_out_clean': lambda text: text.strip(),
            'line_review_recover': mock.Mock(return_value={'status': 'queued', 'say': 'Awaiting normal recording.'}),
        }
        self.app = FastAPI()
        self.lab = install(self.app, self.host)
        self.addAsyncCleanup(self.stop_tasks)

    def record(self, *, technical=False, source=None, candidate=None):
        return self.reviews.record('tint', source or self.source, candidate or self.candidate,
            ['meaning drift'], context={'kind': 'banter', 'stage': 'turn_rewrite', 'marker': 'A',
                'script': 'A: ' + self.source, 'turn': 1, 'chunks': [{'text': 'Exact style sample.'}]},
            technical=technical, evaluation={'machine_ok': False, 'machine_faults': ['meaning drift']})

    def grade(self, source, candidate, *args):
        self.assertTrue(self.preview.get(), 'Diagnostic grading must suppress production review writes')
        return {'ok': True, 'machine_ok': True, 'faults': [], 'machine_faults': []}

    async def stop_tasks(self):
        pending = list(self.lab.tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def settle(self):
        if self.lab.tasks:
            await asyncio.gather(*list(self.lab.tasks))
        await asyncio.sleep(0)

    def body(self, request_id='request-fixture-1', **extra):
        return {'event_seq': self.row['event_seq'], 'expected_revision': self.row['revision'],
                'request_id': request_id, **extra}

    async def request(self, method, suffix, body=None, *, auth=True, review_id=None):
        path = (BASE + '/' + (review_id or self.row['id']) + '/' + suffix
                if not suffix.startswith('/') else suffix)
        headers = {'Authorization': 'Bearer fixture-key'} if auth else {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://fixture') as client:
            return await client.request(method, path, json=body, headers=headers)

    async def trial(self, request_id='trial-fixture-1', candidate='The red door creaks at night / its hinges creak in moonlight.'):
        response = await self.request('POST', 'try', self.body(request_id, candidate=candidate))
        self.assertEqual(response.status_code, 200, response.text)
        await self.settle()
        return self.store.get_operation(response.json()['operation']['id'])

    async def test_auth_and_read_only_inspection_cannot_create_operations_or_change_settings(self):
        settings, policy = self.store.settings(), self.reviews.policy()
        for method, path, body in (
            ('GET', 'workbench?event_seq=' + str(self.row['event_seq']), None),
            ('POST', 'discuss', self.body(message='Why was this rejected?')),
            ('POST', 'try', self.body(candidate='A new candidate.')),
            ('POST', 'apply', self.body(trial_id='missing-trial')),
            ('POST', '/api/orchestrator/rejection-lab/settings', {'expected_revision': 1, 'enabled': True, 'crystal_instruction': 'Do something.'}),
        ):
            result = await self.request(method, path, body, auth=False)
            self.assertEqual(result.status_code, 401, result.text)
        result = await self.request('GET', 'workbench?event_seq=' + str(self.row['event_seq']))
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['diagnostics']['pipeline']['ready'], 48)
        self.assertEqual(self.store.history(self.row['id'], self.row['event_seq'], 'operations')['total'], 0)
        self.assertEqual(self.store.settings(), settings)
        self.assertEqual(self.reviews.policy(), policy)
        self.host['call_ollama'].assert_not_awaited()
        self.host['line_review_recover'].assert_not_called()

    async def test_one_asynchronous_job_and_retried_request_share_one_model_call_and_question(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def model(**kwargs):
            started.set()
            await release.wait()
            return {'message': {'content': 'A complete measured answer.'}}
        self.host['call_ollama'].side_effect = model
        body = self.body(message='Why is the recording queue waiting?')
        first = await self.request('POST', 'discuss', body)
        await asyncio.wait_for(started.wait(), 1)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['operation']['status'], 'pending')
        inspected = await self.request('GET', 'workbench?event_seq=' + str(self.row['event_seq']))
        self.assertEqual(inspected.status_code, 200, inspected.text)
        self.assertEqual(inspected.json()['operations'][0]['status'], 'pending')
        self.assertEqual(inspected.json()['trace_sources'], [])
        duplicate, denied = await asyncio.gather(
            self.request('POST', 'discuss', body),
            self.request('POST', 'discuss', self.body('request-another', message='Another question.')))
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertEqual(duplicate.json()['operation']['id'], first.json()['operation']['id'])
        self.assertEqual(denied.status_code, 429, denied.text)
        self.assertEqual(self.store.history(self.row['id'], self.row['event_seq'])['total'], 1)
        release.set()
        await self.settle()
        replay = await self.request('POST', 'discuss', body)
        self.assertEqual(replay.json()['operation']['status'], 'completed')
        self.host['call_ollama'].assert_awaited_once()
        self.assertEqual([m['role'] for m in self.store.history(self.row['id'], self.row['event_seq'])['items']], ['user', 'assistant'])
        self.assertEqual(self.host['call_ollama'].call_args.kwargs['purpose'], 'interactive')

    async def test_generated_trial_uses_production_repair_contract_and_budget(self):
        self.host['call_ollama'].return_value = {'message': {'content': self.candidate}}
        self.host['crystal_source_contract'] = mock.Mock(return_value='Exact production contract for the red door')
        self.host['dj_settings'] = mock.Mock(return_value={'reply_max_chars': 1000})
        response = await self.request('POST', 'try', self.body('shared-prompt-trial'))
        self.assertEqual(response.status_code, 200, response.text)
        await self.settle()
        call = self.host['call_ollama'].call_args.kwargs
        prompt = call['messages'][-1]['content']
        for evidence in (self.source, self.candidate, 'meaning drift',
                         'Exact production contract for the red door',
                         'two or more spoken bars', 'Output budget:'):
            self.assertIn(evidence, prompt)
        self.assertEqual(call['temperature'], .3)
        operation = self.store.get_operation(response.json()['operation']['id'])
        self.assertEqual(operation['status'], 'completed')
        trial = self.store.get_trial(operation['trial_id'])
        self.assertEqual(trial['baseline']['grader_version'], 9)
        # 2026-09-09: the craft priority, the revision ask and the lifted
        # word count on a bar changed the words every road shares, so the
        # shared frame is version 7.
        self.assertEqual(trial['provenance']['prompt_version'], 8)
        self.host['line_review_recover'].assert_not_called()

    async def test_reasoning_trial_is_explicit_bounded_and_does_not_change_production(self):
        settings, policy = self.store.settings(), self.reviews.policy()
        self.host['call_ollama'].return_value = {'message': {'content': self.candidate}}
        for value in ('true', 1, None):
            response = await self.request('POST', 'try', self.body('bad-reasoning', reasoning=value))
            self.assertEqual(response.status_code, 400, response.text)
        self.host['call_ollama'].assert_not_awaited()
        response = await self.request('POST', 'try', self.body('reasoning-trial', reasoning=True))
        self.assertEqual(response.status_code, 200, response.text)
        await self.settle()
        call = self.host['call_ollama'].call_args.kwargs
        self.assertTrue(call['thinking'])
        self.assertEqual(call['max_tokens'], 768)
        self.assertEqual(call['purpose'], 'interactive')
        operation = self.store.get_operation(response.json()['operation']['id'])
        self.assertEqual(operation['status'], 'completed')
        self.assertTrue(self.store.get_trial(operation['trial_id'])['provenance']['reasoning_requested'])
        self.assertEqual(self.store.settings(), settings)
        self.assertEqual(self.reviews.policy(), policy)
        self.host['line_review_recover'].assert_not_called()

    async def test_diagnostic_joins_real_model_fifo_when_both_station_writer_slots_are_occupied(self):
        import app as station
        labels = ('station-first', 'station-second', 'diagnostic-question')
        entered = {label: asyncio.Event() for label in labels}
        release = {label: asyncio.Event() for label in labels}
        order = []

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, *, json):
                label = json['messages'][-1]['content']
                order.append(label)
                entered[label].set()
                await release[label].wait()
                response = mock.Mock()
                response.json.return_value = {'message': {'content': 'Complete reply to ' + label}}
                return response

        with ExitStack() as stack:
            for name, value in {'_LAB_RUNTIME': self.runtime, '_OLLAMA_JOBS': {}, '_OLLAMA_ONE': {},
                                '_OLLAMA_GATE': asyncio.Semaphore(2), '_OLLAMA_DEFERRED': {},
                                '_OLLAMA_DEFERRED_CATEGORIES': {}}.items():
                stack.enter_context(mock.patch.object(station, name, value))
            stack.enter_context(mock.patch.object(station.httpx, 'AsyncClient', return_value=Client()))
            actual_call = self.runtime.model_call(station.call_ollama.__wrapped__)
            self.host['call_ollama'] = actual_call
            tasks = []
            try:
                first = asyncio.create_task(actual_call(model='fixture-discussion-model',
                    messages=[{'role': 'user', 'content': labels[0]}], temperature=.2, max_tokens=100,
                    purpose='station:gallery'))
                tasks.append(first)
                await asyncio.wait_for(entered[labels[0]].wait(), 1)
                second = asyncio.create_task(actual_call(model='fixture-discussion-model',
                    messages=[{'role': 'user', 'content': labels[1]}], temperature=.2, max_tokens=100,
                    purpose='station:manager'))
                tasks.append(second)
                await asyncio.sleep(0)
                self.assertEqual([row['category'] for row in station._OLLAMA_JOBS.values()], ['station', 'station'])
                diagnostic = asyncio.create_task(self.lab.model([{'role': 'user', 'content': labels[2]}]))
                tasks.append(diagnostic)
                await asyncio.sleep(0)
                self.assertEqual(len(station._OLLAMA_JOBS), 3, 'The diagnostic must enter the queue, not be deferred as a third station writer')
                self.assertEqual([row['category'] for row in station._OLLAMA_JOBS.values()], ['station', 'station', 'interactive'])
                self.assertEqual(order, [labels[0]])
                self.assertEqual(station._OLLAMA_DEFERRED, {})
                release[labels[0]].set()
                await asyncio.wait_for(entered[labels[1]].wait(), 1)
                self.assertEqual(order, list(labels[:2]), 'Interactive work must preserve the common per-model FIFO')
                release[labels[1]].set()
                await asyncio.wait_for(entered[labels[2]].wait(), 1)
                release[labels[2]].set()
                results = await asyncio.wait_for(asyncio.gather(*tasks), 1)
                self.assertEqual(results[2], 'Complete reply to diagnostic-question')
                self.assertEqual(order, list(labels))
                self.assertEqual(station._OLLAMA_JOBS, {})
                self.assertEqual(station._OLLAMA_DEFERRED_CATEGORIES, {})
                self.assertEqual(station._OLLAMA_GATE._value, 2)
                self.assertEqual(station._ollama_lane('fixture-discussion-model')._value, 1)
            finally:
                for event in release.values():
                    event.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def test_failed_model_discussion_keeps_its_exact_prompt_and_error_selectable(self):
        @self.runtime.model_call
        async def failed_model(**kwargs):
            raise RuntimeError('Fixture model connection stopped after receiving the full prompt.')
        self.host['call_ollama'].side_effect = failed_model
        body = self.body('failed-model-discussion', message='Why did this exact rewrite fail?')
        response = await self.request('POST', 'discuss', body)
        self.assertEqual(response.status_code, 200, response.text)
        await self.settle()
        operation = self.store.get_operation(response.json()['operation']['id'])
        self.assertEqual(operation['status'], 'failed')
        self.assertIn('Fixture model connection stopped', operation['error'])
        trace_id = operation['result']['trace_id']
        inspected = await self.request('GET', 'workbench?event_seq=' + str(self.row['event_seq']) + '&trace_id=' + trace_id)
        self.assertEqual(inspected.status_code, 200, inspected.text)
        self.assertIn(trace_id, [row['id'] for row in inspected.json()['trace_sources']])
        trace = inspected.json()['trace']['items']
        self.assertEqual([row['record']['kind'] for row in trace], ['model_request', 'model_error'])
        request_details = trace[0]['record']['details']
        self.assertEqual(request_details['kwargs']['messages'][-1]['content'], body['message'])
        self.assertEqual(trace[1]['record']['details']['error'], operation['error'])
        self.assertEqual(trace[1]['record']['details']['call_id'], request_details['call_id'])
        replay = await self.request('POST', 'discuss', body)
        self.assertEqual(replay.json()['operation']['result']['trace_id'], trace_id)
        self.host['call_ollama'].assert_awaited_once()
        self.host['line_review_recover'].assert_not_called()
        self.assertEqual([row['role'] for row in self.store.history(self.row['id'], self.row['event_seq'])['items']], ['user'])

    async def test_old_occurrence_can_be_discussed_but_stale_trial_cannot_grade_or_recover(self):
        old = copy.deepcopy(self.row)
        self.record()
        inspected = await self.request('GET', 'workbench?event_seq=' + str(old['event_seq']))
        self.assertFalse(inspected.json()['occurrence_current'])
        self.assertTrue(inspected.json()['capabilities']['discuss'])
        self.assertFalse(inspected.json()['capabilities']['try_wording'])
        discussed = await self.request('POST', 'discuss', self.body(message='Explain this older cut.'))
        self.assertEqual(discussed.status_code, 200, discussed.text)
        await self.settle()
        trial = await self.request('POST', 'try', self.body('stale-trial-request', candidate='A changed line.'))
        self.assertEqual(trial.status_code, 409, trial.text)
        self.host['tint_evaluate'].assert_not_called()
        self.host['line_review_recover'].assert_not_called()
        self.assertEqual(self.store.history(old['id'], old['event_seq'])['total'], 2)

    async def test_trial_records_exact_baseline_machine_grade_and_provenance_without_production_changes(self):
        before, settings, policy = self.reviews.get(self.row['id']), self.store.settings(), self.reviews.policy()
        candidate = 'The red door creaks at night / its hinges creak in moonlight.'
        operation = await self.trial(candidate=candidate)
        self.assertEqual(operation['status'], 'completed', operation)
        trial = self.store.get_trial(operation['trial_id'])
        self.assertEqual(trial['candidate'], candidate)
        self.assertEqual(trial['baseline']['candidate'], self.candidate)
        self.assertEqual(trial['baseline']['source'], self.source)
        self.assertTrue(trial['evaluation']['ok'])
        self.assertFalse(trial['provenance']['production_changed'])
        self.assertEqual(trial['provenance']['origin'], 'operator_text')
        self.assertEqual(self.reviews.get(self.row['id']), before)
        self.assertEqual(self.reviews.policy(), policy)
        self.assertEqual(self.store.settings(), settings)
        self.assertFalse(self.preview.get())
        self.host['call_ollama'].assert_not_awaited()
        self.host['line_review_recover'].assert_not_called()
        self.assertEqual(self.store.trace_history(trial['provenance']['trace_id'])['items'][0]['record']['kind'], 'trial_evaluation')

    async def test_manual_candidate_is_cleaned_before_grade_storage_and_explicit_apply(self):
        supplied = 'A: "The red door creaks at night / its hinges creak in moonlight."'
        cleaned = 'The red door creaks at night / its hinges creak in moonlight.'
        self.host['_tint_out_clean'] = mock.Mock(return_value=cleaned)
        operation = await self.trial('manual-cleanup-trial', candidate=supplied)
        self.assertEqual(operation['status'], 'completed', operation)
        self.host['_tint_out_clean'].assert_called_once_with(supplied)
        self.assertEqual(self.host['tint_evaluate'].call_args.args[1], cleaned)
        self.assertEqual(self.store.get_trial(operation['trial_id'])['candidate'], cleaned)
        response = await self.request('POST', 'apply', self.body('apply-cleaned-trial', trial_id=operation['trial_id']))
        await self.settle()
        self.assertEqual(self.store.get_operation(response.json()['operation']['id'])['status'], 'completed')
        self.assertEqual(self.host['line_review_recover'].call_args.args[0]['candidate'], cleaned)
        self.assertTrue(all(call.args[1] == cleaned for call in self.host['tint_evaluate'].call_args_list))
        self.host['call_ollama'].assert_not_awaited()

    async def test_generated_trial_selects_the_retained_content_kind_model_and_cleans_its_reply(self):
        self.row = self.reviews.record('tint', 'A gallery painting needs a frame.', 'A poor gallery rewrite.',
            ['rhyme'], context={'kind': 'gallery', 'stage': 'turn_rewrite',
                              'chunks': [{'text': 'Exact style sample.'}], 'crystal': 'Fixture style'})
        supplied = 'A: "A painting needs a frame / the gallery keeps its name."'
        cleaned = 'A painting needs a frame / the gallery keeps its name.'
        self.host['call_ollama'].return_value = {'message': {'content': supplied}}
        self.host['_tint_out_clean'] = mock.Mock(return_value=cleaned)
        response = await self.request('POST', 'try', self.body('generated-gallery-trial', instruction='Keep the painting and frame.'))
        self.assertEqual(response.status_code, 200, response.text)
        await self.settle()
        operation = self.store.get_operation(response.json()['operation']['id'])
        self.assertEqual(operation['status'], 'completed', operation)
        self.host['tint_model_for'].assert_called_once_with('gallery')
        self.assertEqual(self.host['call_ollama'].call_args.kwargs['model'], 'fixture-tint-model')
        self.host['_tint_out_clean'].assert_called_once_with(supplied)
        self.assertEqual(self.host['tint_evaluate'].call_args.args[1], cleaned)
        trial = self.store.get_trial(operation['trial_id'])
        self.assertEqual(trial['candidate'], cleaned)
        self.assertEqual(trial['provenance']['origin'], 'model_trial')
        self.host['line_review_recover'].assert_not_called()

    async def test_failing_trial_stale_settings_or_other_occurrence_cannot_be_applied(self):
        self.host['tint_evaluate'].side_effect = lambda *args: {'ok': True, 'machine_ok': False,
            'faults': [], 'machine_faults': ['missing rhyme']}
        failing = await self.trial('failing-trial-request')
        self.assertFalse(self.store.get_trial(failing['trial_id'])['evaluation']['ok'])
        response = await self.request('POST', 'apply', self.body('apply-failing-request', trial_id=failing['trial_id']))
        await self.settle()
        self.assertEqual(self.store.get_operation(response.json()['operation']['id'])['status'], 'failed')
        self.host['tint_evaluate'].side_effect = self.grade
        passing = await self.trial('passing-trial-request')
        self.store.update_settings(1, 'Preserve negation explicitly.', True)
        response = await self.request('POST', 'apply', self.body('apply-stale-settings', trial_id=passing['trial_id']))
        await self.settle()
        operation = self.store.get_operation(response.json()['operation']['id'])
        self.assertEqual(operation['status'], 'failed')
        self.assertIn('changed', operation['error'])
        other = self.record(source='A distinct source.', candidate='A distinct candidate.')
        response = await self.request('POST', 'apply', {
            'event_seq': other['event_seq'], 'expected_revision': other['revision'],
            'request_id': 'apply-wrong-occurrence', 'trial_id': passing['trial_id']}, review_id=other['id'])
        await self.settle()
        self.assertIn('different cut', self.store.get_operation(response.json()['operation']['id'])['error'])
        self.assertEqual(self.reviews.get(self.row['id'])['review_status'], 'pending')
        self.host['line_review_recover'].assert_not_called()

    async def test_explicit_apply_recovers_only_tested_candidate_once_without_changing_global_policy(self):
        policy = self.reviews.policy()
        passing = await self.trial()
        body = self.body('apply-tested-request', trial_id=passing['trial_id'])
        response = await self.request('POST', 'apply', body)
        self.assertEqual(response.status_code, 200, response.text)
        await self.settle()
        operation = self.store.get_operation(response.json()['operation']['id'])
        self.assertEqual(operation['status'], 'completed', operation)
        self.host['line_review_recover'].assert_called_once()
        recovered = self.host['line_review_recover'].call_args.args[0]
        self.assertEqual(recovered['candidate'], self.store.get_trial(passing['trial_id'])['candidate'])
        self.assertEqual(recovered['decision']['scope'], 'instance')
        self.assertEqual(self.reviews.policy(), policy)
        replay = await self.request('POST', 'apply', body)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()['operation']['id'], operation['id'])
        self.host['line_review_recover'].assert_called_once()

    async def test_workbench_history_pages_keep_full_original_trace_and_missing_trace_is_honest(self):
        missing = await self.request('GET', 'workbench?event_seq=' + str(self.row['event_seq']))
        self.assertFalse(missing.json()['trace']['available'])
        self.assertIn('No original prompt trace was captured', missing.json()['trace']['note'])
        row = self.reviews.record('tint', 'A trace-linked source.', 'A trace-linked candidate.', ['rhyme'],
            context={'stage': 'turn_rewrite', 'lab_trace_id': 'exact-run'})
        exact = '  Full prompt with Unicode Ω\n' + 'The original words remain. ' * 100
        for index in range(35):
            claim = self.store.begin(row['id'], row['event_seq'], 'discuss', f'history-{index}', {},
                                     messages=[{'role': 'user', 'content': str(index)}])
            self.store.finish(claim['operation']['id'], claim['lease_token'], result={'ok': True})
            self.store.append_trace('exact-run', {'index': index, 'prompt': exact})
        newer = await self.request('GET', 'workbench?event_seq=' + str(row['event_seq']), review_id=row['id'])
        data = newer.json()
        self.assertEqual(data['messages']['total'], 35)
        self.assertEqual(data['trace']['total'], 35)
        older = await self.request('GET', 'workbench?event_seq=' + str(row['event_seq'])
            + '&messages_before=' + str(data['messages']['next_before'])
            + '&trace_before=' + str(data['trace']['next_before']), review_id=row['id'])
        self.assertEqual([int(item['content']) for item in older.json()['messages']['items'] + data['messages']['items']], list(range(35)))
        traces = older.json()['trace']['items'] + data['trace']['items']
        self.assertEqual([item['record']['index'] for item in traces], list(range(35)))
        self.assertTrue(all(item['record']['prompt'] == exact for item in traces))
        self.host['call_ollama'].assert_not_awaited()

    async def test_original_trace_stops_at_the_cut_even_with_a_later_requested_page_cursor(self):
        records = [self.store.append_trace('original-cut-run', {'step': index, 'prompt': f'Exact step {index}.'})
                   for index in range(10)]
        cut_step = records[-1]['seq']
        row = self.reviews.record('tint', 'The original trace source.', 'The original rejected words.', ['rhyme'],
            context={'stage': 'turn_rewrite', 'lab_trace_id': 'original-cut-run', 'lab_cut_step': cut_step})
        later = [self.store.append_trace('original-cut-run', {'step': index, 'prompt': f'Later step {index}.'})
                 for index in range(10, 30)]
        suffix = 'workbench?event_seq=' + str(row['event_seq'])
        for cursor in ('', '&trace_before=' + str(later[-1]['seq'] + 100)):
            response = await self.request('GET', suffix + cursor, review_id=row['id'])
            self.assertEqual(response.status_code, 200, response.text)
            trace = response.json()['trace']
            self.assertEqual(trace['trace_id'], 'original-cut-run')
            self.assertEqual([item['record']['step'] for item in trace['items']], list(range(10)))
            self.assertTrue(all(item['seq'] <= cut_step for item in trace['items']))
        older = await self.request('GET', suffix + '&trace_before=' + str(records[4]['seq']), review_id=row['id'])
        self.assertEqual([item['record']['step'] for item in older.json()['trace']['items']], list(range(4)))
        self.host['call_ollama'].assert_not_awaited()
        self.host['line_review_recover'].assert_not_called()

    async def test_same_occurrence_discussion_and_trial_traces_remain_selectable_beyond_recent_operations(self):
        response = await self.request('POST', 'discuss', self.body('trace-discussion-request', message='Explain the observed cut.'))
        await self.settle()
        discussion = self.store.get_operation(response.json()['operation']['id'])
        discussion_trace = discussion['result']['trace_id']
        exact = 'The complete discussion prompt.\n' + 'Do not shorten these retained words. ' * 100
        self.store.append_trace(discussion_trace, {'prompt': exact, 'origin': 'discussion'})
        trial_operation = await self.trial('trace-trial-request')
        trial_trace = trial_operation['result']['trace_id']
        for index in range(35):
            claim = self.store.begin(self.row['id'], self.row['event_seq'], 'discuss', f'newer-operation-{index}', {})
            self.store.finish(claim['operation']['id'], claim['lease_token'], result={'trace_id': f'newer-run-{index}'})
        recent = await self.request('GET', 'workbench?event_seq=' + str(self.row['event_seq']))
        self.assertEqual(len(recent.json()['operations']), 30)
        self.assertNotIn(discussion['id'], [row['id'] for row in recent.json()['operations']])
        for trace_id in (discussion_trace, trial_trace):
            selected = await self.request('GET', 'workbench?event_seq=' + str(self.row['event_seq']) + '&trace_id=' + trace_id)
            self.assertEqual(selected.status_code, 200, selected.text)
            self.assertEqual(selected.json()['trace']['trace_id'], trace_id)
            self.assertIn(trace_id, [row['id'] for row in selected.json()['trace_sources']])
            if trace_id == discussion_trace:
                self.assertEqual(selected.json()['trace']['items'][0]['record']['prompt'], exact)
            else:
                self.assertEqual(selected.json()['trace']['items'][0]['record']['kind'], 'trial_evaluation')
        self.host['line_review_recover'].assert_not_called()

    async def test_trace_selection_rejects_another_occurrence_or_review_even_with_known_trace_ids(self):
        old = copy.deepcopy(self.row)
        later = self.record()
        self.assertEqual(later['id'], old['id'])
        self.assertNotEqual(later['event_seq'], old['event_seq'])
        other = self.reviews.record('tint', 'Another review source.', 'Another rejected candidate.', ['rhyme'],
            context={'stage': 'turn_rewrite', 'lab_trace_id': 'other-original-trace'})
        for row, trace_id in ((later, 'later-occurrence-trace'), (other, 'other-discussion-trace')):
            claim = self.store.begin(row['id'], row['event_seq'], 'discuss', 'foreign-trace-request', {})
            self.store.append_trace(trace_id, {'prompt': 'Full evidence belonging to another scope.'})
            self.store.finish(claim['operation']['id'], claim['lease_token'], result={'trace_id': trace_id})
        self.store.append_trace('other-original-trace', {'prompt': 'Another cut original evidence.'})
        for trace_id in ('later-occurrence-trace', 'other-discussion-trace', 'other-original-trace', 'unknown-trace'):
            response = await self.request('GET', 'workbench?event_seq=' + str(old['event_seq']) + '&trace_id=' + trace_id)
            self.assertEqual(response.status_code, 404, response.text)
            self.assertIn('does not belong', response.json()['detail'])
        self.host['call_ollama'].assert_not_awaited()
        self.host['line_review_recover'].assert_not_called()

    async def test_only_explicit_settings_post_changes_future_instruction_with_revision_conflict(self):
        original = self.store.settings()
        bad = await self.request('POST', '/api/orchestrator/rejection-lab/settings', {
            'expected_revision': 1, 'enabled': True, 'crystal_instruction': 'Preserve all questions.', 'apply_now': True})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.store.settings(), original)
        response = await self.request('POST', '/api/orchestrator/rejection-lab/settings', {
            'expected_revision': 1, 'enabled': True, 'crystal_instruction': 'Preserve all questions.'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['revision'], 2)
        conflict = await self.request('POST', '/api/orchestrator/rejection-lab/settings', {
            'expected_revision': 1, 'enabled': False, 'crystal_instruction': ''})
        self.assertEqual(conflict.status_code, 409)
        self.assertTrue(self.store.settings()['enabled'])
        self.host['call_ollama'].assert_not_awaited()
        self.host['line_review_recover'].assert_not_called()

    async def test_technical_cut_supports_discussion_but_never_trial_grading(self):
        technical = self.record(source='Audio is absent.', candidate='A missing file.', technical=True)
        response = await self.request('POST', 'try', {'event_seq': technical['event_seq'],
            'expected_revision': technical['revision'], 'request_id': 'technical-try-request',
            'candidate': 'A candidate cannot repair a missing file.'}, review_id=technical['id'])
        self.assertEqual(response.status_code, 400, response.text)
        self.host['tint_evaluate'].assert_not_called()
        self.host['line_review_recover'].assert_not_called()


class EffectiveInstructionTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_crystal_turn_prompt_contains_only_explicitly_enabled_instruction(self):
        import app as station
        with tempfile.TemporaryDirectory() as folder:
            store = RejectionLabStore(Path(folder) / 'lab.sqlite3')
            instruction = 'Retain every question and its original concrete nouns.'
            store.update_settings(1, instruction, False)
            prompts = []
            async def writer(prompt, *args, **kwargs):
                prompts.append(prompt)
                raise asyncio.CancelledError
            with ExitStack() as stack:
                for name, replacement in {
                    '_REJECTION_LAB': store, '_LAB_RUNTIME': LabRuntime(store),
                    'ask_model': mock.AsyncMock(side_effect=writer),
                    'tint_seen': mock.Mock(), '_tint_flow': mock.Mock(),
                    'crystal_force': mock.Mock(return_value=.88),
                    'crystal_grade_strict': mock.Mock(return_value=True),
                    'crystal_tint_holds': mock.Mock(return_value=True),
                    'crystal_coverage_target': mock.Mock(return_value=100),
                }.items():
                    stack.enter_context(mock.patch.object(station, name, replacement))
                for enabled in (False, True):
                    if enabled:
                        store.update_settings(2, instruction, True)
                    with self.assertRaises(asyncio.CancelledError):
                        await station.crystal_turn.__wrapped__(
                            'The red door creaks at night and the window rattles in the cold wind.',
                            'Fixture rhyme world', [], kind='banter', model='fixture-model')
            self.assertEqual(len(prompts), 2)
            self.assertNotIn(instruction, prompts[0])
            self.assertIn(instruction, prompts[1])
            self.assertIn('instruction revision 3', prompts[1])


if __name__ == '__main__':
    unittest.main()
