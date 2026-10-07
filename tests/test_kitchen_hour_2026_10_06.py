"""[kitchen-hour] 2026-10-06: one kitchen under the hour (wave H).

The board's needs gain the upcoming Book Time and supercut windows' unvoiced parts; a window's part is made by the
segment runtime's voicing pass under the task's own room; System 2's prepare jobs stand down under engine system3;
the writer lanes dial admits a second lane only while every condition holds.

Measured before this: a Book Time part stood at 3 of 10 takes for an hour while System 2's one lane was owed and the
board recorded other roads first.

Pure rules (fake sheet, fake windows) run first; the board, the prep pass, System 2 and the lanes dial run against
the real app module with its readers patched.
"""
import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import kitchen_hour
import app
import system2_runtime
import dynamic_segments_system2

NOW = time.time()   # the app reads the real clock; the pure rules take the moment explicitly


def window(kind, start, slot_id="w1", road="banter"):
    """A coord_upcoming-shaped row for a window (the sheet's own kind, published on the banter road)."""
    return {"kind": kind, "road": road, "label": kind, "slot_id": slot_id,
            "occurrence": "%s@%d" % (slot_id, int(start)), "due_at": float(start),
            "starts_in": round(start - NOW, 1),
            "slot": {"id": slot_id, "kind": kind, "dynamic_template": kind, "minutes": 6.5},
            "cannot": ""}


def parts_for(table):
    """A fake sheet's parts: occurrence -> list of part dicts."""
    return lambda row: [dict(p) for p in table.get(row["occurrence"], [])]


def part(pid, phase, left, takes):
    return {"id": pid, "phase": phase, "chunks_left": left, "takes": takes}


def book_entry(sid, phase, chunks, takes):
    """A book row as the segment runtime holds it: chunks written, takes recorded (a list)."""
    return {"sid": sid, "book_phase": phase, "chunks": chunks, "takes": [{"key": "t%d" % i} for i in range(takes)]}


def settings_facts(**over):
    facts = {"ceiling": 2, "system3": True, "second_lane": True, "render_in_flight": False,
             "hot_c": 60.0, "hot_ceiling_c": 90.0, "pantry_short": True, "window_soon": False,
             "pantry_seconds": 100, "target_seconds": 7200}
    facts.update(over)
    return facts


