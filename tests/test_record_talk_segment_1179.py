# -*- coding: utf-8 -*-
"""#1179: a record's talk on the hour's sheet - made, identified, played.

    "make sure that this is scheduled to be resolved by the orchestrator.
    Make sure this is put in an hourly segment and it is made, id'd and
    given play."

and, the same principle stated generally at the retirement desk:

    "When I resume the recording room for these clips, that means that I
    also want them to be scheduled by the orchestrator into hourly
    segments and be ran."

app.py is never imported: it is 9.8 MB and needs the whole station up.
Two things are executed instead, which between them are the whole change:

  * track_talk_segment.py, imported for real - every derivation, every
    price, every id;
  * the exact source text the patch inserts into app.py, exec'd in a
    namespace holding stand-ins for the handful of station globals it
    touches, so a typo in the patch fails HERE rather than on air.  This
    is the technique tests/test_event_roads_1177.py established.

Everything runs off a TemporaryDirectory.  Nothing reads or writes data/,
the ledger, the air log or any other live store; nothing opens a socket
and nothing calls a model.

WHAT THE REQUEST ASKS FOR, AND WHERE EACH IS ASSERTED:

    the sheet naming the road        TheSheetNamesTheRoad
    a part sized to the window       APartSizedToTheWindow
    ids riding to the ledger         IdsRideToTheLedger
    a send-off reaching the air      TheSendOffReachesTheAir
    the switch off changing nothing  TheSwitchOffChangesNothing
    resuming queues it for an hour   ResumingPutsItInTheQueue
    the desk follows it, or says
      which step it is stuck at      TheDeskFollowsFinishedWork
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import station_modifiers                            # noqa: E402
import track_talk_segment as T                      # noqa: E402


# --------------------------------------------------------------------
# The patch script lives outside the repository on purpose: the station
# is broadcasting and every app.py change is applied by hand.  Point
# SPARK_RECORD_TALK_PATCH at it, or leave it where the agent wrote it.
# Without it the patch-execution tests skip and say so; the module tests
# run either way.
# --------------------------------------------------------------------
CANDIDATES = [
    os.getenv("SPARK_RECORD_TALK_PATCH", ""),
    str(Path(tempfile.gettempdir()) / "claude" / "patch_1179_record_talk.py"),
    r"C:\Users\EHMECK~1\AppData\Local\Temp\claude"
    r"\--10-89-1-246-ehm-eckx-pinevoice-stack-spark-agent"
    r"\4c062de1-24db-4acb-9996-7567ccd60535\scratchpad"
    r"\patch_1179_record_talk.py",
]


def find_patch() -> Path | None:
    for name in CANDIDATES:
        if name and Path(name).is_file():
            return Path(name)
    return None


def load_patch():
    found = find_patch()
    if not found:
        return None
    spec = importlib.util.spec_from_file_location("patch_1179", str(found))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = load_patch()
skip_no_patch = unittest.skipIf(
    P is None, "patch script not found; set SPARK_RECORD_TALK_PATCH")


class Clock(object):
    """A hand-wound time.time(), so memoisation is testable without sleeps."""

    def __init__(self, at: float = 1_000_000.0):
        self.at = float(at)

    def time(self) -> float:
        return self.at


class Booth(object):
    """Stand-ins for the station globals the inserted block really uses."""

    def __init__(self, tmp: str):
        self.tmp = Path(tmp)
        self.clock = Clock()
        self.logged: list[tuple[str, str]] = []
        self.room = 81.9                    # the live window, measured
        self.cover = 23516.2                # the live reserve, measured
        self.larder: list[dict[str, Any]] = []
        self.shelf: dict[str, list[dict[str, Any]]] = {}
        self.finish_queue: dict[str, Any] = {"ids": [], "why": {}}
        self.selected_ids: list[str] = []
        self.shelf_why: dict[str, Any] = {"at": 0.0, "kind": "", "why": ""}

    # --- the station's own helpers, as the block calls them -----------
    def data_path(self, *parts: str) -> Path:
        return self.tmp.joinpath(*parts)

    def pipeline_log(self, kind: str, text: str, extra: str = "") -> None:
        self.logged.append((kind, text))

    def prep_room_left(self) -> float:
        return self.room

    def prepared_seconds(self) -> float:
        return self.cover

    def dialogue_entry(self, row: Any) -> dict[str, Any] | None:
        return (row or {}).get("entry")

    def retire_id(self, kind: str, row: Any) -> str:
        return str((row or {}).get("sid") or "")

    def retire_kind_label(self, kind: str) -> str:
        return {"gallery": "Painting selling",
                "manager": "a memo from upstairs"}.get(str(kind), str(kind))

    def cupboard_row_complete(self, kind: str, row: Any) -> bool:
        return bool((row or {}).get("complete"))

    def row_unaired(self, row: Any) -> bool:
        return not int((row or {}).get("aired") or 0)

    def commitment_inventory_plan(self, *a: Any, **k: Any) -> dict[str, Any]:
        return {"selected_ids": list(self.selected_ids)}

    def cupboard_finish_load(self) -> dict[str, Any]:
        return self.finish_queue


def make_namespace(booth: Booth, book: station_modifiers.ModifierBook) -> dict:
    """Exec the patch's inserted desk with the station stubbed around it."""
    ns: dict[str, Any] = {
        "Any": Any,
        "time": booth.clock,
        "data_path": booth.data_path,
        "pipeline_log": booth.pipeline_log,
        "track_talk_segment": T,
        "station_modifiers": station_modifiers,
        "prep_room_left": booth.prep_room_left,
        "prepared_seconds": booth.prepared_seconds,
        "dialogue_entry": booth.dialogue_entry,
        "retire_id": booth.retire_id,
        "retire_kind_label": booth.retire_kind_label,
        "cupboard_row_complete": booth.cupboard_row_complete,
        "row_unaired": booth.row_unaired,
        "commitment_inventory_plan": booth.commitment_inventory_plan,
        "_cupboard_finish_load": booth.cupboard_finish_load,
        "_LARDER": booth.larder,
        "_SHELF": booth.shelf,
        "_READY_SHELF_WHY": booth.shelf_why,
        "_MODIFIER_LOCK": threading.RLock(),
        "_MODIFIER_BOOK": book,
    }
    exec(compile(P.DESK, "<DESK>", "exec"), ns)
    return ns


