"""[pincrop] The station's crop routes, exercised as routes.

The block tools/pincrop_patch.py inserts into app.py is executed here inside
a real FastAPI app, with app.py's own names (data_path, pinelink_state, the
auth gates, pipeline_log) stubbed - so what is tested is the very text the
patch writes, not a copy of it.

  * POST writes data/pinelink_crop.json whole, exactly as tools/pinelink.py
    crop_wanted() will read it (the host module is imported and made to
    read the file this station wrote);
  * "saved" and "applied" are different claims: pending, supervisor_cuts
    and the say sentence each tell the truth for their state;
  * a box that is a slip, a whole-frame box, and a body that is not a box
    are each refused with a sentence and NOTHING is written;
  * the whole-picture frame road serves only the house - the public door
    and any tune-in token get 403 - and never a half-written JPEG.

Run from pincrop/station:  python -m unittest tests.test_pincrop_routes
"""
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.testclient import TestClient

HERE = Path(__file__).resolve().parent
STATION = HERE.parent
PINCROP = STATION.parent

# The very text the patch writes into app.py.
SPEC = importlib.util.spec_from_file_location(
    "pincrop_patch", STATION / "tools" / "pincrop_patch.py")
patch_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patch_mod)
BLOCK = patch_mod._ROUTES_NEW.split("\n", 3)[3]  # drop the re-emitted anchor

# The host's reader, to prove the two sides read one file the same way.
HSPEC = importlib.util.spec_from_file_location(
    "pinelink_under_test", PINCROP / "host" / "tools" / "pinelink.py")
pinelink = importlib.util.module_from_spec(HSPEC)
HSPEC.loader.exec_module(pinelink)

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 2048 + b"\xff\xd9"


def build(tmp: Path):
    """The [pincrop] block, alive inside a fresh FastAPI app over tmp."""
    import asyncio
    import os
    app = FastAPI()
    state: dict = {"state": "live", "fresh": True}
    logged: list = []
    ns = {
        "app": app, "Request": Request, "Header": Header,
        "HTTPException": HTTPException, "Response": Response,
        "Any": Any, "asyncio": asyncio, "json": json, "os": os,
        "time": time,
        "data_path": lambda name: tmp / "data" / name,
        "PINELINK_DIR": tmp / "data" / "pinelink",
        "PINELINK_FRAME": tmp / "data" / "pinelink" / "frame.jpg",
        "pinelink_state": lambda: dict(state),
        "require_read_auth": lambda authorization=None: None,
        "require_auth": lambda authorization=None: None,
        "pipeline_log": lambda lane, text: logged.append((lane, text)),
    }
    exec(compile(BLOCK, "app.py[pincrop]", "exec"), ns)
    (tmp / "data" / "pinelink").mkdir(parents=True, exist_ok=True)
    return app, ns, state, logged


