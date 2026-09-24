"""#1261/#1262: the memo from upstairs never got through, and nothing
was writing down why.

The operator: "it's imperative that the segments that we have play out...
I want him capable of interrupting the banter to say the messages", and
then the harder one - "the orchestrator is supposed to be learning from
each broadcast, each schedule, how to better schedule things... it would
be one thing if this was the first broadcast."

The machinery to interrupt had existed since #1189/#1192 and had never
fired for the manager. entry_own_aired was why: it asked `kind in
(row["round"], row["kind"])`, and `round` is the ENTRY a line aired
under, not what the line IS. Measured over six hours of real air log:
under `round=manager`, 51 of 93 lines and 451 of 990 seconds were NOT the
manager - phone calls, stings, the SFX Guy, an advert - and every one of
them counted as the manager answering for himself. One sting inside his
four minutes made the entry read as served.

These tests pin that distinction and the two behaviours built on it,
because all three fail silently: a miscounted entry looks like a served
one, an interrupt that never fires looks like a quiet manager, and a
ledger that measures the wrong thing still prints a confident number.
"""
import time
import unittest
from unittest import mock

import app


def aired(kind, round_, seconds):
    return {"kind": kind, "round": round_, "seconds": seconds,
            "air_at": time.time()}


class EntryOwnAired(unittest.TestCase):
    """Only the CONTENT answers "did this road happen"."""

    def test_a_sting_inside_the_entry_is_not_the_manager(self):
        """The measured failure, as a fixture. Before #1261 this returned
        990 and the entry read as served."""
        rows = [aired("manager", "manager", 539.0),
                aired("call", "manager", 300.0),
                aired("sfx", "manager", 100.0),
                aired("sfxguy", "manager", 50.0),
                aired("ad", "manager", 1.0)]
        with mock.patch.object(app, "_director_aired", lambda a, b: rows):
            self.assertEqual(app.entry_own_aired("manager", 0.0, 240.0), 539.0)

    def test_an_entry_of_nothing_but_calls_reads_as_unanswered(self):
        rows = [aired("call", "manager", 120.0), aired("sfx", "manager", 9.0)]
        with mock.patch.object(app, "_director_aired", lambda a, b: rows):
            self.assertEqual(app.entry_own_aired("manager", 0.0, 240.0), 0.0)

    def test_a_road_keeps_its_own_sub_kinds(self):
        """An interjection is part of a banter round; a call is what the
        caller road puts out. Narrowing to the bare road name would have
        broken both."""
        rows = [aired("banter", "banter", 30.0),
                aired("interject", "banter", 6.0),
                aired("sfx", "banter", 4.0)]
        with mock.patch.object(app, "_director_aired", lambda a, b: rows):
            self.assertEqual(app.entry_own_aired("banter", 0.0, 240.0), 36.0)
        rows = [aired("call", "caller", 90.0), aired("sfx", "caller", 4.0)]
        with mock.patch.object(app, "_director_aired", lambda a, b: rows):
            self.assertEqual(app.entry_own_aired("caller", 0.0, 240.0), 90.0)


