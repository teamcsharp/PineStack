"""[plquiet] The two silence sliders, proven on simulated timelines.

- hand-back (settings.silence_seconds, default 45 s): a set that goes quiet
  longer than this gives the air back to the DJ; sound before then keeps it.
  The no-frames DROPOUT path stays its own, immediate, threshold.
- new album track (settings.split_seconds, default 15 s): quiet longer than
  this closes the track (keeping a 2 s ring-out, the rest of the silence cut)
  and the next sound opens the next numbered track with a 0.5 s lead-in.
- both are read live: a changed setting needs no restart.

  docker exec -w /tmp/wX -e PYTHONPATH=tests:. -e SPARK_AGENT_DATA_DIR=/tmp/wX_data \
      spark-agent nice -n 10 python3 -m unittest tests.test_pinelive_quiet -v
"""
import json
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path

import pinelive

FB = pinelive.FRAME_BYTES
FRAME = b"\x01\x02" * (FB // 2)
LOUD = b"\x03\x04" * (FB // 2)          # about -30 dBFS
QUIET = b"\x00\x00" * (FB // 2)
PER_S = int(1000 / pinelive.FRAME_MS)   # frames a second
TAIL = int(pinelive.SPLIT_TAIL_S * PER_S)
PRE = int(pinelive.SPLIT_PREROLL_S * PER_S)


def _join_decants():
    for th in [x for x in threading.enumerate() if x.name == "pinelive-decant"]:
        th.join(120)


class _Owner:
    """The recorder's owner, reduced to what the recorder calls."""

    def __init__(self, **settings):
        self.settings = dict({"silence_db": -60.0}, **settings)
        self.closed = []
        self.splits = 0

    def event_id(self):
        return "ev-quiet"

    def courier_hand(self, paths, folder):
        return []

    def cut_closed(self, row):
        self.closed.append(row)

    def track_split(self):
        self.splits += 1

    def error(self, code, say):
        raise AssertionError("%s: %s" % (code, say))


class _KeepWav(unittest.TestCase):
    """Decant keeps the WAV (no MP3), so the file itself can be measured."""

    def setUp(self):
        self._mp3 = pinelive.to_mp3
        pinelive.to_mp3 = lambda p: None
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)

    def tearDown(self):
        pinelive.to_mp3 = self._mp3
        self._td.cleanup()


class Settings(unittest.TestCase):
    def test_defaults_ranges_and_the_clamp(self):
        got, refused = pinelive.clean_settings({})
        self.assertEqual((got["silence_seconds"], got["split_seconds"]), (45.0, 15.0))
        got, _ = pinelive.clean_settings({"silence_seconds": 3, "split_seconds": 1})
        self.assertEqual((got["silence_seconds"], got["split_seconds"]), (10.0, 5.0))
        got, _ = pinelive.clean_settings({"silence_seconds": 999, "split_seconds": 999})
        self.assertEqual((got["silence_seconds"], got["split_seconds"]), (180.0, 120.0))
        # the split can never outlast the hand-back: it follows it down
        got, refused = pinelive.clean_settings({"split_seconds": 60})       # hand-back 45
        self.assertEqual(got["split_seconds"], 44.0)
        self.assertEqual(refused, [])
        got, _ = pinelive.clean_settings({"silence_seconds": 12}, {"split_seconds": 15.0})
        self.assertEqual((got["silence_seconds"], got["split_seconds"]), (12.0, 11.0))


class AlbumTracks(_KeepWav):
    """split_seconds = 15: gaps of 10 s stay inside a track, 20 s and 50 s split."""

    def run_timeline(self, owner, segments):
        rec = pinelive.Recorder(owner)
        folder = self.dir / "ev"
        rec.begin(folder, "ev", 3600.0, "wav", 1)
        t = 1790000000.0
        for seconds, live in segments:
            for _ in range(int(round(seconds * PER_S))):
                t += 0.1
                rec.tap(FRAME, live, {"t": t})
        rec.end()
        _join_decants()
        return folder, sorted(owner.closed, key=lambda r: r["index"])

    def assert_wav_seconds(self, path, seconds):
        raw = path.read_bytes()
        data = struct.unpack("<I", raw[40:44])[0]
        self.assertEqual(data, len(raw) - 44)
        self.assertAlmostEqual(data / float(pinelive.RATE * 4), seconds, places=2)

    def test_10s_gap_stays_in_the_same_track(self):
        owner = _Owner()
        folder, rows = self.run_timeline(owner, [(3, LOUD), (10, QUIET), (3, LOUD)])
        self.assertEqual(owner.splits, 0)
        self.assertEqual([r["index"] for r in rows], [1])
        self.assertAlmostEqual(rows[0]["seconds"], 16.0)
        self.assert_wav_seconds(folder / rows[0]["input"], 16.0)

    def test_20s_gap_makes_a_new_track_trimmed_and_led_in(self):
        owner = _Owner()
        folder, rows = self.run_timeline(owner, [(3, LOUD), (20, QUIET), (4, LOUD)])
        self.assertEqual(owner.splits, 1)
        self.assertEqual([r["index"] for r in rows], [1, 2])
        # track 1: the music + a 2 s ring-out, not the 15 s of silence
        self.assertAlmostEqual(rows[0]["seconds"], 3.0 + pinelive.SPLIT_TAIL_S)
        for key in ("input", "mix"):
            self.assert_wav_seconds(folder / rows[0][key], 3.0 + pinelive.SPLIT_TAIL_S)
        # track 2: a 0.5 s lead-in, then the music
        self.assertAlmostEqual(rows[1]["seconds"], pinelive.SPLIT_PREROLL_S + 4.0)
        self.assert_wav_seconds(folder / rows[1]["mix"], pinelive.SPLIT_PREROLL_S + 4.0)
        self.assertIn("_c001_", rows[0]["input"])
        self.assertIn("_c002_", rows[1]["input"])
        # the ring-out is the silence itself, and the file ends there
        raw = (folder / rows[0]["input"]).read_bytes()[44:]
        self.assertEqual(raw[-TAIL * FB:], QUIET * TAIL)
        self.assertEqual(raw[-(TAIL + 1) * FB:-TAIL * FB], LOUD)

    def test_50s_gap_is_one_split_too(self):
        owner = _Owner()
        folder, rows = self.run_timeline(owner, [(3, LOUD), (50, QUIET), (2, LOUD)])
        self.assertEqual(owner.splits, 1)
        self.assertEqual([round(r["seconds"], 2) for r in rows],
                         [3.0 + pinelive.SPLIT_TAIL_S, pinelive.SPLIT_PREROLL_S + 2.0])

    def test_the_slider_is_read_live(self):
        owner = _Owner()
        owner.settings["split_seconds"] = 8.0             # moved before the gap: 10 s now splits
        folder, rows = self.run_timeline(owner, [(3, LOUD), (10, QUIET), (3, LOUD)])
        self.assertEqual(owner.splits, 1)
        self.assertEqual(len(rows), 2)


class _Live:
    """LiveSource's clock, driven by the test: rx_at (frames arrive) and
    signal_at/signal_since (above the floor), exactly as read_frame sets them."""
    duck_now = 0.0

    def __init__(self, *a, **kw):
        self.rx_at = 0.0
        self.signal_at = 0.0
        self.signal_since = 0.0

    def hear(self, now, loud, arrives=True):
        if arrives:
            self.rx_at = now
        if arrives and loud:
            if not self.signal_since or now - self.signal_at > 0.5:
                self.signal_since = now
            self.signal_at = now

    def signal_run(self, now=None):
        if not self.signal_since or now - self.signal_at > 0.5:
            return 0.0
        return now - self.signal_since

    def close(self):
        pass

    def summary(self):
        return {}


class HandBack(_KeepWav):
    """silence_seconds = 45 on a real PineLive: tick() on a simulated clock,
    the recorder fed the same timeline."""

    def setUp(self):
        super().setUp()
        self._saved = (pinelive.LiveSource, pinelive.PineLive._supervise, pinelive._G)
        pinelive.LiveSource = _Live
        pinelive.PineLive._supervise = lambda self: None
        pinelive._G = {}

    def tearDown(self):
        pinelive.LiveSource, pinelive.PineLive._supervise, pinelive._G = self._saved
        super().tearDown()

    def armed(self, **settings):
        pl = pinelive.PineLive(data_dir=self.dir)
        pl.boot()
        if settings:
            pl.set_settings(settings)
        stamp = "20260929-120000"
        with pl.lock:
            pl.event = {"id": "mxlive-" + stamp, "name": pinelive.EVENT_NAME,
                        "started_at": time.time(), "folder": "%s_%s" % (stamp, pinelive.EVENT_SLUG),
                        "armed": True, "fallbacks": 0, "rehearse": False, "album": True}
            pl.source_kind, pl.device, pl.token = "usb", "hw:TEST", "t"
            pl._arm_runtime(resume=False)
        return pl

    def play(self, pl, segments, t0=None):
        """(seconds, 'loud'|'quiet'|'gone') segments; returns the phase at
        the end of each segment."""
        t = t0 or getattr(pl, "_sim_t", 0) or time.time()     # one clock across calls
        out = []
        for seconds, what in segments:
            for _ in range(int(round(seconds * PER_S))):
                t += 0.1
                pl.live.hear(t, what == "loud", arrives=what != "gone")
                if what != "gone":
                    pl.recorder.tap(FRAME, LOUD if what == "loud" else QUIET, {"t": t})
                pl.tick(now=t)
            out.append(pl.phase)
        pl._sim_t = t
        return out

    def test_10s_and_20s_gaps_stay_on_air_50s_hands_back(self):
        pl = self.armed()
        got = self.play(pl, [(3, "loud"), (10, "quiet"), (3, "loud"), (20, "quiet"),
                             (3, "loud"), (50, "quiet"), (3, "loud")])
        # 10 s: the set keeps the air; 20 s: it keeps the air (a new track);
        # 50 s: the station took it back at 45 s; the set's sound takes it again
        self.assertEqual(got, ["live", "live", "live", "live", "live", "fallback", "live"])
        self.assertEqual(pl.event["fallbacks"], 1)
        codes = [e["code"] for e in pl.errors]
        self.assertIn("silence", codes)
        self.assertNotIn("dropout", codes)
        pl.recorder.end()
        _join_decants()
        rows = sorted(pl.recorder.cuts, key=lambda r: r["index"])
        # track 1 = 3 s + 10 s gap + 3 s; the 20 s and 50 s gaps each open a new one
        self.assertEqual(len(rows), 3, rows)
        self.assertAlmostEqual(rows[0]["seconds"], 16.0 + pinelive.SPLIT_TAIL_S)
        self.assertEqual(pl.event.get("track"), 3)

    def test_sound_just_before_the_hand_back_keeps_the_set(self):
        pl = self.armed()
        got = self.play(pl, [(3, "loud"), (44, "quiet"), (1, "loud"), (44, "quiet")])
        self.assertEqual(got, ["live"] * 4)

    def test_the_hand_back_slider_is_read_live(self):
        pl = self.armed()
        self.play(pl, [(3, "loud"), (30, "quiet")])
        pl.set_settings({"silence_seconds": 20})          # mid-silence: 30 s > 20 s
        self.assertEqual(self.play(pl, [(0.3, "quiet")]), ["fallback"])
        pl2 = self.armed(silence_seconds=90)
        self.assertEqual(self.play(pl2, [(3, "loud"), (60, "quiet")]), ["live", "live"])

    def test_a_dropout_still_hands_back_at_once(self):
        pl = self.armed()
        got = self.play(pl, [(3, "loud"), (2.5, "gone"), (1, "gone")])
        self.assertEqual(got, ["live", "live", "fallback"])      # dropout_seconds = 3
        self.assertIn("dropout", [e["code"] for e in pl.errors])

    def test_an_old_settings_file_takes_the_new_default_once(self):
        if True:
            td = str(self.dir / "boot")
            Path(td).mkdir()
            p = Path(td) / "settings.json"
            p.write_text(json.dumps({"silence_seconds": 30.0, "cut_seconds": 600}))
            pl = pinelive.PineLive(data_dir=Path(td))
            pl.boot()
            self.assertEqual(pl.settings["silence_seconds"], 45.0)
            self.assertEqual(pl.settings["split_seconds"], 15.0)
            self.assertEqual(pl.settings["cut_seconds"], 600)
            on_disk = json.loads(p.read_text())
            self.assertEqual((on_disk["silence_seconds"], on_disk["split_seconds"]), (45.0, 15.0))
            # the operator's later choice is kept across a restart
            p.write_text(json.dumps(dict(on_disk, silence_seconds=90.0, split_seconds=20.0)))
            pl2 = pinelive.PineLive(data_dir=Path(td))
            pl2.boot()
            self.assertEqual((pl2.settings["silence_seconds"], pl2.settings["split_seconds"]), (90.0, 20.0))

    def test_state_carries_the_readout(self):
        pl = self.armed(split_seconds=12)
        self.play(pl, [(3, "loud")], t0=time.time() - 20)
        pl.live.signal_at = time.time() - 7.0
        q = pl.state()["quiet"]
        self.assertEqual((q["handoff_s"], q["split_s"]), (45.0, 12.0))
        self.assertTrue(6.5 <= q["silent_s"] <= 8.0, q)
        self.assertTrue(q["album"])


if __name__ == "__main__":
    unittest.main()
