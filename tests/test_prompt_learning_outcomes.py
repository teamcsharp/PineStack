import copy
import json
import unittest
from unittest import mock

from prompt_learning import PromptLearningConflictError, _patterns
from tests import test_prompt_learning as fixtures


class PromptLearningOutcomeTests(unittest.TestCase):
    setUp = fixtures.PromptLearningTests.setUp
    row = fixtures.PromptLearningTests.row
    enable = fixtures.PromptLearningTests.enable
    seed = fixtures.PromptLearningTests.seed

    def measured(self, i, version=1, *, ok=False, semantic=True, model="gemma4:31b", **changes):
        row = {"attempt_id": f"request-{version}-{i}:0", "source": f"The station keeps source number {i}.",
            "candidate": f"Candidate words for attempt {version} number {i}.",
            "parent": f"Whole parent {i // 2}", "kind": "gallery", "model": model,
            "profile": "force88-crystal-a-fluid-contract1", "prompt_version": 3,
            "grader_version": 5, "contract_version": 1, "learning_revision": self.store.settings()["revision"],
            "strategy_ids": [f"gallery:quantities:v{version}"], "stage": "first", "prior_attempt_id": "",
            "machine_ok": ok, "effective_ok": ok, "semantic_ok": semantic, "rhyme_ok": True,
            "faults": [] if ok else ["quantities"]}
        row.update(changes)
        return row

    def warm(self):
        self.enable()
        self.seed()

    def test_each_supported_kind_gets_guidance_despite_full_legacy_twelve_slots(self):
        self.enable()
        for n, kind in enumerate(("gallery", "caller", "ad", "manager", "banter", "track_talk", "news", "sfxguy")):
            for i in range(3):
                row = self.row(n * 10 + i, kind=kind)
                row["evaluation"]["semantic"].update(missing_names=["Mara"], negation=False, question=False)
                self.store.observe(row)
        self.assertGreater(len(self.store.status()["hints"]), 12)
        for kind in ("news", "sfxguy", "gallery", "caller"):
            selection = self.store.selection(kind)
            self.assertTrue(selection["guidance"])
            self.assertLessEqual(len(selection["guidance"]), 1000)
            self.assertLessEqual(len(selection["strategy_ids"]), 4)
            self.assertTrue(all(s.startswith(kind + ":") for s in selection["strategy_ids"]))

    def test_new_current_failure_families_replace_older_source_votes(self):
        self.warm()
        for i in range(3):
            row = self.row(i)
            row.update(id=f"new-{i}", event_seq=100 + i)
            row["evaluation"] = {"version": 5, "machine_ok": False,
                "rhyme": {"required": True, "rap": {"ok": False}}}
            self.store.observe(row)
        self.assertEqual([r["pattern"] for r in self.store.status()["hints"]], ["rhyme"])

    def test_stronger_current_pattern_can_replace_a_full_incumbent_kind(self):
        self.enable()
        for i in range(3):
            row = self.row(i)
            row["evaluation"]["semantic"].update(missing_names=["Mara"], negation=False, question=False)
            self.store.observe(row)
        self.assertEqual(len(self.store.selection("gallery")["strategy_ids"]), 4)
        for i in range(20, 40):
            row = self.row(i, evaluation={"version": 5, "machine_ok": False,
                "rhyme": {"required": True, "rap": {"ok": False}}})
            self.store.observe(row)
        self.assertIn("gallery:rhyme:v1", self.store.selection("gallery")["strategy_ids"])
        self.assertEqual(len(self.store.selection("gallery")["strategy_ids"]), 4)

    def test_actual_attempts_are_idempotent_and_readers_never_open_storage(self):
        self.warm()
        row = self.measured(0)
        self.assertTrue(self.store.outcome(row)["recorded"])
        revision = self.store.settings()["revision"]
        self.assertFalse(self.store.outcome(row)["recorded"])
        self.assertEqual(self.store.settings()["revision"], revision)
        changed = {**row, "effective_ok": True}
        with self.assertRaises(PromptLearningConflictError):
            self.store.outcome(changed)
        with self.assertRaises(PromptLearningConflictError):
            self.store.outcome({**row, "candidate": "Different actual wording, identical grades."})
        with mock.patch.object(self.store, "_connect", side_effect=AssertionError("read writes")):
            self.assertTrue(self.store.selection("gallery")["guidance"])
            self.assertEqual(self.store.status()["outcomes"]["observations"], 1)

    def test_only_distinct_comparable_production_sources_can_start_an_exploration(self):
        self.warm()
        for flag in ("technical", "deferred", "preview", "regrade", "imported"):
            self.assertFalse(self.store.outcome(self.measured(0, **{flag: True}))["recorded"])
        for i in range(9):
            self.store.outcome(self.measured(i, model="unknown"))
        self.assertTrue(self.store.selection("gallery")["strategy_ids"][0].endswith(":v1"))
        for i in range(7):
            self.store.outcome(self.measured(i + 20))
        self.assertTrue(self.store.selection("gallery")["strategy_ids"][0].endswith(":v1"))
        self.store.outcome(self.measured(27))
        self.assertTrue(self.store.selection("gallery")["strategy_ids"][0].endswith(":v2"))
        hint = self.store.status()["hints"][0]
        self.assertEqual(hint["phase"], "exploring")
        self.assertIn("unproven", hint["recipe_reason"])

    def test_comparable_improvement_is_supported_without_factual_or_rhyme_regression(self):
        self.warm()
        for i in range(8):
            self.store.outcome(self.measured(i))
        revision = self.store.settings()["revision"]
        for i in range(8):
            self.store.outcome(self.measured(20 + i, version=2, ok=True))
        self.assertEqual(self.store.settings()["revision"], revision)  # words did not change
        hint = self.store.status()["hints"][0]
        self.assertEqual(hint["phase"], "supported")
        self.assertIn("not causal proof", hint["recipe_reason"])
        self.assertEqual(len(self.store.status()["outcomes"]["cohorts"]), 2)

    def test_repeated_attempts_of_one_source_do_not_become_eight_independent_exposures(self):
        self.warm()
        for i in range(20):
            row = self.measured(i, source="The same short source.", parent="The same original parent.")
            self.store.outcome(row)
        self.assertEqual(self.store.status()["outcomes"]["cohorts"][0]["sources"], 1)
        self.assertTrue(self.store.selection("gallery")["strategy_ids"][0].endswith(":v1"))

    def test_recipe_with_better_effective_rate_but_more_factual_failures_is_not_supported(self):
        self.warm()
        for i in range(8):
            self.store.outcome(self.measured(i))
        for i in range(16):
            self.store.outcome(self.measured(i + 20, version=2, ok=True, semantic=False))
        self.assertNotEqual(self.store.status()["hints"][0]["phase"], "supported")
        self.assertTrue(self.store.selection("gallery")["strategy_ids"][0].endswith(":v3"))

    def test_failed_variants_exhaust_once_and_do_not_loop_back_or_waive_requirements(self):
        self.warm()
        for version in (1, 2, 3):
            for i in range(8):
                self.store.outcome(self.measured(i + version * 20, version=version))
        self.assertEqual(self.store.status()["hints"][0]["phase"], "exhausted")
        self.assertEqual(self.store.selection("gallery")["strategy_ids"], [])
        mode = self.store.settings()["mode"]
        revision = self.store.settings()["revision"]
        self.store.outcome(self.measured(120, version=3))
        self.assertEqual(self.store.settings()["revision"], revision)
        self.assertEqual(self.store.settings()["mode"], mode)

    def test_exhaustion_survives_outcome_retention_hint_eviction_and_restart(self):
        self.warm()
        for version in (1, 2, 3):
            for i in range(8):
                self.store.outcome(self.measured(i + version * 20, version=version))
        with mock.patch("prompt_learning.OUTCOME_WINDOW", 8):
            for i in range(120, 130):
                self.store.outcome(self.measured(i, version=3, model="unknown"))
        for i in range(3):
            row = self.row(i, id=f"later-{i}", event_seq=200 + i,
                evaluation={"version": 5, "machine_ok": False,
                            "rhyme": {"required": True, "rap": {"ok": False}}})
            self.store.observe(row)
        self.assertNotIn("gallery:quantities", [r["id"] for r in self.store.status()["hints"]])
        self.store = fixtures.PromptLearningStore(self.path, now=lambda: self.clock + 1)
        for i in range(300, 303):
            self.store.observe(self.row(i))
        hint = next(r for r in self.store.status()["hints"] if r["id"] == "gallery:quantities")
        self.assertEqual(hint["phase"], "exhausted")
        self.assertNotIn("gallery:quantities:v1", self.store.selection("gallery")["strategy_ids"])

    def test_all_attempt_counts_include_successes_without_a_selected_strategy(self):
        first = self.measured(0, strategy_ids=[], ok=True)
        self.store.outcome(first)
        self.store.outcome(self.measured(1, strategy_ids=[], stage="repair", semantic=False))
        totals = self.store.status()["outcomes"]["measured_attempts"]
        self.assertEqual(totals["all"]["attempts"], 2)
        self.assertEqual(totals["all"]["without_strategy"], 2)
        self.assertEqual(totals["first"]["raw_passes"], 1)
        self.assertEqual(totals["repair"]["semantic_failures"], 1)
        self.assertEqual(self.store.status()["outcomes"]["cohorts"], [])

    def test_outcome_reuses_only_its_own_transaction_aggregates(self):
        self.warm()
        with mock.patch.object(self.store, "_outcomes", wraps=self.store._outcomes) as outcomes, mock.patch.object(
                self.store, "_summarize", wraps=self.store._summarize) as evidence:
            self.store.outcome(self.measured(0))
            self.assertEqual(outcomes.call_count, 1)
            self.assertEqual(evidence.call_count, 1)
            self.assertEqual(self.store.status()["outcomes"]["observations"], 1)
            self.store.outcome(self.measured(1, ok=True))
            self.assertEqual(outcomes.call_count, 2)
            self.assertEqual(evidence.call_count, 2)
            self.assertEqual(self.store.status()["outcomes"]["observations"], 2)
            self.assertEqual(self.store.status()["outcomes"]["measured_attempts"]["all"]["raw_passes"], 1)

    def test_decoding_cache_rechecks_actual_database_body_and_retention(self):
        self.warm()
        self.store.outcome(self.measured(0))
        with self.store._connect() as db:
            row = json.loads(db.execute("SELECT body FROM prompt_outcomes").fetchone()[0])
            row.update(machine_ok=True, effective_ok=True, faults=[])
            db.execute("UPDATE prompt_outcomes SET body=?", (json.dumps(row),))
        # Simulate an external exact-store maintenance change; cached decoding
        # must not override a fresh SQLite snapshot even at the same sequence.
        self.store.outcome(self.measured(1))
        self.assertEqual(self.store.status()["outcomes"]["measured_attempts"]["all"]["raw_passes"], 1)
        with mock.patch("prompt_learning.OUTCOME_WINDOW", 1):
            self.store.outcome(self.measured(2))
            self.assertEqual(len(self.store._outcome_decode_cache), 1)
            self.assertEqual(self.store.status()["outcomes"]["measured_attempts"]["all"]["raw_passes"], 0)

    def test_meaning_grade_does_not_learn_from_advisory_spelling_rhyme_failure(self):
        report = {"grade": "meaning", "machine_ok": True,
                  "rhyme": {"required": True, "ok": False, "rap": {"ok": True}}}
        self.assertNotIn("rhyme", _patterns(report))
        report["machine_ok"] = False  # some unrelated actual style failure
        report["transformation"] = {"ok": False, "cadence_changed": False}
        self.assertEqual(_patterns(report), ["cadence"])
        report["grade"] = "strict"
        self.assertIn("rhyme", _patterns(report))
        report["rhyme"].update(ok=True, rap={"ok": False})
        report["editorial"] = {"mode": "fluid"}
        self.assertIn("rhyme", _patterns(report))

    def test_only_explicit_factual_guard_codes_become_anchor_failures(self):
        report = {"machine_ok": True, "semantic": {"ok": True}, "editorial": {
            "ok": False, "guard_evidence": [{"code": "attempt_became_asserted_action",
                "source_quote": "try to carry", "candidate_quote": "we carry"}]}}
        self.assertEqual(_patterns(report), ["anchors"])
        report["editorial"]["guard_evidence"] = [{"code": "source_needs_repair"}]
        self.assertEqual(_patterns(report), ["anchors"])
        report["editorial"] = {"ok": True, "advisory_faults": ["rhetoric was not materially transformed"],
            "guard_evidence": [{"code": "style_changed"}, "attempt_became_asserted_action"]}
        self.assertEqual(_patterns(report), [])

    def test_measured_unsupported_positive_contrast_is_an_anchor_failure(self):
        report = {"semantic": {"ok": False, "contrast": False,
            "unsupported_positive_contrasts": [{"form": "but_nominal", "focus": "how we act",
                "source_negative": "not our abilities that show", "unsupported_terms": ["act"]}]}}
        self.assertEqual(_patterns(report), ["anchors"])
        report["semantic"]["contrast"] = True
        self.assertEqual(_patterns(report), [])
        report["semantic"].update(contrast=False, unsupported_positive_contrasts=[])
        self.assertEqual(_patterns(report), [])
        self.assertEqual(_patterns({"faults": ["unsupported positive contrast, but how we act"]}), [])

    def test_different_model_profile_length_or_stage_never_proves_improvement(self):
        self.warm()
        for i in range(8):
            self.store.outcome(self.measured(i))
        for i in range(8):
            self.store.outcome(self.measured(20 + i, version=2, ok=True, profile="different-force"))
        self.assertNotEqual(self.store.status()["hints"][0]["phase"], "supported")
        self.assertTrue(self.store.selection("gallery")["strategy_ids"][0].endswith(":v2"))
        self.assertTrue(all(c["profile"] in ("different-force", "force88-crystal-a-fluid-contract1")
                            for c in self.store.status()["outcomes"]["cohorts"]))

    def test_repair_link_is_bound_to_original_work_and_rollback_pauses_adaptation(self):
        self.warm()
        first = self.measured(0)
        self.store.outcome(first)
        repair = {**first, "attempt_id": "repair:0", "stage": "repair", "prior_attempt_id": first["attempt_id"],
                  "machine_ok": True, "effective_ok": True, "faults": []}
        self.store.outcome(repair)
        self.assertEqual(self.store.status()["outcomes"]["linked_repairs"], 1)
        cohort = next(c for c in self.store.status()["outcomes"]["cohorts"] if c["stage"] == "repair")
        self.assertEqual(cohort["same_family_repairs"], {"pairs": 1, "resolved": 1, "rate": 1.0})
        with self.assertRaises(PromptLearningConflictError):
            self.store.outcome({**repair, "attempt_id": "bad:0", "source": "Different source"})
        self.store.rollback(self.store.settings()["revision"], expected_revision=self.store.settings()["revision"])
        pinned = self.store.selection("gallery")
        for i in range(1, 10):
            self.store.outcome(self.measured(i))
        self.assertEqual(self.store.selection("gallery"), pinned)
        self.store.update(self.store.settings()["revision"], resume=True)
        self.assertTrue(self.store.selection("gallery")["strategy_ids"][0].endswith(":v2"))


if __name__ == "__main__":
    unittest.main()
