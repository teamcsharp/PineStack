"""[s3-cover-b] the last un-rolled, un-stamped audio: every music spin is a
recorded roll on its music_log row (GAP 2), the sampler's three legs roll and
note their clip (GAP 3), the airing doors plan a node for a produced spot, a
music-bed spot, an older manager page and a loose board clip (GAPs 4/5/10),
and a gold bar never airs unstamped while the dice are live (GAP 9).

Imports app (run in the container). Nothing touches the station's data dir:
the dice are a System3Runtime on a temp store; the music log, the recent book
and every library read are patched."""
import asyncio
import inspect
import json
import random
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app
import system3
import system3_runtime
from test_system3_runtime import FakeStation, settle


class Dice:
    """System 3's dice and line door as the station installs them, on a temp store."""

    def __init__(self, mode="active"):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.rt = system3_runtime.System3Runtime(system3_runtime._Host(FakeStation(self.tmp.name)))
        self.rt.settings = system3.normalise_settings({"mode": mode})
        self.rt.ready = True
        system3_runtime._S3_ROLLS.set(None)
        system3_runtime._S3_WRITE.set(None)
        vars(system3_runtime._S3_LAST).clear()

    def door(self):
        rt = self.rt

        async def direct_line(**ctx):
            return await rt.direct_line(ctx)
        return {"system3_chance": rt.chance, "system3_roll": rt.roll, "system3_pick": rt.pick,
                "system3_pool": rt.pool, "system3_last_roll": rt.last_roll,
                "system3_dice_live": rt._dice_live, "system3_direct_line": direct_line,
                "system3_bind_line": rt.bind_line,
                "system3_writing_for": system3_runtime._S3_WRITE}

    def rolls(self, key):
        return [r for r in self.rt.station_view(500) if r["key"] == key]

    def close(self):
        settle()
        self.rt.store.close()
        self.tmp.cleanup()


DOOR_NAMES = ("system3_chance", "system3_roll", "system3_pick", "system3_pool",
              "system3_last_roll", "system3_dice_live", "system3_direct_line",
              "system3_bind_line", "system3_writing_for")


class CoverBase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        # System 3 not installed unless a test asks for the dice
        self.stack.enter_context(mock.patch.dict(app.__dict__, {}))
        for name in DOOR_NAMES:
            app.__dict__.pop(name, None)
        for name, value in (("_recent_load", lambda: None), ("_recent_save", lambda: None),
                            ("_RECENT_DIRTY", [0]), ("_SFX_ROLLED", {}),
                            ("pipeline_log", lambda *a, **k: None)):
            self.patch(**{name: value})

    def patch(self, **values):
        for name, value in values.items():
            self.stack.enter_context(mock.patch.object(app, name, value))

    def dice(self, mode="active"):
        dice = Dice(mode)
        self.addCleanup(dice.close)
        app.__dict__.update(dice.door())
        return dice


# --- GAP 2: EVERY SPIN IS A RECORDED ROLL -------------------------------------
TRACKS = [{"id": "t%d" % i, "station": "x", "path": "/m/%d.mp3" % i, "album": "A",
           "title": "Song %d" % i, "artist": "Band", "seconds": 180.0} for i in range(12)]


