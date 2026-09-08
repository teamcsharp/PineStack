import asyncio
import copy
from pathlib import Path
import unittest
from contextlib import ExitStack
from unittest import mock

import app


class NabuVolumeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.settings = {"dj": {"box_volume_control": True, "music_box_level": .64},
                         "voice_out": {"media_player": app.NABU_SATELLITE}}
        self.radio = {"voice_device": "nabu", "music_to": "box", "voice_to": "box",
                      "reply_to": "box", "voice_clips": [], "box_talk": True,
                      "on": True, "now": {"id": "record", "path": "/fixture/record.wav"},
                      "started": 100.0}
        replacements = {
            "_RADIO": self.radio, "_MUSIC_LEVEL_SET": {}, "_BOX_HOLD": [],
            "_BOX_DOWN": {"until": 0.0, "fails": 0}, "_ANNOUNCE_LOCK": asyncio.Lock(),
            "_ANNOUNCE_LAST": {}, "_LAST_PLAYOUT": {}, "_BOX_LAST_OK": [0.0],
            "_HEAL_STREAK": [0], "_PAPER_MISS": [0],
            "load_settings": mock.Mock(side_effect=lambda: copy.deepcopy(self.settings)),
            "dj_settings": mock.Mock(side_effect=lambda: dict(self.settings["dj"])),
            "save_settings": mock.Mock(), "pipeline_log": mock.Mock(),
            "note_activity": mock.Mock(), "require_auth": mock.Mock(),
            "_ha_creds": mock.Mock(return_value=("test-token", app.NABU_SATELLITE)),
            "radio_paused": mock.Mock(return_value=False),
            "box_talk_ok": mock.Mock(return_value=True),
            "satellite_ready": mock.AsyncMock(return_value=True),
            "music_url": mock.Mock(return_value="http://station/music/record"),
            "music_hot_file": mock.Mock(return_value=Path("/fixture/record.wav")),
            "_nabu_spoken_source": mock.Mock(return_value=Path("/fixture/voice.wav")),
            "_nabu_audio_url": mock.AsyncMock(return_value="http://station/nabu-audio/fixture.flac?t=fixture"),
            "_NABU_MUSIC_CONTROL": asyncio.Lock(), "_NABU_MUSIC_EPOCH": [0],
            "_NABU_MUTE_CONTROL": asyncio.Lock(), "_NABU_MUTE_STATE": {"muted": None},
            "_NABU_SPEECH_CONTROL": asyncio.Lock(), "_NABU_SPEECH_ACTIVE": {},
            "_NABU_SPEECH_EPOCH": {"voice": 0, "reply": 0},
            "_routing_save": mock.Mock(), "_operator_routing_stamp": mock.Mock(),
            "dj_state": mock.Mock(return_value={"ok": True}),
            "nabu_mix_changed": mock.AsyncMock(return_value={"ok": True, "applies": "music only"}),
        }
        for name, value in replacements.items():
            self.stack.enter_context(mock.patch.object(app, name, value, create=True))
        self.client = mock.AsyncMock()
        self.client.__aenter__.return_value = self.client
        self.client.post.return_value = mock.Mock(status_code=200)
        self.client.get.return_value = mock.Mock(status_code=200)
        self.client.get.return_value.json.return_value = {"attributes": {"is_volume_muted": False}}
        self.stack.enter_context(mock.patch.object(app.httpx, "AsyncClient", return_value=self.client))

    async def test_music_never_sets_nabu_volume_even_with_legacy_opt_in_or_restart(self):
        pending = []
        with mock.patch.object(app, "fire_and_forget_speech", side_effect=pending.append):
            for _ in range(2):
                app._MUSIC_LEVEL_SET.clear()  # a restart used to reassert the stored .64
                await app.music_play_on_box({"id": "record", "seconds": 1})
                await pending.pop(0)
        posts = self.client.post.call_args_list
        self.assertEqual(len(posts), 2)
        self.assertTrue(all(call.args[0].endswith("/media_player/play_media") for call in posts))
        self.assertTrue(all("volume_level" not in call.kwargs["json"] for call in posts))
        self.assertEqual(app._MUSIC_LEVEL_SET, {})

    async def test_announcement_replay_never_sets_or_restores_the_device_volume(self):
        with (mock.patch.object(app, "_clip_seconds", return_value=0.0),
              mock.patch.object(app, "_airtime_note")):
            await app._play_on_box("/media/recorded.wav", "test", replay=True)
        self.assertEqual(self.client.post.await_count, 1)
        call = self.client.post.call_args
        self.assertTrue(call.args[0].endswith("/media_player/play_media"))
        self.assertTrue(call.kwargs["json"]["announce"])
        self.assertNotIn("volume_level", call.kwargs["json"])
        self.assertEqual(call.kwargs["json"]["extra"], {"bypass_proxy": True})

    async def test_only_deliberate_volume_control_can_send_one_adjustment(self):
        denied = await app.box_level_send(.22)
        self.assertFalse(denied["ok"])
        self.client.post.assert_not_awaited()
        accepted = await app.box_level_send(.84, operator=True)
        self.assertTrue(accepted["ok"])
        self.client.post.assert_awaited_once()
        self.assertEqual(self.client.post.call_args.kwargs["json"],
                         {"entity_id": app.NABU_MEDIA_PLAYER, "volume_level": .84})

    async def test_system_routing_restore_cannot_reassert_a_saved_volume(self):
        request = mock.Mock()
        request.json = mock.AsyncMock(return_value={"system": True, "music_level": .22})
        request.headers = {}
        await app.dj_output_api(request, "test")
        self.client.post.assert_not_awaited()
        app.save_settings.assert_not_called()

    async def test_music_slider_changes_only_nabu_music_mix_not_the_shared_dial(self):
        request = mock.Mock()
        request.json = mock.AsyncMock(return_value={"music_level": .84})
        request.headers = {}
        await app.dj_output_api(request, "test")
        self.client.post.assert_not_awaited()
        app.nabu_mix_changed.assert_awaited_once_with("music")
        self.assertEqual(app.save_settings.call_args.args[0]["dj"]["nabu_music_level"], .84)

    async def test_startup_and_old_checkbox_cannot_reenable_automatic_nabu_control(self):
        app._routing_voice_device_set("nabu")
        self.assertFalse(app.save_settings.call_args.args[0]["dj"]["box_volume_control"])
        request = mock.Mock()
        request.json = mock.AsyncMock(return_value={"music_control": True})
        request.headers = {}
        await app.dj_output_api(request, "test")
        self.assertFalse(app.save_settings.call_args.args[0]["dj"]["box_volume_control"])
        self.client.post.assert_not_awaited()

    async def test_actual_nabu_entity_is_protected_even_if_route_metadata_is_stale(self):
        self.radio["voice_device"] = "pine"
        self.assertFalse(app.box_volume_control(app.NABU_MEDIA_PLAYER))
        self.assertFalse(app.box_volume_control(app.NABU_SATELLITE))
        self.assertTrue(app.box_volume_control("media_player.other_speaker"))


if __name__ == "__main__":
    unittest.main()
