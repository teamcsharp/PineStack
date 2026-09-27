"""[listener-uploads] The tune page's plus: what the station takes, how it
names and stages it, how the courier carries it, and that the door and the
page are wired in app.py. Pure: no station."""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import listener_uploads as lu

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def box(brand):
    return b"\x00\x00\x00\x20ftyp" + brand + b"\x00\x00\x02\x00" + b"\x00" * 64


class Sniff(unittest.TestCase):
    def test_video_sound_and_pictures_are_named_by_what_they_are(self):
        riff = lambda form: b"RIFF\x24\x00\x00\x00" + form + b"\x00" * 64
        cases = {
            box(b"isom"): ("video", "mp4"), box(b"mp42"): ("video", "mp4"), box(b"qt  "): ("video", "mov"),
            box(b"M4A "): ("audio", "m4a"), box(b"3gp5"): ("video", "3gp"), box(b"heic"): ("image", "heic"),
            box(b"M4V "): ("video", "m4v"), box(b"avif"): ("image", "avif"),
            b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\x82\x84webm" + b"\x00" * 40: ("video", "webm"),
            b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\x82\x88matroska" + b"\x00" * 40: ("video", "mkv"),
            riff(b"WAVE"): ("audio", "wav"), riff(b"AVI "): ("video", "avi"), riff(b"WEBP"): ("image", "webp"),
            b"FORM\x00\x00\x00\x10AIFF" + b"\x00" * 32: ("audio", "aiff"),
            b"fLaC\x00\x00\x00\x22" + b"\x00" * 40: ("audio", "flac"),
            b"OggS\x00\x02" + b"\x00" * 22 + b"OpusHead" + b"\x00" * 30: ("audio", "opus"),
            b"OggS\x00\x02" + b"\x00" * 22 + b"\x01vorbis" + b"\x00" * 30: ("audio", "ogg"),
            b"ID3\x04\x00\x00\x00\x00\x00\x21" + b"\x00" * 40: ("audio", "mp3"),
            b"\xff\xfb\x90\x64" + b"\x00" * 60: ("audio", "mp3"),
            b"\xff\xf1\x50\x80" + b"\x00" * 60: ("audio", "aac"),
            b"#!AMR\n" + b"\x00" * 40: ("audio", "amr"),
            b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 40: ("image", "jpg"),
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 40: ("image", "png"),
            b"GIF89a" + b"\x00" * 40: ("image", "gif"),
        }
        for head, want in cases.items():
            self.assertEqual(lu.sniff(head), want, head[:16])

    def test_what_is_not_media_is_refused(self):
        for head in (b"<!doctype html><html>" + b" " * 40, b"<svg xmlns='http://www.w3.org/2000/svg'>" + b" " * 20,
                     b"PK\x03\x04" + b"\x00" * 40, b"MZ\x90\x00" + b"\x00" * 60, b"\x7fELF" + b"\x00" * 60,
                     b"#!/bin/sh\necho hi\n" + b" " * 40, b"%PDF-1.7\n" + b" " * 40, b"RIFF\x00\x00\x00\x00JUNK" + b"\x00" * 40,
                     b"\xff\xff\xff\xff" + b"\x00" * 40, b"short"):
            self.assertIsNone(lu.sniff(head), head[:12])


class Names(unittest.TestCase):
    def test_a_name_is_one_plain_file_with_the_sniffed_extension(self):
        name = lu.upload_name("Grandma Lou", "../../etc/passwd.mp3", "mp4", now=1790540000)
        self.assertRegex(name, r"^\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d_Grandma-Lou_passwd\.mp4$")
        self.assertTrue(lu.name_ok(name))
        name = lu.upload_name("", "Été à Montréal ☀.MOV", "mov", now=1790540000)
        self.assertTrue(name.endswith("_listener_Ete-a-Montreal.mov"), name)
        self.assertTrue(lu.upload_name("x", "", "wav").endswith("_x_upload.wav"))
        self.assertTrue(lu.upload_name("x", "C:\\Users\\me\\clip one.webm", "webm").endswith("_x_clip-one.webm"))
        for bad in ("../x.mp4", "a/b.mp4", ".hidden.mp4", "x.mp4.part", "", "a" * 300):
            self.assertFalse(lu.name_ok(bad), bad)


