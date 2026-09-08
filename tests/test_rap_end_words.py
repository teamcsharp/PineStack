"""#1076: bars that land on a pronoun, a silent-e plural or an unstressed -y.

Six hours of the review journal held 307 refused bars; 36 of them were
rhymes the rap reading refused for one of three spelling reasons - the
landing word sat in the stop list ("imagine that", "way through / for
you", "by and by"), a silent e before a plural counted as a syllable
("seems / schemes"), or a final unstressed -y was read as the vowel of
"sky" ("plain to see / a century"). These are the exact bars off the
journal; the prose controls are the exact sources they were written from.
The grader's version is unchanged: the reading only accepts more.
"""
import unittest

import app

LANDED = [
    "When I say it's done, let's chat; Give a big answer, imagine that",
    "Balanced, it seems; But what we balancing in these schemes?",
    "Tear it down, yeah; that's the only way through; Just gotta let heat build "
    "until the whole thing changes shape for you",
    "When that busted ice machine caught your eye; What did you do next, and what "
    "changed by and by?",
    "L makes sense now, it's plain to see; Why Thor's favor lasted a century",
    "I'll recite what she penned, let it be; can you spot the problem? Do we agree?",
    "Not just a small thing, no; Always twisted, smells like a setup show",
    "It ain't our abilities that show who we be; just a mask on the face, not the "
    "true degree",
]
PROSE = [
    "The dialogue explored concepts of patience and waiting; time lets you find a "
    "deeper state; hosts noted how music guides the listener; right there in the moment.",
    "I don't know the specifics right now, but I feel like this whole situation is "
    "about more than just some misplaced items; it feels like a bigger game is being "
    "played in my neighborhood.",
    "Specifics unknown right now, but I feel a scheme; More than misplaced items; "
    "my neighborhood's a bigger game",
    "We went to the store and then we saw a",
    # The operator's pinned controls (tests/test_crystal_whole_resume.py,
    # tests/test_tint_rhyme.py) stay refused with the wider landings.
    "I stay near, Have no fear",
    "The red gate; Seven copper plates",
    "When you saw the sliding magnets, what did you do next, and what shifted after that?",
    "Hello, this is Maxine Brown, calling from a car behind the store with rain on the roof.",
]


class RapEndWords(unittest.TestCase):
    def test_landings_on_function_words_count(self):
        for bar in LANDED:
            with self.subTest(bar=bar):
                self.assertTrue(app.rap_rhyme_evidence(bar)["ok"], bar)

    def test_prose_is_still_refused(self):
        for text in PROSE:
            with self.subTest(text=text):
                self.assertFalse(app.rap_rhyme_evidence(text)["ok"], text)

    def test_articles_cannot_land(self):
        self.assertEqual(app._rap_end("we go to the"), "go")
        self.assertEqual(app._rap_end("imagine that"), "that")
        self.assertFalse(app._rap_slant("the", "be", end=True))
        self.assertFalse(app._rap_slant("that", "chat"))          # internal pairs stay strict

    def test_silent_e_before_a_plural_is_not_a_syllable(self):
        self.assertTrue(app._rap_slant("seems", "schemes"))
        self.assertTrue(app._rap_slant("game", "names"))
        self.assertEqual(app._rap_depth("schemes"), 1)
        self.assertEqual(app._rap_depth("named"), 1)
        # A plural that IS a syllable keeps its vowel.
        self.assertEqual(app._rap_norm("houses"), "houses")

    def test_unstressed_final_y_lands_on_see(self):
        self.assertTrue(app._rap_slant("see", "century", end=True))
        self.assertFalse(app._rap_slant("see", "century"))     # internal pairs stay strict
        self.assertFalse(app._rap_slant("see", "sky", end=True))
        self.assertTrue(app._rap_slant("fly", "sky", end=True))

    def test_two_short_fragments_need_a_full_coda(self):
        self.assertTrue(app._rap_slant("gate", "plates", end=True))
        self.assertFalse(app._rap_coda_equal("gate", "plates"))
        self.assertTrue(app._rap_coda_equal("chat", "that"))
        self.assertFalse(app.rap_rhyme_evidence("The red gate; Seven copper plates")["ok"])
        self.assertTrue(app.rap_rhyme_evidence("By the red gate we wait; Seven copper plates")["ok"])

    def test_the_grader_version_is_unchanged(self):
        self.assertEqual(app.CRYSTAL_GRADER_VERSION, 9)


if __name__ == "__main__":
    unittest.main()
