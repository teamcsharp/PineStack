"""Recovery restores retained words and identities without certifying playback."""
import copy
import hashlib
import re
import unittest

from line_review_runtime import build_recovery


def parse(script, *_names):
    return [(match.group(1), match.group(2).strip()) for match in re.finditer(
        r"(?:^|\n)([A-E]):\s*(.*?)(?=\n[A-E]:|$)", script, re.S)]


def sha(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class ReviewRecoveryTests(unittest.TestCase):
    def row(self, **updates):
        row = {"id": "review-one", "gate": "tint", "technical": False,
               "review_status": "allowed", "source": "Second original line.",
               "candidate": "Second revised rhyme, arriving right on time.",
               "context": {"kind": "banter", "turn": 2, "marker": "B",
                           "script": "A: First original line.\nB: Second original line.\nA: Final original line.",
                           "chunks": [{"file": "crystal.txt", "text": "Complete retained passage"}],
                           "crystal": "The retained world"}}
        row.update(updates)
        return row

    def test_restore_middle_cut_preserves_full_script_order_and_exact_resume_hashes(self):
        row = self.row()
        original = row["context"]["script"]
        row["context"]["tint_progress"] = {"source": sha(original), "turns": [
            {"marker": "A", "source": sha("First original line."), "text": "First retained rhyme."},
            {"marker": "B", "source": sha("Second original line."), "text": "", "cut": True},
            {"marker": "A", "source": sha("Final original line."), "text": "Final retained rhyme."}]}
        before = copy.deepcopy(row)
        got = build_recovery(row, parse, "current-profile")
        self.assertEqual(got["script"], original)
        self.assertEqual(got["script_plain"], original)
        self.assertEqual(got["profile"], "current-profile")
        self.assertEqual(got["review_ids"], ["review-one"])
        self.assertEqual(got["tint_progress"]["source"], sha(original))
        self.assertEqual([r["marker"] for r in got["tint_progress"]["turns"]], ["A", "B", "A"])
        self.assertEqual([r["text"] for r in got["tint_progress"]["turns"]],
                         ["First retained rhyme.", row["candidate"], "Final retained rhyme."])
        self.assertEqual(got["tint_progress"]["turns"][1]["source"], sha("Second original line."))
        self.assertEqual(row, before, "Planning must not mutate the retained evidence")
        self.assertNotIn("evaluation", got["tint_progress"]["turns"][1])
        self.assertNotIn("cut", got["tint_progress"]["turns"][1])

    def test_preserves_case_outer_whitespace_and_consecutive_same_speaker(self):
        original = " \nA: One  Exact line.\nA: Second original line.\nB: Final unfinished turn  \n"
        row = self.row(context={"kind": "banter", "turn": 2, "marker": "A", "plain_script": original})
        got = build_recovery(row, parse)
        self.assertEqual(got["script"], original)
        self.assertEqual(got["tint_progress"]["source"], sha(original.strip()))
        self.assertEqual([r["marker"] for r in got["tint_progress"]["turns"]], ["A", "A", "B"])
        self.assertEqual(got["tint_progress"]["turns"][0]["source"], sha("One  Exact line."))

    def test_stale_progress_is_discarded_without_losing_other_original_turns(self):
        row = self.row()
        row["context"]["tint_progress"] = {"source": "wrong-script", "turns": [
            {"marker": "A", "source": sha("First original line."), "text": "Wrong old words"}]}
        got = build_recovery(row, parse)
        self.assertEqual(got["tint_progress"]["turns"][0]["text"], "")
        self.assertIn("First original line.", got["script"])

    def test_mismatched_marker_source_or_index_is_blocked(self):
        for patch in ({"turn": 99}, {"turn": True}, {"marker": "C"}, {"turn": 1}):
            row = self.row(); row["context"].update(patch)
            with self.subTest(patch=patch):
                self.assertIn("blocked_reason", build_recovery(row, parse))
        row = self.row(source="Changed source")
        self.assertIn("blocked_reason", build_recovery(row, parse))

    def test_duplicate_original_words_require_an_unambiguous_index(self):
        row = self.row(context={"script": "A: Second original line.\nB: Second original line."})
        self.assertIn("unique position", build_recovery(row, parse)["blocked_reason"])
        row["context"].update(turn=2, marker="B")
        self.assertEqual(build_recovery(row, parse)["tint_progress"]["turns"][1]["text"], row["candidate"])

    def test_standalone_line_needs_known_speaker_and_keeps_exact_words(self):
        row = self.row(context={"kind": "banter", "who": "cohost"})
        got = build_recovery(row, parse)
        self.assertEqual(got["script"], "B: " + row["source"])
        row["context"]["who"] = "unidentified person"
        self.assertIn("known speaker", build_recovery(row, parse)["blocked_reason"])
        row["technical"] = True
        self.assertIn("technical failure", build_recovery(row, parse)["blocked_reason"])

    def test_caller_identity_and_source_metadata_survive_but_old_readiness_does_not(self):
        script = "A: Hello.\nC: My exact caller line.\nB: Goodbye."
        row = self.row(source="My exact caller line.", context={"kind": "caller", "turn": 2, "marker": "C",
            "script_plain": script, "entry": {"caller_name": "Mara", "caller_voice": "voice-mara",
                "caller_fx": {"pitch": -2}, "call": {"topic": "A copper plate", "speakerbox_text": "Full source",
                    "quality": {"ok": True}, "fingerprint": "old", "contract_version": 9},
                "keys": ["old-audio"], "made": 3, "prepared": True, "preparing": True,
                "tint": {"ok": True}, "profile": "old", "unknown_control": "never-copy"}})
        got = build_recovery(row, parse, "new")
        self.assertEqual(got["caller_name"], "Mara")
        self.assertEqual(got["caller_voice"], "voice-mara")
        self.assertEqual(got["call"], {"topic": "A copper plate", "speakerbox_text": "Full source"})
        for field in ("keys", "made", "prepared", "preparing", "tint", "unknown_control"):
            self.assertNotIn(field, got)
        del row["context"]["entry"]["caller_voice"]
        self.assertIn("name and voice", build_recovery(row, parse)["blocked_reason"])

    def test_whole_caller_contract_restores_candidate_by_matching_original_speaker_order(self):
        source = "A: Hello.\nC: My original line.\nB: Goodbye."
        candidate = "A: A warm hello.\nC: My revised rhyme.\nB: A warm goodbye."
        row = self.row(gate="call_contract", source=source, candidate=candidate,
                      context={"kind": "caller", "script_plain": source, "script": candidate,
                               "entry": {"caller_name": "Mara", "caller_voice": "mara"}})
        got = build_recovery(row, parse)
        self.assertEqual(got["script"], source)
        self.assertEqual([r["text"] for r in got["tint_progress"]["turns"]], [t for _, t in parse(candidate)])
        changed = candidate.replace("C:", "B:")
        row.update(candidate=changed); row["context"]["script"] = changed
        self.assertIn("speaker order", build_recovery(row, parse)["blocked_reason"])

    def test_track_text_uses_original_track_and_side_without_generic_banter_or_audio(self):
        row = self.row(gate="track_talk", source="The reviewed outro.", candidate="",
                      context={"kind": "track_talk", "track": {"id": "track-7", "title": "The real record"},
                               "part": "outro", "script": "The reviewed outro.", "script_plain": "Original outro.",
                               "side": {"text": "Discarded", "key": "audio", "tint_ok": True}})
        got = build_recovery(row, parse)
        self.assertEqual(got["recovery_kind"], "track_talk")
        self.assertEqual(got["track"]["id"], "track-7")
        self.assertEqual(got["entry"], {"text": "The reviewed outro.", "text_plain": "Original outro.",
                                        "who": "cohost", "review_ids": [row["id"]]})
        self.assertNotIn("script", got)
        del row["context"]["track"]["id"]
        self.assertIn("track ID", build_recovery(row, parse)["blocked_reason"])

    def test_track_fidelity_requires_original_part_and_never_changes_the_track_context(self):
        row = self.row(gate="track_talk_fidelity", source="Original intro.", candidate="Reviewed rewrite.",
                      context={"kind": "track_talk", "track": {"id": "track-7"}, "part": "intro"})
        got = build_recovery(row, parse)
        self.assertEqual(got["entry"]["who"], "dj")
        self.assertEqual(got["entry"]["text"], "Reviewed rewrite.")
        row["context"]["script_plain"] = "A different track source."
        self.assertIn("reviewed original", build_recovery(row, parse)["blocked_reason"])
        del row["context"]["script_plain"]
        row["context"]["part"] = "somewhere"
        self.assertIn("intro or outro", build_recovery(row, parse)["blocked_reason"])
        row["gate"] = "tint"; row["context"]["kind"] = "banter"
        self.assertIn("Track-bound", build_recovery(row, parse)["blocked_reason"])

    def test_whole_draft_reviews_restore_every_original_turn_and_ignore_trimmed_subset(self):
        original = "A: First complete line.\nA: Second complete line.\nB: Final unfinished thought"
        for gate in ("segment_brief", "radio_draft", "draft_fragment", "draft_trimming"):
            with self.subTest(gate=gate):
                row = self.row(gate=gate, source=original, candidate="A: First complete line.",
                               context={"kind": "model_draft", "script": original})
                got = build_recovery(row, parse)
                self.assertEqual(got["script"], original)
                self.assertEqual([r["marker"] for r in got["tint_progress"]["turns"]], ["A", "A", "B"])
                self.assertTrue(all(not r["text"] for r in got["tint_progress"]["turns"]))
                self.assertNotIn("tint", got)
        row["context"]["script"] = "A: Unrelated draft."
        self.assertIn("whole-script source", build_recovery(row, parse)["blocked_reason"])

    def test_explicit_empty_kind_is_not_relabelled_and_unmarked_draft_is_blocked(self):
        row = self.row()
        row["context"]["kind"] = ""
        self.assertEqual(build_recovery(row, parse)["prep_kind"], "")
        row = self.row(gate="draft_fragment", source="Unattributed words", candidate="",
                       context={"kind": "model_draft", "script": "Unattributed words"})
        self.assertIn("no parseable speaker", build_recovery(row, parse)["blocked_reason"])

    def test_whole_tint_rewrite_restores_candidates_but_never_quality_proof(self):
        original = "A: Original first.\nB: Original second."
        candidate = "A: Reviewed first.\nB: Reviewed second."
        row = self.row(gate="tint_structure", source=original, candidate=candidate,
                      context={"kind": "banter", "script_plain": original, "script": candidate})
        got = build_recovery(row, parse)
        self.assertEqual(got["tint_progress"]["rejected_candidate"], candidate)
        self.assertEqual([r["text"] for r in got["tint_progress"]["turns"]], [t for _, t in parse(candidate)])
        self.assertNotIn("evaluation", got["tint_progress"])

    def test_unmarked_original_requires_matching_source_and_explicit_known_speaker(self):
        original = "  Exact Case, and  spacing. \n"
        for speaker, marker in (("dj", "A"), ("cohost", "B"), ("third", "D")):
            with self.subTest(speaker=speaker):
                row = self.row(source="Exact Case, and spacing.", candidate="Reviewed words.",
                    context={"kind": "", "speaker": speaker, "script_plain": original})
                before = copy.deepcopy(row)
                got = build_recovery(row, parse)
                self.assertEqual(got["review_original_script"], original)
                self.assertEqual(got["script"], marker + ": " + original)
                self.assertEqual(got["tint_progress"]["source"], sha(got["script"].strip()))
                self.assertEqual(got["tint_progress"]["turns"][0]["marker"], marker)
                self.assertEqual(got["tint_progress"]["turns"][0]["text"], "Reviewed words.")
                self.assertEqual(got["prep_kind"], "")
                self.assertEqual(row, before)
        row["source"] = "exact Case, and spacing."
        self.assertIn("differs from the reviewed source", build_recovery(row, parse)["blocked_reason"])
        row["source"] = "Exact Case, and spacing."
        for speaker in ("unknown person", "drop", ""):
            row["context"]["speaker"] = speaker
            self.assertIn("known speaker mapping", build_recovery(row, parse)["blocked_reason"])

    def test_unmarked_caller_needs_original_identity_even_with_explicit_marker(self):
        row = self.row(source="My original words.", candidate="My reviewed words.",
            context={"kind": "caller", "marker": "C", "script_plain": "My original words."})
        self.assertIn("name and voice", build_recovery(row, parse)["blocked_reason"])
        row["context"]["entry"] = {"caller_name": "Mara", "caller_voice": "mara-voice"}
        got = build_recovery(row, parse)
        self.assertEqual(got["script"], "C: My original words.")
        self.assertEqual(got["caller_voice"], "mara-voice")

    def test_blend_restores_whole_candidate_with_original_speakers_and_metadata(self):
        original = "A: Original welcome.\nC: Original account.\nB: Original farewell."
        candidate = "A: Reviewed welcome.\nC: Reviewed account.\nB: Reviewed farewell."
        row = self.row(gate="blend", source=original, candidate=candidate,
            context={"kind": "caller", "script_plain": original, "script": candidate,
                     "verbatim": ["A retained passage"],
                     "entry": {"caller_name": "Mara", "caller_voice": "mara-voice"}})
        got = build_recovery(row, parse)
        self.assertEqual(got["script"], original)
        self.assertEqual([r["text"] for r in got["tint_progress"]["turns"]], [t for _, t in parse(candidate)])
        self.assertEqual(got["caller_voice"], "mara-voice")
        self.assertEqual(got["verbatim"], ["A retained passage"])
        self.assertNotIn("tint", got)

    def test_blend_with_changed_speaker_order_or_stale_source_cannot_be_recovered(self):
        original = "A: First source.\nB: Second source."
        for candidate in ("B: First rewrite.\nA: Second rewrite.", "A: Only one rewrite."):
            row = self.row(gate="blend", source=original, candidate=candidate,
                context={"kind": "banter", "script_plain": original, "script": candidate})
            self.assertIn("speaker order", build_recovery(row, parse)["blocked_reason"])
        row["context"]["script_plain"] = "A: A different source.\nB: An unrelated source."
        self.assertIn("reviewed source", build_recovery(row, parse)["blocked_reason"])

    def test_rejected_ad_length_and_repetition_restore_exact_active_text_and_product(self):
        for gate in ("ad_length", "ad_repetition"):
            with self.subTest(gate=gate):
                row = self.row(gate=gate, source="Try the Blue Spoon today.", candidate="",
                    context={"kind": "ad", "speaker": "dj", "script": "Try the Blue Spoon today.",
                             "script_plain": "The original Blue Spoon advert.",
                             "product": "Blue Spoon", "seed": "Retained source passage"})
                got = build_recovery(row, parse)
                self.assertEqual(got["script"], "A: Try the Blue Spoon today.")
                self.assertEqual(got["review_source_plain"], "The original Blue Spoon advert.")
                self.assertEqual(got["product"], "Blue Spoon")
                self.assertEqual(got["seed"], "Retained source passage")
                self.assertEqual(got["tint_progress"]["turns"][0]["text"], row["source"])
                self.assertNotIn("tint_ok", got)
                row["context"]["script"] = "A different product advert."
                self.assertIn("reviewed source", build_recovery(row, parse)["blocked_reason"])

    def test_track_recovery_retains_passages_and_only_matching_source_progress(self):
        source = "The original track observation."
        progress = {"source": sha(source), "world": "Retained world",
                    "chunks": [{"text": "The actual reference passage"}],
                    "turns": [], "rejected_candidate": "Reviewed observation."}
        row = self.row(gate="track_talk_fidelity", source=source, candidate="Reviewed observation.",
            context={"kind": "track_talk", "track": {"id": "track-7"}, "part": "intro",
                     "side": {"tint_progress": progress, "tint_ok": True,
                              "tint": {"ok": True, "evaluation": {"ok": True}}}})
        before = copy.deepcopy(row)
        got = build_recovery(row, parse)["entry"]
        self.assertEqual(got["review_tint"], {"world": progress["world"], "chunks": progress["chunks"]})
        self.assertEqual(got["tint_progress"], progress)
        self.assertNotIn("tint_ok", got)
        self.assertNotIn("evaluation", got["review_tint"])
        got["tint_progress"]["chunks"][0]["text"] = "Local mutation"
        self.assertEqual(row, before)
        row["context"]["side"]["tint_progress"]["source"] = "another-source"
        self.assertNotIn("tint_progress", build_recovery(row, parse)["entry"])
        row["context"].update(chunks=[{"text": "Direct retained reference"}], crystal="Direct world")
        self.assertEqual(build_recovery(row, parse)["entry"]["review_tint"],
                         {"chunks": [{"text": "Direct retained reference"}], "world": "Direct world"})

    def test_bare_shelf_line_preserves_explicit_voice_without_inventing_a_speaker(self):
        source = "The exact old shelf source."
        candidate = "SPEAKER: The exact reviewed rewrite."
        row = self.row(source=source, candidate=candidate, context={"kind": "ad", "script_plain": source,
            "script": candidate, "marker": "", "turn": 1, "entry_id": "ad-original",
            "crystal": "Original world", "chunks": [{"text": "Retained passage"}],
            "entry": {"text": "Earlier active copy", "text_plain": source, "voice": "paid-explicit-voice",
                "sid": "ad-original", "product": "Original product", "seed": "Original seed", "at": 42,
                "cast": "original-cast", "key": "old-audio", "prepared": True, "seconds": 9,
                "tint_ok": True, "tint": {"ok": True, "evaluation": {"ok": True}}}})
        before = copy.deepcopy(row)
        got = build_recovery(row, parse)
        self.assertEqual(got["recovery_kind"], "shelf_line")
        self.assertEqual(got["kind"], "ad")
        made = got["row"]
        self.assertEqual(made["text"], candidate)
        self.assertEqual(made["text_plain"], source)
        self.assertEqual(made["voice"], "paid-explicit-voice")
        self.assertEqual(made["who"], "")
        self.assertEqual(made["sid"], "ad-original")
        self.assertEqual(made["product"], "Original product")
        self.assertEqual(made["cast"], "original-cast")
        self.assertEqual(made["review_tint"], {"chunks": [{"text": "Retained passage"}], "world": "Original world"})
        for field in ("key", "prepared", "seconds", "tint_ok", "tint", "script"):
            self.assertNotIn(field, made)
        self.assertEqual(row, before)

    def test_bare_shelf_line_blocks_wrong_source_candidate_entry_and_multi_voice_rewrite(self):
        source = "The original shelf line."
        for mutation in ("source", "candidate", "entry", "multi_voice"):
            with self.subTest(mutation=mutation):
                row = self.row(source=source, candidate="Reviewed shelf line.",
                    context={"kind": "ad", "entry_id": "same-row", "script_plain": source,
                             "entry": {"text": source, "voice": "explicit-voice", "sid": "same-row"}})
                if mutation == "source":
                    row["context"]["entry"]["text"] = "Another stored source."
                elif mutation == "candidate":
                    row["context"]["candidate_original"] = "Different candidate."
                elif mutation == "entry":
                    row["context"]["entry"]["sid"] = "different-row"
                else:
                    row["candidate"] = "A: Host words.\nB: Cohost words."
                self.assertIn("blocked_reason", build_recovery(row, parse))

    def test_bare_ad_repetition_restores_reviewed_active_text_and_keeps_older_plain_as_evidence(self):
        row = self.row(gate="ad_repetition", source="Active reviewed advert.", candidate="",
            context={"kind": "ad", "script": "Active reviewed advert.", "script_plain": "Older plain source.",
                     "entry": {"text": "Active reviewed advert.", "text_plain": "Older plain source.",
                               "voice": "explicit-voice", "who": "drop", "sid": "ad-old"}})
        got = build_recovery(row, parse)
        self.assertEqual(got["row"]["text"], row["source"])
        self.assertEqual(got["row"]["who"], "drop")
        self.assertEqual(got["row"]["voice"], "explicit-voice")
        self.assertEqual(got["row"]["text_plain"], "Older plain source.")

    def test_bare_brief_approval_keeps_underlying_source_for_the_prior_tint_approval(self):
        row = self.row(gate="segment_brief", source="The reviewed active candidate.", candidate="",
            context={"kind": "ad", "script": "The reviewed active candidate.",
                     "script_plain": "The original underlying source.",
                     "entry": {"text": "The reviewed active candidate.",
                               "text_plain": "The original underlying source.", "voice": "original-voice"}})
        made = build_recovery(row, parse)["row"]
        self.assertEqual(made["text"], "The reviewed active candidate.")
        self.assertEqual(made["text_plain"], "The original underlying source.")
        row["context"]["entry"]["text"] = "A changed active candidate."
        self.assertIn("reviewed active text", build_recovery(row, parse)["blocked_reason"])


if __name__ == "__main__":
    unittest.main()
