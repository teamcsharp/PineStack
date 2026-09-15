"""#1164: the manager has a seat, a segment named after him, and no voice.

    "I am noticing some of the scripts missing entire segments, for
     example the manager is supposed to call during the manager's
     segment."  - the operator

Measured before any of this was written. Over twenty-four hours the air
log carries 1,176 rows of manager segment, spoken by dj (5,048 rows
across the night) and cohost (3,714), and ZERO rows whose speaker is
`manager`. booth_actor_name has known how to name that seat since #749
and cast_signature has read dj.manager_voice since #1057; neither has
ever been heard, and dj.manager_voice could never even be SET, because
the dj settings dict is a wholesale rebuild and the key was not in it.

So the manager rings the booth and reads the memo down the phone in his
own voice, behind a switch that defaults off.

These tests pin the six things that would fail silently and still look
correct on a panel:

  * that the switch OFF is not a new road at all - the memo goes out
    through exactly the call dj_manager_note has always made, with no
    seat, no caller and no phone anywhere near it;
  * that the switch ON puts the MANAGER SEAT on the rows, all the way
    from dj_banter's argument to the marker map that decides `who`;
  * that one round still books exactly ONE memo, and that re-airing the
    same memo updates the row it already has rather than growing a twin;
  * that the round is written to FIT its entry - and, when the entry
    cannot hold a call, that the road stands down instead of writing one
    that will be refused for length;
  * that the screenplay reads ring -> his lines -> hang-up, in that
    order, with the memo at the head of the segment;
  * that a manager seat with no pinned voice falls back LOUDLY, and that
    a manager with no voice at all does not borrow a host's.

Nothing here touches the live script ledger or data/: every path is a
temp file and every station road is a mock.
"""
import asyncio
import inspect
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import app

# Captured before any test can patch it: one test wants the REAL book.
REAL_MEMO_SAVE = app.manager_memo_save


def run(coro):
    """One coroutine, on its own loop. asyncio.to_thread needs a running
    loop, and the memo book is written through one."""
    return asyncio.run(coro)


class Recorder:
    """A stand-in for dj_banter that remembers how it was called."""

    def __init__(self, lines=None):
        self.lines = list(lines if lines is not None else
                          ["C: The memo is on my desk.",
                           "A: We heard you.",
                           "C: Then hear it again.",
                           "B: He hung up."])
        self.calls = []

    async def __call__(self, *a, **kw):
        self.calls.append({"args": a, "kw": dict(kw)})
        return list(self.lines)

    @property
    def kw(self):
        return self.calls[-1]["kw"]


def manager_note_world(gripe="", topic="", note="Spin more records."):
    """Everything dj_manager_note touches on the way to the memo, stubbed
    so the test is about the one decision it is about."""
    dj = {"manager_gripe_pct": 0 if not gripe else 100,
          "manager_topic_pct": 0 if not topic else 100,
          "manager_name": "Mr Vance", "manager_voice": "",
          "call_stream": True, "banter": True}
    return [
        mock.patch.object(app, "dj_settings", lambda: dict(dj)),
        mock.patch.object(app, "talk_is_incessant", lambda *a, **k: False),
        mock.patch.object(app, "shelf_take", lambda *a, **k: None),
        mock.patch.object(app, "booth_hot", lambda: 20.0),
        mock.patch.object(app, "station_disposition_text", lambda *a: note),
        mock.patch.object(app, "radio_prompt_instruction", lambda *a: ""),
        mock.patch.object(app, "crystal_tint_two_pass", lambda: True),
        mock.patch.object(app, "crystal_active", lambda: []),
        mock.patch.object(
            app, "upstairs_list",
            lambda: ([{"id": "g1", "gripe": gripe, "uses": 0}]
                     if gripe else [])),
        mock.patch.object(app, "upstairs_update", lambda *a, **k: None),
        mock.patch.object(app, "drop_bombshell", lambda: {"text": topic}),
        mock.patch.object(app, "quota_stamp", lambda *a, **k: None),
        mock.patch.object(app, "manager_memo_save", lambda *a, **k: None),
        mock.patch.object(app, "pipeline_log", lambda *a, **k: None),
    ]


