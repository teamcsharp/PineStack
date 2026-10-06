import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from fastapi import FastAPI, HTTPException
import app
from pantry_lifecycle import PantryLifecycle
from pantry_lifecycle_runtime import install

class StationIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.manager=PantryLifecycle(app.__dict__,Path(self.tmp.name)/"lifecycle.json")
        self.manager.policy["mode"]="air"
        for name,value in [("_PANTRY_LIFECYCLE",self.manager),("_SHELF",{}),("_LARDER",[]),("_PANTRY",{}),("_READY_SHELF_BUSY",set())]:
            patch=mock.patch.object(app,name,value);patch.start();self.addCleanup(patch.stop)
        for name in ["_pantry_save","_larder_save","pipeline_log","pantry_reaction_harvest"]:
            patch=mock.patch.object(app,name);patch.start();self.addCleanup(patch.stop)
    def row(self):
        row={"at":time.time(),"id":"one","entry":{"script":"A: I hear you.\nB: Tell me more.\nA: Go on.","lines":3,"prep_kind":"ad"}}
        app._SHELF["ad"]=[row];return row
    def test_native_air_metadata_carries_stable_lifecycle_identity(self):
        row=self.row();first=app._ready_air_entry("ad",row);second=app._ready_air_entry("ad",row)
        self.assertEqual(first["_pantry_lifecycle_id"],second["_pantry_lifecycle_id"])
        self.assertEqual(first["_pantry_lifecycle_delivery"],1)
    def test_receipt_hook_settles_and_deduplicates_exact_item(self):
        row=self.row();entry=app._ready_air_entry("ad",row)
        self.manager.queued("ad",row);app._ready_round_ack(entry);app._ready_round_ack(entry)
        self.assertEqual(self.manager.counts["delivered"],1);self.assertEqual(app._SHELF["ad"],[])
    async def test_unbound_production_never_reaches_recording_engine(self):
        entry={"script":"A: Fragment","prep_kind":"manager"}
        with mock.patch.object(app,"s3_binding_withheld",return_value="missing planned turns"),mock.patch.object(app,"ensure_entry_tinted",new=mock.AsyncMock()) as tint:
            self.assertFalse(await app.larder_prepare(entry));tint.assert_not_called()
    def test_readiness_refuses_expired_stock_even_when_legacy_freshness_is_off(self):
        row=self.row();row["at"]=time.time()-90000
        with mock.patch.object(app,"content_gate_enabled",return_value=False):
            self.assertFalse(app.dialogue_row_ready("ad",row))
            self.assertGreater(app.stock_expires_at("ad",row),0)
    def test_generic_repeat_requires_evergreen_nomination(self):
        row=self.row();row.update(aired_at=time.time(),aired=1)
        self.assertFalse(app.shelf_is_repeat("ad",row))
    def test_busy_receipt_is_completed_after_worker_releases_source(self):
        row=self.row();entry=app._ready_air_entry("ad",row);app._READY_SHELF_BUSY.add(id(row))
        self.manager.confirmed(entry);self.assertEqual(row["pantry_lifecycle"]["state"],"delivered")
        app._READY_SHELF_BUSY.clear();self.assertTrue(self.manager.retire("ad",row,"delivered"))

    def test_coordinator_reports_blocked_work_even_with_an_active_render(self):
        self.row()
        with mock.patch.object(app,"writing_room_state",return_value={}),mock.patch.object(app,"recording_booths",return_value={"preparing":1}):
            state=app.orchestrator_pipeline_state()
        self.assertIn("blocked",state["bottleneck"])
        self.assertIn("original System Three plan",state["next_step"])

    def test_single_contract_requires_exact_original_plan_and_words(self):
        from types import SimpleNamespace
        row=self.row();entry=app._ready_air_entry("ad",row)
        entry.update(script="A: I hear you, keep going.",lines=1,system3={"mode":"active","conversation_id":"native","planned_turns":1,"turns":{"0":"native:t00"}},turn_dice={"0":{"s3":{"turn_id":"native:t00"}}})
        conv={"mode":"active","turns":[{"speaker":"A","turn_id":"native:t00","text":"I hear you, keep going."}],"actual":[{"speaker":"A","text":"I hear you, keep going."}]}
        runtime=SimpleNamespace(recent={"native":conv})
        # Install the real contract adapter in a separate namespace.
        api=FastAPI();host=dict(app.__dict__);host["data_path"]=lambda n:Path(self.tmp.name)/("single-"+n);host["_SYSTEM3_RUNTIME"]=lambda:runtime
        install(api,host)
        contract=host["pantry_single_contract"]
        self.assertTrue(contract(entry))
        changed=dict(entry,script="A: A different recorded sentence.")
        self.assertFalse(contract(changed))
        conv["turns"].append({"speaker":"B","turn_id":"native:t01"})
        self.assertFalse(contract(entry))

class LifecycleApi(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.api=FastAPI();self.host={"data_path":lambda n:Path(self.tmp.name)/n,"require_auth":lambda a:None,"require_read_auth":lambda a:None,"_SHELF":{},"_LARDER":[]}
        self.manager=install(self.api,self.host)
    async def invoke(self,path,body):
        request=mock.Mock();request.json=mock.AsyncMock(return_value=body)
        endpoint=next(r.endpoint for r in self.api.routes if getattr(r,"path",None)==path)
        return await endpoint(request,authorization=None)
    async def test_policy_rejects_unknown_nan_and_fractional_counts(self):
        for body in [{"ordinary_hours":float("nan")},{"reaction_cap":1.5},{"unknown":2},{"mode":"guess"}]:
            with self.subTest(body=body),self.assertRaises(HTTPException):await self.invoke("/api/pantry/lifecycle/policy",body)
        self.assertEqual(self.manager.policy["mode"],"trace")
    async def test_policy_activation_is_persisted(self):
        await self.invoke("/api/pantry/lifecycle/policy",{"mode":"air"})
        self.assertTrue(PantryLifecycle(self.host,self.manager.path).enabled)
    async def test_time_sensitive_segment_cannot_be_nominated(self):
        with self.assertRaises(HTTPException):await self.invoke("/api/pantry/lifecycle/nominate",{"id":"news","kind":"evergreen"})

if __name__=="__main__":unittest.main()
