"""2026-09-08 (evening): "once the words are rhyming ... I want to keep and
reuse the elements that are converted into song lyrics. These should fill all
the dead air and keep the station rapping 24/7." And the orchestrator's own
reflection on what passed and what did not."""
import json
import time
import unittest
from contextlib import ExitStack
from unittest import mock

import app


BAR = "The plate is copper, mate / the station cannot wait"


class GoldHarvestTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.gold = {"loaded": True, "rows": []}
        self.pantry = {"k1": {"text": "The plate is copper, mate, the station cannot wait", "who": "cohost",
                              "clip": {"path": "/media/take-1.wav", "seconds": 4.2}},
                       "k2": {"text": "A plain line that never rhymed at all", "who": "dj",
                              "clip": {"path": "/media/take-2.wav", "seconds": 3.0}}}
        for name, value in {"_GOLD": self.gold, "_gold_save": mock.Mock(), "_PANTRY": self.pantry,
                            "_pantry_key_ready": lambda key: key in self.pantry,
                            "_row_clip_keys": lambda row, depth=0: list(row.get("keys") or []),
                            "pipeline_log": mock.Mock(), "_clip_seconds": lambda path: 4.2}.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    def test_the_passed_bars_of_a_cut_round_become_gold_with_their_takes(self):
        entry = {"keys": ["k1", "k2"], "tint_progress": {"turns": [
            {"marker": "B", "text": BAR, "evaluation": {"ok": True}},
            {"marker": "A", "text": "A plain line that never rhymed at all", "evaluation": {"ok": False}, "cut": True},
        ]}}
        self.assertEqual(app.gold_harvest_entry(entry, "tint strike"), 1)
        rows = self.gold["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["who"], "cohost")
        self.assertEqual(rows[0]["path"], "take-1.wav")
        self.assertEqual(rows[0]["seconds"], 4.2)
        # Twice is once: the store is keyed on the words.
        self.assertEqual(app.gold_harvest_entry(entry, "again"), 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(app.gold_harvest_entry({"tint_progress": {"turns": []}}, "x"), 0)

    def test_a_bar_whose_take_is_gone_is_not_gold(self):
        entry = {"keys": ["k9"], "tint_progress": {"turns": [{"marker": "B", "text": BAR, "evaluation": {"ok": True}}]}}
        self.assertEqual(app.gold_harvest_entry(entry, "x"), 0)


class GoldGapTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.gold = {"loaded": True, "rows": [
            {"key": "a", "who": "cohost", "text": BAR, "path": "take-1.wav", "seconds": 4.2,
             "at": time.time() - 3600, "fired": 0, "last": 0.0}]}
        self.speak = mock.AsyncMock(return_value="ok")
        for name, value in {"_GOLD": self.gold, "_gold_save": mock.Mock(), "pipeline_log": mock.Mock(),
                            "dj_speak": self.speak, "media_sign": lambda name: "sig-" + name,
                            "VOICE_MEDIA_DIR": mock.MagicMock()}.items():
            self.stack.enter_context(mock.patch.object(app, name, value))
        app.VOICE_MEDIA_DIR.__truediv__ = lambda self_, name: mock.Mock(is_file=lambda: True)

    async def test_a_gold_bar_fills_the_air_without_a_render(self):
        self.assertEqual(await app.gold_fill_gap("dead air"), "bar")
        self.speak.assert_awaited_once()
        kwargs = self.speak.await_args.kwargs
        self.assertEqual(kwargs["clip"]["path"], "/media/take-1.wav")
        self.assertEqual(kwargs["clip"]["sig"], "sig-take-1.wav")
        self.assertEqual(kwargs["who"], "cohost")
        self.assertTrue(kwargs["checked"])
        self.assertFalse(kwargs["sting"])
        self.assertEqual(self.gold["rows"][0]["fired"], 1)
        # It rests five minutes on the dead-air road, twenty on the sting road.
        self.assertEqual(await app.gold_fill_gap("dead air"), "")
        self.assertIsNone(app.gold_pick())
        self.gold["rows"][0]["last"] = time.time() - 301
        self.assertIsNotNone(app.gold_pick(min_rest=app.GOLD_GAP_REST))
        self.assertIsNone(app.gold_pick())

    async def test_the_gap_filler_reaches_for_gold_before_the_sample(self):
        radio = {"on": True, "voice_to": "box"}
        sting = mock.AsyncMock(return_value="sample.wav")
        with mock.patch.object(app, "_RADIO", radio), mock.patch.object(app, "_SPEAKING", [0]), \
                mock.patch.object(app, "_SPOKE_AT", [0.0]), mock.patch.object(app, "radio_paused", lambda: False), \
                mock.patch.object(app, "_floor_busy", lambda: False), \
                mock.patch.object(app, "dj_settings", lambda: {"sfx_gap": 0, "drop_voice": ""}), \
                mock.patch.object(app, "box_talk_ok", lambda: True), mock.patch.object(app, "box_firmware_down_now", lambda: False), \
                mock.patch.object(app, "_SFX_GAP", {"at": 0.0, "turn": 0, "count": 0, "why": "", "went": ""}), \
                mock.patch.object(app, "SFX_GAP_REST", 0.0), mock.patch.object(app, "dj_sting", sting):
            self.assertEqual(await app.sfx_fill_gap("silence"), "bar")
            sting.assert_not_awaited()
            # The bar rests; the sample is what is left.
            app._SFX_GAP["at"] = 0.0
            self.assertEqual(await app.sfx_fill_gap("silence"), "sample")
            # Under a held floor a bar would take the floor: sample only.
            app._SFX_GAP["at"] = 0.0
            self.gold["rows"][0]["last"] = 0.0
            with mock.patch.object(app, "_floor_busy", lambda: True):
                self.assertEqual(await app.sfx_fill_gap("rendering", under_floor=True), "sample")


class ReflectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.state = {"loaded": True, "roads": {}, "running": "", "last": {}, "errors": []}
        self.ring = [
            {"at": time.time() - 60, "ok": True, "machine_ok": True, "kind": "caller", "rhyme": True,
             "source": "Hold on to line seven five six three eight.", "candidate": "Hold the line, seven five six three eight / hello now, what you see there, mate",
             "faults": []},
            {"at": time.time() - 50, "ok": False, "machine_ok": False, "kind": "caller", "rhyme": False,
             "source": "Sarah is calling from the bus shelter.", "candidate": "Sarah calls from the shelter of the bus",
             "faults": ["no rhyme evidence - the bar does not land a rhyme"]},
            {"at": time.time() - 40, "ok": False, "machine_ok": False, "kind": "banter", "rhyme": False,
             "source": "x", "candidate": "y", "faults": ["semantic preservation failed"]},
        ]
        outcomes = [{"at": time.time() - 30, "kind": "caller", "stage": "first", "machine_ok": i % 3 != 0,
                     "effective_ok": i % 3 != 0, "faults": [] if i % 3 else ["rhyme"]} for i in range(12)]
        learner = mock.Mock()
        learner.recent_outcomes = lambda kind="", since=0.0, limit=800: [o for o in outcomes if o["kind"] == kind]
        store = mock.Mock()
        store.summaries = lambda **kw: {"items": []}
        for name, value in {"_REFLECTION": self.state, "_reflection_save": mock.Mock(),
                            "_TINT_JUDGE_RING": self.ring, "_PROMPT_LEARNING": learner, "_LINE_REVIEW": store,
                            "pipeline_log": mock.Mock(), "note_action": mock.Mock(),
                            "tint_model_for": lambda kind="": "deep-model", "model_ctx": lambda: 8192,
                            "_TINT_OUTPUT_READY": {}}.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    def test_the_hour_is_gathered_with_counts_from_the_learner(self):
        got = app.reflection_gather("caller", time.time() - 3600)
        self.assertEqual(len(got["accepted"]), 1)
        self.assertEqual(len(got["refused"]), 1)
        self.assertEqual(got["attempts"], 12)
        self.assertEqual(got["passes"], 8)
        self.assertEqual(got["refusals"], 4)
        self.assertEqual(got["top_faults"], ["rhyme"])

    def test_the_reply_is_read_leniently(self):
        parsed = app.reflection_parse('Sure.\n{"rules": ["Land the caller\'s number on a rhyme word, not mid-bar.", "x"], "exemplars": [1, "2"], "note": "Numbers end bars."}')
        self.assertEqual(len(parsed["rules"]), 1)
        self.assertEqual(parsed["exemplars"], [1, 2])
        self.assertEqual(parsed["note"], "Numbers end bars.")
        bullets = app.reflection_parse("- Land every phone number at the end of a bar.\n- keep it")
        self.assertEqual(bullets["rules"], ["Land every phone number at the end of a bar."])

    async def test_a_reflection_is_kept_and_rides_the_prompt_then_retires_when_the_road_gets_worse(self):
        reply = {"message": {"content": json.dumps({
            "rules": ["Land the caller's number at the end of the first bar and rhyme the second on it.",
                      "Keep the caller's name in the first bar.", "Say the place once, plainly."],
            "exemplars": [1], "note": "Numbers make the landing."})}}
        with mock.patch.object(app, "call_ollama", mock.AsyncMock(return_value=reply)) as call:
            got = await app.reflection_run("caller")
        self.assertTrue(got["ok"], got)
        self.assertEqual(call.await_args.kwargs["model"], "deep-model")
        self.assertEqual(call.await_args.kwargs["purpose"], "station:reflection")
        version = app.reflection_current("caller")
        self.assertEqual(version["version"], 1)
        self.assertEqual(len(version["rules"]), 3)
        self.assertAlmostEqual(version["born_rate"], 8 / 12, places=3)
        self.assertEqual(version["exemplars"][0]["candidate"][:13], "Hold the line")
        guidance = app.reflection_guidance("caller")
        self.assertIn("THE ORCHESTRATOR'S REFLECTION on caller lines (version 1", guidance)
        self.assertIn("Land the caller's number", guidance)
        self.assertIn("BARS OF THIS ROAD THAT PASSED", guidance)
        self.assertLessEqual(len(guidance), app.REFLECTION_GUIDANCE_CHARS + 2)
        self.assertEqual(app.reflection_version("caller"), 1)
        self.assertEqual(app.reflection_guidance("banter"), "")
        # The hour under it went worse: the version retires and the prompt block goes.
        self.assertIsNotNone(app.reflection_judge("caller", 0.4, 20))
        self.assertTrue(version["retired"])
        self.assertEqual(app.reflection_guidance("caller"), "")
        # A thin hour does not reflect; a forced one does.
        thin = mock.Mock()
        thin.recent_outcomes = lambda kind="", since=0.0, limit=800: []
        with mock.patch.object(app, "_PROMPT_LEARNING", thin), mock.patch.object(app, "_TINT_JUDGE_RING", []):
            self.assertFalse((await app.reflection_run("caller"))["ok"])
        status = app.reflection_status()
        self.assertEqual(status["roads"]["caller"]["versions"], 1)
        self.assertEqual(status["roads"]["caller"]["current"], 0)

    def test_the_due_road_is_the_one_with_the_most_refusals(self):
        self.assertEqual(app.reflection_due(), "caller")
        self.state["last"]["caller"] = time.time()
        self.assertEqual(app.reflection_due(), "")


if __name__ == "__main__":
    unittest.main()
