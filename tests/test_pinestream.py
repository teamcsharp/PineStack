"""[pinestream] PineStream: the station's half and PineLive's switch.

- the switch is the master: off answers every frame keep:false, drops the
  held frame, serves nothing and tells a viewer show:false
- only the chosen source may push; a frame is one whole JPEG, size-capped
- an empty post keeps a still screen live; silence goes stale (a veil)
- private drops the picture at once and serves the dark placeholder
- the routes: the door needs a live token, the house reads, the panel's
  preview is signed, the push needs the key
- PineLive: stream_on / stream_source / rates are settings (clamped,
  refused), flips are counted only when the switch really moves, and the
  panel's state carries a `stream` block
- app.py (source-level, not imported): installed, opened on the door, rides
  /api/pinelink/mine, and the tune page carries the PiP

  docker exec -w /tmp/wX -e PYTHONPATH=tests:. -e SPARK_AGENT_DATA_DIR=/tmp/wX_data \\
      spark-agent nice -n 10 python3 -m unittest tests.test_pinestream -v
"""
import ast
import asyncio
import tempfile
import unittest
from pathlib import Path

import pinelive
import pinestream

JPEG = bytes(pinelive.PLACEHOLDER_JPEG)        # a real 160x90 JPEG
ROOT = Path(__file__).resolve().parent.parent


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(settings=None, flips=0):
    s = {"stream_on": False, "stream_source": "pinetab", "stream_fps": 2,
         "stream_width": 640, "stream_quality": 60}
    s.update(settings or {})
    box = {"s": s, "flips": flips}
    clock = Clock()
    ps = pinestream.PineStream(settings=lambda: box["s"], flips=lambda: box["flips"], clock=clock)
    return ps, box, clock


