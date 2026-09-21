"""The admission store and the sequencer, in isolation.

    "Acceptance requires every started occurrence to have been committed
     first, every next occurrence to follow the admitted sequence, and
     existing committed positions to remain unchanged."

Every test here builds its own store under `tempfile.TemporaryDirectory`
and its own controller. Nothing imports app.py, nothing reads the live data
directory, and nothing can reach `data/script_ledger*`.

That last sentence is not decoration. The audit found the opposite already
happening: "Some fixtures do not redirect the script-ledger writer and could
append fixture rows to the live ledger." A test that writes into the running
station's record of what it broadcast is worse than no test, so
`LiveStoreIsolationTests` at the foot of this file asserts the isolation
rather than trusting it.
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import broadcast_admission as ba


class Fixture:
    """A controller over a temporary directory, with a clock you can drive."""

    def __init__(self, **kwargs):
        self.dir = tempfile.TemporaryDirectory(prefix="admission-")
        self.root = Path(self.dir.name)
        self.media = self.root / "media"
        self.media.mkdir(parents=True, exist_ok=True)
        self.now = 1_789_000_000.0
        self.counter = 0
        self.controller = self.open(**kwargs)

    def open(self, **kwargs):
        kwargs.setdefault("clock", lambda: self.now)
        kwargs.setdefault("resolve_audio", self.resolve)
        kwargs.setdefault("new_id", self.next_id)
        kwargs.setdefault("durable", False)
        return ba.PlayoutController.open(self.root / "admission", **kwargs)

    def reopen(self, **kwargs):
        """A restart: a brand new controller over the same durable store."""
        self.controller = self.open(**kwargs)
        return self.controller

    def next_id(self):
        self.counter += 1
        return "id%03d" % self.counter

    def resolve(self, path):
        name = ba.media_key(path)
        return (self.media / name) if name else None

    def clip(self, name, seconds=4.0, rate=16000):
        """A real, readable wav. `verify` reads bytes; it is not given a mock."""
        frames = int(seconds * rate)
        data = b"\x00\x00" * frames
        header = (b"RIFF" + (36 + len(data)).to_bytes(4, "little") + b"WAVEfmt "
                  + (16).to_bytes(4, "little") + (1).to_bytes(2, "little")
                  + (1).to_bytes(2, "little") + rate.to_bytes(4, "little")
                  + (rate * 2).to_bytes(4, "little") + (2).to_bytes(2, "little")
                  + (16).to_bytes(2, "little") + b"data"
                  + len(data).to_bytes(4, "little"))
        (self.media / name).write_bytes(header + data)
        return "/media/" + name

    def round(self, name, lines, *, seconds=None, producer="test", sig="s1",
              lane="speech", revision="rev-1"):
        """A welded round file plus the cue sheet that names its lines."""
        span = seconds if seconds is not None else float(len(lines)) * 4.0
        path = self.clip(name, seconds=span)
        rows = []
        at = 0.0
        for index, line_id in enumerate(lines):
            rows.append({"id": line_id, "from": at, "until": at + 4.0,
                         "clip_tail": 0.4, "who": "dj", "text": "line " + str(index)})
            at += 4.0
        return ba.welded_round_candidate(path=path, sig=sig, rows=rows,
                                         length=span, producer=producer,
                                         lane=lane, script_revision=revision)

    def sting(self, name="sting.wav", producer="dj_sting", lane="sfx", sig="x"):
        path = self.clip(name, seconds=1.5)
        return ba.candidate(lane=lane, producer=producer, path=path, sig=sig,
                            seconds=1.5,
                            assembly={"assembly_id": "sting-" + name,
                                      "media": path, "seconds": 1.5,
                                      "cue_map_revision": "sting-1",
                                      "cue_map": [{"occurrence_id": "sting:" + name,
                                                   "ordinal": 0, "start_s": 0.0,
                                                   "end_s": 1.5}]})

    def close(self):
        self.dir.cleanup()


class AdmissionBase(unittest.TestCase):
    def setUp(self):
        self.fix = Fixture()
        self.addCleanup(self.fix.close)
        self.controller = self.fix.controller


# ------------------------------------------------- committed first, in order


class CommitmentTests(AdmissionBase):
    def test_every_started_occurrence_was_committed_first(self):
        candidate = self.fix.round("round-1.wav", ["a", "b", "c"])
        record = self.controller.admit(candidate)
        self.assertEqual(record["state"], ba.ADMITTED)
        verdict = self.controller.gate(lane="speech", path=candidate["path"],
                                       sig=candidate["sig"], producer="_speak_turns")
        self.assertTrue(verdict.allow)
        self.assertFalse(verdict.would_refuse)
        self.assertEqual(verdict.occurrence_id, record["occurrence_id"])
        self.assertEqual(self.controller.occurrence(verdict.occurrence_id)["state"],
                         ba.DISPATCHING)

    def test_an_uncommitted_dispatch_is_refused_when_enforcement_is_on(self):
        controller = self.fix.reopen(mode=ba.MODE_ENFORCE, enforce_lanes=("speech",))
        path = self.fix.clip("loose.wav")
        verdict = controller.gate(lane="speech", path=path, sig="z",
                                  producer="dj_sting")
        self.assertFalse(verdict.allow)
        self.assertEqual(verdict.reason, ba.UNADMITTED)
        self.assertTrue(verdict.enforced)

    def test_observe_mode_allows_it_and_writes_down_what_it_would_have_done(self):
        path = self.fix.clip("loose.wav")
        verdict = self.controller.gate(lane="speech", path=path, sig="z",
                                       producer="continuity_air")
        self.assertTrue(verdict.allow, "observe mode may never change behaviour")
        self.assertTrue(verdict.would_refuse)
        self.assertEqual(verdict.reason, ba.UNADMITTED)
        counts = self.controller.stats()["counts"]
        self.assertEqual(counts["would_refuse:unadmitted"], 1)
        # The census still gives the script something to show, labelled.
        row = self.controller.occurrence(verdict.occurrence_id)
        self.assertEqual(row["origin"], "observed_dispatch")
        self.assertEqual(row["producer"], "continuity_air")

    def test_a_reply_is_never_gated(self):
        # #647: the assistant answering you is not broadcast, and the pause
        # is deliberately narrower than the FM switch.
        controller = self.fix.reopen(mode=ba.MODE_ENFORCE, enforce_lanes=("speech",))
        verdict = controller.gate(lane="speech", path="/media/ack.wav",
                                  producer="pine_speak_ack", reply=True)
        self.assertTrue(verdict.allow)
        self.assertEqual(verdict.reason, "exempt")
        self.assertFalse(verdict.would_refuse)

    def test_the_next_occurrence_follows_the_admitted_sequence(self):
        first = self.controller.admit(self.fix.round("r1.wav", ["a", "b"]))
        second = self.controller.admit(self.fix.round("r2.wav", ["c", "d"]))
        third = self.controller.admit(self.fix.sting())
        self.assertEqual([r["occurrence_id"] for r in self.controller.ready_buffer(9)],
                         [first["occurrence_id"], second["occurrence_id"],
                          third["occurrence_id"]])
        self.assertEqual(self.controller.next_occurrence()["occurrence_id"],
                         first["occurrence_id"])

    def test_one_at_a_time_while_something_is_in_flight(self):
        first = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.controller.admit(self.fix.round("r2.wav", ["b"]))
        self.controller.begin(first["occurrence_id"])
        self.assertIsNone(self.controller.next_occurrence())
        self.controller.record_delivery(first["occurrence_id"], ba.ACCEPTED)
        self.assertIsNotNone(self.controller.next_occurrence())

    def test_out_of_order_dispatch_is_named_and_refusable(self):
        first = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        second = self.controller.admit(self.fix.round("r2.wav", ["b"]))
        verdict = self.controller.gate(lane="speech", path=second["audio"]["path"],
                                       sig=second["audio"]["sig"], producer="dj_sting")
        self.assertTrue(verdict.allow, "observe mode")
        self.assertTrue(verdict.would_refuse)
        self.assertEqual(verdict.reason, ba.OUT_OF_ORDER)
        self.assertEqual(verdict.detail["waiting_on"], [first["occurrence_id"]])

    def test_order_enforcement_is_a_separate_rung_from_admission_enforcement(self):
        controller = self.fix.reopen(mode=ba.MODE_ENFORCE, enforce_lanes=("speech",),
                                     enforce_order=True)
        controller.admit(self.fix.round("r1.wav", ["a"]))
        second = controller.admit(self.fix.round("r2.wav", ["b"]))
        verdict = controller.gate(lane="speech", path=second["audio"]["path"],
                                  sig=second["audio"]["sig"], producer="dj_sting")
        self.assertFalse(verdict.allow)
        self.assertEqual(verdict.reason, ba.OUT_OF_ORDER)


# ------------------------------------------------------- positions never move


class PositionTests(AdmissionBase):
    def test_committed_positions_never_change(self):
        first = self.controller.admit(self.fix.round("r1.wav", ["a", "b", "c"]))
        self.assertEqual(first["positions"], [1, 3])
        second = self.controller.admit(self.fix.round("r2.wav", ["d"]))
        self.assertEqual(second["position"], 4)
        # A failure, a withdrawal and an interruption, none of which renumber.
        self.controller.begin(first["occurrence_id"])
        self.controller.record_delivery(first["occurrence_id"], ba.FAILED,
                                        evidence={"error": "box refused"})
        self.controller.withdraw(second["occurrence_id"], "the slot closed")
        third = self.controller.admit_interruption(self.fix.sting())
        self.assertEqual(third["position"], 5)
        self.assertEqual(self.controller.occurrence(first["occurrence_id"])["positions"],
                         [1, 3])
        self.assertEqual(self.controller.occurrence(second["occurrence_id"])["position"], 4)

    def test_a_delivery_failure_retains_the_committed_identity_and_position(self):
        record = self.controller.admit(self.fix.round("r1.wav", ["a", "b"]))
        self.controller.begin(record["occurrence_id"])
        self.controller.record_delivery(record["occurrence_id"], ba.BLOCKED,
                                        evidence={"why": "the box is quiet"})
        after = self.controller.occurrence(record["occurrence_id"])
        self.assertEqual(after["occurrence_id"], record["occurrence_id"])
        self.assertEqual(after["positions"], record["positions"])
        self.assertEqual(after["outcome"], ba.BLOCKED)
        self.assertEqual(after["audio"]["hash"], record["audio"]["hash"])

    def test_each_cue_line_owns_its_own_sequence_position(self):
        record = self.controller.admit(self.fix.round("r1.wav", ["a", "b", "c"]))
        self.assertEqual([c["position"] for c in record["cues"]], [1, 2, 3])
        self.assertEqual([c["line_id"] for c in record["cues"]], ["a", "b", "c"])
        self.assertTrue(all(c["occurrence_id"] == record["occurrence_id"]
                            for c in record["cues"]))

    def test_a_withdrawn_occurrence_leaves_its_hole_rather_than_closing_it(self):
        first = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        second = self.controller.admit(self.fix.round("r2.wav", ["b"]))
        self.assertTrue(self.controller.withdraw(first["occurrence_id"], "replaced"))
        self.assertEqual(self.controller.next_occurrence()["occurrence_id"],
                         second["occurrence_id"])
        self.assertEqual(self.controller.occurrence(first["occurrence_id"])["position"], 1)
        self.assertEqual(second["position"], 2)


# ----------------------------------------------------------- what is admitted


class VerificationTests(AdmissionBase):
    def test_audio_that_is_not_there_is_never_admitted(self):
        candidate = self.fix.round("gone.wav", ["a"])
        (self.fix.media / "gone.wav").unlink()
        with self.assertRaises(ba.AdmissionError):
            self.controller.admit(candidate)
        self.assertEqual(self.controller.stats()["occurrences"], 0)

    def test_cue_offsets_that_are_not_known_are_never_admitted(self):
        path = self.fix.clip("blind.wav")
        candidate = ba.candidate(lane="speech", producer="test", path=path,
                                 assembly={"assembly_id": "a1", "media": path,
                                           "seconds": 4.0, "cue_map": []})
        result = self.controller.verify(candidate)
        self.assertFalse(result["ok"])
        self.assertIn("the ordered line/cue offsets are not known", result["problems"])

    def test_a_ready_replacement_is_chosen_here_and_the_reason_is_recorded(self):
        broken = self.fix.round("broken.wav", ["a"])
        (self.fix.media / "broken.wav").unlink()
        good = self.fix.round("good.wav", ["b"], producer="the_shelf")
        record = self.controller.admit(broken, alternatives=[good])
        self.assertEqual(record["producer"], "the_shelf")
        self.assertEqual(record["replacement"]["of"], broken["candidate_id"])
        self.assertIn("not available", record["replacement"]["reason"])

    def test_overlapping_cues_are_refused_in_strict_sequential_mode(self):
        path = self.fix.clip("overlap.wav", seconds=10)
        candidate = ba.candidate(lane="speech", producer="test", path=path,
                                 assembly={"assembly_id": "a1", "media": path,
                                           "seconds": 10.0,
                                           "cue_map": [{"occurrence_id": "a",
                                                        "start_s": 0, "end_s": 6},
                                                       {"occurrence_id": "b",
                                                        "start_s": 3, "end_s": 9}]})
        result = self.controller.verify(candidate)
        self.assertFalse(result["ok"])
        self.assertIn("cue 1 starts before cue 0 ends", result["problems"])

    def test_a_repeated_line_occurrence_id_inside_one_assembly_is_refused(self):
        path = self.fix.clip("twice.wav", seconds=10)
        candidate = ba.candidate(lane="speech", producer="test", path=path,
                                 assembly={"assembly_id": "a1", "media": path,
                                           "seconds": 10.0,
                                           "cue_map": [{"occurrence_id": "a",
                                                        "start_s": 0, "end_s": 4},
                                                       {"occurrence_id": "a",
                                                        "start_s": 4, "end_s": 8}]})
        result = self.controller.verify(candidate)
        self.assertFalse(result["ok"])
        self.assertIn("cue 1 repeats the line occurrence id a", result["problems"])

    def test_sample_positions_are_accepted_only_with_a_declared_rate(self):
        path = self.fix.clip("samples.wav", seconds=10)
        cues = [{"occurrence_id": "a", "start_sample": 0, "end_sample": 48000}]
        without = ba.candidate(lane="speech", producer="test", path=path,
                               assembly={"assembly_id": "a1", "media": path,
                                         "seconds": 10.0, "cue_map": cues})
        self.assertFalse(self.controller.verify(without)["ok"])
        with_rate = ba.candidate(lane="speech", producer="test", path=path,
                                 assembly={"assembly_id": "a1", "media": path,
                                           "seconds": 10.0, "sample_rate": 48000,
                                           "cue_map": cues})
        result = self.controller.verify(with_rate)
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["cues"][0]["end_s"], 1.0)

    def test_the_audio_hash_method_is_always_recorded(self):
        record = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.assertEqual(record["audio"]["hash_method"], ba.HASH_FULL)
        self.assertEqual(len(record["audio"]["hash"]), 64)

    def test_a_take_rewritten_under_a_pinned_assembly_is_refused(self):
        candidate = self.fix.round("r1.wav", ["a"])
        candidate["assembly"]["final_audio_hash"] = "0" * 64
        result = self.controller.verify(candidate)
        self.assertFalse(result["ok"])
        self.assertIn("the final audio hash does not match the assembly's",
                      result["problems"])

    def test_speech_end_is_kept_apart_from_the_cue_end(self):
        record = self.controller.admit(self.fix.round("r1.wav", ["a", "b"]))
        cue = record["cues"][0]
        self.assertEqual(cue["end_s"], 4.0)
        self.assertEqual(cue["speech_end_s"], 3.6)
        self.assertLess(cue["speech_end_s"], cue["end_s"])


# --------------------------------------------------------- the same sample


class SampleReuseTests(AdmissionBase):
    def test_playing_the_same_sting_twice_makes_two_occurrences(self):
        first = self.controller.admit(self.fix.sting("bell.wav"))
        second = self.controller.admit(self.fix.sting("bell.wav"))
        self.assertNotEqual(first["occurrence_id"], second["occurrence_id"])
        self.assertEqual(first["audio"]["hash"], second["audio"]["hash"],
                         "same bytes, same content id")
        self.assertNotEqual(first["position"], second["position"])

    def test_the_first_dispatch_claims_the_first_occurrence(self):
        first = self.controller.admit(self.fix.sting("bell.wav"))
        second = self.controller.admit(self.fix.sting("bell.wav"))
        path = first["audio"]["path"]
        one = self.controller.gate(lane="sfx", path=path, sig="x", producer="dj_sting")
        two = self.controller.gate(lane="sfx", path=path, sig="x", producer="dj_sting")
        self.assertEqual(one.occurrence_id, first["occurrence_id"])
        self.assertEqual(two.occurrence_id, second["occurrence_id"])

    def test_a_third_play_of_a_twice_admitted_sample_is_unadmitted(self):
        self.controller.admit(self.fix.sting("bell.wav"))
        self.controller.admit(self.fix.sting("bell.wav"))
        path = "/media/bell.wav"
        for _ in range(2):
            self.controller.gate(lane="sfx", path=path, sig="x", producer="dj_sting")
        third = self.controller.gate(lane="sfx", path=path, sig="x", producer="dj_sting")
        self.assertTrue(third.would_refuse)
        self.assertEqual(third.reason, ba.UNADMITTED)


# --------------------------------------------- competing producers and slots


class CompetitionTests(AdmissionBase):
    def test_two_producers_racing_get_two_positions_not_one(self):
        first = self.controller.admit(self.fix.round("r1.wav", ["a"], producer="burst"))
        second = self.controller.admit(self.fix.round("r2.wav", ["b"], producer="rescue"))
        self.assertEqual(sorted([first["position"], second["position"]]), [1, 2])
        self.assertEqual({first["producer"], second["producer"]}, {"burst", "rescue"})

    def test_a_random_sfx_slot_is_decided_before_the_affected_material(self):
        held = self.controller.reserve_position(lane="sfx", reason="a random sting",
                                                producer="sfx_cadence")
        after = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.assertLess(held["position"], after["position"])
        # Nothing may run past a slot that has not been filled.
        self.assertIsNone(self.controller.next_occurrence())
        verdict = self.controller.gate(lane="speech", path=after["audio"]["path"],
                                       sig=after["audio"]["sig"], producer="burst")
        self.assertTrue(verdict.would_refuse)
        self.assertEqual(verdict.reason, ba.SLOT_PENDING)

    def test_filling_the_reserved_slot_lets_the_reader_move_again(self):
        held = self.controller.reserve_position(lane="sfx", reason="a random sting")
        after = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        sting = self.controller.admit(self.fix.sting(),
                                      reservation=held["reservation_id"])
        self.assertEqual(sting["position"], held["position"])
        self.assertEqual(self.controller.next_occurrence()["occurrence_id"],
                         sting["occurrence_id"])
        self.assertEqual(after["position"], held["position"] + 1)

    def test_a_released_slot_does_not_hold_the_reader_for_ever(self):
        held = self.controller.reserve_position(lane="sfx", reason="maybe a sting")
        record = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.controller.release_reservation(held["reservation_id"], "no sting this round")
        self.assertEqual(self.controller.next_occurrence()["occurrence_id"],
                         record["occurrence_id"])

    def test_an_interruption_never_rewrites_a_position_already_read(self):
        first = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.controller.begin(first["occurrence_id"])
        breaking = self.controller.admit_interruption(self.fix.sting("news.wav"))
        self.assertGreater(breaking["position"], first["position"])
        self.assertEqual(breaking["origin"], "interruption")
        self.assertEqual(self.controller.occurrence(first["occurrence_id"])["position"],
                         first["position"])


# ------------------------------------------------ receipts, acks, ownership


class ReceiptTests(AdmissionBase):
    def test_a_command_acknowledgment_is_accepted_not_delivered(self):
        record = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.controller.begin(record["occurrence_id"])
        self.controller.record_delivery(
            record["occurrence_id"], ba.ACCEPTED,
            evidence={"evidence": "home_assistant_command_accepted",
                      "audible_confirmed": False})
        after = self.controller.occurrence(record["occurrence_id"])
        self.assertEqual(after["outcome"], ba.ACCEPTED)
        self.assertIs(after["delivery"]["audible_confirmed"], False)

    def test_the_first_verdict_stands_and_a_duplicate_is_kept_beside_it(self):
        record = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.controller.begin(record["occurrence_id"])
        self.assertTrue(self.controller.record_delivery(record["occurrence_id"],
                                                        ba.ACCEPTED))
        self.assertFalse(self.controller.record_delivery(record["occurrence_id"],
                                                         ba.FAILED))
        after = self.controller.occurrence(record["occurrence_id"])
        self.assertEqual(after["outcome"], ba.ACCEPTED)
        self.assertEqual(self.controller.stats()["counts"]["late_receipt"], 1)

    def test_a_delayed_acknowledgment_from_a_previous_player_cannot_land(self):
        record = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.controller.begin(record["occurrence_id"])
        stale = self.controller.generation
        self.controller.bump_generation("the operator changed the output route")
        self.assertFalse(self.controller.record_delivery(
            record["occurrence_id"], ba.DELIVERED, generation=stale))
        after = self.controller.occurrence(record["occurrence_id"])
        self.assertEqual(after["outcome"], ba.UNCERTAIN)
        self.assertEqual(after["delivery"]["evidence"]["source"], "generation")

    def test_a_stale_player_cannot_start_the_next_occurrence(self):
        record = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        stale = self.controller.generation
        self.controller.bump_generation("route change")
        verdict = self.controller.gate(lane="speech", path=record["audio"]["path"],
                                       sig=record["audio"]["sig"],
                                       producer="old player", generation=stale)
        self.assertEqual(verdict.reason, ba.STALE_GENERATION)
        self.assertEqual(self.controller.occurrence(record["occurrence_id"])["state"],
                         ba.ADMITTED)

    def test_a_stale_advance_moves_nothing(self):
        self.controller.admit(self.fix.round("r1.wav", ["a"]))
        stale = self.controller.generation
        self.controller.bump_generation("route change")
        self.assertIsNone(self.controller.advance(generation=stale))
        self.assertEqual(self.controller.stats()["counts"]["stale_advance"], 1)

    def test_player_acks_are_bounded_and_never_a_verdict(self):
        record = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.controller.begin(record["occurrence_id"])
        for index in range(40):
            self.controller.acknowledge(record["occurrence_id"], listener="tab",
                                        event="timeupdate", position_s=index * 0.25)
        self.assertEqual(self.controller.occurrence(record["occurrence_id"])["state"],
                         ba.DISPATCHING)
        self.assertEqual(len(self.controller._occurrences[record["occurrence_id"]]["acks"]),
                         24)

    def test_a_stalled_poll_leaves_the_occurrence_in_flight_and_uncertain_on_handover(self):
        # No receipt ever arrives: nothing may quietly promote it to heard.
        record = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.controller.begin(record["occurrence_id"])
        self.fix.now += 600
        self.assertEqual(self.controller.occurrence(record["occurrence_id"])["state"],
                         ba.DISPATCHING)
        self.assertIsNone(self.controller.next_occurrence())
        self.controller.bump_generation("watchdog took the air back")
        self.assertEqual(self.controller.occurrence(record["occurrence_id"])["outcome"],
                         ba.UNCERTAIN)


# --------------------------------------------------- reconciliation and view


class ReconcileTests(AdmissionBase):
    def test_reconcile_maps_the_players_actual_file_and_offset_to_a_cue(self):
        record = self.controller.admit(self.fix.round("r1.wav", ["a", "b", "c"]))
        self.controller.begin(record["occurrence_id"])
        got = self.controller.reconcile(media="r1.wav", position_s=5.0)
        self.assertTrue(got["agreed"])
        self.assertEqual(got["cue"]["line_id"], "b")
        self.assertEqual(got["cue"]["position"], record["position"] + 1)

    def test_a_player_sounding_something_nobody_admitted_is_said_so(self):
        self.controller.admit(self.fix.round("r1.wav", ["a"]))
        got = self.controller.reconcile(media="somebody-elses.wav", position_s=1.0)
        self.assertFalse(got["agreed"])
        self.assertIn("no admitted occurrence names", got["reason"])

    def test_cue_at_returns_nothing_outside_every_window(self):
        record = self.controller.admit(self.fix.round("r1.wav", ["a", "b"]))
        self.assertIsNone(self.controller.cue_at(record["occurrence_id"], 99.0))
        self.assertEqual(self.controller.cue_at(record["occurrence_id"], 0.0)["line_id"],
                         "a")

    def test_the_cue_map_the_view_reads_carries_the_committed_sequence(self):
        first = self.controller.admit(self.fix.round("r1.wav", ["a", "b"]))
        self.controller.begin(first["occurrence_id"])
        payload = self.controller.cue_map()
        self.assertEqual(payload["current"]["occurrence_id"], first["occurrence_id"])
        self.assertEqual(payload["current"]["media"], "r1.wav")
        self.assertEqual(payload["mode"], ba.MODE_OBSERVE)
        self.assertEqual([c["line_id"] for c in payload["occurrences"][0]["cues"]],
                         ["a", "b"])
        json.dumps(payload)              # the view is handed JSON, not objects

    def test_incident_references_are_absent_rather_than_invented(self):
        candidate = self.fix.round("r1.wav", ["a"], revision="")
        record = self.controller.admit(candidate)
        self.controller.begin(record["occurrence_id"])
        refs = self.controller.references()
        self.assertTrue(refs["available"])
        self.assertEqual(refs["playback_occurrence_id"], record["occurrence_id"])
        self.assertIsNone(refs["script_revision"])
        self.assertIsNone(refs["performer_session"])
        self.assertIsNone(refs["accepted_cuts"])
        self.assertEqual(refs["assembly_id"], "welded-r1.wav")

    def test_incident_references_say_so_when_nothing_has_aired(self):
        refs = self.controller.references()
        self.assertFalse(refs["available"])
        self.assertIn("no occurrence has been dispatched", refs["why"])


# --------------------------------------------- restart, crash, hour rollover


class RecoveryTests(AdmissionBase):
    def test_a_restart_keeps_every_committed_position(self):
        first = self.controller.admit(self.fix.round("r1.wav", ["a", "b"]))
        second = self.controller.admit(self.fix.round("r2.wav", ["c"]))
        controller = self.fix.reopen()
        self.assertEqual(controller.occurrence(first["occurrence_id"])["positions"],
                         [1, 2])
        self.assertEqual(controller.occurrence(second["occurrence_id"])["position"], 3)
        third = controller.admit(self.fix.round("r3.wav", ["d"]))
        self.assertEqual(third["position"], 4, "a position is never reused")

    def test_a_restart_bumps_the_ownership_generation(self):
        before = self.controller.generation
        controller = self.fix.reopen()
        self.assertGreater(controller.generation, before)

    def test_work_in_flight_across_a_restart_becomes_uncertain_not_delivered(self):
        record = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.controller.begin(record["occurrence_id"])
        controller = self.fix.reopen()
        after = controller.occurrence(record["occurrence_id"])
        self.assertEqual(after["outcome"], ba.UNCERTAIN)
        self.assertEqual(after["delivery"]["evidence"]["source"], "restart")

    def test_a_receipt_from_before_the_restart_is_refused(self):
        record = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.controller.begin(record["occurrence_id"])
        stale = self.controller.generation
        controller = self.fix.reopen()
        self.assertFalse(controller.record_delivery(record["occurrence_id"],
                                                    ba.DELIVERED, generation=stale))

    def test_a_torn_last_ledger_line_means_the_admission_never_happened(self):
        kept = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.controller.checkpoint()
        lost = self.controller.admit(self.fix.round("r2.wav", ["b"]))
        ledger = self.fix.root / "admission" / "ledger.jsonl"
        raw = ledger.read_bytes()
        ledger.write_bytes(raw[:-12])            # the process died mid-write
        controller = self.fix.reopen()
        self.assertIsNotNone(controller.occurrence(kept["occurrence_id"]))
        self.assertIsNone(controller.occurrence(lost["occurrence_id"]))

    def test_a_torn_line_never_leaves_a_half_admitted_occurrence(self):
        self.controller.admit(self.fix.round("r1.wav", ["a"]))
        ledger = self.fix.root / "admission" / "ledger.jsonl"
        with open(ledger, "a", encoding="utf-8") as handle:
            handle.write('{"type":"admitted","at":1,"occurrence":{"occurr')
        controller = self.fix.reopen()
        for row in controller.cue_map()["occurrences"]:
            self.assertTrue(row["occurrence_id"])
            self.assertIn("position", row)

    def test_a_crash_between_admission_and_handoff_withdraws_the_admission(self):
        """2026-09-21: THE CONTRACT CHANGED, AND THE MEASUREMENT IS WHY.

        This test used to assert the opposite - that a commitment survives
        the restart and is claimed by the dispatch that follows it. On the
        live station that never happened once. 674 occurrences stood
        `admitted` and never dispatched, every one of them from the burst
        road, the oldest at position 16 and four days old, and together
        they were the whole of the gate's 2,584 out-of-order refusals.

        They could not have been claimed: a burst's mix is content-
        addressed, and the re-mix after a restart is drawn with fresh seam
        beats, so it is a different file with a different key. The claim
        had nothing to match.

        Nothing is lost by taking the stranded one back, because every
        producer now commits its own occurrence before it dispatches: the
        road that airs after the restart brings its own commitment with
        it. The POSITION stands and the script keeps the hole, marked."""
        record = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        controller = self.fix.reopen()          # died before the transport call
        held = controller.occurrence(record["occurrence_id"])
        self.assertEqual(held["state"], ba.WITHDRAWN)
        self.assertEqual(held["withdrawn_why"], ba.STRANDED_WHY)
        self.assertEqual(held["position"], record["position"])

    def test_a_stranded_occurrence_stops_blocking_the_line_behind_it(self):
        """The reason it matters at all: with ordering enforced, one
        stranded commitment is silence for everything behind it."""
        stranded = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        controller = self.fix.reopen()
        controller.mode = ba.MODE_ENFORCE
        controller.enforce_order = True
        after = controller.admit(self.fix.round("r2.wav", ["b"]))
        self.assertGreater(after["position"], stranded["position"])
        verdict = controller.gate(lane="speech", path=after["audio"]["path"],
                                  sig=after["audio"]["sig"], producer="burst")
        self.assertTrue(verdict.allow)
        self.assertEqual(verdict.reason, "admitted")

    def test_a_restart_says_how_many_it_took_back(self):
        """A withdrawal nobody can count is a withdrawal nobody can audit."""
        self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.controller.admit(self.fix.round("r2.wav", ["b"]))
        controller = self.fix.reopen()
        self.assertEqual(controller.stats()["counts"].get("withdrawn:stranded"),
                         2)

    def test_an_occurrence_already_delivered_is_not_withdrawn_by_a_restart(self):
        record = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.controller.begin(record["occurrence_id"])
        self.controller.record_delivery(record["occurrence_id"], ba.ACCEPTED)
        controller = self.fix.reopen()
        held = controller.occurrence(record["occurrence_id"])
        self.assertEqual(held["state"], ba.FINISHED)
        self.assertEqual(held["outcome"], ba.ACCEPTED)

    def test_an_hour_rollover_changes_nothing_about_the_sequence(self):
        # The hour is a formatting boundary in the script, not a playback
        # step. #1268 already learned that the reading does not end because
        # the hour did; the positions must not either.
        first = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.controller.begin(first["occurrence_id"])
        self.controller.record_delivery(first["occurrence_id"], ba.ACCEPTED)
        self.fix.now = 1_789_003_600.0           # the clock rolls into a new hour
        second = self.controller.admit(self.fix.round("r2.wav", ["b"]))
        self.assertEqual(second["position"], first["position"] + 1)
        self.assertEqual(self.controller.generation, first["generation"])

    def test_pause_and_resume_do_not_dispatch_or_renumber_anything(self):
        first = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        # A pause is the station declining at the transport; the controller
        # simply never sees a gate call, and nothing moves.
        self.fix.now += 300
        self.assertEqual(self.controller.occurrence(first["occurrence_id"])["state"],
                         ba.ADMITTED)
        second = self.controller.admit(self.fix.round("r2.wav", ["b"]))
        self.assertEqual(second["position"], first["position"] + 1)
        verdict = self.controller.gate(lane="speech", path=first["audio"]["path"],
                                       sig=first["audio"]["sig"], producer="resume")
        self.assertTrue(verdict.allow)
        self.assertEqual(verdict.occurrence_id, first["occurrence_id"])

    def test_a_disconnect_and_reconnect_reconciles_before_advancing(self):
        first = self.controller.admit(self.fix.round("r1.wav", ["a", "b"]))
        self.controller.admit(self.fix.round("r2.wav", ["c"]))
        self.controller.begin(first["occurrence_id"])
        self.controller.bump_generation("the player disconnected")
        # It came back, still sounding the same file at 5 seconds.
        got = self.controller.reconcile(media="r1.wav", position_s=5.0)
        self.assertEqual(got["occurrence_id"], first["occurrence_id"])
        self.assertEqual(got["cue"]["line_id"], "b")
        self.assertFalse(got["agreed"], "nothing is in flight under the new owner")
        self.assertEqual(self.controller.occurrence(first["occurrence_id"])["outcome"],
                         ba.UNCERTAIN)

    def test_a_checkpoint_plus_a_fresh_ledger_recovers_the_same_picture(self):
        first = self.controller.admit(self.fix.round("r1.wav", ["a"]))
        self.controller.begin(first["occurrence_id"])
        self.controller.record_delivery(first["occurrence_id"], ba.ACCEPTED)
        self.controller.store.compact(self.controller._snapshot())
        controller = self.fix.reopen()
        after = controller.occurrence(first["occurrence_id"])
        self.assertEqual(after["outcome"], ba.ACCEPTED)
        self.assertEqual(after["position"], first["position"])


# ------------------------------------------ the assembler's actual cue map


class AssemblerCueMapTests(AdmissionBase):
    """The shape `conversation_assembly.py` really emits.

    Written against that module on the day it landed, by reading the dict it
    builds - `start_seconds`, `speech_end_seconds`, `cue_end_seconds`, a
    plain hex `final_audio_hash`, samples in `start_sample`/`cue_end_sample`.
    No part of it is invented, and none of it is run here: the assembler
    needs ffmpeg and this suite must not.
    """

    RATE = 24000

    def cue_map(self, lines, *, rate=None):
        rate = rate or self.RATE
        cues, offset = [], 0
        for ordinal, line in enumerate(lines):
            speech = int(3.5 * rate)
            pause = int(0.4 * rate)
            speech_end = offset + speech
            cue_end = speech_end + pause
            cues.append({
                "occurrence_id": line, "ordinal": ordinal, "kind": "line",
                "speaker": "dj", "text": "line " + line,
                "cut_id": "cut-" + line,
                "start_sample": offset, "speech_start_sample": offset,
                "speech_end_sample": speech_end, "cue_end_sample": cue_end,
                "pause_frames": pause,
                "start_seconds": round(offset / rate, 6),
                "speech_end_seconds": round(speech_end / rate, 6),
                "cue_end_seconds": round(cue_end / rate, 6),
                "pause_seconds": round(pause / rate, 6),
                "source_frames": speech, "exact": True,
                "source": {"take_id": "take-" + line,
                           "master_hash": "0" * 64,
                           "start_sample": 0, "end_sample": speech,
                           "boundary_method": "alignment"}})
            offset = cue_end
        return {"cue_map_revision": "cue-map-1", "assembly_id": "asm-77",
                "script_revision": "rev-9", "mode": "strict_sequential",
                "sample_rate": rate, "channels": 1, "frame_count": offset,
                "seconds": round(offset / rate, 6),
                "final_audio_hash": "", "derivation": "measured",
                "cues": cues,
                "sequence": [c["occurrence_id"] for c in cues]}

    def test_the_assemblers_own_cue_map_is_admitted_as_written(self):
        path = self.fix.clip("asm-77.wav", seconds=12.0, rate=self.RATE)
        cue_map = self.cue_map(["a", "b", "c"])
        cue_map["media"] = path
        record = self.controller.admit(
            ba.candidate(lane="speech", producer="conversation_assembly",
                         path=path, assembly=cue_map))
        self.assertEqual(record["assembly_id"], "asm-77")
        self.assertEqual(record["script_revision"], "rev-9")
        self.assertEqual(record["cue_map_revision"], "cue-map-1")
        self.assertEqual([c["line_id"] for c in record["cues"]], ["a", "b", "c"])
        self.assertEqual([c["position"] for c in record["cues"]], [1, 2, 3])
        self.assertEqual(record["cues"][0]["cut_id"], "cut-a")
        self.assertEqual(record["cues"][0]["who"], "dj")

    def test_the_assemblers_seconds_are_taken_exactly_not_re_derived(self):
        path = self.fix.clip("asm-77.wav", seconds=12.0, rate=self.RATE)
        cue_map = self.cue_map(["a", "b"])
        cue_map["media"] = path
        record = self.controller.admit(
            ba.candidate(lane="speech", producer="conversation_assembly",
                         path=path, assembly=cue_map))
        first = record["cues"][0]
        self.assertEqual(first["start_s"], 0.0)
        self.assertEqual(first["speech_end_s"], 3.5)
        self.assertEqual(first["end_s"], 3.9)
        self.assertLess(first["speech_end_s"], first["end_s"],
                        "the inserted pause must not start the next line")
        self.assertEqual(record["cues"][1]["start_s"], 3.9)

    def test_a_declared_full_hash_is_checked_when_it_can_be(self):
        import hashlib
        path = self.fix.clip("asm-77.wav", seconds=2.0, rate=self.RATE)
        blob = (self.fix.media / "asm-77.wav").read_bytes()
        cue_map = self.cue_map(["a"])
        cue_map.update(media=path, seconds=2.0, frame_count=int(2.0 * self.RATE),
                       final_audio_hash=hashlib.sha256(blob).hexdigest())
        cue_map["cues"] = cue_map["cues"][:1]
        cue_map["cues"][0].update(cue_end_seconds=1.9, speech_end_seconds=1.5)
        record = self.controller.admit(
            ba.candidate(lane="speech", producer="conversation_assembly",
                         path=path, assembly=cue_map))
        self.assertEqual(record["audio"]["hash"], cue_map["final_audio_hash"])

    def test_a_hash_that_cannot_be_checked_is_unchecked_not_wrong(self):
        # A LONG CONVERSATION MUST NOT BE REFUSED FOR BEING LONG. Above the
        # full-hash cap this module identifies a file by size plus its first
        # and last mebibyte; comparing that to the assembler's full digest
        # would refuse every long round on air.
        path = self.fix.clip("asm-long.wav", seconds=2.0, rate=self.RATE)
        cue_map = self.cue_map(["a"])
        cue_map.update(media=path, seconds=2.0, final_audio_hash="9" * 64)
        cue_map["cues"] = cue_map["cues"][:1]
        cue_map["cues"][0].update(cue_end_seconds=1.9, speech_end_seconds=1.5)
        controller = self.controller
        original = ba.audio_identity

        def span_only(target, **kw):
            kw["full_hash_max_bytes"] = 0
            return original(target, **kw)

        ba.audio_identity = span_only
        try:
            result = controller.verify(
                ba.candidate(lane="speech", producer="conversation_assembly",
                             path=path, assembly=cue_map))
        finally:
            ba.audio_identity = original
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["audio"]["hash_method"], ba.HASH_SPAN)
        self.assertIs(result["audio"]["declared_hash_checked"], False)

    def test_a_rewritten_take_under_a_pinned_hash_is_still_refused(self):
        path = self.fix.clip("asm-77.wav", seconds=12.0, rate=self.RATE)
        cue_map = self.cue_map(["a"])
        cue_map.update(media=path, final_audio_hash="1" * 64)
        result = self.controller.verify(
            ba.candidate(lane="speech", producer="conversation_assembly",
                         path=path, assembly=cue_map))
        self.assertFalse(result["ok"])
        self.assertIn("the final audio hash does not match the assembly's",
                      result["problems"])

    def manifest_record(self, lines):
        """The other landed shape: `script_manifest.finished_conversation`.

        It spells four things differently from the assembler's own cue map -
        `revision`, `final_sha256` (PREFIXED), `final_sample_rate`,
        `final_frame_count` - lists its rows under `cue_map`, and names the
        window `cue_start_sample` / `cue_end_sample`. Both must admit."""
        rate = self.RATE
        rows, offset = [], 0
        for ordinal, line in enumerate(lines, start=1):
            speech = int(3.5 * rate)
            pause = int(0.4 * rate)
            rows.append({"occurrence_id": line, "ordinal": ordinal,
                         "cut_id": "cut-" + line,
                         "cue_start_sample": offset,
                         "speech_start_sample": offset,
                         "speech_end_sample": offset + speech,
                         "cue_end_sample": offset + speech + pause,
                         "source_frames": speech})
            offset += speech + pause
        return {"kind": "finished_conversation", "assembly_id": "asm-88",
                "revision": "rev-9", "cuts": ["cut-" + i for i in lines],
                "mix": {"rate": rate}, "final_sha256": "sha256:" + "0" * 64,
                "final_sample_rate": rate, "final_frame_count": offset,
                "cue_map": rows, "cue_source": "measured",
                "cue_map_revision": "cue-abc123"}

    def test_the_manifest_record_shape_admits_too(self):
        path = self.fix.clip("asm-88.wav", seconds=12.0, rate=self.RATE)
        record = self.manifest_record(["a", "b", "c"])
        record["media"] = path
        got = self.controller.verify(
            ba.candidate(lane="speech", producer="script_manifest",
                         path=path, assembly=record))
        self.assertFalse(got["ok"], "a pinned hash that is wrong is refused")
        self.assertIn("the final audio hash does not match the assembly's",
                      got["problems"])
        import hashlib
        blob = (self.fix.media / "asm-88.wav").read_bytes()
        record["final_sha256"] = "sha256:" + hashlib.sha256(blob).hexdigest()
        admitted = self.controller.admit(
            ba.candidate(lane="speech", producer="script_manifest",
                         path=path, assembly=record))
        self.assertEqual(admitted["assembly_id"], "asm-88")
        self.assertEqual(admitted["script_revision"], "rev-9")
        self.assertEqual(admitted["cue_map_revision"], "cue-abc123")
        self.assertEqual([c["line_id"] for c in admitted["cues"]],
                         ["a", "b", "c"])
        self.assertEqual(admitted["cues"][0]["start_s"], 0.0)
        self.assertEqual(admitted["cues"][0]["speech_end_s"], 3.5)
        self.assertEqual(admitted["cues"][0]["end_s"], 3.9)

    def test_a_prefixed_digest_and_a_bare_one_are_the_same_digest(self):
        self.assertEqual(ba.Contracts.bare_digest("sha256:" + "a" * 64),
                         "a" * 64)
        self.assertEqual(ba.Contracts.bare_digest("A" * 64), "a" * 64)
        self.assertEqual(ba.Contracts.bare_digest(None), "")

    def test_seconds_are_derived_from_frames_and_rate_when_absent(self):
        path = self.fix.clip("asm-88.wav", seconds=12.0, rate=self.RATE)
        record = self.manifest_record(["a"])
        record["media"] = path
        record.pop("final_sha256")
        got = self.controller.verify(
            ba.candidate(lane="speech", producer="script_manifest",
                         path=path, assembly=record))
        self.assertTrue(got["ok"], got["problems"])
        self.assertAlmostEqual(got["seconds"], 3.9, places=4)

    def test_samples_alone_are_enough_when_the_rate_is_declared(self):
        path = self.fix.clip("asm-77.wav", seconds=12.0, rate=self.RATE)
        cue_map = self.cue_map(["a", "b"])
        cue_map["media"] = path
        for cue in cue_map["cues"]:
            for key in ("start_seconds", "speech_end_seconds",
                        "cue_end_seconds"):
                cue.pop(key)
        record = self.controller.admit(
            ba.candidate(lane="speech", producer="conversation_assembly",
                         path=path, assembly=cue_map))
        self.assertEqual(record["cues"][0]["start_s"], 0.0)
        self.assertEqual(record["cues"][0]["speech_end_s"], 3.5)
        self.assertEqual(record["cues"][0]["end_s"], 3.9)


# --------------------------------------------------------------- isolation


class LiveStoreIsolationTests(unittest.TestCase):
    def test_nothing_in_this_module_names_a_live_runtime_store(self):
        # The names are assembled rather than written out, or this check
        # would find its own forbidden list and fail on itself.
        forbidden = ("script" + "_ledger", "/app" + "/data",
                     "data/" + "script_reports", "voice" + "_media",
                     "pine_" + "requests")
        source = Path(__file__).with_name("test_broadcast_admission_2026_09_15.py")
        text = source.read_text(encoding="utf-8")
        for name in forbidden:
            self.assertNotIn('"' + name, text)
            self.assertNotIn("'" + name, text)

    def test_the_module_imports_nothing_that_touches_the_running_station(self):
        text = Path(ba.__file__).read_text(encoding="utf-8")
        for forbidden in ("import app", "from app import", "httpx", "fastapi",
                          "script" + "_ledger"):
            self.assertNotIn(forbidden, text)

    def test_a_controller_writes_only_under_the_directory_it_was_given(self):
        with tempfile.TemporaryDirectory(prefix="admission-scope-") as room:
            root = Path(room)
            before = set(p.name for p in root.iterdir())
            fixture = Fixture()
            try:
                fixture.controller.admit(fixture.round("r1.wav", ["a"]))
                fixture.controller.checkpoint()
                written = {p.name for p in (fixture.root / "admission").iterdir()}
                self.assertEqual(written, {"ledger.jsonl", "state.json"})
            finally:
                fixture.close()
            self.assertEqual(before, set(p.name for p in root.iterdir()))

    def test_the_default_mode_is_observe_so_a_live_station_is_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="admission-mode-") as room:
            controller = ba.PlayoutController.open(Path(room) / "a", durable=False)
            self.assertEqual(controller.mode, ba.MODE_OBSERVE)
            self.assertEqual(controller.enforce_lanes, set())
            self.assertFalse(controller.enforce_order)
            self.assertTrue(controller.gate(lane="speech", path="/media/x.wav",
                                            producer="anything").allow)


if __name__ == "__main__":
    unittest.main()
