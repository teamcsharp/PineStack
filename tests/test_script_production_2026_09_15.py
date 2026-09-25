"""The producer: freeze, session, cut, assemble, admit - and every refusal.

Boundary 6 of `docs/notes/speaker-recording-and-script-assembly.md`: the
orchestrator wiring that actually runs the flow the note describes.

Every test writes to a `tempfile.TemporaryDirectory` and nothing else. No
test imports `app.py`, touches `data/`, or appends to the script ledger -
the 2026-09-14 audit records that existing fixtures have appended rows to
the live document, and `LiveStoreIsolationTests` asserts the isolation here
rather than trusting it.

    python -m pytest tests/test_script_production_2026_09_15.py -q
"""
from __future__ import annotations

import json
import math
import os
import re
import struct
import sys
import tempfile
import unittest
from unittest import mock
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import conversation_assembly as ca          # noqa: E402
import line_alignment as la                 # noqa: E402
import manifest_store as ms                 # noqa: E402
import script_manifest as sm                # noqa: E402
import script_production as sp              # noqa: E402

RATE = 24000
TAIL_MS = ca.box_tail_ms()


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

def tone(path: Path, seconds: float, hz: float, *, rate: int = RATE,
         tail_ms: int = TAIL_MS) -> Path:
    """One rendered take: a pure tone with the station's BOX_TAIL_MS pad on
    the end, which is exactly the shape `voice_render_any` leaves on disk."""
    frames = int(seconds * rate)
    samples = [int(9000 * math.sin(2 * math.pi * hz * n / rate))
               for n in range(frames)]
    samples += [0] * int(rate * tail_ms / 1000.0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack("<%dh" % len(samples), *samples))
    return path


class Fixture:
    """A round exactly as `larder_prepare` would leave it: a plan in script
    order, a cast, and one rendered file per line in a pantry."""

    def __init__(self, root: Path, plan=None):
        self.root = Path(root)
        self.media = self.root / "voice_media"
        self.data = self.root / "data"
        self.media.mkdir(parents=True, exist_ok=True)
        self.data.mkdir(parents=True, exist_ok=True)
        self.plan = plan or [
            ("Right, that is the memo dealt with.", "hostvoice", "dj"),
            ("Is it though.", "cohostvoice", "cohost"),
            ("Right, that is the memo dealt with.", "hostvoice", "dj"),
            ("Is it though.", "cohostvoice", "cohost"),
        ]
        self.voices = {"dj": "hostvoice", "cohost": "cohostvoice"}
        self.pantry: dict[str, dict] = {}
        for index, (text, voice, who) in enumerate(self.plan):
            key = self.key(text, voice, self.engine(voice))
            if key in self.pantry:
                continue
            name = "%032x.wav" % (index + 1)
            path = tone(self.media / name, 0.5 + 0.12 * index, 300 + 90 * index)
            self.pantry[key] = {"path": str(path),
                                "seconds": round(0.5 + 0.12 * index, 3)}

    # the station's own lookups, injected
    @staticmethod
    def engine(voice: str) -> str:
        return "xtts"

    @staticmethod
    def key(text: str, voice: str, engine: str) -> str:
        return sm.content_cache_key(text, voice, engine)

    def clip(self, text: str, voice: str, engine: str):
        return self.pantry.get(self.key(text, voice, engine))

    def source(self, conversation_id: str = "round-1"):
        return sp.round_source(
            conversation_id, self.plan, self.voices,
            engine_for=self.engine, clip_for=self.clip,
            media_root=self.media, cache_key_for=self.key,
            label="a booth round", kind="banter")

    def producer(self, mode: str = "shadow", **kwargs):
        producer = sp.ScriptProducer(self.data, self.media, **kwargs)
        producer.switch.write(mode)
        return producer


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="script-production-")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)


# --------------------------------------------------------------------------
# the switch
# --------------------------------------------------------------------------