class TheSwitchIsTheMaster(unittest.TestCase):
    def test_off_refuses_holds_nothing_serves_nothing(self):
        ps, box, _ = make()
        code, ans = ps.accept("pinetab", JPEG)
        self.assertEqual(code, 200)
        self.assertFalse(ans["keep"])
        self.assertEqual(ps.jpeg, b"")
        self.assertEqual(ps.frame(), (None, "off"))
        self.assertFalse(ps.viewer(True)["show"])

    def test_on_serves_the_frame_it_was_given(self):
        ps, box, _ = make({"stream_on": True})
        code, ans = ps.accept("pinetab", JPEG, agent="tablet")
        self.assertEqual(code, 200)
        self.assertTrue(ans["keep"])
        self.assertEqual((ans["fps"], ans["width"], ans["quality"]), (2, 640, 60))
        self.assertEqual(ps.frame(), (JPEG, "live"))
        v = ps.viewer(True)
        self.assertTrue(v["show"])
        self.assertEqual(v["state"], "live")
        self.assertEqual(ps.status()["size"], [160, 90])

    def test_switching_off_drops_the_held_frame_at_once(self):
        ps, box, _ = make({"stream_on": True})
        ps.accept("pinetab", JPEG)
        box["s"]["stream_on"] = False
        self.assertEqual(ps.frame(), (None, "off"))
        self.assertEqual(ps.jpeg, b"")
        self.assertEqual(ps.status()["frames"], 0)

    def test_only_the_chosen_screen_may_push(self):
        ps, box, _ = make({"stream_on": True, "stream_source": "pineapp"})
        code, ans = ps.accept("pinetab", JPEG)
        self.assertFalse(ans["keep"])
        self.assertEqual(ps.frame(), (None, "waiting"))
        code, ans = ps.accept("pineapp", JPEG)
        self.assertTrue(ans["keep"])
        self.assertEqual(ps.frame()[1], "live")

    def test_a_frame_is_one_whole_jpeg_and_capped(self):
        ps, box, _ = make({"stream_on": True})
        self.assertEqual(ps.accept("pinetab", b"not a jpeg")[0], 400)
        self.assertEqual(ps.accept("pinetab", JPEG[:-2])[0], 400)
        big = b"\xff\xd8" + b"\0" * pinestream.MAX_BYTES + b"\xff\xd9"
        self.assertEqual(ps.accept("pinetab", big)[0], 413)
        self.assertEqual(ps.jpeg, b"")

    def test_a_still_screen_stays_live_and_silence_goes_stale(self):
        ps, box, clock = make({"stream_on": True})
        ps.accept("pinetab", JPEG)
        clock.t += pinestream.FRESH_S - 1
        ps.accept("pinetab", b"")                      # unchanged: keep-alive
        clock.t += pinestream.FRESH_S - 1
        self.assertEqual(ps.frame()[1], "live")
        clock.t += 2
        self.assertEqual(ps.frame(), (None, "waiting"))

    def test_private_drops_the_picture_and_says_why(self):
        ps, box, _ = make({"stream_on": True})
        ps.accept("pinetab", JPEG)
        ps.accept("pinetab", b"", private=True, why="a key field is on the screen")
        self.assertEqual(ps.jpeg, b"")
        jpeg, state = ps.frame()
        self.assertEqual(state, "private")
        self.assertEqual(jpeg, JPEG)                   # the dark placeholder, not the screen
        v = ps.viewer(True)
        self.assertEqual((v["state"], v["why"]), ("private", "a key field is on the screen"))
        ps.accept("pinetab", JPEG)                     # a real frame lifts the veil
        self.assertEqual(ps.frame()[1], "live")

    def test_a_viewer_without_leave_sees_nothing(self):
        ps, box, _ = make({"stream_on": True}, flips=3)
        ps.accept("pinetab", JPEG)
        v = ps.viewer(False)
        self.assertFalse(v["show"])
        self.assertEqual(v["state"], "off")
        self.assertEqual(v["switch"], {"on": True, "flips": 3, "yours": False})

    def test_settings_are_read_defensively(self):
        got = pinestream.clamp_choice({"stream_on": 1, "stream_source": "bogus",
                                       "stream_fps": 99, "stream_width": "x"})
        self.assertEqual(got, {"on": True, "source": "pinetab", "fps": 60, "width": 640, "quality": 60})

    def test_watching_counts_recent_viewers_only(self):
        ps, box, clock = make({"stream_on": True})
        ps.seen("t:a")
        ps.seen("t:b")
        ps.seen("")
        self.assertEqual(ps.watching(), 2)
        clock.t += pinestream.VIEWER_S + 1
        ps.seen("t:c")
        self.assertEqual(ps.watching(), 1)


