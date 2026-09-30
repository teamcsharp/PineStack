# -*- coding: utf-8 -*-
"""[reply-gap] the pause between replies: bounds, the roll's window, the
settings on disk, the seams it applies to, a produced round's cue map, and the
segment planner budgeting (N - 1) pauses.

Pure (no station): python3 -m pytest tests/test_reply_gap_2026_09_30.py
"""
import json
import random
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import reply_gap as rg  # noqa: E402


class Bounds(unittest.TestCase):
    def test_gap_is_point_two_to_ten_default_one(self):
        self.assertEqual(rg.GAP_MIN, 0.2)
        self.assertEqual(rg.GAP_MAX, 10.0)
        self.assertEqual(rg.GAP_DEFAULT, 1.0)
        self.assertEqual(rg.clamp_gap(0), 0.2)
        self.assertEqual(rg.clamp_gap(-5), 0.2)
        self.assertEqual(rg.clamp_gap(0.2), 0.2)
        self.assertEqual(rg.clamp_gap(10), 10.0)
        self.assertEqual(rg.clamp_gap(99), 10.0)
        self.assertEqual(rg.clamp_gap("junk"), 1.0)
        self.assertEqual(rg.clamp_gap(float("nan")), 1.0)
        self.assertEqual(rg.clamp_gap(1.73), 1.7)        # the slider's step

    def test_range_bounds(self):
        self.assertEqual(rg.clamp_range(0), 0.2)   # [reply-gap:between] a time, like the gap
        self.assertEqual(rg.clamp_range(50), 10.0)
        self.assertEqual(rg.clamp_range(None), 1.0)

    def test_defaults(self):
        got = rg.normalise({})
        self.assertEqual((got["gap"], got["range"], got["roll"]), (1.0, 1.0, False))
        self.assertIs(rg.normalise({"roll": "on"})["roll"], True)


class TheRoll(unittest.TestCase):
    def test_window_is_between_the_two_sliders(self):
        # [reply-gap:between] "only rolling values between slider 1 and slider 2"
        self.assertEqual(rg.window({"gap": 1, "range": 1.9}), (1.0, 1.9))
        self.assertEqual(rg.window({"gap": 5, "range": 2}), (2.0, 5.0))    # either way round
        self.assertEqual(rg.window({"gap": 1, "range": 1}), (1.0, 1.0))    # equal: no spread
        self.assertEqual(rg.window({"gap": 0.2, "range": 0.1}), (0.2, 0.2))  # 0.1 clamps to 0.2
        self.assertEqual(rg.window({"gap": 9.5, "range": 12}), (9.5, 10.0))

    def test_expected_is_the_gap_or_the_window_middle(self):
        self.assertEqual(rg.expected({"gap": 3, "range": 1, "roll": False}), 3.0)
        self.assertEqual(rg.expected({"gap": 5, "range": 2, "roll": True}), 3.5)
        self.assertEqual(rg.expected({"gap": 1, "range": 1.9, "roll": True}), 1.45)

    def test_every_roll_lands_inside_the_window_on_the_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            rg.use_path(Path(tmp) / "reply_gap.json")
            rg.save({"gap": 0.2, "range": 2.0, "roll": True})   # [reply-gap:between]
            rng = random.Random(7)
            seen = set()
            for _ in range(500):
                got = rg.draw(rng=rng)
                self.assertTrue(got["rolled"])
                self.assertTrue(0.2 <= got["s"] <= 2.0, got)
                self.assertAlmostEqual(got["s"] * 10, round(got["s"] * 10))
                self.assertTrue(1 <= got["dice"] <= 100)
                seen.add(got["s"])
            self.assertGreater(len(seen), 12, "a roll that never varies is not a roll")
            self.assertIn(0.2, seen)
            self.assertIn(2.0, seen)
            rg.save({"roll": False})
            self.assertEqual(rg.draw(rng=rng), {"s": 0.2, "rolled": False})   # roll off: slider one
            self.assertTrue(rg.recent(3), "each roll leaves a receipt")
            rg.use_path(None)

    def test_gap_from_u_ends(self):
        self.assertEqual(rg.gap_from_u(0.0, 0.2, 2.0), 0.2)
        self.assertEqual(rg.gap_from_u(0.999999, 0.2, 2.0), 2.0)
        self.assertEqual(rg.dice_of(0.0), 1)
        self.assertEqual(rg.dice_of(0.999), 100)


