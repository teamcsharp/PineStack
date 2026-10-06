"""An audible board receipt must not hold the station on slow shelf metadata."""
import ast
import asyncio
from pathlib import Path
import re
import threading
import unittest


class SfxReceiptFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_durable_receipt_precedes_background_history_and_no_duplicate_lookup(self):
        source=(Path(__file__).resolve().parents[1]/'app.py').read_text(encoding='utf-8')
        nodes=[]
        for name in ('_sfx_cadence_history','_sfx_cadence_audible'):
            tail=source[source.index('def '+name+'('):]
            end=re.search(r'(?m)^(?:def |async def |[A-Z_]\w*\s*=)',tail[tail.index('\n')+1:])
            nodes.append(ast.parse(tail[:tail.index('\n')+1+end.start()]).body[0])
        loop_thread=threading.get_ident();events=[];tasks=[];seen=set()
        class Cadence:
            def record(self,rows):
                added={row['id'] for row in rows}-seen;seen.update(added)
                events.append(('receipt',threading.get_ident()))
                return added
        def lookup(sample):
            events.append(('lookup',threading.get_ident()))
            return Path('fixture.wav')
        ns=dict(asyncio=asyncio,_SFX_CADENCE=Cadence(),sfx_by_id=lookup,
            sfx_history_add=lambda *args:events.append(('history',threading.get_ident())),
            sfx_note_play=lambda *args:None,fire_and_forget=lambda coro:tasks.append(asyncio.create_task(coro)),
            note_activity=lambda *args,**kwargs:events.append(('activity',threading.get_ident())),
            cast_name=lambda who:who)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'board receipt adapters','exec'),ns)
        rows=[{'id':'fixture','from':0,'until':1,'who':'sfxguy','sfx_sample_id':'sample','text':'fixture'}]
        ns['_sfx_cadence_audible'](rows,2)
        ns['_sfx_cadence_audible'](rows,2)
        self.assertEqual(len(tasks),1)
        self.assertNotIn('lookup',[event[0] for event in events])
        await asyncio.gather(*tasks)
        self.assertEqual([event[0] for event in events].count('history'),1)
        self.assertTrue(all(tid!=loop_thread for name,tid in events if name in ('lookup','history')))
        self.assertTrue(all(tid==loop_thread for name,tid in events if name in ('receipt','activity')))