class Routes(unittest.TestCase):
    """The four routes on a bare FastAPI app with the station's auth stubbed."""

    def setUp(self):
        try:
            from fastapi import FastAPI, HTTPException
            from fastapi.testclient import TestClient
        except Exception as err:  # noqa: BLE001
            self.skipTest("fastapi test client: %s" % err)
        self.saved = (pinestream.PS, pinestream._G)
        ps, self.box, self.clock = make({"stream_on": True})
        pinestream.PS = ps

        def require_auth(a):
            if a != "Bearer k":
                raise HTTPException(status_code=401, detail="Unauthorized")

        g = {"require_auth": require_auth, "require_read_auth": lambda a: None,
             "listen_ok": lambda t: t == "good", "token_tag": lambda t: "tag-" + t,
             "media_sign": lambda key: "sig-" + key}
        app = FastAPI()
        pinestream.install(app, g)
        self.c = TestClient(app)

    def tearDown(self):
        pinestream.PS, pinestream._G = self.saved

    def push(self, body=JPEG, source="pinetab", key="Bearer k", extra=""):
        return self.c.post("/api/pinestream/frame?source=" + source + extra, content=body,
                           headers={"Authorization": key, "Content-Type": "image/jpeg"})

    def test_the_push_needs_the_key_and_answers_keep(self):
        self.assertEqual(self.push(key="Bearer nope").status_code, 401)
        r = self.push()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["keep"])
        self.box["s"]["stream_on"] = False
        self.assertFalse(self.push().json()["keep"])

    def test_the_door_needs_a_live_token(self):
        self.push()
        door = {"x-pinebox-public": "1"}
        self.assertEqual(self.c.get("/api/pinestream/frame.jpg", headers=door).status_code, 403)
        self.assertEqual(self.c.get("/api/pinestream/frame.jpg?t=bad", headers=door).status_code, 403)
        r = self.c.get("/api/pinestream/frame.jpg?t=good", headers=door)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, JPEG)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertFalse(self.c.get("/api/pinestream/mine", headers=door).json()["show"])
        self.assertTrue(self.c.get("/api/pinestream/mine?t=good", headers=door).json()["show"])
        self.assertEqual(pinestream.PS.watching(), 1)

    def test_the_house_and_the_signed_preview(self):
        self.push()
        self.assertEqual(self.c.get("/api/pinestream/frame.jpg").status_code, 200)
        self.assertEqual(self.c.get("/api/pinestream/frame.jpg?s=wrong").status_code, 403)
        st = self.c.get("/api/pinestream/state", headers={"Authorization": "Bearer k"}).json()
        self.assertEqual(st["preview"], "/api/pinestream/frame.jpg?s=sig-" + pinestream.PREVIEW_KEY)
        self.assertEqual(self.c.get(st["preview"]).status_code, 200)
        door = {"x-pinebox-public": "1"}
        self.assertEqual(self.c.get(st["preview"], headers=door).status_code, 403)
        self.assertEqual(self.c.get("/api/pinestream/state").status_code, 401)

    def test_off_serves_nothing(self):
        self.push()
        self.box["s"]["stream_on"] = False
        r = self.c.get("/api/pinestream/frame.jpg?t=good")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.headers["x-pinestream"], "off")

    def test_live_stream_enforces_the_same_access_as_stills(self):
        door = {"x-pinebox-public": "1"}
        for query in ("", "?t=bad", "?s=sig-pinestream-preview"):
            self.assertEqual(self.c.get("/api/pinestream/live.mjpg" + query, headers=door).status_code, 403)
        self.box["s"]["stream_on"] = False
        self.assertEqual(self.c.get("/api/pinestream/live.mjpg?t=good").status_code, 404)
        self.assertIn("live.mjpg", self.c.get("/api/pinestream/mine?t=good").json()["stream"])


class LiveFrames(unittest.IsolatedAsyncioTestCase):
    async def test_frames_wake_immediately_and_slow_consumers_get_latest(self):
        ps, box, _ = make({"stream_on": True, "stream_fps": 30})
        feed = ps.live_frames(lambda: True, 'live-viewer')
        pending = asyncio.create_task(anext(feed))
        await asyncio.sleep(0)
        first = b'\xff\xd8first\xff\xd9'
        ps.accept('pinetab', first)
        self.assertIn(first, await asyncio.wait_for(pending, .2))
        ps.accept('pinetab', b'\xff\xd8stale\xff\xd9')
        latest = b'\xff\xd8latest\xff\xd9'
        ps.accept('pinetab', latest)
        self.assertIn(latest, await asyncio.wait_for(anext(feed), .2))
        self.assertEqual(len(ps.subscribers), 1)
        self.assertEqual(ps.watching(), 1)
        await feed.aclose()
        self.assertEqual(len(ps.subscribers), 0)

    async def test_private_off_and_revoked_access_stop_exposing_picture(self):
        ps, box, _ = make({"stream_on": True})
        authorized = True
        ps.accept('pinetab', JPEG)
        feed = ps.live_frames(lambda: authorized)
        self.assertIn(JPEG, await anext(feed))
        ps.accept('pinetab', b'', private=True)
        # The private placeholder is sent, never the previous screen.
        self.assertIn(pinestream._placeholder(), await asyncio.wait_for(anext(feed), .2))
        authorized = False
        with self.assertRaises(StopAsyncIteration): await anext(feed)
        self.assertEqual(len(ps.subscribers), 0)
        box['s']['stream_on'] = False
        off = ps.live_frames(lambda: True)
        with self.assertRaises(StopAsyncIteration): await anext(off)

    async def test_cancelled_waiter_releases_subscription(self):
        ps, _, _ = make({"stream_on": True})
        feed = ps.live_frames(lambda: True)
        pending = asyncio.create_task(anext(feed))
        await asyncio.sleep(0)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError): await pending
        self.assertEqual(len(ps.subscribers), 0)