class Persistence(unittest.TestCase):
    def test_saved_to_disk_and_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "reply_gap.json"
            rg.use_path(path)
            self.assertEqual(rg.settings()["gap"], 1.0)          # no file: the default
            rg.save({"gap": 3.33, "range": 12, "roll": True}, by="test")
            on_disk = json.loads(path.read_text())
            self.assertEqual((on_disk["gap"], on_disk["range"], on_disk["roll"]), (3.3, 10.0, True))
            rg.use_path(path)                                     # a fresh process
            got = rg.state()
            self.assertEqual((got["gap"], got["range"], got["roll"]), (3.3, 10.0, True))
            self.assertEqual(got["bounds"]["gap"], [0.2, 10.0])
            self.assertEqual((got["lo"], got["hi"]), (3.3, 10.0))
            rg.save({"gap": 0.5})                                 # a partial POST keeps the rest
            self.assertEqual(rg.settings()["range"], 10.0)
            rg.use_path(None)


def _items():
    return [
        {"who": "dj", "turn_end": False},       # 0: SKIP, first clip of a turn
        {"who": "dj", "turn_end": True},        # 1: ...the same turn's last clip
        {"who": "cohost", "turn_end": True},    # 2: DILL answers
        {"who": "dj", "turn_end": True, "listening_response": True},  # 3: "mm-hm"
        {"who": "cohost", "turn_end": True},    # 4
    ]


class Seams(unittest.TestCase):
    def test_which_seams_are_replies(self):
        items = _items()
        # seg: [ring, i0, i1, sting, i2, i3, i4, hangup]
        seg_ix = [1, 2, 3, 4, 5, 6]
        turn_ix = [0, 1, -1, 2, 3, 4]
        flags = rg.reply_seams(8, seg_ix, turn_ix, items)
        self.assertNotIn(0, flags, "the ring is not a reply")
        self.assertFalse(flags[1], "two clips of one speaker's turn keep the beat")
        self.assertTrue(flags[2], "a DJ turn into the SFX Guy's sting is a reply seam")
        self.assertTrue(flags[3], "the sting into the next DJ is a reply seam")
        self.assertFalse(flags[4], "into a listening response keeps the beat")
        self.assertFalse(flags[5], "out of a listening response keeps the beat")
        self.assertTrue(flags[6], "the last line into the hang-up")

    def test_burst_sets_reply_seams_and_carries(self):
        with tempfile.TemporaryDirectory() as tmp:
            rg.use_path(Path(tmp) / "g.json")
            rg.save({"gap": 2.5, "roll": False})
            items = [{"who": "dj", "turn_end": False}, {"who": "dj", "turn_end": True},
                     {"who": "cohost", "turn_end": True}]
            transcript = [("dj", "a", 3), ("dj", "b", 3), ("drop", "boom", 1), ("cohost", "c", 3)]
            beats = [0.1, 0.1, 0.1, 0.0]
            self.assertTrue(rg.CARRY_BY_DOOR, "the page door owns the pause into the next page")
            out, notes = rg.burst(beats, [0, 1, 2, 3], [0, 1, -1, 2], transcript, items, carry=True)
            self.assertNotIn("carry", notes, "no second pause: the door seams the next page")
            rg.CARRY_BY_DOOR = False
            out, notes = rg.burst(beats, [0, 1, 2, 3], [0, 1, -1, 2], transcript, items, carry=True)
            rg.CARRY_BY_DOOR = True
            self.assertEqual(out, [0.1, 2.5, 2.5, 0.0])
            self.assertEqual(notes["carry"]["s"], 2.5, "the pause into the next page")
            rows = [{"until": 3.1}, {"until": 8.6}, {"until": 12.1}, {"until": 15.1}]
            rg.stamp_rows(rows, [0, 1, 2, 3], notes)
            self.assertNotIn("gap", rows[0])
            self.assertEqual(rows[1]["gap"]["s"], 2.5)
            self.assertEqual(rows[1]["gap"]["inside"], 2.5)
            self.assertEqual(rows[3]["gap"]["inside"], 0.0)
            self.assertAlmostEqual(rg.carry_seconds(notes, 16.06, rows), 1.54, places=3)
            out, notes = rg.burst(beats, [0, 1, 2, 3], [0, 1, -1, 2], transcript, items, carry=False)
            self.assertNotIn("carry", notes)
            self.assertEqual(out[-1], 0.0, "the file's last segment never gets a beat")
            self.assertEqual(rg.plain(3), [2.5, 2.5, 0.0])
            rg.use_path(None)


