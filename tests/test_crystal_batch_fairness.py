"""Real rewrite wrappers yield bounded groups without losing saved wording.

Only model responses and station side effects are mocked. Tests share the
existing isolated fixture; builders, output planner, parser and wrappers run.
"""
import copy
import hashlib
import json
import unittest

import app
from crystal_contract import extract_contract
from tests import test_crystal_prompt_integration as integration


def evidence_rows(prompt):
    for line in prompt.splitlines():
        try:
            rows = json.loads(line)
        except ValueError:
            continue
        if isinstance(rows, list) and rows and isinstance(rows[0], dict) and "requested" in rows[0]:
            return rows
    raise AssertionError("Actual model request has no original-turn evidence")


class CrystalBatchFairnessTests(unittest.IsolatedAsyncioTestCase):
    # Reuse fixture setup without inheriting/discovering its unrelated tests.
    SOURCE = integration.CrystalPromptIntegrationTests.SOURCE
    RAW_GOOD = integration.CrystalPromptIntegrationTests.RAW_GOOD
    GOOD = integration.CrystalPromptIntegrationTests.GOOD
    BAD = integration.CrystalPromptIntegrationTests.BAD
    META = integration.CrystalPromptIntegrationTests.META
    WORLD = integration.CrystalPromptIntegrationTests.WORLD
    CHUNKS = integration.CrystalPromptIntegrationTests.CHUNKS
    INSTRUCTION = integration.CrystalPromptIntegrationTests.INSTRUCTION
    grade = integration.CrystalPromptIntegrationTests.grade
    answering_batches = integration.CrystalPromptIntegrationTests.answering_batches
    good_for = integration.CrystalPromptIntegrationTests.__dict__["good_for"]
    raw_good_for = integration.CrystalPromptIntegrationTests.__dict__["raw_good_for"]
    bad_report = integration.CrystalPromptIntegrationTests.__dict__["bad_report"]

    def setUp(self):
        integration.CrystalPromptIntegrationTests.setUp(self)
        self.settings["reply_max_chars"] = 6500
        app.crystal_prompt_contract.side_effect = extract_contract

    def short_turns(self):
        return [("A" if i % 2 == 0 else "B",
                 f"Mara cannot return the twelve copper plates before midnight at position {i + 1}.")
                for i in range(20)]

    async def first_pass(self, turns):
        source = "\n".join(f"{marker}: {text}" for marker, text in turns)
        armed = app.crystal_prompt_round(turns, self.WORLD, self.CHUNKS, .88, "caller")
        return await app._crystal_round_first_pass(source, turns, armed, self.WORLD,
                                                 self.CHUNKS, [], "fixture-model", kind="caller")

    def assert_group_evidence(self, turns, expected_indices):
        requested = []
        for call in self.writer.call_args_list:
            rows = evidence_rows(call.args[0])
            self.assertEqual([(row["speaker"], row["source"]) for row in rows], turns)
            selected = [row for row in rows if row["requested"]]
            # 2026-09-09: the CAP, not the number it happened to hold. The
            # invariant is that a group is bounded by the station's group
            # cap and the operator's reply budget, whichever is smaller -
            # pinning the literal made a tuning change look like a broken
            # contract.
            self.assertLessEqual(call.kwargs["limit"],
                                 min(app.CRYSTAL_GROUP_OUTPUT_CHARS,
                                     self.settings["reply_max_chars"]))
            self.assertEqual(call.kwargs["model"], "fixture-model")
            self.assertIn(self.WORLD, call.args[0])
            self.assertIn(self.CHUNKS[0]["text"], call.args[0])
            for row in selected:
                facts = row["source_contract"]
                source_contract = extract_contract(row["source"])
                self.assertEqual(facts["content_anchors"], source_contract["anchors"])
                self.assertEqual(facts["negation_to_retain"], source_contract["negations"])
                self.assertEqual(facts["quantities_to_retain"], source_contract["numbers"])
                self.assertEqual(facts["names_to_retain"], [
                    {"text": name["text"], "match": name["normalized"]}
                    for name in source_contract["names"]])
                requested.append(row["id"] - 1)
        self.assertEqual(requested, expected_indices)

    async def test_twenty_short_first_pass_turns_use_capped_groups_with_complete_facts(self):
        turns = self.short_turns()
        requested = self.answering_batches()
        rows = await self.first_pass(turns)
        self.assertGreater(len(requested), 1)
        self.assert_group_evidence(turns, list(range(20)))
        self.assertEqual([row["text"] for row in rows], [self.good_for(source) for _, source in turns])
        self.assertEqual([row["source"] for row in rows],
                         [hashlib.sha1(source.encode()).hexdigest() for _, source in turns])

    async def test_repair_groups_keep_full_failed_candidates_and_skip_accepted_positions(self):
        turns = self.short_turns()
        accepted = {0, 7, 18}
        candidates = {i: self.BAD + f" Failed position {i + 1}." for i in range(20)}
        original_rows = [{"marker": marker, "source": hashlib.sha1(source.encode()).hexdigest(),
                          "selected": True, "text": self.good_for(source) if i in accepted else "",
                          **({} if i in accepted else {"rejected_candidate": candidates[i]})}
                         for i, (marker, source) in enumerate(turns)]
        requested = self.answering_batches()
        repaired, wrote = await app._crystal_round_repass(turns, original_rows, "", self.WORLD,
            self.CHUNKS, [], "fixture-model", kind="caller", passes=1)
        self.assertTrue(wrote)
        self.assertGreater(len(requested), 1)
        self.assert_group_evidence(turns, [i for i in range(20) if i not in accepted])
        for call in self.writer.call_args_list:
            for row in evidence_rows(call.args[0]):
                if row["requested"]:
                    repair = row["rejected_attempt"]
                    self.assertEqual(repair["candidate"], candidates[row["id"] - 1])
                    self.assertEqual(repair["evaluation"]["semantic"]["missing_numbers"],
                                     [{"value": "12", "kind": "number"}])
                    self.assertFalse(repair["evaluation"]["semantic"]["negation"])
        self.assertEqual([row["text"] for row in repaired], [self.good_for(source) for _, source in turns])

    async def test_deferred_groups_resume_without_reasking_accepted_rows(self):
        turns = self.short_turns()
        original = "\n".join(f"{marker}: {source}" for marker, source in turns)
        first_requests = self.answering_batches(defer_on=2)
        held = await app.crystal_tint(original, "banter", [], critical=True)
        self.assertTrue(held.get("deferred"), held)
        self.assertFalse(held["ok"])
        progress = copy.deepcopy(held["progress"])
        accepted = set(first_requests[0])
        self.assertEqual({i for i, row in enumerate(progress["turns"]) if row.get("text")}, accepted)
        self.assertFalse(any(row.get("cut") for row in progress["turns"]))
        self.assertEqual(len(progress["turns"]), 20)
        self.writer.reset_mock()
        resumed = self.answering_batches()
        done = await app.crystal_tint(original, "banter", [], critical=True, progress=progress)
        self.assertTrue(done["ok"], done.get("why"))
        self.assertTrue(done["coverage"]["met"])
        self.assertEqual([i for batch in resumed for i in batch], [i for i in range(20) if i not in accepted])
        self.assert_group_evidence(turns, [i for i in range(20) if i not in accepted])

    async def test_oversized_repair_turn_keeps_full_user_ceiling_and_words(self):
        source = ("Mara cannot return twelve copper plates before midnight. " * 26).strip()
        turns = [("A", source), ("B", self.SOURCE)]
        failed = self.BAD + " Full retained failure. " * 50
        rows = [{"marker": "A", "source": hashlib.sha1(source.encode()).hexdigest(),
                 "text": "", "selected": True, "rejected_candidate": failed},
                {"marker": "B", "source": hashlib.sha1(self.SOURCE.encode()).hexdigest(),
                 "text": self.GOOD, "selected": True}]
        requested = self.answering_batches()
        result, wrote = await app._crystal_round_repass(turns, rows, "", self.WORLD,
            self.CHUNKS, [], "fixture-model", kind="caller", passes=1)
        self.assertTrue(wrote)
        self.assertEqual(requested, [[0]])
        self.assertEqual(self.writer.call_args.kwargs["limit"], 6500)
        evidence = evidence_rows(self.writer.call_args.args[0])
        self.assertEqual(evidence[0]["source"], source)
        self.assertEqual(evidence[0]["rejected_attempt"]["candidate"], failed)
        self.assertEqual(result[0]["text"], self.good_for(source))
        self.assertEqual(result[1]["text"], self.GOOD)

    async def test_oversized_first_pass_position_remains_pending_for_full_ceiling_repair(self):
        source = ("Mara cannot return twelve copper plates before midnight. " * 26).strip()
        turns = [("A", self.SOURCE), ("B", source), ("A", self.SOURCE)]
        requested = self.answering_batches()
        rows = await self.first_pass(turns)
        self.assertEqual([i for batch in requested for i in batch], [0, 2])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["text"], "")
        self.assertEqual(rows[1]["source"], hashlib.sha1(source.encode()).hexdigest())
        self.assertFalse(rows[1].get("cut"))
        self.writer.reset_mock()
        repairs = self.answering_batches()
        done, wrote = await app._crystal_round_repass(turns, rows, "", self.WORLD,
            self.CHUNKS, [], "fixture-model", kind="caller", passes=1)
        self.assertTrue(wrote)
        self.assertEqual(repairs, [[1]])
        self.assertEqual(self.writer.call_args.kwargs["limit"], 6500)
        self.assertEqual(evidence_rows(self.writer.call_args.args[0])[1]["source"], source)
        self.assertEqual([row["text"] for row in done], [self.good_for(text) for _, text in turns])

    async def test_lower_operator_ceiling_still_controls_every_group(self):
        self.settings["reply_max_chars"] = 800
        turns = self.short_turns()
        requested = self.answering_batches()
        await self.first_pass(turns)
        self.assertGreater(len(requested), 1)
        self.assert_group_evidence(turns, list(range(20)))


if __name__ == "__main__":
    unittest.main()