class ManagerDue(unittest.TestCase):
    """When the memo is due, and when it is emphatically not."""

    def test_his_own_entry_going_by_empty_makes_him_due(self):
        now = time.time()
        with mock.patch.object(app, "entry_window_now",
                               lambda: ("manager", now - 120, now + 120)), \
                mock.patch.object(app, "entry_own_aired",
                                  lambda k, a, b: 0.0):
            self.assertIn("none of him in it", app.manager_due_why())

    def test_an_entry_he_has_already_answered_is_not_due(self):
        now = time.time()
        with mock.patch.object(app, "entry_window_now",
                               lambda: ("manager", now - 120, now + 120)), \
                mock.patch.object(app, "entry_own_aired",
                                  lambda k, a, b: 96.0):
            self.assertEqual(app.manager_due_why(), "")

    def test_his_entry_is_his_from_the_moment_it_opens(self):
        """The operator chose "every entry": the memo is a fixture of the
        show, not something that happens if there is room left over. He
        used to have to wait a quarter of the window first, by which time
        a call had usually taken it - measured, that is exactly how a
        240-second entry ended with 0s of manager in it."""
        now = time.time()
        with mock.patch.object(app, "entry_window_now",
                               lambda: ("manager", now - 5, now + 235)), \
                mock.patch.object(app, "entry_own_aired",
                                  lambda k, a, b: 0.0):
            self.assertIn("none of him in it", app.manager_due_why())

    def test_he_breaks_in_anyway_when_the_road_has_gone_too_long(self):
        """The operator's real point: an entry that is permanently eaten
        is not a reason for the segment to stop existing."""
        now = time.time()
        with mock.patch.object(app, "entry_window_now",
                               lambda: ("gallery", now - 10, now + 100)), \
                mock.patch.object(app, "manager_last_aired",
                                  lambda: now - 3000), \
                mock.patch.object(app, "manager_break_after", lambda: 1500.0):
            self.assertIn("no memo has been on the air",
                          app.manager_due_why())

    def test_inside_the_window_he_waits(self):
        now = time.time()
        with mock.patch.object(app, "entry_window_now",
                               lambda: ("gallery", now - 10, now + 100)), \
                mock.patch.object(app, "manager_last_aired",
                                  lambda: now - 300), \
                mock.patch.object(app, "manager_break_after", lambda: 1500.0):
            self.assertEqual(app.manager_due_why(), "")


class EntryLedger(unittest.TestCase):
    """#1262: what the entry actually did, and what ate it if it did not.

    Short of material and being talked over take opposite cures, and
    every reading the orchestrator had could only see the first."""

    def test_an_eaten_entry_records_what_ate_it(self):
        rows = [aired("call", "manager", 140.0), aired("sfx", "manager", 20.0),
                aired("manager", "manager", 4.0)]
        with mock.patch.object(app, "_director_aired", lambda a, b: rows):
            got = app._entry_ledger_row({"kind": "manager", "start": 0.0,
                                         "deadline": 240.0, "stock": 19})
        self.assertFalse(got["served"])
        self.assertEqual(got["own"], 4)
        self.assertEqual(got["ate"], {"call": 140.0, "sfx": 20.0})
        self.assertEqual(got["stock"], 19)

    def test_a_served_entry_says_so(self):
        rows = [aired("manager", "manager", 96.0), aired("sfx", "manager", 3.0)]
        with mock.patch.object(app, "_director_aired", lambda a, b: rows):
            got = app._entry_ledger_row({"kind": "manager", "start": 0.0,
                                         "deadline": 240.0, "stock": 19})
        self.assertTrue(got["served"])

    def test_talked_over_and_starved_are_told_apart(self):
        """The whole value of the ledger. Same adherence, opposite cure."""
        talked = [{"road": "manager", "kind": "manager", "served": False,
                   "own": 0, "window": 240, "stock": 19,
                   "ate": {"call": 180.0}} for _ in range(5)]
        starved = [{"road": "gallery", "kind": "gallery", "served": False,
                    "own": 0, "window": 240, "stock": 0,
                    "ate": {}} for _ in range(5)]
        with mock.patch.object(app, "_entry_ledger_load",
                               lambda: talked + starved):
            got = app.schedule_lessons()
        book = {r["road"]: r for r in got["roads"]}
        self.assertIn("TALKED OVER", book["manager"]["lesson"])
        self.assertIn("call", book["manager"]["lesson"])
        self.assertIn("SHORT OF MATERIAL", book["gallery"]["lesson"])
        self.assertEqual(book["manager"]["adherence"], 0)

    def test_a_road_that_always_lands_is_not_reported_as_a_problem(self):
        good = [{"road": "ad", "kind": "ad", "served": True, "own": 40,
                 "window": 120, "stock": 8, "ate": {}} for _ in range(6)]
        with mock.patch.object(app, "_entry_ledger_load", lambda: good):
            got = app.schedule_lessons()
        seat = got["roads"][0]
        self.assertEqual(seat["adherence"], 100)
        self.assertEqual(seat["missed"], 0)
        self.assertIn("every time", seat["lesson"])


