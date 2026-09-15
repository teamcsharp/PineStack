# -*- coding: utf-8 -*-
"""#1169/#1170: a modifier has an id, rides the round, and traces both ways.

The operator, inbox #1169:

    "I want to be able to trace these things across the segments happening
    to the segments as modifiers for their events when they are occurring."

Everything here runs off a TemporaryDirectory.  Nothing reads or writes
data/, the script ledger, the air log or any other live store, and nothing
makes a model call, opens a socket or touches the station: the whole point
of putting the desk in a pure module was that its behaviour could be
asserted without any of that.

The six the request names, and where each is asserted:

    an id survives a restart          IdentityIsDurable
    a round under two modifiers
        names both                    TheRide.test_a_round_written_under_two...
    a segment names what shaped it    TheRide.test_a_segment_names_...
    a modifier names every segment    TheTrace.test_a_modifier_names_every...
    an expired modifier stops riding   Expiry
    the switch off changes nothing    TheSwitch

plus WiredIntoTheStation, which asserts the patch actually hangs the module
off app.py in the places the request names - a desk nothing calls is the
#1146 failure mode, and a test that only exercises the library would not
notice it.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import station_modifiers as sm        # noqa: E402
except ImportError:                       # the patch has not been applied yet
    raise unittest.SkipTest(
        "station_modifiers.py is not in the tree - run "
        "tools/patch_modifiers_1169.py --check")


# --- a clock the tests own ------------------------------------------------
class Clock:
    def __init__(self, at=1_000_000.0):
        self.at = float(at)

    def __call__(self):
        return self.at

    def tick(self, seconds):
        self.at += float(seconds)
        return self.at


# --- the station, as far as a modifier can see it -------------------------
class Desk:
    """The five calls app.py makes, and nothing else.

    A deliberately thin stand-in: ride() where the sid is minted, ids_for()
    in the ledger row and the air-log row, named ids in the inspector.  If
    this harness and the patch ever disagree, WiredIntoTheStation is the
    test that says so."""

    def __init__(self, root, clock, mode=sm.MODE_RIDE):
        self.clock = clock
        self.book = sm.ModifierBook(root, clock=clock)
        self.switch = sm.ModifierSwitch(Path(root) / "modifiers", clock=clock,
                                        env={})
        self.switch.write(mode)
        self.ledger = []              # script_ledger.jsonl
        self.air = []                 # air_log.jsonl

    # what modifiers_trace_on()/modifiers_air_on() do
    def traces(self):
        return self.switch.traces()

    def airs(self):
        return self.switch.airs()

    def write_round(self, sid, kind="banter", lines=(), heard=True):
        """One round: mint, ride, write the ledger rows, air the lines."""
        rode = self.book.ride(sid, None) if self.traces() else []
        mods = self.book.ids_for(sid) if self.traces() else []
        for ord_, (who, text) in enumerate(lines):
            row = {"block": 1, "ord": ord_, "at": self.clock(), "sid": sid,
                   "round": kind, "who": who, "text": text, "seconds": 3.0}
            if mods:
                row["mods"] = list(mods)
            self.ledger.append(row)
            air = {"id": "%s-%d" % (sid, ord_), "sid": sid, "who": who,
                   "round": kind, "text": text, "seconds": 3.0,
                   "air_at": self.clock(),
                   "aired": "stream" if heard else "prepared"}
            if mods:
                air["mods"] = list(mods)
            self.air.append(air)
        return rode

    def inspect(self, sid):
        """segment_inspect's new key, built the way the patch builds it."""
        return sm.trace_segments([], []) if False else [
            {"id": one, "kind": sm.split_id(one)[0],
             "name": (self.book.get(one) or {}).get("name") or ""}
            for one in (self.book.ids_for(sid) if self.traces() else [])]

    def trace(self, mid):
        rides = self.book.rides_for(mid)
        return sm.trace_segments(rides, self.air)


