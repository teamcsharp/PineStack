"""Behavioral checks for book progress, switching, cast routing and API security."""
import asyncio, json, tempfile, unittest, zipfile
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import book_mode

class BookTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.source=self.root/'shelf'; self.source.mkdir()
        # Real EPUB spine, metadata, and XHTML extraction, without a fake reader.
        path=self.source/'download_12345.epub'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('META-INF/container.xml','<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="book.opf"/></rootfiles></container>')
            z.writestr('book.opf','<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>A Test Book</dc:title></metadata><manifest><item id="c" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c"/></spine></package>')
            z.writestr('chapter.xhtml','<html><body><p>Dr. Smith read the guide. The lead pipe was heavy. They lead the expedition! This is the fourth sentence.</p></body></html>')
        self.mode=book_mode.BookMode(self.root/'cache',[str(self.source)]); self.mode.scan(); self.book=next(iter(self.mode.catalog))
    def tearDown(self):self.tmp.cleanup()
    def test_real_epub_and_cover(self):
        rows=self.mode.lines(self.book)
        self.assertEqual(len(rows),4);self.assertEqual(rows[0]['text'],'Dr. Smith read the guide.')
        self.assertEqual(rows[1]['page'],1)
        svg=self.mode.cover(self.book);self.assertIn(b'<svg',svg);self.assertEqual(svg,self.mode.cover(self.book))
        self.assertEqual(self.mode.books('test')['total'],1);self.assertEqual(self.mode.books('missing')['total'],0)
    def test_catalog_uses_and_caches_package_title_without_reading_chapters(self):
        row=self.mode.row(self.book)
        self.assertEqual(row['title'],'A Test Book')
        self.assertEqual(row['title_source'],'metadata')
        with patch('book_mode.book_metadata',side_effect=AssertionError('unchanged metadata reread')):
            self.mode.scan()
            reloaded=book_mode.BookMode(self.root/'cache',[str(self.source)]);reloaded.scan()
        self.assertEqual(reloaded.books('a test')['total'],1)
        self.assertEqual(reloaded.books('download')['total'],0)
        reloaded.catalog[self.book].pop('metadata_version')
        with patch('library_extract.read_document',side_effect=AssertionError('catalog extracts chapter text')):
            reloaded.scan()
        self.assertEqual(reloaded.row(self.book)['title'],'A Test Book')
        self.assertNotIn('path',reloaded.books()['books'][0])
    def test_metadata_batches_publish_and_persist_before_slow_titles_finish(self):
        template=Path(self.mode.row(self.book)['path']).read_bytes()
        for index in range(36):(self.source/f'batch_{index:02d}.epub').write_bytes(template)
        release=Event();partial=Event();blocked=Event();counter_lock=Lock();in_flight=0;peak=0;waiting=0
        original_write=self.mode._write
        def metadata(path):
            nonlocal in_flight,peak,waiting
            index=int(path.stem.split('_')[1])
            with counter_lock:
                in_flight+=1;peak=max(peak,in_flight)
                if index>=32:
                    waiting+=1
                    if waiting==4:blocked.set()
            try:
                if index>=32 and not release.wait(10):raise AssertionError('test did not release slow titles')
                return dict(title=f'Corrected Title {index:02d}',author='Actual Author',title_source='metadata',metadata_version=book_mode.CATALOG_VERSION)
            finally:
                with counter_lock:in_flight-=1
        def write(name,value):
            original_write(name,value)
            if name=='catalog.json':
                corrected=sum(row['title'].startswith('Corrected Title') for row in value.values())
                if 0<corrected<36:partial.set()
        with patch('book_mode.book_metadata',side_effect=metadata),patch.object(self.mode,'_write',side_effect=write),ThreadPoolExecutor(max_workers=1) as scanner:
            future=scanner.submit(self.mode.scan)
            try:
                self.assertTrue(partial.wait(5),'corrected titles not published during scan')
                self.assertTrue(blocked.wait(5),'slow titles did not run concurrently')
                self.assertFalse(future.done())
                snapshot=self.mode.catalog
                self.assertEqual(self.mode.books('corrected')['total'],32)
                self.assertEqual(self.mode.row(self.book)['title'],'A Test Book')
                saved=json.loads((self.root/'cache'/'catalog.json').read_text())
                self.assertEqual(sum(row['title'].startswith('Corrected Title') for row in saved.values()),32)
                self.assertTrue(self.mode.books()['metadata_progress']['active'])
                self.assertLessEqual(peak,8);self.assertGreater(peak,1)
            finally:release.set()
            self.assertEqual(future.result(timeout=5)['count'],37)
        self.assertIsNot(snapshot,self.mode.catalog)
        self.assertEqual(sum(row['title'].startswith('Corrected Title') for row in snapshot.values()),32)
        self.assertEqual(self.mode.books('corrected')['total'],36)
        self.assertFalse(self.mode.books()['metadata_progress']['active'])
        self.assertTrue(all(row['metadata_version']==book_mode.CATALOG_VERSION for row in self.mode.catalog.values()))
    def test_changed_metadata_rebuilds_persisted_title_cover(self):
        old=self.mode.cover(self.book);old_version=self.mode.cover_version(self.book)
        path=Path(self.mode.row(self.book)['path'])
        with zipfile.ZipFile(path) as archive:members={name:archive.read(name) for name in archive.namelist()}
        members['book.opf']=members['book.opf'].replace(b'A Test Book',b'The Actual Title &amp; Its Sequel').replace(b'</metadata>',b'<dc:creator>Ann Author</dc:creator></metadata>')
        with zipfile.ZipFile(path,'w') as archive:
            for name,body in members.items():archive.writestr(name,body)
        self.mode.scan();row=self.mode.row(self.book)
        self.assertEqual(row['title'],'The Actual Title & Its Sequel');self.assertEqual(row['author'],'Ann Author')
        cover=self.mode.cover(self.book)
        self.assertNotEqual(old,cover);self.assertNotEqual(old_version,self.mode.cover_version(self.book))
        self.assertIn(b'The Actual Title &amp; Its Sequel',cover);self.assertIn(b'Ann Author',cover)
        self.assertEqual(cover,self.mode.cover(self.book))
        saved=json.loads((self.root/'cache'/self.book/'cover.json').read_text())
        self.assertEqual(saved['title'],row['title']);self.assertEqual(saved['stamp'],row['stamp'])
    def test_pdf_metadata_and_malformed_metadata_fallback(self):
        from pypdf import PdfWriter
        path=self.source/'anonymous_download.pdf';writer=PdfWriter();writer.add_blank_page(width=300,height=420)
        writer.add_metadata({'/Title':'A Real PDF Title','/Author':'Pat Writer'})
        with path.open('wb') as source:writer.write(source)
        (self.source/'Damaged_Book.epub').write_bytes(b'not an epub')
        self.mode.scan()
        pdf=self.mode.books('real pdf')['books'][0]
        self.assertEqual(pdf['title'],'A Real PDF Title');self.assertEqual(pdf['author'],'Pat Writer')
        fallback=self.mode.books('damaged')['books'][0]
        self.assertEqual(fallback['title'],'Damaged Book');self.assertEqual(fallback['title_source'],'filename')
        self.assertIn(b'Damaged Book',self.mode.cover(fallback['id']))
    def test_cached_titles_survive_unavailable_share(self):
        moved=self.root/'offline';self.source.rename(moved)
        self.mode.scan()
        self.assertEqual(self.mode.books('a test')['total'],1);self.assertTrue(self.mode.errors)
        self.assertIn(b'A Test Book',self.mode.cover(self.book))
    def test_progress_only_on_ordered_heard_receipt(self):
        self.mode.select(self.book);self.mode.active=True
        self.mode.pending['one']=dict(epoch=self.mode.epoch,line=0)
        self.mode.pending['two']=dict(epoch=self.mode.epoch,line=1)
        with self.assertRaises(ValueError):self.mode.receipt('two')
        self.assertNotIn(self.book,self.mode.store['books'])
        self.mode.receipt('one');self.assertEqual(self.mode.position,1)
        reloaded=book_mode.BookMode(self.root/'cache',[str(self.source)]);reloaded.scan()
        resume=reloaded.select(self.book);self.assertTrue(resume['confirm_resume']);self.assertEqual(resume['resume_line'],1)
        self.assertEqual(reloaded.book,'');reloaded.select(self.book,confirm=True);self.assertEqual(reloaded.position,1)
    def test_seek_and_invalidate_do_not_mark_unheard(self):
        self.mode.select(self.book);self.mode.active=True;self.mode.pending['old']=dict(epoch=self.mode.epoch,line=0)
        self.mode.seek(2)
        with self.assertRaises(ValueError):self.mode.receipt('old')
        self.assertNotIn(self.book,self.mode.store['books'])
        with self.assertRaises(ValueError):self.mode.seek(100)
    def test_changed_edition_requires_restart(self):
        self.mode.select(self.book);self.mode.store['books'][self.book]=dict(last_line=0,stamp='old')
        self.assertTrue(self.mode.select(self.book)['changed'])
        with self.assertRaises(ValueError):self.mode.select(self.book,confirm=True)
        self.mode.select(self.book,start=True);self.assertEqual(self.mode.position,0)
    def test_preferences_and_contextual_pronunciation(self):
        self.mode.select(self.book)
        self.mode.preferences(dict(readers=['manager','caller'],routing='sequential',speed=16))
        self.assertEqual([self.mode.speaker(i) for i in range(3)],['manager','caller','manager'])
        for invalid in (dict(speed=3),dict(readers=[]),dict(gap_ms=-1),dict(blend_ms=float('nan'))):
            with self.assertRaises(ValueError):self.mode.preferences(invalid)
        self.mode.pronunciation(1,'lead','led')
        self.assertEqual(self.mode.spoken_text('The lead pipe was heavy.',1),'The led pipe was heavy.')
        self.assertEqual(self.mode.spoken_text('They lead the expedition!',2),'They lead the expedition!')
    def test_missing_share_is_reported(self):
        m=book_mode.BookMode(self.root/'other',[str(self.root/'missing')]);result=m.scan()
        self.assertEqual(result['count'],0);self.assertTrue(result['errors'])

