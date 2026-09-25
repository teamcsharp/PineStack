import tempfile
import unittest
from pathlib import Path

from playout_sequencer import LinearSequencer, MODE_LINEAR, MODE_SHADOW


class Clock:
    def __init__(self, at=1000.0):
        self.at = float(at)

    def __call__(self):
        return self.at

    def move(self, seconds):
        self.at += float(seconds)


class LinearPlayoutContractTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.mode = MODE_LINEAR
        self.seq = LinearSequencer(
            clock=self.clock, mode_reader=lambda: self.mode,
            held_stale_s=30, hold_reserve_s=20,
            events_path=Path(tempfile.mkdtemp()) / "events.jsonl",
        )

    def test_competing_producers_release_in_script_block_order(self):
        self.seq.hold("later", block=12, ord0=0, seconds=20, lines=3,
                      road="banter", audio_ready=True)
        self.seq.hold("first", block=11, ord0=0, seconds=15, lines=2,
                      road="caller", audio_ready=True)
        self.assertEqual(self.seq.head()["key"], "first")
        self.assertFalse(self.seq.release_check("later")["head"])
        self.assertTrue(self.seq.release_check("first")["head"])
        self.seq.dispatched("occ-first", route="page", starts_at=self.clock(),
                            seconds=15, key="first", delivery_id="d-first")
        self.assertEqual(self.seq.head()["key"], "later")

    def test_a_making_round_blocks_competing_dialogue_but_not_a_clip(self):
        self.seq.making("writing", road="banter", lines=4, eta_s=20)
        blocked = self.seq.ask_fill("continuity", dialogue=True)
        clip = self.seq.ask_fill("sfx", dialogue=False)
        self.assertFalse(blocked["allow"])
        self.assertTrue(blocked["enforced"])
        self.assertTrue(clip["allow"])

    def test_delayed_ack_is_bound_to_its_delivery_and_route(self):
        self.seq.dispatched("page-occ", route="page", starts_at=self.clock(),
                            seconds=30, delivery_id="page-delivery")
        self.seq.dispatched("box-occ", route="box", starts_at=self.clock(),
                            seconds=40, delivery_id="box-delivery")
        self.clock.move(8)
        self.seq.heard(delivery_id="box-delivery", event="playing",
                       position_s=8, listener="tablet")
        self.clock.move(4)
        self.seq.heard(delivery_id="page-delivery", event="ended",
                       position_s=30, listener="old-page")
        box = self.seq.heard(delivery_id="box-delivery", event="playing",
                             position_s=12, listener="tablet")
        self.assertEqual(box["oid"], "box-occ")
        self.assertEqual(box["route"], "box")
        self.assertFalse(box["ended_at"])

    def test_dispatch_recovers_a_held_round_by_occurrence(self):
        """A lost script key must not reserve the air until stale eviction."""
        self.seq.hold("sid:round-7", block=7, seconds=30, lines=4,
                      road="banter", occurrence="occ-round-7",
                      audio_ready=True)

        sent = self.seq.dispatched(
            "occ-round-7", route="page", starts_at=self.clock(), seconds=30,
            key="occ:", delivery_id="delivery-7")

        self.assertIsNone(self.seq.head())
        self.assertEqual(sent["oid"], "occ-round-7")
        self.assertEqual(self.seq.state()["counts"]["released_by_occurrence"], 1)

    def test_older_round_with_reused_sid_does_not_release_newer_audio(self):
        self.seq.hold("sid:repeat", block=12, seconds=30, lines=4,
                      road="banter", media="/media/new.wav", audio_ready=True)

        old = self.seq.dispatched(
            "delivery:old", route="page", starts_at=self.clock(), seconds=20,
            key="sid:repeat", media="/media/old.wav?t=signature",
            delivery_id="old-delivery")

        self.assertEqual(old["media"], "old.wav")
        self.assertEqual(self.seq.head()["media"], "new.wav")
        self.assertEqual(self.seq.state()["counts"]["release_mismatch"], 1)

        self.seq.dispatched(
            "delivery:new", route="page", starts_at=self.clock() + 20,
            seconds=30, key="sid:repeat", media="/media/new.wav?t=signature",
            delivery_id="new-delivery")
        self.assertIsNone(self.seq.head())
        self.assertEqual(self.seq.state()["counts"]["released"], 1)

    def test_occurrence_lookup_cannot_release_a_different_file(self):
        self.seq.hold("sid:repeat", block=12, seconds=30,
                      occurrence="occ-12", media="/media/new.wav",
                      audio_ready=True)

        self.seq.dispatched("occ-12", route="page", starts_at=self.clock(),
                            seconds=20, key="sid:repeat",
                            media="/media/old.wav", delivery_id="old-delivery")

        self.assertEqual(self.seq.head()["media"], "new.wav")
        self.assertNotIn("released", self.seq.state()["counts"])

    def test_withdrawn_and_stale_holds_cannot_choke_the_line(self):
        self.seq.hold("withdrawn", block=1, seconds=20, audio_ready=True)
        self.seq.hold("next", block=2, seconds=20, audio_ready=True)
        self.assertTrue(self.seq.forget("withdrawn", "operator withdrew it"))
        self.assertEqual(self.seq.head()["key"], "next")
        self.clock.move(31)
        self.seq.evict_stale(self.clock())
        self.assertIsNone(self.seq.head())
        self.assertLessEqual(self.seq.page_floor(), self.clock())

    def test_an_old_ready_round_keeps_its_slot_while_earlier_audio_plays(self):
        """Age is not staleness while the round's turn is still ahead."""
        self.seq.dispatched("long-opening", route="page", starts_at=self.clock(),
                            seconds=120, delivery_id="opening-delivery")
        self.seq.hold("ready-round", block=4, seconds=30, lines=5,
                      road="banter", audio_ready=True)
        self.clock.move(25)  # older than hold_reserve_s, 95s before its turn
        self.assertEqual(self.seq.reserve_until(), self.clock() + 95 + 30)
        self.assertEqual(self.seq.head()["key"], "ready-round")

    def test_shadow_records_pressure_without_enforcing_it(self):
        self.mode = MODE_SHADOW
        self.seq.hold("ready", block=1, seconds=20, audio_ready=True)
        verdict = self.seq.ask_fill("rescue", dialogue=True)
        self.assertTrue(verdict["allow"])
        self.assertFalse(verdict["enforced"])
        self.assertGreater(verdict["would_be_after"], 0)
        self.assertEqual(self.seq.page_floor(), 0.0)

    def test_repaired_reservations_move_only_unstarted_audio(self):
        self.seq.dispatched("one", route="page", starts_at=1060,
                            seconds=5, delivery_id="one-delivery")
        self.seq.dispatched("two", route="page", starts_at=1170,
                            seconds=5, delivery_id="two-delivery")
        self.assertTrue(self.seq.retime_unstarted("one-delivery", 1007))
        self.assertTrue(self.seq.retime_unstarted("two-delivery", 1012))
        self.assertAlmostEqual(self.seq.air_free_at("page"), 1017)
        self.seq.heard(delivery_id="one-delivery", event="playing",
                       position_s=1, audible=1, listener="tablet", at=1009)
        self.assertFalse(self.seq.retime_unstarted("one-delivery", 1020))


if __name__ == "__main__":
    unittest.main()
