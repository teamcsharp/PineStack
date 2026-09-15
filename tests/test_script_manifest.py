"""The acceptance list of `docs/notes/speaker-recording-and-script-assembly.md`,
as tests: actors finishing out of order, duplicate wording, missing/repeated/
dropped words, corrupt or changed masters, revision changes, interrupted
sessions, retries, duration-changing effects, stale player receipts, and the
rule that no incomplete conversation may be admitted.

These tests import `script_manifest` and `manifest_store` only. They never
import `app`, never start anything, and write ONLY into a temporary
directory: the sequential-playout audit records that some existing fixtures
can append fixture rows to the live script ledger, and nothing here goes near
a runtime store.
"""
import json
import tempfile
import unittest
from pathlib import Path

import script_manifest as sm
from manifest_store import ManifestStore

RATE = 48000
GAP = 4800  # a tenth of a second of scripted pause between lines


def a_cast():
    return {"Ada": {"voice": "ada-1", "engine": "xtts", "config": {"speed": 1.0}},
            "Bo": {"voice": "bo-1", "engine": "xtts", "config": {"speed": 1.0}}}


def a_script(**kwargs):
    """Four lines, two actors, and line 3 repeats line 1 word for word."""
    return sm.frozen_script("teatime", a_cast(), [
        sm.script_line("Ada", "Say that again.", instructions="dry"),
        sm.script_line("Bo", "The kettle is on."),
        sm.script_line("Ada", "Say that again.", instructions="dry"),
        sm.script_line("Bo", "The kettle is off."),
    ], **kwargs)


def a_master(script, actor, take_id, *, session_id="", payload=b"", frames=480000,
             mode="segmented", rate=RATE):
    data = payload or (actor.encode("utf-8") * 64)
    return sm.master_recording(
        take_id, session_id=session_id or ("sess-" + actor.lower()),
        revision=script["revision"], actor=actor,
        audio_sha256=sm.audio_digest(data), sample_rate=rate, frame_count=frames,
        media_ref="/voice/%s.wav" % take_id, mode=mode), data


def a_cut(script, master, line, *, cut_id="", start=0, frames=24000,
          method="renderer_boundary", transcript=None, state="accepted",
          rate=None):
    checks = {"actor": line["actor"]}
    if transcript is not None:
        checks["transcript"] = transcript
    return sm.line_cut(
        cut_id or ("cut-%d" % line["ordinal"]),
        occurrence_id=line["occurrence_id"], ordinal=line["ordinal"],
        take_id=master["take_id"], master_sha256=master["audio_sha256"],
        sample_rate=rate or master["sample_rate"], start_sample=start,
        end_sample=start + frames, boundary_method=method,
        verification=checks, state=state)


def cuts_for(script, masters, *, frames=24000):
    """One accepted cut per line, laid out inside each actor's own master."""
    out = {}
    offset = {actor: 0 for actor in masters}
    for line in script["lines"]:
        master = masters[line["actor"]]
        cut = a_cut(script, master, line, start=offset[line["actor"]], frames=frames,
                    transcript=line["text"])
        offset[line["actor"]] += frames + 1000
        out[line["occurrence_id"]] = cut
    return out


def assemble(script, cuts, *, assembly_id="asm-1", gap=GAP, stretch=1.0,
             effects=None, cue_source="measured", order=None, final_payload=b"final"):
    """A cue map measured from the actual edited sample counts."""
    sequence = order or sm.script_sequence(script)
    rows, ordered_cut_ids, position = [], [], 0
    for ident in sequence:
        cut = cuts[ident]
        source = cut["end_sample"] - cut["start_sample"]
        spoken = int(round(source * stretch))
        rows.append(sm.cue_entry(
            occurrence_id=ident, ordinal=cut["ordinal"], cut_id=cut["cut_id"],
            cue_start_sample=position, speech_start_sample=position,
            speech_end_sample=position + spoken,
            cue_end_sample=position + spoken + gap, source_frames=source))
        ordered_cut_ids.append(cut["cut_id"])
        position += spoken + gap
    mix = {"sample_rate": RATE, "gap_samples": gap}
    if effects:
        mix["effects"] = effects
    return sm.finished_conversation(
        assembly_id, revision=script["revision"], cuts=ordered_cut_ids, mix=mix,
        final_sha256=sm.audio_digest(final_payload), final_sample_rate=RATE,
        final_frame_count=position, cue_map=rows, cue_source=cue_source)


