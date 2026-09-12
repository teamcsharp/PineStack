"""#1260: the cupboard was full of finished radio nobody was taking.

Measured 2026-09-12: 25 recorded memos from upstairs and 30 recorded
gallery rounds had never been on the air, the oldest 103 hours old, while
the same two roads were written and rendered LIVE ninety times in the
same 24 hours. Both doors from the cupboard to the air were shut for
ordinary running - a slot that almost never comes round, and a silence
the SFX Guy fills first - so nothing ever asked.

These tests pin the three things that would fail silently and still look
correct on a panel:

  * that the explanation the desk shows is the AIR'S OWN reason, not a
    second opinion about it. A row that is ready and unheard must say so
    in those words, and a row that is off brief must not;
  * that the standing consumer actually picks the LONGEST-waiting row
    rather than the head of a shelf, and refuses to run when the dial is
    off or the interval has not elapsed;
  * that the replace sweep never reaches for a row the air could still
    take. #1075 is the rule it would break: unheard radio is an argument
    for airing it, not for binning it.
"""
import time
import unittest
from unittest import mock

import app


def row(kind="manager", *, age_h=50.0, aired=0, ready=True, off_brief=False,
        seconds=40.0, made=2, chunks=2):
    at = time.time() - age_h * 3600.0
    entry = {"script": "A: a memo landed\nB: it did", "script_plain": "x",
             "script_tinted": "A: a memo landed\nB: it did", "use": "tinted",
             "chunks": chunks, "made": made, "keys": ["k1", "k2"],
             "prep_kind": kind, "off_brief": off_brief}
    return {"entry": entry, "at": at, "kind": kind, "seconds": seconds,
            "aired": aired, "aired_at": (at + 60.0) if aired else 0.0,
            "off_brief": off_brief, "cast": "cohost=a|dj=b",
            "sid": "%s-%s" % (kind, int(at)), "brief": {"want": "a memo"}}


