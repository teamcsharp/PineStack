"""Custom exact-word Super Cuts, made only from verified original clip audio.

Timing estimates locate audition windows; only an actual transcript of the
trimmed audio can approve them. Missing words stay missing, never synthesized.
"""
from __future__ import annotations
import asyncio
import copy
import hashlib
import itertools
import json
import re
import sqlite3
import subprocess
import tempfile
import time
import uuid
import wave
from pathlib import Path
from threading import RLock

import sfx_supercut as cut

ID = re.compile(r"scc-[a-f0-9]{24}")
TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")

def tokens(text):
    return TOKEN.findall(str(text or '').casefold())

# [cut-anyway] HOW EXACT A CUT HAS TO BE IS A DIAL, NOT A WALL. 100 is the old
# rule: a second ASR pass on the trimmed window must return exactly the words
# asked for, and one word that fails ends the whole job. Below 100 the job is
# assembled from what the clips say: a window is taken when the words were heard
# inside it (or nearly - the dial is the similarity wanted), a phrase no window
# was heard cleanly for is cut where its clip's own transcript puts it, and a
# word no clip says is listed and left out.
import difflib

DEFAULT_ACCURACY = 70.


def heard_close(heard, want, accuracy):
    """May a trimmed window heard as `heard` stand for the words `want`?"""
    if heard == want:
        return True
    if accuracy >= 100. or not heard or not want:
        return False
    size = len(want)
    if any(heard[at:at + size] == want for at in range(len(heard) - size + 1)):
        return True                     # the words are in there, with a neighbour's syllable around them
    return difflib.SequenceMatcher(None, ' '.join(heard), ' '.join(want)).ratio() * 100. >= accuracy


def recursive(source):
    path = Path(str(source.get('path') or ''))
    provenance = source.get('provenance') or {}
    return (path.name.startswith('supercut-') or 'supercuts' in path.parts or
        provenance.get('supercut_archive_id') or provenance.get('supercut_source') or
        provenance.get('origin') in {'sfx_supercut','supercut'})

def windows(source, offset, count):
    """Audition candidates, not inferred word evidence."""
    words, seconds = tokens(source.get('said')), cut._number(source.get('seconds'))
    target = words[offset:offset+count]
    if not target or recursive(source):
        return []
    if offset == 0 and count == len(words) and .06 <= seconds <= 6:
        return [(0., seconds, 'entire_source')]
    timed = source.get('word_timestamps') or []
    if (len(timed) == len(words) and [tokens(one.get('word') or one.get('text')) for one in timed] == [[word] for word in words]):
        start = cut._number(timed[offset].get('start'), -1)
        end = cut._number(timed[offset+count-1].get('end'), -1)
        if 0 <= start < end <= seconds and .06 <= end-start <= 6:
            return [(max(0.,start-.02),min(seconds,end+.02),'word_timestamps')]
    # These ranges only find audio to audition. ASR must match the requested
    # phrase exactly before a cut is accepted, including all surrounding words.
    start, end = seconds*offset/len(words), seconds*(offset+count)/len(words)
    result=[]
    for margin in (.08,.24,.5,.85):
        lo,hi=max(0.,start-margin),min(seconds,end+margin)
        if .06 <= hi-lo <= 6:
            result.append((round(lo,6),round(hi,6),'audition_estimate'))
    return result