class EntryWindowReadsBothEngines(unittest.TestCase):
    """#1262: it could not read a System2 hour at all.

    A legacy slot carries `minutes`; a System2 occurrence carries `start`
    and `deadline` and no `minutes`, and System2 has been the default
    engine since #1070 - so `minutes <= 0` returned "no entry" on every
    call and FIVE separate rungs built on this window were dead:
    entry_own_aired, entry_arrears_note, the #1192 floor yield,
    entry_arrears_serve and the #1262 ledger.

    Found only because the ledger was made to say why it was empty. Both
    shapes are pinned here so the two engines cannot drift apart again.
    """

    def test_a_system2_occurrence_is_read(self):
        slot = {"kind": "manager", "start": 1000.0, "deadline": 1240.0,
                "id": "hour-06", "occurrence": "x", "engine": "system2"}
        with mock.patch.object(app, "schedule_take", lambda: slot),                 mock.patch.dict(app._RADIO, {"sched_pos": {}}, clear=False):
            self.assertEqual(app.entry_window_now(),
                             ("manager", 1000.0, 1240.0))

    def test_a_legacy_slot_is_still_read(self):
        slot = {"kind": "manager", "minutes": 4.0}
        with mock.patch.object(app, "schedule_take", lambda: slot),                 mock.patch.dict(app._RADIO,
                                {"sched_pos": {"started": 1000.0}},
                                clear=False):
            self.assertEqual(app.entry_window_now(),
                             ("manager", 1000.0, 1240.0))

    def test_no_clock_at_all_is_still_no_entry(self):
        with mock.patch.object(app, "schedule_take", lambda: {}),                 mock.patch.dict(app._RADIO, {"sched_pos": {}}, clear=False):
            self.assertEqual(app.entry_window_now(), ("", 0.0, 0.0))

    def test_a_kind_with_no_clock_is_refused_rather_than_guessed(self):
        """A window with no end is not a window. Guessing one would make
        every rung above it act on an entry that may already be over."""
        with mock.patch.object(app, "schedule_take",
                               lambda: {"kind": "manager"}),                 mock.patch.dict(app._RADIO, {"sched_pos": {}}, clear=False):
            self.assertEqual(app.entry_window_now(), ("", 0.0, 0.0))


