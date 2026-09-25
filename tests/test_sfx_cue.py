import unittest

from sfx_cue import CueCandidate, choose_due_cue


class SfxCueChoiceTests(unittest.TestCase):
    def setUp(self):
        self.pool = (
            CueCandidate("video", 12.0, True),
            CueCandidate("audio", 8.0, False),
        )

    def choose(self, pool=None, draw=0.0, **kwargs):
        return choose_due_cue(
            self.pool if pool is None else pool,
            max_seconds=15.0,
            random_float=lambda: draw,
            pick=lambda keys: keys[0],
            **kwargs,
        )

    def test_exact_eighty_twenty_draw_per_due_cue(self):
        choices = [self.choose(draw=i / 100) for i in range(100)]
        self.assertEqual(sum(choice.video for choice in choices), 80)
        self.assertEqual(sum(not choice.video for choice in choices), 20)
        self.assertTrue(self.choose(draw=0.799).video)
        self.assertFalse(self.choose(draw=0.8).video)

    def test_operator_video_share_overrides_default(self):
        choices = [self.choose(draw=i / 100, video_share=0.25) for i in range(100)]
        self.assertEqual(sum(choice.video for choice in choices), 25)

    def test_empty_requested_side_falls_back_to_available_side(self):
        choice = self.choose(pool=self.pool[1:], draw=0.1)
        self.assertEqual(choice.key, "audio")
        self.assertTrue(choice.requested_video)
        self.assertFalse(choice.video)
        choice = self.choose(pool=self.pool[:1], draw=0.9)
        self.assertEqual(choice.key, "video")
        self.assertFalse(choice.requested_video)

    def test_constraints_are_applied_before_match_and_pick(self):
        pool = (
            CueCandidate("barred", 3.0, True, eligible=False),
            CueCandidate("long", 16.0, True),
            CueCandidate("zero", 0.0, True),
            CueCandidate("nan", float("nan"), True),
            CueCandidate("valid", 12.0, True),
        )
        seen = []

        def match(line, keys):
            seen.append((line, keys))
            return "long"

        choice = choose_due_cue(
            pool, max_seconds=15.0, random_float=lambda: 0.1,
            pick=lambda keys: keys[0], preceding_line="A door opens.",
            semantic_enabled=True, match=match,
        )
        self.assertEqual(seen, [("A door opens.", ("valid",))])
        self.assertEqual((choice.key, choice.source), ("valid", "random"))

    def test_semantic_wins_only_on_chosen_side(self):
        seen = []

        def match(line, keys):
            seen.append((line, keys))
            return keys[-1]

        pool = (CueCandidate("video-a", 4.0, True),
                CueCandidate("video-b", 5.0, True), self.pool[1])
        choice = self.choose(pool=pool, preceding_line="A train arrives.",
                             semantic_enabled=True, match=match)
        self.assertEqual((choice.key, choice.source), ("video-b", "semantic"))
        self.assertEqual(seen, [("A train arrives.", ("video-a", "video-b"))])

    def test_disabled_or_blank_match_uses_random_pick(self):
        def fail(*_args):
            self.fail("matcher should not run")

        self.assertEqual(self.choose(match=fail).source, "random")
        self.assertEqual(self.choose(match=fail, semantic_enabled=True,
                                     preceding_line="  ").source, "random")

    def test_match_failure_and_unpickable_side_fall_back(self):
        offered = []

        def pick(keys):
            offered.append(keys)
            return None if keys == ("video",) else keys[0]

        choice = choose_due_cue(
            self.pool, max_seconds=15.0, random_float=lambda: 0.1,
            pick=pick, preceding_line="hello", semantic_enabled=True,
            match=lambda _line, _keys: (_ for _ in ()).throw(RuntimeError()),
        )
        self.assertEqual((choice.key, choice.video), ("audio", False))
        self.assertEqual(offered, [("video",), ("audio",)])

    def test_invalid_picker_result_cannot_escape_offered_pool(self):
        choice = choose_due_cue(
            self.pool, max_seconds=15.0, random_float=lambda: 0.0,
            pick=lambda keys: "barred" if keys == ("video",) else keys[0],
        )
        self.assertEqual(choice.key, "audio")

    def test_no_eligible_cue_does_not_draw(self):
        choice = choose_due_cue(
            [CueCandidate("too-long", 99.0, True)], max_seconds=15.0,
            random_float=lambda: self.fail("should not draw"),
            pick=lambda _keys: self.fail("should not pick"),
        )
        self.assertIsNone(choice)

    def test_invalid_rng_or_cap_is_rejected(self):
        with self.assertRaises(ValueError):
            self.choose(draw=1.0)
        with self.assertRaises(ValueError):
            choose_due_cue(self.pool, max_seconds=0.0,
                           random_float=lambda: 0.0, pick=lambda keys: keys[0])


if __name__ == "__main__":
    unittest.main()
