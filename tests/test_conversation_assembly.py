"""Assembly and cue map (boundary 3 of the speaker-recording note).

Every fixture here is synthesised into a fresh temporary directory and
removed again.  Nothing touches `data/`, and in particular nothing touches
the script ledger: the 2026-09-14 audit records that existing fixtures have
appended rows to the live document, and no test in this file imports
`app.py` or any module that writes one.

The audio fixtures are pure tones — one distinct frequency per occurrence —
so a cue position can be checked ACOUSTICALLY rather than merely
arithmetically.  `dominant_hz` reads the tone back out of the finished mix
at the position the cue map claims.  A cue map that is internally
consistent but describes the wrong audio fails these tests.
"""
from __future__ import annotations

import array
import hashlib
import io
import math
import os
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path

import conversation_assembly as ca
from conversation_assembly import (
    Assembly,
    AssemblyRefused,
    Extra,
    assemble_conversation,
    cue_at,
    cue_map_json,
    frozen_script,
    materialize_strips,
    stream_windows,
    verify_assembly,
)

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# Fixture audio
# --------------------------------------------------------------------------

def tone(hz: float, seconds: float, rate: int, level: int = 9000) -> list[int]:
    return [int(level * math.sin(2 * math.pi * hz * i / rate))
            for i in range(int(rate * seconds))]


def silence(seconds: float, rate: int) -> list[int]:
    return [0] * int(rate * seconds)


def write_wav(path: Path, samples: list[int], rate: int,
              channels: int = 1) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def read_wav(blob: bytes) -> tuple[array.array, int]:
    with wave.open(io.BytesIO(blob), "rb") as reader:
        rate = reader.getframerate()
        buf = array.array("h")
        buf.frombytes(reader.readframes(reader.getnframes()))
    return buf, rate


def dominant_hz(buf: array.array, start: int, end: int, rate: int) -> float:
    """The frequency of a pure tone, by zero crossings.

    Deliberately crude: it only has to tell 200 Hz from 400 Hz from 700 Hz,
    and it is immune to the gain changes `loudnorm` and `alimiter` apply.
    """
    window = buf[max(0, start):min(len(buf), end)]
    if len(window) < 64:
        return 0.0
    crossings = 0
    for i in range(1, len(window)):
        if (window[i - 1] < 0) != (window[i] < 0):
            crossings += 1
    return crossings * rate / (2.0 * len(window))


class Booth:
    """A performer's continuous master take, and where its lines sit in it.

    One master per actor, recorded in that ACTOR'S order — which is not the
    script's order.  That is the whole point of the first test.
    """

    def __init__(self, root: Path, rate: int = 24000):
        self.root = root
        self.rate = rate
        self.masters: list[dict] = []
        self.cuts: list[dict] = []

    def record(self, take_id: str, actor: str,
               lines: list[tuple[str, int, float, float]]) -> None:
        """`lines` is [(occurrence_id, ordinal, hz, seconds), ...]."""
        samples: list[int] = []
        samples += silence(0.25, self.rate)         # the actor settling
        cuts = []
        for occurrence_id, ordinal, hz, seconds in lines:
            start = len(samples)
            samples += tone(hz, seconds, self.rate)
            samples += silence(0.40, self.rate)     # the pause before the next
            cuts.append((occurrence_id, ordinal, start, len(samples)))
        samples += silence(0.30, self.rate)
        path = self.root / f"{take_id}.wav"
        write_wav(path, samples, self.rate)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.masters.append({
            "take_id": take_id, "actor": actor, "audio_hash": digest,
            "sample_rate": self.rate, "frames": len(samples),
            "path": str(path),
        })
        for occurrence_id, ordinal, start, end in cuts:
            self.cuts.append({
                "occurrence_id": occurrence_id, "ordinal": ordinal,
                "master_hash": digest, "start_sample": start,
                "end_sample": end, "boundary_method": "fixture",
                "verified": True,
            })