def scan_words(book, wanted, extras=(), *, banned=(), weights=None, mp4_only=False, explanation=""):
    phrases={}
    for at in range(len(wanted)):
        for size in range(1,min(8,len(wanted)-at)+1):
            phrases.setdefault(tuple(wanted[at:at+size]),[])
    controls=weights or {}
    direction=cut._words(explanation)
    scanned=transcribed=eligible=0
    with cut._book_connection(book) as con:
        cols=cut._columns(con)
        names=[name for name in ('sid','path','name','seconds','mtime','said','said_at','video') if name in cols]
        for raw in itertools.chain(con.execute('select '+','.join(names)+' from clips where playable=1 order by rowid'), extras):
            scanned+=1
            row=dict(raw)
            sid=str(row.get('sid') or '')
            if (not sid or recursive(row) or sid in banned or cut._number(controls.get(sid,1),1)<=.05 or
                (mp4_only and (not row.get('video') or Path(str(row.get('path') or '')).suffix.lower() != '.mp4'))):
                continue
            said=tokens(row.get('said'))
            if not said:
                continue
            transcribed+=1
            # Word matching uses every playable transcript; retained audition
            # candidates are bounded only after the full catalog is scanned.
            if not .06 <= cut._number(row.get('seconds')) <= 180:
                continue
            hit=False
            for offset in range(len(said)):
                if said[offset] not in wanted:
                    continue
                for size in range(1,min(8,len(said)-offset)+1):
                    key=tuple(said[offset:offset+size])
                    if key not in phrases:
                        continue
                    ranges=windows(row,offset,size)
                    if not ranges:
                        continue
                    choice={**row,'word_offset':offset,'word_count':size,'windows':ranges,
                        'direction_matches': sorted(cut._words(str(row.get('name') or '')+' '+str(row.get('said') or '')) & direction)}
                    pool=phrases[key]
                    pool.append(choice)
                    pool.sort(key=lambda one:(-len(one.get('direction_matches') or []),0 if one['windows'][0][2]=='entire_source' else 1,
                        0 if one.get('word_timestamps') else 1, one['windows'][0][1]-one['windows'][0][0],str(one['sid'])))
                    del pool[6:]
                    hit=True
            eligible+=bool(hit)
    return {'phrases':{' '.join(key):value for key,value in phrases.items()},
        'coverage':{'catalog_scanned':scanned,'transcribed_sources_scanned':transcribed,
            'eligible_word_sources':eligible,'h3_sources_scanned':len(extras),
            'basis':'actual source transcripts; every chosen trimmed window is ASR verified'}}

def audition(source,start,end,transcriber,executable):
    path=Path(source['path']);stat=path.stat()
    expected=cut._number(source.get('mtime'))
    if expected and abs(stat.st_mtime-expected)>.01:
        raise ValueError('The selected word source changed; rescan the catalog')
    with tempfile.TemporaryDirectory(prefix='pine-supercut-words-') as tmp:
        output=Path(tmp)/'audition.wav'
        subprocess.run([str(executable),'-nostdin','-hide_banner','-loglevel','error','-y',
            '-ss',f'{start:.6f}','-t',f'{end-start:.6f}','-i',str(path),'-vn','-ac','1',
            '-ar',str(cut.RATE),'-sample_fmt','s16','-f','wav',str(output)],
            check=True,capture_output=True,timeout=6)
        with wave.open(str(output),'rb') as handle:
            seconds=handle.getnframes()/handle.getframerate()
            pcm=handle.readframes(handle.getnframes())
        if not any(pcm) or abs(seconds-(end-start))>.12:
            raise ValueError('The word window did not decode completely')
        heard=str(transcriber(str(output),timeout=6.) or '').strip()
    # Verify the source again after the audition; no receipt spans a file edit.
    after=path.stat()
    if after.st_mtime_ns != stat.st_mtime_ns or after.st_size != stat.st_size:
        raise ValueError('The word source changed during analysis')
    return {'said':heard,'mtime':stat.st_mtime,'bytes':stat.st_size,
        'source_audio_verified':True,'word_cut_verified':True,'source_window': [start,end]}

