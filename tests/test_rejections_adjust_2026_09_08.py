"""2026-09-08 (evening): the adjustments read off the rejection queue.

197 pending cuts, 188 of them tint; 180 graded before the afternoon's road
changes. Of the 108 meaning cuts, 62 were the negation check, 46 the name
check (54 of 71 findings the station's own name), 22 the question check.
Under the meaning grade a rhetorical negation and an inner question fold,
the station name and a descriptive opener are reported and not bound, a
raw transcript swath is bounded before the tint sees it, and the queue is
re-read against today's grader.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
import line_review
from crystal_contract import (VERSION, _question_is_inner, _rhetorical_negations_only,
                              compare_contract)


class RhetoricalNegation(unittest.TestCase):
    def test_the_frames(self):
        for text in ("It's visceral, not just structural.",
                     "Suspended moment? No, it should have been called a holding of breath.",
                     "Dissonance is right; it's all mismatched signals, isn't it?",
                     "I can't shake the feeling that something is missing.",
                     "The blues aren't tranquil; they are the crushing weight of the abyss.",
                     "This isn't about feeling sorry, it is about the tangible reality.",
                     "A current you just have to ride, no matter what kind of water you are in."):
            with self.subTest(text=text):
                self.assertTrue(_rhetorical_negations_only(text), text)
        for text in ("He did not win, taking the near-miss with strange grace.",
                     "Your son is not safe.", "I never said that.", "Nothing happened after that."):
            with self.subTest(text=text):
                self.assertFalse(_rhetorical_negations_only(text), text)

    def test_the_report_keeps_the_strict_verdict_and_names_the_frame(self):
        report = compare_contract("It's visceral, not just structural.", "Visceral, and structural too")
        self.assertFalse(report["negation"])
        self.assertTrue(report["negation_rhetorical"])
        self.assertEqual(report["negation_basis"], "rhetorical negation dropped")
        self.assertFalse(report["ok"])                       # the strict comparison is unchanged
        plain = compare_contract("He did not win the prize.", "He won the prize, that's nice")
        self.assertFalse(plain["negation"])
        self.assertFalse(plain["negation_rhetorical"])
        self.assertEqual(plain["negation_basis"], "negation dropped")


class InnerQuestion(unittest.TestCase):
    def test_where_the_question_sits(self):
        self.assertTrue(_question_is_inner("You think so? I mean, look at the colors in that first one."))
        self.assertFalse(_question_is_inner("But how can you separate the systems? When they scan everything?"))
        self.assertFalse(_question_is_inner("What made you call?"))

    def test_the_report(self):
        report = compare_contract("You think so? Look at the colors, it's loud.", "Look at the hues, it seems so loud")
        self.assertFalse(report["question"])
        self.assertTrue(report["question_inner"])
        self.assertEqual(report["question_basis"], "inner question folded")
        ends = compare_contract("Look at the colors. You think so?", "Look at the hues, so loud")
        self.assertFalse(ends["question"])
        self.assertFalse(ends["question_inner"])


class Names(unittest.TestCase):
    def test_a_descriptive_opener_is_reported_not_bound(self):
        report = compare_contract("Taut wire is too mechanical; it should have been called an exposed nerve.",
                                  "The wire feels mechanical; an exposed nerve is what it should be called")
        self.assertEqual(report["missing_names"], [])
        self.assertEqual([row["reason"] for row in report["possible_names_missing"]], ["descriptive opener"])
        shimmer = compare_contract("Shimmering light hits the wall.", "Light hits the wall, it's tall")
        self.assertEqual(shimmer["missing_names"], [])

    def test_real_names_unknown_words_and_finite_verbs_still_bind(self):
        self.assertEqual([row["text"] for row in compare_contract("Ious. The king holds the plate.",
                                                                    "The king holds the plate.")["missing_names"]], ["Ious"])
        self.assertFalse(compare_contract("Dale woulda taken that turn.", "He woulda taken that turn.")["entities"])
        self.assertFalse(compare_contract("Dreamscape is too flowery.", "It is too flowery.")["entities"])
        self.assertFalse(compare_contract("Reading is fun for me.", "It is fun for me.")["entities"])

    def test_the_station_name_is_boilerplate(self):
        plate = {"chicken", "tendo", "little", "pine", "box", "fm", "station"}
        report = compare_contract("Something is missing right here at Chicken Tendo Little Pine Box FM Station.",
                                  "Something is missing here in the box, on the station", boilerplate=plate)
        self.assertTrue(report["entities"], report["missing_names"])
        self.assertEqual({row["reason"] for row in report["possible_names_missing"]}, {"station boilerplate"})
        bound = compare_contract("Something is missing right here at Chicken Tendo Little Pine Box FM Station.",
                                 "Something is missing here in the box, on the station")
        self.assertFalse(bound["entities"])
        with mock.patch.object(app, "dj_settings", lambda: {"station_name": "Chicken Tendo Little Pine Box FM Station"}):
            words = app._tint_boilerplate()
        self.assertTrue({"chicken", "tendo", "pine", "box", "fm", "station"} <= words)

    def test_the_contract_version_is_unchanged(self):
        self.assertEqual(VERSION, 3)


class GraderFolds(unittest.TestCase):
    def test_the_meaning_grade_folds_a_rhetorical_negation_the_strict_grade_does_not(self):
        source = "It's visceral, not just structural; the wire cuts the air."
        candidate = "It's visceral, the wire cuts the air; structural too, beyond compare"
        with mock.patch.object(app, "_crystal_vocab", lambda: set()):
            meaning = app.tint_evaluate(source, candidate, [], force=0.88, kind="banter", strict=False)
            strict = app.tint_evaluate(source, candidate, [], force=0.88, kind="banter", strict=True)
        self.assertTrue(meaning["ok"], meaning["faults"])
        self.assertIn("a rhetorical negation was folded into the bar", meaning["advisory"])
        self.assertFalse(strict["ok"])
        self.assertIn("semantic preservation failed", strict["faults"])

    def test_the_meaning_grade_folds_an_inner_question(self):
        source = "You think so? Look at the colors in that first one, it is loud."
        candidate = "Look at the hues in that first one, it seems so loud; an ugly mess, orange and blue shroud"
        with mock.patch.object(app, "_crystal_vocab", lambda: set()):
            meaning = app.tint_evaluate(source, candidate, [], force=0.88, kind="banter", strict=False)
        self.assertTrue(meaning["ok"], meaning["faults"])
        self.assertIn("an inner question was folded into a statement", meaning["advisory"])

    def test_a_dropped_fact_negation_is_still_refused_under_the_meaning_grade(self):
        source = "He did not win the prize; the line dropped before the end."
        candidate = "He won the prize, the line dropped before the end; that is how the story is penned"
        with mock.patch.object(app, "_crystal_vocab", lambda: set()):
            meaning = app.tint_evaluate(source, candidate, [], force=0.88, kind="banter", strict=False)
        self.assertFalse(meaning["ok"])
        self.assertIn("semantic preservation failed", meaning["faults"])


class TranscriptSwaths(unittest.TestCase):
    def test_a_raw_transcript_swath_is_bounded_and_punctuated_text_is_not(self):
        raw = " ".join(["word"] * 200)
        out = app._verbatim_turn_text(raw)
        self.assertLessEqual(len(out), 241)
        self.assertTrue(out.endswith("."))
        punctuated = ("A sentence here. " * 30).strip()
        self.assertEqual(app._verbatim_turn_text(punctuated), punctuated)
        short = "just a few words with no end"
        self.assertEqual(app._verbatim_turn_text(short), short)


class RegradeSweep(unittest.TestCase):
    def test_the_queue_is_re_read_against_todays_grader(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = line_review.LineReviewStore(Path(tmp) / "lr.sqlite3")
            passes = store.record("tint", "It's visceral, not just structural; the wire cuts the air.",
                                  "It's visceral, the wire cuts the air; structural too, beyond compare",
                                  ["semantic checks did not pass"], {"kind": "banter", "chunks": []},
                                  evaluation={"strength": 0.88, "version": 9})
            fails = store.record("tint", "He did not win the prize; the line dropped before the end.",
                                 "He won the prize, the line dropped before the end; that is how the story is penned",
                                 ["semantic checks did not pass"], {"kind": "banter", "chunks": []},
                                 evaluation={"strength": 0.88, "version": 9})
            formula = store.record("tint", "Grandma Lou, good to have you. What made you call about the garbage?",
                                   "Lou, what made you call about the garbage; tonight we fight",
                                   ["rap rhyme evidence did not pass"], {"kind": "caller", "chunks": []},
                                   evaluation={"strength": 0.88, "version": 9})
            with mock.patch.object(app, "_LINE_REVIEW", store), \
                    mock.patch.object(app, "_crystal_vocab", lambda: set()), \
                    mock.patch.object(app, "crystal_grade_strict", lambda: False):
                got = app.line_review_regrade_pending()
            self.assertEqual((got["passes_now"], got["read_plain"], got["kept"]), (1, 1, 1), got)
            self.assertEqual(store.get(passes["id"])["review_status"], "noted")
            self.assertEqual(store.get(passes["id"])["effect"]["status"], "stale_grader")
            self.assertEqual(store.get(formula["id"])["effect"]["status"], "read_plain")
            self.assertEqual(store.get(fails["id"])["review_status"], "pending")
            # A second sweep finds nothing left to move.
            with mock.patch.object(app, "_LINE_REVIEW", store), \
                    mock.patch.object(app, "_crystal_vocab", lambda: set()), \
                    mock.patch.object(app, "crystal_grade_strict", lambda: False):
                again = app.line_review_regrade_pending()
            self.assertEqual((again["passes_now"], again["read_plain"]), (0, 0), again)


if __name__ == "__main__":
    unittest.main()