class Base(unittest.TestCase):

    def stack(self, patches):
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

    def switch(self, value):
        """Point the switch at a temp file holding `value` (None = the
        file does not exist at all, which is the shipped state)."""
        d = Path(tempfile.mkdtemp(prefix="pine1164-"))
        path = d / "manager_calls_in"
        if value is not None:
            path.write_text(value)
        self.stack([mock.patch.object(app, "MANAGER_CALL_SWITCH_PATH", path)])
        # The reader memoises for MANAGER_CALL_SWITCH_EVERY seconds; each
        # test gets a cold cache so it reads the file it was just given.
        app._MANAGER_CALL_SWITCH.update({"at": 0.0, "on": False,
                                         "said": None})
        self.addCleanup(lambda: app._MANAGER_CALL_SWITCH.update(
            {"at": 0.0, "on": False, "said": None}))
        return path


# ---------------------------------------------------------------------------
class TheSwitch(Base):
    """off, on, and everything that is not the word "on"."""

    def test_missing_file_is_off(self):
        """The shipped state. Nothing under data/, nothing changes."""
        self.switch(None)
        self.assertFalse(app.manager_calls_in())

    def test_off_is_off_and_on_is_on(self):
        for word, want in (("off", False), ("on", True), ("ON\n", True),
                           ("  on  ", True), ("", False), ("yes", False),
                           ("1", False)):
            with self.subTest(word=word):
                self.switch(word)
                self.assertIs(app.manager_calls_in(), want)

    def test_it_is_re_read_without_a_restart(self):
        """The whole point of a file rather than a setting: the operator
        turns him on, hears him, turns him off, all inside one segment."""
        path = self.switch("off")
        self.assertFalse(app.manager_calls_in())
        path.write_text("on")
        app._MANAGER_CALL_SWITCH["at"] = 0.0      # the five seconds pass
        self.assertTrue(app.manager_calls_in())
        path.write_text("off")
        app._MANAGER_CALL_SWITCH["at"] = 0.0
        self.assertFalse(app.manager_calls_in())

    def test_an_unreadable_switch_is_an_off_switch(self):
        """A share that hiccups must never put a man on the phone."""
        self.switch("on")
        self.assertTrue(app.manager_calls_in())
        app._MANAGER_CALL_SWITCH["at"] = 0.0
        with mock.patch.object(type(app.MANAGER_CALL_SWITCH_PATH),
                               "read_text",
                               side_effect=OSError("the share blinked")):
            self.assertFalse(app.manager_calls_in())


# ---------------------------------------------------------------------------
class SwitchOffChangesNothing(Base):
    """#1164 (5): "The old memo-read road must remain exactly as it is
    when the switch is off - byte-for-byte the same behaviour."

    So this asserts the SHAPE of the call dj_manager_note has always
    made: three lines, whole, own material, no bank, and - the part that
    would give the new road away - no caller, no voice, no seat."""

    def test_the_memo_road_is_the_memo_road(self):
        self.switch("off")
        banter = Recorder(["A: a memo landed", "B: it did"])
        self.stack(manager_note_world() +
                   [mock.patch.object(app, "dj_banter", banter),
                    mock.patch.object(app, "_manager_rings_booth",
                                      mock.AsyncMock())])
        said = run(app.dj_manager_note(None))
        self.assertEqual(said, ["A: a memo landed", "B: it did"])
        self.assertEqual(len(banter.calls), 1)
        kw = banter.kw
        self.assertEqual(kw["lines"], 3)
        self.assertTrue(kw["whole"])
        self.assertTrue(kw["own_material"])
        self.assertIsNone(kw["bank_to"])
        for absent in ("caller_name", "caller_voice", "caller_seat",
                       "caller_fx"):
            self.assertNotIn(absent, kw,
                             "%s reached the memo road with the switch off"
                             % absent)
        self.assertIn("memo", kw["angle"].lower())
        app._manager_rings_booth.assert_not_awaited()

    def test_the_phone_is_never_lifted_with_the_switch_off(self):
        """Not merely "no call aired" - the line is never even taken, so
        a real caller cannot be blocked by a segment that is not calling
        anybody."""
        self.switch("off")
        took = []
        self.stack(manager_note_world() +
                   [mock.patch.object(app, "dj_banter", Recorder(["A: x"])),
                    mock.patch.object(app, "call_line_take",
                                      lambda *a, **k: took.append(a) or True)])
        run(app.dj_manager_note(None))
        self.assertEqual(took, [])

    def test_the_preparer_never_rings_anybody(self):
        """bank_to is the preparation road. A banked memo is written to be
        READ - there is nobody in the room to answer a phone an hour from
        now - so the call road must not touch it even switched on."""
        self.switch("on")
        banter = Recorder(["A: banked memo"])
        pile = []
        self.stack(manager_note_world() +
                   [mock.patch.object(app, "dj_banter", banter),
                    mock.patch.object(app, "_manager_rings_booth",
                                      mock.AsyncMock())])
        run(app.dj_manager_note(None, bank_to=pile))
        app._manager_rings_booth.assert_not_awaited()
        self.assertNotIn("caller_seat", banter.kw)


