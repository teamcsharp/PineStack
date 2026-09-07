import hashlib
import unittest
from unittest import mock

import app


class TintContractTests(unittest.IsolatedAsyncioTestCase):
    SOURCE = "The station needs a copper plate before midnight."
    TINTED = ("Before midnight, the station needs that copper plate; "
              "operation meets calibration to settle the wait.")
    CHUNKS = [{"text": "Operation, calibration, apparatus and constellation."}]

    def grade(self, candidate, source=None, chunks=None):
        return app.tint_evaluate(source or self.SOURCE, candidate,
                                 self.CHUNKS if chunks is None else chunks,
                                 force=1.0)

    def test_meaning_rhyme_lexicon_and_rhetoric_all_pass(self):
        report = self.grade(self.TINTED)
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["rhyme"]["internal_pairs"])
        self.assertTrue(report["rhyme"]["multisyllabic_pairs"])
        self.assertTrue(report["transformation"]["crystal_lexicon"])
        self.assertIn("screening", report["limitations"])

    def test_different_text_without_rhyme_does_not_pass(self):
        # #1064: the spelling rhyme proof blocks under the strict grade and
        # is advisory under the meaning grade.
        candidate = self.SOURCE + " That apparatus hums beside the tall window."
        report = app.tint_evaluate(self.SOURCE, candidate, self.CHUNKS,
                                   force=1.0, strict=True)
        self.assertFalse(report["ok"])
        self.assertFalse(report["rhyme"]["ok"])
        self.assertEqual(report["grade"], "strict")
        lenient = app.tint_evaluate(self.SOURCE, candidate, self.CHUNKS,
                                    force=1.0, strict=False)
        self.assertFalse(lenient["rhyme"]["ok"])
        self.assertIn("no proven internal, multisyllabic or chained rhyme",
                      lenient["advisory"])
        self.assertEqual(lenient["grade"], "meaning")

    def test_appending_rhyme_to_untouched_proposition_is_not_transformation(self):
        report = self.grade(self.SOURCE + " Operation meets calibration.")
        self.assertFalse(report["transformation"]["ok"])

    def test_only_shared_grammatical_endings_are_not_rhyme(self):
        report = app._rhyme_pairs(["walking", "reading", "cooking"])
        self.assertFalse(report["ok"], report)

    def test_changed_numbers_names_questions_and_negation_fail(self):
        source = "Mara returned 12 copper plates before midnight."
        for made in (
            "Mara returned 13 copper plates before midnight; operation meets calibration.",
            "Nora returned 12 copper plates before midnight; operation meets calibration.",
            "Mara never returned 12 copper plates before midnight; operation meets calibration.",
            "Mara returned 12 copper plates before midnight; operation meets calibration?",
        ):
            with self.subTest(made=made):
                self.assertFalse(self.grade(made, source=source)["semantic"]["ok"])

    def test_source_phrase_copying_across_chunk_boundary_fails(self):
        chunks = [{"text": "velvet copper towers"}, {"text": "cover silent hours"}]
        report = self.grade(self.TINTED + " Velvet copper towers cover silent hours.",
                            chunks=chunks)
        self.assertFalse(report["copying"]["ok"])
        self.assertIn("velvet copper towers cover silent hours", report["copying"]["phrases"])

    def test_readiness_invalidates_old_strength_or_coverage(self):
        report = {"coverage": {"met": True, "target": 100,
                                "version": 4, "strength": 1.0}}
        with (mock.patch.object(app, "dialogue_tint_required", return_value=True),
              mock.patch.object(app, "crystal_coverage_target", return_value=100),
              mock.patch.object(app, "crystal_force", return_value=1.0)):
            self.assertTrue(app.tint_coverage_ready(report))
            report["coverage"]["strength"] = 0.5
            self.assertFalse(app.tint_coverage_ready(report))
            report["coverage"].update(strength=1.0, target=50)
            self.assertFalse(app.tint_coverage_ready(report))

    async def test_coverage_100_includes_short_lines_and_speakerbox(self):
        source = "A: Yes.\nB: " + self.SOURCE
        units = [("A", "Yes."), ("B", self.SOURCE)]
        results = ["Yes, request expressed; operation meets calibration.", self.TINTED]
        with (mock.patch.object(app, "crystal_active", return_value=[{"name": "test"}]),
              mock.patch.object(app, "crystal_stanzas", return_value=self.CHUNKS),
              mock.patch.object(app, "crystal_world_prompt", return_value="test"),
              mock.patch.object(app, "crystal_coverage_target", return_value=100),
              mock.patch.object(app, "crystal_force", return_value=1.0),
              mock.patch.object(app, "banter_turns", return_value=units),
              mock.patch.object(app, "tint_should_stop", return_value=""),
              mock.patch.object(app, "task_cost", return_value=0.1),
              mock.patch.object(app, "task_note"),
              mock.patch.object(app, "pipeline_log"),
              mock.patch.object(app, "_tint_flow"),
              mock.patch.object(app, "tint_spend_note"),
              mock.patch.object(app, "trail_note"),
              mock.patch.object(app, "chunk_answer"),
              mock.patch.object(app, "crystal_turn", side_effect=results) as rewrite):
            report = await app.crystal_tint(source, "banter", [["source", self.SOURCE]], critical=True)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["coverage"]["eligible"], 2)
        self.assertEqual(report["coverage"]["changed"], 2)
        self.assertEqual(len(report["approved_lines"]), 2)
        self.assertEqual(rewrite.call_args_list[1].args[4], [])
        self.assertEqual(report["speakerbox_sources"], [self.SOURCE])

    def test_paper_counts_untouched_stories_in_coverage(self):
        one = {"body": self.SOURCE, "meta": {}}
        two = {"body": self.SOURCE + "\n\n" + self.SOURCE, "meta": {}}
        with mock.patch.object(app, "crystal_coverage_target", return_value=100):
            app.paper_tint_plan(one)
            app.paper_tint_plan(two)
            one["meta"]["tint"].update(attempted=1, changed=1, met=True, status="complete")
            summary = app.paper_tint_summary([one, two])
        self.assertEqual(summary["eligible"], 3)
        self.assertEqual(summary["attempted"], 1)
        self.assertEqual(summary["changed"], 1)
        self.assertFalse(summary["met"])
        self.assertIn("0/2", app.paper_tint_status(two["meta"]))

    async def test_paper_attempt_is_not_a_success(self):
        story = {"slug": "sample", "body": self.SOURCE, "meta": {}}
        press = {"attempted_paras": 0, "attempted_stories": 0, "tinted_paras": 0,
                 "tinted_stories": 0, "started": 123.0}
        with (mock.patch.dict(app._PAPER_PRESS, press, clear=True),
              mock.patch.object(app, "crystal_coverage_target", return_value=100),
              mock.patch.object(app, "crystal_tint_two_pass", return_value=True),
              mock.patch.object(app, "crystal_active", return_value=[{}]),
              mock.patch.object(app, "paper_tint_left", return_value=20),
              mock.patch.object(app, "tint_should_stop", return_value=""),
              mock.patch.object(app, "crystal_line", return_value=self.SOURCE),
              mock.patch.object(app, "_tint_flow")):
            self.assertFalse(await app.paper_tint_story(story, "test"))
            self.assertEqual(app._PAPER_PRESS["attempted_paras"], 1)
            self.assertEqual(app._PAPER_PRESS["tinted_paras"], 0)
        report = story["meta"]["tint"]
        self.assertEqual(report["status"], "failed")
        self.assertFalse(story["meta"]["tinted"])

    async def test_selected_failed_tint_never_reaches_stream_renderer(self):
        with (mock.patch.object(app, "dj_settings", return_value={**app.DEFAULT_DJ, "caller_static": 0}),
              mock.patch.object(app, "session_voices", return_value={"dj": "test"}),
              mock.patch.object(app, "fresh_pool_top"),
              mock.patch.object(app, "render_backlog_top"),
              mock.patch.object(app, "fresh_pool_take", return_value={}),
              mock.patch.object(app, "dialogue_tint_required", return_value=True),
              mock.patch.object(app, "crystal_coverage_target", return_value=100),
              mock.patch.object(app, "tint_coverage_ready", return_value=False),
              mock.patch.object(app, "tint_output_ready", return_value=False),
              mock.patch.object(app, "crystal_line", return_value=self.SOURCE),
              mock.patch.object(app, "spoken_text", side_effect=lambda t: t),
              mock.patch.object(app, "names_only", return_value=True),
              mock.patch.object(app, "is_binned", return_value=False),
              mock.patch.object(app, "looks_english", return_value=True),
              mock.patch.object(app, "minutes_only", return_value=True),
              mock.patch.object(app, "seat_reseat", side_effect=lambda w: w),
              mock.patch.object(app, "note_drop"),
              mock.patch.object(app, "pipeline_log"),
              mock.patch.object(app, "voice_render_any") as render):
            result = await app._speak_turns_floorless(
                [("A", self.SOURCE)], None, 1, render_stream=True, allow_repeat=True)
        self.assertEqual(result, [])
        render.assert_not_called()

    def test_editorial_change_invalidates_previously_tinted_paragraph(self):
        story = {"body": self.TINTED, "meta": {"tint": {
            "eligible": 1, "attempted": 1, "changed": 1, "required": 1,
            "target": 100, "met": True,
            "paragraphs": [{"key": "body:0", "ok": True,
                            "output_hash": hashlib.sha1(self.TINTED.encode()).hexdigest()}]}}}
        with mock.patch.object(app, "crystal_coverage_target", return_value=100):
            self.assertTrue(app.paper_tint_summary([story])["met"])
            story["body"] = self.SOURCE
            self.assertFalse(app.paper_tint_summary([story])["met"])
        self.assertEqual(story["meta"]["tint"]["changed"], 0)

    def test_paper_visible_interview_and_classified_copy_are_eligible(self):
        story = {"body": "| data | remains a table |", "meta": {
            "interview": {"qa": [{"q": "Who called?", "a": "Mara called."}]},
            "classifieds": [{"body": self.SOURCE, "price": "$12"}]}}
        self.assertEqual([r["key"] for r in app.paper_tint_units(story)],
                         ["qa:0:q", "qa:0:a", "classified:0"])

    def test_image_subjects_are_citizens_or_goods_with_provenance(self):
        pictures = [
            {"name": "resident.png", "desc": "A woman carrying a red suitcase", "kind": "described"},
            {"name": "goods.png", "desc": "A copper kettle with a broken handle", "kind": "shown"},
            {"name": "unknown.png", "desc": "", "kind": "filler"},
        ]
        with mock.patch.object(app, "paper_plate_rank", return_value=(0, 0, 0)):
            subjects = app.paper_gallery_subjects({"pictures": pictures})
        self.assertEqual([s["role"] for s in subjects], ["resident", "goods or service"])
        self.assertIn("resident.png", app.paper_gallery_clause(subjects))
        self.assertIn("Do not sell people", app.paper_gallery_clause(subjects))

    def test_later_radio_hours_rotate_full_newspaper_stories(self):
        edition = {"at": 900.0, "articles": [
            {"file": f"{i}.md", "body": f"Story {i}: " + self.SOURCE,
             "meta": {"headline": f"Story {i}", "section": "gallery"}}
            for i in range(4)]}
        with (mock.patch.dict(app._PAPER_DISCUSSION, {}, clear=True),
              mock.patch.object(app, "paper_latest_id", return_value="edition-1"),
              mock.patch.object(app, "paper_edition_read", return_value=edition) as read,
              mock.patch.object(app.time, "time", return_value=1000.0),
              mock.patch.object(app, "_tint_flow")):
            first = app.paper_discussion_context()
            second = app.paper_discussion_context()
            third = app.paper_discussion_context()
        self.assertEqual(len(first["articles"]), 2)
        self.assertIn(self.SOURCE, first["prompt"])
        self.assertNotEqual(first["articles"], second["articles"])
        self.assertEqual(third, {})
        read.assert_called_once()


if __name__ == "__main__":
    unittest.main()
