"""The diagnostic lab preserves evidence without owning writers or playback."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from rejection_lab import RejectionLabStore, LabConflictError, LabLeaseError


class RejectionLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "lab.sqlite3"
        self.clock = [1000.0]
        self.store = RejectionLabStore(self.path, now=lambda: self.clock[0])

    def begin(self, **changes):
        args = {"review_id": "review-a", "event_seq": 12, "kind": "chat", "request_id": "request-one",
                "payload": {"question": "Why did this exact turn fail?", "baseline_revision": 3},
                "messages": [{"role": "user", "content": "Why did this exact turn fail?"}]}
        args.update(changes)
        return self.store.begin(**args)

    def trial(self):
        return {"baseline": {"source": "The complete original turn.", "candidate": "The refused revision.", "revision": 3},
                "candidate": "A separate complete trial; never substituted into the live script.",
                "evaluation": {"ok": False, "machine_ok": False, "faults": ["meaning drift"]},
                "provenance": {"origin": "isolated_trial", "review_id": "review-a", "event_seq": 12,
                               "source_hash": "original-baseline-hash", "grader_version": 4}}

    def test_discussion_keeps_full_words_scope_and_idempotent_result_across_restart(self):
        content = ("Full original words — keep whitespace.\n\n" * 300) + "FINAL-CONTENT-MARKER"
        start = self.begin(messages=[{"role": "user", "content": content}])
        self.assertTrue(start["claimed"])
        self.assertNotIn("lease_token", start["operation"])
        duplicate = self.begin(messages=[{"role": "user", "content": content}])
        self.assertFalse(duplicate["claimed"])
        self.assertIsNone(duplicate["lease_token"])
        self.assertEqual(duplicate["operation"]["id"], start["operation"]["id"])
        answer = {"answer": "Actual stored answer", "proposals": []}
        result = self.store.finish(start["operation"]["id"], start["lease_token"], result=answer,
                                   messages=[{"role": "assistant", "content": "Actual stored answer"}])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"], answer)
        reopened = RejectionLabStore(self.path, now=lambda: self.clock[0])
        history = reopened.history("review-a", 12)
        self.assertEqual([row["role"] for row in history["items"]], ["user", "assistant"])
        self.assertEqual(history["items"][0]["content"], content)
        self.assertEqual(reopened.get_operation(result["id"])["result"], answer)
        self.assertEqual(reopened.history("review-a", 13)["total"], 0)
        self.assertEqual(reopened.history("another-review", 12)["total"], 0)
        history["items"][0]["content"] = "External mutation"
        self.assertEqual(reopened.history("review-a", 12)["items"][0]["content"], content)

    def test_request_identity_binds_payload_and_initial_message_but_is_scoped_to_occurrence_and_kind(self):
        start = self.begin()
        for change in ({"payload": {"question": "Different expensive work"}},
                       {"messages": [{"role": "user", "content": "Different words"}]}):
            with self.subTest(change=change), self.assertRaises(LabConflictError):
                self.begin(**change)
        for change in ({"event_seq": 13}, {"review_id": "review-b"}, {"kind": "trial"}):
            other = self.begin(**change)
            self.assertTrue(other["claimed"])
            self.assertNotEqual(other["operation"]["id"], start["operation"]["id"])
        self.assertEqual(self.store.history("review-a", 12, "operations")["total"], 2)

    def test_concurrent_store_instances_grant_exactly_one_owner_and_user_message(self):
        stores = [RejectionLabStore(self.path) for _ in range(8)]
        def claim(index):
            return stores[index % len(stores)].begin("review-a", 12, "chat", "same-request", {"question": "One model call"},
                messages=[{"role": "user", "content": "One model call"}])
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(claim, range(32)))
        self.assertEqual(sum(row["claimed"] for row in results), 1)
        self.assertEqual(len({row["operation"]["id"] for row in results}), 1)
        self.assertEqual(self.store.history("review-a", 12)["total"], 1)

    def test_reads_and_restarts_never_reclaim_expired_work_and_explicit_reclaim_fences_old_owner(self):
        first = self.begin(lease_seconds=10)
        self.clock[0] += 11
        reopened = RejectionLabStore(self.path, now=lambda: self.clock[0])
        self.assertTrue(reopened.get_operation(first["operation"]["id"])["lease_expired"])
        self.assertEqual(reopened.history("review-a", 12, "operations")["items"][0]["attempt"], 1)
        same = self.begin(lease_seconds=10)
        self.assertFalse(same["claimed"])
        second = self.begin(lease_seconds=10, reclaim_expired=True)
        self.assertTrue(second["claimed"])
        self.assertNotEqual(second["lease_token"], first["lease_token"])
        self.assertEqual(second["operation"]["attempt"], 2)
        with self.assertRaises(LabLeaseError):
            self.store.finish(first["operation"]["id"], first["lease_token"], result={"late": True})
        with self.assertRaises(LabLeaseError):
            self.store.renew(first["operation"]["id"], first["lease_token"])
        self.store.finish(second["operation"]["id"], second["lease_token"], result={"owner": "second"})
        self.assertEqual(self.store.history("review-a", 12)["total"], 1)

    def test_renewal_keeps_live_owner_and_failed_work_is_not_automatically_retried(self):
        start = self.begin(lease_seconds=10)
        self.clock[0] += 9
        renewed = self.store.renew(start["operation"]["id"], start["lease_token"], lease_seconds=20)
        self.assertEqual(renewed["lease_until"], self.clock[0] + 20)
        self.clock[0] += 11
        failure = self.store.fail(start["operation"]["id"], start["lease_token"], {"message": "The model was unavailable"})
        self.assertEqual(failure["status"], "failed")
        self.assertEqual(self.store.fail(start["operation"]["id"], start["lease_token"], failure["error"]), failure)
        self.assertFalse(self.begin(reclaim_expired=True)["claimed"])
        self.assertEqual(self.store.history("review-a", 12)["total"], 1, "The user's question survives failure")
        with self.assertRaises(LabLeaseError):
            self.store.finish(start["operation"]["id"], start["lease_token"], result={"pretend": "success"})

    def test_trial_receipt_is_immutable_separate_from_baseline_and_has_exact_provenance(self):
        start = self.begin(kind="trial")
        trial = self.trial()
        result = {"summary": "The real grader still refuses this candidate"}
        finished = self.store.finish(start["operation"]["id"], start["lease_token"], result=result, trial=trial)
        self.assertEqual(finished["result"], result)
        stored = self.store.get_trial(finished["trial_id"])
        self.assertEqual(stored["baseline"], trial["baseline"])
        self.assertEqual(stored["candidate"], trial["candidate"])
        self.assertEqual(stored["evaluation"], trial["evaluation"])
        self.assertEqual(stored["provenance"], trial["provenance"])
        self.assertNotIn("applied", stored)
        self.assertEqual(self.store.finish(start["operation"]["id"], start["lease_token"], result=result, trial=trial), finished)
        with self.assertRaises(LabConflictError):
            self.store.finish(start["operation"]["id"], start["lease_token"], result=result,
                              trial={**trial, "candidate": "Another candidate"})
        self.assertEqual(self.store.history("review-a", 12, "trials")["total"], 1)
        stored["baseline"]["source"] = "External overwrite"
        self.assertEqual(RejectionLabStore(self.path).get_trial(finished["trial_id"])["baseline"], trial["baseline"])

    def test_failed_finish_rolls_back_assistant_trial_and_trace_before_status_change(self):
        start = self.begin(kind="trial")
        arguments = {"result": {"answer": "Completed diagnostic"}, "trial": self.trial(),
                     "messages": [{"role": "assistant", "content": "Exact complete diagnosis"}],
                     "traces": [{"trace_id": "actual-pass", "record": {"prompt": "Exact prompt", "response": "Exact answer"}}]}
        with closing(self.store._connect()) as db:
            db.execute("""CREATE TRIGGER refuse_fixture_completion BEFORE UPDATE OF status ON lab_operations
                WHEN NEW.status='completed' BEGIN SELECT RAISE(ABORT,'fixture disk failure'); END""")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "fixture disk failure"):
            self.store.finish(start["operation"]["id"], start["lease_token"], **arguments)
        self.assertEqual(self.store.get_operation(start["operation"]["id"])["status"], "pending")
        self.assertEqual(self.store.history("review-a", 12)["total"], 1)
        self.assertEqual(self.store.history("review-a", 12, "trials")["total"], 0)
        self.assertEqual(self.store.trace_history("actual-pass")["total"], 0)
        with closing(self.store._connect()) as db:
            db.execute("DROP TRIGGER refuse_fixture_completion")
        self.store.finish(start["operation"]["id"], start["lease_token"], **arguments)
        self.assertEqual(self.store.history("review-a", 12)["total"], 2)
        self.assertEqual(self.store.history("review-a", 12, "trials")["total"], 1)
        self.assertEqual(self.store.trace_history("actual-pass")["total"], 1)

    def test_trace_before_rejection_exists_keeps_exact_order_and_distinguishes_reconstruction(self):
        prompt = "SYSTEM exact spacing\n\nUSER: " + "Every prompt word. " * 700
        actual = {"kind": "model_request", "attempt": 1, "prompt": prompt,
                  "request": {"messages": [{"role": "user", "content": prompt}], "temperature": .8},
                  "provenance": {"origin": "captured", "model": "fixture-model"}}
        self.store.append_trace("actual-crystal-pass", actual)
        self.store.append_trace("actual-crystal-pass", {"kind": "model_response", "attempt": 1, "response": "Complete output\nEND"})
        self.store.append_trace("actual-crystal-pass", {"kind": "evaluation", "evaluation": {"machine_ok": False, "faults": ["actual fault"]}})
        self.store.append_trace("separate-pass", {"kind": "reconstructed_prompt", "prompt": "Estimated prior context", "provenance": {"origin": "reconstructed"}})
        traces = RejectionLabStore(self.path).trace_history("actual-crystal-pass")["items"]
        self.assertEqual([row["record"]["kind"] for row in traces], ["model_request", "model_response", "evaluation"])
        self.assertEqual(traces[0]["record"], actual)
        self.assertEqual(traces[1]["record"]["response"], "Complete output\nEND")
        self.assertEqual(self.store.history("review-a", 12, "operations")["total"], 0)
        self.assertEqual(self.store.trace_history("separate-pass")["items"][0]["record"]["provenance"]["origin"], "reconstructed")

    def test_chronological_pages_retain_every_message_trace_and_operation_without_scope_bleed(self):
        for number in range(7):
            start = self.begin(request_id=f"request-{number}", messages=[{"role": "user", "content": f"question {number}"}])
            self.store.finish(start["operation"]["id"], start["lease_token"], result={},
                              messages=[{"role": "assistant", "content": f"answer {number}"}])
            self.store.append_trace("all-ordered-traces", {"number": number})
        def collect(read):
            before, collected = 0, []
            while True:
                page = read(before)
                self.assertEqual([row["seq"] for row in page["items"]], sorted(row["seq"] for row in page["items"]))
                collected = page["items"] + collected
                if not page["has_more"]:
                    break
                before = page["next_before"]
            self.assertEqual(len(collected), len({row["seq"] for row in collected}))
            return collected
        messages = collect(lambda before: self.store.history("review-a", 12, before=before, limit=3))
        self.assertEqual([row["content"] for row in messages], [part for i in range(7) for part in (f"question {i}", f"answer {i}")])
        traces = collect(lambda before: self.store.trace_history("all-ordered-traces", before=before, limit=2))
        self.assertEqual([row["record"]["number"] for row in traces], list(range(7)))
        operations = collect(lambda before: self.store.history("review-a", 12, "operations", before=before, limit=2))
        self.assertEqual(len(operations), 7)
        self.assertTrue(all(row["status"] == "completed" for row in operations))

    def test_oversized_or_invalid_records_are_rejected_without_truncation_or_partial_history(self):
        small = RejectionLabStore(Path(self.temp.name) / "bounded.sqlite3", max_record_bytes=1024)
        for value in ({"prompt": "large " * 1000}, {"prompt": float("nan")}, {"prompt": object()}):
            with self.subTest(value_type=type(value["prompt"]).__name__), self.assertRaises(ValueError):
                small.append_trace("one-pass", value)
        self.assertEqual(small.trace_history("one-pass")["total"], 0)
        for change in ({"event_seq": 0}, {"event_seq": True}, {"review_id": ""},
                       {"lease_seconds": 0}, {"reclaim_expired": "yes"}, {"payload": []},
                       {"messages": [{"role": "unknown", "content": "words"}]},
                       {"messages": [{"role": "user", "content": "words", "event_seq": 99}]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.begin(**change)
        self.assertEqual(self.store.history("review-a", 12, "operations")["total"], 0)

    def test_begin_message_failure_cannot_leave_an_owned_operation_without_its_question(self):
        original = self.store._insert_messages
        def interrupted(*args):
            original(*args)
            raise OSError("simulated journal failure")
        with mock.patch.object(self.store, "_insert_messages", side_effect=interrupted):
            with self.assertRaises(OSError):
                self.begin()
        self.assertEqual(self.store.history("review-a", 12)["total"], 0)
        self.assertEqual(self.store.history("review-a", 12, "operations")["total"], 0)
        self.assertTrue(self.begin()["claimed"])

    def test_settings_require_explicit_revision_and_preserve_exact_additive_instruction(self):
        initial = self.store.settings()
        self.assertFalse(initial["enabled"])
        self.assertEqual(initial["crystal_instruction"], "")
        instruction = "Preserve the original facts.\n\nKeep each complete speaker turn."
        changed = self.store.update_settings(initial["revision"], instruction, True)
        self.assertEqual(changed["revision"], initial["revision"] + 1)
        self.assertEqual(RejectionLabStore(self.path).settings(), changed)
        self.assertEqual(self.store.update_settings(changed["revision"], instruction, True), changed)
        with self.assertRaises(LabConflictError):
            self.store.update_settings(initial["revision"], "Overwrite a newer instruction", False)
        for text, enabled in (("x" * 4001, True), (None, True), (instruction, "true")):
            with self.assertRaises(ValueError):
                self.store.update_settings(changed["revision"], text, enabled)
        self.assertEqual(self.store.settings(), changed)
        self.assertEqual(self.store.history("review-a", 12, "operations")["total"], 0)

    def test_concurrent_settings_updates_allow_only_one_inspected_revision_to_win(self):
        stores = [RejectionLabStore(self.path), RejectionLabStore(self.path)]
        def update(index):
            try:
                return stores[index].update_settings(1, f"Explicit instruction {index}", True)
            except LabConflictError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(update, range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.store.settings()["revision"], 2)

    def test_failed_result_trace_is_durable_immutable_and_owned_without_changing_old_callers(self):
        claim = self.begin()
        operation_id, owner = claim['operation']['id'], claim['lease_token']
        result = {'trace_id': 'failed-model-run', 'diagnostic': {'step': 'model_error'}}
        failed = self.store.fail(operation_id, owner, 'Model timed out.', result=result)
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['result'], result)
        reopened = RejectionLabStore(self.path, now=lambda: self.clock[0])
        self.assertEqual(reopened.get_operation(operation_id), failed)
        self.assertEqual(reopened.fail(operation_id, owner, 'Model timed out.', result=result), failed)
        result['diagnostic']['step'] = 'mutated caller input'
        for changed_error, changed_result in [('Another failure.', failed['result']),
                                              ('Model timed out.', {'trace_id': 'another-run'}),
                                              ('Model timed out.', None)]:
            with self.subTest(error=changed_error, result=changed_result), self.assertRaises(LabConflictError):
                reopened.fail(operation_id, owner, changed_error, result=changed_result)
        with self.assertRaises(LabLeaseError):
            reopened.fail(operation_id, 'wrong-owner', 'Model timed out.', result=failed['result'])
        self.assertEqual(reopened.get_operation(operation_id), failed)
        legacy = self.store.begin('review-a', 12, 'chat', 'legacy-failure', {})
        legacy_failed = self.store.fail(legacy['operation']['id'], legacy['lease_token'], 'Older caller.')
        self.assertIsNone(legacy_failed['result'])
        self.assertEqual(self.store.fail(legacy['operation']['id'], legacy['lease_token'], 'Older caller.'), legacy_failed)

    def test_direct_request_lookup_finds_old_receipts_without_history_or_scope_leaks(self):
        original = self.begin()
        operation_id = original['operation']['id']
        completed = self.store.finish(operation_id, original['lease_token'], result={'answer': 'Stored answer.'})
        for index in range(105):
            self.store.begin('review-a', 12, 'chat', f'newer-{index}', {})
        before = self.store.history('review-a', 12, 'operations')['total']
        self.assertNotIn(operation_id, [row['id'] for row in self.store.history('review-a', 12, 'operations', limit=100)['items']])
        with mock.patch.object(self.store, 'history', side_effect=AssertionError('Exact lookup must not scan pages')):
            found = self.store.find_request('review-a', 12, 'chat', original['operation']['request_id'])
            self.assertEqual(found, completed)
            self.assertNotIn('lease_token', found)
            for scope in [('other-review', 12, 'chat'), ('review-a', 13, 'chat'), ('review-a', 12, 'try')]:
                self.assertIsNone(self.store.find_request(*scope, original['operation']['request_id']))
            self.assertIsNone(self.store.find_request('review-a', 12, 'chat', 'missing'))
            for args in [('', 12, 'chat', 'id'), ('review-a', True, 'chat', 'id'),
                         ('review-a', 12, '', 'id'), ('review-a', 12, 'chat', '')]:
                with self.subTest(args=args), self.assertRaises(ValueError):
                    self.store.find_request(*args)
        self.assertEqual(self.store.history('review-a', 12, 'operations')['total'], before)
        self.assertEqual(self.store.get_operation(operation_id), completed)

    def test_invalid_pagination_does_not_silently_expand_or_cross_history(self):
        for args in ({"before": -1}, {"before": True}, {"limit": 0}, {"limit": 201}, {"limit": "50"}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.store.history("review-a", 12, **args)
            with self.subTest(trace_args=args), self.assertRaises(ValueError):
                self.store.trace_history("trace-a", **args)
        with self.assertRaises(ValueError):
            self.store.history("review-a", 12, "untrusted table")
        self.assertIsNone(self.store.get_trial("missing"))
        self.assertIsNone(self.store.get_operation("missing"))


if __name__ == "__main__":
    unittest.main()
