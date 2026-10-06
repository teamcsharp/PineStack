"""Durable, source-only Super Cut review library in the station's SFX ads folder.

Audio and its authored script remain distinct from the transcript of clips that
actually supplied the montage. Registration never publishes a playback event.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import json
import math
import re
import shutil
import sqlite3
import threading
import time
import uuid
import wave
from pathlib import Path
from typing import Any, Mapping

SCHEMA = 'sfx.supercut.archive/1'
ID = re.compile(r'sca-[a-f0-9]{24}')


def _atomic_text(path, text):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(text, encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_copy(source, target, digest):
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
        return
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        shutil.copyfile(source, temporary)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
            raise ValueError('Supercut audio changed while saving its archive')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def audio_facts(path, *, custom=False):
    path = Path(path)
    # Native renders are at most 60 seconds of mono 24 kHz PCM. Refuse arbitrary
    # large paths before reading; an archive endpoint is never a file resolver.
    if not path.is_file() or path.stat().st_size > (6 if custom else 4) * 1024 * 1024:
        raise ValueError('The complete Super Cut WAV is missing or too large')
    blob = path.read_bytes()
    with wave.open(str(path), 'rb') as handle:
        frames, rate, channels, width = (handle.getnframes(), handle.getframerate(),
                                        handle.getnchannels(), handle.getsampwidth())
        pcm = handle.readframes(frames)
    if (rate != 24000 or channels != 1 or width != 2 or
            len(pcm) != frames * 2 or not any(pcm)):
        raise ValueError('The archived Super Cut must be nonempty mono 24 kHz PCM')
    seconds = frames / rate
    if not (.06 if custom else 30) <= seconds <= (120 if custom else 60):
        raise ValueError('A complete Super Cut must contain 30 to 60 seconds of audio')
    return {'sha256': hashlib.sha256(blob).hexdigest(), 'body_frames': frames,
            'sample_rate': rate, 'seconds': seconds, 'bytes': len(blob)}


class SupercutArchive:
    def __init__(self, host: dict[str, Any]):
        self.host = host
        self.ads_dir = Path(host.get('SFX_ADS_DIR') or Path(host.get('DATA_DIR') or 'data') / 'sfx_ads')
        self.root = self.ads_dir / 'supercuts'
        self.db_path = self.root / 'archive.sqlite3'
        self.lock = threading.RLock()
        self.migration = {'state': 'idle', 'scanned': 0, 'archived': 0, 'skipped': 0}

    @contextmanager
    def connection(self):
        self.root.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path, timeout=10)
        try:
            con.row_factory = sqlite3.Row
            con.execute('create table if not exists archive (id text primary key, plan_id text, '
                        'created_at real not null, product text, station text, audio_name text, '
                        'sha256 text not null, reusable_ad_id text, metadata text not null)')
            con.execute('create index if not exists archive_created on archive(created_at desc, id)')
            with con:
                yield con
        finally:
            con.close()

    @staticmethod
    def identity(identifier):
        if not ID.fullmatch(str(identifier or '')):
            raise ValueError('Invalid Super Cut archive identity')
        return str(identifier)

    def decorate(self, row):
        value = json.loads(row['metadata'])
        value['reusable_ad_id'] = str(row['reusable_ad_id'] or '')
        sign = self.host.get('media_sign')
        signature = str(sign(value['id'])) if callable(sign) else ''
        value['audio_url'] = '/api/sfx/supercut/archive/' + value['id'] + '/audio'
        if signature:
            value['audio_url'] += '?t=' + signature
        if value.get('video_name'):
            value['kind'] = 'video'
            value['video_url'] = '/api/sfx/supercut/archive/' + value['id'] + '/video'
            if signature:
                value['video_url'] += '?t=' + signature
        return value

    def record(self, result: Mapping[str, Any]):
        if not result.get('ok') or not result.get('complete') or not result.get('source_only'):
            raise ValueError('Only a complete source-only Super Cut can enter the archive')
        plan = copy.deepcopy(result.get('source_plan') or {})
        pid = str(plan.get('id') or '')
        if not re.fullmatch(r'sc-[a-f0-9]{24}', pid) or not plan.get('complete') or not plan.get('source_only'):
            raise ValueError('The archive requires the complete original source plan')
        source = Path(str(result.get('path') or ''))
        custom = bool((plan.get("config") or {}).get("custom"))
        facts = audio_facts(source, custom=custom)
        reported = float(result.get('seconds') or plan.get('seconds') or 0)
        if not math.isfinite(reported) or abs(reported - facts['seconds']) > .002:
            raise ValueError('The measured archive audio differs from its completed plan')
        cues = copy.deepcopy(result.get('cues') or plan.get('cues') or [])
        clips = plan.get('clips') or []
        if not (1 if custom else 3) <= len(cues) <= 64 or len(cues) != len(clips):
            raise ValueError('The archive requires every original source cue')
        previous = 0.0
        for cue, clip in zip(cues, clips):
            start, end = float(cue.get('at', -1)), float(cue.get('until', -1))
            if (not math.isfinite(start + end) or abs(start - previous) > .002 or
                    not (.05 if custom else .4) <= end - start <= 6.12 or cue.get('sid') != clip.get('sid')):
                raise ValueError('The archived source cues do not cover the actual audio')
            previous = end
        if abs(previous - facts['seconds']) > .002:
            raise ValueError('The archived source cues miss part of the completed audio')
        identifier = 'sca-' + hashlib.sha256((pid + ':' + facts['sha256']).encode()).hexdigest()[:24]
        audio_name = 'supercut-' + identifier[4:] + '.wav'
        cfg = plan.get('config') or {}
        campaign = copy.deepcopy(plan.get('campaign') or cfg.get('campaign') or {})
        generated = str(plan.get('generated_script') or campaign.get('script') or result.get('generated_script') or '')
        # Prefer the explicit renderer transcript. Never call the generated
        # campaign script a recording or silently substitute it for source audio.
        recorded = str(result.get('recorded_text') or ' / '.join(str(c.get('said') or '[source audio: ' + str(c.get('name') or '') + ']') for c in cues))
        created = float(plan.get('rendered_at') or time.time())
        item = str(campaign.get('product') or cfg.get('item') or result.get('product') or 'Pine Box FM')[:200]
        value = {'schema': SCHEMA, 'id': identifier, 'archive_id': identifier,
                 'plan_id': pid, 'title': item + ' Super Cut', 'product': item,
                 'sponsor': str(cfg.get('sponsor') or campaign.get('sponsor') or 'Pine Box FM')[:200],
                 'station': str(cfg.get('station') or 'Pine Box FM')[:100],
                 'created_at': created, 'hour': campaign.get('hour') or plan.get('occurrence') or '',
                 'status': 'ready', 'source_only': True, 'complete': True, 'custom': custom,
                 'custom_job_id': str(plan.get('custom_job_id') or ''),
                 'seconds': round(facts['seconds'], 6), 'body_frames': facts['body_frames'],
                 'sample_rate': facts['sample_rate'], 'audio_sha256': facts['sha256'],
                 'audio_name': audio_name, 'audio_bytes': facts['bytes'],
                 'generated_script': generated, 'recorded_text': recorded,
                 'campaign': campaign, 'cues': cues, 'source_plan': plan,
                 'occurrence': str(plan.get('occurrence') or ''), 'autoplay': False}
        video_source = result.get('video_path') or (source.with_name(plan['video']) if plan.get('video') else None)
        if video_source:
            from sfx_supercut_video import video_facts, require_mp4_sources
            require_mp4_sources(plan)
            video_source = Path(video_source)
            video = video_facts(video_source, seconds=facts['seconds'])
            if result.get('video_sha256') and result['video_sha256'] != video['video_sha256']:
                raise ValueError('The rendered Super Cut MP4 changed before archival')
            value.update(video, kind='video', video_source_only=True,
                         video_name='supercut-' + identifier[4:] + '.mp4')
        with self.lock:
            with self.connection() as con:
                existing = con.execute('select * from archive where id=?', (identifier,)).fetchone()
                if existing:
                    value = self.decorate(existing)
                _atomic_copy(source, self.ads_dir / audio_name, facts['sha256'])
                if video_source:
                    _atomic_copy(video_source, self.ads_dir / value['video_name'], value['video_sha256'])
                metadata = {k: v for k, v in value.items() if k not in ('audio_url', 'reusable_ad_id', 'video_url')}
                _atomic_text(self.root / (identifier + '.json'), json.dumps(metadata, ensure_ascii=False, indent=1))
                _atomic_text(self.root / (identifier + '.script.txt'), metadata['generated_script'])
                _atomic_text(self.root / (identifier + '.transcript.txt'), metadata['recorded_text'])
                con.execute('insert into archive(id,plan_id,created_at,product,station,audio_name,sha256,metadata) '
                            'values(?,?,?,?,?,?,?,?) on conflict(id) do update set metadata=excluded.metadata',
                            (identifier, pid, metadata['created_at'], item, metadata['station'], audio_name,
                             facts['sha256'], json.dumps(metadata, ensure_ascii=False)))
                row = con.execute('select * from archive where id=?', (identifier,)).fetchone()
                result_row = self.decorate(row)
            # Put the exact measured audio in the existing SFX ads book. This
            # supplies library availability without queueing a delivery or replay.
            register = self.host.get('sfx_db_write_row')
            if callable(register):
                result_row['sfx_registered'] = bool(register(self.ads_dir / audio_name, facts['seconds'], playable=1))
        return result_row

    def list(self, *, limit=24, offset=0, query='', summary=False):
        limit = max(1, min(100, int(limit)))
        offset = max(0, min(1000000, int(offset)))
        query = str(query or '').strip()[:200]
        if not self.db_path.is_file():
            return {'ok': True, 'rows': [], 'total': 0, 'limit': limit, 'offset': offset, 'has_more': False}
        where, args = ('where product like ? or station like ?', ('%' + query + '%', '%' + query + '%')) if query else ('', ())
        with self.connection() as con:
            total = con.execute('select count(*) from archive ' + where, args).fetchone()[0]
            rows = con.execute('select * from archive ' + where + ' order by created_at desc,id desc limit ? offset ?',
                               (*args, limit, offset)).fetchall()
        views = [self.decorate(row) for row in rows]
        if summary:
            for row in views:
                for key in ('source_plan','cues','generated_script','recorded_text'):
                    row.pop(key, None)
                row['campaign'] = {k:v for k,v in row['campaign'].items() if k not in
                    ('script','system_prompt','generation_prompt')}
        return {'ok': True, 'rows': views, 'total': total,
                'limit': limit, 'offset': offset, 'has_more': offset + len(rows) < total}

    def detail(self, identifier):
        identifier = self.identity(identifier)
        if not self.db_path.is_file():
            raise FileNotFoundError('No such archived Super Cut')
        with self.connection() as con:
            row = con.execute('select * from archive where id=?', (identifier,)).fetchone()
        if row is None:
            raise FileNotFoundError('No such archived Super Cut')
        return self.decorate(row)

    def audio(self, identifier):
        row = self.detail(identifier)
        path = self.ads_dir / row['audio_name']
        facts = audio_facts(path, custom=bool(row.get('custom')))
        if facts['sha256'] != row['audio_sha256']:
            raise ValueError('The archived Super Cut audio changed')
        return path

    def video(self, identifier):
        row = self.detail(identifier)
        name = row.get('video_name') or ''
        if not re.fullmatch(r'supercut-[a-f0-9]{24}\.mp4', name):
            raise ValueError('This historical archive has no MP4 video')
        path = self.ads_dir / name
        from sfx_supercut_video import video_facts
        facts = video_facts(path, seconds=row['seconds'])
        if facts['video_sha256'] != row.get('video_sha256'):
            raise ValueError('The archived Super Cut MP4 changed')
        return path

    def reuse(self, identifier):
        identifier = self.identity(identifier)
        with self.lock:
            row = self.detail(identifier)
            source = self.audio(identifier)
            ad_list, ad_save = self.host.get('ad_list'), self.host.get('ad_save')
            if not callable(ad_list) or not callable(ad_save) or not self.host.get('PRODUCED_ADS_DIR'):
                raise ValueError('The native reusable ad library is unavailable')
            existing = next((ad for ad in ad_list() if ad.get('supercut_archive_id') == identifier), None)
            destination = Path(self.host['PRODUCED_ADS_DIR'])
            destination.mkdir(parents=True, exist_ok=True)
            name = hashlib.sha256(('supercut-ad:' + identifier).encode()).hexdigest()[:32] + '.wav'
            _atomic_copy(source, destination / name, row['audio_sha256'])
            video_extra = {}
            if row.get('video_name'):
                video_source = self.video(identifier)
                video_name = Path(name).with_suffix('.mp4').name
                _atomic_copy(video_source, destination / video_name, row['video_sha256'])
                video_extra = {'video': video_name, 'video_sha256': row['video_sha256'], 'video_source_only': True}
            if existing is None:
                existing = ad_save(row['product'], row['recorded_text'], kind='produced', extra={
                    'audio': name, 'voice': 'SFX Guy', 'seconds': row['seconds'],
                    'engine': 'sfx_supercut', 'source_only': True, 'supercut_archive_id': identifier,
                    'generated_script': row['generated_script'], 'source_plan': row['source_plan'],
                    'cues': row['cues'], 'audio_sha256': row['audio_sha256'], **video_extra})
                already = False
            else:
                already = True
            with self.connection() as con:
                con.execute('update archive set reusable_ad_id=? where id=?', (str(existing['id']), identifier))
            return {'ok': True, 'archive_id': identifier, 'ad_id': str(existing['id']),
                    'reusable': True, 'already_registered': already, 'autoplay': False}

    def migrate(self, plan_root, media_root):
        """Register completed historical plans once; retain every original file."""
        marker = self.root / 'legacy-migration.json'
        if marker.is_file():
            self.migration = json.loads(marker.read_text(encoding='utf-8'))
            return dict(self.migration)
        report = {'state': 'complete', 'scanned': 0, 'archived': 0, 'skipped': 0, 'at': time.time()}
        for path in sorted(Path(plan_root).glob('sc-*.json')):
            report['scanned'] += 1
            try:
                plan = json.loads(path.read_text(encoding='utf-8'))
                clip = str(plan.get('clip') or '')
                if not re.fullmatch(r'[a-f0-9]{32}\.wav', clip) or not plan.get('rendered_at'):
                    report['skipped'] += 1
                    continue
                self.record({'ok': True, 'complete': plan.get('complete'), 'source_only': plan.get('source_only'),
                             'source_plan': plan, 'path': str(Path(media_root) / clip),
                             'seconds': plan.get('seconds'), 'cues': plan.get('cues')})
                report['archived'] += 1
            except (OSError, ValueError, TypeError, sqlite3.Error, wave.Error):
                report['skipped'] += 1
        self.root.mkdir(parents=True, exist_ok=True)
        _atomic_text(marker, json.dumps(report, indent=1))
        self.migration = report
        return dict(report)