# --------------------------------------------------------------------------
class Identity(unittest.TestCase):

    def test_a_guest_keeps_the_id_its_own_store_gave_it(self):
        """#1169 asks for a code, not a second book. guests.json already
        says 4f959ea0; the modifier id must be built out of that and not
        replace it."""
        self.assertEqual(sm.modifier_id("guest", "4f959ea0"), "guest:4f959ea0")
        self.assertEqual(sm.split_id("guest:4f959ea0"), ("guest", "4f959ea0"))

    def test_an_event_is_the_one_kind_that_gets_a_key_minted(self):
        """The station holds these as bare names in caller_themes.json, so
        the key is derived from the name - same name, same key, for ever."""
        first = sm.name_key("Vaporized")
        self.assertTrue(first)
        self.assertEqual(first, sm.name_key("  vaporized  "))
        self.assertNotEqual(first, sm.name_key("Broth"))

    def test_a_thing_that_is_not_one_of_the_four_has_no_id(self):
        self.assertEqual(sm.modifier_id("weather", "abc"), "")
        self.assertFalse(sm.is_modifier_id("weather:abc"))
        self.assertFalse(sm.is_modifier_id("4f959ea0"))
        self.assertFalse(sm.is_modifier_id(""))

    def test_a_key_cannot_smuggle_a_separator_into_the_id(self):
        mid = sm.modifier_id("topic", "a:b/c d")
        self.assertEqual(sm.split_id(mid)[0], "topic")
        self.assertNotIn(":", sm.split_id(mid)[1])


class IdentityIsDurable(unittest.TestCase):
    """An id survives a restart."""

    def test_an_id_raised_before_a_restart_is_the_same_id_after_one(self):
        clock = Clock()
        with tempfile.TemporaryDirectory() as root:
            book = sm.ModifierBook(root, clock=clock)
            row = book.raise_(sm.KIND_GUEST, "e40ad093", "Sticky Nick")
            mid, raised = row["id"], row["raised"]
            self.assertTrue(Path(root, "modifiers.json").exists())

            clock.tick(60)
            fresh = sm.ModifierBook(root, clock=clock)     # the restart
            again = fresh.get(mid)
            self.assertEqual(again["id"], mid)
            self.assertEqual(again["name"], "Sticky Nick")
            self.assertEqual(again["raised"], raised,
                             "a restart must not restamp when it was raised")
            self.assertTrue(sm.record_standing(again, clock()))

    def test_the_ride_ledger_survives_a_restart_too(self):
        clock = Clock()
        with tempfile.TemporaryDirectory() as root:
            book = sm.ModifierBook(root, clock=clock)
            book.raise_(sm.KIND_PLOT, "04fb434bf97a", "Wanted Dead Or Alive")
            book.ride("1d209523f1ee")
            fresh = sm.ModifierBook(root, clock=clock)
            self.assertEqual(fresh.ids_for("1d209523f1ee"),
                             ["plot:04fb434bf97a"])

    def test_a_torn_book_is_an_empty_book_and_never_an_exception(self):
        """Colour may not take the station off the air: a half-written or
        junk store has to read as nothing, not raise."""
        with tempfile.TemporaryDirectory() as root:
            Path(root, "modifiers.json").write_text("{not json", encoding="utf-8")
            Path(root, "modifier_rides.jsonl").write_text(
                '{"sid":"aa","ids":["guest:1"]}\n{"sid":"bb",', encoding="utf-8")
            book = sm.ModifierBook(root)
            self.assertEqual(book.all(), [])
            self.assertEqual(book.ids_for("aa"), ["guest:1"])
            self.assertEqual(book.ids_for("bb"), [])

    def test_the_book_is_written_whole_or_not_at_all(self):
        """courier_write's pattern. A reader that opens the file mid-save
        must never see half a book."""
        with tempfile.TemporaryDirectory() as root:
            book = sm.ModifierBook(root)
            book.raise_(sm.KIND_TOPIC, "2a2919f9", "feeding the beast")
            rows = json.loads(Path(root, "modifiers.json").read_text(
                encoding="utf-8"))
            self.assertEqual(len(rows), 1)
            self.assertEqual([p.name for p in Path(root).glob("*.tmp")], [])


