"""#1079 the request book; #1080 lanes and the schedule's permit;
#1082 the strike cap and the fault memo."""
import asyncio
import os
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app


def _stagnant(accepted=3):
    return {"ok": False, "coverage": {"accepted": accepted}, "progress": {"turns": [
        {"text": "", "evaluation": {"ok": False, "faults": ["no rhyme evidence"]}}]}}


class StrikeCapTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.now = 50000.0
        self.stack.enter_context(mock.patch.object(app.time, "time", lambda: self.now))
        self.stack.enter_context(mock.patch.object(app, "_tint_retry_context",
                                                   lambda entry, kind: "ctx-1"))
        self.stack.enter_context(mock.patch.object(app, "pipeline_log", mock.Mock()))
        self.stack.enter_context(mock.patch.object(app, "tint_seen", mock.Mock()))

    def test_twelve_answers_strike_the_line_out_and_a_new_lesson_does_not_release_it(self):
        entry = {"prep_kind": "caller"}
        for _ in range(3):
            app._tint_retry_note(entry, "ctx-1", 3, _stagnant(), 4)
            self.now += 2000.0
        state = entry["tint_retry_budget"]
        self.assertTrue(state["exhausted"])
        self.assertEqual(state["strikes"], 12)
        self.assertTrue(app.tint_exhausted(entry))
        self.assertIn("struck out", state["reason"])
        app.tint_seen.assert_called_with("exhausted")
        # A new lesson or prompt revision used to release the wait; not now.
        with mock.patch.object(app, "_tint_retry_context", lambda entry, kind: "ctx-2"):
            status = app.tint_retry_status(entry, "caller")
            self.assertTrue(status["waiting"])
            self.assertEqual(status["release_reason"], "")
            self.assertFalse(app.tint_retry_due(entry, "caller"))
        # Only the operator's own recovery reopens it.
        entry["review_recovery_pending"] = True
        self.assertTrue(app.tint_retry_due(entry, "caller"))

    def test_eleven_answers_still_cool_down_the_old_way(self):
        entry = {}
        app._tint_retry_note(entry, "ctx-1", 3, _stagnant(), 4)
        app._tint_retry_note(entry, "ctx-1", 3, _stagnant(), 4)
        app._tint_retry_note(entry, "ctx-1", 3, _stagnant(), 3)
        state = entry["tint_retry_budget"]
        self.assertEqual(state["strikes"], 11)
        self.assertFalse(state.get("exhausted"))
        self.assertGreater(state["retry_at"], self.now)
        self.assertEqual(state["cooldown_rounds"], 3)

    def test_progress_resets_the_strikes(self):
        entry = {}
        app._tint_retry_note(entry, "ctx-1", 3, _stagnant(), 4)
        app._tint_retry_note(entry, "ctx-1", 3, _stagnant(), 4)
        self.assertEqual(entry["tint_retry_budget"]["strikes"], 8)
        app._tint_retry_note(entry, "ctx-1", 3, _stagnant(accepted=4), 2)
        self.assertEqual(entry["tint_retry_budget"]["strikes"], 0)
        self.assertFalse(entry["tint_retry_budget"].get("exhausted"))

    def test_a_struck_out_row_no_longer_holds_a_stocking_slot(self):
        row = {"text": "Plain words.", "text_plain": "Plain words.",
               "tint_retry_budget": {"exhausted": True}}
        with mock.patch.object(app, "dialogue_entry", lambda r: None), \
                mock.patch.object(app, "dialogue_tint_ready", lambda k, r: False):
            self.assertFalse(app.dialogue_row_viable("banter", row))
            row["tint_retry_budget"] = {}
            self.assertTrue(app.dialogue_row_viable("banter", row))