# ---------------------------------------------------------------------------
class TheManagerSeat(Base):
    """#1164 (1): the manager is a caller with a different seat."""

    def test_the_seat_reaches_dj_banter(self):
        self.switch("on")
        banter = Recorder()
        self.stack(manager_note_world() +
                   [mock.patch.object(app, "dj_banter", banter),
                    mock.patch.object(app, "manager_call_turns_for_slot",
                                      lambda: 4),
                    mock.patch.object(app, "manager_call_voice",
                                      mock.AsyncMock(
                                          return_value=("v-boss", True))),
                    mock.patch.object(app, "call_line_take",
                                      lambda *a, **k: True),
                    mock.patch.object(app, "call_ended",
                                      lambda *a, **k: None)])
        said = run(app.dj_manager_note(None))
        self.assertTrue(said)
        kw = banter.kw
        self.assertEqual(kw["caller_seat"], "manager")
        self.assertEqual(kw["caller_name"], "Mr Vance")
        self.assertEqual(kw["caller_voice"], "v-boss")
        self.assertEqual(kw["lines"], 4)
        # The words the brief will look for have to be ASKED for.
        low = kw["angle"].lower()
        for word in ("on the line", "memo", "upstairs", "'c: ...'"):
            self.assertIn(word, low, "the angle never asks for %r" % word)

    def test_he_reads_the_memo_the_round_already_had(self):
        """#1164 (2): "The memo text the round already has is what he
        says." Not a new memo written for the phone - the same material
        the memo road would have handed the pair, including #1173's
        gripe out of the upstairs book and #1244's topic off the
        operator's board. The segment is the same segment; the only
        thing that changed is who is saying it."""
        self.switch("on")
        banter = Recorder()
        self.stack(manager_note_world(gripe="the lunch breaks are out of "
                                            "hand",
                                      topic="that business with the van") +
                   [mock.patch.object(app, "dj_banter", banter),
                    mock.patch.object(app, "manager_call_turns_for_slot",
                                      lambda: 5),
                    mock.patch.object(app, "manager_call_voice",
                                      mock.AsyncMock(
                                          return_value=("v-boss", True))),
                    mock.patch.object(app, "call_line_take",
                                      lambda *a, **k: True),
                    mock.patch.object(app, "call_ended",
                                      lambda *a, **k: None)])
        run(app.dj_manager_note(None))
        angle = banter.kw["angle"]
        self.assertIn("the lunch breaks are out of hand", angle)
        self.assertIn("that business with the van", angle)
        self.assertEqual(banter.kw["caller_seat"], "manager")

    def test_the_seat_is_carried_on_the_round_entry(self):
        """dj_banter -> entry -> _banter_air -> speak_turns is the chain,
        and the entry is the only thing that survives between them."""
        self.assertIn("caller_seat", inspect.signature(app.dj_banter)
                      .parameters)
        self.assertEqual(inspect.signature(app.dj_banter)
                         .parameters["caller_seat"].default, "caller")
        self.assertIn("caller_seat", inspect.signature(app.speak_turns)
                      .parameters)
        self.assertEqual(inspect.signature(app.speak_turns)
                         .parameters["caller_seat"].default, "caller")
        src = inspect.getsource(app.dj_banter)
        self.assertIn('"caller_seat": caller_seat', src)
        air = inspect.getsource(app._banter_air)
        self.assertIn('caller_seat=str(', air)
        self.assertIn('entry.get("caller_seat") or "caller"', air)

    def test_the_marker_map_really_seats_him(self):
        """The last link, executed rather than asserted about.

        `_who_of` is a closure inside _speak_turns_floorless - it is the
        one line that decides what `who` a 'C:' turn airs under, and the
        air row, the name, the voice and the round are all written off
        it. This lifts that exact text out of the shipped file and runs
        it, so a change to the map fails here."""
        src = inspect.getsource(app._speak_turns_floorless).split("\n")
        at = next((i for i, ln in enumerate(src)
                   if ln.strip().startswith("def _who_of(")), -1)
        self.assertGreater(at, -1, "_who_of has gone")
        ret = next((i for i in range(at, len(src))
                    if src[i].strip().startswith("return (")), -1)
        self.assertGreater(ret, -1, "_who_of's return has moved")
        end = next(i for i in range(ret, len(src))
                   if src[i].rstrip().endswith('else "cohost")'))
        body = ("def _who_of(marker, caller_seat):\n"
                + "\n".join(src[ret:end + 1]) + "\n")
        self.assertIn("caller_seat if marker ==", body)
        ns = {}
        exec(compile(body, "<who_of>", "exec"), ns)          # noqa: S102
        who_of = ns["_who_of"]
        self.assertEqual(who_of("C", "manager"), "manager")
        self.assertEqual(who_of("C", "caller"), "caller")
        # ...and nobody else moved seat.
        for marker, seat in (("A", "dj"), ("B", "cohost"), ("D", "third"),
                             ("E", "caller2")):
            self.assertEqual(who_of(marker, "manager"), seat)

    def test_every_seat_decision_reads_the_seat(self):
        """Every decision downstream of the marker map that would
        otherwise still say "caller".

        There are nine of them and they are easy to miss, which is why
        this is a test and not a comment: the voice the engine is asked
        for on both roads, the phone rack, the name and voice on the air
        row, the name on the call archive's transcript and on the stream
        rows, and - the one that hides longest - the list of seats whose
        aired lines are REMEMBERED. A seat left out of that last one is
        a speaker who can repeat himself for ever and whose rows System2
        is never told aired.

        And the turn-by-turn road, which most of the show does not use
        and which therefore nobody watches: there, a manager left out
        airs dry, unnamed, and filed as an "interject"."""
        src = inspect.getsource(app._speak_turns_floorless)
        for want in ('caller_voice if who == caller_seat',
                     'item["who"] == caller_seat',
                     'item["who"] in (caller_seat, "caller2")',
                     'caller_name if who == caller_seat',
                     '"caller2", "drop", caller_seat)',
                     '"call" if who == caller_seat else "interject"',
                     'fx=phone_fx if who == caller_seat else None',
                     'name=caller_name if who == caller_seat else ""'):
            self.assertIn(want, src, "a seat decision still hard-codes "
                                     "the caller: %s" % want)
        self.assertNotIn('if who == "caller"', src)
        self.assertNotIn('item["who"] == "caller"', src)
        # booth_actor_name is called three times in here, at three
        # different indents - the air row, the call archive's transcript
        # and the stream rows - and all three take the same decision.
        # Patch two of the three and the transcript disagrees with the
        # air about who was speaking, which is a bug that reads as a
        # panel glitch for weeks.
        #
        # Asserted as "all of them", not "three of them": two sessions
        # edit this file, and a test that pins a count breaks on somebody
        # else's unrelated fourth caller. The invariant is that every
        # booth_actor_name call in here reads the seat.
        named = src.count('"name": booth_actor_name(')
        seated = src.count("who, caller_name if who == caller_seat")
        self.assertGreaterEqual(named, 3)
        self.assertEqual(seated, named,
                         "%d of %d booth_actor_name calls read the seat; "
                         "the rest still hard-code the caller"
                         % (seated, named))

    def test_the_memo_entry_is_not_relabelled_a_phone_call(self):
        """airlog_round_now answers "caller" for anything carrying a
        caller name, and _banter_air's hint says "a caller name beats
        everything". Unmasked, the whole manager segment would have
        filed itself in the air log as a caller round and the screenplay
        would have played it on the phone-line set."""
        src = inspect.getsource(app._speak_turns_floorless)
        self.assertIn('caller_name if caller_seat == "caller" else ""', src)
        air = inspect.getsource(app._banter_air)
        self.assertIn('or "caller") == "caller"', air)
        banter = inspect.getsource(app.dj_banter)
        self.assertIn('"prep_kind": (caller_seat if caller_name '
                      'and caller_seat != "caller"', banter)


