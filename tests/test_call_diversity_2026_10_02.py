"""Equal caller intents, source availability, recovery/replay and operator approval."""
import ast
import asyncio
import copy
import json
import random
import unittest
from collections import Counter
from pathlib import Path
import call_diversity as diversity
import system3
from test_system3_callend import call_inputs, settings
from test_orchestrator_s3_2026_09_29 import Sandbox

class Diversity(unittest.TestCase):
    def plan(self, seed="diverse", config=None):
        cfg = config or system3.default_config()
        conv = system3.new_conversation(call_inputs(), cfg, settings(seed), conversation_id="diverse")
        system3.plan_call(conv, cfg)
        return conv, cfg

    def test_equal_draws_are_replayable_and_do_not_change_emotions(self):
        conv,cfg = self.plan()
        self.assertTrue(system3.replay(conv,cfg)["ok"])
        events = [e for e in conv["decision_events"] if e["family"] in diversity.INTENT_FAMILIES]
        self.assertEqual(len(events),4)
        for ev in events:
            candidates = ev["stages"][0]["candidates"]
            self.assertEqual({r["weight"] for r in candidates},{1.0})
        off=copy.deepcopy(cfg)
        for t in off["tables"]:
            if t["family"] in diversity.FAMILIES:t["enabled"]=False
        plain,_=self.plan(config=off)
        a=[(e["family"],e.get("selected"),e["rng"]) for e in conv["decision_events"] if e["family"]=="ES"]
        b=[(e["family"],e.get("selected"),e["rng"]) for e in plain["decision_events"] if e["family"]=="ES"]
        self.assertEqual(a,b)
        self.assertNotIn("The request line is ringing",system3.render_call_sheet(conv))
        self.assertIn("oppose",system3.render_call_sheet(conv))

    def test_recovery_excludes_failed_intent_and_replays(self):
        conv,cfg=self.plan()
        turn=next(t for t in conv["turns"] if t["leg"]=="answer")
        old=turn["diversity"][0]["key"]
        self.assertTrue(diversity.recover(conv,cfg,turn["index"],{"why":"already aired"}))
        self.assertNotEqual(old,turn["diversity"][0]["key"])
        self.assertFalse(diversity.recover(conv,cfg,turn["index"],{"why":"again"}))
        self.assertTrue(system3.replay(conv,cfg)["ok"])
        self.assertEqual(conv["inputs"]["call"]["first"],"Dana")

    def test_source_uniformity_and_visible_exclusions(self):
        cfg=system3.default_config(); counts=Counter()
        for i in range(400):
            conv=system3.new_conversation(call_inputs(),cfg,settings(str(i)))
            sel=diversity.draw(conv,cfg,"CALLSOURCE",unavailable={"internet":"search unavailable"})
            counts[sel["id"]]+=1
            excluded=conv["decision_events"][-1]["stages"][0]["excluded"]
            self.assertTrue(any("search unavailable"==r["why"] for r in excluded))
        self.assertEqual(set(counts),{"speakerbox","topics","station"})
        self.assertTrue(all(95<n<175 for n in counts.values()),counts)

    def test_options_are_bounded_duplicate_checked_and_equal(self):
        t=diversity.default_tables()[0]
        t["weight"]=9;t["categories"][0]["weight"]=8
        t["categories"][0]["items"][0]["weight"]=7
        normalized=system3.validate_table(t)
        self.assertEqual(normalized["categories"][0]["items"][0]["weight"],1)
        t["categories"][0]["items"].append(copy.deepcopy(t["categories"][0]["items"][0]))
        t["categories"][0]["items"][-1]["id"]="duplicate"
        with self.assertRaises(ValueError):system3.validate_table(t)

class Approval(Sandbox):
    def test_generated_option_waits_for_operator_then_can_be_undone(self):
        rt=self.desk.rt()
        before=copy.deepcopy(rt.config)
        p=self.desk.propose_option("CALLANGLE1","Interpret the caller's problem as a misplaced celebration.")
        self.assertEqual(before,rt.config)
        self.assertFalse(self.desk.confirm(p["id"],"station")["ok"])
        self.assertTrue(self.desk.confirm(p["id"],"operator")["ok"])
        self.assertTrue(self.desk.undo(p["id"])["ok"])

    def test_new_wheel_waits_for_operator_and_undo_removes_it(self):
        t=diversity.default_tables()[0];t["id"]="CALLOPEN2"
        p=self.desk.propose_wheel(t)
        self.assertFalse(self.desk.confirm(p["id"],"station")["ok"])
        self.assertTrue(self.desk.confirm(p["id"])["ok"])
        self.assertTrue(self.desk.undo(p["id"])["ok"])
        self.assertFalse(any(t["id"]=="CALLOPEN2" for t in self.desk.rt().config["tables"]))

