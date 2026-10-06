"""Exercise one-click routes and station adapters without booting the station."""
import asyncio
import copy
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI, HTTPException
import httpx

from station_troubleshoot import StationTroubleshooter
from station_troubleshoot_runtime import StationTroubleshootRuntime, install


class StationRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.now = 1000.0
        self.time_patch = patch("station_troubleshoot_runtime.time.time", lambda: self.now)
        self.time_patch.start()
        self.active_worker = SimpleNamespace(done=Mock(return_value=False))
        self.ns = {
            "data_path": lambda name: Path(self.storage.name) / name,
            "radio_paused": lambda: False, "_RADIO": {"on": True},
            "_LARDER": [], "_SHELF": {}, "_DIALOGUE_RECOVERY": [],
            "dialogue_row_ready": lambda kind, row: bool(row.get("ready")),
            "row_unaired": lambda entry: not entry.get("aired_at"),
            "tint_recovery_status": lambda: {"why": ""},
            "recording_booths": lambda: {},
            "_RADIO_WORKERS": {"tint_recovery": {"task": self.active_worker}},
            "_DIALOGUE_HEARD": [900], "_LAST_HEARD": [999],
            "_LARDER_WRITING": [False], "_OLLAMA_GATE": asyncio.Lock(),
            "broadcast_triangulate": lambda: {"cause": "healthy", "why": "Music is audible.", "cure": ""},
            "dialogue_quiet_for": lambda: 0,
            "_RENDER_BACKLOG": [], "_BOX_HOLD": [], "_BUILD_MS": 800000,
            "_SYNTH_TRIED": [0], "_LAST_SYNTH": [0],
            "host_clone_engine": lambda: "f5",
            "f5_health": AsyncMock(return_value={"ready": True}),
            "xtts_health": AsyncMock(return_value={"ready": True}),
            "_system3": lambda: SimpleNamespace(ready=True),
            "_director_post": AsyncMock(return_value=True),
            "broadcast_step": AsyncMock(return_value={"ok": True, "changed": True}),
            "_s3_recover_larder_candidates": AsyncMock(return_value=0),
            "radio_worker_start": Mock(), "tint_recovery_clock": AsyncMock(),
            "tint_recovery_step": AsyncMock(return_value=False),
            "_TINT_RECOVERY_STATE": {"running": False},
            "_BROADCAST_RECOVERY_JOBS": SimpleNamespace(run=AsyncMock(return_value=(True, False))),
            "AIR_RESTART_STAMP": Path(self.storage.name) / "last-restart",
            "AIR_RESTART_REST": 3600,
            "HOSTSVC_KICK_PATH": Path(self.storage.name) / "hostsvc-kick",
        }
        self.runtime = StationTroubleshootRuntime(self.ns)

    def test_startup_quiet_counts_from_boot_without_inventing_a_speech_receipt(self):
        self.ns["_DIALOGUE_HEARD"] = [0]
        self.ns["_BUILD_MS"] = 990000
        view = self.runtime._snapshot()
        self.assertEqual(view["speech_quiet_seconds"], 10)
        self.assertEqual(view["heard_at"], 0)

    def test_quiet_uses_actual_speech_after_first_delivery(self):
        self.ns["_DIALOGUE_HEARD"] = [980]
        self.ns["_BUILD_MS"] = 990000
        self.assertEqual(self.runtime._snapshot()["speech_quiet_seconds"], 20)

    async def asyncTearDown(self):
        manager = self.runtime.manager
        if manager is not None:
            for task in manager._tasks.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*manager._tasks.values(), return_exceptions=True)
            if hasattr(manager, "flush"):
                await manager.flush()
        self.time_patch.stop()
        self.storage.cleanup()

    async def test_observation_uses_dialogue_receipts_instead_of_music_hearing(self):
        self.ns["_LARDER"] = [{"ready": True}, {"ready": False}]
        view = await self.runtime.observe()
        self.assertEqual(view["heard_at"], 900)
        self.assertNotEqual(view["heard_at"], self.ns["_LAST_HEARD"][0])
        self.assertEqual(view["ready"], 1)
        self.assertTrue(view["automatic_recovery"])

    async def test_advancing_speech_overrides_stale_queued_clip_diagnosis(self):
        self.ns["_DIALOGUE_HEARD"]=[999]
        self.ns["_PAGE_DELIVERIES"]={"dj":{"speech":True,"clip":{}}}
        self.ns["_PAGE_ACK_EVENTS"]=[{"at":999,"event":"playing","progressed":True,"audible_volume":1,"delivery_id":"dj"}]
        self.ns["broadcast_triangulate"]=lambda:{"cause":"not_started","why":"Old head has not started","cure":"reload_pages"}
        diagnosis=await self.runtime.diagnose()
        self.assertEqual(diagnosis["cause"],"healthy")
        self.assertEqual(diagnosis["actions"],[])
        self.assertEqual(diagnosis["production_health"]["state"],"degraded")

    async def test_maintenance_banks_low_reserve_while_current_audio_advances(self):
        self.ns["_LARDER"]=[{"ready":True}]
        self.ns["_PAGE_DELIVERIES"]={"dj":{"speech":True,"clip":{}}}
        self.ns["_PAGE_ACK_EVENTS"]=[{"at":1000,"event":"playing","progressed":True,"audible_volume":1,"delivery_id":"dj"}]
        await self.runtime.maintain()
        args=self.ns["_BROADCAST_RECOVERY_JOBS"].run.await_args.args
        self.assertEqual(args[0],"station-maintenance-bank")
        await args[1]()
        self.ns["broadcast_step"].assert_awaited_once_with("bank")

    async def test_maintenance_does_not_append_more_stock_to_a_long_queue(self):
        self.ns["_SHELF"]={"manager":[{"ready":True}]}
        self.ns["_LARDER"]=[{"ready":True}]*4
        self.ns["_PAGE_AIR_UNTIL"]=[1300]
        self.ns["_listeners_live"]=lambda:[{}]
        await self.runtime.maintain()
        self.ns["_BROADCAST_RECOVERY_JOBS"].run.assert_not_awaited()

    async def test_short_silent_queue_gets_one_approved_unheard_cupboard_performance(self):
        row={"ready":True,"at":990}
        self.ns.update(_SHELF={"manager":[row]},_listeners_live=lambda:[{}],
            record_follow_cue=Mock(return_value=True),unheard_stock_air=AsyncMock(return_value="manager"))
        result=await self.runtime.repair("cupboard_supply")
        self.assertTrue(result["changed"])
        self.ns["record_follow_cue"].assert_called_once_with("manager",row)
        self.ns["unheard_stock_air"].assert_awaited_once_with(force=True)

    async def test_active_speech_and_pause_protect_cupboard_handoff(self):
        self.ns["_listeners_live"]=lambda:[{}]
        self.ns["record_follow_cue"]=Mock()
        self.ns["unheard_stock_air"]=AsyncMock()
        self.ns["_PAGE_DELIVERIES"]={"dj":{"speech":True,"clip":{}}}
        self.ns["_PAGE_ACK_EVENTS"]=[{"at":1000,"event":"playing","progressed":True,"audible_volume":1,"delivery_id":"dj"}]
        result=await self.runtime.repair("cupboard_supply")
        self.assertTrue(result["pending"])
        self.ns["record_follow_cue"].assert_not_called()
        self.ns["unheard_stock_air"].assert_not_awaited()
        self.ns["radio_paused"]=lambda:True
        await self.runtime.maintain()
        self.ns["_BROADCAST_RECOVERY_JOBS"].run.assert_not_awaited()

    async def test_automatic_finishing_is_bounded_and_preserves_rejected_or_busy_rows(self):
        held={"off_brief":True};busy={"preparing":True}
        approved=[{"id":str(i),"script":"approved"} for i in range(7)]
        rows=[("banter",r) for r in [held,busy,*approved]]
        added=[]
        self.ns.update(cupboard_incomplete_rows=lambda:rows,cupboard_finish_ids=lambda:set(),
            retire_id=lambda k,r:r.get("id","held"),dialogue_row_viable=lambda k,r:True,
            dialogue_tint_ready=lambda k,r:True,cupboard_finish_add=lambda k,r,w:added.append(r) or {"ok":True})
        result=await self.runtime.repair("finish_recordings")
        self.assertEqual(result["added"],4)
        self.assertEqual(added,approved[:4])
        self.assertTrue(held["off_brief"])
        self.assertTrue(busy["preparing"])

    async def test_maintenance_failure_does_not_stop_silence_watchdog(self):
        self.ns["_listeners_live"]=lambda:[{}]
        self.runtime.maintain=AsyncMock(side_effect=RuntimeError("failed maintenance"))
        manager=SimpleNamespace(status=lambda:{"running":False},start=Mock(return_value={"id":"recovery"}))
        self.runtime.get_manager=AsyncMock(return_value=manager)
        self.assertTrue(await self.runtime.watch_once())
        manager.start.assert_called_once()

    async def test_silent_ad_only_reserve_is_delivered_and_new_conversation_is_banked(self):
        self.ns["_SHELF"]={"ad":[{"ready":True}]}
        self.ns["DIALOGUE_QUIET_ALARM"]=60
        self.ns["dialogue_quiet_for"]=lambda:100
        diagnosis=await self.runtime.diagnose()
        self.assertEqual([row["step"] for row in diagnosis["actions"]],["stock","bank"])
        await self.ns["_OLLAMA_GATE"].acquire()
        try:
            diagnosis=await self.runtime.diagnose()
            self.assertEqual([row["step"] for row in diagnosis["actions"]],["stock"])
        finally:
            self.ns["_OLLAMA_GATE"].release()

    async def test_diagnosis_requests_only_the_failed_selected_voice_engine(self):
        self.ns.update({"_RENDER_BACKLOG": [{"line": "owed"}],
                        "_SYNTH_TRIED": [900], "_LAST_SYNTH": [600]})
        self.ns["f5_health"].return_value = {"ready": False}
        diagnosis = await self.runtime.diagnose()
        self.assertEqual([row["step"] for row in diagnosis["actions"]], ["voice:f5"])
        self.ns["f5_health"].assert_awaited_once()
        self.ns["xtts_health"].assert_not_awaited()
        self.assertTrue((await self.runtime.repair("voice:f5"))["ok"])
        self.ns["_director_post"].assert_awaited_once_with("/director/engine/f5/deploy")
        self.ns["broadcast_step"].assert_not_awaited()

    async def test_healthy_selected_voice_engine_is_not_reloaded(self):
        self.ns.update({"_RENDER_BACKLOG": [{"line": "owed"}],
                        "_SYNTH_TRIED": [900], "_LAST_SYNTH": [600]})
        diagnosis = await self.runtime.diagnose()
        self.assertEqual(diagnosis["actions"], [])
        self.ns["_director_post"].assert_not_awaited()

    def writer_probe(self, statuses):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.side_effect = [httpx.Response(status, request=httpx.Request(
            "GET", "http://writer.test/api/tags")) for status in statuses]
        self.ns["OLLAMA_URL"] = "http://writer.test/"
        return client

    async def test_two_failed_writer_probes_diagnose_only_writer_restart(self):
        client = self.writer_probe([503, 503])
        with patch("station_troubleshoot_runtime.httpx.AsyncClient", return_value=client):
            diagnosis = await self.runtime.diagnose()
        self.assertEqual([row["step"] for row in diagnosis["actions"]], ["writer_service"])
        self.assertTrue(diagnosis["actions"][0]["restart"])
        self.assertEqual(client.get.await_count, 2)
        client.get.assert_awaited_with("http://writer.test/api/tags")
        self.ns["broadcast_step"].assert_not_awaited()

    async def test_healthy_or_transiently_failed_writer_probe_needs_no_restart(self):
        for statuses in ([200], [503, 200]):
            with self.subTest(statuses=statuses):
                client = self.writer_probe(statuses)
                with patch("station_troubleshoot_runtime.httpx.AsyncClient", return_value=client):
                    diagnosis = await self.runtime.diagnose()
                self.assertEqual(diagnosis["actions"], [])
                self.assertEqual(client.get.await_count, len(statuses))

    async def test_writer_restart_sends_only_named_host_supervisor_signal(self):
        result = await self.runtime.repair("writer_service")
        self.assertTrue(result["changed"])
        self.assertEqual(self.ns["HOSTSVC_KICK_PATH"].read_text(), "ollama")
        self.assertEqual([path.name for path in Path(self.storage.name).iterdir()], ["hostsvc-kick"])
        self.ns["_director_post"].assert_not_awaited()
        self.ns["broadcast_step"].assert_not_awaited()

    async def test_active_writer_is_not_probed_or_restarted(self):
        self.ns["_LARDER_WRITING"] = [True]
        client = self.writer_probe([503, 503])
        with patch("station_troubleshoot_runtime.httpx.AsyncClient", return_value=client):
            diagnosis = await self.runtime.diagnose()
        self.assertEqual(diagnosis["actions"], [])
        client.get.assert_not_awaited()
        self.assertFalse((await self.runtime.repair("writer_service"))["changed"])
        self.assertFalse(self.ns["HOSTSVC_KICK_PATH"].exists())

    async def test_recording_in_progress_prevents_voice_and_station_restart(self):
        self.ns["recording_booths"] = lambda: {"live": True}
        voice = await self.runtime.repair("voice:f5")
        station = await self.runtime.repair("restart_station")
        self.assertFalse(voice["changed"])
        self.assertFalse(station["changed"])
        self.ns["_director_post"].assert_not_awaited()
        self.ns["broadcast_step"].assert_not_awaited()
        self.assertFalse(self.ns["AIR_RESTART_STAMP"].exists())

    async def test_selected_engine_recording_also_prevents_voice_restart(self):
        self.ns["recording_booths"] = lambda: {"engines": {"f5": 1}}
        self.assertFalse((await self.runtime.repair("voice:f5"))["changed"])
        self.ns["_director_post"].assert_not_awaited()

    async def test_selected_engine_recording_also_prevents_station_restart(self):
        self.ns["recording_booths"] = lambda: {"engines": {"f5": 1}}
        self.assertFalse((await self.runtime.repair("restart_station"))["changed"])
        self.ns["broadcast_step"].assert_not_awaited()
        self.assertFalse(self.ns["AIR_RESTART_STAMP"].exists())

    async def test_concurrent_manager_loads_share_one_off_loop_constructor(self):
        thread_ids = []
        marker = SimpleNamespace(status=Mock())

        def construct(**kwargs):
            thread_ids.append(threading.get_ident())
            self.assertEqual(kwargs["persist_path"], Path(self.storage.name) / "station_troubleshoot.json")
            return marker

        with patch("station_troubleshoot_runtime.StationTroubleshooter", side_effect=construct) as constructor:
            first, second = await asyncio.gather(self.runtime.get_manager(), self.runtime.get_manager())
            self.assertIs(first, marker)
            self.assertIs(second, marker)
            constructor.assert_called_once()
            self.assertNotEqual(thread_ids[0], threading.get_ident())
        self.runtime.manager = None

    async def test_station_restart_respects_saved_rest_and_only_restarts_station(self):
        self.now = 10000
        self.assertTrue((await self.runtime.repair("restart_station"))["changed"])
        self.assertEqual(float(self.ns["AIR_RESTART_STAMP"].read_text()), self.now)
        self.assertFalse((await self.runtime.repair("restart_station"))["changed"])
        self.ns["broadcast_step"].assert_awaited_once_with("restart")
        self.ns["_director_post"].assert_not_awaited()

    async def test_recovery_request_preserves_cooldown_and_reuses_existing_worker(self):
        self.ns["_LARDER"] = [{"ready": True}]
        state = {"active": True, "pass": 4, "attempt": 3, "total_attempts": 12,
                 "style_level": 2, "cooldown_until": 1200, "last_reason": "alignment rejected"}
        self.ns["_DIALOGUE_RECOVERY"] = [{"id": "owed-conversation", "kind": "banter",
                                         "ready_at": 1100, "entry": {"dialogue_recovery": state}}]
        before = copy.deepcopy(self.ns["_DIALOGUE_RECOVERY"])
        result = await self.runtime.request_recovery("job-1")
        self.assertEqual(self.ns["_DIALOGUE_RECOVERY"], before)
        self.assertEqual(result["next_retry_at"], 1200)
        self.assertTrue(result["pending"])
        self.ns["radio_worker_start"].assert_not_called()
        self.ns["_BROADCAST_RECOVERY_JOBS"].run.assert_awaited_once_with(
            "station-dialogue-recovery", self.ns["tint_recovery_step"], 20.0)
        self.ns["broadcast_step"].assert_not_awaited()

    async def test_empty_conversation_reserve_prioritizes_fresh_work_over_failed_drafts(self):
        self.ns["_DIALOGUE_RECOVERY"]=[{"id":"held","entry":{}}]
        result=await self.runtime.request_recovery("fresh-job")
        self.assertTrue(result["pending"])
        args=self.ns["_BROADCAST_RECOVERY_JOBS"].run.await_args.args
        self.assertEqual(args[0],"station-fresh-dialogue")
        await args[1]()
        self.ns["broadcast_step"].assert_awaited_once_with("bank")
        self.ns["tint_recovery_step"].assert_not_awaited()

    async def test_missing_recovery_worker_restarts_under_its_existing_name(self):
        self.ns["_RADIO_WORKERS"] = {}
        self.ns["_TINT_RECOVERY_STATE"] = {"running": True}
        result = await self.runtime.request_recovery("job-2")
        self.assertTrue(result["pending"])
        self.ns["radio_worker_start"].assert_called_once_with("tint_recovery", self.ns["tint_recovery_clock"])
        self.ns["_BROADCAST_RECOVERY_JOBS"].run.assert_not_awaited()

    async def test_operator_pause_does_not_admit_or_start_recovery(self):
        self.ns["radio_paused"] = lambda: True
        diagnosis = await self.runtime.diagnose()
        result = await self.runtime.request_recovery("job-paused")
        self.assertEqual(diagnosis["actions"], [])
        self.assertFalse(result["ok"])
        self.ns["_s3_recover_larder_candidates"].assert_not_awaited()
        self.ns["radio_worker_start"].assert_not_called()

    def make_routes(self):
        def require_auth(value):
            if value != "Bearer editor":
                raise HTTPException(401, "write authorization required")

        def require_read_auth(value):
            if value not in ("Bearer reader", "Bearer editor"):
                raise HTTPException(401, "read authorization required")

        self.ns.update(require_auth=require_auth, require_read_auth=require_read_auth)
        app = FastAPI()
        self.runtime = install(app, self.ns)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://station.test")

    async def test_start_requires_write_auth_and_status_requires_read_auth(self):
        async with self.make_routes() as client:
            for header in (None, "Bearer reader"):
                response = await client.post("/api/station/troubleshoot", json={},
                    headers={"Authorization": header} if header else {})
                self.assertEqual(response.status_code, 401)
            self.assertIsNone(self.runtime.manager)
            response = await client.get("/api/station/troubleshoot/not-a-job")
            self.assertEqual(response.status_code, 401)

    async def test_actual_routes_join_running_job_and_return_saved_status(self):
        release = asyncio.Event()
        async with self.make_routes() as client:
            async def diagnose():
                await release.wait()
                return {"cause": "dialogue_rejected", "actions": []}

            self.runtime.manager = StationTroubleshooter(
                diagnose=diagnose, repair=AsyncMock(),
                request_recovery=AsyncMock(return_value={"ok": True, "pending": 1}),
                observe=AsyncMock(return_value={"heard_at": 900, "pending": 1}),
                persist_path=Path(self.storage.name) / "route-jobs.json", verify_seconds=0)
            first = await client.post("/api/station/troubleshoot", json={"allow_restarts": True},
                                      headers={"Authorization": "Bearer editor"})
            second = await client.post("/api/station/troubleshoot", json={},
                                       headers={"Authorization": "Bearer editor"})
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.json()["id"], first.json()["id"])
            self.assertTrue(first.json()["allow_restarts"])
            release.set()
            report = await self.runtime.manager.wait(first.json()["id"])
            status = await client.get("/api/station/troubleshoot/" + report["id"],
                                      headers={"Authorization": "Bearer reader"})
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()["status"], "pending")
            self.assertFalse(status.json()["verified"])
            self.runtime.manager.request_recovery.assert_awaited_once()
            missing = await client.get("/api/station/troubleshoot/missing", headers={"Authorization": "Bearer reader"})
            self.assertEqual(missing.status_code, 404)

    async def test_actual_route_rejects_nonobject_and_can_diagnose_without_start(self):
        async with self.make_routes() as client:
            invalid = await client.post("/api/station/troubleshoot", json=[],
                                        headers={"Authorization": "Bearer editor"})
            self.assertEqual(invalid.status_code, 400)
            self.runtime.diagnose = AsyncMock(return_value={"cause": "dialogue_rejected", "actions": []})
            diagnosis = await client.post("/api/station/troubleshoot", json={"fix": False},
                                          headers={"Authorization": "Bearer editor"})
            self.assertEqual(diagnosis.status_code, 200)
            self.assertEqual(diagnosis.json()["cause"], "dialogue_rejected")
            self.assertIsNone(self.runtime.manager)
            self.runtime.diagnose.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