class AssemblyTestCase(unittest.TestCase):
    """Base: a temp directory per test, and nothing outside it."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="assembly-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # The station's own default, so the arithmetic in these tests is the
        # arithmetic the station does.  Restored afterwards.
        self._old_tail = os.environ.get("BOX_TAIL_MS")
        os.environ["BOX_TAIL_MS"] = "900"
        self.addCleanup(self._restore_tail)

    def _restore_tail(self) -> None:
        if self._old_tail is None:
            os.environ.pop("BOX_TAIL_MS", None)
        else:
            os.environ["BOX_TAIL_MS"] = self._old_tail

    def four_line_exchange(self, rate: int = 24000) -> tuple[dict, Booth]:
        """The note's own example, recorded the note's own way.

        "In a four-line exchange, actor A can record lines 1 and 3, and
        actor B lines 2 and 4; assembly must produce 1, 2, 3, 4."

        Actor B's master is created FIRST and appears first in every list,
        so nothing here can pass by accident of container order.
        """
        booth = Booth(self.tmp, rate)
        booth.record("take-B", "cohost", [("occ-2", 1, 400.0, 0.50),
                                          ("occ-4", 3, 1100.0, 0.50)])
        booth.record("take-A", "dj", [("occ-1", 0, 200.0, 0.50),
                                      ("occ-3", 2, 700.0, 0.50)])
        script = {
            "revision": "rev-4line",
            "occurrences": [
                {"occurrence_id": "occ-1", "ordinal": 0, "speaker": "dj",
                 "text": "good evening"},
                {"occurrence_id": "occ-2", "ordinal": 1, "speaker": "cohost",
                 "text": "good evening"},
                {"occurrence_id": "occ-3", "ordinal": 2, "speaker": "dj",
                 "text": "shall we"},
                {"occurrence_id": "occ-4", "ordinal": 3, "speaker": "cohost",
                 "text": "we shall"},
            ],
        }
        return script, booth

    def assemble(self, script, booth, **kw) -> Assembly:
        kw.setdefault("beats", [0.12, 0.12, 0.12, 0.0])
        kw.setdefault("assembly_id", "asm-test")
        return assemble_conversation(script, booth.masters, booth.cuts, **kw)


# ==========================================================================


class OrderTests(AssemblyTestCase):

    def test_out_of_order_recording_is_assembled_in_script_order(self):
        """Actor A records 1 and 3, actor B records 2 and 4 -> 1, 2, 3, 4."""
        script, booth = self.four_line_exchange()
        # The cuts are handed over in completion order, which is neither
        # script order nor even a stable one.
        booth.cuts = [booth.cuts[i] for i in (3, 0, 2, 1)]
        self.assertEqual([c["occurrence_id"] for c in booth.cuts],
                         ["occ-3", "occ-2", "occ-1", "occ-4"])
        with self.assemble(script, booth) as assembly:
            cue_map = assembly.cue_map
            self.assertEqual(cue_map["sequence"],
                             ["occ-1", "occ-2", "occ-3", "occ-4"])
            # …and the AUDIO is in that order too, not merely the bookkeeping.
            buf, rate = read_wav(assembly.audio)
            for cue, expected in zip(cue_map["cues"],
                                     [200.0, 400.0, 700.0, 1100.0]):
                start = cue["start_sample"]
                end = cue["speech_end_sample"]
                mid = start + (end - start) // 4
                heard = dominant_hz(buf, mid, mid + (end - start) // 2, rate)
                self.assertAlmostEqual(
                    heard, expected, delta=expected * 0.06,
                    msg=f"{cue['occurrence_id']} sounds like {heard:.0f} Hz, "
                        f"not {expected:.0f} Hz")

    def test_filesystem_order_and_session_order_change_nothing(self):
        """The same script, four different input orderings, one cue map."""
        script, booth = self.four_line_exchange()
        masters, cuts = list(booth.masters), list(booth.cuts)
        seen = set()
        for rotation in range(4):
            booth.masters = masters[rotation % 2:] + masters[:rotation % 2]
            booth.cuts = cuts[rotation:] + cuts[:rotation]
            with self.assemble(script, booth) as assembly:
                seen.add(tuple(assembly.cue_map["sequence"]))
                seen.add(tuple((c["start_sample"], c["cue_end_sample"])
                               for c in assembly.cue_map["cues"]))
        # Two entries only: the one sequence and the one timeline.
        self.assertEqual(len(seen), 2)
        self.assertIn(("occ-1", "occ-2", "occ-3", "occ-4"), seen)

    def test_cue_sequence_is_proved_equal_to_the_frozen_script_sequence(self):
        script, booth = self.four_line_exchange()
        with self.assemble(script, booth) as assembly:
            frozen = frozen_script(script)
            verdict = verify_assembly(assembly, frozen)
            self.assertTrue(verdict["ok"], verdict["failures"])
            self.assertTrue(
                verdict["checks"]["cue_sequence_equals_script"]["ok"])
            self.assertTrue(
                verdict["checks"]["one_cue_per_occurrence"]["ok"])
            self.assertTrue(verdict["checks"]["ordinals_ascending"]["ok"])
            self.assertEqual(assembly.cue_map["sequence"],
                             list(frozen.ids()))

    def test_a_cue_map_that_is_reordered_after_the_fact_fails_verification(self):
        """The check is a check, not a formality."""
        script, booth = self.four_line_exchange()
        with self.assemble(script, booth) as assembly:
            cues = assembly.cue_map["cues"]
            cues[1], cues[2] = cues[2], cues[1]
            verdict = verify_assembly(assembly, script)
            self.assertFalse(verdict["ok"])
            self.assertFalse(
                verdict["checks"]["cue_sequence_equals_script"]["ok"])


class IdenticalWordsTests(AssemblyTestCase):

    def test_two_occurrences_of_identical_words_land_at_different_positions(self):
        """"including two occurrences with identical words".

        The pantry key hashes engine, voice and text (app.py:13618) and so
        cannot tell these two apart.  The occurrence id can, and the two
        performances are genuinely different audio.
        """
        booth = Booth(self.tmp)
        booth.record("take-A", "dj", [
            ("occ-1", 0, 200.0, 0.50),
            ("occ-2", 1, 900.0, 0.50),      # "that's the one" — first time
            ("occ-3", 2, 400.0, 0.50),
            ("occ-4", 3, 1500.0, 0.50),     # "that's the one" — second time
        ])
        script = {
            "revision": "rev-echo",
            "occurrences": [
                {"occurrence_id": "occ-1", "ordinal": 0, "speaker": "dj",
                 "text": "listen to this"},
                {"occurrence_id": "occ-2", "ordinal": 1, "speaker": "dj",
                 "text": "that's the one"},
                {"occurrence_id": "occ-3", "ordinal": 2, "speaker": "dj",
                 "text": "and again"},
                {"occurrence_id": "occ-4", "ordinal": 3, "speaker": "dj",
                 "text": "that's the one"},
            ],
        }
        with self.assemble(script, booth) as assembly:
            cues = {c["occurrence_id"]: c for c in assembly.cue_map["cues"]}
            first, second = cues["occ-2"], cues["occ-4"]
            self.assertEqual(first["text"], second["text"])
            self.assertNotEqual(first["start_sample"],
                                second["start_sample"])
            self.assertLess(first["cue_end_sample"], second["start_sample"])
            # Different source cuts, so different performances — not one
            # cached clip served twice.
            self.assertNotEqual(first["source"]["start_sample"],
                                second["source"]["start_sample"])
            buf, rate = read_wav(assembly.audio)
            for cue, hz in ((first, 900.0), (second, 1500.0)):
                span = cue["speech_end_sample"] - cue["start_sample"]
                mid = cue["start_sample"] + span // 4
                self.assertAlmostEqual(
                    dominant_hz(buf, mid, mid + span // 2, rate), hz,
                    delta=hz * 0.06)


class PauseTests(AssemblyTestCase):

    def test_an_inserted_pause_does_not_start_the_next_line_early(self):
        """"Retain separate speech-end and cue-end positions so an inserted
        pause does not falsely start the next line."
        """
        script, booth = self.four_line_exchange()
        # Half a second of held silence after line 2 — a real beat, not a
        # seam tick.
        for cut in booth.cuts:
            if cut["occurrence_id"] == "occ-2":
                cut["pause_after"] = 0.5
        with self.assemble(script, booth) as assembly:
            cues = {c["occurrence_id"]: c for c in assembly.cue_map["cues"]}
            second, third = cues["occ-2"], cues["occ-3"]
            rate = assembly.cue_map["sample_rate"]
            self.assertEqual(second["pause_frames"], int(round(0.5 * rate)))
            # The pause sits BETWEEN speech end and cue end…
            self.assertEqual(second["cue_end_sample"] - second["speech_end_sample"],
                             second["pause_frames"])
            # …and the next line begins at the cue end, not the speech end.
            self.assertEqual(third["start_sample"], second["cue_end_sample"])
            self.assertGreater(third["start_sample"], second["speech_end_sample"])
            # The pause really is silent in the finished audio.
            buf, _rate = read_wav(assembly.audio)
            gap = buf[second["speech_end_sample"] + 200:
                      second["cue_end_sample"] - 200]
            self.assertTrue(gap, "the pause has no frames")
            self.assertLess(max(abs(s) for s in gap), 800,
                            "the 'pause' is not silent")
            # And nothing is highlighted-as-next during it.
            mid = (second["speech_end_sample"] + second["cue_end_sample"]) // 2
            self.assertEqual(
                cue_at(assembly.cue_map, mid / rate)["occurrence_id"], "occ-2")

    def test_a_longer_pause_moves_every_later_cue_by_exactly_its_length(self):
        script, booth = self.four_line_exchange()
        base_cuts = [dict(c) for c in booth.cuts]
        with self.assemble(script, booth, beats=[0.1, 0.1, 0.1, 0.0]) as base:
            before = {c["occurrence_id"]: c["start_sample"]
                      for c in base.cue_map["cues"]}
        booth.cuts = [dict(c) for c in base_cuts]
        for cut in booth.cuts:
            if cut["occurrence_id"] == "occ-2":
                cut["pause_after"] = 0.6
        with self.assemble(script, booth, beats=[0.1, 0.1, 0.1, 0.0]) as after:
            moved = {c["occurrence_id"]: c["start_sample"]
                     for c in after.cue_map["cues"]}
        rate = 24000
        shift = int(round(0.6 * rate)) - int(round(0.1 * rate))
        self.assertEqual(moved["occ-1"], before["occ-1"])
        self.assertEqual(moved["occ-2"], before["occ-2"])
        self.assertEqual(moved["occ-3"], before["occ-3"] + shift)
        self.assertEqual(moved["occ-4"], before["occ-4"] + shift)

    def test_a_negative_pause_is_refused_as_an_undeclared_overlap(self):
        script, booth = self.four_line_exchange()
        for cut in booth.cuts:
            if cut["occurrence_id"] == "occ-2":
                cut["pause_after"] = -0.2
        with self.assertRaises(AssemblyRefused) as caught:
            self.assemble(script, booth)
        self.assertEqual(caught.exception.reason, "overlap_requested")

    def test_overlap_mode_is_refused_rather_than_silently_sequential(self):
        script, booth = self.four_line_exchange()
        with self.assertRaises(AssemblyRefused) as caught:
            self.assemble(script, booth, mode="overlap")
        self.assertEqual(caught.exception.reason, "unsupported_mode")


class EffectTests(AssemblyTestCase):

    def test_a_duration_changing_effect_moves_every_later_cue(self):
        """"Duration-changing effects require updated cue positions."

        `atempo=0.5` makes line 2 twice as long.  Lines 1 and 2 keep their
        starts; 3 and 4 move by the full amount line 2 grew — measured, not
        assumed, because the strip is re-measured after the effect runs.
        """
        script, booth = self.four_line_exchange()
        base_cuts = [dict(c) for c in booth.cuts]
        beats = [0.1, 0.1, 0.1, 0.0]
        with self.assemble(script, booth, beats=beats) as base:
            plain = {c["occurrence_id"]: c for c in base.cue_map["cues"]}
        booth.cuts = [dict(c) for c in base_cuts]
        for cut in booth.cuts:
            if cut["occurrence_id"] == "occ-2":
                cut["effects"] = ["atempo=0.5"]
        with self.assemble(script, booth, beats=beats) as slowed:
            moved = {c["occurrence_id"]: c for c in slowed.cue_map["cues"]}

        grew = ((moved["occ-2"]["speech_end_sample"]
                 - moved["occ-2"]["start_sample"])
                - (plain["occ-2"]["speech_end_sample"]
                   - plain["occ-2"]["start_sample"]))
        self.assertGreater(grew, 4000, "atempo=0.5 did not lengthen the line")
        self.assertEqual(moved["occ-1"]["start_sample"],
                         plain["occ-1"]["start_sample"])
        self.assertEqual(moved["occ-2"]["start_sample"],
                         plain["occ-2"]["start_sample"])
        for later in ("occ-3", "occ-4"):
            self.assertEqual(moved[later]["start_sample"],
                             plain[later]["start_sample"] + grew,
                             f"{later} did not move by the full growth")
        # The whole file grew by the same amount, and the cue map says so.
        self.assertEqual(slowed.cue_map["body_frames"],
                         base.cue_map["body_frames"] + grew)
        self.assertEqual(moved["occ-2"]["source"]["effects"], ["atempo=0.5"])

        # And the SOUND is still in the right place. `atempo` stretches
        # time without moving pitch, so the line still reads as its own
        # 400 Hz — for twice as long, at the position the cue map gives.
        buf, rate = read_wav(slowed.audio)
        cue = moved["occ-2"]
        span = cue["speech_end_sample"] - cue["start_sample"]
        mid = cue["start_sample"] + span // 4
        self.assertAlmostEqual(dominant_hz(buf, mid, mid + span // 2, rate),
                               400.0, delta=25.0)
        # the line that follows it is the next one, not a smear of this one
        later = moved["occ-3"]
        span3 = later["speech_end_sample"] - later["start_sample"]
        mid3 = later["start_sample"] + span3 // 4
        self.assertAlmostEqual(dominant_hz(buf, mid3, mid3 + span3 // 2,
                                           rate), 700.0, delta=45.0)


class ResamplingTests(AssemblyTestCase):

    def test_a_master_at_another_rate_is_resampled_and_measured_not_assumed(self):
        """"including resampling".

        The master is 48 kHz.  Its cut offsets are 48 kHz sample positions
        and are NOT final mix offsets; the final cue positions are 24 kHz
        samples measured off audio that was actually resampled.
        """
        script, booth = self.four_line_exchange(rate=48000)
        with self.assemble(script, booth) as assembly:
            cue_map = assembly.cue_map
            self.assertEqual(cue_map["sample_rate"], 24000)
            for cue in cue_map["cues"]:
                self.assertEqual(cue["source"]["master_sample_rate"], 48000)
                self.assertTrue(cue["source"]["resampled"])
                # THE POINT: the source offset is not the mix offset.
                self.assertNotEqual(cue["source"]["start_sample"],
                                    cue["start_sample"])
            self.assertTrue(verify_assembly(assembly, script)["ok"])
            buf, rate = read_wav(assembly.audio)
            for cue, hz in zip(cue_map["cues"],
                               [200.0, 400.0, 700.0, 1100.0]):
                span = cue["speech_end_sample"] - cue["start_sample"]
                mid = cue["start_sample"] + span // 4
                self.assertAlmostEqual(
                    dominant_hz(buf, mid, mid + span // 2, rate), hz,
                    delta=hz * 0.06)

    def test_two_actors_at_different_rates_share_one_timeline(self):
        booth = Booth(self.tmp, 24000)
        booth.record("take-A", "dj", [("occ-1", 0, 200.0, 0.5),
                                      ("occ-3", 2, 700.0, 0.5)])
        wide = Booth(self.tmp, 44100)
        wide.record("take-B", "cohost", [("occ-2", 1, 400.0, 0.5),
                                         ("occ-4", 3, 1100.0, 0.5)])
        booth.masters += wide.masters
        booth.cuts += wide.cuts
        script = {"revision": "rev-mixed", "occurrences": [
            {"occurrence_id": f"occ-{n}", "ordinal": n - 1,
             "speaker": "dj" if n % 2 else "cohost", "text": f"line {n}"}
            for n in (1, 2, 3, 4)]}
        with self.assemble(script, booth) as assembly:
            self.assertTrue(verify_assembly(assembly, script)["ok"])
            rates = [c["source"]["master_sample_rate"]
                     for c in assembly.cue_map["cues"]]
            self.assertEqual(rates, [24000, 44100, 24000, 44100])
            self.assertEqual(assembly.cue_map["sequence"],
                             ["occ-1", "occ-2", "occ-3", "occ-4"])


class RefusalTests(AssemblyTestCase):

    def test_a_missing_cut_is_refused_rather_than_assembled(self):
        """"No incomplete conversation may be admitted."""
        script, booth = self.four_line_exchange()
        booth.cuts = [c for c in booth.cuts if c["occurrence_id"] != "occ-3"]
        with self.assertRaises(AssemblyRefused) as caught:
            self.assemble(script, booth)
        self.assertEqual(caught.exception.reason, "missing_cut")
        self.assertIn("occ-3", caught.exception.facts["occurrences"])

    def test_an_unverified_cut_is_refused(self):
        script, booth = self.four_line_exchange()
        for cut in booth.cuts:
            if cut["occurrence_id"] == "occ-2":
                cut["verified"] = False
        with self.assertRaises(AssemblyRefused) as caught:
            self.assemble(script, booth)
        self.assertEqual(caught.exception.reason, "unverified_cut")

    def test_a_string_verdict_that_is_not_an_acceptance_is_refused(self):
        script, booth = self.four_line_exchange()
        for cut in booth.cuts:
            if cut["occurrence_id"] == "occ-2":
                cut.pop("verified")
                cut["verification"] = {"ok": False, "why": "repeated speech"}
        with self.assertRaises(AssemblyRefused) as caught:
            self.assemble(script, booth)
        self.assertEqual(caught.exception.reason, "unverified_cut")

    def test_two_cuts_for_one_occurrence_are_refused(self):
        script, booth = self.four_line_exchange()
        booth.cuts.append(dict(booth.cuts[0]))
        with self.assertRaises(AssemblyRefused) as caught:
            self.assemble(script, booth)
        self.assertEqual(caught.exception.reason, "duplicate_cut")

    def test_a_cut_for_an_occurrence_outside_the_revision_is_refused(self):
        script, booth = self.four_line_exchange()
        stray = dict(booth.cuts[0])
        stray["occurrence_id"] = "occ-9"
        booth.cuts.append(stray)
        with self.assertRaises(AssemblyRefused) as caught:
            self.assemble(script, booth)
        self.assertEqual(caught.exception.reason, "cut_outside_script")

    def test_a_corrupt_master_is_refused(self):
        """A master whose bytes changed is no longer the one cut against."""
        script, booth = self.four_line_exchange()
        target = Path(booth.masters[0]["path"])
        blob = bytearray(target.read_bytes())
        blob[-2000:] = b"\x11\x22" * 1000          # tamper with the audio
        target.write_bytes(bytes(blob))
        with self.assertRaises(AssemblyRefused) as caught:
            self.assemble(script, booth)
        self.assertEqual(caught.exception.reason, "master_changed")

    def test_a_master_that_is_not_readable_audio_is_refused(self):
        script, booth = self.four_line_exchange()
        target = Path(booth.masters[0]["path"])
        was = booth.masters[0]["audio_hash"]
        target.write_bytes(b"this is not a wav file, it is a note")
        now = hashlib.sha256(target.read_bytes()).hexdigest()
        # The store's recorded hash agrees with the bytes on disk. The bytes
        # are still not audio, and no offset can be taken against them.
        booth.masters[0]["audio_hash"] = now
        booth.masters[0]["frames"] = 0
        for cut in booth.cuts:
            if cut["master_hash"] == was:
                cut["master_hash"] = now
        with self.assertRaises(AssemblyRefused) as caught:
            self.assemble(script, booth)
        self.assertEqual(caught.exception.reason, "unreadable_master")

    def test_a_master_that_lost_frames_is_refused(self):
        script, booth = self.four_line_exchange()
        booth.masters[0]["frames"] += 5000         # the ledger says longer
        with self.assertRaises(AssemblyRefused) as caught:
            self.assemble(script, booth)
        self.assertEqual(caught.exception.reason, "master_frames_mismatch")

    def test_a_missing_master_file_is_refused(self):
        script, booth = self.four_line_exchange()
        Path(booth.masters[0]["path"]).unlink()
        with self.assertRaises(AssemblyRefused) as caught:
            self.assemble(script, booth)
        self.assertEqual(caught.exception.reason, "master_missing")

    def test_a_cut_past_the_end_of_its_master_is_refused(self):
        script, booth = self.four_line_exchange()
        booth.cuts[0]["end_sample"] = 10 ** 9
        with self.assertRaises(AssemblyRefused) as caught:
            self.assemble(script, booth)
        self.assertEqual(caught.exception.reason, "cut_out_of_bounds")

    def test_a_cut_whose_ordinal_contradicts_the_script_is_refused(self):
        script, booth = self.four_line_exchange()
        for cut in booth.cuts:
            if cut["occurrence_id"] == "occ-3":
                cut["ordinal"] = 0
        with self.assertRaises(AssemblyRefused) as caught:
            self.assemble(script, booth)
        self.assertEqual(caught.exception.reason, "ordinal_disagreement")

    def test_a_script_without_occurrence_ids_is_refused(self):
        with self.assertRaises(AssemblyRefused) as caught:
            frozen_script({"revision": "r", "occurrences": [
                {"ordinal": 0, "speaker": "dj", "text": "hello"}]})
        self.assertEqual(caught.exception.reason, "no_occurrence_id")

    def test_a_script_without_a_revision_is_refused(self):
        with self.assertRaises(AssemblyRefused) as caught:
            frozen_script({"occurrences": [{"occurrence_id": "a",
                                            "ordinal": 0}]})
        self.assertEqual(caught.exception.reason, "no_revision")

    def test_refusal_leaves_no_temporary_directory_behind(self):
        script, booth = self.four_line_exchange()
        booth.cuts[0]["end_sample"] = 10 ** 9
        before = set(Path(tempfile.gettempdir()).glob("assembly-*"))
        with self.assertRaises(AssemblyRefused):
            self.assemble(script, booth)
        after = set(Path(tempfile.gettempdir()).glob("assembly-*"))
        self.assertEqual(after - before, set())