class TheRide(unittest.TestCase):

    def setUp(self):
        self.clock = Clock()
        self._tmp = tempfile.TemporaryDirectory()
        self.desk = Desk(self._tmp.name, self.clock)
        self.book = self.desk.book

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_round_written_under_two_modifiers_names_both(self):
        guest = self.book.raise_(sm.KIND_GUEST, "e40ad093", "Sticky Nick")
        plot = self.book.raise_(sm.KIND_PLOT, "04fb434bf97a", "HandPan Maniac")
        rode = self.desk.write_round("sid-two", lines=[("dj", "hello"),
                                                       ("third", "hi")])
        self.assertEqual(sorted(rode), sorted([guest["id"], plot["id"]]))
        for row in self.desk.ledger:
            self.assertEqual(sorted(row["mods"]),
                             sorted([guest["id"], plot["id"]]))
        for row in self.desk.air:
            self.assertEqual(sorted(row["mods"]),
                             sorted([guest["id"], plot["id"]]))

    def test_a_segment_names_the_modifiers_that_shaped_it(self):
        """The inspector's direction: from a segment back to the modifier."""
        self.book.raise_(sm.KIND_EVENT, sm.name_key("Vaporized"), "Vaporized")
        self.desk.write_round("sid-one", lines=[("dj", "a")])
        named = self.desk.inspect("sid-one")
        self.assertEqual([n["kind"] for n in named], ["event"])
        self.assertEqual([n["name"] for n in named], ["Vaporized"])

    def test_a_segment_written_under_nothing_names_nothing(self):
        self.desk.write_round("sid-bare", lines=[("dj", "a")])
        self.assertEqual(self.desk.inspect("sid-bare"), [])
        self.assertNotIn("mods", self.desk.ledger[0])
        self.assertNotIn("mods", self.desk.air[0])

    def test_one_round_rides_once_however_often_it_is_asked(self):
        self.book.raise_(sm.KIND_TOPIC, "2a2919f9", "feeding the beast")
        first = self.book.ride("sid-x")
        again = self.book.ride("sid-x")
        self.assertEqual(first, again)
        rows = [json.loads(l) for l in
                Path(self._tmp.name, "modifier_rides.jsonl").read_text(
                    encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(rows), 1)

    def test_a_ride_row_is_an_id_list_and_never_a_copy_of_the_thing(self):
        """"Keep it small - an id list, not a copy of the thing." The
        plotline's title, acts and running account must not end up in a
        ledger that is written once per round."""
        self.book.raise_(sm.KIND_PLOT, "04fb434bf97a",
                         "Wanted Dead Or Alive: Bla The HandPan Maniac",
                         note="Act 3: the whole world collapses")
        self.book.ride("sid-small")
        raw = Path(self._tmp.name, "modifier_rides.jsonl").read_text(
            encoding="utf-8")
        self.assertIn("plot:04fb434bf97a", raw)
        self.assertNotIn("HandPan", raw)
        self.assertNotIn("collapses", raw)
        self.assertLess(len(raw), 200)

    def test_a_round_with_no_sid_rides_nothing(self):
        self.book.raise_(sm.KIND_GUEST, "e40ad093", "Sticky Nick")
        self.assertEqual(self.book.ride(""), [])
        self.assertEqual(self.book.ride("   "), [])


class TheTrace(unittest.TestCase):

    def setUp(self):
        self.clock = Clock()
        self._tmp = tempfile.TemporaryDirectory()
        self.desk = Desk(self._tmp.name, self.clock)
        self.book = self.desk.book
        self.guest = self.book.raise_(sm.KIND_GUEST, "e40ad093", "Sticky Nick")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_modifier_names_every_segment_it_touched(self):
        self.desk.write_round("sid-1", lines=[("dj", "a"), ("third", "b")])
        self.clock.tick(120)
        self.desk.write_round("sid-2", lines=[("dj", "c")])
        self.clock.tick(120)
        self.desk.write_round("sid-3", lines=[("dj", "d")])
        got = self.desk.trace(self.guest["id"])
        self.assertEqual([s["sid"] for s in got], ["sid-1", "sid-2", "sid-3"])
        self.assertEqual([s["lines"] for s in got], [2, 1, 1])
        self.assertTrue(all(s["heard"] for s in got))

    def test_the_trace_says_which_of_them_were_actually_heard(self):
        """#1239: "written" and "heard" are different answers, and a trace
        that conflates them is how a fault stays invisible for two days."""
        self.desk.write_round("sid-heard", lines=[("dj", "a")], heard=True)
        self.clock.tick(60)
        self.desk.write_round("sid-refused", lines=[("dj", "b")], heard=False)
        got = {s["sid"]: s for s in self.desk.trace(self.guest["id"])}
        self.assertTrue(got["sid-heard"]["heard"])
        self.assertFalse(got["sid-refused"]["heard"])
        self.assertEqual(got["sid-refused"]["heard_lines"], 0)
        self.assertIn("refused or withdrawn", got["sid-refused"]["say"])

    def test_a_segment_that_never_reached_the_air_log_says_so(self):
        self.book.ride("sid-ghost")
        got = self.desk.trace(self.guest["id"])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["lines"], 0)
        self.assertFalse(got[0]["heard"])
        self.assertIn("not one line of it reached the air log", got[0]["say"])

    def test_the_trace_names_the_seats_that_spoke_under_it(self):
        """The evidence #1169 actually wants: not that a guest was raised,
        but that the third seat opened its mouth while he was in it."""
        self.desk.write_round("sid-1", lines=[("dj", "a"), ("third", "b"),
                                              ("cohost", "c")])
        got = self.desk.trace(self.guest["id"])
        self.assertEqual(got[0]["seats"], ["cohost", "dj", "third"])

    def test_a_modifier_that_rode_nothing_says_that_plainly(self):
        summary = sm.trace_summary(self.guest, [])
        self.assertEqual(summary["segments"], 0)
        self.assertIn("has not ridden a single segment", summary["say"])

    def test_a_modifier_that_rode_and_was_never_heard_shouts_about_it(self):
        self.desk.write_round("sid-1", lines=[("dj", "a")], heard=False)
        segs = self.desk.trace(self.guest["id"])
        summary = sm.trace_summary(self.guest, segs)
        self.assertEqual(summary["heard"], 0)
        self.assertEqual(summary["written_never_heard"], 1)
        self.assertIn("NOT ONE of them was heard", summary["say"])

    def test_one_segment_traces_back_to_each_of_its_modifiers(self):
        plot = self.book.raise_(sm.KIND_PLOT, "04fb434bf97a", "HandPan")
        self.desk.write_round("sid-shared", lines=[("dj", "a")])
        for mid in (self.guest["id"], plot["id"]):
            self.assertEqual([s["sid"] for s in self.desk.trace(mid)],
                             ["sid-shared"])


