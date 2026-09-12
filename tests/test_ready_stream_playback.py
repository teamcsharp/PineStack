"""Prepared streams keep exact performances and earn credit from receipts."""
import asyncio
import copy
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import app


class ReadyStreamPlaybackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.takes = []
        for i, (who, voice, text) in enumerate([
            ("dj", "voice-original-a", "The Blue painting holds a copper kettle."),
            ("cohost", "voice-original-b", "Its handle is bent beside the window."),
            ("dj", "voice-original-a", "That shadow returns along the lower frame.")]):
            name = f"take-{i}.wav"
            (self.root / name).write_bytes(b"existing recorded audio")
            self.takes.append({"i": i, "who": who, "voice": voice, "text": text,
                               "key": f"key-{i}", "clip": {"path": "/media/" + name,
                               "sig": "signature", "seconds": 3, "voice": voice}})
        self.takes[0]["round"] = {"prep_kind": "gallery",
            "script": "\n".join(t["text"] for t in self.takes),
            "swaths": [{"file": "source.md", "lines": [self.takes[0]["text"]]}]}
        self.radio = {"voice_to": "here", "chat": [], "on": True, "voice_clips": []}
        settings = {**app.DEFAULT_DJ, "caller_static": 0, "sfxguy_rate": 100,
                    "drop_voice": "drop-test", "stream_texture": False}
        replacements = {
            "VOICE_MEDIA_DIR": self.root, "_RADIO": self.radio,
            "_TALK_CUT": [0], "_PREMAKE_GATE": asyncio.Semaphore(0),
            "_PAGE_DELIVERIES": {}, "_PAGE_ACK_EVENTS": [], "_PAGE_ACKED_LINES": set(),
            "_PAGE_AIR_UNTIL": [0.0], "_BOX_DOWN": {}, "_BOX_HOLD": [],
            "_LAST_PLAYOUT": {}, "_STREAM_NOW": {}, "_GALLERY_PENDING": {},
            # These transport fixtures reuse the same three lines. Persistent
            # repeat-ledger integration is isolated in test_system2_repeat_host.
            # The admission window asks whether System2 owns the clock; a
            # bare Mock answers yes and the fixture's ready rounds stop
            # fitting their slot. These are legacy-engine fixtures.
            "_system2": mock.Mock(return_value=mock.Mock(
                enabled=False, repeat_allowed=mock.Mock(return_value=True))),
            "dj_settings": mock.Mock(return_value=settings),
            "radio_paused": mock.Mock(return_value=False),
            "dialogue_tint_required": mock.Mock(return_value=True),
            "tint_coverage_ready": mock.Mock(return_value=True),
            "spoken_text": mock.Mock(side_effect=lambda t: t),
            "pantry_get": mock.Mock(return_value=None),
            "voice_engine_for": mock.Mock(return_value="piper"),
            "box_talk_ok": mock.Mock(return_value=True),
            "box_firmware_down_now": mock.Mock(return_value=False),
            "_clip_seconds": mock.Mock(side_effect=lambda path: 9.0 if "joined" in str(path) else 3.0),
            "_call_concat_blocking": mock.Mock(return_value=b"joined existing takes"),
            "concat_beats": mock.Mock(side_effect=lambda count: [0.0] * count),
            "concat_real_seconds": mock.Mock(side_effect=lambda seconds, beat: seconds),
            "_store_media": mock.Mock(return_value={"path": "/media/joined.wav", "sig": "joined"}),
            "_paged_settle": mock.AsyncMock(), "_play_on_box": mock.AsyncMock(return_value=""),
            "page_reservation_repair": mock.Mock(return_value=[]),
            "page_clip_seconds": mock.Mock(return_value=9.0),
            "gallery_pending_pick": mock.Mock(return_value=[]),
            "booth_actor_name": mock.Mock(side_effect=lambda who, *a: who),
            "airlog_round_now": mock.Mock(return_value="gallery"),
            "_model_call_for": mock.Mock(return_value={}),
            "_episode_stage": mock.Mock(), "_stream_now_set": mock.Mock(),
            "_stream_now_clear": mock.Mock(), "pipeline_log": mock.Mock(),
            "station_flow_event": mock.Mock(), "note_drop": mock.Mock(),
            "air_remember": mock.Mock(), "speakbox_remember": mock.Mock(),
            "quota_stamp": mock.Mock(), "manager_memo_save": mock.Mock(),
            "airlog_news_said": mock.Mock(), "talk_said_now": mock.Mock(),
            "listener_note": mock.Mock(), "render_backlog_ack": mock.Mock(),
            "page_recovery_read": mock.Mock(return_value=[]),
        }
        for name, value in replacements.items():
            self.patch(name, value)
        self.forbidden = []
        for name in ("session_voices", "voice_generate", "voice_render_any", "speak",
                     "dj_speak", "crystal_line", "freshen_script", "ask_model", "dj_sting"):
            self.forbidden.append(self.patch(name, mock.AsyncMock(side_effect=AssertionError(name))))
        for name in ("fresh_pool_top", "render_backlog_top", "sfxguy_line", "sting_due",
                     "add_listening_responses", "seat_reseat", "gold_pick", "gold_note"):
            self.forbidden.append(self.patch(name, mock.Mock(side_effect=AssertionError(name))))
        self.handoff = mock.Mock()

    def patch(self, name, value):
        return self.stack.enter_context(mock.patch.object(app, name, value))

    async def play(self, **kwargs):
        result = await app._speak_turns_floorless([], None, 1,
            ready_takes=copy.deepcopy(self.takes), on_handoff=self.handoff, **kwargs)
        for call in self.forbidden:
            call.assert_not_called()
        return result

    def ack(self, event, position, sequence, volume=0.5):
        clip = self.radio["voice_clips"][0]
        return app.page_playback_ack({"delivery_id": clip["delivery_id"],
            "listener_id": "test-page", "event": event, "current_time": position,
            "sequence": sequence, "volume": volume, "audible_volume": volume})

    async def test_complete_stream_preserves_exact_order_voices_road_and_receipt_windows(self):
        result = await self.play()
        self.assertEqual(result, [f"{t['who']}: {t['text']}" for t in self.takes])
        self.handoff.assert_called_once()
        self.assertEqual(len(self.radio["voice_clips"]), 1)
        clip = self.radio["voice_clips"][0]
        rows = clip["stream"]["rows"]
        self.assertEqual([r["text"] for r in rows], [t["text"] for t in self.takes])
        self.assertEqual([r["who"] for r in rows], [t["who"] for t in self.takes])
        self.assertEqual([r["voice"] for r in self.radio["chat"]], [t["voice"] for t in self.takes])
        self.assertEqual([r["kind"] for r in rows], ["gallery"] * 3)
        self.assertEqual([(r["from"], r["until"]) for r in rows], [(0, 3), (3, 6), (6, 9)])
        app.air_remember.assert_not_called()
        app.speakbox_remember.assert_not_called()
        self.ack("playing", 0.2, 1)
        self.assertEqual(app.air_remember.call_count, 1)
        self.ack("playing", 3.2, 2)
        self.ack("playing", 6.2, 3)
        self.assertEqual(app.air_remember.call_count, 3)
        app.speakbox_remember.assert_not_called()
        self.ack("ended", 9, 4)
        app.speakbox_remember.assert_called_once()
        self.assertTrue(app.page_playback_state()["line_audit"][0]["complete"])
        self.ack("ended", 9, 5)
        self.assertEqual(app.air_remember.call_count, 3)
        self.assertEqual([c.args[2] for c in app.air_remember.call_args_list], ["gallery"] * 3)
        app.speakbox_remember.assert_called_once()

    async def test_concat_failure_missing_file_and_no_route_keep_work_uncommitted(self):
        for failure in ("concat", "missing", "route"):
            with self.subTest(failure=failure):
                self.radio["voice_clips"].clear()
                self.handoff.reset_mock()
                app._call_concat_blocking.return_value = None if failure == "concat" else b"joined"
                self.radio["voice_to"] = "off" if failure == "route" else "here"
                missing = self.root / "take-1.wav"
                if failure == "missing":
                    missing.unlink()
                try:
                    self.assertEqual(await self.play(), [])
                    self.handoff.assert_not_called()
                    self.assertEqual(self.radio["voice_clips"], [])
                    app.air_remember.assert_not_called()
                finally:
                    missing.write_bytes(b"existing recorded audio")

    async def test_box_refusal_keeps_original_without_dry_synthesis_or_second_hold_owner(self):
        self.radio["voice_to"] = "box"
        self.assertEqual(await self.play(), [])
        self.handoff.assert_not_called()
        self.assertEqual(app._BOX_HOLD, [])
        app.air_remember.assert_not_called()

    async def test_cancel_after_page_handoff_does_not_revert_acceptance(self):
        self.radio["voice_to"] = "both"
        self.radio["monitor"] = True  # the explicit simultaneous page/box route
        app._play_on_box.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.play()
        self.handoff.assert_called_once()
        self.assertEqual(len(self.radio["voice_clips"]), 1)
        app.air_remember.assert_not_called()

    async def test_page_then_box_receipt_credits_each_take_and_source_once(self):
        self.radio["voice_to"] = "both"
        self.radio["monitor"] = True
        async def box(*args):
            self.ack("playing", 0.2, 1)
            self.ack("playing", 3.2, 2)
            self.ack("playing", 6.2, 3)
            self.ack("ended", 9, 4)
            return "verified-box-url"
        app._play_on_box.side_effect = box
        await self.play()
        self.assertEqual(app.air_remember.call_count, 3)
        app.speakbox_remember.assert_called_once()

    async def test_pause_during_concat_prevents_publication_and_consumption(self):
        def concat(*args):
            app.radio_paused.return_value = True
            return b"joined"
        app._call_concat_blocking.side_effect = concat
        self.assertEqual(await self.play(), [])
        self.assertEqual(self.radio["voice_clips"], [])
        self.handoff.assert_not_called()

    async def test_withdrawal_during_concat_rechecks_before_publication(self):
        eligible = [True]
        def concat(*args):
            self.assertTrue(eligible[0])  # accepted when the assembly began
            eligible[0] = False  # the operator withdraws before the handoff
            return b"joined"
        app._call_concat_blocking.side_effect = concat
        permit = mock.Mock(side_effect=lambda: eligible[0])
        self.assertEqual(await self.play(can_handoff=permit), [])
        permit.assert_called()
        self.assertEqual(self.radio["voice_clips"], [])
        self.handoff.assert_not_called()
        app._play_on_box.assert_not_awaited()
        app.air_remember.assert_not_called()
        app.speakbox_remember.assert_not_called()

    def capture_slot(self):
        self.radio["sched_pos"] = {"occurrence": "gallery-occurrence",
            "slot_id": "gallery-slot", "started": 1000.0}
        self.radio["sched_slot"] = {"id": "gallery-slot", "kind": "gallery", "minutes": 1 / 3}
        self.patch("schedule_read", mock.Mock(return_value={"enabled": True}))
        self.patch("VOICE_BROADCAST_LEAD_MS", 1000)
        self.takes[0]["round"]["_ready_slot"] = {"occurrence": "gallery-occurrence",
            "slot_id": "gallery-slot", "kind": "gallery", "deadline": 1020.0}

    async def test_final_measured_length_uses_remaining_slot_without_charging_assembly_twice(self):
        self.capture_slot()
        clock = [1000.0]
        self.stack.enter_context(mock.patch.object(app.time, "time", side_effect=lambda: clock[0]))
        # Nine seconds fits after a five-second assembly, but would fail if
        # those five seconds were charged again. Longer media or later
        # completion must be refused even though the original takes fit.
        for finished, joined, accepted in [(1005.0, 9.0, True),
                                           (1005.0, 16.0, False),
                                           (1012.0, 9.0, False)]:
            with self.subTest(finished=finished, joined=joined):
                clock[0] = 1000.0
                self.radio["voice_clips"].clear()
                self.radio["chat"].clear()
                app._PAGE_AIR_UNTIL[0] = 0.0
                app._PAGE_DELIVERIES.clear()
                self.handoff.reset_mock()
                def concat(*args):
                    clock[0] = finished
                    return b"joined"
                app._call_concat_blocking.side_effect = concat
                app._clip_seconds.side_effect = lambda path: joined if "joined" in str(path) else 3.0
                app.page_clip_seconds.return_value = joined
                result = await self.play()
                self.assertEqual(bool(result), accepted)
                self.assertEqual(len(self.radio["voice_clips"]), int(accepted))
                self.assertEqual(self.handoff.call_count, int(accepted))
                app.air_remember.assert_not_called()
                app._play_on_box.assert_not_awaited()

    async def test_same_kind_replacement_occurrence_cannot_receive_prior_slot_stream(self):
        self.capture_slot()
        self.stack.enter_context(mock.patch.object(app.time, "time", return_value=1000.0))
        def concat(*args):
            # The road and slot ID are unchanged; it is a different airing.
            self.radio["sched_pos"]["occurrence"] = "next-gallery-occurrence"
            return b"joined"
        app._call_concat_blocking.side_effect = concat
        self.assertEqual(await self.play(), [])
        self.assertEqual(self.radio["voice_clips"], [])
        self.handoff.assert_not_called()
        app._play_on_box.assert_not_awaited()
        app.air_remember.assert_not_called()


if __name__ == "__main__":
    unittest.main()
