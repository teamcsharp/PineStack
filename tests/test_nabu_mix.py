"""Independent stream gains use existing audio and preserve the device dial."""
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import app
from tests import test_nabu_volume as fixtures

_mix_changed = app.nabu_mix_changed
_spoken_source = app._nabu_spoken_source


class NabuMixTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.NabuVolumeTests.setUp

    async def test_zero_music_stops_only_media_without_waiting_for_announcement(self):
        self.settings["dj"]["nabu_music_level"] = 0
        await app._ANNOUNCE_LOCK.acquire()
        try:
            result = await asyncio.wait_for(_mix_changed("music"), 1)
        finally:
            app._ANNOUNCE_LOCK.release()
        self.assertTrue(result["ok"])
        self.client.post.assert_awaited_once()
        call = self.client.post.call_args
        self.assertTrue(call.args[0].endswith("/media_player/media_stop"))
        self.assertEqual(call.kwargs["json"], {"entity_id": app.NABU_MEDIA_PLAYER})
        app._nabu_audio_url.assert_not_awaited()

    async def test_music_refresh_preserves_current_record_offset(self):
        self.settings["dj"]["nabu_music_level"] = .2
        with mock.patch.object(app.time, "time", return_value=137.25):
            result = await _mix_changed("music")
        self.assertTrue(result["ok"])
        self.assertEqual(result["offset"], 37.25)
        call = app._nabu_audio_url.call_args
        self.assertEqual(call.args[1], .2)
        self.assertEqual(call.kwargs["offset"], 37.25)
        self.assertEqual(call.kwargs["channels"], 2)
        payload = self.client.post.call_args.kwargs["json"]
        self.assertFalse(payload["announce"])
        self.assertEqual(payload["extra"], {"bypass_proxy": True})
        self.assertNotIn("volume_level", payload)

    async def test_zero_stops_stale_device_music_even_without_current_record(self):
        self.settings["dj"]["nabu_music_level"] = 0
        self.radio["now"] = None
        result = await _mix_changed("music")
        self.assertTrue(result["ok"])
        self.assertTrue(self.client.post.call_args.args[0].endswith("/media_stop"))

    async def test_zero_clears_buffered_music_after_app_route_pause_and_master_off(self):
        self.settings["dj"]["nabu_music_level"] = 0
        self.radio.update(music_to="here", on=False, box_talk=False, now=None)
        app.radio_paused.return_value = True
        app.box_talk_ok.return_value = False
        result = await _mix_changed("music")
        self.assertTrue(result["ok"])
        self.client.post.assert_awaited_once()
        self.assertTrue(self.client.post.call_args.args[0].endswith("/media_stop"))
        self.assertEqual(self.client.post.call_args.kwargs["json"], {"entity_id": app.NABU_MEDIA_PLAYER})
        app._nabu_audio_url.assert_not_awaited()

    async def test_old_music_post_finishes_before_zero_stop_and_cannot_restart_after_it(self):
        entered, release = asyncio.Event(), asyncio.Event()
        posted = []
        async def post(url, **kwargs):
            posted.append(url.rsplit("/", 1)[-1])
            if posted[-1] == "play_media":
                entered.set()
                await release.wait()
            return mock.Mock(status_code=200)
        self.client.post.side_effect = post
        old = asyncio.create_task(_mix_changed("music"))
        await entered.wait()
        self.settings["dj"]["nabu_music_level"] = 0
        self.radio["music_to"] = "here"
        stop = asyncio.create_task(_mix_changed("music"))
        await asyncio.sleep(0)
        release.set()
        await old
        self.assertTrue((await stop)["ok"])
        self.assertEqual(posted, ["play_media", "media_stop"])

    async def test_queued_old_occurrence_of_same_record_is_refused(self):
        track = dict(self.radio["now"])
        self.radio["started"] = 200
        result = await app._nabu_music_dispatch(track, app._NABU_MUSIC_EPOCH[0],
                                                expected_started=100)
        self.assertFalse(result["ok"])
        app._nabu_audio_url.assert_not_awaited()
        self.client.post.assert_not_awaited()

    async def test_route_off_during_conversion_prevents_late_music_restart(self):
        async def convert(*args, **kwargs):
            self.radio["music_to"] = "off"
            return "http://fixture/old.flac"
        app._nabu_audio_url.side_effect = convert
        result = await _mix_changed("music")
        self.assertFalse(result["ok"])
        self.client.post.assert_not_awaited()

    async def test_superseded_slider_or_new_record_cannot_publish_old_mix(self):
        async def convert(*args, **kwargs):
            self.settings["dj"]["nabu_music_level"] = 0
            app._NABU_MUSIC_EPOCH[0] += 1
            self.radio["now"] = {"id": "next-record"}
            return "http://fixture/old.flac"
        app._nabu_audio_url.side_effect = convert
        result = await _mix_changed("music")
        self.assertFalse(result["ok"])
        self.client.post.assert_not_awaited()

    async def test_encode_failure_cannot_fall_back_to_unattenuated_music(self):
        app._nabu_audio_url.side_effect = ValueError("encode failed")
        result = await _mix_changed("music")
        self.assertFalse(result["ok"])
        self.assertIn("could not be applied", result["why"])
        self.client.post.assert_not_awaited()

    async def test_voice_setting_is_next_dispatch_and_never_stops_either_pipeline(self):
        self.settings["dj"].update(nabu_voice_level=1, nabu_reply_level=.25)
        self.assertEqual((await _mix_changed("voice"))["gain"], 2)
        self.assertEqual((await _mix_changed("reply"))["gain"], .5)
        self.client.post.assert_not_awaited()
        app._nabu_audio_url.assert_not_awaited()

    async def test_recorded_speech_uses_gain_at_delivery_without_tts(self):
        self.settings["dj"].update(nabu_voice_level=1, nabu_reply_level=.25)
        with (mock.patch.object(app, "_clip_seconds", return_value=0),
              mock.patch.object(app, "box_firmware_down_now", return_value=False),
              mock.patch.object(app, "voice_generate", side_effect=AssertionError("TTS called"))):
            result = await app._play_on_box("/media/recorded.wav", "fixture", replay=True)
            self.assertEqual(result, app.NABU_SATELLITE)
            self.assertEqual(app._nabu_audio_url.call_args.args[1], 2)
            await app._play_on_box("/media/recorded.wav", "fixture", reply=True)
            self.assertEqual(app._nabu_audio_url.call_args.args[1], .5)
        self.assertTrue(all(c.kwargs["json"]["announce"] for c in self.client.post.call_args_list))

    async def test_recorded_speech_conversion_failure_preserves_it_for_retry(self):
        app._nabu_audio_url.side_effect = ValueError("encode failed")
        with mock.patch.object(app, "box_firmware_down_now", return_value=False):
            result = await app._play_on_box("/media/recorded.wav", "fixture", replay=True)
        self.assertEqual(result, "")
        self.client.post.assert_not_awaited()
        self.assertIn("could not be applied", app._ANNOUNCE_LAST["error"])

    async def test_intentional_speech_mute_keeps_dispatch_receipt_without_false_healing(self):
        self.settings["dj"]["nabu_voice_level"] = 0
        async def accepted(*args, **kwargs):
            self.settings["dj"]["nabu_voice_level"] = 1  # changed AFTER dispatch
            return mock.Mock(status_code=200)
        self.client.post.side_effect = accepted
        with (mock.patch.object(app, "_clip_seconds", return_value=10),
              mock.patch.object(app, "box_firmware_down_now", return_value=False),
              mock.patch.object(app.asyncio, "sleep", new_callable=mock.AsyncMock),
              mock.patch.object(app, "_nabu_played_since", side_effect=AssertionError("false proof")),
              mock.patch.object(app, "_airtime_note", side_effect=AssertionError("silent airtime")),
              mock.patch.object(app, "satellite_selfheal", side_effect=AssertionError("operator mute is not broken"))):
            result = await app._play_on_box("/media/recorded.wav", "fixture", replay=True)
        self.assertEqual(result, app.NABU_SATELLITE)
        self.assertEqual(app._LAST_PLAYOUT["audible_gain"], 0)
        self.assertTrue(app._LAST_PLAYOUT["intentional_mute"])
        self.assertTrue(app._LAST_PLAYOUT["ok"])
        self.assertFalse(app._LAST_PLAYOUT["audible_confirmed"])
        self.assertEqual(app._LAST_PLAYOUT["evidence"], "operator_muted_stream")

    async def test_recorded_ads_resolve_only_valid_durable_names(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "abcdef1234.mp3"
            path.write_bytes(b"retained original")
            with mock.patch.object(app, "PRODUCED_ADS_DIR", Path(folder)):
                self.assertEqual(_spoken_source("/ads-audio/abcdef1234.mp3?t=fixture"), path)
                self.assertIsNone(_spoken_source("/ads-audio/../abcdef1234.mp3"))
                self.assertIsNone(_spoken_source("/ads-audio/abcdef4321.mp3"))

    async def test_signed_flac_route_serves_exact_range_and_requires_auth(self):
        with tempfile.TemporaryDirectory() as folder:
            key = "a" * 32 + ".flac"
            (Path(folder) / key).write_bytes(b"fLaC" + bytes(range(64)))
            request = mock.Mock(query_params={"t": "good"}, headers={"range": "bytes=4-7"})
            with (mock.patch.object(app, "_nabu_audio_cache", return_value=mock.Mock(directory=Path(folder))),
                  mock.patch.object(app, "media_sign", return_value="good")):
                response = await app.nabu_audio_file(key, request)
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response.media_type, "audio/flac")
                body = b"".join([part async for part in response.body_iterator])
                self.assertEqual(body, bytes(range(4)))
                request.query_params = {"t": "wrong"}
                with mock.patch.object(app, "require_auth", side_effect=app.HTTPException(401)):
                    with self.assertRaises(app.HTTPException):
                        await app.nabu_audio_file(key, request)
                self.assertEqual((await app.nabu_audio_file("../bad.flac", request)).status_code, 404)


if __name__ == "__main__":
    unittest.main()
