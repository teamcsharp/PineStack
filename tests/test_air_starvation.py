"""2026-09-07: the station played records and nothing else under the hold.

The deep lane was serial and every refused bar cost a further ask; sixteen
finished rounds sat behind an alignment refusal; a plain re-aired call passed
no gate; a stray "resume radio" off the mic unpaused a deliberate pause; and
no sound effect could play without a line to ride on."""
import unittest
from unittest import mock

import app
from tint_recovery import evaluate_legacy, align_turns

BAR = "Copper plate by midnight or the lights go dark, that's the spark."
PLAIN = "That explains my call, I thought the station should have a report from outside the room."


def _bar_grader(source, candidate, chunks, answering="", force=0.0, kind="", **kw):
    ok = " / " in str(candidate) or ", " in str(candidate)
    return {"ok": bool(ok), "faults": [] if ok else ["no rhyme evidence - the bar does not land a rhyme"]}


class RepassTests(unittest.IsolatedAsyncioTestCase):
    async def test_refused_bars_are_re_asked_together_once(self):
        turns = [("A", "one plain line here"), ("B", "two plain line here"), ("A", "three plain line here")]
        first = [{"marker": "A", "source": "x", "text": "bar one / done", "selected": True, "evaluation": {}},
                 {"marker": "B", "source": "y", "text": "two plain line here", "selected": True, "evaluation": {}},
                 {"marker": "A", "source": "z", "text": "three plain line here", "selected": True, "evaluation": {}}]
        asks = []

        async def _ask(prompt, **kw):
            asks.append(prompt)
            return "2: bar two / a shoe\n3: bar three / a tree"

        with (mock.patch.object(app, "tint_evaluate", side_effect=_bar_grader),
              mock.patch.object(app, "ask_model", side_effect=_ask),
              mock.patch.object(app, "tint_should_stop", return_value=""),
              mock.patch.object(app, "crystal_force", return_value=0.88),
              mock.patch.object(app, "tint_seen"),
              mock.patch.object(app, "pipeline_log")):
            rows, batched = await app._crystal_round_repass(
                turns, first, "ARMED", "DOOM", [], [], "deep", "banter")
        self.assertTrue(batched)
        self.assertEqual(len(asks), 1)                       # nothing left after one pass
        self.assertIn("2: two plain line here", asks[0])
        self.assertNotIn("1: one plain line here", asks[0])  # the bar that passed is not re-asked
        self.assertEqual(rows[1]["text"], "bar two, a shoe")  # cleaned like a single bar
        self.assertTrue(rows[1]["evaluation"]["ok"])
        self.assertTrue(rows[2]["evaluation"]["ok"])
        self.assertEqual(rows[0]["text"], "bar one / done")

    async def test_a_stubborn_line_is_left_for_the_line_pass_after_two_passes(self):
        turns = [("A", "one plain line here"), ("B", "two plain line here")]
        first = [{"marker": "A", "text": "bar one / done", "selected": True, "evaluation": {}},
                 {"marker": "B", "text": "two plain line here", "selected": True, "evaluation": {}}]
        asks = []

        async def _ask(prompt, **kw):
            asks.append(prompt)
            return "2: still plain"

        with (mock.patch.object(app, "tint_evaluate", side_effect=_bar_grader),
              mock.patch.object(app, "ask_model", side_effect=_ask),
              mock.patch.object(app, "tint_should_stop", return_value=""),
              mock.patch.object(app, "crystal_force", return_value=0.88),
              mock.patch.object(app, "tint_seen"),
              mock.patch.object(app, "pipeline_log")):
            rows, batched = await app._crystal_round_repass(
                turns, first, "ARMED", "DOOM", [], [], "deep", "banter")
        self.assertTrue(batched)
        self.assertEqual(len(asks), 2)
        self.assertEqual(rows[1]["text"], "two plain line here")
        self.assertFalse(rows[1]["evaluation"]["ok"])


