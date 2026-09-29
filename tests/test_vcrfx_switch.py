"""[vcrfx] PineCam to live counts its flips for the viewer's CRT.

- every real flip of tailscale_video is counted; a save that does not change
  it is not (a viewer must never replay a flip that did not happen)
- the clock's PineLive block carries the switch (on, flips, armed), for the
  house and for the door alike - the door's picture follows it
- the module-level video_switch() answers even when PineLive is broken
- app.py: /api/pinelink/mine answers `switch` and the viewer check can be
  asked "but for the switch" (source-level: app.py is not imported here)

  docker exec -w /tmp/wX -e PYTHONPATH=tests:. spark-agent nice -n 10 \\
      python3 -m unittest tests.test_vcrfx_switch -v
"""
import ast
import tempfile
import time
import unittest
from pathlib import Path

import pinelive


class _Src:
    duck_now = 0.0

    def __init__(self, *a, **kw):
        pass

    def close(self):
        pass

    def summary(self):
        return {}


class VideoSwitchFlips(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)
        self._saved = (pinelive.LiveSource, pinelive.PineLive._supervise, pinelive._G)
        pinelive.LiveSource = _Src
        pinelive.PineLive._supervise = lambda self: None
        pinelive._G = {}
        self.pl = pinelive.PineLive(data_dir=self.dir)
        self.pl.boot()

    def tearDown(self):
        pinelive.LiveSource, pinelive.PineLive._supervise, pinelive._G = self._saved
        self._td.cleanup()

    def arm(self, stamp="20260929-120000"):
        pl = self.pl
        with pl.lock:
            pl.event = {"id": "mxlive-" + stamp, "name": pinelive.EVENT_NAME,
                        "started_at": time.time(), "folder": "%s_%s" % (stamp, pinelive.EVENT_SLUG),
                        "armed": True, "fallbacks": 0, "rehearse": False,
                        "album": bool(pl.settings.get("record", True))}
            pl.source_kind, pl.device, pl.token = "usb", "hw:TEST", "t"
            pl._arm_runtime(resume=False)

    def test_each_real_flip_is_counted_and_nothing_else(self):
        pl = self.pl
        start = pl.video_switch()["flips"]
        want = not bool(pl.settings.get("tailscale_video"))
        for _ in range(6):                      # six fast flips
            pl.set_settings({"tailscale_video": want})
            want = not want
        self.assertEqual(pl.video_switch()["flips"], start + 6)
        now = bool(pl.settings.get("tailscale_video"))
        pl.set_settings({"tailscale_video": now})          # the same value again
        pl.set_settings({"cut_seconds": 300})              # another setting
        self.assertEqual(pl.video_switch()["flips"], start + 6)
        self.assertEqual(pl.video_switch()["on"], now)

    def test_the_clock_carries_the_switch_while_armed(self):
        pl = self.pl
        self.assertEqual(pl.clock_extra({"pinelive": True}, away=True), {})   # no set: nothing
        self.arm()
        try:
            pl.set_settings({"tailscale_video": False})
            before = pl.video_switch()["flips"]
            pl.set_settings({"tailscale_video": True})
            for away in (False, True):
                sw = pl.clock_extra({"pinelive": True}, away=away)["pinelive"]["picture"]["switch"]
                self.assertEqual(sw, {"on": True, "flips": before + 1, "armed": True})
            pl.set_settings({"tailscale_video": False})
            pic = pl.clock_extra({"pinelive": True}, away=True)["pinelive"]["picture"]
            self.assertEqual(pic["art"], "")                     # the door loses the picture...
            self.assertEqual(pic["switch"]["flips"], before + 2)  # ...and is told it was a flip
            self.assertFalse(pic["switch"]["on"])
        finally:
            try:
                pl.stop()
            except Exception:  # noqa: BLE001
                pass

    def test_module_answer_never_throws(self):
        saved = pinelive.PL
        try:
            pinelive.PL = None
            self.assertEqual(pinelive.video_switch(), {"on": False, "flips": 0, "armed": False})
        finally:
            pinelive.PL = saved


class MineAnswersTheSwitch(unittest.TestCase):
    """app.py is 270k lines and boots the station on import; read it instead."""

    @classmethod
    def setUpClass(cls):
        cls.src = Path("app.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.src)

    def fn(self, name):
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return node
        self.fail("no %s in app.py" % name)

    def test_viewer_ok_can_be_asked_but_for_the_switch(self):
        f = self.fn("pinelink_viewer_ok")
        self.assertEqual([a.arg for a in f.args.args], ["token", "switch"])
        self.assertTrue(f.args.defaults and f.args.defaults[0].value is True)
        body = ast.get_source_segment(self.src, f)
        self.assertIn("if switch and pinelive.public_video_blocked():", body)

    def test_mine_answers_switch_with_yours(self):
        body = ast.get_source_segment(self.src, self.fn("pinelink_mine_api"))
        self.assertIn('"switch": _vcr_switch(t),', body)
        helper = ast.get_source_segment(self.src, self.fn("_vcr_switch"))
        self.assertIn("pinelink_viewer_ok(t, switch=False)", helper)
        self.assertIn("pinelive.video_switch()", helper)

    def test_the_asset_is_served_and_allowed_through_the_door(self):
        self.assertIn('"pine-vcr.js": "application/javascript; charset=utf-8",', self.src)
        self.assertIn('"/spark/asset/pine-vcr.js",', self.src)
        tune = self.src[self.src.index('RADIO_PAGE_HTML = r"""'):]
        self.assertIn('<script src="/spark/asset/pine-vcr.js"></script>', tune[:4000])


if __name__ == "__main__":
    unittest.main()
