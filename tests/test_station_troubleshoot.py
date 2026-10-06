import asyncio
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from station_troubleshoot import StationTroubleshooter


class StationTroubleshootTests(unittest.IsolatedAsyncioTestCase):
    async def test_speech_absence_rediagnoses_and_repairs_newly_ready_stock_once(self):
        checks=[]
        def diagnose():
            checks.append(self.now)
            return {"pending":0,"actions":[] if len(checks)==1 else [{"step":"stock"}]}
        runner=self.make(diagnose=diagnose,
            observe=lambda:{"heard_at":self.now if self.repairs else 0,"pending":0},
            sustain_seconds=2,minimum_receipts=2,max_quiet_seconds=1,rediagnose_seconds=2)
        done=await runner.wait(runner.start()["id"])
        self.assertTrue(done["verified"])
        self.assertEqual(self.repairs,["stock"])
        self.assertGreaterEqual(len(checks),2)

    async def test_repeated_diagnosis_keeps_the_same_action_bound_and_restart_opt_out(self):
        runner=self.make(diagnose=lambda:{"actions":[{"step":"stock"},{"step":"stream","restart":True}]},
            observe=lambda:{"heard_at":0,"pending":0},max_actions=2,
            max_quiet_seconds=1,rediagnose_seconds=2)
        done=await runner.wait(runner.start(allow_restarts=False)["id"])
        self.assertFalse(done["verified"])
        self.assertEqual(self.repairs,["stock"])
        self.assertEqual(done["attempted_actions"],["stock"])

    async def test_one_receipt_cannot_prove_sustained_flow(self):
        runner=self.make(observe=lambda:{"heard_at":1001,"pending":0},sustain_seconds=4,minimum_receipts=3)
        job=runner.start();result=await runner.wait(job["id"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["flow_proof"]["receipts"],1)

    async def test_multiple_receipts_with_a_stable_queue_prove_sustained_flow(self):
        runner=self.make(observe=lambda:{"heard_at":self.now,"pending":0},sustain_seconds=4,minimum_receipts=3)
        job=runner.start();result=await runner.wait(job["id"])
        self.assertTrue(result["verified"])
        self.assertGreaterEqual(result["flow_proof"]["window_seconds"],4)

    async def test_growing_backlog_reports_verified_playback_and_pending_production(self):
        runner=self.make(diagnose=lambda:{"pending":1},observe=lambda:{"heard_at":self.now,"pending":2},sustain_seconds=4,minimum_receipts=3)
        job=runner.start();result=await runner.wait(job["id"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["production_status"], "pending")
        self.assertIn("2 draft(s) remain", result["report"])

    async def test_deferred_repair_retries_then_completes_without_duplicate_success(self):
        attempts=[]
        def repair(step):
            attempts.append(step)
            return {"ok": len(attempts)>1, "pending": len(attempts)==1}
        runner=self.make(diagnose=lambda:{"actions":[{"step":"stock"}]},repair=repair,
            observe=lambda:{"heard_at":self.now if len(attempts)>1 else 0},
            rediagnose_seconds=2,repair_retry_seconds=2,max_quiet_seconds=1,
            sustain_seconds=2,minimum_receipts=2)
        result=await runner.wait(runner.start()["id"])
        self.assertTrue(result["verified"])
        self.assertEqual(attempts,["stock","stock"])
        self.assertEqual(result["completed_actions"],["stock"])

    async def test_failed_draft_worker_does_not_prevent_repair_or_playback_verification(self):
        def request(job_id):raise RuntimeError("writer unavailable")
        runner=self.make(request=request,
            diagnose=lambda:{"actions":[] if self.now==1000 else [{"step":"stock"}]},
            observe=lambda:{"heard_at":self.now if self.repairs else 0,"pending":5},
            rediagnose_seconds=2,max_quiet_seconds=1,sustain_seconds=2,minimum_receipts=2)
        result=await runner.wait(runner.start()["id"])
        self.assertTrue(result["verified"])
        self.assertEqual(self.repairs,["stock"])
        self.assertEqual(result["recovery_error"],"RuntimeError")
        self.assertEqual(result["production_status"],"pending")

    async def test_permanently_failed_repair_has_a_bounded_retry_budget(self):
        attempts=[]
        def repair(step):
            attempts.append(step)
            return {"ok":False}
        runner=self.make(repair=repair,diagnose=lambda:{"actions":[{"step":"stock"}]},
            observe=lambda:{"heard_at":0},rediagnose_seconds=2,repair_retry_seconds=2,
            repair_attempts=2,max_quiet_seconds=1)
        result=await runner.wait(runner.start()["id"])
        self.assertFalse(result["verified"])
        self.assertEqual(attempts,["stock","stock"])
        self.assertEqual(result["completed_actions"],[])

    def setUp(self):
        self.now = 1000.0
        self.repairs = []
        self.requests = []
        self.storage = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.storage.cleanup()

    async def sleep(self, seconds):
        self.now += seconds
        await asyncio.sleep(0)

    def make(self, *, diagnose=None, repair=None, request=None, observe=None, **kwargs):
        def default_repair(step):
            self.repairs.append(step)
            return {"ok": True, "changed": True}

        def default_request(job_id):
            self.requests.append(job_id)
            return {"pending": 1, "automatic_recovery": True}

        return StationTroubleshooter(
            diagnose=diagnose or (lambda: {"cause": "dialogue_rejected", "actions": []}),
            repair=repair or default_repair,
            request_recovery=request or default_request,
            observe=observe or (lambda: {"heard_at": 999, "ready": 0, "pending": 1,
                                         "automatic_recovery": True}),
            clock=lambda: self.now, sleep=self.sleep, verify_seconds=8,
            poll_seconds=2, persist_path=kwargs.pop("persist_path",
                Path(self.storage.name) / "station-troubleshoot.json"), **kwargs)

    async def test_repeated_clicks_join_one_job_and_one_recovery_request(self):
        runner = self.make()
        first = runner.start()
        second = runner.start()
        self.assertEqual(first["id"], second["id"])
        done = await runner.wait(first["id"])
        self.assertEqual(self.requests, [first["id"]])
        self.assertEqual(done["status"], "pending")
        self.assertFalse(done["running"])

    async def test_only_diagnosed_unique_actions_are_run_with_a_bound(self):
        runner = self.make(diagnose=lambda: {
            "actions": [{"step": "handover", "reason": "The air owner stopped polling."},
                        {"step": "handover"}, {"step": "voice-floor", "restart": True},
                        {"step": "stock"}, {"step": "unneeded-reset"}]}, max_actions=3)
        done = await runner.wait(runner.start()["id"])
        self.assertEqual(self.repairs, ["handover", "voice-floor", "stock"])
        self.assertTrue(done["changed"])
        self.assertEqual(set(done["attempted_actions"]), set(self.repairs))
        self.assertNotIn("deep", self.repairs)

    async def test_restart_setting_does_not_stop_owned_queue_repair(self):
        runner = self.make(diagnose=lambda: {
            "actions": [{"step": "voice-floor", "restart": True},
                        {"step": "handover", "restart": False}]})
        done = await runner.wait(runner.start(allow_restarts=False)["id"])
        self.assertEqual(self.repairs, ["handover"])
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(any("deferred" in row["text"] for row in done["transcript"]))

    async def test_success_requires_new_dj_playback_evidence(self):
        calls = []

        def observe():
            calls.append(self.now)
            return {"heard_at": self.now if len(calls) > 1 else 999,
                    "ready": 1, "pending": 0}

        runner = self.make(observe=observe)
        done = await runner.wait(runner.start()["id"])
        self.assertEqual(done["status"], "success")
        self.assertTrue(done["verified"])
        self.assertGreater(done["observation"]["heard_at"], done["started_at"])

    async def test_prepared_or_queued_script_does_not_claim_audible_success(self):
        runner = self.make(observe=lambda: {"heard_at": 1000, "ready": 5, "pending": 0})
        done = await runner.wait(runner.start()["id"])
        self.assertEqual(done["status"], "pending")
        self.assertFalse(done["verified"])
        self.assertIn("prepared", done["report"])
        self.assertIn("not been verified", done["report"])

    async def test_cooldown_is_reported_and_not_bypassed_by_polling(self):
        runner = self.make(observe=lambda: {
            "pending": 6, "ready": 0, "heard_at": 999,
            "blocked": ["final handoff rows must align with every planned turn"],
            "next_retry_at": 1200, "automatic_recovery": True,
            "recovery": {"attempts_per_pass": 3, "cooldown_until": 1200}})
        done = await runner.wait(runner.start()["id"])
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(done["status"], "pending")
        self.assertIn("cooldown", done["report"])
        self.assertIn("final handoff", done["report"])
        self.assertEqual(done["observation"]["next_retry_at"], 1200)

    async def test_operator_pause_is_preserved_and_reported(self):
        runner = self.make(diagnose=lambda: {"cause": "paused", "actions": []},
                           observe=lambda: {"ready": 0, "pending": 0,
                                            "blocked": ["The operator paused the station."]})
        done = await runner.wait(runner.start()["id"])
        self.assertEqual(self.repairs, [])
        self.assertEqual(done["status"], "blocked")
        self.assertIn("operator paused", done["report"])

    async def test_failed_repair_is_visible_while_recovery_still_runs(self):
        def repair(step):
            raise RuntimeError("voice director unavailable")

        runner = self.make(diagnose=lambda: {"actions": [{"step": "director", "restart": True}]},
                           repair=repair)
        done = await runner.wait(runner.start()["id"])
        self.assertEqual(len(self.requests), 1)
        self.assertFalse(done["verified"])
        self.assertTrue(any("voice director unavailable" in row["text"]
                            for row in done["transcript"]))

    async def test_error_in_evidence_does_not_make_a_green_report(self):
        def observe():
            raise RuntimeError("cannot read playback receipts")

        runner = self.make(observe=observe)
        done = await runner.wait(runner.start()["id"])
        self.assertEqual(done["status"], "blocked")
        self.assertFalse(done["verified"])
        self.assertIn("cannot read playback receipts", done["report"])

    async def test_restart_checkpoint_and_recovery_request_survive_interruption(self):
        reached_observe = asyncio.Event()

        async def observe():
            reached_observe.set()
            await asyncio.Event().wait()

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "station-troubleshoot.json"
            diagnose = lambda: {"actions": [{"step": "director", "restart": True}]}
            runner = self.make(diagnose=diagnose, observe=observe, persist_path=path)
            first = runner.start()
            await reached_observe.wait()
            await runner.flush()
            saved = json.loads(path.read_text())["jobs"][0]
            self.assertTrue(saved["recovery_requested"])
            self.assertEqual(saved["attempted_actions"], ["director"])
            runner._tasks[first["id"]].cancel()
            with self.assertRaises(asyncio.CancelledError):
                await runner.wait(first["id"])
            await runner.flush()
            restored = self.make(diagnose=diagnose, persist_path=path,
                                 observe=lambda: {"heard_at": 1100, "ready": 1})
            self.assertEqual(len(restored.resume_pending()), 1)
            done = await restored.wait(first["id"])
            self.assertEqual(self.repairs, ["director"])
            self.assertEqual(self.requests, [first["id"]])
            self.assertEqual(done["status"], "success")
            self.assertTrue(any(row["phase"] == "resuming" for row in done["transcript"]))

    async def test_status_snapshots_cannot_mutate_owned_job_state(self):
        runner = self.make()
        first = runner.start()
        first["transcript"].append({"text": "pretend success"})
        first["verified"] = True
        done = await runner.wait(first["id"])
        self.assertFalse(done["verified"])
        self.assertFalse(any(row["text"] == "pretend success" for row in done["transcript"]))

    async def test_invalid_callback_report_is_visible(self):
        runner = self.make(diagnose=lambda: True)
        done = await runner.wait(runner.start()["id"])
        self.assertEqual(done["status"], "blocked")
        self.assertIn("must return a report", done["report"])
        self.assertEqual(self.requests, [])

    async def test_slow_data_share_does_not_block_start_or_the_event_loop(self):
        runner = self.make()
        writing = threading.Event()
        release = threading.Event()
        thread_ids = []
        write_snapshot = runner._write_snapshot

        def slow_write(data):
            thread_ids.append(threading.get_ident())
            writing.set()
            release.wait(3)
            write_snapshot(data)

        runner._write_snapshot = slow_write
        began = time.perf_counter()
        job = runner.start()
        elapsed = time.perf_counter() - began
        try:
            self.assertLess(elapsed, 0.25)
            self.assertTrue(await asyncio.to_thread(writing.wait, 1))
            await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.25)
            self.assertTrue(thread_ids)
            self.assertTrue(all(tid != threading.get_ident() for tid in thread_ids))
        finally:
            release.set()
            await runner.wait(job["id"])

    async def test_restart_callback_runs_only_after_its_checkpoint_is_on_disk(self):
        path = Path(self.storage.name) / "checkpoint.json"
        checkpoint_seen = []

        def repair(step):
            saved = json.loads(path.read_text())["jobs"][0]
            checkpoint_seen.append(saved)
            self.assertEqual(saved["restart_checkpoint"], step)
            self.assertIn(step, saved["attempted_actions"])
            return {"ok": True, "changed": True}

        runner = self.make(diagnose=lambda: {"actions": [{"step": "director", "restart": True}]},
                           repair=repair, persist_path=path)
        await runner.wait(runner.start()["id"])
        self.assertEqual(len(checkpoint_seen), 1)

    async def test_checkpoint_write_failure_holds_the_restart_and_reports_blocked(self):
        runner = self.make(diagnose=lambda: {"actions": [{"step": "director", "restart": True}]})

        def fail_write(data):
            raise OSError("data share unavailable")

        runner._write_snapshot = fail_write
        done = await runner.wait(runner.start()["id"])
        self.assertEqual(self.repairs, [])
        self.assertEqual(done["status"], "blocked")
        self.assertFalse(done["verified"])
        self.assertIn("checkpoint could not be saved", done["report"])
        self.assertIn("data share unavailable", done["report"])

    async def test_checkpoint_timeout_holds_the_restart_without_stalling_the_loop(self):
        release = threading.Event()
        runner = self.make(diagnose=lambda: {"actions": [{"step": "director", "restart": True}]},
                           persistence_timeout=0.03)
        write_snapshot = runner._write_snapshot

        def slow_write(data):
            release.wait(3)
            write_snapshot(data)

        runner._write_snapshot = slow_write
        job = runner.start()
        try:
            await asyncio.wait_for(runner._tasks[job["id"]], 0.5)
            done = runner.status(job["id"])
            self.assertEqual(self.repairs, [])
            self.assertEqual(done["status"], "blocked")
            self.assertIn("checkpoint timed out", done["report"])
        finally:
            release.set()
            runner.persistence_timeout = 3.0
            await runner.flush()

    async def test_restart_requires_persistent_job_storage(self):
        runner = self.make(diagnose=lambda: {"actions": [{"step": "director", "restart": True}]},
                           persist_path=None)
        done = await runner.wait(runner.start()["id"])
        self.assertEqual(self.repairs, [])
        self.assertEqual(done["status"], "blocked")
        self.assertIn("persistent job storage", done["report"])


if __name__ == "__main__":
    unittest.main()