class SourcePipeline(unittest.IsolatedAsyncioTestCase):
    def namespace(self, source):
        path=Path(__file__).resolve().parents[1]/"app.py"
        node=getattr(type(self),"source_node",None)
        if node is None:
            code=path.read_text(encoding="utf-8-sig")
            code=code[code.index("async def system3_caller_premise("):code.index("async def caller_topic(")]
            tree=ast.parse(code)
            node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="system3_caller_premise")
            type(self).source_node=node
        async def quote(**kw):return {"file":"real.md","text":"A raccoon took a tram."}
        async def search(query):return [{"title":"The lost tram","url":"https://example.org/tram","content":"A real result."}]
        ns={"Any":object,"time":__import__("time"),"system3_call_source":lambda exclusions: {"id":source},
            "theme_owns_air":lambda:{},"read_bombshells":lambda:[{"id":"t","text":"misplaced trams"}],
            "SEARXNG_URL":"local search","speakbox_quote":quote,"search_searxng":search,
            "s3_choice":lambda key,options,*args,**kwargs:options[0],"banter_pool":lambda n:["station music"],
            "booth_hot":lambda:82,"banter_material":lambda:"station music"}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),"exec"),ns)
        return ns

    async def test_each_source_reaches_the_premise_and_internet_receipt(self):
        for source in ("speakerbox","topics","internet","station"):
            ns=self.namespace(source)
            topic,seed=await ns["system3_caller_premise"]()
            self.assertEqual(seed["system3_source"]["source"],source)
            self.assertIn(seed["system3_source"]["material"],topic)
            if source=="internet":
                self.assertEqual(seed["internet_source"]["url"],"https://example.org/tram")
                self.assertEqual(seed["internet_source"]["query"],"misplaced trams")

    async def test_explicit_theme_and_disabled_system_preserved(self):
        ns=self.namespace("topics");ns["theme_owns_air"]=lambda:{"text":"operator subject"}
        self.assertIsNone(await ns["system3_caller_premise"]())
        ns["theme_owns_air"]=lambda:{};ns["system3_call_source"]=lambda exclusions:None
        self.assertIsNone(await ns["system3_caller_premise"]())

    async def test_failed_search_is_excluded_before_reroll(self):
        ns=self.namespace("internet");seen=[]
        def draw(exclusions):
            seen.append(dict(exclusions));return {"id":"topics" if "internet" in exclusions else "internet"}
        async def empty(query):return []
        ns.update(system3_call_source=draw,search_searxng=empty)
        _,seed=await ns["system3_caller_premise"]()
        self.assertEqual(seed["system3_source"]["source"],"topics")
        self.assertIn("internet",seen[-1])
        self.assertEqual(len(seed["system3_source"]["failures"]),1)

class RuntimeRecovery(unittest.TestCase):
    def test_whole_retry_keeps_identity_premise_and_replays(self):
        import system3_runtime
        cfg=system3.default_config()
        original=system3.new_conversation(call_inputs(),cfg,settings("retry"),conversation_id="same-call")
        system3.plan_call(original,cfg)
        class Runtime:
            async def _callend_after_plan(self,handle,ctx):pass
            def remember(self,conv):pass
            def rewrite_material(self,handle):pass
        rt=Runtime()
        handle=system3_runtime.Handle(rt,original,cfg,True)
        old=copy.deepcopy(original)
        report={"novelty":{"ok":False,"fingerprint":"real-dialogue","similarity":0.52}}
        self.assertTrue(asyncio.run(system3_runtime.System3Runtime.diversity_retry(rt,handle,{},report)))
        self.assertEqual(handle.conv["identity"]["conversation_id"],"same-call")
        self.assertEqual(handle.conv["identity"]["trace_id"],old["identity"]["trace_id"])
        self.assertEqual(handle.conv["inputs"]["call"],old["inputs"]["call"])
        self.assertEqual(handle.conv["identity"]["revision"],2)
        self.assertTrue(system3.replay(handle.conv,cfg)["ok"])
        for family in diversity.INTENT_FAMILIES:
            self.assertNotEqual(old["call_diversity"]["selections"][family]["key"],handle.conv["call_diversity"]["selections"][family]["key"])
        self.assertFalse(asyncio.run(system3_runtime.System3Runtime.diversity_retry(rt,handle,{},report)))

    def test_aired_repeat_recovers_before_recording(self):
        cfg=system3.default_config()
        conv=system3.new_conversation(call_inputs(),cfg,settings("repeat"))
        system3.plan_call(conv,cfg)
        text="The request line is ringing, you are live, go ahead."
        run=system3.gate_open(conv,[("A",text)],None,rewrites=2,visits=3)
        run["repeat_check"]=lambda candidate: candidate==text
        run["diversity_config"]=cfg
        ask=system3.gate_next(conv,run)
        self.assertIsNotNone(ask)
        self.assertEqual(conv["call_diversity"]["repairs"][0]["turn_index"],0)
        self.assertIn("fresh words",ask["prompt"])
        self.assertTrue(system3.replay(conv,cfg)["ok"])

