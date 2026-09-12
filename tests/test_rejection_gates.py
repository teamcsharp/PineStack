"""Editorial permission preserves machine evidence and recoverable original words."""
import copy
import hashlib
import tempfile
import unittest
from contextlib import ExitStack
from unittest import mock

import app
from line_review import LineReviewStore
from line_review_runtime import build_recovery
from tests import test_tint_cut as tint_cut


class RejectionGateTests(unittest.IsolatedAsyncioTestCase):
    SOURCE = tint_cut.TintCutTests.SOURCE
    TINTED = tint_cut.TintCutTests.TINTED
    BAD = tint_cut.TintCutTests.BAD
    CHUNKS = tint_cut.TintCutTests.CHUNKS

    def setUp(self):
        self.real_capture = app.line_review_capture
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.permits = self.stack.enter_context(mock.patch.object(
            app, "line_review_permits", return_value=False))
        self.capture = self.stack.enter_context(mock.patch.object(
            app, "line_review_capture", return_value={"id": "fixture-cut", "event_seq": 1}))
        self.stack.enter_context(mock.patch.object(app, "line_review_policy",
                                                  return_value={"enabled": True}))
        self.stack.enter_context(mock.patch.object(app, "station_flow_event"))
        self.stack.enter_context(mock.patch.object(app, "pipeline_log"))

    def test_language_filter_uses_review_policy_without_bypassing_empty_text(self):
        with mock.patch.object(app, "looks_english", return_value=False):
            self.assertEqual(app.english_only("Una conversación completa."), "")
            self.assertEqual(self.permits.call_args.args, ("language", "Una conversación completa."))
            self.assertTrue(self.permits.call_args.kwargs["record"])
            self.permits.return_value = True
            self.assertEqual(app.english_only("Una conversación completa."), "Una conversación completa.")
            self.assertEqual(app.english_only(""), "")

    async def test_parent_context_is_saved_without_changing_approval_scope_and_resets_on_error(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LineReviewStore(directory + "/review.sqlite3")
            with mock.patch.object(app, "_LINE_REVIEW", store):
                self.capture.side_effect = self.real_capture
                async def work():
                    row = app.line_review_capture("tint", self.SOURCE, self.BAD,
                        reasons=["failed grade"], context={"kind": "", "stage": "inner_rewrite"})
                    self.assertEqual(row["context"]["entry"]["caller_voice"], "original-voice")
                    self.assertEqual(row["context"]["kind"], "")
                    self.assertNotIn("who", row["context"])
                    raise RuntimeError("stop this test rewrite")
                previous = app._LINE_REVIEW_CONTEXT.get()
                with self.assertRaises(RuntimeError):
                    await app._line_review_scoped(work(), {
                        "entry": {"caller_voice": "original-voice"},
                        "who": "caller", "kind": "caller", "marker": "C"})
                self.assertEqual(app._LINE_REVIEW_CONTEXT.get(), previous)

    async def test_durable_approval_recovery_survives_ensure_entry_and_empty_kind(self):
        units = [("A", self.SOURCE), ("B", self.SOURCE)]
        original = "\n".join(f"{m}: {s}" for m, s in units)
        source_hash = hashlib.sha1(self.SOURCE.encode()).hexdigest()
        self.tint_patches([], units)
        with tempfile.TemporaryDirectory() as directory:
            store = LineReviewStore(directory + "/review.sqlite3")
            review = store.record("tint", self.SOURCE, self.BAD, ["failed grade"],
                context={"kind": "", "marker": "A", "turn": 1, "script_plain": original,
                    "chunks": self.CHUNKS, "crystal": "test", "tint_progress": {
                        "source": hashlib.sha1(original.encode()).hexdigest(), "world": "test",
                        "chunks": self.CHUNKS, "turns": [
                            {"marker": "A", "source": source_hash, "text": ""},
                            {"marker": "B", "source": source_hash, "text": self.TINTED}]}})
            store.decide(review["id"], "allow")
            entry = build_recovery(review, app.banter_turns, "current")
            self.assertNotIn("blocked_reason", entry)
            entry.update(review_recovery_pending=True, review_tint_kind="")
            self.permits.side_effect = lambda gate, source, candidate="", **kw: store.evaluate(
                gate, source, candidate, kw.get("reasons"), context=kw.get("context"),
                technical=kw.get("technical", False))["allowed"]
            with (mock.patch.object(app, "dialogue_tint_required", return_value=True),
                  mock.patch.object(app, "_larder_current", return_value=True),
                  mock.patch.object(app, "_larder_profile_signature", return_value="current"),
                  mock.patch.object(app, "brief_note", return_value={"checked": False}),
                  mock.patch.object(app, "_pantry_save"), mock.patch.object(app, "_larder_save"),
                  mock.patch.object(app, "crystal_turn", new_callable=mock.AsyncMock) as writer):
                self.assertTrue(await app.ensure_entry_tinted(entry, "banter"))
            writer.assert_not_awaited()
            self.assertIn("A: " + self.BAD, entry["script_tinted"])
            self.assertEqual(entry["use"], "tinted")
            self.assertFalse(entry["tint"]["evaluation"]["turns"][0]["machine_ok"])

    def tint_patches(self, results, units):
        for patch in tint_cut.TintCutTests.patches(self, results, units):
            self.stack.enter_context(patch)

    def test_tint_permission_keeps_the_failed_machine_report(self):
        with mock.patch.object(app, "_crystal_vocab", return_value=frozenset()):
            raw = app.tint_evaluate(self.SOURCE, self.BAD, self.CHUNKS, kind="banter", force=1)
            self.permits.return_value = True
            allowed = app.tint_evaluate(self.SOURCE, self.BAD, self.CHUNKS, kind="banter", force=1)
        self.assertFalse(raw["ok"])
        self.assertTrue(allowed["ok"])
        self.assertTrue(allowed["operator_accepted"])
        self.assertFalse(allowed["machine_ok"])
        self.assertEqual(allowed["machine_faults"], raw["faults"])
        for key in ("semantic", "rhyme", "copying", "transformation", "faults"):
            self.assertEqual(raw[key], allowed[key])
        args, kw = self.permits.call_args
        self.assertEqual(args, ("tint", self.SOURCE, self.BAD))
        self.assertEqual(kw["context"]["kind"], "banter")
        self.assertFalse(kw.get("record", False))
        self.assertNotIn("who", kw["context"])
        self.capture.assert_not_called()

    def test_tint_empty_or_prompt_debris_cannot_be_approved(self):
        self.permits.return_value = True
        for candidate in ("", "!!!", "As an AI language model, I cannot comply."):
            self.permits.reset_mock()
            report = app.tint_evaluate(self.SOURCE, candidate, self.CHUNKS, force=1)
            self.assertFalse(report["ok"], candidate)
            self.permits.assert_not_called()

    async def test_actual_cut_keeps_full_context_and_exact_approval_resumes_it(self):
        units = [("A", self.SOURCE), ("B", self.SOURCE), ("A", self.SOURCE)]
        source = "\n".join(f"{m}: {s}" for m, s in units)
        self.tint_patches([self.TINTED, self.BAD, self.BAD, self.BAD, self.TINTED], units)
        cut = await app.crystal_tint(source, "banter", critical=True)
        args, kw = next((c.args, c.kwargs) for c in self.capture.call_args_list
                        if c.kwargs.get("context", {}).get("stage") == "turn_cut")
        self.assertEqual(args, ("tint", self.SOURCE, self.BAD))
        self.assertEqual(kw["context"]["script_plain"], source)
        self.assertEqual(kw["context"]["turns"], units)
        self.assertEqual(kw["context"]["marker"], "B")
        self.assertNotIn("who", kw["context"])
        saved = cut["progress"]["turns"][1]
        self.assertEqual(kw["context"]["tint_progress"]["turns"][0]["text"], self.TINTED)
        self.assertEqual(saved["text"], "")
        self.assertEqual(saved["rejected_candidate"], self.BAD)
        self.assertEqual(saved["rejected_source"], self.SOURCE)
        self.permits.side_effect = lambda gate, before, candidate="", **meta: (
            (gate, before, candidate, meta.get("context", {}).get("kind"))
            == ("tint", self.SOURCE, self.BAD, "banter"))
        with mock.patch.object(app, "crystal_turn", new_callable=mock.AsyncMock) as rewrite:
            resumed = await app.crystal_tint(source, "banter", progress=cut["progress"], critical=True)
        rewrite.assert_not_awaited()
        self.assertTrue(resumed["ok"], resumed.get("why"))
        self.assertIn("B: " + self.BAD, resumed["script"])
        self.assertNotIn("cut", resumed["progress"]["turns"][1])
        self.assertFalse(resumed["progress"]["turns"][1]["evaluation"]["machine_ok"])

    async def test_unchanged_approved_whole_line_retains_honest_change_count(self):
        self.tint_patches([], [])
        self.permits.return_value = True
        with mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock,
                               return_value=self.SOURCE):
            result = await app.crystal_tint(self.SOURCE, "track_talk", whole_only=True)
        self.assertTrue(result["ok"], result.get("why"))
        self.assertEqual(result["script"], self.SOURCE)
        self.assertEqual(result["coverage"]["changed"], 0)
        self.assertEqual(result["coverage"]["accepted"], 1)
        self.assertFalse(result["evaluation"]["turns"][0]["machine_ok"])

    async def test_whole_line_rejection_is_recoverable_without_another_model_visit(self):
        self.tint_patches([], [])
        with mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock,
                               return_value=self.BAD):
            first = await app.crystal_tint(self.SOURCE, "track_talk", whole_only=True)
        self.assertFalse(first["ok"])
        self.assertEqual(first["progress"]["rejected_candidate"], self.BAD)
        self.permits.return_value = True
        with mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock) as writer:
            resumed = await app.crystal_tint(self.SOURCE, "track_talk", whole_only=True,
                                             progress=first["progress"])
        self.assertTrue(resumed["ok"], resumed.get("why"))
        self.assertEqual(resumed["script"], self.BAD)
        writer.assert_not_awaited()

    def caller_entry(self):
        active = "A: Welcome back to the station.\nC: My bicycle broke down by the river."
        return {"prep_kind": "caller", "caller_name": "Mara", "script": active,
                "script_tinted": active, "script_plain": active.replace("river", "bridge"),
                "use": "tinted", "call": {"quality": {"ok": False, "faults": ["no farewell"]}},
                "tint_fails": 3, "keys": ["clip"], "voice": "caller-voice"}

    def test_caller_grade_acceptance_cannot_forge_machine_proof(self):
        entry = self.caller_entry()
        self.permits.return_value = True
        with mock.patch.object(app, "call_flow_report", return_value={"ok": False, "faults": ["no farewell"]}):
            report = app.call_entry_regrade(entry)
        self.assertTrue(report["ok"])
        self.assertFalse(report["machine_ok"])
        self.assertEqual(report["machine_faults"], ["no farewell"])
        kw = self.permits.call_args.kwargs
        self.assertEqual(kw["context"]["entry"]["voice"], "caller-voice")

    def test_caller_strike_preserves_approved_active_words_and_audio(self):
        entry = self.caller_entry()
        original = copy.deepcopy(entry)
        self.permits.return_value = True
        with mock.patch.object(app, "_dialogue_audio_drop") as drop:
            report = app._call_tint_strike(entry, ["no farewell"])
        self.assertTrue(report["ok"])
        self.assertEqual(entry["script"], original["script"])
        self.assertEqual(entry["keys"], ["clip"])
        drop.assert_not_called()

    def test_speakerless_caller_cannot_bypass_the_technical_gate(self):
        entry = self.caller_entry()
        entry["script"] = "There are no speaker labels in this malformed conversation."
        self.permits.return_value = True
        with mock.patch.object(app, "call_flow_report", return_value={"ok": False, "faults": ["missing cast"]}):
            report = app.call_entry_regrade(entry)
        self.assertFalse(report["ok"])
        self.assertTrue(self.permits.call_args.kwargs["technical"])

    def test_retiring_call_records_every_turn_and_metadata_before_removal(self):
        entry = self.caller_entry()
        original = copy.deepcopy(entry)
        with (mock.patch.object(app, "_SHELF", {"caller": [entry]}),
              mock.patch.object(app, "_PANTRY", {"clip": {"url": "clip.wav"}}),
              mock.patch.object(app, "dialogue_entry", side_effect=lambda row: row),
              mock.patch.object(app, "_row_clip_keys", return_value=["clip"]),
              mock.patch.object(app, "pantry_spoken_for", return_value=set()),
              mock.patch.object(app, "_pantry_save")):
            self.assertTrue(app.retire_rejected_call_entry(entry))
            self.assertEqual(app._SHELF["caller"], [])
        call = next(c for c in self.permits.call_args_list
                    if c.kwargs["context"]["stage"] == "row_retired")
        self.assertTrue(call.kwargs["record"])
        self.assertEqual(call.kwargs["context"]["entry"], original)
        self.assertEqual(len(call.kwargs["context"]["turns"]), 2)
        self.assertNotIn("discarded", call.kwargs["context"]["entry"])

    def test_track_text_and_fidelity_overrides_keep_raw_faults(self):
        track = {"id": "record", "title": "River Music", "artist": "The Quartet"}
        self.permits.return_value = True
        short = app.track_talk_text_report("River Music starts now.", track)
        self.assertTrue(short["ok"])
        self.assertFalse(short["machine_ok"])
        fidelity = app.track_talk_tint_fidelity(self.SOURCE, self.SOURCE, track)
        self.assertTrue(fidelity["ok"])
        self.assertFalse(fidelity["machine_ok"])
        malformed = app.track_talk_text_report("A: River Music\nB: Hello", track)
        self.assertFalse(malformed["ok"])
        self.assertTrue(malformed["technical"])

    def test_allowed_track_link_is_not_silently_renamed_or_trimmed(self):
        track = {"id": "record", "title": "River Music", "artist": "The Quartet"}
        original = "The drums have a very steady beat. " * 15
        self.permits.return_value = True
        governed, report = app.track_talk_tint_govern(original, track)
        self.assertEqual(governed, " ".join(original.split()))
        self.assertTrue(report["ok"])
        self.assertFalse(report["machine_ok"])
        self.capture.assert_not_called()

    def test_radio_draft_permission_preserves_full_script_and_rejects_malformed_payload(self):
        entry = {"script": "A: The drums are very quiet.\nB: I can hear the cymbals.",
                 "prep_kind": "banter", "profile": "profile-a"}
        report = {"ok": False, "faults": ["the turns are too brief"]}
        self.permits.return_value = True
        self.assertTrue(app._radio_draft_review(entry, report, "draft_rewrite", record=True))
        call = self.permits.call_args
        self.assertEqual(call.args, ("radio_draft", entry["script"]))
        self.assertEqual(call.kwargs["context"]["entry"], entry)
        self.assertTrue(call.kwargs["record"])
        malformed = {"script": "There are no speaker turns."}
        self.assertFalse(app._radio_draft_review(malformed, report, "draft_rewrite", record=True))
        self.assertTrue(self.permits.call_args.kwargs["technical"])

    def test_bank_refusal_snapshot_retains_voice_and_source(self):
        entry = {"script": "A: A complete line.\nB: Another line.", "prep_kind": "banter",
                 "voice": "voice-a", "source": "source.txt", "off_brief": True,
                 "brief": {"checked": True, "ok": False, "why": "wrong topic"}}
        app._radio_entry_rejected(entry, "reserve_row_rejected")
        call = self.capture.call_args
        self.assertEqual(call.args, ("segment_brief", entry["script"]))
        self.assertEqual(call.kwargs["context"]["entry"], entry)
        entry["voice"] = "new-voice"
        self.assertEqual(call.kwargs["context"]["entry"]["voice"], "voice-a")

    async def test_direct_duplicate_gate_obeys_operator_permission_before_audio(self):
        norm = " ".join(app.re.sub(r"[^a-z0-9 ]+", "", self.SOURCE.lower()).split())
        with (mock.patch.object(app, "radio_paused", return_value=False),
              mock.patch.object(app, "performance_vector", return_value={}),
              mock.patch.object(app, "spoken_text", side_effect=lambda text: text),
              mock.patch.object(app, "station_name_scrub", side_effect=lambda text: text),
              mock.patch.object(app, "_RECENT_SPOKEN", [norm]),
              mock.patch.object(app, "_floor_stage"),
              mock.patch.object(app, "dialogue_tint_wanted", return_value=False),
              mock.patch.object(app, "air_repeat_check", return_value={"block": False}),
              mock.patch.object(app, "session_voices", new_callable=mock.AsyncMock,
                                return_value={"dj": "voice"}) as voices,
              mock.patch.object(app, "configured_radio_voice", return_value="voice"),
              mock.patch.object(app, "box_talk_ok", return_value=True),
              mock.patch.object(app, "_RADIO", {"voice_to": "off"}),
              mock.patch.object(app, "_SPEAK_LAST", {})):
            await app._dj_speak_floorless("intro", line=self.SOURCE)
            voices.assert_not_awaited()
            self.permits.return_value = True
            await app._dj_speak_floorless("intro", line=self.SOURCE)
            voices.assert_awaited_once()

    async def test_deleted_track_side_is_captured_with_recovery_identity(self):
        track = {"id": "record", "title": "River Music", "artist": "The Quartet"}
        bad = "The orchestra sounds very distant and the drummer keeps a steady beat tonight."
        with (mock.patch.object(app, "track_talk_on", return_value=True),
              mock.patch.object(app, "track_lookahead", return_value=[track]),
              mock.patch.object(app, "track_talk_get", return_value=None),
              mock.patch.object(app, "track_talk_write", new_callable=mock.AsyncMock, return_value=bad),
              mock.patch.object(app, "track_talk_save"),
              mock.patch.object(app, "_TRACK_TALK", {}),
              mock.patch.object(app, "dialogue_tint_wanted", return_value=False),
              mock.patch.object(app, "prep_render_line", new_callable=mock.AsyncMock) as render):
            self.assertFalse(await app.prep_track_talk())
            self.assertEqual(app._TRACK_TALK, {})
        render.assert_not_awaited()
        call = self.capture.call_args
        self.assertEqual(call.args, ("track_talk", bad))
        self.assertEqual(call.kwargs["context"]["track"]["id"], "record")
        self.assertEqual(call.kwargs["context"]["part"], "intro")
        self.assertEqual(call.kwargs["context"]["entry"]["text"], bad)

    async def test_recovered_track_candidate_is_graded_against_original_before_any_rewrite(self):
        track = {"id": "record", "title": "Copper Plate", "artist": "The Quartet"}
        side = {"text": self.BAD, "text_plain": self.SOURCE, "review_ids": ["review"],
                "review_tint": {"chunks": self.CHUNKS, "world": "test"}}
        bank = {"record": {"intro": side}}
        self.permits.side_effect = lambda gate, source, candidate="", **kw: (
            (gate, source, candidate, kw.get("context", {}).get("kind"))
            == ("tint", self.SOURCE, self.BAD, "track_talk"))
        with (mock.patch.object(app, "track_talk_on", return_value=True),
              mock.patch.object(app, "track_lookahead", return_value=[track]),
              mock.patch.object(app, "track_talk_get", return_value=side),
              mock.patch.object(app, "track_talk_save"),
              mock.patch.object(app, "_track_talk_prune"),
              mock.patch.object(app, "_TRACK_TALK", bank),
              mock.patch.object(app, "dialogue_tint_wanted", return_value=True),
              mock.patch.object(app, "dialogue_tint_required", return_value=True),
              mock.patch.object(app, "crystal_force", return_value=1),
              mock.patch.object(app, "_crystal_vocab", return_value=frozenset()),
              mock.patch.object(app, "_pantry_key_ready", return_value=True),
              mock.patch.object(app, "session_voices", new_callable=mock.AsyncMock, return_value={"dj": "voice"}),
              mock.patch.object(app, "prep_render_line", new_callable=mock.AsyncMock,
                                return_value={"key": "real-take", "seconds": 2}),
              mock.patch.object(app, "crystal_tint", new_callable=mock.AsyncMock) as rewrite):
            self.assertTrue(await app.prep_track_talk())
        rewrite.assert_not_awaited()
        result = bank["record"]["intro"]
        self.assertEqual(result["text"], self.BAD)
        self.assertFalse(result["tint"]["evaluation"]["machine_ok"])
        self.assertTrue(result["tint_ok"])

    async def test_cancelled_review_during_track_render_cannot_become_ready(self):
        track = {"id": "record", "title": "Copper Plate", "artist": "The Quartet"}
        side = {"text": self.TINTED, "tint_ok": True}
        bank = {"record": {"intro": side}}
        async def render(*args, **kwargs):
            bank["record"]["intro"]["review_cancel_pending"] = True
            return {"key": "finished-after-cancel", "seconds": 2}
        with (mock.patch.object(app, "track_talk_on", return_value=True),
              mock.patch.object(app, "track_lookahead", return_value=[track]),
              mock.patch.object(app, "track_talk_get", return_value=side),
              mock.patch.object(app, "track_talk_save"),
              mock.patch.object(app, "_TRACK_TALK", bank),
              mock.patch.object(app, "dialogue_tint_wanted", return_value=False),
              mock.patch.object(app, "session_voices", new_callable=mock.AsyncMock, return_value={"dj": "voice"}),
              mock.patch.object(app, "prep_render_line", side_effect=render)):
            self.assertFalse(await app.prep_track_talk())
        self.assertNotIn("intro", bank["record"])


if __name__ == "__main__":
    unittest.main()
