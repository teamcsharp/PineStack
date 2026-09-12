"""Actual tint wrappers keep one prompt contract and resumable ordered work.

Every model response and production side effect is replaced. The shared prompt
builders, budget planner, turn parser and wrapper control flow remain real.
Run with an isolated SPARK_AGENT_DATA_DIR, as for the backend test suite.
"""
import copy
import hashlib
import unittest
from contextlib import ExitStack
from unittest import mock

import app


class CrystalPromptIntegrationTests(unittest.IsolatedAsyncioTestCase):
    SOURCE = "Mara cannot return the twelve copper plates before midnight."
    RAW_GOOD = "Mara cannot return twelve copper plates before midnight / The return must wait, however tight."
    GOOD = "Mara cannot return twelve copper plates before midnight; The return must wait, however tight."
    BAD = "Mara can return twenty-four gold plates before noon."
    SECOND_BAD = "Mara can sell the gold plates before noon."
    META = "Please provide the original line to rewrite."
    WORLD = "Preserved world: dry comic images and dense internal rhymes."
    CHUNKS = [{"file": "fixture-style.txt", "text": "Operation meets calibration. Full style tail stays."}]
    INSTRUCTION = "Keep the end-rhyme pair concise."

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # 2026-09-09: these cases count the asks of the FIRST-PASS ladder -
        # the meta retry, the unchanged retry, caller fidelity and the
        # evaluator repair. The one revision pass added the same day is a
        # separate stage that runs on an ALREADY-ACCEPTED bar and is proved in
        # test_crystal_revision; left on here it would be priced into every
        # ladder count and hide the thing these cases measure.
        self.settings = {**app.DEFAULT_DJ, "reply_max_chars": 1000,
                         "crystal_tint_pass": True, "crystal_tint_hold": True,
                         "crystal_coverage": 100, "crystal_revision": "off"}
        values = {
            "dj_settings": mock.Mock(return_value=self.settings),
            "crystal_force": mock.Mock(return_value=.88),
            "crystal_operator_refinement": mock.Mock(return_value=self.INSTRUCTION),
            "crystal_active": mock.Mock(return_value=[{"name": "fixture", "on": True}]),
            "crystal_stanzas": mock.Mock(return_value=self.CHUNKS),
            "crystal_world_prompt": mock.Mock(return_value=self.WORLD),
            "crystal_coverage_target": mock.Mock(return_value=100),
            "crystal_tint_holds": mock.Mock(return_value=True),
            "crystal_vocab_warm": mock.AsyncMock(),
            "crystal_prompt_contract": mock.Mock(side_effect=lambda text: "Exact source contract: " + text),
            "_crystal_vocab": mock.Mock(return_value=frozenset()),
            "tint_model_for": mock.Mock(return_value="fixture-model"),
            "tint_fast_model": mock.Mock(return_value="fixture-model"),
            "tint_should_stop": mock.Mock(return_value=""),
            "surplus": mock.Mock(return_value=0),
            "task_cost": mock.Mock(return_value=.1),
            "_PREP_DEADLINE": [0.0],
            "line_review_permits": mock.Mock(return_value=False),
            "line_review_capture": mock.Mock(return_value={"id": "fixture-review", "event_seq": 1}),
            "line_review_policy": mock.Mock(return_value={"enabled": True}),
        }
        for name in ("tint_seen", "pipeline_log", "station_flow_event", "task_note",
                     "_tint_flow", "tint_spend_note", "trail_note", "chunk_answer",
                     "_tint_output_note"):
            values[name] = mock.Mock()
        for name, value in values.items():
            self.stack.enter_context(mock.patch.object(app, name, value))
        self.turn_builder = self.stack.enter_context(mock.patch.object(
            app, "crystal_prompt_turn", wraps=app.crystal_prompt_turn))
        self.round_builder = self.stack.enter_context(mock.patch.object(
            app, "crystal_prompt_round", wraps=app.crystal_prompt_round))
        self.planner = self.stack.enter_context(mock.patch.object(
            app, "crystal_budget_plan", wraps=app.crystal_budget_plan))
        self.writer = self.stack.enter_context(mock.patch.object(
            app, "ask_model", new=mock.AsyncMock(side_effect=AssertionError("Unexpected model call"))))
        self.grader = self.stack.enter_context(mock.patch.object(
            app, "tint_evaluate", side_effect=self.grade))
        self.stack.enter_context(mock.patch.object(app, "_looks_meta",
                                                   side_effect=lambda text: str(text) == self.META))

    @classmethod
    def good_for(cls, source):
        return app._tint_out_clean(cls.raw_good_for(source))

    @classmethod
    def raw_good_for(cls, source):
        return source.rstrip(".") + " / The copper plates can wait."

    @classmethod
    def bad_report(cls, candidate):
        return {"ok": False, "machine_ok": False, "version": 4, "strength": .88,
                "faults": ["semantic preservation failed", "no rhyme evidence"],
                "semantic": {"missing_names": [{"text": "Mara", "normalized": "mara"}],
                             "missing_numbers": [{"value": "12", "kind": "number"}],
                             "missing": ["copper", "midnight"], "negation": False},
                "candidate_fingerprint": hashlib.sha1(str(candidate).encode()).hexdigest()}

    def grade(self, source, candidate, *args, **kwargs):
        good = candidate in (self.GOOD, self.good_for(source))
        return ({"ok": True, "machine_ok": True, "faults": [],
                 "version": 4, "strength": .88} if good else self.bad_report(candidate))

    async def turn(self, kind="banter"):
        return await app.crystal_turn(self.SOURCE, self.WORLD, self.CHUNKS,
                                      kind=kind, model="fixture-model")

    def assert_shared_contract(self, prompt):
        self.assertIn(self.SOURCE, prompt)
        self.assertIn(self.WORLD, prompt)
        self.assertIn(self.CHUNKS[0]["text"], prompt)
        self.assertIn(self.INSTRUCTION, prompt)
        self.assertIn(" / ", prompt)
        self.assertIn("rhyme", prompt.lower())
        self.assertIn("SOURCE CONTRACT", prompt)

    def assert_repair(self, model_index, candidate, expected_report=None):
        prompt = self.writer.call_args_list[model_index].args[0]
        self.assert_shared_contract(prompt)
        candidates = [call for call in self.turn_builder.call_args_list
                      if call.kwargs.get("candidate") == candidate]
        self.assertTrue(candidates, "The real prompt builder did not receive the actual failed candidate")
        report = candidates[-1].kwargs.get("evaluation")
        self.assertIsInstance(report, dict)
        self.assertTrue(report.get("faults"), report)
        if expected_report is not None:
            self.assertEqual({key: report.get(key) for key in expected_report}, expected_report)
        self.assertIn(candidate, prompt)

    async def test_meta_retry_keeps_source_style_rhyme_and_actual_meta_response(self):
        self.writer.side_effect = [self.META, self.RAW_GOOD]
        self.assertEqual(await self.turn(), self.GOOD)
        self.assertEqual(self.writer.await_count, 2)
        self.assert_repair(1, self.META)

    async def test_unchanged_retry_keeps_actual_unchanged_candidate_and_fault(self):
        self.writer.side_effect = [self.SOURCE, self.RAW_GOOD]
        self.assertEqual(await self.turn(), self.GOOD)
        self.assertEqual(self.writer.await_count, 2)
        self.assert_repair(1, self.SOURCE)

    async def test_both_caller_fidelity_repairs_keep_latest_candidate_and_full_report(self):
        reports = {self.BAD: {"ok": False, "faults": ["lost the copper plates"],
                             "missing_numbers": [{"value": "12"}]},
                   self.SECOND_BAD: {"ok": False, "faults": ["invented a sale"],
                                    "missing_names": [{"text": "Mara"}]}}

        def fidelity(plain, rewritten, *args, **kwargs):
            candidate = app.banter_turns(rewritten)[-1][1]
            return copy.deepcopy(reports.get(candidate, {"ok": True, "faults": []}))

        self.writer.side_effect = [self.BAD, self.SECOND_BAD, self.RAW_GOOD]
        with mock.patch.object(app, "call_tint_report", side_effect=fidelity):
            self.assertEqual(await self.turn("caller"), self.GOOD)
        self.assertEqual(self.writer.await_count, 3)
        self.assert_repair(1, self.BAD, reports[self.BAD])
        self.assert_repair(2, self.SECOND_BAD, reports[self.SECOND_BAD])

    async def test_evaluator_repair_keeps_actual_candidate_and_detailed_machine_faults(self):
        self.writer.side_effect = [self.BAD, self.RAW_GOOD]
        self.assertEqual(await self.turn(), self.GOOD)
        self.assert_repair(1, self.BAD, self.bad_report(self.BAD))

    async def test_failed_turn_returns_safe_source_and_latest_failed_evidence_separately(self):
        self.writer.side_effect = [self.BAD, self.SECOND_BAD]
        result = await self.turn()
        self.assertIsInstance(result, str)
        self.assertEqual(str(result), self.SOURCE)
        self.assertEqual(result.rejected_candidate, self.SECOND_BAD)
        expected = self.bad_report(self.SECOND_BAD)
        self.assertEqual({key: result.evaluation.get(key) for key in expected}, expected)
        self.assertFalse(result.evaluation["machine_ok"])

    async def test_resumed_turn_builder_receives_retained_failed_attempt_from_parent_context(self):
        failure = self.bad_report(self.BAD)
        self.writer.side_effect = [self.RAW_GOOD]
        result = await app._line_review_scoped(self.turn(), {
            "last_rejected_candidate": self.BAD,
            "last_rejected_evaluation": failure,
            "script_plain": "A: " + self.SOURCE,
        })
        self.assertEqual(result, self.GOOD)
        self.assertEqual(self.writer.await_count, 1)
        self.assert_repair(0, self.BAD, failure)

    async def test_outer_turn_retry_preserves_latest_failure_instead_of_grading_safe_source(self):
        original = "A: " + self.SOURCE + "\nB: " + self.SOURCE
        contexts = []

        async def rewrite(source, *args, **kwargs):
            contexts.append(copy.deepcopy(app._LINE_REVIEW_CONTEXT.get()))
            if len(contexts) <= 2:
                candidate = self.BAD if len(contexts) == 1 else self.SECOND_BAD
                return app.CrystalTurnFailure(source, candidate, self.bad_report(candidate))
            return self.GOOD

        with (mock.patch.object(app, "_crystal_round_first_pass", new=mock.AsyncMock(return_value=[])),
              mock.patch.object(app, "_crystal_round_repass", new=mock.AsyncMock(return_value=([], False))),
              mock.patch.object(app, "crystal_turn", side_effect=rewrite)):
            report = await app.crystal_tint(original, "banter", [], critical=True)
        self.assertTrue(report["ok"], report.get("why"))
        self.assertTrue(report["coverage"]["met"])
        self.assertEqual(len(contexts), 4)
        self.assertEqual(contexts[1]["last_rejected_candidate"], self.BAD)
        self.assertEqual(contexts[1]["last_rejected_evaluation"], self.bad_report(self.BAD))
        self.assertEqual(contexts[2]["last_rejected_candidate"], self.SECOND_BAD)
        self.assertEqual(contexts[2]["last_rejected_evaluation"], self.bad_report(self.SECOND_BAD))
        self.assertEqual(contexts[2]["script_plain"], original)
        self.assertFalse(any(call.args[1] == self.SOURCE for call in self.grader.call_args_list))

    def long_turns(self):
        return [("A" if i % 2 == 0 else "B",
                 (f"Position {i + 1} concerns the copper plates beside the river. " * 5).strip())
                for i in range(4)]

    def answering_batches(self, defer_on=None):
        requested = []

        async def answer(prompt, **kwargs):
            call = self.round_builder.call_args
            turns = call.args[0]
            indices = call.kwargs.get("selected_indices")
            selected = list(range(len(turns))) if indices is None else list(indices)
            requested.append(selected)
            if len(requested) == defer_on:
                raise app.WritingDeferred("fixture admission full")
            return "\n".join(f"{turns[i][0] if indices is None else i + 1}: {self.raw_good_for(turns[i][1])}"
                             for i in selected)

        self.writer.side_effect = answer
        return requested

    async def first_pass(self, turns):
        source = "\n".join(f"{marker}: {text}" for marker, text in turns)
        return await app._crystal_round_first_pass(source, turns, "legacy armed context",
            self.WORLD, self.CHUNKS, [], "fixture-model")

    async def test_first_pass_uses_bounded_ordered_batches_instead_of_skipping_long_round(self):
        turns = self.long_turns()
        requested = self.answering_batches()
        rows = await self.first_pass(turns)
        self.planner.assert_called()
        self.assertGreater(len(requested), 1)
        self.assertEqual([i for batch in requested for i in batch], list(range(4)))
        self.assertEqual([row["marker"] for row in rows], [marker for marker, _ in turns])
        self.assertEqual([row["source"] for row in rows],
                         [hashlib.sha1(source.encode()).hexdigest() for _, source in turns])
        self.assertEqual([row["text"] for row in rows], [self.good_for(source) for _, source in turns])
        self.assertTrue(all(call.kwargs["limit"] <= self.settings["reply_max_chars"]
                            for call in self.writer.call_args_list))

    async def test_first_pass_deferral_keeps_completed_batch_and_pending_source_positions(self):
        turns = self.long_turns()
        requested = self.answering_batches(defer_on=2)
        with self.assertRaises(app.WritingDeferred) as caught:
            await self.first_pass(turns)
        rows = caught.exception.turns
        self.assertEqual(len(rows), len(turns))
        completed = set(requested[0])
        for i, ((marker, source), row) in enumerate(zip(turns, rows)):
            self.assertEqual(row["marker"], marker)
            self.assertEqual(row["source"], hashlib.sha1(source.encode()).hexdigest())
            self.assertEqual(row.get("text", ""), self.good_for(source) if i in completed else "")
            self.assertFalse(row.get("cut"), "Admission deferral is not an editorial cut")
        self.assertEqual(len(requested), 2)

    async def test_outer_round_deferral_retains_progress_and_resume_does_not_reask_completed_batch(self):
        turns = self.long_turns()
        original = "\n".join(f"{marker}: {source}" for marker, source in turns)
        first_requests = self.answering_batches(defer_on=2)
        held = await app.crystal_tint(original, "banter", [], critical=True)
        self.assertFalse(held["ok"])
        self.assertTrue(held["deferred"])
        self.assertEqual(held["script"], "")
        progress = held["progress"]
        self.assertEqual(progress["source"], hashlib.sha1(original.encode()).hexdigest())
        self.assertEqual(len(progress["turns"]), len(turns))
        completed = set(first_requests[0])
        self.assertEqual({i for i, row in enumerate(progress["turns"]) if row.get("text")}, completed)
        self.assertFalse(any(row.get("cut") for row in progress["turns"]))
        self.writer.reset_mock()
        resumed_requests = self.answering_batches()
        finished = await app.crystal_tint(original, "banter", [], critical=True,
                                          progress=copy.deepcopy(progress))
        self.assertTrue(finished["ok"], finished.get("why"))
        self.assertTrue(finished["coverage"]["met"])
        self.assertEqual([i for batch in resumed_requests for i in batch],
                         [i for i in range(len(turns)) if i not in completed])
        self.assertEqual([row["text"] for row in finished["progress"]["turns"]],
                         [self.good_for(source) for _, source in turns])

    async def test_resumed_batch_reasks_only_failed_positions_with_actual_evidence(self):
        turns = [("A", self.SOURCE), ("B", self.SOURCE), ("A", self.SOURCE)]
        rows = [{"marker": marker, "source": hashlib.sha1(source.encode()).hexdigest(),
                 "text": self.GOOD if i != 1 else "", "selected": True,
                 **({"rejected_candidate": self.BAD} if i == 1 else {})}
                for i, (marker, source) in enumerate(turns)]
        self.writer.side_effect = ["2: " + self.RAW_GOOD]
        repaired, did_write = await app._crystal_round_repass(turns, rows,
            "legacy marker instruction must not conflict", self.WORLD,
            self.CHUNKS, [], "fixture-model", kind="caller", passes=2)
        self.assertTrue(did_write)
        self.assertEqual(self.writer.await_count, 1)
        self.assertEqual(self.round_builder.call_args.kwargs["selected_indices"], [1])
        prompt = self.writer.call_args.args[0]
        self.assertIn(self.BAD, prompt)
        self.assertIn('"value":"12"', prompt)
        self.assertIn(" / ", prompt)
        self.assertEqual([row["text"] for row in repaired], [self.GOOD] * 3)
        self.writer.reset_mock()
        self.writer.side_effect = AssertionError("Accepted rows must not cost another model request")
        again, wrote_again = await app._crystal_round_repass(turns, repaired, "",
            self.WORLD, self.CHUNKS, [], "fixture-model", kind="caller", passes=2)
        self.writer.assert_not_awaited()
        self.assertFalse(wrote_again)
        self.assertEqual([row["text"] for row in again], [self.GOOD] * 3)

    async def test_caller_with_one_cut_and_ten_accepted_turns_is_still_incomplete(self):
        # Real parser and whole-call fidelity check: local per-turn successes
        # cannot conceal a missing conversational position.
        turns = [("A" if i % 2 == 0 else "C",
                  f"The caller reports copper plates at position {i + 1} before midnight.")
                 for i in range(11)]
        original = "\n".join(f"{marker}: {source}" for marker, source in turns)
        self.assertEqual(len(app.banter_turns(original)), 11)

        async def rewrite(source, *args, **kwargs):
            return self.BAD if source == turns[5][1] else self.good_for(source)

        with (mock.patch.object(app, "_crystal_round_first_pass", new=mock.AsyncMock(return_value=[])),
              mock.patch.object(app, "_crystal_round_repass", new=mock.AsyncMock(return_value=([], False))),
              mock.patch.object(app, "crystal_turn", side_effect=rewrite)):
            report = await app.crystal_tint(original, "caller", [], critical=True)
        self.assertEqual(report["coverage"]["accepted"], 10, report.get("why"))
        self.assertEqual(report["coverage"]["cut"], 1)
        self.assertFalse(report["coverage"]["met"])
        self.assertFalse(report["ok"])
        self.assertFalse(report["evaluation"]["ok"])
        progress = report["progress"]["turns"]
        self.assertEqual(len(progress), 11)
        self.assertEqual(progress[5]["rejected_candidate"], self.BAD)
        self.assertEqual(sum(bool(row.get("text")) for row in progress), 10)


if __name__ == "__main__":
    unittest.main()