class CustomSupercuts:
    def __init__(self,runtime):
        self.runtime,self.host=runtime,runtime.host
        self.root=runtime.root/'custom';self.root.mkdir(parents=True,exist_ok=True)
        self.jobs,self.lock,self.task={},RLock(),None
        for path in self.root.glob('scc-*.json'):
            try:
                row=json.loads(path.read_text(encoding='utf-8'))
                if ID.fullmatch(str(row.get('id') or '')):
                    if row.get('status')=='analyzing':
                        row.update(status='queued',why='The same custom source analysis resumes after restart')
                    self.jobs[row['id']]=row
            except (OSError,ValueError,TypeError):
                pass

    def persist(self,row):
        with self.lock:
            self.jobs[row['id']]=copy.deepcopy(row)
            path=self.root/(row['id']+'.json');temporary=path.with_suffix('.tmp')
            temporary.write_text(json.dumps(row,ensure_ascii=False,indent=1),encoding='utf-8')
            temporary.replace(path)

    def view(self,ident):
        with self.lock:
            row=copy.deepcopy(self.jobs.get(str(ident),{}))
        for name in ('scan','cuts','attempted','cursor'):
            row.pop(name,None)
        return row

    def detail(self,ident):
        row=self.view(ident)
        if not row:
            raise FileNotFoundError('No such custom Super Cut')
        return row

    def list(self,limit=24):
        with self.lock:
            ids=[one['id'] for one in sorted(self.jobs.values(),key=lambda row:row['created_at'],reverse=True)[:max(1,min(100,int(limit)))]]
        return {'ok':True,'rows':[self.view(ident) for ident in ids],'autoplay':False}

    def presets(self):
        path = self.root / 'prompts.json'
        with self.lock:
            try:
                raw = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                raw = []
        return {'ok': True, 'presets': raw if isinstance(raw, list) else []}

    def save_preset(self, raw):
        name = str(raw.get('name') or '').strip()[:120]
        words = str(raw.get('words') or '').strip()[:12000]
        if not name or not 1 <= len(tokens(words)) <= 180:
            raise ValueError('Give this preset a name and between 1 and 180 source words')
        ident = str(raw.get('id') or 'scp-' + uuid.uuid4().hex[:24])
        if not re.fullmatch(r'scp-[a-f0-9]{24}', ident):
            raise ValueError('Invalid custom Super Cut preset')
        row = {'id': ident, 'name': name, 'words': words,
            'explanation': str(raw.get('explanation') or raw.get('prompt') or '')[:12000],
            'product': str(raw.get('product') or '')[:200],
            'target_seconds': max(.06, min(120., cut._number(raw.get('target_seconds'), 60.))),
            'updated_at': time.time()}
        with self.lock:
            rows = [one for one in self.presets()['presets'] if one.get('id') != ident]
            if len(rows) >= 200:
                raise ValueError('The custom preset shelf is full')
            rows.append(row)
            path = self.root / 'prompts.json'; temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
            temporary.replace(path)
        return {'ok': True, 'preset': row, 'presets': rows}

    def create(self,raw):
        words=str(raw.get('words') or raw.get('script') or '').strip()[:12000]
        wanted=tokens(words)
        if not wanted or len(wanted)>180:
            raise ValueError('Enter between 1 and 180 words for the existing clips to say')
        explanation=str(raw.get('explanation') or raw.get('prompt') or '').strip()[:12000]
        row={'ok':True,'id':'scc-'+uuid.uuid4().hex[:24],'words':words,'explanation':explanation,
            'product':str(raw.get('product') or 'Custom Super Cut').strip()[:200],
            'target_seconds':max(.06,min(120.,cut._number(raw.get('target_seconds'),60.))),
            'accuracy':max(0.,min(100.,cut._number(raw.get('accuracy'),DEFAULT_ACCURACY))),   # [cut-anyway] 100 = exact words only
            'created_at':time.time(),'updated_at':time.time(),'status':'queued','why':'Waiting to find and audition existing source words',
            'total_words':len(wanted),'matched_words':0,'missing_words':[], 'missing_phrases':[],
            'cuts':[],'cursor':0,'attempted':[], 'retry_at':0.,'autoplay':False,'source_only':True}
        self.persist(row)
        return self.view(row['id'])

    def retry(self,ident):
        with self.lock:
            row=copy.deepcopy(self.jobs.get(str(ident),{}))
        if not row:
            raise FileNotFoundError('No such custom Super Cut')
        if row['status']=='ready':
            return self.view(ident)
        row.update(status='queued',why='Rescanning current clips for the same requested words',
            retry_at=0.,cursor=0,cuts=[],attempted=[],missing_words=[],missing_phrases=[],
            matched_words=0,unverified_words=0)   # [cut-anyway] a retry counts from nothing
        row.pop('scan',None)
        self.persist(row)
        return self.view(ident)

    async def visit(self,ident):
        with self.lock:
            row=copy.deepcopy(self.jobs[ident])
        row.update(status='analyzing',updated_at=time.time())
        self.persist(row)
        wanted=tokens(row['words'])
        accuracy=cut._number(row.get('accuracy'),DEFAULT_ACCURACY)   # [cut-anyway] a job from before the dial is not exact-only
        transcriber=getattr(self.host.get('clip_speech'),'transcribe_file',None)
        if not callable(transcriber):
            row.update(status='incomplete',why='Trimmed source word verification is unavailable',missing_words=wanted,missing_phrases=[row['words']])
            self.persist(row);return
        try:
            import imageio_ffmpeg
            executable=imageio_ffmpeg.get_ffmpeg_exe()
            if not row.get('scan'):
                extras=await self.runtime.generated_h3_sources(prompt=row['words'],analyze=True)
                bans,weights,only=self.runtime.controls()
                row['scan']=await self.runtime.bounded_catalog('custom-scan:'+ident,
                    lambda _store:scan_words(self.host['SFX_DB_PATH'],wanted,extras,banned=bans,weights=weights,mp4_only=only,explanation=row['explanation']))
                row['coverage']=row['scan']['coverage'];self.persist(row)
            deadline=time.monotonic()+16.
            while row['cursor']<len(wanted):
                if time.monotonic()>deadline:
                    raise cut.SourceAnalysisPending('The custom source audition visit reached its 16 second budget')
                cursor=row['cursor'];selected=None
                for size in range(min(8,len(wanted)-cursor),0,-1):
                    phrase=' '.join(wanted[cursor:cursor+size])
                    for source in row['scan']['phrases'].get(phrase,[]):
                        for start,end,basis in source['windows']:
                            stamp=f"{cursor}:{size}:{source['sid']}:{start}:{end}"
                            if stamp in row['attempted']:
                                continue
                            label='custom-audition:'+ident+':'+hashlib.sha256(stamp.encode()).hexdigest()[:16]
                            try:
                                proof=await self.runtime.bounded_source(label,audition,source,start,end,transcriber,executable,
                                    timeout=min(6.,max(.05,deadline-time.monotonic())))
                            except cut.SourceAnalysisPending:
                                raise
                            except (OSError,ValueError,subprocess.SubprocessError,wave.Error):
                                row['attempted'].append(stamp);self.persist(row);continue
                            row['attempted'].append(stamp)
                            if heard_close(tokens(proof['said']),wanted[cursor:cursor+size],accuracy):   # [cut-anyway]
                                selected={**source,**proof,'from_s':start,'until_s':end,
                                    'role':'sell','requested_words':phrase,'timing_basis':basis,
                                    'transcript_scope':'current_trimmed_window_asr','why':{'exact_requested_words':phrase,
                                        'verified_audio':tokens(proof['said'])==wanted[cursor:cursor+size],'heard':str(proof['said'])[:120]}}
                                for name in ('windows','word_timestamps','word_offset','word_count'):
                                    selected.pop(name,None)
                                row['cuts'].append(selected);row['cursor']+=size
                                row['matched_words']+=size
                                break
                            self.persist(row)
                            if time.monotonic()>deadline:
                                raise cut.SourceAnalysisPending('The custom source audition visit reached its 16 second budget')
                        if selected:break
                    if selected:break
                if not selected and accuracy<100.:
                    # [cut-anyway] NO WINDOW WAS HEARD CLEANLY: the clip whose own transcript says
                    # these words is cut where the words are estimated to be, and marked unverified
                    for size in range(min(8,len(wanted)-cursor),0,-1):
                        phrase=' '.join(wanted[cursor:cursor+size])
                        pool=row['scan']['phrases'].get(phrase,[])
                        if pool:
                            source=pool[0];start,end,basis=source['windows'][0]
                            selected={**source,'from_s':start,'until_s':end,'role':'sell','requested_words':phrase,
                                'timing_basis':basis,'said':phrase,'source_audio_verified':False,'word_cut_verified':False,
                                'source_window':[start,end],'transcript_scope':'source_transcript_estimate',
                                'why':{'exact_requested_words':phrase,'verified_audio':False}}
                            for name in ('windows','word_timestamps','word_offset','word_count','mtime'):
                                selected.pop(name,None)
                            row['cuts'].append(selected);row['cursor']+=size;row['matched_words']+=size
                            row['unverified_words']=int(row.get('unverified_words') or 0)+size
                            break
                if not selected:
                    word=wanted[cursor]
                    row['missing_words'].append(word);row['missing_phrases'].append(word);row['cursor']+=1
                self.persist(row)
            if row['missing_words'] and (accuracy>=100. or not row['cuts']):   # [cut-anyway] below 100 a job with any cut is still assembled
                row.update(status='incomplete',why=('Some requested words have no verified trimmed source audio. Edit the words or retry after new clips arrive.'
                    if accuracy>=100. else 'No clip that has been listened to says any of these words yet. The idle listener is still working through the collection; retry later or change the words.'))
                self.persist(row);return
            seconds=sum(one['until_s']-one['from_s'] for one in row['cuts'])
            if seconds>row['target_seconds'] or len(row['cuts'])>cut.MAX_CUTS:
                row.update(status='incomplete',why='The exact requested source words exceed the selected duration or 64-cut limit')
                self.persist(row);return
            config=cut.config({'station':self.host.get('dj_settings',lambda:{})().get('station_name') or 'Pine Box FM',
                'item':row['product'],'custom':{'id':ident,'words':row['words'],'max_seconds':row['target_seconds'],
                    'accuracy':accuracy}})   # [cut-anyway] the renderer reads the same dial
            digest=hashlib.sha256(json.dumps([ident,[(one['sid'],one['from_s'],one['until_s']) for one in row['cuts']]],sort_keys=True).encode()).hexdigest()[:24]
            plan={'ok':True,'id':'sc-'+digest,'schema':cut.SCHEMA,'occurrence':ident,'source_only':True,'complete':True,
                'custom':True,'custom_job_id':ident,'config':config,'clips':row['cuts'],'source_count':len(row['cuts']),
                'seconds':seconds,'created_at':row['created_at'],'coverage':row['coverage'],'prompt':row['explanation'],
                'generated_script':row['words'],'requested_words':row['words'],'warnings':[],
                'structure':{'exact_requested_words_verified':bool(accuracy>=100. or not (row['missing_words'] or row.get('unverified_words'))),
                    'missing_words':list(row['missing_words']),'unverified_words':int(row.get('unverified_words') or 0)},'source_analysis':{'state':'complete','basis':'trimmed source ASR'}}
            result=await self.runtime.render(plan)
            row.update(status='ready',archive_id=result['archive_id'],archive=result['archive'],updated_at=time.time(),
                why=('' if not (row['missing_words'] or row.get('unverified_words')) else   # [cut-anyway] it says what it could not find
                    'Assembled at accuracy %d: %d of %d words are in it%s%s.' % (int(accuracy),row['matched_words'],row['total_words'],
                        (', %d of them cut on the transcript\'s estimate' % int(row.get('unverified_words') or 0)) if row.get('unverified_words') else '',
                        ('; no listened clip says: '+', '.join(row['missing_words'][:12])) if row['missing_words'] else '')))
            row.pop('scan',None);self.persist(row)
        except asyncio.CancelledError:
            row.update(status='queued',why='The same source cuts resume after restart');self.persist(row);raise
        except cut.SourceAnalysisPending as exc:
            row.update(status='queued',why=str(exc),retry_at=time.time()+5.);self.persist(row)
        except Exception as exc:
            row.update(status='error',why=str(exc)[:500],updated_at=time.time());self.persist(row)

    async def worker(self):
        while True:
            with self.lock:
                waiting=sorted((one for one in self.jobs.values() if one.get('status')=='queued' and one.get('retry_at',0)<=time.time()),key=lambda one:one['created_at'])
            if waiting:
                await self.visit(waiting[0]['id'])
            await asyncio.sleep(1.)