class Expiry(unittest.TestCase):
    """A modifier that expired stops riding."""

    def setUp(self):
        self.clock = Clock()
        self._tmp = tempfile.TemporaryDirectory()
        self.desk = Desk(self._tmp.name, self.clock)
        self.book = self.desk.book

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_topic_stops_riding_once_it_has_stood_its_time(self):
        topic = self.book.raise_(sm.KIND_TOPIC, "2a2919f9", "the beast",
                                 stands_s=600.0)
        self.assertEqual(self.desk.write_round("sid-early",
                                               lines=[("dj", "a")]),
                         [topic["id"]])
        self.clock.tick(601)
        self.assertEqual(self.desk.write_round("sid-late",
                                               lines=[("dj", "b")]), [])
        self.assertEqual(self.desk.inspect("sid-late"), [])
        self.assertNotIn("mods", self.desk.ledger[-1])

    def test_an_expired_modifier_keeps_the_segments_it_already_touched(self):
        """It stops riding; it does not stop being traceable. #1169 asks for
        the segments a guest touched, not for the guest to be forgotten the
        moment he leaves the building."""
        guest = self.book.raise_(sm.KIND_GUEST, "e40ad093", "Sticky Nick",
                                 stands_s=300.0)
        self.desk.write_round("sid-while-here", lines=[("dj", "a")])
        self.clock.tick(301)
        self.desk.write_round("sid-after", lines=[("dj", "b")])
        self.assertFalse(sm.record_standing(self.book.get(guest["id"]),
                                            self.clock()))
        self.assertEqual([s["sid"] for s in self.desk.trace(guest["id"])],
                         ["sid-while-here"])

    def test_a_guest_sent_home_stops_riding_at_once(self):
        guest = self.book.raise_(sm.KIND_GUEST, "e40ad093", "Sticky Nick")
        self.assertTrue(sm.record_standing(self.book.get(guest["id"]),
                                           self.clock()))
        self.book.drop(guest["id"])
        self.assertEqual(self.desk.write_round("sid-gone",
                                               lines=[("dj", "a")]), [])

    def test_a_guest_stands_until_dropped_and_not_on_a_timer(self):
        guest = self.book.raise_(sm.KIND_GUEST, "e40ad093", "Sticky Nick")
        self.assertEqual(guest["until"], 0.0)
        self.clock.tick(86400 * 3)
        self.assertTrue(sm.record_standing(self.book.get(guest["id"]),
                                           self.clock()))

    def test_raising_a_thing_that_came_back_is_a_new_raise(self):
        first = self.book.raise_(sm.KIND_EVENT, "abc", "Broth", stands_s=100.0)
        self.clock.tick(200)
        again = self.book.raise_(sm.KIND_EVENT, "abc", "Broth", stands_s=100.0)
        self.assertEqual(first["id"], again["id"])
        self.assertGreater(again["raised"], first["raised"])

    def test_re_raising_while_it_still_stands_does_not_restamp_it(self):
        first = self.book.raise_(sm.KIND_EVENT, "abc", "Broth", stands_s=1000.0)
        self.clock.tick(10)
        again = self.book.raise_(sm.KIND_EVENT, "abc", "Broth", stands_s=1000.0)
        self.assertEqual(again["raised"], first["raised"])
        self.assertGreater(again["until"], first["until"])