class FinalArtifactTests(AssemblyTestCase):

    def test_the_finished_artifact_is_verified_before_it_is_advertised(self):
        script, booth = self.four_line_exchange()
        with self.assemble(script, booth) as assembly:
            cue_map = assembly.cue_map
            self.assertIn("verified", cue_map)
            self.assertTrue(cue_map["verified"]["ok"])
            # hash
            self.assertEqual(
                hashlib.sha256(assembly.audio).hexdigest(),
                cue_map["final_audio_hash"])
            # frame count
            buf, rate = read_wav(assembly.audio)
            self.assertEqual(len(buf), cue_map["frame_count"])
            self.assertEqual(rate, 24000)
            # exactly one cue per required occurrence, in the frozen order
            self.assertEqual(cue_map["sequence"], ["occ-1", "occ-2",
                                                   "occ-3", "occ-4"])

    def test_a_tampered_hash_or_frame_count_fails_verification(self):
        script, booth = self.four_line_exchange()
        with self.assemble(script, booth) as assembly:
            good = dict(assembly.cue_map)
            assembly.cue_map = dict(good, final_audio_hash="0" * 64)
            verdict = verify_assembly(assembly, script)
            self.assertFalse(verdict["ok"])
            self.assertFalse(verdict["checks"]["final_audio_hash"]["ok"])
            assembly.cue_map = dict(good, frame_count=good["frame_count"] + 1)
            verdict = verify_assembly(assembly, script)
            self.assertFalse(verdict["ok"])
            self.assertFalse(verdict["checks"]["frame_count"]["ok"])

    def test_the_cue_timeline_accounts_for_every_frame_of_the_file(self):
        """Contiguous cues, nothing overlapping, and a tail that is the box
        pad plus the measured loudness residual — no unexplained frames."""
        script, booth = self.four_line_exchange()
        with self.assemble(script, booth) as assembly:
            cue_map = assembly.cue_map
            cues = cue_map["cues"]
            self.assertEqual(cues[0]["start_sample"],
                             cue_map["mix_latency_frames"])
            for earlier, later in zip(cues, cues[1:]):
                self.assertEqual(later["start_sample"],
                                 earlier["cue_end_sample"])
            body = sum(c["cue_end_sample"] - c["start_sample"] for c in cues)
            self.assertEqual(body, cue_map["body_frames"])
            self.assertLessEqual(abs(cue_map["mix_residual_frames"]),
                                 ca.MIX_RESIDUAL_TOLERANCE_FRAMES)
            self.assertEqual(cue_map["tail_pad_frames"], int(24000 * 0.9))

    def test_the_cue_map_is_json_durable(self):
        script, booth = self.four_line_exchange()
        with self.assemble(script, booth) as assembly:
            import json
            text = cue_map_json(assembly.cue_map)
            self.assertEqual(json.loads(text)["sequence"],
                             assembly.cue_map["sequence"])
            self.assertEqual(json.loads(cue_map_json(assembly.record
                                                     ))["assembly_id"],
                             "asm-test")

    def test_strips_are_released_by_default_and_materialized_on_request(self):
        """"Store the master plus cut offsets; materialize individual strip
        files only when an adapter or editor needs them."""
        script, booth = self.four_line_exchange()
        assembly = self.assemble(script, booth)
        self.assertEqual(assembly.strips, {})
        self.assertEqual(
            [c["start_sample"] for c in assembly.record["cuts"]],
            [next(x["start_sample"] for x in booth.cuts
                  if x["occurrence_id"] == c["occurrence_id"])
             for c in assembly.record["cuts"]])
        with self.assertRaises(AssemblyRefused):
            materialize_strips(assembly, self.tmp / "out")
        with self.assemble(script, booth, keep_strips=True) as kept:
            made = materialize_strips(kept, self.tmp / "out")
            self.assertEqual(len(made), 4)
            for path in made.values():
                self.assertTrue(path.is_file())


