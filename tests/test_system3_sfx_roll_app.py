"""[s3-sfx-roll] app.py's pick roads under System 3's dice: the board's clip
is the family, then the clip - two recorded rolls - and the addition row, the
ledger stamp and the node carry what they landed on, with the clip's picture.

Imports app (run in the container). Nothing here touches the station's data
dir: the dice are a System3Runtime on a temp store, and the recent book, the
clip book, the script ledger and every share read are patched."""
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app
import system3
import system3_runtime
from test_air_order import LedgerSandbox
from test_system3_runtime import FakeStation, settle

ROLL = {"road": "book", "category": {"label": "moon", "dice": 12, "u": 0.11, "of": 2, "index": 1},
        "clip": {"label": "landing", "dice": 55, "u": 0.54, "of": 3, "index": 2, "tries": 1}}


class Dice:
    """System 3's dice as the station installs them - live, on a temp store."""

    def __init__(self, mode="active"):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.rt = system3_runtime.System3Runtime(system3_runtime._Host(FakeStation(self.tmp.name)))
        self.rt.settings = system3.normalise_settings({"mode": mode})
        self.rt.ready = True
        system3_runtime._S3_ROLLS.set(None)
        vars(system3_runtime._S3_LAST).clear()
        self.pick = mock.Mock(side_effect=self.rt.pick)

    def door(self):
        return {"system3_pick": self.pick, "system3_last_roll": self.rt.last_roll,
                "system3_dice_live": self.rt._dice_live}

    def rolls(self, key):
        return [r for r in self.rt.station_view() if r["key"] == key]

    def weights(self, key):
        """The weights the road handed the door for its last roll under `key`."""
        call = [c for c in self.pick.call_args_list if c.args[0] == key][-1]
        return dict(zip(call.args[1], call.args[3]))

    def close(self):
        settle()
        self.rt.store.close()
        self.tmp.cleanup()


class SfxRollAppTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        # the recent book is the station's data dir: never written from here
        for name, value in (("_RADIO", {"recent": {}}), ("_recent_load", lambda: None),
                            ("_recent_save", lambda: None), ("_RECENT_DIRTY", [0]),
                            ("_SFX_CADENCE_STATUS", {}), ("_SFX_ROLLED", {})):
            self.stack.enter_context(mock.patch.object(app, name, value))

    def dice(self, mode="active"):
        dice = Dice(mode)
        self.addCleanup(dice.close)
        self.stack.enter_context(mock.patch.dict(app.__dict__, dice.door()))
        return dice

    def patch(self, **values):
        for name, value in values.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    # --- the drop folders' pool ------------------------------------------------
    def pool(self, weights=None, missing=()):
        root = self.tmp / "samples"
        paths = []
        for fam, names in (("horns", ["air horn.wav", "bike horn.wav"]), ("laughs", ["giggle.wav"])):
            (root / fam).mkdir(parents=True, exist_ok=True)
            for name in names:
                path = root / fam / name
                if name not in missing:
                    path.write_bytes(b"recorded")
                paths.append(path)
        self.patch(SFX_ROOT=root, SFX_LOCAL_ROOT=self.tmp / "local", _SFX_POOL_CACHE=paths,
                   dj_settings=mock.Mock(return_value={"sfx_drop_folders": ["horns", "laughs"]}),
                   sfx_id=lambda p: Path(p).name, sfx_bans=lambda: set(),
                   sfx_weights=lambda: dict(weights or {}), sfx_cap_seconds=lambda: 4.0,
                   sfx_seconds=lambda p: 1.0)
        return paths

    def test_the_pool_rolls_the_family_then_the_clip_and_notes_both(self):
        dice = self.dice()
        self.pool()
        path = app._sfx_cadence_pick()
        self.assertIsNotNone(path)
        cat, clip = dice.rolls("sfx.category"), dice.rolls("sfx.clip")
        self.assertEqual((len(cat), len(clip)), (1, 1))
        self.assertEqual(cat[0]["picked"], path.parent.name)
        self.assertEqual(sorted(cat[0]["candidates"]), ["horns", "laughs"])
        self.assertEqual(clip[0]["picked"], path.stem)
        self.assertEqual(clip[0]["label"], "which clip in " + path.parent.name)
        self.assertEqual(clip[0]["media"]["thumb_kind"], "spectrogram")
        self.assertNotIn("poster", clip[0], "an audio clip has no frame")
        got = app._sfx_roll_take(path)
        self.assertEqual(got["road"], "pool")
        self.assertEqual(got["category"], {"label": path.parent.name, "dice": cat[0]["dice"], "u": cat[0]["u"],
                                           "of": 2, "index": cat[0]["index"]})
        self.assertEqual((got["clip"]["label"], got["clip"]["dice"], got["clip"]["of"], got["clip"]["tries"]),
                         (path.stem, clip[0]["dice"], clip[0]["of"], 1))

    def test_a_family_weighs_the_sum_of_its_clips(self):
        dice = self.dice()
        self.pool(weights={"air horn.wav": 1.0, "bike horn.wav": 3.0, "giggle.wav": 0.06})
        path = app._sfx_cadence_pick()
        self.assertEqual(dice.weights("sfx.category"), {"horns": 4.0, "laughs": 0.06})
        if path.parent.name == "horns":
            self.assertEqual(dice.weights("sfx.clip"), {"air horn": 1.0, "bike horn": 3.0})

    def test_a_clip_that_fails_the_file_check_is_rolled_again_and_both_rolls_are_recorded(self):
        dice = self.dice()
        self.pool(weights={"air horn.wav": 1e9, "bike horn.wav": 0.06, "giggle.wav": 0.06},
                  missing=("air horn.wav",))
        path = app._sfx_cadence_pick()
        self.assertNotEqual(path.name, "air horn.wav")
        clip = dice.rolls("sfx.clip")
        self.assertEqual([r["picked"] for r in clip], ["air horn", path.stem])
        self.assertEqual(len(dice.rolls("sfx.category")), 2)
        self.assertEqual(app._sfx_roll_take(path)["clip"]["tries"], 2)

    def test_system3_off_the_station_rolls_its_own_and_notes_nothing(self):
        dice = self.dice(mode="off")
        paths = self.pool()
        path = app._sfx_cadence_pick()
        self.assertIn(path, paths)
        self.assertEqual(dice.rt.station_view(), [])
        self.assertEqual(app._sfx_roll_take(path), {})

    # --- the clip book -------------------------------------------------------------
    def book(self):
        db = sqlite3.connect(":memory:", check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE clips(path,seconds,playable,video,deck_cycle,folder)")
        db.executemany("INSERT INTO clips VALUES(?,?,?,?,?,?)",
                       [("/clips/moon/%s.mp4" % n, 3, 1, 1, 0, "moon") for n in ("landing", "crater", "rover")]
                       + [("/clips/vine/%s.mp4" % n, 2, 1, 1, 0, "vine") for n in ("oops", "yeet")]
                       + [("/clips/vine/long.mp4", 90, 1, 1, 0, "vine")])
        self.addCleanup(db.close)
        self.patch(sfx_db_reader=lambda: db, sfx_video_rotation_cycle=lambda: 1,
                   sfx_video_recent_folders=lambda: [], sfx_pin_prefix=lambda: "")
        return db

    def test_the_book_rolls_its_folder_then_the_clip_when_asked(self):
        dice = self.dice()
        self.book()
        rolled = {}
        path, seconds = app.sfx_db_pick_short_video(12.0, rolled=rolled)
        folder = path.parent.name
        self.assertEqual(rolled["category"]["label"], folder)
        self.assertEqual(rolled["category"]["of"], 2)
        self.assertEqual(rolled["clip"]["label"], path.stem)
        self.assertEqual(rolled["clip"]["of"], 3 if folder == "moon" else 2, "the long clip is not on the wheel")
        rec = dice.rolls("sfx.clip")[-1]
        self.assertEqual(rec["dice"], rolled["clip"]["dice"])
        self.assertTrue(rec["poster"].startswith("/api/sfx/poster/%s?t=" % app.sfx_id(path)))
        # not asked for the board's roll: the book's own draw (the endless set,
        # the deck) is System 3's too since dice3 part 3 - under its own keys,
        # never recorded as the board's category/clip
        keys = lambda: [r.get("key") for r in dice.rt.station_view()]
        before = keys()
        self.assertIsNotNone(app.sfx_db_pick_short_video(12.0))
        after = keys()
        self.assertEqual(after.count("sfx.clip"), before.count("sfx.clip"))
        self.assertEqual(after.count("sfx.category"), before.count("sfx.category"))
        self.assertIn("sfxtv.short_folder", after[len(before):])

    def picture_road(self):
        wav = self.tmp / "levelled.wav"
        wav.write_bytes(b"levelled")
        self.patch(sfx_match_on=lambda _video=False: False, sfx_bans=lambda: set(), sfx_weights=lambda: {},
                   sting_recent=lambda _p: False, sfx_video_on_cooldown=lambda _k: False,
                   sfx_cap_seconds=lambda: 12.0, _as_wav=lambda _p, timeout=4.0: wav,
                   sfx_is_silent=lambda _p: False, sfx_levelled=lambda p: p,
                   _sfx_video_rotation_mark_clip=mock.Mock(), sfx_level_submit=mock.Mock())
        return wav

    def test_the_picture_road_stops_at_the_two_it_tries_and_notes_the_books_rolls(self):
        dice = self.dice()
        self.book()
        self.picture_road()
        path, audio, seconds, why = app._sfx_cadence_video_pick("a line")
        self.assertEqual((len(dice.rolls("sfx.category")), len(dice.rolls("sfx.clip"))), (2, 2),
                         "a roll nobody would try is not on the record")
        got = app._sfx_roll_take(path)
        self.assertEqual((got["road"], got["clip"]["label"], got["clip"]["tries"]), ("book", path.stem, 1))

    def test_system3_off_the_picture_road_draws_as_it_always_did(self):
        self.dice(mode="off")
        self.book()
        self.picture_road()
        real = app.sfx_db_pick_short_video
        spy = mock.Mock(side_effect=lambda cap: real(cap))
        self.patch(sfx_db_pick_short_video=spy)
        self.assertIsNotNone(app._sfx_cadence_video_pick("a line"))
        self.assertEqual(spy.call_count, min(6, app.SFX_CADENCE_TRIES))
        self.assertTrue(all(len(c.args) == 1 and not c.kwargs for c in spy.call_args_list))

    # --- the matcher's tied peers --------------------------------------------------
    def test_which_matched_peer_plays_is_a_recorded_pick_by_name(self):
        dice = self.dice()
        peers = ["/clips/moon/landing.mp4", "/clips/moon/crater.mp4"]
        got = app.unrepeated(peers, "s3-sfx-roll-test", keep=0,
                             director=app._S3ClipDice("sfx.match", "which matched clip"))
        rec = dice.rolls("sfx.match")[-1]
        self.assertEqual(rec["candidates"], ["landing", "crater"])
        self.assertEqual(rec["picked"], Path(got).stem)
        self.assertTrue(rec["poster"].startswith("/api/sfx/poster/"))
        self.assertEqual(app._s3_sfx_rolled("sfx.match", Path(got).stem)["dice"], rec["dice"])
        import inspect
        self.assertIn('_S3ClipDice("sfx.match"', inspect.getsource(app.sfx_match_sting_pick))

    # --- the addition row, the ledger stamp ------------------------------------------
    def test_the_addition_row_carries_the_rolls_and_the_picture_once(self):
        video = Path("/clips/moon/landing.mp4")
        sid = app.sfx_id(video)
        app._sfx_roll_note(video, "book", ROLL["category"], ROLL["clip"], 1)
        row = {"who": "board"}
        app._sfx_roll_carry(row, video)
        self.assertEqual(row["poster"], "/api/sfx/poster/%s?t=%s" % (sid, app.media_sign(sid)))
        self.assertEqual(row["sfx_roll"]["clip"]["dice"], 55)
        self.assertEqual((row["sfx_roll"]["thumb"], row["sfx_roll"]["thumb_kind"]), (row["poster"], "frame"))
        again = {"who": "board"}
        app._sfx_roll_carry(again, video)
        self.assertNotIn("sfx_roll", again, "a note is taken once")
        self.assertIn("poster", again)
        audio = {"who": "board"}
        app._sfx_roll_carry(audio, Path("/samples/horns/air horn.wav"))
        self.assertEqual(audio, {"who": "board"}, "no roll, no frame: nothing to carry")
        app._sfx_roll_note(video, "pool", {}, {}, 1)
        self.assertEqual(app._sfx_roll_take(video), {}, "the station's own draw notes nothing")

    def test_the_ledger_row_keeps_the_stamps_rolls_and_poster(self):
        poster = "/api/sfx/poster/abc?t=x"
        with LedgerSandbox() as box:
            app.script_ledger_commit("sid-1", [
                {"line_id": "B1", "who": "board", "kind": "sfx", "text": "landing",
                 "system3": {"conversation_id": "c1", "mode": "active", "turn_id": "",
                             "sfx_roll": ROLL, "poster": poster}}], "banter")
            row = box.rows()[-1]
        self.assertEqual(row["system3"]["sfx_roll"], ROLL)
        self.assertEqual(row["system3"]["poster"], poster)


if __name__ == "__main__":
    unittest.main()