class FrozenScriptTests(unittest.TestCase):
    def test_identical_words_are_two_occurrences_the_pantry_key_cannot_tell_apart(self):
        script = a_script()
        first, third = script["lines"][0], script["lines"][2]
        self.assertEqual(first["text"], third["text"])
        # app.py:13618 hashes engine + voice + text, so the content cache key
        # is the same for both performances. Manifest identity is not.
        self.assertEqual(sm.content_cache_key(first["text"], "ada-1", "xtts"),
                         sm.content_cache_key(third["text"], "ada-1", "xtts"))
        self.assertNotEqual(first["occurrence_id"], third["occurrence_id"])
        self.assertEqual(first["performance_digest"], third["performance_digest"])
        self.assertEqual(len(set(sm.script_sequence(script))), 4)
        self.assertEqual([r["ordinal"] for r in script["lines"]], [1, 2, 3, 4])
        self.assertTrue(sm.validate_frozen_script(script)["ok"])

    def test_a_line_spoken_by_nobody_in_the_cast_cannot_be_frozen(self):
        with self.assertRaises(sm.ManifestError) as caught:
            sm.frozen_script("teatime", a_cast(), [sm.script_line("Cleo", "Hello.")])
        self.assertIn("not in the cast", str(caught.exception))

    def test_editing_a_frozen_script_in_place_is_caught(self):
        script = a_script()
        script["lines"][1]["text"] = "The kettle is cold."
        got = sm.validate_frozen_script(script)
        self.assertFalse(got["ok"])
        codes = {r["code"] for r in got["refusals"]}
        self.assertIn("script_occurrence_mismatch", codes)
        self.assertIn("script_revision_mismatch", codes)
        self.assertTrue(all(r["reason"] for r in got["refusals"]))

    def test_a_script_change_creates_a_new_revision(self):
        script = a_script()
        lines = [dict(r) for r in script["lines"]]
        lines[3]["text"] = "The kettle is cold."
        later = sm.revise_script(script, lines=lines)
        self.assertNotEqual(script["revision"], later["revision"])
        self.assertEqual(script["lines"][3]["text"], "The kettle is off.")
        self.assertNotEqual(script["lines"][3]["occurrence_id"],
                            later["lines"][3]["occurrence_id"])

    def test_completed_audio_carries_over_only_on_a_compatible_contract(self):
        script = a_script()
        have = {line["occurrence_id"]: "cut-%d" % line["ordinal"]
                for line in script["lines"]}
        lines = [dict(r) for r in script["lines"]]
        lines[3]["text"] = "The kettle is cold."
        later = sm.revise_script(script, lines=lines)
        got = sm.carry_over(script, later, have)
        self.assertFalse(got["ok"])
        self.assertEqual(sorted(got["carried"]),
                         sorted(r["occurrence_id"] for r in later["lines"][:3]))
        self.assertEqual([r["ordinal"] for r in got["dropped"]], [4])
        self.assertIn("text", got["dropped"][0]["changed"])
        self.assertIn("cannot reuse its audio", got["dropped"][0]["reason"])

    def test_a_new_voice_drops_every_line_that_actor_speaks(self):
        script = a_script()
        have = {line["occurrence_id"]: "cut-%d" % line["ordinal"]
                for line in script["lines"]}
        cast = a_cast()
        cast["Ada"]["voice"] = "ada-2"
        later = sm.revise_script(script, cast=cast)
        got = sm.carry_over(script, later, have)
        dropped = {row["ordinal"]: row for row in got["dropped"]}
        self.assertEqual(sorted(dropped), [1, 3])
        self.assertIn("voice", dropped[1]["changed"])
        self.assertEqual(len(got["carried"]), 2)

    def test_repeated_wording_carries_over_in_reading_order_not_by_text_hash(self):
        script = a_script()
        # Only the FIRST of the two identical lines was ever recorded.
        have = {script["lines"][0]["occurrence_id"]: "cut-1"}
        later = sm.revise_script(script)
        got = sm.carry_over(script, later, have)
        self.assertEqual(got["carried"],
                         {later["lines"][0]["occurrence_id"]: "cut-1"})
        self.assertIn(later["lines"][2]["occurrence_id"],
                      [row["occurrence_id"] for row in got["dropped"]])


class SessionTests(unittest.TestCase):
    def test_a_session_takes_its_own_actors_lines_in_reading_order(self):
        script = a_script()
        session = sm.performer_session("sess-ada", script, "Ada")
        self.assertEqual(session["assignments"],
                         [script["lines"][0]["occurrence_id"],
                          script["lines"][2]["occurrence_id"]])
        self.assertEqual(session["voice"], "ada-1")
        self.assertTrue(sm.validate_session(session, script)["ok"])

    def test_a_session_may_not_be_assigned_another_actors_line(self):
        script = a_script()
        session = sm.performer_session(
            "sess-ada", script, "Ada",
            assignments=[script["lines"][0]["occurrence_id"],
                         script["lines"][1]["occurrence_id"]])
        got = sm.validate_session(session, script)
        self.assertFalse(got["ok"])
        self.assertEqual([r["code"] for r in got["refusals"]], ["session_wrong_actor"])
        self.assertIn("which Bo speaks", got["reason"])

    def test_a_session_recorded_on_another_engine_is_refused(self):
        script = a_script()
        session = sm.performer_session("sess-ada", script, "Ada", engine="f5")
        got = sm.validate_session(session, script)
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "session_contract_mismatch")

    def test_an_incomplete_performance_is_not_ready(self):
        script = a_script()
        session = sm.performer_session(
            "sess-ada", script, "Ada", state="complete",
            accepted={script["lines"][0]["occurrence_id"]: "cut-1"})
        got = sm.validate_session(session, script)
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "session_incomplete")
        self.assertEqual(got["remaining"], [script["lines"][2]["occurrence_id"]])