class ApiTests(BookTests):
    def setUp(self):
        super().setUp();self.paused=False;self.bank=[];self.app=FastAPI()
        def auth(value):
            if value!='Bearer test':raise HTTPException(401,detail='Unauthorized')
        def pause(on,why=''):self.paused=on
        self.g=dict(data_path=lambda _:self.root/'api-cache',require_auth=auth,require_read_auth=auth,radio_paused=lambda:self.paused,radio_pause_set=pause,media_sign=lambda _: 'signed')
        with patch.dict('os.environ',{'PINE_BOOK_FOLDERS':str(self.source)}):self.api_mode=book_mode.register(self.app,self.g)
        self.api_mode.scan();self.book=next(iter(self.api_mode.catalog));self.client=TestClient(self.app);self.headers={'Authorization':'Bearer test'}
    def post(self,url,body):return self.client.post(url,json=body,headers=self.headers)
    def test_start_requires_selected_title_and_browsing_keeps_fm_playing(self):
        response=self.post('/api/books/mode',dict(active=True))
        self.assertEqual(response.status_code,409);self.assertIn('Choose a book',response.json()['detail'])
        self.assertFalse(self.paused);self.assertFalse(self.api_mode.active)
        self.assertNotIn('mode_lease',self.api_mode.store)
        self.client.get('/api/books',headers=self.headers)
        self.post('/api/books/'+self.book+'/select',{})
        self.assertFalse(self.paused);self.assertFalse(self.api_mode.active)
        self.assertEqual(self.post('/api/books/mode',dict(active=True)).status_code,200)
        self.assertTrue(self.paused);self.assertTrue(self.api_mode.active)
    def test_catalog_signed_cover_image_renders_and_stale_cards_are_rebuilt(self):
        catalog=self.client.get('/api/books',headers=self.headers).json();row=catalog['books'][0]
        self.assertIn('cover_url',row);self.assertIn('v='+row['cover_version'],row['cover_url'])
        self.assertEqual(self.client.get('/api/books/'+self.book+'/cover.svg').status_code,401)
        self.assertEqual(self.client.get('/api/books/'+self.book+'/cover.svg?t=wrong').status_code,401)
        response=self.client.get(row['cover_url'])
        self.assertEqual(response.status_code,200,response.text);self.assertTrue(response.headers['content-type'].startswith('image/svg+xml'))
        self.assertIn(b'<svg',response.content);self.assertIn(b'A Test Book',response.content)
        self.assertEqual(response.headers['etag'],'"'+row['cover_version']+'"')
        self.assertEqual(self.client.get(row['cover'],headers=self.headers).json()['svg'],response.text)
        self.assertFalse(self.paused);self.assertNotIn(self.book,self.api_mode.store['books'])
    def test_find_passages_auth_paging_and_no_progress(self):
        url='/api/books/'+self.book+'/find?q=LEAD&limit=1'
        self.assertEqual(self.client.get(url).status_code,401)
        first=self.client.get(url,headers=self.headers).json()
        self.assertEqual(first['total'],2);self.assertEqual(first['matches'][0]['line'],1)
        second=self.client.get(url+'&offset=1',headers=self.headers).json()
        self.assertEqual(second['matches'][0]['line'],2)
        self.assertEqual(self.client.get('/api/books/'+self.book+'/find',headers=self.headers).json()['matches'],[])
        self.assertEqual(self.client.get('/api/books/'+self.book+'/find?q=nonexistent',headers=self.headers).json()['total'],0)
        self.assertNotIn(self.book,self.api_mode.store['books'])
    def test_auth_pause_and_restore(self):
        self.assertEqual(self.client.get('/api/books').status_code,401)
        self.post('/api/books/'+self.book+'/select',{})
        self.assertEqual(self.post('/api/books/mode',dict(active=True)).status_code,200);self.assertTrue(self.paused)
        self.assertEqual(self.post('/api/books/mode',dict(active=False)).status_code,200);self.assertFalse(self.paused)
        self.paused=True;self.post('/api/books/mode',dict(active=True));self.post('/api/books/mode',dict(active=False));self.assertTrue(self.paused)
    def test_select_claim_preview_and_invalid_receipt(self):
        result=self.post('/api/books/'+self.book+'/select',{});self.assertEqual(result.status_code,200,result.text)
        self.post('/api/books/mode',dict(active=True))
        session=result.json()['session'];claimed=self.post('/api/books/claim',{});self.assertNotEqual(session,claimed.json()['session'])
        preview=self.client.get('/api/books/'+self.book+'/sentences',headers=self.headers)
        self.assertEqual(len(preview.json()['lines']),4)
        self.assertEqual(self.post('/api/books/heard',dict(token='unheard')).status_code,409)
        self.assertEqual(self.client.get('/api/books/'+self.book+'/file?t=wrong').status_code,401)
        self.assertEqual(self.client.get('/api/books/'+self.book+'/file?t=signed').status_code,200)


class NarrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import httpx
        self.fixture=BookTests();self.fixture.setUp();self.app=FastAPI();self.paused=False
        async def actors():return dict(host='voice-host',dj='voice-host',cohost='voice-cohost',third='voice-third')
        async def ask(*args,**kwargs):return '{"pace":1,"pitch_st":0,"energy":0}'
        async def render(text,voice,engine,**kwargs):self.rendered=(text,voice,kwargs);return dict(path='/media/test.wav',sig='signed')
        def auth(value):
            if value!='Bearer test':raise HTTPException(401)
        def pause(on,why=''):self.paused=on
        self.g=dict(data_path=lambda _:self.fixture.root/'narration',require_auth=auth,require_read_auth=auth,radio_paused=lambda:self.paused,radio_pause_set=pause,media_sign=lambda _: 'signed',dj_settings=lambda:dict(voice='voice-host',cohost_voice='voice-cohost'),session_voices=actors,voice_engine_for=lambda _: 'piper',read_character=lambda _: None,ask_model=ask,voice_render_any=render,cast_name=lambda r:r.title())
        with patch.dict('os.environ',{'PINE_BOOK_FOLDERS':str(self.fixture.source)}):self.mode=book_mode.register(self.app,self.g)
        self.mode.scan();self.book=next(iter(self.mode.catalog));self.mode.select(self.book);self.mode.active=True;self.mode.preferences(dict(sfx=False))
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://test',headers={'Authorization':'Bearer test'})
    async def asyncTearDown(self):await self.client.aclose();self.fixture.tearDown()
    async def test_cast_render_and_receipt(self):
        result=await self.client.post('/api/books/next',json=dict(session=self.mode.session,line=0));self.assertEqual(result.status_code,200,result.text)
        item=result.json();self.assertEqual(self.rendered[0],'Dr. Smith read the guide.');self.assertEqual(self.rendered[1],'voice-host')
        self.assertEqual(item['reader_node']['selected'],'host');self.assertEqual(self.mode.position,0)
        await self.client.post('/api/books/heard',json=dict(token=item['token']));self.assertEqual(self.mode.position,1)
        second=await self.client.post('/api/books/next',json=dict(session=self.mode.session,line=1));self.assertEqual(second.json()['reader'],'cohost')
    async def test_switch_cancels_inflight_voice_and_rejects_old_session(self):
        entered=asyncio.Event()
        async def stalled(*args,**kwargs):entered.set();await asyncio.Event().wait()
        self.g['voice_render_any']=stalled;old=self.mode.session
        task=asyncio.create_task(self.client.post('/api/books/next',json=dict(session=old,line=0)))
        await asyncio.wait_for(entered.wait(),2)
        toggled=await asyncio.wait_for(self.client.post('/api/books/mode',json=dict(active=False)),2)
        self.assertFalse(toggled.json()['active'])
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertNotIn(self.book,self.mode.store['books'])
    async def test_reader_roulette_replays_and_weights(self):
        self.mode.preferences(dict(readers=['host','manager'],routing='roulette',reader_node=dict(label='Solo manager',weights=dict(host=0,manager=1))))
        self.assertEqual(self.mode.speaker(0),'manager');a=self.mode.last_decision.copy();self.assertEqual(self.mode.speaker(0),'manager');self.assertEqual(a,self.mode.last_decision)

