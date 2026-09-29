"""[pltoggle] The PineLive header switches, proven without a device.

- Album recording OFF: the set arms and airs, the Recorder writes nothing
  (no folder, no tracks, no decant) and the host's safety master is off.
- Mid-set flips: ON opens a track with the next sound, OFF closes it cleanly
  and nothing more is written; ON again continues at the next index.
- Remembered: the choice lives in settings.json; a restarted station arms the
  next set with the last-used value, on or off.
- PineCam to live OFF blocks only the public picture: the Pine Cam frame is
  still read, the Picture keeps publishing it and the house clock shows it.

  docker exec -w /tmp/wX -e PYTHONPATH=tests:. spark-agent nice -n 10 \
      python3 -m unittest tests.test_pinelive_toggles -v
"""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

import pinelive


class _Src:
    """LiveSource stand-in: never connects to the host's door."""
    duck_now = 0.0

    def __init__(self, *a, **kw):
        pass

    def close(self):
        pass

    def summary(self):
        return {}


def _join_decants():
    for th in [x for x in threading.enumerate() if x.name == "pinelive-decant"]:
        th.join(120)


def _files(root: Path):
    return sorted(p.name for p in root.rglob("*") if p.is_file()) if root.exists() else []


class _Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)
        self._saved = (pinelive.LiveSource, pinelive.PineLive._supervise, pinelive._G)
        pinelive.LiveSource = _Src
        pinelive.PineLive._supervise = lambda self: None      # no tick: nothing takes the air
        pinelive._G = {}

    def tearDown(self):
        pinelive.LiveSource, pinelive.PineLive._supervise, pinelive._G = self._saved
        self._td.cleanup()

    def booted(self):
        pl = pinelive.PineLive(data_dir=self.dir)
        pl.boot()
        return pl

    def arm(self, pl, stamp="20260929-120000"):
        """What start() does once its checks pass (no radio, no host here)."""
        with pl.lock:
            pl.event = {"id": "mxlive-" + stamp, "name": pinelive.EVENT_NAME,
                        "started_at": time.time(), "folder": "%s_%s" % (stamp, pinelive.EVENT_SLUG),
                        "armed": True, "fallbacks": 0, "rehearse": False,
                        "album": bool(pl.settings.get("record", True))}
            pl.source_kind, pl.device, pl.token = "usb", "hw:TEST", "t"
            pl._arm_runtime(resume=False)
        return pl.cuts_root / pl.event["folder"]

    @staticmethod
    def feed(pl, n, loud=True, t0=1790000000.0):
        frame = b"\x01\x02" * (pinelive.FRAME_BYTES // 2)
        live = (b"\x03\x04" if loud else b"\x00\x00") * (pinelive.FRAME_BYTES // 2)
        for i in range(n):
            pl.recorder.tap(frame, live, {"t": t0 + i * 0.1})

    @staticmethod
    def drain(pl):
        """Every queued frame handled: a harmless item goes last, then the queue empties."""
        pl.recorder.q.put(("cut_seconds", pl.settings["cut_seconds"]))
        deadline = time.time() + 10
        while not pl.recorder.q.empty() and time.time() < deadline:
            time.sleep(0.02)
        time.sleep(0.2)

    def control(self, pl):
        return json.loads(pl.control_path.read_text())


class AlbumOff(_Base):
    def test_album_off_writes_nothing_and_the_set_still_arms(self):
        pl = self.booted()
        pl.set_settings({"record": False})
        folder = self.arm(pl)
        self.assertTrue(pl.armed())
        self.assertFalse(pl.recorder.active)                  # the recorder never began
        self.assertFalse(self.control(pl)["master"])          # no safety master on the host
        self.assertTrue(self.control(pl)["armed"])            # the host still captures: the set airs
        self.feed(pl, 40)
        self.drain(pl)
        st = pl.state()
        self.assertFalse(st["recording"]["on"])
        self.assertFalse(st["recording"]["album"])
        pl.stop("test")
        _join_decants()
        self.assertFalse(folder.exists(), _files(pl.cuts_root))
        self.assertEqual(_files(pl.cuts_root), [])
        self.assertEqual(pl.recorder.cuts, [])

    def test_mid_set_flips_start_and_suspend_cleanly(self):
        pl = self.booted()
        pl.set_settings({"record": False})
        folder = self.arm(pl)
        self.feed(pl, 20)
        self.drain(pl)
        self.assertEqual(_files(pl.cuts_root), [])            # off: nothing yet

        pl.set_settings({"record": True})                    # ON mid-set
        self.assertTrue(pl.recorder.active)
        self.assertTrue(self.control(pl)["master"])
        self.feed(pl, 25)
        self.drain(pl)
        self.assertEqual(pl.recorder.index, 1)                # a track opened on the sound

        pl.set_settings({"record": False})                   # OFF mid-set: closed cleanly
        _join_decants()
        self.assertFalse(self.control(pl)["master"])
        self.assertEqual(len(pl.recorder.cuts), 1)
        row = pl.recorder.cuts[0]
        self.assertAlmostEqual(row["seconds"], 25 * pinelive.FRAME_MS / 1000.0)
        self.assertFalse(row["final"])
        before = _files(folder)
        self.assertEqual(len(before), 2)                      # one pair: input + mix

        self.feed(pl, 30)                                     # off: frames are not written
        self.drain(pl)
        self.assertEqual(_files(folder), before)
        self.assertEqual(pl.recorder.index, 1)

        pl.set_settings({"record": True})                    # ON again: the next index
        self.feed(pl, 15)
        self.drain(pl)
        pl.stop("test")
        _join_decants()
        self.assertEqual(sorted(r["index"] for r in pl.recorder.cuts), [1, 2])
        self.assertEqual(len(_files(folder)), 4)

    def test_off_on_a_sub_second_track_leaves_no_stub(self):
        pl = self.booted()
        folder = self.arm(pl)                                 # default: album on
        self.feed(pl, 3)                                      # 0.3 s of sound
        self.drain(pl)
        pl.set_settings({"record": False})
        _join_decants()
        self.assertEqual(_files(folder), [])
        self.assertEqual(pl.recorder.cuts, [])
        pl.stop("test")


class Remembered(_Base):
    def test_the_next_set_starts_with_the_last_used_choice(self):
        pl = self.booted()
        self.assertTrue(pl.settings["record"])                # default on
        self.arm(pl)
        pl.set_settings({"record": False})                   # used OFF during the set
        pl.stop("test")
        on_disk = json.loads(pl.settings_path.read_text())
        self.assertFalse(on_disk["record"])

        pl2 = self.booted()                                   # the station restarted
        self.assertFalse(pl2.settings["record"])
        self.arm(pl2, "20260929-130000")
        self.assertFalse(pl2.recorder.active)                 # stays off
        self.assertFalse(pl2.event["album"])
        pl2.set_settings({"record": True})                   # used ON
        pl2.stop("test")
        _join_decants()

        pl3 = self.booted()
        self.assertTrue(pl3.settings["record"])
        self.arm(pl3, "20260929-140000")
        self.assertTrue(pl3.recorder.active)                  # restored on
        self.assertTrue(self.control(pl3)["master"])
        pl3.stop("test")
        _join_decants()


class CamToLive(_Base):
    def _frame(self):
        path = self.dir / "frame.jpg"
        path.write_bytes(b"\xff\xd8" + os.urandom(4000) + b"\xff\xd9")
        pinelive._G["PINELINK_FRAME"] = path
        return path

    def test_off_blocks_the_public_picture_only(self):
        path = self._frame()
        pl = self.booted()
        self.arm(pl)
        pl.phase = "live"
        pl.set_settings({"tailscale_video": False})
        # the camera is still read and the Picture keeps publishing it
        deadline = time.time() + 5
        while pl.picture.kind != "cam" and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(pl.picture.kind, "cam")
        self.assertEqual(pl.picture.jpeg, path.read_bytes())
        seq = pl.picture.seq
        time.sleep(0.2)
        path.write_bytes(b"\xff\xd8" + os.urandom(4000) + b"\xff\xd9")   # the next frame
        os.utime(path, (time.time() + 1, time.time() + 1))
        deadline = time.time() + 5
        while pl.picture.seq == seq and time.time() < deadline:
            time.sleep(0.05)
        self.assertGreater(pl.picture.seq, seq)                # still capturing
        # the house sees it; the public side does not
        home = pl.clock_extra({"pinelive": True}, away=False)
        self.assertEqual(home["pinelive"]["picture"]["kind"], "cam")
        away = pl.clock_extra({"pinelive": True}, away=True)
        self.assertEqual(away["pinelive"]["picture"]["kind"], "none")
        self.assertTrue(pl.public_video_blocked())
        # and the switch is the same road both ways: on opens the public side
        pl.set_settings({"tailscale_video": True})
        self.assertFalse(pl.public_video_blocked())
        self.assertEqual(pl.clock_extra({"pinelive": True}, away=True)
                         ["pinelive"]["picture"]["kind"], "cam")
        self.assertTrue(pl.state()["picture"]["tailscale_video"])
        pl.phase = "arming"                                   # end quietly: no air to give back
        pl.stop("test")


if __name__ == "__main__":
    unittest.main()