class CupboardWhy(unittest.TestCase):
    """The desk says what the air decided, in the air's own words."""

    def setUp(self):
        self.patches = [
            mock.patch.object(app, "cast_signature", lambda: "cohost=a|dj=b"),
            mock.patch.object(app, "_larder_current", lambda e: True),
            mock.patch.object(app, "dialogue_tint_ready", lambda k, r: True),
            mock.patch.object(app, "_ready_slot_window",
                              lambda k: {"kind": "record", "deadline": 0.0}),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_ready_and_unheard_says_nobody_asked(self):
        """The finding itself. Nothing is wrong with the round; the reason
        it has not aired is that no road ever asked for it, and that has
        to be SAID rather than left as an absence of reasons."""
        r = row(age_h=103.0)
        with mock.patch.object(app, "dialogue_audio_ready", lambda k, x: True), \
                mock.patch.object(app, "shelf_rows", lambda k: [r]):
            got = app.cupboard_why_row("manager", r)
        self.assertFalse(got["blocked"])
        self.assertTrue(got["never_heard"])
        codes = [x["code"] for x in got["reasons"]]
        self.assertIn("never_asked_for", codes)
        # ...and it must name the shut door, because that is the cure.
        self.assertIn("no_slot", codes)
        self.assertIn("4d", got["say"] + str(got["waited"]) or "")

    def test_off_brief_is_blocked_and_never_says_nobody_asked(self):
        """A row the air will never take must not be described as merely
        unlucky. Both halves matter: the operator decides what to remove
        from this text."""
        r = row(off_brief=True)
        with mock.patch.object(app, "dialogue_audio_ready", lambda k, x: True), \
                mock.patch.object(app, "shelf_rows", lambda k: [r]):
            got = app.cupboard_why_row("manager", r)
        self.assertTrue(got["blocked"])
        codes = [x["code"] for x in got["reasons"]]
        self.assertIn("off_brief", codes)
        self.assertNotIn("never_asked_for", codes)

    def test_unrendered_and_clip_gone_are_told_apart(self):
        """"Written but never recorded" and "its recording was pruned"
        take opposite cures, and the desk showed neither."""
        half = row(made=1, chunks=2)
        with mock.patch.object(app, "dialogue_audio_ready", lambda k, x: False), \
                mock.patch.object(app, "shelf_rows", lambda k: [half]):
            got = app.cupboard_why_row("manager", half)
        self.assertIn("unrendered", [x["code"] for x in got["reasons"]])
        done = row(made=2, chunks=2)
        with mock.patch.object(app, "dialogue_audio_ready", lambda k, x: False), \
                mock.patch.object(app, "shelf_rows", lambda k: [done]):
            got = app.cupboard_why_row("manager", done)
        self.assertIn("clip_gone", [x["code"] for x in got["reasons"]])

    def test_queue_position_is_named(self):
        """FIFO is the whole reason a good row waits, and it was invisible."""
        first, second = row(age_h=80.0), row(age_h=70.0)
        with mock.patch.object(app, "dialogue_audio_ready", lambda k, x: True), \
                mock.patch.object(app, "shelf_rows", lambda k: [first, second]):
            got = app.cupboard_why_row("manager", second)
        self.assertEqual(got["queue_ahead"], 1)
        self.assertIn("behind_others", [x["code"] for x in got["reasons"]])


class UnheardPick(unittest.TestCase):
    """The consumer spends the longest wait first, across roads."""

    def test_oldest_across_roads_wins(self):
        old_gallery = row("gallery", age_h=90.0)
        newer_manager = row("manager", age_h=10.0)
        shelves = {"manager": [newer_manager], "gallery": [old_gallery],
                   "news": [], "caller": []}
        with mock.patch.object(app, "shelf_rows", lambda k: shelves.get(k, [])), \
                mock.patch.object(app, "dialogue_row_ready", lambda k, r: True), \
                mock.patch.object(app, "cupboard_unheard_after", lambda: 7200.0):
            kind, got, age = app.unheard_pick()
        self.assertEqual(kind, "gallery")
        self.assertIs(got, old_gallery)
        self.assertGreater(age, 80 * 3600)

    def test_nothing_younger_than_the_dial_is_taken(self):
        shelves = {"manager": [row("manager", age_h=0.5)], "gallery": [],
                   "news": [], "caller": []}
        with mock.patch.object(app, "shelf_rows", lambda k: shelves.get(k, [])), \
                mock.patch.object(app, "dialogue_row_ready", lambda k, r: True), \
                mock.patch.object(app, "cupboard_unheard_after", lambda: 7200.0):
            kind, got, _ = app.unheard_pick()
        self.assertIsNone(got)

    def test_a_row_that_has_been_out_is_never_picked(self):
        """This road exists for rounds NOBODY has heard. Repeats have
        their own rest and their own innings and must not borrow this."""
        shelves = {"manager": [row("manager", age_h=90.0, aired=1)],
                   "gallery": [], "news": [], "caller": []}
        with mock.patch.object(app, "shelf_rows", lambda k: shelves.get(k, [])), \
                mock.patch.object(app, "dialogue_row_ready", lambda k, r: True), \
                mock.patch.object(app, "cupboard_unheard_after", lambda: 7200.0):
            _, got, _ = app.unheard_pick()
        self.assertIsNone(got)


class ReplaceSweep(unittest.TestCase):
    """"Replace what is not used" may never mean "bin unheard radio"."""

    def test_an_airable_unheard_row_is_never_offered_to_the_desk(self):
        old = row("manager", age_h=200.0)
        asked = []
        with mock.patch.dict(app._SHELF, {"manager": [old]}, clear=True), \
                mock.patch.object(app, "dialogue_row_ready", lambda k, r: True), \
                mock.patch.object(app, "retire_may",
                                  lambda k, r, w="": asked.append(w) or False):
            app._UNHEARD_SWEPT[0] = 0.0
            app.unheard_replace_sweep()
        self.assertEqual(asked, [])

    def test_a_blocked_row_past_the_horizon_reaches_the_desk(self):
        dead = row("manager", age_h=200.0, off_brief=True)
        asked = []
        with mock.patch.dict(app._SHELF, {"manager": [dead]}, clear=True), \
                mock.patch.object(app, "dialogue_row_ready", lambda k, r: False), \
                mock.patch.object(app, "retire_may",
                                  lambda k, r, w="": asked.append(w) or False):
            app._UNHEARD_SWEPT[0] = 0.0
            app.unheard_replace_sweep()
        self.assertEqual(len(asked), 1)
        self.assertIn("unheard", asked[0])

    def test_a_young_blocked_row_is_left_alone(self):
        dead = row("manager", age_h=2.0, off_brief=True)
        asked = []
        with mock.patch.dict(app._SHELF, {"manager": [dead]}, clear=True), \
                mock.patch.object(app, "dialogue_row_ready", lambda k, r: False), \
                mock.patch.object(app, "retire_may",
                                  lambda k, r, w="": asked.append(w) or False):
            app._UNHEARD_SWEPT[0] = 0.0
            app.unheard_replace_sweep()
        self.assertEqual(asked, [])


class OutOfTurn(unittest.TestCase):
    """The sheet may not hold finished radio nobody has heard.

    Measured after the first deploy of this patch: the watchdog rung it
    shipped with never ran once in ten minutes, because /api/dj said
    box.floor was "a booth round" held for 248 seconds and the pair talk
    all but continuously. A cure that waits for a gap on this station is
    a cure that never runs, so the exemption has to apply where the ROAD
    asks - and only to rounds that have never been heard.
    """

    def test_an_overdue_unheard_row_is_free_of_the_sheet(self):
        with mock.patch.object(app, "cupboard_unheard_on", lambda: True),                 mock.patch.object(app, "cupboard_unheard_after", lambda: 7200.0):
            self.assertTrue(app.unheard_free("manager", row(age_h=50.0)))

    def test_a_young_unheard_row_still_waits_its_turn(self):
        with mock.patch.object(app, "cupboard_unheard_on", lambda: True),                 mock.patch.object(app, "cupboard_unheard_after", lambda: 7200.0):
            self.assertFalse(app.unheard_free("manager", row(age_h=0.5)))

    def test_a_repeat_never_borrows_the_exemption(self):
        """A rested repeat has its own rest and its own innings. If this
        were true for aired rows the sheet would stop meaning anything."""
        with mock.patch.object(app, "cupboard_unheard_on", lambda: True),                 mock.patch.object(app, "cupboard_unheard_after", lambda: 7200.0):
            self.assertFalse(app.unheard_free("manager", row(age_h=90.0, aired=2)))

    def test_the_switch_turns_it_off(self):
        with mock.patch.object(app, "cupboard_unheard_on", lambda: False),                 mock.patch.object(app, "cupboard_unheard_after", lambda: 7200.0):
            self.assertFalse(app.unheard_free("manager", row(age_h=90.0)))


class BothFitTestsAgree(unittest.TestCase):
    """The fit test is asked TWICE and both must ask the same question.

    _ready_shelf_air checks whether the round fits its slot once to
    select it and again after the floor has been taken, because the
    window can move while a round waits for the floor. The first #1260
    patch widened only the first: an unheard round was selected, the
    floor was taken for it, and the next line refused it with the
    sheet's answer. Measured live - a gallery entry aired 102 lines of
    banter under `round=gallery` with `kind=gallery` at zero, six
    minutes after that patch went live.

    A duplicated gate is not something a behavioural test can see from
    outside, so this reads the source. If the two ever disagree again
    this is the line that says so.
    """

    def test_no_fit_test_is_left_asking_rescue_alone(self):
        import inspect
        src = inspect.getsource(app._ready_shelf_air)
        self.assertIn("free = bool(rescue) or unheard_free(kind, row)", src)
        self.assertEqual(src.count("_ready_round_fits(kind, takes, window)"), 2,
                         "the number of fit tests changed - check both "
                         "honour `free`")
        self.assertNotIn("not rescue\n", src.replace(" ", ""))
        self.assertEqual(src.count("if not takes or (not free"), 2)


if __name__ == "__main__":
    unittest.main()
