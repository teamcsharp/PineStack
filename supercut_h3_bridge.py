"""Verified Super Cut audio references and completed H3 source enumeration."""
from __future__ import annotations
import asyncio
import copy
import math
import time
from pathlib import Path
from threading import RLock
from typing import Any

class SupercutH3Bridge:
    def __init__(self, host):
        self.host = host
        self.source_path = host.get('workshop_source_path')
        self.reference_view = host.get('workshop_reference_view')
        self.cache, self.cache_signature = [], None
        self.lock = RLock()

    def archive(self):
        runtime = self.host.get('_sfx_supercut_runtime')
        archive = getattr(runtime, 'archive', None)
        if archive is None:
            raise ValueError('The Super Cuts archive is unavailable')
        return archive

    def resolve(self, source_type, source_id):
        if source_type == 'supercut':
            return self.archive().audio(str(source_id)), 'audio'
        if not callable(self.source_path):
            raise ValueError('The H3 reference resolver is unavailable')
        return self.source_path(source_type, source_id)

    def reference(self, row):
        if row.get('source_type') != 'supercut':
            return self.reference_view(row) if callable(self.reference_view) else {}
        ident = str(row.get('source') or '')
        try:
            archive = self.archive()
            path = archive.audio(ident)
            detail = archive.detail(ident)
            return {'available': True, 'id': ident, 'kind': 'audio', 'name': path.stem,
                    'source_type': 'supercut', 'url': detail.get('audio_url') or '',
                    'seconds': detail.get('seconds'), 'poster': ''}
        except (ValueError, FileNotFoundError, OSError) as exc:
            return {'available': False, 'id': ident, 'source_type': 'supercut', 'reason': str(exc)[:240]}

    def sources(self):
        """Metadata candidates only; request speech is never an ASR transcript."""
        reader, finder = self.host.get('_read_all_generations'), self.host.get('comfy_output_find')
        if not callable(reader) or not callable(finder):
            return []
        ledger = self.host.get('GENERATIONS_PATH')
        try:
            stat = Path(ledger).stat() if ledger else None
            signature = (stat.st_mtime_ns, stat.st_size) if stat else None
        except OSError:
            signature = None
        # A bounded age also notices removed/replaced files in an unchanged ledger.
        with self.lock:
            if self.cache_signature and self.cache_signature[0] == signature and time.monotonic() - self.cache_signature[1] < 30:
                return copy.deepcopy(self.cache)
        root = Path(self.host.get('COMFY_OUTPUT') or '/comfy-output').resolve()
        kinds = {str(k).lower() for k in (self.host.get('SFX_VIDEO_TYPES') or {'.mp4', '.webm', '.mkv', '.mov'})}
        seen, rows = set(), []
        for generation in reader():
            if not isinstance(generation, dict) or generation.get('status') != 'done':
                continue
            for filename in generation.get('files') or []:
                if not isinstance(filename, str) or Path(filename).suffix.lower() not in kinds:
                    continue
                try:
                    path = finder(filename)
                    if path is None:
                        continue
                    path = Path(path).resolve()
                    if not path.is_relative_to(root) or not path.is_file() or path.name.lower().startswith('supercut-') or path in seen:
                        continue
                    stat = path.stat()
                    sid = self.host['sfx_id'](path) if callable(self.host.get('sfx_id')) else path.stem
                    held = self.host.get('sfx_seconds_held')
                    def duration(value):
                        try:
                            seconds = float(value or 0)
                            return seconds if math.isfinite(seconds) and seconds > 0 else 0.0
                        except (ValueError, TypeError, OverflowError):
                            return 0.0
                    seconds = duration(held(path)) if callable(held) else 0.0
                    if not seconds:
                        seconds = duration(generation.get('duration_seconds') or generation.get('duration_s'))
                    if not seconds:
                        probe = self.host.get('_media_duration_probe')
                        seconds = duration(probe(path)) if callable(probe) else 0.0
                    if not seconds:
                        continue
                except (OSError, ValueError, TypeError):
                    # One expired output or malformed old receipt cannot hide the rest.
                    continue
                seen.add(path)
                requested = ' '.join(str(generation.get(k) or '') for k in ('speech', 'product', 'prompt'))[:4000]
                rows.append({'sid': str(sid), 'path': str(path), 'name': path.name,
                    'seconds': seconds, 'mtime': stat.st_mtime, 'video': True, 'said': '',
                    'candidate_text': requested, 'provenance': {'origin': 'h3', 'existing_audio_only': True,
                    'job_id': str(generation.get('prompt_id') or ''), 'requested_text_unverified': True,
                    'source_type': str(generation.get('source_type') or ''),
                    'source': str(generation.get('source') or '')}})
        with self.lock:
            self.cache, self.cache_signature = rows, (signature, time.monotonic())
        return copy.deepcopy(rows)

    def preset(self, ident, prompt, detail):
        loader = self.host.get('h3_prompts_load')
        store = loader() if callable(loader) else {}
        selected = next((p for p in store.get('presets', []) if str(p.get('id')) == str(ident)), None)
        if selected is None:
            raise ValueError('That H3 prompt preset is unavailable')
        fields_fn = self.host.get('h3_prompts_fields')
        fields = fields_fn(selected) if callable(fields_fn) else dict(selected)
        fill = self.host.get('h3_prompts_fill')
        direction = fields.get('clip') or fields.get('goal') or ''
        if callable(fill):
            direction = fill(direction, conversation=detail.get('recorded_text') or detail.get('generated_script') or '',
                             record='', goal=fields.get('goal') or '', speech='')
        brief = {k: fields[k] for k in ('audio_direction', 'constraints') if fields.get(k)}
        return {'prompt': prompt or str(direction), 'h3_brief': brief,
                'style': fields.get('style') or '', 'h3_prompts': {'id': str(ident), 'name': selected.get('name') or '',
                'preset': copy.deepcopy(selected), 'direction': str(direction), 'road': 'clip'}}

    async def render(self, ident, body):
        if not isinstance(body, dict):
            raise ValueError('Expected an object')
        archive = self.archive()
        path, detail = await asyncio.gather(asyncio.to_thread(archive.audio, ident), asyncio.to_thread(archive.detail, ident))
        prompt = str(body.get('prompt') or body.get('direction') or '').strip()[:6000]
        payload = {}
        if body.get('preset_id'):
            payload.update(await asyncio.to_thread(self.preset, body['preset_id'], prompt, detail))
        for key in ('duration_seconds', 'duration_s', 'duration_mode', 'frames', 'steps_override', 'seed', 'style', 'h3_brief', 'h3_prompts'):
            if key in body:
                payload[key] = copy.deepcopy(body[key])
        payload['prompt'] = prompt or payload.get('prompt') or ('Create a vivid station spot around this existing Super Cut: ' + str(detail.get('product') or detail.get('title') or path.stem))
        payload.update(mode='reference', source_type='supercut', source=str(ident), purpose='supercut',
                       speech='', hourly=False, air_it=body.get('air_it') is True)
        renderer = self.host.get('_comfy_workshop_render_payload')
        if not callable(renderer):
            raise ValueError('The H3 render queue is unavailable')
        result = await renderer(payload)
        return dict(result, ok=True, source={'id': str(ident), 'type': 'supercut', 'kind': 'audio',
                    'seconds': detail.get('seconds'), 'audio_sha256': detail.get('audio_sha256')},
                    source_only_input=True, autoplay=False)


def install(app: Any, host: dict[str, Any]):
    from fastapi import Header, HTTPException, Request
    globals()['Request'] = Request
    runtime = SupercutH3Bridge(host)
    host['SUPERCUT_H3_BRIDGE'] = runtime
    host['workshop_source_path'] = runtime.resolve
    host['workshop_reference_view'] = runtime.reference
    host['supercut_h3_sources'] = runtime.sources

    @app.post('/api/sfx/supercut/archive/{ident}/h3')
    async def render(ident: str, request: Request, authorization: str | None = Header(default=None)):
        host['require_auth'](authorization)
        try:
            return await runtime.render(ident, await request.json())
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)[:300]) from exc
    return runtime