class LeakTests(unittest.TestCase):
    def test_a_rerun_must_rap_under_the_hold(self):
        raps = {"transcript": [{"text": BAR}, {"text": BAR}, {"text": PLAIN}]}
        plain = {"transcript": [{"text": PLAIN}, {"text": PLAIN}, {"text": BAR}]}
        self.assertTrue(app._rerun_rhymes(raps))
        self.assertFalse(app._rerun_rhymes(plain))
        self.assertFalse(app._rerun_rhymes({"transcript": [{"text": BAR}]}))   # too short to judge

    def test_a_struck_call_is_untinted_under_the_hold(self):
        entry = {"script_plain": "A: " + PLAIN, "script_tinted": "A: " + BAR, "script": "A: " + BAR,
                 "use": "tinted", "tint": {"ok": True, "coverage": {"met": True, "version": 4}}}
        with (mock.patch.object(app, "crystal_tint_holds", return_value=True),
              mock.patch.object(app, "_dialogue_audio_drop"),
              mock.patch.object(app, "call_entry_regrade", return_value={"ok": True})):
            app._call_tint_strike(entry, ["it rambled"])
        self.assertEqual(entry["script"], "A: " + PLAIN)
        self.assertFalse(entry["tint"]["ok"])
        self.assertEqual(entry["tint"]["coverage"], {})

    def test_a_spoken_resume_wrapped_in_a_recording_is_refused(self):
        with mock.patch.object(app, "pipeline_log"):
            self.assertEqual(app.station_intent("resume the radio"), "unpause")
            self.assertEqual(app.station_intent("hey pine box, unpause the radio please"), "unpause")
            self.assertEqual(app.station_intent(
                "Okay, the resume radio what it's very noble of you to try and cover for Tim but the reali"), "")

    def test_a_real_pause_with_a_tail_is_a_command(self):
        with mock.patch.object(app, "pipeline_log"):
            self.assertEqual(app.station_intent("Pause the radio playback."), "pause")
            self.assertEqual(app.station_intent("pause the radio station please"), "pause")
            self.assertEqual(app.station_intent("Pause the radio. Not really. Donald Trump's books."), "")

    def test_a_stale_speaker_order_verdict_is_superseded(self):
        stale = {"tint_revalidation": {"state": "repair_required",
                                       "why": "the old rewrite changed the speaker order or turn count"}}
        self.assertTrue(app._audit_superseded(stale))
        self.assertFalse(app._audit_superseded({**stale, "tint_progress": {"turns": [1]}}))
        self.assertFalse(app._audit_superseded({"tint_revalidation": {"state": "repair_required",
                                                                      "why": "no rhyme evidence"}}))
        self.assertFalse(app._audit_superseded({}))

    def test_a_reordered_rewrite_is_aligned_not_refused(self):
        source = "A: The station needs a copper plate before midnight.\nB: Skip found a bin of records in the store room."
        tinted = ("B: Skip found a bin of records / stacked in the store room, spectres.\n"
                  "A: Copper plate by midnight / or the lights go dark, that's the spark.")
        got = evaluate_legacy(source, tinted, [{"text": "passage"}], app.banter_turns, _bar_grader,
                              target=100, force=0.88, kind="banter")
        self.assertEqual(got["state"], "revalidated", got["why"])
        self.assertEqual([t["marker"] for t in got["progress"]["turns"]], ["A", "B"])
        self.assertIn("Copper plate", got["progress"]["turns"][0]["text"])
        self.assertEqual(len(got["approved_lines"]), 2)

    def test_alignment_leaves_an_unanswered_original_empty(self):
        aligned, unmatched = align_turns(
            [("A", "The station needs a copper plate before midnight."), ("B", "Skip found a bin of records.")],
            [("A", "Copper plate by midnight, that's the spark."), ("B", "Something about the weather entirely.")])
        self.assertIn("Copper plate", aligned[0][1])
        self.assertEqual(aligned[1][1], "")
        self.assertEqual(unmatched, 1)


class RecordStingTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_sting_rides_the_record_when_nobody_is_speaking(self):
        async def _sleep(_s):
            return None
        stung = mock.AsyncMock(return_value="x")
        with (mock.patch.object(app.asyncio, "sleep", side_effect=_sleep),
              mock.patch.object(app, "radio_paused", return_value=False),
              mock.patch.dict(app._RADIO, {"on": True, "voice_to": "here"}),
              mock.patch.object(app, "_SPEAKING", [0]),
              mock.patch.object(app, "_floor_busy", return_value=False),
              mock.patch.object(app, "dj_sting", stung),
              mock.patch.object(app, "pipeline_log")):
            await app._sting_over_record({"title": "a record"})
        stung.assert_awaited_once()

    async def test_no_sting_over_a_voice_or_a_pause(self):
        async def _sleep(_s):
            return None
        stung = mock.AsyncMock(return_value="x")
        with (mock.patch.object(app.asyncio, "sleep", side_effect=_sleep),
              mock.patch.object(app, "radio_paused", return_value=True),
              mock.patch.dict(app._RADIO, {"on": True}),
              mock.patch.object(app, "dj_sting", stung)):
            await app._sting_over_record({})
        with (mock.patch.object(app.asyncio, "sleep", side_effect=_sleep),
              mock.patch.object(app, "radio_paused", return_value=False),
              mock.patch.dict(app._RADIO, {"on": True}),
              mock.patch.object(app, "_SPEAKING", [1]),
              mock.patch.object(app, "dj_sting", stung)):
            await app._sting_over_record({})
        stung.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