class RewriteWheel(unittest.TestCase):
    def test_each_request_is_editable_eligible_and_replayable(self):
        for iid in ("dramatic","rap_battle","innuendo","speakerbox_plot","feature_pitch","station_threat"):
            cfg=system3.default_config()
            rw=next(t for t in cfg["tables"] if t["id"]=="RW1")
            for item in rw["categories"][0]["items"]:item["weight"]=int(item["id"]==iid)
            inputs=call_inputs();inputs["call"]["station"]="Pine Box FM"
            inputs["rewrite_features"]=[{"id":"rolodex","label":"Rolodex","text":"Rolodex shows recorded RNG decisions."},
                                        {"id":"speakerbox","label":"Speakerbox","text":"Speakerbox stores source passages."}]
            conv=system3.new_conversation(inputs,cfg,settings(iid))
            system3.plan_call(conv,cfg)
            prompt=diversity.rewrite_request(conv,cfg)
            self.assertEqual(conv["rewrite_request"]["selected"]["id"],iid)
            self.assertTrue(prompt)
            self.assertFalse(conv["rewrite_request"]["bypasses_validation"])
            self.assertNotIn("{speakerbox}",prompt);self.assertNotIn("{feature}",prompt)
            self.assertTrue(system3.replay(conv,cfg)["ok"])
            if iid=="feature_pitch":self.assertTrue(any(e["family"]=="RWFEATURE" for e in conv["decision_events"]))

    def test_missing_material_visibly_excludes_requests(self):
        cfg=system3.default_config();inputs=call_inputs();inputs["call"]["speakerbox"]=""
        conv=system3.new_conversation(inputs,cfg,settings("no-source"))
        diversity.rewrite_request(conv,cfg)
        excluded=next(e for e in conv["decision_events"] if e["family"]=="RW")["stages"][0]["excluded"]
        self.assertEqual(len(excluded),3)

    def test_rewrite_is_selected_once_for_a_scenario(self):
        cfg=system3.default_config();conv=system3.new_conversation(call_inputs(),cfg,settings("one-pass"))
        first=diversity.rewrite_request(conv,cfg,"copy")
        self.assertEqual(first,diversity.rewrite_request(conv,cfg,"again"))
        self.assertEqual(sum(e["family"]=="RW" for e in conv["decision_events"]),1)

class Expansion(Sandbox):
    def test_persistent_collision_generates_only_a_proposal_with_cooldown(self):
        calls=[]
        async def writer(prompt,limit=0,spice=0,result_contract=""):
            self.assertEqual(result_contract,"roulette_option")
            calls.append(prompt)
            return json.dumps({"text":"Reframe the concrete problem as an unexpected obligation to a fictional neighbor."})
        self.desk.ns["ask_model"]=writer
        before=copy.deepcopy(self.desk.rt().config)
        for cid in ("first","second","third"):
            conv={"identity":{"conversation_id":cid},"call_diversity":{
                "selections":{"CALLANGLE":{"table":"CALLANGLE1"}},
                "repairs":[{"reason":"still copies after repair","selections":[{"family":"CALLANGLE"}]}]}}
            result=asyncio.run(self.desk.caller_diversity_failure(conv))
            if cid=="second":self.assertTrue(result and result["needs_operator"])
            else:self.assertIsNone(result)
        self.assertEqual(len(calls),1)
        self.assertEqual(before,self.desk.rt().config)

    def test_invalid_node_change_is_rejected_before_proposal(self):
        with self.assertRaises(ValueError):
            self.desk.propose_section("structures",{"caller.legs":[]})

class ProposalAPI(Sandbox):
    def test_request_is_resolved_and_new_option_endpoint_only_proposes(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import orchestrator_s3
        app=FastAPI()
        self.ns.update(data_path=lambda name:str(Path(self.tmp.name)/name),
                       require_auth=lambda authorization:None,require_read_auth=lambda authorization:None)
        desk=orchestrator_s3.install(app,self.ns)
        with TestClient(app) as client:
            response=client.get("/openapi.json")
            self.assertEqual(response.status_code,200,response.text)
            old=copy.deepcopy(desk.rt().config)
            response=client.post("/api/orchestrator/system3/propose",json={"option":{"table":"RW1","text":"Rewrite this as a mistaken awards ceremony."}})
            self.assertEqual(response.status_code,200,response.text)
            self.assertTrue(response.json()["needs_operator"])
            self.assertEqual(old,desk.rt().config)
