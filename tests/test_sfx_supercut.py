"""Whole-catalog source-only supercut planning, roulette, and measured rendering."""
import asyncio
import copy
import hashlib
import json
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

import sfx_supercut as cut
import sfx_vectors


class Supercuts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.book = self.root / "clips.db"
        self.con = sqlite3.connect(self.book)
        self.con.execute("create table clips(path text primary key,sid text,name text,folder text,video integer,seconds real,playable integer,mtime real,said text,said_at real,seen_desc text)")
        self.addCleanup(self.con.close)
        self.store = sfx_vectors.Store(self.root / "vectors", roots={"made": str(self.root)}, dims=24)
        self.addCleanup(self.store.close)
        self.cfg = cut.config({"context": "chapter books curiosity", "target_seconds": 45})
        for i in range(34):
            self.add("s%03d" % i, "Listen to the radio station and enjoy music track number %d" % i, 2.0)
        self.add("open", "Hello everybody welcome tonight", 1.0)
        self.add("close", "Thanks for listening to Pine Box FM. Goodbye", 2.0)
        self.add("news", "Today we are reading books and discussing a chapter", 2.0)
        self.add("flair", "Wow fantastic incredible yes!", 2.0)

    def add(self, sid, said, seconds, name="", *, playable=True):
        path = self.root / (sid + ".wav")
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(cut.RATE)
            out.writeframes(b"\x10\x00" * int(cut.RATE * seconds))
        self.con.execute("insert into clips values(?,?,?,?,?,?,?,?,?,?,?)",
                         (str(path), sid, name or said, "clips", 0, seconds, int(playable), path.stat().st_mtime, said, 1 if said else None, ""))
        self.con.commit()
        return path

    def scan(self, **kwargs):
        return cut.scan_catalog(self.book, self.store, self.cfg, **kwargs)

    def test_every_source_row_is_scored_even_after_an_ordinary_suggestion_limit(self):
        for i in range(550):
            self.add("decoy%03d" % i, "potato teapot obscure", 1.0)
        self.add("last", "chapter books curiosity reading chapter books", 2.0)
        scan = self.scan()
        self.assertEqual(scan["coverage"]["catalog_scanned"], 589)
        self.assertEqual(scan["roles"]["timely"][0]["sid"], "last")
        self.assertLessEqual(len(scan["roles"]["timely"]), cut.POOL)
        self.assertEqual(scan["coverage"]["audio_pending"], 0)
        self.assertGreater(scan["coverage"]["semantic_pending"], 0)

    def test_disabled_weighted_and_duplicate_sources_do_not_fill_the_cut(self):
        scan = self.scan(banned={"s000"}, weights={"s001": 0})
        plan = cut.compose(scan, self.cfg, "hour-one")
        self.assertTrue(plan["ok"], plan)
        ids = [p["sid"] for p in plan["clips"]]
        self.assertNotIn("s000", ids)
        self.assertNotIn("s001", ids)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(plan["clips"][0]["role"], "opening")
        self.assertEqual(plan["clips"][-1]["role"], "closing")
        self.assertTrue(plan["structure"]["station_identity_verified"])
        self.assertTrue(all(p["from_s"] == 0 and p["until_s"] == p["seconds"] for p in plan["clips"]))
        self.assertLessEqual(abs(plan["seconds"] - 45), 1.0)

    def test_unverified_filename_is_not_spoken_station_identity(self):
        self.con.execute("update clips set said='',said_at=null,name='PineBox source' where sid='close'")
        self.con.commit()
        scan = self.scan()
        plan = cut.compose(scan, self.cfg, "hour-two")
        self.assertFalse(plan["ok"])
        self.assertEqual(plan["needs"], ["station_identity"])
        self.assertEqual(scan["identity_to_analyze"][0]["sid"], "close")
        self.assertEqual(scan["coverage"]["audio_pending"], 1)

    def test_system3_roulette_receives_relevant_bounded_candidates(self):
        seen = []
        def roll(role, candidates):
            seen.append((role, [p["sid"] for p in candidates]))
            return len(candidates)-1
        plan = cut.compose(self.scan(), self.cfg, "hour-three", roulette=roll)
        self.assertTrue(plan["ok"], plan)
        self.assertGreater(len(seen), 3)
        self.assertTrue(all(len(sids) <= 8 for _, sids in seen))
        self.assertEqual(seen[0][0], "closing")

    def test_random_occurrence_is_stable_and_plan_has_complete_source_evidence(self):
        scan = self.scan()
        one = cut.compose(scan, self.cfg, "hour-four")
        two = cut.compose(scan, self.cfg, "hour-four")
        self.assertEqual(one["id"], two["id"])
        self.assertTrue(one["source_only"])
        self.assertTrue(one["complete"])
        self.assertTrue(all(p.get("why") for p in one["clips"]))
        self.assertEqual(one["source_count"], len(one["clips"]))

    def test_rapid_cut_max_and_mp4_policy_are_respected(self):
        self.add("long", "Hello radio station music enjoy amazing", 9.0)
        self.assertNotIn("long", {p["sid"] for p in self.scan()["roles"]["sell"]})
        self.assertEqual(self.scan(mp4_only=True)["coverage"]["eligible_short_sources"], 0)

    def test_renderer_publishes_only_source_pcm_with_exact_measured_cues(self):
        plan = cut.compose(self.scan(), self.cfg, "hour-render")
        output = self.root / ("f"*32 + ".wav")
        calls = []
        def decode(args, **kwargs):
            source = Path(args[args.index("-i")+1])
            calls.append(source)
            shutil.copyfile(source, args[-1])
            return mock.Mock(returncode=0)
        with mock.patch.object(cut.subprocess, "run", side_effect=decode):
            result = cut.render_source_plan(plan, output, "ffmpeg")
        self.assertEqual(calls, [Path(p["path"]) for p in plan["clips"]])
        self.assertEqual(result["engine"], "sfx_supercut")
        self.assertEqual(result["sample_rate"], cut.RATE)
        self.assertEqual(result["body_frames"], int(result["seconds"] * cut.RATE))
        self.assertEqual(result["cues"][-1]["until"], result["seconds"])
        self.assertEqual(result["cues"][0]["source_from"], 0)
        self.assertTrue(output.is_file())

    def test_one_failed_cut_never_publishes_a_partial_promo(self):
        plan = cut.compose(self.scan(), self.cfg, "hour-failure")
        output = self.root / ("e"*32 + ".wav")
        with mock.patch.object(cut.subprocess, "run", side_effect=cut.subprocess.CalledProcessError(1, "ffmpeg")):
            with self.assertRaises(cut.subprocess.SubprocessError):
                cut.render_source_plan(plan, output, "ffmpeg")
        self.assertFalse(output.exists())
        with self.assertRaises(ValueError):
            cut.render_source_plan(plan, output, "ffmpeg", banned={plan["clips"][0]["sid"]})

    def test_changed_source_is_refused_before_publication(self):
        plan = cut.compose(self.scan(), self.cfg, "hour-changed")
        plan["clips"][0]["mtime"] -= 2
        with self.assertRaisesRegex(ValueError, "changed"):
            cut.render_source_plan(plan, self.root / "changed.wav", "ffmpeg")

    def test_resumable_full_census_crosses_every_row_and_reports_partial_analysis(self):
        runtime = cut.SupercutRuntime({"DATA_DIR": self.root, "SFX_DB_PATH": self.book})
        with mock.patch.object(cut, "SYNC_BATCH", 7):
            while not runtime.progress["complete"]:
                runtime.sync_batch(self.store)
        self.assertEqual(runtime.progress["seen"], 38)
        self.assertEqual(self.store.counts()["clips"], 38)
        restarted = cut.SupercutRuntime({"DATA_DIR": self.root, "SFX_DB_PATH": self.book})
        self.assertEqual(restarted.progress["rowid"], runtime.progress["rowid"])
        report = cut.census(self.book, self.store)
        self.assertEqual(report["metadata_pending"], 0)
        self.assertEqual(report["semantic_pending"], 38)
        self.assertFalse(report["analysis_complete"])

    def test_every_embedded_source_participates_in_semantic_scoring(self):
        rows = self.con.execute("select sid,path,name,folder,video,seconds,said,mtime from clips").fetchall()
        columns = ("sid", "path", "name", "folder", "video", "seconds", "said", "mtime")
        self.store.upsert_clips([dict(zip(columns, row)) for row in rows])
        embed = sfx_vectors.fake_embedder(24)
        todo = self.store.clips_to_embed(100)
        self.store.put_clip_vectors([r["sid"] for r in todo], embed([self.store.clip_text(r) for r in todo]))
        queries = cut.role_queries(self.cfg)
        vectors = dict(zip(queries, embed(list(queries.values()))))
        scan = self.scan(vectors=vectors)
        self.assertEqual(scan["coverage"]["semantic_scored"], 38)
        self.assertEqual(scan["coverage"]["semantic_pending"], 0)
        self.assertIn("semantic", scan["roles"]["sell"][0]["why"])

    def test_item_context_and_custom_generation_prompt_reach_role_queries(self):
        cfg = cut.config({"item": "Superbeans", "context": "space exploration"})
        queries = cut.role_queries(cfg, "sell the lunar lunch with a kitchen joke")
        self.assertIn("Superbeans", queries["sell"])
        self.assertIn("lunar lunch", queries["sell"])
        self.assertIn("space exploration", queries["timely"])

    def test_occurrence_memo_keeps_same_plan_without_redrawing_or_playing(self):
        store = self.store
        class VectorRuntime:
            def __init__(self): self.store = store
            def desk_busy(self): return True
            async def run(self, fn, *args): return fn(*args)
        source = VectorRuntime()
        rolls = []
        def roulette(key, labels, weights, description):
            rolls.append((key, labels))
            return 0
        host = {"DATA_DIR": self.root, "SFX_DB_PATH": self.book,
                "_sfx_vectors": lambda: source, "s3_weighted": roulette}
        runtime = cut.SupercutRuntime(host)
        async def twice():
            one = await runtime.plan(self.cfg, occurrence="test-occurrence")
            count = len(rolls)
            two = await runtime.plan(self.cfg, occurrence="test-occurrence")
            return one, two, count
        one, two, count = asyncio.run(twice())
        self.assertTrue(one["ok"], one)
        self.assertEqual(one["id"], two["id"])
        self.assertEqual(len(rolls), count)
        self.assertTrue(runtime.memo_path.is_file())
        self.assertFalse(list((self.root / "sfx_supercuts").glob("*.wav")))

    def test_changed_source_description_is_refreshed_before_sealing(self):
        plan = cut.compose(self.scan(), self.cfg, "seal-analysis")
        first = plan["clips"][0]
        first["mtime"] -= 2
        speech = mock.Mock()
        speech.transcribe_file.return_value = "Hello everybody!"
        host = {"DATA_DIR": self.root, "SFX_DB_PATH": self.book, "clip_speech": speech}
        runtime = cut.SupercutRuntime(host)
        sealed = asyncio.run(runtime.seal(plan))
        self.assertEqual(sealed["clips"][0]["said"], "Hello everybody!")
        self.assertEqual(sealed["clips"][0]["transcript_scope"], "current_entire_source_asr")
        self.assertTrue(sealed["clips"][0]["source_changed_since_catalog"])
        self.assertEqual(sealed["source_analysis"]["refreshed_selected_sources"], 1)
        self.assertEqual(speech.transcribe_file.call_count, 1)

    def test_existing_recorded_station_ids_are_verified_without_consuming_the_pantry(self):
        name = "a"*32 + ".wav"
        shutil.copyfile(self.root / "open.wav", self.root / name)
        pantry = {"old-recording": {"kind": "station_id", "text": "Welcome to Pine Box FM",
                                   "used": 17, "clip": {"path": "/media/"+name, "engine": "xtts"}}}
        before = json.dumps(pantry, sort_keys=True)
        speech = mock.Mock()
        speech.transcribe_file.return_value = "Welcome to Pine Box FM"
        runtime = cut.SupercutRuntime({"DATA_DIR": self.root, "VOICE_MEDIA_DIR": self.root,
                                      "_PANTRY": pantry, "clip_speech": speech})
        sources = asyncio.run(runtime.recorded_station_sources(self.cfg, analyze=True))
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["provenance"]["original_media_key"], name)
        self.assertEqual(sources[0]["provenance"]["original_engine"], "xtts")
        self.assertTrue(sources[0]["provenance"]["existing_audio_only"])
        self.assertEqual(json.dumps(pantry, sort_keys=True), before)
        self.assertEqual(speech.transcribe_file.call_count, 1)
        again = asyncio.run(runtime.recorded_station_sources(self.cfg, analyze=True))
        self.assertEqual(again, sources)
        self.assertEqual(speech.transcribe_file.call_count, 1)
        scan = self.scan(extra_sources=sources, mp4_only=True)
        self.assertTrue(scan["roles"]["opening"])
        self.assertEqual(scan["coverage"]["catalog_scanned"], 39)
        self.assertEqual(scan["coverage"]["catalog_total"], 38)
        self.assertEqual(scan["coverage"]["recorded_station_sources"], 1)

    def test_slow_source_worker_yields_without_queuing_duplicate_analysis(self):
        async def run():
            runtime = cut.SupercutRuntime({'DATA_DIR':self.root})
            gate = threading.Event()
            calls = []
            def slow(): calls.append(1); gate.wait(1); return 'verified words'
            with self.assertRaises(cut.SourceAnalysisPending):
                await runtime.bounded_source('original-asr',slow,timeout=.02)
            with self.assertRaises(cut.SourceAnalysisPending):
                await runtime.bounded_source('different-asr',slow,timeout=.02)
            self.assertEqual(calls,[1])
            gate.set()
            await asyncio.sleep(.04)
            self.assertEqual(await runtime.bounded_source('original-asr',slow,timeout=.02),'verified words')
            self.assertEqual(calls,[1])
            runtime.source_pool.shutdown(wait=False)
        asyncio.run(run())

    def test_auxiliary_station_identity_analysis_yields_and_reuses_its_original_request(self):
        async def run():
            name='c'*32+'.wav'
            shutil.copyfile(self.root/'close.wav',self.root/name)
            pantry={'source':{'kind':'station_id','text':'Pine Box FM station','clip':{'path':'/media/'+name}}}
            calls=[];gate=threading.Event()
            def slow(path,**kwargs): calls.append((path,kwargs));gate.wait(1);return 'Pine Box FM station'
            runtime=cut.SupercutRuntime({'DATA_DIR':self.root,'VOICE_MEDIA_DIR':self.root,'_PANTRY':pantry,
                                         'clip_speech':mock.Mock(transcribe_file=slow)})
            original=runtime.bounded_source
            async def quick(label,fn,*args,timeout=6):
                return await original(label,fn,*args,timeout=.02 if label.startswith('station-asr:') else timeout)
            runtime.bounded_source=quick
            with self.assertRaises(cut.SourceAnalysisPending):
                await runtime.recorded_station_sources(self.cfg,analyze=True)
            self.assertEqual(len(calls),1)
            self.assertLessEqual(calls[0][1]['timeout'],6)
            gate.set();await asyncio.sleep(.04)
            rows=await runtime.recorded_station_sources(self.cfg,analyze=True)
            self.assertEqual(len(rows),1)
            self.assertEqual(len(calls),1)
            runtime.source_pool.shutdown(wait=False)
        asyncio.run(run())

    def test_pending_plan_resumes_same_source_and_reuses_completed_asr(self):
        async def run():
            plan = cut.compose(self.scan(),self.cfg,'frozen-source-analysis')
            plan['clips'][1]['mtime'] -= 2
            gate = threading.Event()
            calls = []
            def slow(path,**kwargs):
                calls.append(path);gate.wait(1);return 'Fresh Pine Box FM radio listen.'
            runtime = cut.SupercutRuntime({'DATA_DIR':self.root,'clip_speech':mock.Mock(transcribe_file=slow)})
            original = runtime.bounded_source
            async def quick(label,fn,*args,timeout=6):
                return await original(label,fn,*args,timeout=.02 if label.startswith('asr:') else timeout)
            runtime.bounded_source = quick
            with self.assertRaises(cut.SourceAnalysisPending): await runtime.seal(plan)
            saved = runtime.load(plan['id'])
            self.assertFalse(saved['complete'])
            self.assertEqual(saved['analysis_state'],'pending')
            self.assertTrue(saved['clips'][1]['source_analysis_pending'])
            self.assertEqual(saved['clips'][1]['sid'],plan['clips'][1]['sid'])
            gate.set();await asyncio.sleep(.04)
            completed = await runtime.seal(saved)
            self.assertTrue(completed['complete'])
            self.assertEqual(completed['id'],plan['id'])
            self.assertEqual(len(calls),1)
            runtime.source_pool.shutdown(wait=False)
        asyncio.run(run())

    def test_explicit_bootstrap_rechecks_native_pcm_hash_source_controls_and_item(self):
        plan = cut.compose(self.scan(),self.cfg,'original-unplayed-preview')
        self.assertTrue(plan['ok'],plan)
        pcm = b''
        cues = []
        for source in plan['clips']:
            with wave.open(source['path'],'rb') as audio:
                audio.setpos(round(source['from_s']*cut.RATE))
                chunk = audio.readframes(round((source['until_s']-source['from_s'])*cut.RATE))
            start = len(pcm)/2/cut.RATE
            pcm += chunk
            cues.append({**source,'at':start,'until':len(pcm)/2/cut.RATE,
                         'body_seconds':len(chunk)/2/cut.RATE,
                         'source_from':source['from_s'],'source_until':source['until_s']})
        name='b'*32+'.wav'
        path=self.root/name
        with wave.open(str(path),'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(cut.RATE);audio.writeframes(pcm)
        plan.update(clip=name,cues=cues,seconds=len(pcm)/2/cut.RATE,rendered_at=time.time())
        banned=set()
        runtime=cut.SupercutRuntime({'DATA_DIR':self.root,'VOICE_MEDIA_DIR':self.root,
                                    'media_sign':lambda name:'test-signature','sfx_bans':lambda:banned})
        runtime.save(plan)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        prepared=runtime.verify_bootstrap(plan['id'],digest,'first-scheduled-occurrence',self.cfg)
        self.assertEqual(prepared['body_frames'],len(pcm)//2)
        self.assertEqual(prepared['sample_rate'],cut.RATE)
        self.assertEqual(prepared['source_plan']['clips'],plan['clips'])
        self.assertEqual(prepared['cues'],cues)
        self.assertEqual(prepared['source_plan']['occurrence'],'first-scheduled-occurrence')
        self.assertEqual(prepared['source_plan']['bootstrap_from_occurrence'],plan['occurrence'])
        self.assertNotIn('system3',prepared)
        self.assertEqual(runtime.load(plan['id'])['occurrence'],plan['occurrence'])
        with self.assertRaisesRegex(ValueError,'hash changed'):
            runtime.verify_bootstrap(plan['id'],'0'*64,'first-scheduled-occurrence',self.cfg)
        banned.add(plan['clips'][0]['sid'])
        with self.assertRaisesRegex(ValueError,'banned or disabled'):
            runtime.verify_bootstrap(plan['id'],digest,'first-scheduled-occurrence',self.cfg)
        banned.clear()
        with self.assertRaisesRegex(ValueError,'does not match'):
            runtime.verify_bootstrap(plan['id'],digest,'first-scheduled-occurrence',{**self.cfg,'item':'Pine Box FM and I'})
        altered=copy.deepcopy(plan);altered['clips'][0]['mtime']-=2;runtime.save(altered)
        with self.assertRaisesRegex(ValueError,'changed since'):
            runtime.verify_bootstrap(plan['id'],digest,'first-scheduled-occurrence',self.cfg)
        runtime.source_pool.shutdown(wait=False)

    def test_explicit_bootstrap_route_uses_existing_write_auth_and_native_runtime(self):
        class App:
            def __init__(self): self.routes={}
            def get(self,path): return lambda fn:self.register('GET',path,fn)
            def post(self,path): return lambda fn:self.register('POST',path,fn)
            def register(self,method,path,fn): self.routes[method,path]=fn;return fn
            def on_event(self,event): return lambda fn:fn
        app=App()
        auth=mock.Mock()
        host={'DATA_DIR':self.root,'require_auth':auth}
        runtime=cut.install(app,host)
        runtime.bootstrap=mock.AsyncMock(return_value={'ok':True,'autoplay':False})
        request=mock.Mock(json=mock.AsyncMock(return_value={'plan_id':'original','media_sha256':'digest'}))
        result=asyncio.run(app.routes['POST','/api/sfx/supercut/bootstrap'](request,'Bearer authorized'))
        auth.assert_called_once_with('Bearer authorized')
        runtime.bootstrap.assert_awaited_once_with('original','digest')
        self.assertEqual(result,{'ok':True,'autoplay':False})
        runtime.source_pool.shutdown(wait=False)

    def test_native_preparation_keeps_audio_body_target_separate_from_system2_wall_target(self):
        async def run():
            runtime=cut.SupercutRuntime({'DATA_DIR':self.root})
            runtime.plan=mock.AsyncMock(return_value={'ok':False,'needs':['pending-source']})
            await runtime.prepare({'target_seconds':60,'minutes':1,'dynamic_config':self.cfg},
                                  'operator custom station promo','first-scheduled')
            args,kwargs=runtime.plan.await_args
            self.assertEqual(args[0]['target_seconds'],45)
            self.assertEqual(args[0]['min_seconds'],30)
            self.assertEqual(kwargs['prompt'],'operator custom station promo')
            self.assertEqual(kwargs['occurrence'],'first-scheduled')
            await runtime.prepare({'target_seconds':38},'standalone preview','preview')
            self.assertEqual(runtime.plan.await_args.args[0]['target_seconds'],38)
            runtime.source_pool.shutdown(wait=False)
        asyncio.run(run())

    def test_bootstrap_approval_never_falls_back_for_another_occurrence_or_custom_prompt(self):
        async def run():
            runtime=cut.SupercutRuntime({'DATA_DIR':self.root,'VOICE_MEDIA_DIR':self.root})
            exact='frozen station promo prompt'
            approved={'ok':True,'audio':'existing.wav','source_only':True}
            runtime.bootstrap_ready['first']={'prepared':approved,'requested':self.cfg,
                'prompt_hash':hashlib.sha256(exact.encode()).hexdigest()}
            runtime.plan=mock.AsyncMock(return_value={'ok':False,'needs':['fresh-planning']})
            result=await runtime.prepare({'dynamic_config':self.cfg},exact,'first')
            self.assertEqual(result,approved)
            runtime.plan.assert_not_awaited()
            await runtime.prepare({'dynamic_config':self.cfg},exact,'second')
            await runtime.prepare({'dynamic_config':self.cfg},exact+' changed','first')
            await runtime.prepare({'dynamic_config':{**self.cfg,'item':'another product'}},exact,'first')
            self.assertEqual(runtime.plan.await_count,3)
            runtime.source_pool.shutdown(wait=False)
        asyncio.run(run())

    def test_complete_catalog_future_yields_and_reuses_one_scan_without_a_queue(self):
        async def run():
            vectors=mock.Mock(store=self.store)
            runtime=cut.SupercutRuntime({'DATA_DIR':self.root,'_sfx_vectors':lambda:vectors})
            gate=threading.Event();calls=[]
            def full_scan(store):
                calls.append(1);gate.wait(1)
                return cut.scan_catalog(self.book,store,self.cfg)
            try:
                with self.assertRaises(cut.SourceAnalysisPending):
                    await runtime.bounded_catalog('full-config',full_scan,timeout=.02)
                self.assertFalse(runtime.catalog_future[1].cancelled())
                with self.assertRaises(cut.SourceAnalysisPending):
                    await runtime.bounded_catalog('full-config',full_scan,timeout=.02)
                with self.assertRaises(cut.SourceAnalysisPending):
                    await runtime.bounded_catalog('different-config',full_scan,timeout=.02)
                self.assertEqual(calls,[1])
                gate.set();await asyncio.sleep(.05)
                scan=await runtime.bounded_catalog('full-config',full_scan,timeout=.02)
                self.assertEqual(scan['coverage']['catalog_scanned'],38)
                self.assertEqual(calls,[1])
                self.assertIsNot(runtime.catalog_index.con,self.store.con)
                with self.assertRaises(sqlite3.OperationalError):
                    await runtime.bounded_catalog('forbidden-write',lambda store:store.con.execute('delete from clips'),timeout=.1)
                self.assertEqual(self.store.con.execute('select count(*) from clips').fetchone()[0],0)
            finally:
                gate.set();runtime.catalog_pool.shutdown(wait=False);runtime.source_pool.shutdown(wait=False)
        asyncio.run(run())

    def test_status_harvesting_a_completed_scan_cannot_clear_its_next_live_future(self):
        async def run():
            vectors=mock.Mock(store=self.store)
            runtime=cut.SupercutRuntime({'DATA_DIR':self.root,'_sfx_vectors':lambda:vectors})
            first_release=asyncio.Event();second_gate=threading.Event();first_observed=asyncio.Event()
            actual_wait_for=asyncio.wait_for
            async def controlled_wait(future,timeout):
                result=await actual_wait_for(future,timeout)
                if not first_observed.is_set():
                    first_observed.set()
                    await first_release.wait()
                return result
            try:
                with mock.patch.object(cut.asyncio,'wait_for',side_effect=controlled_wait):
                    first=asyncio.create_task(runtime.bounded_catalog('scan',lambda store:'complete-scan',timeout=1))
                    await first_observed.wait()
                    self.assertTrue(runtime.catalog_future[1].done())
                    # A status visitor harvests the completed scan and starts a
                    # coverage read before the original caller resumes.
                    second=asyncio.create_task(runtime.bounded_catalog('coverage',lambda store:second_gate.wait(1),timeout=1))
                    await asyncio.sleep(.02)
                    retained=runtime.catalog_future
                    self.assertEqual(retained[0],'coverage')
                    self.assertFalse(retained[1].done())
                    first_release.set()
                    self.assertEqual(await first,'complete-scan')
                    self.assertIs(runtime.catalog_future,retained)
                    self.assertEqual(runtime.catalog_analysis['operation'],'coverage')
                    self.assertEqual(runtime.catalog_analysis['state'],'scanning')
                    second_gate.set()
                    await second
                    self.assertIsNone(runtime.catalog_future)
            finally:
                first_release.set();second_gate.set()
                runtime.catalog_pool.shutdown(wait=False);runtime.source_pool.shutdown(wait=False)
        asyncio.run(run())

    def test_owned_catalog_scores_all_vectors_without_loading_the_keepers_matrix(self):
        for i in range(35):
            vec=[0.0]*24;vec[i%24]=1.0
            self.store.upsert_clips([{'sid':'s%03d'%i,'path':str(self.root/('s%03d'%i+'.wav')),'said':'radio music'}])
            self.store.put_clip_vectors(['s%03d'%i],[vec])
        index=cut._CatalogIndex(self.store)
        try:
            query=[1.0]+[0.0]*23
            with mock.patch.object(self.store,'_load_matrix',side_effect=AssertionError('shared matrix read')):
                scores=cut._semantic(index,{'sell':query})
            self.assertEqual(len(scores),35)
            self.assertAlmostEqual(scores.get('s000')['sell'],1)
            self.assertAlmostEqual(scores.get('s034')['sell'],0)
            self.assertIsNone(index._matrix)
            self.assertEqual(index.counts()['clips_embedded'],35)
        finally:
            index.con.close()

    def test_catalog_wait_does_not_consume_or_reset_the_shared_source_analysis_budget(self):
        async def run():
            vectors=mock.Mock(store=self.store)
            vectors.desk_busy.return_value=True
            runtime=cut.SupercutRuntime({'DATA_DIR':self.root,'SFX_DB_PATH':self.book,'_sfx_vectors':lambda:vectors})
            clock=[0.0]
            async def recorded(*args,**kwargs):
                clock[0]+=3.0
                return []
            async def scan(*args,**kwargs):
                clock[0]+=20.0
                return self.scan()
            async def seal(plan,*,deadline):
                self.assertEqual(clock[0],23.0)
                self.assertEqual(deadline-clock[0],13.0)
                plan['complete']=True
                return plan
            runtime.recorded_station_sources=recorded
            runtime.bounded_catalog=scan
            runtime.seal=seal
            try:
                with mock.patch.object(cut,'time',mock.Mock(monotonic=lambda:clock[0],time=time.time)):
                    plan=await runtime.plan(self.cfg,occurrence='source-budget-after-catalog',verify=True)
                self.assertTrue(plan['complete'])
            finally:
                runtime.catalog_pool.shutdown(wait=False);runtime.source_pool.shutdown(wait=False)
        asyncio.run(run())

    def test_native_plan_does_not_wait_in_the_shared_vector_keeper_queue(self):
        async def run():
            vectors=mock.Mock(store=self.store)
            vectors.desk_busy.return_value=True
            vectors.run=mock.AsyncMock(side_effect=AssertionError('shared vector queue used'))
            runtime=cut.SupercutRuntime({'DATA_DIR':self.root,'SFX_DB_PATH':self.book,'_sfx_vectors':lambda:vectors})
            try:
                plan=await runtime.plan(self.cfg,occurrence='owned-catalog-path',verify=True)
                self.assertTrue(plan['ok'],plan)
                self.assertTrue(plan['complete'])
                self.assertEqual(plan['coverage']['catalog_scanned'],38)
                vectors.run.assert_not_awaited()
                self.assertEqual(runtime.memo[next(iter(runtime.memo))],plan['id'])
            finally:
                runtime.catalog_pool.shutdown(wait=False);runtime.source_pool.shutdown(wait=False)
        asyncio.run(run())

    def test_current_source_words_reclassify_a_stale_sales_clip_as_flair(self):
        plan = cut.compose(self.scan(), self.cfg, "refresh-role")
        p = plan["clips"][1]
        p["mtime"] -= 2
        self.assertEqual(p["role"], "sell")
        speech = mock.Mock()
        speech.transcribe_file.return_value = "Potatoes!"
        runtime = cut.SupercutRuntime({"DATA_DIR": self.root, "SFX_DB_PATH": self.book, "clip_speech": speech})
        sealed = asyncio.run(runtime.seal(plan))
        self.assertEqual(sealed["clips"][1]["role"], "flair")
        self.assertEqual(sealed["clips"][1]["planned_role"], "sell")
        self.assertEqual(sealed["clips"][1]["why"]["current_spoken_matches"], [])


if __name__ == "__main__":
    unittest.main()
