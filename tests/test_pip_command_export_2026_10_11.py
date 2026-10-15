"""Exercise the real export request/claim/report handlers without booting the station."""
import ast
import asyncio
import json
import threading
import time
import types
import unittest
import uuid
from pathlib import Path
from typing import Any

SRC = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
NAMES = {'export_screen_request', 'export_screen_claim_api', 'export_screen_done_api',
         'export_screen_heartbeat_api', 'export_progress', 'chat_completions'}
TREE = ast.parse(SRC)

class Request:
    def __init__(self, **body): self.body = body
    async def json(self): return self.body

class ExportCommands(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = 1000
        self.ns = dict(Any=Any, Request=Request, Header=lambda **_:None,
            time=types.SimpleNamespace(time=lambda:self.clock, strftime=time.strftime), uuid=uuid,
            _SCREEN_EXPORT={}, _SCREEN_EXPORT_QUEUE=[], _SCREEN_EXPORT_FINISHED={},
            _SCREEN_EXPORT_LOCK=threading.RLock(), SCREEN_EXPORT_HOLD={'pip':1200,'app':600,'tab':1200},
            SCREEN_EXPORT_LIFE=180, SCREEN_EXPORT_NAMES={'pip':'PinePiP'}, _EXPORT_UPLOADS={},
            export_desk_dir=lambda:'exports', spoken_folder=str, _screen_export_minutes=str,
            require_auth=lambda _:None, pipeline_log=lambda *_:None, note_action=lambda _:None,
            courier_read=lambda:[])
        nodes = []
        for node in TREE.body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in NAMES:
                node.decorator_list=[]
                nodes.append(node)
        exec(compile(ast.Module(nodes,[]),'app.py','exec'),self.ns)

    def order(self):
        reply = self.ns['export_screen_request']({'screen':'pip','seconds':300})
        if not self.ns['_SCREEN_EXPORT_QUEUE']:
            self.assertNotIn('Queued', reply)
        return dict(self.ns['_SCREEN_EXPORT'])

    async def test_chat_export_runs_without_model_and_streaming_creates_only_one_job(self):
        async def no_inbox(*_): return None
        self.ns.update(latest_user_text=lambda messages:messages[-1]['content'],
                       pine_conversation=no_inbox, pine_conversation_session=lambda *_:'',
                       llm_commands=types.SimpleNamespace(rewrite=lambda text:(text,)),
                       parse_export_command=lambda _: {'screen':'pip','seconds':300}, json=json,
                       StreamingResponse=lambda events, **_:events)
        # The model/context functions are deliberately absent: this must finish
        # using just the deterministic export path, including streamed replies.
        response=await self.ns['chat_completions'](Request(messages=[{'role':'user','content':'export the last 5 minutes from Pine Pip'}]))
        self.assertEqual(response['model'],'cutter')
        self.assertEqual(self.ns['_SCREEN_EXPORT']['seconds'],300)
        stream=await self.ns['chat_completions'](Request(messages=[{'role':'user','content':'export the last 5 minutes from Pine Pip'}],stream=True))
        chunks=[chunk async for chunk in stream]
        self.assertIn('[DONE]',chunks[-1])
        self.assertEqual(len(self.ns['_SCREEN_EXPORT_QUEUE']),1)

    async def call(self,name,**body):
        return await self.ns['export_screen_'+name+'_api'](Request(**body))

    async def test_lease_can_recover_after_renderer_disappears_but_not_during_long_encode(self):
        order=self.order()
        claim=await self.call('claim',id=order['id'],device='pip',owner='first')
        self.assertTrue(claim['go'])
        self.clock+=100
        self.assertTrue((await self.call('heartbeat',id=order['id'],owner='first'))['ok'])
        self.clock+=100
        self.assertFalse((await self.call('claim',id=order['id'],device='pip',owner='second'))['go'])
        self.clock+=21
        claim=await self.call('claim',id=order['id'],device='pip',owner='second')
        self.assertTrue(claim['go'])
        self.assertEqual(claim['age_ms'],221000)
        self.assertFalse((await self.call('done',id=order['id'],owner='first',ok=True))['ok'])

    async def test_repeated_commands_queue_and_completion_retry_does_not_finish_next_order(self):
        first=self.order()
        await self.call('claim',id=first['id'],device='pip',owner='desk')
        self.clock+=1
        self.order()
        self.assertEqual(self.ns['_SCREEN_EXPORT']['id'],first['id'])
        second=self.ns['_SCREEN_EXPORT_QUEUE'][0]
        self.assertNotEqual(first['name'],second['name'])
        report=dict(id=first['id'],owner='desk',ok=True,result={'where':'local.mp4','seconds':300})
        self.assertTrue((await self.call('done',**report))['ok'])
        self.assertEqual(self.ns['_SCREEN_EXPORT']['id'],second['id'])
        self.assertTrue((await self.call('done',**report))['ok'])
        self.assertFalse(self.ns['_SCREEN_EXPORT']['done'])

    async def test_local_save_is_success_even_when_upload_is_unavailable(self):
        order=self.order()
        await self.call('claim',id=order['id'],device='pip',owner='desk')
        await self.call('done',id=order['id'],owner='desk',ok=True,result={
            'where':'local.mp4','seconds':298,'uploaded':{'ok':False},'warning':'Audio has gaps.'})
        progress=self.ns['export_progress']()
        self.assertEqual(progress['stage'],'saved')
        self.assertIn('local.mp4',progress['say'])
        self.assertIn('Audio has gaps',progress['say'])

if __name__ == '__main__': unittest.main()