class WindowNeeds(unittest.TestCase):
    """Cost, deadline and order of the windows' needs, from a fake sheet and fake windows."""

    def test_cost_and_deadline_from_chunks_and_start(self):
        start = NOW + 1800
        row = window("book_time", start)
        needs = kitchen_hour.window_needs([row], parts_for({row["occurrence"]: [part("p1", "opening", 4, 6)]}),
                                          now=NOW)
        self.assertEqual(len(needs), 1)
        need = needs[0]
        self.assertEqual(need["prep"], "banter")
        self.assertEqual(need["kind"], "banter")
        self.assertEqual(need["cost"], 40.0)                              # 4 chunks x 10 s
        self.assertAlmostEqual(need["deadline"], start - 60, delta=0.01)  # the window's start minus 60 s
        self.assertAlmostEqual(need["starts_in"], 1800.0, delta=0.01)
        self.assertEqual(need["slot_id"], "w1")
        self.assertEqual(need["occurrence"], row["occurrence"])
        self.assertEqual(need["part"], "p1")
        self.assertIn("needs its opening part voiced (4 chunks left)", need["why"])
        self.assertTrue(need["why"].startswith("Book Time at "))

    def test_chunk_seconds_is_a_parameter(self):
        row = window("book_time", NOW + 900)
        need = kitchen_hour.window_needs([row], parts_for({row["occurrence"]: [part("p", "closing", 3, 0)]}),
                                         now=NOW, chunk_seconds=4.0)[0]
        self.assertEqual(need["cost"], 12.0)

    def test_parts_not_owed_are_not_needs(self):
        row = window("book_time", NOW + 900)
        table = {row["occurrence"]: [part("done", "opening", 0, 10)]}
        self.assertEqual(kitchen_hour.window_needs([row], parts_for(table), now=NOW), [])

    def test_rows_that_are_not_windows_are_not_needs(self):
        banter = dict(window("book_time", NOW + 900), kind="banter", slot={"kind": "banter"})
        table = {banter["occurrence"]: [part("p", "opening", 5, 0)]}
        self.assertEqual(kitchen_hour.window_needs([banter], parts_for(table), now=NOW), [])

    def test_supercut_need_is_its_clip(self):
        row = window("sfx_supercut", NOW + 600, slot_id="s1")
        need = kitchen_hour.window_needs([row], parts_for({row["occurrence"]: [part("clip", "clip", 1, 0)]}),
                                         now=NOW)[0]
        self.assertEqual(need["cost"], 10.0)
        self.assertAlmostEqual(need["deadline"], NOW + 600 - 60, delta=0.01)
        self.assertTrue(need["why"].startswith("Supercut at "))
        self.assertIn("needs its clip made (1 chunks left)", need["why"])

    def test_nearest_deadline_first_across_windows(self):
        late = window("book_time", NOW + 3000, slot_id="b2")
        soon = window("sfx_supercut", NOW + 1500, slot_id="s1")
        table = {late["occurrence"]: [part("op", "opening", 2, 0)],
                 soon["occurrence"]: [part("clip", "clip", 1, 0)]}
        needs = kitchen_hour.window_needs([late, soon], parts_for(table), now=NOW)
        self.assertEqual([n["slot_id"] for n in needs], ["s1", "b2"])
        self.assertLess(needs[0]["deadline"], needs[1]["deadline"])

    def test_a_part_with_no_takes_is_first_in_its_window(self):
        row = window("book_time", NOW + 1200)
        table = {row["occurrence"]: [part("open", "opening", 3, 2), part("close", "closing", 10, 0)]}
        needs = kitchen_hour.window_needs([row], parts_for(table), now=NOW)
        self.assertEqual([n["part"] for n in needs], ["close", "open"])   # the missing part first
        self.assertEqual(needs[0]["cost"], 100.0)

    def test_the_book_order_breaks_a_tie_between_parts_with_takes(self):
        row = window("book_time", NOW + 1200)
        table = {row["occurrence"]: [part("d", "discussion", 2, 1), part("o", "opening", 2, 1)]}
        needs = kitchen_hour.window_needs([row], parts_for(table), now=NOW)
        self.assertEqual([n["part"] for n in needs], ["o", "d"])


class BoardOrder(unittest.TestCase):
    """A window need within twenty minutes outranks quota-only needs; a later one waits behind them."""

    def test_urgent_window_goes_ahead_of_the_board(self):
        quota = [{"prep": "news", "why": "quota only", "cost": 50.0}]
        row = window("book_time", NOW + 900)
        near = kitchen_hour.window_needs([row], parts_for({row["occurrence"]: [part("o", "opening", 2, 0)]}),
                                         now=NOW)
        out = kitchen_hour.merge_needs(quota, near)
        self.assertEqual([n["prep"] for n in out], ["banter", "news"])
        self.assertEqual(out[0]["why"], near[0]["why"])

    def test_a_far_window_waits_behind_the_board(self):
        quota = [{"prep": "news", "why": "quota only", "cost": 50.0}]
        row = window("book_time", NOW + 3000)
        far = kitchen_hour.window_needs([row], parts_for({row["occurrence"]: [part("o", "opening", 2, 0)]}),
                                        now=NOW)
        out = kitchen_hour.merge_needs(quota, far)
        self.assertEqual([n["prep"] for n in out], ["news", "banter"])

    def test_due_soon_is_twenty_minutes(self):
        self.assertTrue(kitchen_hour.window_due_soon([{"starts_in": 1200.0}]))
        self.assertFalse(kitchen_hour.window_due_soon([{"starts_in": 1201.0}]))
        self.assertFalse(kitchen_hour.window_due_soon([]))


