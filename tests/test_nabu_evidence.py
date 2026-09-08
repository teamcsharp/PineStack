"""Expose the limits of Nabu state evidence without changing handoff policy."""
import unittest
from unittest import mock

import app
from tests import test_nabu_volume as fixtures


class NabuEvidenceTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.NabuVolumeTests.setUp

    async def send(self, seconds):
        with (mock.patch.object(app, "_clip_seconds", return_value=seconds),
              mock.patch.object(app, "_airtime_note"),
              mock.patch.object(app, "box_firmware_down_now", return_value=False),
              mock.patch.object(app, "_nabu_played_since", new_callable=mock.AsyncMock,
                                return_value=True) as state,
              mock.patch.object(app.asyncio, "sleep", new_callable=mock.AsyncMock)):
            result = await app._play_on_box("/media/recorded.wav", "test", replay=True)
        self.assertEqual(result, app.NABU_SATELLITE)
        self.assertTrue(app._LAST_PLAYOUT["ok"])  # existing handoff behavior
        self.assertTrue(app._LAST_PLAYOUT["transport_accepted"])
        self.assertFalse(app._LAST_PLAYOUT["audible_confirmed"])
        self.client.post.assert_awaited_once()
        call = self.client.post.call_args
        self.assertTrue(call.args[0].endswith("/media_player/play_media"))
        self.assertTrue(call.kwargs["json"]["announce"])
        self.assertNotIn("volume_level", call.kwargs["json"])
        self.assertEqual(call.kwargs["json"]["extra"], {"bypass_proxy": True})
        return state

    async def test_state_after_wait_is_labeled_as_inference(self):
        state = await self.send(10.0)
        state.assert_awaited_once()
        self.assertEqual(app._LAST_PLAYOUT["evidence"],
                         "home_assistant_state_after_wait")
        self.assertIn("music", app._LAST_PLAYOUT["evidence_note"])

    async def test_unknown_duration_acceptance_does_not_claim_audible_proof(self):
        state = await self.send(0.0)
        state.assert_not_awaited()
        self.assertEqual(app._LAST_PLAYOUT["evidence"],
                         "home_assistant_command_accepted")

    async def test_status_exposes_basis_without_any_device_mutation(self):
        await self.send(10.0)
        before = self.client.post.await_count
        with (mock.patch.object(app, "require_read_auth"),
              mock.patch.object(app, "pinebox_diagnose", new_callable=mock.AsyncMock,
                                return_value={"healthy": True}),
              mock.patch.object(app, "station_health_words", return_value=(True, "ready")),
              mock.patch.object(app, "box_overridden", return_value=None),
              mock.patch.object(app, "music_box_level", return_value=.64),
              mock.patch.object(app, "airtime_summary", return_value={} )):
            status = await app.pinebox_status_api("fixture")
        delivery = status["delivery"]
        self.assertTrue(delivery["transport_accepted"])
        self.assertEqual(delivery["reported_basis"], "home_assistant_state_after_wait")
        self.assertFalse(delivery["audible_confirmed"])
        self.assertIn("not confirmed", delivery["evidence_note"])
        self.assertEqual(self.client.post.await_count, before)


if __name__ == "__main__":
    unittest.main()
