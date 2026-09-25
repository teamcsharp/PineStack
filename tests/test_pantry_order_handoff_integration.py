import asyncio
import unittest
from contextlib import ExitStack
from unittest import mock

import app

_REAL_CLOCK_READY = app.pantry_order_clock_ready


class PantryOrderHandoffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in (("_PANTRY_ORDER_AT", [0.0]),
                            ("_PANTRY_ORDER_LAST", {}),
                            ("_PANTRY_ORDER_RECORD_ACTIVE", set()),
                            ("_PANTRY_ORDER_QUALITY_ACTIVE", set()),
                            ("_ALT_JOBS", {})):
            self.stack.enter_context(mock.patch.object(app, name, value))
        for name in ("orch_used", "orch_turn", "pipeline_log", "note_action"):
            self.stack.enter_context(mock.patch.object(app, name))
        self.stack.enter_context(mock.patch.object(app, "pantry_order_clock_ready",
                                                   return_value=True))

    async def test_commission_waits_for_published_system2_clock(self):
        with (mock.patch.object(app, "pantry_orders_mode", return_value="air"),
              mock.patch.object(app, "pantry_order_clock_ready", return_value=False),
              mock.patch.object(app, "pantry_order_schedule_work") as work):
            self.assertEqual(await app.pantry_orders_tick(), {})
        self.assertEqual(app._PANTRY_ORDER_AT[0], 0.0)
        work.assert_not_called()

    def test_clock_guard_applies_only_to_on_air_system2(self):
        with (mock.patch.object(app, "_RADIO", {"on": True, "sched_pos": {}}),
              mock.patch.object(app, "_system2", return_value=mock.Mock(enabled=True))):
            self.assertFalse(_REAL_CLOCK_READY())
            app._RADIO["sched_pos"] = {"started": 1000.0}
            self.assertTrue(_REAL_CLOCK_READY())
            app._RADIO["sched_pos"] = {}
            app._RADIO["on"] = False
            self.assertTrue(_REAL_CLOCK_READY())
            app._RADIO["on"] = True
        with (mock.patch.object(app, "_RADIO", {"on": True, "sched_pos": {}}),
              mock.patch.object(app, "_system2", return_value=mock.Mock(enabled=False))):
            self.assertTrue(_REAL_CLOCK_READY())

    def test_glass_shows_bound_quality_job_and_its_room_state(self):
        repair = {"road": "news", "commit_id": "news@180", "item_id": "news-1",
                  "sid": "news-1", "due_in": 180, "add_turns": 4,
                  "body_short_seconds": 20, "job": "qlt-1"}
        app._PANTRY_ORDER_LAST.update({"quality_dispatched": 1,
            "schedule_handoff": {"quality": [repair]}})
        app._ALT_JOBS["qlt-1"] = {"state": "recording"}
        with (mock.patch.object(app, "orch_register_state", return_value={}),
              mock.patch.object(app, "orch_glass_face", return_value={}),
              mock.patch.object(app, "orch_glass_roads", return_value=[]),
              mock.patch.object(app, "orch_glass_pressure", return_value={})):
            commission = app.orch_glass_state()["commission"]
        self.assertEqual(commission["quality_dispatched"], 1)
        self.assertEqual(commission["quality"][0]["state"], "recording")
        self.assertEqual(commission["quality"][0]["body_short_seconds"], 20)

    def test_bank_shortfall_leads_without_double_counting_aggregate_demand(self):
        with mock.patch.object(app, "_COORD_PLAN", {"tasks": [
                {"road": "ad", "want_seconds": 500, "due_in": 900,
                 "bare": False, "why": "aggregate"},
                {"road": "caller", "want_seconds": 300, "due_in": 1200}]}):
            plan = app.pantry_order_plan({"write": [
                {"road": "news", "want_seconds": 240, "due_in": 60,
                 "commit_id": "news-1", "bare": True},
                {"road": "ad", "want_seconds": 120, "due_in": 0,
                 "commit_id": "ad-1", "bare": True}]})
        self.assertEqual([task["road"] for task in plan["tasks"]],
                         ["news", "ad", "caller"])
        self.assertEqual(plan["tasks"][1]["want_seconds"], 500)
        self.assertEqual(plan["tasks"][1]["due_in"], 0)
        self.assertTrue(plan["tasks"][1]["bare"])

    def test_bank_task_passes_existing_work_order_budget(self):
        with mock.patch.object(app, "_COORD_PLAN", {"tasks": []}):
            plan = app.pantry_order_plan({"write": [
                {"road": "news", "want_seconds": 240, "due_in": 30,
                 "commit_id": "news-1", "bare": True, "why": "bound gap"}]})
        order = app.coord_work_order(
            plan, budget=300, price=lambda road: 60,
            covers=lambda road: 120, chance=lambda road: 1,
            full=lambda road: False, label=lambda road: road)
        self.assertEqual(order["orders"][0]["road"], "news")
        self.assertEqual(order["orders"][0]["items"], 2)
        self.assertEqual(order["orders"][0]["due_in"], 30)

    def test_record_target_rechecks_exact_bound_id_and_readiness(self):
        row = {"sid": "ad-1", "text": "A written advert"}
        selected = {"id": "ad-1", "kind": "ad", "ready": False, "row": row}
        with (mock.patch.object(app, "commitment_inventory_plan",
                                return_value={"selected": [selected]}),
              mock.patch.object(app, "dialogue_row_ready", return_value=False)):
            self.assertEqual(app.pantry_order_record_target(
                {"road": "ad", "item_id": "ad-1"}), ("single", row))
            self.assertEqual(app.pantry_order_record_target(
                {"road": "ad", "item_id": "other"}), ("", None))
            selected["ready"] = True
            self.assertEqual(app.pantry_order_record_target(
                {"road": "ad", "item_id": "ad-1"}), ("", None))

    def test_quality_target_rechecks_exact_future_slot_and_source(self):
        row = {"sid": "g-1", "entry": {"script": "A: Ready."}}
        slot = {"road": "gallery", "commit_id": "slot@123",
                "in_seconds": 180, "current": False,
                "stock": [{"id": "g-1"}]}
        selected = {"id": "g-1", "kind": "gallery", "ready": True,
                    "row": row}
        order = {"road": "gallery", "item_id": "g-1", "sid": "g-1",
                 "commit_id": "slot@123"}
        with (mock.patch.object(app, "commitment_inventory_plan",
                                return_value={"slots": [slot],
                                              "selected": [selected]}),
              mock.patch.object(app, "dialogue_row_ready", return_value=True)):
            self.assertEqual(app.pantry_order_quality_target(order), (slot, row))
            slot["commit_id"] = "another@123"
            self.assertIsNone(app.pantry_order_quality_target(order))
            slot["commit_id"] = "slot@123"
            slot["in_seconds"] = 40
            self.assertIsNone(app.pantry_order_quality_target(order))

    def test_incomplete_track_talk_carrier_is_a_bound_record_target(self):
        carrier = {"id": "record-1", "intro": {"key": "ready"}, "outro": {}}
        selected = {"id": "track_talk:record-1", "kind": "track_talk",
                    "ready": False, "row": carrier}
        with (mock.patch.object(app, "commitment_inventory_plan",
                                return_value={"selected": [selected]}),
              mock.patch.object(app, "track_talk_pair_ready", return_value=False)):
            self.assertEqual(app.pantry_order_record_target(
                {"road": "track_talk", "item_id": "track_talk:record-1"}),
                ("track_talk", carrier))
            self.assertEqual(app.pantry_order_record_target(
                {"road": "track_talk", "item_id": "track_talk:other"}),
                ("", None))

    def test_schedule_work_reads_exact_bank_hour(self):
        bank = {"available": True, "slots": [
            {"road": "news", "label": "News", "in_seconds": 90,
             "commit_id": "news-1", "owns_seconds": 240,
             "short_seconds": 240, "written_only_seconds": 0,
             "state": "missing", "items": []}]}
        with (mock.patch.object(app, "bank_view", return_value=bank) as read,
              mock.patch.object(app, "shelf_full", return_value=False)):
            work = app.pantry_order_schedule_work()
        read.assert_called_once_with(60)
        self.assertEqual(work["write"][0]["road"], "news")

    async def test_trace_costs_bank_priority_without_dispatch(self):
        handoff = {"available": True, "write": [
            {"road": "news", "want_seconds": 240, "due_in": 30,
             "commit_id": "news-1", "bare": True}],
            "record": [{"road": "ad", "item_id": "ad-1"}]}
        seen = []

        def cost(plan):
            seen.append(plan)
            return {"orders": [{"road": "news", "items": 1}],
                    "say": "news first"}

        with (mock.patch.object(app, "pantry_orders_mode", return_value="trace"),
              mock.patch.object(app, "pantry_order_schedule_work",
                                return_value=handoff),
              mock.patch.object(app, "coord_work_order", side_effect=cost),
              mock.patch.object(app, "fire_and_forget") as launch,
              mock.patch.object(app, "_COORD_PLAN", {"tasks": []})):
            result = await app.pantry_orders_tick()
        self.assertEqual(seen[0]["tasks"][0]["road"], "news")
        self.assertEqual(result["schedule_handoff"], handoff)
        self.assertEqual(result["placed"], 0)
        self.assertEqual(result["recording_dispatched"], 0)
        launch.assert_not_called()

    async def test_air_dispatches_one_record_and_one_bounded_write(self):
        handoff = {"available": True, "write": [
            {"road": "news", "want_seconds": 240, "due_in": 30,
             "commit_id": "news-1", "bare": True}],
            "record": [{"road": "ad", "item_id": "ad-1"}]}
        launched = []

        def launch(coro):
            task = asyncio.create_task(coro)
            launched.append(task)
            return task

        with (mock.patch.object(app, "pantry_orders_mode", return_value="air"),
              mock.patch.object(app, "pantry_order_schedule_work",
                                return_value=handoff),
              mock.patch.object(app, "coord_work_order", return_value={
                  "orders": [{"road": "news", "items": 1, "why": "due"}],
                  "say": "news first"}),
              mock.patch.object(app, "pantry_order_record",
                                new_callable=mock.AsyncMock) as record,
              mock.patch.object(app, "pantry_order_record_target",
                                return_value=("single", {"sid": "ad-1"})),
              mock.patch.object(app, "alt_generate_job",
                                new_callable=mock.AsyncMock) as write,
              mock.patch.object(app, "fire_and_forget", side_effect=launch),
              mock.patch.object(app, "alt_window", return_value="break"),
              mock.patch.object(app, "shelf_full", return_value=False),
              mock.patch.object(app, "commitment_write_needed",
                                return_value=True),
              mock.patch.object(app, "alt_job_put") as put,
              mock.patch.object(app, "_COORD_PLAN", {"tasks": []})):
            result = await app.pantry_orders_tick()
            await asyncio.gather(*launched)
        self.assertEqual(result["recording_dispatched"], 1)
        self.assertEqual(result["placed"], 1)
        record.assert_awaited_once_with(handoff["record"][0])
        write.assert_awaited_once()
        self.assertEqual(put.call_args.kwargs["kind"], "news")

    async def test_full_shelf_quality_ticket_dispatches_once_without_overfill(self):
        repair = {"road": "gallery", "sid": "g-1", "item_id": "g-1",
                  "commit_id": "slot@123", "why": "structure"}
        launched = []

        def launch(coro):
            task = asyncio.create_task(coro)
            launched.append(task)
            return task

        with (mock.patch.object(app, "pantry_orders_mode", return_value="air"),
              mock.patch.object(app, "pantry_order_schedule_work",
                                return_value={"write": [], "record": [],
                                              "quality": [repair]}),
              mock.patch.object(app, "coord_work_order",
                                return_value={"orders": [], "say": "quality"}),
              mock.patch.object(app, "pantry_order_quality_target",
                                return_value=({}, {"sid": "g-1"})),
              mock.patch.object(app, "pantry_order_quality",
                                new_callable=mock.AsyncMock) as quality,
              mock.patch.object(app, "fire_and_forget", side_effect=launch),
              mock.patch.object(app, "alt_window", return_value="break"),
              mock.patch.object(app, "shelf_full", return_value=True),
              mock.patch.object(app, "_COORD_PLAN", {"tasks": []})):
            result = await app.pantry_orders_tick()
            await asyncio.gather(*launched)
        self.assertEqual(result["quality_dispatched"], 1)
        self.assertEqual(result["placed"], 0)
        quality.assert_awaited_once()

    async def test_unrepresentable_manager_role_is_held_not_retried(self):
        repair = {"road": "manager", "sid": "m-1", "item_id": "m-1",
                  "commit_id": "slot@123", "missing_roles": ["manager"]}
        with (mock.patch.object(app, "pantry_orders_mode", return_value="air"),
              mock.patch.object(app, "pantry_order_schedule_work",
                                return_value={"write": [], "record": [],
                                              "quality": [repair]}),
              mock.patch.object(app, "coord_work_order",
                                return_value={"orders": [], "say": "quality"}),
              mock.patch.object(app, "fire_and_forget") as launch,
              mock.patch.object(app, "alt_window", return_value="break")):
            result = await app.pantry_orders_tick()
        self.assertEqual(result["quality_dispatched"], 0)
        self.assertIn("cannot evidence", repair["held"])
        launch.assert_not_called()

    async def test_spent_quality_attempts_do_not_make_new_tickets(self):
        repair = {"road": "gallery", "sid": "g-1", "item_id": "g-1",
                  "commit_id": "slot@123"}
        with (mock.patch.object(app, "pantry_orders_mode", return_value="air"),
              mock.patch.object(app, "pantry_order_schedule_work",
                                return_value={"write": [], "record": [],
                                              "quality": [repair]}),
              mock.patch.object(app, "coord_work_order",
                                return_value={"orders": [], "say": "quality"}),
              mock.patch.object(app, "pantry_order_quality_target",
                                return_value=({}, {"quality_attempts": 2,
                                                   "quality_protocol": app.QUALITY_REPAIR_VERSION})),
              mock.patch.object(app, "fire_and_forget") as launch,
              mock.patch.object(app, "alt_window", return_value="break")):
            result = await app.pantry_orders_tick()
        self.assertEqual(result["quality_dispatched"], 0)
        self.assertIn("already spent", repair["held"])
        launch.assert_not_called()

    async def test_returned_quality_repair_does_not_hold_the_writer_slot(self):
        repair = {"road": "gallery", "sid": "g-1", "item_id": "g-1",
                  "commit_id": "slot@123"}
        app._ALT_JOBS["old"] = {"kind": "gallery", "state": "waiting for repair"}
        row = {"quality_draft": {"quality_repair_needed": True}}
        with (mock.patch.object(app, "pantry_orders_mode", return_value="air"),
              mock.patch.object(app, "pantry_order_schedule_work",
                                return_value={"write": [], "record": [],
                                              "quality": [repair]}),
              mock.patch.object(app, "coord_work_order",
                                return_value={"orders": [], "say": "quality"}),
              mock.patch.object(app, "pantry_order_quality_target",
                                return_value=({}, row)),
              mock.patch.object(app, "pantry_window", return_value="break"),
              mock.patch.object(app, "alt_window", return_value="break"),
              mock.patch.object(app, "fire_and_forget",
                                side_effect=lambda coro: coro.close()) as launch):
            result = await app.pantry_orders_tick()
        self.assertEqual(result["quality_dispatched"], 1)
        self.assertIn("job", repair)
        launch.assert_called_once()

    async def test_quality_repair_recovers_turns_lost_during_preparation(self):
        source = {"script": "A: Original.\nB: Reply.", "seconds": 120.0,
                  "tint": {"old": True}, "use": "tinted", "prep_turns": 2}
        row = {"sid": "g-1", "entry": source, "seconds": 120.0,
               "quality_attempts": 2}
        order = {"road": "gallery", "sid": "g-1", "item_id": "g-1",
                 "commit_id": "slot@123", "allocated_seconds": 120,
                 "add_turns": 2}
        records = []

        async def record(draft):
            records.append((row["entry"] is source, "tint" in draft,
                            "prep_turns" in draft))
            if len(records) == 1:
                draft["script"] = source["script"]
            draft["seconds"] = 125.0
            draft["prepared"] = True
            return True

        with (mock.patch.object(app, "pantry_order_quality_target",
                                return_value=({}, row)),
              mock.patch.object(app, "alt_window", return_value="break"),
              mock.patch.object(app, "pantry_window", return_value="break"),
              mock.patch.object(app, "prep_should_stop", return_value=""),
              mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock,
                                side_effect=["A: New one.\nB: New two.",
                                             "A: Repair one.\nB: Repair two."]) as writer,
              mock.patch.object(app, "larder_prepare", side_effect=record),
              mock.patch.object(app, "dialogue_row_ready",
                                side_effect=lambda _kind, candidate:
                                candidate.get("entry", candidate).get("prepared", False)),
              mock.patch.object(app, "commitment_inventory_plan",
                                return_value={"selected": [
                                    {"id": "g-1", "row": row, "ready": True}]}),
              mock.patch.object(app, "pantry_order_quality_save"),
              mock.patch.object(app, "prep_room_left", return_value=60)):
            await app.pantry_order_quality("job-1", order)
            self.assertIs(row["entry"], source)
            self.assertTrue(row["quality_draft"]["quality_repair_needed"])
            self.assertEqual(app._ALT_JOBS["job-1"]["state"], "waiting for repair")
            self.assertEqual(row["quality_last_fault"]["draft_turns"], 2)
            await app.pantry_order_quality("job-2", order)
        self.assertEqual(records, [(True, False, False), (True, False, False)])
        self.assertEqual(writer.await_count, 2)
        self.assertEqual(row["quality_attempts"], 0)
        self.assertEqual(row["quality_successes"], 1)
        self.assertEqual(row["quality_protocol"], app.QUALITY_REPAIR_VERSION)
        self.assertNotIn("quality_draft", row)
        self.assertEqual(app._ALT_JOBS["job-2"]["state"], "done")

    async def test_quality_worker_keeps_original_until_fully_recorded(self):
        source = {"script": "A: A long enough original.\nB: Reply.",
                  "seconds": 120.0, "prep_kind": "gallery"}
        row = {"sid": "g-1", "entry": source, "seconds": 120.0}
        order = {"road": "gallery", "sid": "g-1", "item_id": "g-1",
                 "commit_id": "slot@123", "allocated_seconds": 120,
                 "add_turns": 1}
        seen = []

        async def record(draft):
            seen.append(row["entry"] is source)
            draft["seconds"] = 125.0
            draft["prepared"] = True
            return True

        with (mock.patch.object(app, "pantry_order_quality_target",
                                return_value=({}, row)),
              mock.patch.object(app, "alt_window", return_value="break"),
              mock.patch.object(app, "pantry_window", return_value="break"),
              mock.patch.object(app, "prep_should_stop", return_value=""),
              mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock,
                                return_value="A: A long enough original.\nB: Reply.\nA: More."),
              mock.patch.object(app, "larder_prepare", side_effect=record),
              mock.patch.object(app, "dialogue_row_ready",
                                side_effect=lambda _kind, candidate:
                                candidate.get("entry", candidate).get("prepared", True)),
              mock.patch.object(app, "commitment_inventory_plan",
                                return_value={"selected": [
                                    {"id": "g-1", "row": row, "ready": True}]}),
              mock.patch.object(app, "pantry_order_quality_save"),
              mock.patch.object(app, "prep_room_left", return_value=60)):
            await app.pantry_order_quality("job", order)
        self.assertEqual(seen, [True])
        self.assertIsNot(row["entry"], source)
        self.assertEqual(row["sid"], "g-1")
        self.assertEqual(row["quality_attempts"], 0)
        self.assertEqual(row["quality_successes"], 1)
        self.assertNotIn("quality_draft", row)
        self.assertTrue(app._ALT_JOBS["job"]["selected"])

    async def test_unusable_quality_offers_are_bounded_without_spending_recording_attempts(self):
        source = {"script": "A: Original.\nB: Reply.", "seconds": 120.0}
        row = {"sid": "g-1", "entry": source}
        order = {"road": "gallery", "sid": "g-1", "item_id": "g-1",
                 "commit_id": "slot@123", "add_turns": 3}
        with (mock.patch.object(app, "pantry_order_quality_target",
                                return_value=({}, row)),
              mock.patch.object(app, "alt_window", return_value="break"),
              mock.patch.object(app, "prep_should_stop", return_value=""),
              mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock,
                                return_value="A: Too short." ) as writer,
              mock.patch.object(app, "pantry_order_quality_save")):
            for _ in range(4):
                await app.pantry_order_quality("job", order)
        self.assertIs(row["entry"], source)
        self.assertEqual(row["quality_attempts"], 0)
        self.assertEqual(row["quality_offer_failures"], 3)
        self.assertEqual(row["quality_last_fault"]["offered_turns"], 1)
        self.assertEqual(writer.await_count, 3)

    async def test_quality_offer_must_supply_words_for_the_missing_airtime(self):
        source = {"script": "A: Original.\nB: Reply.", "seconds": 120.0}
        row = {"sid": "g-1", "entry": source}
        order = {"road": "gallery", "sid": "g-1", "item_id": "g-1",
                 "commit_id": "slot@123", "add_turns": 2,
                 "body_short_seconds": 20.0}
        with (mock.patch.object(app, "pantry_order_quality_target",
                                return_value=({}, row)),
              mock.patch.object(app, "alt_window", return_value="break"),
              mock.patch.object(app, "prep_should_stop", return_value=""),
              mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock,
                                return_value="A: More.\nB: Yes."),
              mock.patch.object(app, "larder_prepare",
                                new_callable=mock.AsyncMock) as record,
              mock.patch.object(app, "pantry_order_quality_save")):
            await app.pantry_order_quality("short-words", order)
        self.assertIs(row["entry"], source)
        self.assertEqual(row["quality_attempts"], 0)
        self.assertGreater(row["quality_last_fault"]["wanted_words"],
                           row["quality_last_fault"]["offered_words"])
        record.assert_not_awaited()

    async def test_quality_recording_must_close_the_measured_duration_gap(self):
        source = {"script": "A: Original.\nB: Reply.", "seconds": 120.0}
        row = {"sid": "g-1", "entry": source}
        order = {"road": "gallery", "sid": "g-1", "item_id": "g-1",
                 "commit_id": "slot@123", "add_turns": 2,
                 "body_short_seconds": 20.0}

        async def record(draft):
            draft["seconds"] = 129.0
            draft["prepared"] = True

        offer = "A: " + "Specific new detail matters here. " * 7 + "\nB: " \
            + "We can test each fact against the next. " * 7
        with (mock.patch.object(app, "pantry_order_quality_target",
                                return_value=({}, row)),
              mock.patch.object(app, "alt_window", return_value="break"),
              mock.patch.object(app, "pantry_window", return_value="break"),
              mock.patch.object(app, "prep_should_stop", return_value=""),
              mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock,
                                return_value=offer),
              mock.patch.object(app, "larder_prepare", side_effect=record),
              mock.patch.object(app, "dialogue_row_ready", return_value=True),
              mock.patch.object(app, "pantry_order_quality_save"),
              mock.patch.object(app, "prep_room_left", return_value=60)):
            await app.pantry_order_quality("short-recording", order)
        self.assertIs(row["entry"], source)
        self.assertTrue(row["quality_draft"]["quality_repair_needed"])
        self.assertEqual(row["quality_last_fault"]["target_seconds"], 140.0)
        self.assertEqual(app._ALT_JOBS["short-recording"]["state"], "waiting for repair")

    async def test_partial_quality_draft_resumes_without_rewriting_source(self):
        source = {"script": "A: Original.\nB: Reply.", "seconds": 120.0}
        draft = {"script": "A: Original.\nA: More.\nB: Reply.",
                 "prep_kind": "gallery", "preparing": True, "seconds": 40.0}
        row = {"sid": "g-1", "entry": source, "quality_draft": draft,
               "quality_attempts": 1, "quality_commit_id": "slot@123"}
        order = {"road": "gallery", "sid": "g-1", "item_id": "g-1",
                 "commit_id": "slot@123", "add_turns": 1}
        with (mock.patch.object(app, "pantry_order_quality_target",
                                return_value=({}, row)),
              mock.patch.object(app, "pantry_window", return_value="break"),
              mock.patch.object(app, "prep_should_stop", return_value=""),
              mock.patch.object(app, "larder_prepare", new_callable=mock.AsyncMock,
                                return_value=False) as record,
              mock.patch.object(app, "dialogue_row_ready", return_value=False),
              mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock) as writer,
              mock.patch.object(app, "pantry_order_quality_save"),
              mock.patch.object(app, "prep_room_left", return_value=60)):
            await app.pantry_order_quality("job", order)
        self.assertIs(row["entry"], source)
        self.assertIs(row["quality_draft"], draft)
        self.assertNotIn("preparing", draft)
        self.assertEqual(row["quality_attempts"], 1)
        self.assertEqual(app._ALT_JOBS["job"]["state"], "waiting for recording")
        record.assert_awaited_once_with(draft)
        writer.assert_not_awaited()

    async def test_short_recorded_replacement_never_displaces_full_audio(self):
        source = {"script": "A: Original.\nB: Reply.", "seconds": 120.0}
        row = {"sid": "g-1", "entry": source}
        order = {"road": "gallery", "sid": "g-1", "item_id": "g-1",
                 "commit_id": "slot@123", "allocated_seconds": 120,
                 "add_turns": 1}

        async def record(draft):
            draft["seconds"] = 70.0
            draft["prepared"] = True
            return True

        with (mock.patch.object(app, "pantry_order_quality_target",
                                return_value=({}, row)),
              mock.patch.object(app, "alt_window", return_value="break"),
              mock.patch.object(app, "pantry_window", return_value="break"),
              mock.patch.object(app, "prep_should_stop", return_value=""),
              mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock,
                                return_value="A: Additional exchange."),
              mock.patch.object(app, "larder_prepare", side_effect=record),
              mock.patch.object(app, "dialogue_row_ready", return_value=True),
              mock.patch.object(app, "pantry_order_quality_save"),
              mock.patch.object(app, "prep_room_left", return_value=60)):
            await app.pantry_order_quality("job", order)
        self.assertIs(row["entry"], source)
        self.assertEqual(row["quality_attempts"], 1)
        self.assertNotIn("quality_draft", row)
        self.assertIn("shorter", app._ALT_JOBS["job"]["why"])

    async def test_quality_rewrite_requires_normalized_missing_role(self):
        source = {"script": "A: Original.\nA: Still me.", "seconds": 120.0}
        row = {"sid": "g-1", "entry": source}
        order = {"road": "gallery", "sid": "g-1", "item_id": "g-1",
                 "commit_id": "slot@123", "add_turns": 1,
                 "missing_roles": ["cohost"]}
        with (mock.patch.object(app, "pantry_order_quality_target",
                                return_value=({}, row)),
              mock.patch.object(app, "alt_window", return_value="break"),
              mock.patch.object(app, "prep_should_stop", return_value=""),
              mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock,
                                return_value="A: More from me."),
              mock.patch.object(app, "larder_prepare",
                                new_callable=mock.AsyncMock) as record,
              mock.patch.object(app, "pantry_order_quality_save")):
            await app.pantry_order_quality("job", order)
        self.assertIs(row["entry"], source)
        self.assertNotIn("quality_draft", row)
        self.assertIn("cohost", app._ALT_JOBS["job"]["why"])
        record.assert_not_awaited()

    async def test_stale_record_does_not_consume_the_only_recording_turn(self):
        rows = [{"road": "gallery", "item_id": "stale"},
                {"road": "manager", "item_id": "due"}]
        launched = []

        def launch(coro):
            task = asyncio.create_task(coro)
            launched.append(task)
            return task

        with (mock.patch.object(app, "pantry_orders_mode", return_value="air"),
              mock.patch.object(app, "pantry_order_schedule_work",
                                return_value={"write": [], "record": rows}),
              mock.patch.object(app, "coord_work_order",
                                return_value={"orders": [], "say": "record"}),
              mock.patch.object(app, "pantry_order_record_target",
                                side_effect=[("", None), ("round", {"sid": "due"})]),
              mock.patch.object(app, "pantry_order_record",
                                new_callable=mock.AsyncMock) as record,
              mock.patch.object(app, "fire_and_forget", side_effect=launch),
              mock.patch.object(app, "alt_window", return_value="break")):
            result = await app.pantry_orders_tick()
            await asyncio.gather(*launched)
        self.assertEqual(rows[0]["state"], "no longer ready for recording")
        self.assertEqual(result["recording_dispatched"], 1)
        record.assert_awaited_once_with(rows[1])

    async def test_active_writing_ticket_is_not_duplicated(self):
        with (mock.patch.object(app, "pantry_orders_mode", return_value="air"),
              mock.patch.object(app, "pantry_order_schedule_work",
                                return_value={"write": [], "record": []}),
              mock.patch.object(app, "coord_work_order", return_value={
                  "orders": [{"road": "news", "items": 1}], "say": "news"}),
              mock.patch.object(app, "_ALT_JOBS", {
                  "running": {"kind": "news", "state": "writing"}}),
              mock.patch.object(app, "alt_window", return_value="break"),
              mock.patch.object(app, "fire_and_forget") as launch,
              mock.patch.object(app, "alt_job_put") as put):
            result = await app.pantry_orders_tick()
        self.assertEqual(result["placed"], 0)
        self.assertIn("already active", result["orders"][0]["held"])
        put.assert_not_called()
        launch.assert_not_called()

    async def test_stale_bound_shortfall_does_not_place_writing_ticket(self):
        with (mock.patch.object(app, "pantry_orders_mode", return_value="air"),
              mock.patch.object(app, "pantry_order_schedule_work",
                                return_value={"write": [], "record": []}),
              mock.patch.object(app, "coord_work_order", return_value={
                  "orders": [{"road": "news", "items": 1,
                              "scheduled_commit_id": "news-1"}],
                  "say": "news"}),
              mock.patch.object(app, "alt_window", return_value="break"),
              mock.patch.object(app, "shelf_full", return_value=False),
              mock.patch.object(app, "commitment_write_needed",
                                return_value=False),
              mock.patch.object(app, "fire_and_forget") as launch,
              mock.patch.object(app, "alt_job_put") as put):
            result = await app.pantry_orders_tick()
        self.assertEqual(result["placed"], 0)
        self.assertIn("no longer needs", result["orders"][0]["held"])
        put.assert_not_called()
        launch.assert_not_called()

    async def test_record_visit_uses_live_window_and_releases_claim(self):
        item = {"road": "news", "item_id": "news-1"}
        app._PANTRY_ORDER_RECORD_ACTIVE.add("news-1")
        with (mock.patch.object(app, "pantry_window", return_value="break"),
              mock.patch.object(app, "prep_should_stop", return_value=""),
              mock.patch.object(app, "pantry_order_record_target",
                                return_value=("round", {"script": "Hello"})),
              mock.patch.object(app, "recording_sitting",
                                new_callable=mock.AsyncMock,
                                return_value={"finished": 1}) as sitting):
            await app.pantry_order_record(item)
        self.assertEqual(item["state"], "recorded")
        self.assertNotIn("news-1", app._PANTRY_ORDER_RECORD_ACTIVE)
        sitting.assert_awaited_once()

        held = {"road": "news", "item_id": "news-2"}
        with (mock.patch.object(app, "pantry_window", return_value=""),
              mock.patch.object(app, "pantry_order_record_target") as target):
            await app.pantry_order_record(held)
        self.assertIn("waiting", held["state"])
        target.assert_not_called()

    async def test_track_talk_record_visit_targets_exact_carrier(self):
        item = {"road": "track_talk", "item_id": "track_talk:record-1"}
        with (mock.patch.object(app, "pantry_window", return_value="break"),
              mock.patch.object(app, "prep_should_stop", return_value=""),
              mock.patch.object(app, "pantry_order_record_target",
                                return_value=("track_talk", {"id": "record-1"})),
              mock.patch.object(app, "prep_track_talk",
                                new_callable=mock.AsyncMock, return_value=True) as prepare):
            await app.pantry_order_record(item)
        self.assertEqual(item["state"], "recorded")
        prepare.assert_awaited_once_with("record-1")

    async def test_single_read_filter_records_only_the_bound_item(self):
        first = {"sid": "ad-1", "text": "First"}
        second = {"sid": "ad-2", "text": "Second"}
        with (mock.patch.object(app, "_SHELF", {"ad": [first, second]}),
              mock.patch.object(app, "committed_stock_ids",
                                return_value={"ad-1", "ad-2"}),
              mock.patch.object(app, "dialogue_row_ready", return_value=False),
              mock.patch.object(app, "dialogue_row_viable", return_value=True),
              mock.patch.object(app, "dialogue_tint_ready", return_value=True),
              mock.patch.object(app, "ensure_shelf_row_tinted",
                                new_callable=mock.AsyncMock, return_value=True),
              mock.patch.object(app, "prep_should_stop", return_value=""),
              mock.patch.object(app, "prep_render_line",
                                new_callable=mock.AsyncMock,
                                return_value={"key": "clip", "seconds": 3}),
              mock.patch.object(app, "alt_sid", side_effect=lambda k, r: r["sid"])):
            self.assertTrue(await app.prep_voice_pending("ad", "ad-2"))
        self.assertNotIn("key", first)
        self.assertEqual(second["key"], "clip")


if __name__ == "__main__":
    unittest.main()