class PineLiveCarriesTheSwitch(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._saved = (pinelive.PineLive._supervise, pinelive._G)
        pinelive.PineLive._supervise = lambda self: None
        pinelive._G = {}
        self.pl = pinelive.PineLive(data_dir=Path(self._td.name))
        self.pl.boot()

    def tearDown(self):
        pinelive.PineLive._supervise, pinelive._G = self._saved
        self._td.cleanup()

    def test_off_by_default_and_the_choices_are_settings(self):
        self.assertFalse(pinelive.DEFAULTS["stream_on"])
        new, refused = self.pl.set_settings({"stream_source": "pineapp", "stream_fps": 40,
                                             "stream_width": 100, "stream_quality": 75})
        self.assertEqual(refused, [])
        self.assertEqual((new["stream_source"], new["stream_fps"], new["stream_width"],
                          new["stream_quality"]), ("pineapp", 40, 320, 75))
        new, refused = self.pl.set_settings({"stream_source": "the moon"})
        self.assertEqual(refused, ["stream_source"])
        self.assertEqual(new["stream_source"], "pineapp")

    def test_each_real_flip_is_counted_and_nothing_else(self):
        start = int(getattr(self.pl, "stream_flips", 0))
        want = True
        for _ in range(5):
            self.pl.set_settings({"stream_on": want})
            want = not want
        self.assertEqual(self.pl.stream_flips, start + 5)
        now = bool(self.pl.settings["stream_on"])
        self.pl.set_settings({"stream_on": now})
        self.pl.set_settings({"stream_source": "pinetab"})
        self.pl.set_settings({"tailscale_video": True})
        self.assertEqual(self.pl.stream_flips, start + 5)

    def test_the_state_carries_the_stream_block(self):
        saved = pinestream.PS          # in the station the module reads the one PL; here, this one
        pinestream.PS = pinestream.PineStream(settings=lambda: self.pl.settings,
                                              flips=lambda: self.pl.stream_flips)
        self.addCleanup(setattr, pinestream, "PS", saved)
        self.pl.set_settings({"stream_on": True, "stream_source": "pinetab"})
        pinestream.PS.accept("pinetab", JPEG)
        st = self.pl.state()["stream"]
        self.assertEqual(st["picture"], "live")
        self.assertEqual(st["size"], [160, 90])
        self.assertTrue(st["on"])
        self.assertEqual(st["source"], "pinetab")
        self.assertIn(st["picture"], ("waiting", "live", "private"))
        self.assertIn("flips", st)

    def test_a_restart_comes_back_off(self):
        """The operator's rule: after any station restart stream_on is false until
        he flips it again; the source, rate, width and quality are remembered, and
        a screen still pushing is told keep:false."""
        self.pl.set_settings({"stream_on": True, "stream_source": "pineapp",
                              "stream_fps": 3, "stream_width": 800, "stream_quality": 75})
        again = pinelive.PineLive(data_dir=Path(self._td.name))
        again.boot()
        self.assertFalse(again.settings["stream_on"])
        self.assertEqual((again.settings["stream_source"], again.settings["stream_fps"],
                          again.settings["stream_width"], again.settings["stream_quality"]),
                         ("pineapp", 3, 800, 75))
        import json
        on_disk = json.loads(again.settings_path.read_text())
        self.assertFalse(on_disk["stream_on"])       # the file says what the station does
        ps = pinestream.PineStream(settings=lambda: again.settings)
        code, ans = ps.accept("pineapp", JPEG)
        self.assertFalse(ans["keep"])                 # the desk still pushing is stopped
        self.assertEqual(ps.frame(), (None, "off"))
        third = pinelive.PineLive(data_dir=Path(self._td.name))
        third.boot()                                  # a second restart: still off
        self.assertFalse(third.settings["stream_on"])

    def test_on_after_a_restart_only_when_flipped(self):
        again = pinelive.PineLive(data_dir=Path(self._td.name))
        again.boot()
        again.set_settings({"stream_on": True})
        self.assertTrue(again.settings["stream_on"])


class AppWiring(unittest.TestCase):
    """app.py is read, not imported (the live app must never start here)."""

    @classmethod
    def setUpClass(cls):
        cls.src = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.src)

    def test_installed_and_opened_on_the_door(self):
        self.assertIn("\nimport pinestream ", self.src)
        self.assertIn("\npinestream.install(app, globals())", self.src)
        i = self.src.index("\npinestream.install(app, globals())")
        tail = self.src[i:i + 600]
        for path in ('"/api/pinestream/mine"', '"/api/pinestream/frame.jpg"', '"/spark/asset/pine-closex.js"'):
            self.assertIn(path, tail)
        self.assertNotIn('"/api/pinestream/frame"', tail)    # the push is never public

    def test_the_cam_poll_carries_it(self):
        fn = next(n for n in ast.walk(self.tree)
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "pinelink_mine_api")
        body = ast.get_source_segment(self.src, fn)
        self.assertIn('"pinestream": pinestream.mine_for(', body)

    def test_the_tune_page_has_the_window(self):
        i = self.src.index('RADIO_PAGE_HTML = r"""')
        page = self.src[i:self.src.index('\n"""', i)]
        for bit in (".pinestream {", "window.PineStreamTune = {", "PineStreamTune.news(got && got.pinestream)",
                    '<script src="/spark/asset/pine-closex.js">', "pbfm.pinestream.hidden",
                    "V.flip(box, want, burst, o)"):
            self.assertIn(bit, page)