class Routes(unittest.TestCase):
    def setUp(self):
        self.tmp_ = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp_.cleanup)
        self.tmp = Path(self.tmp_.name)
        self.app, self.ns, self.state, self.logged = build(self.tmp)
        self.client = TestClient(self.app)
        self.crop_file = self.tmp / "data" / "pinelink_crop.json"

    # ------------------------------------------------------------ the POST

    def test_a_posted_box_reaches_the_file_the_supervisor_reads(self):
        r = self.client.post("/api/pinelink/crop",
                             json={"x": 0.25, "y": 0.1, "w": 0.5, "h": 0.6})
        self.assertTrue(r.json()["ok"], r.text)
        got = json.loads(self.crop_file.read_text())
        self.assertEqual(got["crop"], {"x": 0.25, "y": 0.1, "w": 0.5, "h": 0.6})
        # the host reads the station's file as the very same box
        pinelink.CROP_FILE = self.crop_file
        want, bad = pinelink.crop_wanted()
        self.assertEqual(bad, "")
        self.assertEqual(want, {"x": 0.25, "y": 0.1, "w": 0.5, "h": 0.6})
        self.assertTrue(self.logged and "pine cam crop" in self.logged[0][1])

    def test_the_wrapped_and_bare_shapes_are_one_road(self):
        a = self.client.post("/api/pinelink/crop",
                             json={"crop": {"x": 0.2, "y": 0.2, "w": 0.4, "h": 0.4}})
        self.assertTrue(a.json()["ok"])
        first = self.crop_file.read_text()
        b = self.client.post("/api/pinelink/crop",
                             json={"x": 0.2, "y": 0.2, "w": 0.4, "h": 0.4})
        self.assertTrue(b.json()["ok"])
        self.assertEqual(json.loads(first)["crop"],
                         json.loads(self.crop_file.read_text())["crop"])

    def test_reset_and_null_both_take_the_crop_away(self):
        for body in ({"reset": True}, {"crop": None}):
            self.client.post("/api/pinelink/crop",
                             json={"x": 0.3, "y": 0.3, "w": 0.3, "h": 0.3})
            r = self.client.post("/api/pinelink/crop", json=body)
            self.assertTrue(r.json()["ok"], r.text)
            self.assertIsNone(json.loads(self.crop_file.read_text())["crop"])

    def test_a_slip_is_refused_with_a_sentence_and_nothing_is_written(self):
        r = self.client.post("/api/pinelink/crop",
                             json={"x": 0.5, "y": 0.5, "w": 0.01, "h": 0.01})
        got = r.json()
        self.assertFalse(got["ok"])
        self.assertIn("bigger", got["say"])
        self.assertFalse(self.crop_file.exists())

    def test_the_whole_frame_is_no_crop(self):
        r = self.client.post("/api/pinelink/crop",
                             json={"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0})
        self.assertTrue(r.json()["ok"])
        self.assertIsNone(json.loads(self.crop_file.read_text())["crop"])

    def test_not_a_box_is_refused(self):
        for body in ({}, {"x": "a", "y": 0, "w": 1, "h": 1}, {"crop": [1, 2, 3]}):
            r = self.client.post("/api/pinelink/crop", json=body)
            self.assertFalse(r.json()["ok"], body)
            self.assertFalse(self.crop_file.exists())
        # NaN (json.dumps writes it, the parser refuses it) and non-JSON both
        # land as an empty body, which is not a box
        for raw in (b'{"x": 0, "y": 0, "w": NaN, "h": 1}', b"not json at all"):
            r = self.client.post("/api/pinelink/crop", content=raw,
                                 headers={"Content-Type": "application/json"})
            self.assertFalse(r.json()["ok"], raw)
            self.assertFalse(self.crop_file.exists())

    def test_the_clamp_matches_the_supervisors_to_the_last_place(self):
        import random
        rnd = random.Random(1470)
        for _ in range(2000):
            raw = {"x": rnd.uniform(-0.5, 1.2), "y": rnd.uniform(-0.5, 1.2),
                   "w": rnd.uniform(-0.2, 1.5), "h": rnd.uniform(-0.2, 1.5)}
            try:
                ours = self.ns["pinelink_crop_clean"](dict(raw))
            except ValueError:
                ours = ValueError
            try:
                theirs = pinelink.crop_clean(dict(raw))
            except ValueError:
                theirs = ValueError
            if ours is ValueError or theirs is ValueError:
                # the station also files a whole-frame box under "no crop";
                # the supervisor keeps it (it cuts nothing either way)
                if ours is None and theirs is not ValueError:
                    continue
                self.assertEqual(ours, theirs, raw)
            elif ours is None:
                self.assertTrue(theirs is None or (
                    theirs["w"] >= 0.995 and theirs["h"] >= 0.995), raw)
            else:
                self.assertEqual(ours, theirs, raw)

    # ------------------------------------------------------------- the GET

    def test_saved_but_an_old_supervisor_says_nothing_is_cropped(self):
        self.client.post("/api/pinelink/crop",
                         json={"x": 0.2, "y": 0.2, "w": 0.5, "h": 0.5})
        got = self.client.get("/api/pinelink/crop").json()
        self.assertEqual(got["want"], {"x": 0.2, "y": 0.2, "w": 0.5, "h": 0.5})
        self.assertIsNone(got["applied"])
        self.assertFalse(got["supervisor_cuts"])
        self.assertTrue(got["pending"])
        self.assertIn("NOTHING is cropped", got["say"])

    def test_applied_and_matching_reads_cropped(self):
        self.client.post("/api/pinelink/crop",
                         json={"x": 0.2, "y": 0.2, "w": 0.5, "h": 0.5})
        self.state["crop"] = {"on": True, "box": {"x": 0.2, "y": 0.2, "w": 0.5, "h": 0.5},
                              "error": "", "at": time.time(), "src": [848, 480],
                              "cut": [170, 96, 424, 240], "out": [848, 480], "pad": [0, 0]}
        got = self.client.get("/api/pinelink/crop").json()
        self.assertFalse(got["pending"])
        self.assertTrue(got["supervisor_cuts"])
        self.assertIn("cropped: only the box goes out", got["say"])
        self.assertIn("50%", got["say"])

    def test_a_new_box_over_a_running_cut_is_pending(self):
        self.state["crop"] = {"on": True, "box": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5},
                              "error": "", "at": time.time()}
        self.client.post("/api/pinelink/crop",
                         json={"x": 0.3, "y": 0.3, "w": 0.4, "h": 0.4})
        got = self.client.get("/api/pinelink/crop").json()
        self.assertTrue(got["pending"])
        self.assertEqual(got["applied"], {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5})

    def test_no_crop_anywhere_says_the_whole_picture(self):
        self.state["crop"] = {"on": False, "box": None, "error": "", "at": 0.0}
        got = self.client.get("/api/pinelink/crop").json()
        self.assertFalse(got["pending"])
        self.assertIn("whole picture", got["say"])

    # ------------------------------------------------------- the two doors

    def test_the_public_door_gets_403_on_every_crop_road(self):
        hdr = {"x-pinebox-public": "1"}
        self.assertEqual(self.client.get("/api/pinelink/crop", headers=hdr).status_code, 403)
        self.assertEqual(self.client.post("/api/pinelink/crop", headers=hdr,
                                          json={"x": 0, "y": 0, "w": 1, "h": 1}).status_code, 403)
        self.assertEqual(self.client.get("/api/pinelink/crop/frame.jpg", headers=hdr).status_code, 403)

    def test_a_tune_in_token_never_sees_the_whole_picture(self):
        self.assertEqual(
            self.client.get("/api/pinelink/crop/frame.jpg?t=1789").status_code, 403)

    # ------------------------------------------------------ the whole frame

    def test_with_no_crop_the_whole_picture_is_frame_jpg(self):
        (self.tmp / "data" / "pinelink" / "frame.jpg").write_bytes(JPEG)
        r = self.client.get("/api/pinelink/crop/frame.jpg")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, JPEG)
        self.assertIn("no-store", r.headers["cache-control"])

    def test_with_a_crop_cut_the_whole_picture_is_frame_raw(self):
        self.state["crop"] = {"on": True, "box": {"x": 0.2, "y": 0.2, "w": 0.5, "h": 0.5},
                              "error": "", "at": time.time() - 30}
        raw = JPEG.replace(b"\xe0", b"\xe1", 1)
        (self.tmp / "data" / "pinelink" / "frame_raw.jpg").write_bytes(raw)
        (self.tmp / "data" / "pinelink" / "frame.jpg").write_bytes(JPEG)
        r = self.client.get("/api/pinelink/crop/frame.jpg")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, raw)

    def test_a_half_written_jpeg_is_never_served(self):
        (self.tmp / "data" / "pinelink" / "frame.jpg").write_bytes(JPEG[:-2] + b"\x00\x00")
        self.assertEqual(self.client.get("/api/pinelink/crop/frame.jpg").status_code, 404)

    def test_a_frame_older_than_the_cut_is_never_served(self):
        # the raw file is from BEFORE this cut began: the box would land on
        # the wrong picture, so 404 until the running ffmpeg writes one
        raw_path = self.tmp / "data" / "pinelink" / "frame_raw.jpg"
        raw_path.write_bytes(JPEG)
        import os
        old = time.time() - 3.0
        os.utime(raw_path, (old, old))
        self.state["crop"] = {"on": True, "box": {"x": 0.2, "y": 0.2, "w": 0.5, "h": 0.5},
                              "error": "", "at": time.time()}
        self.assertEqual(self.client.get("/api/pinelink/crop/frame.jpg").status_code, 404)

    def test_nothing_on_disk_is_404_not_500(self):
        self.assertEqual(self.client.get("/api/pinelink/crop/frame.jpg").status_code, 404)


if __name__ == "__main__":
    unittest.main()
