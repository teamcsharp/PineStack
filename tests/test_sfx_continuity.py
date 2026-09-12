"""Emergency host replies use the same recorded cadence and audible receipts."""
import copy
import io
import math
import struct
import unittest
import wave
from unittest import mock

import app
import test_continuity as fixture
from sfx_cadence import SfxCadence


def wav_bytes(frequency, seconds=0.5):
    frames = b''.join(struct.pack('<h', round(7000 * math.sin(i * frequency * 2 * math.pi / 24000)))
                      for i in range(round(seconds * 24000)))
    output = io.BytesIO()
    with wave.open(output, 'wb') as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(24000)
        handle.writeframes(frames)
    return output.getvalue(), frames


class SfxContinuityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixture.ContinuityTests.setUp(self)
        fixture.ContinuityTests.seed(self)
        def patch(name, value):
            return self.stack.enter_context(mock.patch.object(app, name, value))
        self.patch = patch
        self.saved = []
        self.host_frames = []
        for who, frequency in [('dj', 220), ('cohost', 440)]:
            audio, frames = wav_bytes(frequency)
            (self.root / (who + '.wav')).write_bytes(audio)
            self.host_frames.append(frames)
        sample, self.sample_frames = wav_bytes(880)
        self.sample = self.root / 'sample.wav'; self.sample.write_bytes(sample)
        guy, self.guy_frames = wav_bytes(660)
        (self.root / 'guy.wav').write_bytes(guy)
        self.settings = {**app.DEFAULT_DJ, 'sfx': True, 'sfx_every_units': 2,
            'sfxguy_every_units': 4, 'sfxguy_rate': 100, 'drop_voice': 'guy'}
        def store(audio, ext='wav'):
            self.saved.append(audio)
            (self.root / 'assembled.wav').write_bytes(audio)
            return {'path': '/media/assembled.wav', 'sig': 'assembled'}
        async def box(path, sig, **kwargs):
            app._LAST_PLAYOUT.update(key=app._played_out_key(path), ok=True, audible_gain=1,
                                    intentional_mute=False, at=app.time.time())
            return path
        for name, value in {
            'dj_settings': mock.Mock(return_value=self.settings),
            '_SFX_CADENCE': SfxCadence(self.root / 'cadence.sqlite3'),
            '_SFX_CADENCE_STATUS': {'sample_due': 0, 'sample_omitted': 0, 'guy_due': 0,
                                    'guy_omitted': 0, 'last_sample': ''},
            '_sfx_cadence_pick': mock.Mock(return_value=self.sample),
            'sfx_seconds': mock.Mock(return_value=.5), 'sfx_id': mock.Mock(return_value='sample'),
            'sfxguy_ready_pick': mock.Mock(return_value=None), 'sfxguy_ready_commit': mock.Mock(),
            'sfxguy_ready_release': mock.Mock(), 'sfx_note_play': mock.Mock(),
            '_store_media': mock.Mock(side_effect=store), '_play_on_box': mock.AsyncMock(side_effect=box),
            '_PAGE_ACKED_LINES': set(), '_PAGE_DELIVERIES': {}, '_PAGE_ACK_EVENTS': [],
            '_PAGE_AIR_UNTIL': [0], 'page_reservation_repair': mock.Mock(return_value=[]),
            'page_clip_seconds': mock.Mock(return_value=2), 'page_recovery_read': mock.Mock(return_value=[]),
            'listener_note': mock.Mock(), 'air_remember': mock.Mock(), 'render_backlog_ack': mock.Mock(),
            'station_flow_event': mock.Mock(), 'box_hold': mock.Mock(), 'pipeline_log': mock.Mock(),
            'prep_render_line': mock.AsyncMock(side_effect=AssertionError('live TTS')),
            'ask_model': mock.AsyncMock(side_effect=AssertionError('live writing')),
            'crystal_tint': mock.AsyncMock(side_effect=AssertionError('live tint')),
        }.items(): patch(name, value)

    def guy(self):
        app.sfxguy_ready_pick.return_value = {'id': 'reserved-guy', 'entry_id': 'guy-entry',
            'text': 'Keep talking in time; I am hearing the rhyme.', 'voice': 'guy', 'who': 'drop',
            'seconds': .5, 'clip': {'path': '/media/guy.wav'}}

    async def test_actual_ffmpeg_keeps_core_pcm_exact_and_appends_every_second_host_sample(self):
        debt = copy.deepcopy(self.debt)
        self.assertTrue(await app.continuity_air('Original strict work is still owed'))
        with wave.open(io.BytesIO(self.saved[-1]), 'rb') as handle:
            result = handle.readframes(handle.getnframes())
        self.assertEqual(result, self.host_frames[0] + self.host_frames[1] + self.sample_frames)
        self.assertEqual([r['who'] for r in self.radio['chat']], ['dj', 'cohost', 'board'])
        self.assertEqual([(r['from'], r['until']) for r in self.radio['chat']], [(0, .5), (.5, 1), (1, 1.5)])
        self.assertEqual(app._SFX_CADENCE.state(), {'heard_units': 2, 'heard_samples': 1})
        self.assertEqual(self.debt, debt)
        self.assertTrue(all(not r['coverage_credit'] for r in self.radio['chat']))
        self.assertFalse(await app.continuity_air('The60s guard still applies'))
        self.assertEqual(app._play_on_box.await_count, 1)
        app.prep_render_line.assert_not_awaited(); app.ask_model.assert_not_awaited()

    async def test_recorded_guy_at_fourth_unit_and_page_box_deduplicate(self):
        app._SFX_CADENCE.record([{'id': 'prior-a', 'units': 1}, {'id': 'prior-b', 'units': 1}])
        self.guy(); self.radio['voice_to'] = 'both'
        self.assertTrue(await app.continuity_air('Reserve'))
        rows = self.radio['chat']
        self.assertEqual([r['who'] for r in rows], ['dj', 'cohost', 'board', 'drop'])
        self.assertEqual(rows[-1]['voice'], 'guy')
        app.sfxguy_ready_commit.assert_called_once_with('reserved-guy')
        delivery = self.radio['voice_clips'][0]['delivery_id']
        for seq, (event, at) in enumerate([('playing', .1), ('playing', .6), ('playing', 1.1),
                                          ('playing', 1.6), ('ended', 2)], 1):
            app.page_playback_ack({'delivery_id': delivery, 'listener_id': 'test-listener',
                'event': event, 'current_time': at, 'sequence': seq, 'volume': .5, 'audible_volume': .5})
        self.assertEqual(app._SFX_CADENCE.state(), {'heard_units': 4, 'heard_samples': 1})
        app.sfxguy_ready_commit.assert_called_once()

    async def test_failed_optional_decode_keeps_both_originals_and_releases_guy(self):
        app._SFX_CADENCE.record([{'id': 'a', 'units': 1}, {'id': 'b', 'units': 1}])
        self.guy(); (self.root / 'guy.wav').unlink(); self.sample.unlink()
        self.assertTrue(await app.continuity_air('Reserve'))
        self.assertEqual([r['who'] for r in self.radio['chat']], ['dj', 'cohost'])
        with wave.open(io.BytesIO(self.saved[-1]), 'rb') as handle:
            self.assertEqual(handle.readframes(handle.getnframes()), b''.join(self.host_frames))
        app.sfxguy_ready_release.assert_called_once_with('reserved-guy')
        app.sfxguy_ready_commit.assert_not_called()

    async def test_pause_during_optional_assembly_refuses_and_releases_without_air(self):
        app._SFX_CADENCE.record([{'id': 'a', 'units': 1}, {'id': 'b', 'units': 1}]); self.guy()
        original = app._continuity_sfx_build
        def assemble(*args):
            out = original(*args); app.radio_paused.return_value = True; return out
        self.patch('_continuity_sfx_build', mock.Mock(side_effect=assemble))
        self.assertFalse(await app.continuity_air('Pause during assembly'))
        app._play_on_box.assert_not_awaited()
        app.sfxguy_ready_release.assert_called_once_with('reserved-guy')
        app.sfxguy_ready_commit.assert_not_called()

    async def test_muted_handoff_has_no_audible_credit_or_fake_held_failure(self):
        async def box(path, sig):
            app._LAST_PLAYOUT.update(key=app._played_out_key(path), ok=True,
                intentional_mute=True, audible_gain=0)
            return path
        app._play_on_box.side_effect = box
        self.assertTrue(await app.continuity_air('Operator muted'))
        self.assertEqual(app._SFX_CADENCE.state()['heard_units'], 0)
        app.air_remember.assert_not_called(); app.talk_said_now.assert_not_called()
        app.box_hold.assert_not_called()
        self.assertTrue(all(r['aired'] == 'muted' for r in self.radio['chat']))

    async def test_failed_box_saves_exact_rows_media_and_duration_for_normal_hold_replay(self):
        app._play_on_box.side_effect = None; app._play_on_box.return_value = ''
        self.assertTrue(await app.continuity_air('Device unavailable'))  # normal page rescue
        app.box_hold.assert_called_once()
        kwargs = app.box_hold.call_args.kwargs
        self.assertEqual([r['who'] for r in kwargs['rows']], ['dj', 'cohost', 'board'])
        self.assertEqual(kwargs['length'], 1.5)
        self.assertEqual(app._SFX_CADENCE.state()['heard_units'], 0)

    async def test_long_original_pair_keeps_its_full_audio_and_omits_optional_media(self):
        for who, frequency in [('dj', 220), ('cohost', 440)]:
            audio, _ = wav_bytes(frequency, 15)
            (self.root / (who + '.wav')).write_bytes(audio)
        self.patch('_continuity_sfx_build', mock.Mock(side_effect=AssertionError('no optional assembly needed')))
        self.assertTrue(await app.continuity_air('Long original pair'))
        self.assertEqual([r['who'] for r in self.radio['chat']], ['dj', 'cohost'])
        self.assertEqual(self.radio['chat'][-1]['until'], 30)
        self.assertEqual(app._SFX_CADENCE_STATUS['sample_omitted'], 1)
        app._continuity_sfx_build.assert_not_called()

    async def test_off_air_change_during_assembly_prevents_publication(self):
        original = app._continuity_sfx_build
        def assemble(*args):
            out = original(*args); self.radio['on'] = False; return out
        self.patch('_continuity_sfx_build', mock.Mock(side_effect=assemble))
        self.assertFalse(await app.continuity_air('Stopped during assembly'))
        app._play_on_box.assert_not_awaited()
        self.assertEqual(self.radio['chat'], [])


if __name__ == '__main__':
    unittest.main()
