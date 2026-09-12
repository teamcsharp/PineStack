import copy
from contextlib import ExitStack
import unittest
from unittest import mock

import app


class NabuMixSettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.settings = {'dj': {'box_volume': .8, 'music_box_level': .64}}
        self.radio = {'voice_device': 'nabu', 'voice_to': 'box', 'music_to': 'box',
                      'reply_to': 'box', 'box_talk': True, 'voice_clips': []}
        def save(data):
            self.settings = copy.deepcopy(data)
            return data
        for name, value in {
            '_RADIO': self.radio, '_BOX_HOLD': [], '_BOX_DOWN': {'until': 0, 'fails': 0},
            'load_settings': mock.Mock(side_effect=lambda: copy.deepcopy(self.settings)),
            'dj_settings': mock.Mock(side_effect=lambda: self.settings['dj']),
            'save_settings': mock.Mock(side_effect=save), 'require_auth': mock.Mock(),
            '_routing_save': mock.Mock(), '_operator_routing_stamp': mock.Mock(),
            '_routing_voice_device_set': mock.Mock(), 'request_box_route_wake': mock.Mock(),
            'pipeline_log': mock.Mock(), 'dj_state': mock.Mock(return_value={}),
            'box_level_send': mock.AsyncMock(), 'voice_generate': mock.AsyncMock(),
            'nabu_mix_changed': mock.AsyncMock(return_value={'ok': True, 'applies': 'next clip'}),
        }.items():
            self.stack.enter_context(mock.patch.object(app, name, value, create=True))

    async def request(self, body):
        request = mock.Mock(headers={}, client=mock.Mock(host='test'))
        request.json = mock.AsyncMock(return_value=body)
        return await app.dj_output_api(request, 'test')

    async def test_independent_nabu_levels_keep_rendered_audio_and_physical_dial_unchanged(self):
        result = await self.request({'music_level': 0, 'voice_level': 1, 'reply_level': .3})
        self.assertEqual(self.settings['dj']['nabu_music_level'], 0)
        self.assertEqual(self.settings['dj']['nabu_voice_level'], 1)
        self.assertEqual(self.settings['dj']['nabu_reply_level'], .3)
        self.assertEqual(self.settings['dj']['box_volume'], .8)
        app.box_level_send.assert_not_awaited()
        app.voice_generate.assert_not_awaited()
        self.assertEqual(set(result['mix_applied']), {'music', 'voice', 'reply'})
        self.assertEqual([c.args[0] for c in app.nabu_mix_changed.await_args_list],
                         ['music', 'voice', 'reply'])

    async def test_speech_zero_is_saved_as_zero(self):
        await self.request({'voice_level': 0, 'reply_level': 0})
        self.assertEqual(self.settings['dj']['nabu_voice_level'], 0)
        self.assertEqual(self.settings['dj']['nabu_reply_level'], 0)
        app.box_level_send.assert_not_awaited()

    async def test_automatic_restore_never_reasserts_levels(self):
        await self.request({'system': True, 'music_level': 0, 'voice_level': 0, 'reply_level': 0})
        app.save_settings.assert_not_called()
        app.nabu_mix_changed.assert_not_awaited()

    async def test_other_speakers_keep_existing_explicit_volume_behavior(self):
        self.radio['voice_device'] = 'pine'
        await self.request({'voice_level': 1})
        self.assertEqual(self.settings['dj']['box_volume'], 1.6)
        self.assertNotIn('nabu_voice_level', self.settings['dj'])
        app.nabu_mix_changed.assert_not_awaited()

    async def test_invalid_level_or_route_has_no_partial_settings_side_effect(self):
        for bad in ({'music_level': 0, 'voice_level': 'bad'},
                    {'music_level': float('nan')}, {'voice_level': True},
                    {'voice': 'wrong', 'music_level': 0}):
            with self.subTest(bad=bad), self.assertRaises(app.HTTPException) as error:
                await self.request(bad)
            self.assertEqual(error.exception.status_code, 400)
            app.save_settings.assert_not_called()
            app.nabu_mix_changed.assert_not_awaited()

    def test_validation_preserves_legacy_music_and_unity_speech_defaults(self):
        incoming = copy.deepcopy(app.DEFAULT_SETTINGS)
        incoming['dj'] = {'music_box_level': .22}
        settings = app.validate_settings(incoming)['dj']
        self.assertEqual(settings['nabu_music_level'], .22)
        self.assertEqual(settings['nabu_voice_level'], .5)
        self.assertEqual(settings['nabu_reply_level'], .5)
        incoming['dj'] = {'nabu_music_level': 0, 'nabu_voice_level': 0, 'nabu_reply_level': 0}
        settings = app.validate_settings(incoming)['dj']
        self.assertEqual(settings['nabu_voice_level'], 0)
        self.assertEqual(settings['nabu_reply_level'], 0)


if __name__ == '__main__':
    unittest.main()
