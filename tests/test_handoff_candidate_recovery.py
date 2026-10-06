"""Live failure shapes, isolated from production data/model/playback side effects."""
import ast
import asyncio
import copy
import hashlib
import json
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import handoff_preparation as hp
import system3
import system3_handoff
import system3_runtime
import test_system3_handoff_runtime as runtime_tests
from test_system3_handoff_runtime import DJ
from test_system3_runtime import settle

ROOT = Path(__file__).resolve().parents[1]
LIVE = json.loads((ROOT / "tests/fixtures/stale_gallery_handoff.json").read_text(encoding="utf-8-sig"))


def parse(script, *_names):
    return [(s.split(":", 1)[0], s.split(":", 1)[1].strip()) for s in script.splitlines() if ":" in s]


def station_functions(*names):
    """Compile only the requested real functions; importing app boots stores."""
    lines = (ROOT / "app.py").read_text(encoding="utf-8").splitlines(True)
    blocks = []
    for name in names:
        at = next(i for i, s in enumerate(lines) if s.startswith("def " + name + "(") or s.startswith("async def " + name + "("))
        end = at + 1
        while end < len(lines):
            line = lines[end]
            if line.strip() and not line[0].isspace() and not line.startswith("#"):
                break
            end += 1
        blocks.append("".join(lines[at:end]))
    return compile("from __future__ import annotations\n" + "\n".join(blocks), "station candidate functions", "exec")


class CandidateRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.base = runtime_tests.HandoffRuntimeTests(methodName="runTest")
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.rt = self.base.rt

    def saved_gallery(self):
        h = self.base.handle(road="gallery")
        shape = LIVE["conversation"]
        h.conv["identity"]["conversation_id"] = shape["identity"]["conversation_id"]
        h.conv["status"] = shape["status"]
        h.conv["turns"] = [dict(t, name=DJ.get({"A":"host_name", "B":"cohost_name", "D":"third_name"}[t["speaker"]]),
                                 decisions=[], directions=[], text="", phase="OPEN") for t in shape["turns"]]
        h.conv["handoff"] = {"status": shape["handoff_status"]}
        self.rt.remember(h.conv)
        self.rt.persist(h.conv)
        settle()
        self.rt.store.add_lines([dict(r, conversation_id=h.id, text="Already committed dialogue.", at=time.time()) for r in LIVE["ledger_lines"]])
        return h, dict(LIVE["candidate"]["system3"], config_hash=h.conv["config_hash"])

    def test_persisted_gallery_identity_is_permanent_and_never_rewritten(self):
        h, stamp = self.saved_gallery()
        self.assertEqual(len(self.rt.store.conversation(h.id)["lines"]), 4)
        before = copy.deepcopy(self.rt.store.conversation(h.id))
        state = asyncio.run(self.rt.handoff_candidate_status(stamp))
        self.assertFalse(state["ok"])
        self.assertTrue(state["permanent"])
        writer = AsyncMock()
        result = asyncio.run(self.rt.handoff_exchange(stamp, [("A", "Stale candidate.")], writer, dj=DJ))
        self.assertEqual(result["status"], "refused")
        writer.assert_not_awaited()
        after = self.rt.store.conversation(h.id)
        self.assertEqual(before["lines"], after["lines"])
        self.assertEqual(before["turns"], after["turns"])

    def test_pending_current_producer_is_temporary_and_not_retired(self):
        h = self.base.handle()
        self.rt.pending_links["current"] = {"conversation_id": h.id}
        state = asyncio.run(self.rt.handoff_candidate_status({"conversation_id": h.id}))
        self.assertFalse(state["ok"])
        self.assertFalse(state["permanent"])
        self.rt.pending_links.clear()
        self.assertTrue(asyncio.run(self.rt.handoff_candidate_status({"conversation_id": h.id}))["ok"])

    def test_legacy_all_dropped_candidate_cannot_hold_new_production_slots(self):
        h=self.base.handle()
        for turn in h.conv["turns"]:turn["status"]="dropped"
        state=asyncio.run(self.rt.handoff_candidate_status({"conversation_id":h.id}))
        self.assertFalse(state["ok"]);self.assertTrue(state["permanent"])
        self.assertEqual(self.rt.store.conversation(h.id)["lines"],[])

    def test_copy_gate_rejected_required_closing_is_never_revived(self):
        h=self.base.handle();rows=self.base.rows(h);last=h.conv["turns"][-1]
        last["decisions"]=[{"family":"FL","item":"closure"}]
        h.conv["turn_gate"]={"output_turn_ids":[t["turn_id"] for t in h.conv["turns"][:-1]],
            "turns":[{"turn_id":last["turn_id"],"turn":last["index"],"state":"dropped"}],"held":""}
        before=copy.deepcopy(h.conv);writer=AsyncMock()
        result=asyncio.run(self.rt.handoff_exchange(h,rows[:-1],writer,dj=DJ))
        self.assertEqual(result["status"],"refused");self.assertEqual(h.conv,before)
        writer.assert_not_awaited()

    def test_repair_returning_another_direction_echo_cannot_get_a_receipt(self):
        h=self.base.handle();rows=self.base.rows(h);rows[0]=(rows[0][0],"Echo a spoken direction.")
        before=copy.deepcopy(h.conv);writer=AsyncMock(return_value="Echo another spoken direction.")
        with patch.object(system3,"direction_echo",side_effect=lambda text,kit:"a direction" if text.startswith("Echo") else ""):
            result=asyncio.run(self.rt.handoff_exchange(h,rows,writer,dj=DJ))
        self.assertEqual(result["status"],"refused");self.assertEqual(h.conv,before)
        self.assertNotIn("handoff",h.conv)

    def test_tint_selection_uses_actual_approved_ids_for_repeated_seats(self):
        h=self.base.handle();template=h.conv["turns"][0]
        h.conv["turns"]=[dict(copy.deepcopy(template),turn_id=h.id+":t%02d"%i,index=i,
                             speaker=seat,tint={"rhyme":i in (1,3,5)}) for i,seat in enumerate("ABABAB")]
        approved=[h.conv["turns"][i]["turn_id"] for i in (0,3,4,5)]
        h.conv["turn_gate"]={"output_turn_ids":approved}
        self.base.station["banter_turns"]=parse
        with patch.object(system3,"align",side_effect=AssertionError("seat matching cannot identify gate survivors")):
            selected=self.rt.tint_turns(h,"A: Opening.\nB: Second.\nA: Third.\nB: Closing.")
        self.assertEqual(selected,{1,3})

    def test_actual_partial_writer_shape_completes_original_fl_closing_then_binds(self):
        h = self.base.handle()
        fresh = LIVE["fresh_failure"]
        h.conv["identity"]["conversation_id"] = fresh["conversation_id"]
        h.conv["turns"] = [dict(t, name=DJ.get({"A":"host_name", "B":"cohost_name", "D":"third_name"}[t["speaker"]]),
                                 decisions=[], directions=[], text="", phase="OPEN") for t in fresh["turns"]]
        h.conv["turns"][-1]["decisions"] = copy.deepcopy(fresh["ending_decisions"])
        h.rolls = [{"turn": i+1, "roll": i+100} for i in range(len(h.conv["turns"]))]
        phrases = ["The photograph disappeared before the doors opened.", "The delivery receipt lists a second frame.",
                   "A member of staff can check the storage cupboard.", "The guest tour needs the wall labels in place.",
                   "That frame belongs beside the entrance desk."]
        ids = fresh["written_turn_ids"]
        rows = [(t["speaker"], phrases[i]) for i,t in enumerate(h.conv["turns"]) if t["turn_id"] in ids]
        gate = system3.gate_open(h.conv, rows, rewrites=0, visits=0)
        done = system3.gate_close(h.conv, gate)
        self.assertFalse(done["held"])
        self.assertEqual(len(rows), 5)
        self.assertEqual(len(h.conv["turns"]), 11)
        expected_last = h.conv["turns"][-1]["turn_id"]
        self.assertIn(expected_last, h.conv["turn_gate"]["unwritten_turn_ids"])
        writer = AsyncMock(return_value="We can put the frame beside that desk. Back to the music.")
        result = asyncio.run(self.rt.handoff_exchange(h, rows, writer, dj=DJ))
        self.assertEqual(result["status"], "ready", result)
        self.assertTrue(result["changed"])
        self.assertEqual(result["turn_ids"], ids + [expected_last])
        self.assertEqual(writer.await_count, 1)
        self.assertTrue(writer.await_args.args[0]["mandatory_closing"])
        self.assertEqual(writer.await_args.args[0]["turn_id"], expected_last)
        self.assertEqual(h.conv["turns"][-1]["reply_to"]["turn_id"],ids[-1])
        self.assertEqual([r["roll"] for r in h.rolls], [100,101,102,103,104,110])
        entry = {"script": "\n".join("%s: %s" % row for row in result["rows"]), "prep_kind":"banter"}
        hp.apply_script_result(entry, dict(result, changed=False), Mock())
        self.base.station["banter_turns"] = parse
        with patch.object(self.rt, "echo_cut", side_effect=AssertionError("certified text cannot be cut after review")):
            self.rt.bind_entry(entry, h)
        self.assertTrue(hp.receipt_matches_script(entry))
        self.assertEqual([entry["system3"]["turns"][str(i)] for i in range(len(result["rows"]))], ids + [expected_last])
        settle()
        self.assertEqual(self.rt.store.conversation(h.id)["lines"], [])


