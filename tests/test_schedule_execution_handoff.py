import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class ScheduleExecutionHandoffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 1000.0
        self.slots = [
            {"id": "first", "kind": "ad", "minutes": 1},
            {"id": "second", "kind": "ad", "minutes": 1},
        ]
        self.radio = {"sched_pos": {"preset": "test", "index": 0,
                      "started": self.now, "hour": "", "slot_id": "first"}}
        patches = {
            "_RADIO": self.radio,
            "schedule_read": mock.Mock(return_value={
                "enabled": True, "presets": {"test": self.slots}}),
            "schedule_preset_now": mock.Mock(return_value="test"),
            "schedule_hour_slots": mock.Mock(return_value=("test", [], False)),
            "_sched_hour_key": mock.Mock(return_value="2026-09-07T12"),
            "_sched_pos_save": mock.Mock(),
            "_sched_pos_restore": mock.Mock(),
            "radio_paused": mock.Mock(return_value=False),
            "ballast_swap": mock.Mock(return_value={}),
            "coord_carry_forward": mock.Mock(),
            "schedule_prompt_for": mock.Mock(return_value=""),
            "prompt_window_text": mock.Mock(return_value=""),
            "station_flow_event": mock.Mock(),
            "pipeline_log": mock.Mock(),
        }
        for name, value in patches.items():
            patch = mock.patch.object(app, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        clock = mock.patch.object(app.time, "time", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.dj = {"talk_radio_mode": True, "talk_radio": 100}

    async def test_first_slot_is_consumed_by_success_not_panel_reads(self):
        with mock.patch.object(app, "dj_ad_break", new=mock.AsyncMock(
                return_value=True)) as ad:
            app.schedule_take()
            app.schedule_take()
            self.assertTrue(await app.schedule_extra_round("ad", None, self.dj))
            app.schedule_take()
            self.assertFalse(self.radio["sched_first"])
            self.assertIsNone(await app.schedule_extra_round("ad", None, self.dj))
            self.assertEqual(ad.await_count, 1)

    async def test_later_slot_poll_cannot_consume_first_dispatch(self):
        self.now += 61
        self.assertEqual(app.schedule_take()["id"], "second")
        app.schedule_take()
        with mock.patch.object(app, "dj_ad_break", new=mock.AsyncMock(
                return_value=True)) as ad:
            self.assertTrue(await app.schedule_extra_round("ad", None, self.dj))
            ad.assert_awaited_once_with(zero_work_only=True, on_handoff=mock.ANY)

    async def test_failed_handoff_remains_eligible_after_more_polls(self):
        self.now += 61
        app.schedule_take()
        with mock.patch.object(app, "dj_ad_break", new=mock.AsyncMock(
                side_effect=[False, True])) as ad:
            self.assertFalse(await app.schedule_extra_round("ad", None, self.dj))
            app.schedule_take()
            self.assertTrue(await app.schedule_extra_round("ad", None, self.dj))
            self.assertEqual(ad.await_count, 2)

    async def test_overlapping_dispatch_and_poll_during_handoff(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def play(**kwargs):
            started.set()
            await release.wait()
            return True

        app.schedule_take()
        with mock.patch.object(app, "dj_ad_break", side_effect=play) as ad:
            first = asyncio.create_task(app.schedule_extra_round("ad", None, self.dj))
            await started.wait()
            try:
                app.schedule_take()
                self.assertIsNone(await app.schedule_extra_round("ad", None, self.dj))
            finally:
                release.set()
                await first
            self.assertEqual(ad.await_count, 1)
            app.schedule_take()
            self.assertFalse(self.radio["sched_first"])

    async def test_cancellation_releases_claim_without_consuming_action(self):
        started = asyncio.Event()

        async def play(**kwargs):
            started.set()
            await asyncio.Event().wait()

        app.schedule_take()
        with mock.patch.object(app, "dj_ad_break", side_effect=play):
            task = asyncio.create_task(app.schedule_extra_round("ad", None, self.dj))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        app.schedule_take()
        with mock.patch.object(app, "dj_ad_break", new=mock.AsyncMock(return_value=True)):
            self.assertTrue(await app.schedule_extra_round("ad", None, self.dj))

    async def test_previous_completion_cannot_consume_new_slot(self):
        async def play(**kwargs):
            self.now += 61
            self.assertEqual(app.schedule_take()["id"], "second")
            return True

        app.schedule_take()
        with mock.patch.object(app, "dj_ad_break", side_effect=play):
            self.assertTrue(await app.schedule_extra_round("ad", None, self.dj))
        self.assertTrue(self.radio["sched_first"])
        with mock.patch.object(app, "dj_ad_break", new=mock.AsyncMock(return_value=True)):
            self.assertTrue(await app.schedule_extra_round("ad", None, self.dj))

    def test_slot_transition_is_not_a_clock_jam(self):
        self.slots[0]["minutes"] = 5
        self.slots[1]["minutes"] = 0.5
        self.now += 310
        self.assertEqual(app.schedule_jammed(), "")
        self.assertEqual(self.radio["sched_pos"]["slot_id"], "second")

    async def test_pause_and_restart_preserve_completed_occurrence(self):
        app.schedule_take()
        with mock.patch.object(app, "dj_ad_break", new=mock.AsyncMock(return_value=True)):
            await app.schedule_extra_round("ad", None, self.dj)
        occurrence = self.radio["sched_pos"]["occurrence"]
        self.radio["paused_sched_elapsed"] = 10
        self.radio.pop("sched_actions_done", None)  # only persisted position survives
        self.now += 600
        with mock.patch.object(app, "radio_paused", return_value=True):
            app.schedule_take()
        self.assertEqual(self.radio["sched_pos"]["occurrence"], occurrence)
        self.assertFalse(self.radio["sched_first"])

    async def test_wrap_starts_a_new_occurrence_even_at_index_zero(self):
        app.schedule_take()
        with mock.patch.object(app, "dj_ad_break", new=mock.AsyncMock(return_value=True)) as ad:
            await app.schedule_extra_round("ad", None, self.dj)
            self.now += 121
            app.schedule_take()
            self.assertTrue(await app.schedule_extra_round("ad", None, self.dj))
            self.assertEqual(ad.await_count, 2)

    async def test_record_guard_runs_once_and_failed_skip_is_retryable(self):
        self.slots[0]["kind"] = "record"
        app.schedule_take()
        with (mock.patch.object(app, "_schedule_pin_record") as pin,
              mock.patch.object(app, "track_may_cut", return_value=True),
              mock.patch.object(app, "dj_skip", side_effect=[RuntimeError("player"), None]) as skip):
            self.assertFalse(await app.schedule_extra_round("record", None, self.dj))
            app.schedule_take()
            self.assertIsNone(await app.schedule_extra_round("record", None, self.dj))
            app.schedule_take()
            self.assertIsNone(await app.schedule_extra_round("record", None, self.dj))
            self.assertEqual(skip.call_count, 2)
            self.assertEqual(pin.call_count, 2)

    async def test_interjection_is_independent_of_completed_clock_occurrence(self):
        app.schedule_take()
        with mock.patch.object(app, "dj_ad_break", new=mock.AsyncMock(return_value=True)) as ad:
            await app.schedule_extra_round("ad", None, self.dj)
            self.radio["interject_prompt"] = {"at": 1001.0}
            self.assertTrue(await app.schedule_extra_round("ad", None, self.dj))
            self.assertEqual(ad.await_count, 2)

    async def test_accepted_publication_commits_even_if_other_route_is_cancelled(self):
        async def play(**kwargs):
            kwargs["on_handoff"]()
            raise asyncio.CancelledError()

        app.schedule_take()
        with mock.patch.object(app, "dj_ad_break", side_effect=play):
            with self.assertRaises(asyncio.CancelledError):
                await app.schedule_extra_round("ad", None, self.dj)
        app.schedule_take()
        self.assertFalse(self.radio["sched_first"])

    async def test_unscheduled_operator_ad_does_not_inherit_consumed_slot(self):
        app.schedule_take()
        with mock.patch.object(app, "dj_ad_break", new=mock.AsyncMock(return_value=True)) as ad:
            await app.schedule_extra_round("ad", None, self.dj)
            self.assertTrue(await app.schedule_extra_round("ad", None, self.dj,
                                                         occurrence=""))
            self.assertEqual(ad.await_count, 2)

    def test_independent_clocks_obey_sheet_when_selected_output_is_audible(self):
        self.slots[0]["kind"] = "record"
        cases = [
            ("here", 100.0, "desktop", 999.0, 0.4, ""),
            ("here", 999.0, "desktop", 100.0, 0.4, "the air is quiet"),
            ("here", 999.0, "desktop", 999.0, 0.0, "the air is quiet"),
            ("box", 999.0, "desktop", 100.0, 0.4, ""),
            ("box", 100.0, "desktop", 999.0, 0.4, "the air is quiet"),
            ("both", 100.0, "desktop", 999.0, 0.4, ""),
        ]
        for route, box_at, listener, ack_at, volume, expected in cases:
            with self.subTest(route=route, box_at=box_at, volume=volume):
                self.radio["voice_to"] = route
                with (mock.patch.object(app, "_BOX_LAST_OK", [box_at]),
                      mock.patch.object(app, "_TALK_ACK", {
                          "at": ack_at, "listener": listener, "audible_volume": volume}),
                      mock.patch.object(app, "_CLOCK_HELD", {}),
                      mock.patch.object(app, "_BOX_DOWN", {}),
                      mock.patch.object(app, "_BOX_HOLD", [])):
                    self.assertEqual(app.clock_may_air("ad"), expected)

    def test_published_unacknowledged_app_clip_does_not_hide_real_silence(self):
        self.radio.update(voice_to="here", voice_clips=[{"ts": 1000000}])
        with (mock.patch.object(app, "_BOX_LAST_OK", [999.0]),
              mock.patch.object(app, "_TALK_ACK", {}),
              mock.patch.object(app, "_CLOCK_HELD", {})):
            self.assertEqual(app.clock_may_air("ad"), "the air is quiet")


class ProducedAdHandoffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / "spot.mp3").write_bytes(b"existing audio fixture")
        self.entry = {"id": "spot", "audio": "spot.mp3", "text": "A real finished ad.",
                      "product": "product", "uses": 2, "seed_file": "source.txt",
                      "seed_text": "Real source words.", "seed_mind": "current"}
        self.shelf_row = {"produced": "spot", "id": "prepared"}
        self.radio = {"on": True, "voice_to": "box", "last_ad": 100.0, "chat": []}
        self.shelf = {"ad": [self.shelf_row]}
        self.deliveries = {}
        self.clips = []

        def booth(*args, **kwargs):
            row = {"id": "ad-row", "who": "dj", "kind": "ad", "text": args[0], **kwargs}
            self.radio["chat"].append(row)
            return row

        def publish(clip):
            self.clips.append(clip)
            self.deliveries["delivery"] = {"clip": clip, "state": "published"}
            return "delivery"

        patches = {
            "_RADIO": self.radio, "_SHELF": self.shelf,
            "PRODUCED_ADS_DIR": self.root, "_COORD_SPOT_AT": [0.0],
            "_COORD_SPOT_BUSY": [False], "_GAP_OPEN": {"seconds": 60},
            "_SPEAKING": [False], "_LAST_SYNTH": [0.0], "_BOX_HOLD": [],
            "_BOX_DOWN": {}, "_PAGE_DELIVERIES": self.deliveries,
            "_PAGE_ACKED_LINES": set(), "radio_paused": mock.Mock(return_value=False),
            "_floor_busy": mock.Mock(return_value=False),
            "ad_list": mock.Mock(side_effect=lambda: [self.entry]),
            "ad_update": mock.Mock(), "pipeline_log": mock.Mock(),
            "media_sign": mock.Mock(return_value="signature"),
            "ad_now_set": mock.Mock(side_effect=lambda *a: self.radio.update(ad_now={"at": 1000})),
            "ad_booth_row": mock.Mock(side_effect=booth),
            "page_carries_live": mock.Mock(return_value=False),
            "page_feed_append": mock.Mock(side_effect=publish),
            "_play_on_box": mock.AsyncMock(return_value=False),
            "_episode_stage": mock.Mock(), "ad_aired": mock.Mock(),
            "ad_remember": mock.Mock(), "air_remember": mock.Mock(),
            "speakbox_remember": mock.Mock(), "talk_said_now": mock.Mock(),
            "dj_settings": mock.Mock(return_value={}), "ad_pick": mock.Mock(return_value=None),
        }
        for name, value in patches.items():
            patch = mock.patch.object(app, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        clock = mock.patch.object(app.time, "time", return_value=1000.0)
        clock.start()
        self.addCleanup(clock.stop)

    def test_selection_peeks_without_spending_prepared_row(self):
        self.assertIs(app.coord_spot_ready(), self.entry)
        self.assertEqual(self.shelf["ad"], [self.shelf_row])

    async def test_failed_gap_handoff_preserves_stock_cooldown_and_usage(self):
        self.assertFalse(await app.coord_fill_gap())
        self.assertEqual(self.shelf["ad"], [self.shelf_row])
        self.assertEqual(app._COORD_SPOT_AT, [0.0])
        self.assertEqual(self.radio["last_ad"], 100.0)
        self.assertNotIn("ad_now", self.radio)
        app.ad_update.assert_not_called()
        app.ad_aired.assert_not_called()
        app.speakbox_remember.assert_not_called()

    async def test_missing_file_and_no_route_are_not_success(self):
        self.entry["audio"] = "missing.mp3"
        self.assertFalse(await app._air_produced_ad(self.entry))
        app.ad_booth_row.assert_not_called()
        self.entry["audio"] = "spot.mp3"
        self.radio["voice_to"] = "none"
        self.assertFalse(await app._air_produced_ad(self.entry))
        app._play_on_box.assert_not_awaited()
        app.ad_aired.assert_not_called()
        app._episode_stage.assert_not_called()

    async def test_cancelled_unaccepted_gap_handoff_releases_claim_and_retains_row(self):
        started = asyncio.Event()

        async def play(*args):
            started.set()
            await asyncio.Event().wait()

        with mock.patch.object(app, "_play_on_box", side_effect=play):
            task = asyncio.create_task(app.coord_fill_gap())
            await started.wait()
            self.assertFalse(await app.coord_fill_gap())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.shelf["ad"], [self.shelf_row])
        self.assertFalse(app._COORD_SPOT_BUSY[0])
        app.ad_update.assert_not_called()

    async def test_page_publication_commits_only_handoff_then_ack_credits_once(self):
        app.page_carries_live.return_value = True
        self.radio["voice_to"] = "here"
        self.assertTrue(await app.coord_fill_gap())
        self.assertEqual(self.shelf["ad"], [])
        app.ad_update.assert_called_once_with("spot", uses=3)
        app.ad_aired.assert_not_called()
        app.speakbox_remember.assert_not_called()
        clip = self.clips[0]
        self.assertEqual(clip["row_id"], "ad-row")
        self.assertEqual(clip["remember_text"], self.entry["text"])
        self.assertIsNot(clip["produced_ad"], self.entry)
        app._acknowledge_delivery_lines("delivery", clip)
        app._acknowledge_delivery_lines("delivery", clip)
        app.ad_aired.assert_called_once_with(self.entry, "page")
        app.speakbox_remember.assert_called_once()
        app.air_remember.assert_called_once_with(self.entry["text"], "dj", "ad")

    async def test_page_receipt_before_box_completion_does_not_double_credit(self):
        app.page_carries_live.return_value = True
        self.radio["voice_to"] = "both"

        async def box(*args):
            app._acknowledge_delivery_lines("delivery", self.clips[0])
            return True

        with mock.patch.object(app, "_play_on_box", side_effect=box):
            self.assertTrue(await app._air_produced_ad(self.entry))
        app.ad_aired.assert_called_once_with(self.entry, "page")
        app.air_remember.assert_called_once()

    async def test_published_handoff_survives_cancel_of_second_route(self):
        app.page_carries_live.return_value = True
        self.radio["voice_to"] = "both"
        with mock.patch.object(app, "_play_on_box", side_effect=asyncio.CancelledError()):
            with self.assertRaises(asyncio.CancelledError):
                await app.coord_fill_gap()
        self.assertEqual(self.shelf["ad"], [])
        app.ad_update.assert_called_once_with("spot", uses=3)
        app.ad_aired.assert_not_called()
        self.assertFalse(app._COORD_SPOT_BUSY[0])

    async def test_commit_cannot_remove_replacement_row_with_same_ad_id(self):
        replacement = {"id": "new-prepared", "produced": "spot"}

        async def play(entry, on_handoff):
            self.shelf["ad"] = [replacement]
            on_handoff()
            return True

        with mock.patch.object(app, "_air_produced_ad", side_effect=play):
            self.assertTrue(await app.coord_fill_gap())
        self.assertEqual(self.shelf["ad"], [replacement])

    async def test_zero_work_break_does_not_report_missing_audio_or_refusal_as_aired(self):
        self.entry["audio"] = "gone.mp3"
        self.assertEqual(await app.dj_ad_break(zero_work_only=True), "")
        self.entry["audio"] = "spot.mp3"
        self.assertEqual(await app.dj_ad_break(zero_work_only=True), "")
        self.assertEqual(self.radio["last_ad"], 100.0)
        app.ad_update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