class Staging(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_file_is_staged_whole_and_never_overwrites_another(self):
        out = os.path.join(self.dir, "outbox")
        a = lu.stage(out, "one.mp4", b"x" * 10)
        b = lu.stage(out, "one.mp4", b"y" * 5)
        self.assertEqual(os.path.basename(a), "one.mp4")
        self.assertEqual(os.path.basename(b), "one-1.mp4")
        self.assertEqual(sorted(os.listdir(out)), ["one-1.mp4", "one.mp4"], "no .part is left behind")
        self.assertEqual(lu.outbox_bytes(out), 15)
        self.assertEqual(lu.receipt(os.path.join(self.dir, "receipts"), out, "one.mp4")["state"], "queued")
        self.assertEqual(lu.receipt(os.path.join(self.dir, "receipts"), out, "none.mp4")["state"], "unknown")
        self.assertEqual(lu.receipt(os.path.join(self.dir, "receipts"), out, "../x")["state"], "unknown")
        with self.assertRaises(ValueError):
            lu.stage(out, "../escape.mp4", b"z")

    def test_the_allowance(self):
        log = []
        self.assertEqual(lu.throttle(log, "k", 1000, 100.0), "")
        log.append((100.0, "k", 1000))
        self.assertIn("one at a time", lu.throttle(log, "k", 1000, 100.5))
        self.assertEqual(lu.throttle(log, "other", 1000, 100.5), "")
        log[:] = [(100.0 + i * 10, "k", 1000) for i in range(lu.PER_HOUR)]
        self.assertIn("uploads in an hour", lu.throttle(log, "k", 1000, 100.0 + lu.PER_HOUR * 10))
        log[:] = [(100.0, "k", lu.PER_HOUR_BYTES)]
        self.assertIn("MB in an hour", lu.throttle(log, "k", 10, 200.0))
        log[:] = [(100.0, "k", 1)]
        self.assertEqual(lu.throttle(log, "k", 1, 100.0 + 3601), "", "an hour later the allowance is back")


class Courier(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.c = _load("uploads_courier", "tools/uploads_courier.py")
        for name in ("OUTBOX", "RECEIPTS", "FAILED"):
            setattr(self.c, name, os.path.join(self.dir, name.lower()))
        self.c.DEST = os.path.join(self.dir, "share")
        os.makedirs(self.c.DEST)
        os.makedirs(self.c.OUTBOX)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def receipt(self, name):
        with open(os.path.join(self.c.RECEIPTS, name + ".json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_it_never_writes_into_an_unmounted_folder(self):
        lu.stage(self.c.OUTBOX, "a.mp4", b"hello")
        os.utime(os.path.join(self.c.OUTBOX, "a.mp4"), (1, 1))
        self.assertEqual(self.c.one_pass(), 0)
        self.assertEqual(os.listdir(self.c.DEST), [])
        self.assertEqual(self.receipt("a.mp4")["state"], "waiting")

    def test_it_carries_a_whole_file_and_leaves_a_receipt(self):
        lu.stage(self.c.OUTBOX, "a.mp4", b"hello")
        lu.stage(self.c.OUTBOX, "a.mp4", b"again")
        for n in os.listdir(self.c.OUTBOX):
            os.utime(os.path.join(self.c.OUTBOX, n), (1, 1))
        with open(os.path.join(self.c.DEST, "a.mp4"), "wb") as fh:
            fh.write(b"already there")
        with mock.patch("os.path.ismount", return_value=True):
            self.assertEqual(self.c.one_pass(), 2)
        self.assertEqual(sorted(os.listdir(self.c.DEST)), ["a-1.mp4", "a-2.mp4", "a.mp4"],
                         "a name already on the share is never overwritten")
        self.assertEqual(os.listdir(self.c.OUTBOX), [])
        got = self.receipt("a.mp4")
        self.assertEqual((got["state"], got["bytes"]), ("delivered", 5))
        self.assertTrue(got["dest"].startswith("\\\\10.89.1.125\\QuickSwap\\samples_grabbed\\user\\"))
        self.assertEqual(lu.receipt(self.c.RECEIPTS, self.c.OUTBOX, "a.mp4")["state"], "delivered")


class Wiring(unittest.TestCase):
    def test_the_door_and_the_page_are_in_app_py(self):
        mod = _load("listener_upload_patch", "tools/listener_upload_patch.py")
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)))
        self.assertIn('"/api/listener/upload"}', text)
        self.assertIn('"/api/listener/upload/status"}', text)
        page = text[text.index('RADIO_PAGE_HTML = r"""'):]
        page = page[:page.index('"""', 30)]
        for bit in ('id="upFab"', 'accept="video/*,audio/*,image/*"', "const UP_MAX = 20 * 1024 * 1024;",
                    "/api/listener/upload?name=", "body.car .up-fab"):
            self.assertIn(bit, page)


if __name__ == "__main__":
    unittest.main()
