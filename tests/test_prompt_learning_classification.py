"""Versioned derived labels preserve the original occurrence and decisions."""
import copy
import json
import unittest
from unittest import mock

from prompt_learning import CLASSIFIER_VERSION, PromptLearningConflictError
from tests import test_prompt_learning as fixtures


class PromptLearningClassificationTests(unittest.TestCase):
    setUp = fixtures.PromptLearningTests.setUp
    row = fixtures.PromptLearningTests.row
    enable = fixtures.PromptLearningTests.enable

    def legacy(self, index):
        row = self.row(index, evaluation={"version": 5, "grade": "meaning", "machine_ok": False,
            "rhyme": {"required": True, "ok": False, "rap": {"ok": True}},
            "transformation": {"ok": False, "cadence_changed": False}})
        with mock.patch("prompt_learning.CLASSIFIER_VERSION", 1), mock.patch(
                "prompt_learning._patterns", return_value=["rhyme", "cadence"]):
            self.store.observe(row)
        return row

    def reopen(self):
        self.store = fixtures.PromptLearningStore(self.path, now=lambda: self.clock)

    def test_upgrade_reclassifies_advisory_rhyme_and_retains_exact_decision(self):
        self.enable()
        rows = [self.legacy(i) for i in range(3)]
        original = copy.deepcopy(rows)
        voted = copy.deepcopy(rows[0])
        voted.update(revision=2, decision={"by": "operator", "scope": "exact", "action": "keep", "at": 1001})
        with mock.patch("prompt_learning.CLASSIFIER_VERSION", 1), mock.patch(
                "prompt_learning._patterns", return_value=["rhyme", "cadence"]):
            self.store.decision(voted)
        self.reopen()
        self.assertEqual([r["pattern"] for r in self.store.status()["hints"]], ["rhyme", "cadence"])
        before = self.store.settings()["revision"]
        self.assertEqual(self.store.status()["classification"]["pending"], 3)
        refs = self.store.pending_reclassifications()
        self.assertEqual([r["event_seq"] for r in refs], [3, 2, 1])
        for row in rows:
            result = self.store.observe(row)
            self.assertTrue(result["reclassified"])
            self.assertFalse(result["recorded"])  # no new occurrence or operator vote
        self.assertEqual(rows, original)
        self.assertEqual(self.store.pending_reclassifications(), [])
        self.assertGreater(self.store.settings()["revision"], before)
        self.assertEqual([r["pattern"] for r in self.store.status()["hints"]], ["cadence"])
        self.assertEqual(self.store.status()["hints"][0]["operator_confirmed"], 1)
        audit = self.store.classification_history(limit=2)
        self.assertEqual(audit["total"], 3)
        self.assertTrue(audit["has_more"])
        self.assertEqual(audit["items"][0]["before"]["patterns"], ["rhyme", "cadence"])
        self.assertEqual(audit["items"][0]["after"]["patterns"], ["cadence"])
        self.assertEqual(audit["items"][0]["after"]["classifier_version"], CLASSIFIER_VERSION)
        self.assertEqual(self.store.classification_history(before=audit["next_before"])["items"][0]["seq"], 1)
        self.assertFalse(self.store.observe(rows[0])["reclassified"])
        self.assertEqual(self.store.classification_history()["total"], 3)
        self.reopen()
        self.assertEqual(self.store.status()["classification"], {"version": CLASSIFIER_VERSION, "pending": 0, "migrations": 3})

    def test_changed_immutable_work_cannot_be_migrated(self):
        row = self.legacy(0)
        self.reopen()
        for field in ("source", "candidate", "parent", "grader", "kind", "gate"):
            changed = copy.deepcopy(row)
            if field in ("source", "candidate"):
                changed[field] += " Different words."
            elif field == "parent":
                changed["context"]["script_plain"] += " Other parent."
            elif field == "grader":
                changed["evaluation"]["version"] = 6
            elif field == "kind":
                changed["context"]["kind"] = "caller"
            else:
                changed["gate"] = "tint_structure"
            with self.subTest(field=field), self.assertRaises(PromptLearningConflictError):
                self.store.observe(changed)
        self.assertEqual(self.store.status()["classification"]["pending"], 1)
        self.assertEqual(self.store.classification_history()["total"], 0)
        self.store.observe(row)
        changed = copy.deepcopy(row)
        changed["evaluation"]["transformation"]["cadence_changed"] = True
        with self.assertRaises(PromptLearningConflictError):
            self.store.observe(changed)  # no same-version regrading under an existing occurrence

    def test_protected_exclusions_remain_excluded_and_cannot_be_removed(self):
        rows = [self.row(0, technical=True), self.row(1, gate="other"),
                self.row(2, evaluation={"version": 4, "machine_ok": False})]
        with mock.patch("prompt_learning.CLASSIFIER_VERSION", 1):
            for row in rows:
                self.store.observe(row)
        self.reopen()
        changed = {**rows[0], "technical": False}
        with self.assertRaises(PromptLearningConflictError):
            self.store.observe(changed)
        for row in rows:
            self.assertTrue(self.store.observe(row)["reclassified"])
        self.assertEqual(self.store.status()["patterns"], [])
        self.assertEqual(self.store.status()["excluded"], {
            "technical": 1, "unsupported_gate": 1, "old_or_unknown_grader": 1})

    def test_refs_include_all_retained_rows_and_support_unversioned_legacy_data(self):
        rows = [self.legacy(i) for i in range(3)]
        with self.store._connect() as db:
            saved = db.execute("SELECT body FROM prompt_evidence WHERE event_seq=1").fetchone()[0]
            body = json.loads(saved)
            body.pop("classifier_version")
            db.execute("UPDATE prompt_evidence SET body=? WHERE event_seq=1", (json.dumps(body),))
        with mock.patch("prompt_learning.WINDOW", 2):
            self.reopen()
            self.assertEqual(self.store.status()["observation_count"], 2)
            self.assertEqual(self.store.status()["classification"]["pending"], 3)
            self.assertEqual([r["event_seq"] for r in self.store.pending_reclassifications(limit=2)], [3, 2])
        self.store.observe(rows[2])
        self.store.observe(rows[1])
        self.assertEqual(self.store.pending_reclassifications(), [{"review_id": "review-0", "event_seq": 1, "classifier_version": 1}])
        self.store.observe(rows[0])
        self.assertEqual(self.store.pending_reclassifications(), [])

    def test_bulk_upgrades_once_and_invalid_row_rolls_back_every_receipt(self):
        self.enable()
        rows = [self.legacy(i) for i in range(6)]
        self.reopen()
        before = self.store.settings()["revision"]
        bad = copy.deepcopy(rows[-1])
        bad["candidate"] = "Different original evidence."
        with self.assertRaises(PromptLearningConflictError):
            self.store.reclassify(rows[:-1] + [bad])
        self.assertEqual(self.store.classification_history()["total"], 0)
        self.assertEqual(len(self.store.pending_reclassifications()), 6)
        with mock.patch.object(self.store, "_outcomes", wraps=self.store._outcomes) as outcomes, mock.patch.object(
                self.store, "_summarize", wraps=self.store._summarize) as summary:
            result = self.store.reclassify(rows)
            self.assertEqual(outcomes.call_count, 1)
            self.assertEqual(summary.call_count, 1)
        self.assertEqual(result["reclassified"], 6)
        self.assertEqual(self.store.settings()["revision"], before + 1)
        self.assertEqual(self.store.classification_history()["total"], 6)
        self.assertEqual(self.store.pending_reclassifications(), [])
        self.assertEqual(self.store.reclassify(rows)["reclassified"], 0)
        self.assertEqual(self.store.settings()["revision"], before + 1)
        with self.assertRaises(PromptLearningConflictError):
            self.store.reclassify([self.row(99)])


if __name__ == "__main__":
    unittest.main()