class WriterLanesRules(unittest.TestCase):
    """The lanes dial: 2 only when every condition holds, never past the ceiling."""

    def test_all_conditions_hold_gives_two(self):
        lanes, why = kitchen_hour.writer_lanes(settings_facts())
        self.assertEqual(lanes, 2)
        self.assertIn("pantry holds 100 s of 7200 s", why)

    def test_ceiling_of_one_is_one(self):
        self.assertEqual(kitchen_hour.writer_lanes(settings_facts(ceiling=1))[0], 1)

    def test_engine_or_setting_must_allow_it(self):
        self.assertEqual(kitchen_hour.writer_lanes(settings_facts(system3=False, second_lane=False))[0], 1)
        self.assertEqual(kitchen_hour.writer_lanes(settings_facts(system3=False, second_lane=True))[0], 2)
        self.assertEqual(kitchen_hour.writer_lanes(settings_facts(system3=True, second_lane=False))[0], 2)

    def test_a_render_in_flight_keeps_one_lane(self):
        self.assertEqual(kitchen_hour.writer_lanes(settings_facts(render_in_flight=True))[0], 1)

    def test_heat_keeps_one_lane(self):
        lanes, why = kitchen_hour.writer_lanes(settings_facts(hot_c=90.0))
        self.assertEqual(lanes, 1)
        self.assertIn("at or over", why)
        self.assertEqual(kitchen_hour.writer_lanes(settings_facts(hot_c=89.9))[0], 2)
        self.assertEqual(kitchen_hour.writer_lanes(settings_facts(hot_c=None))[0], 1)

    def test_pantry_or_window_must_ask_for_it(self):
        self.assertEqual(kitchen_hour.writer_lanes(settings_facts(pantry_short=False, window_soon=False))[0], 1)
        self.assertEqual(kitchen_hour.writer_lanes(settings_facts(pantry_short=False, window_soon=True))[0], 2)
        self.assertEqual(kitchen_hour.writer_lanes(settings_facts(pantry_short=True, window_soon=False))[0], 2)

    def test_admission_counts_the_held_lanes(self):
        self.assertTrue(kitchen_hour.lane_admits(0, 1))
        self.assertFalse(kitchen_hour.lane_admits(1, 1))
        self.assertTrue(kitchen_hour.lane_admits(1, 2))
        self.assertFalse(kitchen_hour.lane_admits(2, 2))


# [kitchen-gate] the window needs wait for the switch: these tests run under engine system3 (System 2 stood down).
SYSTEM3_ENGINE = lambda: SimpleNamespace(stood_down=lambda: True)
SYSTEM2_ENGINE = lambda: SimpleNamespace(stood_down=lambda: False)