class ExtraSegmentTests(AssemblyTestCase):

    def test_a_sting_before_the_first_line_moves_every_line_and_gets_a_cue(self):
        """app.py welds a ring at the head of a call; every turn after it
        starts later.  The old road anchored that arithmetic on the ring's
        length ON DISK; here the ring is measured like everything else."""
        script, booth = self.four_line_exchange()
        ring = self.tmp / "ring.wav"
        write_wav(ring, tone(1300.0, 0.7, 24000) + silence(0.9, 24000), 24000)
        # One beat per segment, and the same beat for the same line in
        # both runs - #778's rule, that the timeline and the audio are built
        # out of the same numbers.
        with self.assemble(script, booth,
                           beats=[0.12, 0.12, 0.12, 0.0]) as plain:
            bare = {c["occurrence_id"]: c["start_sample"]
                    for c in plain.cue_map["cues"]}
        with self.assemble(script, booth,
                           beats=[0.12, 0.12, 0.12, 0.12, 0.0],
                           extras=[
                Extra(extra_id="ring-1", path=ring, kind="sfx",
                      label="the phone ringing")]) as assembly:
            cues = assembly.cue_map["cues"]
            self.assertEqual(cues[0]["occurrence_id"], "ring-1")
            self.assertEqual(cues[0]["kind"], "sfx")
            self.assertEqual(assembly.cue_map["sequence"],
                             ["occ-1", "occ-2", "occ-3", "occ-4"])
            lead = cues[0]["cue_end_sample"] - cues[0]["start_sample"]
            after = {c["occurrence_id"]: c["start_sample"] for c in cues}
            for occurrence in ("occ-1", "occ-2", "occ-3", "occ-4"):
                self.assertEqual(after[occurrence],
                                 bare[occurrence] + lead)
            self.assertTrue(verify_assembly(assembly, script)["ok"])