class DeskCase(unittest.TestCase):
    """A temp directory, a stubbed booth, and the patch's own desk code."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="rectalk-")
        self.booth = Booth(self.tmp)
        self.book = station_modifiers.ModifierBook(
            self.tmp, clock=self.booth.clock.time)
        if P is not None:
            self.ns = make_namespace(self.booth, self.book)
        self.switch = Path(self.tmp) / "record_talk" / "mode"
        self.follow_switch = Path(self.tmp) / "finished_work" / "mode"

    def set_mode(self, word: str) -> None:
        self.switch.parent.mkdir(parents=True, exist_ok=True)
        self.switch.write_text(word + "\n", encoding="utf-8")
        self.booth.clock.at += 10.0             # past the switch's ttl

    def set_follow(self, word: str) -> None:
        self.follow_switch.parent.mkdir(parents=True, exist_ok=True)
        self.follow_switch.write_text(word + "\n", encoding="utf-8")
        self.booth.clock.at += 10.0


# ======================================================================
# 1. THE SHEET NAMES THE ROAD
# ======================================================================
class TheSheetNamesTheRoad(unittest.TestCase):
    """A record entry owes its bookends, and nothing else changes.

    The whole sheet change is (road, cannot) for one entry, because every
    reader that decides whether an entry expresses demand reads those two
    and nothing else."""

    def test_the_road_it_derives_to_is_one_the_station_already_plumbs(self):
        # Not a new road. coord_upcoming has had a `road == "track_talk"`
        # branch since #1089 and SCHED_PREP_KIND has had the key; the
        # whole point of deriving to it is that everything downstream is
        # already written.
        self.assertEqual(T.TALK_ROAD, "track_talk")
        self.assertEqual(T.RECORD_ENTRY_KINDS, ("record",))

    def test_a_record_entry_is_live_only_with_the_switch_off(self):
        road, cannot = T.entry_demand(
            "record", "record", "a record is not a round", T.MODE_OFF)
        self.assertEqual(road, "record")
        self.assertEqual(cannot, "a record is not a round")

    def test_trace_does_not_touch_the_sheet(self):
        # Identity is a separate decision from the running order, and an
        # operator must be able to take the first without the second.
        road, cannot = T.entry_demand(
            "record", "record", "a record is not a round", T.MODE_TRACE)
        self.assertEqual((road, cannot), ("record", "a record is not a round"))

    def test_on_air_a_record_entry_owes_its_talk(self):
        road, cannot = T.entry_demand(
            "record", "record", "a record is not a round", T.MODE_AIR)
        self.assertEqual(road, "track_talk")
        # The refusal is cleared, and that is what makes the demand real:
        # coord_upcoming skips `cannot` rows before anything is measured.
        self.assertEqual(cannot, "")

    def test_no_other_entry_kind_is_touched_in_any_mode(self):
        for mode in T.MODES:
            for kind, road in (("gallery", "gallery"), ("news", "news"),
                               ("recap", "recap"), ("deep", "deep"),
                               ("guest", "guest"), ("ad", "ad")):
                got = T.entry_demand(kind, road, "because", mode)
                self.assertEqual(got, (road, "because"),
                                 "%s changed under %s" % (kind, mode))

    def test_a_real_track_talk_entry_is_left_exactly_as_it_was(self):
        # The plain "canonical hour" preset carries one; it must keep
        # behaving as it did before any of this.
        for mode in T.MODES:
            self.assertEqual(
                T.entry_demand("track_talk", "track_talk", "", mode),
                ("track_talk", ""))

    def test_the_entry_says_why_it_now_owes_something(self):
        self.assertIn("talk it in and out",
                      T.entry_note("record", T.MODE_AIR))
        self.assertEqual(T.entry_note("record", T.MODE_OFF), "")
        self.assertEqual(T.entry_note("gallery", T.MODE_AIR), "")

    @skip_no_patch
    def test_the_patch_derivation_never_raises(self):
        """record_talk_entry must be total: a broken switch is an off
        switch and an entry that owes nothing is the station of tonight."""
        entry = self.__dict__.setdefault("_ns", None)
        del entry
        tmp = tempfile.mkdtemp(prefix="rectalk-sheet-")
        booth = Booth(tmp)
        ns = make_namespace(booth, station_modifiers.ModifierBook(
            tmp, clock=booth.clock.time))
        self.assertEqual(ns["record_talk_entry"]("record", "record", "no"),
                         ("record", "no"))
        Path(tmp, "record_talk").mkdir(parents=True, exist_ok=True)
        Path(tmp, "record_talk", "mode").write_text("air\n", encoding="utf-8")
        booth.clock.at += 10.0
        self.assertEqual(ns["record_talk_entry"]("record", "record", "no"),
                         ("track_talk", ""))


# ======================================================================
# 2. A PART SIZED TO THE WINDOW
# ======================================================================
class APartSizedToTheWindow(unittest.TestCase):
    """What one part really costs, and why the window is not the lever.

    The station refused the road with "it measures about 160s on this box
    and the window open right now allows 22s".  These are the numbers
    behind that sentence, measured on the live station on 2026-09-15."""

    # The live figures the design was sized against.
    LIVE_ROAD_P90 = 160.2               # task_cost("track_talk")
    LIVE_ROOM = 81.9                    # prep_room_left() on a 3m record
    LIVE_COVER = 23516.2                # prepared_seconds()

    def test_the_measured_audio_law(self):
        # Least squares over 19,208 air-log rows carrying text and a
        # measured duration: audio = 4.06 + 0.2621 * words.
        self.assertAlmostEqual(T.expected_audio_s(0), 4.06, places=2)
        self.assertAlmostEqual(T.expected_audio_s(39), 14.28, places=1)
        self.assertGreater(T.expected_audio_s(70), T.expected_audio_s(32))

    def test_a_send_off_is_one_or_two_lines_and_an_intro_is_not(self):
        low, high = T.brief_words(T.PART_OUTRO, T.MODE_AIR)
        self.assertEqual((low, high), (12, 32))
        self.assertEqual(T.brief_words(T.PART_INTRO, T.MODE_AIR), (12, 70))
        self.assertIn("1 to 2", T.brief_sentence(T.PART_OUTRO, T.MODE_AIR))
        self.assertIn("2 to 4", T.brief_sentence(T.PART_INTRO, T.MODE_AIR))

    def test_the_brief_never_goes_under_the_contract_floor(self):
        # track_talk_text_report refuses "fewer than twelve spoken words"
        # and "more than ninety". A brief that asks for a line the
        # station will then throw away is worse than no brief.
        for part in T.PARTS:
            for mode in T.MODES:
                low, high = T.brief_words(part, mode)
                self.assertGreaterEqual(low, 12)
                self.assertLessEqual(high, 90)
                self.assertLess(low, high)

    def test_a_shorter_send_off_saves_seconds_not_the_hundred_it_needs(self):
        """THE FINDING THAT DECIDED THE DESIGN.

        Only the render scales with words; the model visit and the tint
        round are per-round costs.  So making the send-off small is worth
        doing and cannot possibly make a part fit the window."""
        intro = T.part_cost_s(T.PART_INTRO, T.MODE_AIR)
        outro = T.part_cost_s(T.PART_OUTRO, T.MODE_AIR)
        self.assertLess(outro, intro)               # it IS cheaper
        self.assertLess(intro - outro, 20.0)        # ...by seconds
        self.assertGreater(outro, self.LIVE_ROOM)   # and still far too dear

    def test_a_part_does_not_fit_the_window_that_is_open(self):
        self.assertFalse(T.fits_window(self.LIVE_ROAD_P90, self.LIVE_ROOM))
        for part in T.PARTS:
            self.assertFalse(T.fits_window(
                T.part_cost_s(part, T.MODE_AIR), self.LIVE_ROOM))

    def test_and_does_not_need_to_because_a_deadline_reads_the_reserve(self):
        """prep_deadline_pick's own rule: the budget is an efficiency rule
        and efficiency does not get to overrule the clock."""
        self.assertTrue(T.reachable_on_deadline(
            self.LIVE_ROAD_P90, self.LIVE_COVER, self.LIVE_ROOM))
        for part in T.PARTS:
            self.assertTrue(T.reachable_on_deadline(
                T.part_cost_s(part, T.MODE_AIR),
                self.LIVE_COVER, self.LIVE_ROOM))

    def test_the_two_things_that_can_still_refuse_it(self):
        # A window too small to start anything in at all...
        self.assertFalse(T.reachable_on_deadline(160.2, self.LIVE_COVER, 5.0))
        # ...and a reserve that would run dry before it finished.
        self.assertFalse(T.reachable_on_deadline(160.2, 90.0, self.LIVE_ROOM))
        # The floor is the station's own PREP_DEADLINE_FLOOR.
        self.assertEqual(T.DEADLINE_FLOOR_S, 20.0)

    def test_the_sizing_report_says_which_of_those_it_is(self):
        good = T.sizing(T.PART_OUTRO, T.MODE_AIR, self.LIVE_ROOM,
                        self.LIVE_COVER)
        self.assertFalse(good["fits_window"])
        self.assertTrue(good["reachable"])
        self.assertIn("deadline", good["why"])
        bad = T.sizing(T.PART_OUTRO, T.MODE_AIR, 2.0, self.LIVE_COVER)
        self.assertFalse(bad["reachable"])
        self.assertIn("no window", bad["why"])


# ======================================================================
# 3. IDS RIDING TO THE LEDGER
# ======================================================================
class IdsRideToTheLedger(unittest.TestCase):
    """A part is identified, and the identity reaches the books.

    Measured before this was written: over 48.6 hours of air_log.jsonl,
    140 of 140 `intro` rows and 3,354 of 3,386 `interject` rows carry no
    sid at all.  Nothing the pair say about a record has ever had one."""

    TRACK = {"id": "2628d48b9a11e3fd", "title": "Withered Promises",
             "artist": "haircuts for men", "seconds": 220.0}

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="rectalk-id-")
        self.clock = Clock()
        self.book = station_modifiers.ModifierBook(
            self.tmp, clock=self.clock.time)

    def test_the_id_is_derived_so_it_is_the_same_every_time(self):
        first = T.part_id(self.TRACK["id"], "outro")
        self.assertEqual(first, "talk:2628d48b9a11e3fd.outro")
        self.assertEqual(first, T.part_id(self.TRACK["id"], "outro"))
        self.assertNotEqual(first, T.part_id(self.TRACK["id"], "intro"))

    def test_it_is_a_modifier_id_so_it_rides_the_road_that_exists(self):
        pid = T.part_id(self.TRACK["id"], "intro")
        self.assertTrue(station_modifiers.is_modifier_id(pid))
        kind, _key = station_modifiers.split_id(pid)
        self.assertEqual(kind, station_modifiers.KIND_TALK)

    def test_the_id_names_the_record_and_the_half(self):
        pid = T.part_id(self.TRACK["id"], "outro")
        self.assertEqual(T.split_part_id(pid), ("2628d48b9a11e3fd", "outro"))
        # A string that is not one of ours must not be read as one.
        self.assertEqual(T.split_part_id("guest:4f959ea0"), ("", ""))
        self.assertEqual(T.split_part_id("talk:nodotpart"), ("", ""))
        self.assertEqual(T.split_part_id(""), ("", ""))

    def test_nothing_is_minted_for_a_record_with_no_id(self):
        self.assertEqual(T.part_id("", "intro"), "")
        self.assertEqual(T.part_id("x", "middle"), "")
        self.assertEqual(T.part_sid("", "intro", 1.0), "")

    def test_the_segment_id_is_stable_for_one_airing(self):
        one = T.part_sid(self.TRACK["id"], "outro", 1_000_000.4)
        two = T.part_sid(self.TRACK["id"], "outro", 1_000_000.9)
        self.assertEqual(one, two)                   # same second, same sid
        self.assertTrue(one.startswith("tt-"))
        later = T.part_sid(self.TRACK["id"], "outro", 1_000_060.0)
        self.assertNotEqual(one, later)              # a later airing differs
        other = T.part_sid(self.TRACK["id"], "intro", 1_000_000.4)
        self.assertNotEqual(one, other)              # the halves differ

    def test_the_id_rides_the_segment_the_way_the_ledger_reads_it(self):
        """ids_for(sid) is precisely what modifiers_for_sid() calls, and
        airlog_row_from and script_ledger_commit already stamp its result
        onto every row they write."""
        plan = T.ride_plan(self.TRACK, "outro", self.clock.time(), T.MODE_TRACE)
        self.book.raise_(plan["kind"], plan["key"], plan["name"],
                         stands_s=plan["stands_s"], source=plan["source"])
        rode = self.book.ride(plan["sid"], [plan["id"]],
                              round_kind="track_talk", source="outro")
        self.assertEqual(rode, [plan["id"]])
        self.assertEqual(self.book.ids_for(plan["sid"]), [plan["id"]])

    def test_and_the_join_answers_in_both_directions(self):
        plan = T.ride_plan(self.TRACK, "intro", self.clock.time(), T.MODE_AIR)
        self.book.raise_(plan["kind"], plan["key"], plan["name"],
                         stands_s=plan["stands_s"], source=plan["source"])
        self.book.ride(plan["sid"], [plan["id"]], round_kind="track_talk")
        # segment -> what shaped it
        self.assertIn(plan["id"], self.book.ids_for(plan["sid"]))
        # part -> every segment it touched
        rides = self.book.rides_for(plan["id"])
        self.assertEqual([r["sid"] for r in rides], [plan["sid"]])
        # and the id names the record it introduces
        self.assertEqual(T.split_part_id(plan["id"])[0], self.TRACK["id"])

    def test_a_part_made_ahead_airs_under_the_id_it_was_made_with(self):
        made = T.part_stamp(self.TRACK, "outro", 1_000_000.0, T.MODE_AIR)
        self.assertEqual(made["talk_id"], "talk:2628d48b9a11e3fd.outro")
        plan = T.ride_plan(self.TRACK, "outro", 1_000_500.0, T.MODE_AIR,
                           held=made)
        self.assertEqual(plan["id"], made["talk_id"])
        self.assertTrue(plan["prepared"])
        # A part written live has no stamp and gets the same string,
        # which is the point of deriving it rather than minting it.
        live = T.ride_plan(self.TRACK, "outro", 1_000_500.0, T.MODE_AIR)
        self.assertEqual(live["id"], plan["id"])
        self.assertFalse(live["prepared"])

    def test_the_book_names_it_in_words_a_person_reads(self):
        self.assertEqual(
            T.part_name(self.TRACK, "outro"),
            "the send-off after Withered Promises by haircuts for men")
        self.assertTrue(T.part_name({}, "intro").endswith("a record"))

    def test_a_record_stops_being_what_is_going_on_when_it_stops_turning(self):
        plan = T.ride_plan(self.TRACK, "intro", 1000.0, T.MODE_AIR)
        self.assertEqual(plan["stands_s"], 280.0)       # its length plus a bit
        short = T.ride_plan({"id": "x"}, "intro", 1000.0, T.MODE_AIR)
        self.assertEqual(short["stands_s"], 240.0)      # the store did not say

    def test_a_record_link_is_traced_and_never_spoken(self):
        """It must not reach a writing prompt or a dead-air filler: the
        pair would be told to discuss the introduction instead of reading
        it, and the gap road would announce a send-off that has not
        happened."""
        self.assertIn(station_modifiers.KIND_TALK,
                      station_modifiers.SILENT_KINDS)
        row = station_modifiers.make_record(
            station_modifiers.KIND_TALK, "abc.intro",
            T.part_name(self.TRACK, "intro"), 1000.0, 300.0)
        guest = station_modifiers.make_record(
            station_modifiers.KIND_GUEST, "4f959ea0", "Ada", 1000.0)
        clause = station_modifiers.standing_clause([row, guest])
        self.assertIn("Ada", clause)
        self.assertNotIn("Withered Promises", clause)
        said = station_modifiers.gap_lines([row, guest])
        self.assertEqual([s["kind"] for s in said],
                         [station_modifiers.KIND_GUEST])


# ======================================================================
# 4. A SEND-OFF ACTUALLY REACHING THE AIR PATH
# ======================================================================
class TheSendOffReachesTheAir(unittest.TestCase):
    """Of 95 track_talk rows on air in twenty-four hours, 90 were intros,
    5 were opens and not one was a send-off.

    The air path DOES ask - _record_talk_body takes the outro of the
    record just gone.  Two things keep the shelf under it empty."""

    def test_the_one_affordable_visit_goes_to_the_half_with_no_fallback(self):
        # Off: the order prep_track_talk has always used.
        self.assertEqual(T.part_order(T.MODE_OFF), ("intro", "outro"))
        self.assertEqual(T.part_order(T.MODE_TRACE), ("intro", "outro"))
        # On: the send-off, because the intro has a live fallback on the
        # air path and the send-off has none at all.
        self.assertEqual(T.part_order(T.MODE_AIR), ("outro", "intro"))

    def test_one_visit_per_record_therefore_makes_a_send_off(self):
        """prep_track_talk writes ONE part per visit and breaks on the
        first unready half.  Simulated over the exact loop it runs."""
        def one_visit(record: dict, mode: str) -> str:
            for part in T.part_order(mode):
                if not record.get(part):
                    return part
            return ""
        blank: dict[str, Any] = {}
        self.assertEqual(one_visit(blank, T.MODE_OFF), "intro")
        self.assertEqual(one_visit(blank, T.MODE_AIR), "outro")
        # and the second visit finishes the pair either way
        self.assertEqual(one_visit({"outro": 1}, T.MODE_AIR), "intro")

    def test_the_record_just_gone_survives_to_be_sent_off(self):
        """THE SECOND FAULT.  _track_talk_prune keeps `now` - "its
        send-off has not aired yet" - and `coming` and the queue.  By the
        time the air path asks, the needle is down on the NEXT record and
        the one being sent off is in none of those three."""
        queue_and_now = {"queued-1", "queued-2", "now-playing"}
        history = [{"id": "two-ago"}, {"id": "just-gone"}]
        # Off: exactly the set the sweep has always had.
        self.assertEqual(T.prune_allow(queue_and_now, history, T.MODE_OFF),
                         queue_and_now)
        # On: the record whose send-off is owed is kept.
        kept = T.prune_allow(queue_and_now, history, T.MODE_AIR)
        self.assertIn("just-gone", kept)
        self.assertIn("two-ago", kept)          # a skip can put one between
        self.assertTrue(queue_and_now.issubset(kept))

    def test_the_sweep_would_have_destroyed_the_finished_send_off(self):
        """The whole fault, run as the sweep runs it."""
        shelf = {"just-gone": {"outro": {"text": "that was ..."}},
                 "queued-1": {"intro": {"text": "coming up ..."}}}
        allowed = {"queued-1", "now-playing"}
        history = [{"id": "just-gone"}]

        def sweep(mode: str) -> dict:
            keep = T.prune_allow(allowed, history, mode)
            return {k: v for k, v in shelf.items() if k in keep}

        # Today: the paid-for send-off is swept one moment before it is
        # owed, and the air path finds nothing.
        self.assertNotIn("just-gone", sweep(T.MODE_OFF))
        # With the switch on it is still there when the air path asks.
        self.assertIn("just-gone", sweep(T.MODE_AIR))

    def test_an_empty_history_never_turns_the_sweep_destructive(self):
        # The sweep's own guard: "do not turn a temporarily empty queue
        # into a destructive sweep."  Nothing here may weaken it.
        self.assertEqual(T.prune_allow(set(), [], T.MODE_AIR), set())
        self.assertEqual(T.prune_allow(set(), [{"id": ""}], T.MODE_AIR), set())
        self.assertEqual(T.prune_allow({"a"}, None, T.MODE_AIR), {"a"})

    @skip_no_patch
    def test_the_patch_gives_the_send_off_a_segment_of_its_own(self):
        """The send-off goes out through dj_speak("interject", ...) - one
        row in a bucket of 3,386.  With a sid it is answerable."""
        tmp = tempfile.mkdtemp(prefix="rectalk-air-")
        booth = Booth(tmp)
        book = station_modifiers.ModifierBook(tmp, clock=booth.clock.time)
        ns = make_namespace(booth, book)
        gone = {"id": "23e5fbff054507f8", "title": "AFTER HOURS",
                "artist": "slowski", "seconds": 180.0}
        self.assertEqual(ns["record_talk_ride"](gone, "outro"), "")   # off
        Path(tmp, "record_talk").mkdir(parents=True, exist_ok=True)
        Path(tmp, "record_talk", "mode").write_text("trace\n", encoding="utf-8")
        booth.clock.at += 10.0
        sid = ns["record_talk_ride"](gone, "outro", {"text": "that was ..."})
        self.assertTrue(sid.startswith("tt-"))
        self.assertEqual(book.ids_for(sid),
                         ["talk:23e5fbff054507f8.outro"])


# ======================================================================
# 5. THE SWITCH OFF CHANGES NOTHING
# ======================================================================
class TheSwitchOffChangesNothing(DeskCase):
    """Off is the station exactly as it runs tonight, and off is what a
    missing, empty, unreadable or misspelt switch means."""

    def test_every_derivation_is_the_identity_function(self):
        self.assertEqual(T.entry_demand("record", "record", "no", T.MODE_OFF),
                         ("record", "no"))
        self.assertEqual(T.part_order(T.MODE_OFF), ("intro", "outro"))
        self.assertEqual(T.brief_sentence("outro", T.MODE_OFF),
                         "Use 2 to 4 natural spoken sentences and "
                         "12 to 70 words.")
        self.assertEqual(T.part_stamp({"id": "a"}, "outro", 1.0, T.MODE_OFF),
                         {})
        self.assertEqual(T.ride_plan({"id": "a"}, "outro", 1.0, T.MODE_OFF),
                         {})
        self.assertEqual(T.prune_allow({"a", "b"}, [{"id": "c"}], T.MODE_OFF),
                         {"a", "b"})
        self.assertFalse(T.keep_just_gone(T.MODE_OFF))

    def test_the_prompt_clause_is_byte_identical_to_the_one_in_app(self):
        # The line the patch replaces reads exactly this.
        self.assertEqual(
            T.brief_sentence("intro", T.MODE_OFF),
            "Use 2 to 4 natural spoken sentences and 12 to 70 words.")

    def test_a_missing_switch_is_off(self):
        sw = T.TalkSwitch(Path(self.tmp) / "record_talk", env={})
        self.assertEqual(sw.mode(), T.MODE_OFF)
        self.assertFalse(sw.traces())
        self.assertFalse(sw.airs())

    def test_an_unreadable_or_misspelt_switch_is_off(self):
        sw = T.TalkSwitch(Path(self.tmp) / "record_talk", env={})
        for word in ("", "   ", "ON AIR PLEASE", "yes", "TRACE-ISH", "1"):
            self.set_mode(word)
            sw._read_at = 0.0
            self.assertEqual(sw.mode(), T.MODE_OFF, repr(word))

    def test_the_three_words_and_the_kindest_reading_of_on(self):
        sw = T.TalkSwitch(Path(self.tmp) / "record_talk", env={})
        for word, want in (("off", T.MODE_OFF), ("trace", T.MODE_TRACE),
                           ("air", T.MODE_AIR), ("on", T.MODE_AIR),
                           ("  AIR \n", T.MODE_AIR)):
            self.set_mode(word)
            sw._read_at = 0.0
            self.assertEqual(sw.mode(), want, repr(word))

    def test_the_switch_is_memoised_for_its_ttl(self):
        sw = T.TalkSwitch(Path(self.tmp) / "record_talk", env={}, ttl=5.0,
                          clock=self.booth.clock.time)
        self.set_mode("air")
        self.assertEqual(sw.mode(), T.MODE_AIR)
        self.set_mode("off")
        self.booth.clock.at -= 10.0             # inside the ttl again
        self.assertEqual(sw.mode(), T.MODE_AIR)
        self.booth.clock.at += 10.0
        self.assertEqual(sw.mode(), T.MODE_OFF)

    @skip_no_patch
    def test_the_desk_itself_does_nothing_with_the_switch_off(self):
        self.assertEqual(self.ns["record_talk_mode"](), T.MODE_OFF)
        self.assertFalse(self.ns["record_talk_sheet_on"]())
        self.assertFalse(self.ns["record_talk_trace_on"]())
        self.assertEqual(self.ns["record_talk_part_order"](),
                         ("intro", "outro"))
        self.assertEqual(self.ns["record_talk_stamp"]({"id": "a"}, "outro"), {})
        self.assertEqual(self.ns["record_talk_ride"]({"id": "a"}, "outro"), "")
        self.assertEqual(self.ns["record_talk_entry"]("record", "record", "x"),
                         ("record", "x"))
        self.assertEqual(self.ns["record_follow_desk"](), {})
        row: dict[str, Any] = {}
        self.assertFalse(self.ns["record_follow_cue"]("gallery", row))
        self.assertEqual(row, {})
        self.assertEqual(self.booth.logged, [])

    @skip_no_patch
    def test_the_desk_never_raises_whatever_it_is_handed(self):
        for bad in (None, "", 0, [], {"id": None}):
            self.assertEqual(self.ns["record_talk_ride"](bad, "outro"), "")
            self.assertEqual(self.ns["record_talk_stamp"](bad, "outro"), {})
        self.assertEqual(self.ns["record_talk_entry"](None, None, None),
                         ("", ""))


# ======================================================================
# 6. RESUMING PUTS IT IN THE QUEUE FOR AN HOUR
# ======================================================================
@skip_no_patch
class ResumingPutsItInTheQueue(DeskCase):
    """"When I resume the recording room for these clips ... I also want
    them to be scheduled by the orchestrator into hourly segments and be
    ran."

    Today cupboard_finish_sweep drops the id the moment the row is
    complete and logs that it is finished.  The row was never anywhere
    but its own shelf, and from that moment it is indistinguishable from
    the other 458 rows in the cupboard.  `cue_at` is the one durable mark
    unheard_pick() reads first, on every road, with no dial."""

    def test_finishing_a_resumed_round_cues_it(self):
        self.set_follow("air")
        row: dict[str, Any] = {"sid": "gallery-ea62b25956"}
        self.assertTrue(self.ns["record_follow_cue"]("gallery", row))
        self.assertEqual(row["cue_at"], self.booth.clock.at)
        self.assertTrue(any("CUED" in text for _k, text in self.booth.logged))

    def test_it_keeps_the_moment_it_was_first_asked_for(self):
        self.set_follow("air")
        row: dict[str, Any] = {"sid": "manager-f4dc5fff84", "cue_at": 55.0}
        self.assertFalse(self.ns["record_follow_cue"]("manager", row))
        self.assertEqual(row["cue_at"], 55.0)

    def test_trace_watches_and_does_not_cue(self):
        # Reading a desk and changing what airs are different risks.
        self.set_follow("trace")
        row: dict[str, Any] = {"sid": "gallery-1"}
        self.assertFalse(self.ns["record_follow_cue"]("gallery", row))
        self.assertNotIn("cue_at", row)

    def test_off_cues_nothing_and_says_nothing(self):
        row: dict[str, Any] = {"sid": "gallery-1"}
        self.assertFalse(self.ns["record_follow_cue"]("gallery", row))
        self.assertNotIn("cue_at", row)
        self.assertEqual(self.booth.logged, [])

    def test_a_row_that_is_not_a_row_is_refused_quietly(self):
        self.set_follow("air")
        for bad in (None, "", 0, []):
            self.assertFalse(self.ns["record_follow_cue"]("gallery", bad))


# ======================================================================
# 7. THE DESK FOLLOWS FINISHED WORK, OR NAMES THE STEP IT IS STUCK AT
# ======================================================================
class TheDeskFollowsFinishedWork(unittest.TestCase):
    """"Make sure that the orchestrator is keeping track of these elements
    behind the scenes and making sure that they make it to the air."

    The answer names the FIRST step not passed, because that is the step
    somebody has to do something about."""

    NOW = 1_000_000.0

    def follow(self, **facts: Any) -> dict[str, Any]:
        base = {"id": "gallery-ea62b25956", "road": "gallery",
                "label": "Painting selling", "seconds": 196.0,
                "made_at": self.NOW - 199_051.0}
        base.update(facts)
        return T.follow_row(base, self.NOW)

    def test_written_and_not_finished(self):
        got = self.follow(complete=False)
        self.assertEqual(got["step"], "written")
        self.assertIn("recording room has not finished it", got["say"])

    def test_the_operator_sent_it_back_and_it_is_still_being_made(self):
        got = self.follow(complete=False, resumed=True)
        self.assertEqual(got["step"], "resumed")
        self.assertIn("sent it back", got["say"])

    def test_finished_radio_that_nothing_has_asked_for(self):
        """The 131 rounds in the cupboard that have never been heard."""
        got = self.follow(complete=True)
        self.assertEqual(got["step"], "recorded")
        self.assertIn("nothing has asked for it", got["say"])
        self.assertGreater(got["waited_seconds"], 48 * 3600)

    def test_finished_and_cued_is_in_the_queue_for_an_hour(self):
        got = self.follow(complete=True, cued_at=self.NOW - 60)
        self.assertEqual(got["step"], "cued")
        self.assertIn("waiting for the next gap", got["say"])

    def test_bound_to_an_entry_that_has_not_come_round(self):
        got = self.follow(complete=True, owed=True, entry="hour-12")
        self.assertEqual(got["step"], "owed")
        self.assertIn("hour-12", got["say"])

    def test_it_went_out_and_says_where(self):
        got = self.follow(complete=True, aired=1, aired_at=self.NOW - 30,
                          used_by={"slot_id": "hour-12", "hour": "2026-09-15T06"})
        self.assertEqual(got["step"], "aired")
        self.assertIn("hour-12", got["say"])
        self.assertIn("2026-09-15T06", got["say"])
        self.assertTrue(all(got["steps"].values()))

    def test_the_door_that_refused_it_is_quoted(self):
        """"the gallery round runs 196s and its entry has 92s left (45s
        grace)" - the refusal that makes the cupboard pile up."""
        why = ("the gallery round runs 196s and its entry has 92s left "
               "(45s grace) - the round is longer than the time the sheet "
               "gives it")
        got = self.follow(complete=True, blocked=why)
        self.assertIn("92s left", got["say"])
        self.assertIn("The last door to refuse it said", got["say"])

    def test_the_steps_are_cumulative_so_the_answer_is_a_path(self):
        got = self.follow(complete=True, cued_at=self.NOW)
        self.assertTrue(got["steps"]["written"])
        self.assertTrue(got["steps"]["recorded"])
        self.assertTrue(got["steps"]["cued"])
        self.assertFalse(got["steps"]["owed"])
        self.assertFalse(got["steps"]["aired"])

    def test_the_headline_names_the_oldest_thing_stuck(self):
        rows = [self.follow(complete=True),
                self.follow(id="x", made_at=self.NOW - 60, complete=True),
                self.follow(id="y", complete=True, aired=1,
                            aired_at=self.NOW)]
        out = T.follow_summary(rows, self.NOW)
        self.assertEqual(out["stuck"], 2)
        self.assertEqual(out["counts"]["recorded"], 2)
        self.assertEqual(out["counts"]["aired"], 1)
        self.assertEqual(out["worst"]["id"], "gallery-ea62b25956")
        self.assertIn("have not reached the air", out["say"])

    def test_an_empty_desk_says_so(self):
        out = T.follow_summary([], self.NOW)
        self.assertEqual(out["stuck"], 0)
        self.assertIn("nothing", out["say"])

    @skip_no_patch
    def test_the_desk_walks_the_shelves_and_answers(self):
        tmp = tempfile.mkdtemp(prefix="rectalk-desk-")
        booth = Booth(tmp)
        ns = make_namespace(booth, station_modifiers.ModifierBook(
            tmp, clock=booth.clock.time))
        booth.shelf["gallery"] = [
            {"sid": "gallery-1", "at": booth.clock.at - 200_000,
             "complete": True, "entry": {"seconds": 196.0}},
            {"sid": "gallery-2", "at": booth.clock.at - 100,
             "complete": False, "entry": {"seconds": 0.0}},
        ]
        booth.finish_queue["ids"] = ["gallery-2"]
        booth.selected_ids = ["gallery-1"]
        # Off: the desk is what it is today.
        self.assertEqual(ns["record_follow_desk"](), {})
        Path(tmp, "finished_work").mkdir(parents=True, exist_ok=True)
        Path(tmp, "finished_work", "mode").write_text("trace\n",
                                                      encoding="utf-8")
        booth.clock.at += 10.0
        got = ns["record_follow_desk"]()
        self.assertEqual(got["mode"], T.MODE_TRACE)
        steps = {r["id"]: r["step"] for r in got["rows"]}
        self.assertEqual(steps["gallery-1"], "owed")
        self.assertEqual(steps["gallery-2"], "resumed")
        self.assertEqual(got["stuck"], 2)
        # Oldest-first, so the thing that has waited longest is read first.
        self.assertEqual(got["rows"][0]["id"], "gallery-1")

    @skip_no_patch
    def test_the_two_switches_are_independent(self):
        """An operator must be able to read the desk without changing the
        running order, and change the running order without the desk."""
        tmp = tempfile.mkdtemp(prefix="rectalk-two-")
        booth = Booth(tmp)
        ns = make_namespace(booth, station_modifiers.ModifierBook(
            tmp, clock=booth.clock.time))
        Path(tmp, "record_talk").mkdir(parents=True, exist_ok=True)
        Path(tmp, "record_talk", "mode").write_text("air\n", encoding="utf-8")
        booth.clock.at += 10.0
        self.assertTrue(ns["record_talk_sheet_on"]())
        self.assertFalse(ns["record_follow_on"]())
        self.assertEqual(ns["record_follow_desk"](), {})


# ======================================================================
# 8. THE BOARD SAYS WHICH OF THE THREE IT IS
# ======================================================================
class TheBoardSaysWhereItStands(unittest.TestCase):
    """#1128's lesson: an instrument nothing reads is a dead wire, and
    "why is this road zero" has now cost five separate investigations."""

    def test_off_says_the_sheet_cannot_ask_for_it(self):
        said = T.board_say(T.MODE_OFF)
        self.assertIn("not on the hour's sheet", said)

    def test_trace_says_identified_but_not_scheduled(self):
        said = T.board_say(T.MODE_TRACE)
        self.assertIn("IDENTIFIED", said)
        self.assertIn("running order is unchanged", said)

    def test_air_says_what_the_sheet_owes(self):
        said = T.board_say(T.MODE_AIR, {"owed_seconds": 180.0, "rows": 2})
        self.assertIn("owes it 180s", said)
        self.assertIn("2 prepared", said)
        self.assertIn("send-off is written first", said)


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
