"""[s3-lists] The desk's doors over HTTP, against the station's REAL store
functions - without importing app.py.

The registry block and its routes are taken from tools/system3_lists_patch.py
(REGISTRY); the store functions they call (the quip shelf, the topics board,
the ad book, the upstairs pages, the gold bank) are lifted by name out of
app.py's own text and run in a small FastAPI app over a temporary data
directory. So this runs anywhere FastAPI does (the container, a dev box),
and what it exercises is the code that ships.

S3_APP_PY=path/to/app.py points it at another copy (default: the repo's)."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from threading import RLock
import time
import unittest
import uuid
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

try:
    from fastapi import FastAPI, Header, HTTPException, Request
    from fastapi.testclient import TestClient
except Exception as exc:  # noqa: BLE001
    raise unittest.SkipTest("needs fastapi + httpx: %s" % exc)

import system3_lists_patch
from sfx_speech_bank import SfxSpeechBank, line_key

STORE_FUNCTIONS = (
    "_sfxguy_voice", "sfxguy_quips", "sfxguy_quips_save", "_sfxguy_key", "_sfxguy_said",
    "read_bombshells", "write_bombshells", "add_bombshell", "split_exchange", "_json_rows", "_json_write",
    "ad_airings", "ad_list", "_ads_write", "ad_save", "ad_update", "ad_delete",
    "upstairs_list", "_upstairs_write", "upstairs_save", "upstairs_update", "upstairs_delete",
    "_gold_rows", "_gold_save", "gold_burnt_rows",
)


def lift(source: str, name: str) -> str:
    """One top-level def out of app.py's text: its line to the next line that
    starts at column 0 (a blank or a comment does not end it)."""
    m = re.search(r"^def %s\(" % re.escape(name), source, re.M)
    if not m:
        raise AssertionError("app.py has no def %s" % name)
    out = []
    for line in source[m.start():].split("\n"):
        if out and line and not line[0].isspace() and not line.startswith("#") and not line.startswith(")"):
            break
        out.append(line)
    return "\n".join(out)


class Routes(unittest.TestCase):
    KEY = "Bearer k"

    @classmethod
    def setUpClass(cls):
        path = Path(os.environ.get("S3_APP_PY") or ROOT / "app.py")
        if not path.exists():
            raise unittest.SkipTest("no app.py at %s" % path)
        source = path.read_text(encoding="utf-8")
        cls.lifted = [(name, compile(lift(source, name), "app.py:" + name, "exec")) for name in STORE_FUNCTIONS]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = Path(self.tmp.name)
        self.data = data
        app = FastAPI()
        ns: dict[str, Any] = {
            "__name__": "fake_app", "Any": Any, "FastAPI": FastAPI, "Header": Header, "HTTPException": HTTPException,
            "Request": Request, "asyncio": asyncio, "time": time, "json": json, "re": re, "uuid": uuid,
            "hashlib": hashlib, "RLock": RLock, "Path": Path, "app": app,
            "data_path": lambda name: data / name,
            "require_read_auth": lambda authorization: None,
            "dj_settings": lambda: {"drop_voice": "v"},
            "_sfxguy_ready_profile": lambda: "p",
            "_SFX_READY_BANK": SfxSpeechBank(data / "sfxguy_speech.json", data),
            # the quip shelf
            "SFXGUY_QUIPS_DIR": data / "sfxguy_quips", "SFXGUY_SEED_QUIPS": ["Seed one.", "Seed two."],
            "SFXGUY_SAID_PATH": data / "sfxguy_said.json", "_SFXGUY_QUIPS_LOCK": RLock(),
            # the topics board
            "BOMBSHELL_PATH": data / "banter_topics.json", "_BOMBSHELL_LOCK": RLock(), "BOMBSHELL_MAX": 300,
            "TOPIC_TRASH_PATH": data / "banter_topics.trash.json", "_SWITCH_LOCK": RLock(), "_SWITCH_QUEUE": [],
            "bombshell_shape_for": lambda row: "blindside",
            "bombshell_angle": lambda text, shape="", reply="": "ANGLE " + text,
            # the ad book
            "ADS_PATH": data / "ad_reads.json", "_ADS_LOCK": RLock(), "AD_KEEP_SECONDS": 7 * 24 * 3600,
            "PRODUCED_ADS_DIR": data / "ads_audio", "AD_AIRINGS_PATH": data / "ad_airings.json",
            # the upstairs pages
            "UPSTAIRS_PATH": data / "upstairs_pages.json", "_UPSTAIRS_LOCK": RLock(), "UPSTAIRS_KEEP": 300,
            "UPSTAIRS_AUDIO_DIR": data / "upstairs_audio",
            # the gold bank
            "GOLD_PATH": data / "gold_bars.json", "_GOLD": {"loaded": False, "rows": []}, "GOLD_TEXT_MAX": 20000,
            "GOLD_BURNT_PATH": data / "gold_burnt.json", "_WORD_DIAL_LOCK": RLock(),
        }
        self.gold_notes = []
        ns["word_edit_note"] = lambda endpoint, **kw: self.gold_notes.append((endpoint, kw)) or {}

        def require_auth(authorization):
            if authorization != self.KEY:
                raise HTTPException(status_code=401, detail="Unauthorized")
        ns["require_auth"] = require_auth
        for _name, code in self.lifted:
            exec(code, ns)
        exec(compile(system3_lists_patch.REGISTRY, "system3_lists_patch.REGISTRY", "exec"), ns)
        self.ns = ns
        self.client = TestClient(app)

    def get(self, path, **params):
        got = self.client.get(path, params=params)
        self.assertEqual(got.status_code, 200, got.text)
        return got.json()

    def write(self, method, path, body=None, status=200, auth=True):
        got = self.client.request(method, path, json=body, headers={"Authorization": self.KEY} if auth else {})
        self.assertEqual(got.status_code, status, got.text)
        return got.json()

    # --- the registry ---------------------------------------------------------
    def test_the_registry_lists_the_bank_first_with_counts_and_doors(self):
        self.ns["_SFX_READY_BANK"].seed("v", "p", [{"text": "I sold the tapes to Sawyer."}])
        got = self.get("/api/system3/lists")["lists"]
        self.assertEqual([l["id"] for l in got],
                         ["sfxguy.bank", "sfxguy.quips", "topics.board", "ads.book", "upstairs.pages", "gold.bars"])
        self.assertEqual((got[0]["family"], got[0]["count"]), ("BANK", 1))
        self.assertEqual(got[0]["can"], {"add": True, "edit": True, "switch": True, "remove": True})
        self.assertEqual(got[5]["can"], {"add": False, "edit": False, "switch": False, "remove": True})
        self.assertEqual(got[1]["count"], 2, "a voice with no shelf file reads the seed list")

    def test_writes_need_the_key_and_unknowns_are_404(self):
        self.write("POST", "/api/system3/lists/sfxguy.bank/rows", {"text": "x"}, status=401, auth=False)
        self.write("POST", "/api/system3/lists/nope/rows", {"text": "x"}, status=404)
        self.assertEqual(self.client.get("/api/system3/lists/nope").status_code, 404)
        self.write("PUT", "/api/system3/lists/sfxguy.bank/rows/feedface", {"text": "x"}, status=404)
        self.write("PUT", "/api/system3/lists/sfxguy.quips/rows/" + line_key("Seed one."), {"on": False}, status=405)
        self.write("POST", "/api/system3/lists/gold.bars/rows", {"text": "x"}, status=405)

    # --- the speech bank --------------------------------------------------------
    def test_the_bank_over_http(self):
        bank = self.ns["_SFX_READY_BANK"]
        bank.seed("v", "p", [{"text": "I sold the tapes to Sawyer."}])
        rid = line_key("I sold the tapes to Sawyer.")
        page = self.get("/api/system3/lists/sfxguy.bank", q="sawyer")
        self.assertEqual([(r["id"], r["state"]) for r in page["rows"]], [(rid, "waiting")])
        got = self.write("PUT", "/api/system3/lists/sfxguy.bank/rows/" + rid, {"text": "I kept the tapes."})
        self.assertEqual((got["was"], got["id"], got["row"]["text"]), (rid, line_key("I kept the tapes."), "I kept the tapes."))
        got = self.write("POST", "/api/system3/lists/sfxguy.bank/rows", {"text": "A new one from the desk."})
        self.assertEqual(got["row"]["state"], "waiting")
        self.write("POST", "/api/system3/lists/sfxguy.bank/rows", {"text": "a new ONE from the desk."}, status=400)
        self.write("PUT", "/api/system3/lists/sfxguy.bank/rows/" + got["id"], {"on": False})
        self.assertEqual(self.get("/api/system3/lists/sfxguy.bank", state="off")["total"], 1)
        self.write("DELETE", "/api/system3/lists/sfxguy.bank/rows/" + line_key("I kept the tapes."))
        self.assertEqual(bank.seed("v", "p", [{"text": "I sold the tapes to Sawyer."}]), 0)
        edits = self.get("/api/system3/lists/sfxguy.bank")["edits"]
        self.assertEqual([e["op"] for e in edits], ["remove", "switch", "add", "add", "edit"])
        self.assertIn("failed", edits[2], "the refused duplicate is on the record as failed")
        self.assertNotIn("failed", edits[3])
        self.assertEqual(edits[0]["who"]["addr"], "testclient")

    # --- the quip shelf -------------------------------------------------------
    def test_the_quip_shelf(self):
        base = "/api/system3/lists/sfxguy.quips"
        self.write("POST", base + "/rows", {"text": "Cue the horns."})
        self.write("POST", base + "/rows", {"text": "cue the  horns."}, status=400)
        self.write("PUT", base + "/rows/" + line_key("Seed one."), {"text": "Seed one, sharpened."})
        self.write("DELETE", base + "/rows/" + line_key("Seed two."))
        shelf = json.loads((self.data / "sfxguy_quips" / "v.json").read_text())
        self.assertEqual(shelf, ["Seed one, sharpened.", "Cue the horns."])
        rows = self.get(base)["rows"]
        self.assertEqual(rows[0]["note"], "also a source of his speech bank")
        self.write("PUT", base + "/rows/" + line_key("Cue the horns."), {"text": "  "}, status=400)

    # --- the topics board -----------------------------------------------------
    def test_the_topics_board(self):
        base = "/api/system3/lists/topics.board"
        got = self.write("POST", base + "/rows", {"text": "1. Who took my stapler? 2. Nobody took your stapler."})
        rid = got["id"]
        self.assertIn("answered with: Nobody took your stapler.", got["row"]["note"])
        self.ns["_SWITCH_QUEUE"].append({"topic_id": rid, "premise": "old"})
        self.write("PUT", base + "/rows/" + rid, {"text": "Who took my good stapler?"})
        row = self.ns["read_bombshells"]()[0]
        self.assertEqual((row["text"], row["reply"]), ("Who took my good stapler?", "Nobody took your stapler."),
                         "the answer is kept when new words carry none")
        self.assertEqual(self.ns["_SWITCH_QUEUE"][0]["premise"], "ANGLE Who took my good stapler?")
        self.write("DELETE", base + "/rows/" + rid)
        self.assertEqual(self.ns["read_bombshells"](), [])
        binned = json.loads((self.data / "banter_topics.trash.json").read_text())
        self.assertEqual((binned[0]["id"], binned[0]["binned_why"]), (rid, "removed on the System 3 desk"))

    # --- the ad book ----------------------------------------------------------
    def test_the_ad_book(self):
        base = "/api/system3/lists/ads.book"
        audio = self.data / "ads_audio"
        audio.mkdir()
        (audio / "abc123.mp3").write_bytes(b"spot")
        spot = self.ns["ad_save"]("Pine Cones", "Buy pine cones.", kind="produced", extra={"audio": "abc123.mp3"})
        self.assertEqual(self.get(base)["rows"][0]["state"], "produced")
        self.write("PUT", base + "/rows/" + spot["id"], {"on": False})
        self.assertIs(self.ns["ad_list"]()[0]["auto_air"], False)
        self.write("PUT", base + "/rows/" + spot["id"], {"text": "Buy fresh pine cones."})
        row = self.ns["ad_list"]()[0]
        self.assertEqual((row["text"], row["audio"]), ("Buy fresh pine cones.", ""))
        self.assertFalse((audio / "abc123.mp3").exists(), "the recording of the old words is gone")
        self.write("DELETE", base + "/rows/" + spot["id"])
        self.assertEqual(self.ns["ad_list"](), [])

    # --- the upstairs pages ---------------------------------------------------
    def test_the_upstairs_pages(self):
        base = "/api/system3/lists/upstairs.pages"
        got = self.write("POST", base + "/rows", {"text": "Spin more records."})
        self.assertEqual(got["row"]["state"], "not recorded")
        self.write("PUT", base + "/rows/" + got["id"], {"text": "Spin more records and talk less."})
        self.assertEqual(self.ns["upstairs_list"]()[0]["text"], "Spin more records and talk less.")
        self.write("DELETE", base + "/rows/" + got["id"])
        self.write("DELETE", base + "/rows/" + got["id"], status=404)

    # --- the gold bank --------------------------------------------------------
    def test_the_gold_bank_burns_to_the_bin(self):
        (self.data / "gold_bars.json").write_text(json.dumps([
            {"key": "g1", "who": "dj", "text": "Gold one.", "fired": 3, "last": 5.0, "seconds": 2.5},
            {"key": "g2", "who": "cohost", "text": "Gold two.", "fired": 0}]))
        rows = self.get("/api/system3/lists/gold.bars")["rows"]
        self.assertEqual([(r["id"], r["plays"]) for r in rows], [("g1", 3), ("g2", 0)])
        self.write("PUT", "/api/system3/lists/gold.bars/rows/g1", {"text": "x"}, status=405)
        self.write("DELETE", "/api/system3/lists/gold.bars/rows/g1")
        self.assertEqual([b["key"] for b in json.loads((self.data / "gold_bars.json").read_text())], ["g2"])
        self.assertEqual(json.loads((self.data / "gold_burnt.json").read_text())[0]["key"], "g1")
        self.assertEqual(self.gold_notes[0][0], "/api/system3/lists/gold.bars")


if __name__ == "__main__":
    unittest.main()
