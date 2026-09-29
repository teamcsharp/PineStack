"""[no-repeat-24h] [s3-wall-folder] [s3-line-no] [s3-gold] [everything-rolls] in app.py.

Imports app (run in the container with SPARK_AGENT_DATA_DIR on a temp dir);
every book is a temp Book, every door that would speak or skip is a recorder."""
import asyncio
import re
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import air_norepeat
import app

SRC = Path(app.__file__).read_text(encoding="utf-8")


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        d = Path(self._dir.name)
        self.book = air_norepeat.Book(d / "book.json", d / "ref.jsonl")
        self._p = mock.patch.object(app, "NOREPEAT", self.book)
        self._p.start()
        self._log = mock.patch.object(app, "pipeline_log", lambda *a, **k: None)
        self._log.start()

    def tearDown(self):
        self._log.stop()
        self._p.stop()
        self._dir.cleanup()


class LineGate(_Tmp):
    LINE = "I just don't see how that relates to the actual content we are dealing with."

    def test_a_heard_line_is_refused_and_recorded(self):
        self.assertEqual(app.norepeat_line_gate(self.LINE, "dj", "banter"), "")
        app.norepeat_note_line(self.LINE, "banter", "id-1")
        why = app.norepeat_line_gate(self.LINE.upper(), "cohost", "", road="banter")    # any seat, a new id
        self.assertTrue(why)
        self.assertEqual(self.book.state()["refusals_by_road"], {"line:banter": 1})
        self.assertEqual(app.norepeat_line_gate(self.LINE, "dj", "", by_hand=True), "")  # the operator's own

    def test_the_gates_sit_where_the_air_passes(self):
        turns = SRC[SRC.index("async def _speak_turns_floorless("):]
        turns = turns[:turns.index("\nasync def ", 10)]
        gate = turns.index("[no-repeat-24h:turns]")
        self.assertLess(gate, turns.index("[s3-turnchain] not a line just said"))
        self.assertNotIn("allow_repeat", turns[gate:gate + 700])     # no replay exemption
        self.assertIn("[no-repeat-24h:dj_speak]", SRC)

    def test_airlog_rows_are_noted(self):
        row = {"id": "x1", "aired": "stream", "kind": "call", "who": "dj", "text": self.LINE, "air_at": time.time()}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(app, "AIR_LOG_PATH", Path(tmp) / "air.jsonl"):
            app.airlog_write_rows([row])
        self.assertTrue(self.book.used_text(self.LINE))


class Banks(_Tmp):
    SCRIPT = ("A: Whenever the Italians are on television, the whole block goes quiet.\n"
              "B: That sounds like some deeply irrelevant historical noise to bring into this.\n"
              "A: I just don't see how that relates to the actual content we are dealing with.")

    def row(self, aired_ago=None):
        r = {"sid": "s1", "entry": {"script": self.SCRIPT}}
        if aired_ago is not None:
            r["aired_at"] = time.time() - aired_ago
        return r

    def test_a_round_aired_inside_the_day_is_struck(self):
        self.assertIn("min ago", app.norepeat_round_refusal("banter", self.row(600)))
        self.assertEqual(app.norepeat_round_refusal("banter", self.row(90000)), "")
        for ln in self.SCRIPT.splitlines()[:2]:
            app.norepeat_note_line(ln.split(": ", 1)[1], "banter")
        self.assertIn("lines were on air", app.norepeat_round_refusal("banter", self.row(90000)))

    def test_the_reair_gate_and_the_pick_strike_it_before_any_roll(self):
        with mock.patch.object(app, "_reair_marks", lambda: {}):
            self.assertTrue(app.bank_reair_refusal("banter", self.row(600)))
            got, stamp = app.bank_reair_pick("banter", [self.row(600), self.row(1200)], "test")
        self.assertIsNone(got)
        self.assertIsNone(stamp)