class AppBoard(unittest.TestCase):
    """The windows reach the board through the app's own readers, with the sheet and the runtime patched."""

    def setUp(self):
        app._KITCHEN_WINDOWS.update(at=0.0, needs=[])
        app._SLOT_WANT.update(at=0.0, needs=[], kind="", why="")
        self.table = {}
        self.runtime = SimpleNamespace(
            unvoiced_parts=lambda row: [dict(p) for p in self.table.get(row["occurrence"], [])],
            source_entry=lambda row: row)

    def test_kitchen_window_needs_reads_the_upcoming_windows(self):
        near = window("book_time", time.time() + 900, slot_id="w1")
        later = window("sfx_supercut", time.time() + 2400, slot_id="s1")
        self.table = {near["occurrence"]: [book_entry("o", "opening", 4, 1)],
                      later["occurrence"]: []}
        with mock.patch.object(app, "coord_upcoming", lambda *a, **k: [near, later]), \
                mock.patch.object(app, "coord_ahead_seconds", lambda: 7200.0), \
                mock.patch.dict(app.__dict__, {"DYNAMIC_SEGMENTS_RUNTIME": self.runtime, "_system2": SYSTEM3_ENGINE}), \
                mock.patch.dict(app._SHELF, {"sfx_supercut": [{"dynamic_occurrence": later["occurrence"]}]}):
            needs = app.kitchen_window_needs()
            roads = app.kitchen_window_roads()
        self.assertEqual(len(needs), 1)                        # the supercut's clip is held: nothing owed
        self.assertEqual(needs[0]["cost"], 30.0)               # 4 chunks less the one take
        self.assertEqual(needs[0]["prep"], "banter")
        self.assertEqual(roads, {"banter"})

    def test_window_needs_wait_for_the_switch(self):
        """[kitchen-gate] under engine system2 the board takes no window needs at all."""
        near = window("book_time", time.time() + 900, slot_id="w1")
        self.table = {near["occurrence"]: [book_entry("o", "opening", 4, 1)]}
        with mock.patch.object(app, "coord_upcoming", lambda *a, **k: [near]), \
                mock.patch.object(app, "coord_ahead_seconds", lambda: 7200.0), \
                mock.patch.dict(app.__dict__, {"DYNAMIC_SEGMENTS_RUNTIME": self.runtime, "_system2": SYSTEM2_ENGINE}):
            self.assertEqual(app.kitchen_window_needs(), [])

    def test_supercut_clip_held_on_the_shelf_is_not_owed(self):
        row = window("sfx_supercut", time.time() + 600, slot_id="s1")
        with mock.patch.dict(app._SHELF, {"sfx_supercut": [{"dynamic_occurrence": row["occurrence"]}]}):
            self.assertEqual(app._kitchen_window_parts(self.runtime, row), [])
        with mock.patch.dict(app._SHELF, {"sfx_supercut": []}):
            self.assertEqual(app._kitchen_window_parts(self.runtime, row)[0]["chunks_left"], 1)

    def test_board_needs_carry_the_window_first(self):
        near = window("book_time", time.time() + 900, slot_id="w1")
        self.table = {near["occurrence"]: [book_entry("o", "opening", 2, 0)]}
        with mock.patch.object(app, "coord_upcoming", lambda *a, **k: [near]), \
                mock.patch.object(app, "coord_ahead_seconds", lambda: 7200.0), \
                mock.patch.dict(app.__dict__, {"DYNAMIC_SEGMENTS_RUNTIME": self.runtime, "_system2": SYSTEM3_ENGINE}), \
                mock.patch.object(app, "hour_owes", lambda: []), \
                mock.patch.object(app, "arrears_owed", lambda: []), \
                mock.patch.object(app, "orch_policy", lambda k: "none"), \
                mock.patch.object(app, "cupboard_short", lambda: []), \
                mock.patch.object(app, "slot_board", lambda ahead=1: {"slots": []}):
            needs = app.slot_needs()
        self.assertEqual(needs[0]["prep"], "banter")
        self.assertEqual(needs[0]["cost"], 20.0)
        self.assertTrue(needs[0]["why"].startswith("Book Time at"))

    def test_the_board_takes_a_window_need(self):
        need = {"prep": "banter", "kind": "banter", "cost": 40.0,
                "why": "Book Time at 15:45 needs its opening part voiced (4 chunks left)",
                "window": window("book_time", time.time() + 900), "deadline": time.time() + 840}
        patches = [
            mock.patch.object(app, "prep_room_left", lambda: 300.0),
            mock.patch.object(app, "prepared_seconds", lambda: 0.0),
            mock.patch.object(app, "prep_tier", lambda cover=-1.0: "bare"),
            mock.patch.object(app, "prep_budget", lambda tier="", room=-1.0, cover=-1.0: 200.0),
            mock.patch.object(app, "prep_thin_seconds", lambda: 600.0),
            mock.patch.object(app, "prep_deep_seconds", lambda: 1800.0),
            mock.patch.object(app, "schedule_prep_order", lambda: []),
            mock.patch.object(app, "PREP_BOARD", ("banter",)),
            mock.patch.object(app, "off_air", lambda: False),
            mock.patch.object(app, "orch_policy", lambda k: "none"),
            mock.patch.object(app, "committed_stock_ids", lambda kind, ready=True: []),
            mock.patch.object(app, "commitment_write_needed", lambda kind: False),
            mock.patch.object(app, "event_roads_prepare", lambda: False),
            mock.patch.object(app, "commit_for", lambda kind: ""),
            mock.patch.object(app, "shelf_full", lambda kind: False),
            mock.patch.object(app, "shelf_rows", lambda kind: []),
            mock.patch.object(app, "shelf_unvoiced", lambda kind: 0),
            mock.patch.object(app, "task_cost", lambda kind: 80.0),
            mock.patch.object(app, "task_gain", lambda kind: 100.0),
            mock.patch.object(app, "task_rate", lambda kind: 1.0),
            mock.patch.object(app, "task_stat", lambda kind: {"measured": False}),
            mock.patch.object(app, "prep_need", lambda kind: 1.0),
            mock.patch.object(app, "hour_owes", lambda: []),
            mock.patch.object(app, "prep_deadline_pick", lambda rows, room, cover: None),
            mock.patch.object(app, "kitchen_window_needs", lambda: [dict(need)]),
            mock.patch.object(app, "slot_needs", lambda: [dict(need)]),
        ]
        for p in patches:
            p.start()
        try:
            plan = app.prep_plan(set())
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(plan["kind"], "banter")
        self.assertTrue(plan["forced"])
        self.assertEqual(plan["window_need"]["why"], need["why"])
        self.assertIn("Book Time at", plan["why"])
        self.assertIn("at about 40s", plan["why"])             # priced by its chunks, not the road's 80 s


