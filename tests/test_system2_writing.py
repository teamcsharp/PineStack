"""Scoped authoring budgets and actual dj_banter source/prompt integration."""
import ast
import copy
import inspect
import re
import unittest
from contextlib import ExitStack
from unittest import mock

import system2_runtime as runtime
from system2_writing import source_thought, turn_instruction, scene_complete


class SourceTests(unittest.TestCase):
    def test_selects_complete_sentence_and_keeps_full_exact_evidence(self):
        text = "The night train reached the platform. " + "The next complete sentence is much longer. " * 20
        row = {"file": "source.md", "text": text, "lines": [text], "id": "source-id"}
        original = copy.deepcopy(row)
        got = source_thought(row, 100)
        self.assertEqual(got["text"], "The night train reached the platform.")
        self.assertEqual(got["original_source"]["text"], text)
        self.assertEqual(got["original_source"]["lines"], [text])
        self.assertEqual(row, original)
        self.assertEqual(got["file"], "source.md")

    def test_no_partial_sentence_or_lost_honorific(self):
        self.assertEqual(source_thought({"text": "a long unfinished source without terminal punctuation"}, 20)["text"], "")
        self.assertEqual(source_thought({"text": "Dr. Smith brought the samples home."}, 80)["text"],
                         "Dr. Smith brought the samples home.")
        self.assertEqual(source_thought({"text": "This entire sentence cannot fit this tiny budget."}, 12)["text"], "")

    def test_budget_is_task_local_and_does_not_shrink_crystal_reply_cap(self):
        settings = {"reply_max_chars": 6500, "banter_max_lines": 24,
                    "banter_min_lines": 16, "third_name": "Old", "third_voice": "old"}
        self.assertIs(runtime.settings_for_work(settings), settings)
        token = runtime.WORK.set({"kind": "caller", "generation_turns": 6,
                                  "template": {"seconds": 180, "target_seconds": 180}})
        try:
            scoped = runtime.settings_for_work(settings)
        finally:
            runtime.WORK.reset(token)
        budget = scoped["system2_budget"]
        self.assertEqual(budget["seconds"], 90)
        self.assertEqual(budget["turns"], 11)
        self.assertLessEqual(budget["words_high"], 20)
        self.assertLess(budget["max_chars"], 1500)
        self.assertEqual(scoped["reply_max_chars"], 6500)
        self.assertEqual(settings["banter_max_lines"], 24)
        self.assertIs(runtime.settings_for_work(settings), settings)
        self.assertIn("complete", turn_instruction(budget))

    def test_remaining_debt_and_guest_overlay_survive_together(self):
        token = runtime.WORK.set({"kind": "banter", "generation_turns": 6,
                                  "template": {"seconds": 180, "debt_seconds": 60},
                                  "guest": {"name": "Guest", "voice": "guest-voice", "who": "Author"}})
        try:
            settings = runtime.settings_for_work({"reply_max_chars": 6500})
        finally:
            runtime.WORK.reset(token)
        self.assertEqual(settings["third_voice"], "guest-voice")
        self.assertEqual(settings["system2_budget"]["seconds"], 60)
        self.assertEqual(settings["system2_budget"]["turns"], 6)

    def test_short_scene_requires_complete_thoughts_and_turns(self):
        turns = [(m, "The train reached the platform and we heard it.") for m in ("A", "B", "A", "B")]
        self.assertTrue(scene_complete(turns, 4))
        self.assertFalse(scene_complete(turns[:2], 4))
        self.assertFalse(scene_complete(turns[:-1] + [("B", "The train reached the platform and")], 4))


class StopAtTint(BaseException):
    pass


class WriterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import app
        self.app = app
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.draft = "\n".join(f"{m}: The train reached the platform, and this complete reply explains the detail." for m in ("A", "B", "A", "B", "A", "B"))
        self.source = {"file": "source.md", "text": "The night train reached the platform. " + "Another full sentence is retained only as evidence. " * 20}
        self.settings = copy.deepcopy(app.DEFAULT_DJ)
        self.settings.update(banter=True, reply_max_chars=6500, speakbox_rate=1,
            speakbox_prepend_rate=1, speakbox_append_rate=1, speakbox_full_swath_rate=1,
            speakbox_quotes_system2=False,   # [#1233] this fixture proves the switch
            speakbox_full_swath_chars=2600, banter_max_lines=24, banter_min_lines=16,
            third_name="", drop_voice="", heat_rate=0, lyrics_talk=False,
            banter_engine="one-call")
        original = app.dj_banter
        tree = ast.parse(inspect.getsource(original))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        keep = {"dj_banter", "banter_bank_plan", "plot_label_scrub",
                "system2_current_work", "system2_source_thought",
                "system2_turn_instruction", "system2_stamp_entry",
                "system2_scene_complete"}
        for name in names - keep:
            value = getattr(app, name, None)
            if inspect.isfunction(value):
                patcher = mock.AsyncMock if inspect.iscoroutinefunction(value) else mock.Mock
                self.stack.enter_context(mock.patch.object(app, name, patcher(return_value="")))
        self.stack.enter_context(mock.patch.object(app, "_RADIO", {"on": True, "voices": {}, "chat": []}))
        self.stack.enter_context(mock.patch.object(app, "_LARDER", []))
        self.stack.enter_context(mock.patch.object(app.random, "random", return_value=.99))
        app.dj_settings.side_effect = lambda: runtime.settings_for_work(self.settings)
        app.approach_pick.return_value = {}
        app.banter_material.return_value = {}
        app.paper_discussion_context.return_value = {}
        app.speakbox_quote.return_value = copy.deepcopy(self.source)
        app.speakbox_aside.side_effect = lambda row, **kw: " Use this exact source: " + row.get("text", "")
        app.box_rate_now.return_value = 1
        app.phrase_pressure.return_value = 1  # strongest legacy postdraft inflation
        app.ask_model.return_value = self.draft
        app.banter_turns.side_effect = lambda text, *args: re.findall(r"([ABCDE]):\s*(.*?)(?=\n[ABCDE]:|$)", text, re.S)
        app.unrepeated.side_effect = lambda values, *args, **kw: values[0] if values else ""
        app._radio_draft_review.return_value = True
        app.crystal_tint_two_pass.return_value = True
        self.tint_inputs = []
        async def stop(script, *args, **kw):
            self.tint_inputs.append(script)
            raise StopAtTint()
        app.crystal_tint.side_effect = stop
        async def scoped(awaitable, *args, **kw):
            return await awaitable
        app._line_review_scoped.side_effect = scoped
        self.writer = original

    async def test_actual_writer_has_short_prompt_and_no_postdraft_source_padding(self):
        token = runtime.WORK.set({"kind": "banter", "generation_turns": 6,
            "template": {"seconds": 180}, "slot_id": "slot", "job_id": "job", "trace_id": "trace"})
        self.addCleanup(runtime.WORK.reset, token)
        try:
            await self.writer(angle="A precise story about the train.", lines=6, bank=True, force_seed=True)
        except StopAtTint:
            pass
        else:
            self.fail("Writer stopped before tint: " + str(self.app.pipeline_log.call_args_list)[-1500:])
        calls = self.app.ask_model.call_args_list
        self.assertEqual(len(calls), 1)
        prompt = calls[0].args[0]
        self.assertIn("complete short scene", prompt)
        self.assertNotIn("60 to 100 words", prompt)
        self.assertNotIn(self.source["text"], prompt)
        self.assertIn("The night train reached the platform.", prompt)
        self.assertLess(calls[0].kwargs["limit"], 1600)
        self.assertEqual(self.tint_inputs, [self.draft])
        self.app.speakbox_remember.assert_not_called()
        self.app.blend_script.assert_not_called()

    async def test_actual_repair_uses_same_short_budget_and_keeps_candidate(self):
        first = "A: The train reached the platform and nobody answered it."
        self.app.ask_model.side_effect = [first, self.draft]
        self.app._radio_draft_review.return_value = False
        token = runtime.WORK.set({"kind": "banter", "generation_turns": 6,
            "template": {"seconds": 180}, "slot_id": "slot", "job_id": "job", "trace_id": "trace"})
        self.addCleanup(runtime.WORK.reset, token)
        with self.assertRaises(StopAtTint):
            await self.writer(angle="A precise story about the train.", lines=6, bank=True, force_seed=True)
        self.assertEqual(self.app.ask_model.call_count, 2)
        initial, repair = self.app.ask_model.call_args_list
        self.assertIn(first, repair.args[0])
        self.assertIn("complete short exchange", repair.args[0])
        self.assertNotIn("at least 55 words", repair.args[0])
        self.assertEqual(initial.kwargs["limit"], repair.kwargs["limit"])
        self.assertEqual(self.tint_inputs, [self.draft])


if __name__ == "__main__":
    unittest.main()
