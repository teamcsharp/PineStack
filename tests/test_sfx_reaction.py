import unittest

from sfx_reaction import COMPLAINT_LINES, complaint_after_heard_clip, complaint_due


class SfxReactionTests(unittest.TestCase):
    def setUp(self):
        self.clip = {"id": "board-row-1", "who": "board", "kind": "sfx",
                     "aired": "stream"}

    def test_one_in_three_boundary_uses_injected_roll(self):
        self.assertTrue(complaint_due(lambda: 0.0))
        self.assertTrue(complaint_due(lambda: 1.0 / 3.0 - 0.000001))
        self.assertFalse(complaint_due(lambda: 1.0 / 3.0))
        self.assertFalse(complaint_due(lambda: 0.99))

    def test_no_receipt_means_no_roll_or_complaint(self):
        def should_not_roll():
            self.fail("A clip without audible evidence must not roll")

        self.assertIsNone(complaint_after_heard_clip(
            self.clip, heard_ids=set(), prior_speaker="dj",
            random_float=should_not_roll))

    def test_omitted_withdrawn_and_muted_clips_never_react(self):
        for state in ("omitted", "withdrawn", "never", "muted"):
            with self.subTest(state=state):
                self.assertIsNone(complaint_after_heard_clip(
                    {**self.clip, "aired": state}, heard_ids={self.clip["id"]},
                    prior_speaker="dj",
                    random_float=lambda: self.fail("A missed clip must not roll")))

    def test_only_host_following_board_sfx_can_react(self):
        for changed in ({"who": "dj"}, {"kind": "station_id"}, {"id": ""}):
            with self.subTest(changed=changed):
                self.assertIsNone(complaint_after_heard_clip(
                    {**self.clip, **changed}, heard_ids={self.clip["id"]},
                    prior_speaker="dj", random_float=lambda: 0.0))
        self.assertIsNone(complaint_after_heard_clip(
            self.clip, heard_ids={self.clip["id"]}, prior_speaker="caller",
            random_float=lambda: 0.0))

    def test_heard_board_clip_can_get_preauthored_opposite_host_reply(self):
        first = complaint_after_heard_clip(
            self.clip, heard_ids={self.clip["id"]}, prior_speaker="dj",
            random_float=lambda: 0.0)
        self.assertEqual(first["who"], "cohost")
        self.assertEqual(first["after_clip_id"], self.clip["id"])
        self.assertIn(first["text"], COMPLAINT_LINES)
        self.assertEqual(first, complaint_after_heard_clip(
            self.clip, heard_ids={self.clip["id"]}, prior_speaker="dj",
            random_float=lambda: 0.0))
        self.assertEqual(complaint_after_heard_clip(
            self.clip, heard_ids={self.clip["id"]}, prior_speaker="cohost",
            random_float=lambda: 0.0)["who"], "dj")

    def test_losing_roll_returns_no_cue_without_changing_inputs(self):
        clip_before = dict(self.clip)
        heard_ids = {self.clip["id"]}
        self.assertIsNone(complaint_after_heard_clip(
            self.clip, heard_ids=heard_ids, prior_speaker="dj",
            random_float=lambda: 0.8))
        self.assertEqual(self.clip, clip_before)
        self.assertEqual(heard_ids, {self.clip["id"]})


if __name__ == "__main__":
    unittest.main()
