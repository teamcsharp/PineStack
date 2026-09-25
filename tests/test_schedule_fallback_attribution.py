import unittest
from contextlib import ExitStack
from unittest import mock

import app


class ScheduleFallbackAttributionTests(unittest.IsolatedAsyncioTestCase):
    async def test_newly_ready_system2_slot_preempts_legacy_draw_after_breath(self):
        radio = {"on": True, "sched_pos": {"occurrence": "gallery-now"}}
        runtime = mock.Mock(enabled=True)
        calls = 0

        async def dispatch():
            nonlocal calls
            calls += 1
            if calls == 2:
                radio["on"] = False
                return True
            return False

        runtime.dispatch = mock.AsyncMock(side_effect=dispatch)
        runtime.fallback_due.return_value = True
        with (mock.patch.object(app, "_RADIO", radio),
              mock.patch.object(app, "_system2", return_value=runtime),
              mock.patch.object(app, "radio_paused", return_value=False),
              mock.patch.object(app, "dj_settings", return_value={"talk_radio_mode": True}),
              mock.patch.object(app, "torrent_breath", return_value=0),
              mock.patch.object(app.asyncio, "sleep", new=mock.AsyncMock()),
              mock.patch.object(app, "pipeline_log"),
              mock.patch.object(app, "switchboard_take") as switchboard,
              mock.patch.object(app, "schedule_take") as schedule):
            await app._torrent_talk()
        self.assertEqual(runtime.dispatch.await_count, 2)
        switchboard.assert_not_called()
        schedule.assert_not_called()

    async def run_round(self, kind, *, primary=False, banter=True,
                        policy_kind="", continuity=False, talk=50):
        radio = {"on": True, "now": None, "sched_pos": {
            "preset": "fixture", "index": 1, "slot_id": kind, "started": 900},
            "sched_slot": {"kind": kind}}
        hour = {"id": "isolated-hour", "aired": {}, "schedule": {}}
        log = []
        dj = {"talk_radio_mode": True, "talk_radio": talk, "stream_show": True}
        line = "This is the actual spoken content from the completed recording."

        async def play(road, success):
            if success:
                app.coord_air_note(line, "dj", road)
                return [line]
            return []

        async def banter_play(*args, **kwargs):
            return await play("banter", banter)

        async def primary_play(*args, **kwargs):
            return await play(policy_kind or kind, primary)

        async def emergency(*args, **kwargs):
            return bool(await play("emergency_host", continuity))

        patches = {
            "_RADIO": radio, "_SCHED_LOG": log, "_HOUR_ACTIVE": hour,
            "_SEGMENT_TASK": [], "_SHELF": {},
            "radio_paused": mock.Mock(return_value=False),
            "dj_settings": mock.Mock(return_value=dj),
            "torrent_breath": mock.Mock(return_value=0),
            "quota_target": mock.Mock(return_value=0),
            "switchboard_take": mock.Mock(return_value=None),
            "schedule_take": mock.Mock(return_value={"kind": kind, "id": kind}),
            "schedule_jammed": mock.Mock(return_value=""),
            "prepared_by_kind": mock.Mock(return_value={kind: 1}),
            "gap_kind_policy": mock.Mock(return_value=(
                policy_kind or kind, "recorded fallback chosen" if policy_kind else "")),
            "gap_round_note": mock.Mock(),
            "gap_round_done": mock.Mock(side_effect=lambda *args: radio.update(on=False)),
            "seat_return_if_needed": mock.AsyncMock(),
            "schedule_extra_round": mock.AsyncMock(return_value=None),
            "dj_gallery_round": mock.AsyncMock(side_effect=primary_play),
            "dj_news": mock.AsyncMock(side_effect=primary_play),
            "dj_manager_note": mock.AsyncMock(side_effect=primary_play),
            "dj_deep_round": mock.AsyncMock(side_effect=primary_play),
            "dj_caller": mock.AsyncMock(side_effect=primary_play),
            "dj_call_generated": mock.AsyncMock(return_value={}),
            "dj_banter": mock.AsyncMock(side_effect=banter_play),
            "continuity_air": mock.AsyncMock(side_effect=emergency),
            "active_guest": mock.Mock(return_value=None),
            "pipeline_log": mock.Mock(), "station_flow_event": mock.Mock(),
        }
        with ExitStack() as stack:
            for name, value in patches.items():
                stack.enter_context(mock.patch.object(app, name, value))
            stack.enter_context(mock.patch.object(app.asyncio, "sleep", new=mock.AsyncMock()))
            stack.enter_context(mock.patch.object(app.time, "time", return_value=1000.0))
            await app._torrent_talk()
            self.assertEqual(len(log), 1)
            # A repeated report must not invent a second kept/missed event or
            # add another copy of the fallback's actual audio seconds.
            app.coord_schedule_note(log[0], log[0]["aired"], log[0]["why"])
            radio["fixture_primary_calls"] = {
                road: patches[function].call_args for road, function in {
                    "gallery": "dj_gallery_round", "news": "dj_news",
                    "manager": "dj_manager_note"}.items()}
            radio["fixture_banter_call"] = patches["dj_banter"].call_args
        return radio, hour, log[0]

    async def test_inline_cover_misses_original_road_and_credits_only_banter(self):
        for kind in ("gallery", "news", "manager", "caller", "deep", "guest"):
            with self.subTest(kind=kind):
                radio, hour, row = await self.run_round(kind)
                road = str(app.SCHED_PREP_KIND.get(kind) or kind)
                if road not in app.ALT_PREP_KINDS:
                    road = "other"
                self.assertFalse(row["aired"])
                self.assertFalse(row["requirement_fulfilled"])
                self.assertTrue(row["covered"])
                self.assertEqual(row["served_kind"], "banter")
                self.assertEqual(radio["last_round_served_kind"], "banter")
                self.assertEqual(hour["schedule"][road]["kept"], 0)
                self.assertEqual(hour["schedule"][road]["missed"], 1)
                self.assertEqual(hour["schedule"][road]["covered_by"], {"banter": 1})
                self.assertEqual(set(hour["aired"]), {"banter"})
                self.assertEqual(len(hour["schedule"][road]["outcomes"]), 1)

    async def test_original_road_success_remains_kept(self):
        for kind in ("gallery", "news", "manager", "caller"):
            with self.subTest(kind=kind):
                _, hour, row = await self.run_round(kind, primary=True)
                self.assertTrue(row["aired"])
                self.assertFalse(row["covered"])
                self.assertEqual(row["served_kind"], kind)
                self.assertEqual(hour["schedule"][kind]["kept"], 1)
                self.assertEqual(hour["schedule"][kind]["missed"], 0)
                self.assertEqual(set(hour["aired"]), {kind})

    async def test_policy_caller_cover_is_not_credited_as_original_gallery(self):
        _, hour, row = await self.run_round("gallery", primary=True, policy_kind="caller")
        self.assertFalse(row["aired"])
        self.assertTrue(row["covered"])
        self.assertEqual(row["served_kind"], "caller")
        self.assertIn("recorded fallback chosen", row["why"])
        self.assertEqual(hour["schedule"]["gallery"]["missed"], 1)
        self.assertEqual(hour["schedule"]["gallery"]["covered_by"], {"caller": 1})
        self.assertEqual(set(hour["aired"]), {"caller"})

    async def test_emergency_cover_is_visible_without_satisfying_content_contract(self):
        _, hour, row = await self.run_round("news", banter=False, continuity=True)
        self.assertFalse(row["aired"])
        self.assertTrue(row["covered"])
        self.assertEqual(row["served_kind"], "emergency_host")
        self.assertEqual(hour["aired"], {})
        self.assertEqual(hour["schedule"]["news"]["covered_by"], {"emergency_host": 1})

    async def test_failed_cover_is_not_reported_as_played(self):
        _, hour, row = await self.run_round("manager", banter=False)
        self.assertFalse(row["aired"])
        self.assertFalse(row["covered"])
        self.assertEqual(row["served_kind"], "")
        self.assertIn("no cover aired", row["why"])
        self.assertEqual(hour["aired"], {})
        self.assertNotIn("covered_by", hour["schedule"]["manager"])

    async def test_full_talk_dispatches_completed_original_roads_through_strict_player(self):
        for kind in ("gallery", "news", "manager"):
            with self.subTest(kind=kind):
                radio, hour, row = await self.run_round(kind, primary=True, talk=100)
                self.assertTrue(row["requirement_fulfilled"])
                self.assertEqual(row["served_kind"], kind)
                self.assertEqual(set(hour["aired"]), {kind})
                self.assertTrue(radio["fixture_primary_calls"][kind].kwargs["shelf_only"])
                self.assertIsNone(radio["fixture_banter_call"])

    async def test_full_talk_ready_take_race_uses_only_banked_cover_and_marks_miss(self):
        for kind in ("gallery", "news", "manager"):
            with self.subTest(kind=kind):
                radio, hour, row = await self.run_round(kind, primary=False, talk=100)
                self.assertFalse(row["requirement_fulfilled"])
                self.assertEqual(row["served_kind"], "banter")
                self.assertTrue(radio["fixture_primary_calls"][kind].kwargs["shelf_only"])
                self.assertTrue(radio["fixture_banter_call"].kwargs["shelf_only"])
                self.assertEqual(set(hour["aired"]), {"banter"})

    def test_full_talk_keeps_only_a_matching_verified_shelf_road(self):
        dj = {"talk_radio_mode": True, "talk_radio": 100}
        with (mock.patch.object(app, "_GAP_STOCK_FIRST", [1]),
              mock.patch.object(app, "_RADIO", {}),
              mock.patch.object(app, "gap_stock_kind", return_value="caller") as fallback):
            for kind in ("gallery", "news", "manager"):
                with mock.patch.object(app, "_ready_shelf_row", return_value={"id": kind}) as ready:
                    self.assertEqual(app.gap_kind_policy(kind, dj, now=1000), (kind, ""))
                    ready.assert_called_once_with(kind)
                fallback.assert_not_called()
            with mock.patch.object(app, "_ready_shelf_row", return_value=None):
                chosen, reason = app.gap_kind_policy("gallery", dj, now=1000)
                self.assertEqual(chosen, "caller")
                self.assertIn("100% talk", reason)


if __name__ == "__main__":
    unittest.main()