class ShareLinksAreVeiled(unittest.TestCase):
    """Every surface that shows a tune-in link carries data-pine-private, so
    PineStream shows 'Private screen' while it is open (read, not run)."""

    def test_the_panel_remote_modal(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        i = src.index("async function remotePanel()")
        body = src[i:src.index("document.body.appendChild(shade);", i)]
        self.assertIn('shade.setAttribute("data-pine-private"', body)
        for bit in ('api("/api/share")', 'api("/api/share/car"'):     # the list and the car link live in it
            j = src.index(bit, i)
            self.assertLess(j, src.index("async function artistReadPanel()", i))

    def test_the_desk_drawer_and_the_cam_viewers(self):
        html = (ROOT / "desktop" / "renderer" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<section data-pine-private="a tune-in link is on the screen">\n        <h3>Public broadcast</h3>', html)
        self.assertRegex(html, r'id="pineCamViewers"[^>]*data-pine-private=')

    def test_the_go_live_sheet_on_both_screens(self):
        desk = (ROOT / "desktop" / "renderer" / "pinelive.js").read_text(encoding="utf-8")
        tab = (ROOT / "app" / "src" / "main" / "assets" / "pine-views" / "pinelive.js").read_text(encoding="utf-8")
        self.assertEqual(desk, tab)
        i = desk.index("function openShareSheet()")
        self.assertIn("s.back.setAttribute('data-pine-private'", desk[i:i + 400])

    def test_the_agent_reads_the_attribute(self):
        js = (ROOT / "desktop" / "renderer" / "pinestream.js").read_text(encoding="utf-8")
        self.assertIn("querySelectorAll('[data-pine-private]')", js)


class ChooserAndCamGrey(unittest.TestCase):
    """[pinestream-choose] the screens' check-ins; [camgrey] the camera's words."""

    def test_a_screen_that_checks_in_can_stream(self):
        ps, box, clock = make()
        src = ps.sources()
        self.assertFalse(src["pinetab"]["ok"])
        self.assertEqual(src["pineapp"]["why"], "the Pine app is not open")
        ps.checkin("pinetab", True)
        ps.checkin("pineapp", False)
        ps.checkin("bogus", True)
        src = ps.sources()
        self.assertEqual(sorted(src), ["pineapp", "pinetab"])
        self.assertTrue(src["pinetab"]["ok"])
        self.assertEqual(src["pineapp"]["why"], "the Pine app is minimised or hidden")
        clock.t += pinestream.CHECKIN_S + 1
        self.assertIn("has not checked in for", ps.sources()["pinetab"]["why"])
        self.assertIn("sources", ps.status())

    def test_the_state_route_takes_the_check_in(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except Exception as err:  # noqa: BLE001
            self.skipTest(str(err))
        saved = (pinestream.PS, pinestream._G)

        def restore():
            pinestream.PS, pinestream._G = saved
        self.addCleanup(restore)
        pinestream.PS = make()[0]
        app = FastAPI()
        pinestream.install(app, {"require_auth": lambda a: None, "require_read_auth": lambda a: None})
        c = TestClient(app)
        got = c.get("/api/pinestream/state?from=pinetab&awake=0").json()
        self.assertEqual(got["sources"]["pinetab"]["why"], "the PineTab's screen is asleep")
        got = c.get("/api/pinestream/state?from=pinetab&awake=1").json()
        self.assertTrue(got["sources"]["pinetab"]["ok"])

    def test_the_picture_block_names_why_the_camera_is_off(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        saved = (pinelive.PineLive._supervise, pinelive._G)

        def restore():
            pinelive.PineLive._supervise, pinelive._G = saved
        self.addCleanup(restore)
        pinelive.PineLive._supervise = lambda self: None
        link = {"state": "no-link", "fresh": True,
                "why": "the camera's network is not being broadcast, or the join failed"}
        pinelive._G = {"pinelink_state": lambda: dict(link)}
        pl = pinelive.PineLive(data_dir=Path(td.name))
        pl.boot()
        pic = pl.state()["picture"]
        self.assertEqual((pic["cam_live"], pic["cam_state"], pic["cam_seen_ago"]), (False, "no-link", None))
        self.assertIn("not being broadcast", pic["cam_why"])
        link.update(state="live", why="")
        self.assertTrue(pl.state()["picture"]["cam_live"])
        link.update(state="no-link")
        pic = pl.state()["picture"]
        self.assertFalse(pic["cam_live"])
        self.assertIsNotNone(pic["cam_seen_ago"])     # last seen, since this station started
        link.update(state="live", fresh=False)          # a stale claim is not live
        self.assertFalse(pl.state()["picture"]["cam_live"])

    def test_the_views_carry_the_greying_and_the_chooser(self):
        desk = (ROOT / "desktop" / "renderer" / "pinelive.js").read_text(encoding="utf-8")
        tab = (ROOT / "app" / "src" / "main" / "assets" / "pine-views" / "pinelive.js").read_text(encoding="utf-8")
        self.assertEqual(desk, tab)
        for bit in ("paintCamGrey(h.cam.root", "paintCamGrey(p.parts.ts.root", "function openChooser(anchor)",
                    "if (next) { openChooser(node);", "paintStreamPicker(h.streamSrc, src, on)",
                    "if (ui.chooser) closeChooser();"):
            self.assertIn(bit, desk)
        agent = (ROOT / "desktop" / "renderer" / "pinestream.js").read_text(encoding="utf-8")
        self.assertIn("'/api/pinestream/state?from='", agent)


if __name__ == "__main__":
    unittest.main()
