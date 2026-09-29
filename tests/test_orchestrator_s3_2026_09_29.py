"""[orch-s3] The orchestrator's System 3 desk: sensors, the review/confirm/undo
discipline, the ask he raises and what the station may answer alone, the
cupboard and table doors, and the app.py edit tool's contract.

    docker cp <dry tree> spark-agent:/tmp/wX
    docker exec -w /tmp/wX -e PYTHONPATH=tests:. spark-agent nice -n 10 \
        python3 -m unittest tests.test_orchestrator_s3_2026_09_29

Never imports app.py; every station door is the sandbox's (tools/orch_s3_sandbox.py).
"""
import asyncio
import importlib.util
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

import orchestrator_s3 as os3
import system3

HERE = Path(__file__).resolve().parent.parent


def load_tool(name):
    p = HERE / "tools" / name
    if not p.exists():
        raise unittest.SkipTest("%s is not here" % name)
    sys.path.insert(0, str(p.parent))
    spec = importlib.util.spec_from_file_location(name[:-3], p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sb = load_tool("orch_s3_sandbox.py")
        self.ns = self.sb.build(Path(self.tmp.name))
        self.desk = self.ns["_desk"]
        self.calls = self.ns["_calls"]

    def tearDown(self):
        self.ns["_ledger"].close()
        self.tmp.cleanup()

    def cmd(self, text):
        return asyncio.run(self.desk.command(text))


class Sensors(unittest.TestCase):
    def test_origin_splits_rogue_from_untraced(self):
        u = {"items_total": 100, "items": [
            {"line_id": "a" * 32, "producer": "ad_break_legacy", "road": "ad", "text": "x", "path": "ad_break_legacy<x"},
            {"line_id": "b" * 32, "producer": "page_recovery_chat_rows", "road": "interject", "text": "y",
             "path": "page_recovery_chat_rows<page_recovery_start"}],
            "by_path": [{"producer": "ad_break_legacy", "road": "ad", "count": 2, "last": 1},
                        {"producer": "page_recovery_chat_rows", "road": "interject", "count": 3, "last": 1},
                        {"producer": "odd_writer", "road": "round: banter", "count": 1, "last": 1}]}
        got = {(f["class"], f["road"]): f for f in os3.sense_origin(u, {"ad": "active", "interject": "active"})}
        self.assertEqual(got[("rogue", "ad")]["severity"], "high")
        self.assertIn("why #aaaaaaaa", got[("rogue", "ad")]["identify"])
        self.assertEqual(got[("untraced", "interject")]["severity"], "medium")
        self.assertEqual(got[("rogue", "banter")]["severity"], "medium")     # banter not active here

    def test_mp3_leak_overlap_dead_air_stale_undecodable(self):
        f = os3.sense_mp4({"mp4_only": True, "left_empty": 2, "quarantine": {"clips": 3}},
                          {"audio_only_rows": 2, "players": {"pinetab": {"not_displayed_by_reason": {
                              "MEDIA_ERR_SRC_NOT_SUPPORTED": 1}, "surfaces": {}}}})
        self.assertEqual({x["class"] for x in f}, {"mp3_leak", "dead_air", "undecodable"})
        self.assertEqual(os3.sense_mp4({"mp4_only": False}, {"audio_only_rows": 5}), [])
        rx = {"receivers": [{"id": "pinetab", "sounding": True}, {"id": "desktop", "sounding": True},
                            {"id": "car", "sounding": True}]}
        self.assertEqual(os3.sense_receivers(rx, True)[0]["class"], "overlap")
        quiet = {"receivers": [{"id": "pinetab", "sounding": False}]}
        self.assertEqual(os3.sense_receivers(quiet, True)[0]["class"], "dead_air")
        self.assertEqual(os3.sense_receivers(quiet, False), [])
        now = time.time()
        gaps = [{"until": now - 10, "seconds": 150, "cause": "event-loop stall", "prev": {"id": "c" * 32}}]
        self.assertEqual(os3.sense_gaps(gaps, now)[0]["severity"], "high")
        self.assertEqual(os3.sense_gaps([{"until": now - 10, "seconds": 5}], now), [])
        self.assertEqual(os3.sense_script(now - 1200, {"line_id": "d" * 32}, True, False, now)[0]["class"],
                         "stale_script")
        self.assertEqual(os3.sense_script(now - 1200, None, True, True, now), [])      # paused is not stale

    def test_every_class_has_a_playbook_and_elements_name_their_doors(self):
        for cls in ("rogue", "untraced", "mp3_leak", "overlap", "dead_air", "stale_script", "undecodable"):
            b = os3.PLAYBOOK[cls]
            self.assertTrue(b["identify"] and b["resolve"] and b["never"], cls)
        keys = {e["key"] for e in os3.ELEMENTS}
        self.assertTrue({"origin", "why", "tree", "tables", "cupboard", "filemgr", "display", "mp4",
                         "receivers", "es1", "h3speak", "actors", "roll"} <= keys)

    def test_set_path_and_diff(self):
        t = {"categories": [{"id": "a", "weight": 1, "items": [{"id": "x", "odds": 0.2}]}]}
        n = {"categories": [{"id": "a", "weight": 1, "items": [{"id": "x", "odds": 0.2}]}]}
        os3.set_path(n, "categories.a.items.x.odds", 0.5)
        self.assertEqual(os3.flat_diff(t, n), [["categories.a.items.x.odds", 0.2, 0.5]])
        with self.assertRaises(ValueError):
            os3.set_path(n, "categories.nope.weight", 1)


class Discipline(Sandbox):
    def test_survey_finds_the_rogue_ad_and_the_untraced_lines(self):
        v = self.desk.survey()
        classes = [(f["class"], f["severity"]) for f in v["findings"]]
        self.assertEqual(classes[0], ("rogue", "high"))
        self.assertIn(("untraced", "medium"), classes)
        rogue = v["findings"][0]
        titles = [self.desk.find_proposal(p)["title"] for p in rogue["proposals"]]
        self.assertEqual(len(titles), 2)                       # the stamped ad is never nominated
        self.assertTrue(all("legacy" in t for t in titles))
        fac = self.desk.faculties()
        for name in ("origin", "mp4", "receivers", "gaps", "script", "tables", "cupboard"):
            self.assertGreaterEqual(fac[name]["ok"], 1, name)

    def test_the_first_option_is_always_the_stations_to_take(self):
        self.desk.survey()
        a1 = self.desk.ask()
        a2 = self.desk.ask()
        self.assertEqual((a1["topic"], a2["topic"]), ("s3_rogue", "s3_untraced"))
        self.assertEqual(self.desk.ask(), {})                  # half a day per topic
        for a in (a1, a2):
            first = a["questions"][0]["options"][0]["does"]
            self.assertRegex(first, r"^s3(file|note):")
            self.assertLessEqual(len(a["questions"][0]["options"]), 4)
        verb, _, arg = a1["questions"][0]["options"][0]["does"].partition(":")
        self.desk.verb(verb, arg, alone=True)
        self.desk.verb(verb, arg, alone=True)
        self.assertEqual(sum(1 for c in self.calls if c[0] == "pine_append"), 1)   # once a day

    def test_station_alone_confirms_only_station_may(self):
        self.desk.survey()
        rogue = self.desk.memo["value"]["findings"][0]
        pid = rogue["proposals"][0]
        self.assertIn("retirement desk", self.desk.verb("s3fix", pid, alone=True))
        self.assertEqual([c[0] for c in self.calls].count("retire_may"), 1)
        self.assertTrue(self.desk.undo(pid)["ok"])
        self.assertEqual(self.calls[-1][1][1], "keep")
        for p in (self.desk.propose_cupboard("ad-legacy02", "remove"),
                  self.desk.propose_cupboard("gallery-old001", "finish"),
                  self.desk.propose_quarantine("q9", "/sfx/q9.mp3", "undecodable")):
            self.assertIn("waits for the operator", self.desk.verb("s3fix", p["id"], alone=True))
            self.assertEqual(self.desk.find_proposal(p["id"])["state"], "proposed")
        self.assertFalse(any(c[0] == "retire_decide" and c[1][1] == "remove" for c in self.calls))
        self.assertFalse(any(c[0] in ("sfx_quarantine", "cupboard_finish_add") for c in self.calls))

    def test_table_review_confirm_undo_and_a_stale_review(self):
        rt = self.ns["_rt"]
        t = next(x for x in rt.config["tables"] if x.get("categories"))
        cat = t["categories"][0]
        key = "odds" if "odds" in cat else "weight"
        was = cat.get(key)
        ok, say, lines = self.cmd("table %s set categories.%s.%s=%s" % (t["id"], cat["id"], key, float(was) + 1))
        self.assertTrue(ok, say)
        pid = say.split()[1]
        self.assertIn("categories.%s.%s" % (cat["id"], key), lines[0])
        h0 = system3.config_hash(rt.config)
        self.assertIn("operator", self.desk.verb("s3fix", pid, alone=True))
        self.assertEqual(system3.config_hash(rt.config), h0)          # nothing saved by the station
        got = self.desk.confirm(pid)
        self.assertTrue(got["ok"], got)
        live = next(x for x in rt.config["tables"] if x["id"] == t["id"])
        self.assertEqual(live["categories"][0][key], float(was) + 1)
        self.assertEqual(got["proposal"]["hash_before"], h0)
        self.assertTrue(self.desk.undo(pid)["ok"])
        live = next(x for x in rt.config["tables"] if x["id"] == t["id"])
        self.assertEqual(live["categories"][0][key], was)
        # a review older than the live config is refused, not written over it
        p2 = self.desk.propose_table(t["id"], {"categories.%s.%s" % (cat["id"], key): float(was) + 2})
        self.desk._save_config(dict(rt.config, sfx=dict(rt.config.get("sfx") or {}, moved=True)), "someone else")
        got = self.desk.confirm(p2["id"])
        self.assertFalse(got["ok"])
        self.assertIn("review it again", got["say"])

    def test_cupboard_cue_undo_and_listing_by_stamp(self):
        ok, say, lines = self.cmd("cupboard gallery")
        self.assertTrue(any("S3" in ln for ln in lines) and any("legacy" in ln for ln in lines))
        ok, say, _ = self.cmd("cupboard gallery-ready1 cue")
        pid = say.split()[1].rstrip(":")
        self.assertTrue(self.cmd("confirm %s" % pid)[0])
        row = self.ns["_SHELF"]["gallery"][1]
        self.assertIn("cue_at", row)
        self.assertTrue(self.cmd("undo %s" % pid)[0])
        self.assertNotIn("cue_at", row)
        ok, say, _ = self.cmd("cupboard nothing-here cue")
        self.assertFalse(ok)

    def test_why_code_reads_the_life_story(self):
        ok, say, lines = self.cmd("why cdb3ea55")
        self.assertTrue(ok)
        self.assertIn("rogue via page_recovery_chat_rows", say)

    def test_judge_hears_system3(self):
        self.desk.survey()
        legacy = self.ns["_SHELF"]["ad"][0]
        stamped = self.ns["_SHELF"]["ad"][2]
        self.assertIn("Untraced", self.desk.judge_note("ad", legacy))
        self.assertIn("System 3 scripted it", self.desk.judge_note("ad", stamped))

    def test_a_missing_door_is_counted_not_fatal(self):
        self.ns.pop("_ORIGIN_LEDGER")
        v = self.desk.survey()
        self.assertIn("error", self.desk.faculties()["origin"])
        self.assertIsInstance(v["findings"], list)


class Tool(unittest.TestCase):
    def test_contract(self):
        tool = load_tool("orch_s3_app_patch.py")
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "app.py"
            p.write_bytes(b"nothing here\n")
            self.assertEqual(tool.run(tool.EDITS, ["--check", str(p)], marker=tool.MARKER), 1)
            body = "head\n" + "".join("x\n" + e.anchor + "y\n" for e in tool.EDITS) + "tail\n"
            p.write_bytes(body.replace("\n", "\r\n").encode())
            self.assertEqual(tool.run(tool.EDITS, ["--check", str(p)], marker=tool.MARKER), 0)
            self.assertEqual(tool.run(tool.EDITS, ["--apply", str(p)], marker=tool.MARKER), 0)
            out = p.read_bytes().decode()
            self.assertIn("[orch-s3]", out)
            self.assertNotIn("\n", out.replace("\r\n", ""))
            self.assertEqual(tool.run(tool.EDITS, ["--apply", str(p)], marker=tool.MARKER), 2)
            self.assertEqual(tool.run(tool.EDITS, ["--check", str(p)], marker=tool.MARKER), 2)
            lf = out.replace("\r\n", "\n")
            for e in tool.EDITS:                   # no insert re-creates its own anchor
                self.assertEqual(lf.count(e.anchor), 1 if e.replace is None else 0, e.name)

    def test_orch_verbs_reads_the_new_verbs(self):
        tool = load_tool("orch_s3_app_patch.py")
        verbs = next(e for e in tool.EDITS if e.name == "verbs").text
        found = set()
        for group in re.findall(r'verb in \(([^)]*)\)', verbs):
            found |= {x.strip().strip('"') for x in group.split(",") if x.strip()}
        self.assertEqual(found, {"s3note", "s3file", "s3fix", "s3undo", "s3hold"})

    def test_this_trees_app_py(self):
        app = HERE / "app.py"
        if not app.exists():
            raise unittest.SkipTest("no app.py in this tree")
        tool = load_tool("orch_s3_app_patch.py")
        rc = tool.run(tool.EDITS, ["--check", str(app)], marker=tool.MARKER)
        self.assertIn(rc, (0, 2))
        if rc == 2:
            s = app.read_text(encoding="utf-8")
            self.assertLess(s.index("_s3desk.maybe_survey()"), s.index("        if orch_open():\n            orch_decide_alone()"))
            self.assertLess(s.index('_s3ask = globals().get("orch_s3_ask")'),
                            s.index("        # 4. NOTHING IS WRONG - but six hours is six hours."))
            self.assertLess(s.index("import orchestrator_s3 as _orch_s3"), s.index("_filemgr.install(app, globals())"))


if __name__ == "__main__":
    unittest.main()
