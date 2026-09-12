import asyncio
import copy
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app


class MusicRestoreTests(unittest.TestCase):
    def test_emergency_speech_cannot_credit_the_ambient_content_contract(self):
        active = {"aired": {"caller": 10}}
        with (mock.patch.object(app, "_RADIO", {"sched_slot": {"kind": "caller"}}),
              mock.patch.object(app, "_HOUR_ACTIVE", active),
              mock.patch.object(app, "radio_paused", return_value=False)):
            app.coord_air_note("We are keeping you company while the next conversation gets ready.",
                               "dj", "emergency_host")
            app.coord_air_note("I'm listening.", "dj", "response_audition")
        self.assertEqual(active["aired"], {"caller": 10})

    def test_already_aired_record_is_not_forced_back_to_front_by_owed_old_links(self):
        a, b, c = [{"id": key, "title": key} for key in "abc"]
        links = {"a": {"intro": {"at": 100, "text": "Still owed."}},
                 "b": {"intro": {"at": 110, "text": "Not aired yet."}}}
        with (mock.patch.object(app, "_RADIO", {"queue": [c, a, b]}),
              mock.patch.object(app, "_TRACK_TALK", links),
              mock.patch.object(app, "read_played", return_value=[{"id": "a", "at": 150}]),
              mock.patch.object(app, "track_talk_save"),
              mock.patch.object(app, "pipeline_log")):
            self.assertEqual(app.track_talk_restore_queue(), 1)
            self.assertEqual([r["id"] for r in app._RADIO["queue"]], ["b", "c", "a"])
            self.assertEqual(links["a"]["intro"]["text"], "Still owed.")
            self.assertEqual(app.track_talk_restore_queue(), 1)
            self.assertEqual([r["id"] for r in app._RADIO["queue"]], ["b", "c", "a"])


class ContinuityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.voices = {"dj": "host", "cohost": "other"}
        self.radio = {"on": True, "voice_to": "box", "voice_device": "nabu", "chat": []}
        self.debt = {"id": "failed-script", "tint": {"ok": False}, "script": "Original owed words."}
        replacements = {
            "CONTINUITY_PATH": self.root / "reserve.json", "VOICE_MEDIA_DIR": self.root,
            "_CONTINUITY_BANK": {}, "_CONTINUITY_LOADED": [False],
            "_CONTINUITY_PREP_LOCK": asyncio.Lock(), "_CONTINUITY_STATE": {"last_air": 0, "next_pair": 0},
            "_RADIO": self.radio, "_LARDER": [self.debt], "_SPEAKING": [0],
            "_PANTRY": {}, "_LAST_PLAYOUT": {"ok": True},
            "session_voices": mock.AsyncMock(return_value=self.voices),
            "voice_engine_for": mock.Mock(return_value="xtts"),
            "radio_paused": mock.Mock(return_value=False), "_floor_busy": mock.Mock(return_value=False),
            "talk_quiet_for": mock.Mock(return_value=100), "talk_quiet_limit": mock.Mock(return_value=12),
            "_floor_take": mock.AsyncMock(return_value=True), "_floor_drop": mock.Mock(),
            "box_talk_ok": mock.Mock(return_value=True), "station_flow_event": mock.Mock(),
            "talk_said_now": mock.Mock(), "page_delivery_apply": mock.Mock(),
            "_paged_settle": mock.AsyncMock(), "_PAGE_AIR_UNTIL": [321],
        }
        for name, value in replacements.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    def seed(self):
        for who, voice, text in zip(("dj", "cohost"), self.voices.values(), app.CONTINUITY_PAIRS[0]):
            name = f"{who}.wav"
            (self.root / name).write_bytes(b"actual recorded file in fixture")
            app._CONTINUITY_BANK[app.continuity_key(who, voice, "xtts", text)] = {
                "who": who, "voice": voice, "engine": "xtts", "text": text,
                "clip": {"path": "/media/" + name, "seconds": 8}}

    async def test_finished_two_host_reserve_uses_nabu_and_preserves_failed_tint_debt(self):
        self.seed()
        original = copy.deepcopy(self.debt)
        with (mock.patch.object(app, "_response_audition_build", return_value=(b"wav", [8, 9])),
              mock.patch.object(app, "_store_media", return_value={"path": "/media/pair.wav", "sig": "signed"}),
              mock.patch.object(app, "_play_on_box", return_value="/media/pair.wav") as play,
              mock.patch.object(app, "page_feed_append") as page,
              mock.patch.object(app, "prep_render_line") as render,
              mock.patch.object(app, "box_level_send") as volume):
            self.assertTrue(await app.continuity_air("Tint generation is still owed"))
            self.assertFalse(await app.continuity_air("Do not repeat immediately"))
        play.assert_awaited_once()
        page.assert_not_called()
        render.assert_not_awaited()
        volume.assert_not_awaited()
        self.assertEqual(self.debt, original)
        self.assertEqual([r["who"] for r in self.radio["chat"]], ["dj", "cohost"])
        self.assertTrue(all(r["emergency"] and not r["coverage_credit"] for r in self.radio["chat"]))
        self.assertTrue(all(r["kind"] == "emergency_host" for r in self.radio["chat"]))

    async def test_empty_reserve_never_requests_live_render_and_pause_never_spends_stock(self):
        with mock.patch.object(app, "prep_render_line") as render:
            self.assertFalse(await app.continuity_air("No recordings"))
            self.seed()
            app.radio_paused.return_value = True
            self.assertFalse(await app.continuity_air("Paused"))
        render.assert_not_awaited()
        app._floor_take.assert_not_awaited()

    async def test_both_outputs_publish_and_hold_floor_until_page_reservation_settles(self):
        self.seed()
        self.radio["voice_to"] = "both"
        with (mock.patch.object(app, "_response_audition_build", return_value=(b"wav", [8, 9])),
              mock.patch.object(app, "_store_media", return_value={"path": "/media/pair.wav", "sig": "signed"}),
              mock.patch.object(app, "_play_on_box", return_value="/media/pair.wav") as play,
              mock.patch.object(app, "page_feed_append", return_value="real-delivery") as page):
            async def settling(until):
                app._floor_drop.assert_not_called()
                self.assertEqual(until, 321)
            app._paged_settle.side_effect = settling
            self.assertTrue(await app.continuity_air("Recorded cover"))
        play.assert_awaited_once()
        page.assert_called_once()
        app._paged_settle.assert_awaited_once()
        app._floor_drop.assert_called_once_with(True)

    async def test_muted_device_output_cannot_be_bypassed_by_page_rescue(self):
        self.seed()
        app.box_talk_ok.return_value = False
        with mock.patch.object(app, "page_feed_append") as page:
            self.assertFalse(await app.continuity_air("Device intentionally quiet"))
        page.assert_not_called()
        app._floor_take.assert_not_awaited()

    async def test_lower_talk_setting_spends_recorded_cover_before_new_synthesis(self):
        with (mock.patch.object(app, "talk_is_incessant", return_value=False),
              mock.patch.object(app, "_COVER_AT", [0]),
              mock.patch.object(app, "continuity_air", return_value=True) as cover,
              mock.patch.object(app, "fresh_pool_take") as fresh,
              mock.patch.object(app, "dj_speak") as synth):
            self.assertTrue(await app.cover_the_gap("dj", "A measured silence"))
        cover.assert_awaited_once_with("A measured silence")
        fresh.assert_not_called()
        synth.assert_not_awaited()

    async def test_cast_change_during_decode_cannot_publish_old_cast(self):
        self.seed()
        app.session_voices.side_effect = [self.voices, self.voices, {"dj": "changed", "cohost": "other"}]
        with (mock.patch.object(app, "_response_audition_build", return_value=(b"wav", [8, 9])),
              mock.patch.object(app, "_play_on_box") as play,
              mock.patch.object(app, "page_feed_append") as page):
            self.assertFalse(await app.continuity_air("Cast changed"))
        play.assert_not_awaited()
        page.assert_not_called()
        app._floor_drop.assert_called_once_with(True)

    async def test_preparation_persists_actual_clip_for_each_voice_without_tint_credit(self):
        async def record(text, who, voice, kind):
            (self.root / f"{who}.wav").write_bytes(b"recorded fixture")
            app._PANTRY[who] = {"clip": {"path": f"/media/{who}.wav", "seconds": 8,
                                         "voice": voice, "engine": "xtts"}}
            return {"key": who}
        with mock.patch.object(app, "prep_render_line", side_effect=record):
            self.assertEqual(await app.continuity_prepare(2), 2)
        app._CONTINUITY_BANK.clear()
        app._CONTINUITY_LOADED[0] = False
        restored = app.continuity_pick("dj", "host", app.CONTINUITY_PAIRS[0][0])
        self.assertIsNotNone(restored)
        self.assertFalse(restored["coverage_credit"])
        (self.root / "dj.wav").unlink()
        self.assertIsNone(app.continuity_pick("dj", "host", app.CONTINUITY_PAIRS[0][0]))

    async def test_persisted_reserve_survives_media_sweep_after_pantry_expires(self):
        self.seed()
        app.CONTINUITY_PATH.write_text(json.dumps(app._CONTINUITY_BANK), encoding="utf-8")
        app._CONTINUITY_BANK.clear()
        app._CONTINUITY_LOADED[0] = False
        self.assertFalse(app._PANTRY)
        protected = app._protected_media_keys()
        self.assertTrue({"dj.wav", "cohost.wav"}.issubset(protected))


if __name__ == "__main__":
    unittest.main()
