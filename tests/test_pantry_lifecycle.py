import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from pantry_lifecycle import PantryLifecycle, reusable_reaction

class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=200000.0
        self.host={"_SHELF":{},"_LARDER":[],"_PANTRY":{},"_PAGE_AIR_UNTIL":[0],
                   "alt_sid":lambda k,r:r["id"],"dialogue_row_ready":lambda k,r:r.get("ready",False),
                   "cupboard_row_seconds":lambda k,r:r.get("seconds",30),
                   "_ready_slot_window":lambda k:{"kind":k,"deadline":self.now+600,"occurrence":"slot-1"},
                   "pantry_spoken_for":lambda:set(),"_row_clip_keys":lambda r:set(r.get("keys",[])),
                   "system3_pick":lambda *a:0,"gold_source":lambda r:r.get("source"),
                   "cupboard_why_row":lambda k,r:{"reasons":[{"code":"unbound"}]},
                   "_gold_rows":lambda:[],"pantry_window":lambda:False}
        self.manager=PantryLifecycle(self.host,Path(self.tmp.name)/"policy.json",lambda:self.now)
        self.manager.policy["mode"]="air"
    def row(self,ident="one",kind="manager",age=3600,ready=True,**fields):
        row=dict(id=ident,at=self.now-age,ready=ready,seconds=30,**fields)
        self.host["_SHELF"].setdefault(kind,[]).append(row);return row
    async def test_expiry_overrules_unheard_and_rhyme(self):
        row=self.row(age=86401,ready=False,entry={"script":"A: old rhymed work"})
        await self.manager.tick()
        self.assertEqual(self.host["_SHELF"]["manager"],[])
        self.assertEqual(row["pantry_lifecycle"]["reason"],"lifecycle freshness deadline")
    async def test_trace_does_not_retire_or_attach_metadata(self):
        row=self.row(age=90000);before=dict(row);self.manager.policy["mode"]="trace"
        await self.manager.tick()
        self.assertEqual(row,before);self.assertEqual(self.manager.snapshot()["states"]["expired"],1)
    def test_creation_clock_never_resets_on_rewrite(self):
        row=self.row();self.manager.meta("manager",row);deadline=self.manager.deadline("manager",row)
        row["at"]=self.now;self.assertEqual(self.manager.deadline("manager",row),deadline)
    def test_news_has_shorter_freshness(self):
        row=self.row(kind="news",age=3601)
        self.assertTrue(self.manager.unavailable("news",row))
    def test_closed_or_incompatible_segment_never_selected(self):
        self.row(kind="recap");self.host["_ready_slot_window"]=lambda k:{"kind":"news","deadline":self.now+600}
        self.assertIsNone(self.manager.pick()[1])
    def test_runway_and_duration_must_fit(self):
        self.row();self.host["_PAGE_AIR_UNTIL"][0]=self.now+590
        self.assertIsNone(self.manager.pick()[1])
    def test_final_hour_prioritizes_earliest_deadline(self):
        self.row("young");old=self.row("old",age=23.5*3600)
        self.assertIs(self.manager.pick()[1],old)
        self.assertEqual(self.manager.recent[-1]["action"],"deadline_priority")
    def test_roulette_records_candidates_and_misses(self):
        selected=self.row("first");other=self.row("second")
        self.assertIs(self.manager.pick()[1],selected)
        self.assertEqual(self.manager.recent[-1]["candidates"],["first","second"])
        self.assertEqual(other["pantry_lifecycle"]["misses"],1)
    def test_queue_is_not_delivery_and_duplicate_selection_is_blocked(self):
        row=self.row();self.manager.queued("manager",row)
        self.assertNotIn("aired",row);self.assertEqual(row["pantry_lifecycle"]["state"],"queued")
        self.assertIsNone(self.manager.pick()[1])
    def test_native_complete_receipt_retires_single_use(self):
        row=self.row();self.manager.queued("manager",row)
        self.manager.confirmed({"_pantry_lifecycle_id":"one"})
        self.assertEqual(row["heard"],1);self.assertEqual(self.manager.counts["delivered"],1)
        self.assertEqual(self.host["_SHELF"]["manager"],[])
        self.manager.confirmed({"_pantry_lifecycle_id":"one"})
        self.assertEqual(self.manager.counts["delivered"],1)
    async def test_timed_out_delivery_has_bounded_retries(self):
        row=self.row();self.manager.queued("manager",row)
        self.now+=100;await self.manager.tick()
        self.assertEqual(row["pantry_lifecycle"]["failures"],1)
        self.manager.failed("manager",row,"error");self.manager.failed("manager",row,"error")
        self.now+=31;await self.manager.tick()
        self.assertEqual(self.host["_SHELF"]["manager"],[])
    async def test_shared_audio_survives_retirement(self):
        row=self.row(age=90000,keys=["shared","loose"])
        self.host["_PANTRY"]={"shared":{},"loose":{}}
        self.host["pantry_spoken_for"]=lambda:{"shared"}
        await self.manager.tick();self.assertEqual(set(self.host["_PANTRY"]),{"shared"})
    async def test_inflight_worker_is_not_deleted_underneath(self):
        row=self.row(age=90000,entry={"preparing":True})
        await self.manager.tick();self.assertIn(row,self.host["_SHELF"]["manager"])
    async def test_repair_failure_consumes_budget_and_releases_active(self):
        row=self.row(ready=False)
        async def repair(k,r):raise RuntimeError("bad writer")
        self.host["pantry_lifecycle_repair"]=repair
        await self.manager.repair("manager",row)
        self.assertFalse(self.manager.active);self.assertEqual(row["pantry_lifecycle"]["repair_attempts"],1)
    def test_invalid_binding_is_rejected_before_recording(self):
        entry={};self.host["s3_binding_withheld"]=lambda e:"missing roulette turns"
        self.assertFalse(self.manager.admit_production(entry))
    def test_backpressure_preserves_news_and_current_debt(self):
        for i in range(8):self.row(str(i),ready=False)
        self.assertTrue(self.manager.backpressure("manager"));self.assertFalse(self.manager.backpressure("news"))
    async def test_evergreen_has_count_and_duration_bounds(self):
        self.manager.policy["evergreen_cap"]=1
        first=self.row("first");second=self.row("second")
        for r in (first,second):self.manager.meta("manager",r)["repertoire"]="evergreen"
        await self.manager.tick();self.assertEqual(len(self.host["_SHELF"]["manager"]),1)
    def test_evergreen_receipt_keeps_capped_repertoire_and_cooldown(self):
        row=self.row();self.manager.meta("manager",row)["repertoire"]="evergreen"
        self.manager.confirmed({"_pantry_lifecycle_id":"one"})
        self.assertIn(row,self.host["_SHELF"]["manager"]);self.assertIsNone(self.manager.pick()[1])
    def test_reactions_need_source_and_standalone_use_and_caps(self):
        self.manager.policy["reaction_cap"]=1
        rows=[dict(text="I hear you, keep going.",seconds=3,path="a.wav",source={"turn_id":"a"},at=self.now),
              dict(text="Fair enough, tell me more.",seconds=3,path="b.wav",source={"turn_id":"b"},at=self.now),
              dict(text="Today's painting is worth 500 dollars.",seconds=3,path="c.wav",source={"turn_id":"c"})]
        self.manager.trim_reactions(rows);self.assertEqual(len(rows),1)
        self.assertTrue(reusable_reaction(rows[0]["text"]))
    def test_reaction_probation_and_unused_limits(self):
        rows=[dict(text="I hear you, keep going.",seconds=3,path="a.wav",source={"turn_id":"a"},at=self.now-8*86400,fired=0)]
        self.manager.trim_reactions(rows);self.assertEqual(rows,[])
    def test_policy_and_counters_survive_restart(self):
        self.manager.note("manager",self.row(),"reserved","test");self.manager.save()
        restored=PantryLifecycle(self.host,self.manager.path,lambda:self.now)
        self.assertTrue(restored.enabled);self.assertEqual(restored.counts["reserved"],1)
    async def test_maintenance_clock_retires_even_when_preparation_window_closed(self):
        from pantry_lifecycle_runtime import lifecycle_clock
        self.row(age=90000, ready=False)
        with mock.patch("pantry_lifecycle_runtime.sleep", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await lifecycle_clock(self.manager)
        self.assertEqual(self.host["_SHELF"]["manager"], [])
        self.assertEqual(self.manager.last_error, "")

    async def test_maintenance_clock_reports_failures_and_keeps_running(self):
        from pantry_lifecycle_runtime import lifecycle_clock
        calls = 0
        async def tick():
            nonlocal calls
            calls += 1
            if calls == 1: raise RuntimeError("test failure")
            self.manager.last_tick += 30
        self.manager.tick = mock.AsyncMock(side_effect=tick)
        with mock.patch("pantry_lifecycle_runtime.sleep", side_effect=[None, asyncio.CancelledError]):
            with self.assertRaises(asyncio.CancelledError):
                await lifecycle_clock(self.manager)
        self.assertEqual(self.manager.tick.await_count, 2)
        self.assertEqual(self.manager.last_error, "")

    async def test_lazy_runtime_receives_retirement_observation_without_stopping_cleanup(self):
        runtime = mock.Mock()
        self.host["_SYSTEM3_RUNTIME"] = lambda: runtime
        for n in range(3):
            self.row(ident=str(n), age=90000, entry={"system3":{"conversation_id":"original"}})
        await self.manager.tick()
        self.assertEqual(self.host["_SHELF"]["manager"], [])
        self.assertEqual(runtime.observe_later.call_count, 3)
        self.assertEqual(self.manager.counts["retired"], 3)

    async def test_ordinary_previously_heard_stock_is_consumed_but_publication_is_not_delivery(self):
        heard = self.row(ident="heard", heard=1)
        published = self.row(ident="published", aired=1)
        self.assertTrue(self.manager.unavailable("manager", heard))
        self.assertFalse(self.manager.unavailable("manager", published))
        await self.manager.tick()
        self.assertEqual(self.host["_SHELF"]["manager"], [published])

    def test_regenerating_unused_reaction_does_not_reset_probation(self):
        rows=[dict(text="I hear you, keep going.",seconds=3,path="a.wav",source={"turn_id":"a"},at=self.now,created_at=self.now-8*86400,fired=0)]
        self.manager.trim_reactions(rows)
        self.assertEqual(rows, [])

    def test_census_counts_work_not_cached_audio(self):
        self.host["_PANTRY"]={str(i):{} for i in range(3000)};self.row(ready=False)
        self.assertEqual(self.manager.snapshot()["states"]["blocked"],1)

if __name__ == "__main__":unittest.main()