class SpinTests(CoverBase):
    def library(self, requests=(), every=3, loved=("t3",)):
        self.radio = {"requests": [dict(r) for r in requests], "queue": [], "station": "all",
                      "since_tape": 0, "recent": {}, "coming": None}
        tape_calls = []

        def mixtape_pick():
            tape_calls.append(1)
            name = app.unrepeated(["Tape A", "Tape B"], "mixtape",
                                  director=app._S3Dice("mixtape.pick", "which MX tape goes on"))
            return {"id": "mx-" + name, "title": name, "tape": True, "seconds": 600.0}
        self.patch(_RADIO=self.radio, dj_settings=lambda: {"mixtape_every": every,
                                                          "radio_skip_folders": ["audiobook"]},
                   music_index=lambda: [dict(t) for t in TRACKS], banned_ids=lambda: set(),
                   loved_ids=lambda: set(loved), music_focus=lambda: {}, radio_paused=lambda: False,
                   _TRACK_TALK={}, _LIBRARY={}, _music_hot_warm=lambda *a, **k: False,
                   track_talk_restore_queue=lambda: 0, mixtape_pick=mixtape_pick,
                   read_requests=lambda: {"r1": {"asked_last": "play the moon song"}},
                   pinelive=mock.Mock(live_track=mock.Mock(return_value=None)),
                   MUSIC_LOG_PATH=self.tmp / "music_log.jsonl", RADIO_CACHE=self.tmp,
                   require_read_auth=lambda authorization: None)
        return tape_calls

    def spins(self, n):
        out = []
        for _ in range(n):
            track = app.dj_next_track()
            app._music_log_append(track)
            out.append(track)
        return out

    def test_every_spin_carries_the_roll_that_let_it_out(self):
        dice = self.dice()
        self.library(requests=[{"id": "r1", "title": "Moon"}])
        got = self.spins(8)
        lanes = [t["s3_spin"]["lane"] for t in got]
        self.assertEqual(lanes[0], "request")
        self.assertIn("mixtape", lanes)
        self.assertGreaterEqual(lanes.count("rotation"), 5)
        for t in got:
            spin = t["s3_spin"]
            self.assertNotIn("forced", spin, spin)
        req = got[0]["s3_spin"]
        self.assertEqual((req["roll"]["key"], req["roll"]["kind"], req["roll"]["hit"]),
                         ("records.request_jump", "chance", True))
        self.assertEqual(req["requested_by"], "play the moon song")
        tape = got[lanes.index("mixtape")]["s3_spin"]
        self.assertEqual(tape["roll"]["key"], "mixtape.pick")
        self.assertEqual(tape["due"]["key"], "records.mixtape_due")
        deal = dice.rolls("records.rotation_deal")
        self.assertEqual(len(deal), 1, "one roll deals the whole shuffle")
        for t in got:
            if t["s3_spin"]["lane"] == "rotation":
                self.assertEqual(t["s3_spin"]["deal"]["dice"], deal[0]["dice"])
                self.assertEqual(t["s3_spin"]["deal"]["key"], "records.rotation_deal")
                self.assertEqual(t["s3_spin"]["deal"]["loved_weight"], 0.3)
        # the library's own rows were never touched
        self.assertTrue(all("s3_spin" not in t for t in TRACKS))
        # the air door wrote each spin's record on its row, and the popup reads it
        rows = [json.loads(x) for x in (self.tmp / "music_log.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(isinstance(r.get("s3"), dict) and r["s3"].get("lane") for r in rows))
        recent = asyncio.run(app.music_spins_recent_api(limit=60, authorization=None))
        self.assertEqual((recent["count"], recent["traced"]), (8, 8))
        one = asyncio.run(app.music_spins_api(got[1]["id"], authorization=None))
        self.assertEqual(one["count"], 1)
        self.assertEqual(list(one["lanes"]), [got[1]["s3_spin"]["lane"]])

    def test_the_desk_rows_appear_once(self):
        dice = self.dice()
        self.library(requests=[{"id": "r1", "title": "Moon"}])
        self.spins(8)
        added = dice.rt.dice_flush()
        for key in ("records.request_jump", "records.mixtape_due", "records.loved_bias"):
            self.assertEqual(added.count(key), 1, (key, added))
        # the deal is a plain roll (a number, not an odds row): recorded, never tabled
        self.assertNotIn("records.rotation_deal", added)
        self.assertEqual(dice.rolls("records.rotation_deal")[0]["kind"], "roll")
        self.radio["requests"].append({"id": "r1", "title": "Moon"})
        self.radio["queue"] = []
        self.spins(8)
        self.assertEqual(dice.rt.dice_flush(), [], "a second pass tables nothing new")
        self.assertGreaterEqual(len(dice.rolls("records.request_jump")), 2)

    def test_the_desk_can_hold_a_request_back(self):
        self.dice()
        self.library(requests=[{"id": "r1", "title": "Moon"}])
        with mock.patch.object(app, "s3_chance", side_effect=lambda key, *a, **k: key != "records.request_jump"):
            got = app.dj_next_track()
        self.assertEqual(got["s3_spin"]["lane"], "rotation")
        self.assertEqual(len(self.radio["requests"]), 1, "the request stays queued")

    def test_live_set_is_an_honest_forced_note(self):
        self.library()
        self.patch(pinelive=mock.Mock(live_track=mock.Mock(return_value={"id": "pl", "title": "Live"})))
        spin = app.dj_next_track()["s3_spin"]
        self.assertTrue(spin["forced"])
        self.assertIn("MX Live", spin["why"])

    def test_dice_off_the_rotation_is_dealt_exactly_as_before(self):
        """Seed sweep, System 3 off: radio_fill's order is the pre-cover_b
        algorithm's (one random.random() deals, loved sorted at 0.3), and the
        request lane spends no draw."""
        self.library(loved=("t3", "t7"))
        loved = {"t3", "t7"}
        for seed in range(200):
            random.seed(seed)
            got = [t["id"] for t in app.radio_fill("all")]
            random.seed(seed)
            ref = [dict(t) for t in TRACKS]
            deal = random.Random(int(random.random() * (1 << 53)))
            deal.shuffle(ref)
            ref.sort(key=lambda t: deal.random() * (0.3 if t["id"] in loved else 1.0))
            self.assertEqual(got, [t["id"] for t in ref], seed)
        self.radio["requests"] = [{"id": "r1", "title": "Moon"}]
        state = random.getstate()
        spin = app.dj_next_track()["s3_spin"]
        self.assertEqual(random.getstate(), state, "the request lane drew nothing")
        self.assertEqual(spin["lane"], "request")
        self.assertTrue(spin["forced"], "no System 3 roll owns it: the honest note")

    def test_dice_live_the_deal_roll_is_unmoved(self):
        """Seed sweep, dice live: the deal is still the FIRST draw on the task's
        station stream (records.loved_bias is drawn after it)."""
        self.dice()
        self.library()
        for seed in ("s%d" % i for i in range(50)):
            system3_runtime._S3_ROLLS.set({"seed": seed, "rolls": [],
                                           "stream": system3.DrawStream("station|" + seed)})
            app.radio_fill("all")
            want = system3.DrawStream("station|" + seed).next("ROLL:records.rotation_deal")["u"]
            self.assertEqual(app._RADIO["rotation_deal_s3"]["u"], want, seed)


# --- GAP 3: THE SAMPLER'S LEGS ROLL AND NOTE THEIR CLIP ---------------------
class SamplerTests(CoverBase):
    def pool(self, fresh=(), unheard=()):
        root = self.tmp / "samples" / "horns"
        root.mkdir(parents=True)
        names = [str(root / ("clip %d.wav" % i)) for i in range(8)]
        pool = [Path(n) for n in names]
        memo = {"unheard": set(unheard), "fresh": set(fresh)}
        self.patch(dj_settings=lambda: {"sfx": True, "sfx_rate": 1.0, "sfx_gap": 0.0},
                   sfx_anxiety=lambda: 0.0, _STING_AT=[0.0], _SFX_POOL_AT=[time.time()],
                   _sting_draw_sets=lambda: (pool, list(names), set(fresh)),
                   sfx_ratio_draw=lambda p, n, f, *a: (p, n, f, None),
                   sfx_ads_share=lambda: 0.0, sfx_video_share=lambda: 0.0,
                   sfx_match_on=lambda *a: False, _STING_DRAW_MEMO=memo,
                   SFX_UNHEARD_SHARE=1.0, SFX_FRESH_SHARE=1.0, STING_SUBPOOL_MIN=2,
                   _RADIO={"recent": {}},
                   _sfx_roll_media=lambda p: {"id": Path(p).name, "kind": "audio",
                                              "thumb": "/api/sfx/spec/x", "thumb_kind": "spectrogram"})
        return names

    def leg(self, which):
        dice = self.dice()
        root = self.tmp / "samples" / "horns"
        every = [str(root / ("clip %d.wav" % i)) for i in range(8)]
        names = self.pool(**({which: every} if which else {}))
        path = app.sting_due("a line")
        self.assertIn(str(path), names)
        rolled = dice.rolls("sfx.sampler")
        self.assertEqual(len(rolled), 1)
        self.assertEqual(rolled[0]["picked"], path.stem)
        note = app._sfx_roll_take(path)
        self.assertEqual(note["road"], "sampler")
        self.assertEqual((note["clip"]["dice"], note["clip"]["of"]),
                         (rolled[0]["dice"], rolled[0]["of"]))
        return note

    def test_the_rotation_leg_rolls_and_notes_the_clip(self):
        self.assertIn("rotation", self.leg("")["category"]["by"])

    def test_the_fresh_leg_rolls_and_notes_the_clip(self):
        self.assertIn("fresh", self.leg("fresh")["category"]["by"])

    def test_the_never_heard_leg_rolls_and_notes_the_clip(self):
        self.assertIn("never-heard", self.leg("unheard")["category"]["by"])

    def test_dice_off_the_draw_is_the_stations_own_as_before(self):
        """Seed sweep, System 3 off: the rotation leg lands where random.choice did."""
        names = self.pool()
        for seed in range(200):
            app._RADIO["recent"] = {}
            random.seed(seed)
            got = app.sting_due("a line")
            random.seed(seed)
            random.random()                                  # sting.drop's own roll
            self.assertEqual(str(got), random.choice(names), seed)
            self.assertEqual(app._sfx_roll_take(got), {}, "no System 3 dice to show")


# --- GAPs 4/5/10: A NODE PLANNED AT THE AIRING DOOR -------------------------
class DoorTests(CoverBase):
    def test_a_produced_spot_row_bd161f_shape_is_stamped_at_its_door(self):
        dice = self.dice()
        self.patch(_RADIO={"chat": [], "ad_now": {}}, dj_settings=lambda: {"host_name": "Caine"})
        sentinel = object()
        system3_runtime._S3_WRITE.set(sentinel)
        row = app.ad_booth_row("Buy the moon.", "Moon Co", ad_id="bd161f", audio="x.mp3",
                               aired="held", air_at=time.time())
        self.assertEqual((row["kind"], row.get("round", "")), ("ad", ""))
        self.assertNotIn("system3", row)
        stamp = asyncio.run(app._s3_door_line("ad_spot", who="dj", context="a produced spot: Moon Co",
                                              text="Buy the moon."))
        row["system3"] = stamp
        self.assertEqual(stamp["road"], "ad_spot")
        self.assertEqual(stamp["mode"], "active")
        self.assertTrue(stamp["conversation_id"] and stamp["turn_id"])
        self.assertIs(system3_runtime._S3_WRITE.get(), sentinel,
                      "the door node never becomes the conversation a later prompt writes for")
        self.assertEqual(app._s3_line_stamp_of(row)["conversation_id"], stamp["conversation_id"])
        src = inspect.getsource(getattr(app, "_air_produced_ad_floorless", app._air_produced_ad))   # [s3-chain-tests]
        self.assertIn('_s3_door_line(\n            "ad_spot"', src)
        self.assertIn('_s3_door_line(\n            "ad_spot"', inspect.getsource(getattr(app, "_dj_music_ad_floorless", app.dj_music_ad)))   # [s3-chain-tests]
        settle()
        self.assertTrue(dice.rt.store.conversation(stamp["conversation_id"]))

    def test_an_older_manager_page_gets_the_same_stamping(self):
        self.dice()
        self.patch(dj_settings=lambda: {})
        stamp = asyncio.run(app._s3_door_line("upstairs", who="manager", seat="C", name="Mr Pine",
                                              context="the coffee", text="Who drank my coffee?"))
        self.assertEqual(stamp["road"], "upstairs")
        src = inspect.getsource(getattr(app, "_dj_upstairs_page_floorless", app.dj_upstairs_page))   # [s3-chain-tests]
        self.assertIn('"upstairs", who="manager", seat="C", name=boss', src)
        self.assertIn("upstairs_update(str(made.get(\"id\") or \"\"),\n                                system3=", src)

    def test_the_door_answers_none_when_system3_does_not(self):
        self.assertIsNone(asyncio.run(app._s3_door_line("ad_spot", text="x")))
        dice = self.dice(mode="off")
        self.patch(dj_settings=lambda: {})
        self.assertIsNone(asyncio.run(app._s3_door_line("ad_spot", text="x")))
        dice.rt.settings = system3.normalise_settings({"mode": "active"})

    def test_a_loose_board_clip_gets_a_node_carrying_its_rolls(self):
        self.dice()
        self.patch(dj_settings=lambda: {})
        roll = {"road": "sampler", "clip": {"label": "air horn", "dice": 41, "of": 8}}
        row = {"who": "board", "kind": "sfx", "text": "air horn", "sfx_roll": roll, "poster": "/p"}
        asyncio.run(app._s3_loose_board_stamp(row, Path("/s/horns/air horn.wav")))
        self.assertEqual(row["system3"]["road"], "interject")
        self.assertEqual(row["system3"]["sfx_roll"], roll)
        self.assertEqual(row["system3"]["poster"], "/p")
        # a row already stamped keeps its node
        kept = {"system3": {"conversation_id": "c1"}}
        asyncio.run(app._s3_loose_board_stamp(kept, Path("/s/a.wav")))
        self.assertEqual(kept["system3"], {"conversation_id": "c1"})
        src = inspect.getsource(app.dj_sting)
        self.assertLess(src.index("_sfx_roll_carry(_sting_row, sample)"),
                        src.index('_RADIO["chat"].append(_sting_row)'))

    def test_dice_off_a_loose_clip_stays_honestly_unstamped(self):
        row = {"who": "board", "kind": "sfx", "text": "x"}
        asyncio.run(app._s3_loose_board_stamp(row, Path("/s/x.wav")))
        self.assertNotIn("system3", row)


# --- GAP 9: NO GOLD BAR AIRS UNSTAMPED WHILE THE DICE ARE LIVE --------------
class GoldTests(CoverBase):
    def bank(self):
        media = self.tmp / "voice_media"
        media.mkdir()
        rows = []
        for i, src in enumerate(({"conversation_id": "c1", "turn_id": "t01"}, None, None)):
            (media / ("g%d.wav" % i)).write_bytes(b"take")
            rows.append({"key": "g%d" % i, "who": "dj", "text": "bar %d" % i, "path": "g%d.wav" % i,
                         "fired": 0, "last": 0, "at": 1.0, **({"source": src} if src else {})})
        self.patch(_gold_rows=lambda: rows, VOICE_MEDIA_DIR=media, repeat_window=lambda: 0.0,
                   cast_names_line_stale=lambda r: False, _s3_active=lambda: False)
        return rows

    def test_under_selected_roads_only_sourced_bars_are_picked(self):
        self.dice(mode="active_selected_roads")
        rows = self.bank()
        for _ in range(30):
            for r in rows:
                r["last"] = 0
            bar = app.gold_pick(min_rest=300.0)
            self.assertEqual(bar["key"], "g0")
            self.assertTrue(app.gold_air_stamp(bar))

    def test_system3_off_the_bank_is_as_it_was(self):
        rows = self.bank()
        seen = set()
        for seed in range(40):
            random.seed(seed)
            for r in rows:
                r["last"] = 0
            seen.add(app.gold_pick(min_rest=300.0)["key"])
        self.assertEqual(seen, {"g0", "g1", "g2"})

    def test_an_unstampable_bar_ends_the_run_rather_than_looping(self):
        src = inspect.getsource(app.gold_fill_gap)
        refuse = src.index("refused at the door")
        self.assertLess(src.index("break", refuse), src.index("out = await _door", refuse))
        self.assertNotIn("continue", src[refuse:src.index("out = await _door", refuse)])


if __name__ == "__main__":
    unittest.main()
