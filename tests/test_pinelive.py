"""PineLive core: the pieces that can be proven without a device.

Run one module at a time, niced, in the container tree:
  PYTHONPATH=/tmp/pinelive-fin:/tmp/pinelive-fin/tests:/tmp/pinelive-fin/tools \
      nice -n 19 timeout 600 python -m unittest tests.test_pinelive -v
"""
import importlib.util
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

import pinelive

HERE = Path(__file__).resolve().parent.parent


def _load_host():
    spec = importlib.util.spec_from_file_location(
        "pinelive_host", HERE / "tools" / "pinelive_host.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("pinelive_host", mod)
    spec.loader.exec_module(mod)
    return mod


class Settings(unittest.TestCase):
    def test_defaults_and_clamps(self):
        got, refused = pinelive.clean_settings({"cut_seconds": 5, "duck_db": -99,
                                               "live_gain_db": 100, "nonsense": 1})
        self.assertEqual(got["cut_seconds"], 30)          # clamped up
        self.assertEqual(got["duck_db"], -30.0)           # clamped to range
        self.assertEqual(got["live_gain_db"], 12.0)
        self.assertIn("nonsense (unknown)", refused)

    def test_enums_and_dest(self):
        got, refused = pinelive.clean_settings({"format": "ogg", "picture_mode": "ads",
                                               "channel_mode": "left",
                                               "dest": "\\\\10.89.1.125\\QuickSwap\\X",
                                               "channel_pair": [3, 4]})
        self.assertIn("format", refused)
        self.assertEqual(got["picture_mode"], "ads")
        self.assertEqual(got["channel_mode"], "left")
        self.assertEqual(got["channel_pair"], [3, 4])
        _, refused2 = pinelive.clean_settings({"dest": "data/relative"})
        self.assertIn("dest", refused2)


class CutsAndWav(unittest.TestCase):
    def test_cut_names_pair_and_sort(self):
        a1, m1 = pinelive.cut_names(1790000000.0, 1)
        a2, m2 = pinelive.cut_names(1790000210.0, 2)
        self.assertTrue(a1.endswith("_c001_input.wav"))
        self.assertTrue(m1.endswith("_c001_mix.wav"))
        self.assertEqual(a1[:-len("_input.wav")], m1[:-len("_mix.wav")])
        self.assertLess(a1, a2)                            # time order sorts

    def test_wav_header(self):
        h = pinelive.wav_header(1000)
        self.assertEqual(h[:4], b"RIFF")
        self.assertEqual(struct.unpack("<I", h[4:8])[0], 1036)
        self.assertEqual(struct.unpack("<H", h[22:24])[0], 2)          # stereo
        self.assertEqual(struct.unpack("<I", h[24:28])[0], 44100)

    def test_recorder_splits_on_silence(self):
        """[pltrack3] [plsplit]/[plmp3]: a track closes after SPLIT_SILENCE_S of
        quiet input, nothing records between tracks, the next opens on sound,
        and each pair is decanted (MP3 unless flac)."""
        import threading

        class Owner:
            settings = {"silence_db": -60.0}

            def __init__(self):
                self.closed = []
                self.splits = 0

            def event_id(self):
                return "ev-test"

            def courier_hand(self, paths, folder):
                return ["c1", "c2"]

            def cut_closed(self, row):
                self.closed.append(row)

            def track_split(self):
                self.splits += 1

            def error(self, code, say):
                raise AssertionError("%s: %s" % (code, say))

        owner = Owner()
        rec = pinelive.Recorder(owner)
        split = int(pinelive.SPLIT_SILENCE_S * 1000 / pinelive.FRAME_MS)
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "ev"
            rec.begin(folder, "ev", 210.0, "wav", 1)
            frame = b"\x01\x02" * (pinelive.FRAME_BYTES // 2)
            loud = b"\x03\x04" * (pinelive.FRAME_BYTES // 2)      # about -30 dBFS
            quiet = b"\x00\x00" * (pinelive.FRAME_BYTES // 2)
            t0 = 1790000000.0
            seq = [loud] * 20 + [quiet] * (split + 5) + [loud] * 15
            for i, live in enumerate(seq):
                rec.tap(frame, live, {"t": t0 + i * 0.1})
            rec.end()                                      # closes the second track
            for th in [x for x in threading.enumerate() if x.name == "pinelive-decant"]:
                th.join(120)
            rows = sorted(owner.closed, key=lambda r: r["index"])
            self.assertEqual(owner.splits, 1)
            self.assertEqual([r["index"] for r in rows], [1, 2])
            tail = int(pinelive.SPLIT_TAIL_S * 1000 / pinelive.FRAME_MS)       # [plquiet] ring-out kept
            pre = int(pinelive.SPLIT_PREROLL_S * 1000 / pinelive.FRAME_MS)     # [plquiet] lead-in
            self.assertAlmostEqual(rows[0]["seconds"], (20 + tail) * pinelive.FRAME_MS / 1000.0)
            self.assertAlmostEqual(rows[1]["seconds"], (pre + 15) * pinelive.FRAME_MS / 1000.0)
            for row in rows:
                self.assertEqual(row["courier"], ["c1", "c2"])
                for key in ("input", "mix"):
                    p = folder / row[key]
                    self.assertTrue(p.is_file(), p)
                    self.assertIn(p.suffix, (".mp3", ".wav"))   # .wav only without ffmpeg


class LiveSourceFrames(unittest.TestCase):
    def test_read_frame_pads_when_starved(self):
        src = pinelive.LiveSource(connect=False)
        got, ok = src.read_frame()
        self.assertFalse(ok)
        self.assertEqual(len(got), pinelive.FRAME_BYTES)
        self.assertEqual(src.short_frames, 1)

    def test_read_frame_roundtrip(self):
        src = pinelive.LiveSource(connect=False)
        # two frames' worth: the cushion sits in the trim deadband, so the
        # first read hands the first frame back byte for byte
        payload = (bytes(range(256)) * (2 * pinelive.FRAME_BYTES // 256 + 2))[:2 * pinelive.FRAME_BYTES]
        src._take(payload)
        got, ok = src.read_frame()
        self.assertTrue(ok)
        self.assertEqual(got, payload[:pinelive.FRAME_BYTES])

    def test_resample_frame_length(self):
        if pinelive.np is None:
            self.skipTest("no numpy")
        raw = b"\x00\x01" * 2 * (pinelive.FRAME_SAMPLES + 1)
        out = pinelive.resample_frame(raw, pinelive.FRAME_SAMPLES + 1)
        self.assertEqual(len(out), pinelive.FRAME_BYTES)


class StateAndDoors(unittest.TestCase):
    def _pl(self, td):
        pl = pinelive.PineLive(data_dir=Path(td))
        return pl

    def test_event_state_shape_and_live_id(self):
        with tempfile.TemporaryDirectory() as td:
            pl = self._pl(td)
            st = pl.event_state()
            self.assertEqual(st["phase"], "idle")
            self.assertFalse(st["armed"])
            self.assertIsNone(st["event"])
            pl.event = {"id": "mxlive-x", "started_at": time.time(), "fallbacks": 0}
            pl.phase = "live"
            st2 = pl.event_state()
            self.assertTrue(st2["live"] and st2["armed"])
            self.assertEqual(st2["event"]["name"], "MX Live")
            lid = pl.live_id()
            self.assertEqual(len(lid), 16)
            self.assertTrue(pl.is_live_id(lid))
            self.assertFalse(pl.is_live_id("0" * 16))
            track = pl.live_track()
            self.assertTrue(track["live"] and track["pinelive"])
            self.assertEqual(track["title"], "MX Live")

    def test_public_video_blocked_only_while_armed(self):
        with tempfile.TemporaryDirectory() as td:
            pl = self._pl(td)
            self.assertFalse(pl.public_video_blocked())    # idle: nothing to block
            pl.event = {"id": "e"}
            pl.phase = "live"
            self.assertTrue(pl.public_video_blocked())     # default: video off
            pl.settings["tailscale_video"] = True
            self.assertFalse(pl.public_video_blocked())

    def test_album_choice_in_state_and_control(self):
        """[pltoggle] the album switch is settings.record: state shows it,
        a rehearsal never records, and the host's master follows it."""
        import json
        with tempfile.TemporaryDirectory() as td:
            pl = self._pl(td)
            self.assertTrue(pl.state()["recording"]["album"])      # default on
            pl.event = {"id": "e", "folder": "f"}
            pl.phase = "live"
            pl.write_control()
            self.assertTrue(json.loads(pl.control_path.read_text())["master"])
            self.assertTrue(pl.state()["recording"]["on"])
            pl.settings["record"] = False
            pl.write_control()
            self.assertFalse(json.loads(pl.control_path.read_text())["master"])
            st = pl.state()
            self.assertFalse(st["recording"]["on"])
            self.assertFalse(st["recording"]["album"])
            pl.settings["record"] = True
            pl.event["rehearse"] = True
            self.assertFalse(pl.state()["recording"]["on"])         # a test is never recorded

    def test_troubleshoot_first_fail_walks_the_chain(self):
        with tempfile.TemporaryDirectory() as td:
            pl = self._pl(td)
            # no host_state.json at all: the host check fails first
            got = pl.troubleshoot()
            self.assertEqual(got["first_fail"], "host")
            self.assertEqual(got["checks"][0]["result"], "fail")
            # a fresh host with a ready device but no signal
            pl._host_memo = (time.time() + 999, {
                "at": time.time(),
                "devices": {"usb": [{"id": "hw:CARD=EP136,DEV=0", "card": 2, "card_id": "EP136",
                                     "usb_id": "2367:9420", "usb_name": "teenage engineering EP-136",
                                     "capture": True, "class_compliant": True, "status": "ready",
                                     "channels": 8, "formats": ["S32_LE"], "rates": [48000]}]},
                "capture": {"state": "running", "kind": "usb", "device": "hw:CARD=EP136,DEV=0"},
                "level": {"last_frame_ago": 0.1, "signal_ago": 999.0, "level_db": -80.0,
                          "peak_db": -70.0},
            })
            got2 = pl.troubleshoot()
            by_id = {c["id"]: c for c in got2["checks"]}
            for cid in ("host", "usb", "alsa", "class", "free", "capture"):
                self.assertEqual(by_id[cid]["result"], "pass", cid)
            self.assertEqual(got2["first_fail"], "signal")

    def test_clock_extra_blanks_the_public_picture(self):
        with tempfile.TemporaryDirectory() as td:
            pl = self._pl(td)
            pl.event = {"id": "e", "folder": "f"}
            pl.phase = "live"
            home = pl.clock_extra({"pinelive": True}, away=False)
            self.assertTrue(home["live"])
            self.assertEqual(home["pinelive"]["phase"], "live")
            self.assertNotIn("art", home)                  # the house keeps its art
            away = pl.clock_extra({"pinelive": True}, away=True)
            self.assertEqual(away["pinelive"]["picture"]["kind"], "none")
            self.assertEqual(away["pinelive"]["picture"]["art"], "")
            self.assertEqual(away["art"], "")


class HostPieces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.host = _load_host()

    def test_pair_filter(self):
        self.assertEqual(self.host.pair_filter(1, [1, 2]), "pan=stereo|c0=c0|c1=c0")
        self.assertEqual(self.host.pair_filter(8, [3, 4]), "pan=stereo|c0=c2|c1=c3")
        self.assertEqual(self.host.pair_filter(2, [7, 9]), "pan=stereo|c0=c1|c1=c1")

    def test_ingest_params(self):
        fmt, rate, ch, why = self.host.ingest_params({"format": "s16le", "rate": 48000,
                                                      "channels": 2})
        self.assertEqual((fmt, rate, ch, why), ("s16le", 48000, 2, ""))
        self.assertTrue(self.host.ingest_params({"format": "mp3"})[3])
        self.assertTrue(self.host.ingest_params({"rate": 7000})[3])
        self.assertTrue(self.host.ingest_params({"channels": 9})[3])

    def test_normaliser_cmd_normalises(self):
        cmd = self.host.normaliser_cmd("ffmpeg", "s32le", 48000, 8, [1, 2])
        self.assertIn("s32le", cmd)
        self.assertIn("aresample=44100", " ".join(cmd))
        self.assertEqual(cmd[-1], "pipe:1")

    def test_parse_lsusb(self):
        names = self.host.parse_lsusb(
            "Bus 003 Device 009: ID 2367:9420 Teenage Engineering EP-133\n"
            "Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub\n")
        self.assertEqual(names.get("2367:9420"), "Teenage Engineering EP-133")

    def test_scan_devices_survives_an_empty_tree(self):
        with tempfile.TemporaryDirectory() as td:
            got = self.host.scan_devices(root=Path(td), lsusb_text="")
            self.assertEqual(got["usb"], [])
            self.assertEqual(got["alsa_other"], [])


class MixerDuck(unittest.TestCase):
    """The station mixer's live bed (tools/pinelive_stream_patch.py applied
    to station_stream.py): stereo kept, the operator's trim, and the duck
    ramping per frame at its own attack/release."""

    @classmethod
    def setUpClass(cls):
        try:
            import station_stream
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest("no station_stream here: %s" % exc)
        if not hasattr(station_stream, "_live_bed"):
            raise unittest.SkipTest("station_stream has no live bed (patch not applied)")
        cls.ss = station_stream

    class Src:
        gain = 1.0
        duck_gain = 10 ** (-10.8 / 20.0)
        duck_attack_ms = 100.0
        duck_release_ms = 100.0
        duck_now = 0.0

    def test_duck_ramps_in_and_out(self):
        ss = self.ss
        raw = bytes((0, 64)) * 2 * ss.FRAME_SAMPLES      # 0.5 full scale
        src = self.Src()
        level = 0.0
        bed, level = ss._live_bed(raw, src, True, level)      # a DJ line starts
        self.assertEqual(level, 1.0)                          # 100 ms frame = the whole attack
        self.assertAlmostEqual(src.duck_now, 1.0)
        # fully ducked: the frame's END sits at duck_gain x the input
        end = float(bed[-2]) / 16384.0
        self.assertAlmostEqual(end, src.duck_gain, places=2)
        bed2, level = ss._live_bed(raw, src, False, level)    # the line ends
        self.assertEqual(level, 0.0)
        end2 = float(bed2[-2]) / 16384.0
        self.assertAlmostEqual(end2, 1.0, places=2)

    def test_stereo_is_kept_and_gain_applied(self):
        ss = self.ss
        frame = bytearray()
        for _ in range(ss.FRAME_SAMPLES):
            frame += struct.pack("<hh", 8192, -4096)          # L != R
        src = self.Src()
        src.gain = 2.0
        bed, _ = ss._live_bed(bytes(frame), src, False, 0.0)
        self.assertAlmostEqual(float(bed[0]) / 8192.0, 2.0, places=3)
        self.assertAlmostEqual(float(bed[1]) / -4096.0, 2.0, places=3)


if __name__ == "__main__":
    unittest.main()
