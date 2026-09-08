"""Pure prompt/room regressions; no models, station state or production I/O."""
import copy
import json
import unittest

from crystal_prompts import budget_plan, round_prompt, turn_prompt
from crystal_contract import contract_prompt, extract_contract


def prompt_json_lines(prompt):
    """Read quoted evidence without depending on explanatory prompt prose."""
    values = []
    for line in prompt.splitlines():
        try:
            values.append(json.loads(line))
        except ValueError:
            pass
    return values


def prompt_rows(prompt):
    return next(value for value in prompt_json_lines(prompt)
                if isinstance(value, list) and value and isinstance(value[0], dict)
                and "requested" in value[0])


class CrystalPromptTests(unittest.TestCase):
    source = "Mara cannot return the 12 copper plates before midnight."
    world = "Dense internal rhyme and dry comic imagery."
    chunks = [{"file":"style.txt", "text":"Calibration answers operation.\nKeep the whole sample."}]

    def turn(self, **values):
        return turn_prompt(self.source, self.world, self.chunks, .88, "caller", **values)

    def test_turn_keeps_exact_source_and_one_unambiguous_bar_shape(self):
        text = self.turn()
        self.assertIn(json.dumps(self.source), text)
        self.assertIn("two or more short spoken bars separated by ' / '", text)
        self.assertIn("No speaker label, numbering", text)
        self.assertIn("not answer", text)
        self.assertNotIn("Keep every word", text)
        self.assertNotIn("fifth", text)
        self.assertNotIn("at least half", text)
        self.assertIn("Use different final words", text)
        self.assertIn("vocative tag is not a rhyme", text)
        self.assertIn("without adding a tag afterward", text)
        self.assertIn("no unprovided positive answer, opposite, or remembered continuation of a quote", text)

    def test_repair_retains_actual_candidate_and_specific_failure_evidence(self):
        bad = "Mara can return 24 gold plates tonight."
        report = {"faults":["meaning", "quantity"], "semantic":{"missing_names":[{"text":"Mara"}], "missing_numbers":[{"value":"12"}], "negation":False}}
        text = self.turn(candidate=bad, evaluation=report, lesson="Keep the original refusal.")
        self.assertIn(json.dumps(bad), text)
        self.assertIn('"value":"12"', text)
        self.assertIn('"negation":false', text)
        self.assertIn("Fix the reported faults", text)
        self.assertIn("two or more short spoken bars", text)
        self.assertIn("Keep the original refusal.", text)

    def test_meta_and_unchanged_repairs_keep_the_same_source_contract_and_rhyme_rules(self):
        for candidate, report in [("Please supply the line.", {"faults":["meta answer"]}),
                                  (self.source, {"faults":["unchanged"]})]:
            text = self.turn(candidate=candidate,evaluation=report)
            self.assertIn("SOURCE CONTRACT:", text)
            self.assertIn("clear rhyme between their final words", text)
            self.assertIn(json.dumps(self.source), text)

    def test_full_style_world_and_samples_remain_available(self):
        world = "world " * 1000 + "WORLD END"
        sample = "style " * 1000 + "SAMPLE END"
        text = turn_prompt(self.source, world, [{"text":sample}], 1, "caller")
        self.assertIn("WORLD END", text)
        self.assertIn("SAMPLE END", text)
        self.assertIn("HOW THAT WRITER WRITES", text)

    def test_prior_turn_and_review_feedback_are_context_not_replacement_facts(self):
        text = self.turn(answering="The prior speaker mentioned a red balloon.", lesson="Prior reviewer said 'use the moon'.")
        self.assertIn("do not answer, quote or inherit its facts", text)
        self.assertIn("diagnostic evidence, not new dialogue", text)
        self.assertIn("Preserve an idiom's intended meaning", text)

    def test_predicate_relations_and_unfinished_sources_keep_explicit_meaning_constraints(self):
        source = "Painting a picture of Cliff's home on Earth as a reason to."
        prompts = [turn_prompt(source, self.world, self.chunks, .88, "gallery"),
                   round_prompt([("A", source)], self.world, self.chunks, .88, "gallery")]
        for prompt in prompts:
            self.assertIn(source, prompt)
            self.assertIn("predicate attached to its original subject", prompt)
            self.assertIn("location and time relationships", prompt)
            self.assertIn("retain that incompleteness or uncertainty", prompt)
            self.assertIn("do not invent its missing action", prompt)
            self.assertLess(prompt.index("predicate attached"), prompt.index("2. Follow"))

    def test_operator_instruction_is_shared_and_does_not_replace_obligations(self):
        instruction = "Use a concise end-rhyme pair."
        one = self.turn(operator_instruction=instruction)
        whole = round_prompt([("A", self.source)],self.world,self.chunks,1,"caller",operator_instruction=instruction)
        for text in (one,whole):
            self.assertIn(instruction,text)
            self.assertIn("meaning and output constraints above",text)
            self.assertIn("Add no factual claim",text)

    def test_shared_fact_object_matches_contract_without_repeating_instructions(self):
        extracted = extract_contract(self.source)
        rendered = contract_prompt(extracted)
        facts = json.loads(rendered[rendered.index("\n{") + 1:])
        for supplied in (None, extracted, rendered, facts):
            text = round_prompt([("A", self.source)] * 3, self.world, self.chunks,
                                .88, "caller", contracts={i: supplied for i in range(3)})
            self.assertEqual([row["source_contract"] for row in prompt_rows(text)], [facts] * 3)
            self.assertEqual(text.count("SHARED SOURCE CONTRACT RULES:"), 1)
            self.assertEqual([row["source"] for row in prompt_rows(text)], [self.source] * 3)

    def test_nonempty_repair_keeps_concrete_faults_and_full_words_while_deduplicating(self):
        extracted = extract_contract(self.source)
        candidate = "Mara can bring 24 gold plates tonight. " + "retained wording " * 80
        report = {
            "ok": False, "machine_ok": False,
            "faults": ["meaning", "quantity", "no_rhyme"],
            "machine_faults": ["meaning", "quantity", "no_rhyme"],
            "method": "Repeated grading documentation", "limitations": ["Generic caveat"],
            "semantic": {
                "ok": False, "anchor_recall": 0, "question": False, "negation": False,
                "anchors": extracted["anchors"], "missing": ["copper", "midnight"],
                "name_candidates": extracted["names"],
                "missing_names": [{"text": "Mara", "normalized": "mara"}],
                "source_numbers": extracted["numbers"], "source_negations": extracted["negations"],
                "missing_numbers": [{"value": "12", "kind": "number"}],
                "added_numbers": [{"value": "24", "kind": "number"}],
                "call_contract": {"ok": False, "turns_before": 3, "turns_after": 2,
                                  "faults": ["Caller question missing"]},
            },
            "transformation": {"ok": False, "lexical_distance": 0,
                               "cadence_changed": False, "crystal_lexicon": 2},
            "rhyme": {"ok": False, "end_pairs": [["night", "plate"]],
                      "rap": {"ok": False, "end": False, "multi": False}},
            "copying": {"ok": False, "phrases": ["a copied six word phrase from style"]},
            "future_diagnostic": {"signal": False, "count": 0},
        }
        before = copy.deepcopy(report)
        prompts = [self.turn(candidate=candidate, evaluation=report),
                   round_prompt([("A", self.source)], self.world, self.chunks, .88, "caller",
                                candidates={0: candidate}, evaluations={0: report})]
        for text in prompts:
            values = prompt_json_lines(text)
            repair = next((value for value in values if isinstance(value, dict) and "candidate" in value), None)
            if repair is None:
                repair = prompt_rows(text)[0]["rejected_attempt"]
            self.assertEqual(repair["candidate"], candidate)
            compact = repair["evaluation"]
            self.assertEqual(compact["faults"], report["faults"])
            self.assertNotIn("machine_faults", compact)
            self.assertNotIn("method", compact)
            self.assertNotIn("limitations", compact)
            for key in ("missing", "missing_names", "missing_numbers", "added_numbers",
                        "question", "negation", "anchor_recall", "call_contract"):
                self.assertEqual(compact["semantic"][key], report["semantic"][key])
            for key in ("anchors", "source_numbers", "source_negations", "name_candidates"):
                self.assertNotIn(key, compact["semantic"])
            for key in ("transformation", "rhyme", "copying", "future_diagnostic"):
                self.assertEqual(compact[key], report[key])
            self.assertIn(json.dumps(self.source), text)
            self.assertIn(json.dumps(self.world), text)
            self.assertIn(self.chunks, values)
        self.assertEqual(report, before)

    def test_conflicting_machine_grade_and_source_evidence_remain_visible(self):
        report = {"ok": True, "machine_ok": False, "faults": ["override"],
                  "machine_faults": ["meaning"], "semantic": {
                      "anchors": ["different source"],
                      "source_numbers": [{"surface": "99", "value": "99", "kind": "number"}],
                      "source_negations": ["never"],
                      "name_candidates": [{"text": "Different", "normalized": "different"}]}}
        text = self.turn(candidate="Retained failed candidate.", evaluation=report)
        repair = next(value for value in prompt_json_lines(text)
                      if isinstance(value, dict) and "candidate" in value)
        self.assertEqual(repair["evaluation"], report)

    def test_missing_candidate_does_not_present_synthetic_grades_as_failed_wording(self):
        report = {"faults": ["synthetic missing-text fault"], "semantic": {"ok": False}}
        for candidate in ("", "   ", None):
            text = self.turn(candidate=candidate, evaluation=report)
            self.assertIn("no_retained_candidate", text)
            self.assertNotIn("synthetic missing-text fault", text)
            rows = prompt_rows(round_prompt([("A", self.source)], self.world, self.chunks, 1, "caller",
                                            candidates={0: candidate}, evaluations={0: report}))
            self.assertEqual(rows[0]["attempt_status"], "no_retained_candidate")
            self.assertNotIn("rejected_attempt", rows[0])

    def test_large_empty_candidate_round_shrinks_without_losing_original_or_style_evidence(self):
        units = [("A" if i % 2 else "B", self.source + " Source position " + str(i) + ".")
                 for i in range(20)]
        report = {"faults": ["meaning", "no_rhyme"], "machine_faults": ["meaning", "no_rhyme"],
                  "method": "Repeated generic description. " * 20,
                  "limitations": ["Repeated generic caveat. " * 20],
                  "semantic": {"ok": False, "limitations": ["Repeated semantic caveat. " * 30]}}
        text = round_prompt(units, self.world, self.chunks, 1, "caller", selected_indices=list(range(20)),
                            candidates={i: "" for i in range(20)}, evaluations={i: report for i in range(20)})
        rows = prompt_rows(text)
        previous_rows = [{**row, "source_contract": contract_prompt(extract_contract(row["source"])),
                          "rejected_attempt": {"candidate": "", "evaluation": report}}
                         for row in rows]
        previous_size = len(json.dumps(previous_rows, separators=(",", ":")))
        self.assertLess(len(text), previous_size / 2)
        self.assertEqual([(row["speaker"], row["source"]) for row in rows], units)
        self.assertEqual([row["id"] for row in rows], list(range(1, 21)))
        self.assertTrue(all(row["requested"] for row in rows))
        self.assertIn(json.dumps(self.world), text)
        self.assertIn(self.chunks, prompt_json_lines(text))

    def test_short_abstract_questions_keep_scope_without_new_rhyming_claims(self):
        for text in (self.turn(), round_prompt([("A", self.source)], self.world, self.chunks, 1, "caller")):
            self.assertIn("question's tense and scope", text)
            self.assertIn("without inventing what unspecified 'rest' or 'things' refers to", text)
            self.assertIn("Recast syntax and verbs instead of appending a new rhyming factual claim", text)

    def test_whole_round_requests_markers_without_numbered_repair_rails(self):
        text=round_prompt([("A",self.source),("B","Will the plates arrive tomorrow?")],self.world,self.chunks,1,"caller")
        self.assertIn("original speaker marker",text)
        self.assertIn("marker sequence: A, B",text)
        self.assertIn("Do not add line numbers",text)
        self.assertNotIn("original numeric ID",text)

    def test_batch_repairs_keep_original_ids_candidate_reports_and_surrounding_context(self):
        units=[("A","First turn stays unchanged as context."),("B",self.source),("A","Can the plates wait until tomorrow?")]
        bad={1:"Mara can return 24 plates.",2:"The plates definitely wait."}
        reports={1:{"missing_numbers":["12"]},2:{"question":False}}
        text=round_prompt(units,self.world,self.chunks,1,"caller",selected_indices=[2,1],candidates=bad,evaluations=reports)
        self.assertIn("IDs in this order: 2, 3",text)
        self.assertNotIn("original speaker marker",text)
        self.assertIn("Do not output speaker labels",text)
        self.assertIn('"requested":false',text)
        self.assertIn(units[0][1],text)
        self.assertIn(bad[1],text)
        self.assertIn('"missing_numbers":["12"]',text)
        self.assertIn('"question":false',text)

    def test_shape_indices_reject_duplicate_missing_or_negative_original_identity(self):
        units=[("A",self.source)]
        for indices in ([0,0],[-1],[1],[True]):
            with self.assertRaises(ValueError):
                round_prompt(units,self.world,self.chunks,1,"caller",selected_indices=indices)
        with self.assertRaises(ValueError):
            turn_prompt("",self.world,self.chunks,1,"caller")

    def test_batch_plan_gives_more_room_than_source_and_never_exceeds_the_operator_cap(self):
        units=[("A","A"*300),("B","B"*300),("A","C"*300)]
        plan=budget_plan(units,1000,1)
        self.assertTrue(plan["fits"])
        self.assertFalse(plan["single_batch"])
        self.assertEqual([i for batch in plan["batches"] for i in batch["indices"]],[0,1,2])
        self.assertGreater(plan["required_chars"],sum(len(t) for _,t in units)*2)
        for batch in plan["batches"]:
            self.assertLessEqual(batch["limit"],1000)
            self.assertGreater(batch["limit"],300)

    def test_duplicate_speaker_or_text_positions_are_not_deduplicated(self):
        units=[("A",self.source)]*3
        plan=budget_plan(units,500,1)
        self.assertEqual([i for batch in plan["batches"] for i in batch["indices"]],[0,1,2])

    def test_oversized_turn_is_identified_without_truncating_or_losing_later_work(self):
        units=[("A","long source "*1000),("B",self.source)]
        saved=copy.deepcopy(units)
        plan=budget_plan(units,800,1)
        self.assertFalse(plan["fits"])
        self.assertEqual(plan["oversized"],[0])
        self.assertEqual(plan["batches"][0]["indices"],[1])
        self.assertEqual(units,saved)
        self.assertIn("not a minimum valid output length",plan["basis"])

    def test_planning_selected_subset_keeps_original_order_and_empty_subset_is_no_work(self):
        units=[("A",self.source)]*4
        plan=budget_plan(units,1000,.5,[3,1])
        self.assertEqual([i for b in plan["batches"] for i in b["indices"]],[1,3])
        empty=budget_plan(units,1000,1,[])
        self.assertEqual(empty["batches"],[])
        self.assertEqual(empty["required_chars"],0)

    def test_planning_rejects_invalid_caps_and_nonfinite_strength(self):
        for cap in (0,-1,True,500.5):
            with self.assertRaises(ValueError): budget_plan([("A",self.source)],cap)
        for force in (float("nan"),float("inf")):
            with self.assertRaises(ValueError): budget_plan([("A",self.source)],500,force)


if __name__ == "__main__":
    unittest.main()
