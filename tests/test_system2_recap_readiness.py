"""Exact-hour recap and conservative on-air preparation contracts."""
import asyncio
import copy
import json
import tempfile
import unittest
from unittest import mock

import system2_runtime as adapter
from test_system2_runtime import Host


class RecapReadinessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 10000.0
        timer = mock.patch.object(adapter.time, "time", side_effect=lambda: self.now)
        timer.start()
        self.addCleanup(timer.stop)
        self.host = Host(self.temp.name, lambda: self.now)
        self.host.ALT_PREP_KINDS += ("recap", "ad")
        self.host.templates = [{"id": "recap", "kind": "recap", "minutes": 2}]
        self.host.alt_sid = lambda kind, row: row.get("id") or row.get("entry", {}).get("id")
        self.host._SPEAKING = [False]
        self.host._floor_busy = mock.Mock(return_value=False)
        self.runtime = adapter.System2Runtime(self.host)
        self.runtime.store.now = lambda: self.now
        self.runtime.config.update(engine="system2", horizon_hours=1)

    async def test_old_recap_is_excluded_from_plan_dispatch_and_fallback_blocking(self):
        old = self.host.add("old-recap", kind="recap", system2_slot="hour-6400000:recap")
        status = await self.runtime.refresh()
        slot = status["hours"][0]["slots"][0]
        candidate = self.runtime.candidate("recap", old)
        self.assertEqual(candidate["slot_id"], old["system2_slot"])
        self.assertEqual(slot["allocations"], [])
        self.assertTrue(slot["require_slot_binding"])

        # A persisted allocation from before the new binding rule must not air.
        live_slot = self.runtime._plans[0]["slots"][0]
        forged = copy.deepcopy(candidate)
        forged["slot_id"] = live_slot["id"]
        self.assertFalse(self.runtime.store._slot_matches(forged, live_slot))
        live_slot["allocations"] = [{"candidate": forged}]
        self.runtime.refresh = mock.AsyncMock(return_value=None)
        self.assertFalse(await self.runtime.dispatch())
        self.host._banter_air.assert_not_awaited()
        self.assertTrue(self.runtime.fallback_due())
        self.assertTrue(any("another observed hour" in call.args[1]
                            for call in self.host.pipeline_log.call_args_list))

    async def test_measured_lead_prepares_fresh_recap_and_persists_verified_duration(self):
        self.host.templates = [
            {"id": "record", "kind": "record", "minutes": 8},
            {"id": "recap", "kind": "recap", "minutes": 2},
        ]
        self.host.task_stat = mock.Mock(return_value={"measured": True, "p90": 400})
        self.assertGreater(self.runtime.recap_lead_seconds(), 480)
        saved = self.host.DATA_DIR / "recap-shelf.json"
        self.host._pantry_save.side_effect = lambda force: saved.write_text(
            json.dumps(self.host.rows.get("recap") or []), encoding="utf-8")

        async def write_recap(*args, **kwargs):
            entry = self.host.add("fresh-recap", kind="recap")
            self.host.rows["recap"].remove(entry)
            kwargs["bank_to"].append(entry)

        self.host.dj_banter.side_effect = write_recap
        with mock.patch.object(self.runtime.store, "complete_job",
                               wraps=self.runtime.store.complete_job) as complete:
            await self.runtime.prepare()
        self.host.dj_banter.assert_awaited_once()
        self.assertEqual(self.runtime._work["kind"], "recap")
        self.assertEqual(self.host.rows["recap"][0]["seconds"], 7)
        self.assertEqual(self.host.rows["recap"][0]["entry"]["seconds"], 7)
        self.assertEqual(json.loads(saved.read_text(encoding="utf-8"))[0]["seconds"], 7)
        self.assertTrue(complete.call_args.kwargs["candidates"][0]["ready"])
        self.assertEqual(complete.call_args.kwargs["candidates"][0]["seconds"], 7)

        # A fresh runtime must recover the same verified media and exact pin.
        reloaded = copy.copy(self.host)
        reloaded.rows = {"banter": [], "recap": json.loads(saved.read_text(encoding="utf-8"))}
        reloaded._LARDER = reloaded.rows["banter"]
        runtime = adapter.System2Runtime(reloaded)
        runtime.store.now = lambda: self.now
        runtime.config.update(engine="system2", horizon_hours=1)
        state = await runtime.refresh()
        slot = state["hours"][0]["slots"][1]
        self.assertEqual(slot["allocations"][0]["candidate"]["seconds"], 7)
        self.assertEqual(slot["allocations"][0]["candidate"]["slot_id"], slot["id"])

    async def test_failed_checkpoint_never_completes_recap_job(self):
        async def write_recap(*args, **kwargs):
            entry = self.host.add("unpersisted-recap", kind="recap")
            self.host.rows["recap"].remove(entry)
            kwargs["bank_to"].append(entry)

        self.host.dj_banter.side_effect = write_recap
        self.host._pantry_save.side_effect = OSError("disk full")
        await self.runtime.prepare()
        job = next(j for j in self.runtime.store.jobs() if j["kind"] == "recap")
        self.assertNotEqual(job["state"], "completed")
        self.assertFalse(job.get("ready_output"))

    async def test_on_air_claims_near_first_then_only_far_ad_or_gallery(self):
        self.runtime.config["horizon_hours"] = 6
        self.host.ALT_PREP_KINDS += ("gallery",)

        def far_slots(settings, key):
            if float(key) < self.now + 7200:
                return "configured", [{"id": "record", "kind": "record", "minutes": 5}], False
            return "configured", [
                {"id": "ad", "kind": "ad", "minutes": 2},
                {"id": "news", "kind": "news", "minutes": 2},
                {"id": "gallery", "kind": "gallery", "minutes": 4},
            ], False

        self.host.schedule_hour_slots = far_slots
        with mock.patch.object(self.runtime.store, "claim_job",
                               wraps=self.runtime.store.claim_job) as claim:
            await self.runtime.prepare()
        self.assertEqual(claim.call_count, 2)
        self.assertEqual(claim.call_args_list[0].kwargs["lookahead_seconds"], 3600)
        self.assertEqual(claim.call_args_list[1].kwargs["lookahead_seconds"], 21600)
        self.assertEqual(set(claim.call_args_list[1].kwargs["kinds"]), {"ad", "gallery"})
        self.assertIn(self.runtime._work["kind"], ("ad", "gallery"))
        self.assertTrue(all(j["attempts"] == 0 for j in self.runtime.store.jobs()
                            if j["kind"] == "news"))

    async def test_near_news_keeps_first_refusal_and_far_pass_is_not_used(self):
        self.runtime.config["horizon_hours"] = 6
        self.host.templates = [{"id": "news", "kind": "news", "minutes": 2}]
        with mock.patch.object(self.runtime.store, "claim_job",
                               wraps=self.runtime.store.claim_job) as claim:
            await self.runtime.prepare()
        self.assertEqual(claim.call_count, 1)
        self.assertEqual(claim.call_args.kwargs["lookahead_seconds"], 3600)
        self.assertEqual(self.runtime._work["kind"], "news")


if __name__ == "__main__":
    unittest.main()
