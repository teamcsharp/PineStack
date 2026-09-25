"""Real strict-stream plumbing with prepared-only, receipt-counted punctuation."""
import copy
import unittest
from pathlib import Path
from unittest import mock

import app
import test_ready_stream_playback as fixture
from sfx_cadence import SfxCadence


class SfxStreamCadenceTests(unittest.IsolatedAsyncioTestCase):
    patch = fixture.ReadyStreamPlaybackTests.patch
    play = fixture.ReadyStreamPlaybackTests.play
    ack = fixture.ReadyStreamPlaybackTests.ack

    def setUp(self):
        fixture.ReadyStreamPlaybackTests.setUp(self)
        self.patch('_SFX_CADENCE', SfxCadence(self.root / 'cadence.sqlite3'))
        self.patch('_SFX_CADENCE_STATUS', {'sample_due': 0, 'sample_omitted': 0,
                    'guy_due': 0, 'guy_omitted': 0, 'last_sample': ''})
        app.dj_settings.return_value.update(sfx=True, sfx_every_units=2,
                    sfxguy_every_units=4, sfxguy_rate=100)
        self.sample = self.root / 'scratch.wav'
        self.sample.write_bytes(b'existing sample')
        self.patch('_sfx_cadence_pick', mock.Mock(return_value=self.sample))
        self.patch('_sfx_cadence_video_pick', mock.Mock(return_value=None))
        self.patch('sfx_levelled', mock.Mock(side_effect=lambda path: path))
        self.patch('complaint_due', mock.Mock(return_value=False))
        self.patch('sfx_seconds', mock.Mock(return_value=1.0))
        self.patch('sfx_id', mock.Mock(return_value='scratch-id'))
        self.patch('sfx_by_id', mock.Mock(side_effect=lambda _sid: self.sample))
        self.patch('sfx_note_play', mock.Mock())
        self.patch('sfx_history_add', mock.Mock())
        self.patch('note_activity', mock.Mock())
        self.patch('sfxguy_ready_pick', mock.Mock(return_value=None))
        self.patch('sfxguy_ready_commit', mock.Mock())
        self.patch('sfxguy_ready_release', mock.Mock())
        self.add_host()
        app._clip_seconds.side_effect = lambda path: 14.0 if 'joined' in str(path) else 3.0
        app.page_clip_seconds.return_value = 14.0

    def add_host(self):
        take = copy.deepcopy(self.takes[1])
        take.update(i=len(self.takes), text='The frame returns the copper gleam.')
        self.takes.append(take)

    def bank_take(self):
        (self.root / 'guy.wav').write_bytes(b'actual prepared guy')
        take = {'id': 'reserved-guy', 'entry_id': 'guy-source', 'text': 'I hear that frame; I share the claim.',
                'voice': 'drop-test', 'who': 'drop', 'seconds': 2.0,
                'key': 'prepared-guy', 'clip': {'path': '/media/guy.wav'}}
        app.sfxguy_ready_pick.return_value = take
        app._clip_seconds.side_effect = lambda path: 16.0 if 'joined' in str(path) else 3.0
        app.page_clip_seconds.return_value = 16.0
        return take

    async def test_every_other_host_exact_clip_order_and_separate_road_credit(self):
        original = copy.deepcopy(self.takes)
        await self.play()
        self.assertEqual(self.takes, original)
        paths = app._call_concat_blocking.call_args.args[0]
        self.assertEqual([Path(p).name for p in paths],
                         ['take-0.wav', 'take-1.wav', 'scratch.wav', 'take-2.wav', 'take-1.wav', 'scratch.wav'])
        rows = self.radio['voice_clips'][0]['stream']['rows']
        self.assertEqual([r['who'] for r in rows], ['dj', 'cohost', 'board', 'dj', 'cohost', 'board'])
        self.assertEqual([r['kind'] for r in rows], ['gallery', 'gallery', 'sfx', 'gallery', 'gallery', 'sfx'])
        self.assertEqual([r['text'] for r in rows if r['who'] != 'board'], [t['text'] for t in original])
        self.assertEqual(app._SFX_CADENCE.state(), {'heard_units': 0, 'heard_samples': 0})
        self.ack('received', 14, 1)
        self.ack('playing', 14, 2, volume=0)
        self.assertEqual(app._SFX_CADENCE.state()['heard_units'], 0)
        self.ack('playing', 0.2, 3)
        self.assertEqual(app._SFX_CADENCE.state()['heard_units'], 0)
        self.ack('playing', 3.1, 4)
        self.assertEqual(app._SFX_CADENCE.state()['heard_units'], 1)
        self.ack('playing', 6.1, 5)
        self.ack('playing', 7.1, 6)
        self.ack('playing', 10.1, 7)
        self.ack('playing', 13.1, 8)
        self.ack('ended', 14, 9)
        self.assertEqual(app._SFX_CADENCE.state(), {'heard_units': 4, 'heard_samples': 2})
        app.speakbox_remember.assert_called_once()
        app._sfx_cadence_audible(rows, 14)  # the same complete hardware copy
        self.assertEqual(app._SFX_CADENCE.state()['heard_units'], 4)
        self.assertEqual(app.sfx_note_play.call_count, 2)
        self.assertEqual(app.sfx_history_add.call_count, 2)
        app.sfx_history_add.assert_called_with(self.sample, 'board')
        receipts = [call for call in app.note_activity.call_args_list
                    if call.args and call.args[0] == 'sfx']
        self.assertEqual(len(receipts), 2)
        self.assertTrue(all(call.kwargs['speaker'] == 'The SFX Guy'
                            for call in receipts))
        self.assertEqual(app.sfx_levelled.call_count, 2)

    async def test_video_cadence_welds_levelled_audio_and_rings_silent_picture(self):
        app.dj_settings.return_value['sfx_video_share'] = 100
        video = self.root / 'sample.mp4'
        levelled = self.root / 'levelled.wav'
        video.write_bytes(b'picture')
        levelled.write_bytes(b'levelled audio')
        app._sfx_cadence_video_pick.return_value = (video, levelled, 2.0, 'matched line')
        pictures = self.patch('page_picture_append', mock.Mock(return_value={}))
        await self.play()
        paths = app._call_concat_blocking.call_args.args[0]
        self.assertEqual(sum(Path(path).name == 'levelled.wav' for path in paths), 2)
        rows = self.radio['voice_clips'][0]['stream']['rows']
        board = [row for row in rows if row['who'] == 'board']
        self.assertEqual(len(board), 2)
        self.assertTrue(all(row['sfx_video_id'] == 'scratch-id' for row in board))
        self.assertEqual(pictures.call_count, 2)
        for call in pictures.call_args_list:
            self.assertTrue(call.args[0]['silent_picture'])
            self.assertGreater(call.kwargs['at_ms'], 0)

    async def test_prepared_guy_keeps_own_voice_and_commits_only_audible_completion(self):
        take = self.bank_take()
        await self.play()
        rows = self.radio['voice_clips'][0]['stream']['rows']
        self.assertEqual(rows[-1]['who'], 'drop')
        self.assertEqual(rows[-1]['kind'], 'sfxguy')
        self.assertEqual(rows[-1]['voice'], take['voice'])
        self.assertEqual(rows[-1]['text'], take['text'])
        app.sfxguy_ready_commit.assert_not_called()
        self.ack('playing', 0.2, 1)
        self.ack('ended', 16, 2)
        app.sfxguy_ready_commit.assert_called_once_with('reserved-guy')
        app.note_activity.assert_any_call(
            'sfxguy', 'interjection heard', line=mock.ANY,
            text=take['text'], speaker='The SFX Guy')
        app._sfx_cadence_audible(rows, 16)
        app.sfxguy_ready_commit.assert_called_once()

    async def test_full_core_budget_wins_over_optional_insertions(self):
        self.bank_take()
        self.patch('_ready_round_fits', mock.Mock(side_effect=lambda *a, **kw: float(kw.get('seconds') or 0) <= 13))
        app._clip_seconds.side_effect = lambda path: 12.0 if 'joined' in str(path) else 3.0
        app.page_clip_seconds.return_value = 12.0
        self.assertTrue(await self.play())
        self.assertEqual([r['text'] for r in self.radio['voice_clips'][0]['stream']['rows']],
                         [t['text'] for t in self.takes])
        self.assertEqual(app._SFX_CADENCE_STATUS['sample_omitted'], 2)
        app.sfxguy_ready_release.assert_called_once_with('reserved-guy')

    async def test_concat_failure_releases_unheard_guy_and_keeps_stock(self):
        self.bank_take()
        app._call_concat_blocking.return_value = None
        self.assertEqual(await self.play(), [])
        self.handoff.assert_not_called()
        app.sfxguy_ready_release.assert_called_once_with('reserved-guy')
        app.sfxguy_ready_commit.assert_not_called()
        self.assertEqual(app._SFX_CADENCE.state()['heard_units'], 0)

    async def test_late_pause_releases_reserved_optional_take(self):
        self.bank_take()
        def concat(*args):
            app.radio_paused.return_value = True
            return b'joined'
        app._call_concat_blocking.side_effect = concat
        self.assertEqual(await self.play(), [])
        self.handoff.assert_not_called()
        app.sfxguy_ready_release.assert_called_once_with('reserved-guy')

    async def test_caller_and_drop_do_not_spend_host_cadence(self):
        self.assertEqual(await app._sfx_cadence_additions('caller', 'caller words', 1, 20), [])
        self.assertEqual(await app._sfx_cadence_additions('drop', 'guy words', 1, 20), [])
        app._sfx_cadence_pick.assert_not_called()
        app.sfxguy_ready_pick.assert_not_called()

    async def test_partial_audible_unit_advances_next_programme_without_credit_for_failed_tail(self):
        app._sfx_cadence_audible([{'id': 'earlier', 'who': 'dj', 'from': 0, 'until': 3},
                                {'id': 'unheard-tail', 'who': 'cohost', 'from': 3, 'until': 6}], 3.1)
        await self.play()
        rows = self.radio['voice_clips'][0]['stream']['rows']
        self.assertEqual([r['who'] for r in rows][:2], ['dj', 'board'])
        self.assertEqual(app._SFX_CADENCE.state()['heard_units'], 1)

    async def test_position_jump_does_not_credit_skipped_or_muted_middle(self):
        rows = [{'id': 'skipped', 'who': 'dj', 'from': 0, 'until': 3},
                {'id': 'skipped-guy', 'who': 'drop', 'from': 3, 'until': 5,
                 'sfxguy_reservation': 'unheard'},
                {'id': 'heard-tail', 'who': 'cohost', 'from': 10, 'until': 13}]
        app._sfx_cadence_audible(rows, 13, previous=10)
        self.assertEqual(app._SFX_CADENCE.state()['heard_units'], 1)
        app.sfxguy_ready_commit.assert_not_called()

    async def test_bad_optional_sample_cannot_discard_original_accepted_dialogue(self):
        app._sfx_cadence_pick.side_effect = OSError('sample share unavailable')
        app._clip_seconds.side_effect = lambda path: 12.0 if 'joined' in str(path) else 3.0
        self.assertTrue(await self.play())
        self.assertEqual([r['text'] for r in self.radio['voice_clips'][0]['stream']['rows']],
                         [t['text'] for t in self.takes])

    async def test_late_optional_overrun_rejoins_exact_core_once_without_tts(self):
        self.bank_take()
        joins = []
        def concat(paths, *args):
            joins.append([Path(p).name for p in paths])
            return b'joined'
        app._call_concat_blocking.side_effect = concat
        self.patch('_ready_round_fits', mock.Mock(side_effect=lambda *a, **kw:
            not joins or float(kw.get('seconds') or 0) <= 13))
        app._clip_seconds.side_effect = lambda path: (20.0 if len(joins) == 1 else 12.0) if 'joined' in str(path) else 3.0
        app.page_clip_seconds.return_value = 12
        self.assertTrue(await self.play())
        self.assertEqual(len(joins), 2)
        self.assertIn('scratch.wav', joins[0])
        self.assertIn('guy.wav', joins[0])
        self.assertEqual(joins[1], ['take-0.wav', 'take-1.wav', 'take-2.wav', 'take-1.wav'])
        self.assertEqual([r['text'] for r in self.radio['voice_clips'][0]['stream']['rows']],
                         [t['text'] for t in self.takes])
        app.sfxguy_ready_release.assert_called_once_with('reserved-guy')
        app.sfxguy_ready_commit.assert_not_called()

    async def test_user_muted_box_consumes_handoff_without_audible_or_source_credit(self):
        self.bank_take()
        self.radio['voice_to'] = 'box'
        async def box(path, sig, **kwargs):
            app._LAST_PLAYOUT.update(key=app._played_out_key(path), ok=True,
                                    intentional_mute=True, audible_gain=0.0)
            return 'accepted intentional silence'
        app._play_on_box.side_effect = box
        self.assertTrue(await self.play())
        self.handoff.assert_called_once()
        self.assertEqual(app._BOX_HOLD, [])
        self.assertEqual(app._SFX_CADENCE.state(), {'heard_units': 0, 'heard_samples': 0})
        app.sfxguy_ready_commit.assert_not_called()
        app.air_remember.assert_not_called()
        app.speakbox_remember.assert_not_called()
        app.talk_said_now.assert_not_called()
        self.assertTrue(all(r['aired'] == 'muted' for r in self.radio['chat']))

    async def test_audible_page_counts_once_even_when_simultaneous_box_was_muted(self):
        self.bank_take()
        self.radio.update(voice_to='both', monitor=True)
        async def box(path, sig, **kwargs):
            app._LAST_PLAYOUT.update(key=app._played_out_key(path), ok=True,
                                    intentional_mute=True, audible_gain=0.0)
            return 'accepted intentional silence'
        app._play_on_box.side_effect = box
        await self.play()
        self.ack('playing', 0.2, 1)
        for sequence, position in enumerate([3.1, 6.1, 7.1, 10.1, 13.1, 14.1], 2):
            self.ack('playing', position, sequence)
        self.ack('ended', 16, 8)
        self.assertEqual(app._SFX_CADENCE.state(), {'heard_units': 4, 'heard_samples': 2})
        app.sfxguy_ready_commit.assert_called_once_with('reserved-guy')
        app.speakbox_remember.assert_called_once()

    async def test_dispatch_snapshot_wins_over_later_slider_or_missing_mute_boolean(self):
        self.assertFalse(app._box_receipt_audible({'audible_gain': 0.0}))
        self.assertFalse(app._box_receipt_audible({'audible_gain': 1.0, 'intentional_mute': True}))
        app.dj_settings.return_value['nabu_voice_level'] = 0
        self.assertTrue(app._box_receipt_audible({'audible_gain': 1.0, 'intentional_mute': False}))
        self.assertTrue(app._box_receipt_audible({}))  # unchanged older/non-Nabu receipts

    async def test_muted_held_replay_consumes_delivery_debt_without_heard_credit(self):
        self.patch('_radio_cast_signature', mock.Mock(return_value='cast'))
        rows = [{'id': 'held-host', 'who': 'dj', 'text': 'Exact held words.', 'from': 0, 'until': 3},
                {'id': 'held-guy', 'who': 'drop', 'text': 'Exact prepared rhyme.',
                 'from': 3, 'until': 5, 'sfxguy_reservation': 'held-reservation'}]
        clip = {'id': 'held-host', 'path': '/media/take-0.wav', 'sig': 'held', 'cast': 'cast',
                'rows': rows, 'length': 5, 'who': 'dj', 'text': 'Exact held words.'}
        self.radio['chat'] = [{'id': row['id'], 'aired': 'held'} for row in rows]
        async def box(path, sig, **kwargs):
            app._LAST_PLAYOUT.update(key=app._played_out_key(path), ok=True,
                at=app.time.time(), intentional_mute=True, audible_gain=0.0)
            return 'accepted intentional silence'
        app._play_on_box.side_effect = box
        self.assertTrue(await app._replay_held(clip))
        self.assertEqual(app._SFX_CADENCE.state()['heard_units'], 0)
        app.sfxguy_ready_commit.assert_not_called()
        app.air_remember.assert_not_called()
        app.talk_said_now.assert_not_called()
        self.assertEqual(app.render_backlog_ack.call_count, 2)
        self.assertTrue(all(row['aired'] == 'muted' for row in self.radio['chat']))


if __name__ == '__main__':
    unittest.main()
