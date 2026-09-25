"""Duration and room readiness contracts without importing the live station."""

import unittest

from segment_contract import (build_segment_contract, evaluate_segment_contract,
                              preparation_tasks)


class SegmentLengthReadinessTests(unittest.TestCase):
    def test_record_carrier_needs_playback_but_no_script(self):
        contract = build_segment_contract({"kind": "record", "owns_seconds": 240})
        coverage = evaluate_segment_contract(contract, [{"playable_seconds": 240}])
        tasks = {row["room"]: row for row in preparation_tasks(contract, coverage)}
        self.assertTrue(coverage["ready"])
        self.assertTrue(tasks["writing"]["ready"])
        self.assertEqual(tasks["writing"]["want_seconds"], 0)
        self.assertTrue(tasks["recording"]["ready"])

    def test_track_talk_is_two_bookends_not_turns_scaled_to_record_length(self):
        contract = build_segment_contract({"kind": "record", "road": "track_talk",
                                           "owns_seconds": 240})
        self.assertEqual(contract["minimum_turns"], 2)
        self.assertEqual(contract["minimum_events"], 2)
        self.assertEqual(contract["speech_seconds"], 0)
        supply = {"scripted_seconds": 2, "recorded_seconds": 2,
                  "playable_seconds": 240, "roles": ["dj"],
                  "turns": 2, "events": 2,
                  "bookends": {"intro": {"written": True, "recorded": True},
                               "outro": {"written": True, "recorded": True}}}
        complete = evaluate_segment_contract(contract, [supply])
        self.assertTrue(complete["ready"], complete)
        self.assertTrue(all(row["ready"] for row in
                            preparation_tasks(contract, complete)))
        one_side = evaluate_segment_contract(contract, [dict(supply, turns=1,
                                                              events=1)])
        self.assertFalse(one_side["ready"])
        self.assertEqual(one_side["missing_turns"], 1)
        self.assertEqual(one_side["missing_events"], 1)
        no_host = evaluate_segment_contract(contract, [dict(supply, roles=["caller"])])
        self.assertFalse(no_host["ready"])
        missing_take = evaluate_segment_contract(contract, [dict(
            supply, bookends={"intro": {"written": True, "recorded": True},
                              "outro": {"written": True, "recorded": False}})])
        self.assertFalse(missing_take["ready"])
        self.assertEqual(missing_take["missing_recorded_bookends"], ["outro"])
        tasks = {row["room"]: row for row in preparation_tasks(contract, missing_take)}
        self.assertTrue(tasks["writing"]["ready"])
        self.assertFalse(tasks["recording"]["ready"])
        self.assertEqual(tasks["recording"]["want_seconds"], 8)
        missing_script = evaluate_segment_contract(contract, [dict(
            supply, bookends={"intro": {"written": True, "recorded": True}})])
        self.assertEqual(missing_script["missing_bookends"], ["outro"])
        self.assertGreater(missing_script["script_short_seconds"], 1)
        self.assertEqual(preparation_tasks(contract, missing_script)[1]["want_seconds"], 8)

    def test_speech_and_actual_body_both_have_to_cover_banter_slot(self):
        contract = build_segment_contract({"kind": "banter", "owns_seconds": 120})
        base = {"scripted_seconds": 120, "recorded_seconds": 120,
                "playable_seconds": 120, "roles": ["dj", "cohost"],
                "turns": contract["minimum_turns"], "events": 2}
        self.assertTrue(evaluate_segment_contract(contract, [base])["ready"])
        thin = evaluate_segment_contract(contract, [dict(base, scripted_seconds=20,
                                                        recorded_seconds=20)])
        self.assertFalse(thin["ready"])
        self.assertGreater(thin["script_short_seconds"], 80)
        self.assertGreater(thin["recording_short_seconds"], 80)
        stale = evaluate_segment_contract(contract, [dict(base, body_frames=60_000,
                                                          speech_frames=60_000,
                                                          sample_rate=1000)])
        self.assertFalse(stale["ready"])
        self.assertEqual(stale["playable_seconds"], 60)
        self.assertEqual(stale["recorded_seconds"], 60)
        self.assertGreater(stale["duration_short_seconds"], 50)
        capped = evaluate_segment_contract(contract, [dict(
            base, body_frames=120_000, speech_frames=120_000,
            sample_rate=1000, playable_seconds=60)])
        self.assertEqual(capped["playable_seconds"], 60)
        self.assertFalse(capped["ready"])

    def test_full_length_dialogue_with_too_few_turns_still_owes_writing(self):
        contract = build_segment_contract({"kind": "gallery", "owns_seconds": 240})
        coverage = evaluate_segment_contract(contract, [{
            "scripted_seconds": 240, "recorded_seconds": 240,
            "playable_seconds": 240, "roles": ["dj", "cohost"],
            "turns": 5, "events": 5}])
        self.assertEqual(coverage["duration_short_seconds"], 0)
        self.assertEqual(coverage["missing_turns"], 11)
        self.assertEqual(coverage["writing_structure_short_seconds"], 24)
        writing = next(row for row in preparation_tasks(contract, coverage)
                       if row["room"] == "writing")
        self.assertEqual(writing["want_seconds"], 24)

    def test_fully_recorded_natural_dialogue_passes_word_and_turn_tolerance(self):
        contract = build_segment_contract({"kind": "gallery", "owns_seconds": 240})
        coverage = evaluate_segment_contract(contract, [{
            "scripted_seconds": 237.9, "recorded_seconds": 239.97,
            "playable_seconds": 240, "roles": ["dj", "cohost"],
            "turns": 19, "events": 19}])
        self.assertEqual(contract["minimum_turns"], 16)
        self.assertEqual(contract["minimum_speech_seconds"], 216)
        self.assertTrue(coverage["ready"], coverage)

    def test_manager_memo_is_read_by_pair_not_a_third_recorded_voice(self):
        contract = build_segment_contract({"kind": "manager", "owns_seconds": 240})
        self.assertEqual(contract["required_roles"], ["dj", "cohost"])
        coverage = evaluate_segment_contract(contract, [{
            "scripted_seconds": 240, "recorded_seconds": 240,
            "playable_seconds": 240, "roles": ["dj", "cohost"],
            "turns": contract["minimum_turns"], "events": 3}])
        self.assertTrue(coverage["ready"], coverage)

    def test_measured_full_speech_can_clear_small_word_rate_error(self):
        contract = build_segment_contract({"kind": "caller", "owns_seconds": 180})
        coverage = evaluate_segment_contract(contract, [{
            "scripted_seconds": 158.4, "recorded_seconds": 180,
            "playable_seconds": 180, "roles": ["dj", "cohost", "caller"],
            "turns": contract["minimum_turns"], "events": 2}])
        self.assertTrue(coverage["ready"], coverage)
        writing = next(row for row in preparation_tasks(contract, coverage)
                       if row["room"] == "writing")
        self.assertTrue(writing["ready"])

    def test_long_single_reads_need_duration_not_extra_speakers(self):
        for road in ("ad", "news", "station_id"):
            with self.subTest(road=road):
                contract = build_segment_contract({"road": road,
                                                   "owns_seconds": 120})
                self.assertEqual(contract["minimum_turns"], 1)
                self.assertEqual(contract["minimum_events"], 1)
                supply = {"scripted_seconds": 120, "recorded_seconds": 120,
                          "playable_seconds": 120, "roles": ["talent"],
                          "turns": 1, "events": 1}
                self.assertTrue(evaluate_segment_contract(contract, [supply])["ready"])
                short = evaluate_segment_contract(contract, [dict(
                    supply, scripted_seconds=20, recorded_seconds=20)])
                self.assertFalse(short["ready"])
                self.assertGreater(short["script_short_seconds"], 80)


if __name__ == "__main__":
    unittest.main()
