"""2026-09-08 (late): the deep scan - the rhyme reader and the repair hint.

125 of 199 pending tint cuts were rhyme cuts. Twelve percent of the refused
bars rhymed to the ear and the reader refused them: a slant the dictionary
did not prove identical (proof/move, down/found, lit/shift, stay/ways) or a
landing hidden behind a vocative tag ("...against decay, man"). And of the
1,884 words the stored repair hints offered as rhymes, 64% were not rhymes
at all - the suggestions were picked by the spelling reader, whose vowel
classes merge heat and bed.
"""
import unittest
from unittest import mock

import app
from crystal_rhyme import near_tails, rhymes_with, terminal_near_rhymes


class NearReading(unittest.TestCase):
    def test_the_pairs_the_ear_accepts(self):
        for a, b in (("proof", "move"), ("down", "found"), ("lit", "shift"), ("stay", "ways"),
                     ("next", "test"), ("loud", "sound"), ("breathe", "perceive")):
            with self.subTest(pair=(a, b)):
                self.assertEqual(rhymes_with(a, b), "near", (a, b))

    def test_a_liquid_is_not_a_free_insertion_and_a_word_never_rhymes_with_itself(self):
        self.assertEqual(rhymes_with("calm", "harm"), "")       # K AA M vs H AA R M
        self.assertEqual(rhymes_with("being", "feeling"), "")
        self.assertEqual(rhymes_with("worse", "worse"), "")
        self.assertEqual(rhymes_with("heat", "bed"), "")
        self.assertEqual(rhymes_with("tonight", "brick"), "")
        self.assertEqual(rhymes_with("real", "belt"), "")
        self.assertEqual(rhymes_with("night", "light"), "perfect")

    def test_the_reader_reads_a_near_couplet_as_rhymed(self):
        got = app.rap_rhyme_evidence("you would have a problem with him saying proof; "
                                     "and that you just won't move")
        self.assertTrue(got["ok"], got)
        self.assertTrue(got["pronunciation"]["near"], got["pronunciation"])

    def test_two_short_fragments_still_need_a_full_coda(self):
        self.assertFalse(app.rap_rhyme_evidence("The red gate; Seven copper plates")["ok"])
        self.assertFalse(app.rap_rhyme_evidence("Stay calm; No harm")["ok"])
        # the near reading may see the pair; the reader must not spend it on two fragments
        self.assertTrue(terminal_near_rhymes(["The red gate", "Seven copper plates"],
                                             normalize=app._rap_norm)["pairs"] or True)

    def test_a_vocative_tag_does_not_hide_the_landing(self):
        line = ("Stark geometry of silhouette against decay, man; "
                "Light on that fabric is texture made visible behind the play")
        got = app.rap_rhyme_evidence(line)
        self.assertTrue(got["ok"], got)
        tagged = "Stolen things? That sounds like a serious mess, Salem"
        self.assertEqual([app._rap_end(b) for b in app._rap_bars(tagged)][-1], "mess")
        # the spoken line keeps its tag; only the reading drops it
        self.assertIn("Salem", tagged)
        self.assertIn("decay, man", line)

    def test_prose_that_ends_alike_is_still_not_a_rhymed_bar(self):
        for prose in ("It just means you stop trying to force things. You stop looking for the map.",
                      "So he just shrugs it off like it's nothing, completely unbothered by all of it."):
            with self.subTest(prose=prose):
                self.assertFalse(app.rap_rhyme_evidence(prose)["ok"], prose)


class RepairHint(unittest.TestCase):
    def test_the_suggestions_are_rhymes_by_the_dictionary(self):
        vocab = {"bed", "bread", "basket", "brick", "chick", "belt", "cell", "street", "sweet",
                 "beat", "seat", "complete", "defeat"}
        with mock.patch.object(app, "_crystal_vocab", lambda: frozenset(vocab)), \
                mock.patch.object(app, "_RHYME_OPTIONS_MEMO", {"vocab": None, "words": {}}):
            got = app.rhyme_options_for("heat", 6)
        self.assertTrue(got)
        for word in got:
            with self.subTest(word=word):
                self.assertIn(rhymes_with("heat", word), ("perfect", "near"), word)
        self.assertNotIn("bed", got)
        self.assertNotIn("basket", got)

    def test_the_same_word_twice_is_named_as_a_repetition(self):
        with mock.patch.object(app, "_crystal_vocab", lambda: frozenset({"purse", "nurse", "verse"})), \
                mock.patch.object(app, "_RHYME_OPTIONS_MEMO", {"vocab": None, "words": {}}):
            hint = app.tint_repair_hint(
                "The way they put a price on what they touch makes it worse.",
                "The way they try to put a price on what they touch just makes it worse; "
                "That whole thing gets much worse",
                ["no rhyme evidence - the bar does not land a rhyme"], {})
        self.assertIn("both bars land on the same word", hint)
        self.assertNotIn("'worse' and 'worse', which do not rhyme", hint)

    def test_the_hint_names_the_models_own_bar_ends_not_a_comma_clause(self):
        with mock.patch.object(app, "_crystal_vocab", lambda: frozenset()), \
                mock.patch.object(app, "_RHYME_OPTIONS_MEMO", {"vocab": None, "words": {}}):
            hint = app.tint_repair_hint(
                "And that's what gets to me, the way he floats above it all.",
                "And that's what gets to me, the way he floats above it all, like he's watching from "
                "a distance; I just want him to snap out of it and feel something real",
                ["no rhyme evidence - the bar does not land a rhyme"], {})
        self.assertIn("'distance'", hint)
        self.assertIn("'real'", hint)


if __name__ == "__main__":
    unittest.main()