class PrepOnePass(unittest.TestCase):
    """prep_one makes a window's part through the runtime's pass under the task's own room."""

    def test_prep_one_calls_the_pass_under_cost_plus_fifteen(self):
        need = {"prep": "banter", "cost": 40.0,
                "why": "Book Time at 15:45 needs its opening part voiced (4 chunks left)",
                "window": window("book_time", time.time() + 900)}
        seen = {}

        async def fake_pass(due):
            seen["due"] = due
            seen["room"] = app._PREP_TASK_DEADLINE.get()
            return True

        work = mock.AsyncMock(return_value=False)
        app._PREP_LAST.clear()
        app._PREP_LAST.update({"kind": "banter", "window_need": need})
        with mock.patch.dict(app.__dict__, {"dynamic_segment_prepare_pass": fake_pass}), \
                mock.patch.object(app, "_prep_one_work", work):
            before = time.time()
            did = asyncio.run(app.prep_one("banter"))
        self.assertTrue(did)
        self.assertEqual(seen["due"]["occurrence"], need["window"]["occurrence"])
        self.assertAlmostEqual(seen["room"], before + 40.0 + 15.0, delta=3.0)
        work.assert_not_called()
        self.assertNotIn("window_need", app._PREP_LAST)          # taken once, not again on the next pass

    def test_prep_one_without_a_window_pick_builds_as_before(self):
        app._PREP_LAST.clear()
        work = mock.AsyncMock(return_value=True)
        with mock.patch.object(app, "_prep_one_work", work):
            self.assertTrue(asyncio.run(app.prep_one("banter")))
        work.assert_awaited_once_with("banter")

    def test_a_supercut_need_uses_the_supercut_pass(self):
        need = {"prep": "banter", "cost": 10.0, "why": "Supercut at 16:58 needs its clip made (1 chunks left)",
                "window": window("sfx_supercut", time.time() + 600, slot_id="s1")}
        calls = []

        async def fake_supercut(due):
            calls.append(due["slot_id"])
            return {"ok": True}

        app._PREP_LAST.clear()
        app._PREP_LAST.update({"kind": "banter", "window_need": need})
        with mock.patch.dict(app.__dict__, {"dynamic_segment_prepare_supercut": fake_supercut}):
            self.assertTrue(asyncio.run(app.prep_one("banter")))
        self.assertEqual(calls, ["s1"])


class System2IdlesUnderSystem3(unittest.TestCase):
    """Under engine system3 System 2's prepare loop and window jobs do nothing."""

    def make(self, engine):
        rt = object.__new__(system2_runtime.System2Runtime)
        rt.config = {"engine": engine, "horizon_hours": 6, "generation_turns": 9,
                     "legacy_keepers": True, "fallback": True}
        rt._prepare_lock = asyncio.Semaphore(1)
        rt._works = {}
        rt._work = {}
        rt.host = SimpleNamespace(CANNOT_PREPARE={})
        rt.refresh = mock.AsyncMock()
        rt._claim_preparation = mock.AsyncMock(return_value=None)
        return rt

    def test_stood_down_and_not_enabled_under_system3(self):
        rt = self.make("system3")
        self.assertTrue(rt.stood_down())
        self.assertFalse(rt.enabled)
        with mock.patch.object(rt, "_rooms_open", lambda: True), mock.patch.object(rt, "_off_air", lambda: False):
            asyncio.run(rt.prepare())
            self.assertIsNone(rt.prepare_spawn())
        rt.refresh.assert_not_awaited()
        rt._claim_preparation.assert_not_awaited()

    def test_system2_still_prepares_under_system2(self):
        rt = self.make("system2")
        self.assertFalse(rt.stood_down())
        self.assertTrue(rt.enabled)
        with mock.patch.object(rt, "_rooms_open", lambda: True), mock.patch.object(rt, "_off_air", lambda: False):
            asyncio.run(rt.prepare())
        rt.refresh.assert_awaited()
        rt._claim_preparation.assert_awaited()

    def test_window_claims_and_tickets_idle_under_system3(self):
        runtime = SimpleNamespace(stood_down=lambda: True, enabled=False)
        dyn = object.__new__(dynamic_segments_system2.DynamicSystem2)
        dyn.runtime = runtime
        dyn.writer_ticket = None
        dyn.requested = {}
        original = mock.AsyncMock(return_value=None)
        dyn.original = {"_claim_preparation": original}
        dyn.prepare_job = mock.AsyncMock()
        self.assertIsNone(asyncio.run(dyn.claim(("banter",), 3600)))
        original.assert_not_awaited()
        dyn.prepare_job.assert_not_awaited()
        self.assertIs(asyncio.run(dyn.wait_for_book_writer({"slot_id": "x"}, {})), False)
        self.assertIsNone(dyn.writer_ticket)