class PageDoor(unittest.TestCase):
    """[reply-gap:door] the pause before every message on the page feed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        rg.use_path(Path(self.tmp.name) / "g.json")
        rg._BOOKED.update(until=0.0, tail=0.0)

    def tearDown(self):
        rg.use_path(None)
        self.tmp.cleanup()

    def clip(self, **kw):
        base = {"url": "/media/" + "a" * 32 + ".wav", "text": "a line", "speech": True}
        base.update(kw)
        return base

    def test_what_is_a_message(self):
        self.assertTrue(rg.is_message(self.clip()))
        self.assertTrue(rg.is_message({"url": "/sfx/abc", "sting": True}), "the SFX Guy's sting")
        self.assertFalse(rg.is_message(self.clip(kind="reply")), "a person's reply is exempt (#206)")
        self.assertFalse(rg.is_message(self.clip(picture_only=True)))
        self.assertFalse(rg.is_message({"text": "no audio"}))

    def test_the_pause_follows_the_words_not_the_tail(self):
        rg.save({"gap": 2.0, "roll": False})
        prev = self.clip()
        rg.booked(dict(prev, tail_s=0.9), 100.0)            # the air ends at 100, 0.9 s of it silence
        nxt = self.clip(broadcast_ms=100000)
        start = rg.door(nxt, 100.0, 95.0, tail_of=lambda c: 0.8)
        self.assertAlmostEqual(start, 99.1 + 2.0, places=6)
        self.assertEqual(nxt["gap_before"]["s"], 2.0)
        self.assertEqual(nxt["tail_s"], 0.8)
        self.assertEqual(rg.overlap(nxt), 0.0)

    def test_a_short_pause_starts_inside_the_silent_tail(self):
        rg.save({"gap": 0.2, "roll": False})
        rg.booked(dict(self.clip(), tail_s=0.9), 100.0)
        nxt = self.clip(broadcast_ms=100000)
        start = rg.door(nxt, 100.0, 95.0)
        self.assertAlmostEqual(start, 99.3, places=6)
        self.assertAlmostEqual(rg.overlap(nxt), 0.7, places=6)

    def test_a_tail_that_is_not_the_cursors_is_not_trusted(self):
        rg.save({"gap": 0.2, "roll": False})
        rg.booked(dict(self.clip(), tail_s=0.9), 80.0)       # some other clip's end
        nxt = self.clip(broadcast_ms=100000)
        self.assertAlmostEqual(rg.door(nxt, 100.0, 95.0), 100.2, places=6)

    def test_a_quiet_air_has_no_seam_and_rolls_nothing(self):
        rg.save({"gap": 1.0, "range": 1.0, "roll": True})
        before = len(rg.recent(500))
        nxt = self.clip(broadcast_ms=200000)
        self.assertEqual(rg.door(nxt, 100.0, 200.0, rng=random.Random(1)), 200.0)
        self.assertNotIn("gap_before", nxt)
        self.assertEqual(len(rg.recent(500)), before)

    def test_a_clip_held_later_by_its_maker_is_never_moved_earlier(self):
        rg.save({"gap": 1.0, "roll": False})
        nxt = self.clip(broadcast_ms=130000)                 # the sequencer said 130
        self.assertEqual(rg.door(nxt, 100.0, 95.0), 130.0)

    def test_rolling_every_message_gets_its_own_receipted_roll(self):
        rg.save({"gap": 1.0, "range": 1.9, "roll": True})
        rng = random.Random(3)
        air = 100.0
        seen = []
        for i in range(40):
            clip = self.clip(broadcast_ms=int(air * 1000))
            start = rg.door(clip, air, air - 5, rng=rng)
            g = clip["gap_before"]
            self.assertTrue(g["rolled"])
            self.assertTrue(0.2 <= g["s"] <= 2.9)
            self.assertAlmostEqual(start, air + g["s"], places=6)
            seen.append(g["s"])
            air = start + 4.0
            rg.booked(clip, air)
        self.assertGreater(len(set(seen)), 8)

    def test_the_pages_own_floor_is_free_air(self):
        """Nothing booked: the cursor is the page's floor (now + lead), not
        the end of a message - no seam, no roll."""
        rg.save({"gap": 1.0, "range": 1.9, "roll": True})
        nxt = self.clip(broadcast_ms=107000)
        self.assertEqual(rg.door(nxt, 107.0, 107.0, rng=random.Random(2)), 107.0)
        self.assertNotIn("gap_before", nxt)

    def test_a_paged_round_books_its_end_from_the_doors_start(self):
        rg.save({"gap": 3.0, "roll": False})
        rg.booked(dict(self.clip(), tail_s=0.9), 100.0)
        rows = [{"id": "r"}]
        burst = self.clip(broadcast_ms=100000, stream={"rows": rows, "length": 30})
        start = rg.door(burst, 100.0, 95.0)
        self.assertAlmostEqual(rg.started(rows, 100.0), start)
        self.assertEqual(rg.started([{"id": "other"}], 100.0), 100.0)

    def test_a_recovered_clip_keeps_its_pause(self):
        nxt = self.clip(broadcast_ms=100000, gap_before={"s": 3.0})
        self.assertIsNone(rg.door(nxt, 100.0, 95.0))
        self.assertEqual(nxt["gap_before"], {"s": 3.0})


class StreamMixer(unittest.TestCase):
    def test_a_voice_knows_its_tail(self):
        try:
            import station_stream as ss
        except Exception as exc:  # noqa: BLE001 - numpy etc. live in the container
            self.skipTest("station_stream not importable here: %s" % exc)
        v = ss._Voice("k", 1.0, "/x.wav", 0.0, False, 0.9, 4.2)
        self.assertEqual((v.tail, v.seconds, v.played), (0.9, 4.2, 0.0))
        self.assertEqual(ss._Voice("k", 1.0, "/x.wav", 0.0).tail, 0.0)
        src = (ROOT / "station_stream.py").read_text(encoding="utf-8")
        self.assertIn("airing.played >= airing.seconds - airing.tail", src)


class ProducedRound(unittest.TestCase):
    def cue_map(self):
        rate = 24000
        cues, off = [], 120
        for i, (speech, pause) in enumerate([(48000, 2400), (24000, 3600), (36000, 0)]):
            cues.append({"occurrence_id": "o%d" % i, "kind": "line",
                         "start_sample": off, "speech_start_sample": off,
                         "speech_end_sample": off + speech, "cue_end_sample": off + speech + pause,
                         "pause_frames": pause})
            off += speech + pause
        return {"sample_rate": rate, "cues": cues, "body_frames": 48000 + 2400 + 24000 + 3600 + 36000,
                "frame_count": 120 + 114000 + 21600, "sequence": ["o0", "o1", "o2"],
                "mix": {"beats": [0.1, 0.15, 0.0]}}

    def test_retime_moves_every_later_cue_by_the_difference(self):
        cm = self.cue_map()
        body = cm["body_frames"]
        self.assertTrue(rg.retime_cue_map(cm, {"o0": 1.0, "o1": 2.5, "o2": 0.0}))
        c0, c1, c2 = cm["cues"]
        self.assertEqual(c0["pause_frames"], 24000)
        self.assertEqual(c0["cue_end_sample"], 120 + 48000 + 24000)
        self.assertEqual(c1["start_sample"], c0["cue_end_sample"], "the next line starts where the pause ends")
        self.assertEqual(c1["pause_frames"], 60000)
        self.assertEqual(c2["start_sample"], c1["cue_end_sample"])
        self.assertEqual(cm["body_frames"], body + (24000 - 2400) + (60000 - 3600))
        self.assertEqual(cm["mix"]["beats"], [1.0, 2.5, 0.0])
        self.assertAlmostEqual(c1["start_seconds"], c1["start_sample"] / 24000, places=6)

    def test_retime_for_burst_reads_the_rows_production_ids(self):
        cm = self.cue_map()
        meta = {"cue_map": cm}
        items = [{"production": {"occurrence_id": "o%d" % i}} for i in range(3)]
        self.assertTrue(rg.retime_for_burst(meta, [1.0, 1.0, 0.0], [0, 1, 2], [0, 1, 2], items))
        self.assertEqual([c["pause_frames"] for c in cm["cues"]], [24000, 24000, 0])


class Planner(unittest.TestCase):
    """app.py's segment budget, executed from the patched source."""

    @classmethod
    def setUpClass(cls):
        text = (ROOT / "app.py").read_text(encoding="utf-8")
        if "[reply-gap]" not in text:
            raise unittest.SkipTest("app.py is not patched here")
        cls.text = text
        m = re.search(r"\ndef segment_budget\(.*?(?=\n\n\ndef )", text, re.S)
        assert m, "segment_budget not found"
        cls.src = m.group(0)

    def budget(self, gap, per=6.5, seconds=600.0):
        ns = {"Any": object, "SEGMENT_TALK_SHARE": {}, "SEGMENT_TALK_SHARE_ELSE": 1.0,
              "mean_turn_seconds": lambda kind: per, "TURNS_PER_CYCLE": 1,
              "CONCAT_TAIL": 0.9, "CONCAT_KEEP": 0.06, "reply_gap_seam": lambda: gap}
        exec(compile("from typing import Any\n" + self.src, "segment_budget", "exec"), ns)
        return ns["segment_budget"]("banter", seconds=seconds)

    def test_the_segment_budgets_n_minus_one_pauses(self):
        for gap in (0.2, 1.0, 3.0, 10.0):
            got = self.budget(gap)
            n, speech = got["turns"], 6.5 - 0.84
            self.assertLessEqual(n * speech + (n - 1) * gap, 600.0 + 1e-6, gap)
            self.assertGreater((n + 1) * speech + n * gap, 600.0, gap)
            self.assertEqual(got["reply_gap"], round(gap, 2))
            self.assertIn("between replies", got["say"])
        self.assertLess(self.budget(10.0)["turns"], self.budget(1.0)["turns"],
                        "longer pauses leave room for fewer lines")

    def test_the_fit_checks_and_stock_price_ask_the_gap(self):
        for needle in (
                "duration = (seconds + max(0, len(lines) - 1) * reply_gap_seam()",
                "duration += (max(0, len(takes) - 1) * reply_gap_seam()",
                "+ reply_gap_seam() * max(0, len(batch) - 1)",
                "actual = max(0.0, actual + reply_gap_stock_extra(len(keys)))",
                "max(0, lines - 1) * reply_gap_seam()",
                "beats, _rg_notes = reply_gap_burst(beats, seg_ix, turn_ix, transcript,",
                "+ reply_gap_carry(_rg_notes, length, rows))",
                '"gap": (r.get("gap") if isinstance(r.get("gap"), dict)',
                "_reply_gap.install(app, globals())"):
            self.assertEqual(self.text.count(needle), 1, needle)

    def test_the_patch_reports_applied(self):
        got = subprocess.run([sys.executable, str(ROOT / "tools" / "reply_gap_patch.py"),
                              "--check", str(ROOT / "app.py")], capture_output=True, text=True)
        self.assertEqual(got.returncode, 2, got.stdout + got.stderr)

    def test_the_door_patch_reports_applied(self):
        got = subprocess.run([sys.executable, str(ROOT / "tools" / "reply_gap_door_patch.py"),
                              "--check", str(ROOT / "app.py"), str(ROOT / "station_stream.py")],
                             capture_output=True, text=True)
        self.assertEqual(got.returncode, 2, got.stdout + got.stderr)

    def test_the_door_is_in_page_feed_append(self):
        m = re.search(r"\ndef page_feed_append\(clip.*?(?=\n\n\n)", self.text, re.S)
        self.assertTrue(m)
        body = m.group(0)
        self.assertIn("_rg_start = reply_gap_door(clip, _rg_air, time.time() + lead)", body)
        self.assertIn("reply_gap_booked(clip,", body)
        self.assertIn("cursor = max(cursor - reply_gap_overlap(clip), start) + duration", self.text)
        for needle in ("pineReplyGapFloor(clip)) - Date.now();", "pineReplyGapEarly(clip, player, djVoiceQueue)",
                       "pineReplyGapEarly(clip, voice, voiceQueue)", "pineReplyGapWordsEnded(clip, null, djVoiceQueue)"):
            self.assertEqual(self.text.count(needle), 1 if "Floor" not in needle else 2, needle)


if __name__ == "__main__":
    unittest.main()