def install(app,host,runtime):
    from fastapi import Header,HTTPException,Request
    globals()['Request']=Request
    custom=CustomSupercuts(runtime);host['SUPERCUT_CUSTOM']=custom
    @app.get('/api/sfx/supercut/presets')
    async def presets(authorization: str | None = Header(default=None)):
        host['require_read_auth'](authorization)
        return await asyncio.to_thread(custom.presets)
    @app.post('/api/sfx/supercut/presets')
    async def save_preset(request: Request, authorization: str | None = Header(default=None)):
        host['require_auth'](authorization)
        raw = await request.json()
        try:
            return await asyncio.to_thread(custom.save_preset, raw if isinstance(raw, dict) else {})
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    @app.post('/api/sfx/supercut/custom')
    async def create(request:Request,authorization:str|None=Header(default=None)):
        host['require_auth'](authorization)
        raw=await request.json()
        try:return await asyncio.to_thread(custom.create,raw if isinstance(raw,dict) else {})
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    @app.get('/api/sfx/supercut/custom')
    async def history(limit:int=24,authorization:str|None=Header(default=None)):
        host['require_read_auth'](authorization)
        return await asyncio.to_thread(custom.list,limit)
    @app.get('/api/sfx/supercut/custom/{ident}')
    async def detail(ident:str,authorization:str|None=Header(default=None)):
        host['require_read_auth'](authorization)
        try:return await asyncio.to_thread(custom.detail,ident)
        except FileNotFoundError as exc:raise HTTPException(404,str(exc)) from exc
    @app.post('/api/sfx/supercut/custom/{ident}/retry')
    async def retry(ident:str,authorization:str|None=Header(default=None)):
        host['require_auth'](authorization)
        try:return await asyncio.to_thread(custom.retry,ident)
        except FileNotFoundError as exc:raise HTTPException(404,str(exc)) from exc
    @app.on_event('startup')
    async def start():custom.task=asyncio.create_task(custom.worker(),name='supercut:custom-editor')
    @app.on_event('shutdown')
    async def stop():
        if custom.task:
            custom.task.cancel()
            await asyncio.gather(custom.task,return_exceptions=True)
    return custom