class SwitchTests(TempCase):

    def test_default_is_off(self):
        switch = sp.ProductionSwitch(self.root / "script_production", env={})
        self.assertEqual(switch.mode(), sp.MODE_OFF)
        self.assertTrue(switch.settings().off)

    def test_every_mode_word(self):
        for word, mode in (("off", sp.MODE_OFF), ("shadow", sp.MODE_SHADOW),
                           ("on", sp.MODE_ON)):
            self.assertEqual(sp.parse_settings(word).mode, mode)

    def test_unknown_word_is_off_not_on(self):
        # An operator's typo must never be read as permission.
        for word in ("enforce", "yes", "ON!", "shadw", ""):
            self.assertEqual(sp.parse_settings(word).mode, sp.MODE_OFF, word)

    def test_road_defaults_to_segmented(self):
        self.assertEqual(sp.parse_settings("shadow").road, sp.ROAD_SEGMENTED)
        self.assertEqual(sp.parse_settings("shadow continuous").road,
                         sp.ROAD_CONTINUOUS)
        self.assertEqual(sp.ROAD_SEGMENTED, la.MODE_SEGMENTED)
        self.assertEqual(sp.ROAD_CONTINUOUS, la.MODE_CONTINUOUS)

    def test_numbers(self):
        self.assertEqual(sp.parse_settings("on").max_lines, 72)
        got = sp.parse_settings("on budget=12.5 every=7 lines=3")
        self.assertEqual((got.budget_s, got.every_s, got.max_lines),
                         (12.5, 7.0, 3))
        bad = sp.parse_settings("on budget=nonsense every=-4 lines=0")
        self.assertEqual(bad.budget_s, sp.DEFAULT_BUDGET_S)
        self.assertEqual(bad.every_s, sp.DEFAULT_EVERY_S)
        self.assertEqual(bad.max_lines, sp.DEFAULT_MAX_LINES)

    def test_file_wins_and_is_reread_without_a_restart(self):
        now = [1000.0]
        room = self.root / "script_production"
        switch = sp.ProductionSwitch(room, env={}, ttl=3.0,
                                     clock=lambda: now[0])
        switch.write("off")
        self.assertEqual(switch.mode(), "off")
        switch.write("shadow")
        # written through the switch, so the cache is cleared: immediate
        self.assertEqual(switch.mode(), "shadow")
        # a write by somebody else is picked up after the ttl, not before
        (room / "mode").write_text("on\n", encoding="utf-8")
        self.assertEqual(switch.mode(), "shadow")
        now[0] += 4.0
        self.assertEqual(switch.mode(), "on")

    def test_environment_only_when_the_file_is_empty(self):
        room = self.root / "script_production"
        switch = sp.ProductionSwitch(
            room, env={"SPARK_AGENT_SCRIPT_PRODUCTION": "shadow"})
        self.assertEqual(switch.mode(), "shadow")
        switch.write("off")
        self.assertEqual(switch.mode(), "off")


# --------------------------------------------------------------------------
# building the round
# --------------------------------------------------------------------------

class RoundSourceTests(TempCase):

    def test_script_order_and_cast(self):
        fixture = Fixture(self.root)
        source, refusals = fixture.source()
        self.assertEqual(refusals, [])
        self.assertEqual([line.actor for line in source.lines],
                         ["dj", "cohost", "dj", "cohost"])
        self.assertEqual(sorted(source.cast), ["cohost", "dj"])
        self.assertEqual(source.cast["dj"]["engine"], "xtts")

    def test_a_line_with_no_audio_refuses_the_whole_round(self):
        fixture = Fixture(self.root)
        fixture.pantry.pop(next(iter(fixture.pantry)))
        _source, refusals = fixture.source()
        self.assertIn("round_incomplete", [r["code"] for r in refusals])

    def test_audio_missing_from_disk_is_named(self):
        fixture = Fixture(self.root)
        first = next(iter(fixture.pantry.values()))
        os.remove(first["path"])
        _source, refusals = fixture.source()
        self.assertIn("media_missing", [r["code"] for r in refusals])

    def test_a_seat_that_changes_voice_is_not_one_performance(self):
        plan = [("one", "a", "dj"), ("two", "b", "dj")]
        fixture = Fixture(self.root, plan=plan)
        _source, refusals = fixture.source()
        self.assertIn("no_cast", [r["code"] for r in refusals])

    def test_context_is_the_surrounding_dialogue(self):
        fixture = Fixture(self.root)
        source, _ = fixture.source()
        self.assertEqual(getattr(source.lines[0], "context_before"), "")
        self.assertTrue(getattr(source.lines[0], "context_after")
                        .startswith("cohost: "))

    def test_multiple_render_chunks_count_as_one_spoken_turn(self):
        fixture = Fixture(self.root, plan=[
            ("Opening half.", "hostvoice", "dj"),
            ("Closing half.", "hostvoice", "dj"),
            ("Reply.", "cohostvoice", "cohost"),
        ])
        source, refusals = sp.round_source(
            "round-chunks", fixture.plan, fixture.voices,
            engine_for=fixture.engine, clip_for=fixture.clip,
            media_root=fixture.media,
            line_plan=[{"at": 0, "line_from": 0, "line_to": 2},
                       {"at": 1, "line_from": 2, "line_to": 3}])
        self.assertEqual(refusals, [])
        self.assertEqual([line.turn for line in source.lines], [0, 0, 1])
        result = fixture.producer("shadow").produce(source)
        self.assertTrue(result.ok, result.reasons)
        self.assertEqual(result.supply["turns"], 2)