class TintCutProofTests(unittest.IsolatedAsyncioTestCase):
    def entry(self):
        source = [("A","A photograph is missing from the wall."),("B","The invoice gives us another lead."),
                  ("A","That frame arrived with the morning delivery."),("B","Check the cupboard before the gallery opens.")]
        review = [{"marker":s,"source":hashlib.sha1(t.encode()).hexdigest(),"text":t,"selected":True} for s,t in source]
        review[1].update(cut=True,text="",rejected_source=source[1][1])
        entry = {"use":"tinted","script_plain":"\n".join("%s: %s" % r for r in source),
                 "script":"\n".join("%s: %s" % r for i,r in enumerate(source) if i!=1),"tint":{"review_turns":review}}
        return entry, source

    async def test_proven_tint_cut_uses_gate_ids_and_never_seat_alignment(self):
        entry,source = self.entry()
        from test_system3_handoff import fixture, PEOPLE, Writer
        # This repeated seat sequence reproduces the ambiguity: align can
        # choose an earlier dropped B, while the gate approved specific IDs.
        conv,config,_ = fixture(["Unused"]*6,seats=["A","B","A","B","A","B"])
        ids=[conv["turns"][i]["turn_id"] for i in (0,3,4,5)]
        conv["turn_gate"]={"output_turn_ids":ids,"turns":[{"turn_id":conv["turns"][i]["turn_id"],"turn":i,"state":"dropped"} for i in (1,2)]}
        proof=hp.tint_cut_receipt(entry,parse)
        rows=parse(entry["script"])
        system3_handoff.reconcile_copy_gate(conv,rows,proof)
        self.assertEqual([t["turn_id"] for t in conv["turns"]],[ids[0],ids[2],ids[3]])
        self.assertEqual(conv["handoff_gate"]["tint_cut_turn_ids"],[ids[1]])
        result=await system3_handoff.finalize_exchange(conv,config,rows,PEOPLE,
            Writer(lambda request: "The staff assigned %s a separate frame before tomorrow's guest tour." % request["turn_id"]))
        self.assertEqual(result["turn_ids"],[ids[0],ids[2],ids[3]])

    def test_abandoned_or_forged_tint_cut_proof_is_refused(self):
        for mutate in (lambda e:e["tint"]["review_turns"][1].update(source="bad"),
                       lambda e:e.update(script=e["script_plain"]),
                       lambda e:e["tint"]["review_turns"].pop()):
            entry,_=self.entry();mutate(entry)
            with self.assertRaises(ValueError):hp.tint_cut_receipt(entry,parse)

    def test_tint_cut_cannot_drop_final_original_fl_closing(self):
        from test_system3_handoff import fixture
        entry,source=self.entry(); review=entry["tint"]["review_turns"]
        review[1].pop("cut");review[1]["text"]=source[1][1]
        review[-1].update(cut=True,text="",rejected_source=source[-1][1])
        entry["script"]="\n".join("%s: %s" % r for r in source[:-1])
        conv,_,_=fixture([text for _,text in source],seats=[seat for seat,_ in source])
        conv["turns"][-1]["decisions"]=[{"family":"FL","item":"closure"}]
        conv["turn_gate"]={"output_turn_ids":[t["turn_id"] for t in conv["turns"]]}
        with self.assertRaisesRegex(ValueError,"required conversation leg"):
            system3_handoff.reconcile_copy_gate(conv,parse(entry["script"]),hp.tint_cut_receipt(entry,parse))


class CandidateAdmissionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.code=station_functions("_s3_retire_handoff_candidate","dialogue_entry","dialogue_row_ready",
            "dialogue_row_viable","larder_prepare","_banter_air","_ready_air_entry","_s3_recover_larder_candidates")

    def namespace(self):
        ns={"time":time,"copy":copy,"_LARDER":[],"_SHELF":{},"_UNHEARD_MEMO":{"at":1},
            "_larder_save":Mock(),"_pantry_save":Mock(),"pipeline_log":Mock(),"_radio_entry_rejected":Mock(),
            "_banter_no":lambda why:[],"_pantry_lifecycle":lambda:None,"_PANTRY":{},
            "content_gate_enabled":lambda *_:False,"_larder_current":lambda *_:True,
            "script_has_forgotten_line":lambda *_:False,"tint_exhausted":lambda *_:False,
            "dialogue_tint_ready":lambda *_:True,"dialogue_audio_ready":lambda *_:True,
            "s3_binding_withheld":lambda *_:""}
        exec(self.code,ns);return ns

    async def test_stale_committed_candidate_quarantines_copies_and_releases_stock_cap(self):
        ns=self.namespace();cid=LIVE["candidate"]["system3"]["conversation_id"]
        stale={"script":"A: Stale words.","prep_kind":"gallery","system3":{"mode":"active","conversation_id":cid}}
        stored=copy.deepcopy(stale);ns["_SHELF"]={"gallery":[{"entry":stored}]};ns["_LARDER"]=[copy.deepcopy(stale)]
        valid=copy.deepcopy(stale);hp.apply_script_result(valid,{"status":"ready","changed":False,"rows":parse(valid["script"])},Mock())
        ns["_SHELF"]["gallery"].append({"entry":valid})
        ns["system3_handoff_candidate_status"]=AsyncMock(return_value={"ok":False,"permanent":True,"why":LIVE["observed_failure"]})
        ns["_s3_handoff_entry"]=AsyncMock(side_effect=AssertionError("committed dialogue must not be rewritten"))
        result=await ns["_banter_air"](copy.deepcopy(stale),None)
        self.assertEqual(result,[])
        ns["_s3_handoff_entry"].assert_not_awaited()
        self.assertTrue(stored["handoff_unavailable"])
        self.assertTrue(ns["_LARDER"][0]["handoff_unavailable"])
        self.assertFalse(ns["dialogue_row_viable"]("gallery",{"entry":stored}))
        self.assertFalse(ns["dialogue_row_ready"]("gallery",{"entry":stored}))
        self.assertFalse(await ns["larder_prepare"](stored))
        self.assertNotIn("handoff_unavailable",valid)
        self.assertTrue(ns["dialogue_row_viable"]("gallery",{"entry":valid}))
        self.assertTrue(ns["dialogue_row_ready"]("gallery",{"entry":valid}))
        self.assertEqual(sum(ns["dialogue_row_viable"]("gallery",r) for r in ns["_SHELF"]["gallery"]),1)

    async def test_authenticated_nested_stock_bypasses_review_and_remains_ready(self):
        ns=self.namespace();entry={"script":"A: Certified original.","prep_kind":"gallery","system3":{"mode":"active","conversation_id":"original"}}
        hp.apply_script_result(entry,{"changed":False,"status":"ready","rows":parse(entry["script"])},Mock())
        normalized=ns["_ready_air_entry"]("gallery",{"entry":entry})
        self.assertTrue(hp.receipt_matches_script(normalized))
        ns["system3_handoff_candidate_status"]=AsyncMock(side_effect=AssertionError("authentic stock needs no new review"))
        ns["_s3_handoff_entry"]=AsyncMock(side_effect=AssertionError("authentic stock cannot be rewritten"))
        ns["_system2_repeat_rows_async"]=AsyncMock(return_value=False)
        self.assertEqual(await ns["_banter_air"](normalized,None,ready_takes=[]),[])
        ns["system3_handoff_candidate_status"].assert_not_awaited()
        ns["_s3_handoff_entry"].assert_not_awaited()
        self.assertNotIn("handoff_unavailable",entry)

    async def test_bank_recovery_quarantines_dead_slots_but_keeps_current_producers(self):
        ns=self.namespace()
        dead={"script":"A: Dead draft.","prep_kind":"banter","system3":{"mode":"active","conversation_id":"dead"}}
        busy=copy.deepcopy(dead);busy["system3"]["conversation_id"]="busy";busy["preparing"]=True
        pending=copy.deepcopy(dead);pending["system3"]["conversation_id"]="pending"
        ns["_LARDER"]=[dead,busy,pending]
        async def status(stamp):
            return {"ok":False,"permanent":stamp["conversation_id"]=="dead","why":"unreviewed candidate unavailable"}
        ns["system3_handoff_candidate_status"]=AsyncMock(side_effect=status)
        self.assertEqual(await ns["_s3_recover_larder_candidates"](),1)
        self.assertEqual(ns["system3_handoff_candidate_status"].await_count,2)
        self.assertTrue(dead["handoff_unavailable"])
        self.assertNotIn("handoff_unavailable",busy)
        self.assertNotIn("handoff_unavailable",pending)


if __name__ == "__main__":unittest.main()
