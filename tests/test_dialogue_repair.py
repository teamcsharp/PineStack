"""Recovery completes plans without reassigning text or bypassing contracts."""
import copy
import unittest

import dialogue_repair as dr
import system3


class DialogueRepairTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = system3.default_config()
        self.settings = system3.normalise_settings({"mode": "active", "test_seed": "repair-test"})
        inputs = {"road": "banter", "seats": ["A", "B"], "names": {"A": "Dill", "B": "Skip"},
            "roles": {"A": "dj", "B": "cohost"}, "turns": 4,
            "subject": {"topic": "The gallery opens Friday.", "authority": "obligated", "sources": ["brief"]}}
        self.conv = system3.new_conversation(inputs, self.config, self.settings, conversation_id="repair")
        self.conv["turns"] = [{"turn_id": "repair:t%d" % i, "index": i, "speaker": seat,
            "name": inputs["names"][seat], "status": "planned", "text": "", "script_index": None,
            "step": "respond", "directions": ["Answer the preceding speaker."], "decisions": [],
            "mandatory_closing": i == 3}
            for i, seat in enumerate(["A", "B", "A", "B"])]
        self.variant = {"operation": "repair", "variation_id": "variation-one", "seed": "new-seed",
                        "pass": 1, "attempt": 1, "style_level": 0}

    @staticmethod
    def script(request):
        preserved = {row["turn_id"]: row["text"] for row in request["preserved_rows"]}
        return "\n".join("%s: %s" % (turn["speaker"], preserved.get(turn["turn_id"],
            "A focused response about the gallery, detail %d." % i))
            for i, turn in enumerate(request["planned_turns"]))

    async def recover(self, rows, writer=None, **options):
        calls = []
        async def generated(request):
            calls.append(copy.deepcopy(request))
            return writer(request) if writer else self.script(request)
        result = await dr.prepare_recovery(self.conv, self.config, rows, [], generated,
            self.variant, **options)
        return result, calls

    async def test_missing_tail_is_written_once_and_known_prefix_stays_identified(self):
        rows = [("A", "The gallery opens Friday."), ("B", "Who arranged the photographs?")]
        result, calls = await self.recover(rows)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result[:2], rows)
        self.assertEqual(len(result), 4)
        self.assertEqual([row["turn_id"] for row in calls[0]["preserved_rows"]], ["repair:t0", "repair:t1"])
        self.assertTrue(all(turn["status"] == "generated" for turn in self.conv["turns"]))

    async def test_mismatched_seat_never_moves_its_facts_to_a_planned_turn(self):
        result, calls = await self.recover([("A", "Opening fact."), ("A", "An ambiguous later fact.")])
        self.assertEqual([row["turn_id"] for row in calls[0]["preserved_rows"]], ["repair:t0"])
        self.assertEqual(calls[0]["source_rows"][1][1], "An ambiguous later fact.")
        self.assertNotEqual(result[1][1], "An ambiguous later fact.")

    async def test_middle_same_seat_drop_preserves_proven_survivor_identity(self):
        self.conv["turns"] = [dict(self.conv["turns"][0], turn_id="first", index=0, speaker="A"),
            dict(self.conv["turns"][1], turn_id="dropped", index=1, speaker="A", name="Dill"),
            dict(self.conv["turns"][2], turn_id="survivor", index=2, speaker="A"),
            dict(self.conv["turns"][3], turn_id="closing", index=3)]
        rows = [("A", "Opening fact."), ("A", "Exact later protected fact."), ("B", "Closing thought.")]
        result, calls = await self.recover(rows, protected_ids=["survivor"],
            source_turn_ids=["first", "survivor", "closing"])
        self.assertEqual(result[2], ("A", "Exact later protected fact."))
        self.assertNotEqual(result[1][1], "Exact later protected fact.")
        identified = {row["turn_id"]: row for row in calls[0]["preserved_rows"]}
        self.assertNotIn("dropped", identified)
        self.assertEqual(identified["survivor"]["index"], 2)
        self.assertTrue(identified["survivor"]["protected"])

    async def test_invalid_proven_source_mapping_refuses_without_guessing(self):
        for ids, rows in [(["repair:t2"], [("B", "Wrong speaker.")]),
                          (["repair:t2", "repair:t0"], [("A", "Later."), ("A", "First.")]),
                          (["repair:t0", "repair:t0"], [("A", "First."), ("A", "Duplicate.")]),
                          (["missing"], [("A", "Unplanned identity.")])]:
            with self.subTest(ids=ids):
                with self.assertRaisesRegex(ValueError, "proven recovery"):
                    await self.recover(rows, source_turn_ids=ids)

    async def test_writer_cannot_change_identified_prefix_or_protected_copy(self):
        for protected in [(), ("repair:t0",)]:
            with self.subTest(protected=protected):
                with self.assertRaisesRegex(ValueError, "immutable identified turn"):
                    await self.recover([("A", "Exact opening.")], writer=lambda request:
                        self.script(request).replace("Exact opening.", "Altered opening."), protected_ids=protected)

    async def test_stale_identity_remains_unassigned_source_evidence_in_fresh_operations(self):
        original = copy.deepcopy(self.conv)
        rows = [("A", "Opening fact."), ("A", "A fact from a removed old leg."),
                ("A", "Exact surviving copy."), ("B", "Closing fact.")]
        source_ids = ["repair:t0", "removed:old-leg", "repair:t2", "repair:t3"]
        for operation in ("rewrite", "reroll", "rebuild"):
            with self.subTest(operation=operation):
                self.conv = copy.deepcopy(original)
                self.variant["operation"] = operation
                result, calls = await self.recover(rows, source_turn_ids=source_ids,
                                                  protected_ids=["repair:t2"])
                self.assertEqual(len(calls), 1)
                request = calls[0]
                self.assertEqual(request["source_rows"], rows)
                preserved = {row["turn_id"]: row for row in request["preserved_rows"]}
                self.assertEqual(set(preserved), {"repair:t2"})
                self.assertEqual(result[preserved["repair:t2"]["index"]], rows[2])
                self.assertFalse(any(t["text"] == rows[1][1] for t in self.conv["turns"]))
                evidence = request["source_identity_evidence"]
                self.assertEqual(evidence["identified_source_turn_ids"], ["repair:t0", "repair:t2", "repair:t3"])
                self.assertEqual(evidence["unassigned_rows"], [{"source_index": 1,
                    "source_turn_id": "removed:old-leg", "speaker": "A"}])
                receipt = self.conv["dialogue_recovery_preparation"]
                self.assertEqual(receipt["source_identity_evidence"], evidence)
                self.assertEqual(receipt["original_rows"], rows)
                self.assertEqual(self.conv["subject"]["topic"], original["subject"]["topic"])
                self.assertEqual(self.conv["participants"], original["participants"])

    async def test_fresh_operations_keep_strict_source_vector_and_ownership_checks(self):
        original = copy.deepcopy(self.conv)
        invalid = [(["repair:t2", "old", "repair:t0"], [("A", "Later."), ("A", "Old."), ("A", "First.")]),
                   (["repair:t0", "old", "repair:t0"], [("A", "First."), ("A", "Old."), ("A", "Duplicate.")]),
                   (["old", "old"], [("A", "Old first."), ("A", "Old duplicate.")]),
                   (["repair:t0", "old"], [("B", "Wrong seat."), ("A", "Old.")]),
                   (["repair:t0", "old"], [("A", "Vector too short.")])]
        for operation in ("rewrite", "reroll", "rebuild"):
            for ids, rows in invalid:
                with self.subTest(operation=operation, ids=ids):
                    self.conv = copy.deepcopy(original)
                    self.variant["operation"] = operation
                    with self.assertRaisesRegex(ValueError, "proven recovery"):
                        await self.recover(rows, source_turn_ids=ids)

    async def test_repeated_absent_source_ids_remain_unassigned_without_prefix_guessing(self):
        original = copy.deepcopy(self.conv)
        rows = [("A", "Exact surviving copy."), ("A", "Unassigned earlier fact."),
                ("A", "Unassigned later fact."), ("B", "Closing fact.")]
        for absent in ("", None):
            for operation in ("rewrite", "reroll", "rebuild"):
                with self.subTest(absent=absent, operation=operation):
                    self.conv = copy.deepcopy(original)
                    self.variant["operation"] = operation
                    source_ids = ["repair:t2", absent, absent, "repair:t3"]
                    result, calls = await self.recover(rows, source_turn_ids=source_ids,
                                                      protected_ids=["repair:t2"])
                    request = calls[0]
                    self.assertEqual(request["source_rows"], rows)
                    fixed = request["preserved_rows"]
                    self.assertEqual([row["turn_id"] for row in fixed], ["repair:t2"])
                    self.assertEqual(result[fixed[0]["index"]], rows[0])
                    self.assertNotEqual(result[0], rows[0])
                    self.assertEqual(request["source_identity_evidence"]["unassigned_rows"], [
                        {"source_index": 1, "source_turn_id": "", "speaker": "A"},
                        {"source_index": 2, "source_turn_id": "", "speaker": "A"}])

    async def test_absent_same_seat_rows_cannot_identify_protected_copy_or_repair(self):
        rows = [("A", "Unknown first fact."), ("A", "Unknown second fact.")]
        for absent in ("", None):
            with self.subTest(absent=absent):
                self.variant["operation"] = "rewrite"
                with self.assertRaisesRegex(ValueError, "protected turn has no identified"):
                    await self.recover(rows, source_turn_ids=[absent, absent], protected_ids=["repair:t2"])
                self.variant["operation"] = "repair"
                with self.assertRaisesRegex(ValueError, "proven recovery"):
                    await self.recover(rows, source_turn_ids=[absent, absent])

    async def test_stale_same_seat_wording_cannot_supply_missing_protected_copy(self):
        self.variant["operation"] = "rewrite"
        with self.assertRaisesRegex(ValueError, "protected turn has no identified"):
            await self.recover([("A", "Words from a removed leg.")],
                               source_turn_ids=["removed"], protected_ids=["repair:t2"])

    async def test_stored_protected_copy_survives_stale_unassigned_source(self):
        self.variant["operation"] = "rewrite"
        self.conv["turns"][2]["text"] = "The gallery opens Friday."
        result, calls = await self.recover([("A", "Words from a removed leg.")],
            source_turn_ids=["removed"], protected_ids=["repair:t2"])
        self.assertEqual(result[2], ("A", "The gallery opens Friday."))
        self.assertEqual(calls[0]["source_rows"], [("A", "Words from a removed leg.")])

    async def test_unplanned_extra_rows_are_not_silently_discarded(self):
        with self.assertRaisesRegex(ValueError, "silently discard"):
            await self.recover([("A", "One.")] * 5)

    async def test_rewrite_can_recover_extra_rows_as_explicit_source_evidence(self):
        self.variant["operation"] = "rewrite"
        original = [("A", "A source fact %d." % index) for index in range(5)]
        result, calls = await self.recover(original)
        self.assertEqual(len(result), 4)
        self.assertEqual(calls[0]["source_rows"], original)
        self.assertEqual(self.conv["dialogue_recovery_preparation"]["original_rows"], original)

    async def test_protected_missing_identity_refuses_before_model_work(self):
        with self.assertRaisesRegex(ValueError, "protected turn has no identified"):
            await self.recover([("A", "First.")], protected_ids=["repair:t3"])

    async def test_full_aligned_rejection_repairs_mutable_rows(self):
        result, calls = await self.recover([("A", "First."), ("B", "Second."), ("A", "Third."), ("B", "Last.")],
            protected_ids=["repair:t0"])
        self.assertEqual(result[0], ("A", "First."))
        self.assertEqual([row["turn_id"] for row in calls[0]["preserved_rows"]], ["repair:t0"])

    async def test_rebuild_preserves_speaker_identity_and_required_landing(self):
        self.variant.update(operation="rebuild", style_level=2)
        before = copy.deepcopy(self.conv)
        result, calls = await self.recover([("A", "Exact sponsor opening.")], protected_ids=["repair:t0"])
        self.assertEqual(self.conv["participants"], before["participants"])
        self.assertEqual(self.conv["identity"]["conversation_id"], "repair")
        self.assertEqual(self.conv["identity"]["trace_id"], before["identity"]["trace_id"])
        self.assertEqual(self.conv["identity"]["revision"], 2)
        self.assertEqual(self.conv["turns"][-1]["turn_id"], "repair:t3")
        self.assertTrue(self.conv["turns"][-1]["mandatory_closing"])
        self.assertEqual(result[0], ("A", "Exact sponsor opening."))
        self.assertEqual(self.conv["subject"]["topic"], before["subject"]["topic"])
        self.assertEqual(len(calls), 1)

    async def test_rebuild_refuses_recorded_or_committed_dialogue(self):
        self.variant["operation"] = "rebuild"
        self.conv["lines"] = [{"id": "recorded"}]
        with self.assertRaisesRegex(ValueError, "recorded or committed"):
            await self.recover([])
        self.conv.pop("lines")
        self.conv["chapter_state"] = {"state": "in_flight"}
        with self.assertRaisesRegex(ValueError, "recorded or committed"):
            await self.recover([])

    async def test_bound_unrecorded_draft_is_reopened_with_ancestry(self):
        self.conv["bindings"] = [{"turn_id": "repair:t0", "draft": "old"}]
        _result, _calls = await self.recover([])
        self.assertEqual(self.conv["bindings"], [])
        self.assertEqual(self.conv["dialogue_recovery_unbound"], [{"turn_id": "repair:t0", "draft": "old"}])

    async def test_rebuild_new_ids_never_alias_prior_turns_or_events(self):
        self.variant["operation"] = "rebuild"
        self.conv["decision_events"] = [{"event_id": "repair:0000", "seq": 0, "meta": {}}]
        _result, _calls = await self.recover([])
        events = self.conv["decision_events"]
        self.assertEqual(len({event["event_id"] for event in events}), len(events))
        self.assertEqual([event["seq"] for event in events], list(range(len(events))))
        fresh = [turn for turn in self.conv["turns"] if turn["turn_id"] != "repair:t3"]
        self.assertTrue(all(turn["turn_id"].startswith("repair:recovery:r2:") for turn in fresh))
        self.assertTrue(all(event["conversation_id"] == "repair" for event in events[1:]))

    async def test_topic_randomness_applies_only_to_free_ungrounded_banter(self):
        self.variant["operation"] = "reroll"
        self.conv["subject"].update(authority="free", sources=[])
        result, _calls = await self.recover([])
        self.assertIn(self.conv["subject"]["topic"], dr.FREE_TOPICS)
        self.assertFalse(self.conv["dialogue_recovery_variant"]["topic"]["premise_preserved"])
        self.assertEqual(len(result), 4)

    def test_parser_refuses_wrong_order_missing_rows_and_explanatory_text(self):
        for script in ("A: First.\nB: Second.",
                       "B: Wrong.\nA: Order.\nA: Third.\nB: Last.",
                       "Here is your script:\nA: First.\nB: Second.\nA: Third.\nB: Last."):
            with self.subTest(script=script):
                with self.assertRaises(ValueError):
                    dr.parse_exchange(script, self.conv["turns"])


if __name__ == "__main__":
    unittest.main()