class MasterAndCutTests(unittest.TestCase):
    def setUp(self):
        self.script = a_script()
        self.master, self.data = a_master(self.script, "Ada", "take-ada")
        self.line = self.script["lines"][0]

    def test_a_changed_master_no_longer_verifies(self):
        self.assertTrue(sm.verify_master_bytes(self.master, self.data)["ok"])
        got = sm.verify_master_bytes(self.master, self.data + b"!")
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "master_hash_mismatch")
        self.assertIn("no longer hashes", got["reason"])

    def test_a_cut_of_a_changed_master_is_refused(self):
        cut = a_cut(self.script, self.master, self.line)
        moved = dict(self.master, audio_sha256=sm.audio_digest(b"different"))
        got = sm.validate_cut(cut, master=moved, script=self.script)
        self.assertFalse(got["ok"])
        self.assertIn("cut_master_mismatch", {r["code"] for r in got["refusals"]})

    def test_a_cut_past_the_end_of_its_master_is_refused(self):
        cut = a_cut(self.script, self.master, self.line, start=479000, frames=5000)
        got = sm.validate_cut(cut, master=self.master, script=self.script)
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "cut_out_of_bounds")

    def test_a_cut_counted_at_another_sample_rate_is_refused(self):
        cut = a_cut(self.script, self.master, self.line, rate=44100)
        got = sm.validate_cut(cut, master=self.master, script=self.script)
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "cut_sample_rate_mismatch")

    def test_silence_alone_cannot_establish_a_boundary(self):
        cut = a_cut(self.script, self.master, self.line, method="silence",
                    transcript=self.line["text"])
        got = sm.validate_cut(cut, master=self.master, script=self.script)
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "cut_boundary_ambiguous")
        self.assertIn("cannot establish which line was spoken", got["reason"])

    def test_an_alignment_without_a_transcript_proves_nothing(self):
        cut = a_cut(self.script, self.master, self.line, method="alignment")
        got = sm.validate_cut(cut, master=self.master, script=self.script)
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "cut_no_text_evidence")

    def test_dropped_words_are_refused(self):
        cut = a_cut(self.script, self.master, self.line, method="alignment",
                    transcript="Say that")
        got = sm.validate_cut(cut, master=self.master, script=self.script)
        self.assertFalse(got["ok"])
        self.assertIn("cut_words_missing", {r["code"] for r in got["refusals"]})
        self.assertEqual(got["missing"], ["again"])

    def test_repeated_speech_is_refused(self):
        cut = a_cut(self.script, self.master, self.line, method="alignment",
                    transcript="Say that say that again.")
        got = sm.validate_cut(cut, master=self.master, script=self.script)
        self.assertFalse(got["ok"])
        self.assertIn("cut_words_repeated", {r["code"] for r in got["refusals"]})

    def test_words_that_are_not_in_the_script_are_refused(self):
        cut = a_cut(self.script, self.master, self.line, method="alignment",
                    transcript="Say that again, Bo.")
        got = sm.validate_cut(cut, master=self.master, script=self.script)
        self.assertFalse(got["ok"])
        self.assertIn("cut_words_extra", {r["code"] for r in got["refusals"]})

    def test_another_actors_take_cannot_supply_a_line(self):
        other, _ = a_master(self.script, "Bo", "take-bo")
        cut = a_cut(self.script, other, self.line, transcript=self.line["text"])
        got = sm.validate_cut(cut, master=other, script=self.script)
        self.assertFalse(got["ok"])
        self.assertIn("cut_actor_mismatch", {r["code"] for r in got["refusals"]})

    def test_exactly_one_accepted_cut_is_required_for_every_line(self):
        by_actor = {"Ada": self.master,
                    "Bo": a_master(self.script, "Bo", "take-bo")[0]}
        cuts = cuts_for(self.script, by_actor)
        masters = {m["take_id"]: m for m in by_actor.values()}
        rows = list(cuts.values())
        got = sm.validate_cut_set(rows, script=self.script, masters=masters)
        self.assertTrue(got["ok"], got["reasons"])
        self.assertEqual(len(got["accepted"]), 4)

        twice = rows + [dict(rows[0], cut_id="cut-1b")]
        got = sm.validate_cut_set(twice, script=self.script, masters=masters)
        self.assertFalse(got["ok"])
        self.assertIn("cut_duplicate_accepted", {r["code"] for r in got["refusals"]})

        short = sm.validate_cut_set(rows[:3], script=self.script, masters=masters)
        self.assertFalse(short["ok"])
        self.assertEqual([r["code"] for r in short["refusals"]],
                         ["cut_missing_for_occurrence"])
        self.assertIn("needs a retake", short["reason"])

    def test_a_retake_replaces_a_rejected_take(self):
        rejected = a_cut(self.script, self.master, self.line, cut_id="cut-1a",
                         method="alignment", transcript="Say that", state="rejected")
        good = a_cut(self.script, self.master, self.line, cut_id="cut-1b",
                     start=30000, transcript=self.line["text"])
        got = sm.validate_cut_set([rejected, good], script=self.script,
                                  masters={"take-ada": self.master},
                                  occurrences=[self.line["occurrence_id"]])
        self.assertTrue(got["ok"], got["reasons"])
        self.assertEqual(got["accepted"][self.line["occurrence_id"]], "cut-1b")

    def test_overlapping_accepted_cuts_inside_one_take_are_ambiguous(self):
        first = a_cut(self.script, self.master, self.script["lines"][0],
                      cut_id="cut-1", start=0, frames=24000,
                      transcript="Say that again.")
        second = a_cut(self.script, self.master, self.script["lines"][2],
                       cut_id="cut-3", start=20000, frames=24000,
                       transcript="Say that again.")
        got = sm.validate_cut_set(
            [first, second], script=self.script, masters={"take-ada": self.master},
            occurrences=[self.script["lines"][0]["occurrence_id"],
                         self.script["lines"][2]["occurrence_id"]])
        self.assertFalse(got["ok"])
        self.assertIn("cut_overlap_ambiguous", {r["code"] for r in got["refusals"]})


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.script = a_script()
        self.masters = {"Ada": a_master(self.script, "Ada", "take-ada")[0],
                        "Bo": a_master(self.script, "Bo", "take-bo")[0]}
        self.cuts = cuts_for(self.script, self.masters)
        self.by_id = {c["cut_id"]: c for c in self.cuts.values()}

    def test_actors_finishing_out_of_order_still_assemble_1_2_3_4(self):
        # Ada finished lines 1 and 3 before Bo started 2 and 4; the cuts are
        # handed to the assembler in completion order.
        completion = [self.cuts[self.script["lines"][0]["occurrence_id"]],
                      self.cuts[self.script["lines"][2]["occurrence_id"]],
                      self.cuts[self.script["lines"][1]["occurrence_id"]],
                      self.cuts[self.script["lines"][3]["occurrence_id"]]]
        self.assertEqual([c["ordinal"] for c in completion], [1, 3, 2, 4])
        assembly = assemble(self.script, self.cuts)
        got = sm.validate_assembly(assembly, script=self.script,
                                   cuts_by_id=self.by_id, masters={
                                       m["take_id"]: m for m in self.masters.values()})
        self.assertTrue(got["ok"], got["reasons"])
        self.assertEqual([r["ordinal"] for r in assembly["cue_map"]], [1, 2, 3, 4])

    def test_the_final_cue_sequence_equals_the_frozen_script_sequence(self):
        assembly = assemble(self.script, self.cuts)
        self.assertEqual(sm.cue_sequence(assembly), sm.script_sequence(self.script))

    def test_a_shuffled_cue_map_is_refused(self):
        order = list(sm.script_sequence(self.script))
        order[1], order[2] = order[2], order[1]
        assembly = assemble(self.script, self.cuts, order=order)
        got = sm.validate_assembly(assembly, script=self.script, cuts_by_id=self.by_id)
        self.assertFalse(got["ok"])
        self.assertIn("assembly_sequence_mismatch", {r["code"] for r in got["refusals"]})

    def test_rescaled_cue_positions_are_refused(self):
        assembly = assemble(self.script, self.cuts, cue_source="rescaled")
        got = sm.validate_assembly(assembly, script=self.script, cuts_by_id=self.by_id)
        self.assertFalse(got["ok"])
        self.assertIn("cue_map_estimated", {r["code"] for r in got["refusals"]})
        self.assertIn("measured from the actual edited sample counts", got["reasons"][0])

    def test_duration_changing_effects_need_updated_cue_positions(self):
        effects = [{"name": "stretch", "changes_duration": True}]
        stale = assemble(self.script, self.cuts, effects=effects, stretch=1.0)
        got = sm.validate_assembly(stale, script=self.script, cuts_by_id=self.by_id)
        self.assertFalse(got["ok"])
        self.assertIn("cue_map_stale_for_effects", {r["code"] for r in got["refusals"]})

        updated = assemble(self.script, self.cuts, effects=effects, stretch=1.08)
        got = sm.validate_assembly(updated, script=self.script, cuts_by_id=self.by_id,
                                   masters={m["take_id"]: m
                                            for m in self.masters.values()})
        self.assertTrue(got["ok"], got["reasons"])
        self.assertGreater(updated["final_frame_count"],
                           assemble(self.script, self.cuts)["final_frame_count"])

    def test_an_inserted_pause_does_not_start_the_next_line(self):
        assembly = assemble(self.script, self.cuts)
        first, second = assembly["cue_map"][0], assembly["cue_map"][1]
        self.assertLess(first["speech_end_sample"], first["cue_end_sample"])
        self.assertEqual(first["cue_end_sample"], second["cue_start_sample"])
        quiet = sm.cue_lookup(assembly, first["speech_end_sample"] + 1)
        self.assertEqual(quiet["occurrence_id"], first["occurrence_id"])
        self.assertFalse(quiet["speaking"])

    def test_overlapping_cues_are_refused_in_strict_sequential_mode(self):
        assembly = assemble(self.script, self.cuts)
        assembly["cue_map"][1]["cue_start_sample"] = 0
        assembly["cue_map"][1]["speech_start_sample"] = 0
        got = sm.validate_assembly(assembly, script=self.script, cuts_by_id=self.by_id)
        self.assertFalse(got["ok"])
        self.assertIn("cue_overlap", {r["code"] for r in got["refusals"]})

    def test_a_missing_line_makes_the_conversation_incomplete(self):
        order = sm.script_sequence(self.script)[:3]
        assembly = assemble(self.script, self.cuts, order=order)
        got = sm.validate_assembly(assembly, script=self.script, cuts_by_id=self.by_id)
        self.assertFalse(got["ok"])
        codes = {r["code"] for r in got["refusals"]}
        self.assertIn("cut_missing_for_occurrence", codes)
        self.assertIn("assembly_sequence_mismatch", codes)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.script = a_script()
        self.masters = {"Ada": a_master(self.script, "Ada", "take-ada")[0],
                        "Bo": a_master(self.script, "Bo", "take-bo")[0]}
        self.cuts = cuts_for(self.script, self.masters)
        self.by_id = {c["cut_id"]: c for c in self.cuts.values()}
        self.assembly = assemble(self.script, self.cuts)

    def test_a_complete_conversation_is_admitted_with_contiguous_positions(self):
        admission = sm.broadcast_admission("adm-1", assembly=self.assembly,
                                           start_position=17)
        got = sm.validate_admission(admission, assembly=self.assembly,
                                    script=self.script, cuts_by_id=self.by_id)
        self.assertTrue(got["ok"], got["reasons"])
        self.assertEqual(sorted(got["positions"].values()), [17, 18, 19, 20])

    def test_no_incomplete_conversation_may_be_admitted(self):
        order = sm.script_sequence(self.script)[:2]
        partial = assemble(self.script, self.cuts, assembly_id="asm-partial",
                           order=order)
        admission = sm.broadcast_admission("adm-2", assembly=partial)
        got = sm.validate_admission(admission, assembly=partial, script=self.script,
                                    cuts_by_id=self.by_id)
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "admission_incomplete_assembly")
        self.assertIn("not a complete verified conversation", got["reason"])

    def test_admission_without_the_cut_records_is_refused_not_assumed(self):
        admission = sm.broadcast_admission("adm-3", assembly=self.assembly)
        got = sm.validate_admission(admission, assembly=self.assembly,
                                    script=self.script, cuts_by_id=None)
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "admission_unverifiable")

    def test_a_final_file_that_changed_after_admission_is_refused(self):
        admission = sm.broadcast_admission("adm-4", assembly=self.assembly)
        rebuilt = dict(self.assembly, final_sha256=sm.audio_digest(b"remastered"))
        got = sm.validate_admission(admission, assembly=rebuilt, script=self.script,
                                    cuts_by_id=self.by_id)
        self.assertFalse(got["ok"])
        self.assertIn("admission_audio_mismatch", {r["code"] for r in got["refusals"]})

    def test_playing_the_same_audio_twice_makes_two_occurrences(self):
        first = sm.broadcast_admission("adm-5", assembly=self.assembly)
        second = sm.broadcast_admission("adm-6", assembly=self.assembly)
        self.assertNotEqual(first["playback_occurrence_id"],
                            second["playback_occurrence_id"])
        reused = sm.broadcast_admission(
            "adm-7", assembly=self.assembly,
            playback_occurrence_id=first["playback_occurrence_id"])
        got = sm.validate_admission(
            reused, assembly=self.assembly, script=self.script,
            cuts_by_id=self.by_id,
            used_playback_occurrences=[first["playback_occurrence_id"]])
        self.assertFalse(got["ok"])
        self.assertIn("admission_occurrence_reused", {r["code"] for r in got["refusals"]})

    def test_a_receipt_from_the_admitted_occurrence_names_the_line(self):
        admission = sm.broadcast_admission("adm-8", assembly=self.assembly)
        third = self.assembly["cue_map"][2]
        receipt = {"playback_occurrence_id": admission["playback_occurrence_id"],
                   "assembly_id": self.assembly["assembly_id"],
                   "final_sha256": self.assembly["final_sha256"],
                   "cue_map_revision": self.assembly["cue_map_revision"],
                   "position_samples": third["speech_start_sample"] + 10,
                   "at_ms": 1000}
        got = sm.validate_playback_receipt(admission, receipt,
                                           assembly=self.assembly,
                                           now_ms=1500, max_age_ms=2000)
        self.assertTrue(got["ok"], got["reasons"])
        self.assertEqual(got["occurrence_id"], third["occurrence_id"])
        self.assertEqual(got["ordinal"], 3)

    def test_a_stale_player_receipt_is_refused(self):
        admission = sm.broadcast_admission("adm-9", assembly=self.assembly)
        previous = sm.broadcast_admission("adm-10", assembly=self.assembly)
        stale = {"playback_occurrence_id": previous["playback_occurrence_id"],
                 "assembly_id": self.assembly["assembly_id"],
                 "final_sha256": self.assembly["final_sha256"],
                 "cue_map_revision": self.assembly["cue_map_revision"],
                 "position_samples": 0, "at_ms": 1000}
        got = sm.validate_playback_receipt(admission, stale, assembly=self.assembly)
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "receipt_wrong_occurrence")
        self.assertIn("must not advance the broadcast", got["reason"])

        other_file = dict(stale,
                          playback_occurrence_id=admission["playback_occurrence_id"],
                          final_sha256=sm.audio_digest(b"some other take"))
        got = sm.validate_playback_receipt(admission, other_file,
                                           assembly=self.assembly)
        self.assertEqual(got["refusals"][0]["code"], "receipt_wrong_audio")

        old_cues = dict(stale,
                        playback_occurrence_id=admission["playback_occurrence_id"],
                        cue_map_revision="cue-0000000000000000")
        got = sm.validate_playback_receipt(admission, old_cues, assembly=self.assembly)
        self.assertEqual(got["refusals"][0]["code"], "receipt_stale_cue_map")

        expired = dict(stale,
                       playback_occurrence_id=admission["playback_occurrence_id"])
        got = sm.validate_playback_receipt(admission, expired, assembly=self.assembly,
                                           now_ms=99000, max_age_ms=2000)
        self.assertEqual(got["refusals"][0]["code"], "receipt_expired")

    def test_a_position_past_the_end_of_the_file_is_refused(self):
        admission = sm.broadcast_admission("adm-11", assembly=self.assembly)
        receipt = {"playback_occurrence_id": admission["playback_occurrence_id"],
                   "position_samples": self.assembly["final_frame_count"] + 5000}
        got = sm.validate_playback_receipt(admission, receipt, assembly=self.assembly)
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "cue_position_out_of_range")

    def test_an_admitted_occurrence_pins_its_takes(self):
        admission = sm.broadcast_admission("adm-12", assembly=self.assembly)
        pins = sm.pin_index([admission], {self.assembly["assembly_id"]: self.assembly},
                            self.by_id)
        self.assertEqual(sorted(pins["takes"]), ["take-ada", "take-bo"])
        replacement = dict(self.masters["Ada"],
                           audio_sha256=sm.audio_digest(b"re-recorded"))
        got = sm.check_overwrite("master", "take-ada", self.masters["Ada"],
                                 replacement, pins)
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "pinned_take_overwrite")
        self.assertIn("must never overwrite it", got["reason"])
        same = sm.check_overwrite("master", "take-ada", self.masters["Ada"],
                                  dict(self.masters["Ada"]), pins)
        self.assertTrue(same["ok"])
        self.assertTrue(same["unchanged"])