class IntegratorSurfaceTests(AssemblyTestCase):

    def test_stream_windows_match_the_shape_app_py_already_uses(self):
        script, booth = self.four_line_exchange()
        with self.assemble(script, booth) as assembly:
            windows = stream_windows(assembly.cue_map)
            self.assertEqual([w["id"] for w in windows],
                             ["occ-1", "occ-2", "occ-3", "occ-4"])
            for window in windows:
                self.assertEqual(set(window),
                                 {"id", "ordinal", "kind", "who", "from",
                                  "until", "speech_until", "tail", "exact"})
                self.assertLessEqual(window["from"], window["speech_until"])
                self.assertLessEqual(window["speech_until"], window["until"])
            # contiguous, like `rows` in app.py
            for earlier, later in zip(windows, windows[1:]):
                self.assertAlmostEqual(earlier["until"], later["from"],
                                       places=5)
            # the seam beat is inside the window and offered separately, so
            # a download can leave it off
            self.assertAlmostEqual(
                windows[0]["until"] - windows[0]["speech_until"],
                windows[0]["tail"], places=5)
            self.assertEqual(windows[-1]["tail"], 0.0)

    def test_cue_at_answers_with_the_occurrence_that_is_sounding(self):
        script, booth = self.four_line_exchange()
        with self.assemble(script, booth) as assembly:
            cue_map = assembly.cue_map
            for cue in cue_map["cues"]:
                middle = ((cue["start_sample"] + cue["speech_end_sample"])
                          / 2.0 / cue_map["sample_rate"])
                self.assertEqual(cue_at(cue_map, middle)["occurrence_id"],
                                 cue["occurrence_id"])
            self.assertIsNone(cue_at(cue_map, cue_map["seconds"] - 0.01))

    def test_the_rescale_this_replaces_would_not_have_produced_these_cues(self):
        """The old road's arithmetic, run over the same round, differs.

        This is not a claim that the old numbers were useless — they were
        close.  It is the evidence that they were ESTIMATES: the same
        inputs, through app.py's `concat_real_seconds` + `_made / _ours`
        rescale, land somewhere other than the measured truth.
        """
        script, booth = self.four_line_exchange()
        with self.assemble(script, booth, beats=[0.12, 0.12, 0.12, 0.0]
                           ) as assembly:
            cue_map = assembly.cue_map
            rate = cue_map["sample_rate"]
            # app.py's estimate: each clip measured ON DISK, minus the
            # assumed 0.9 welded tail, plus CONCAT_KEEP, plus the beat.
            beats = [0.12, 0.12, 0.12, 0.0]
            measured = []
            for cut in sorted(booth.cuts, key=lambda c: c["ordinal"]):
                measured.append((cut["end_sample"] - cut["start_sample"])
                                / 24000.0)
            estimated, offset = [], 0.0
            for seconds, beat in zip(measured, beats):
                real = max(0.25, seconds - 0.9 + ca.CONCAT_KEEP + beat)
                estimated.append((offset, offset + real))
                offset += real
            made = (cue_map["frame_count"] / rate) - 0.9   # less the box pad
            scale = made / offset if offset > 0.5 else 1.0
            rescaled = [(a * scale, b * scale) for a, b in estimated]
            exact = [(c["start_seconds"], c["cue_end_seconds"])
                     for c in cue_map["cues"]]
            drift = max(abs(r[0] - e[0]) for r, e in zip(rescaled, exact))
            self.assertGreater(
                drift, 0.01,
                "the rescale and the measurement agreed exactly, which would "
                "mean this test is no longer exercising the difference")