# --------------------------------------------------------------------------
# the whole road, in shadow
# --------------------------------------------------------------------------

class ShadowProductionTests(TempCase):

    def setUp(self):
        super().setUp()
        self.fixture = Fixture(self.root)
        self.producer = self.fixture.producer("shadow")
        self.source, refusals = self.fixture.source()
        self.assertEqual(refusals, [])
        self.result = self.producer.produce(self.source)

    def test_it_produced_a_complete_admissible_conversation(self):
        self.assertTrue(self.result.ok, self.result.reasons)
        self.assertTrue(self.result.revision)
        self.assertTrue(self.result.assembly_id)
        self.assertTrue(self.result.playback_occurrence_id)
        self.assertEqual(len(self.result.cuts), 4)

    def test_the_cue_map_is_measured_and_never_rescaled(self):
        self.assertEqual(self.result.cue_map["derivation"], "measured")
        self.assertEqual(self.result.cue_map["sample_rate"], RATE)
        starts = [c["start_sample"] for c in self.result.cue_map["cues"]]
        self.assertEqual(starts, sorted(starts))
        for cue in self.result.cue_map["cues"]:
            self.assertTrue(cue["exact"])
            self.assertLessEqual(cue["speech_end_sample"], cue["cue_end_sample"])

    def test_supply_uses_measured_body_and_speech_not_file_tail(self):
        supply = self.producer.round_payload(self.result)["production"]["supply"]
        cues = self.result.cue_map["cues"]
        self.assertEqual(supply["body_frames"], self.result.cue_map["body_frames"])
        self.assertEqual(supply["sample_rate"], RATE)
        self.assertEqual(supply["speech_frames"], sum(
            cue["speech_end_sample"] - cue["speech_start_sample"]
            for cue in cues if cue["kind"] == "line"))
        self.assertLess(supply["playable_seconds"], self.result.seconds)
        self.assertLessEqual(supply["recorded_seconds"], supply["playable_seconds"])
        self.assertEqual(supply["roles"], ["cohost", "dj"])
        self.assertEqual(supply["lines"], len(self.source.lines))

    def test_the_finished_sequence_is_the_frozen_sequence(self):
        script = self.producer.store.load_script(self.result.revision)
        self.assertEqual(self.result.cue_map["sequence"], script["sequence"])

    def test_two_occurrences_of_identical_words_are_different_records(self):
        script = self.producer.store.load_script(self.result.revision)
        first, third = script["lines"][0], script["lines"][2]
        self.assertEqual(first["text"], third["text"])
        self.assertNotEqual(first["occurrence_id"], third["occurrence_id"])
        # and the station's own content key cannot tell them apart, which is
        # exactly why the manifest identity exists
        self.assertEqual(sm.content_cache_key(first["text"], "hostvoice", "xtts"),
                         sm.content_cache_key(third["text"], "hostvoice", "xtts"))

    def test_it_is_labelled_segmented_synthesis_and_never_continuous(self):
        self.assertEqual(self.result.road, sp.ROAD_SEGMENTED)
        for master in self.result.masters:
            self.assertEqual(master["mode"], "segmented")
        for cut in self.result.cuts:
            self.assertEqual(cut["boundary_method"], sp.BOUNDARY_RENDERER)
            self.assertEqual(cut["verification"]["synthesis"],
                             la.MODE_SEGMENTED)
            self.assertFalse(cut["verification"]["ambiguous"])

    def test_no_cut_was_decided_by_silence(self):
        for cut in self.result.cuts:
            self.assertNotIn(cut["boundary_method"],
                             sm.AMBIGUOUS_BOUNDARY_METHODS)

    def test_a_cut_is_the_whole_master_because_the_renderer_drew_the_edges(self):
        masters = {m["take_id"]: m for m in self.result.masters}
        for cut in self.result.cuts:
            master = masters[cut["take_id"]]
            self.assertEqual(cut["start_sample"], 0)
            self.assertEqual(cut["end_sample"], master["frame_count"])

    def test_shadow_throws_the_audio_away(self):
        self.assertFalse(self.result.aired)
        self.assertEqual(self.result.media, "")
        digest = self.result.cue_map["final_audio_hash"]
        self.assertFalse((self.fixture.media / (digest[:32] + ".wav")).exists())
        # ...and the round payload carries no cue map, so the air road is
        # byte for byte what it would have been
        payload = self.producer.round_payload(self.result)
        self.assertNotIn("cue_map", payload)
        self.assertTrue(payload["production"]["available"])

    def test_every_manifest_record_is_on_disk(self):
        store = self.producer.store
        revision = self.result.revision
        self.assertIsNotNone(store.load_script(revision))
        self.assertEqual(len(store.records("session", revision)), 2)
        self.assertEqual(len(store.records("master", revision)), 4)
        self.assertEqual(len(store.records("cut", revision)), 4)
        self.assertEqual(len(store.records("assembly", revision)), 1)
        self.assertEqual(len(store.records("admission", revision)), 1)

    def test_the_store_rebuilds_undamaged(self):
        view = self.producer.store.rebuild()
        self.assertEqual(view["damaged"], [])

    def test_the_disagreement_with_the_estimate_was_measured(self):
        got = self.result.disagreement
        self.assertTrue(got["comparable"], got.get("why"))
        self.assertEqual(got["lines"], 4)
        self.assertEqual(len(got["per_line"]), 4)
        self.assertGreaterEqual(got["max_abs_s"], 0.0)

    def test_the_ledger_recorded_the_round(self):
        report = self.producer.ledger.report()
        self.assertEqual(report["rounds"], 1)
        self.assertEqual(report["complete"], 1)
        self.assertEqual(report["aired"], 0)
        self.assertGreater(report["cost_seconds"]["total"], 0.0)

    def test_the_incident_references_are_all_present(self):
        refs = sp.references(self.result, mode="shadow")
        for field in ("script_revision", "performer_sessions", "accepted_cuts",
                      "assembly_id", "cue_map_revision", "final_audio_hash",
                      "playback_occurrence_id"):
            self.assertTrue(refs[field], field)
        self.assertTrue(refs["available"])
        self.assertIn("discarded", refs["why"])

    def test_an_absent_reference_says_so_instead_of_inventing_one(self):
        refs = sp.references(None)
        self.assertFalse(refs["available"])
        self.assertIsNone(refs["script_revision"])
        self.assertIsNone(refs["playback_occurrence_id"])
        self.assertTrue(refs["why"])


