"""Verified archive references and truthful H3 source provenance."""
import asyncio, copy, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from supercut_h3_bridge import SupercutH3Bridge, install

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.audio=self.root/'supercut.wav'; self.audio.write_bytes(b'verified audio')
        self.detail={'id':'sca-good','product':'Pine Mug','seconds':45,'audio_sha256':'trusted-hash',
            'audio_url':'signed/audio','recorded_text':'Welcome to Pine Box FM'}
        self.archive=SimpleNamespace(audio=self.resolve_audio,detail=lambda ident:copy.deepcopy(self.detail))
        self.renderer=AsyncMock(return_value={'prompt_id':'render-1','duration_s':10})
        self.host={'_sfx_supercut_runtime':SimpleNamespace(archive=self.archive),
            '_comfy_workshop_render_payload':self.renderer,
            'workshop_source_path':lambda kind, ident:(self.root/'old',kind),
            'workshop_reference_view':lambda row:{'legacy':True},
            'h3_prompts_load':lambda:{'presets':[{'id':'saved','name':'My saved prompt','clip':'Animate {conversation}',
                'style':'cinematic','audio_direction':'Use the reference','constraints':'Keep the dialogue'}]},
            'h3_prompts_fields':lambda preset:dict(preset),
            'h3_prompts_fill':lambda prompt,**kw:prompt.replace('{conversation}',kw['conversation'])}
        self.bridge=SupercutH3Bridge(self.host)
    def resolve_audio(self, ident):
        if ident!='sca-good':raise FileNotFoundError('Missing verified archive')
        return self.audio
    def test_existing_reference_types_remain_available(self):
        self.assertEqual(self.bridge.resolve('clip','old')[1],'clip')
        self.assertEqual(self.bridge.reference({'source_type':'clip'}),{'legacy':True})
        self.assertEqual(self.bridge.resolve('supercut','sca-good'),(self.audio,'audio'))
        self.assertEqual(self.bridge.reference({'source_type':'supercut','source':'sca-good'})['url'],'signed/audio')
        self.assertFalse(self.bridge.reference({'source_type':'supercut','source':'missing'})['available'])
    def test_render_forces_verified_reference_without_new_speech_or_airing(self):
        result=asyncio.run(self.bridge.render('sca-good',{'prompt':'Make a neon spot','source':'forged',
            'source_type':'clip','mode':'text','speech':'fake text','hourly':True,'air_it':False,'duration_s':12}))
        payload=self.renderer.call_args.args[0]
        self.assertEqual((payload['mode'],payload['source_type'],payload['source']),('reference','supercut','sca-good'))
        self.assertEqual(payload['speech'],'');self.assertFalse(payload['hourly']);self.assertFalse(payload['air_it'])
        self.assertEqual(payload['duration_s'],12);self.assertFalse(result['autoplay'])
        self.assertEqual(result['source']['audio_sha256'],'trusted-hash');self.assertTrue(result['source_only_input'])
        self.assertEqual(self.audio.read_bytes(),b'verified audio')
    def test_preset_fills_actual_words_and_explicit_prompt_can_override(self):
        asyncio.run(self.bridge.render('sca-good',{'preset_id':'saved'}))
        payload=self.renderer.call_args.args[0]
        self.assertEqual(payload['prompt'],'Animate Welcome to Pine Box FM')
        self.assertEqual(payload['style'],'cinematic');self.assertEqual(payload['h3_prompts']['id'],'saved')
        asyncio.run(self.bridge.render('sca-good',{'preset_id':'saved','prompt':'My exact instruction'}))
        self.assertEqual(self.renderer.call_args.args[0]['prompt'],'My exact instruction')
        with self.assertRaises(ValueError):asyncio.run(self.bridge.render('sca-good',{'preset_id':'absent'}))
    def test_missing_or_unverified_archive_never_submits(self):
        with self.assertRaises(FileNotFoundError):asyncio.run(self.bridge.render('absent',{}))
        self.renderer.assert_not_awaited()
        with self.assertRaises(ValueError):asyncio.run(self.bridge.render('sca-good',[]))
    def test_all_done_outputs_are_candidates_but_requested_words_are_unverified(self):
        for name in ('first.mp4','second.webm','bad.mp4','supercut-old.mp4','not-done.mp4'):(self.root/name).write_bytes(b'media')
        outside=self.root.parent/'outside-h3-test.mp4';outside.write_bytes(b'outside');self.addCleanup(outside.unlink)
        generations=[{'status':'done','prompt_id':'job','speech':'requested words','duration_s':8,
            'source_type':'supercut','source':'sca-good','files':['first.mp4','second.webm','supercut-old.mp4','outside.mp4',{'bad':'row'}]},
            {'status':'queued','files':['not-done.mp4'],'duration_s':8},
            {'status':'done','files':['bad.mp4'],'duration_s':'invalid'}]
        self.host.update(COMFY_OUTPUT=self.root,_read_all_generations=lambda:generations,
            comfy_output_find=lambda name:outside if name=='outside.mp4' else self.root/name,
            sfx_id=lambda path:'sid-'+path.stem,_media_duration_probe=lambda path:0)
        rows=self.bridge.sources();self.assertEqual([r['name'] for r in rows],['first.mp4','second.webm'])
        for row in rows:
            self.assertEqual(row['said'],'');self.assertIn('requested words',row['candidate_text'])
            self.assertTrue(row['provenance']['requested_text_unverified']);self.assertEqual(row['provenance']['source'],'sca-good')
        rows[0]['said']='poison';self.assertEqual(self.bridge.sources()[0]['said'],'')
    def test_authentication_precedes_archive_and_comfy(self):
        app=FastAPI()
        def auth(value):
            if value!='Bearer allowed':raise HTTPException(401,'Authentication required')
        self.host['require_auth']=auth;install(app,self.host)
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/sfx/supercut/archive/sca-good/h3',json={}).status_code,401)
            self.renderer.assert_not_awaited()
            response=client.post('/api/sfx/supercut/archive/sca-good/h3',headers={'Authorization':'Bearer allowed'},json={'prompt':'test'})
            self.assertEqual(response.status_code,200);self.assertEqual(response.json()['prompt_id'],'render-1')
            self.assertEqual(client.post('/api/sfx/supercut/archive/absent/h3',headers={'Authorization':'Bearer allowed'},json={}).status_code,404)
if __name__=='__main__':unittest.main()