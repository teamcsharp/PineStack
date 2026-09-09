"""2026-09-08, the rejections census: 974 pending cuts were read. A transcript
repair with no full stop is the repair, not a fragment; a round whose facts
arrive in its angle is not fed a film transcript; the repair ask says what to
do; a bar that later passed retires the cuts of its line."""
import unittest
from unittest import mock

import system2_runtime as runtime

import app
import crystal_rhyme
import test_crystal_model_output as adapter_fixture
import test_system2_writing as writer_fixture


class TranscriptRepairTests(unittest.IsolatedAsyncioTestCase):
    setUp = adapter_fixture.CrystalModelOutputTests.setUp

    async def test_a_long_repair_without_a_full_stop_is_the_repair(self):
        body = " ".join(f"and then the speaker number {i} said the thing about the copper plate"
                        for i in range(12))
        self.assertGreaterEqual(len(body), 400)
        self.assertNotRegex(body, r"[.!?]")
        self.call.return_value = {"message": {"content": body}, "done_reason": "stop"}
        # The repair road asks with a document-sized limit; the default 300 is for spoken lines.
        self.assertEqual(await app.ask_model("Repair.", limit=6000, result_contract="transcript_repair"), body)
        app.line_review_permits.assert_not_called()

    async def test_a_short_repair_that_stops_mid_thought_is_still_held(self):
        self.call.return_value = {"message": {"content": "Mara left the"}}
        self.assertEqual(await app.ask_model("Repair.", result_contract="transcript_repair"), "")
        self.assertEqual(app.line_review_permits.call_args.args[:2], ("draft_fragment", "Mara left the"))

    async def test_a_long_unpunctuated_draft_on_an_ordinary_road_is_still_a_fragment(self):
        body = " ".join("an ordinary dialogue draft that never finishes a sentence" for _ in range(10))
        self.call.return_value = {"message": {"content": body}}
        self.assertEqual(await app.ask_model("Write dialogue."), "")
        self.assertEqual(app.line_review_permits.call_args.args[0], "draft_fragment")

    async def test_a_json_shaped_reply_is_not_a_fragment(self):
        body = '{"lines": ["The plate is copper", "the station waits"]}'
        self.call.return_value = {"message": {"content": body}}
        self.assertEqual(await app.ask_model("Plan the hour."), body)
        app.line_review_permits.assert_not_called()


