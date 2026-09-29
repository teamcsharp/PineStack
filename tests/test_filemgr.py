"""[filemgr] the disk on the base bar: plan math, hot clear, cold job, snapshot
round-trip, refusal while live, auth. Every test runs on a temp data dir."""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

import filemgr


def _groups(tmp: Path) -> Path:
    man = {"groups": [
        {"id": "tts-cache", "label": "Voice cache", "description": "rendered speech",
         "tier": "cache", "paths": ["tts_cache/**  (contents; folder kept)", "nope.json (if present)"],
         "empty": [], "mode": "hot",
         "reason": "read fresh"},
        {"id": "ring", "label": "Chat ring", "description": "the feed", "tier": "lines",
         "paths": ["ring.json"], "empty": [{"path": "ring.json", "empty": []}],
         "mode": "hot", "reason": "owned by the ring lock"},
        {"id": "airlog", "label": "Air log", "description": "what aired", "tier": "history",
         "paths": ["air_log.jsonl", "logs/*.log"], "empty": [], "mode": "cold",
         "reason": "held open by the keeper"},
        {"id": "settings", "label": "Settings", "description": "every knob",
         "tier": "settings", "paths": ["settings.json"],
         "empty": [{"path": "settings.json", "empty": {}}], "mode": "cold",
         "reason": "loaded at import"},
        {"id": "sneaky", "label": "Sneaky", "description": "must never reach KEEP",
         "tier": "cache", "paths": ["**/*.bin", "../outside", "filemgr/*"], "empty": [],
         "mode": "hot", "reason": ""},
        # the clean-slate builder's own key names: clear / clear_why / empty_forms
        {"id": "shelves", "label": "Shelves", "description": "banked rounds", "tier": "lines",
         "paths": ["pantry.json"], "empty_forms": [{"path": "pantry.json", "form": {}}],
         "clear": "hot", "clear_why": "the purge road drops the memory",
         "hot_road": "POST /api/cache/purge {\"areas\": [\"pantry\"]}", "in_this_wipe": False},
        {"id": "prefs", "label": "Prefs", "description": "", "tier": "settings",
         "paths": ["settings.json"], "empty": [{"path": "settings.json", "empty": {}}],
         "mode": "hot", "reason": "save_settings owns it"},
        {"id": "creds", "label": "State + credentials", "description": "", "tier": "configs",
         "paths": [], "empty": [{"path": "shares.json", "empty": "absent"}], "mode": "cold",
         "reason": ""},
        {"id": "kept", "label": "Kept", "description": "", "tier": "keep",
         "paths": ["music"], "empty": [], "mode": "cold", "reason": ""},
    ]}
    p = tmp / "groups.json"
    p.write_text(json.dumps(man))
    return p


def _seed(data: Path) -> None:
    (data / "tts_cache" / "sub").mkdir(parents=True)
    (data / "tts_cache" / "a.wav").write_bytes(b"x" * 100)
    (data / "tts_cache" / "sub" / "b.wav").write_bytes(b"y" * 50)
    (data / "ring.json").write_text(json.dumps([{"id": 1}, {"id": 2}]))
    (data / "air_log.jsonl").write_text('{"a":1}\n' * 10)          # 80 bytes
    (data / "logs").mkdir()
    (data / "logs" / "one.log").write_text("z" * 20)
    (data / "settings.json").write_text(json.dumps({"dj": {"voice": "x"}}))
    (data / "speakbox").mkdir()
    (data / "speakbox" / "keep.bin").write_bytes(b"k" * 7)
    (data / "filemgr").mkdir()
    (data / "filemgr" / "keep.bin").write_bytes(b"k" * 7)
    (data / "blob.bin").write_bytes(b"b" * 9)
    (data / "pantry.json").write_text(json.dumps({"k": 1}))
    (data / "shares.json").write_text(json.dumps({"link": "secret"}))


class _PL:
    phase = "idle"


