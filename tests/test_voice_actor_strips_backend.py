"""[va-strips] The app.py block (tools/voice_actor_strips_patch.py), exercised
in isolation: the block the tool inserts is compiled into a namespace of
station stand-ins, so both routes and every helper run for real without the
269k-line app. voice_generate is a stand-in that RECORDS how it was called
(the one-engine proof) and writes a real 16-bit WAV (the envelope proof).

  python test_voice_actor_strips_backend.py            (desk)
  STRIPS_TOOL_SRC=<b64> python - < this file            (in the container)
"""
import asyncio
import base64
import hmac
import json
import math
import os
import random
import re
import sqlite3
import struct
import sys
import tempfile
import time
import types
import unittest
import wave
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import quote

if os.environ.get("STRIPS_TOOL_SRC"):
    tool = types.ModuleType("voice_actor_strips_patch")
    exec(base64.b64decode(os.environ["STRIPS_TOOL_SRC"]).decode("utf-8"), tool.__dict__)
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import voice_actor_strips_patch as tool   # noqa: E402

ANCHOR = tool._ROUTES_OLD
BLOCK = tool._ROUTES_NEW[: -len(ANCHOR)]
assert tool._ROUTES_NEW.endswith(ANCHOR)


class HTTPException(Exception):
    def __init__(self, status_code=500, detail=""):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class FakeApp:
    def __init__(self):
        self.routes = {}

    def _reg(self, method, path):
        def deco(fn):
            self.routes[(method, path)] = fn
            return fn
        return deco

    def get(self, path):
        return self._reg("GET", path)

    def post(self, path):
        return self._reg("POST", path)


class Req:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


def Header(default=None):
    return default


def sine_wav(path, amp=0.5, secs=0.5, rate=24000, width=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(width)
        w.setframerate(rate)
        n = int(rate * secs)
        if width == 2:
            frames = b"".join(struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * 440 * i / rate)))
                              for i in range(n))
        else:
            frames = bytes(128 for _ in range(n))
        w.writeframes(frames)


def run(coro):
    return asyncio.run(coro)