class RepairHintTests(unittest.TestCase):
    VOCAB = frozenset("plate gate weight freight man pan ran clan station copper night light "
                      "bright midnight sight".split())

    def setUp(self):
        self.stack = mock.patch.object(app, "_crystal_vocab", return_value=self.VOCAB)
        self.stack.start()
        self.addCleanup(self.stack.stop)
        app._RHYME_OPTIONS_MEMO.update(vocab=None, words={})

    def test_rhyme_options_are_crystal_words_the_grader_would_accept(self):
        options = app.rhyme_options_for("late")
        self.assertTrue(options)
        for word in options:
            with self.subTest(word=word):
                self.assertIn(word, self.VOCAB)
                # 2026-09-08 (the deep scan): the grader's reading is the
                # spelling proof OR the pronouncing dictionary, and the
                # suggestions are now picked by the dictionary first - late/
                # weight and late/freight are perfect rhymes the spelling
                # reader refuses over their digraph. Measured before this,
                # 64% of the words the hint offered were not rhymes at all.
                self.assertTrue(app._rap_slant("late", word, end=True)
                                or crystal_rhyme.rhymes_with("late", word), word)
        self.assertNotIn("late", options)
        self.assertEqual(app.rhyme_options_for("x"), [])
        self.assertEqual(app.rhyme_options_for(""), [])

    def test_a_no_rhyme_fault_names_both_landings_and_offers_words(self):
        hint = app.tint_repair_hint(
            "The station needs a copper plate before midnight.",
            "The station wants a copper plate / before the midnight man",
            ["no rhyme evidence - the bar does not land a rhyme"], {})
        self.assertIn("'plate'", hint)
        self.assertIn("'man'", hint)
        self.assertTrue(any(word in hint for word in ("gate", "weight", "freight")), hint)
        self.assertTrue(any(word in hint for word in ("pan", "ran", "clan")), hint)

    def test_a_meaning_fault_says_which_facts_to_put_back(self):
        semantic = {"missing": ["copper", "midnight"],
                    "missing_names": [{"text": "Mara", "normalized": "mara"}],
                    "missing_numbers": [{"kind": "number", "value": "12", "count": 1}],
                    "added_numbers": [{"kind": "number", "value": "3", "count": 1}],
                    "question": True, "negation": False}
        hint = app.tint_repair_hint("Mara needs twelve copper plates by midnight, not three.",
                                    "She needs plates tonight, three of them.",
                                    ["semantic preservation failed"], semantic)
        for expected in ("MEANING", "Mara", "12", "drop the number you added: 3", "negation",
                         "copper", "midnight"):
            with self.subTest(expected=expected):
                self.assertIn(expected, hint)

    def test_no_fault_no_hint_and_a_broken_report_never_raises(self):
        self.assertEqual(app.tint_repair_hint("a", "b", [], {}), "")
        self.assertIsInstance(app.tint_repair_hint("a", None, ["no rhyme evidence"], None), str)

    def test_the_evaluation_report_carries_the_hint_the_repair_ask_reads(self):
        report = app.tint_evaluate("The station needs a copper plate before midnight.",
                                   "The station needs a copper plate before midnight.",
                                   [], force=0.88, strict=False)
        self.assertFalse(report["ok"])
        self.assertTrue(report["repair_hint"])
        passed = app.tint_evaluate("The station needs a copper plate before midnight.",
                                   "Before midnight the station needs its plate / copper, not chrome, "
                                   "and it cannot wait",
                                   [], force=0.88, strict=False)
        if passed["ok"]:
            self.assertEqual(passed["repair_hint"], "")


class OwnMaterialTests(unittest.IsolatedAsyncioTestCase):
    setUp = writer_fixture.WriterTests.setUp

    async def test_a_round_with_its_own_material_draws_no_speakbox_seed(self):
        token = runtime.WORK.set({"kind": "news", "generation_turns": 6,
                                  "template": {"seconds": 180}, "slot_id": "slot",
                                  "job_id": "job", "trace_id": "trace"})
        self.addCleanup(runtime.WORK.reset, token)
        try:
            await self.writer(angle="The wire: the council voted on the copper plate.", lines=6,
                              bank=True, force_seed=True, own_material=True)
        except writer_fixture.StopAtTint:
            pass
        self.app.speakbox_quote.assert_not_called()
        prompt = self.app.ask_model.call_args_list[0].args[0]
        self.assertNotIn("The night train reached the platform.", prompt)
        self.assertIn("the council voted on the copper plate", prompt)

    async def test_the_same_round_without_the_flag_still_draws_its_seed(self):
        token = runtime.WORK.set({"kind": "banter", "generation_turns": 6,
                                  "template": {"seconds": 180}, "slot_id": "slot",
                                  "job_id": "job", "trace_id": "trace"})
        self.addCleanup(runtime.WORK.reset, token)
        try:
            await self.writer(angle="A precise story about the train.", lines=6, bank=True, force_seed=True)
        except writer_fixture.StopAtTint:
            pass
        self.app.speakbox_quote.assert_called()

    async def test_the_legacy_road_with_its_own_material_staples_no_swath(self):
        # No System2 work: the legacy prepend / append / full-swath draws are live
        # and every rate fires (random -> 0, box_rate_now -> 1).
        self.app.random.random.return_value = 0.0
        try:
            await self.writer(angle="The wire: the council voted on the copper plate.", lines=6,
                              own_material=True)
        except writer_fixture.StopAtTint:
            pass
        self.app.speakbox_quote.assert_not_called()

    def test_the_roads_that_carry_their_own_facts_say_so(self):
        import inspect
        for name in ("_news_once", "dj_recap", "dj_fan_mail", "dj_manager_call"):
            fn = getattr(app, name, None)
            if fn is None:
                continue
            with self.subTest(road=name):
                self.assertIn("own_material=True", inspect.getsource(fn))


if __name__ == "__main__":
    unittest.main()
