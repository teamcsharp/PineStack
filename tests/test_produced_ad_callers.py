"""Every produced-ad entry point reports handoff separately from hearing it."""
import asyncio
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import app


class ProducedAdCallerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.entry = {"id": "spot", "text": "The exact finished sponsor read.",
                      "audio": "spot.mp3", "uses": 2}
        self.patch("_RADIO", {"sched_pos": {"occurrence": "slot-1"}})
        self.patch("require_auth", mock.Mock())
        self.patch("ad_list", mock.Mock(side_effect=lambda: [dict(self.entry)]))
        self.update = self.patch("ad_update", mock.Mock())
        self.patch("ad_aired", mock.Mock(side_effect=AssertionError("receipt owns air credit")))
        self.patch("station_flow_event", mock.Mock())
        self.patch("_sched_pos_save", mock.Mock())
        self.patch("pipeline_log", mock.Mock())

    def patch(self, name, value):
        return self.stack.enter_context(mock.patch.object(app, name, value))

    async def test_scheduled_ad_is_once_per_occurrence_below_full_talk(self):
        self.patch("talk_is_incessant", mock.Mock(return_value=False))
        ad = self.patch("dj_ad_break", mock.AsyncMock(return_value=self.entry["text"]))
        self.assertTrue(await app.schedule_extra_round("ad", None, {}, occurrence="slot-1"))
        self.assertIsNone(await app.schedule_extra_round("ad", None, {}, occurrence="slot-1"))
        self.assertEqual(ad.await_count, 1)
        self.assertTrue(await app.schedule_extra_round("ad", None, {}, occurrence=""))
        self.assertEqual(ad.await_count, 2)  # explicit operator pick remains independent

    async def test_play_refusal_does_not_spend_use_or_claim_ad(self):
        self.patch("_air_produced_ad", mock.AsyncMock(return_value=False))
        result = await app.dj_ads_play("spot", authorization="test")
        self.assertEqual(result["ad"], "")
        self.assertFalse(result["accepted"])
        self.assertEqual(result["delivery"], "not_accepted")
        self.update.assert_not_called()

    async def test_play_publication_counts_one_use_without_claiming_audibility(self):
        async def handoff(entry, on_handoff):
            on_handoff()
            return True
        self.patch("_air_produced_ad", handoff)
        result = await app.dj_ads_play("spot", authorization="test")
        self.assertEqual(result["ad"], self.entry["text"])
        self.assertTrue(result["accepted"])
        self.assertEqual(result["delivery"], "handoff_accepted")
        self.assertNotIn("aired", result)
        self.update.assert_called_once_with("spot", uses=3)

    async def test_cancel_after_page_publication_keeps_committed_use(self):
        async def handoff(entry, on_handoff):
            on_handoff()
            raise asyncio.CancelledError()
        self.patch("_air_produced_ad", handoff)
        with self.assertRaises(asyncio.CancelledError):
            await app.dj_ads_play("spot", authorization="test")
        self.update.assert_called_once_with("spot", uses=3)

    async def test_cancel_before_handoff_and_failed_dry_read_spend_no_use(self):
        self.patch("_air_produced_ad", mock.AsyncMock(side_effect=asyncio.CancelledError()))
        with self.assertRaises(asyncio.CancelledError):
            await app.dj_ads_play("spot", authorization="test")
        self.entry.pop("audio")
        self.patch("dj_speak", mock.AsyncMock(return_value=""))
        result = await app.dj_ads_play("spot", authorization="test")
        self.assertEqual(result["ad"], "")
        self.update.assert_not_called()

    async def test_production_preserves_saved_audio_when_playback_is_refused(self):
        folder = self.stack.enter_context(tempfile.TemporaryDirectory())
        root = Path(folder)
        (root / "voice.wav").write_bytes(b"recorded audio fixture")
        self.patch("VOICE_MEDIA_DIR", root)
        self.patch("PRODUCED_ADS_DIR", root)
        self.patch("spoken_text", lambda text: text)
        self.patch("voice_engine_for", mock.Mock(return_value="piper"))
        self.patch("voice_generate", mock.AsyncMock(return_value={"path": "/voice/voice.wav"}))
        self.patch("music_track", mock.Mock(return_value=None))
        self.patch("_music_bed_track", mock.Mock(return_value=None))
        self.patch("ad_save", mock.Mock(return_value=dict(self.entry)))
        self.patch("_produced_ad_write", mock.Mock(return_value="spot.mp3"))
        self.patch("sfx_seconds", mock.Mock(return_value=4.5))
        self.patch("media_sign", mock.Mock(return_value="signature"))
        handoff = self.patch("_air_produced_ad", mock.AsyncMock(return_value=False))
        for requested, accepted, state in [(True, False, "not_accepted"),
                                            (True, True, "handoff_accepted"),
                                            (False, False, "not_requested")]:
            with self.subTest(requested=requested, accepted=accepted):
                handoff.reset_mock()
                handoff.return_value = accepted
                result = await app.ad_produce("Sponsor", self.entry["text"], "voice-1",
                                              "chosen-track", air=requested)
                self.assertEqual(result["text"], self.entry["text"])
                self.assertEqual(result["audio"], "spot.mp3")
                self.assertNotIn("error", result)  # production succeeded and remains reusable
                self.assertNotIn("aired", result)
                self.assertEqual(result["playback_requested"], requested)
                self.assertEqual(result["accepted"], accepted)
                self.assertEqual(result["delivery"], state)
                self.assertEqual(handoff.await_count, int(requested))
        self.assertFalse(any("uses" in call.kwargs for call in self.update.call_args_list))


if __name__ == "__main__":
    unittest.main()
