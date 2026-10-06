"""Exercise real claim logic with leased jobs; no station startup needed."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

tree=ast.parse((Path(__file__).parents[1]/'system2_runtime.py').read_text(encoding='utf-8'))
runtime=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='System2Runtime')
method=next(n for n in runtime.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_claim_preparation')
namespace={'asyncio':asyncio}
exec(compile(ast.Module(body=[method],type_ignores=[]),'claim-production','exec'),namespace)
claim=namespace['_claim_preparation']


class ConversationPriorityTests(unittest.IsolatedAsyncioTestCase):
    def host(self, jobs, candidates=(), paused=False):
        return SimpleNamespace(_candidates=list(candidates),_conversation_last_priority=False,
            config={'horizon_hours':2},host=SimpleNamespace(radio_paused=lambda:paused),
            store=SimpleNamespace(claim_job=Mock(side_effect=jobs)))

    async def test_ads_cannot_satisfy_the_conversation_floor(self):
        job={'kind':'banter','slot_id':'conversation','token':'real-lease'}
        h=self.host([job],[{'kind':'ad','ready':True,'eligible':True,'seconds':400}])
        result=await claim(h,['ad','caller','banter'],3600)
        self.assertIs(result,job)
        self.assertTrue(result['conversation_reserve_priority'])
        self.assertEqual(h.store.claim_job.call_args.kwargs['kinds'],['banter'])
        self.assertEqual(result['token'],'real-lease')

    async def test_empty_reserve_alternates_with_normal_deadline_work(self):
        h=self.host([{'kind':'banter'},{'kind':'caller'},{'kind':'banter'}])
        kinds=['caller','banter']
        self.assertEqual((await claim(h,kinds,3600))['kind'],'banter')
        self.assertEqual((await claim(h,kinds,3600))['kind'],'caller')
        self.assertEqual((await claim(h,kinds,3600))['kind'],'banter')
        self.assertEqual([c.kwargs['kinds'] for c in h.store.claim_job.call_args_list],
                         [['banter'],kinds,['banter']])

    async def test_ready_conversation_resumes_normal_planning(self):
        ready={'kind':'banter','ready':True,'eligible':True,'seconds':20}
        h=self.host([{'kind':'gallery'}],[ready,ready.copy()])
        await claim(h,['gallery','banter'],3600)
        self.assertEqual(h.store.claim_job.call_args.kwargs['kinds'],['gallery','banter'])

    async def test_blocked_drafts_do_not_count_as_reserve(self):
        h=self.host([{'kind':'banter'}],[{'kind':'banter','ready':True,'eligible':False,'seconds':50}])
        await claim(h,['caller','banter'],3600)
        self.assertEqual(h.store.claim_job.call_args.kwargs['kinds'],['banter'])

    async def test_no_claimable_banter_falls_back_without_inventing_a_job(self):
        job={'kind':'caller','slot_id':'call','token':'owned'}
        h=self.host([None,job])
        self.assertIs(await claim(h,['caller','banter'],3600),job)
        self.assertFalse(h._conversation_last_priority)

    async def test_pause_and_busy_banter_road_keep_normal_claims(self):
        for paused,kinds in ((True,['banter','caller']),(False,['caller'])):
            h=self.host([{'kind':'caller'}],paused=paused)
            await claim(h,kinds,3600)
            self.assertEqual(h.store.claim_job.call_args.kwargs['kinds'],kinds)

    async def test_far_future_evergreen_fallback_is_preserved(self):
        h=self.host([None,None,{'kind':'gallery'}])
        result=await claim(h,['banter','ad','gallery'],3600)
        self.assertEqual(result['kind'],'gallery')
        self.assertEqual(h.store.claim_job.call_args.kwargs['kinds'],['ad','gallery'])
        self.assertEqual(h.store.claim_job.call_args.kwargs['lookahead_seconds'],7200)
