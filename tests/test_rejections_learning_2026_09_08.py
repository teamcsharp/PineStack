"""2026-09-08 (evening): the rejections the operator saw, and what the
station learns from them."""
import unittest
from unittest import mock

import app


class TransformationRuleTests(unittest.TestCase):
    SOURCE = "Hold on to line seven five six three eight; Hello now, what you see there"

    def test_the_operators_own_edit_passes_it_rhymes_now(self):
        # Typed by the operator into "Try wording" and refused for exactly one
        # fault: the candidate carries the source's words and adds a landing.
        made = "Hold on to line seven five six three eight; Hello now, what you see there this late."
        report = app.tint_evaluate(self.SOURCE, made, [], force=0.88, strict=False)
        self.assertTrue(report["ok"], report["faults"])
        self.assertTrue(report["transformation"]["rhyme_added"])
        self.assertEqual(report["transformation"]["lexical_distance"], 0.143)

    def test_an_echo_that_does_not_rhyme_is_still_refused(self):
        made = "Hold on to line seven five six three eight; Hello now, what you see there tonight."
        report = app.tint_evaluate(self.SOURCE, made, [], force=0.88, strict=False)
        self.assertFalse(report["ok"])
        self.assertFalse(report["transformation"]["rhyme_added"])
        self.assertIn("rhetoric was not materially transformed", report["faults"])

    def test_the_strict_grade_still_demands_the_full_transformation(self):
        made = "Hold on to line seven five six three eight; Hello now, what you see there this late."
        report = app.tint_evaluate(self.SOURCE, made, [], force=0.88, strict=True)
        self.assertIn("rhetoric was not materially transformed", report["faults"])

    def test_an_echo_is_named_as_an_echo_in_the_repair_hint(self):
        # 92 of the 95 "not transformed" cuts in the census handed the source back unchanged.
        hint = app.tint_repair_hint(self.SOURCE, self.SOURCE + " tonight.",
                                    ["rhetoric was not materially transformed"], {})
        self.assertIn("ECHO", hint)
        self.assertIn("two to four bars", hint)
        recast = app.tint_repair_hint(self.SOURCE, "Line seven five six three eight is on hold, so hello and tell me now.",
                                      ["rhetoric was not materially transformed"], {})
        self.assertIn("STYLE", recast)
        self.assertNotIn("ECHO", recast)

    def test_a_source_that_already_rhymes_gets_no_credit_for_keeping_it(self):
        source = "The plate is copper and the station waits tonight / the copper hums and the light is bright"
        made = source + " indeed"
        report = app.tint_evaluate(source, made, [], force=0.88, strict=False)
        self.assertFalse(report["transformation"]["rhyme_added"])


class DictionaryRhymeTests(unittest.TestCase):
    def test_perfect_dictionary_rhymes_on_suffix_words_are_end_pairs(self):
        # The census: dictionary pairs on 1 of 133 refused bars - the spelling
        # reading's suffix depth was throwing the dictionary's own proofs away.
        for text, pair in (
            ("Hello, this is Maxine, calling from a garage; Old box fan keeps changing speed, mechanical mirage",
             ("garage", "mirage")),
            ("Not sure where to steer; That feeling you hold dear, holding it near", ("steer", "near")),
            ("You're live; So let the moment arrive", ("live", "arrive")),
        ):
            with self.subTest(pair=pair):
                got = app.rap_rhyme_evidence(text)
                self.assertTrue(got["ok"], got)
                self.assertIn(pair, [tuple(p) for p in got["end"]])

    def test_a_shared_suffix_alone_is_still_not_a_rhyme(self):
        for text in ("Softness; Emptiness", "That is the being; This is the feeling", "Stay calm; No harm"):
            with self.subTest(text=text):
                self.assertFalse(app.rap_rhyme_evidence(text)["ok"])


class NewsBriefTests(unittest.TestCase):
    def test_the_wires_own_words_are_evidence_the_story_was_told(self):
        script = ("A: Word from the wire tonight, the council voted late; the copper bridge will close by eight. "
                  "B: Officials call it repairs, I call it a shame; the commuters stuck in traffic know the game. "
                  "A: And that is the bulletin, back to the music we came.")
        titles = "Council votes to close the copper bridge for repairs / King sends letter to the mayor"
        with mock.patch.object(app, "line_review_permits", mock.Mock(return_value=False)):
            got = app.segment_audit("news", script, titles=titles)
            self.assertTrue(got["ok"], got)
            self.assertTrue(any(str(f).startswith("wire:") for f in got["found"]), got["found"])
            bare = app.segment_audit("news", "A: The river runs cold tonight and the moon is on the water; "
                                             "B: the silver hums and the light is bright, said the porter. "
                                             "A: And that is the whole of it, back to the music now.", titles=titles)
            self.assertFalse(bare["ok"])


class PronounOneTests(unittest.TestCase):
    def test_this_one_before_a_verb_is_a_pronoun_not_a_count(self):
        import crystal_contract
        for source in ("This one looks like a hairy taxidermy display.", "That one sounds like noise.",
                       "This one really hits.", "I want the quiet one."):
            with self.subTest(source=source):
                quantities = [row for row in crystal_contract._numbers(source) if not row.get("ambiguous")]
                self.assertEqual(quantities, [], source)
        counted = [row for row in crystal_contract._numbers("Bring this one plate to the desk.") if not row.get("ambiguous")]
        self.assertTrue(counted)


class CallerRoadTests(unittest.TestCase):
    def test_the_phone_roads_formula_lines_are_read_plain(self):
        for said in ("Hold on, that's line seven five six three eight. Hello?",
                     "Thank you for calling, Ferret. Stay with Pine Box FM; more music after this.",
                     "Tunis, good to have you. What made you call about My garbage was stolen from the porch?"):
            with self.subTest(said=said):
                self.assertTrue(app._tint_formula_turn("caller", said))
        self.assertFalse(app._tint_formula_turn("caller", "Hi, this is Crazy Pete, calling from the apartment stairwell."))
        self.assertFalse(app._tint_formula_turn("banter", "Thank you for calling, Ferret."))

    def test_the_novelty_comparison_reads_the_callers_turns_only(self):
        script = "A: Thank you for calling, Sarah. What made you call about My garbage was stolen?\nC: Well, my garbage was stolen off the porch last night.\nB: Sarah, good to have you."
        self.assertEqual(app._call_caller_text(app.call_script_text(script)),
                         "C: Well, my garbage was stolen off the porch last night.")
        self.assertEqual(app._call_caller_text("no labels here"), "")
        theirs = "A: Thank you for calling, Tunis. What made you call about My garbage was stolen?\nC: They took the bins, every one of them, and left the lids.\nB: Tunis, good to have you."
        mine = app._call_novelty_grams(app._call_caller_text(app.call_script_text(script)))
        other = app._call_novelty_grams(app._call_caller_text(app.call_script_text(theirs)))
        self.assertTrue(mine and other)
        self.assertLess(len(mine & other) / len(mine | other), app.CALL_NOVELTY_MAX_SIMILARITY)


if __name__ == "__main__":
    unittest.main()
