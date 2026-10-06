"""Recovery policy regressions; no station import or live state is required."""
import copy
import json
import random
import unittest

from dialogue_recovery import (
    DEFAULT_RECOVERY, begin_attempt, note_deferred, note_failure, note_success,
    pick_recovery_candidate, recovery_state, rejection_key,
)


class FixedRandom:
    def __init__(self, draw=0.0):
        self.draw = draw

    def random(self):
        return self.draw

    def getrandbits(self, _bits):
        return 7


class DialogueRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.container = {}
        self.state = recovery_state(self.container)

    def fail_attempt(self, now, reason="handoff rows must align", rng=None):
        attempt = begin_attempt(self.state, now, rng=rng)
        self.assertTrue(attempt["allow"])
        note_failure(self.state, reason, now + 1)
        return attempt

    def test_initialization_is_json_compatible_and_policy_is_choice_local(self):
        self.assertIs(recovery_state(self.container), self.state)
        json.dumps(self.container)
        other = recovery_state({})
        self.state["policy"]["cooldown_seconds"] = 90
        self.assertEqual(other["policy"]["cooldown_seconds"], 60)
        self.assertEqual(DEFAULT_RECOVERY["cooldown_seconds"], 60)
        self.assertIsNot(other["trace"], self.state["trace"])

    def test_three_different_operations_then_cooldown_and_continued_escalation(self):
        attempts = [self.fail_attempt(t) for t in (10, 20, 30)]
        self.assertEqual([a["operation"] for a in attempts], ["repair", "rewrite", "reroll"])
        before = copy.deepcopy(self.state)
        denied = begin_attempt(self.state, 90)
        self.assertFalse(denied["allow"])
        self.assertEqual(denied["cooldown_until"], 91)
        self.assertEqual(self.state, before)
        resumed = begin_attempt(self.state, 91)
        self.assertEqual((resumed["pass"], resumed["attempt"], resumed["operation"]),
                         (2, 1, "rebuild"))
        self.assertEqual(self.state["operations_in_pass"], ["rebuild"])

    def test_cooldown_is_measured_from_failure_not_production_start(self):
        self.fail_attempt(10)
        self.fail_attempt(20)
        self.assertTrue(begin_attempt(self.state, 30)["allow"])
        note_failure(self.state, "handoff rows must align", 600)
        self.assertFalse(begin_attempt(self.state, 659)["allow"])
        self.assertTrue(begin_attempt(self.state, 660)["allow"])

    def test_identical_rejection_twice_marks_stuck_and_new_reason_breaks_streak(self):
        note_failure(self.state, "  Rows   must align ", 0)
        self.assertFalse(self.state["stuck"])
        note_failure(self.state, "rows must ALIGN", 1)
        self.assertTrue(self.state["stuck"])
        self.assertEqual(self.state["same_reason_count"], 2)
        note_failure(self.state, "speaker identity missing", 2)
        self.assertFalse(self.state["stuck"])
        self.assertEqual(self.state["same_reason_count"], 1)
        note_failure(self.state, "", 3)
        note_failure(self.state, "", 4)
        self.assertFalse(self.state["stuck"])

    def test_overlap_is_blocked_and_rejected_call_does_not_reserve_another_operation(self):
        first = begin_attempt(self.state, 0)
        self.assertTrue(first["allow"])
        blocked = begin_attempt(self.state, 299)
        self.assertFalse(blocked["allow"])
        self.assertIn("in progress", blocked["reason"])
        self.assertEqual(self.state["total_attempts"], 1)
        note_failure(self.state, "refused", 299)
        self.assertEqual(begin_attempt(self.state, 300)["operation"], "rewrite")

    def test_expired_owner_can_reenter_and_late_old_outcomes_are_ignored(self):
        first = begin_attempt(self.state, 100)
        self.assertFalse(begin_attempt(self.state, 399)["allow"])
        second = begin_attempt(self.state, 400)
        self.assertTrue(second["allow"])
        self.assertEqual(second["operation"], "rewrite")
        self.assertEqual(self.state["failures"], 1)
        before = copy.deepcopy(self.state)
        note_success(self.state, 401, variation_id=first["variation_id"])
        note_failure(self.state, "late old rejection", 401, variation_id=first["variation_id"])
        note_deferred(self.state, 401, variation_id=first["variation_id"])
        self.assertEqual(self.state, before)
        note_success(self.state, 402, variation_id=second["variation_id"])
        self.assertFalse(self.state["in_flight"])

    def test_old_persisted_owner_without_start_time_cannot_wedge_forever(self):
        begin_attempt(self.state, 100)
        self.state["started_at"] = None
        self.assertTrue(begin_attempt(self.state, 101)["allow"])

    def test_model_admission_deferral_refunds_operation_without_failure_or_seed_reuse(self):
        first = begin_attempt(self.state, 100, rng=FixedRandom())
        note_deferred(self.state, 101, variation_id=first["variation_id"])
        self.assertEqual(self.state["failures"], 0)
        self.assertEqual(self.state["attempt"], 0)
        self.assertEqual(self.state["operations_in_pass"], [])
        self.assertFalse(self.state["in_flight"])
        second = begin_attempt(self.state, 102, rng=FixedRandom())
        self.assertEqual(second["operation"], "repair")
        self.assertNotEqual(second["seed"], first["seed"])
        note_failure(self.state, "handoff mismatch", 103)
        third = begin_attempt(self.state, 104)
        note_deferred(self.state, 105)
        self.assertTrue(self.state["active"])
        self.assertEqual(self.state["attempt"], 1)
        self.assertEqual(begin_attempt(self.state, 106)["operation"], third["operation"])

    def test_changing_ids_and_numbers_do_not_hide_repeated_logical_rejections(self):
        reason_a = "conversation_id=conv-a23: turn 4 expected 3 rows; error 502"
        reason_b = "conversation_id=conv-b94: turn 7 expected 5 rows; error 503"
        self.assertEqual(rejection_key(reason_a), rejection_key(reason_b))
        note_failure(self.state, reason_a, 0)
        note_failure(self.state, reason_b, 1)
        self.assertTrue(self.state["stuck"])
        self.assertEqual(self.state["last_reason"], reason_b)
        note_failure(self.state, "conversation_id=conv-b95: speaker missing", 2)
        self.assertFalse(self.state["stuck"])
        self.assertEqual(rejection_key("request 550e8400-e29b-41d4-a716-446655440000 rows invalid"),
                         rejection_key("request 550e8400-e29b-41d4-a716-446655440001 rows invalid"))

    def test_random_is_reproducible_and_seed_stays_fresh_even_with_constant_rng(self):
        left, right = recovery_state({}), recovery_state({})
        a = begin_attempt(left, 100, rng=random.Random(123))
        b = begin_attempt(right, 100, rng=random.Random(123))
        self.assertEqual(a, b)
        rng = FixedRandom()
        seeds, topics, variations = set(), set(), set()
        now = 0
        for i in range(120):
            attempt = begin_attempt(self.state, now, rng=rng)
            self.assertTrue(attempt["allow"])
            seeds.add(attempt["seed"])
            topics.add(attempt["topic_seed"])
            variations.add(attempt["variation_id"])
            note_failure(self.state, "same refusal", now)
            now = max(now + 1, self.state["cooldown_until"])
        self.assertEqual(len(seeds), 120)
        self.assertEqual(len(topics), 120)
        self.assertEqual(len(variations), 120)
        self.assertLessEqual(len(self.state["trace"]), 32)

    def test_every_pass_is_distinct_and_there_is_no_lifetime_retry_cap(self):
        now = 0
        for pass_number in range(1, 11):
            operations = []
            for _ in range(3):
                attempt = self.fail_attempt(now)
                operations.append(attempt["operation"])
                self.assertEqual(attempt["pass"], pass_number)
                now += 2
            self.assertEqual(len(set(operations)), 3)
            now = self.state["cooldown_until"]
        self.assertEqual(self.state["total_attempts"], 30)

    def test_style_relaxation_is_gradual_and_preserves_speakers_character_coherence(self):
        expected = {0: [], 2: ["rhyme"], 4: ["rhyme", "length"],
                    6: ["rhyme", "length", "style"]}
        now = 0
        for failures in range(7):
            attempt = begin_attempt(self.state, now)
            self.assertTrue(attempt["allow"])
            if failures in expected:
                self.assertEqual(attempt["relax"], expected[failures])
                for key in ("preserve_speakers", "preserve_character", "preserve_coherence"):
                    self.assertTrue(attempt[key])
            if failures < 6:
                note_failure(self.state, "creative rejection", now + 1)
                now = max(now + 2, self.state["cooldown_until"])
        note_success(self.state, now + 1)

    def test_success_clears_failure_state_without_repeating_seed_or_discarding_audit(self):
        first = self.fail_attempt(10, rng=FixedRandom())
        self.fail_attempt(20, rng=FixedRandom())
        self.fail_attempt(30, rng=FixedRandom())
        note_success(self.state, 50)
        self.assertFalse(self.state["active"])
        self.assertFalse(self.state["stuck"])
        self.assertFalse(self.state["in_flight"])
        self.assertEqual(self.state["failures"], 0)
        self.assertEqual(self.state["cooldown_until"], 0)
        self.assertEqual(self.state["style_level"], 0)
        self.assertIsNone(self.state["first_failure_at"])
        self.assertEqual(self.state["trace"][-1]["event"], "success")
        again = begin_attempt(self.state, 51, rng=FixedRandom())
        self.assertEqual(again["operation"], "repair")
        self.assertNotEqual(again["seed"], first["seed"])

    def test_disabled_policy_and_nonfinite_times_cannot_schedule(self):
        state = recovery_state({}, {"enabled": False})
        self.assertFalse(begin_attempt(state, 100)["allow"])
        for now in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                begin_attempt(self.state, now)
        with self.assertRaises(ValueError):
            recovery_state({}, {"attempts_per_pass": 5})