class TheSwitch(unittest.TestCase):
    """The switch off changes nothing."""

    def test_a_missing_switch_file_is_off(self):
        with tempfile.TemporaryDirectory() as root:
            switch = sm.ModifierSwitch(Path(root) / "modifiers", env={})
            self.assertEqual(switch.mode(), sm.MODE_OFF)
            self.assertFalse(switch.traces())
            self.assertFalse(switch.airs())

    def test_an_empty_or_unreadable_or_misspelt_switch_is_off(self):
        for text in ("", "   ", "ON_PLEASE", "yes", "1", "tracee", "\n\n"):
            with tempfile.TemporaryDirectory() as root:
                switch = sm.ModifierSwitch(Path(root) / "modifiers", env={},
                                           ttl=0.0)
                switch.write(text)
                self.assertEqual(switch.mode(), sm.MODE_OFF,
                                 "%r must not be read as permission" % (text,))

    def test_trace_records_ids_and_does_not_reach_the_air(self):
        clock = Clock()
        with tempfile.TemporaryDirectory() as root:
            desk = Desk(root, clock, mode=sm.MODE_TRACE)
            desk.book.raise_(sm.KIND_GUEST, "e40ad093", "Sticky Nick")
            self.assertTrue(desk.traces())
            self.assertFalse(desk.airs())
            self.assertEqual(desk.write_round("sid-1", lines=[("dj", "a")]),
                             ["guest:e40ad093"])

    def test_with_the_switch_off_nothing_rides_and_no_row_changes(self):
        clock = Clock()
        with tempfile.TemporaryDirectory() as root:
            desk = Desk(root, clock, mode="off")
            desk.book.raise_(sm.KIND_GUEST, "e40ad093", "Sticky Nick")
            desk.book.raise_(sm.KIND_PLOT, "04fb434bf97a", "HandPan")
            self.assertEqual(desk.write_round("sid-1", lines=[("dj", "a"),
                                                              ("third", "b")]),
                             [])
            self.assertEqual(desk.inspect("sid-1"), [])
            for row in desk.ledger + desk.air:
                self.assertNotIn("mods", row)
            self.assertFalse(Path(root, "modifier_rides.jsonl").exists())

    def test_with_the_switch_off_the_prompt_gains_not_one_character(self):
        with tempfile.TemporaryDirectory() as root:
            book = sm.ModifierBook(root)
            book.raise_(sm.KIND_GUEST, "e40ad093", "Sticky Nick")
            switch = sm.ModifierSwitch(Path(root) / "modifiers", env={})
            # this is exactly what modifiers_clause() does
            clause = (sm.standing_clause(book.standing())
                      if switch.airs() else "")
            self.assertEqual(clause, "")

    def test_the_switch_takes_effect_without_a_restart(self):
        clock = Clock()
        with tempfile.TemporaryDirectory() as root:
            switch = sm.ModifierSwitch(Path(root) / "modifiers", env={},
                                       ttl=3.0, clock=clock)
            switch.write("off")
            self.assertEqual(switch.mode(), sm.MODE_OFF)
            Path(root, "modifiers", "mode").write_text("ride\n",
                                                       encoding="utf-8")
            clock.tick(4)                 # one TTL later, same process
            self.assertEqual(switch.mode(), sm.MODE_RIDE)

    def test_on_is_read_the_kindest_way(self):
        with tempfile.TemporaryDirectory() as root:
            switch = sm.ModifierSwitch(Path(root) / "modifiers", env={})
            switch.write("on")
            self.assertEqual(switch.mode(), sm.MODE_RIDE)


class WhatTheWriterHears(unittest.TestCase):

    def test_nothing_standing_costs_the_prompt_nothing(self):
        self.assertEqual(sm.standing_clause([]), "")

    def test_the_clause_never_contains_the_id(self):
        """A presenter who reads "guest:e40ad093" out loud has said the
        quiet part. The id is a ledger fact, not a line."""
        rows = [sm.make_record(sm.KIND_GUEST, "e40ad093", "Sticky Nick", 0.0),
                sm.make_record(sm.KIND_PLOT, "04fb434bf97a", "HandPan", 0.0)]
        clause = sm.standing_clause(rows)
        self.assertIn("Sticky Nick", clause)
        self.assertIn("HandPan", clause)
        self.assertNotIn("e40ad093", clause)
        self.assertNotIn("guest:", clause)

    def test_the_clause_tells_the_writer_not_to_say_the_code(self):
        rows = [sm.make_record(sm.KIND_GUEST, "e40ad093", "Sticky Nick", 0.0)]
        self.assertIn("identifier out loud", sm.standing_clause(rows))

    def test_a_modifier_with_no_name_cannot_colour_anything(self):
        rows = [sm.make_record(sm.KIND_TOPIC, "2a2919f9", "", 0.0)]
        self.assertEqual(sm.standing_clause(rows), "")


