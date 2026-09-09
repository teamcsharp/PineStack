"""2026-09-09: the rejection queue read row by row, and the false refusals closed.

The operator saw a panel card offering "623 cut lines wait for your decision"
and asked what could be changed to make the station more amiable. Two of the
three answers were measurements rather than code.

Read off the 107 pending tint rows in `data/line_review.sqlite3`, the single
failing leg was:

    35  rhyme - no pair landed at all
    11  entities - a "name" the bar did not keep
    11  negation
     4  question
     3  the anchor floor
    18  a round-level turn check carrying no per-bar detail

**The rhyme block is genuine and is deliberately left alone.** Replaying the
grader's own near reading (`crystal_rhyme.rhymes_with`) over every one of
those rows rescues NONE of the 30 that named a pair: two landed both bars on
the same word and two wrote one bar instead of two. `ponder`/`air`,
`called`/`there`, `up`/`gone`, `seconds`/`now` do not rhyme by any reading.
Lowering that bar would only put unrhymed lines on the air, which is the
opposite of what the operator asked for; the fix there is a better first ask.

**The entity block was almost entirely one bug.** 33 of 35 "lost names" were
words like Furnace, Longing, Reality, Velocity and Bewilderment, and 18 of 23
entity refusals had a source that was PROPOSING A TITLE. The gallery road is
two hosts arguing about what a picture should have been called, so every
proposal drops three or four Title-Cased ordinary words into the source, and
the name rule then demanded the bar reproduce each of them verbatim.

The cause is an asymmetry. A capitalised word at a sentence opener is checked
against the crystal's vocabulary and against `_descriptive_opener`; the same
word one clause later was bound with no check at all.
"""
import unittest

import crystal_contract


def _names(source):
    got = crystal_contract.extract_contract(source, (), ())
    bound = [n["text"] for n in got["names"] if not n.get("heuristic")]
    freed = {n["text"]: n["reason"] for n in got["names"] if n.get("heuristic")}
    return bound, freed


class ACoinedTitleIsNotSomebodysName(unittest.TestCase):
    def test_the_words_of_an_invented_title_are_reported_not_bound(self):
        for source, coined in (
            ("It should have been called The Inferno of Immediate Action, because "
             "it captures everything happening at once.",
             ("Inferno", "Immediate", "Action")),
            ("it should have been called something like The Furnace of Creation",
             ("Furnace", "Creation")),
            ("we should be calling it The Engine of Becoming", ("Engine", "Becoming")),
            ("it should have been called The Artificial Longing", ("Artificial", "Longing")),
            ("it should have been called The Apex Gaze; it's not just raw power",
             ("Apex", "Gaze")),
        ):
            bound, freed = _names(source)
            for word in coined:
                self.assertIn(word, freed, source)
                self.assertEqual(freed[word], "coined title")
            self.assertEqual(bound, [], source)

    def test_a_word_the_dictionary_does_not_know_is_still_a_name(self):
        """The escape the sentence opener already had, applied at the same
        strength: a coinage in its own right stays bound."""
        for source, still in (
            ("it should have been called The Dreamscape of Velocity", "Dreamscape"),
            ("it should have been called The Shockwave of Unsettled Delight", "Shockwave"),
            ("it should have been called Jarell's Corner", "Jarell's"),
        ):
            bound, _freed = _names(source)
            self.assertIn(still, bound, source)

    def test_a_capitalised_word_outside_a_title_proposal_is_untouched(self):
        bound, freed = _names("Skip said the transfer is at 4:00 AM and Lara agreed")
        self.assertIn("Skip", bound)
        self.assertIn("Lara", bound)
        self.assertNotIn("Skip", freed)

    def test_the_proposal_does_not_reach_past_its_own_sentence(self):
        """"...called The Furnace. Meanwhile Lara went home." - Lara is not
        part of the title and never becomes heuristic."""
        bound, freed = _names("It should have been called The Furnace. "
                              "Meanwhile Lara went to the roof.")
        self.assertIn("Lara", bound)
        self.assertEqual(freed.get("Furnace"), "coined title")