# ---------------------------------------------------------------------------
class OneMemoPerRound(Base):
    """#1164 (2): "still book exactly one memo per round, still update
    the same row"."""

    def book(self):
        d = Path(tempfile.mkdtemp(prefix="pine1164-memo-"))
        path = d / "manager_memos.json"
        self.stack([mock.patch.object(app, "MANAGER_MEMOS_PATH", path)])
        return path

    def test_one_round_books_one_memo(self):
        path = self.book()
        self.switch("on")
        banter = Recorder()
        self.stack(manager_note_world() +
                   [mock.patch.object(app, "dj_banter", banter),
                    mock.patch.object(app, "manager_call_turns_for_slot",
                                      lambda: 4),
                    mock.patch.object(app, "manager_call_voice",
                                      mock.AsyncMock(
                                          return_value=("v-boss", True))),
                    mock.patch.object(app, "call_line_take",
                                      lambda *a, **k: True),
                    mock.patch.object(app, "call_ended",
                                      lambda *a, **k: None)])
        # the real book, deliberately - this is the thing under test
        self.stack([mock.patch.object(app, "manager_memo_save",
                                      REAL_MEMO_SAVE)])
        run(app.dj_manager_note(None))
        rows = json.loads(path.read_text())
        self.assertEqual(len(rows), 1, "a call booked %d memos" % len(rows))
        self.assertEqual(rows[0]["uses"], 1)
        self.assertEqual(rows[0]["how"], "call")

    def test_re_airing_the_same_memo_updates_the_same_row(self):
        """The #1146 archive rule: the shelf is inventory, this is the
        permanent book, and an aired twin stamps the original's ledger
        rather than writing a second memo."""
        path = self.book()
        text = "A: management wants it quiet\nB: they always do"
        first = app.manager_memo_save(text, "call", True, "", 1000.0)
        again = app.manager_memo_save(text, "call", True, "", 2000.0)
        rows = json.loads(path.read_text())
        self.assertEqual(len(rows), 1)
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(rows[0]["uses"], 2)

    def test_the_memo_is_stamped_where_the_round_began(self):
        """#1162: the screenplay places "a memo comes down from
        upstairs" at this row's ts. Stamped at the RECEIPT it lands after
        every line that reads it - measured at 7m 12s after the first
        line of its own round, which is past the end of the segment. So
        the call road stamps the moment the phone rang."""
        path = self.book()
        began = time.time() - 300.0
        app.manager_memo_save("A: a memo\nB: a memo", "call", True, "", began)
        rows = json.loads(path.read_text())
        self.assertEqual(rows[0]["ts"], int(began))
        self.assertLess(rows[0]["ts"], time.time() - 200)

    def test_the_road_stamps_the_start_not_the_receipt(self):
        """...and that the call road actually passes it."""
        seen = {}

        def save(text, how="", aired=False, memo_id="", at=0.0):
            seen.update({"text": text, "how": how, "aired": aired, "at": at})
            return {"id": "m1"}

        self.switch("on")
        self.stack(manager_note_world() +
                   [mock.patch.object(app, "dj_banter", Recorder()),
                    mock.patch.object(app, "manager_memo_save", save),
                    mock.patch.object(app, "manager_call_turns_for_slot",
                                      lambda: 4),
                    mock.patch.object(app, "manager_call_voice",
                                      mock.AsyncMock(
                                          return_value=("v-boss", True))),
                    mock.patch.object(app, "call_line_take",
                                      lambda *a, **k: True),
                    mock.patch.object(app, "call_ended",
                                      lambda *a, **k: None)])
        before = time.time()
        run(app.dj_manager_note(None))
        self.assertTrue(seen.get("aired"))
        self.assertGreaterEqual(seen["at"], before)
        self.assertLessEqual(seen["at"], time.time())