class _PineLive:
    def __init__(self) -> None:
        self.PL = _PL()


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.data = self.tmp / "data"
        self.data.mkdir()
        _seed(self.data)
        self.ring = [{"id": 1}, {"id": 2}]
        self.ring_lock = threading.RLock()
        self.roads = []
        self.saved = []
        self.ns = {"pinelive": _PineLive(), "_RING": self.ring, "_RING_LOCK": self.ring_lock,
                   "_filemgr_road": lambda m, p, b: self.roads.append((m, p, b)) or {"ok": True},
                   "save_settings": self._save_settings,
                   "DEFAULT_SETTINGS": {"prompts": [{"name": "default"}]}}
        self._owners = dict(filemgr.OWNERS)
        filemgr.OWNERS.clear()
        filemgr.OWNERS.update({
            "tts_cache/**": {"fresh": "1"},
            "ring.json": {"lock": "_RING_LOCK", "memory": "_RING"},
            "settings.json": {"call": "save_settings", "arg": "DEFAULT_SETTINGS"},
        })
        self.fm = filemgr.FileManager(self.data, _groups(self.tmp), self.ns)
        self.restarts = []
        self.fm.restart = lambda: self.restarts.append(time.time())
        self.fm.live_probe = lambda: ("PineLive is live" if self.ns["pinelive"].PL.phase == "live" else "")

    def _save_settings(self, value):
        self.saved.append(value)
        (self.data / "settings.json").write_text(json.dumps({"normalized": True}))
        return value

    def tearDown(self) -> None:
        filemgr.OWNERS.clear()
        filemgr.OWNERS.update(self._owners)
        self._td.cleanup()

    def wait(self, jid: str, states=("done", "failed", "restarting")) -> dict:
        for _ in range(200):
            job = next(r for r in self.fm.jobs()["jobs"] if r["id"] == jid)
            if job["state"] in states:
                return job
            time.sleep(0.05)
        self.fail("job %s never settled" % jid)


class TestManifestAndPlan(Base):
    def test_manifest_refuses_escapes_and_keeps_unknown_tiers(self):
        man = self.fm.manifest()
        ids = [g["id"] for g in man["groups"]]
        self.assertEqual(ids, ["tts-cache", "sneaky", "ring", "shelves", "airlog", "settings", "prefs", "creds"])
        shelves = next(g for g in man["groups"] if g["id"] == "shelves")
        self.assertEqual((shelves["mode"], shelves["suggested"]), ("hot", False))
        self.assertEqual(shelves["empty"], [{"path": "pantry.json", "empty": {}}])
        sneaky = next(g for g in man["groups"] if g["id"] == "sneaky")
        self.assertEqual(sneaky["paths"], ["**/*.bin"])
        self.assertTrue(any("sneaky" in p for p in man["problems"]))
        self.assertEqual([k["id"] for k in man["kept"]], ["kept"])

    def test_glob_never_reaches_keep_paths(self):
        files, _ = filemgr.expand(self.data, {"paths": ["**/*.bin"]})
        self.assertEqual(sorted(files), ["blob.bin"])

    def test_plan_math(self):
        p = self.fm.plan(["tts-cache", "airlog", "nope"], snapshot=True)
        self.assertEqual(p["files"], 2 + 2)
        self.assertEqual(p["bytes"], 150 + 80 + 20)
        self.assertEqual(p["hot"], ["tts-cache"])
        self.assertEqual(p["cold"], ["airlog"])
        self.assertTrue(p["restart"])
        self.assertEqual(p["unknown"], ["nope"])
        self.assertEqual(p["typed_word"], "")
        self.assertFalse(p["destructive"])
        self.assertTrue(p["snapshot"]["on"])
        self.assertGreaterEqual(p["snapshot"]["bytes"], 250)
        self.assertTrue(p["snapshot"]["name"].startswith("pinebox-snapshot-"))
        self.ns["export_desk_dir"] = lambda: "\\\\host\\QuickSwap\\PineBoxRecordings"
        self.assertTrue(self.fm.plan(["tts-cache"])["snapshot"]["quickswap_dest"])
        secret = self.fm.plan(["tts-cache", "creds"])["snapshot"]
        self.assertEqual(secret["quickswap_dest"], "")          # credentials never ride the courier
        self.assertIn("credentials", secret["kept_local_why"])
        s = self.fm.plan(["settings"], snapshot=False)
        self.assertEqual(s["typed_word"], "RESET")
        self.assertTrue(s["destructive"])
        self.assertFalse(s["snapshot"]["on"])

    def test_unowned_hot_is_demoted_to_the_restart(self):
        filemgr.OWNERS["ring.json"] = {"lock": "_NO_SUCH_LOCK", "memory": "_NO_SUCH_RING"}
        p = self.fm.plan(["ring"])
        self.assertEqual(p["cold"], ["ring"])
        self.assertEqual(p["groups"][0]["unowned"], ["ring.json"])

    def test_sizes_single_flight_memo(self):
        a = self.fm.sizes()
        b = self.fm.sizes()
        self.assertIs(a, b)
        row = next(g for g in a["groups"] if g["id"] == "tts-cache")
        self.assertEqual((row["files"], row["bytes"]), (2, 150))
        self.assertEqual(a["typed_word"], "RESET")


