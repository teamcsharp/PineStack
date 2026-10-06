"""Hourly script identity, exact custom words, and honest H3 source evidence."""
import asyncio
import copy
import json
import sqlite3
import tempfile
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import dynamic_segments
import segment_prompts
import sfx_supercut as cut
import sfx_supercut_custom as custom
import supercut_campaigns as campaigns

class HourlyCampaigns(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.old={name:getattr(segment_prompts,name) for name in ('_HOST','_PATH','_BOOK','_READ','_MEMO','_RIDES','_RECENT')}
        self.addCleanup(lambda:[setattr(segment_prompts,k,v) for k,v in self.old.items()])
        segment_prompts._HOST={};segment_prompts._PATH=self.root/'prompts.json'
        segment_prompts._BOOK={'kinds':{},'uses':[],'at':0.};segment_prompts._READ=[False]
        segment_prompts._MEMO={};segment_prompts._RIDES={};segment_prompts._RECENT=[]
        dynamic_segments.ensure_defaults(segment_prompts)
        self.host={'DATA_DIR':self.root,'dj_settings':lambda:{'station_name':'Pine Box FM','sponsors':['Saved Coffee']},'_LARDER_WRITING':[False]}
        self.rt=campaigns.SupercutCampaigns(self.host)
        self.hour=self.rt.effective_hour
        self.choice={'config':{**dynamic_segments.SFX_SUPERCUT['config'],'product_mode':'mixed','products':[{'name':'Saved Mug','description':'A ceramic mug'}]},
            'system_prompt':'Make a source-only ad for {product} on {stationname}',
            'generation_prompt':'Sell {product} for {sponsor}', 'name':'My saved custom prompt'}

    def test_current_hour_legacy_and_restarts_keep_exact_frozen_next_hour_identity(self):
        async def run():
            self.assertEqual(await self.rt.freeze(self.hour-3600,chosen=self.choice),{})
            first=await self.rt.freeze(self.hour,chosen=self.choice)
            again=await self.rt.freeze(self.hour,chosen={'config':{'product_mode':'fixed','item':'Changed'}})
            self.assertEqual(first,again)
            fresh=campaigns.SupercutCampaigns(self.host)
            self.assertEqual(fresh.effective_hour,self.hour)
            self.assertEqual(await fresh.freeze(self.hour),first)
        asyncio.run(run())

    def test_mixed_alternates_saved_and_invented_products_and_rejects_reused_inventions(self):
        async def run():
            with mock.patch.object(campaigns.secrets,'choice',side_effect=lambda rows:rows[0]):
                first=await self.rt.freeze(self.hour,chosen=self.choice)
                self.assertEqual(first['product_source'],'saved')
                second=await self.rt.freeze(self.hour+3600,chosen=self.choice)
                self.assertEqual(second['product_source'],'invented')
            good={'product':'Comet Coffee','script':'Come try Comet Coffee today, our wonderful coffee to enjoy with every show, only on Pine Box FM.'}
            product,script=self.rt.accept(second,good)
            self.rt.items[str(self.hour+3600)].update(product=product,script=script)
            third=await self.rt.freeze(self.hour+7200,chosen=self.choice)
            self.assertEqual(third['product_source'],'saved')
            fourth=await self.rt.freeze(self.hour+10800,chosen=self.choice)
            with self.assertRaisesRegex(ValueError,'repeats'):
                self.rt.accept(fourth,good)
        asyncio.run(run())

    def test_writer_respects_existing_admission_and_never_makes_audio(self):
        calls=[]
        async def writer(system,generation,**kw):
            calls.append((system,generation,kw))
            return {'product':'Pine Box FM','script':'Tune in to Pine Box FM today for your favorite music and our live hosts. Enjoy Pine Box FM.'}
        self.host['supercut_campaign_write']=writer
        choice={**self.choice,'config':{**self.choice['config'],'product_mode':'fixed','item':'Pine Box FM'}}
        async def run():
            self.host['_LARDER_WRITING'][0]=True
            row=await self.rt.ensure(self.hour,chosen=choice,wait_seconds=2.)
            self.assertEqual(calls,[]);self.assertEqual(row['status'],'pending')
            self.host['_LARDER_WRITING'][0]=False
            row=await self.rt.ensure(self.hour,chosen=choice,wait_seconds=2.)
            self.assertEqual(row['status'],'script_ready');self.assertIn('Pine Box FM',row['resolved_system_prompt'])
            self.assertEqual(len(calls),1);self.assertFalse(self.host['_LARDER_WRITING'][0])
            await self.rt.ensure(self.hour,chosen=choice)
            self.assertEqual(len(calls),1);self.assertNotIn('audio',row)
        asyncio.run(run())

    def test_product_controls_persist_through_template_store_and_routes_keep_frozen_hour(self):
        app=FastAPI();self.host.update(require_auth=lambda key:None,require_read_auth=lambda key:None)
        runtime=campaigns.install(app,self.host);client=TestClient(app)
        answer=client.put('/api/sfx/supercut/products',json={'product_mode':'mixed','products':[{'name':'New headphones','description':'Sparkly'}]}).json()
        self.assertEqual(answer['product_mode'],'mixed')
        self.assertIn('New headphones',[one['name'] for one in answer['products']])
        config=segment_prompts.dial_preview('sfx_supercut')['config']
        self.assertEqual(config['products'][0]['description'],'Sparkly')
        self.assertTrue(config['campaign_enabled']);self.assertEqual(runtime.effective_hour,self.hour)
        self.assertEqual(client.put('/api/sfx/supercut/products',json={'product_mode':'nonsense'}).status_code,422)

    def test_scheduled_prepare_freezes_actual_due_hour_once_and_waits_for_script(self):
        import dynamic_segments_runtime as dynamic
        chosen=segment_prompts.dial_preview('sfx_supercut')
        segment_prompts.patch_alternative('sfx_supercut',chosen['id'],{'config':{
            **dynamic_segments.SFX_SUPERCUT['config'],'product_mode':'fixed','item':'Saved Coffee'}})
        source=self.root/'ready.wav';source.write_bytes(b'fixture recorded source body')
        prepared=[]
        async def prepare(slot,prompt,occurrence):
            prepared.append((copy.deepcopy(slot),prompt,occurrence))
            return {'ok':True,'clip':source.name,'path':str(source),'seconds':45.,'body_frames':1080000,'sample_rate':24000,
                'recorded_text':'Verified source coffee words, Pine Box FM',
                'source_plan':{'id':'sc-'+('a'*24),'complete':True,'source_only':True,'clips':[{'sid':'source'}],
                    'structure':{'opening':True,'sell':True,'closing':True,'station_identity_verified':True}}}
        async def writer(system,generation,**kw):
            return {'product':'Saved Coffee','script':'Try our Saved Coffee today, a wonderful coffee to enjoy while listening to your favorite shows on Pine Box FM.'}
        self.host.update(SUPERCUT_CAMPAIGNS=self.rt,supercut_campaign_write=writer,
            sfx_supercut_prepare=prepare,PRODUCED_ADS_DIR=self.root/'produced',_SHELF={})
        engine=dynamic.DynamicSegments(self.host)
        due={'kind':'sfx_supercut','slot_id':'future-58','due_at':self.hour+3600+58*60,
            'slot':{'id':'future-58','kind':'sfx_supercut','minutes':1.25}}
        async def run():
            self.host['_LARDER_WRITING'][0]=True
            self.assertIsNone(await engine.prepare_supercut(due))
            self.assertEqual(prepared,[])
            self.host['_LARDER_WRITING'][0]=False
            row=await engine.prepare_supercut(due)
            self.assertIsNotNone(row,engine.last)
            self.assertEqual(row['product'],'Saved Coffee')
            self.assertEqual(len(prepared),1)
            campaign=prepared[0][0]['dynamic_config']['campaign']
            self.assertEqual(campaign['hour_epoch'],self.hour+3600)
            self.assertEqual(len(self.rt.items),1)
            self.assertIn(campaign['script'],prepared[0][1])
            self.assertEqual(len(segment_prompts.uses_for('sfx_supercut')),1)
            self.assertIs(await engine.prepare_supercut(due),row)
            self.assertEqual(len(prepared),1)
        asyncio.run(run())

class ExactCustomWords(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.book=self.root/'clips.db'
        self.con=sqlite3.connect(self.book);self.addCleanup(self.con.close)
        self.con.execute('create table clips(path text primary key,sid text,name text,video integer,seconds real,playable integer,mtime real,said text)')
        self.a=self.add('a','Hello',1.,10)
        self.b=self.add('b','Pine Box FM',2.,20)
        self.host={'DATA_DIR':self.root,'SFX_DB_PATH':self.book,'SFX_ADS_DIR':self.root/'sfx_ads',
            'VOICE_MEDIA_DIR':self.root/'voice_media','dj_settings':lambda:{'station_name':'Pine Box FM'},
            'clip_speech':SimpleNamespace(transcribe_file=self.transcribe)}
        self.rt=cut.SupercutRuntime(self.host)
        self.addCleanup(self.rt.source_pool.shutdown,wait=True);self.addCleanup(self.rt.catalog_pool.shutdown,wait=True)
        # No extra station process or model service is imported by these fixtures.
        self.rt.catalog_read=lambda fn:fn(None)
        self.custom=custom.CustomSupercuts(self.rt)
        self.heard={10:'Hello',20:'Pine Box FM'}
    def add(self,sid,said,seconds,marker,name=''):
        path=self.root/(sid+'.wav')
        with wave.open(str(path),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(int(marker).to_bytes(2,'little',signed=True)*int(seconds*24000))
        self.con.execute('insert into clips values(?,?,?,?,?,?,?,?)',(str(path),sid,name or sid,0,seconds,1,path.stat().st_mtime,said));self.con.commit()
        return path
    def transcribe(self,path,**kwargs):
        with wave.open(str(path),'rb') as f:marker=int.from_bytes(f.readframes(1),'little',signed=True)
        return self.heard.get(marker,'')

    def test_full_scan_finds_last_row_words_and_never_treats_filenames_as_speech(self):
        for i in range(40):self.add('decoy'+str(i),'Potato',1.,30)
        self.add('final','Buy the coffee',1.,40)
        self.add('filename','',1.,50,'nonexistentword')
        view=custom.scan_words(self.book,custom.tokens('buy the coffee nonexistentword'))
        self.assertEqual(view['coverage']['catalog_scanned'],44)
        self.assertEqual(view['phrases']['buy the coffee'][0]['sid'],'final')
        self.assertEqual(view['phrases']['nonexistentword'],[])

    def test_exact_actual_audio_builds_short_custom_archive_without_padding_or_station_insertion(self):
        row=self.custom.create({'words':'Hello Pine Box FM','explanation':'Fast, then station name','target_seconds':10})
        asyncio.run(self.custom.visit(row['id']))
        result=self.custom.detail(row['id'])
        self.assertEqual(result['status'],'ready',result)
        self.assertEqual(result['matched_words'],4);self.assertEqual(result['missing_words'],[])
        archive=result['archive'];self.assertEqual(archive['seconds'],3.)
        self.assertTrue(archive['custom']);self.assertFalse(archive['autoplay'])
        self.assertEqual(archive['generated_script'],'Hello Pine Box FM')
        self.assertEqual(len(archive['cues']),2)
        self.assertTrue(self.rt.archive.audio(archive['id']).is_file())
        fresh=custom.CustomSupercuts(self.rt)
        self.assertEqual(fresh.detail(row['id'])['archive_id'],archive['id'])

    def test_unknown_or_mismatching_audio_is_incomplete_and_cannot_publish(self):
        self.heard[10]='Goodbye'
        row=self.custom.create({'words':'Hello missingword'})
        asyncio.run(self.custom.visit(row['id']))
        result=self.custom.detail(row['id'])
        self.assertEqual(result['status'],'incomplete')
        self.assertEqual(result['missing_words'],['hello','missingword'])
        self.assertNotIn('archive_id',result);self.assertFalse(self.rt.archive.db_path.exists())
        self.heard[10]='Hello';again=self.custom.retry(row['id'])
        self.assertEqual(again['status'],'queued')
        asyncio.run(self.custom.visit(row['id']))
        self.assertEqual(self.custom.detail(row['id'])['missing_words'],['missingword'])

    def test_named_presets_recall_both_words_and_direction_after_restart(self):
        first=self.custom.save_preset({'name':'My hook','words':'Hello','explanation':'SFX guy: one dry clip','target_seconds':5})
        ident=first['preset']['id']
        self.custom.save_preset({**first['preset'],'explanation':'Now punchy'})
        fresh=custom.CustomSupercuts(self.rt)
        self.assertEqual(len(fresh.presets()['presets']),1)
        self.assertEqual(fresh.presets()['presets'][0]['id'],ident)
        self.assertEqual(fresh.presets()['presets'][0]['explanation'],'Now punchy')
        self.assertEqual(fresh.presets()['presets'][0]['words'],'Hello')

    def test_h3_completed_audio_is_analyzed_and_generated_prompt_is_not_spoken_evidence(self):
        path=self.add('h3','',2.,60);self.heard[60]='Real H3 audio words'
        self.host['supercut_h3_sources']=lambda:[{'sid':'h3','path':str(path),'seconds':2.,'mtime':path.stat().st_mtime,
            'said':'','candidate_text':'Fake unsupported promise','video':True,'provenance':{'origin':'h3','existing_audio_only':True}}]
        rows=asyncio.run(self.rt.generated_h3_sources(prompt='Fake unsupported promise',analyze=True))
        self.assertEqual(rows[0]['said'],'Real H3 audio words')
        self.assertNotIn('Fake unsupported',rows[0]['said'])
        scan=custom.scan_words(self.book,custom.tokens('real h3 audio words'),rows)
        self.assertTrue(scan['phrases']['real h3 audio words'])
        self.assertEqual(scan['coverage']['h3_sources_scanned'],1)

    def test_scheduled_long_h3_excerpt_keeps_exact_verified_source_offset(self):
        path=self.add('longh3','',10.,60)
        said='hello everybody buy coffee on the radio today please now'
        timed=[{'word':word,'start':i*.4,'end':(i+1)*.4} for i,word in enumerate(said.split())]
        self.host['supercut_h3_sources']=lambda:[{'sid':'longh3','path':str(path),'seconds':10.,
            'mtime':path.stat().st_mtime,'said':said,'word_timestamps':timed,'video':True,
            'provenance':{'origin':'h3','existing_audio_only':True}}]
        seen=[]
        def verify(source,start,end,transcriber,executable):
            seen.append((start,end))
            return {'said':' '.join(said.split()[:6]),'mtime':path.stat().st_mtime,'bytes':path.stat().st_size,
                'source_audio_verified':True,'word_cut_verified':True}
        with mock.patch.object(custom,'audition',side_effect=verify):
            rows=asyncio.run(self.rt.generated_h3_sources(prompt='coffee',analyze=True,max_seconds=6.))
        self.assertEqual(len(rows),1);self.assertTrue(seen)
        self.assertEqual(rows[0]['source_seconds'],10.)
        self.assertAlmostEqual(rows[0]['seconds'],2.42)
        self.assertEqual(rows[0]['transcript_scope'],'current_h3_trimmed_window_asr')
        scan=cut.scan_catalog(self.book,None,cut.config({'item':'coffee'}),extra_sources=rows)
        selected=next(row for row in scan['roles']['sell'] if row['sid']=='longh3')
        self.assertEqual(selected['from_s'],seen[0][0]);self.assertEqual(selected['until_s'],seen[0][1])
        self.assertEqual(selected['source_seconds'],10.)
        self.assertTrue(selected['word_cut_verified'])
        # Invented prompt words cannot approve a different heard trim.
        self.rt.h3_sources={}
        with mock.patch.object(custom,'audition',return_value={'said':'Something else'}):
            self.assertEqual(asyncio.run(self.rt.generated_h3_sources(prompt='coffee',analyze=True,max_seconds=6.)),[])

    def test_recursive_supercut_files_and_h3_supercut_derivatives_are_excluded(self):
        path=self.add('supercut-old','Hello',1.,10)
        raw={'sid':'derived','path':str(self.a),'seconds':1.,'said':'Hello',
            'provenance':{'origin':'h3','existing_audio_only':True,'supercut_archive_id':'sca-'+'a'*24}}
        scan=custom.scan_words(self.book,['hello'],[raw])
        self.assertEqual([one['sid'] for one in scan['phrases']['hello']],['a'])

    def test_unverified_custom_plan_or_changed_source_never_exports_audio(self):
        cfg=cut.config({'custom':{'id':'scc-'+'a'*24,'words':'Hello','max_seconds':3}})
        source={'sid':'a','path':str(self.a),'seconds':1.,'from_s':0.,'until_s':1.,'said':'Hello','mtime':self.a.stat().st_mtime}
        plan={'ok':True,'source_only':True,'complete':True,'config':cfg,'clips':[source]}
        with self.assertRaisesRegex(ValueError,'verified trimmed'):
            cut.render_source_plan(plan,self.root/'no.wav','ffmpeg')
        source.update(word_cut_verified=True,source_audio_verified=True,mtime=source['mtime']-2)
        with self.assertRaisesRegex(ValueError,'changed'):
            cut.render_source_plan(plan,self.root/'no.wav','ffmpeg')
        self.assertFalse((self.root/'no.wav').exists())

if __name__=='__main__':unittest.main()