class MirrorTests(unittest.TestCase):
    """The mixer here must not drift from the mixer in app.py.

    Reading app.py as TEXT — never importing it, which would start a radio
    station and write to `data/`.
    """

    @classmethod
    def setUpClass(cls) -> None:
        path = REPO / "app.py"
        if not path.is_file():
            raise unittest.SkipTest("app.py is not beside this checkout")
        cls.source = path.read_text(encoding="utf-8", errors="replace")

    def test_the_mixer_constants_still_equal_app_pys(self):
        for literal in (f"CONCAT_KEEP = {ca.CONCAT_KEEP}",
                        f"CONCAT_BEAT = {ca.CONCAT_BEAT}",
                        f"SEG_TRIM_DB = {ca.SEG_TRIM_DB}"):
            self.assertIn(literal, self.source,
                          f"app.py no longer says `{literal}`; the assembler "
                          "and the mixer have drifted apart")
        self.assertIn('int(os.getenv("BOX_TAIL_MS", "900"))', self.source)

    def test_the_filter_graph_still_matches_app_pys(self):
        for fragment in (ca.LOUDNORM, ca.LIMITER,
                         "aformat=sample_fmts=s16:channel_layouts=mono",
                         "areverse,silenceremove=start_periods=1:",
                         "anoisesrc=color=brown:amplitude=0.04,"
                         "highpass=f=1500,"):
            self.assertIn(fragment, self.source,
                          f"app.py's mixer no longer contains {fragment!r}")

    def test_the_refusal_threshold_still_matches_app_pys(self):
        self.assertIn("if len(blob) <= 4000:", self.source)
        self.assertEqual(ca.MIN_MIX_BYTES, 4000)

    def test_this_module_generates_the_legs_app_py_generates(self):
        """Build the leg text both ways and compare, for one input."""
        beat = 0.123
        mine = ca._leg(2, beat, (), pad=True)
        theirs = (f"[{2}:a]aresample=24000,"
                  "aformat=sample_fmts=s16:channel_layouts=mono,"
                  "areverse,silenceremove=start_periods=1:"
                  f"start_silence={ca.CONCAT_KEEP}:start_threshold=-50dB,"
                  f"areverse,apad=pad_dur={beat}")
        self.assertEqual(mine, theirs)