class AVocativeIsNotAFactTheTurnCarries(unittest.TestCase):
    def test_a_name_the_turn_is_addressing_may_go(self):
        for source in ("And then there is this final piece, Skip, this one is pure yearning",
                       "Skip, look at the colours in that one"):
            bound, freed = _names(source)
            self.assertEqual(freed.get("Skip"), "vocative", source)
            self.assertNotIn("Skip", bound, source)

    def test_a_name_the_turn_talks_ABOUT_stays_bound(self):
        bound, freed = _names("Skip told Lara that Skip was leaving")
        self.assertIn("Skip", bound)
        self.assertIn("Lara", bound)
        self.assertEqual(freed, {})


class AQuestionAskedWithoutItsMark(unittest.TestCase):
    def test_an_interrogative_bar_still_does_the_questions_job(self):
        report = crystal_contract.compare_contract(
            "Control is an illusion when you're dealing with things that slip "
            "through your fingers; what kind of garbage are we discussing here?",
            "Control is an illusion when things slip through your fingers; what "
            "kind of mess you find; What sort of garbage are we dealing with "
            "inside your mind")
        self.assertTrue(report["question"])
        self.assertEqual(report["question_basis"], "the bar asks in form without the mark")

    def test_a_bare_wh_opener_is_not_a_question(self):
        """"How the ground can fall" is a statement. Without the auxiliary
        inversion this escape would accept a bar that dropped a real
        question, so the inversion is required."""
        report = crystal_contract.compare_contract(
            "But if we don't acknowledge the pretense, then how can we even begin?",
            "But how the ground can fall; When the base begins to stall")
        self.assertFalse(report["question"])


class ASourceThatDeniesByNamingAnAbsence(unittest.TestCase):
    def test_a_lack_of_something_is_a_denial_the_bar_may_say_plainly(self):
        report = crystal_contract.compare_contract(
            "You are seriously saying that the whole setup is just about a lack of "
            "faith in any kind of defense or outcome when things get really heavy, "
            "you heard me?",
            "You seriously say the setup is 'bout no defense or outcome when things "
            "get heavy, you heard?")
        self.assertTrue(report["negation"])
        self.assertEqual(report["negation_basis"], "the source denies by naming an absence")

    def test_a_bar_may_still_not_invent_a_denial(self):
        report = crystal_contract.compare_contract(
            "The transfer is at four and the crate is heavy.",
            "There is no transfer and no crate at all")
        self.assertFalse(report["negation"])
        self.assertEqual(report["negation_basis"], "negation added")


class TheBroadFrameStoppedShadowingTheCarefulOne(unittest.TestCase):
    """Found by this sweep, not reported by the station: the deep scan of
    2026-09-08 added "make/let + one + think/wonder/..." as a pronominal
    frame ABOVE an older frame that checked what followed the verb, so
    "Make one wonder machine" stopped counting its machine. The count now
    survives only when the following word is a noun and the pair is a
    compound."""

    def test_a_compound_still_carries_its_count(self):
        self.assertTrue(crystal_contract.extract_contract("Make one wonder machine.")["numbers"])

    def test_the_impersonal_pronoun_still_counts_nothing(self):
        for source in ("It makes one wonder where power comes from.",
                       "It makes one wonder.", "The scene made one wonder.",
                       "Makes one think on what all try to show"):
            self.assertEqual(crystal_contract.extract_contract(source)["numbers"], [], source)


class TheRhymeBarDoesNotMove(unittest.TestCase):
    """The measurement that decided to leave it alone: over the 30 pending
    rows that named a pair, the near reading rescues none."""

    def test_the_pairs_the_queue_refused_do_not_rhyme_by_any_reading(self):
        import crystal_rhyme
        for a, b in (("ponder", "air"), ("called", "there"), ("up", "gone"),
                     ("now", "upstairs"), ("one", "consume"), ("down", "be"),
                     ("seconds", "now"), ("potent", "happen"), ("up", "fall")):
            self.assertEqual(crystal_rhyme.rhymes_with(a, b), "",
                             "%s/%s must stay refused" % (a, b))


if __name__ == "__main__":
    unittest.main()