class DeadAir(unittest.TestCase):
    """#1170: "whenever there's dead air ... these are things that are said
    on the station that also get codes and IDs"."""

    def test_every_gap_line_carries_the_id_it_came_from(self):
        rows = [sm.make_record(sm.KIND_GUEST, "e40ad093", "Sticky Nick", 0.0),
                sm.make_record(sm.KIND_PLOT, "04fb434bf97a", "HandPan", 0.0),
                sm.make_record(sm.KIND_EVENT, "abc", "Vaporized", 0.0)]
        lines = sm.gap_lines(rows)
        self.assertEqual(len(lines), 3)
        for line in lines:
            self.assertTrue(sm.is_modifier_id(line["id"]))
            self.assertIn(line["name"], line["text"])

    def test_a_guest_in_the_room_is_what_the_gap_says_first(self):
        rows = [sm.make_record(sm.KIND_GUEST, "e40ad093", "Sticky Nick", 0.0)]
        self.assertIn("Sticky Nick", sm.gap_lines(rows)[0]["text"])

    def test_nothing_standing_means_nothing_to_say(self):
        self.assertEqual(sm.gap_lines([]), [])


class FollowingTheLiveStores(unittest.TestCase):
    """The four stores stay the truth; the desk reads them.

    Fixtures below are the SHAPES measured on the live station on
    2026-09-15, not invented ones."""

    GUESTS = [{"id": "4f959ea0", "name": "Billy Badass",
               "who": "Homeless fighter", "why": "...", "voice": ""},
              {"id": "e40ad093", "name": "Sticky Nick",
               "who": "Sticky icky nick.", "why": "...",
               "voice": "vl_13c3d7cd"}]
    PLOTS = [{"id": "04fb434bf97a",
              "title": "Wanted Dead Or Alive: Bla The HandPan Maniac",
              "acts": ["Act 1: a handpanner is loose in the city.",
                       "Act 2: the police are seduced by the handpan.",
                       "Act 3: the world collapses into handpanners."],
              "act_idx": 2, "active": True, "done": False,
              "span_minutes": 60.0, "started_at": 1_000_000.0,
              "act_live": 3}]
    THEMES = {"active": "Vaporized",
              "themes": [{"name": "Vaporized", "text": "Im going to enter..."},
                         {"name": "Broth", "text": "A strange man..."}]}
    TOPICS = [{"id": "2a2919f9", "text": "Everything we show is a lie.",
               "kind": "topic", "added": 999_000, "used": 0},
              {"id": "c813ea9d", "text": "We are all feeding the beast.",
               "kind": "topic", "added": 999_000, "used": 1,
               "last": 1_000_000.0}]

    def test_guest_mode_off_means_no_guest_is_standing(self):
        """The measured state of the station: guests.json holds five and
        dj.guest_mode is False, so not one of them is in the room."""
        got = sm.from_stores(guests=self.GUESTS,
                             dj={"guest_mode": False, "guest_id": ""},
                             now=1_000_000.0)
        self.assertEqual([r for r in got if r["kind"] == sm.KIND_GUEST], [])

    def test_the_seated_guest_is_the_one_dj_settings_names(self):
        got = sm.from_stores(guests=self.GUESTS,
                             dj={"guest_mode": True, "guest_id": "e40ad093"},
                             now=1_000_000.0)
        guests = [r for r in got if r["kind"] == sm.KIND_GUEST]
        self.assertEqual(len(guests), 1)
        self.assertEqual(guests[0]["key"], "e40ad093")
        self.assertEqual(guests[0]["name"], "Sticky Nick")
        self.assertEqual(guests[0]["stands_s"], 0.0)

    def test_the_active_plotline_stands_for_what_is_left_of_its_span(self):
        got = sm.from_stores(plotlines=self.PLOTS, now=1_000_000.0 + 600)
        plots = [r for r in got if r["kind"] == sm.KIND_PLOT]
        self.assertEqual(len(plots), 1)
        self.assertEqual(plots[0]["key"], "04fb434bf97a")
        self.assertAlmostEqual(plots[0]["stands_s"], 3000.0, places=1)
        self.assertIn("Act 3", plots[0]["note"])

    def test_a_finished_plotline_does_not_stand(self):
        done = [dict(self.PLOTS[0], done=True)]
        self.assertEqual(sm.from_stores(plotlines=done, now=1_000_000.0), [])

    def test_the_active_theme_becomes_an_event_with_a_stable_key(self):
        got = sm.from_stores(themes=self.THEMES, now=1_000_000.0)
        events = [r for r in got if r["kind"] == sm.KIND_EVENT]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["name"], "Vaporized")
        self.assertEqual(events[0]["key"], sm.name_key("Vaporized"))
        again = sm.from_stores(themes=self.THEMES, now=2_000_000.0)
        self.assertEqual(again[0]["key"], events[0]["key"])

    def test_a_topic_the_station_has_never_said_is_stock_not_colour(self):
        got = sm.from_stores(topics=self.TOPICS, now=1_000_000.0)
        topics = [r for r in got if r["kind"] == sm.KIND_TOPIC]
        self.assertEqual([t["key"] for t in topics], ["c813ea9d"])

    def test_a_store_that_is_missing_or_junk_contributes_nothing(self):
        self.assertEqual(sm.from_stores(), [])
        self.assertEqual(sm.from_stores(guests="not a list", dj="nope",
                                        topics=17, plotlines={"a": 1},
                                        themes=[1, 2, 3]), [])

    def test_the_stores_put_things_up_and_take_them_down_again(self):
        clock = Clock()
        with tempfile.TemporaryDirectory() as root:
            book = sm.ModifierBook(root, clock=clock)
            seated = {"guest_mode": True, "guest_id": "e40ad093"}
            out = sm.follow_stores(book, sm.from_stores(
                guests=self.GUESTS, dj=seated, plotlines=self.PLOTS,
                now=clock()), now=clock())
            self.assertIn("guest:e40ad093", out["standing"])
            self.assertIn("plot:04fb434bf97a", out["standing"])

            clock.tick(30)                       # the guest is sent home
            gone = {"guest_mode": False, "guest_id": ""}
            out = sm.follow_stores(book, sm.from_stores(
                guests=self.GUESTS, dj=gone, plotlines=self.PLOTS,
                now=clock()), now=clock())
            self.assertEqual(out["down"], ["guest:e40ad093"])
            self.assertNotIn("guest:e40ad093", out["standing"])
            self.assertIn("plot:04fb434bf97a", out["standing"])

    def test_the_stores_never_take_down_a_hand_raise(self):
        """An operator who raised a thing by hand outranks a store that has
        never heard of it (#206: a person outranks the show)."""
        clock = Clock()
        with tempfile.TemporaryDirectory() as root:
            book = sm.ModifierBook(root, clock=clock)
            book.raise_(sm.KIND_EVENT, "byhand", "The cat in the sewer",
                        source="")
            out = sm.follow_stores(book, [], now=clock())
            self.assertEqual(out["down"], [])
            self.assertIn("event:byhand", out["standing"])


