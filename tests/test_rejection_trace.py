"""Exact diagnostic evidence stays inside its originating asynchronous pass."""
import asyncio
import copy
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app
from line_review import LineReviewStore
from rejection_lab import RejectionLabStore
from rejection_lab_runtime import LabRuntime


class RejectionTraceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RejectionLabStore(Path(self.temp.name) / 'lab.sqlite3')
        self.runtime = LabRuntime(self.store)

    def records(self, trace_id):
        return [row['record'] for row in self.store.trace_history(trace_id, limit=200)['items']]

    async def test_full_messages_options_and_reply_are_not_truncated_or_mutable(self):
        source = ('Exact Mixed Case café words, with \n spaces. ' * 220)
        messages = [{'role': 'system', 'content': source}, {'role': 'user', 'content': source[::-1]}]
        reply = {'message': {'content': 'An actual raw reply. ' * 500}, 'eval_count': 500}

        @self.runtime.model_call
        async def model(*, messages, temperature=.35, seed=None):
            return reply

        @self.runtime.scoped('outer')
        async def run(text):
            trace_id = self.runtime.current_id()
            self.assertIs(await model(messages=messages, seed=901), reply)
            return trace_id

        trace_id = await run(source)
        records = self.records(trace_id)
        request = next(row['details'] for row in records if row['kind'] == 'model_request')
        response = next(row['details'] for row in records if row['kind'] == 'model_response')
        self.assertEqual(request['messages'], messages)
        self.assertEqual(request['temperature'], .35)
        self.assertEqual(request['seed'], 901)
        self.assertEqual(response['response'], reply)
        self.assertEqual(request['call_id'], response['call_id'])
        messages[0]['content'] = 'changed afterward'
        reply['message']['content'] = 'changed afterward'
        saved = self.records(trace_id)
        self.assertEqual(saved[1]['details']['messages'][0]['content'], source)
        self.assertNotEqual(saved[2]['details']['response']['message']['content'], 'changed afterward')
        self.assertEqual(self.runtime.current_id(), '')

    async def test_concurrent_passes_and_nested_stages_keep_exact_decision_pointers(self):
        reviews = LineReviewStore(Path(self.temp.name) / 'reviews.sqlite3')
        ready = asyncio.Event()
        started = 0

        @self.runtime.model_call
        async def model(*, messages):
            await ready.wait()
            await asyncio.sleep(0)
            self.runtime.record('model_wire_request', {'call_id': self.runtime.call.get(), 'messages': messages})
            return {'message': {'content': messages[0]['content'] + ' reply'}}

        @self.runtime.scoped('inner')
        async def inner(text):
            response = await model(messages=[{'role': 'user', 'content': text}])
            return app.line_review_capture('tint', text, response['message']['content'], ['rhyme'],
                context={'kind': 'banter', 'stage': 'turn_cut', 'turn': 1})

        @self.runtime.scoped('outer')
        async def outer(text):
            nonlocal started
            started += 1
            if started == 2:
                ready.set()
            trace_id = self.runtime.current_id()
            row = await inner(text)
            self.assertEqual(row['context']['lab_trace_id'], trace_id)
            return trace_id, row

        with mock.patch.object(app, '_LAB_RUNTIME', self.runtime), mock.patch.object(app, '_LINE_REVIEW', reviews), \
                mock.patch.object(app, 'station_flow_event'), mock.patch.object(app, '_LINE_REVIEW_CONTEXT') as ambient:
            ambient.get.return_value = {}
            results = await asyncio.gather(outer('First actual source.'), outer('Second actual source.'))
        self.assertNotEqual(results[0][0], results[1][0])
        for trace_id, row in results:
            records = self.records(trace_id)
            request = next(item['details'] for item in records if item['kind'] == 'model_request')
            wire = next(item['details'] for item in records if item['kind'] == 'model_wire_request')
            cut = next(item['details'] for item in records if item['kind'] == 'rejection')
            self.assertEqual(request['messages'][0]['content'], row['source'])
            self.assertEqual(wire['call_id'], request['call_id'])
            self.assertEqual(wire['messages'], request['messages'])
            self.assertEqual((cut['review_id'], cut['event_seq']), (row['id'], row['event_seq']))
            self.assertEqual(cut['candidate'], row['candidate'])
            self.assertEqual([item['details']['stage'] for item in records if item['kind'] == 'stage_started'], ['outer', 'inner'])
        self.assertEqual(self.runtime.current_id(), '')
        self.assertEqual(self.runtime.call.get(), '')

    async def test_model_error_and_cancellation_are_captured_and_context_is_reset(self):
        for failure in (RuntimeError('Exact upstream failure'), asyncio.CancelledError('cancelled request')):
            seen = []

            @self.runtime.model_call
            async def model(*, messages):
                raise failure

            @self.runtime.scoped('failing')
            async def run():
                seen.append(self.runtime.current_id())
                await model(messages=[{'role': 'user', 'content': 'Failed source.'}])

            with self.subTest(failure=type(failure).__name__), self.assertRaises(type(failure)):
                await run()
            records = self.records(seen[0])
            request = next(item['details'] for item in records if item['kind'] == 'model_request')
            error = next(item['details'] for item in records if item['kind'] == 'model_error')
            self.assertEqual(request['call_id'], error['call_id'])
            self.assertEqual(error['error'], str(failure))
            self.assertEqual(error['error_type'], type(failure).__name__)
            self.assertEqual(records[-1]['kind'], 'stage_failed')
            self.assertEqual(self.runtime.current_id(), '')
            self.assertEqual(self.runtime.call.get(), '')

    async def test_invalid_invocation_does_not_leave_trace_scope_on_later_work(self):
        @self.runtime.scoped('requires-text')
        async def run(text):
            return text

        with self.assertRaises(TypeError):
            await run()
        self.assertEqual(self.runtime.current_id(), '')
        self.assertIsNone(self.runtime.record('unrelated', {'source': 'Later independent work'}))

    async def test_capture_failure_is_visible_but_does_not_change_result_or_unscoped_work(self):
        @self.runtime.model_call
        async def model(*, messages):
            return {'message': {'content': 'The exact result'}}

        @self.runtime.scoped('working')
        async def run():
            return await model(messages=[{'role': 'user', 'content': 'The source'}])

        with mock.patch.object(self.store, 'append_trace', side_effect=OSError('disk unavailable')) as append:
            self.assertEqual((await run())['message']['content'], 'The exact result')
            self.assertGreater(self.runtime.errors, 0)
            self.assertEqual(self.runtime.last_error, 'OSError')
            count = append.call_count
            await model(messages=[{'role': 'user', 'content': 'Unscoped'}])
            self.assertEqual(append.call_count, count)
        self.assertEqual(self.runtime.current_id(), '')

    async def test_actual_ollama_wire_messages_and_raw_response_match_trace(self):
        messages = [{'role': 'system', 'content': 'Complete system instruction\n' * 150},
                    {'role': 'user', 'content': 'Full case-sensitive source and context.\n' * 200}]
        response_body = {'message': {'content': 'Raw model result\n' * 300}, 'eval_count': 22}
        requests = []

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, *, json):
                requests.append(copy.deepcopy(json))
                response = mock.Mock()
                response.json.return_value = copy.deepcopy(response_body)
                return response

        with ExitStack() as stack:
            for name, value in {'_LAB_RUNTIME': self.runtime, '_OLLAMA_JOBS': {}, '_OLLAMA_ONE': {},
                                '_OLLAMA_GATE': asyncio.Semaphore(2)}.items():
                stack.enter_context(mock.patch.object(app, name, value))
            stack.enter_context(mock.patch.object(app.httpx, 'AsyncClient', return_value=Client()))
            actual_call = self.runtime.model_call(app.call_ollama.__wrapped__)
            token = self.runtime.scope.set({'trace_id': 'actual-wire-test'})
            try:
                got = await actual_call(model='isolated-fixture-model', messages=messages,
                    temperature=.7, max_tokens=321, top_p=.87, num_ctx=4096, seed=17,
                    repeat_penalty=1.12, purpose='interactive:rejection-lab')
            finally:
                self.runtime.scope.reset(token)
        records = self.records('actual-wire-test')
        request = next(item['details'] for item in records if item['kind'] == 'model_request')
        wire = next(item['details'] for item in records if item['kind'] == 'model_wire_request')
        response = next(item['details'] for item in records if item['kind'] == 'model_response')
        self.assertEqual(wire['call_id'], request['call_id'])
        self.assertEqual(wire['body'], requests[0])
        self.assertEqual(request['messages'], requests[0]['messages'])
        self.assertEqual(response['response'], got)
        self.assertEqual(got, response_body)
        self.assertEqual(requests[0]['options'], {'temperature': .7, 'top_p': .87,
            'num_predict': 321, 'num_ctx': 4096, 'seed': 17, 'repeat_penalty': 1.12})
        self.assertFalse(requests[0]['think'])
        self.assertEqual(self.runtime.current_id(), '')


if __name__ == '__main__':
    unittest.main()
