import asyncio
import unittest
from contextlib import ExitStack
from unittest import mock

import app


class PantryOrderHandoffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in (("_PANTRY_ORDER_AT", [0.0]),
                            ("_PANTRY_ORDER_LAST", {}),
                            ("_PANTRY_ORDER_RECORD_ACTIVE", set()),
                            ("_ALT_JOBS", {})):
            self.stack.enter_context(mock.patch.object(app, name, value))
        for name in ("orch_used", "orch_turn", "pipeline_log", "note_action"):
            self.stack.enter_context(mock.patch.object(app, name))

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