# ---------------------------------------------------------------------------
class ItFitsItsEntry(Base):
    """#1164 (6): "a call that adds a ring, a hang-up and two extra turns
    must be written to FIT."

    Tonight's measurement is rounds being refused for length - "the
    gallery round runs 196s and its entry has 92s left". The ring and the
    hang-up cost nothing (they are action lines off the call ledger, not
    speech), so the only thing to size is the turns."""

    def entry(self, owns):
        self.stack([
            mock.patch.object(app, "_RADIO",
                              dict(app._RADIO, sched_slot={"kind": "manager",
                                                           "minutes": 3})),
            mock.patch.object(app, "sched_entry_left", lambda: owns),
            mock.patch.object(app, "coord_upcoming", lambda *a: []),
            mock.patch.object(app, "call_turn_seconds", lambda: 12.0),
        ])

    def test_the_turns_are_written_to_land_inside_the_entry(self):
        for owns in (70.0, 90.0, 120.0, 180.0, 240.0, 600.0):
            with self.subTest(owns=owns):
                self.entry(owns)
                turns = app.manager_call_turns_for_slot()
                self.assertGreaterEqual(turns, app.MANAGER_CALL_TURNS_MIN)
                self.assertLessEqual(turns, app.MANAGER_CALL_TURNS_MAX)
                runs = turns * 12.0 + app.MANAGER_CALL_TOP_AND_TAIL
                self.assertLessEqual(
                    runs, owns,
                    "a %d-turn call runs %.0fs in an entry with %.0fs left"
                    % (turns, runs, owns))

    def test_an_entry_too_short_for_a_call_gets_the_memo(self):
        """Not a shorter call - no call. Below four turns there is
        nothing a listener would call a phone call, and the segment the
        station already knows how to make is better than a bad new one."""
        for owns in (20.0, 40.0, 60.0, 65.0):
            with self.subTest(owns=owns):
                self.entry(owns)
                self.assertEqual(app.manager_call_turns_for_slot(), 0)

    def test_no_room_means_the_memo_road_runs(self):
        self.switch("on")
        banter = Recorder()
        logs = []
        self.stack(manager_note_world() +
                   [mock.patch.object(app, "dj_banter", banter),
                    mock.patch.object(app, "manager_call_turns_for_slot",
                                      lambda: 0),
                    mock.patch.object(app, "sched_entry_left", lambda: 30.0),
                    mock.patch.object(app, "call_line_take",
                                      lambda *a, **k: True),
                    mock.patch.object(app, "pipeline_log",
                                      lambda *a, **k: logs.append(a))])
        said = run(app.dj_manager_note(None))
        self.assertTrue(said)
        self.assertNotIn("caller_seat", banter.kw)      # the memo road
        self.assertTrue(any("1164" in str(a) for a in logs),
                        "the road stood down without saying why")

    def test_no_sheet_running_is_unrestricted(self):
        """Exactly what the caller road does with an absent schedule:
        take the floor rather than refuse."""
        self.stack([
            mock.patch.object(app, "_RADIO", dict(app._RADIO, sched_slot={})),
            mock.patch.object(app, "sched_entry_left", lambda: 0.0),
            mock.patch.object(app, "coord_upcoming", lambda *a: []),
        ])
        self.assertEqual(app.manager_call_turns_for_slot(),
                         app.MANAGER_CALL_TURNS_MIN)

    def test_a_throw_in_the_call_road_names_itself_and_hands_over(self):
        """#1219's lesson applied on the way in: a NEW road in front of a
        road that works must not take the segment off the air, and must
        not swallow the reason either. The memo runs; the fault is named
        with its type; and the phone is hung up on the way out so the
        line cannot be left showing busy (#977)."""
        logs = []
        freed = []

        async def boom(*a, **k):
            raise RuntimeError("the writing desk fell over")

        self.switch("on")
        memo = Recorder(["A: a memo landed", "B: it did"])
        calls = {"n": 0}

        async def banter(*a, **k):
            calls["n"] += 1
            if k.get("caller_seat") == "manager":
                return await boom()
            return await memo(*a, **k)

        self.stack(manager_note_world() +
                   [mock.patch.object(app, "dj_banter", banter),
                    mock.patch.object(app, "manager_call_turns_for_slot",
                                      lambda: 4),
                    mock.patch.object(app, "manager_call_voice",
                                      mock.AsyncMock(
                                          return_value=("v-boss", True))),
                    mock.patch.object(app, "call_line_take",
                                      lambda *a, **k: True),
                    mock.patch.object(app, "call_ended",
                                      lambda *a, **k: freed.append(a)),
                    mock.patch.object(app, "pipeline_log",
                                      lambda *a, **k: logs.append(
                                          " ".join(str(x) for x in a)))])
        said = run(app.dj_manager_note(None))
        self.assertEqual(said, ["A: a memo landed", "B: it did"])
        self.assertEqual(calls["n"], 2)          # the call, then the memo
        shout = [ln for ln in logs if "THREW" in ln]
        self.assertTrue(shout, "the throw was swallowed: %r" % logs)
        self.assertIn("RuntimeError", shout[0])
        self.assertIn("the writing desk fell over", shout[0])
        self.assertTrue(freed, "the phone was left off the hook")

    def test_a_busy_line_is_not_barged(self):
        """The phone is one phone. A caller on it outranks a memo."""
        self.switch("on")
        banter = Recorder()
        self.stack(manager_note_world() +
                   [mock.patch.object(app, "dj_banter", banter),
                    mock.patch.object(app, "manager_call_turns_for_slot",
                                      lambda: 4),
                    mock.patch.object(app, "manager_call_voice",
                                      mock.AsyncMock(
                                          return_value=("v-boss", True))),
                    mock.patch.object(app, "call_line_take",
                                      lambda *a, **k: False),
                    mock.patch.object(app, "call_line_busy",
                                      lambda: "Toothpick Eddie")])
        said = run(app.dj_manager_note(None))
        self.assertTrue(said)
        self.assertNotIn("caller_seat", banter.kw)


