"""Durable Super Cut archival and source-backed reuse contracts."""
import asyncio
import copy
import hashlib
import json
import shutil
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

import sfx_supercut as cut
from sfx_supercut_archive import SupercutArchive


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.media=self.root/'media';self.media.mkdir()
        self.ads=self.root/'sfx_ads'
        self.native=self.root/'ads_audio'
        self.entries=[]
        self.book=[]
        def save(product,text,kind,extra):
            entry=dict(extra,id='ad-'+str(len(self.entries)),product=product,text=text,kind=kind)
            self.entries.append(entry);return entry
        self.host={'DATA_DIR':self.root,'SFX_ADS_DIR':self.ads,'VOICE_MEDIA_DIR':self.media,
            'PRODUCED_ADS_DIR':self.native,'media_sign':lambda key:'signed-'+key,
            'ad_list':lambda:self.entries,'ad_save':save,
            'sfx_db_write_row':lambda path,seconds,playable:self.book.append((path,seconds,playable)) or True}
        self.archive=SupercutArchive(self.host)
        self.path=self.media/('f'*32+'.wav')
        with wave.open(str(self.path),'wb') as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(24000)
            out.writeframes(b'\x10\x00'*int(45*24000))
        said=['Hello welcome'] + ['Listen to radio music number '+str(i) for i in range(13)] + ['Goodbye Pine Box FM']
        clips=[{'sid':'sid-'+str(i),'path':'/original/'+str(i)+'.wav','said':text,
            'role':'opening' if i==0 else 'closing' if i==14 else 'sell','seconds':3,
            'from_s':0,'until_s':3,'mtime':123} for i,text in enumerate(said)]
        cues=[dict(p,at=i*3,until=(i+1)*3,body_seconds=3,source_from=0,source_until=3) for i,p in enumerate(clips)]
        campaign={'id':'campaign-1','product':'Pine Box FM','script':'An authored pitch, never a recording.',
            'hour':'2026-10-04T10:00:00Z','product_origin':'invented','generated_at':123,
            'system_prompt':'producer instructions','generation_prompt':'sales brief'}
        plan={'id':'sc-'+'a'*24,'ok':True,'complete':True,'source_only':True,'seconds':45,
            'config':cut.config({'campaign':campaign}),'clips':clips,'cues':cues,
            'rendered_at':123,'clip':self.path.name,'campaign':campaign,'occurrence':'hour-1',
            'generated_script':campaign['script'],
            'structure':{'opening':True,'sell':True,'closing':True,'station_identity_verified':True}}
        self.result={'ok':True,'complete':True,'source_only':True,'seconds':45,'source_plan':plan,
            'path':str(self.path),'cues':cues,'recorded_text':' / '.join(said)}

    def test_audio_script_transcript_and_source_provenance_are_saved_in_sfx_ads(self):
        row=self.archive.record(self.result)
        self.assertEqual(Path(self.book[0][0]).parent,self.ads)
        self.assertEqual(self.book[0][1:],(45,1))
        self.assertEqual((self.ads/row['audio_name']).read_bytes(),self.path.read_bytes())
        self.assertEqual((self.ads/row['audio_name']).stat().st_size,row['audio_bytes'])
        self.assertEqual((self.archive.root/(row['id']+'.script.txt')).read_text(),row['generated_script'])
        self.assertEqual((self.archive.root/(row['id']+'.transcript.txt')).read_text(),row['recorded_text'])
        self.assertNotEqual(row['generated_script'],row['recorded_text'])
        self.assertEqual(row['source_plan']['clips'],self.result['source_plan']['clips'])
        self.assertIn('?t=signed-',row['audio_url'])
        self.assertFalse(row['autoplay'])
        self.assertEqual(self.entries,[])

    def test_repeated_render_and_restart_keep_one_immutable_review_record(self):
        first=self.archive.record(self.result)
        again=copy.deepcopy(self.result);again['source_plan']['rendered_at']=999
        again['source_plan']['generated_script']='A different draft after the render'
        second=self.archive.record(again)
        restarted=SupercutArchive(self.host)
        self.assertEqual(restarted.list()['total'],1)
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(first['created_at'],restarted.detail(first['id'])['created_at'])
        self.assertEqual((self.archive.root/(first['id']+'.script.txt')).read_text(),first['generated_script'])
        self.assertTrue(self.path.is_file())

    def test_pagination_search_and_summary_are_bounded_and_use_real_products(self):
        for i in range(3):
            result=copy.deepcopy(self.result)
            result['source_plan']['id']='sc-'+('%024x'%i)
            result['source_plan']['rendered_at']=i+100
            result['source_plan']['campaign']['product']='Product '+str(i)
            self.archive.record(result)
        page=self.archive.list(limit=2,offset=0,summary=True)
        self.assertEqual(page['total'],3);self.assertTrue(page['has_more'])
        self.assertEqual([row['product'] for row in page['rows']],['Product 2','Product 1'])
        self.assertNotIn('source_plan',page['rows'][0]);self.assertNotIn('script',page['rows'][0]['campaign'])
        self.assertEqual(self.archive.list(query='Product 0')['total'],1)
        self.assertEqual(self.archive.list(query="' OR 1=1 --")['total'],0)
        self.assertEqual(self.archive.list(limit=100000,offset=-100)['limit'],100)

    def test_invalid_audio_incomplete_plan_and_bad_cues_never_publish(self):
        for key in ('complete','source_only','ok'):
            result=copy.deepcopy(self.result);result[key]=False
            with self.assertRaises(ValueError):self.archive.record(result)
        result=copy.deepcopy(self.result);result['seconds']=44
        with self.assertRaises(ValueError):self.archive.record(result)
        result=copy.deepcopy(self.result);result['cues'][5]['at']+=1
        with self.assertRaises(ValueError):self.archive.record(result)
        self.assertFalse(self.archive.db_path.is_file())
        with wave.open(str(self.path),'wb') as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(24000);out.writeframes(b'\x00\x00'*int(45*24000))
        with self.assertRaises(ValueError):self.archive.record(self.result)
        self.assertFalse(self.archive.db_path.is_file())

    def test_explicit_reuse_registers_original_audio_once_without_playback(self):
        row=self.archive.record(self.result)
        first=self.archive.reuse(row['id']);second=self.archive.reuse(row['id'])
        self.assertFalse(first['already_registered']);self.assertTrue(second['already_registered'])
        self.assertFalse(first['autoplay']);self.assertEqual(len(self.entries),1)
        self.assertEqual(self.entries[0]['text'],row['recorded_text'])
        self.assertEqual(self.entries[0]['generated_script'],row['generated_script'])
        self.assertTrue(self.entries[0]['source_only'])
        self.assertEqual((self.native/self.entries[0]['audio']).read_bytes(),self.path.read_bytes())
        self.assertEqual(self.archive.detail(row['id'])['reusable_ad_id'],first['ad_id'])
        # Ordinary library retention/deletion must never erase the lasting archive.
        (self.native/self.entries[0]['audio']).unlink();self.entries.clear()
        third=self.archive.reuse(row['id']);self.assertFalse(third['already_registered'])
        self.assertTrue(self.archive.audio(row['id']).is_file())

    def test_tampered_audio_and_path_traversal_are_refused(self):
        row=self.archive.record(self.result)
        for identity in ('../outside','sca-'+('a'*24)+'/../outside','f'*32+'.wav'):
            with self.assertRaises(ValueError):self.archive.audio(identity)
        audio=self.ads/row['audio_name']
        content=bytearray(audio.read_bytes());content[-1]^=1;audio.write_bytes(content)
        with self.assertRaisesRegex(ValueError,'changed'):self.archive.audio(row['id'])
        with self.assertRaisesRegex(ValueError,'changed'):self.archive.reuse(row['id'])
        self.assertEqual(self.entries,[])

    def test_completed_legacy_plans_migrate_without_deleting_or_replaying_originals(self):
        plans=self.root/'sfx_supercuts';plans.mkdir()
        original=plans/(self.result['source_plan']['id']+'.json')
        original.write_text(json.dumps(self.result['source_plan']))
        incomplete=plans/('sc-'+'b'*24+'.json');incomplete.write_text('{}')
        report=self.archive.migrate(plans,self.media)
        self.assertEqual((report['scanned'],report['archived'],report['skipped']),(2,1,1))
        self.assertEqual(self.archive.migrate(plans,self.media),report)
        self.assertTrue(original.is_file());self.assertTrue(self.path.is_file());self.assertTrue(incomplete.is_file())
        self.assertEqual(self.archive.list()['total'],1);self.assertEqual(self.entries,[])

    def test_authenticated_archive_routes_and_media_signature_preserve_review_only_behavior(self):
        class App:
            def __init__(self):self.routes={}
            def get(self,path):return lambda fn:self.add('GET',path,fn)
            def post(self,path):return lambda fn:self.add('POST',path,fn)
            def add(self,method,path,fn):self.routes[method,path]=fn;return fn
            def on_event(self,event):return lambda fn:fn
        app=App();read=mock.Mock();write=mock.Mock()
        host=dict(self.host,require_read_auth=read,require_auth=write)
        runtime=cut.install(app,host)
        self.addCleanup(runtime.source_pool.shutdown,wait=False)
        self.addCleanup(runtime.catalog_pool.shutdown,wait=False)
        row=runtime.archive.record(self.result)
        response=asyncio.run(app.routes['GET','/api/sfx/supercut/archive'](2,0,'',True,'Bearer read'))
        self.assertEqual(response['total'],1);read.assert_called_with('Bearer read')
        read.reset_mock()
        request=mock.Mock(query_params={'t':'signed-'+row['id']})
        response=asyncio.run(app.routes['GET','/api/sfx/supercut/archive/{identifier}/audio'](row['id'],request,None))
        self.assertEqual(Path(response.path).parent,self.ads);read.assert_not_called()
        request.query_params={'t':'incorrect'}
        asyncio.run(app.routes['GET','/api/sfx/supercut/archive/{identifier}/audio'](row['id'],request,'Bearer read'))
        read.assert_called_once_with('Bearer read')
        reused=asyncio.run(app.routes['POST','/api/sfx/supercut/archive/{identifier}/reuse'](row['id'],'Bearer write'))
        write.assert_called_once_with('Bearer write');self.assertFalse(reused['autoplay'])

    def test_manual_and_scheduled_prepare_render_paths_archive_once(self):
        async def run():
            runtime=cut.SupercutRuntime(self.host)
            try:
                rendered=copy.deepcopy(self.result)
                with mock.patch.object(cut,'render_source_plan',return_value=rendered):
                    one=await runtime.render(self.result['source_plan'])
                    runtime.plan=mock.AsyncMock(return_value=self.result['source_plan'])
                    two=await runtime.prepare({'dynamic_config':self.result['source_plan']['config']},'pitch','hour-1')
                self.assertEqual(one['archive_id'],two['archive_id'])
                self.assertEqual(runtime.archive.list()['total'],1)
                self.assertEqual(one['generated_script'],self.result['source_plan']['generated_script'])
            finally:
                runtime.source_pool.shutdown(wait=False);runtime.catalog_pool.shutdown(wait=False)
        asyncio.run(run())


if __name__=='__main__':unittest.main()
