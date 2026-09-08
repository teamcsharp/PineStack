"""Real learning-store regressions; fake model transport and no production writes."""
import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app
import prompt_learning
from tests import test_crystal_learning_execution as fixtures
from tests import test_crystal_prompt_integration as integration


def digest(text):
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


class CrystalLearningParentIdentityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.path = Path(temp) / "learning.sqlite3"
        self.store = prompt_learning.PromptLearningStore(self.path)
        self.errors = {"count": 0, "last_error": ""}
        for name, value in {
            "_PROMPT_LEARNING": self.store, "_PROMPT_LEARNING_ERRORS": self.errors,
            "_LAB_RUNTIME": mock.Mock(), "station_flow_event": mock.Mock(),
            "line_review_capture": mock.Mock(), "pipeline_log": mock.Mock(),
            "tint_seen": mock.Mock(), "_tint_flow": mock.Mock(),
            "_tint_output_note": mock.Mock(),
        }.items():
            self.stack.enter_context(mock.patch.object(app, name, value))
        for context, value in ((app._LINE_REVIEW_CONTEXT, {}),
                               (app._CRYSTAL_LEARNING_WIRE, None),
                               (app._REJECTION_LAB_PREVIEW, False)):
            token = context.set(value)
            self.addCleanup(context.reset, token)
        self.source = "I am Mara calling from the red gate tonight."
        self.canonical = f"A: {self.source}\nB: Keep the red gate in sight."
        self.raw = "The phone rings before the presenter answers. " + self.canonical
        self.refinement = fixtures.Refinement("Exact pinned guidance", "profile", 1, [])

    def stored(self):
        with sqlite3.connect(self.path) as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM prompt_outcomes ORDER BY seq")]

    def report(self):
        return {"ok": True, "machine_ok": True, "version": 8, "grade": "meaning",
                "semantic": {"ok": True, "contract_version": 2},
                "rhyme": {"ok": False, "required": True, "rap": {"ok": True}},
                "editorial": {"ok": True}, "faults": []}

    def measured(self, identity, parent, **changes):
        row = {"attempt_id": identity, "source": self.source, "candidate": "Mara is near; the gate is clear.",
               "parent": parent, "kind": "caller", "model": "fixture-model", "profile": "profile",
               "prompt_version": 4, "grader_version": 8, "contract_version": 2,
               "learning_revision": 1, "strategy_ids": [], "stage": "first", "prior_attempt_id": "",
               "machine_ok": False, "effective_ok": False, "semantic_ok": False,
               "rhyme_ok": True, "faults": ["names"]}
        row.update(changes)
        return row

    async def generated(self, parent, prior=None):
        async def transport(*args, **kwargs):
            app._CRYSTAL_LEARNING_WIRE.get()["model"] = "fixture-model"
            return "Mara calls from the red gate tonight; the gate is in sight."
        with mock.patch.object(app, "ask_model", side_effect=transport):
            return await app.crystal_learning_ask("fixture prompt", learning_kind="caller",
                learning_parent=parent, learning_refinement=self.refinement,
                learning_stage="repair" if prior else "first", learning_prior=prior)

    async def test_group_and_single_requests_use_same_retained_raw_parent(self):
        token = app._LINE_REVIEW_CONTEXT.set({"script_plain": self.raw, "script": "Older active copy."})
        try:
            group = await self.generated(self.canonical)
            single = await self.generated(self.source, group.learning_ticket()["attempt_id"])
        finally:
            app._LINE_REVIEW_CONTEXT.reset(token)
        for made in (group, single):
            ticket = made.learning_ticket()
            self.assertEqual(ticket["parent"], self.raw)
            self.assertEqual(ticket["parent_representations"], {"speaker_turns": digest(self.canonical)})
            app.crystal_learning_note(ticket, self.source, str(made), self.report())
        self.assertEqual(self.errors["count"], 0)
        self.assertEqual(self.store.status()["outcomes"]["linked_repairs"], 1)
        self.assertIsNone(app._CRYSTAL_LEARNING_WIRE.get())
        unscoped = await self.generated(self.canonical)
        self.assertEqual(unscoped.learning_ticket()["parent"], self.canonical)
        self.assertNotIn("parent_representations", unscoped.learning_ticket())

    async def test_unscoped_tint_pins_raw_parent_through_first_pass_and_grouped_repair(self):
        harness = integration.CrystalPromptIntegrationTests()
        harness.setUp()
        # This helper instance has no unittest asyncio runner: close its owned
        # patch stack directly rather than asking its inactive runner to clean.
        self.addCleanup(harness.stack.close)
        bad = "I am someone else calling from a different place."
        good = "Mara calls from the red gate tonight; the same red gate is in sight."
        answer = "Keep the red gate in sight; hold it safe tonight."
        replies = iter((f"A: {bad}\nB: {answer}", f"1: {good}"))
        async def transport(*args, **kwargs):
            app._CRYSTAL_LEARNING_WIRE.get()["model"] = "fixture-model"
            return next(replies)
        def grade(original, candidate, *args, **kwargs):
            report = self.report()
            if candidate == bad:
                report.update(ok=False, machine_ok=False, faults=["semantic preservation failed"])
                report["semantic"].update(ok=False, missing_names=["Mara"])
                report["editorial"]["ok"] = False
            return report
        harness.writer.side_effect = transport
        harness.grader.side_effect = grade
        with mock.patch.object(app, "crystal_operator_refinement", return_value=self.refinement):
            result = await app.crystal_tint.__wrapped__(self.raw, kind="banter")
        self.assertTrue(result["ok"], result.get("why"))
        self.assertEqual(harness.writer.await_count, 2)
        self.assertEqual(self.errors["count"], 0)
        rows = self.stored()
        self.assertEqual(len(rows), 3)
        self.assertEqual({row["parent_hash"] for row in rows}, {digest(self.raw)})
        self.assertEqual(rows[-1]["prior_attempt_id"], rows[0]["attempt_id"])
        self.assertEqual(self.store.status()["outcomes"]["linked_repairs"], 1)
        self.assertEqual(app._LINE_REVIEW_CONTEXT.get(), {})

    async def test_verified_legacy_boundary_keeps_old_row_without_claiming_linked_repair(self):
        prior = self.measured("legacy-group:0", self.canonical)
        self.store.outcome(prior)
        original = copy.deepcopy(self.stored()[0])
        token = app._LINE_REVIEW_CONTEXT.set({"script_plain": self.raw})
        try:
            made = await self.generated(self.canonical, prior["attempt_id"])
        finally:
            app._LINE_REVIEW_CONTEXT.reset(token)
        for _ in range(2):
            app.crystal_learning_note(made.learning_ticket(), self.source, str(made), self.report())
        rows = self.stored()
        self.assertEqual(self.errors["count"], 0)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], original)
        boundary = rows[1]["lineage_boundary"]
        self.assertFalse(boundary["linked"])
        self.assertEqual(boundary["prior_parent_hash"], digest(self.canonical))
        self.assertEqual(boundary["current_parent_hash"], digest(self.raw))
        self.assertEqual(rows[1]["prior_attempt_id"], prior["attempt_id"])
        status = self.store.status()["outcomes"]
        self.assertEqual(status["linked_repairs"], 0)
        self.assertEqual(status["lineage_boundaries"]["count"], 1)
        self.assertTrue(all(c["same_family_repairs"]["pairs"] == 0 for c in status["cohorts"]))

    def test_boundary_requires_exact_source_kind_and_known_parent_representation(self):
        prior = self.measured("legacy:0", self.canonical)
        self.store.outcome(prior)
        repair = self.measured("repair:0", self.raw, stage="repair", prior_attempt_id="legacy:0",
                               parent_representations={"speaker_turns": digest(self.canonical)})
        for change in ({"source": "Different caller request."}, {"kind": "gallery"},
                       {"parent_representations": {}},
                       {"parent_representations": {"speaker_turns": digest("Unrelated parent")}}):
            with self.subTest(change=change), self.assertRaises(prompt_learning.PromptLearningConflictError):
                self.store.outcome({**repair, **change})
        self.assertEqual(len(self.stored()), 1)
        self.assertTrue(self.store.outcome(repair)["recorded"])
        for change in ({"candidate": "Different generated wording."},
                       {"parent_representations": {"speaker_turns": digest("Edited metadata")}}):
            with self.assertRaises(prompt_learning.PromptLearningConflictError):
                self.store.outcome({**repair, **change})

    def test_boundary_duplicate_survives_prior_retention_and_old_rows_need_no_new_default(self):
        prior = self.measured("legacy:0", self.canonical)
        self.store.outcome(prior)
        self.assertEqual(self.store.outcome({**prior, "parent_representations": {}})["reason"], "duplicate")
        repair = self.measured("repair:0", self.raw, stage="repair", prior_attempt_id="legacy:0",
                               parent_representations={"speaker_turns": digest(self.canonical)})
        with mock.patch.object(prompt_learning, "OUTCOME_WINDOW", 1):
            self.store.outcome(repair)
        self.assertEqual(len(self.stored()), 1)
        self.assertEqual(self.store.outcome(repair)["reason"], "duplicate")
        self.assertEqual(self.stored()[0]["lineage_boundary"]["prior_parent_hash"], digest(self.canonical))

    async def test_operator_allowed_caller_failure_keeps_one_failed_measured_outcome(self):
        candidate = "I am someone else calling from a different place."
        async def transport(*args, **kwargs):
            app._CRYSTAL_LEARNING_WIRE.get()["model"] = "fixture-model"
            return candidate
        with (mock.patch.object(app, "ask_model", side_effect=transport) as model,
              mock.patch.object(app, "crystal_operator_refinement", return_value=self.refinement),
              mock.patch.object(app, "crystal_force", return_value=.88),
              mock.patch.object(app, "tint_evaluate", side_effect=lambda *a, **k: self.report()),
              mock.patch.object(app, "call_tint_report", return_value={"ok": False, "faults": ["Caller identity changed"]}),
              mock.patch.object(app, "line_review_permits", return_value=True)):
            result = await app.crystal_turn.__wrapped__(self.source, "world", [], kind="caller", model="fixture-model")
        self.assertEqual(str(result), candidate)  # Explicit operator permission still applies.
        self.assertEqual(model.await_count, 1)
        self.assertEqual(self.errors["count"], 0)
        rows = self.stored()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["attempt_id"], result.attempt_id)
        for key in ("machine_ok", "effective_ok", "semantic_ok"):
            self.assertFalse(rows[0][key])
        self.assertIn("caller_structure", rows[0]["faults"])

    async def test_new_caller_rewrite_resets_prior_failure_and_records_real_success(self):
        bad = "I am someone else calling from a different place."
        good = "Mara calls from the red gate tonight; the same red gate is in sight."
        outputs = iter((bad, good))
        async def transport(*args, **kwargs):
            app._CRYSTAL_LEARNING_WIRE.get()["model"] = "fixture-model"
            return next(outputs)
        with (mock.patch.object(app, "ask_model", side_effect=transport) as model,
              mock.patch.object(app, "crystal_operator_refinement", return_value=self.refinement),
              mock.patch.object(app, "crystal_force", return_value=.88),
              mock.patch.object(app, "tint_evaluate", side_effect=lambda *a, **k: self.report()),
              mock.patch.object(app, "call_tint_report", side_effect=lambda before, after: {
                  "ok": bad not in after, "faults": ["Caller identity changed"] if bad in after else []}),
              mock.patch.object(app, "line_review_permits", return_value=False)):
            result = await app.crystal_turn.__wrapped__(self.source, "world", [], kind="caller", model="fixture-model")
        self.assertEqual(str(result), good)
        self.assertEqual(model.await_count, 2)
        self.assertEqual(self.errors["count"], 0)
        rows = self.stored()
        self.assertEqual(len(rows), 2)
        self.assertFalse(rows[0]["effective_ok"])
        self.assertTrue(rows[1]["effective_ok"])
        self.assertEqual(rows[1]["prior_attempt_id"], rows[0]["attempt_id"])


if __name__ == "__main__":
    unittest.main()