class FaultMemoTests(unittest.TestCase):
    def setUp(self):
        saved = dict(app._TINT_FAULT_MEMO)
        app._TINT_FAULT_MEMO.clear()

        def restore():
            app._TINT_FAULT_MEMO.clear()
            app._TINT_FAULT_MEMO.update(saved)
        self.addCleanup(restore)

    def test_the_first_ask_carries_the_earlier_refusal(self):
        self.assertEqual(app.tint_prior_lesson("Fresh line.", "road lesson"), "road lesson")
        app.tint_fault_remember("Just get to the point, man.",
                                ["changed name: Mara -> David", "no rhyme evidence"], "Bar one")
        app.tint_fault_remember("  just get to the POINT, man. ", ["no rhyme evidence"], "Bar two")
        lesson = app.tint_prior_lesson("Just get to the point, man.", "road lesson")
        self.assertIn("refused 2 time(s)", lesson)
        self.assertIn("changed name", lesson)
        self.assertIn("Bar two", lesson)
        self.assertTrue(lesson.endswith("road lesson"))
        self.assertEqual(app.tint_fault_memo_status(),
                         {"lines": 1, "refusals": 2, "repeat_lines": 1})

    def test_capture_feeds_the_memo_but_not_for_technical_faults(self):
        lab = mock.Mock()
        lab.current_id.return_value = ""
        with mock.patch.object(app._LINE_REVIEW, "record",
                               return_value={"id": "r1", "event_seq": 1}), \
                mock.patch.object(app, "prompt_learning_observe", mock.Mock()), \
                mock.patch.object(app, "station_flow_event", mock.Mock()), \
                mock.patch.object(app, "_LAB_RUNTIME", lab):
            app.line_review_capture("tint", "A source line here.", "A bar.",
                                    reasons=["no rhyme evidence"], context={"kind": "banter"})
            app.line_review_capture("tint", "A technical one.", "", reasons=["no audio"],
                                    context={"kind": "banter"}, technical=True)
        self.assertIn("refused 1 time(s)", app.tint_prior_lesson("A source line here."))
        self.assertEqual(app.tint_prior_lesson("A technical one."), "")


