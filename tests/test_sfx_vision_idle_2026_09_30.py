"""[sfx-vision-idle] the SFX Guy studies frames of his clips while the station rests."""
import unittest

import sfx_vision_idle as v


class Answers(unittest.TestCase):
    def test_the_two_line_answer(self):
        desc, tags = v.parse_answer("DESCRIPTION: A man yells at a parked car at night.\n"
                                    "TAGS: man, yelling, car, night, street, Angry")
        self.assertEqual(desc, "A man yells at a parked car at night.")
        self.assertEqual(tags, ["man", "yelling", "car", "night", "street", "angry"])

    def test_a_model_that_ignores_the_format_still_gives_tags(self):
        desc, tags = v.parse_answer("dog, beach, running, sunset")
        self.assertEqual(desc, "")
        self.assertEqual(tags, ["dog", "beach", "running", "sunset"])

    def test_markdown_and_duplicates_are_cleaned(self):
        _d, tags = v.parse_answer("**TAGS:** - crowd; crowd, * neon lights *, " + "x" * 80)
        self.assertEqual(tags, ["crowd", "neon lights"])

    def test_merge_ranks_shared_tags_first_and_keeps_old_words(self):
        frames = [{"tags": ["man", "car"]}, {"tags": ["car", "night"]}, {"tags": ["car", "man"]}]
        self.assertEqual(v.merge_seen(frames, "hand written, man"), "car, man, night, hand written")

    def test_merge_is_bounded(self):
        frames = [{"tags": ["tag%03d" % i for i in range(200)]}]
        self.assertLessEqual(len(v.merge_seen(frames)), v.SEEN_MOST)


if __name__ == "__main__":
    unittest.main()