# --------------------------------------------------------------------------
# on
# --------------------------------------------------------------------------

class OnModeTests(TempCase):

    def test_on_keeps_the_audio_and_hands_over_the_cue_map(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("on")
        source, _ = fixture.source()
        result = producer.produce(source)
        self.assertTrue(result.ok, result.reasons)
        self.assertTrue(result.aired)
        kept = Path(result.media)
        self.assertTrue(kept.is_file())
        # content-addressed the way every other clip on this station is
        self.assertTrue(re.match(r"^[a-f0-9]{32}\.wav$", kept.name))
        self.assertEqual(kept.name[:32],
                         result.cue_map["final_audio_hash"][:32])
        payload = producer.round_payload(result)
        self.assertIn("cue_map", payload)
        self.assertEqual(payload["cue_map"]["derivation"], "measured")
        # the beats travel with the map, so the air road's re-mix is the
        # file that was measured
        self.assertEqual(len(payload["cue_map"]["mix"]["beats"]), 4)

    def test_the_occurrence_map_names_every_line_by_ordinal(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("on")
        source, _ = fixture.source()
        result = producer.produce(source)
        rows = producer.occurrence_map(source, result)
        self.assertEqual([r["ordinal"] for r in rows], [1, 2, 3, 4])
        self.assertEqual([r["actor"] for r in rows],
                         ["dj", "cohost", "dj", "cohost"])
        self.assertEqual(len({r["occurrence_id"] for r in rows}), 4)
        for row in rows:
            self.assertTrue(row["cut_id"])
            self.assertTrue(row["take_id"])


# --------------------------------------------------------------------------
# refusals and recovery
# --------------------------------------------------------------------------

class RefusalTests(TempCase):

    def test_off_produces_nothing_even_when_called(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("off")
        source, _ = fixture.source()
        result = producer.produce(source)
        self.assertFalse(result.ok)
        self.assertEqual(result.refusal(), "production_off")
        self.assertFalse((self.root / "data" / "manifests").exists())

    def test_a_round_longer_than_the_switch_allows(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("shadow lines=2")
        source, _ = fixture.source()
        result = producer.produce(source)
        self.assertEqual(result.refusal(), "round_too_long")

    def test_an_unreadable_master_refuses_the_conversation(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("shadow")
        source, _ = fixture.source()
        Path(source.lines[1].media).write_bytes(b"not a wav at all")
        result = producer.produce(source)
        self.assertFalse(result.ok)
        self.assertIn("media_unreadable", result.codes)

    def test_a_changed_master_under_a_stored_cut_is_caught(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("shadow")
        source, _ = fixture.source()
        first = producer.produce(source)
        self.assertTrue(first.ok, first.reasons)
        # the same revision, a different master behind one of its lines
        tone(Path(source.lines[0].media), 0.9, 410)
        second = producer.produce(source)
        self.assertFalse(second.ok)
        self.assertTrue(second.refusals)

    def test_resuming_the_same_revision_keeps_its_original_creation_stamp(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("shadow")
        source, _ = fixture.source()
        first = sp.Production()
        with mock.patch.object(sm.time, "time", return_value=100.0):
            frozen = producer.freeze(source, first)
        self.assertIsNotNone(frozen)
        second = sp.Production()
        with mock.patch.object(sm.time, "time", return_value=200.0):
            resumed = producer.freeze(source, second)
        self.assertIsNotNone(resumed, second.reasons)
        self.assertEqual(resumed["revision"], frozen["revision"])
        self.assertEqual(resumed["created_at"], 100.0)
        self.assertEqual(second.refusals, [])

    def test_an_interrupted_session_resumes_from_verified_takes(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("shadow")
        source, _ = fixture.source()
        first = producer.produce(source)
        self.assertTrue(first.ok, first.reasons)
        revision = first.revision
        session_id = producer.session_id(revision, "dj")
        resumed = producer.store.resume_session(session_id, revision,
                                                commit=False)
        self.assertTrue(resumed["ok"], resumed.get("reasons"))
        self.assertEqual(len(resumed["session"]["accepted"]), 2)
        self.assertEqual(resumed["dropped"], [])
        self.assertEqual(resumed["remaining"], [])

    def test_a_resume_drops_work_a_deleted_cut_can_no_longer_prove(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("shadow")
        source, _ = fixture.source()
        first = producer.produce(source)
        revision = first.revision
        cuts = producer.store.records("cut", revision)
        victim = sorted(cuts)[0]
        os.remove(producer.store.record_path("cut", revision, victim))
        session = None
        for actor in ("dj", "cohost"):
            got = producer.store.resume_session(
                producer.session_id(revision, actor), revision, commit=False)
            if got["dropped"]:
                session = got
        self.assertIsNotNone(session, "the deleted cut was not noticed")
        self.assertTrue(session["dropped"][0]["reason"])
        self.assertTrue(session["remaining"])

    def test_an_admitted_occurrence_pins_its_take(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("shadow")
        source, _ = fixture.source()
        result = producer.produce(source)
        pins = producer.store.pins(result.revision)
        self.assertTrue(pins["takes"])
        self.assertTrue(pins["assemblies"])

    def test_the_refusal_vocabulary_is_complete(self):
        # every code this module can emit has a sentence beside it
        text = (ROOT / "script_production.py").read_text(encoding="utf-8")
        for code in re.findall(r'refuse\(\s*"([a-z_]+)"', text):
            self.assertIn(code, sp.REFUSALS, code)


# --------------------------------------------------------------------------
# order
# --------------------------------------------------------------------------

class ReadingOrderTests(TempCase):

    def test_actors_finishing_out_of_order_still_assemble_1_2_3_4(self):
        # The note's own example: A records lines 1 and 3, B lines 2 and 4.
        # Recording is grouped by performer; assembly must not be.
        fixture = Fixture(self.root)
        producer = fixture.producer("shadow")
        source, _ = fixture.source()
        result = producer.produce(source)
        self.assertTrue(result.ok, result.reasons)
        ordinals = [c["ordinal"] for c in result.cue_map["cues"]]
        self.assertEqual(ordinals, [1, 2, 3, 4])
        script = producer.store.load_script(result.revision)
        speakers = [sm.script_line_by_occurrence(script, c["occurrence_id"])["actor"]
                    for c in result.cue_map["cues"]]
        self.assertEqual(speakers, ["dj", "cohost", "dj", "cohost"])

    def test_a_cue_position_is_a_final_mix_position_not_a_master_offset(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("shadow")
        source, _ = fixture.source()
        result = producer.produce(source)
        for cue in result.cue_map["cues"][1:]:
            self.assertEqual(cue["source"]["start_sample"], 0)
            self.assertGreater(cue["start_sample"], 0)


# --------------------------------------------------------------------------
# the continuous-take road: a second capability, off
# --------------------------------------------------------------------------

class ContinuousRoadTests(TempCase):
    """A second capability with its own identity, and it is off.

    `docs/notes/continuous-take-bench-2026-09-15.md` measured it: not faster
    (21% slower uncontended), no measured prosody benefit (identical 0.034
    median read-back CER), and unreachable above 1,000 characters because the
    XTTS clone server truncates there silently. So it stays behind the
    switch, and the shipped road never depends on it.
    """

    def part(self, fixture, actor, seconds=1.6, hz=330):
        return tone(fixture.root / ("part-%s.wav" % actor), seconds, hz)

    def test_it_is_not_reached_by_the_word_that_turns_the_other_road_on(self):
        self.assertEqual(sp.parse_settings("on").road, sp.ROAD_SEGMENTED)
        self.assertEqual(sp.parse_settings("shadow").road, sp.ROAD_SEGMENTED)

    def test_with_no_master_it_refuses_rather_than_relabelling_the_other_road(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("shadow continuous")
        source, _ = fixture.source()
        result = producer.produce(source)
        self.assertFalse(result.ok)
        self.assertIn("continuous_master_missing", result.codes)
        self.assertEqual(result.cuts, [])

    def test_with_a_master_but_no_recogniser_it_refuses_by_name(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("shadow continuous")
        source, _ = fixture.source()
        source.parts = {"dj": str(self.part(fixture, "dj")),
                        "cohost": str(self.part(fixture, "cohost"))}
        result = producer.produce(source)
        self.assertIn("alignment_unavailable", result.codes)
        self.assertEqual(result.cuts, [])

    def test_a_part_over_the_engines_silent_ceiling_is_refused(self):
        # voice_clone_server.py:371 is _synthesize(text[:1000], ...): it
        # truncates in the server, returns HTTP 200, and three measured
        # rounds lost 34-40% of their words with no error anywhere. A part
        # that cannot have been performed whole is not a continuous take.
        long_line = "word " * 260                    # 1,300 characters
        plan = [(long_line.strip(), "hostvoice", "dj")]
        fixture = Fixture(self.root, plan=plan)
        producer = fixture.producer("shadow continuous",
                                    align=lambda **kw: {"words": []})
        source, _ = fixture.source()
        source.parts = {"dj": str(self.part(fixture, "dj"))}
        result = producer.produce(source)
        self.assertIn("request_cap_exceeded", result.codes)
        self.assertIn("1000", " ".join(result.reasons))
        self.assertEqual(sp.ENGINE_REQUEST_CAPS["xtts"], 1000)
        self.assertEqual(sp.ENGINE_REQUEST_CAPS["f5"], 280)

    def test_a_recogniser_that_hears_the_part_produces_aligned_cuts(self):
        fixture = Fixture(self.root)

        def recogniser(*, media, script, sample_rate, frame_count):
            words = []
            text = []
            span = (frame_count / float(sample_rate))
            said = [w for line in script for w in str(line["text"]).split()]
            step = span / max(1, len(said))
            for index, word in enumerate(said):
                words.append({"word": word, "start": index * step,
                              "end": (index + 1) * step, "probability": 0.99})
                text.append(word)
            return {"text": " ".join(text), "words": words}

        producer = fixture.producer("shadow continuous", align=recogniser)
        source, _ = fixture.source()
        source.parts = {"dj": str(self.part(fixture, "dj", 2.0, 300)),
                        "cohost": str(self.part(fixture, "cohost", 2.0, 400))}
        result = producer.produce(source)
        self.assertTrue(result.ok, result.reasons)
        self.assertEqual(result.road, sp.ROAD_CONTINUOUS)
        # ONE master per performer, not one per line
        self.assertEqual(len(result.masters), 2)
        self.assertEqual(len(result.cuts), 4)
        for master in result.masters:
            self.assertEqual(master["mode"], "continuous")
        for cut in result.cuts:
            self.assertEqual(cut["boundary_method"], sp.BOUNDARY_ALIGNMENT)
            self.assertEqual(cut["verification"]["synthesis"],
                             la.MODE_CONTINUOUS)
            self.assertTrue(cut["verification"]["transcript"])

    def test_a_recogniser_that_cannot_be_reached_is_named_not_swallowed(self):
        fixture = Fixture(self.root)

        def broken(**_kwargs):
            raise OSError("voice-lab is down")

        producer = fixture.producer("shadow continuous", align=broken)
        source, _ = fixture.source()
        source.parts = {"dj": str(self.part(fixture, "dj"))}
        result = producer.produce(source)
        self.assertIn("alignment_unavailable", result.codes)
        self.assertIn("voice-lab is down", " ".join(result.reasons))

    def test_a_recogniser_that_heard_something_else_is_refused(self):
        fixture = Fixture(self.root)
        heard = "completely different words entirely"

        def wrong(*, media, script, sample_rate, frame_count):
            return {"text": heard,
                    "words": [{"word": w, "start": i * 0.2,
                               "end": i * 0.2 + 0.2, "probability": 0.99}
                              for i, w in enumerate(heard.split())]}

        producer = fixture.producer("shadow continuous", align=wrong)
        source, _ = fixture.source()
        source.parts = {"dj": str(self.part(fixture, "dj")),
                        "cohost": str(self.part(fixture, "cohost"))}
        result = producer.produce(source)
        self.assertFalse(result.ok)
        self.assertTrue(result.codes)

    def test_nothing_in_this_module_ever_calls_an_engine(self):
        # The station's own 800-character cap is what stands between it and
        # the silent truncation. Nothing here may add a second road to it.
        text = (ROOT / "script_production.py").read_text(encoding="utf-8")
        # a CALL, not a mention: the docstring names the station's renderer
        # to explain why this module does not use it.
        for forbidden in ("voice_render_any(", "requests.post(", "import httpx",
                          "urlopen(", "import aiohttp", "http://", "https://"):
            self.assertNotIn(forbidden, text, forbidden)


# --------------------------------------------------------------------------
# the estimate this replaces
# --------------------------------------------------------------------------

class EstimateTests(TempCase):

    def test_the_estimate_is_computed_and_is_not_the_measurement(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("shadow")
        source, _ = fixture.source()
        result = producer.produce(source)
        rows = sp.estimated_windows(
            [line.media for line in source.lines],
            (result.assembly_record.get("mix") or {}).get("beats") or [],
            float(result.seconds))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["from"], 0.0)
        got = sp.compare_windows(result.cue_map, rows)
        self.assertTrue(got["comparable"])
        self.assertEqual(got["paired_by"], "ordinal")

    def test_lists_of_different_lengths_are_refused_not_zipped(self):
        got = sp.compare_windows({"cues": [{"ordinal": 1, "kind": "line"}]},
                                 [{"from": 0.0}, {"from": 1.0}])
        self.assertFalse(got["comparable"])
        self.assertIn("different numbers of lines", got["why"])

    def test_nothing_to_compare_says_so(self):
        got = sp.compare_windows({"cues": []}, [])
        self.assertFalse(got["comparable"])
        self.assertTrue(got["why"])


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------

class LedgerTests(TempCase):

    def test_refusals_are_recorded_as_well_as_successes(self):
        ledger = sp.ProductionLedger(self.root / "script_production")
        ledger.record({"ok": True, "mode": "shadow", "road": sp.ROAD_SEGMENTED,
                       "lines": 4, "cost_seconds": 2.0,
                       "disagreement": {"lines": 4, "mean_abs_s": 0.02,
                                        "max_abs_s": 0.05,
                                        "head_delta_s": -0.01,
                                        "tail_delta_s": 0.03}})
        ledger.record({"ok": False, "mode": "shadow", "road": sp.ROAD_SEGMENTED,
                       "refusal_codes": ["cut_refused", "session_incomplete"],
                       "cost_seconds": 1.0})
        report = ledger.report()
        self.assertEqual(report["rounds"], 2)
        self.assertEqual(report["complete"], 1)
        self.assertEqual(report["refused"], 1)
        self.assertEqual(report["refusals"]["cut_refused"], 1)
        self.assertEqual(report["disagreement"]["rounds"], 1)
        self.assertEqual(report["cost_seconds"]["total"], 3.0)

    def test_a_torn_final_line_is_dropped_not_guessed(self):
        room = self.root / "script_production"
        ledger = sp.ProductionLedger(room)
        ledger.record({"ok": True, "mode": "shadow"})
        with (room / "rounds.jsonl").open("a", encoding="utf-8") as handle:
            handle.write('{"ok": true, "mode": "sha')
        self.assertEqual(len(ledger.rows()), 1)

    def test_it_is_bounded(self):
        ledger = sp.ProductionLedger(self.root / "script_production", keep=10)
        for index in range(320):
            ledger.record({"ok": True, "n": index})
        self.assertLessEqual(len(ledger.rows()), 220)

    def test_the_state_view_reads_without_running_anything(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("shadow")
        source, _ = fixture.source()
        producer.produce(source)
        got = sp.state(fixture.data)
        self.assertEqual(got["mode"], "shadow")
        self.assertEqual(got["road"], sp.ROAD_SEGMENTED)
        self.assertEqual(got["report"]["rounds"], 1)
        self.assertIn(sp.ROAD_CONTINUOUS, got["roads"])


# --------------------------------------------------------------------------
# pacing
# --------------------------------------------------------------------------

class PacingTests(TempCase):

    def test_due_respects_the_interval(self):
        now = [5000.0]
        fixture = Fixture(self.root)
        producer = sp.ScriptProducer(fixture.data, fixture.media,
                                     clock=lambda: now[0])
        producer.switch.write("shadow every=120")
        self.assertTrue(producer.due())
        producer._last_at = now[0]
        self.assertFalse(producer.due())
        now[0] += 121
        self.assertTrue(producer.due())

    def test_due_is_false_while_the_switch_is_off(self):
        fixture = Fixture(self.root)
        producer = fixture.producer("off")
        self.assertFalse(producer.due())


# --------------------------------------------------------------------------
# the mirror
# --------------------------------------------------------------------------

class MirrorTests(unittest.TestCase):
    """`estimated_windows` copies app.py's arithmetic. Drift must fail a test
    rather than a broadcast, so this reads app.py AS TEXT - it is never
    imported; importing it starts a radio station."""

    @classmethod
    def setUpClass(cls):
        target = ROOT / "app.py"
        if not target.is_file():
            raise unittest.SkipTest("no app.py beside this test")
        cls.text = target.read_text(encoding="utf-8", errors="replace")

    def test_the_constants_still_agree(self):
        for name, value in (("CONCAT_TAIL", sp.CONCAT_TAIL),
                            ("CONCAT_KEEP", sp.CONCAT_KEEP),
                            ("SEG_TRIM_DB", sp.SEG_TRIM_DB),
                            ("SEG_TRIM_LOOK", sp.SEG_TRIM_LOOK)):
            found = re.search(r"^%s = ([-0-9.]+)" % name, self.text, re.M)
            self.assertIsNotNone(found, name)
            self.assertAlmostEqual(float(found.group(1)), float(value), 6, name)

    def test_seg_real_seconds_still_reads_the_same(self):
        self.assertIn(
            "return max(0.05, float(measured) - max(0.0, float(tail) - CONCAT_KEEP)",
            self.text)
        self.assertIn(
            "return max(0.25, measured - CONCAT_TAIL + CONCAT_KEEP + max(0.0, beat))",
            self.text)

    def test_the_producer_hooks_still_exist_in_app_py(self):
        # The anchors the orchestrator patch is built on.
        for anchor in ("def _round_chunks(", "async def larder_prepare(",
                       "def reconcile_round_takes(",
                       "async def _speak_turns_floorless("):
            self.assertEqual(self.text.count(anchor), 1, anchor)

    def test_admit_round_is_rebound_not_edited(self):
        """`admission_admit_round` is DEFINED TWICE ON PURPOSE.

        The gate's own patch owns the first one; the production glue rebinds
        it by name so the burst road's single call site carries the frozen
        references without that patch's text being touched (and without
        breaking its revert). Two definitions is the contract, not a
        duplicate - but the second one must be the rebind, and it must still
        fall through to the first."""
        self.assertEqual(self.text.count("def admission_admit_round("), 2)
        self.assertIn('if "admission_admit_round" in globals():', self.text)
        self.assertIn("_admission_admit_round_before_production = "
                      "admission_admit_round", self.text)
        self.assertIn("return _admission_admit_round_before_production(",
                      self.text)


# --------------------------------------------------------------------------
# isolation
# --------------------------------------------------------------------------

class LiveStoreIsolationTests(unittest.TestCase):

    def test_this_module_names_no_live_store(self):
        text = (ROOT / "script_production.py").read_text(encoding="utf-8")
        for forbidden in ("import" + " app", "script" + "_ledger",
                          "pine" + "_requests", "air" + "_log.jsonl"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_this_test_names_no_live_store(self):
        text = Path(__file__).read_text(encoding="utf-8")
        # built rather than written, so this test does not fail on itself
        forbidden = ["import" + " app", "script" + "_ledger",
                     "data" + "/larder.json"]
        for name in forbidden:
            self.assertEqual(text.count(name), 0, name)

    def test_the_store_root_is_always_under_the_given_data_root(self):
        with tempfile.TemporaryDirectory() as room:
            producer = sp.ScriptProducer(Path(room) / "data",
                                         Path(room) / "media")
            self.assertTrue(str(producer.store.root).startswith(room))
            self.assertTrue(str(producer.root).startswith(room))
            self.assertTrue(str(producer.ledger.path).startswith(room))


if __name__ == "__main__":
    unittest.main()