class StoreTests(unittest.TestCase):
    """Durability and recovery. Every one of these writes to a temp directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "manifests"
        self.store = ManifestStore(self.root)
        self.script = a_script()
        self.audio = {}
        self.masters = {}
        for actor, take in (("Ada", "take-ada"), ("Bo", "take-bo")):
            master, data = a_master(self.script, actor, take,
                                    session_id="sess-" + actor.lower())
            self.masters[actor] = master
            self.audio[master["media_ref"]] = data
        self.cuts = cuts_for(self.script, self.masters)

    def fill(self, *, admit=True):
        self.assertTrue(self.store.put_script(self.script)["ok"])
        sessions = {}
        for actor in ("Ada", "Bo"):
            session = sm.performer_session("sess-" + actor.lower(), self.script, actor)
            self.assertTrue(self.store.put_session(session)["ok"])
            self.assertTrue(self.store.put_master(self.masters[actor])["ok"])
            sessions[actor] = session
        for cut in self.cuts.values():
            got = self.store.put_cut(cut)
            self.assertTrue(got["ok"], got["reasons"])
        for actor, session in sessions.items():
            accepted = {line["occurrence_id"]: self.cuts[line["occurrence_id"]]["cut_id"]
                        for line in self.script["lines"] if line["actor"] == actor}
            done = dict(session, accepted=accepted, state="complete")
            self.assertTrue(self.store.put_session(done)["ok"])
            sessions[actor] = done
        assembly = assemble(self.script, self.cuts)
        got = self.store.put_assembly(assembly)
        self.assertTrue(got["ok"], got["reasons"])
        admission = None
        if admit:
            admission = sm.broadcast_admission("adm-1", assembly=assembly)
            got = self.store.put_admission(admission)
            self.assertTrue(got["ok"], got["reasons"])
        return sessions, assembly, admission

    def test_the_default_root_is_data_manifests_and_no_test_uses_it(self):
        self.assertEqual(ManifestStore().root, Path("data/manifests"))
        self.assertTrue(str(self.store.root).startswith(self.tmp.name))

    def test_neither_module_imports_the_running_station(self):
        for name in ("script_manifest.py", "manifest_store.py"):
            source = (Path(__file__).resolve().parent.parent / name).read_text(
                encoding="utf-8")
            for line in source.splitlines():
                stripped = line.strip()
                self.assertFalse(stripped.startswith("import app")
                                 or stripped.startswith("from app "), name)

    def test_records_land_on_disk_with_an_event_for_every_transition(self):
        sessions, assembly, admission = self.fill()
        revision = self.script["revision"]
        self.assertTrue((self.root / revision / "script.json").is_file())
        self.assertEqual(len(self.store.records("cut", revision)), 4)
        self.assertEqual(self.store.load("admission", revision, "adm-1")
                         ["playback_occurrence_id"],
                         admission["playback_occurrence_id"])
        kinds = [e["kind"] for e in self.store.events()]
        self.assertIn("script.frozen", kinds)
        self.assertIn("cut.stored", kinds)
        self.assertIn("admission.stored", kinds)
        self.assertEqual([e["seq"] for e in self.store.events()],
                         sorted(e["seq"] for e in self.store.events()))
        self.assertEqual(self.store.events(revision=revision)[0]["kind"],
                         "script.frozen")
        self.assertEqual(list(self.root.rglob("*.tmp")), [])

    def test_a_second_script_for_one_revision_is_refused(self):
        self.assertTrue(self.store.put_script(self.script)["ok"])
        forged = dict(self.script)
        forged["lines"] = [dict(r) for r in self.script["lines"]]
        forged["lines"][0] = dict(forged["lines"][0], text="Say nothing.")
        got = self.store.put_script(forged)
        self.assertFalse(got["ok"])
        self.assertIn(got["refusals"][0]["code"],
                      ("script_revision_frozen", "script_occurrence_mismatch",
                       "script_revision_mismatch"))

    def test_a_record_for_an_unstored_revision_is_refused(self):
        master, _ = a_master(self.script, "Ada", "take-x")
        got = self.store.put_master(master)
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "unknown_revision")
        self.assertEqual(self.store.events()[-1]["kind"], "master.refused")

    def test_a_rejected_take_is_kept_with_the_reason_it_failed(self):
        self.assertTrue(self.store.put_script(self.script)["ok"])
        self.assertTrue(self.store.put_master(self.masters["Ada"])["ok"])
        line = self.script["lines"][0]
        bad = a_cut(self.script, self.masters["Ada"], line, cut_id="cut-1a",
                    method="alignment", transcript="Say that", state="rejected")
        got = self.store.put_cut(bad)
        self.assertFalse(got["ok"])
        self.assertTrue(got["stored"])
        self.assertIsNotNone(self.store.load("cut", self.script["revision"], "cut-1a"))
        event = [e for e in self.store.events() if e["subject"] == "cut-1a"][-1]
        self.assertEqual(event["kind"], "cut.stored")
        self.assertFalse(event["ok"])
        self.assertTrue(any("scripted word" in r for r in event["reasons"]))

        good = a_cut(self.script, self.masters["Ada"], line, cut_id="cut-1b",
                     start=30000, transcript=line["text"])
        self.assertTrue(self.store.put_cut(good)["ok"])

    def test_an_accepted_cut_that_does_not_verify_is_never_stored(self):
        self.assertTrue(self.store.put_script(self.script)["ok"])
        self.assertTrue(self.store.put_master(self.masters["Ada"])["ok"])
        line = self.script["lines"][0]
        bad = a_cut(self.script, self.masters["Ada"], line, cut_id="cut-bad",
                    method="silence", transcript=line["text"], state="accepted")
        got = self.store.put_cut(bad)
        self.assertFalse(got["ok"])
        self.assertFalse(got["stored"])
        self.assertIsNone(self.store.load("cut", self.script["revision"], "cut-bad"))

    def test_an_incomplete_conversation_is_refused_at_the_store(self):
        self.assertTrue(self.store.put_script(self.script)["ok"])
        for actor in ("Ada", "Bo"):
            self.assertTrue(self.store.put_master(self.masters[actor])["ok"])
        for line in self.script["lines"][:3]:
            self.assertTrue(self.store.put_cut(self.cuts[line["occurrence_id"]])["ok"])
        partial = assemble(self.script, self.cuts,
                           order=sm.script_sequence(self.script)[:3])
        got = self.store.put_assembly(partial)
        self.assertFalse(got["ok"])
        self.assertIsNone(self.store.load("assembly", self.script["revision"],
                                          partial["assembly_id"]))
        admission = sm.broadcast_admission("adm-bad", assembly=partial)
        got = self.store.put_admission(admission)
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "admission_assembly_missing")

    def test_new_work_never_overwrites_a_take_an_admission_pinned(self):
        self.fill()
        replacement = dict(self.masters["Ada"],
                           audio_sha256=sm.audio_digest(b"re-recorded"))
        got = self.store.put_master(replacement)
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "pinned_take_overwrite")
        stored = self.store.load("master", self.script["revision"], "take-ada")
        self.assertEqual(stored["audio_sha256"], self.masters["Ada"]["audio_sha256"])
        line = self.script["lines"][0]
        moved = dict(self.cuts[line["occurrence_id"]], start_sample=99, end_sample=999)
        self.assertFalse(self.store.put_cut(moved)["ok"])

    def test_rebuild_recovers_the_view_and_names_what_it_cannot(self):
        self.fill()
        revision = self.script["revision"]
        got = self.store.rebuild()
        self.assertTrue(got["ok"], got["reasons"])
        self.assertEqual(got["counts"], {"revisions": 1, "sessions": 2, "masters": 2,
                                         "cuts": 4, "assemblies": 1, "admissions": 1})
        self.assertEqual(sorted(got["pins"]["takes"]), ["take-ada", "take-bo"])
        view = got["revisions"][revision]
        self.assertEqual(sm.script_sequence(view["script"]),
                         sm.script_sequence(self.script))

        # A torn write, a stray file, an event log with a half-written tail,
        # and a revision directory with no script at all.
        (self.root / revision / "cuts" / "cut-torn.json").write_text(
            '{"kind": "line_cut", "cut_id"', encoding="utf-8")
        (self.root / revision / "masters" / "take-ada.json").rename(
            self.root / revision / "masters" / "take-renamed.json")
        with open(self.root / "events.jsonl", "a", encoding="utf-8") as handle:
            handle.write('{"seq": 999, "kind": "cut.st')
        (self.root / "rev-orphan").mkdir()
        damaged = self.store.rebuild()
        self.assertFalse(damaged["ok"])
        codes = {row["code"] for row in damaged["damaged"]}
        self.assertEqual(codes, {"record_unreadable", "record_id_mismatch",
                                 "event_unreadable", "script_missing"})
        self.assertTrue(all(row["reason"] and row["path"]
                            for row in damaged["damaged"]))
        # The undamaged records are still recovered.
        self.assertEqual(damaged["counts"]["cuts"], 4)
        self.assertEqual(damaged["counts"]["masters"], 1)

    def test_an_interrupted_session_resumes_from_its_verified_takes(self):
        self.assertTrue(self.store.put_script(self.script)["ok"])
        session = sm.performer_session("sess-ada", self.script, "Ada")
        self.assertTrue(self.store.put_session(session)["ok"])
        self.assertTrue(self.store.put_master(self.masters["Ada"])["ok"])
        first, third = self.script["lines"][0], self.script["lines"][2]
        for line in (first, third):
            self.assertTrue(self.store.put_cut(self.cuts[line["occurrence_id"]])["ok"])
        interrupted = dict(session, state="interrupted", accepted={
            first["occurrence_id"]: self.cuts[first["occurrence_id"]]["cut_id"],
            third["occurrence_id"]: self.cuts[third["occurrence_id"]]["cut_id"]})
        self.assertTrue(self.store.put_session(interrupted)["ok"])

        # A second store, as after a restart: nothing is held in memory.
        fresh = ManifestStore(self.root)
        got = fresh.resume_session("sess-ada", self.script["revision"],
                                   read_audio=lambda ref: self.audio[ref])
        self.assertTrue(got["ok"], got["reasons"])
        self.assertEqual(got["session"]["state"], "complete")
        self.assertEqual(len(got["verified"]), 2)
        self.assertEqual(got["remaining"], [])
        self.assertEqual(fresh.load("session", self.script["revision"],
                                    "sess-ada")["state"], "complete")
        self.assertIn("session.resumed", [e["kind"] for e in fresh.events()])

    def test_resuming_drops_work_whose_master_changed_and_says_so(self):
        self.test_an_interrupted_session_resumes_from_its_verified_takes()
        fresh = ManifestStore(self.root)
        got = fresh.resume_session("sess-ada", self.script["revision"],
                                   read_audio=lambda ref: b"a different recording")
        self.assertFalse(got["ok"])
        self.assertEqual(got["verified"], [])
        self.assertEqual(len(got["remaining"]), 2)
        self.assertEqual(got["session"]["state"], "recording")
        self.assertTrue(all("no longer hashes" in row["reason"]
                            for row in got["dropped"]))
        self.assertEqual(fresh.load("session", self.script["revision"],
                                    "sess-ada")["accepted"], {})

    def test_resuming_drops_a_take_whose_cut_is_gone(self):
        self.test_an_interrupted_session_resumes_from_its_verified_takes()
        revision = self.script["revision"]
        third = self.script["lines"][2]
        gone = self.cuts[third["occurrence_id"]]["cut_id"]
        (self.root / revision / "cuts" / (gone + ".json")).unlink()
        # Put the session back into its interrupted shape first.
        session = self.store.load("session", revision, "sess-ada")
        session["accepted"][third["occurrence_id"]] = gone
        session["state"] = "interrupted"
        ManifestStore(self.root)._write_json(
            self.root / revision / "sessions" / "sess-ada.json", session)

        got = ManifestStore(self.root).resume_session("sess-ada", revision)
        self.assertFalse(got["ok"])
        self.assertEqual(got["verified"],
                         [self.script["lines"][0]["occurrence_id"]])
        self.assertEqual(got["remaining"], [third["occurrence_id"]])
        self.assertIn("is not on disk", got["dropped"][0]["reason"])
        self.assertEqual(got["session"]["state"], "recording")

    def test_an_abandoned_session_is_not_quietly_resumed(self):
        self.assertTrue(self.store.put_script(self.script)["ok"])
        session = sm.performer_session("sess-bo", self.script, "Bo",
                                       state="abandoned")
        self.assertTrue(self.store.put_session(session)["ok"])
        got = self.store.resume_session("sess-bo", self.script["revision"])
        self.assertFalse(got["ok"])
        self.assertEqual(got["refusals"][0]["code"], "session_abandoned")

    def test_a_revision_change_leaves_the_admitted_revision_untouched(self):
        _, assembly, admission = self.fill()
        lines = [dict(r) for r in self.script["lines"]]
        lines[3]["text"] = "The kettle is cold."
        later = sm.revise_script(self.script, lines=lines)
        self.assertTrue(self.store.put_script(later)["ok"])
        self.assertEqual(len(self.store.list_revisions()), 2)
        # The admitted revision still reads exactly as it was committed.
        stored = self.store.load("admission", self.script["revision"], "adm-1")
        self.assertEqual(stored["final_sha256"], assembly["final_sha256"])
        self.assertEqual(stored["playback_occurrence_id"],
                         admission["playback_occurrence_id"])
        self.assertEqual(sm.script_sequence(
            self.store.load_script(self.script["revision"])),
            sm.script_sequence(self.script))
        carried = sm.carry_over(self.script, later, {
            line["occurrence_id"]: self.cuts[line["occurrence_id"]]["cut_id"]
            for line in self.script["lines"]})
        self.assertEqual(len(carried["carried"]), 3)
        self.assertEqual(len(carried["dropped"]), 1)

    def test_every_refusal_carries_a_sentence_a_person_can_read(self):
        self.fill()
        refused = [e for e in self.store.events() if not e["ok"]]
        replacement = dict(self.masters["Bo"], media_ref="/voice/elsewhere.wav")
        got = self.store.put_master(replacement)
        self.assertFalse(got["ok"])
        for row in got["refusals"]:
            self.assertTrue(row["code"] and row["reason"])
            self.assertGreater(len(row["reason"].split()), 4)
        self.assertGreater(len([e for e in self.store.events() if not e["ok"]]),
                           len(refused))


if __name__ == "__main__":
    unittest.main()