class WiredIntoTheStation(unittest.TestCase):
    """The desk is hung where the request says it must be hung.

    Asserted against the PATCH SCRIPT's own hunk text rather than a
    paraphrase, because the failure this guards against is not a wrong
    implementation - it is a correct one that nothing calls (#1146, the
    rung that waits for a floor that never comes)."""

    @classmethod
    def setUpClass(cls):
        """Import the patch script and read the text it will actually write,
        not the escaped source of the string literals that hold it."""
        import importlib.util
        here = Path(__file__).resolve().parent.parent
        found = None
        for candidate in (here / "tools" / "patch_modifiers_1169.py",
                          here / "patch_modifiers_1169.py"):
            if candidate.exists():
                found = candidate
                break
        if found is None:
            raise unittest.SkipTest("the patch script is not in the tree")
        spec = importlib.util.spec_from_file_location("_patch1169", found)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls.patch = mod
        cls.hunks = {name: (old, new) for name, old, new in mod.hunks()}
        cls.src = mod.FACADE + mod.ROUTES + "".join(
            new for _n, _o, new in mod.hunks())

    def after(self, name):
        """The text one hunk puts into app.py."""
        self.assertIn(name, self.hunks, "no hunk called %r" % name)
        return self.hunks[name][1]

    def test_the_module_is_imported_at_all(self):
        self.assertIn("import station_modifiers", self.after("import"))

    def test_the_ids_ride_at_the_moment_the_sid_is_minted(self):
        was, now = self.hunks["ride"]
        self.assertIn("_round_sid = uuid.uuid4().hex[:12]", was)
        self.assertNotIn("modifiers_ride_round", was)
        self.assertIn("modifiers_ride_round(_round_sid)", now)

    def test_the_ids_land_in_the_script_ledger_row(self):
        self.assertIn('"mods": _mods', self.after("ledger"))
        self.assertIn("_mods = modifiers_for_sid(", self.after("ledger-lookup"))

    def test_the_ids_land_in_the_air_log_row(self):
        now = self.after("airlog")
        self.assertIn('row["mods"] = _mods', now)
        self.assertIn('modifiers_for_sid(str(row.get("sid")', now)

    def test_the_inspector_gains_the_reverse_direction(self):
        self.assertIn('"modifiers": []}', self.after("inspect-skel"))
        self.assertIn('out["modifiers"] = modifiers_named(',
                      self.after("inspect-fill"))

    def test_the_trace_route_exists(self):
        routes = self.patch.ROUTES
        for route in ('@app.get("/api/modifier/trace")',
                      '@app.get("/api/modifiers")',
                      '@app.post("/api/modifier/raise")',
                      '@app.post("/api/modifier/drop")'):
            self.assertIn(route, routes)

    def test_the_prompt_hears_it_on_the_layer_every_road_assembles(self):
        was, now = self.hunks["prompt"]
        self.assertIn("lead += plot_clause()", was)
        self.assertIn("lead += modifiers_clause()", now)

    def test_the_dead_air_fill_is_handed_what_is_standing(self):
        self.assertIn("modifiers_gap_context()", self.after("gap-talk"))
        self.assertIn("modifiers_gap_sid()", self.after("gap-sid"))
        self.assertIn("sid=_mod_sid", self.after("gap-sid"))

    def test_what_airs_is_behind_the_switch(self):
        for guarded in ("def modifiers_clause",
                        "def modifiers_gap_context",
                        "def modifiers_seat_guest"):
            body = self.patch.FACADE.split(guarded, 1)[1][:1400]
            self.assertIn("modifiers_air_on()", body,
                          "%s must be behind the switch" % guarded)

    def test_what_only_records_is_behind_the_switch_too(self):
        for guarded in ("def modifiers_ride_round", "def modifiers_for_sid"):
            body = self.patch.FACADE.split(guarded, 1)[1][:1400]
            self.assertIn("modifiers_trace_on()", body)

    def test_the_switch_defaults_off(self):
        body = self.patch.FACADE.split("def modifiers_mode", 1)[1][:400]
        self.assertIn("return station_modifiers.MODE_OFF", body)

    def test_the_guest_is_actually_seated(self):
        """The measured reason the third seat spoke three times in a day:
        nothing in the running station ever called set_guest, and every door
        into that seat is behind `if dj["third_name"]`."""
        self.assertIn("set_guest(guest)", self.patch.FACADE)
        self.assertIn("third_name", self.patch.FACADE)
        was, now = self.hunks["caller-to-guest"]
        self.assertNotIn("set_guest", was)
        self.assertIn("set_guest(guest)", now)
        self.assertIn("modifiers_air_on()", now)

    def test_a_single_line_may_name_its_segment_without_anyone_asking(self):
        """The sid kwarg defaults empty, so every existing caller of
        dj_speak produces exactly the entry it produced before."""
        self.assertIn('sid: str = ""', self.after("speak-sig"))
        self.assertIn('sid: str = ""', self.after("floorless-sig"))
        self.assertIn('**({"sid": str(sid)} if sid else {}),',
                      self.after("entry-sid"))

    def test_every_hunk_only_adds_and_none_is_a_no_op(self):
        """A hunk that deletes app.py's own text is a hunk that can lose
        another writer's work. Two other people are editing this file."""
        for name, (was, now) in self.hunks.items():
            self.assertNotEqual(was, now, name)
            self.assertGreater(len(now), len(was), name)

    def test_the_hunks_round_trip(self):
        """--revert has to give back the bytes that were there, so apply
        then revert must be the identity on a fixture holding every
        anchor."""
        fixture = "".join(was for _n, was, _now in self.patch.hunks())
        blob = fixture.encode("utf-8")
        there = self.patch.apply_all(blob, forward=True)
        self.assertNotEqual(there, blob)
        back = self.patch.apply_all(there, forward=False)
        self.assertEqual(back, blob)

    def test_the_patch_refuses_an_anchor_it_cannot_find(self):
        with self.assertRaises(SystemExit):
            self.patch.apply_all(b"nothing in here at all\n", forward=True)


if __name__ == "__main__":
    unittest.main()
