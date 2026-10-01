"""[call-prod] produced calls: a banked call mixed take by take while paused.

"we have produced phone calls similar to produced ads where during the pause time of
the station we can have actual sound effects and things mixed in with phone calls to
make them more riveting." He picked all four: the line's sounds, the caller's
background, SFX hits on the beats and a music bed under the win."""
import asyncio
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import call_producer as cp

LEGS = ["answer", "introduce", "greet", "arc_raises", "arc_fuels", "arc_boils", "resolution", "reaction",
        "rebuttal", "wrap_call"]
SEATS = ["A", "C", "A", "C", "B", "C", "A", "C", "C", "A"]


def always(key, odds, label):
    return True


def never(key, odds, label):
    return False


def heaviest(key, options, weights, label):
    return max(range(len(weights)), key=lambda i: weights[i])


class Plan(unittest.TestCase):
    """[no-wedge] the plan offers doors; only the dice put a sound in."""

    def test_every_sound_is_a_door_with_odds(self):
        doors = cp.plan_production(LEGS, SEATS, {"resolve": {"tags": ["won"]}, "wrap": {"polite": True}})
        keys = [d["key"] for d in doors]
        for k in ("call.produced.ring", "call.produced.hiss", "call.produced.background", "call.produced.peak_hit",
                  "call.produced.reaction", "call.produced.hangup"):
            self.assertIn(k, keys)
        for d in doors:
            self.assertIn(d["kind"], ("chance", "choice"))
            if d["kind"] == "chance":
                self.assertTrue(0 < d["odds"] < 1, d)          # never certain: it is a roll
            else:
                self.assertTrue(all(w > 0 for w in d["weights"]), d)   # every option can come up

    def test_all_doors_open(self):
        plan, rolled = cp.resolve_plan(cp.plan_production(
            LEGS, SEATS, {"resolve": {"tags": ["won", "prize"]}, "wrap": {"polite": True}}), always, heaviest)
        self.assertEqual(plan[0]["pre"], ["ring", "pickup"])
        for i, seat in enumerate(SEATS):
            under = (plan.get(i) or {}).get("under") or []
            self.assertEqual("ambience" in under, seat == "C", (i, seat))
        self.assertIn("hit:tension", plan[LEGS.index("arc_boils")]["post"])
        self.assertIn("bed:win", plan[LEGS.index("reaction")]["under"])
        self.assertEqual(plan[len(LEGS) - 1]["post"], ["hangup_click"])
        self.assertEqual(len(rolled), 6)

    def test_all_doors_shut_leave_only_the_picks(self):
        plan, rolled = cp.resolve_plan(cp.plan_production(LEGS, SEATS, {"resolve": {"tags": ["refused"]}}),
                                       never, heaviest)
        self.assertNotIn(0, plan)
        self.assertEqual(plan[7]["post"], ["hit:lose"])          # the outcome leans, the pick is still a pick
        self.assertEqual(plan[9]["post"], ["hangup_slam"])
        self.assertTrue(all(r.get("hit") is False for r in rolled if "hit" in r))

    def test_the_outcome_leans_but_never_decides(self):
        dead = cp.plan_production(LEGS, SEATS, {"wrap": {"dead_line": True}})
        hang = next(d for d in dead if d["key"] == "call.produced.hangup")
        self.assertEqual(hang["options"][hang["weights"].index(max(hang["weights"]))], "the busy tone")
        plan, _ = cp.resolve_plan(dead, never, lambda key, o, w, l: 0)     # the dice land on the click anyway
        self.assertEqual(plan[9]["post"], ["hangup_click"])

    def test_the_manager_gets_the_intercom_door(self):
        legs = LEGS[:7] + ["manager_cuts_in"] + LEGS[7:]
        seats = SEATS[:7] + ["E"] + SEATS[7:]
        doors = cp.plan_production(legs, seats, {"resolve": {"manager_act": "x", "tags": ["manager"]}})
        door = next(d for d in doors if d["key"] == "call.produced.intercom")
        self.assertEqual(door["at"], [legs.index("manager_cuts_in")])
        bg = next(d for d in doors if d["key"] == "call.produced.background")
        self.assertNotIn(legs.index("manager_cuts_in"), bg["at"])

    def test_keys_are_new_and_stable(self):
        a = cp.production_key("k1", {"pre": ["ring"]}, {"ambience": "/x.wav"})
        self.assertTrue(a.startswith("prod-"))
        self.assertEqual(a, cp.production_key("k1", {"pre": ["ring"]}, {"ambience": "/x.wav"}))
        self.assertNotEqual(a, cp.production_key("k1", {"pre": ["ring"]}, {"ambience": "/y.wav"}))


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
class Mix(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, src in (("voice.mp3", "sine=f=220:d=3:sample_rate=24000"),
                          ("amb.wav", "anoisesrc=d=2:c=brown:r=24000"), ("hit.wav", "sine=f=880:d=6:sample_rate=24000")):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, "-ac", "1",
                            str(self.tmp / name)], check=True)
        self.assets = {"ambience": str(self.tmp / "amb.wav"), "hit:tension": str(self.tmp / "hit.wav"),
                       "hit:win": str(self.tmp / "hit.wav"), "bed:win": str(self.tmp / "amb.wav")}

    def test_every_sound_lands_and_the_take_is_untouched(self):
        voice = self.tmp / "voice.mp3"
        before = voice.read_bytes()
        for ops, want in (({"pre": ["ring", "pickup"], "under": ["hiss", "ambience"]}, 5.66),
                          ({"post": ["hit:tension"]}, 7.0), ({"under": ["bed:win"], "post": ["hit:win"]}, 7.0),
                          ({"post": ["hangup_slam"]}, 4.8), ({"post": ["busy"]}, 5.0), ({"pre": ["intercom"]}, 3.5)):
            out = self.tmp / "out.mp3"
            self.assertTrue(cp.mix_take(voice, out, ops, self.assets), ops)
            self.assertAlmostEqual(cp.seconds_of(out), want, delta=0.25)
        self.assertEqual(voice.read_bytes(), before)

    def test_a_missing_asset_is_skipped_not_fatal(self):
        out = self.tmp / "out.mp3"
        self.assertTrue(cp.mix_take(self.tmp / "voice.mp3", out, {"pre": ["ring"], "post": ["hit:win"]}, {}))
        self.assertAlmostEqual(cp.seconds_of(out), 5.6, delta=0.25)
        self.assertFalse(cp.mix_take(self.tmp / "voice.mp3", out, {"post": ["hit:win"]}, {}))


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
class Station(unittest.TestCase):
    def test_a_banked_call_is_produced_into_new_takes(self):
        import app
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        media = tmp / "voice_media"
        media.mkdir()
        legs, seats = ["answer", "introduce", "reaction", "wrap_call"], ["A", "C", "C", "A"]
        takes, pantry = [], {}
        for i in range(4):
            name = "take%d.mp3" % i
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            "sine=f=%d:d=2:sample_rate=24000" % (200 + 50 * i), "-ac", "1", str(media / name)], check=True)
            key = "k%d" % i
            pantry[key] = {"clip": {"path": "/media/" + name, "sig": "s", "seconds": 2.0}, "at": 0, "text": "t%d" % i}
            takes.append({"i": i, "key": key, "text": "line %d" % i, "voice": "v", "who": "dj" if seats[i] == "A" else "caller"})
        amb = tmp / "amb.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anoisesrc=d=2:c=brown:r=24000",
                        str(amb)], check=True)
        entry = {"takes": takes, "keys": [t["key"] for t in takes], "chunks": 4, "prep_name": "Dana",
                 "call": {"callend": {"legs": legs, "seats": seats, "resolve": {"tags": ["won"]}, "wrap": {"polite": True}}}}
        row = {"entry": entry, "aired": 0}

        async def asset(name):
            return (str(amb), "test " + name)
        with mock.patch.object(app, "VOICE_MEDIA_DIR", media), \
                mock.patch.dict(app._PANTRY, pantry, clear=True), \
                mock.patch.object(app, "radio_paused", lambda: True), \
                mock.patch.object(app, "shelf_rows", lambda k: [row] if k == "caller" else []), \
                mock.patch.object(app, "dialogue_row_ready", lambda k, r: True), \
                mock.patch.object(app, "row_unaired", lambda r: True), \
                mock.patch.object(app, "_call_prod_asset", asset), \
                mock.patch.object(app, "s3_chance", lambda *a, **k: True), \
                mock.patch.object(app, "s3_weighted", lambda key, o, w, l="", **k: 0), \
                mock.patch.object(app, "_pantry_save", lambda *a, **k: None), \
                mock.patch.object(app, "station_flow_event", lambda *a, **k: None):
            got = asyncio.run(app.call_produce_tick())
            self.assertEqual(got, "produced")
            self.assertEqual(entry["produced"]["takes"], 4)
            for i, t in enumerate(entry["takes"]):
                self.assertTrue(t["key"].startswith("prod-"))
                clip = app._PANTRY[t["key"]]["clip"]
                self.assertTrue(clip["produced"])
                self.assertTrue((media / clip["path"].rsplit("/", 1)[-1]).is_file())
                self.assertIn("k%d" % i, app._PANTRY)              # the cached take is still there, untouched
            self.assertEqual(entry["keys"], [t["key"] for t in entry["takes"]])
            self.assertGreater(entry["seconds"], 8.0)              # the ring, the hit and the hang-up were added
            self.assertEqual(asyncio.run(app.call_produce_tick()), "")   # produced once
            self.assertTrue(entry["produced"]["rolled"])                 # every door's roll is on the record


if __name__ == "__main__":
    unittest.main()
