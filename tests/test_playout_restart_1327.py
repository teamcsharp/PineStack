"""[#1327] The running order survives a restart - what comes back, and what must not.

Every test here is a restart: build a sequencer on a state path, tell it
things, throw it away, and build a second one on the same path.  The second
sequencer is a new process as far as the book is concerned.
"""
import json
import tempfile
import unittest
from pathlib import Path

from playout_sequencer import (LinearSequencer, MODE_LINEAR, MODE_SHADOW,
                               MODE_OFF)


class Clock:
    def __init__(self, at=1000.0):
        self.at = float(at)

    def __call__(self):
        return self.at

    def move(self, seconds):
        self.at += float(seconds)


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.book = self.root / "state.json"
        self.clock = Clock()
        self.mode = MODE_LINEAR

    def seq(self, clock=None, **kw):
        kw.setdefault("held_stale_s", 30)
        kw.setdefault("hold_reserve_s", 20)
        kw.setdefault("snap_every_s", 0.0)
        # These tests drive a FROZEN clock, so the burst floor - which exists
        # to keep a 35-dispatch burst off the event loop - would otherwise
        # swallow every write after the first.  It has its own test below.
        kw.setdefault("snap_force_every_s", 0.0)
        return LinearSequencer(
            clock=clock or self.clock, mode_reader=lambda: self.mode,
            events_path=self.root / "events.jsonl",
            state_path=self.book, **kw)

    # ------------------------------------------------ tier 1: the sounding air

    def test_the_air_already_sounding_comes_back(self):
        """The one thing a restart must not forget: what the listener can hear."""
        first = self.seq()
        first.dispatched("occ-a", route="page", starts_at=self.clock(),
                         seconds=60, delivery_id="d-a", key="sid:a")
        self.assertEqual(first.air_free_at("page"), self.clock() + 60)

        self.clock.move(10)
        after = self.seq()                       # the restart
        self.assertEqual(after.state()["book"]["restored"]["line"], 1)
        # 50 seconds of audio left, and the new process knows it.
        self.assertAlmostEqual(after.air_free_at("page"), self.clock() + 50, 3)
        self.assertGreaterEqual(after.page_floor(), self.clock() + 50)

    def test_a_restart_can_only_push_a_stamp_later_never_earlier(self):
        """The safety property the whole tier rests on."""
        first = self.seq()
        first.dispatched("occ-a", route="page", starts_at=self.clock(),
                         seconds=45, delivery_id="d-a")
        self.clock.move(5)
        blind = LinearSequencer(clock=self.clock, mode_reader=lambda: self.mode,
                                events_path=self.root / "e2.jsonl")
        after = self.seq()
        self.assertGreaterEqual(after.page_floor(), blind.page_floor())
        self.assertGreater(after.page_floor(), self.clock())

    def test_a_promised_clip_does_not_come_back(self):
        """page_recovery_start re-stamps a preserved delivery at a NEW moment;
        a reservation held at the old one is a ghost."""
        first = self.seq()
        first.dispatched("occ-future", route="page",
                         starts_at=self.clock() + 120, seconds=30,
                         delivery_id="d-f")
        after = self.seq()
        restored = after.state()["book"]["restored"]
        self.assertEqual(restored["line"], 0)
        self.assertIn("promised", restored["dropped"])
        self.assertEqual(after.air_free_at("page"), self.clock())

    def test_a_clip_that_is_over_does_not_come_back(self):
        first = self.seq()
        first.dispatched("occ-short", route="page", starts_at=self.clock(),
                         seconds=5, delivery_id="d-s")
        self.clock.move(600)
        after = self.seq()
        self.assertEqual(after.state()["book"]["restored"]["line"], 0)
        self.assertEqual(after.air_free_at("page"), self.clock())

    def test_a_restored_row_expires_by_its_own_end(self):
        """It can never manufacture silence beyond the audio's own length."""
        first = self.seq()
        first.dispatched("occ-a", route="page", starts_at=self.clock(),
                         seconds=30, delivery_id="d-a")
        after = self.seq()
        self.assertGreater(after.air_free_at("page"), self.clock())
        self.clock.move(40)
        self.assertEqual(after.air_free_at("page"), self.clock())
        self.assertEqual(after.page_floor(), self.clock())

    def test_a_restored_row_raises_no_false_stall(self):
        first = self.seq()
        first.dispatched("occ-a", route="page", starts_at=self.clock(),
                         seconds=300, delivery_id="d-a")
        self.clock.move(5)
        first.heard(delivery_id="d-a", event="playing", position_s=5,
                    listener="page")
        self.clock.move(200)                 # far past stall_s
        after = self.seq()
        after.state()
        self.assertEqual(int(after.state()["counts"].get("stalled") or 0), 0)

    def test_a_listener_that_never_reloaded_is_still_heard(self):
        first = self.seq()
        first.dispatched("occ-a", route="page", starts_at=self.clock(),
                         seconds=120, delivery_id="d-a")
        self.clock.move(10)
        after = self.seq()
        got = after.heard(delivery_id="d-a", event="playing", position_s=12,
                          listener="page")
        self.assertIsNotNone(got)
        self.assertEqual(got["oid"], "occ-a")

    # ------------------------------------------------------ tier 3: the claims

    def test_a_held_round_comes_back_as_a_claim_and_not_as_the_head(self):
        """Nothing in the new process can dispatch it, so it must not reserve."""
        first = self.seq()
        first.hold("sid:r1", block=41, ord0=0, seconds=46, lines=11,
                   road="gallery", media="/media/round-r1.wav",
                   sid="r1", occurrence="occ-r1", audio_ready=True)
        self.assertEqual(first.head()["key"], "sid:r1")

        after = self.seq()
        self.assertIsNone(after.head())                     # never the head
        claims = after.carried()
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["key"], "sid:r1")
        self.assertEqual(claims[0]["block"], 41)
        self.assertEqual(claims[0]["media_path"], "/media/round-r1.wav")
        self.assertEqual(claims[0]["blockers"], [])
        self.assertTrue(claims[0]["needs"])

    def test_a_claim_reserves_no_air_and_refuses_no_filler(self):
        first = self.seq()
        first.hold("sid:r1", block=41, seconds=46, lines=11, road="gallery",
                   media="/media/r1.wav", sid="r1", audio_ready=True)
        after = self.seq()
        self.assertEqual(after.reserve_until(), after.air_free_at("page"))
        self.assertEqual(after.page_floor(), self.clock())
        verdict = after.ask_fill("sting", dialogue=False, seconds=6)
        self.assertTrue(verdict["allow"])
        self.assertFalse(verdict["enforced"])
        self.assertEqual(verdict["why"], "")
        rescue = after.ask_fill("rescue", dialogue=True)
        self.assertTrue(rescue["allow"])

    def test_a_round_that_was_still_being_made_is_a_claim_with_its_reason(self):
        first = self.seq()
        first.making("sid:r2", road="banter", lines=4, eta_s=20)
        first.hold("sid:r2", audio_ready=False,
                   why_not_ready="the mixer produced no cue sheet for it")
        after = self.seq()
        claim = after.carried()[0]
        self.assertFalse(claim["audio_ready"])
        self.assertIn("the mixer produced no cue sheet for it", claim["blockers"])
        # ...and a making shelf that is not restored cannot hold dialogue off.
        self.assertTrue(after.ask_fill("continuity", dialogue=True)["allow"])

    def test_the_boot_sweeps_forget_answers_a_claim(self):
        """#1301 withdraws the round; the handshake drops the claim by name."""
        first = self.seq()
        first.hold("sid:r1", block=41, seconds=46, road="gallery", sid="r1",
                   media="/media/r1.wav", audio_ready=True)
        after = self.seq()
        self.assertEqual(len(after.carried()), 1)
        self.assertTrue(after.forget("sid:r1", "the boot sweep withdrew it (#1301)"))
        self.assertEqual(after.carried(), [])
        self.assertFalse(after.forget("sid:r1"))

    def test_a_claim_this_process_already_holds_is_blocked_by_name(self):
        first = self.seq()
        first.hold("sid:r1", block=41, seconds=46, sid="r1",
                   media="/media/r1.wav", audio_ready=True)
        after = self.seq()
        after.hold("sid:r1", block=41, seconds=46, sid="r1",
                   media="/media/r1.wav", audio_ready=True)
        claim = after.carried()[0]
        self.assertIn("this process is already making or holding "
                      "a round under the same name", claim["blockers"])

    def test_a_claim_nobody_answered_expires(self):
        first = self.seq(carried_keep_s=60)
        first.hold("sid:r1", block=41, seconds=46, sid="r1",
                   media="/media/r1.wav", audio_ready=True)
        after = self.seq(carried_keep_s=60)
        self.assertEqual(len(after.carried()), 1)
        self.clock.move(90)
        after.evict_stale(self.clock())
        self.assertEqual(after.carried(), [])
        self.assertEqual(int(after.state()["counts"]["carried_stale"]), 1)

    def test_claims_are_ranked_by_the_ledgers_own_numbers(self):
        first = self.seq()
        first.hold("sid:b", block=12, ord0=0, seconds=10, sid="b",
                   media="/m/b.wav", audio_ready=True)
        first.hold("sid:a", block=11, ord0=3, seconds=10, sid="a",
                   media="/m/a.wav", audio_ready=True)
        after = self.seq()
        self.assertEqual([c["key"] for c in after.carried()],
                         ["sid:a", "sid:b"])

    # ---------------------------------------------------------- tier 2: census

    def test_the_census_accumulates_across_restarts(self):
        first = self.seq()
        # Something must be SOUNDING, or #1295 gives the filler the hole and
        # there is no queue to count.
        first.dispatched("occ-live", route="page", starts_at=self.clock(),
                         seconds=300, delivery_id="d-live")
        first.hold("sid:r1", block=1, seconds=30, sid="r1", audio_ready=True)
        for _ in range(3):
            first.ask_fill("sting", dialogue=False, seconds=200)
        counts = first.state()["counts"]
        self.assertEqual(counts["queued"], 3)

        after = self.seq()
        self.assertEqual(after.state()["counts"]["queued"], 3)
        self.assertEqual(after.state()["asks"]["sting"]["queued"], 3)
        self.assertGreater(after.state()["asks"]["sting"]["pushed_s"], 0)
        # ...and the new process adds to it rather than starting again.
        after.dispatched("occ-live2", route="page", starts_at=self.clock(),
                         seconds=300, delivery_id="d-live2")
        after.hold("sid:r2", block=2, seconds=30, sid="r2", audio_ready=True)
        after.ask_fill("sting", dialogue=False, seconds=200)
        self.assertEqual(after.state()["counts"]["queued"], 4)

    def test_the_book_says_when_the_station_first_started(self):
        first = self.seq()
        first_started = first.state()["started_at"]
        first.hold("sid:r1", block=1, seconds=10, audio_ready=True)
        self.clock.move(300)
        after = self.seq()
        self.assertEqual(after.state()["book"]["first_started_at"], first_started)
        self.assertEqual(after.state()["started_at"], self.clock())

    # -------------------------------------------------------------- the limits

    def test_a_cold_book_keeps_the_counters_and_nothing_else(self):
        first = self.seq(live_max_age_s=60)
        first.dispatched("occ-a", route="page", starts_at=self.clock(),
                         seconds=900, delivery_id="d-a")
        first.hold("sid:r1", block=1, seconds=30, sid="r1", audio_ready=True)
        self.clock.move(120)
        after = self.seq(live_max_age_s=60)
        book = after.state()["book"]["restored"]
        self.assertTrue(book["census"])
        self.assertEqual(book["line"], 0)
        self.assertEqual(book["carried"], 0)
        self.assertGreater(int(after.state()["counts"]["dispatched"]), 0)
        self.assertEqual(after.air_free_at("page"), self.clock())

    def test_an_ancient_book_is_ignored_entirely(self):
        first = self.seq(census_max_age_s=100)
        first.hold("sid:r1", block=1, seconds=30, audio_ready=True)
        self.clock.move(500)
        after = self.seq(census_max_age_s=100)
        book = after.state()["book"]["restored"]
        self.assertTrue(book["read"])
        self.assertFalse(book["census"])
        self.assertEqual(after.state()["counts"].get("held"), None)

    def test_a_corrupt_book_never_raises_and_never_stops_the_air(self):
        for payload in ("", "{", "[]", "null", '{"schema_version": 99}',
                        '{"schema_version": 1, "at": "soon", "line": "no"}',
                        '{"schema_version": 1, "at": 1000, "line": [{"oid": 1}],'
                        ' "held": ["not a row"], "counts": {"a": "b"}}'):
            self.book.write_text(payload, encoding="utf-8")
            seq = self.seq()
            self.assertIsNone(seq.head())
            self.assertEqual(seq.air_free_at("page"), self.clock())
            self.assertTrue(seq.ask_fill("sting", dialogue=False)["allow"])
            self.assertIsInstance(seq.state(), dict)

    def test_a_book_that_cannot_be_written_never_stops_the_air(self):
        blocker = self.root / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        seq = LinearSequencer(clock=self.clock, mode_reader=lambda: self.mode,
                              state_path=blocker / "deeper" / "state.json",
                              snap_every_s=0.0, snap_force_every_s=0.0)
        for n in range(60):
            seq.hold("sid:%d" % n, block=n, seconds=5, audio_ready=True)
        book = seq.state()["book"]
        self.assertGreater(book["errors"], 0)
        # ...and it gives up rather than paying for a write on every count.
        self.assertLessEqual(book["errors"], 25)
        self.assertEqual(seq.head()["block"], 1)

    def test_no_state_path_means_no_book_and_no_io(self):
        seq = LinearSequencer(clock=self.clock, mode_reader=lambda: self.mode)
        seq.hold("sid:r1", block=1, seconds=10, audio_ready=True)
        self.assertEqual(seq.state()["book"]["path"], "")
        self.assertEqual(seq.state()["book"]["writes"], 0)
        self.assertEqual(seq.carried(), [])
        self.assertFalse(list(self.root.glob("state.json")))

    def test_the_book_is_coalesced_and_bounded(self):
        seq = self.seq(snap_every_s=5.0)
        seq.dispatched("occ-a", route="page", starts_at=self.clock(),
                       seconds=600, delivery_id="d-a")
        writes_after_structural = seq.state()["book"]["writes"]
        for n in range(200):                       # 200 listener acks
            seq.heard(delivery_id="d-a", event="playing", position_s=n * 0.5)
        book = seq.state()["book"]
        self.assertEqual(book["writes"], writes_after_structural)
        self.assertGreaterEqual(book["skipped"], 200)
        self.clock.move(10)
        seq.heard(delivery_id="d-a", event="playing", position_s=150)
        self.assertGreater(seq.state()["book"]["writes"], writes_after_structural)

    def test_a_structural_change_is_written_at_once(self):
        seq = self.seq(snap_every_s=3600.0)
        seq.hold("sid:r1", block=1, seconds=30, sid="r1", audio_ready=True)
        snap = json.loads(self.book.read_text(encoding="utf-8"))
        self.assertEqual([r["key"] for r in snap["held"]], ["sid:r1"])
        seq.forget("sid:r1", "withdrawn")
        snap = json.loads(self.book.read_text(encoding="utf-8"))
        self.assertEqual(snap["held"], [])

    def test_a_burst_of_dispatches_costs_one_write_not_thirty_five(self):
        """The event loop pays for this book, so a burst is coalesced."""
        seq = self.seq(snap_every_s=2.0, snap_force_every_s=0.25)
        before = seq.state()["book"]["writes"]
        for n in range(35):                # the shape of a round hitting the feed
            seq.dispatched("occ-%02d" % n, route="page",
                           starts_at=self.clock() + n * 8, seconds=8.0,
                           delivery_id="d-%02d" % n)
        book = seq.state()["book"]
        self.assertLessEqual(book["writes"] - before, 2)
        self.assertGreaterEqual(book["skipped"], 30)
        # ...and the skipped writes are not lost: the next count takes them.
        self.clock.move(1)
        seq.ended("occ-00", route="page", why="the transport reported the end")
        snap = json.loads(self.book.read_text(encoding="utf-8"))
        self.assertEqual(len(snap["line"]), 34)

    def test_off_is_still_inert_after_a_restart(self):
        self.mode = MODE_LINEAR
        first = self.seq()
        first.dispatched("occ-a", route="page", starts_at=self.clock(),
                         seconds=60, delivery_id="d-a")
        first.hold("sid:r1", block=1, seconds=30, sid="r1", audio_ready=True)
        self.clock.move(5)
        self.mode = MODE_OFF
        after = self.seq()
        self.assertEqual(after.page_floor(), 0.0)
        got = after.ask_fill("sting", dialogue=False)
        self.assertTrue(got["allow"])
        self.assertEqual(got["mode"], MODE_OFF)

    def test_shadow_after_a_restart_still_enforces_nothing(self):
        self.mode = MODE_LINEAR
        first = self.seq()
        first.dispatched("occ-a", route="page", starts_at=self.clock(),
                         seconds=60, delivery_id="d-a")
        self.clock.move(5)
        self.mode = MODE_SHADOW
        after = self.seq()
        self.assertEqual(after.page_floor(), 0.0)

    # ------------------------------------------------- the four standing rules

    def test_1290_a_round_keeps_its_place_across_a_restart_too(self):
        """#1290: stop reserving only once the air has actually freed."""
        first = self.seq()
        first.dispatched("long-opening", route="page", starts_at=self.clock(),
                         seconds=120, delivery_id="d-open")
        self.clock.move(5)
        after = self.seq()
        after.hold("ready-round", block=4, seconds=30, lines=5, road="banter",
                   audio_ready=True)
        self.clock.move(25)              # older than hold_reserve_s
        self.assertAlmostEqual(after.reserve_until(), self.clock() + 90 + 30, 3)
        self.assertEqual(after.head()["key"], "ready-round")

    def test_1283_a_round_waiting_its_turn_is_not_stale_across_a_restart(self):
        first = self.seq()
        first.dispatched("long-opening", route="page", starts_at=self.clock(),
                         seconds=600, delivery_id="d-open")
        after = self.seq()
        after.hold("ready-round", block=4, seconds=30, audio_ready=True)
        self.clock.move(120)             # past held_stale_s of 30
        after.evict_stale(self.clock())
        self.assertEqual(after.head()["key"], "ready-round")

    def test_1310_expires_a_reservation_only_while_nothing_is_sounding(self):
        """#1310 landed after this work began and keys on `_sounding`, which
        is exactly what tier 1 restores.  Both directions are checked here
        because a restore that lied about the air would silently re-open the
        dead-air #1310 closed."""
        first = self.seq()
        first.dispatched("occ-live", route="page", starts_at=self.clock(),
                         seconds=120, delivery_id="d-live")
        self.clock.move(5)
        after = self.seq()                       # the restart, mid-clip
        after.hold("sid:r1", block=9, seconds=30, sid="r1", audio_ready=True)
        self.clock.move(25)                      # older than hold_reserve_s

        # Something IS genuinely sounding, so #1310 leaves #1290's
        # reservation standing and the running order is protected.
        self.assertIsNotNone(after.sounding("page"))
        self.assertAlmostEqual(after.reserve_until(),
                               after.air_free_at("page") + 30, 3)

        # Once that audio is over, #1310 expires it exactly as it would
        # have without any restore at all.
        self.clock.move(120)
        self.assertIsNone(after.sounding("page"))
        self.assertEqual(after.reserve_until(), after.air_free_at("page"))

    def test_a_restart_with_nothing_sounding_does_not_re_open_1310s_dead_air(self):
        """A carried claim is not a head, so it cannot reserve at all -
        which is the same answer #1310 reaches, by a shorter road."""
        first = self.seq()
        first.hold("sid:r1", block=9, seconds=46, sid="r1",
                   media="/m/r1.wav", audio_ready=True)
        self.clock.move(400)                     # long past hold_reserve_s
        after = self.seq()
        self.assertIsNone(after.sounding("page"))
        self.assertIsNone(after.head())
        self.assertEqual(after.reserve_until(), after.air_free_at("page"))
        self.assertEqual(after.page_floor(), self.clock())

    def test_1295_a_filler_may_still_have_a_measured_hole_after_a_restart(self):
        first = self.seq()
        first.hold("sid:r1", block=1, seconds=46, sid="r1", audio_ready=True)
        after = self.seq()
        # The claim is inert, so a filler is simply allowed...
        self.assertTrue(after.ask_fill("sting", dialogue=False, seconds=6)["allow"])
        # ...and a round this process holds itself behaves exactly as #1295 says.
        after.hold("sid:r2", block=2, seconds=46, sid="r2", audio_ready=True)
        after.dispatched("occ-far", route="page",
                         starts_at=self.clock() + 400, seconds=10,
                         delivery_id="d-far")
        self.assertTrue(after.ask_fill("sting", dialogue=False, seconds=6)["allow"])
        big = after.ask_fill("gold", dialogue=False, seconds=600)
        self.assertFalse(big["allow"])


if __name__ == "__main__":
    unittest.main()
