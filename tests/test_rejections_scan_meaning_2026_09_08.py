"""2026-09-08 (late): the deep scan - the meaning agent's safe set and the
drain agent's queue hygiene.

Fifteen contract rules measured on the queue (22 pending rows and 31 live
attempts flip, one visible false pass left out), and the three roads that
drain the queue without a model: a newer cut of a line replaces the older,
a row whose round is gone leaves as a note, a row whose round already
carries an accepted bar for the line is superseded.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
import line_review
from crystal_contract import (_filler_negations_only, _lexical_negation_unpacked, _rhetorical_negations_only,
                              compare_contract, extract_contract)


class AddedTags(unittest.TestCase):
    def test_a_two_word_tag_closing_a_bar_is_filler(self):
        for candidate in ("Topic stopped being abstract; that was the moment my garbage was stolen, no dice",
                          "First caller gets it, no collars", "Hit it harder, no guard",
                          "Some ugly stuff there, nothing but a residue"):
            with self.subTest(candidate=candidate):
                self.assertTrue(_filler_negations_only(candidate))
        self.assertFalse(_filler_negations_only("Dale woulda taken that turn flat out; No brakes on that route"))
        # #1076's pinned refusal still stands through the contract.
        self.assertFalse(compare_contract("Dale woulda taken that turn flat out.",
                                          "Dale woulda taken that turn flat out; No brakes on that route.",
                                          anchor_floor=0)["ok"])


class MoreFrames(unittest.TestCase):
    def test_the_six_frames_read_off_the_queue(self):
        for text in ("He doesn't snap out of it, does he? He just keeps drifting.",
                     "It's raw exposure, nothing more, just the grit and the light doing the heavy lifting.",
                     "It's a strange kind of performance, isn't it, trying to maintain some semblance of order.",
                     "saying listen to what I'm saying was there more junk food than real food no yes",
                     "Aren't you sick of being told what to feel?",
                     "A current you ride, no matter how deep the water is."):
            with self.subTest(text=text):
                self.assertTrue(_rhetorical_negations_only(text), text)
        self.assertFalse(_rhetorical_negations_only("He did not win, taking the near-miss with strange grace."))

    def test_a_lexical_negation_in_the_source_may_be_unpacked(self):
        anchors = extract_contract("the endless cycle of demands where needs go unmet")["anchors"]
        self.assertTrue(_lexical_negation_unpacked(anchors, "demands that never end; a need it won't lend"))
        self.assertFalse(_lexical_negation_unpacked(anchors, "demands that pile up; no brakes on the cup"))
        report = compare_contract("The endless cycle of demands wears you down.",
                                  "The cycle of demands that never ends wears you down")
        self.assertTrue(report["negation"], report["negation_basis"])

    def test_the_rap_spelling_of_nothing(self):
        report = compare_contract("Nothing needs us tonight.", "Nothin' needs us tonight, that's right")
        self.assertTrue(report["negation"], report["negation_basis"])


class Questions(unittest.TestCase):
    def test_an_unpunctuated_swath_may_be_punctuated_as_a_question(self):
        source = ("i will find him i will reclaim what you have taken from us why so serious fix the blade in my "
                  "mouth and face choose killing sure will not bring you peace peace was never an option. "
                  "this is the one full stop in a hundred and sixty words of transcript and it should not count "
                  "as punctuation that decides whether a question may be asked of it at all so here we go")
        report = compare_contract(source, "I will find him and reclaim what was taken; why so serious? peace was never an option",
                                  anchor_floor=0)
        self.assertTrue(report["question"], report["question_basis"])

    def test_a_discourse_tag_kept_as_a_question(self):
        report = compare_contract("It just feels like some kind of arbitrary rule imposed on something that should be pure fun, you know?",
                                  "It feels like some arbitrary rule imposed on pure fun, you know?", anchor_floor=0)
        self.assertTrue(report["question"], report["question_basis"])


class Counts(unittest.TestCase):
    def test_more_pronominal_ones(self):
        self.assertTrue(compare_contract("And I may just one one more follow.", "And I may follow once more", anchor_floor=0)["entities"])
        self.assertTrue(compare_contract("The two of them heard you.", "They heard you", anchor_floor=0)["entities"])
        self.assertTrue(compare_contract("The stark white and black one, it should be called Void Mark.",
                                         "The stark white and black, it should be called Void Mark", anchor_floor=0)["entities"])
        self.assertTrue(compare_contract("It makes you think.", "Makes one think on what all try to show", anchor_floor=0)["entities"])
        self.assertFalse(compare_contract("He was caller number seven.", "He was caller number one.")["entities"])
        self.assertFalse(compare_contract("Mara needs one copper plate.", "Mara needs only copper plates.")["entities"])


class Names(unittest.TestCase):
    def test_on_earth_and_common_openers(self):
        self.assertTrue(compare_contract("What on Earth are you talking about?", "What are you talking about, huh?", anchor_floor=0)["entities"])
        for text in ("Anyone can see it.", "Religion is a strange thing.", "Nobody knows.", "Eventually it lands."):
            with self.subTest(text=text):
                self.assertEqual(extract_contract(text)["names"], [], text)
        self.assertFalse(compare_contract("Sarah Sherman called at 3:04 AM.", "She called at 3:04 AM.")["entities"])


class QueueHygiene(unittest.TestCase):
    def _store(self, tmp):
        return line_review.LineReviewStore(Path(tmp) / "lr.sqlite3")

    def test_a_newer_cut_of_the_same_line_replaces_the_older(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            source = "He did not win the prize; the line dropped before the end."
            older = store.record("tint", source, "He won the prize, the line dropped; penned",
                                 ["semantic checks did not pass"], {"kind": "banter", "chunks": []},
                                 evaluation={"strength": 0.88, "version": 9})
            with mock.patch.object(app, "_LINE_REVIEW", store):
                newer = app.line_review_capture("tint", source, "He won the prize, the line dropped; that is the end",
                                                reasons=["semantic checks did not pass"],
                                                context={"kind": "banter", "chunks": []},
                                                evaluation={"strength": 0.88, "version": 9})
            self.assertEqual(store.get(older["id"])["review_status"], "noted")
            self.assertEqual(store.get(older["id"])["effect"]["status"], "superseded")
            self.assertEqual(store.get(newer["id"])["review_status"], "pending")

    def test_the_sweep_notes_a_row_whose_round_is_gone_and_supersedes_a_row_whose_round_has_the_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            gone = store.record("tint", "He did not win the prize; the line dropped before the end.",
                                "He won the prize, the line dropped; penned", ["semantic checks did not pass"],
                                {"kind": "banter", "chunks": []}, evaluation={"strength": 0.88, "version": 9})
            landed = store.record("tint", "It's visceral, not just structural; the wire cuts the air.",
                                  "a bar that lost the thread", ["semantic checks did not pass"],
                                  {"kind": "banter", "chunks": []}, evaluation={"strength": 0.88, "version": 9})
            entry = {"script_plain": "A: It's visceral, not just structural; the wire cuts the air.\nB: Sure.",
                     "script_tinted": "A: Visceral, the wire cuts the air; structural too, beyond compare\nB: Sure."}

            def matching(review):
                return ("banter", {}, entry) if review["id"] == landed["id"] else None

            with mock.patch.object(app, "_LINE_REVIEW", store), \
                    mock.patch.object(app, "line_review_matching", matching), \
                    mock.patch.object(app, "_crystal_vocab", lambda: set()), \
                    mock.patch.object(app, "crystal_grade_strict", lambda: False):
                got = app.line_review_regrade_pending(gone_after=0)
            self.assertEqual((got["round_gone"], got["superseded"]), (1, 1), got)
            self.assertEqual(store.get(gone["id"])["effect"]["status"], "round_gone")
            self.assertEqual(store.get(landed["id"])["effect"]["status"], "superseded")
            # A young row whose round is not found yet is left alone.
            young = store.record("tint", "The station needs a copper plate before midnight.",
                                 "a bar", ["no rhyme evidence - the bar does not land a rhyme"],
                                 {"kind": "banter", "chunks": []}, evaluation={"strength": 0.88, "version": 9})
            with mock.patch.object(app, "_LINE_REVIEW", store), \
                    mock.patch.object(app, "line_review_matching", lambda review: None), \
                    mock.patch.object(app, "_crystal_vocab", lambda: set()), \
                    mock.patch.object(app, "crystal_grade_strict", lambda: False):
                again = app.line_review_regrade_pending()
            self.assertEqual(again["round_gone"], 0, again)
            self.assertEqual(store.get(young["id"])["review_status"], "pending")


class CallContract(unittest.TestCase):
    def test_the_introduction_survives_a_comma_and_an_apostrophe(self):
        script = ("A: The request line is ringing. Pine Box FM, you're live; go ahead.\n"
                  "C: Salem, I am calling from a dimly lit corner of the city.\n"
                  "B: A corner of the city, right.\n"
                  "A: Salem, good to have you. What made you call?\n"
                  "C: My garbage was stolen.\n"
                  "B: Stolen, you say.\n"
                  "A: What did you see first?\n"
                  "C: The bin was gone at dawn.\n"
                  "A: And what did you do next?\n"
                  "C: I called you.\n"
                  "A: Thanks for calling, Salem. Stay with Pine Box FM.")
        report = app.call_flow_report(script, caller_name="Salem", include_shelf=False)
        self.assertTrue(report["introduced"], report["faults"])
        self.assertTrue(report["greeted"], report["faults"])       # the co-host spoke first
        self.assertGreaterEqual(report["answered_questions"], 2, report)
        self.assertNotIn("the caller/host turn share is out of balance", report["faults"])
        # A call nobody greets by name is still refused.
        never = app.call_flow_report(script.replace("A: Salem, good to have you. What made you call?",
                                                    "A: Good to have you. What made you call?"),
                                     caller_name="Salem", include_shelf=False)
        self.assertFalse(never["greeted"], never["faults"])

    def test_the_richness_legs_are_advisory_only_once_the_call_is_rapped(self):
        script = ("A: The request line is ringing. Pine Box FM, you're live; go ahead.\n"
                  "C: Salem here, calling from a dimly lit corner of the city.\n"
                  "A: Salem, good to have you. What made you call?\n"
                  "C: My garbage was stolen.\n"
                  "B: Stolen, you say.\n"
                  "A: What did you see first?\n"
                  "C: The bin was gone at dawn.\n"
                  "A: Thanks for calling, Salem. Stay with Pine Box FM.")
        hard = app.call_flow_report(script, caller_name="Salem", include_shelf=False,
                                    topic="copper plates", speakerbox_text="a copper plate on the shelf")
        soft = app.call_flow_report(script, caller_name="Salem", include_shelf=False,
                                    topic="copper plates", speakerbox_text="a copper plate on the shelf",
                                    soft_quality=True)
        richness = {"the database topic is not carried by both caller and hosts",
                    "the selected Speakerbox source never enters the dialogue",
                    "fewer than two host questions pick up a concrete detail from the caller's prior answer"}
        self.assertTrue(richness & set(hard["faults"]), hard["faults"])
        self.assertFalse(richness & set(soft["faults"]), soft["faults"])
        self.assertTrue(richness & set(soft["soft_faults"]), soft)
        # the protocol legs are binding either way
        bare = app.call_flow_report("A: Hello there.\nC: Hi.", caller_name="Salem",
                                    include_shelf=False, soft_quality=True)
        self.assertFalse(bare["ok"])
        self.assertIn("the caller does not introduce themselves", bare["faults"])


if __name__ == "__main__":
    unittest.main()
