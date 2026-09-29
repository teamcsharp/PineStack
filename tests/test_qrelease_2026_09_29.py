"""[qrelease] + [orch-s3b]: the SFX quarantine's release (per clip, per folder,
re-checked with a real ffmpeg decode, logged, survives a restart) and the
orchestrator desk's answers to the operator's five decisions.

    docker exec -w /tmp/wX -e PYTHONPATH=tests:. spark-agent nice -n 10 \
        python3 -m unittest tests.test_qrelease_2026_09_29

Never imports app.py: the release helpers are exec'd from the edit tool, and
_sfx_quarantine_load is lifted from this tree's app.py (patched) when present.
"""
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from threading import RLock, Thread
from typing import Any

HERE = Path(__file__).resolve().parent.parent
UNDECODABLE_RE = re.compile(
    r"invalid data|error splitting|error while decoding|error code|corrupt|"
    r"could not find codec|decoding error|not supported|moov atom", re.IGNORECASE)


def load_tool(name):
    p = HERE / "tools" / name
    if not p.exists():
        raise unittest.SkipTest("%s is not here" % name)
    sys.path.insert(0, str(p.parent))
    spec = importlib.util.spec_from_file_location(name[:-3], p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def have_ffmpeg():
    try:
        import imageio_ffmpeg
        return bool(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # noqa: BLE001
        return bool(shutil.which("ffmpeg"))


def load_fn_from_app():
    """The patched _sfx_quarantine_load from this tree's app.py, or None."""
    app = HERE / "app.py"
    if not app.exists():
        return None
    s = app.read_text(encoding="utf-8")
    if "[qrelease]" not in s:
        return None
    a = s.index("def _sfx_quarantine_load() -> None:")
    b = s.index("\ndef sfx_quarantined(", a)
    return s[a:b]


class Station:
    """A namespace with the release helpers exec'd into it."""

    def __init__(self, root: Path):
        tool = load_tool("qrelease_app_patch.py")
        self.root = root
        (root / "data").mkdir()
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("CREATE TABLE clips (sid TEXT, path TEXT, playable INTEGER)")
        self.ns: dict[str, Any] = {
            "os": os, "json": json, "time": time, "Path": Path, "shutil": shutil, "subprocess": subprocess,
            "Any": Any, "RLock": RLock, "Thread": Thread, "re": re,
            "data_path": lambda *p: root.joinpath("data", *p),
            "_SFX_QUARANTINE_LOCK": RLock(), "_SFX_QUARANTINED": set(), "_SFX_GONE_FOLDERS": set(),
            "_SFX_QUARANTINE_LOADED": [True], "_SFX_RECEIPT_STRIKES": {}, "_SFX_UNDECODABLE_RE": UNDECODABLE_RE,
            "_sfx_quarantine_path": lambda: root / "data" / "sfx_quarantine.jsonl",
            "_sfx_quarantine_load": lambda: None,
            "sfx_db": lambda: self.db, "_SFX_DB_LOCK": RLock(), "sfx_bans": lambda: {"banned01banned01"},
            "sfx_glue_book": lambda: {"glued": [{"part_ids": ["glued001glued001"]}]},
            "sfx_seconds_held": lambda p: 1.0, "sfx_floor_seconds": lambda: 0.1, "sfx_cap_seconds": lambda: 60.0,
            "sfx_is_video": lambda p: str(p).endswith(".mp4"), "sfx_is_silent": lambda p: False,
            "sfx_by_id": lambda sid: None, "pipeline_log": lambda *a, **k: None,
        }
        exec(tool.HELPERS, self.ns)
        src = load_fn_from_app()
        self.load_src = src

    def quarantine(self, sid: str, path: Path) -> None:
        self.ns["_SFX_QUARANTINED"].add(sid)
        self.db.execute("INSERT INTO clips VALUES (?,?,0)", (sid, str(path)))
        with open(self.ns["_sfx_quarantine_path"](), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": time.time(), "sid": sid, "path": str(path), "why": "test"}) + "\n")

    def playable(self, sid: str) -> int:
        return self.db.execute("SELECT playable FROM clips WHERE sid=?", (sid,)).fetchone()[0]


def good_wav(path: Path) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"".join(struct.pack("<h", (i * 97) % 3000) for i in range(4000)))
    return path


class Release(unittest.TestCase):
    def setUp(self):
        if not have_ffmpeg():
            raise unittest.SkipTest("no ffmpeg here")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = Station(self.root)
        self.lib = self.root / "lib"
        self.lib.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_good_clip_is_released_and_stays_released_after_a_restart(self):
        p = good_wav(self.lib / "good.wav")
        self.st.quarantine("good0000good0000", p)
        got = self.st.ns["sfx_quarantine_release"](sid="good0000good0000", by="test", why="it was fixed")
        self.assertTrue(got["ok"], got)
        self.assertNotIn("good0000good0000", self.st.ns["_SFX_QUARANTINED"])
        self.assertEqual(self.st.playable("good0000good0000"), 1)
        log = [json.loads(x) for x in self.st.ns["SFX_RELEASE_LOG"].read_text().splitlines()]
        self.assertEqual((log[-1]["ok"], log[-1]["by"], log[-1]["why"]), (True, "test", "it was fixed"))
        if self.st.load_src is None:
            self.skipTest("this tree's app.py does not carry [qrelease]")
        ns = dict(self.st.ns, _SFX_QUARANTINED=set(), _SFX_GONE_FOLDERS=set(), _SFX_QUARANTINE_LOADED=[False])
        exec(self.st.load_src, ns)
        ns["_sfx_quarantine_load"]()
        self.assertNotIn("good0000good0000", ns["_SFX_QUARANTINED"])       # the restart keeps the answer

    def test_an_undecodable_clip_stays_with_its_reason(self):
        bad = self.lib / "bad.mp4"
        bad.write_bytes(os.urandom(4096))
        self.st.quarantine("bad00000bad00000", bad)
        got = self.st.ns["sfx_quarantine_release"](sid="bad00000bad00000")
        self.assertFalse(got["ok"])
        self.assertIn("stays quarantined", got["say"])
        self.assertTrue(got["results"][0]["reason"].startswith("ffmpeg"))
        self.assertIn("bad00000bad00000", self.st.ns["_SFX_QUARANTINED"])
        listing = self.st.ns["sfx_quarantine_list"]()
        self.assertTrue(listing["clips"][0]["last_check"].startswith("ffmpeg"))

    def test_a_missing_file_and_an_unknown_clip(self):
        self.st.quarantine("gone0000gone0000", self.lib / "nope.wav")
        got = self.st.ns["sfx_quarantine_release"](sid="gone0000gone0000")
        self.assertEqual(got["results"][0]["reason"], "the file is not on the share")
        self.assertFalse(self.st.ns["sfx_quarantine_release"](sid="notheld0notheld0")["ok"])
        self.assertFalse(self.st.ns["sfx_quarantine_release"]()["ok"])

    def test_banned_and_glued_are_released_but_not_made_playable(self):
        for sid in ("banned01banned01", "glued001glued001"):
            self.st.quarantine(sid, good_wav(self.lib / (sid + ".wav")))
            self.assertTrue(self.st.ns["sfx_quarantine_release"](sid=sid)["ok"])
            self.assertEqual(self.st.playable(sid), 0, sid)

    def test_a_folder_back_on_the_share(self):
        folder = self.lib / "restored"
        self.st.ns["_SFX_GONE_FOLDERS"].add(str(folder))
        self.assertFalse(self.st.ns["sfx_quarantine_release"](folder=str(folder))["ok"])     # not back yet
        folder.mkdir()
        self.st.quarantine("fold0001fold0001", good_wav(folder / "a.wav"))
        bad = folder / "b.mp4"
        bad.write_bytes(os.urandom(2048))
        self.st.quarantine("fold0002fold0002", bad)
        self.st.db.execute("INSERT INTO clips VALUES (?,?,0)", ("fold0003fold0003", str(good_wav(folder / "c.wav"))))
        got = self.st.ns["sfx_quarantine_release"](folder=str(folder), by="test")
        self.assertTrue(got["ok"] and got["started"], got)
        for _ in range(200):
            if not self.st.ns["_SFX_RELEASE_JOB"]["running"]:
                break
            time.sleep(0.1)
        self.assertNotIn(str(folder), self.st.ns["_SFX_GONE_FOLDERS"])
        self.assertEqual(self.st.ns["_SFX_QUARANTINED"], {"fold0002fold0002"})
        self.assertEqual((self.st.playable("fold0001fold0001"), self.st.playable("fold0003fold0003")), (1, 1))
        self.assertIn("1 stay quarantined", self.st.ns["_SFX_RELEASE_JOB"]["say"])


class Desk(unittest.TestCase):
    def setUp(self):
        import orchestrator_s3 as os3
        if not hasattr(os3, "EXCLUSIVE_RECEIVERS"):
            raise unittest.SkipTest("orchestrator_s3.py does not carry [orch-s3b]")
        self.os3 = os3
        self.tmp = tempfile.TemporaryDirectory()
        self.ns = load_tool("orch_s3_sandbox.py").build(Path(self.tmp.name))
        self.desk = self.ns["_desk"]

    def tearDown(self):
        self.ns["_ledger"].close()
        self.tmp.cleanup()

    def test_web_beside_the_pinetab_is_normal(self):
        rx = lambda *ids: {"receivers": [{"id": i, "sounding": True} for i in ids]}  # noqa: E731
        self.assertEqual(self.os3.sense_receivers(rx("pinetab", "web"), True), [])
        self.assertEqual(self.os3.sense_receivers(rx("pinetab", "car", "nabu"), True), [])
        for pair in (("pinetab", "desktop"), ("pinetab", "box"), ("desktop", "box")):
            self.assertEqual(self.os3.sense_receivers(rx(*pair), True)[0]["class"], "overlap", pair)

    def test_page_join_is_not_dead_air(self):
        now = time.time()
        rows = [{"until": now - 5, "seconds": 200, "cause": "page join"}]
        self.assertEqual(self.os3.sense_gaps(rows, now), [])
        rows.append({"until": now - 5, "seconds": 40, "cause": "round turnover"})
        got = self.os3.sense_gaps(rows, now)[0]
        self.assertNotIn("page join", got["evidence"]["by_cause"])

    def test_a_folder_back_is_proposed_and_only_the_operator_releases(self):
        back = Path(self.tmp.name) / "back"
        back.mkdir()
        self.ns["_SFX_GONE_FOLDERS"].add(str(back))
        asked = []
        self.ns["sfx_quarantine_release"] = lambda sid, folder, by, why: asked.append((sid, folder, by)) or {
            "ok": True, "started": True, "say": "checking 3 clip(s)"}
        v = self.desk.survey()
        f = next(x for x in v["findings"] if x["class"] == "undecodable" and "back on the share" in x["title"])
        pid = f["proposals"][0]
        p = self.desk.find_proposal(pid)
        self.assertEqual((p["door"], p["needs_operator"], p["station_may"]), ("release", True, False))
        self.assertIn("waits for the operator", self.desk.verb("s3fix", pid, alone=True))
        self.assertEqual(asked, [])
        got = self.desk.confirm(pid, "operator")
        self.assertTrue(got["ok"], got)
        self.assertEqual(asked[0][1], str(back))
        self.assertFalse(self.desk.undo(pid)["ok"])

    def test_a_failed_check_keeps_the_clip_and_says_why(self):
        self.ns["sfx_quarantine_release"] = lambda sid, folder, by, why: {
            "ok": False, "say": "x.mp4 stays quarantined: ffmpeg: moov atom not found"}
        p = self.desk.propose_release(sid="abcdabcdabcdabcd")
        got = self.desk.confirm(p["id"], "operator")
        self.assertFalse(got["ok"])
        self.assertIn("moov atom", got["say"])
        self.assertEqual(self.desk.find_proposal(p["id"])["state"], "kept")


class Tools(unittest.TestCase):
    def test_contracts(self):
        for name in ("qrelease_app_patch.py", "qrelease_filemgr_patch.py", "orch_s3_wave2_patch.py"):
            tool = load_tool(name)
            for e in tool.EDITS:                     # an insert that inserts nothing is a lost edit
                self.assertTrue(e.text if e.replace is None else e.replace, "%s: %s" % (name, e.name))
            with tempfile.TemporaryDirectory() as t:
                p = Path(t) / "target"
                p.write_bytes(b"nothing here\n")
                self.assertEqual(tool.run(tool.EDITS, ["--check", str(p)], marker=tool.MARKER), 1, name)
                body = "head\n" + "".join("x\n" + e.anchor + "\ny\n" for e in tool.EDITS) + "tail\n"
                p.write_bytes(body.replace("\n", "\r\n").encode())
                self.assertEqual(tool.run(tool.EDITS, ["--check", str(p)], marker=tool.MARKER), 0, name)
                self.assertEqual(tool.run(tool.EDITS, ["--apply", str(p)], marker=tool.MARKER), 0, name)
                out = p.read_bytes().decode()
                self.assertIn(tool.MARKER, out, name)
                self.assertNotIn("\n", out.replace("\r\n", ""), name)
                self.assertEqual(tool.run(tool.EDITS, ["--apply", str(p)], marker=tool.MARKER), 2, name)
                self.assertEqual(tool.run(tool.EDITS, ["--check", str(p)], marker=tool.MARKER), 2, name)

    def test_this_tree(self):
        for name, target in (("qrelease_app_patch.py", "app.py"), ("orch_s3_wave2_patch.py", "orchestrator_s3.py"),
                             ("qrelease_filemgr_patch.py", "desktop/renderer/filemgr.js"),
                             ("qrelease_filemgr_patch.py", "app/src/main/assets/pine-views/filemgr.js")):
            p = HERE / target
            if not p.exists():
                continue
            tool = load_tool(name)
            self.assertIn(tool.run(tool.EDITS, ["--check", str(p)], marker=tool.MARKER), (0, 2), target)


if __name__ == "__main__":
    unittest.main()