class Station:
    """The stand-ins, one fresh station per test."""

    def __init__(self, sfx_rows=40, comfy=("a.png", "b.jpg", "c.webp", "notes.txt", "d.mp4")):
        self.tmp = Path(tempfile.mkdtemp(prefix="vas_"))
        self.data = self.tmp / "data"
        self.data.mkdir()
        self.comfy = self.tmp / "comfy-output"
        self.comfy.mkdir()
        for n in comfy:
            (self.comfy / n).write_bytes(b"x")
        (self.comfy / "sub").mkdir()
        (self.comfy / "sub" / "deep.png").write_bytes(b"x")
        self.media = self.tmp / "voice_media"
        self.media.mkdir()
        self.voices_dir = self.tmp / "voices"
        self.voices = {}
        self.con = sqlite3.connect(":memory:", check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("CREATE TABLE clips (path TEXT, sid TEXT, name TEXT, video INTEGER, playable INTEGER, seconds REAL)")
        for i in range(sfx_rows):
            self.con.execute("INSERT INTO clips VALUES (?,?,?,?,?,?)",
                             ("sfx/f/%d.mp4" % i, "%016x" % (0xabc000 + i), "clip %d" % i,
                              1 if i % 3 == 0 else 0, 0 if i % 9 == 0 else 1, 2.0))
        self.engine = "xtts"
        self.ready = {"xtts": True, "f5": False}
        self.health_calls = []
        self.gen_calls = []
        self.auth = []
        self.wav_width = 2
        ns: dict[str, Any] = {}
        ns.update(dict(
            app=FakeApp(), Header=Header, HTTPException=HTTPException, Request=object, Any=Any,
            RLock=RLock, json=json, os=os, re=re, time=time, random=random, wave=wave, quote=quote,
            asyncio=asyncio, Path=Path,
            data_path=lambda *p: self.data.joinpath(*p),
            COMFY_OUTPUT=self.comfy, VOICE_MEDIA_DIR=self.media,
            sfx_db_reader=lambda: self.con,
            media_sign=lambda k: hmac.new(b"k", k.encode(), "sha1").hexdigest()[:16],
            read_voices=lambda: [dict(v) for v in self.voices.values()],
            VOICE_ID_SHAPE=re.compile(r"^vl_[a-f0-9]{8}\Z"),
            require_read_auth=lambda a: self.auth.append(("read", a)),
            require_auth=lambda a: self.auth.append(("write", a)),
            _voice_actor_body_dict=self._body,
            voice_meta=lambda vid: dict(self.voices[vid]) if vid in self.voices else None,
            host_clone_engine=lambda: self.engine,
            xtts_health=self._health("xtts"), f5_health=self._health("f5"),
            voice_ref_path=self._ref, voice_ref_for=self._ref_for,
            voice_generate=self._generate,
        ))
        exec(compile(BLOCK, "va_strips_block", "exec"), ns)
        self.ns = ns
        self.routes = ns["app"].routes

    @staticmethod
    def _body(payload):
        if not isinstance(payload, dict):
            raise HTTPException(400, "expected a JSON object")
        return payload

    def _health(self, eng):
        async def h(force=False):
            self.health_calls.append(eng)
            return {"ready": self.ready[eng]}
        return h

    def _ref(self, vid):
        v = self.voices.get(vid)
        return Path("/voices/%s/reference.wav" % vid) if v and v.get("_ref", True) else None

    def _ref_for(self, vid, engine):
        p = self._ref(vid)
        return p.with_name("reference_f5.wav") if p is not None and engine == "f5" else p

    async def _generate(self, *args, **kw):
        self.gen_calls.append((args, kw))
        key = "take%d.wav" % len(self.gen_calls)
        sine_wav(self.media / key, amp=0.5, secs=0.5, width=self.wav_width)
        return {"path": "/media/" + key, "sig": "S", "ms": 1234, "engine": args[2], "seconds": 0.5}

    def voice(self, vid, name, engine="xtts", created=0, twin="", ref=True):
        v = {"id": vid, "name": name, "engine": engine, "created": created, "_ref": ref}
        if twin:
            v["provenance"] = {"extract": {"twin_voice": twin}}
        self.voices[vid] = v
        return v

    def faces(self, ids):
        return run(self.routes[("GET", "/api/voice-actor/faces")](ids=ids, authorization="K"))

    def sample(self, body):
        return run(self.routes[("POST", "/api/voice-actor/sample")](request=Req(body), authorization="K"))


class StripsBackend(unittest.TestCase):

    def test_the_block_stays_off_the_render_roads(self):
        self.assertNotIn("performance_vector", BLOCK)
        self.assertNotIn('fx["perf"]', BLOCK)
        self.assertNotIn("engine-switch", BLOCK.replace("never wakes the other", ""))
        self.assertIn('@app.get("/api/voice-actor/faces")', BLOCK)
        self.assertIn('@app.post("/api/voice-actor/sample")', BLOCK)

    def test_faces_are_drawn_once_and_kept_on_disk(self):
        s = Station()
        for i in range(8):
            s.voice("vl_%08x" % i, "Voice %d" % i)
        ids = ",".join("vl_%08x" % i for i in range(8))
        first = s.faces(ids)["faces"]
        self.assertEqual(len(first), 8)
        for vid, f in first.items():
            self.assertIn(f["kind"], ("sfx", "comfy"))
            if f["kind"] == "sfx":
                self.assertRegex(f["url"], r"^/api/sfx/poster/[a-f0-9]{16}\?t=[a-f0-9]{16}$")
            else:
                self.assertRegex(f["url"], r"^/api/generations/image/(a\.png|b\.jpg|c\.webp)\?t=[a-f0-9]{16}&w=320$")
        again = s.faces(ids)["faces"]
        self.assertEqual(first, again, "a profile wears the same face on every call")
        kept = json.loads((s.data / "voice_actor_faces.json").read_text())
        self.assertEqual(set(kept), set(first))
        # a fresh process (memo gone) reads the same faces from the store
        s2 = Station()
        s2.voices = s.voices
        s2.data = s.data
        s2.ns["VOICE_ACTOR_FACES_PATH"] = s.data / "voice_actor_faces.json"
        self.assertEqual(s2.faces(ids)["faces"], first)
        self.assertEqual(s.auth[0], ("read", "K"))

    def test_both_pools_are_used_over_many_profiles(self):
        s = Station()
        for i in range(40):
            s.voice("vl_%08x" % i, "V%d" % i)
        got = s.faces(",".join("vl_%08x" % i for i in range(16)))["faces"]
        kinds = {f["kind"] for f in got.values()}
        self.assertEqual(kinds, {"sfx", "comfy"})

    def test_sfx_faces_are_video_and_playable_only(self):
        s = Station(comfy=())
        s.voice("vl_00000001", "A")
        for _ in range(12):
            s.ns["VOICE_ACTOR_FACES_PATH"].unlink(missing_ok=True)
            f = s.faces("vl_00000001")["faces"]["vl_00000001"]
            sid = re.search(r"poster/([a-f0-9]{16})", f["url"]).group(1)
            row = s.con.execute("SELECT video, playable FROM clips WHERE sid = ?", (sid,)).fetchone()
            self.assertEqual((row["video"], row["playable"]), (1, 1))

    def test_one_empty_pool_falls_to_the_other_and_none_is_honest(self):
        s = Station(sfx_rows=0)
        s.voice("vl_00000001", "A")
        self.assertEqual(s.faces("vl_00000001")["faces"]["vl_00000001"]["kind"], "comfy")
        s = Station(comfy=())
        s.voice("vl_00000001", "A")
        self.assertEqual(s.faces("vl_00000001")["faces"]["vl_00000001"]["kind"], "sfx")
        s = Station(sfx_rows=0, comfy=())
        s.voice("vl_00000001", "A")
        self.assertIsNone(s.faces("vl_00000001")["faces"]["vl_00000001"])
        self.assertFalse((s.data / "voice_actor_faces.json").exists(), "nothing drawn, nothing kept")

    def test_a_render_that_left_the_mount_is_redrawn(self):
        s = Station(sfx_rows=0, comfy=("only.png", "next.png"))
        s.voice("vl_00000001", "A")
        f = s.faces("vl_00000001")["faces"]["vl_00000001"]
        gone = re.search(r"image/([^?]+)", f["url"]).group(1)
        (s.comfy / gone).unlink()
        s.ns["VOICE_ACTOR_FACES_MEMO"]["at"] = 0.0
        f2 = s.faces("vl_00000001")["faces"]["vl_00000001"]
        self.assertNotIn(gone, f2["url"])

    def test_only_library_voices_and_well_formed_ids(self):
        s = Station()
        s.voice("vl_00000001", "A")
        got = s.faces("vl_00000001,vl_deadbeef,../etc,xtts:vl_00000001")["faces"]
        self.assertEqual(set(got), {"vl_00000001", "vl_deadbeef"})
        self.assertIsNone(got["vl_deadbeef"])
        with self.assertRaises(HTTPException) as e:
            s.faces("../x")
        self.assertEqual(e.exception.status_code, 400)
        many = ",".join("vl_%08x" % i for i in range(30))
        self.assertEqual(len(s.faces(many)["faces"]), 16)

    def test_sample_renders_on_the_active_engine_only(self):
        s = Station()
        s.voice("vl_00000001", "Ben  Spapi", engine="f5")
        ans = s.sample({"voice_id": "vl_00000001"})
        self.assertEqual(len(s.gen_calls), 1)
        args, kw = s.gen_calls[0]
        self.assertEqual(args[1:], ("vl_00000001", "xtts"), "engine passed explicitly: the active one")
        self.assertEqual(kw, {}, "no fx, no perf, no strip")
        self.assertIn("Ben Spapi", args[0])
        self.assertEqual(s.health_calls, ["xtts"], "only the active engine's health is asked")
        self.assertEqual((ans["engine"], ans["active"], ans["aired"]), ("xtts", "xtts", False))
        self.assertEqual(ans["url"], "/media/take1.wav?t=S")
        self.assertEqual(ans["reference"], "reference.wav")
        self.assertEqual(s.auth[-1], ("write", "K"))

    def test_the_twin_cut_for_the_active_engine_is_used(self):
        s = Station()
        s.engine = "f5"
        s.ready["f5"] = True
        s.voice("vl_0000000a", "Ann", engine="xtts", twin="vl_0000000b")
        s.voice("vl_0000000b", "Ann (F5)", engine="f5", twin="vl_0000000a")
        ans = s.sample({"voice_id": "vl_0000000a"})
        self.assertEqual(s.gen_calls[0][0][1:], ("vl_0000000b", "f5"))
        self.assertTrue(ans["twin_used"])
        self.assertEqual((ans["profile"], ans["voice_id"], ans["reference"]), ("vl_0000000a", "vl_0000000b", "reference_f5.wav"))
        self.assertIn("Ann", s.gen_calls[0][0][0])

    def test_a_twin_for_the_other_engine_or_without_a_reference_is_not_used(self):
        s = Station()
        s.voice("vl_0000000a", "Ann", engine="f5", twin="vl_0000000b")
        s.voice("vl_0000000b", "Ann 2", engine="f5")
        self.assertFalse(s.sample({"voice_id": "vl_0000000a"})["twin_used"])
        s.voice("vl_0000000b", "Ann 2", engine="xtts", ref=False)
        ans = s.sample({"voice_id": "vl_0000000a"})
        self.assertFalse(ans["twin_used"])
        self.assertEqual(s.gen_calls[-1][0][1:], ("vl_0000000a", "xtts"))

    def test_an_engine_that_is_not_ready_is_a_409_and_nothing_renders(self):
        s = Station()
        s.voice("vl_00000001", "A")
        s.ready["xtts"] = False
        s.ready["f5"] = True                 # the OTHER engine being up changes nothing
        with self.assertRaises(HTTPException) as e:
            s.sample({"voice_id": "vl_00000001"})
        self.assertEqual(e.exception.status_code, 409)
        self.assertIn("never wakes the other", e.exception.detail)
        self.assertEqual(s.gen_calls, [])
        self.assertEqual(s.health_calls, ["xtts"])

    def test_bad_asks_are_named(self):
        s = Station()
        s.voice("vl_00000001", "A", ref=False)
        for body, code in (({"voice_id": "vl_99999999"}, 404), ({"voice_id": "../x"}, 404),
                           ({}, 404), ({"voice_id": "vl_00000001"}, 400)):
            with self.assertRaises(HTTPException) as e:
                s.sample(body)
            self.assertEqual(e.exception.status_code, code, body)
        with self.assertRaises(HTTPException):
            s.sample(["not", "a", "dict"])
        self.assertEqual(s.gen_calls, [])

    def test_the_envelope_is_measured_from_the_take(self):
        s = Station()
        s.voice("vl_00000001", "A")
        env = s.sample({"voice_id": "vl_00000001"})["envelope"]
        self.assertEqual(env["step_s"], 0.02)
        self.assertEqual(len(env["peak"]), 25)                     # 0.5 s / 20 ms
        self.assertTrue(all(abs(p - 0.5) < 0.01 for p in env["peak"]), env["peak"][:4])
        self.assertTrue(all(abs(r - 0.5 / math.sqrt(2)) < 0.01 for r in env["rms"]), env["rms"][:4])

    def test_a_take_that_is_not_16_bit_has_no_reading(self):
        s = Station()
        s.voice("vl_00000001", "A")
        s.wav_width = 1
        self.assertIsNone(s.sample({"voice_id": "vl_00000001"})["envelope"])

    def test_the_tool_is_idempotent_on_a_minimal_text(self):
        text = "x = 1\n\n" + ANCHOR + "async def f():\n    pass\n"
        applied, missing = tool.check(text)
        self.assertEqual((applied, missing), (0, []))
        done = text.replace(ANCHOR, tool._ROUTES_NEW)
        self.assertEqual(tool.check(done), (1, []))
        self.assertEqual(tool.check(done + ANCHOR)[0], 0)          # a second anchor is not "applied"


if __name__ == "__main__":
    unittest.main(verbosity=2)
