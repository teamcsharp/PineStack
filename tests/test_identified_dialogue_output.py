"""Model wording cannot change the roulette's turn ownership or immutable source."""
import ast
from contextlib import asynccontextmanager
import copy
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
import handoff_preparation as hp


def adapter(name):
    text=(Path(__file__).resolve().parents[1]/'app.py').read_text(encoding='utf-8')
    tail=text[text.index('async def '+name+'('):]
    end=re.search(r'(?m)^(?:@|(?:async )?def |class |[A-Z_]\w*\s*=)',tail[tail.index('\n')+1:])
    return ast.parse(tail[:tail.index('\n')+1+end.start()]).body[0]


class IdentifiedDialogueTests(unittest.IsolatedAsyncioTestCase):
    def request(self):
        return {'mode':'recover_exchange','identified_output':True,'char_budget':350,
            'planned_turns':[{'turn_id':'one','speaker':'B','name':'Fixture One'},
                             {'turn_id':'two','speaker':'D','name':'Fixture Two'},
                             {'turn_id':'three','speaker':'A','name':'Fixture Three','mandatory_closing':True}],
            'preserved_rows':[{'turn_id':'two','speaker':'D','index':1,'text':'Exact source: fifty dollars.'}],
            'participants':[],'subject':{},'source_rows':[], 'recovery':{'seed':'fixture','operation':'rewrite'}}

    async def test_json_key_order_cannot_change_speaker_order_and_fixed_copy_is_local(self):
        request=self.request();received=[]
        async def ask(prompt,**kwargs):
            received.append(kwargs)
            return json.dumps({'turn_0002':'Then let us close here.','turn_0000':'That follows the earlier detail.'})
        result=await hp.write_turn(request,ask,str.strip)
        self.assertEqual(result,'B: That follows the earlier detail.\nD: Exact source: fifty dollars.\nA: Then let us close here.')
        self.assertEqual(len(received),1)
        self.assertEqual(received[0]['result_contract'],'json')
        self.assertEqual(received[0]['result_schema']['required'],['turn_0000','turn_0002'])
        self.assertFalse(received[0]['result_schema']['additionalProperties'])

    async def test_wrong_missing_duplicate_and_embedded_speaker_output_are_rejected(self):
        bad=['{}','{"turn_0000":"First.","extra":"Extra.","turn_0002":"Last."}',
             '{"turn_0000":"First.","turn_0000":"Different.","turn_0002":"Last."}',
             '{"turn_0000":"B: First.","turn_0002":"Last."}',
             '{"turn_0000":42,"turn_0002":"Last."}',
             json.dumps({'turn_0000':'x'*1000,'turn_0002':'Last.'})]
        for raw in bad:
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                await hp.write_turn(self.request(),AsyncMock(return_value=raw),str.strip)

    async def test_all_protected_rows_make_no_model_call(self):
        request=self.request()
        request['preserved_rows']=[{'index':i,'turn_id':t['turn_id'],'speaker':t['speaker'],'text':'Exact '+str(i)+'.'} for i,t in enumerate(request['planned_turns'])]
        ask=AsyncMock()
        self.assertEqual(await hp.write_turn(request,ask,str.strip),'B: Exact 0.\nD: Exact 1.\nA: Exact 2.')
        ask.assert_not_awaited()

    async def test_invalid_protected_identity_is_not_reassigned(self):
        request=self.request();request['preserved_rows'][0]['turn_id']='removed'
        ask=AsyncMock()
        with self.assertRaisesRegex(ValueError,'matching planned identity'):
            await hp.write_turn(request,ask,str.strip)
        ask.assert_not_awaited()

    def test_long_plan_budget_remains_inside_operator_output_limit(self):
        request=self.request();request['preserved_rows']=[]
        planned=[{'index':i,'turn_id':str(i),'speaker':'A'} for i in range(25)]
        keys,fixed,schema,ceiling=hp._identified_contract(request,planned,350)
        self.assertEqual(len(keys),25)
        self.assertLessEqual(sum(p['maxLength'] for p in schema['properties'].values())*2+32*len(keys)+8,ceiling)

    async def test_real_handoff_adapter_enables_identified_contract_and_output_limit(self):
        request={'mode':'recover_exchange'};captured=[]
        async def prepare(handle,rows,writer,**kwargs):
            await writer(request)
            return {'status':'ready'}
        with __import__('unittest.mock',fromlist=['patch']).patch.object(hp,'write_turn',AsyncMock(return_value='fixture')) as write:
            ns={'Any':object,'system3_handoff_exchange':prepare,'dj_settings':lambda:{'reply_max_chars':2048},
                'seat_away_who':lambda:'','ask_model':object(),'writer_turn_clean':str.strip,
                'copy':copy,'WritingDeferred':type('WritingDeferred',(Exception,),{})}
            exec(compile(ast.Module(body=[adapter('_s3_handoff_rows')],type_ignores=[]),'actual handoff adapter','exec'),ns)
            await ns['_s3_handoff_rows']({},[('B','fixture')],'banter',{})
            self.assertTrue(write.call_args.args[0]['identified_output'])
            self.assertEqual(write.call_args.args[0]['output_char_limit'],2048)

    async def test_actual_ollama_wire_carries_schema_without_changing_admission(self):
        @asynccontextmanager
        async def context(*args,**kwargs):yield object()
        captured=[]
        async def post(client,url,**kwargs):
            captured.append(kwargs['json'])
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'message':{'content':'{}'}})
        import asyncio,time,uuid
        ns=dict(Any=object,asyncio=asyncio,time=time,uuid=uuid,copy=copy,
            gazette_prompt_messages=AsyncMock(side_effect=lambda value:value),_PB_OPEN='fixture-marker',
            orch_used=Mock(),_ollama_category=lambda purpose:('station',2),_harvest_yields=AsyncMock(),
            _live_round_waits=AsyncMock(),_OLLAMA_JOBS={},_ollama_lane=context,_OLLAMA_GATE=context(),
            httpx=SimpleNamespace(AsyncClient=context),_LAB_RUNTIME=SimpleNamespace(record=Mock(),call=SimpleNamespace(get=lambda:None)),
            recorded_ollama_post=post,OLLAMA_URL='http://fixture')
        exec(compile(ast.Module(body=[adapter('call_ollama')],type_ignores=[]),'actual Ollama adapter','exec'),ns)
        schema={'type':'object','properties':{'turn_0000':{'type':'string'}},'required':['turn_0000']}
        await ns['call_ollama'](model='fixture',messages=[{'role':'user','content':'fixture'}],temperature=.5,max_tokens=100,result_schema=schema)
        self.assertEqual(captured[0]['format'],schema)
        self.assertEqual(ns['_OLLAMA_JOBS'],{})
