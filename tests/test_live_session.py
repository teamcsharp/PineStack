"""Exercise real session files, encoder output, metadata and offline capture."""
import json
import shutil
import subprocess
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pinelive
import pinestream
from live_session import SessionRecorder, folder_name


class Stream:
    def add_tap(self, tap):
        self.tap = tap

    def remove_tap(self, tap):
        self.tap = None


class Owner:
    def __init__(self, path):
        self.data = path
        self.settings = {'silence_db': -60}
        self.carried = []
        self.controls = 0

    def armed(self):
        return False

    def host(self):
        return {'up': True}

    def write_control(self):
        self.controls += 1

    def courier_hand(self, paths, folder):
        self.carried.append((paths, folder))


class Source:
    def __init__(self, **kwargs):
        self.closed = False

    def read_frame(self):
        return (np.full(pinelive.FRAME_SAMPLES * 2, 1000, dtype='<i2').tobytes(), True)

    def close(self):
        self.closed = True


class Sessions(unittest.TestCase):
    def wait(self, recorder):
        until = time.monotonic() + 40
        while recorder.phase in ('recording', 'exporting') and time.monotonic() < until:
            time.sleep(.05)
        self.assertNotIn(recorder.phase, ('recording', 'exporting'), recorder.say)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires ffmpeg and ffprobe')
    def test_all_modes_off_air_with_animated_art_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owner, stream = Owner(root), Stream()
            cam = root / 'cam.jpg'
            cam.write_bytes(pinelive.PLACEHOLDER_JPEG)
            recorder = SessionRecorder(owner, {'STATION_STREAM': stream, 'PINELINK_FRAME': cam,
                                               'terminal_rows': lambda: {'pinetab': {'music': .5, 'voice': 0}}})
            media = root / 'source.mp4'
            recorder.ffmpeg(['-f', 'lavfi', '-i', 'color=c=blue:s=320x240:r=12', '-t', '1', '-c:v', 'libx264', media])
            art = recorder.artwork(media, True, 'crop')
            screen = pinestream.PineStream(settings=lambda: {'stream_on': False})
            screen.checkin('pinetab')
            with patch.object(pinelive, 'LiveSource', Source), patch.object(pinelive.PL, 'session', recorder, create=True), patch.object(pinestream, 'PS', screen):
                ans = recorder.start(dict(album='Live Album', artist='Test Artist', modes=['mix', 'station', 'cam', 'screen'], art=art['art'], burn=True))
                self.assertTrue(ans['ok'], ans)
                self.assertTrue(screen.choice()['on'])
                screen.accept('pinetab', pinelive.PLACEHOLDER_JPEG)
                self.assertFalse(screen.viewer(True)['show'], 'local capture must not enable public display')
                info = {'bed': np.zeros(pinelive.FRAME_SAMPLES * 2),
                        'voice': np.full(pinelive.FRAME_SAMPLES * 2, 2000), 'sfx': False}
                for _ in range(20):
                    recorder.tap(pinelive.SILENCE, None, info)
                self.assertTrue(recorder.stop()['ok'])
                self.wait(recorder)
                self.assertEqual(recorder.phase, 'complete', recorder.say)
                self.assertFalse(screen.choice()['on'])
            self.assertEqual(set(recorder.files), {'mix.mp3', 'station.mp3', 'cam.mp4', 'screen.mp4', 'art-track.mp4'})
            with wave.open(str(recorder.folder / 'mix.wav')) as wav:
                self.assertEqual(wav.getnframes(), 20 * pinelive.FRAME_SAMPLES)
                self.assertEqual(np.frombuffer(wav.readframes(1), dtype='<i2')[0], 1000)
            with wave.open(str(recorder.folder / 'screen-audio.wav')) as wav:
                screen_sample = np.frombuffer(wav.readframes(1), dtype='<i2')[0]
            with wave.open(str(recorder.folder / 'station.wav')) as wav:
                station_sample = np.frombuffer(wav.readframes(1), dtype='<i2')[0]
            self.assertGreater(station_sample, screen_sample)
            with wave.open(str(recorder.folder / 'performance-audio.wav')) as wav:
                self.assertEqual(wav.getnframes(), 20 * pinelive.FRAME_SAMPLES)
                self.assertEqual(np.frombuffer(wav.readframes(1), dtype='<i2')[0], station_sample)
            for name in recorder.files:
                data = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(recorder.folder / name)]))
                self.assertEqual(data['format']['tags']['album'], 'Live Album')
                self.assertEqual(data['format']['tags']['artist'], 'Test Artist')
                if name.endswith('.mp4'):
                    self.assertTrue(any(s['codec_type'] == 'audio' for s in data['streams']))
                    self.assertTrue(any(s['codec_type'] == 'video' for s in data['streams']))
                    audio = next(s for s in data['streams'] if s['codec_type'] == 'audio')
                    video = next(s for s in data['streams'] if s['codec_type'] == 'video')
                    self.assertLess(abs(float(audio.get('start_time', 0)) - float(video.get('start_time', 0))), .05)
                    self.assertLess(abs(float(audio['duration']) - float(video['duration'])), .15)
            self.assertIn('Live Album\\', owner.carried[0][1])
            self.assertEqual(json.loads((recorder.folder / 'session.json').read_text())['phase'], 'complete')

    def test_export_failure_keeps_wav_and_reports_error(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(pinelive, 'LiveSource', Source):
            owner, stream = Owner(Path(temp)), Stream()
            recorder = SessionRecorder(owner, {'STATION_STREAM': stream})
            self.assertTrue(recorder.start(dict(album='Keep master', artist='Artist', modes=['mix']))['ok'])
            with patch.object(recorder, 'ffmpeg', side_effect=ValueError('Encoder unavailable')):
                recorder.tap(pinelive.SILENCE, None, {})
                recorder.stop()
                self.wait(recorder)
            self.assertEqual(recorder.phase, 'error')
            self.assertIn('Encoder unavailable', recorder.say)
            with wave.open(str(recorder.folder / 'mix.wav')) as wav:
                self.assertEqual(wav.getnframes(), pinelive.FRAME_SAMPLES)
            self.assertIsNone(stream.tap)

    def test_validation_and_folder_names(self):
        self.assertEqual(folder_name('A/B: C'), 'A_B_ C')
        for name in ('', '...', 'CON', 'NUL.txt'):
            with self.assertRaises(ValueError):
                folder_name(name)
        with tempfile.TemporaryDirectory() as temp:
            recorder = SessionRecorder(Owner(Path(temp)), {'STATION_STREAM': Stream()})
            for body in ({}, {'album': 'Album', 'artist': 'Artist', 'modes': []},
                         {'album': 'Album', 'artist': 'Artist', 'modes': ['unknown']},
                         {'album': 'Album', 'artist': 'Artist', 'modes': ['mix'], 'art': '../wrong'}):
                self.assertFalse(recorder.start(body)['ok'])

    def test_signed_downloads_and_station_art_resolution(self):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient
        from live_session import install
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owner = Owner(root)
            owner.sign = lambda key: 'signed-' + key
            owner.sig_ok = lambda key, token: token == owner.sign(key)
            def auth(key):
                if key != 'Bearer test':
                    raise HTTPException(401, 'key required')
            source = root / 'clip.mp4'
            source.write_bytes(b'clip')
            app = FastAPI()
            install(app, owner, {'require_auth': auth, 'STATION_STREAM': Stream(), 'sfx_db_path_of': lambda sid: source})
            client = TestClient(app)
            recorder = owner.session
            recorder.folder = root / 'album'
            recorder.folder.mkdir()
            (recorder.folder / 'mix.mp3').write_bytes(b'encoded audio')
            recorder.files = ['mix.mp3']
            self.assertEqual(client.get('/api/pinelive/session/file?name=mix.mp3').status_code, 401)
            link = recorder.state()['downloads'][0]['url']
            self.assertEqual(client.get(link).content, b'encoded audio')
            self.assertEqual(client.get('/api/pinelive/session/file?name=../clip.mp4', headers={'Authorization': 'Bearer test'}).status_code, 404)
            self.assertEqual(client.post('/api/pinelive/session/start', json={}).status_code, 401)
            with patch.object(recorder, 'artwork', return_value={'ok': True, 'art': 'prepared'}) as prepare:
                result = client.post('/api/pinelive/session/art', json={'clip_id': 'a' * 16, 'crop': 'fit'}, headers={'Authorization': 'Bearer test'})
                self.assertEqual(result.status_code, 200, result.text)
                prepare.assert_called_once_with(source, True, 'fit')


if __name__ == '__main__':
    unittest.main()