class TheMemoClaimsTheNextRound(unittest.TestCase):
    """Fighting for the floor cannot work on this station.

    Measured live while this was being built: one booth round held the
    floor for 192 unbroken seconds - the whole of the manager's
    four-minute entry - with the break-in asking for it on every pass and
    the entry finally closing with none of him in it. `_TALK_CUT` ends a
    round at its next TURN BOUNDARY, and a fully banked round has none
    left: #1146 appends every line to the page at once and then holds the
    floor for its own measured airtime. There is nothing to cut, and a
    twenty-second poller waiting for a gap between rounds will not see
    one either.

    So the memo claims the NEXT round at the point the station chooses
    what to say - which is the same point the #1022 substitution is
    already allowed to overrule, and this outranks that.
    """

    def test_it_claims_when_due_with_a_finished_memo(self):
        with mock.patch.object(app, "manager_break_on", lambda: True),                 mock.patch.object(app, "manager_due_why", lambda: "his entry"),                 mock.patch.object(app, "_ready_shelf_row",
                                  lambda k, rescue=False, pick=None: {"x": 1}):
            self.assertEqual(app.manager_break_claim(), "his entry")

    def test_it_never_claims_without_a_finished_memo(self):
        """Announcing a memo that then fails to arrive is worse than not
        announcing one."""
        with mock.patch.object(app, "manager_break_on", lambda: True),                 mock.patch.object(app, "manager_due_why", lambda: "his entry"),                 mock.patch.object(app, "_ready_shelf_row",
                                  lambda k, rescue=False, pick=None: None),                 mock.patch.object(app, "manager_prepared_page", return_value=None):
            self.assertEqual(app.manager_break_claim(), "")

    def test_recorded_page_can_claim_even_when_shelf_is_empty(self):
        with mock.patch.object(app, "manager_break_on", return_value=True), \
                mock.patch.object(app, "manager_due_why", return_value="his entry"), \
                mock.patch.object(app, "_ready_shelf_row", return_value=None), \
                mock.patch.object(app, "manager_prepared_page",
                                  return_value={"id": "ready"}):
            self.assertEqual(app.manager_break_claim(), "his entry")

    def test_it_never_claims_when_nothing_is_due(self):
        with mock.patch.object(app, "manager_break_on", lambda: True),                 mock.patch.object(app, "manager_due_why", lambda: ""),                 mock.patch.object(app, "_ready_shelf_row",
                                  lambda k, rescue=False, pick=None: {"x": 1}):
            self.assertEqual(app.manager_break_claim(), "")

    def test_the_switch_turns_it_off(self):
        with mock.patch.object(app, "manager_break_on", lambda: False),                 mock.patch.object(app, "manager_due_why", lambda: "his entry"),                 mock.patch.object(app, "_ready_shelf_row",
                                  lambda k, rescue=False, pick=None: {"x": 1}):
            self.assertEqual(app.manager_break_claim(), "")

    def test_the_floor_is_asked_once_per_entry_not_once_per_pass(self):
        """The ask token carried the entry's AGE, which changes every
        pass, so "ask once" never matched: ten floor requests in three
        minutes, and the round on the floor ended at none of them."""
        import inspect
        src = inspect.getsource(app.manager_break_in)
        self.assertNotIn('token = "%s|%s" % (why[:40]', src)
        self.assertIn('"entry" if "own entry" in why else "waited"', src)


class EntryGuard(unittest.TestCase):
    """#1263: the entry on the sheet gets its own road first.

    The guard is conditioned on STOCK, and that condition is the whole
    safety argument: it only ever stands something down when there is a
    finished round ready to go out instead, so the air can never be
    emptier for it - only more like the sheet. A guard that could fire on
    an empty road would trade content for silence.
    """

    def setUp(self):
        app._ENTRY_GUARD_MEMO.update({"at": 0.0, "value": None})

    def test_it_holds_when_the_road_has_a_finished_round(self):
        now = time.time()
        with mock.patch.object(app, "entry_guard_on", lambda: True),                 mock.patch.object(app, "entry_window_now",
                                  lambda: ("manager", now - 30, now + 200)),                 mock.patch.object(app, "entry_own_aired", lambda k, a, b: 0.0),                 mock.patch.object(app, "_ready_shelf_row",
                                  lambda k, rescue=False, pick=None: {"x": 1}):
            self.assertEqual(app.entry_guard_road(), "manager")
            self.assertTrue(app.entry_guard_blocks("caller"))
            self.assertTrue(app.entry_guard_blocks("sfxguy"))
            self.assertFalse(app.entry_guard_blocks("manager"))

    def test_an_empty_road_is_never_guarded(self):
        """THE SAFETY PROPERTY. Guarding a road with nothing ready would
        hold the floor against everything and put nothing in its place."""
        now = time.time()
        with mock.patch.object(app, "entry_guard_on", lambda: True),                 mock.patch.object(app, "entry_window_now",
                                  lambda: ("manager", now - 30, now + 200)),                 mock.patch.object(app, "entry_own_aired", lambda k, a, b: 0.0),                 mock.patch.object(app, "_ready_shelf_row",
                                  lambda k, rescue=False, pick=None: None),                 mock.patch.object(app, "manager_prepared_page", return_value=None):
            self.assertEqual(app.entry_guard_road(), "")
            self.assertFalse(app.entry_guard_blocks("caller"))

    def test_recorded_manager_page_blocks_unrelated_call_and_sfx(self):
        now = time.time()
        with mock.patch.object(app, "entry_guard_on", return_value=True), \
                mock.patch.object(app, "entry_window_now",
                                  return_value=("manager", now - 30, now + 200)), \
                mock.patch.object(app, "entry_own_aired", return_value=0.0), \
                mock.patch.object(app, "_ready_shelf_row", return_value=None), \
                mock.patch.object(app, "manager_prepared_page",
                                  return_value={"id": "ready"}):
            self.assertEqual(app.entry_guard_road(), "manager")
            self.assertTrue(app.entry_guard_blocks("caller"))
            self.assertTrue(app.entry_guard_blocks("sfxguy"))
            self.assertFalse(app.entry_guard_blocks("manager"))

    def test_the_guard_lifts_once_the_road_has_aired(self):
        """It buys the road its turn, not the whole entry."""
        now = time.time()
        with mock.patch.object(app, "entry_guard_on", lambda: True),                 mock.patch.object(app, "entry_window_now",
                                  lambda: ("manager", now - 30, now + 200)),                 mock.patch.object(app, "entry_own_aired", lambda k, a, b: 96.0),                 mock.patch.object(app, "_ready_shelf_row",
                                  lambda k, rescue=False, pick=None: {"x": 1}):
            self.assertEqual(app.entry_guard_road(), "")

    def test_the_switch_turns_it_off(self):
        now = time.time()
        with mock.patch.object(app, "entry_guard_on", lambda: False),                 mock.patch.object(app, "entry_window_now",
                                  lambda: ("manager", now - 30, now + 200)),                 mock.patch.object(app, "entry_own_aired", lambda k, a, b: 0.0),                 mock.patch.object(app, "_ready_shelf_row",
                                  lambda k, rescue=False, pick=None: {"x": 1}):
            self.assertEqual(app.entry_guard_road(), "")


