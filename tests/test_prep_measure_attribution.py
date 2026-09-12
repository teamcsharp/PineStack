"""Task cost learning without borrowing concurrent output or grading deferrals."""
import asyncio
from contextlib import ExitStack
from contextvars import ContextVar
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import app


class PreparationAttributionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.clock = 1000.0
        self.ledger = {}
        self.hour_note = mock.Mock()
        for name, value in {
            "_TASK_LEDGER": self.ledger,
            "_WRITING_DEFERRED": ContextVar("test_writing_deferral", default=0),
            "task_ledger_load": mock.Mock(), "task_ledger_save": mock.Mock(),
            "coord_task_note": self.hour_note,
            # Replace app's reference, never asyncio's own clock module.
            "time": SimpleNamespace(monotonic=lambda: self.clock, time=lambda: self.clock),
        }.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    async def test_same_kind_parallel_output_and_live_piper_do_not_become_own_gain(self):
        stock, engines = [0.0], {}
        with (mock.patch.object(app, "prepared_seconds", side_effect=lambda: stock[0]) as total,
              mock.patch.object(app, "take_engine_tally", side_effect=lambda: dict(engines)) as tally):
            for _ in range(3):
                started, completed = asyncio.Event(), asyncio.Event()

                async def own_work():
                    started.set()
                    await completed.wait()
                    return True  # Accepted writing, no own finished audio.

                async def other_ad_job():
                    await started.wait()
                    stock[0] += 100.0
                    engines["piper"] = engines.get("piper", 0) + 1
                    self.clock += 10
                    completed.set()

                await asyncio.gather(app.prep_measure("ad", own_work()), other_ad_job())
        total.assert_not_called()
        tally.assert_not_called()
        self.assertEqual(self.ledger["ad"]["gain"], [])
        self.assertEqual(self.ledger["ad"]["gain_unmeasured_count"], 3)
        self.assertNotIn("ad:piper", self.ledger)
        self.assertEqual(app.task_rate("ad"), 1.8)  # Seed18s / measured10s; old bug gave10.
        self.assertEqual(app.task_stat("ad")["gain_basis"], "bootstrap")
        self.assertEqual(app.task_stat("ad")["gain_samples"], 0)

    async def test_declared_admission_deferrals_leave_quality_and_cost_history_unchanged(self):
        for _ in range(3):
            app.task_note("ad", 10, 18, True)
        before = copy.deepcopy(self.ledger)
        odds, rate = app.task_odds("ad"), app.task_rate("ad")

        async def deferred():
            app._WRITING_DEFERRED.set(app._WRITING_DEFERRED.get() + 1)
            self.clock += 10
            return False

        for _ in range(3):
            self.assertFalse(await app.prep_measure("ad", deferred()))
        self.assertEqual(self.ledger, before)
        self.assertEqual(app.task_odds("ad"), odds)
        self.assertEqual(app.task_rate("ad"), rate)

    async def test_explicit_deferral_is_skipped_but_a_real_failure_is_measured(self):
        async def refused():
            self.clock += 10
            raise app.WritingDeferred("No model was admitted")

        async def failed():
            self.clock += 10
            raise RuntimeError("An admitted job failed")

        self.assertFalse(await app.prep_measure("ad", refused()))
        self.assertEqual(self.ledger, {})
        self.assertFalse(await app.prep_measure("ad", failed()))
        self.assertEqual(self.ledger["ad"]["count"], 1)
        self.assertEqual(self.ledger["ad"]["fail"], 1)

    async def test_another_tasks_deferral_does_not_hide_own_failure(self):
        async def another_task():
            app._WRITING_DEFERRED.set(app._WRITING_DEFERRED.get() + 1)

        async def own_work():
            await asyncio.create_task(another_task())
            self.clock += 10
            return False

        await app.prep_measure("ad", own_work())
        self.assertEqual(self.ledger["ad"]["fail"], 1)

    async def test_successful_retained_work_still_records_cost_after_partial_deferral(self):
        async def retained():
            app._WRITING_DEFERRED.set(app._WRITING_DEFERRED.get() + 1)
            self.clock += 10
            return True

        self.assertTrue(await app.prep_measure("ad", retained()))
        self.assertEqual(self.ledger["ad"]["count"], 1)
        self.assertEqual(self.ledger["ad"]["fail"], 0)
        self.assertEqual(self.ledger["ad"]["gain"], [])

    async def test_child_tint_deferral_reaches_parent_for_both_stored_shapes(self):
        child_tasks = []
        progress = {"turns": [{"text": "Retained approved passage"}]}

        async def child():
            child_tasks.append(asyncio.current_task())
            app._WRITING_DEFERRED.set(app._WRITING_DEFERRED.get() + 1)
            self.clock += 10
            return {"ok": False, "deferred": True, "progress": progress}

        async def rewrite(*_args, **_kwargs):
            before = app._WRITING_DEFERRED.get()
            result = await asyncio.wait_for(asyncio.create_task(child()), timeout=1)
            self.assertEqual(app._WRITING_DEFERRED.get(), before)
            return result

        with ExitStack() as stack:
            for name, value in {
                "dialogue_tint_required": mock.Mock(return_value=True),
                "legacy_tint_revalidate": mock.AsyncMock(return_value=False),
                "crystal_tint": mock.AsyncMock(side_effect=rewrite),
                "_pantry_save": mock.Mock(), "_larder_save": mock.Mock(),
                "pipeline_log": mock.Mock(),
            }.items():
                stack.enter_context(mock.patch.object(app, name, value))
            entry = {"script": "A: Every original word is owed."}
            raw = {"text": "Every original word is owed."}
            for row in ({"entry": entry}, raw):
                before = app._WRITING_DEFERRED.get()
                result = await app.prep_measure("ad", app.ensure_shelf_row_tinted("ad", row))
                self.assertFalse(result)
                self.assertEqual(app._WRITING_DEFERRED.get(), before + 1)
                target = row.get("entry") or row
                self.assertIn("tint_revalidation", target, (row, app.pipeline_log.call_args_list))
                self.assertEqual(target["tint_revalidation"]["state"], "waiting")
                self.assertEqual(target["tint_progress"], progress)
                self.assertNotIn("tinting", target)
        self.assertEqual(len(child_tasks), 2)
        self.assertTrue(all(task is not asyncio.current_task() for task in child_tasks))
        self.assertEqual(self.ledger, {})

    def test_unknown_gain_keeps_numeric_history_and_metadata_across_restart(self):
        for _ in range(3):
            app.task_note("ad", 10, 18, True)
        gains = list(self.ledger["ad"]["gain"])
        app.task_note("ad", 20, 999, True, gain_measured=False)
        self.assertEqual(self.ledger["ad"]["gain"], gains)
        self.hour_note.assert_called_with("ad", 20, 0.0, True)
        # The actual loader, captured from the module before the setup mock.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "task_costs.json"
            path.write_text(json.dumps(self.ledger), encoding="utf-8")
            expected = path.read_bytes()
            with (mock.patch.object(app, "TASK_LEDGER_PATH", path),
                  mock.patch.object(app, "_TASK_LEDGER_LOADED", [False]),
                  mock.patch.object(app, "_TASK_LEDGER", {})):
                REAL_LEDGER_LOAD()
                self.assertEqual(app._TASK_LEDGER["ad"]["gain"], gains)
                self.assertEqual(app.task_gain("ad"), 18)
                status = app.task_stat("ad")
                self.assertEqual(status["gain_basis"], "prior_samples")
                self.assertEqual(status["gain_samples"], 3)
                self.assertEqual(status["gain_unmeasured_count"], 1)
                self.assertFalse(status["last_gain_measured"])
                self.assertEqual(path.read_bytes(), expected)

    async def test_direct_render_keeps_its_actual_duration_measurement(self):
        async def render(*_args, **_kwargs):
            self.clock += 2
            return {"path": "isolated-test.wav", "seconds": 6.0}

        with ExitStack() as stack:
            for name, value in {
                "configured_radio_voice": mock.Mock(return_value="original"),
                "voice_engine_for": mock.Mock(return_value="piper"),
                "pantry_get": mock.Mock(return_value=None), "pantry_put": mock.Mock(),
                "render_relief": mock.Mock(return_value=False), "prep_should_stop": mock.Mock(return_value=""),
                "voice_effect_pick": mock.Mock(return_value={}), "performance_vector": mock.Mock(return_value={}),
                "dj_settings": mock.Mock(return_value={}), "voice_render_any": mock.AsyncMock(side_effect=render),
                "engine_prep_take": mock.Mock(return_value=True), "engine_prep_give": mock.Mock(),
            }.items():
                stack.enter_context(mock.patch.object(app, name, value))
            made = await app.prep_render_line("Every word stays.", "dj", "original", "ad")
        self.assertEqual(made["seconds"], 6.0)
        self.assertEqual(self.ledger["render_line"]["gain"], [6.0])
        self.assertEqual(self.ledger["render_line"]["secs"], [2.0])
        self.assertTrue(self.ledger["render_line"]["last_gain_measured"])


REAL_LEDGER_LOAD = app.task_ledger_load


if __name__ == "__main__":
    unittest.main()