class TestClear(Base):
    def test_hot_clear_through_the_owner(self):
        got = self.fm.start(["tts-cache", "ring"], snapshot=False)
        self.assertTrue(got["ok"], got)
        job = self.wait(got["job"]["id"])
        self.assertEqual(job["state"], "done")
        self.assertEqual(self.ring, [])                       # memory reset in place
        self.assertEqual(json.loads((self.data / "ring.json").read_text()), [])
        self.assertTrue((self.data / "tts_cache").is_dir())   # directory kept
        self.assertEqual([x for x in (self.data / "tts_cache").rglob("*") if x.is_file()], [])
        self.assertTrue((self.data / "tts_cache" / "sub").is_dir())   # the skeleton stays
        self.assertEqual(self.restarts, [])
        self.assertTrue((self.data / "speakbox" / "keep.bin").exists())
        audit = (self.data / "filemgr" / "audit.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(audit[-1])["event"], "clear")

    def test_hot_road_and_call_owner(self):
        got = self.fm.start(["shelves", "prefs"], snapshot=False, typed="RESET")
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["plan"]["hot"], ["shelves", "prefs"])
        job = self.wait(got["job"]["id"])
        self.assertEqual(job["state"], "done", job)
        self.assertEqual(self.roads, [("POST", "/api/cache/purge", {"areas": ["pantry"]})])
        self.assertEqual(json.loads((self.data / "pantry.json").read_text()), {})
        self.assertEqual(self.saved, [{"prompts": [{"name": "default"}]}])   # the owner, with ITS defaults
        self.assertEqual(json.loads((self.data / "settings.json").read_text()), {"normalized": True})

    def test_cold_job_written_then_run_at_boot(self):
        got = self.fm.start(["airlog", "settings"], snapshot=False, typed="reset")
        self.assertTrue(got["ok"], got)
        job = self.wait(got["job"]["id"])
        self.assertEqual(job["state"], "restarting")
        self.assertEqual(len(self.restarts), 1)
        pending = json.loads((self.data / "filemgr" / "pending.json").read_text())
        self.assertEqual([g["id"] for g in pending["groups"]], ["airlog", "settings"])
        self.assertTrue((self.data / "air_log.jsonl").exists())   # nothing cold went live
        # the next process
        res = filemgr.FileManager(self.data, self.fm.groups_path).boot()
        self.assertIn("airlog", res["groups"])
        self.assertFalse((self.data / "air_log.jsonl").exists())
        self.assertFalse((self.data / "logs" / "one.log").exists())
        self.assertEqual(json.loads((self.data / "settings.json").read_text()), {})
        self.assertFalse((self.data / "filemgr" / "pending.json").exists())
        done = next(r for r in self.fm.jobs()["jobs"] if r["id"] == job["id"])
        self.assertEqual(done["state"], "done")
        self.assertIsNone(filemgr.FileManager(self.data, self.fm.groups_path).boot())

    def test_absent_form_deletes_and_annotations_strip(self):
        man = self.fm.manifest()
        tts = next(g for g in man["groups"] if g["id"] == "tts-cache")
        self.assertEqual(tts["paths"], ["tts_cache/**", "nope.json"])
        creds = next(g for g in man["groups"] if g["id"] == "creds")
        self.assertEqual((creds["paths"], creds["empty"]), (["shares.json"], []))
        got = self.fm.start(["creds"], snapshot=False, typed="RESET")
        self.assertTrue(got["ok"], got)
        self.wait(got["job"]["id"])
        filemgr.FileManager(self.data, self.fm.groups_path).boot()
        self.assertFalse((self.data / "shares.json").exists())

    def test_typed_word_required(self):
        got = self.fm.start(["settings"], snapshot=False, typed="")
        self.assertFalse(got["ok"])
        self.assertIn("RESET", got["error"])

    def test_interrupted_boot_is_not_retried(self):
        (self.data / "filemgr" / "pending.running.json").write_text(json.dumps({"job": "x"}))
        self.assertIsNone(self.fm.boot())
        self.assertFalse((self.data / "filemgr" / "pending.running.json").exists())