# ---------------------------------------------------------------------------
class TheScreenplayReadsIt(Base):
    """#1164: the ring and the hang-up are ACTION, drawn off the call
    ledger, which is why they cost the entry nothing and why they have to
    be there at all."""

    def test_ring_lines_and_hangup_in_reading_order(self):
        began, ended = 1_000_000.0, 1_000_090.0
        d = {"records": [], "ads": [], "pauses": [], "papers": [],
             "model_calls": [],
             "calls": [{"at": began, "ends": ended, "name": "Mr Vance",
                        "line": app.MANAGER_CALL_LINE,
                        "topic": "a memo from upstairs", "seconds": 90.0,
                        "turns": 4, "rule": "he puts the phone down",
                        "hostile": False, "id": "c1"}],
             "memos": [{"at": began, "text": "spin more records"}],
             "air": []}
        acts = app._screenplay_actions(d, began - 10, ended + 10)
        acts.sort(key=lambda e: e["at"])
        tags = [a["tag"] for a in acts]
        self.assertIn("call", tags)
        self.assertIn("hangup", tags)
        self.assertIn("memo", tags)
        ring = next(a for a in acts if a["tag"] == "call")
        hang = next(a for a in acts if a["tag"] == "hangup")
        memo = next(a for a in acts if a["tag"] == "memo")
        self.assertIn("The phone rings. Mr Vance is on", ring["text"])
        self.assertIn(app.MANAGER_CALL_LINE, ring["text"])
        self.assertIn("Mr Vance hangs up after", hang["text"])
        self.assertIn("a memo comes down from upstairs",
                      memo["text"].lower())
        # The memo and the ring open the segment; the hang-up closes it,
        # and the manager's own lines sit between the two.
        self.assertEqual(memo["at"], began)
        self.assertEqual(ring["at"], began)
        self.assertGreater(hang["at"], ring["at"])

    def test_actions_sort_ahead_of_speech_at_the_same_instant(self):
        """The screenplay sorts on (at, sort) with actions at 0 - so the
        ring prints ABOVE the first line of the call rather than beside
        it. Pinned because a reader who sees the ring after the first
        line is reading a different scene."""
        acts = app._screenplay_actions(
            {"calls": [{"at": 5.0, "ends": 9.0, "name": "Mr Vance",
                        "line": "x", "seconds": 4.0, "turns": 2, "id": "c"}],
             "memos": [], "records": [], "ads": [], "pauses": [],
             "papers": [], "model_calls": [], "air": []}, 0.0, 20.0)
        events = ([{"at": 5.0, "sort": 1, "what": "line"}]
                  + [{"at": a["at"], "sort": 0, "what": "action"}
                     for a in acts])
        events.sort(key=lambda e: (e["at"], e["sort"]))
        self.assertEqual(events[0]["what"], "action")


