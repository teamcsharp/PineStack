"""Operator review changes effective editorial decisions, with durable evidence."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from line_review import LineReviewStore, ReviewConflictError


class LineReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "reviews.sqlite"
        self.store = LineReviewStore(self.path)

    def record(self, **kwargs):
        args = dict(gate="tint", source="The original line.", candidate="The revised line.",
                    reasons=["no rhyme evidence"], context={"kind": "banter", "who": ""})
        args.update(kwargs)
        return self.store.record(**args)

    def evaluate(self, **kwargs):
        args = dict(gate="tint", source="The original line.", candidate="The revised line.",
                    reasons=["no rhyme evidence"], context={"kind": "banter", "who": ""})
        args.update(kwargs)
        return self.store.evaluate(**args)

    def test_default_rejects_editorial_flags_and_tolerance_counts_unique_flags(self):
        self.assertFalse(self.evaluate()["allowed"])
        self.assertTrue(self.evaluate(reasons=[])["allowed"])
        policy = self.store.policy({"max_faults": 1})
        accepted = self.evaluate(reasons=["no rhyme", "no rhyme", " no rhyme "])
        self.assertTrue(accepted["allowed"])
        self.assertEqual(accepted["fault_count"], 1)
        self.assertEqual(accepted["policy_revision"], policy["revision"])
        self.assertFalse(self.evaluate(reasons=["no rhyme", "meaning changed"])["allowed"])
        self.assertEqual(self.store.summaries()["total"], 0, "Pure grades do not create a review history")

    def test_disabled_gate_and_global_switch_affect_editorial_only(self):
        self.store.policy({"disabled_gates": ["tint"]})
        self.assertEqual(self.evaluate()["reason"], "gate_disabled")
        self.assertFalse(self.evaluate(gate="call_contract")["allowed"])
        self.store.policy({"enabled": False, "max_faults": 10})
        self.assertTrue(self.evaluate(gate="call_contract")["allowed"])
        for reasons in ([], ["missing media"]):
            technical = self.evaluate(technical=True, reasons=reasons)
            self.assertFalse(technical["allowed"])
            self.assertEqual(technical["reason"], "technical")

    def test_operator_approval_binds_normalized_text_case_gate_kind_and_who(self):
        row = self.record(source="The  original\nline.", context={"kind": "banter", "who": "", "speaker": "HOST"})
        self.store.decide(row["id"], "allow", "This is a valid bar", row["revision"])
        approved = self.evaluate(context={"kind": "banter", "marker": "A", "script": "extra evidence"})
        self.assertTrue(approved["allowed"])
        self.assertTrue(approved["operator_approved"])
        for change in ({"source": "the original line."}, {"candidate": "A different revision."},
                       {"gate": "call_contract"}, {"context": {"kind": "caller"}},
                       {"context": {"kind": "banter", "who": "cohost"}}):
            with self.subTest(change=change):
                self.assertFalse(self.evaluate(**change)["allowed"])
        self.assertFalse(self.evaluate(technical=True)["allowed"])
        self.assertEqual(self.store.get(row["id"])["source"], "The  original\nline.")

    def test_hot_evaluation_uses_no_database_and_return_values_cannot_mutate_policy(self):
        row = self.record()
        self.store.decide(row["id"], "allow")
        external = self.store.policy()
        external["enabled"] = False
        external["disabled_gates"].append("other")
        with mock.patch.object(self.store, "_connect", side_effect=AssertionError("SQL on hot path")):
            self.assertTrue(self.evaluate()["operator_approved"])
            self.assertFalse(self.evaluate(gate="other")["allowed"])

    def test_restart_restores_exact_approvals_kept_reviews_and_policy(self):
        allowed = self.record()
        kept = self.record(source="Another source")
        self.store.decide(allowed["id"], "allow", "Keep this bar")
        self.store.decide(kept["id"], "keep", "The rejection is right")
        policy = self.store.policy({"disabled_gates": ["brief"], "max_faults": 0})
        reopened = LineReviewStore(self.path)
        self.assertEqual(reopened.policy(), policy)
        self.assertTrue(reopened.evaluate("tint", "The original line.", "The revised line.", ["bad"], {"kind": "banter"})["allowed"])
        self.assertEqual(reopened.get(kept["id"])["review_status"], "kept")
        self.assertEqual(reopened.summaries()["unreviewed"], 0)

    def test_every_duplicate_occurrence_keeps_full_text_context_and_cursor(self):
        text = "A complete sentence and its details. " * 900
        row = self.record(source=text, candidate=text + "Candidate tail", context={"kind": "banter", "speaker": "HOST", "script": text * 2})
        other = self.record(source="Separate line")
        repeated = self.record(source=text, candidate=text + "Candidate tail", reasons=["different evidence"],
                               context={"kind": "banter", "marker": "A", "script": "Second context"})
        self.assertEqual(row["id"], repeated["id"])
        self.assertEqual(repeated["occurrences"], 2)
        self.assertLess(row["seq"], other["seq"])
        self.assertLess(other["seq"], repeated["seq"])
        full = self.store.get(row["id"])
        self.assertEqual(full["source"], text)
        self.assertEqual(full["history"][1]["context"]["script"], text * 2)
        self.assertEqual(full["history"][0]["context"]["script"], "Second context")
        listed = self.store.summaries()
        self.assertEqual(listed["total"], 2)
        self.assertEqual(listed["items"][0]["who"], "A")
        self.assertNotIn("context", listed["items"][0])
        self.assertLess(len(listed["items"][0]["source_preview"]), len(text))

    def test_new_event_cursor_pages_without_skipping_and_history_remains_complete(self):
        first = self.record()
        for i in range(5):
            self.record(reasons=[f"attempt {i}"])
        cursor, seen, faults = first["seq"], [], []
        while True:
            page = self.store.summaries(after=cursor, limit=2)
            seen.extend(event["seq"] for event in page["events"])
            faults.extend(event["reasons"][0] for event in page["events"])
            cursor = page["next_after"]
            if not page["events_has_more"]:
                break
        self.assertEqual(seen, list(range(first["seq"] + 1, first["seq"] + 6)))
        self.assertEqual(faults, [f"attempt {i}" for i in range(5)], "Each popup retains that occurrence's evidence")
        before, history = 0, []
        while True:
            page = self.store.get(first["id"], before=before, limit=2)
            history.extend(event["seq"] for event in page["history"])
            if not page["history_has_more"]:
                break
            before = page["history_next_before"]
        self.assertEqual(history, list(range(6, 0, -1)))
        self.assertEqual(LineReviewStore(self.path).get(first["id"])["occurrences"], 6)

    def test_summary_paging_filters_and_review_counts(self):
        entries = [self.record(source=f"line {i}", gate="tint" if i % 2 else "brief") for i in range(7)]
        self.store.decide(entries[0]["id"], "keep")
        self.store.decide(entries[1]["id"], "allow")
        page = self.store.summaries(limit=2)
        self.assertEqual(page["total"], 5)
        self.assertEqual(page["unreviewed"], 5)
        ids = [item["id"] for item in page["items"]]
        while page["has_more"]:
            page = self.store.summaries(limit=2, before=page["next_before"])
            ids.extend(item["id"] for item in page["items"])
        self.assertEqual(len(set(ids)), 5)
        self.assertEqual(self.store.summaries(status="all")["total"], 7)
        self.assertEqual(self.store.summaries(status="allowed")["items"][0]["id"], entries[1]["id"])
        self.assertTrue(all(row["gate"] == "tint" for row in self.store.summaries(gate="tint")["items"]))

    def test_empty_client_cursor_receives_first_cut_and_drains_bursts_from_zero(self):
        empty = self.store.summaries(after=0, limit=2)
        self.assertEqual(empty["events"], [])
        self.assertEqual(empty["next_after"], 0)
        self.assertEqual(empty["latest_cursor"], 0)
        first = self.record(source="The first real cut")
        delta = self.store.summaries(after=empty["next_after"], limit=2)
        self.assertEqual([event["id"] for event in delta["events"]], [first["id"]])
        self.assertEqual(delta["next_after"], first["seq"])
        self.assertEqual(self.store.summaries(after=delta["next_after"])["events"], [])
        added = [self.record(source=f"Additional cut {i}") for i in range(5)]
        restarted = LineReviewStore(self.path)
        cursor, seen = 0, []
        while True:
            page = restarted.summaries(after=cursor, limit=2)
            seen.extend(event["id"] for event in page["events"])
            cursor = page["next_after"]
            if not page["events_has_more"]:
                break
        self.assertEqual(seen, [first["id"]] + [row["id"] for row in added])
        self.assertEqual(cursor, added[-1]["seq"])

    def test_decisions_are_versioned_idempotent_and_keep_revokes_approval(self):
        row = self.record()
        changed = self.store.decide(row["id"], "allow", "Valid", row["revision"])
        self.assertTrue(changed["changed"])
        self.assertFalse(self.store.decide(row["id"], "allow", "Valid", row["revision"])["changed"])
        with self.assertRaises(ReviewConflictError):
            self.store.decide(row["id"], "keep", "Changed my mind", row["revision"])
        kept = self.store.decide(row["id"], "keep", "Changed my mind", changed["row"]["revision"])
        self.assertEqual(kept["row"]["review_status"], "kept")
        self.assertFalse(self.evaluate()["allowed"])
        self.assertEqual(len(self.store.get(row["id"])["decisions"]), 2)

    def test_technical_review_cannot_be_approved_even_after_global_disable(self):
        row = self.record(technical=True, reasons=["Media file is missing"])
        self.store.policy({"enabled": False})
        with self.assertRaisesRegex(ValueError, "technical"):
            self.store.decide(row["id"], "allow")
        self.assertEqual(self.store.decide(row["id"], "keep")["row"]["review_status"], "kept")

    def test_new_technical_failure_removes_prior_editorial_approval_from_cache(self):
        row = self.record()
        self.store.decide(row["id"], "allow")
        self.assertTrue(self.evaluate()["operator_approved"])
        repeated = self.record(technical=True, reasons=["missing media"])
        self.assertEqual(repeated["id"], row["id"])
        self.assertEqual(repeated["review_status"], "pending")
        self.assertFalse(self.evaluate()["operator_approved"])
        self.assertFalse(self.evaluate(technical=True)["allowed"])
        with self.assertRaises(ValueError):
            self.store.decide(row["id"], "allow")

    def test_effects_are_durable_without_recording_side_effects_or_repeat_decisions(self):
        row = self.record()
        decision = self.store.decide(row["id"], "allow")
        self.assertEqual(decision["effect"]["status"], "awaiting_recovery")
        result = self.store.track_effect(row["id"], {"status": "restored", "restored_turns": 1})
        self.assertEqual(result["effect"]["restored_turns"], 1)
        retry = self.store.decide(row["id"], "allow")
        self.assertFalse(retry["changed"])
        self.assertEqual(retry["effect"]["status"], "restored")
        self.assertEqual(LineReviewStore(self.path).get(row["id"])["effect"]["status"], "restored")

    def test_concurrent_duplicate_records_keep_one_review_and_every_occurrence(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            records = list(pool.map(lambda i: self.record(context={"kind": "banter", "attempt": i}), range(32)))
        self.assertEqual(len({row["id"] for row in records}), 1)
        self.assertEqual(len({row["seq"] for row in records}), 32)
        full = self.store.get(records[0]["id"])
        self.assertEqual(full["occurrences"], 32)
        self.assertEqual({event["context"]["attempt"] for event in full["history"]}, set(range(32)))

    def test_note_edit_versions_review_without_restarting_recorded_or_kept_work(self):
        row = self.record()
        self.store.decide(row["id"], "allow", "Initial reason")
        recorded = self.store.track_effect(row["id"], {
            "status": "recorded", "entry_id": "original-entry", "made": 4,
            "receipt": {"delivery_id": "already-recorded"}})
        edited = self.store.decide(row["id"], "allow", "Clearer reason", recorded["revision"])
        self.assertTrue(edited["changed"])
        self.assertEqual(edited["effect"], recorded["effect"])
        self.assertEqual(edited["row"]["revision"], recorded["revision"] + 1)
        self.assertTrue(self.evaluate()["operator_approved"])
        again = LineReviewStore(self.path).get(row["id"])
        self.assertEqual(again["effect"], recorded["effect"])
        self.assertEqual(again["decision"]["note"], "Clearer reason")
        kept = self.store.decide(row["id"], "keep", "Changed decision")
        self.assertEqual(kept["effect"]["status"], "kept")
        self.assertNotIn("receipt", kept["effect"])
        changed_note = self.store.decide(row["id"], "keep", "Clearer rejection")
        self.assertEqual(changed_note["effect"], kept["effect"])
        self.assertFalse(self.evaluate()["operator_approved"])

    def test_concurrent_conflicting_decisions_allow_one_winner(self):
        row = self.record()
        def decide(action):
            try:
                return self.store.decide(row["id"], action, expected_revision=row["revision"])
            except ReviewConflictError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(decide, ["allow", "keep"]))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.store.get(row["id"])["decisions"]), 1)

    def test_policy_revision_and_validation_do_not_silently_coerce_inputs(self):
        original = self.store.policy()
        for patch in ({"enabled": "false"}, {"max_faults": -1}, {"max_faults": 11},
                      {"max_faults": True}, {"max_faults": 1.5}, {"disabled_gates": "tint"},
                      {"disabled_gates": [""]}, {"made_up_setting": False}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.store.policy(patch)
            self.assertEqual(self.store.policy(), original)
        changed = self.store.policy({"max_faults": 2, "expected_revision": original["revision"]})
        self.assertEqual(self.store.policy({"max_faults": 2})["revision"], changed["revision"])
        with self.assertRaises(ReviewConflictError):
            self.store.policy({"enabled": False, "expected_revision": original["revision"]})

    def test_bulk_approval_snapshots_all_pages_and_preserves_policy_and_individual_decisions(self):
        pending = [self.record(source=f"Complete pending line {i}.") for i in range(113)]
        technical = self.record(source="Missing audio", technical=True)
        empty = self.record(source=" \n ", candidate="\t")
        kept = self.record(source="Already reviewed and kept.")
        permanent = self.record(source="Already individually approved.")
        self.store.decide(kept["id"], "keep")
        self.store.decide(permanent["id"], "allow")
        policy = self.store.policy()
        cursor = self.store.summaries()["latest_cursor"]
        self.assertTrue(self.store.summaries(limit=50)["has_more"])

        batch = self.store.approve_current("all-pages-snapshot")

        # #1088: a technical failure is the machine's note, never pending, so
        # the snapshot holds the 113 complete lines and the empty one.
        self.assertEqual(self.store.get(technical["id"])["review_status"], "noted")
        self.assertEqual(batch["snapshot_count"], 114)
        self.assertEqual(batch["approved"], 113)
        self.assertEqual(batch["awaiting_recovery"], 113)
        self.assertEqual(batch["queued"], 0, "Approval only requests normal recovery")
        self.assertEqual(batch["skip_reasons"], {"missing_text": 1})
        self.assertEqual(batch["remaining_pending"], 1)
        self.assertEqual(batch["through_cursor"], cursor)
        accepted_ids = {item["id"] for item in batch["items"] if item["status"] == "approved_once"}
        self.assertEqual(accepted_ids, {row["id"] for row in pending})
        self.assertEqual(len(self.store.pending_instances()), 113)
        self.assertEqual(self.store.policy(), policy)
        self.assertEqual(self.store.get(kept["id"])["review_status"], "kept")
        self.assertTrue(self.evaluate(source=permanent["source"])["operator_approved"])
        self.assertEqual(self.store.get(empty["id"])["review_status"], "pending")
        for row in (technical, empty):
            self.assertEqual(self.store.instances_for(row["id"]), [])

    def test_bulk_request_retry_is_durable_and_does_not_capture_later_rejections(self):
        row = self.record()
        batch = self.store.approve_current("retry-batch-identity")
        newer = self.record(source="A later rejection is a separate decision.")
        repeated = self.record(context={"kind": "banter", "trace_id": "future-event"})
        self.assertEqual(repeated["review_status"], "pending")
        expected_revision = self.store.get(row["id"])["revision"]

        self.assertEqual(self.store.approve_current("retry-batch-identity"), batch)
        restarted = LineReviewStore(self.path)
        self.assertEqual(restarted.approve_current("retry-batch-identity"), batch)
        self.assertEqual(restarted.get(row["id"])["revision"], expected_revision)
        self.assertEqual(restarted.get(newer["id"])["review_status"], "pending")
        self.assertEqual(len(restarted.pending_instances()), 1)
        self.assertEqual(restarted.summaries()["unreviewed"], 2)
        # A caller cannot mutate the persisted response or its returned policy.
        batch["items"].clear()
        batch["policy"]["enabled"] = False
        retry = restarted.approve_current("retry-batch-identity")
        self.assertEqual(len(retry["items"]), 1)
        self.assertTrue(retry["policy"]["enabled"])

    def test_once_grant_preserves_original_evidence_and_does_not_approve_future_fingerprint(self):
        context = {"kind": "banter", "who": "", "script": "Original whole programme", "trace_id": "first"}
        row = self.record(context=context, evaluation={"raw_ok": False, "attempt": 1})
        batch = self.store.approve_current("immutable-evidence")
        grant_id = batch["items"][0]["instance_id"]
        grant = self.store.get(grant_id)
        self.assertEqual(grant["original_review_id"], row["id"])
        self.assertEqual(grant["decision"]["event_seq"], row["seq"])
        self.assertFalse(self.evaluate()["allowed"])
        with self.store.instance_scope([grant_id]):
            approved = self.evaluate()
            self.assertEqual(approved["reason"], "instance_approved")
            self.assertTrue(approved["machine_rejected"], "Operator choice does not rewrite the machine grade")
            self.assertFalse(self.evaluate(technical=True)["allowed"])
            self.assertFalse(self.evaluate(source="Different original words")["allowed"])
            self.assertFalse(self.evaluate(context={"kind": "caller"})["allowed"])
            self.assertFalse(self.evaluate(context={"kind": "banter", "who": "cohost"})["allowed"])
        self.record(context={**context, "script": "Later whole programme", "trace_id": "second"},
                    evaluation={"raw_ok": False, "attempt": 2}, reasons=["Later machine evidence"])

        self.assertEqual(self.store.get(row["id"])["review_status"], "pending")
        self.assertEqual(self.store.get(grant_id), grant)
        self.assertFalse(self.evaluate()["allowed"])
        restarted = LineReviewStore(self.path)
        self.assertEqual(restarted.get(grant_id), grant)
        self.assertEqual(restarted.pending_instances(), [grant])
        self.assertFalse(restarted.evaluate("tint", row["source"], row["candidate"], row["reasons"], context)["allowed"])
        with restarted.instance_scope([grant_id]):
            self.assertTrue(restarted.evaluate("tint", row["source"], row["candidate"], row["reasons"], context)["allowed"])
        copied = restarted.pending_instances()[0]
        copied["context"]["script"] = "Caller mutation"
        self.assertEqual(restarted.get(grant_id)["context"]["script"], "Original whole programme")

    def test_older_grant_completion_does_not_overwrite_newer_instance_or_repeat_evidence(self):
        row = self.record(context={"kind": "banter", "trace_id": "first"})
        first = self.store.approve_current("first-occurrence")["items"][0]["instance_id"]
        self.record(context={"kind": "banter", "trace_id": "second"})
        second = self.store.approve_current("second-occurrence")["items"][0]["instance_id"]
        self.assertNotEqual(first, second)
        self.store.track_effect(first, {"status": "recorded", "entry_id": "original-entry", "made": 2})
        self.assertEqual(self.store.get(row["id"])["effect"]["status"], "awaiting_recovery")
        self.assertEqual(self.store.get(row["id"])["decision"]["instance_id"], second)
        self.assertEqual([grant["id"] for grant in self.store.pending_instances()], [second])
        self.assertEqual(self.store.get(first)["context"]["trace_id"], "first")
        self.assertEqual(self.store.get(second)["context"]["trace_id"], "second")
        restarted = LineReviewStore(self.path)
        self.assertEqual([grant["id"] for grant in restarted.pending_instances()], [second])
        self.assertEqual(restarted.get(first)["effect"]["entry_id"], "original-entry")

    def test_keep_revokes_outstanding_grants_and_late_recovery_cannot_restore_them(self):
        row = self.record()
        first = self.store.approve_current("withdraw-first-batch")["items"][0]["instance_id"]
        self.record(context={"kind": "banter", "trace_id": "new occurrence"})
        second = self.store.approve_current("withdraw-second-batch")["items"][0]["instance_id"]
        current = self.store.get(row["id"])
        with self.assertRaises(ReviewConflictError):
            self.store.decide(row["id"], "keep", expected_revision=row["revision"])
        with self.store.instance_scope([first, second]):
            self.assertTrue(self.evaluate()["allowed"])
            self.store.decide(row["id"], "keep", expected_revision=current["revision"])
            self.assertFalse(self.evaluate()["allowed"])
            self.assertEqual(self.store.scoped_instances(), ())
        for grant_id in (first, second):
            late = self.store.track_effect(grant_id, {"status": "recorded", "entry_id": "late-result"})
            self.assertEqual(late["review_status"], "kept")
            self.assertEqual(late["effect"]["status"], "kept")
            self.assertNotIn("entry_id", late["effect"])
        self.assertEqual(self.store.pending_instances(), [])
        restarted = LineReviewStore(self.path)
        with restarted.instance_scope([first, second]):
            self.assertFalse(restarted.evaluate("tint", row["source"], row["candidate"], row["reasons"], row["context"])["allowed"])
        self.assertEqual(restarted.pending_instances(), [])

    def test_individual_allow_after_bulk_approval_retains_its_permanent_semantics(self):
        row = self.record()
        self.store.approve_current("once-before-individual")
        self.assertFalse(self.evaluate()["allowed"])
        current = self.store.get(row["id"])
        decision = self.store.decide(row["id"], "allow", expected_revision=current["revision"])
        self.assertTrue(decision["changed"])
        self.assertNotEqual(decision["row"]["decision"].get("scope"), "instance")
        self.assertTrue(self.evaluate()["allowed"])
        repeated = self.record(context={"kind": "banter", "trace_id": "later"})
        self.assertEqual(repeated["review_status"], "allowed")
        restarted = LineReviewStore(self.path)
        self.assertTrue(restarted.evaluate("tint", row["source"], row["candidate"], row["reasons"], row["context"])["allowed"])

    def test_bulk_transaction_rolls_back_before_publishing_any_partial_grants(self):
        rows = [self.record(source=f"Atomic waiting line {i}") for i in range(3)]
        policy = self.store.policy()
        # Fail while constructing the second grant after the first SQL insert.
        with mock.patch("line_review.uuid.uuid4", side_effect=[mock.Mock(hex="first-grant"), RuntimeError("storage interrupted")]):
            with self.assertRaisesRegex(RuntimeError, "storage interrupted"):
                self.store.approve_current("atomic-retry-identity")
        self.assertEqual(self.store.pending_instances(), [])
        self.assertEqual(self.store.summaries()["unreviewed"], 3)
        for row in rows:
            self.assertEqual(self.store.get(row["id"])["revision"], row["revision"])
            self.assertEqual(self.store.get(row["id"])["decisions"], [])
        reopened = LineReviewStore(self.path)
        self.assertEqual(reopened.pending_instances(), [])
        self.assertEqual(reopened.policy(), policy)
        retry = reopened.approve_current("atomic-retry-identity")
        self.assertEqual(retry["approved"], 3)
        self.assertEqual(len(reopened.pending_instances()), 3)

    def test_concurrent_bulk_retries_commit_one_snapshot_and_one_grant_per_row(self):
        rows = [self.record(source=f"Concurrent waiting line {i}") for i in range(9)]
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.store.approve_current("same-concurrent-request"), range(12)))
        self.assertTrue(all(batch == results[0] for batch in results))
        self.assertEqual(len(self.store.pending_instances()), 9)
        for row in rows:
            self.assertEqual(len(self.store.instances_for(row["id"])), 1)
            self.assertEqual(len(self.store.get(row["id"])["decisions"]), 1)
        self.assertEqual(self.store.approve_current("new-empty-snapshot")["approved"], 0)

    def test_instance_scopes_are_task_local_and_reset_after_nested_failure(self):
        self.record()
        first = self.store.approve_current("task-first-snapshot")["items"][0]["instance_id"]
        self.record(source="Another task's original words.")
        second = self.store.approve_current("task-second-snapshot")["items"][0]["instance_id"]

        async def run_tasks():
            entered, release = asyncio.Event(), asyncio.Event()

            async def approved_task():
                with self.store.instance_scope([first]):
                    entered.set()
                    await release.wait()
                    self.assertTrue(self.evaluate()["allowed"])
                    self.assertFalse(self.evaluate(source="Another task's original words.")["allowed"])
                    with self.assertRaisesRegex(RuntimeError, "nested scope"):
                        with self.store.instance_scope([second, first]):
                            self.assertEqual(set(self.store.scoped_instances()), {first, second})
                            self.assertTrue(self.evaluate(source="Another task's original words.")["allowed"])
                            raise RuntimeError("nested scope")
                    self.assertEqual(self.store.scoped_instances(), (first,))
                self.assertEqual(self.store.scoped_instances(), ())
                self.assertFalse(self.evaluate()["allowed"])

            async def unrelated_task():
                await entered.wait()
                try:
                    self.assertFalse(self.evaluate()["allowed"])
                    self.assertEqual(self.store.scoped_instances(), ())
                    with self.store.instance_scope([second, "unknown-grant"]):
                        self.assertTrue(self.evaluate(source="Another task's original words.")["allowed"])
                        self.assertFalse(self.evaluate()["allowed"])
                finally:
                    release.set()

            await asyncio.gather(approved_task(), unrelated_task())

        asyncio.run(run_tasks())
        self.assertEqual(self.store.scoped_instances(), ())
        self.assertFalse(self.evaluate()["allowed"])

    def test_invalid_reviews_and_paging_fail_without_partial_records(self):
        for change in ({"source": None}, {"candidate": 42}, {"gate": ""}, {"context": []},
                       {"technical": "false"}, {"reasons": {}}, {"reasons": [1]}, {"evaluation": []}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.record(**change)
        self.assertEqual(self.store.summaries()["total"], 0)
        for args in ({"limit": 0}, {"limit": 201}, {"after": -1}, {"before": -1}, {"status": "unknown"}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.store.summaries(**args)
        self.assertIsNone(self.store.get("missing"))
        with self.assertRaises(KeyError):
            self.store.decide("missing", "allow")
        with self.assertRaises(ValueError):
            self.store.decide("missing", "approve everything")


if __name__ == "__main__":
    unittest.main()