class TestSnapshotRestore(Base):
    def test_round_trip(self):
        before = (self.data / "air_log.jsonl").read_bytes()
        got = self.fm.start(["airlog", "tts-cache"], snapshot=True)
        self.assertTrue(got["ok"], got)
        job = self.wait(got["job"]["id"])
        self.assertTrue(job["snapshot_name"].endswith(".tar"))
        filemgr.FileManager(self.data, self.fm.groups_path).boot()
        self.assertFalse((self.data / "air_log.jsonl").exists())
        self.assertFalse((self.data / "tts_cache" / "a.wav").exists())
        snaps = self.fm.jobs()["snapshots"]
        self.assertEqual(snaps[0]["name"], job["snapshot_name"])
        r = self.fm.restore(job["snapshot_name"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(len(self.restarts), 2)
        out = filemgr.FileManager(self.data, self.fm.groups_path).boot()
        self.assertEqual(out["files"], 4)
        self.assertEqual((self.data / "air_log.jsonl").read_bytes(), before)
        self.assertEqual((self.data / "tts_cache" / "sub" / "b.wav").read_bytes(), b"y" * 50)

    def test_restore_refuses_unknown_and_traversal(self):
        self.assertFalse(self.fm.restore("../../etc/passwd")["ok"])
        self.assertFalse(self.fm.restore("nope.tar")["ok"])


class TestRefusal(Base):
    def test_refused_while_live_but_hot_still_allowed(self):
        self.ns["pinelive"].PL.phase = "live"
        got = self.fm.start(["airlog"], snapshot=False)
        self.assertFalse(got["ok"])
        self.assertIn("PineLive", got["error"])
        self.assertFalse((self.data / "filemgr" / "pending.json").exists())
        self.assertEqual(self.restarts, [])
        ok = self.fm.start(["tts-cache"], snapshot=False)
        self.assertTrue(ok["ok"], ok)
        self.wait(ok["job"]["id"])

    def test_restore_refused_while_live(self):
        self.ns["pinelive"].PL.phase = "live"
        (self.data / "filemgr" / "snapshots").mkdir(parents=True)
        (self.data / "filemgr" / "snapshots" / "s.tar").write_bytes(b"")
        self.assertFalse(self.fm.restore("s.tar")["ok"])

    def test_one_job_at_a_time(self):
        self.fm._jobs_write([{"id": "busy", "state": "snapshot", "at": time.time()}])
        got = self.fm.start(["tts-cache"], snapshot=False)
        self.assertFalse(got["ok"])


class TestAuth(unittest.TestCase):
    def test_every_route_needs_the_key(self):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        def require_auth(authorization):
            if authorization != "Bearer k":
                raise HTTPException(status_code=401, detail="Unauthorized")

        with tempfile.TemporaryDirectory() as td:
            app = FastAPI()
            ns = {"require_auth": require_auth, "DATA_DIR": Path(td)}
            filemgr.install(app, ns)
            c = TestClient(app)
            for method, url in (("get", "/api/filemgr/groups"), ("post", "/api/filemgr/plan"),
                                ("post", "/api/filemgr/run"), ("get", "/api/filemgr/jobs"),
                                ("post", "/api/filemgr/restore")):
                r = getattr(c, method)(url, json={}) if method == "post" else c.get(url)
                self.assertEqual(r.status_code, 401, url)
            h = {"Authorization": "Bearer k"}
            self.assertEqual(c.get("/api/filemgr/jobs", headers=h).status_code, 200)
            g = c.get("/api/filemgr/groups", headers=h).json()
            self.assertIn("presets", g)
            self.assertEqual(c.post("/api/filemgr/run", headers=h, json={"groups": []}).status_code, 409)


if __name__ == "__main__":
    unittest.main()