class Records(_Tmp):
    def test_a_heard_record_is_skipped(self):
        q = [{"id": "t1", "title": "one"}, {"id": "t2", "title": "two"}, {"id": "t3", "title": "three"}]
        app.norepeat_note_record("t1", "rotation")
        app.norepeat_note_record("t2", "rotation")
        self.assertEqual(app.norepeat_record_take(q, 0), 2)
        app.norepeat_note_record("t3", "rotation")
        self.assertEqual(app.norepeat_record_take(q, 0), -1)

    def test_remember_played_notes_it(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(app, "PLAYED_PATH", Path(tmp) / "p.json"):
            app.remember_played({"id": "t9", "title": "nine", "s3_spin": {"lane": "rotation"}})
        self.assertTrue(app.norepeat_record_used("t9"))

    def test_the_gap_rolls_a_fresh_record_to_the_front(self):
        q = [{"id": "owned", "title": "a"}, {"id": "heard", "title": "b"},
             {"id": "fresh", "title": "c"}, {"id": "fresh2", "title": "d"}]
        app.norepeat_note_record("heard", "rotation")
        skipped = []
        radio = dict(app._RADIO, on=True, station="all", queue=q, now={"id": "pinned"})
        with mock.patch.dict(app._TRACK_TALK, {"owned": {}}, clear=False), \
                mock.patch.object(app, "_RADIO", radio), \
                mock.patch.object(app, "radio_paused", lambda: False), \
                mock.patch.object(app, "dj_skip", lambda: skipped.append(1)), \
                mock.patch.object(app, "_S3Dice") as dice:
            dice.return_value.pick.return_value = 1                 # the roll lands on the second candidate
            got = app.norepeat_gap_record("test")
        self.assertEqual(got["id"], "fresh2")
        self.assertEqual(radio["queue"][0]["id"], "fresh2")
        self.assertEqual(skipped, [1])
        self.assertIsNone(radio["now"])
        self.assertIn("fresh2", app._GAP_RECORD_ROLL)


class Sfx(_Tmp):
    def test_heard_clips_are_struck_before_the_roll(self):
        paths = [Path("/samples/x/a.mp4"), Path("/samples/x/b.mp4")]
        app.norepeat_note_sfx(app.sfx_id(paths[0]), "board")
        self.assertEqual(app.norepeat_fresh_clips(paths, "board"), [paths[1]])
        self.assertTrue(app.sfx_video_on_cooldown(app.sfx_id(paths[0])))

    def test_gap_clip_rolls_among_the_fresh(self):
        paths = [Path("/samples/x/a.mp4"), Path("/samples/x/b.mp4")]
        app.norepeat_note_sfx(app.sfx_id(paths[1]), "board")
        got = app.norepeat_roll_clip(paths, "sfx.gap_video", "test")
        self.assertEqual(got, paths[0])
        app.norepeat_note_sfx(app.sfx_id(paths[0]), "board")
        self.assertIsNone(app.norepeat_roll_clip(paths, "sfx.gap_video", "test"))   # never a repeat


class WallFolder(unittest.TestCase):
    def con(self):
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE clips (path TEXT, sid TEXT, folder TEXT, video INT, playable INT, deck_cycle INT, seconds REAL)")
        for f, n in (("snl", 3), ("Rest", 5), ("rasslin", 2)):
            for i in range(n):
                c.execute("INSERT INTO clips VALUES (?,?,?,1,1,0,3.0)", ("/s/%s/%d.mp4" % (f, i), "%s%d" % (f, i), f))
        return c

    def test_the_folder_is_rolled_among_the_offered_and_recent_ones_wait(self):
        with mock.patch.object(app, "s3_offer", lambda k, o, l="": list(o)):
            got = app._wall_folder_roll(self.con(), 1, 1, "", ["Rest", "snl"])
        self.assertEqual(got, "rasslin")
        # the station's own draw (no System 3 record): the folder notes no dice
        self.assertEqual(app._wall_folder_category(Path("/s/rasslin/0.mp4")), {"label": "rasslin"})

    def test_the_desk_can_switch_a_folder_off_and_new_ones_join(self):
        items = [{"text": "snl", "weight": 1.0}, {"text": "Rest", "weight": 0.0}]
        with mock.patch.object(app, "s3_pool", lambda k, o, l="": list(o)), \
                mock.patch.dict(app.__dict__, {"system3_pool_items": lambda k: items}):
            self.assertEqual(app.s3_offer("sfxtv.wall_folder", ["Rest", "rasslin", "snl"]), ["rasslin", "snl"])


class FakeDesk:
    """System 3's dice door, recording: every pick lands on the LAST candidate,
    every roll is u = 0.42 (d100 43)."""

    def __init__(self):
        self.last, self.calls = {}, []

    def roll(self, key, label=""):
        self.last[key] = {"kind": "roll", "key": key, "u": 0.42, "dice": 43, "at": time.time()}
        self.calls.append(key)
        return 0.42

    def pick(self, key, cands, label="", weights=None, media=None):
        k = len(cands) - 1
        self.last[key] = {"kind": "pick", "key": key, "u": 0.9, "dice": 91, "index": k + 1, "of": len(cands),
                          "picked": " ".join(str(cands[k]).split())[:160], "at": time.time()}
        self.calls.append(key)
        return k

    def pool(self, key, opts, label=""):
        return list(opts)

    def ns(self):
        return {"system3_roll": self.roll, "system3_pick": self.pick, "system3_pool": self.pool,
                "system3_last_roll": lambda key: self.last.get(key), "system3_pool_items": lambda key: None}


OFF = {"system3_roll": lambda *a, **k: None, "system3_pick": lambda *a, **k: None,
       "system3_pool": lambda *a, **k: None, "system3_last_roll": lambda key: None,
       "system3_pool_items": lambda key: None}


class WallPick(_Tmp):
    """[s3-wall-folder] the endless set's pick against a realistic clip book
    (the real table's columns, sqlite3.Row rows, sids = sfx_id(path))."""

    FOLDERS = (("snl", 4), ("Rest", 6), ("rasslin", 3))

    def setUp(self):
        super().setUp()
        c = sqlite3.connect(":memory:", check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("CREATE TABLE clips (path TEXT PRIMARY KEY, sid TEXT, name TEXT, folder TEXT, video INTEGER, "
                  "playable INTEGER, deck_cycle INTEGER NOT NULL DEFAULT 0, seconds REAL)")
        for f, n in self.FOLDERS:
            for i in range(n):
                p = "/samples/%s/c%d.mp4" % (f, i)
                c.execute("INSERT INTO clips VALUES (?,?,?,?,1,1,0,3.0)", (p, app.sfx_id(Path(p)), "c%d" % i, f))
        self.db = c
        self._m = mock.patch.multiple(app, sfx_db_reader=lambda: c, sfx_video_rotation_cycle=lambda: 1,
                                      dj_settings=lambda: {}, sfx_pin_prefix=lambda: "",
                                      sfx_video_recent_folders=lambda: [])
        self._m.start()
        self._r = mock.patch.dict(app._SFX_ROLLED, {}, clear=True)
        self._r.start()

    def tearDown(self):
        self._r.stop()
        self._m.stop()
        super().tearDown()

    def pick(self, desk_ns):
        with mock.patch.dict(app.__dict__, desk_ns):
            return app.sfx_db_pick_rotation_row(True)

    def test_system3_off_the_set_still_gets_a_clip_and_notes_nothing(self):
        for _ in range(12):
            got = self.pick(OFF)
            self.assertIsNotNone(got)
            self.assertTrue(str(got[0]).startswith("/samples/"))
        self.assertEqual(dict(app._SFX_ROLLED), {})

    def test_system3_on_both_rolls_are_noted_on_the_clip(self):
        desk = FakeDesk()
        got = self.pick(desk.ns())
        # the folder roll: the last of the offered folders (sorted) - snl; the clip
        # roll: u 0.42 over its 4 unspent clips - offset 1
        self.assertEqual(str(got[0]), "/samples/snl/c1.mp4")
        self.assertEqual(desk.calls[:2], ["sfxtv.wall_folder", "sfxtv.deck_clip"])
        noted = app._SFX_ROLLED[str(got[0])]
        self.assertEqual(noted["road"], "wall")
        cat, clip = noted["category"], noted["clip"]
        self.assertEqual((cat["label"], cat["key"], cat["index"], cat["of"], cat["dice"]),
                         ("snl", "sfxtv.wall_folder", 3, 3, 91))
        self.assertEqual((clip["index"], clip["of"], clip["dice"]), (2, 4, 43))

    def test_a_clip_heard_today_is_rolled_again_and_never_costs_the_set_its_clip(self):
        desk = FakeDesk()
        app.norepeat_note_sfx(app.sfx_id(Path("/samples/snl/c1.mp4")), "board")
        got = self.pick(desk.ns())
        self.assertIsNotNone(got)
        self.assertNotEqual(str(got[0]), "/samples/snl/c1.mp4")
        # the same die lands on the same heard clip: after six refusals the folder
        # is given up and ANOTHER folder is rolled (snl excluded) - rasslin, offset 1
        self.assertEqual(str(got[0]), "/samples/rasslin/c1.mp4")
        self.assertEqual(desk.calls.count("sfxtv.wall_folder"), 2)
        self.assertTrue(any(r["kind"] == "sfx" and r["road"] == "wall" for r in self.book.state()["refusals"]))

    def test_everything_heard_today_is_refused_not_repeated(self):
        for f, n in self.FOLDERS:
            for i in range(n):
                app.norepeat_note_sfx(app.sfx_id(Path("/samples/%s/c%d.mp4" % (f, i))), "board")
        self.assertIsNone(self.pick(OFF))


class CallerLine(unittest.TestCase):
    def test_bands_and_numbers(self):
        self.assertEqual(app._call_band("10-99"), (10, 99))
        self.assertEqual(app._call_band("42"), (42, 42))
        self.assertEqual(app._call_band("1,000-9,999"), (1000, 9999))
        self.assertEqual(app._call_band("nonsense"), (1, app.CALL_LINES))

    def test_the_number_comes_off_the_table(self):
        with mock.patch.object(app, "s3_pool", lambda k, o, l="": ["42"]):
            self.assertEqual(app.call_line_no(), 42)
        with mock.patch.object(app, "s3_pool", lambda k, o, l="": ["100-999"]):
            n = app.call_line_no()
        self.assertTrue(100 <= n <= 999)
        self.assertEqual(app._CALL_LINE_LAST["row"], "100-999")

    def test_a_prepared_call_keeps_its_written_line(self):
        self.assertEqual(app._prep_line_said({"line": "line 62,528"}), "line 62,528")
        self.assertTrue(app._prep_line_said({}).startswith("line "))
        self.assertIn('NAME THE LINE: {line_say}', SRC)


class Gold(_Tmp):
    def test_forced_gold_roads_stand_down(self):
        self.assertFalse(app.gold_in_round_due())
        self.assertEqual(asyncio.run(app.gold_fill_gap("test")), "")

    def test_the_bank_strikes_lines_heard_today(self):
        rows = [{"key": "k1", "text": "A kept line about the raccoon van and its engine.", "who": "dj"},
                {"key": "k2", "text": "Another kept line about the harbour at night time.", "who": "cohost"}]
        app.norepeat_note_line(rows[0]["text"], "banter")
        with mock.patch.object(app, "_gold_rows", lambda: rows), \
                mock.patch.object(app, "gold_source", lambda r: {"conversation_id": "c"}), \
                mock.patch.object(app, "cast_names_line_stale", lambda r: False):
            bank = app.system3_gold_bank("banter", {})
            self.assertEqual([b["id"] for b in bank], ["k2"])
            self.assertEqual(app.system3_gold_bank("news", {}), [])


class Sweep(unittest.TestCase):
    def test_the_converted_picks_roll(self):
        for tag in ("[everything-rolls:cadence-cue]", "[everything-rolls:gap-video]", "[everything-rolls:gap-audio]",
                    "[everything-rolls:upstairs-voc]",
                    "[everything-rolls:sfxguy-quip]"):
            self.assertIn(tag, SRC)
        self.assertNotRegex(SRC, re.escape("random_float=random.random,"))


if __name__ == "__main__":
    unittest.main()