class RecoveryRouletteTests(unittest.TestCase):
    def candidate(self, name, failures=0, **changes):
        candidate = {"name": name, **changes}
        state = recovery_state(candidate)
        for _ in range(failures):
            note_failure(state, "rejected", 0)
        return candidate

    def test_recovering_choices_alternate_with_normal_and_input_is_unchanged(self):
        failed = self.candidate("failed", failures=2)
        normal = self.candidate("normal")
        candidates = [failed, normal]
        before = copy.deepcopy(candidates)
        recovered = pick_recovery_candidate(candidates, False, 100, FixedRandom())
        ordinary = pick_recovery_candidate(candidates, True, 100, FixedRandom())
        self.assertIs(recovered, failed)
        self.assertIs(ordinary, normal)
        self.assertEqual(candidates, before)

    def test_only_recovery_work_can_keep_running_when_no_normal_work_is_available(self):
        failed = self.candidate("failed", failures=1)
        self.assertIs(pick_recovery_candidate([failed], True, 100), failed)

    def test_cooldown_disabled_inflight_and_future_items_cannot_starve_runnable_work(self):
        cooling = self.candidate("cooling", failures=3)
        cooling["dialogue_recovery"]["cooldown_until"] = 101
        disabled = self.candidate("disabled", failures=1)
        disabled["dialogue_recovery"]["policy"]["enabled"] = False
        inflight = self.candidate("inflight", failures=1)
        inflight["dialogue_recovery"]["in_flight"] = True
        inflight["dialogue_recovery"]["started_at"] = 1
        unavailable = self.candidate("unavailable", failures=1, runnable=False)
        future = self.candidate("future", failures=1, ready_at=200)
        normal = self.candidate("normal")
        blocked = [cooling, disabled, inflight, unavailable, future]
        self.assertIsNone(pick_recovery_candidate(blocked, False, 100))
        self.assertIs(pick_recovery_candidate(blocked + [normal], False, 100), normal)
        self.assertIs(pick_recovery_candidate([cooling, normal], False, 101), cooling)

    def test_expired_inflight_owner_returns_to_roulette_after_lease(self):
        candidate = self.candidate("stale", failures=1)
        begin_attempt(candidate["dialogue_recovery"], 100)
        self.assertIsNone(pick_recovery_candidate([candidate], False, 399))
        self.assertIs(pick_recovery_candidate([candidate], False, 400), candidate)

    def test_failure_and_aging_raise_weight_but_boost_is_capped(self):
        fresh = self.candidate("fresh", failures=1)
        old = self.candidate("old", failures=1)
        fresh["dialogue_recovery"]["first_failure_at"] = 1200
        old["dialogue_recovery"]["first_failure_at"] = 0
        # At 1200, weights are 3 and 7: a 40% draw crosses fresh's weight.
        self.assertIs(pick_recovery_candidate([fresh, old], False, 1200, FixedRandom(.4)), old)
        # More failures beyond the cap cannot keep pushing the second weight.
        equal = self.candidate("equal", failures=3)
        excessive = self.candidate("excessive", failures=10000)
        self.assertIs(pick_recovery_candidate([equal, excessive], False, 0,
                                             FixedRandom(.49)), equal)
        self.assertIs(pick_recovery_candidate([equal, excessive], False, 0,
                                             FixedRandom(.51)), excessive)

    def test_failed_at_zero_is_still_recovery_and_success_returns_it_to_normal(self):
        candidate = self.candidate("failed", failures=1)
        normal = self.candidate("normal")
        self.assertIs(pick_recovery_candidate([candidate, normal], False, 10,
                                             FixedRandom()), candidate)
        note_success(candidate["dialogue_recovery"], 10)
        self.assertIs(pick_recovery_candidate([candidate, normal], True, 10,
                                             FixedRandom()), candidate)


if __name__ == "__main__":
    unittest.main()
