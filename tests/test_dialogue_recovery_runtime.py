"""Recovery through an isolated System 3 runtime and temporary ledger.

No app.py import, production model, audio recording, or station share access.
"""
import asyncio
import copy
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import dialogue_repair
import dialogue_recovery
import handoff_preparation
import system3
import system3_runtime
from test_system3_runtime import FakeStation, settle


DJ = {"host_name": "Dill", "cohost_name": "Skip", "third_name": "Billy"}


class WritingDeferred(Exception):
    """Stand-in for the station's no-model-admission outcome."""


class DialogueRecoveryRuntimeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.station = FakeStation(tmp.name)
        app = FastAPI()
        system3_runtime.install(app, self.station)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.rt = self.station["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        self.assertTrue(self.rt.ready)
        self.rt.settings = self.rt.apply_settings({"mode": "active", "test_seed": "recovery-runtime"})

    def handle(self):
        config = copy.deepcopy(self.rt.config)
        inputs = {"road": "banter", "seats": ["A", "B", "D"],
                  "names": {"A": "Dill", "B": "Skip", "D": "Billy"},
                  "roles": {"A": "dj", "B": "cohost", "D": "third"},
                  "turns": 4, "target_seconds": 60,
                  "subject": {"topic": "the missing photograph", "authority": "free"},
                  "availability": {}, "speakerbox_rates": {}, "bank": True}
        conv = system3.plan_scene(inputs, config, self.rt.settings,
                                  conversation_id="test-dialogue-recovery")
        conv["mode"] = "active"
        handle = system3_runtime.Handle(self.rt, conv, config, True)
        handle.turns = len(conv["turns"])
        handle.rolls = [{"turn": i + 1, "roll": i + 10} for i in range(handle.turns)]
        self.rt.remember(conv)
        self.rt.persist(conv)
        settle()
        return handle

    @staticmethod
    def rows(handle):
        words = ["The photograph vanished from the table.",
                 "Someone moved the evidence before lunch.",
                 "The gallery staff should check the doorway.",
                 "Tomorrow we can ask the manager about it.",
                 "That question deserves a concrete answer."]
        return [(turn["speaker"], words[i % len(words)] + " Detail %d." % i)
                for i, turn in enumerate(handle.conv["turns"])]

    @staticmethod
    def complete_script(request):
        fixed = {row["index"]: row["text"] for row in request.get("preserved_rows") or []}
        unique = ["Let us examine the frame carefully before drawing a conclusion.",
                  "That suggestion gives our discussion a useful direction.",
                  "I would start with the doorway and work back toward the wall.",
                  "There may be footprints near the loading entrance worth checking.",
                  "Our suspect might simply be a cleaner moving pictures out of harm's way.",
                  "A quick phone call to the owner would settle the delivery schedule.",
                  "The empty wall tells us very little about who carried the photograph.",
                  "Someone should compare the inventory with yesterday's delivery record."]
        turns = request["planned_turns"]
        return "\n".join("%s: %s" % (turn["speaker"], fixed.get(i,
            "Enough detective work for today; back to the music while the gallery checks its records."
            if i == len(turns) - 1 else unique[i % len(unique)] + " Point %d." % i))
            for i, turn in enumerate(turns))

    def finalize(self, handle, rows, writer):
        return asyncio.run(self.station["system3_handoff_exchange"](
            handle, rows, writer, dj=DJ, kind="banter"))

    def test_partial_exchange_is_repaired_by_one_whole_exchange_request(self):
        handle = self.handle()
        stable = handle.conv
        original_turn_ids = [turn["turn_id"] for turn in handle.conv["turns"]]
        original_speakers = copy.deepcopy(handle.conv["participants"])
        rows = self.rows(handle)[:-1]
        requests = []

        async def writer(request):
            requests.append(copy.deepcopy(request))
            return self.complete_script(request)

        result = self.finalize(handle, rows, writer)
        self.assertEqual(result["status"], "ready", result)
        self.assertIs(handle.conv, stable)
        self.assertTrue(result["changed"])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["mode"], "recover_exchange")
        self.assertEqual(requests[0]["recovery"]["operation"], "repair")
        self.assertEqual(result["rows"][:len(rows)], rows)
        self.assertEqual(len(result["rows"]), len(original_turn_ids))
        self.assertEqual([turn["turn_id"] for turn in handle.conv["turns"]], original_turn_ids)
        self.assertEqual(handle.conv["participants"], original_speakers)
        self.assertEqual([seat for seat, _text in result["rows"]],
                         [turn["speaker"] for turn in handle.conv["turns"]])
        self.assertFalse(handle.conv["dialogue_recovery"]["active"])
        self.assertFalse(self.rt._handoff_busy)
        settle()
        saved = self.rt.store.conversation(handle.id)
        self.assertEqual(saved["handoff"]["status"], "ready")
        self.assertEqual(saved["dialogue_recovery"]["total_attempts"], 1)

    def test_three_distinct_failures_persist_debt_then_cooldown_makes_no_model_request(self):
        handle = self.handle()
        before = copy.deepcopy(handle.conv)
        rows = self.rows(handle)[:-1]
        requests = []

        async def invalid_writer(request):
            requests.append(copy.deepcopy(request))
            return "This response has no speaker labels."

        with patch.object(system3_runtime.time, "time", return_value=1000):
            failed = self.finalize(handle, rows, invalid_writer)
        self.assertEqual(failed["status"], "refused", failed)
        self.assertEqual(failed["rows"], [])
        self.assertEqual([r["recovery"]["operation"] for r in requests],
                         ["repair", "rewrite", "reroll"])
        self.assertEqual(len({r["recovery"]["variation_id"] for r in requests}), 3)
        untouched = copy.deepcopy(handle.conv)
        recovery = untouched.pop("dialogue_recovery")
        self.assertEqual(untouched, before)
        self.assertEqual(recovery["attempt"], 3)
        self.assertEqual(recovery["cooldown_until"], 1060)
        self.assertTrue(recovery["stuck"])
        settle()
        saved = self.rt.store.conversation(handle.id)
        self.assertEqual(saved["turns"], before["turns"])
        self.assertEqual(saved["dialogue_recovery"]["total_attempts"], 3)
        with patch.object(system3_runtime.time, "time", return_value=1059):
            cooling = self.finalize(handle, rows, invalid_writer)
        self.assertEqual(cooling["status"], "refused", cooling)
        self.assertEqual(len(requests), 3)
        self.assertEqual(handle.conv["dialogue_recovery"]["total_attempts"], 3)
        self.assertFalse(self.rt._handoff_busy)

        async def valid_writer(request):
            requests.append(copy.deepcopy(request))
            return self.complete_script(request)

        with patch.object(system3_runtime.time, "time", return_value=1060):
            resumed = self.finalize(handle, rows, valid_writer)
        self.assertEqual(resumed["status"], "ready", resumed)
        self.assertEqual(len(requests), 4)
        self.assertEqual(requests[-1]["recovery"]["operation"], "rebuild")
        self.assertEqual(requests[-1]["recovery"]["pass"], 2)
        self.assertEqual(handle.conv["participants"], before["participants"])
        self.assertEqual({seat for seat, _text in resumed["rows"]},
                         {turn["speaker"] for turn in before["turns"]})
        self.assertEqual(handle.conv["identity"]["revision"], before["identity"]["revision"] + 1)
        ids = [event["event_id"] for event in handle.conv["decision_events"]]
        self.assertEqual(len(ids), len(set(ids)), "recovery must not overwrite prior decision identities")
        original_ids = [turn["turn_id"] for turn in before["turns"]]
        self.assertEqual(resumed["original_turn_ids"], original_ids,
                         "old entry metadata must use pre-recovery turn ancestry")
        entry = {"script": "\n".join("%s: %s" % row for row in rows),
                 "turn_source": {str(i): {"source_turn": tid}
                                 for i, tid in enumerate(original_ids)}}
        handoff_preparation.apply_script_result(entry, resumed, lambda _entry: None)
        final_ids = [turn["turn_id"] for turn in handle.conv["turns"]]
        expected = {str(final_ids.index(tid)): {"source_turn": tid}
                    for tid in original_ids if tid in final_ids}
        self.assertEqual(entry["turn_source"], expected,
                         "fresh plan turns must not inherit another turn's source")

    def test_committed_exchange_refuses_before_any_recovery_or_model_work(self):
        handle = self.handle()
        state = dialogue_recovery.recovery_state(handle.conv)
        dialogue_recovery.note_failure(state, "handoff rows must align", 1)
        handle.conv["lines"] = [{"line_id": "already-committed"}]
        before = copy.deepcopy(handle.conv)
        writer = AsyncMock(side_effect=AssertionError("committed exchanges cannot invoke a writer"))
        with patch.object(dialogue_repair, "prepare_recovery", new_callable=AsyncMock) as prepare:
            result = self.finalize(handle, self.rows(handle)[:-1], writer)
        self.assertEqual(result["status"], "refused", result)
        self.assertEqual(result["rows"], [])
        self.assertEqual(handle.conv, before)
        writer.assert_not_awaited()
        prepare.assert_not_awaited()

    def test_stale_binding_is_refused_and_current_finalized_words_bind(self):
        handle = self.handle()
        writer = AsyncMock(side_effect=self.complete_script)
        result = self.finalize(handle, self.rows(handle)[:-1], writer)
        self.assertEqual(result["status"], "ready", result)
        stamp = result["conversation_stamp"]
        entry = {"script": "\n".join("%s: %s" % row for row in result["rows"])}
        before = copy.deepcopy(handle.conv)
        for stale in (dict(stamp, revision=stamp["revision"] + 1),
                      dict(stamp, config_hash="old-config")):
            self.assertFalse(asyncio.run(self.rt.recovery_bind_entry(entry, stale)))
            self.assertEqual(handle.conv, before)
            self.assertNotIn("system3", entry)
        self.assertTrue(asyncio.run(self.rt.recovery_bind_entry(entry, stamp)))
        self.assertEqual(entry["system3"]["conversation_id"], handle.id)
        self.assertEqual(len(entry["system3"]["turns"]), len(result["rows"]))
        self.assertEqual([turn["text"] for turn in handle.conv["turns"]],
                         [text for _seat, text in result["rows"]])

    def test_current_stamp_cannot_bind_words_different_from_the_final_review(self):
        handle = self.handle()
        writer = AsyncMock(side_effect=self.complete_script)
        result = self.finalize(handle, self.rows(handle)[:-1], writer)
        self.assertEqual(result["status"], "ready", result)
        entry = {"script": "A: These different words never received the final dialogue review."}
        before = copy.deepcopy(handle.conv)
        self.assertFalse(asyncio.run(self.rt.recovery_bind_entry(entry, result["conversation_stamp"])))
        self.assertEqual(handle.conv, before)
        self.assertNotIn("system3", entry)

    def test_admission_deferral_refunds_recovery_operation_without_a_creative_rejection(self):
        handle = self.handle()
        before = copy.deepcopy(handle.conv)
        rows = self.rows(handle)[:-1]
        deferred_requests = []

        async def deferred_writer(request):
            deferred_requests.append(copy.deepcopy(request))
            raise WritingDeferred("the writer lane has no model slot")

        with patch.object(system3_runtime.time, "time", return_value=1000):
            result = self.finalize(handle, rows, deferred_writer)
        self.assertEqual(result["status"], "refused", result)
        self.assertTrue(result["deferred"])
        self.assertEqual(result["rows"], [])
        self.assertEqual(len(deferred_requests), 1)
        state = handle.conv["dialogue_recovery"]
        self.assertFalse(state["in_flight"])
        self.assertEqual(state["attempt"], 0)
        self.assertEqual(state["operations_in_pass"], [])
        self.assertEqual(state["failures"], 1, "only the original structural gap is a rejection")
        self.assertEqual(state["cooldown_until"], 0)
        untouched = copy.deepcopy(handle.conv)
        untouched.pop("dialogue_recovery")
        self.assertEqual(untouched, before)
        self.assertFalse(self.rt._handoff_busy)
        settle()
        self.assertEqual(self.rt.store.conversation(handle.id)["dialogue_recovery"]["attempt"], 0)

        requests = []

        async def admitted_writer(request):
            requests.append(copy.deepcopy(request))
            return self.complete_script(request)

        with patch.object(system3_runtime.time, "time", return_value=1000):
            ready = self.finalize(handle, rows, admitted_writer)
        self.assertEqual(ready["status"], "ready", ready)
        self.assertEqual(requests[0]["recovery"]["operation"], "repair")
        self.assertNotEqual(requests[0]["recovery"]["variation_id"],
                            deferred_requests[0]["recovery"]["variation_id"])

    def test_initial_finalizer_admission_deferral_keeps_the_entire_plan_unchanged(self):
        handle = self.handle()
        before = copy.deepcopy(handle.conv)
        rows = self.rows(handle)
        rows[0] = (rows[0][0], "The exhibit needs the photographs framed before its doors open. " * 18)
        writer = AsyncMock(side_effect=WritingDeferred("no model ran"))
        result = self.finalize(handle, rows, writer)
        self.assertEqual(result["status"], "refused", result)
        self.assertTrue(result["deferred"])
        self.assertEqual(result["rows"], [])
        self.assertEqual(handle.conv, before)
        self.assertEqual(writer.await_count, 1)
        self.assertFalse(self.rt._handoff_busy)

    def test_withheld_middle_drop_keeps_exact_source_identities_and_protected_survivor(self):
        handle = self.handle()
        # Repeated seat markers cannot prove which surviving A turn owns text.
        for turn, seat in zip(handle.conv["turns"], ["A", "A", "A", "B"]):
            turn["speaker"] = seat
        original = copy.deepcopy(handle.conv["turns"])
        rows = self.rows(handle)
        survivors = [rows[i] for i in (0, 2, 3)]
        handle.conv["turn_gate"] = {
            "held": "a required review held this exchange",
            "turns": [{"turn_id": original[1]["turn_id"], "turn": 1, "state": "dropped"}],
            "output_turn_ids": [original[i]["turn_id"] for i in (0, 2, 3)],
        }
        requests = []

        async def writer(request):
            requests.append(copy.deepcopy(request))
            return self.complete_script(request)

        result = asyncio.run(self.station["system3_handoff_exchange"](
            handle, survivors, writer, dj=DJ, kind="banter", protected=[1]))
        self.assertEqual(result["status"], "ready", result)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["mode"], "recover_exchange")
        preserved = {row["turn_id"]: row for row in requests[0]["preserved_rows"]}
        self.assertEqual(set(preserved), {original[i]["turn_id"] for i in (0, 2, 3)})
        self.assertEqual(preserved[original[2]["turn_id"]]["index"], 2)
        self.assertTrue(preserved[original[2]["turn_id"]]["protected"])
        self.assertEqual(result["rows"][2], rows[2])
        self.assertNotEqual(result["rows"][1], rows[2])
        self.assertEqual(handle.conv["dialogue_recovery_preparation"]["source_turn_ids"],
                         [original[i]["turn_id"] for i in (0, 2, 3)])
        self.assertFalse(handle.conv["turn_gate"]["held"])
        self.assertEqual(handle.conv["turn_gate"]["output_turn_ids"],
                         [turn["turn_id"] for turn in handle.conv["turns"]])

    def test_required_tint_cut_refusal_enters_recovery_after_reconciliation(self):
        handle = self.handle()
        original = copy.deepcopy(handle.conv["turns"])
        original[-1]["required_closing"] = handle.conv["turns"][-1]["required_closing"] = True
        rows = self.rows(handle)
        handle.conv["turn_gate"] = {"turns": [],
                                   "output_turn_ids": [turn["turn_id"] for turn in original]}
        evidence = {"tint_cuts": {"source_rows": rows, "cut_indexes": [len(rows) - 1],
                                   "output_rows": rows[:-1]}}
        requests = []

        async def writer(request):
            requests.append(copy.deepcopy(request))
            return self.complete_script(request)

        result = asyncio.run(self.station["system3_handoff_exchange"](
            handle, rows[:-1], writer, dj=DJ, kind="banter", assembly_trace=evidence))
        self.assertEqual(result["status"], "ready", result)
        self.assertEqual(len(requests), 1)
        self.assertIn("required conversation leg", requests[0]["rejection"])
        self.assertEqual(requests[0]["recovery"]["failed_turn_ids"], [original[-1]["turn_id"]])
        self.assertEqual([turn["turn_id"] for turn in handle.conv["turns"]],
                         [turn["turn_id"] for turn in original])
        self.assertEqual(result["rows"][:-1], rows[:-1])
        self.assertRegex(result["rows"][-1][1], system3.CUES["close"])

    def test_unwritten_closing_completion_refusal_uses_a_fresh_whole_exchange(self):
        handle = self.handle()
        original = copy.deepcopy(handle.conv["turns"])
        handle.conv["turns"][-1]["required_closing"] = True
        rows = self.rows(handle)[:-1]
        handle.conv["turn_gate"] = {"turns": [], "unwritten_turn_ids": [original[-1]["turn_id"]],
                                   "output_turn_ids": [turn["turn_id"] for turn in original[:-1]]}
        requests = []

        async def writer(request):
            requests.append(copy.deepcopy(request))
            if request["mode"] == "reanchor":
                return "The wooden frame has square corners and a narrow border."
            return self.complete_script(request)

        result = self.finalize(handle, rows, writer)
        self.assertEqual(result["status"], "ready", result)
        self.assertEqual([request["mode"] for request in requests], ["reanchor", "recover_exchange"])
        self.assertEqual(requests[1]["recovery"]["failed_turn_ids"], [original[-1]["turn_id"]])
        self.assertEqual(result["rows"][:-1], rows)
        self.assertRegex(result["rows"][-1][1], system3.CUES["close"])
        self.assertEqual(handle.conv["turn_gate"]["kept"], len(original))

    def test_fresh_copy_rejection_does_not_commit_any_candidate_words_or_plan(self):
        handle = self.handle()
        handle.conv["turn_gate"] = {"held": "the prior dialogue is withheld", "turns": [],
                                   "output_turn_ids": [turn["turn_id"] for turn in handle.conv["turns"]]}
        before = copy.deepcopy(handle.conv)
        requests = []

        async def writer(request):
            requests.append(copy.deepcopy(request))
            return "\n".join("%s: The photograph disappeared before the gallery opened this morning." % turn["speaker"]
                             for turn in request["planned_turns"])

        result = self.finalize(handle, self.rows(handle), writer)
        self.assertEqual(result["status"], "refused", result)
        self.assertEqual(result["rows"], [])
        self.assertEqual([request["recovery"]["operation"] for request in requests],
                         ["repair", "rewrite", "reroll"])
        self.assertIn("copy gate refused", result["why"])
        untouched = copy.deepcopy(handle.conv)
        state = untouched.pop("dialogue_recovery")
        self.assertEqual(untouched, before)
        self.assertEqual(state["attempt"], 3)
        self.assertFalse(self.rt._handoff_busy)

    def test_missing_closing_cue_stays_refused_through_rebuild_after_cooldown(self):
        handle = self.handle()
        original = copy.deepcopy(handle.conv["turns"])
        handle.conv["turns"][-1]["required_closing"] = True
        rows = self.rows(handle)[:-1]
        handle.conv["turn_gate"] = {"turns": [], "unwritten_turn_ids": [original[-1]["turn_id"]],
                                   "output_turn_ids": [turn["turn_id"] for turn in original[:-1]]}
        before = copy.deepcopy(handle.conv)
        requests = []

        async def writer(request):
            requests.append(copy.deepcopy(request))
            if request["mode"] == "reanchor":
                return "The wooden frame has square corners and a narrow border."
            lines = self.complete_script(request).splitlines()
            lines[-1] = "%s: The wooden frame has square corners and a narrow border." % request["planned_turns"][-1]["speaker"]
            return "\n".join(lines)

        with patch.object(system3_runtime.time, "time", return_value=1000):
            first = self.finalize(handle, rows, writer)
        self.assertEqual(first["status"], "refused", first)
        self.assertEqual(first["rows"], [])
        self.assertIn("closing", first["why"])
        attempts_before = len(requests)
        with patch.object(system3_runtime.time, "time", return_value=1059):
            cooling = self.finalize(handle, rows, writer)
        self.assertEqual(cooling["status"], "refused", cooling)
        self.assertEqual(len(requests), attempts_before,
                         "cooldown must suppress the old required-leg writer as well as new recovery commands")
        self.assertEqual(handle.conv["dialogue_recovery"]["cooldown_until"], 1060)
        with patch.object(system3_runtime.time, "time", return_value=1060):
            second = self.finalize(handle, rows, writer)
        self.assertEqual(second["status"], "refused", second)
        self.assertEqual(second["rows"], [])
        recovered = [request for request in requests if request["mode"] == "recover_exchange"]
        self.assertEqual(recovered[3]["recovery"]["operation"], "rebuild")
        self.assertIn("closing", second["why"])
        untouched = copy.deepcopy(handle.conv)
        untouched.pop("dialogue_recovery")
        self.assertEqual(untouched, before)

    def test_admission_deferral_of_original_required_leg_completion_spends_no_recovery(self):
        handle = self.handle()
        original = copy.deepcopy(handle.conv["turns"])
        handle.conv["turns"][-1]["required_closing"] = True
        handle.conv["turn_gate"] = {"turns": [], "unwritten_turn_ids": [original[-1]["turn_id"]],
                                   "output_turn_ids": [turn["turn_id"] for turn in original[:-1]]}
        before = copy.deepcopy(handle.conv)
        requests = []

        async def writer(request):
            requests.append(copy.deepcopy(request))
            raise WritingDeferred("no model slot was admitted")

        result = self.finalize(handle, self.rows(handle)[:-1], writer)
        self.assertEqual(result["status"], "refused", result)
        self.assertTrue(result["deferred"])
        self.assertEqual(result["rows"], [])
        self.assertEqual([request["mode"] for request in requests], ["reanchor"])
        self.assertEqual(handle.conv, before)
        self.assertNotIn("dialogue_recovery", handle.conv)
        self.assertFalse(self.rt._handoff_busy)


if __name__ == "__main__":
    unittest.main()