class LibraryDiscoveryTests(unittest.TestCase):
    def setUp(self):
        import library
        self.lib=library;self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.shelf=self.root/'Epub';self.shelf.mkdir()
        self.previous=(library._DATA,library._INDEX,library._EMBED,library._BUSY,library._REFERENCE)
        library._INDEX=None;library.configure(data_dir=self.root/'vectors',embed=self.embed,busy=lambda:False,reference=[str(self.shelf)])
        self.first=self.shelf/'first.txt';self.first.write_text('This document explains how the sampling machine records and plays a sample. '*8)
        self.arrival=False
    async def embed(self,texts):
        if not self.arrival:
            self.arrival=True
            (self.shelf/'second.txt').write_text('A newly added document describes vector discovery during a long ingestion pass. '*8)
            result=self.lib.discover([str(self.shelf)]);self.assertEqual(len(result['queued']),1)
        return [[1.0,0.0,0.0] for _ in texts]
    def tearDown(self):
        self.lib._DATA,self.lib._INDEX,self.lib._EMBED,self.lib._BUSY,self.lib._REFERENCE=self.previous
        self.lib._SHARDS.clear();self.lib._MATS.clear();self.tmp.cleanup()
    def test_new_file_is_vectorized_in_the_running_pass(self):
        result=asyncio.run(self.lib.ingest_pass([str(self.shelf)]))
        self.assertEqual(result['read'],2)
        self.assertEqual(len([r for r in self.lib.docs() if r['state']=='ready']),2)
    def test_discovery_retains_offline_sources_and_requeues_changes(self):
        first=self.lib.discover([str(self.shelf)]);self.assertEqual(len(first['queued']),1)
        row=self.lib.doc_row(first['queued'][0]);row['state']='ready'
        outage=self.lib.discover([str(self.root/'unavailable')]);self.assertEqual(outage['seen'],0);self.assertIsNotNone(self.lib.doc_row(row['slug']))
        self.first.write_text(self.first.read_text()+' A changed chapter was appended.')
        changed=self.lib.discover([str(self.shelf)]);self.assertEqual(changed['queued'],[row['slug']]);self.assertEqual(row['state'],'queued')
    def test_graph_retains_custom_reader_configuration(self):
        import conversation_graph
        graph=conversation_graph.normalize(dict(nodes=[dict(id='book',type='book_reader',readers=['manager','caller'],routing='single',weights=dict(manager=2,caller=0))]))
        self.assertEqual(graph['nodes'][0]['readers'],['manager','caller']);self.assertEqual(graph['nodes'][0]['routing'],'single');self.assertEqual(graph['nodes'][0]['weights']['manager'],2)

if __name__=='__main__':unittest.main()
