"""2026-09-08: dead air is punctuated with clips that already exist."""
import time
import unittest
from contextlib import ExitStack
from unittest import mock

import app


class GapFillTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.radio = {"on": True, "voice_to": "box"}
        self.speaking = [0]
        self.spoke_at = [0.0]
        self.settings = {"sfx_gap": 0, "drop_voice": ""}
        for name, value in {
            "_RADIO": self.radio, "_SPEAKING": self.speaking, "_SPOKE_AT": self.spoke_at,
            "radio_paused": lambda: False, "_floor_busy": lambda: False,
            "dj_settings": lambda: self.settings, "box_talk_ok": lambda: True,
            "box_firmware_down_now": lambda: False, "pipeline_log": mock.Mock(),
            "_SFX_GAP": {"at": 0.0, "turn": 0, "count": 0, "why": "", "went": ""},
            "_PAGE_ACK_EVENTS": [], "_PAGE_AIR_UNTIL": [0.0],
            "talk_quiet_for": lambda: 0.0, "sfx_queue_deep": lambda: 0,
            "sfx_gap_burst": lambda: 1,
            "SFX_GAP_REST": 9.0,
        }.items():
            self.stack.enter_context(mock.patch.object(app, name, value))
        self.sting = self.stack.enter_context(
            mock.patch.object(app, "dj_sting", new=mock.AsyncMock(return_value="sample.wav")))
        self.speak = self.stack.enter_context(
            mock.patch.object(app, "dj_speak", new=mock.AsyncMock(return_value="ok")))
        self.take = self.stack.enter_context(
            mock.patch.object(app, "shelf_take", mock.Mock(return_value=None)))
        self.gold = self.stack.enter_context(
            mock.patch.object(app, "gold_fill_gap", new=mock.AsyncMock(return_value="")))
        self.gap_talk = self.stack.enter_context(
            mock.patch.object(app, "sfxguy_gap_talk", new=mock.AsyncMock(return_value="")))

    async def test_silence_gets_a_sample_that_exists_and_then_rests(self):
        self.assertEqual(await app.sfx_fill_gap("the room is silent"), "sample")
        self.sting.assert_awaited_once()
        self.assertTrue(self.sting.await_args.kwargs.get("force"))
        self.assertEqual(self.sting.await_args.kwargs.get("who"), "gap")
        self.assertEqual(await app.sfx_fill_gap("still silent"), "")
        self.assertEqual(app._SFX_GAP["count"], 1)
        self.assertEqual(app.sfx_gap_status()["went"], "sample")

    async def test_never_over_a_voice_never_while_paused(self):
        self.speaking[0] = 1
        self.assertEqual(await app.sfx_fill_gap(), "")
        self.speaking[0] = 0
        self.spoke_at[0] = time.time()
        self.assertEqual(await app.sfx_fill_gap(), "")
        self.spoke_at[0] = 0.0
        with mock.patch.object(app, "radio_paused", lambda: True):
            self.assertEqual(await app.sfx_fill_gap(), "")
        self.sting.assert_not_awaited()

    async def test_a_held_floor_is_punctuated_only_when_asked_and_only_with_a_sample(self):
        self.settings["drop_voice"] = "sfx-guy"
        self.take.return_value = {"text": "Pine Box FM, the only box in town."}
        with mock.patch.object(app, "_floor_busy", lambda: True):
            self.assertEqual(await app.sfx_fill_gap("rendering"), "")
            app._SFX_GAP["turn"] = 1            # the next turn would be the liner's
            self.assertEqual(await app.sfx_fill_gap("rendering", under_floor=True), "sample")
        self.speak.assert_not_awaited()

    async def test_the_sfx_guys_recorded_liner_alternates_with_the_samples(self):
        self.settings["drop_voice"] = "sfx-guy"
        self.take.return_value = {"text": "Pine Box FM, the only box in town."}
        app._SFX_GAP["turn"] = 1
        self.assertEqual(await app.sfx_fill_gap("quiet"), "liner")
        self.speak.assert_awaited_once()
        self.assertEqual(self.speak.await_args.args[0], "station_id")
        self.assertEqual(self.speak.await_args.kwargs.get("voice"), "sfx-guy")
        self.sting.assert_not_awaited()

    async def test_the_operators_gap_dial_is_the_rest_when_longer(self):
        self.settings["sfx_gap"] = 30
        app._SFX_GAP["at"] = time.time() - 20
        self.assertEqual(await app.sfx_fill_gap(), "")
        app._SFX_GAP["at"] = time.time() - 31
        self.assertEqual(await app.sfx_fill_gap(), "sample")

    async def test_a_held_floor_gets_one_tactical_fill_not_a_burst(self):
        with (mock.patch.object(app, "_floor_busy", lambda: True),
              mock.patch.object(app, "sfx_gap_burst", lambda: 3)):
            self.assertEqual(
                await app.sfx_fill_gap("a conversation is rendering", under_floor=True),
                "sample")
        self.sting.assert_awaited_once()
        self.assertEqual(app._SFX_GAP["burst"], 1)

    async def test_audible_page_audio_prevents_another_sold_air_burst(self):
        now = time.time()
        app._PAGE_AIR_UNTIL[0] = now + 30
        app._PAGE_ACK_EVENTS.append({
            "at": now, "event": "playing", "muted": False,
            "audible_volume": 1.0,
        })
        with (mock.patch.object(app, "sfx_sold_tolerance", lambda: 10),
              mock.patch.object(app, "sfx_gap_notice", lambda: 6),
              mock.patch.object(app, "talk_quiet_for", lambda: 60.0)):
            self.assertEqual(await app.sfx_fill_gap("the pair are quiet"), "")
        self.sting.assert_not_awaited()
        self.assertIn("air is already sold", app._SFX_GAP["gate"])


if __name__ == "__main__":
    unittest.main()