class PeerModuleReconciliationTests(AssemblyTestCase):
    """The four boundary-3 modules were written in parallel.  These drive
    the REAL records the others emit through this assembler, so a spelling
    that only ever agreed in a note fails here instead of on air."""

    def setUp(self) -> None:
        super().setUp()
        try:
            import script_manifest
        except ImportError:                       # pragma: no cover
            self.skipTest("script_manifest.py is not in this checkout")
        self.sm = script_manifest

    def real_records(self):
        """A frozen script, masters and cuts built by script_manifest."""
        script = self.sm.frozen_script(
            "conv-1",
            {"dj": {"voice": "dj-voice", "engine": "xtts"},
             "cohost": {"voice": "cohost-voice", "engine": "xtts"}},
            [{"actor": "dj", "text": "good evening"},
             {"actor": "cohost", "text": "good evening"},
             {"actor": "dj", "text": "shall we"},
             {"actor": "cohost", "text": "we shall"}])
        order = {row["actor"]: [] for row in script["lines"]}
        hz = {1: 200.0, 2: 400.0, 3: 700.0, 4: 1100.0}
        for row in script["lines"]:
            order[row["actor"]].append(
                (row["occurrence_id"], row["ordinal"], hz[row["ordinal"]], 0.5))
        booth = Booth(self.tmp)
        # cohost first, so nothing can pass by accident of order
        for actor in ("cohost", "dj"):
            booth.record("take-" + actor, actor, order[actor])

        masters, cuts = [], []
        for made in booth.masters:
            masters.append(self.sm.master_recording(
                made["take_id"], session_id="sess-" + made["actor"],
                revision=script["revision"], actor=made["actor"],
                audio_sha256="sha256:" + made["audio_hash"],
                sample_rate=made["sample_rate"],
                frame_count=made["frames"], media_ref=made["path"],
                mode="segmented"))
        take_of = {m["audio_hash"]: m["take_id"] for m in booth.masters}
        said = {row["occurrence_id"]: (row["text"], row["actor"])
                for row in script["lines"]}
        for index, raw in enumerate(booth.cuts):
            text, actor = said[raw["occurrence_id"]]
            cuts.append(self.sm.line_cut(
                "cut-%d" % index, occurrence_id=raw["occurrence_id"],
                ordinal=raw["ordinal"], take_id=take_of[raw["master_hash"]],
                master_sha256="sha256:" + raw["master_hash"],
                sample_rate=24000, start_sample=raw["start_sample"],
                end_sample=raw["end_sample"],
                # script_manifest refuses a silence- or estimate-bounded cut
                # outright; only a renderer boundary, an alignment or a human
                # edit is evidence of which line was spoken.
                boundary_method="alignment",
                verification={"transcript": text, "actor": actor,
                              "ambiguous": False},
                state="accepted"))
        return script, masters, cuts

    def test_script_manifest_records_assemble_without_translation(self):
        script, masters, cuts = self.real_records()
        with assemble_conversation(script, masters, cuts,
                                   beats=[0.12, 0.12, 0.12, 0.0],
                                   assembly_id="asm-real") as made:
            self.assertEqual(made.cue_map["sequence"], script["sequence"])
            self.assertEqual(made.cue_map["script_revision"],
                             script["revision"])
            self.assertTrue(made.cue_map["verified"]["ok"])
            self.assertEqual([c["ordinal"] for c in made.cue_map["cues"]],
                             [1, 2, 3, 4])

    def test_a_pending_or_rejected_cut_state_is_refused(self):
        for state in ("pending", "rejected"):
            with self.subTest(state=state):
                script, masters, cuts = self.real_records()
                cuts[0] = dict(cuts[0], state=state)
                with self.assertRaises(AssemblyRefused) as caught:
                    assemble_conversation(script, masters, cuts)
                self.assertEqual(caught.exception.reason, "unverified_cut")

    def test_the_output_is_accepted_by_script_manifest_and_admission(self):
        """finished_conversation -> validate_assembly -> broadcast_admission."""
        script, masters, cuts = self.real_records()
        with assemble_conversation(script, masters, cuts,
                                   beats=[0.12, 0.12, 0.12, 0.0],
                                   assembly_id="asm-real") as made:
            record = self.sm.finished_conversation(
                **ca.finished_conversation_kwargs(made))
            self.assertEqual(self.sm.cue_sequence(record), script["sequence"])
            verdict = self.sm.validate_assembly(
                record, script=script,
                cuts_by_id={c["cut_id"]: c for c in cuts},
                masters={m["take_id"]: m for m in masters})
            self.assertTrue(verdict.get("ok"), verdict)
            admission = self.sm.broadcast_admission("adm-1", assembly=record)
            self.assertEqual(
                [p["occurrence_id"] for p in admission["sequence_positions"]],
                script["sequence"])
            self.assertEqual(admission["final_sha256"],
                             "sha256:" + made.final_audio_hash)

    def test_line_alignment_cuts_are_accepted_without_an_ok_field(self):
        """`line_alignment.LineCut` carries evidence, not a verdict."""
        try:
            from line_alignment import LineCut
        except ImportError:                       # pragma: no cover
            self.skipTest("line_alignment.py is not in this checkout")
        script, booth = self.four_line_exchange()
        cuts = [LineCut(occurrence_id=raw["occurrence_id"],
                        ordinal=raw["ordinal"], speaker="dj",
                        start_sample=raw["start_sample"],
                        end_sample=raw["end_sample"], sample_rate=24000,
                        boundary_method="alignment",
                        verification={"transcript": "good evening",
                                      "actor": "dj", "ambiguous": False},
                        mode="segmented",
                        master_hash=raw["master_hash"])
                for raw in booth.cuts]
        with assemble_conversation(script, booth.masters, cuts,
                                   beats=[0.12, 0.12, 0.12, 0.0]) as made:
            self.assertEqual(made.cue_map["sequence"],
                             ["occ-1", "occ-2", "occ-3", "occ-4"])
            self.assertTrue(made.cue_map["verified"]["ok"])

    def test_manifest_cue_entries_carry_speech_and_cue_ends_separately(self):
        script, booth = self.four_line_exchange()
        for cut in booth.cuts:
            if cut["occurrence_id"] == "occ-2":
                cut["pause_after"] = 0.4
        with self.assemble(script, booth) as made:
            rows = ca.manifest_cue_entries(made.cue_map)
            self.assertEqual(len(rows), 4)
            self.assertEqual(set(rows[0]),
                             {"occurrence_id", "ordinal", "cut_id",
                              "cue_start_sample", "speech_start_sample",
                              "speech_end_sample", "cue_end_sample",
                              "source_frames"})
            second = rows[1]
            self.assertEqual(second["cue_end_sample"]
                             - second["speech_end_sample"],
                             int(round(0.4 * 24000)))
            self.assertEqual(rows[2]["cue_start_sample"],
                             second["cue_end_sample"])
            for row in rows:
                self.assertGreater(row["source_frames"], 0)

    def test_a_sha256_prefixed_hash_and_a_bare_one_name_the_same_master(self):
        self.assertEqual(ca.bare_hash("sha256:" + "a" * 64), "a" * 64)
        self.assertEqual(ca.bare_hash("a" * 64), "a" * 64)
        self.assertEqual(ca.bare_hash(None), "")


class MixerMeasurementTests(unittest.TestCase):

    def test_the_join_chain_delays_content_by_a_constant_not_a_scale(self):
        """The measurement that justifies this whole module.

        `alimiter`'s attack lookahead delays everything by a constant.  A
        scale factor cannot express a constant, which is exactly why the
        rescale at app.py:83945 cannot be made correct by tuning it.
        """
        latency = ca.measure_mix_latency(False)
        self.assertGreaterEqual(latency, 0)
        self.assertLess(latency, 24000 // 10)
        # Cached, and the same answer twice.
        self.assertEqual(latency, ca.measure_mix_latency(False))


if __name__ == "__main__":
    unittest.main()
