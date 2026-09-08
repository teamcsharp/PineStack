"""Local retrieval wiring and background lifecycle; every embedder is mocked."""
import asyncio
import hashlib
import threading
import unittest
from contextlib import ExitStack
from unittest import mock

import app
import crystal_prompts


class RhymeAssistanceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.provider=mock.Mock()
        self.state={}
        self.pending={}
        self.embed=mock.AsyncMock(side_effect=AssertionError('unexpected embed call'))
        self.trace=mock.Mock()
        for name,value in {'_RHYME_ASSISTANCE':self.provider,
            '_RHYME_ASSISTANCE_PENDING':self.pending,'_RHYME_ASSISTANCE_STATE':self.state,
            '_embed_texts':self.embed,'_OLLAMA_JOBS':{},'_OLLAMA_GATE':asyncio.Semaphore(2),
            '_RHYME_ASSISTANCE_EMBED_LOCK':asyncio.Lock(),
            '_crystal_vocab':mock.Mock(return_value=set()),'EMBED_MODEL':'test-local'}.items():
            self.stack.enter_context(mock.patch.object(app,name,value))
        self.stack.enter_context(mock.patch.object(app._LAB_RUNTIME,'record',self.trace))
        self.provider.query_cached.return_value=False
        self.source='Explain the remaining records.'
        self.evidence={'ready':True,'version':1,'revision':'pinned-corpus',
            'source_sha256':hashlib.sha256(self.source.encode()).hexdigest(),
            'endings':[{'anchor':'records','anchor_in_source':True,'rhyme_phones':['AO','R','D','Z'],
                'options':[{'word':'cords','phones':['K','AO1','R','D','Z']}]}],
            'related':[],'search':{'neural_used':False}}
        self.provider.assist.return_value=self.evidence

    async def test_real_source_contract_reaches_turn_round_and_preview_without_model_or_query_write(self):
        token=app._REJECTION_LAB_PREVIEW.set(True)
        try:contract=app.crystal_prompt_contract(self.source)
        finally:app._REJECTION_LAB_PREVIEW.reset(token)
        prompt=crystal_prompts.turn_prompt(self.source,'world',[],.88,'banter',contract=contract)
        self.assertIn('pinned-corpus',prompt)
        self.assertEqual(prompt.count('pinned-corpus'),1)
        rounded=crystal_prompts.round_prompt([('A',self.source)],'world',[],.88,'banter',contracts=[contract])
        self.assertIn('"word_options"',rounded)
        self.assertEqual(self.pending,{})
        self.embed.assert_not_awaited()
        self.trace.assert_called_once_with('rhyme_assistance',self.evidence)

    async def test_normal_prompt_queues_bounded_future_queries_without_embedding_inline(self):
        for i in range(80):app.crystal_prompt_contract(self.source+str(i))
        self.assertEqual(len(self.pending),64)
        self.embed.assert_not_awaited()

    async def test_grading_contract_does_not_retrieve_or_enqueue_words(self):
        app.crystal_source_contract(self.source)
        self.provider.assist.assert_not_called()
        self.assertEqual(self.pending,{})

    async def test_busy_model_lane_never_launches_embedding_work(self):
        with mock.patch.object(app,'_OLLAMA_JOBS',{'work':{'state':'active'}}):
            self.assertFalse(await app.crystal_rhyme_warm_once())
        self.provider.embedding_batch.assert_not_called()
        self.embed.assert_not_awaited()

    async def test_one_bounded_batch_persists_real_returned_vectors_then_query(self):
        self.pending['one']=self.source
        rows=[{'id':'noun:0001','text':'cited definition','sha256':'h','revision':'r'}]
        self.provider.embedding_batch.return_value=rows
        self.embed.side_effect=None;self.embed.return_value=[[1.0]*8,[2.0]*8]
        self.assertTrue(await app.crystal_rhyme_warm_once())
        self.embed.assert_awaited_once_with(['cited definition',self.source])
        self.provider.put_embeddings.assert_called_once_with('test-local',rows,[[1.0]*8])
        self.provider.put_query_embedding.assert_called_once_with(self.source,'test-local',[2.0]*8)
        self.assertEqual(self.pending,{})

    async def test_failed_or_cancelled_embedding_keeps_pending_source_without_partial_vectors(self):
        self.pending['one']=self.source
        self.provider.embedding_batch.return_value=[{'text':'definition'}]
        self.embed.side_effect=None;self.embed.return_value=[]
        with self.assertRaisesRegex(ValueError,'incomplete'):await app.crystal_rhyme_warm_once()
        self.assertEqual(self.pending,{'one':self.source})
        self.provider.put_embeddings.assert_not_called()
        self.embed.side_effect=asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):await app.crystal_rhyme_warm_once()
        self.assertEqual(self.pending,{'one':self.source})
        self.provider.put_query_embedding.assert_not_called()

    async def test_shutdown_joins_import_thread_before_closing_sqlite(self):
        started=threading.Event();release=threading.Event();finished=threading.Event()
        provider=mock.Mock()
        def initialize():
            started.set();release.wait(3);finished.set()
        provider.initialize.side_effect=initialize
        def close():self.assertTrue(finished.is_set(),'closed SQLite while import thread was active')
        provider.close.side_effect=close
        with mock.patch('rhyme_assistance.RhymeAssistance',return_value=provider):
            task=asyncio.create_task(app.crystal_rhyme_clock())
            self.assertTrue(await asyncio.to_thread(started.wait,2))
            task.cancel();await asyncio.sleep(.01)
            provider.close.assert_not_called()
            release.set()
            with self.assertRaises(asyncio.CancelledError):await task
        provider.close.assert_called_once()

    async def test_two_warm_requests_cannot_duplicate_an_active_embedding_batch(self):
        entered=asyncio.Event();release=asyncio.Event()
        self.provider.embedding_batch.return_value=[{'text':'definition'}]
        async def embed(texts):
            entered.set();await release.wait();return [[1.0]*8]
        self.embed.side_effect=embed
        first=asyncio.create_task(app.crystal_rhyme_warm_once())
        await entered.wait()
        self.assertFalse(await app.crystal_rhyme_warm_once())
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):await first
        self.assertFalse(app._RHYME_ASSISTANCE_EMBED_LOCK.locked())
        self.assertEqual(self.embed.await_count,1)


if __name__=='__main__':unittest.main()
