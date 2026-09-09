import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class ScheduleReadinessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        app._INVENTORY_PLAN.update({"at": 0.0, "hours": 0.0, "plan": {}})
        app._COMMITS.update({"at": 0.0, "rows": []})
        journal = mock.patch.object(app, "station_flow_event")
        journal.start()
        self.addCleanup(journal.stop)

    def test_ready_requires_current_tint_and_every_audio_take(self) -> None:
        entry = {
            "profile": "current",
            "script": "A: plain words",
            "chunks": 2,
            "made": 2,
            "keys": ["one", "two"],
        }
        with (mock.patch.object(app, "dialogue_tint_required",
                                return_value=True),
              mock.patch.object(app, "_larder_current", return_value=True),
              mock.patch.object(app, "_pantry_key_ready", return_value=True)):
            self.assertFalse(app.dialogue_row_ready("banter", entry))

            entry.update({"script_tinted": "A: tinted words",
                          "script": "A: tinted words", "use": "tinted",
                          "tint": {"coverage": {"met": True, "target": 100,
                                                "version": 4, "strength": 1.0}}})
            entry["made"] = 1
            self.assertFalse(app.dialogue_row_ready("banter", entry))

            entry["made"] = 2
            self.assertTrue(app.dialogue_row_ready("banter", entry))

            entry["off_brief"] = True
            self.assertFalse(app.dialogue_row_ready("banter", entry))

    def test_three_hour_horizon_has_physical_larder_capacity(self) -> None:
        with (mock.patch.object(app, "prepare_target_seconds",
                                return_value=3 * 3600.0),
              mock.patch.object(app, "build_lift", return_value=1.0)):
            self.assertEqual(app.larder_cap(), app._LARDER_MAX * 3)

    def test_news_owes_all_three_hours_not_only_next_slot(self) -> None:
        app._NEWS_WANT.update({"at": 0.0, "secs": 0.0})
        slots = [{"kind": "news", "minutes": 4.0},
                 {"kind": "news", "minutes": 4.0},
                 {"kind": "record", "minutes": 52.0}]
        with (mock.patch.object(app, "news_due",
                                return_value={"starts_in": 60.0,
                                              "owns": 240.0}),
              mock.patch.object(app, "news_prep_ahead", return_value=10800.0),
              mock.patch.object(app, "prepare_target_seconds",
                                return_value=10800.0),
              mock.patch.object(app, "schedule_read", return_value={}),
              mock.patch.object(app, "schedule_slots_now",
                                return_value=("hour", slots)),
              mock.patch.object(app, "news_shelf_most", return_value=18)):
            self.assertEqual(app.news_want_seconds(), 1440.0)

    async def test_tint_progress_resumes_at_first_unfinished_turn(self) -> None:
        # Exercise the individual fallback/resume contract without issuing a
        # real batch request. Batch deferral has its own integration tests.
        first_pass = mock.patch.object(app, "_crystal_round_first_pass", return_value=[])
        repass = mock.patch.object(app, "_crystal_round_repass",
                                  side_effect=lambda turns, rows, *a, **k: (rows, False))
        first_pass.start()
        repass.start()
        self.addCleanup(first_pass.stop)
        self.addCleanup(repass.stop)
        first = "The first sufficiently long line carries the actual fact."
        second = "The second sufficiently long line lands the decision."
        script = f"A: {first}\nB: {second}"
        source = hashlib.sha1(script.encode("utf-8")).hexdigest()
        calls: list[str] = []

        async def partial(text, world, chunks, answering="", keep=None,
                          seen=None, kind="", model="", lesson=""):
            calls.append(text)
            return ("A changed first line with a chained internal rhyme."
                    if len(calls) == 1 else text)

        common = (
            mock.patch.object(app, "crystal_active", return_value=[{"x": 1}]),
            mock.patch.object(app, "crystal_stanzas",
                              return_value=[{"text": "source passage"}]),
            mock.patch.object(app, "crystal_world_prompt", return_value="world"),
            mock.patch.object(app, "surplus", return_value=0.0),
            mock.patch.object(app, "tint_should_stop", return_value=""),
            mock.patch.object(app, "tint_fast_model", return_value="fast-test"),
            mock.patch.object(app, "task_cost", return_value=0.1),
            mock.patch.object(app, "task_note"),
            mock.patch.object(app, "tint_spend_note"),
            mock.patch.object(app, "chunk_answer"),
            mock.patch.object(app, "trail_note"),
            mock.patch.object(app, "pipeline_log"),
            mock.patch.object(app, "banter_turns",
                              return_value=[("A", first), ("B", second)]),
            # #1064: the resume contract is the HOLD contract.
            mock.patch.object(app, "crystal_tint_holds", return_value=True),
        )
        with common[0], common[1], common[2], common[3], common[4], \
                common[5], common[6], common[7], common[8], common[9], \
                common[10], common[11], common[12], common[13], \
                mock.patch.object(app, "tint_evaluate", side_effect=lambda source, output, *a, **k:
                                  {"ok": source != output, "faults": []}), \
                mock.patch.object(app, "crystal_turn", side_effect=partial):
            stopped = await app.crystal_tint(script, "banter", critical=True)

        # #1064: the line that would not rap is cut before the studio; the
        # round is whole on its first bar and the cut is on the paperwork.
        self.assertTrue(stopped["ok"], stopped.get("why"))
        self.assertEqual(stopped["coverage"]["cut"], 1)
        self.assertEqual(stopped["progress"]["source"], source)
        self.assertEqual(len(stopped["progress"]["turns"]), 2)
        self.assertTrue(stopped["progress"]["turns"][1].get("cut"))

        calls.clear()

        async def finish(text, world, chunks, answering="", keep=None,
                         seen=None, kind="", model="", lesson=""):
            calls.append(text)
            self.assertEqual(model, "fast-test")
            return "A changed second line with a nested rhythmic decision."

        common = (
            mock.patch.object(app, "crystal_active", return_value=[{"x": 1}]),
            mock.patch.object(app, "crystal_stanzas",
                              return_value=[{"text": "unused new passage"}]),
            mock.patch.object(app, "crystal_world_prompt", return_value="unused"),
            mock.patch.object(app, "surplus", return_value=0.0),
            mock.patch.object(app, "tint_should_stop", return_value=""),
            mock.patch.object(app, "tint_fast_model", return_value="fast-test"),
            mock.patch.object(app, "task_cost", return_value=0.1),
            mock.patch.object(app, "task_note"),
            mock.patch.object(app, "tint_spend_note"),
            mock.patch.object(app, "chunk_answer"),
            mock.patch.object(app, "trail_note"),
            mock.patch.object(app, "pipeline_log"),
            mock.patch.object(app, "banter_turns",
                              return_value=[("A", first), ("B", second)]),
        )
        with common[0], common[1], common[2], common[3], common[4], \
                common[5], common[6], common[7], common[8], common[9], \
                common[10], common[11], common[12], \
                mock.patch.object(app, "tint_evaluate", side_effect=lambda source, output, *a, **k:
                                  {"ok": source != output, "faults": []}), \
                mock.patch.object(app, "crystal_turn", side_effect=finish):
            finished = await app.crystal_tint(
                script, "banter", progress=stopped["progress"], critical=True)

        self.assertTrue(finished["ok"])
        self.assertEqual(calls, [second])
        self.assertIn("A changed first line", finished["script"])
        self.assertIn("A changed second line", finished["script"])

    async def test_simple_shelf_audio_is_invalidated_when_tint_changes_words(self) -> None:
        row = {"text": "A sufficiently long station line before tint.",
               "key": "old-audio", "seconds": 4.0}
        result = {"ok": True,
                  "script": "A changed station line after crystal tint.",
                  "why": "", "chunks": [], "progress": {}}
        with (mock.patch.object(app, "dialogue_tint_required",
                                return_value=True),
              mock.patch.object(app, "crystal_tint",
                                new=mock.AsyncMock(return_value=result)),
              mock.patch.object(app, "_pantry_save"),
              mock.patch.object(app, "brief_note",
                                return_value={"checked": False, "ok": True})):
            self.assertTrue(await app.ensure_shelf_row_tinted(
                "station_id", row, critical=True))

        self.assertTrue(row["tint_ok"])
        self.assertNotIn("key", row)
        self.assertNotIn("seconds", row)
        self.assertEqual(row["text"], result["script"])

    def test_playout_candidate_order_is_exact_fifo(self) -> None:
        oldest = {"sid": "old", "at": 1.0, "priority": -9}
        newest = {"sid": "new", "at": 2.0, "priority": 9}
        self.assertEqual(app.alt_take_order("caller", [oldest, newest]),
                         [oldest, newest])

    def test_finished_audio_never_projects_beyond_actual_seconds(self) -> None:
        row = {"sid": "ad1", "text": "finished advert", "produced": True,
               "seconds": 10.0}
        prior = dict(app._SHELF)
        app._SHELF.clear()
        app._SHELF["ad"] = [row]
        try:
            with (mock.patch.object(app, "dialogue_tint_required",
                                    return_value=False),
                  mock.patch.object(app, "_larder_profile_signature",
                                    return_value="profile"),
                  mock.patch.object(app, "task_gain", return_value=90.0),
                  mock.patch.object(app, "orch_policy", return_value=False),
                  mock.patch.object(app, "shelf_innings", return_value=1)):
                stock = app.dialogue_stock_items("ad")
        finally:
            app._SHELF.clear()
            app._SHELF.update(prior)
        self.assertEqual(stock[0]["seconds"], 10.0)
        self.assertEqual(stock[0]["projected_seconds"], 10.0)

    def test_four_hour_walk_is_not_capped_at_three_laps(self) -> None:
        slots = [
            {"id": "a", "kind": "caller", "label": "A",
             "minutes": 30.0, "enabled": True},
            {"id": "b", "kind": "caller", "label": "B",
             "minutes": 30.0, "enabled": True},
        ]
        store = {"enabled": True, "active": "test",
                 "presets": {"test": slots}, "hours": {},
                 "day": {}, "month": {}}
        prior = dict(app._RADIO)
        app._RADIO["sched_pos"] = {
            "preset": "test", "index": 0, "started": 1000.0,
            "hour": "", "slot_id": "a"}
        try:
            with (mock.patch.object(app, "schedule_read", return_value=store),
                  mock.patch.object(app, "hour_needs_now", return_value={
                      "caller": {"held": 0.0, "rows": 0}}),
                  mock.patch.object(app.time, "time", return_value=1000.0)):
                rows = app.coord_upcoming(4 * 3600.0)
        finally:
            app._RADIO.clear()
            app._RADIO.update(prior)
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({r["commit_id"] for r in rows}), 8)
        self.assertEqual(rows[-1]["starts_in"], 4 * 3600.0)

    def test_pause_freezes_schedule_deadlines_at_the_resume_playhead(self) -> None:
        slots = [
            {"id": "a", "kind": "caller", "label": "A",
             "minutes": 4.0, "enabled": True},
            {"id": "b", "kind": "ad", "label": "B",
             "minutes": 2.0, "enabled": True},
        ]
        store = {"enabled": True, "active": "test",
                 "presets": {"test": slots}, "hours": {},
                 "day": {}, "month": {}, "prompts": {}}
        prior = dict(app._RADIO)
        app._RADIO.update({
            "paused": True, "paused_sched_elapsed": 50.0,
            "sched_slot": dict(slots[0]),
            "sched_pos": {"preset": "test", "index": 0,
                          "started": 100.0, "hour": "", "slot_id": "a"},
        })
        try:
            with (mock.patch.object(app, "schedule_read", return_value=store),
                  mock.patch.object(app, "hour_needs_now", return_value={
                      "caller": {"held": 0.0, "rows": 0},
                      "ad": {"held": 0.0, "rows": 0}}),
                  mock.patch.object(app.time, "time", return_value=1000.0)):
                self.assertEqual(app.sched_entry_left(), 190.0)
                first = app.coord_upcoming(600.0)[0]
            with (mock.patch.object(app, "schedule_read", return_value=store),
                  mock.patch.object(app, "hour_needs_now", return_value={
                      "caller": {"held": 0.0, "rows": 0},
                      "ad": {"held": 0.0, "rows": 0}}),
                  mock.patch.object(app.time, "time", return_value=5000.0)):
                self.assertEqual(app.sched_entry_left(), 190.0)
                later = app.coord_upcoming(600.0)[0]
        finally:
            app._RADIO.clear()
            app._RADIO.update(prior)
        self.assertEqual(first["starts_in"], 190.0)
        self.assertEqual(later["starts_in"], 190.0)
        self.assertEqual(first["slot_id"], "b")
        self.assertEqual(later["slot_id"], "b")

    def test_commitments_allocate_seconds_and_never_reuse_a_row(self) -> None:
        demand = [
            {"commit_id": "one", "kind": "caller", "road": "caller",
             "label": "one", "starts_in": 60.0, "owns_seconds": 120.0},
            {"commit_id": "two", "kind": "caller", "road": "caller",
             "label": "two", "starts_in": 180.0, "owns_seconds": 120.0},
        ]
        stock = [{"id": f"r{i}", "kind": "caller", "row": {},
                  "entry": {}, "ready": True, "seconds": 70.0,
                  "projected_seconds": 70.0, "available": 0.0,
                  "remaining_airings": 1} for i in range(4)]
        with (mock.patch.object(app, "schedule_demand_entries",
                                return_value=demand),
              mock.patch.object(app, "dialogue_stock_items",
                                return_value=stock)):
            plan = app.commitment_inventory_plan(4.0, fresh=True)
        self.assertEqual(plan["short_seconds"], 0.0)
        self.assertEqual(plan["ready_seconds"], 240.0)
        self.assertEqual(len(plan["selected_ids"]), 4)
        self.assertEqual([len(s["stock"]) for s in plan["slots"]], [2, 2])

    def test_incomplete_assigned_row_prevents_duplicate_writing(self) -> None:
        demand = [{"commit_id": "one", "kind": "gallery",
                   "road": "gallery", "label": "one", "starts_in": 600.0,
                   "owns_seconds": 90.0}]
        stock = [{"id": "g1", "kind": "gallery", "row": {}, "entry": {},
                  "ready": False, "seconds": 0.0,
                  "projected_seconds": 90.0, "available": 0.0,
                  "remaining_airings": 1}]
        with (mock.patch.object(app, "schedule_demand_entries",
                                return_value=demand),
              mock.patch.object(app, "dialogue_stock_items",
                                return_value=stock),
              mock.patch.object(app, "task_cost", return_value=30.0)):
            plan = app.commitment_inventory_plan(4.0, fresh=True)
        self.assertEqual(plan["ready_seconds"], 0.0)
        self.assertEqual(plan["short_seconds"], 0.0)
        self.assertEqual(plan["roads"]["gallery"]["unready_items"], 1)
        self.assertEqual(plan["assigned_room_seconds"], 30.0)
        self.assertEqual(plan["room_seconds"], 30.0)

    def test_commit_board_charges_unfinished_assigned_stock(self) -> None:
        plan = {
            "slots": [{
                "commit_id": "near", "sequence": 0, "kind": "gallery",
                "road": "gallery", "label": "near gallery",
                "in_seconds": 10.0, "owns_seconds": 90.0,
                "ready_seconds": 0.0, "planned_seconds": 90.0,
                "short_seconds": 0.0,
                "stock": [{"id": "g1", "ready": False}],
            }]
        }
        with (mock.patch.object(app, "commitment_inventory_plan",
                                return_value=plan),
              mock.patch.object(app, "task_cost", return_value=100.0),
              mock.patch.object(app, "task_gain", return_value=90.0),
              mock.patch.object(app, "cost_on_piper", return_value=20.0),
              mock.patch.object(app, "may_take_on_piper", return_value=False)):
            board = app.commit_board(ahead=1, fresh=True)
        self.assertEqual(board[0]["commit"], "cut")
        self.assertEqual(board[0]["cost"], 100.0)
        self.assertEqual(board[0]["unfinished_stock"], 1)

    async def test_call_sheet_only_contains_committed_tinted_rows(self) -> None:
        first = {"sid": "b1", "script": "A: first", "prep_kind": "banter"}
        unused = {"sid": "b2", "script": "A: unused", "prep_kind": "banter"}
        prior = list(app._LARDER)
        app._LARDER[:] = [first, unused]
        plan = {"selected_ids": ["b1"], "owed_seconds": 60.0,
                "ready_seconds": 0.0, "planned_seconds": 60.0,
                "short_seconds": 0.0}
        try:
            with (mock.patch.object(app, "commitment_inventory_plan",
                                    return_value=plan),
                  mock.patch.object(app, "dialogue_tint_ready",
                                    return_value=True),
                  mock.patch.object(app, "session_voices",
                                    new=mock.AsyncMock(return_value={"dj": "v"})),
                  mock.patch.object(app, "banter_turns",
                                    return_value=[("A", "first")]),
                  mock.patch.object(app, "_round_chunks",
                                    return_value=[("first", "v", "dj")]),
                  mock.patch.object(app, "pantry_get", return_value=None),
                  mock.patch.object(app, "voice_meta", return_value={}),
                  mock.patch.object(app, "voice_engine_for", return_value="xtts"),
                  mock.patch.object(app, "task_rate", return_value=1.0)):
                sheet = await app.call_sheet(4.0)
        finally:
            app._LARDER[:] = prior
        self.assertEqual(sheet["rounds"], 1)
        self.assertEqual(sheet["lines"], 1)
        self.assertEqual(sheet["obligations"]["selected_rows"], 1)

    def test_retirement_preserves_unheard_unassigned_rows_and_audio(self) -> None:
        keep = {"sid": "keep", "text": "kept words", "key": "keep-key"}
        waste = {"sid": "waste", "text": "unused words", "key": "waste-key"}
        prior_shelf = dict(app._SHELF)
        prior_larder = list(app._LARDER)
        prior_pantry = dict(app._PANTRY)
        app._SHELF.clear()
        app._SHELF["ad"] = [keep, waste]
        app._LARDER.clear()
        app._PANTRY.clear()
        app._PANTRY.update({
            "keep-key": {"clip": {"seconds": 5.0}},
            "waste-key": {"clip": {"seconds": 5.0}},
        })
        plan = {"slots": [{"commit_id": "slot"}],
                "selected_ids": ["keep"], "hours": 4.0}
        try:
            with (mock.patch.object(app, "commitment_inventory_plan",
                                    return_value=plan),
                  mock.patch.object(app, "alt_pin_map",
                                    return_value={"ids": set()}),
                  mock.patch.object(app, "_pantry_save"),
                  mock.patch.object(app, "_larder_save"),
                  mock.patch.object(app, "pipeline_log")):
                gone = app.coord_retire()
            self.assertEqual(gone, 0)
            self.assertEqual(app._SHELF["ad"], [keep, waste])
            self.assertIn("keep-key", app._PANTRY)
            self.assertIn("waste-key", app._PANTRY)
        finally:
            app._SHELF.clear()
            app._SHELF.update(prior_shelf)
            app._LARDER[:] = prior_larder
            app._PANTRY.clear()
            app._PANTRY.update(prior_pantry)

    def test_exact_horizon_clips_the_boundary_segment(self) -> None:
        prior = dict(app._RADIO)
        app._RADIO.update({
            "sched_slot": {"kind": "caller", "label": "current"},
            "sched_pos": {"index": 0, "started": 1.0},
        })
        future = [
            {"kind": "gallery", "road": "gallery", "label": "edge",
             "index": 1, "starts_in": 3500.0, "owns_seconds": 300.0},
            {"kind": "ad", "road": "ad", "label": "outside",
             "index": 2, "starts_in": 3600.0, "owns_seconds": 120.0},
        ]
        try:
            with (mock.patch.object(app, "sched_entry_left",
                                    return_value=600.0),
                  mock.patch.object(app, "coord_upcoming",
                                    return_value=future)):
                demand = app.schedule_demand_entries(1.0)
        finally:
            app._RADIO.clear()
            app._RADIO.update(prior)
        self.assertEqual([row["owns_seconds"] for row in demand],
                         [600.0, 100.0])
        self.assertEqual(sum(row["owns_seconds"] for row in demand), 700.0)

    def test_hour_clock_freezes_during_pause_and_records_pause_yield(self) -> None:
        prior = dict(app._HOUR_ACTIVE)
        app._HOUR_ACTIVE.clear()
        app._HOUR_ACTIVE.update({
            "id": "hour", "last_tick": 100.0, "active_seconds": 100.0,
            "was_paused": True, "pause_started": 90.0,
            "pause_start": {"ready_seconds": 10.0, "tint_ready": 2,
                            "short_seconds": 100.0},
            "pause_total": 0.0, "pauses": [],
        })
        improved = {"ready_seconds": 60.0, "tint_ready": 7,
                    "short_seconds": 60.0, "release_ready": False}
        try:
            with mock.patch.object(app, "radio_paused", return_value=True):
                app.coord_hour_tick(200.0)
            self.assertEqual(app._HOUR_ACTIVE["active_seconds"], 100.0)
            with (mock.patch.object(app, "radio_paused", return_value=False),
                  mock.patch.object(app, "coord_hour_inventory",
                                    return_value=improved),
                  mock.patch.object(app, "coord_save"),
                  mock.patch.object(app, "pipeline_log")):
                app.coord_hour_tick(260.0)
                app.coord_hour_tick(270.0)
            self.assertEqual(app._HOUR_ACTIVE["active_seconds"], 110.0)
            pause = app._HOUR_ACTIVE["pauses"][0]
            self.assertEqual(pause["ready_gain"], 50.0)
            self.assertEqual(pause["tint_gain"], 5)
            self.assertEqual(pause["short_reduced"], 40.0)
        finally:
            app._HOUR_ACTIVE.clear()
            app._HOUR_ACTIVE.update(prior)

    def test_closed_hour_miss_raises_persistent_road_priority(self) -> None:
        prior_active = dict(app._HOUR_ACTIVE)
        prior_hours = list(app._HOURS)
        prior_learning = dict(app._HOUR_LEARNING)
        app._HOURS.clear()
        app._HOUR_LEARNING.clear()
        app._HOUR_ACTIVE.clear()
        app._HOUR_ACTIVE.update({
            "id": "missed", "started_at": 1000.0,
            "active_seconds": 3600.0, "pause_total": 0.0,
            "targets": {"caller": 100.0}, "aired": {"caller": 50.0},
            "schedule": {"caller": {"kept": 0, "missed": 1}},
            "production": {}, "tasks": {}, "baseline": {}, "pauses": [],
            "retired_rows": 0, "retired_clips": 0,
        })
        ending = {"ready_seconds": 80.0, "short_seconds": 20.0}
        try:
            with (mock.patch.object(app, "coord_hour_inventory",
                                    return_value=ending),
                  mock.patch.object(app, "may_take_on_piper",
                                    return_value=True),
                  mock.patch.object(app, "piper_authorise") as authorised,
                  mock.patch.object(app, "coord_hour_start"),
                  mock.patch.object(app, "coord_save"),
                  mock.patch.object(app, "pipeline_log")):
                report = app.coord_hour_close(4600.0)
            self.assertFalse(report["all_requirements_met"])
            self.assertEqual(report["roads"]["caller"]["attainment"], 0.5)
            self.assertGreater(app._HOUR_LEARNING["caller"]["factor"], 1.0)
            authorised.assert_called_once_with("caller", 3600.0)
        finally:
            app._HOUR_ACTIVE.clear()
            app._HOUR_ACTIVE.update(prior_active)
            app._HOURS[:] = prior_hours
            app._HOUR_LEARNING.clear()
            app._HOUR_LEARNING.update(prior_learning)

    def test_half_hour_adherence_is_not_the_cumulative_session(self) -> None:
        # Keep the recent receipt inside this half regardless of when the
        # suite runs; wall time within ten seconds of :00/:30 crossed it.
        now = app.time.mktime((2026, 9, 7, 12, 15, 0, 0, 0, -1))
        half = app._half_key(now)
        prior_log = list(app._SCHED_LOG)
        prior_halves = list(app._HALVES)
        app._SCHED_LOG[:] = [
            {"at": now - 10.0, "aired": True},
            {"at": now - 1900.0, "aired": False},
        ]
        try:
            with (mock.patch.object(app, "schedule_adherence",
                                    return_value={"kept": 9, "missed": 9,
                                                  "rate": 0.5}),
                  mock.patch.object(app, "coord_dead_air",
                                    return_value={"seconds": 0.0}),
                  mock.patch.object(app, "hour_short_kinds",
                                    return_value=[])):
                report = app.coord_close_half(half)
            self.assertEqual(report["kept"], 1)
            self.assertEqual(report["missed"], 0)
            self.assertEqual(report["rate"], 1.0)
        finally:
            app._SCHED_LOG[:] = prior_log
            app._HALVES[:] = prior_halves

    def test_aired_line_is_deduplicated_inside_one_playout_event(self) -> None:
        prior_active = dict(app._HOUR_ACTIVE)
        prior_radio = dict(app._RADIO)
        app._HOUR_ACTIVE.clear()
        app._HOUR_ACTIVE.update({"aired": {}, "seen_lines": {}})
        app._RADIO["sched_slot"] = {"kind": "caller"}
        line = "This sufficiently long caller line should count only once."
        try:
            with (mock.patch.object(app, "radio_paused", return_value=False),
                  mock.patch.object(app.time, "time", return_value=1000.0)):
                app.coord_air_note(line, "caller", "stream")
                app.coord_air_note(line, "caller", "stream")
            self.assertAlmostEqual(app._HOUR_ACTIVE["aired"]["caller"],
                                   len(line) / 14.0, places=2)
        finally:
            app._HOUR_ACTIVE.clear()
            app._HOUR_ACTIVE.update(prior_active)
            app._RADIO.clear()
            app._RADIO.update(prior_radio)

    def test_hour_contract_and_learning_survive_restart(self) -> None:
        prior = {
            "gaps": list(app._GAPS), "halves": list(app._HALVES),
            "plan": dict(app._COORD_PLAN), "bare": dict(app._BARE_ARRIVALS),
            "schedule": list(app._SCHED_LOG), "hours": list(app._HOURS),
            "active": dict(app._HOUR_ACTIVE),
            "learning": dict(app._HOUR_LEARNING),
        }
        try:
            app._GAPS[:] = []
            app._HALVES[:] = []
            app._COORD_PLAN.clear()
            app._BARE_ARRIVALS.clear()
            app._BARE_ARRIVALS["caller"] = 2
            app._SCHED_LOG[:] = [{"at": 1.0, "aired": False}]
            app._HOURS[:] = [{"id": "closed", "score": 75.0}]
            app._HOUR_ACTIVE.clear()
            app._HOUR_ACTIVE.update({"id": "open", "last_tick": 1.0,
                                     "active_seconds": 600.0})
            app._HOUR_LEARNING.clear()
            app._HOUR_LEARNING["caller"] = {"factor": 1.4, "hours": 1}
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "coordinator.json"
                with mock.patch.object(app, "COORD_PATH", path):
                    app.coord_save()
                    app._BARE_ARRIVALS.clear()
                    app._SCHED_LOG.clear()
                    app._HOURS.clear()
                    app._HOUR_ACTIVE.clear()
                    app._HOUR_LEARNING.clear()
                    with mock.patch.object(app.time, "time",
                                           return_value=999.0):
                        app.coord_load()
            self.assertEqual(app._BARE_ARRIVALS["caller"], 2)
            self.assertEqual(app._SCHED_LOG[0]["aired"], False)
            self.assertEqual(app._HOURS[0]["id"], "closed")
            self.assertEqual(app._HOUR_ACTIVE["id"], "open")
            self.assertEqual(app._HOUR_ACTIVE["last_tick"], 999.0)
            self.assertEqual(app._HOUR_LEARNING["caller"]["factor"], 1.4)
        finally:
            app._GAPS[:] = prior["gaps"]
            app._HALVES[:] = prior["halves"]
            app._COORD_PLAN.clear()
            app._COORD_PLAN.update(prior["plan"])
            app._BARE_ARRIVALS.clear()
            app._BARE_ARRIVALS.update(prior["bare"])
            app._SCHED_LOG[:] = prior["schedule"]
            app._HOURS[:] = prior["hours"]
            app._HOUR_ACTIVE.clear()
            app._HOUR_ACTIVE.update(prior["active"])
            app._HOUR_LEARNING.clear()
            app._HOUR_LEARNING.update(prior["learning"])

    def test_phone_calls_are_single_use_not_replay_stock(self) -> None:
        self.assertNotIn("caller", app.SHELF_REUSABLE)
        self.assertNotIn("caller", app.SHELF_REUSE_EVERGREEN)

    def test_phone_calls_leave_the_shelf_in_acceptance_order(self) -> None:
        now = app.time.time()
        newer = {"at": now + 1.0, "entry": {"caller_name": "Newer"}}
        older = {"at": now, "entry": {"caller_name": "Older"}}
        rows = [newer, older]
        with (mock.patch.object(app, "shelf_rows", return_value=rows),
              mock.patch.object(app, "alt_take_order",
                                side_effect=AssertionError(
                                    "call FIFO must not use picker order")),
              mock.patch.object(app, "dialogue_row_ready", return_value=True),
              mock.patch.object(app, "shelf_cast_stale", return_value=False),
              mock.patch.object(app, "_larder_current", return_value=True),
              mock.patch.object(app, "alt_took")):
            picked = app.shelf_take("caller")
        self.assertIs(picked, older)
        self.assertEqual(rows, [newer])

    def test_legacy_ungraded_call_is_not_ready_or_viable(self) -> None:
        entry = {"caller_name": "Doreen", "script": "A: Hello\nC: Hi",
                 "profile": "current", "chunks": 1, "made": 1,
                 "keys": ["call-a"], "script_tinted": "A: Hello\nC: Hi",
                 "use": "tinted"}
        with (mock.patch.object(app, "_larder_current", return_value=True),
              mock.patch.object(app, "_pantry_key_ready", return_value=True)):
            self.assertFalse(app.dialogue_row_viable("caller", entry))
            self.assertFalse(app.dialogue_row_ready("caller", entry))

    def test_candidate_picker_does_not_advertise_legacy_call_as_ready(self) -> None:
        entry = {"caller_name": "Doreen", "script": "A: Hello\nC: Hi",
                 "profile": "current", "prepared": True, "chunks": 1,
                 "made": 1, "keys": ["call-a"],
                 "script_tinted": "A: Hello\nC: Hi", "use": "tinted"}
        row = {"at": app.time.time(), "entry": entry}
        with (mock.patch.object(app, "_larder_current", return_value=True),
              mock.patch.object(app, "_pantry_key_ready", return_value=True)):
            card = app.alt_row_view("caller", row)
        self.assertFalse(card["ready"])
        self.assertFalse(card["usable"])
        self.assertIn("active dialogue contract", card["why"])

    def test_inventory_does_not_assign_legacy_call_to_future_schedule(self) -> None:
        prior = list(app._SHELF.get("caller") or [])
        app._SHELF["caller"] = [{
            "at": app.time.time(),
            "entry": {"caller_name": "Doreen", "script": "A: Hi\nC: Hi",
                      "script_plain": "A: Hi\nC: Hi", "profile": "current",
                      "prepared": True, "chunks": 1, "made": 1,
                      "keys": ["legacy-call"]},
        }]
        try:
            rows = app.dialogue_stock_items(
                "caller", include_unready=True, profile="current",
                tint_required=False)
            self.assertEqual(rows, [])
        finally:
            app._SHELF["caller"] = prior

    def test_accepted_call_contract_is_bound_to_final_script(self) -> None:
        script = "A: Hello Doreen\nC: This is Doreen with my greenhouse story."
        fingerprint = app.call_fingerprint(script)
        entry = {
            "caller_name": "Doreen", "script": script,
            "call": {"contract_version": app.CALL_CONTRACT_VERSION,
                     "topic": "greenhouses", "fingerprint": fingerprint,
                     "quality": {"ok": True}},
        }
        self.assertTrue(app.call_entry_contract(entry))
        entry["script"] += " Changed after approval."
        self.assertFalse(app.call_entry_contract(entry))

    def test_candidate_card_exposes_call_acceptance_proof(self) -> None:
        script = "A: Hello Doreen\nC: This is Doreen with my greenhouse story."
        fingerprint = app.call_fingerprint(script)
        entry = {
            "caller_name": "Doreen", "script": script,
            "script_plain": script, "script_tinted": script,
            "use": "tinted", "profile": "current", "chunks": 1,
            "made": 1, "keys": ["call-a"],
            "call": {"contract_version": app.CALL_CONTRACT_VERSION,
                     "topic": "who owns the town greenhouse",
                     "theme": "heat / DGX Spark",
                     "fingerprint": fingerprint,
                     "quality": {"ok": True, "faults": [],
                                 "novelty": {"similarity": 0.12,
                                             "matched_id": "old-7"}}},
        }
        row = {"at": app.time.time(), "entry": entry}
        with (mock.patch.object(app, "_larder_current", return_value=True),
              mock.patch.object(app, "_pantry_key_ready", return_value=True)):
            card = app.alt_row_view("caller", row)
        self.assertEqual(card["call"]["topic"],
                         "who owns the town greenhouse")
        self.assertEqual(card["call"]["fingerprint"], fingerprint)
        self.assertTrue(card["call"]["quality_ok"])
        self.assertEqual(card["call"]["novelty_score"], 0.12)

    def test_written_call_waiting_for_tint_is_viable_but_not_usable(self) -> None:
        script = app._fallback_call_script(
            "Doreen", "the missing greenhouse roof",
            "The greenhouse fan stopped under the glass.")
        with mock.patch.object(app, "_call_history_scripts", return_value=[]):
            report = app.call_flow_report(
                script, "Doreen", topic="the missing greenhouse roof",
                speakerbox_text="The greenhouse fan stopped under the glass.")
        entry = {
            "caller_name": "Doreen", "script": script,
            "script_plain": script, "profile": "current",
            "call": {"contract_version": app.CALL_CONTRACT_VERSION,
                     "topic": "the missing greenhouse roof",
                     "fingerprint": app.call_fingerprint(script),
                     "quality": report},
        }
        row = {"at": app.time.time(), "entry": entry}
        with (mock.patch.object(app, "_larder_current", return_value=True),
              mock.patch.object(app, "dialogue_tint_ready",
                                return_value=False),
              mock.patch.object(app, "dialogue_audio_ready",
                                return_value=False)):
            card = app.alt_row_view("caller", row)
        self.assertTrue(card["viable"])
        self.assertFalse(card["usable"])
        self.assertFalse(card["ready"])
        self.assertIn("tint", card["why"])

    def test_call_contract_is_rebound_after_tint_changes_active_words(self) -> None:
        plain = app._fallback_call_script(
            "Doreen", "the missing greenhouse roof",
            "The greenhouse fan stopped under the glass.")
        tinted = plain.replace("good to have you", "glad you reached us")
        entry = {
            "caller_name": "Doreen", "script": tinted,
            "script_plain": plain, "script_tinted": tinted,
            "use": "tinted",
            "call": {"topic": "the missing greenhouse roof",
                     "speakerbox_text":
                         "The greenhouse fan stopped under the glass.",
                     "contract_version": app.CALL_CONTRACT_VERSION,
                     "fingerprint": app.call_fingerprint(plain),
                     "quality": {"ok": True}},
        }
        self.assertFalse(app.call_entry_contract(entry))
        with mock.patch.object(app, "_call_history_scripts", return_value=[]):
            report = app.call_entry_regrade(entry)
        self.assertTrue(report["ok"], report["faults"])
        self.assertTrue(app.call_entry_contract(entry))
        self.assertEqual(entry["call"]["fingerprint"],
                         app.call_fingerprint(tinted))

    async def test_completed_tint_that_breaks_call_contract_is_not_voiced(self) -> None:
        entry = {
            "caller_name": "Doreen", "script": "A: tinted",
            "script_tinted": "A: tinted", "use": "tinted",
            "brief": {"checked": True, "ok": True},
        }
        with (mock.patch.object(app, "dialogue_tint_required",
                                return_value=True),
              mock.patch.object(app, "_larder_current", return_value=True),
              mock.patch.object(app, "call_entry_regrade",
                                return_value={"ok": False,
                                              "faults": ["broken opening"]}),
              mock.patch.object(app, "_pantry_save"),
              mock.patch.object(app, "_larder_save"),
              mock.patch.object(app, "pipeline_log")):
            accepted = await app.ensure_entry_tinted(entry, "caller")
        self.assertFalse(accepted)

    def test_rejected_completed_call_tint_is_removed_from_inventory(self) -> None:
        entry = {
            "prep_kind": "caller", "caller_name": "Doreen",
            "script": "A: tinted", "script_tinted": "A: tinted",
            "use": "tinted", "call": {
                "quality": {"ok": False, "faults": ["broken opening"]}},
        }
        row = {"entry": entry}
        old_shelf = app._SHELF
        old_pantry = app._PANTRY
        try:
            app._SHELF = {"caller": [row]}
            app._PANTRY = {}
            with (mock.patch.object(app, "_pantry_save"),
                  mock.patch.object(app, "pipeline_log")):
                retired = app.retire_rejected_call_entry(entry)
            self.assertTrue(retired)
            self.assertTrue(entry["discarded"])
            self.assertEqual(app._SHELF["caller"], [])
        finally:
            app._SHELF = old_shelf
            app._PANTRY = old_pantry

    def test_shelved_call_is_persisted_immediately(self) -> None:
        old_shelf = app._SHELF
        try:
            app._SHELF = {}
            with (mock.patch.object(app, "_pantry_save") as saved,
                  mock.patch.object(app, "arrears_paid"),
                  mock.patch.object(app, "cast_signature", return_value={}),
                  mock.patch.object(app, "brief_note",
                                    return_value={"checked": True,
                                                  "ok": True}),
                  mock.patch.object(app, "alt_sid", return_value="caller-1"),
                  mock.patch.object(app, "alt_shelf_trim")):
                app.shelf_put(
                    "caller", {"entry": {"caller_name": "Doreen",
                                           "script": "A: hello"}})
            saved.assert_called_once_with(True)
            self.assertEqual(len(app._SHELF["caller"]), 1)
        finally:
            app._SHELF = old_shelf

    def test_complete_phone_call_contract_passes(self) -> None:
        script = """A: The request line is ringing. Pine Box FM, you're live; go ahead.
C: Hi, this is Doreen, calling from the south side.
B: Doreen, welcome to the show. What happened to the greenhouse roof?
C: My greenhouse roof vanished during the storm while my red tomato plants stayed dry.
A: The greenhouse roof vanished? What was underneath it when you looked up?
C: My red tomato plants were underneath it, and every leaf was perfectly dry.
B: Those dry tomato leaves are strange. Who else saw the missing roof?
C: My neighbor June saw it, brought a ladder, and found one blue hinge in the yard.
B: June and the blue hinge make this feel real. We are sending the repair van.
C: That resolves it for me. I will keep June close and wait for the repair van.
A: Doreen, thank you for calling. Keep June close and stay with Pine Box FM."""
        with mock.patch.object(app, "_call_history_scripts", return_value=[]):
            report = app.call_flow_report(
                script, "Doreen", topic="the missing greenhouse roof")
        self.assertTrue(report["ok"], report["faults"])
        self.assertGreaterEqual(report["caller_turns"], 3)
        self.assertGreaterEqual(report["answered_questions"], 2)
        self.assertTrue(report["topic"]["host"])
        self.assertTrue(report["topic"]["caller"])
        self.assertTrue(report["resolved"])

    def test_complete_call_fallback_itself_passes_the_contract(self) -> None:
        with (mock.patch.object(app, "_call_history_scripts", return_value=[]),
              mock.patch.object(app.time, "time", return_value=1234567890.0)):
            for number in range(24):
                name = f"Caller {number}"
                script = app._fallback_call_script(
                    name, "who should own the town greenhouse",
                    "the copper fan whistles under the greenhouse glass")
                report = app.call_flow_report(
                    script, name, topic="who should own the town greenhouse",
                    speakerbox_text=(
                        "the copper fan whistles under the greenhouse glass"))
                self.assertTrue(report["ok"], (name, report["faults"]))
                self.assertGreaterEqual(report["answered_questions"], 2)
                self.assertGreaterEqual(report["caller_share"], 0.35)
                self.assertTrue(report["speakerbox"]["caller"])
                self.assertTrue(report["speakerbox"]["hosts"])
                self.assertTrue(report["resolved"])

    def test_fallback_identity_is_driven_by_its_speakerbox_pivot(self) -> None:
        first = app._fallback_call_script(
            "Doreen", "heat",
            "A brass telescope arrived under a wool blanket. Its cracked "
            "lens projected a blue orchard across the garage wall.")
        second = app._fallback_call_script(
            "Marlowe", "heat",
            "Three library cards fell from a locked violin case. A penciled "
            "map on the last card ended beneath the courthouse stairs.")
        with mock.patch.object(app, "_call_history_scripts", return_value=[{
                "id": "first", "name": "Doreen", "script": first}]):
            report = app.call_novelty(second)
        self.assertTrue(report["ok"], report)

    def test_caller_must_hand_speakerbox_pivot_to_a_host(self) -> None:
        source = "the copper fan whistles under the greenhouse glass"
        script = app._fallback_call_script(
            "Doreen", "who should own the town greenhouse", source)
        broken = script.replace(source, "another unrelated thought")
        with mock.patch.object(app, "_call_history_scripts", return_value=[]):
            report = app.call_flow_report(
                broken, "Doreen", topic="who should own the town greenhouse",
                speakerbox_text=source)
        self.assertFalse(report["ok"])
        self.assertFalse(report["speakerbox"]["caller"])
        self.assertTrue(any("Speakerbox" in fault
                            for fault in report["faults"]))

    def test_caller_must_resolve_immediately_before_signoff(self) -> None:
        script = app._fallback_call_script(
            "Doreen", "who should own the town greenhouse",
            "the copper fan whistles under the greenhouse glass")
        turns = app.banter_turns(script, "Doreen")
        del turns[-2]
        broken = "\n".join(f"{m}: {t}" for m, t in turns)
        with mock.patch.object(app, "_call_history_scripts", return_value=[]):
            report = app.call_flow_report(
                broken, "Doreen", topic="who should own the town greenhouse",
                speakerbox_text=(
                    "the copper fan whistles under the greenhouse glass"))
        self.assertFalse(report["ok"])
        self.assertFalse(report["resolved"])
        self.assertTrue(any("resolve" in fault for fault in report["faults"]))

    async def test_scheduled_banter_call_uses_prepared_call_first(self) -> None:
        dj = {"talk_radio_mode": True, "talk_radio": 100}
        with (mock.patch.object(
                  app, "dj_caller",
                  new=mock.AsyncMock(return_value=["caller: ready"])
              ) as shelf,
              mock.patch.object(
                  app, "dj_call_generated",
                  new=mock.AsyncMock(return_value={"lines": ["live"]})
              ) as live):
            aired = await app.schedule_extra_round(
                "banter_caller", {"id": "track"}, dj)
        self.assertTrue(aired)
        shelf.assert_awaited_once_with({"id": "track"}, shelf_only=True)
        live.assert_not_awaited()

    async def test_full_talk_never_waits_on_live_call_writing(self) -> None:
        dj = {"talk_radio_mode": True, "talk_radio": 100}
        with (mock.patch.object(
                  app, "dj_caller", new=mock.AsyncMock(return_value=[])),
              mock.patch.object(app, "dj_call_generated",
                                new=mock.AsyncMock()) as live,
              mock.patch.object(app, "prep_one", return_value=None) as prep,
              mock.patch.object(app, "fire_and_forget",
                                side_effect=lambda work: work.close()),
              mock.patch.object(app, "pipeline_log")):
            aired = await app.schedule_extra_round(
                "banter_caller", {"id": "track"}, dj)
        self.assertFalse(aired)
        prep.assert_called_once_with("caller")
        live.assert_not_awaited()

    async def test_full_talk_ad_is_one_zero_work_break(self) -> None:
        dj = {"talk_radio_mode": True, "talk_radio": 100}
        old_first = app._RADIO.get("sched_first")
        try:
            with mock.patch.object(app, "dj_ad_break",
                                   new=mock.AsyncMock(return_value="spot")) as ad:
                app._RADIO["sched_first"] = True
                self.assertTrue(await app.schedule_extra_round("ad", None, dj))
                ad.assert_awaited_once_with(zero_work_only=True, on_handoff=mock.ANY)
                app._RADIO["sched_first"] = False
                self.assertIsNone(
                    await app.schedule_extra_round("ad", None, dj))
                self.assertEqual(ad.await_count, 1)
        finally:
            if old_first is None:
                app._RADIO.pop("sched_first", None)
            else:
                app._RADIO["sched_first"] = old_first

    async def test_full_talk_banter_refuses_live_writing_when_shelf_empty(
            self) -> None:
        with (mock.patch.object(app, "dj_settings", return_value={
                  "banter": True, "banter_min_lines": 2,
                  "banter_max_lines": 3}),
              mock.patch.object(app, "seat_away_who", return_value=""),
              mock.patch.object(app, "_LARDER", []),
              mock.patch.object(app, "banter_material") as live_material):
            self.assertEqual(await app.dj_banter(shelf_only=True), [])
        live_material.assert_not_called()

    def test_full_talk_has_only_a_transport_seam_and_fast_watch(self) -> None:
        dj = {"talk_radio_mode": True, "talk_radio": 100,
              "talk_quiet_most": 95}
        with mock.patch.object(app, "dj_settings", return_value=dj):
            self.assertLess(app.torrent_breath(dj), 0.4)
            # 2026-09-08: the operator's rule is "at longest a 10 second
            # intermission", and detection at twelve plus the two-second
            # tick plus the announce cannot meet it by arithmetic. Eight
            # leaves a ten-to-eleven-second worst case. Measured before the
            # change: 56% of intermissions ran over ten seconds.
            # 2026-09-09 (#1157): four, not eight. At eight, detection plus
            # the two-second tick plus the announce spends the whole
            # ten-second allowance on NOTICING and leaves nothing for the
            # announce itself to be late in.
            self.assertEqual(app.talk_quiet_limit(), 4.0)
            self.assertEqual(app.talk_watch_tick(), 2.0)

    def test_full_talk_replaces_live_only_round_with_recorded_talk(self) -> None:
        dj = {"talk_radio_mode": True, "talk_radio": 100}
        with (mock.patch.object(app, "gap_stock_kind",
                                return_value="banter")):
            kind, why = app.gap_kind_policy("deep", dj, now=1234.0)
            backed_kind, backed_why = app.gap_kind_policy(
                "gallery", dj, now=1234.0)
        self.assertEqual(kind, "banter")
        self.assertIn("100% talk", why)
        self.assertEqual(backed_kind, "banter")
        self.assertIn("zero-work-to-air", backed_why)

    async def test_background_prep_does_not_borrow_live_segment_prompt(
            self) -> None:
        old_prompt = app._RADIO.get("sched_prompt")
        old_interject = app._RADIO.get("interject_prompt")
        app._RADIO["sched_prompt"] = "ANGRY MANAGER SEGMENT"
        app._RADIO.pop("interject_prompt", None)
        try:
            self.assertEqual(app._schedule_prompt_clause(),
                             "ANGRY MANAGER SEGMENT")
            app.prep_context_set("caller")
            self.assertEqual(app._schedule_prompt_clause(), "")
        finally:
            app.prep_context_clear()
            if old_prompt is None:
                app._RADIO.pop("sched_prompt", None)
            else:
                app._RADIO["sched_prompt"] = old_prompt
            if old_interject is None:
                app._RADIO.pop("interject_prompt", None)
            else:
                app._RADIO["interject_prompt"] = old_interject

    def test_brief_location_may_share_one_generic_topic_word(self) -> None:
        topic = ("the heat coming off the DGX Spark, the machine this "
                 "station runs on, and the strange things it does when hot")
        source = "The DGX Spark fan pushes heat into the computer room."
        script = app._fallback_call_script("Doreen", topic, source)
        turns = app.banter_turns(script, "Doreen")
        turns[1] = (
            "C", "Hi, this is Doreen, calling from a motel walkway "
            "beside the ice machine.")
        script = "\n".join(f"{marker}: {said}" for marker, said in turns)
        with mock.patch.object(app, "_call_history_scripts", return_value=[]):
            report = app.call_flow_report(
                script, "Doreen", topic=topic, speakerbox_text=source)
        self.assertTrue(report["ok"], report["faults"])
        self.assertTrue(report["intro_only"])
        self.assertEqual(report["intro_topic_terms"], ["machine"])

    def test_fallback_keeps_numeric_switchboard_id_out_of_tinted_words(self) -> None:
        script = app._fallback_call_script(
            "Doreen", "the missing greenhouse roof",
            "The greenhouse fan stopped under the glass.", "line 91,289")
        opening = app.banter_turns(script, "Doreen")[0][1]
        self.assertIn("request line", opening.lower())
        self.assertNotRegex(opening, r"\d")

    def test_host_questions_must_follow_the_callers_actual_detail(self) -> None:
        script = app._fallback_call_script(
            "Doreen", "who should own the town greenhouse",
            "The copper fan whistles under the greenhouse glass")
        turns = app.banter_turns(script, "Doreen")
        # Break both evidence-based follow-ups while leaving their question
        # marks, turn balance and topic coverage intact.
        for at in (4, 6):
            marker, _said = turns[at]
            turns[at] = (marker,
                         "Why did the purple submarine bother you so much?")
        broken = "\n".join(f"{m}: {t}" for m, t in turns)
        with mock.patch.object(app, "_call_history_scripts", return_value=[]):
            report = app.call_flow_report(
                broken, "Doreen", topic="who should own the town greenhouse",
                speakerbox_text=(
                    "The copper fan whistles under the greenhouse glass"))
        self.assertFalse(report["ok"])
        self.assertLess(report["grounded_questions"], 2)
        self.assertTrue(any("concrete detail" in fault
                            for fault in report["faults"]))

    def test_unrelated_speakerbox_hit_is_not_call_material(self) -> None:
        topic = "heat from the DGX Spark computer"
        bad = app.speakbox_topic_relevance(
            topic, "Mariah danced at a club while the Jeffersons played.")
        good = app.speakbox_topic_relevance(
            topic, "The DGX fan pushes heat off the computer rack.")
        self.assertFalse(bad["ok"])
        self.assertTrue(good["ok"])
        self.assertIn("dgx", good["shared"])

    def test_truncated_speakerbox_hit_is_not_call_material(self) -> None:
        report = app.speakbox_topic_relevance(
            "heat from the DGX Spark computer",
            "My track was actually hot so I")
        self.assertFalse(report["ok"])
        self.assertFalse(report["complete"])

    def test_call_source_relevance_understands_heat_synonyms(self) -> None:
        report = app.speakbox_topic_relevance(
            "heat from the DGX Spark computer",
            "When the temperature drops, the ice cream machines freeze up.")
        self.assertTrue(report["ok"], report)
        self.assertIn("temperature", report["shared"])

    def test_duplicate_speakerbox_seed_is_not_assigned_to_two_calls(self) -> None:
        source = "The copper fan whistles under the greenhouse glass."
        script = app._fallback_call_script(
            "Doreen", "who should own the town greenhouse", source)
        history = [{
            "id": "older", "name": "June",
            "speakerbox_text": source,
            "script": "A: A wholly unrelated archived conversation.",
        }]
        with mock.patch.object(app, "_call_history_scripts",
                               return_value=history):
            report = app.call_flow_report(
                script, "Doreen", topic="who should own the town greenhouse",
                speakerbox_text=source)
        self.assertFalse(report["ok"])
        self.assertFalse(report["speakerbox_novelty"]["ok"])
        self.assertTrue(any("already assigned" in fault
                            for fault in report["faults"]))

    async def test_semantic_seed_skips_a_reserved_call_source(self) -> None:
        hits = [
            {"file": "used.md", "text": "first source.", "score": 0.9},
            {"file": "fresh.md", "text": "second source.", "score": 0.8},
        ]
        with (mock.patch.object(app, "speakbox_search",
                                new=mock.AsyncMock(return_value=hits)),
              mock.patch.object(app, "crystal_active", return_value=[]),
              mock.patch.object(app, "_vector_access_log"),
              mock.patch.object(app, "_load_vectors",
                                return_value={"chunks": []}),
              mock.patch.dict(app._RADIO,
                              {"seed_pins": {}, "seed_blocks": []})):
            seed = await app.speakbox_semantic_seed(
                "heat", avoid_files={"used.md"})
        self.assertEqual(seed["file"], "fresh.md")

    async def test_topic_bound_semantic_seed_searches_a_wide_shelf(self) -> None:
        search = mock.AsyncMock(return_value=[])
        with (mock.patch.object(app, "speakbox_search", search),
              mock.patch.object(app, "crystal_active", return_value=[]),
              mock.patch.dict(app._RADIO,
                              {"seed_pins": {}, "seed_blocks": []})):
            seed = await app.speakbox_semantic_seed(
                "heat", require_overlap=True)
        self.assertEqual(seed, {})
        self.assertEqual(search.await_args.kwargs["k"], 32)

    async def test_call_plot_reserves_sources_already_waiting_in_fifo(self) -> None:
        old_shelf = app._SHELF
        try:
            app._SHELF = {"caller": [
                {"entry": {"call": {"source": "used.md"}}}]}
            semantic = mock.AsyncMock(return_value={
                "file": "fresh.md", "text": "The heat stays in motion.",
                "topic_relevance": {"ok": True}})
            with (mock.patch.object(app, "dj_settings",
                                    return_value={"speakbox_rate": 1}),
                  mock.patch.object(app, "speakbox_semantic_seed", semantic)):
                _clause, seed = await app.call_plot_clause("the heat")
            self.assertEqual(seed["file"], "fresh.md")
            self.assertEqual(semantic.await_args.kwargs["avoid_files"],
                             {"used.md"})
        finally:
            app._SHELF = old_shelf

    def test_semantically_corrupted_call_tint_is_refused(self) -> None:
        plain = """A: Doreen, you are on Pine Box FM. What happened with the greenhouse?
C: Hi, this is Doreen. The greenhouse fan stopped in the heat.
A: The stopped fan matters. What did the thermometer show?
C: It showed ninety degrees beside my red tomato plants.
B: Those tomato plants need help. Who came to the greenhouse?
C: My neighbor June came with a copper fan and cold water.
B: June and the copper fan give us a plan.
A: Doreen, thank you for calling. Stay with Pine Box FM."""
        tinted = """A: Doreen, you are on Pine Box FM. What happened with the greenhouse?
C: Hi, this is Doreen. The greenhouse fan stopped in the heat.
A: The stopped fan makes a plan ignite.
C: The stopped fan makes a plan ignite. Ninety degrees made the night feel right.
B: Ninety degrees made the night feel right. Who came through tonight?
C: Ninety degrees made the night feel right. Who came through tonight? June had water.
B: June and the copper fan give us a plan.
A: So Brak, how your man got a show that's whack?"""
        with mock.patch.object(app, "_call_history_scripts", return_value=[]):
            report = app.call_flow_report(
                tinted, "Doreen", topic="greenhouse heat and the stopped fan",
                source_script=plain)
        self.assertFalse(report["ok"])
        self.assertFalse(report["tint"]["ok"])
        self.assertTrue(any("copied the prior turn" in fault
                            or "lost a name" in fault
                            or "question into a statement" in fault
                            for fault in report["faults"]))

    def test_faithful_question_synonyms_survive_call_tint_gate(self) -> None:
        plain = "A: When you noticed the box fan, what did you do next, and what changed after that?"
        tinted = "A: When you saw the box fan, what action followed, and what shifted then?"
        report = app.call_tint_report(plain, tinted)
        self.assertTrue(report["ok"], report["faults"])

    def test_call_tint_must_keep_a_spoken_signoff(self) -> None:
        plain = "A: Thank you for calling, Doreen. Stay with Pine Box FM."
        tinted = "A: For calling Doreen, stay with Pine Box FM."
        report = app.call_tint_report(plain, tinted, ("Doreen",))
        self.assertFalse(report["ok"])
        self.assertTrue(any("sign-off" in fault for fault in report["faults"]))

    async def test_phone_tint_uses_anchor_retry_before_stalling_round(self) -> None:
        source = "When you noticed the box fan, what did you do next, and what changed after that?"
        faithful = "When you saw the box fan, what action followed next, and what shifted after that?"
        with (mock.patch.object(
                app, "ask_model",
                mock.AsyncMock(side_effect=[
                    "Mars collapsed into an unrelated statement.",
                    "Why did the purple submarine disappear?",
                    faithful])),
              mock.patch.object(app, "tint_model_for", return_value="fast"),
              # This test isolates the semantic anchor retry. Rhyme and
              # source-copy grading are exercised in test_tint_contract.
              mock.patch.object(app, "tint_evaluate", return_value={"ok": True, "faults": []})):
            result = await app.crystal_turn(
                source, "world", [{"text": "A compact style sample."}],
                kind="caller")
        self.assertEqual(result, faithful)

    def test_exact_phone_call_duplicate_is_refused(self) -> None:
        script = """A: Doreen, you are on. What happened?
C: Hi, this is Doreen. My greenhouse roof vanished during the storm.
A: The roof vanished? What was underneath it?
C: My red tomato plants were underneath it and every leaf was dry.
B: Those dry leaves are strange. Who else saw it?
C: My neighbor June saw it and found one blue hinge in the yard.
B: June and the hinge make it real. We will send the repair van.
A: Doreen, thank you for calling. Stay with Pine Box FM."""
        old = [{"id": "old-call", "name": "Doreen", "topic": "storms",
                "script": script}]
        with mock.patch.object(app, "_call_history_scripts", return_value=old):
            novelty = app.call_novelty(script)
        self.assertFalse(novelty["ok"])
        self.assertTrue(novelty["exact"])
        self.assertEqual(novelty["matched_id"], "old-call")

    def test_completed_call_persists_topic_transcript_and_fingerprint(self) -> None:
        prior_live = dict(app._CALL_LIVE)
        prior_chat = list(app._RADIO.get("chat") or [])
        prior_ring = list(app._RADIO.get("call_log") or [])
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "calls.json"
                with (mock.patch.object(app, "CALL_LOG_PATH", path),
                      mock.patch.object(app, "pipeline_log")):
                    app.call_line_free()
                    self.assertTrue(app.call_line_take(
                        "Doreen", {"topic": "greenhouses", "theme": "weather"}))
                    app.call_line_transcript([
                        {"who": "dj", "text": "Doreen, what happened?"},
                        {"who": "caller", "name": "Doreen",
                         "text": "This is Doreen. The roof vanished."},
                    ])
                    app.call_ended("Doreen", "line 3", app.time.time() - 10,
                                   {"id": "bye", "text": "the host signs off"},
                                   2, "calm")
                    rows = app.call_log_read()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["topic"], "greenhouses")
            self.assertEqual(len(rows[0]["transcript"]), 2)
            self.assertTrue(rows[0]["fingerprint"])
        finally:
            app._CALL_LIVE.clear()
            app._CALL_LIVE.update(prior_live)
            app._RADIO["chat"] = prior_chat
            app._RADIO["call_log"] = prior_ring

    def test_call_archive_writer_accepts_timed_transcript_rows(self) -> None:
        transcript = [("dj", "Welcome, Doreen.", 1.2),
                      ("caller", "This is Doreen.", 1.0)]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (mock.patch.object(app, "RADIO_CACHE", root),
                  mock.patch("subprocess.run")):
                app._cache_call_recording(b"RIFF", transcript, "Doreen",
                                          "call123")
            pages = list((root / "calls").glob("*.md"))
            self.assertEqual(len(pages), 1)
            text = pages[0].read_text(encoding="utf-8")
            self.assertIn("Welcome, Doreen.", text)
            self.assertIn("This is Doreen.", text)

    async def test_active_database_theme_anchors_every_generated_call(self) -> None:
        theme = {"name": "municipal gardens",
                 "text": "who should own the town greenhouse"}
        with (mock.patch.object(app, "active_theme", return_value=theme),
              mock.patch.object(app, "themes_read",
                                return_value={"strength": 0, "doc": ""}),
              mock.patch.object(app, "speakbox_quote",
                                new=mock.AsyncMock(return_value={}))):
            topic, _seed = await app.caller_topic()
        self.assertIn(theme["text"], topic)

    def test_pause_defers_independent_phone_clock(self) -> None:
        app._CLOCK_HELD["caller"] = app.time.time()
        with mock.patch.object(app, "radio_paused", return_value=True):
            self.assertEqual(app.clock_may_air("caller"), "")
        self.assertNotIn("caller", app._CLOCK_HELD)

    async def test_generated_call_trigger_banks_instead_of_opening_live_paused(self) -> None:
        queued = mock.AsyncMock(return_value=True)

        def accept_background(coro):
            coro.close()

        with (mock.patch.object(app, "radio_paused", return_value=True),
              mock.patch.object(app, "prep_one", queued),
              mock.patch.object(app, "fire_and_forget",
                                side_effect=accept_background) as dispatched,
              mock.patch.object(app, "pipeline_log"),
              mock.patch.object(app, "call_line_take") as took):
            result = await app.dj_call_generated()
        self.assertEqual(result["state"], "banking")
        queued.assert_called_once_with("caller")
        dispatched.assert_called_once()
        took.assert_not_called()

    def test_track_talk_contract_requires_exact_record_and_rejects_debris(self) -> None:
        track = {"id": "t1", "title": "One Above All", "artist": "Godspeed"}
        good = ("Godspeed bring One Above All into the room with a slow, "
                "weathered rise. Keep that tension under the next breath "
                "because the record is still opening around us.")
        report = app.track_talk_text_report(good, track, "intro")
        self.assertTrue(report["ok"], report["faults"])
        bad = "A: As an AI, here are the full lyrics.\nB: Chorus: la la la."
        report = app.track_talk_text_report(bad, track, "intro")
        self.assertFalse(report["ok"])
        self.assertIn("the line does not name its exact title or artist",
                      report["faults"])
        flattened = (
            "One Above All stays with us. | Speaker | Transcript | |---|---| "
            "| Narrator | Godspeed build a patient atmosphere around the "
            "record and let its final note settle into the room."
        )
        report = app.track_talk_text_report(flattened, track, "outro")
        self.assertFalse(report["ok"])
        self.assertIn("the line looks like a transcript instead of one link",
                      report["faults"])
        echoed = ("The world of MF DOOM: mask mythology and comic-book "
                  "vengeance. One Above All by Godspeed opens with a patient "
                  "rise and keeps a clear melodic shape around the room.")
        report = app.track_talk_text_report(echoed, track, "intro")
        self.assertFalse(report["ok"])
        self.assertIn("the line repeats tint direction instead of presenter speech",
                      report["faults"])

    def test_track_talk_tint_governor_restores_identity_and_caps_verse(self) -> None:
        track = {"id": "t1", "title": "Courage",
                 "artist": "The Whitest Boy Alive"}
        drifted = " ".join(["weathered"] * 110)
        governed, report = app.track_talk_tint_govern(
            drifted, track, "intro")
        self.assertTrue(report["ok"], report["faults"])
        self.assertTrue(report["governed"])
        self.assertIn("Courage", governed)
        self.assertLessEqual(report["words"], 90)

    def test_track_talk_tint_governor_strips_exact_style_card_echo(self) -> None:
        track = {"id": "t1", "title": "Courage",
                 "artist": "The Whitest Boy Alive"}
        source = ("Courage opens with a patient pulse and a clean guitar "
                  "figure that leaves plenty of room around the vocal.")
        world = "The world of MF DOOM: mask mythology and cartoon menace."
        candidate = (world + " Courage comes in with that patient pulse and "
                     "clean guitar figure, leaving plenty of room around the "
                     "vocal before the record takes over.")
        governed, report = app.track_talk_tint_govern(
            candidate, track, "intro", source, world)
        self.assertTrue(report["ok"], report["faults"])
        self.assertTrue(report["governed"])
        self.assertFalse(governed.startswith("The world of"))

    def test_track_talk_tint_must_keep_the_clean_links_observation(self) -> None:
        track = {"id": "t1", "title": "SCIENCE TOUR",
                 "artist": "slowerpace"}
        source = ("SCIENCE TOUR opens with a patient electronic pulse and a "
                  "wide arrangement that gradually pulls the room forward.")
        drifted = ("SCIENCE TOUR stays at the center. Who dance aight / gave "
                   "it to a comic-book fighter / milk and silk under lights "
                   "while somebody starts another unrelated battle.")
        _governed, report = app.track_talk_tint_govern(
            drifted, track, "outro", source)
        self.assertFalse(report["ok"])
        self.assertFalse(report["fidelity"]["ok"])
        self.assertIn("the tint lost the clean link's concrete observation",
                      report["faults"])

    def test_track_talk_queue_survives_restart_with_its_words_and_owner(self) -> None:
        prior = dict(app._TRACK_TALK)
        prior_loaded = app._TRACK_TALK_LOADED[0]
        prior_saved = app._TRACK_TALK_SAVED[0]
        prior_queue = list(app._RADIO.get("queue") or [])
        track = {"id": "t1", "title": "One Above All", "artist": "Godspeed",
                 "at": app.time.time()}
        later = {"id": "t2", "title": "Later", "artist": "Elsewhere"}
        shuffled = {"id": "t3", "title": "Unowned", "artist": "Next"}
        side = {"text": ("Godspeed bring One Above All into the room with a "
                          "patient rise and leave enough air around the final "
                          "note for the next voice to land cleanly."),
                "who": "dj", "key": "voice-key", "seconds": 11.0,
                "tint_ok": True, "at": app.time.time()}
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "track_talk_queue.json"
                with mock.patch.object(app, "TRACK_TALK_PATH", path):
                    app._TRACK_TALK.clear()
                    app._TRACK_TALK["t1"] = {**track, "intro": dict(side)}
                    app._TRACK_TALK["t2"] = {
                        **later,
                        "at": app.time.time(),
                        "intro": {**side, "text": (
                            "Elsewhere bring Later forward with a patient "
                            "pulse and a clear melodic turn that leaves the "
                            "room ready for the record to open.")},
                    }
                    app.track_talk_save(True)
                    app._TRACK_TALK.clear()
                    app._TRACK_TALK_LOADED[0] = False
                    # A restart is allowed to reshuffle the library, but it
                    # must put already-paid dialogue back ahead of that
                    # shuffle so the cached line is actually used.
                    app._RADIO["queue"] = [later, shuffled, track]
                    app.track_talk_load()
                    self.assertEqual(app.track_talk_restore_queue(), 2)
            self.assertEqual(app._TRACK_TALK["t1"]["intro"]["text"],
                             side["text"])
            self.assertEqual(app._TRACK_TALK["t1"]["intro"]["who"], "dj")
            self.assertFalse(app._TRACK_TALK["t1"]["intro"]["off_brief"])
            self.assertEqual([row["id"] for row in app._RADIO["queue"]],
                             ["t1", "t2", "t3"])
            self.assertEqual(app._TRACK_TALK["t1"]["track"]["id"], "t1")
        finally:
            app._TRACK_TALK.clear()
            app._TRACK_TALK.update(prior)
            app._TRACK_TALK_LOADED[0] = prior_loaded
            app._TRACK_TALK_SAVED[0] = prior_saved
            app._RADIO["queue"] = prior_queue

    def test_restart_keeps_clean_track_draft_when_saved_tint_echoes_prompt(self) -> None:
        prior = dict(app._TRACK_TALK)
        prior_loaded = app._TRACK_TALK_LOADED[0]
        prior_saved = app._TRACK_TALK_SAVED[0]
        track = {"id": "t1", "title": "Courage",
                 "artist": "The Whitest Boy Alive", "at": app.time.time()}
        clean = ("Courage opens with a patient pulse and a clean guitar "
                 "figure that leaves enough room around the vocal for the "
                 "record to take over naturally.")
        bad = ("The world of MF DOOM: mask mythology and cartoon menace. "
               + clean)
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "track_talk_queue.json"
                path.write_text(app.json.dumps({
                    "t1": {**track, "intro": {
                        "text": bad, "text_plain": clean, "tint_ok": True,
                        "key": "bad-take", "seconds": 12,
                        "at": app.time.time(),
                    }}
                }))
                with mock.patch.object(app, "TRACK_TALK_PATH", path):
                    app._TRACK_TALK.clear()
                    app._TRACK_TALK_LOADED[0] = False
                    app.track_talk_load()
            side = app._TRACK_TALK["t1"]["intro"]
            self.assertEqual(side["text"], clean)
            self.assertFalse(side["tint_ok"])
            self.assertNotIn("key", side)
            self.assertEqual(side["tint"]["why"],
                             "persisted tint rejected; clean draft retained")
        finally:
            app._TRACK_TALK.clear()
            app._TRACK_TALK.update(prior)
            app._TRACK_TALK_LOADED[0] = prior_loaded
            app._TRACK_TALK_SAVED[0] = prior_saved

    def test_pause_plays_unowned_music_without_spending_owned_fifo(self) -> None:
        prior_radio = dict(app._RADIO)
        prior_talk = dict(app._TRACK_TALK)
        held = [
            {"id": "t0", "title": "First", "artist": "A"},
            {"id": "t1", "title": "Second", "artist": "B"},
            {"id": "t2", "title": "Third", "artist": "C"},
        ]
        unowned = {"id": "free", "title": "Music Bed", "artist": "D"}
        try:
            app._TRACK_TALK.clear()
            for track in held:
                app._TRACK_TALK[track["id"]] = {**track, "at": app.time.time()}
            app._RADIO.update({
                "now": held[0], "queue": [held[1], unowned, held[2]],
                "requests": [], "coming": None, "since_tape": 0,
                "station": "all",
            })
            with (mock.patch.object(app, "radio_paused", return_value=True),
                  mock.patch.object(app, "dj_settings",
                                    return_value={"mixtape_every": 0}),
                  mock.patch.object(app, "track_talk_save"),
                  mock.patch.object(app, "pipeline_log")):
                picked = app.dj_next_track()
            self.assertEqual(picked["id"], "free")
            self.assertEqual([row["id"] for row in app._RADIO["queue"]],
                             ["t0", "t1", "t2"])
            self.assertEqual(list(app._TRACK_TALK), ["t0", "t1", "t2"])
        finally:
            app._RADIO.clear()
            app._RADIO.update(prior_radio)
            app._TRACK_TALK.clear()
            app._TRACK_TALK.update(prior_talk)

    def test_track_lookahead_excludes_live_requests_and_already_coming(self) -> None:
        prior_radio = dict(app._RADIO)
        try:
            app._RADIO.update({
                "coming": {"id": "coming"},
                "requests": [{"id": "request"}],
                "queue": [{"id": "future-1"}, {"id": "future-2"}],
            })
            self.assertEqual([row["id"] for row in app.track_lookahead(10)],
                             ["future-1", "future-2"])
        finally:
            app._RADIO.clear()
            app._RADIO.update(prior_radio)

    async def test_paused_record_round_never_takes_track_dialogue(self) -> None:
        prior_radio = dict(app._RADIO)
        track = {"id": "t1", "title": "One Above All", "artist": "Godspeed"}
        dj = {"research": False, "lyrics_talk": False}
        take = mock.Mock(return_value=None)
        try:
            app._RADIO.update({"now": track, "history": [],
                               "station_id_next": False,
                               "ad_due_next": False})
            with (mock.patch.object(app, "radio_paused", return_value=True),
                  mock.patch.object(app, "track_talk_on", return_value=True),
                  mock.patch.object(app, "track_talk_get", take),
                  mock.patch.object(app, "track_definition", return_value=""),
                  mock.patch.object(app, "dj_speak", new=mock.AsyncMock()),
                  mock.patch.object(app.asyncio, "sleep", new=mock.AsyncMock())):
                await app._record_talk(track, dj, 1, False, True,
                                       intro_only=True)
            take.assert_not_called()
        finally:
            app._RADIO.clear()
            app._RADIO.update(prior_radio)

    def test_one_track_pair_fills_one_music_carrier_and_is_not_reused(self) -> None:
        demand = [
            {"commit_id": "one", "kind": "track_talk", "road": "track_talk",
             "label": "one", "starts_in": 60.0, "owns_seconds": 180.0},
            {"commit_id": "two", "kind": "track_talk", "road": "track_talk",
             "label": "two", "starts_in": 240.0, "owns_seconds": 180.0},
        ]
        track = {"id": "t1", "title": "One Above All", "artist": "Godspeed"}
        side = {"text": "ready", "seconds": 12.0, "key": "k",
                "tint_ok": True}
        prior = dict(app._TRACK_TALK)
        app._TRACK_TALK.clear()
        app._TRACK_TALK["t1"] = {**track, "intro": dict(side),
                                 "outro": dict(side)}
        try:
            with (mock.patch.object(app, "schedule_demand_entries",
                                    return_value=demand),
                  mock.patch.object(app, "track_lookahead", return_value=[track]),
                  mock.patch.object(app, "track_talk_pair_ready", return_value=True),
                  mock.patch.object(app, "track_talk_part_ready", return_value=True),
                  mock.patch.object(app, "task_cost", return_value=30.0)):
                plan = app.commitment_inventory_plan(1.0, fresh=True)
        finally:
            app._TRACK_TALK.clear()
            app._TRACK_TALK.update(prior)
        self.assertEqual(plan["slots"][0]["ready_seconds"], 180.0)
        self.assertEqual(plan["slots"][1]["ready_seconds"], 0.0)
        self.assertEqual(plan["slots"][1]["short_seconds"], 180.0)
        self.assertEqual(plan["roads"]["track_talk"]["new_tasks"], 2)

    async def test_scheduled_track_talk_uses_only_the_current_records_take(self) -> None:
        track = {"id": "live", "title": "One Above All", "artist": "Godspeed"}
        side = {"text": ("Godspeed bring One Above All through the room with "
                          "enough weight to hold the whole record together."),
                "who": "dj", "key": "k", "tint_ok": True}
        prior = dict(app._RADIO)
        takes: list[tuple[str, bool]] = []

        def get_exact(got_track, part, take=False):
            self.assertEqual(got_track["id"], "live")
            takes.append((part, take))
            return dict(side) if part == "intro" else None

        app._RADIO.update({
            "now": track,
            "sched_pos": {"preset": "hour", "index": 2,
                          "slot_id": "talk", "started": 100.0},
            "interject_prompt": {},
        })
        app._RADIO.pop("sched_track_talk", None)
        try:
            with (mock.patch.object(app, "track_talk_get",
                                    side_effect=get_exact),
                  mock.patch.object(app, "track_talk_part_ready",
                                    side_effect=lambda row: bool(row)),
                  mock.patch.object(app, "dj_speak",
                                    new=mock.AsyncMock(return_value=side["text"])),
                  mock.patch.object(app, "coord_air_note") as credited,
                  mock.patch.object(app, "pipeline_log")):
                aired = await app.schedule_extra_round("track_talk", track, {})
            self.assertTrue(aired)
            self.assertIn(("intro", True), takes)
            credited.assert_called_once_with(side["text"], "dj", "track_talk")
        finally:
            app._RADIO.clear()
            app._RADIO.update(prior)

    def test_track_talk_carrier_is_credited_once_per_schedule_occurrence(self) -> None:
        prior_active = dict(app._HOUR_ACTIVE)
        prior_radio = dict(app._RADIO)
        app._HOUR_ACTIVE.clear()
        app._HOUR_ACTIVE.update({"schedule": {}, "aired": {}})
        app._RADIO.update({
            "sched_slot": {"kind": "track_talk", "minutes": 3.0},
            "sched_pos": {"preset": "hour", "index": 2,
                          "slot_id": "talk", "started": 100.0},
        })
        try:
            with mock.patch.object(app, "radio_paused", return_value=False):
                app.coord_schedule_note({"kind": "track_talk"}, True)
                app.coord_schedule_note({"kind": "track_talk"}, True)
            self.assertEqual(app._HOUR_ACTIVE["aired"]["track_talk"], 180.0)
        finally:
            app._HOUR_ACTIVE.clear()
            app._HOUR_ACTIVE.update(prior_active)
            app._RADIO.clear()
            app._RADIO.update(prior_radio)

    async def test_track_talk_render_refusal_is_not_reported_as_inventory_gain(self) -> None:
        track = {"id": "t1", "title": "One Above All", "artist": "Godspeed"}
        text = ("Godspeed bring One Above All into the room on a patient rise, "
                "then leave the final note hanging cleanly above the next "
                "voice that reaches the microphone.")
        prior = dict(app._TRACK_TALK)
        app._TRACK_TALK.clear()
        try:
            with (mock.patch.object(app, "track_talk_on", return_value=True),
                  mock.patch.object(app, "track_lookahead", return_value=[track]),
                  mock.patch.object(app, "track_talk_get", return_value=None),
                  mock.patch.object(app, "track_talk_write",
                                    new=mock.AsyncMock(return_value=text)),
                  mock.patch.object(app, "dialogue_tint_required",
                                    return_value=False),
                  mock.patch.object(app, "session_voices",
                                    new=mock.AsyncMock(return_value={"dj": "v"})),
                  mock.patch.object(app, "prep_render_line",
                                    new=mock.AsyncMock(return_value=None)),
                  mock.patch.object(app, "_track_talk_prune", return_value=0),
                  mock.patch.object(app, "track_talk_save"),
                  mock.patch.object(app, "pipeline_log")):
                made = await app.prep_track_talk()
            self.assertFalse(made)
            self.assertEqual(app._TRACK_TALK["t1"]["intro"]["text"], text)
            self.assertNotIn("key", app._TRACK_TALK["t1"]["intro"])
        finally:
            app._TRACK_TALK.clear()
            app._TRACK_TALK.update(prior)

    def test_pantry_restart_restores_diagnostic_metadata(self) -> None:
        prior_pantry = dict(app._PANTRY)
        prior_shelf = dict(app._SHELF)
        app._PANTRY.clear()
        app._SHELF.clear()
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                media = root / "media"
                media.mkdir()
                (media / "take.wav").write_bytes(b"RIFF")
                pantry = root / "pantry.json"
                pantry.write_text(
                    '{"key": {"clip": {"path": "/voice/take.wav", '
                    '"seconds": 2.0}, "at": 10, "used": 0, "bytes": 4, '
                    '"text": "the exact stored words", "voice": "v1", '
                    '"who": "dj", "kind": "track_talk"}}')
                with (mock.patch.object(app, "PANTRY_PATH", pantry),
                      mock.patch.object(app, "SHELF_PATH", root / "missing.json"),
                      mock.patch.object(app, "VOICE_MEDIA_DIR", media),
                      mock.patch.object(app, "pipeline_log")):
                    app._pantry_load()
            self.assertEqual(app._PANTRY["key"]["text"],
                             "the exact stored words")
            self.assertEqual(app._PANTRY["key"]["kind"], "track_talk")
            self.assertEqual(app._PANTRY["key"]["who"], "dj")
        finally:
            app._PANTRY.clear()
            app._PANTRY.update(prior_pantry)
            app._SHELF.clear()
            app._SHELF.update(prior_shelf)


if __name__ == "__main__":
    unittest.main()