class LanesTests(unittest.TestCase):
    def test_caps_follow_the_lanes_and_the_schedule_gets_its_permit(self):
        with mock.patch.dict(app.__dict__, {"system2_current_work": lambda: None}):
            with mock.patch.object(app, "OLLAMA_LANES", 1):
                self.assertEqual(app._ollama_category("tint round"), ("tint", 2))
                self.assertEqual(app._ollama_category("banter"), ("station", 2))
            with mock.patch.object(app, "OLLAMA_LANES", 2):
                self.assertEqual(app._ollama_category("tint round"), ("tint", 3))
                self.assertEqual(app._ollama_category("banter"), ("station", 3))
            self.assertEqual(app._ollama_category("interactive"), ("interactive", 0))
            self.assertEqual(app._ollama_category("response_bank"), ("repertoire", 1))
        soon = {"template": {"start": time.time() + 600}}
        with mock.patch.dict(app.__dict__, {"system2_current_work": lambda: soon}), \
                mock.patch.object(app, "OLLAMA_LANES", 1):
            self.assertEqual(app._ollama_category("tint round"), ("tint", 3))
            self.assertEqual(app._ollama_category("banter"), ("station", 2))
        later = {"template": {"start": time.time() + 7200}}
        with mock.patch.dict(app.__dict__, {"system2_current_work": lambda: later}), \
                mock.patch.object(app, "OLLAMA_LANES", 1):
            self.assertEqual(app._ollama_category("tint round"), ("tint", 2))
        room = app.writing_room_state()
        self.assertEqual(room["lanes_per_model"], app.OLLAMA_LANES)
        self.assertEqual(room["category_limits_per_model"]["tint"], room["tint_limit_per_model"])

    def test_the_lane_count_comes_from_the_environment(self):
        with mock.patch.dict(os.environ, {"OLLAMA_LANES": "2"}):
            self.assertEqual(app._ollama_lanes_env(), 2)
        with mock.patch.dict(os.environ, {"OLLAMA_LANES": "nine"}):
            self.assertEqual(app._ollama_lanes_env(), 1)
        with mock.patch.dict(os.environ, {"OLLAMA_LANES": "40"}):
            self.assertEqual(app._ollama_lanes_env(), 4)
        env = {k: v for k, v in os.environ.items() if k != "OLLAMA_LANES"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(app._ollama_lanes_env(), 1)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(app, "PINE_JOURNAL_DIR", root / "pine_journal"))
        self.stack.enter_context(mock.patch.object(app, "PINE_COMPLETED_PATH", root / "pine_completed.md"))
        self.stack.enter_context(mock.patch.object(app, "_PINE_JOURNAL_BACKFILLED", [False]))
        self.stack.enter_context(mock.patch.object(app, "model_calls_rows", lambda since, until: [
            {"at": since + 5, "working_ms": 1500, "ms": 2000, "eval_count": 40,
             "prompt_eval_count": 900}]))

    def test_a_page_is_written_with_costs_and_a_flow(self):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 600))
        request = "make the paper rhyme\n\nAttached images:\n/api/pine-uploads/1-a.png"
        reply = ("## What changed\n\n- the press holds the edition\n- what will not rap is cut\n\n"
                 "## What needs you\n\n1. raise the lanes\n")
        meta = app.pine_journal_write(1077, when, request, reply)
        self.assertEqual(meta["costs"]["tokens_in"], (len(request) + 3) // 4)
        self.assertEqual(meta["costs"]["tokens_out"], (len(reply.strip()) + 3) // 4)
        self.assertEqual(meta["costs"]["model_calls"], 1)
        self.assertEqual(meta["costs"]["model_seconds"], 1.5)
        self.assertEqual(meta["costs"]["model_tokens_out"], 40)
        self.assertGreaterEqual(meta["costs"]["elapsed_s"], 540)
        self.assertEqual(meta["images"], ["/api/pine-uploads/1-a.png"])
        self.assertEqual(meta["title"], "make the paper rhyme")
        kinds = [n["kind"] for n in meta["graph"]["nodes"]]
        self.assertEqual(kinds, ["request", "section", "step", "step", "section", "step"])
        self.assertEqual(meta["graph"]["edges"][1], {"from": "n1", "to": "n2"})
        self.assertEqual(meta["graph"]["edges"][3], {"from": "n0", "to": "n4"})
        md = (app.PINE_JOURNAL_DIR / "1077.md").read_text(encoding="utf-8")
        self.assertIn("# Request #1077", md)
        self.assertIn("> make the paper rhyme", md)
        self.assertIn("![attachment](/api/pine-uploads/1-a.png)", md)
        self.assertIn("| tokens in |", md)

    def test_a_reply_without_headings_gets_its_paragraphs_as_sections(self):
        graph = app.pine_journal_graph(9, "hello", "Short.\n\nThe first real paragraph of the reply.\n\n"
                                       "- a step under it\n\nAnother paragraph that stands alone.")
        kinds = [n["kind"] for n in graph["nodes"]]
        self.assertEqual(kinds, ["request", "section", "step", "section"])

    def test_the_archive_is_backfilled_once_and_paged_newest_first(self):
        app.PINE_COMPLETED_PATH.write_text(
            "<!-- Pine Box completed requests and verification. -->\n\n"
            "## #1069 — 2026-09-08 03:10 — resolved\nSubmitted: 2026-09-07 22:01\n\n"
            "fewer rejections\n\nResolution: Done.\nSecond line.\n\n"
            "## #1068 — 2026-09-08 03:09 — resolved\nSubmitted: 2026-09-07 21:50\n\n"
            "clear the cache\n\nResolution: (resolved)\n\n", encoding="utf-8")
        pages = app.pine_journal_index()
        self.assertEqual([p["id"] for p in pages], [1069, 1068])
        self.assertEqual(pages[0]["title"], "fewer rejections")
        self.assertEqual(pages[0]["when"], "2026-09-07 22:01")
        page = app.pine_journal_page(1068)
        self.assertEqual((page["previous_id"], page["next_id"], page["page"], page["pages"]),
                         (1069, None, 2, 2))
        self.assertEqual(app.pine_journal_page(1069)["reply"], "Done.\nSecond line.")
        self.assertEqual(app.pine_journal_page(1069)["next_id"], 1068)
        self.assertIsNone(app.pine_journal_page(5))
        self.assertEqual(app.pine_journal_backfill(), 0)
        self.assertTrue((app.PINE_JOURNAL_DIR / "1068.md").exists())

    def test_the_book_is_served(self):
        if app.LOCK_READS:
            self.skipTest("reads are locked in this environment")
        app.pine_journal_write(1070, "2026-09-08 01:34", "finish the tasks", "## Done\n\n- all of it\n")
        listed = asyncio.run(app.pine_journal_list(authorization=None, key=""))
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["pages"][0]["id"], 1070)
        page = asyncio.run(app.pine_journal_read(1070, authorization=None, key=""))
        self.assertEqual(page["graph"]["nodes"][1]["label"], "Done")
        raw = asyncio.run(app.pine_journal_markdown(1070, authorization=None, key=""))
        self.assertIn(b"# Request #1070", raw.body)
        self.assertIn("text/markdown", raw.media_type)
        with self.assertRaises(app.HTTPException):
            asyncio.run(app.pine_journal_read(4242, authorization=None, key=""))
        html = asyncio.run(app.journal_page())
        self.assertIn("The request book", html)
        self.assertIn("/api/pine-journal", html)


if __name__ == "__main__":
    unittest.main()