class LanesDial(unittest.TestCase):
    """The writer lanes dial at the request book, its memo, its log and its readout."""

    def setUp(self):
        app._KITCHEN_LANES.update(at=0.0, lanes=1, why="", facts={})

    def test_writer_lanes_is_two_only_when_every_condition_holds(self):
        with mock.patch.object(app, "kitchen_lane_facts", lambda: settings_facts()):
            self.assertEqual(app.writer_lanes(), 2)
        app._KITCHEN_LANES.update(at=0.0)
        with mock.patch.object(app, "kitchen_lane_facts", lambda: settings_facts(render_in_flight=True)):
            self.assertEqual(app.writer_lanes(), 1)

    def test_the_request_book_admits_a_second_writer_only_at_two(self):
        model = "gemma-test"

        async def enter_with(lanes_now, other_holds_lane):
            app._OLLAMA_JOBS.clear()
            app._OLLAMA_JOBS["other"] = {"model": model, "lane_held": other_holds_lane, "state": "active"}
            app._OLLAMA_JOBS["ask"] = {"model": model, "state": "waiting"}
            with mock.patch.object(app, "writer_lanes", lambda: lanes_now):
                try:
                    await asyncio.wait_for(app.kitchen_lane_enter(model, "ask"), 0.6)
                    return True
                except asyncio.TimeoutError:
                    return False

        try:
            self.assertFalse(asyncio.run(enter_with(1, True)))    # one lane held, one lane admitted: waits
            self.assertTrue(asyncio.run(enter_with(2, True)))     # second lane open: admitted
            self.assertTrue(asyncio.run(enter_with(1, False)))    # nothing held: admitted
            self.assertTrue(app._OLLAMA_JOBS["ask"]["lane_held"])
        finally:
            app._OLLAMA_JOBS.clear()

    def test_the_log_speaks_once_per_change(self):
        log = mock.MagicMock()
        with mock.patch.object(app, "pipeline_log", log):
            with mock.patch.object(app, "kitchen_lane_facts", lambda: settings_facts()):
                for _ in range(3):
                    app._KITCHEN_LANES["at"] = 0.0
                    app.writer_lanes()
            self.assertEqual(log.call_count, 1)
            self.assertIn("the kitchen opens a second writer lane:", log.call_args[0][1])
            with mock.patch.object(app, "kitchen_lane_facts", lambda: settings_facts(render_in_flight=True)):
                for _ in range(3):
                    app._KITCHEN_LANES["at"] = 0.0
                    app.writer_lanes()
            self.assertEqual(log.call_count, 2)
            self.assertIn("back to one lane: an H3 or ComfyUI render is in flight", log.call_args[0][1])

    def test_the_cupboard_shows_the_lanes(self):
        with mock.patch.object(app, "kitchen_lane_facts", lambda: settings_facts()), \
                mock.patch.object(app, "kitchen_window_needs", lambda: []):
            state = app.kitchen_lanes_state()
        self.assertEqual(state["lanes"], 2)
        self.assertEqual(state["ceiling"], app.OLLAMA_LANES)
        self.assertEqual(state["window_needs"], 0)
        self.assertIn("pantry_short", state["facts"])

    def test_the_setting_is_a_default_on_row(self):
        self.assertIs(app.DEFAULT_DJ["kitchen_second_lane"], True)


if __name__ == "__main__":
    unittest.main()
