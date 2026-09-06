import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import httpx
import app
from resource_guard import ResourceHistory, assess, available_gb, engine_busy, memory_snapshot, gpu_snapshot


class ResourceDecisions(unittest.TestCase):
    def test_neural_summary_keeps_resource_failure_evidence_ahead_of_large_inventory(self):
        history = mock.Mock(rows=[{"at": 100, "memory": {"avail_gb": 10},
                                  "decision": {"tier": "critical"},
                                  "action": {"kind": "free_comfy_cache", "ok": False}}])
        with mock.patch.object(app, "_RESOURCE_HISTORY", history):
            resources = app.resource_brief(since=50, until=200)
        report = {"id": "real-hour", "score": 42, "baseline": {"huge": "x" * 30000},
                  "resources": resources, "roads": {"caller": {"attainment": 0.4, "met": False}}}
        text = app.coord_embedding_text(report)
        self.assertIn('"ok": false', text)
        self.assertIn('"attainment": 0.4', text)
        self.assertNotIn("huge", text)
        self.assertLessEqual(len(text), 16000)

    def test_gb10_unsupported_dedicated_vram_is_unknown_while_utilization_is_measured(self):
        with mock.patch("resource_guard.subprocess.run", return_value=mock.Mock(
                stdout="NVIDIA GB10, 87, 66, 37.44, [N/A], [N/A]\n")):
            state = gpu_snapshot()
        self.assertEqual(state["utilization_percent"], 87)
        self.assertIsNone(state["dedicated_memory_total_mib"])
        self.assertTrue(state["observed"])

    def test_missing_or_invalid_telemetry_never_means_memory_pressure(self):
        for value in ({}, {"avail_gb": None}, {"avail_gb": "bad"},
                      {"avail_gb": float("nan")}, {"avail_gb": -1}):
            self.assertIsNone(available_gb(value))
            decision = assess({"memory": value}, 4)
            self.assertEqual(decision["tier"], "unknown")
            self.assertEqual(decision["actions"], [])

    def test_healthy_memory_retains_models_despite_busy_gpu_and_idle_cache(self):
        decision = assess({"memory": {"avail_gb": 51.2}, "gpu": {"utilization": 96},
                           "comfy": {"observed": True, "busy": False, "idle_seconds": 900}}, 4)
        self.assertEqual(decision["tier"], "healthy")
        self.assertEqual(decision["actions"], [])

    def test_reclaim_requires_sustained_pressure_observed_empty_queue_and_idle(self):
        snapshot = {"memory": {"avail_gb": 11},
                    "comfy": {"observed": True, "busy": False, "idle_seconds": 600}}
        self.assertEqual(assess(snapshot, 1)["actions"], [])
        self.assertEqual(assess(snapshot, 2)["actions"][0]["kind"], "free_comfy_cache")
        for field, value in (("busy", True), ("observed", False), ("idle_seconds", 20)):
            old = snapshot["comfy"][field]
            snapshot["comfy"][field] = value
            self.assertEqual(assess(snapshot, 3)["actions"], [])
            snapshot["comfy"][field] = old

    def test_active_shared_preparation_and_recent_external_render_protect_engine(self):
        for booths in ({"live": 1}, {"preparing": 1}, {"engines": {"shared": 1}},
                       {"engines": {"xtts": 1}}):
            self.assertTrue(engine_busy("xtts", booths))
        self.assertTrue(engine_busy("xtts", {}, {"xtts": 5}))
        self.assertFalse(engine_busy("xtts", {"engines": {"f5": 1}}, {"xtts": 120}))

    def test_host_memory_and_durable_history_keep_real_evidence_without_airtime_credit(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "meminfo"
            path.write_text("MemTotal: 131072000 kB\nMemAvailable: 52428800 kB\n")
            snapshot = {"memory": memory_snapshot(path), "writing": {"waiting": 2}}
            snapshot.update(models=[{"name": "station-writer", "busy": True}],
                            comfy={"observed": True, "busy": False, "idle_seconds": 700},
                            engines_last_render_seconds={"xtts": 12})
            history = ResourceHistory(Path(root) / "resources.json")
            history.record(snapshot, assess(snapshot))
            restored = ResourceHistory(history.path).rows
            self.assertEqual(restored[0]["memory"]["avail_gb"], 50.0)
            for key in ("models", "comfy", "engines_last_render_seconds"):
                self.assertEqual(restored[0][key], snapshot[key])
            self.assertNotIn("broadcast_outcome", restored[0])

    def test_resource_history_retains_at_most_120_observations_after_reload(self):
        with tempfile.TemporaryDirectory() as root:
            history = ResourceHistory(Path(root) / "resources.json")
            history.rows = [{"at": at} for at in range(ResourceHistory.MAX_SAMPLES)]
            history.record({"memory": {"avail_gb": 40}}, {"tier": "healthy"})
            restored = ResourceHistory(history.path).rows
        self.assertEqual(len(restored), 120)
        self.assertEqual(restored[0]["at"], 1)

    def test_hour_summary_keeps_early_pressure_and_failed_actions_without_job_graphs(self):
        def row(at, available, tier):
            return {"at": at, "memory": {"avail_gb": available},
                    "writing": {"jobs": [{"id": "not-for-hour-summary"}]},
                    "decision": {"tier": tier, "reason": "Measured " + tier}}
        rows = [row(90, 99, "healthy"), row(110, 10, "critical"),
                row(200, None, "unknown"), row(300, 40, "healthy"),
                row(400, 50, "healthy"), row(500, 60, "healthy"), row(1100, 2, "critical")]
        rows[1]["action"] = {"kind": "free_comfy_cache", "ok": False,
                             "why": "New image work was observed"}
        with (mock.patch.object(app, "_RESOURCE_HISTORY", mock.Mock(rows=rows)),
              mock.patch.object(app, "_RESOURCE_STATE", {"at": 590, "memory": {"avail_gb": 60}})):
            brief = app.resource_brief(since=100, until=600)
        hour = brief["history"]
        self.assertEqual(hour["samples"], 5)
        self.assertEqual(hour["available_gb"], {"min": 10, "max": 60})
        self.assertEqual(hour["tier_counts"], {"critical": 1, "unknown": 1, "healthy": 3})
        self.assertEqual(hour["memory_samples"], 4)
        self.assertEqual(hour["missing_memory_samples"], 1)
        self.assertFalse(hour["actions"][0]["ok"])
        self.assertEqual(hour["actions"][0]["why"], "New image work was observed")
        self.assertEqual(hour["actions"][0]["reason"], "Measured critical")
        self.assertEqual(hour["retention"]["first_in_interval"], 110)
        self.assertEqual(hour["retention"]["last_in_interval"], 500)
        self.assertNotIn("not-for-hour-summary", json.dumps(hour))
        self.assertEqual(brief["at"], 590)

    def test_hour_summary_bounds_action_details_and_labels_partial_retention(self):
        rows = [{"at": at, "memory": {}, "decision": {"tier": "unknown", "reason": str(at)},
                 "action": {"kind": "free_comfy_cache", "ok": False}}
                for at in range(100, 125)]
        with (mock.patch.object(app, "_RESOURCE_HISTORY", mock.Mock(rows=rows)),
              mock.patch.object(app, "_RESOURCE_STATE", {})):
            hour = app.resource_brief(since=50, until=200)["history"]
        self.assertEqual(hour["action_count"], 25)
        self.assertEqual(len(hour["actions"]), 20)
        self.assertEqual(hour["reason_count"], 25)
        self.assertEqual(len(hour["reasons"]), 20)
        self.assertEqual(hour["available_gb"], {"min": None, "max": None})
        self.assertEqual(hour["retention"]["sample_limit"], 120)
        self.assertIn("precedes retained", hour["retention"]["coverage"])


class LifecycleProtection(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name, value in (("_XTTS_FAILS", []), ("_XTTS_BOUNCE_AT", [0]),
                            ("_XTTS_BOUNCE_PENDING", [""]),
                            ("_XTTS_BOUNCE_GATE", asyncio.Lock())):
            patch = mock.patch.object(app, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    async def test_director_cannot_terminate_during_live_or_prep_render(self):
        with (mock.patch.object(app, "recording_booths", return_value={"live": 1}),
              mock.patch.object(app.httpx, "AsyncClient") as client):
            self.assertFalse(await app._director_post("/director/engine/xtts/terminate"))
        client.assert_not_called()

    async def test_director_rejection_is_failure_without_restarting_healthy_director(self):
        response = httpx.Response(503, request=httpx.Request("POST", "http://director/deploy"))
        client = mock.AsyncMock()
        client.post.return_value = response
        context = mock.MagicMock()
        context.__aenter__ = mock.AsyncMock(return_value=client)
        context.__aexit__ = mock.AsyncMock(return_value=False)
        with (mock.patch.object(app.httpx, "AsyncClient", return_value=context),
              mock.patch.object(app, "_lifeboat_restart") as restart):
            self.assertFalse(await app._director_post("/director/engine/xtts/deploy"))
        restart.assert_not_called()

    async def test_deferred_bounce_retains_failures_then_repairs_after_work_finishes(self):
        failures = [time.time()] * 3
        with (mock.patch.object(app, "_XTTS_FAILS", failures),
              mock.patch.object(app, "_XTTS_BOUNCE_AT", [0]),
              mock.patch.object(app, "xtts_health", return_value={"ready": True}),
              mock.patch.object(app, "resource_engine_protected", side_effect=[True, False]),
              mock.patch.object(app, "_director_post", return_value=True) as director,
              mock.patch.object(app.asyncio, "sleep"), mock.patch.object(app, "pipeline_log")):
            await app._xtts_bounce_maybe(observe_failure=False)
            self.assertEqual(len(failures), 3)
            director.assert_not_called()
            await app._xtts_bounce_maybe(observe_failure=False)
            self.assertEqual(failures, [])
            self.assertEqual([call.args[0] for call in director.await_args_list],
                             ["/director/engine/xtts/terminate", "/director/engine/xtts/deploy"])

    async def test_deferred_bounce_outlives_original_failure_window(self):
        app._XTTS_FAILS[:] = [9999] * 3
        with (mock.patch.object(app, "xtts_health", return_value={"ready": True}),
              mock.patch.object(app, "resource_engine_protected", return_value=True) as protected,
              mock.patch.object(app, "_director_post", return_value=True) as director,
              mock.patch.object(app.asyncio, "sleep"), mock.patch.object(app, "pipeline_log"),
              mock.patch.object(app.time, "time", return_value=10000) as clock):
            await app._xtts_bounce_maybe(observe_failure=False)
            self.assertEqual(app._XTTS_BOUNCE_PENDING[0], "terminate")
            protected.return_value = False
            clock.return_value = 10700
            await app._xtts_bounce_maybe(observe_failure=False)
        self.assertEqual(director.await_count, 2)
        self.assertEqual(app._XTTS_BOUNCE_PENDING[0], "")
        self.assertEqual(app._XTTS_FAILS, [])

    async def test_refused_termination_keeps_pending_evidence_and_retry_budget(self):
        app._XTTS_FAILS[:] = [time.time()] * 3
        with (mock.patch.object(app, "xtts_health", return_value={"ready": True}),
              mock.patch.object(app, "resource_engine_protected", return_value=False),
              mock.patch.object(app, "_director_post", return_value=False),
              mock.patch.object(app, "pipeline_log")):
            await app._xtts_bounce_maybe(observe_failure=False)
        self.assertEqual(app._XTTS_BOUNCE_PENDING[0], "terminate")
        self.assertEqual(len(app._XTTS_FAILS), 3)
        self.assertEqual(app._XTTS_BOUNCE_AT[0], 0)

    async def test_failed_deployment_retries_without_terminating_again(self):
        app._XTTS_FAILS[:] = [time.time()] * 3
        with (mock.patch.object(app, "xtts_health", return_value={"ready": True}) as health,
              mock.patch.object(app, "resource_engine_protected", return_value=False),
              mock.patch.object(app, "_director_post", side_effect=[True, False, True]) as director,
              mock.patch.object(app.asyncio, "sleep"), mock.patch.object(app, "pipeline_log")):
            await app._xtts_bounce_maybe(observe_failure=False)
            self.assertEqual(app._XTTS_BOUNCE_PENDING[0], "deploy")
            self.assertEqual(app._XTTS_BOUNCE_AT[0], 0)
            self.assertEqual(len(app._XTTS_FAILS), 3)
            health.reset_mock()
            await app._xtts_bounce_maybe(observe_failure=False)
            health.assert_not_called()
        self.assertEqual([call.args[0].rsplit("/", 1)[-1] for call in director.await_args_list],
                         ["terminate", "deploy", "deploy"])
        self.assertEqual(app._XTTS_BOUNCE_PENDING[0], "")
        self.assertGreater(app._XTTS_BOUNCE_AT[0], 0)

    async def test_observation_clock_does_not_manufacture_render_failures(self):
        with mock.patch.object(app, "_director_post") as director:
            for _ in range(4):
                await app._xtts_bounce_maybe(observe_failure=False)
        self.assertEqual(app._XTTS_FAILS, [])
        self.assertEqual(app._XTTS_BOUNCE_PENDING[0], "")
        director.assert_not_called()

    async def test_director_retry_rechecks_new_active_work(self):
        client = mock.AsyncMock()
        client.post.side_effect = httpx.ConnectError("director temporarily unreachable")
        context = mock.MagicMock()
        context.__aenter__ = mock.AsyncMock(return_value=client)
        context.__aexit__ = mock.AsyncMock(return_value=False)
        with (mock.patch.object(app.httpx, "AsyncClient", return_value=context),
              mock.patch.object(app, "resource_engine_protected", side_effect=[False, False, True]),
              mock.patch.object(app, "recording_booths", return_value={}),
              mock.patch.object(app, "_lifeboat_restart", return_value=True) as restart,
              mock.patch.object(app.asyncio, "sleep")):
            self.assertFalse(await app._director_post("/director/engine/xtts/terminate"))
        restart.assert_awaited_once()
        client.post.assert_awaited_once()

    async def test_director_restart_protects_work_on_another_engine(self):
        client = mock.AsyncMock()
        client.post.side_effect = httpx.ReadTimeout("director is slow")
        context = mock.MagicMock()
        context.__aenter__ = mock.AsyncMock(return_value=client)
        context.__aexit__ = mock.AsyncMock(return_value=False)
        with (mock.patch.object(app.httpx, "AsyncClient", return_value=context),
              mock.patch.object(app, "resource_engine_protected", return_value=False),
              mock.patch.object(app, "recording_booths", return_value={"preparing": 1, "engines": {"f5": 1}}),
              mock.patch.object(app, "_lifeboat_restart") as restart):
            self.assertFalse(await app._director_post("/director/engine/xtts/terminate"))
        restart.assert_not_called()

    async def test_pressure_reclaim_rechecks_image_queue_and_preserves_new_work(self):
        calls = 0
        async def get(url):
            nonlocal calls
            if url.endswith("/queue"):
                calls += 1
                payload = {"queue_running": [] if calls == 1 else [[1, "new job"]], "queue_pending": []}
            elif url.endswith("/api/ps"):
                payload = {"models": []}
            else:
                payload = {"avail_gb": 10}
            return httpx.Response(200, json=payload, request=httpx.Request("GET", url))
        client = mock.AsyncMock()
        client.get.side_effect = get
        context = mock.MagicMock()
        context.__aenter__ = mock.AsyncMock(return_value=client)
        context.__aexit__ = mock.AsyncMock(return_value=False)
        with (mock.patch.object(app.httpx, "AsyncClient", return_value=context),
              mock.patch.object(app, "memory_snapshot", return_value={"avail_gb": 10}),
              mock.patch.object(app, "gpu_snapshot", return_value={}),
              mock.patch.object(app, "_RESOURCE_GATE", asyncio.Lock()),
              mock.patch.object(app, "_RESOURCE_PRESSURE_SAMPLES", [1]),
              mock.patch.object(app, "_RESOURCE_RECLAIM_AT", [0]),
              mock.patch.object(app, "_RESOURCE_COMFY_IDLE_SINCE", [time.time() - 600]),
              mock.patch.object(app, "_COMFY_LAST_USED", [time.time() - 600]),
              mock.patch.object(app, "_RESOURCE_STATE", {}),
              mock.patch.object(app, "_RESOURCE_HISTORY") as history,
              mock.patch.object(app, "recording_booths", return_value={}),
              mock.patch.object(app, "writing_room_state", return_value={}),
              mock.patch.object(app, "radio_owned_models", return_value=[]),
              mock.patch.object(app, "station_flow_event") as event):
            await app.resource_sample()
        client.post.assert_not_called()
        self.assertFalse(history.record.call_args.args[2]["ok"])
        self.assertNotIn("broadcast_outcome", event.call_args.args[3])

    async def test_external_image_work_resets_idle_observation_before_reclaim(self):
        queue = {"queue_running": [[1, "external client job"]], "queue_pending": []}
        async def get(url):
            payload = queue if url.endswith("/queue") else {"models": [], "avail_gb": 10}
            return httpx.Response(200, json=payload, request=httpx.Request("GET", url))
        client = mock.AsyncMock()
        client.get.side_effect = get
        context = mock.MagicMock()
        context.__aenter__ = mock.AsyncMock(return_value=client)
        context.__aexit__ = mock.AsyncMock(return_value=False)
        idle = [time.time() - 600]
        with (mock.patch.object(app.httpx, "AsyncClient", return_value=context),
              mock.patch.object(app, "memory_snapshot", return_value={"avail_gb": 10}),
              mock.patch.object(app, "gpu_snapshot", return_value={}),
              mock.patch.object(app, "_RESOURCE_GATE", asyncio.Lock()),
              mock.patch.object(app, "_RESOURCE_PRESSURE_SAMPLES", [2]),
              mock.patch.object(app, "_RESOURCE_RECLAIM_AT", [0]),
              mock.patch.object(app, "_RESOURCE_COMFY_IDLE_SINCE", idle),
              mock.patch.object(app, "_COMFY_LAST_USED", [time.time() - 600]),
              mock.patch.object(app, "_RESOURCE_STATE", {}),
              mock.patch.object(app, "_RESOURCE_HISTORY"),
              mock.patch.object(app, "recording_booths", return_value={}),
              mock.patch.object(app, "writing_room_state", return_value={}),
              mock.patch.object(app, "radio_owned_models", return_value=[])):
            await app.resource_sample()
            self.assertEqual(idle[0], 0)
            queue["queue_running"] = []
            fresh_start = time.time()
            snapshot = await app.resource_sample()
            self.assertGreaterEqual(idle[0], fresh_start)
            self.assertLess(snapshot["comfy"]["idle_seconds"], 1)
        client.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