# ---------------------------------------------------------------------------
class TheVoiceFallsBackLoudly(Base):
    """#1164 (3): "If no voice is pinned for that seat, fall back the way
    the station falls back elsewhere and SAY SO in a log line rather than
    silently using a DJ voice."

    Worth saying plainly: dj.manager_voice could not be SET before this
    patch. cast_signature has read it since #1057, the panel has had a
    manager_name field since #749, and the dj settings dict is a
    wholesale rebuild that dropped both on every save - the file's own
    comments name that trap twice. So the patch puts both keys in the
    rebuild, and this is the test that the seat's voice is a voice you
    can actually pin."""

    def test_a_pinned_voice_is_used_as_pinned(self):
        self.stack([mock.patch.object(
            app, "dj_settings", lambda: {"manager_voice": "v-pinned",
                                         "manager_name": "Mr Vance"})])
        voice, pinned = run(app.manager_call_voice())
        self.assertEqual(voice, "v-pinned")
        self.assertTrue(pinned)

    def test_an_unpinned_seat_draws_a_voice_and_says_so(self):
        logs = []
        self.switch("on")
        self.stack(manager_note_world() +
                   [mock.patch.object(app, "dj_banter", Recorder()),
                    mock.patch.object(app, "manager_call_turns_for_slot",
                                      lambda: 4),
                    mock.patch.object(app, "caller_line_voice",
                                      mock.AsyncMock(return_value="v-drawn")),
                    mock.patch.object(app, "voice_friendly",
                                      lambda v: "Gravel"),
                    mock.patch.object(app, "call_line_take",
                                      lambda *a, **k: True),
                    mock.patch.object(app, "call_ended", lambda *a, **k: None),
                    mock.patch.object(app, "pipeline_log",
                                      lambda *a, **k: logs.append(
                                          " ".join(str(x) for x in a)))])
        said = run(app.dj_manager_note(None))
        self.assertTrue(said)
        shout = [ln for ln in logs if "NO VOICE IS PINNED" in ln]
        self.assertTrue(shout, "the seat fell back in silence: %r" % logs)
        self.assertIn("manager_voice", shout[0])

    def test_the_drawn_voice_is_never_a_hosts(self):
        """caller_line_voice is the station's own answer to "a stranger
        needs a voice", and #559 is the reason: it refuses the host's and
        the co-host's. The manager goes through that same door rather
        than through a default, which is what stops him sounding like
        the man he is telling off."""
        src = inspect.getsource(app.manager_call_voice)
        self.assertIn("caller_line_voice", src)

    def test_no_voice_at_all_sends_the_memo_instead(self):
        """The one thing that must never happen: a manager on the air in
        a host's voice. With nothing to ring in with, he does not ring."""
        logs = []
        self.switch("on")
        banter = Recorder()
        self.stack(manager_note_world() +
                   [mock.patch.object(app, "dj_banter", banter),
                    mock.patch.object(app, "manager_call_turns_for_slot",
                                      lambda: 4),
                    mock.patch.object(app, "caller_line_voice",
                                      mock.AsyncMock(return_value="")),
                    mock.patch.object(app, "call_line_take",
                                      lambda *a, **k: True),
                    mock.patch.object(app, "pipeline_log",
                                      lambda *a, **k: logs.append(
                                          " ".join(str(x) for x in a)))])
        said = run(app.dj_manager_note(None))
        self.assertTrue(said)                       # the segment still airs
        self.assertNotIn("caller_seat", banter.kw)  # ...as the memo road
        self.assertTrue([ln for ln in logs if "no voice to" in ln],
                        "he fell back to the memo without saying why")

    def test_the_seat_keys_survive_a_settings_save(self):
        """The wholesale-rebuild trap, pinned. Both keys go in and both
        come back out; before this patch manager_name went in and
        vanished, which is why five roads read a setting nobody could
        set."""
        src = inspect.getsource(app)
        self.assertIn('"manager_voice": str(raw_dj.get("manager_voice")', src)
        self.assertIn('"manager_name": str(raw_dj.get("manager_name")', src)
        self.assertIn('"manager_voice": ""', src)      # DEFAULT_DJ
        self.assertEqual(app.DEFAULT_DJ.get("manager_voice"), "")
        self.assertEqual(app.DEFAULT_DJ.get("manager_name"), "")


