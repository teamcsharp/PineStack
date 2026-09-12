"""Explicit whole-device silence uses mute, never a route or master-level write."""
import asyncio
import copy
import unittest
from unittest import mock

import app
from tests import test_nabu_volume as fixtures

_mix_changed = app.nabu_mix_changed

class NabuZeroTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.NabuVolumeTests.setUp(self)
        for name, value in {
            "_NABU_SPEECH_ACTIVE": {}, "_NABU_SPEECH_CONTROL": asyncio.Lock(),
            "_NABU_SPEECH_EPOCH": {"voice": 0, "reply": 0},
            "_nabu_silence_url": mock.AsyncMock(return_value="http://fixture/verified-silence.flac"),
        }.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    async def request(self, payload):
        request = mock.Mock(headers={}, client=mock.Mock(host="fixture"))
        request.json = mock.AsyncMock(return_value=payload)
        return await app.dj_output_api(request, "fixture")

    async def test_explicit_device_mute_reaches_buffered_audio_with_routes_here_and_announcement_lock_held(self):
        self.stack.enter_context(mock.patch.object(app, "_NABU_MUTE_CONTROL", asyncio.Lock()))
        self.radio.update(music_to="here", voice_to="here", reply_to="here", box_talk=False)
        before = copy.deepcopy(self.radio)
        self.client.get.return_value = mock.Mock(status_code=200)
        self.client.get.return_value.json.return_value = {"attributes": {"is_volume_muted": True, "volume_level": .6}}
        await app._ANNOUNCE_LOCK.acquire()
        try:
            result = await asyncio.wait_for(self.request({"nabu_mute": True}), 1)
        finally:
            app._ANNOUNCE_LOCK.release()
        self.assertTrue(result["nabu_mute"]["ok"])
        self.assertTrue(result["nabu_mute"]["confirmed"])
        self.assertTrue(result["nabu_mute"]["muted"])
        self.client.post.assert_awaited_once()
        self.assertTrue(self.client.post.call_args.args[0].endswith("/volume_mute"))
        self.assertEqual(self.client.post.call_args.kwargs["json"], {
            "entity_id": app.NABU_MEDIA_PLAYER, "is_volume_muted": True})
        self.assertEqual(self.radio, before)
        app.save_settings.assert_not_called()
        app._routing_save.assert_not_called()
        app._operator_routing_stamp.assert_not_called()
        app._nabu_audio_url.assert_not_awaited()

    async def test_explicit_unmute_restores_no_old_route_or_gain_value(self):
        self.stack.enter_context(mock.patch.object(app, "_NABU_MUTE_CONTROL", asyncio.Lock()))
        self.settings["dj"].update(nabu_music_level=0, nabu_voice_level=.9, nabu_reply_level=.25)
        before = copy.deepcopy(self.settings)
        self.client.get.return_value = mock.Mock(status_code=200)
        self.client.get.return_value.json.return_value = {"attributes": {"is_volume_muted": False, "volume_level": .6}}
        result = await self.request({"nabu_mute": False})
        self.assertFalse(result["nabu_mute"]["muted"])
        self.assertTrue(result["nabu_mute"]["confirmed"])
        self.assertEqual(self.client.post.call_args.kwargs["json"], {
            "entity_id": app.NABU_MEDIA_PLAYER, "is_volume_muted": False})
        self.assertEqual(self.settings, before)
        app.save_settings.assert_not_called()

    async def test_mute_rejection_or_delayed_state_is_reported_truthfully(self):
        self.stack.enter_context(mock.patch.object(app, "_NABU_MUTE_CONTROL", asyncio.Lock()))
        self.client.post.return_value = mock.Mock(status_code=503)
        failed = (await self.request({"nabu_mute": True}))["nabu_mute"]
        self.assertFalse(failed["ok"])
        self.assertFalse(failed["confirmed"])
        self.assertIsNone(failed["muted"])
        self.client.get.assert_not_awaited()
        self.client.post.return_value = mock.Mock(status_code=200)
        self.client.get.return_value = mock.Mock(status_code=200)
        self.client.get.return_value.json.return_value = {"attributes": {"is_volume_muted": False}}
        pending = (await self.request({"nabu_mute": True}))["nabu_mute"]
        self.assertTrue(pending["ok"])
        self.assertFalse(pending["confirmed"])
        self.assertFalse(pending["muted"])
        self.assertTrue(pending["requested_muted"])

    async def test_invalid_or_automatic_mute_has_no_partial_route_or_settings_writes(self):
        for payload in ({"nabu_mute": "false"}, {"nabu_mute": 1},
                        {"nabu_mute": True, "system": True},
                        {"nabu_mute": True, "voice": "box"},
                        {"nabu_mute": True, "music_level": 0}):
            with self.subTest(payload=payload), self.assertRaises(app.HTTPException):
                await self.request(payload)
        self.client.post.assert_not_awaited()
        app.save_settings.assert_not_called()
        app._routing_save.assert_not_called()

    async def test_zero_replaces_only_owned_current_speech_and_never_claims_full_hearing(self):
        waiting, finish = asyncio.Event(), asyncio.Event()
        async def clip_wait(_seconds):
            waiting.set()
            await finish.wait()
        with (mock.patch.object(app, "_clip_seconds", return_value=60),
              mock.patch.object(app, "box_firmware_down_now", return_value=False),
              mock.patch.object(app.asyncio, "sleep", side_effect=clip_wait),
              mock.patch.object(app, "_nabu_played_since", side_effect=AssertionError("muted audio is not proof")),
              mock.patch.object(app, "_airtime_note", side_effect=AssertionError("muted tail is not heard"))):
            playing = asyncio.create_task(app._play_on_box("/media/recorded.wav", "fixture", replay=True))
            try:
                await asyncio.wait_for(waiting.wait(), 1)
                self.assertTrue(app._ANNOUNCE_LOCK.locked())
                self.settings["dj"]["nabu_reply_level"] = 0
                other = await asyncio.wait_for(_mix_changed("reply"), 1)
                self.assertEqual(other["applies"], "next spoken clip")
                self.assertEqual(self.client.post.await_count, 1)
                self.settings["dj"]["nabu_voice_level"] = 0
                zero = await asyncio.wait_for(_mix_changed("voice"), 1)
                self.assertEqual(zero["applies"], "active spoken clip")
                self.assertEqual(self.client.post.await_count, 2)
                payload = self.client.post.call_args.kwargs["json"]
                self.assertEqual(payload["media_content_id"], "http://fixture/verified-silence.flac")
                self.assertTrue(payload["announce"])
                self.assertNotIn("volume_level", payload)
                self.assertNotIn("is_volume_muted", payload)
                await _mix_changed("voice")
                self.assertEqual(self.client.post.await_count, 2)
                finish.set()
                self.assertEqual(await playing, app.NABU_SATELLITE)
            finally:
                finish.set()
                if not playing.done():
                    playing.cancel()
                await asyncio.gather(playing, return_exceptions=True)
        self.assertEqual(app._NABU_SPEECH_ACTIVE, {})
        self.assertTrue(app._LAST_PLAYOUT["intentional_mute"])
        self.assertTrue(app._LAST_PLAYOUT["interrupted"])
        self.assertFalse(app._LAST_PLAYOUT["audible_confirmed"])
        self.assertEqual(app._LAST_PLAYOUT["audible_gain"], 1)  # original dispatch, not rewritten history

    async def test_unknown_clip_is_untouched_and_replaced_identity_or_gain_cancels_zero(self):
        self.settings["dj"]["nabu_voice_level"] = 0
        quiet = await _mix_changed("voice")
        self.assertEqual(quiet["applies"], "next spoken clip")
        self.client.post.assert_not_awaited()
        app._nabu_silence_url.assert_not_awaited()
        for changed in ("id", "gain"):
            app._NABU_SPEECH_ACTIVE.update(owner=object(), id="owned", lane="voice", gain=1)
            self.settings["dj"]["nabu_voice_level"] = 0
            async def conversion():
                if changed == "id":
                    app._NABU_SPEECH_ACTIVE["id"] = "new-clip"
                else:
                    self.settings["dj"]["nabu_voice_level"] = 1
                return "http://fixture/silence.flac"
            app._nabu_silence_url.side_effect = conversion
            await _mix_changed("voice")
            self.client.post.assert_not_awaited()

    async def test_future_clip_on_muted_device_is_not_credited_or_repaired_as_silence(self):
        self.client.get.return_value.json.return_value = {"attributes": {"is_volume_muted": True}}
        with (mock.patch.object(app, "_clip_seconds", return_value=1),
              mock.patch.object(app, "box_firmware_down_now", return_value=False),
              mock.patch.object(app.asyncio, "sleep", new_callable=mock.AsyncMock),
              mock.patch.object(app, "_nabu_played_since", side_effect=AssertionError("muted playback is not proof")),
              mock.patch.object(app, "_airtime_note", side_effect=AssertionError("muted audio was not heard")),
              mock.patch.object(app, "satellite_selfheal", side_effect=AssertionError("deliberate mute is not a failure"))):
            self.assertEqual(await app._play_on_box("/media/recorded.wav", "fixture", replay=True), app.NABU_SATELLITE)
        self.assertTrue(app._LAST_PLAYOUT["intentional_mute"])
        self.assertFalse(app._LAST_PLAYOUT["audible_confirmed"])
        self.assertEqual(app._LAST_PLAYOUT["audible_gain"], 1)
        self.assertEqual(self.client.post.call_args.kwargs["json"]["announce"], True)

    async def test_cancelled_playback_releases_owned_channel(self):
        waiting = asyncio.Event()
        async def wait(_seconds):
            waiting.set()
            await asyncio.Event().wait()
        with (mock.patch.object(app, "_clip_seconds", return_value=60),
              mock.patch.object(app, "box_firmware_down_now", return_value=False),
              mock.patch.object(app.asyncio, "sleep", side_effect=wait)):
            playing = asyncio.create_task(app._play_on_box("/media/recorded.wav", "fixture", replay=True))
            await asyncio.wait_for(waiting.wait(), 1)
            self.assertTrue(app._NABU_SPEECH_ACTIVE)
            playing.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await playing
        self.assertEqual(app._NABU_SPEECH_ACTIVE, {})


if __name__ == "__main__":
    unittest.main()
