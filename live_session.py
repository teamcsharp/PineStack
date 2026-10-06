"""Local PineLive album sessions, independent of the public MX Live event.

The mixer callback only queues PCM. Disk IO and exports run on a worker;
WAV masters survive an encoder failure. Video follows the audio frame clock.
"""
from __future__ import annotations

import json
import base64
import queue
import re
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import Header, HTTPException, Request


def folder_name(value):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip(' .')[:100]
    if not name or name.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL', *('COM%d' % i for i in range(1, 10)), *('LPT%d' % i for i in range(1, 10))}:
        raise ValueError('Choose an album name that can be used as a folder.')
    return name


class SessionRecorder:
    def __init__(self, owner, globals_):
        self.owner, self.g = owner, globals_
        self.lock = threading.RLock()
        self.phase = 'idle'
        self.say = ''
        self.files = []
        self.dropped = 0
        self.frames = 0
        self.options = {}
        self.folder = None
        self.source = None
        self.q = queue.Queue(maxsize=100)

    def state(self):
        with self.lock:
            return dict(phase=self.phase, say=self.say, files=list(self.files),
                        seconds=round(self.frames / 10, 1), dropped=self.dropped,
                        album=self.options.get('album', ''),
                        folder=str(self.folder or ''), modes=self.options.get('modes', []),
                        downloads=[dict(name=name, url='/api/pinelive/session/file?name=' + quote(name) + '&t=' + self.owner.sign('album-session:' + str(self.folder) + ':' + name))
                                   for name in self.files] if hasattr(self.owner, 'sign') else [])

    def screen_wanted(self):
        return self.phase == 'recording' and 'screen' in self.options.get('modes', [])

    def start(self, body):
        import pinelive
        with self.lock:
            if self.phase in ('recording', 'exporting'):
                return dict(ok=False, say='A recording or export is already running.')
            try:
                album = str(body.get('album') or '').strip()[:200]
                artist = str(body.get('artist') or '').strip()[:200]
                name = folder_name(album)
                if not artist:
                    raise ValueError('Enter an artist name.')
                modes = body.get('modes')
                if not isinstance(modes, list) or not modes or any(m not in ('mix', 'station', 'cam', 'screen') for m in modes):
                    raise ValueError('Choose at least one capture.')
                stream = self.g.get('STATION_STREAM')
                if stream is None or not hasattr(stream, 'add_tap'):
                    raise ValueError('The station mixer is unavailable.')
                if 'screen' in modes:
                    import pinestream
                    available = pinestream.PS.sources().get('pinetab', {})
                    if not available.get('ok'):
                        raise ValueError(available.get('why') or 'Open and wake the PineTab first.')
                    if pinestream.PS.choice()['on'] and pinestream.PS.choice()['source'] != 'pinetab':
                        raise ValueError('Select PineTab as the PineStream source before recording its screen.')
                if 'cam' in modes and self.camera() is None:
                    raise ValueError('The PineCam has no fresh display frame. Turn on the camera first.')
                art = str(body.get('art') or '')
                if art and not re.fullmatch(r'[a-f0-9]{24}', art):
                    raise ValueError('Choose the artwork again.')
                art_dir = self.owner.data / 'session-art' / art
                if art and not (art_dir / 'cover.jpg').is_file():
                    raise ValueError('The artwork is no longer available.')
                if body.get('burn') and not art:
                    raise ValueError('Choose artwork for the album art video.')
                root = self.owner.data / 'albums' / name
                root.mkdir(parents=True, exist_ok=True)
                self.folder = root / (time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3))
                self.folder.mkdir()
                self.options = dict(album=album, artist=artist, modes=list(set(modes)),
                                    burn=bool(body.get('burn')), art=art)
                self.files, self.frames, self.dropped = [], 0, 0
                self.say = 'Recording locally'
                self.q = queue.Queue(maxsize=100)
                # Open the instrument without handing it the air. When MX Live
                # owns the source, use its already synchronized mixer frames.
                if self.owner.host().get('up'):
                    self.source = pinelive.LiveSource(silence_db=float(self.owner.settings['silence_db']))
                else:
                    self.source = None
                self.phase = 'recording'
                if self.source:
                    self.owner.write_control()
                self._manifest()
                threading.Thread(target=self._run, name='album-session', daemon=True).start()
                stream.add_tap(self.tap)
                return dict(ok=True, say=self.say, session=self.state())
            except Exception as exc:
                if self.source:
                    self.source.close()
                    self.source = None
                self.phase = 'error'
                self.say = str(exc)
                return dict(ok=False, say=self.say, session=self.state())

    def tap(self, frame, live, info):
        with self.lock:
            if self.phase != 'recording':
                return
            try:
                self.q.put_nowait((frame, live, info))
            except queue.Full:
                # Never silently shorten the album: end with an explicit error.
                self.dropped += 1
                self.phase = 'error'
                self.say = 'Disk writer fell behind; recording ended. WAV masters are kept.'

    def stop(self):
        with self.lock:
            if self.phase != 'recording':
                return dict(ok=False, say='No session is recording.', session=self.state())
            self.phase = 'exporting'
            self.say = 'Finishing album files'
        self.g['STATION_STREAM'].remove_tap(self.tap)
        return dict(ok=True, say=self.say, session=self.state())

    def camera(self):
        path = self.g.get('PINELINK_FRAME')
        if path:
            try:
                path = Path(path)
                if time.time() - path.stat().st_mtime < 5:
                    return path.read_bytes()
            except OSError:
                pass
        return None

    def _manifest(self):
        if self.folder:
            (self.folder / 'session.json').write_text(json.dumps(dict(self.state(), **self.options), indent=2), encoding='utf-8')

    def _run(self):
        import pinelive
        import station_stream as mixer
        import numpy as np
        writers, videos = {}, {}
        modes = self.options['modes']
        try:
            audio = set(modes) & {'mix', 'station'}
            if 'cam' in modes or self.options['burn']:
                audio.add('mix')
            if 'cam' in modes:
                audio.add('performance-audio')
            if 'screen' in modes:
                audio.add('screen-audio')
            for mode in audio:
                writers[mode] = pinelive._Wav(self.folder / (mode + '.wav'))
            for mode in set(modes) & {'cam', 'screen'}:
                videos[mode] = open(self.folder / (mode + '.mjpeg'), 'wb')
            while True:
                try:
                    frame, live, info = self.q.get(timeout=.25)
                except queue.Empty:
                    if self.phase != 'recording':
                        break
                    continue
                local_input = None
                if self.source:
                    local_input, _ = self.source.read_frame()
                    if live is None:
                        live = local_input
                music = live if live is not None else info.get('music', pinelive.SILENCE)
                program = frame
                bed = info.get('bed')
                if self.source and not self.owner.armed():
                    bed = np.frombuffer(music, dtype='<i2').astype(np.float64)
                    program = mixer._mixed_program(bed, info.get('voice'), info.get('sfx', False))
                screen_audio = program
                if 'screen-audio' in writers and bed is not None:
                    rows = self.g.get('terminal_rows', lambda: {})()
                    row = rows.get('pinetab') or {}
                    mix = (float(row.get('music', 1)) * 100, float(row.get('voice', 1)) * 100, float(row.get('sfx', 1)) * 100)
                    screen_audio = mixer._mixed_program(bed, info.get('voice'), info.get('sfx', False), mix)
                for mode, writer in writers.items():
                    writer.write({'mix': music, 'station': program, 'performance-audio': program, 'screen-audio': screen_audio}[mode])
                if self.frames % 5 == 0:
                    for mode, fh in videos.items():
                        if mode == 'cam':
                            image = self.camera()
                        else:
                            import pinestream
                            image, _ = pinestream.PS.frame()
                        # Missing/private sources have a dark frame, never old footage.
                        image = image or pinelive.PLACEHOLDER_JPEG
                        fh.write(image)
                self.frames += 1
                if self.frames % 100 == 0:
                    self._manifest()
                    if shutil.disk_usage(self.folder).free < 512 * 1024 * 1024:
                        raise OSError('Disk space is low; recording ended and masters are kept.')
                if self.frames >= 8 * 3600 * 10:
                    self.phase = 'exporting'
            for writer in writers.values():
                writer.close()
            writers.clear()
            for fh in videos.values():
                fh.close()
            videos.clear()
            if self.phase == 'error':
                return
            self.phase = 'exporting'
            if not self.frames:
                raise ValueError('No audio frames arrived; no recording was exported.')
            if self.source:
                self.source.close()
                self.source = None
                self.owner.write_control()
            self._export()
            self.say = 'Album exported'
        except Exception as exc:
            self.phase = 'error'
            self.say = str(exc)[:400]
        finally:
            for writer in writers.values():
                writer.close()
            for fh in videos.values():
                fh.close()
            self.g['STATION_STREAM'].remove_tap(self.tap)
            if self.source:
                self.source.close()
                self.source = None
                self.owner.write_control()
            if self.phase == 'exporting':
                self.phase = 'complete'
            self._manifest()

    def ffmpeg(self, args):
        import pinelive
        result = subprocess.run([pinelive._ffmpeg(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-threads', '2', *map(str, args)], capture_output=True, timeout=3600)
        if result.returncode:
            raise ValueError('Export failed: ' + result.stderr.decode(errors='replace')[-400:])

    def _export(self):
        meta = ['-metadata', 'album=' + self.options['album'], '-metadata', 'artist=' + self.options['artist']]
        art = self.owner.data / 'session-art' / self.options['art'] if self.options['art'] else None
        if art:
            for path in art.iterdir():
                if path.name in ('cover.jpg', 'cover.mp4'):
                    shutil.copyfile(path, self.folder / path.name)
        for wav in self.folder.glob('*.wav'):
            if wav.stem not in self.options['modes']:
                continue
            args = ['-i', wav]
            if art:
                args += ['-i', self.folder / 'cover.jpg', '-map', '0:a', '-map', '1:v', '-c:v', 'copy', '-disposition:v', 'attached_pic']
            out = wav.with_suffix('.mp3')
            self.ffmpeg(args + ['-c:a', 'libmp3lame', '-b:a', '192k', '-id3v2_version', '3', *meta, '-metadata', 'title=' + wav.stem, out])
            self.files.append(out.name)
        for mode in set(self.options['modes']) & {'cam', 'screen'}:
            out = self.folder / (mode + '.mp4')
            self.ffmpeg(['-framerate', '2', '-i', self.folder / (mode + '.mjpeg'), '-i', self.folder / ('performance-audio.wav' if mode == 'cam' else 'screen-audio.wav'), '-map', '0:v:0', '-map', '1:a:0', '-vf', 'scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2,setsar=1', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '25', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', '-movflags', '+faststart', *meta, out])
            self.files.append(out.name)
            (self.folder / (mode + '.mjpeg')).unlink()
        if art and self.options['burn']:
            visual = self.folder / ('cover.mp4' if (self.folder / 'cover.mp4').exists() else 'cover.jpg')
            loop = ['-stream_loop', '-1'] if visual.suffix == '.mp4' else ['-loop', '1']
            out = self.folder / 'art-track.mp4'
            self.ffmpeg([*loop, '-i', visual, '-i', self.folder / 'mix.wav', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '25', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', '-movflags', '+faststart', *meta, out])
            self.files.append(out.name)
        # Keep a local album even when the desk or network share is offline.
        self._manifest()
        self.owner.courier_hand(list(self.folder.glob('*.mp3')) + list(self.folder.glob('*.mp4')) + list(self.folder.glob('cover.jpg')) + [self.folder / 'session.json'], folder_name(self.options['album']) + '\\' + self.folder.name)

    def artwork(self, path, animated, crop):
        key = secrets.token_hex(12)
        target = self.owner.data / 'session-art' / key
        target.mkdir(parents=True)
        vf = ('scale=600:600:force_original_aspect_ratio=increase,crop=600:600' if crop == 'crop' else 'scale=600:600:force_original_aspect_ratio=decrease,pad=600:600:(ow-iw)/2:(oh-ih)/2') + ',setsar=1'
        self.ffmpeg(['-i', path, '-vf', vf, '-frames:v', '1', target / 'cover.jpg'])
        if animated:
            self.ffmpeg(['-i', path, '-t', '6', '-an', '-vf', vf + ',fps=12', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', target / 'cover.mp4'])
        return dict(ok=True, art=key, say='Artwork ready: 600 × 600' + (', up to 6 seconds at 12 fps' if animated else ''))


def install(app, owner, globals_):
    recorder = SessionRecorder(owner, globals_)
    owner.session = recorder

    @app.post('/api/pinelive/session/start')
    async def start(request: Request, authorization: str | None = Header(default=None)):
        globals_['require_auth'](authorization)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, 'Expected an object')
        import asyncio
        return await asyncio.to_thread(recorder.start, body)

    @app.post('/api/pinelive/session/stop')
    async def stop(authorization: str | None = Header(default=None)):
        globals_['require_auth'](authorization)
        return recorder.stop()

    @app.get('/api/pinelive/session/file')
    async def file(name: str, t: str = '', authorization: str | None = Header(default=None)):
        from fastapi.responses import FileResponse
        if name not in recorder.files or not recorder.folder:
            raise HTTPException(404, 'Album file is unavailable')
        if not owner.sig_ok('album-session:' + str(recorder.folder) + ':' + name, t):
            globals_['require_auth'](authorization)
        path = recorder.folder / name
        if not path.is_file():
            raise HTTPException(404, 'Album file is unavailable')
        return FileResponse(path, filename=name)

    @app.post('/api/pinelive/session/art')
    async def art(request: Request, animated: int = 0, crop: str = 'crop', authorization: str | None = Header(default=None)):
        globals_['require_auth'](authorization)
        import asyncio
        staging = owner.data / 'session-art'
        staging.mkdir(parents=True, exist_ok=True)
        path = staging / (secrets.token_hex(12) + '.upload')
        try:
            size = 0
            with path.open('wb') as fh:
                if 'application/json' in request.headers.get('content-type', ''):
                    body = await request.json()
                    clip = str(body.get('clip_id') or '')
                    if clip:
                        if not re.fullmatch(r'[a-f0-9]{16}', clip):
                            raise HTTPException(400, 'Invalid clip identity')
                        resolve = globals_.get('sfx_db_path_of')
                        source = await asyncio.to_thread(resolve, clip) if callable(resolve) else None
                        if source is None or not Path(source).is_file():
                            raise HTTPException(404, 'Station clip is unavailable')
                        return await asyncio.to_thread(recorder.artwork, Path(source), True, str(body.get('crop') or 'crop'))
                    encoded = str(body.get('data') or '')
                    if len(encoded) > 24 * 1024 * 1024:
                        raise HTTPException(413, 'Artwork must be under 16 MB')
                    try:
                        data = base64.b64decode(encoded, validate=True)
                    except ValueError as exc:
                        raise HTTPException(400, 'Invalid artwork data') from exc
                    animated = bool(body.get('animated'))
                    crop = str(body.get('crop') or 'crop')
                    fh.write(data)
                else:
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > 64 * 1024 * 1024:
                            raise HTTPException(413, 'Artwork must be under 64 MB')
                        fh.write(chunk)
            return await asyncio.to_thread(recorder.artwork, path, bool(animated), crop)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            path.unlink(missing_ok=True)