# ---------------------------------------------------------------------------
class TheBriefIsHonest(Base):
    """#1164 (4): "keep its `any` word list honest: if you add 'on the
    line' style markers, they must be words the new round really
    produces"."""

    def test_the_brief_describes_both_shapes(self):
        brief = app.SEGMENT_BRIEF["manager"]
        want = brief["want"].lower()
        self.assertIn("memo", want)
        self.assertIn("phoned down", want)
        for word in ("on the line", "the phone", "hangs up"):
            self.assertIn(word, brief["any"])

    def test_the_memo_road_still_passes_its_own_brief(self):
        """The words added for the call are an OR, so they can never make
        a memo-read round fail. This is the regression that would be
        invisible: a brief updated for the new road that quietly starts
        calling the old road off-brief."""
        memo = ("A: A memo has come down from upstairs and management "
                "wants fewer renders tonight, which is a thing to say to "
                "two people who do not do the rendering.\n"
                "B: Management. Marvellous. I will get right on that "
                "immediately and with enormous enthusiasm.")
        got = app.segment_audit("manager", memo)
        self.assertTrue(got["checked"])
        self.assertTrue(got["ok"], got.get("why"))

    def test_a_call_from_upstairs_passes_the_same_brief(self):
        call = ("A: That is the internal line. It is upstairs, and he is "
                "on the line right now, so somebody had better pick it up "
                "before it rings again.\n"
                "C: It is a memo. I am reading it to you myself because "
                "apparently that is what it takes in this building.\n"
                "B: He hung up. He actually hung up on us.")
        got = app.segment_audit("manager", call)
        self.assertTrue(got["checked"])
        self.assertTrue(got["ok"], got.get("why"))

    def test_the_brief_claims_no_marker_it_cannot_have(self):
        """A 'C:' marker is a thing only the call road can produce. If it
        were declared here, segment_audit would tell the operator that a
        memo-read round "never gets to ... and nobody speaks on the phone
        line" - about a segment with no phone in it."""
        self.assertIsNone(app.SEGMENT_BRIEF["manager"].get("marker"))


if __name__ == "__main__":
    unittest.main()