class OrchestratorActs(unittest.TestCase):
    """#1264: "act, then tell me" - and the two cures are opposite."""

    def setUp(self):
        app._LESSON_APPLIED.update({"at": 0.0, "rows": []})

    def _run(self, rows):
        moved = {}
        with mock.patch.object(app, "lessons_apply_on", lambda: True),                 mock.patch.object(app, "_entry_ledger_load", lambda: rows),                 mock.patch.object(app, "_policy_set",
                                  lambda k, v: moved.__setitem__(k, v)),                 mock.patch.object(app, "judgment_note",
                                  lambda *a, **k: None),                 mock.patch.object(app, "note_action", lambda *a, **k: None),                 mock.patch.object(app, "pipeline_log", lambda *a, **k: None):
            done = app.lessons_apply()
        return done, moved

    def test_a_talked_over_road_gets_the_guard_not_more_writing(self):
        rows = [{"road": "manager", "kind": "manager", "served": False,
                 "own": 0, "window": 240, "stock": 19,
                 "ate": {"call": 180.0}} for _ in range(6)]
        done, moved = self._run(rows)
        self.assertEqual(len(done), 1)
        self.assertTrue(moved.get("entry_guard"))
        self.assertEqual(moved.get("thin_road"), "call")
        self.assertNotIn("drive_road", moved)

    def test_a_starved_road_gets_built_not_guarded(self):
        rows = [{"road": "gallery", "kind": "gallery", "served": False,
                 "own": 0, "window": 240, "stock": 0, "ate": {}}
                for _ in range(6)]
        done, moved = self._run(rows)
        self.assertEqual(moved.get("drive_road"), "gallery")
        self.assertNotIn("entry_guard", moved)

    def test_a_road_that_lands_is_left_alone(self):
        rows = [{"road": "ad", "kind": "ad", "served": True, "own": 40,
                 "window": 120, "stock": 8, "ate": {}} for _ in range(6)]
        done, moved = self._run(rows)
        self.assertEqual(done, [])
        self.assertEqual(moved, {})

    def test_it_will_not_act_on_too_few_entries(self):
        """One bad entry is an anecdote."""
        rows = [{"road": "manager", "kind": "manager", "served": False,
                 "own": 0, "window": 240, "stock": 19,
                 "ate": {"call": 180.0}} for _ in range(2)]
        done, moved = self._run(rows)
        self.assertEqual(done, [])


if __name__ == "__main__":
    unittest.main()
