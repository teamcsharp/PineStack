"""System 3's host adapter against a stand-in station: System 3 -> plan
-> running order -> doors -> bind -> performance -> SFX -> script ledger ->
the operator APIs, in each mode, and the fallbacks when a road fails."""
import asyncio
import json
from pathlib import Path
import re
import tempfile
import time
import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import system3
import system3_runtime


class FakeStation(dict):
    """The namespace install() reads, with just enough station in it."""

    def __init__(self, root, quote_delay=0.0, quote_fails=False):
        super().__init__()
        self.root = Path(root)
        docs = self.root / "speakbox"
        docs.mkdir()
        for name, lines in (("aa.md", ["Hello mom.", "I could eat."]),
                            ("43d.md", ["I want to eat.", "Someone got eaten.", "We can eat."])):
            (docs / name).write_text("\n".join(lines))
        self.logged, self.flow, self.remembered = [], [], []
        self.quote_calls = 0

        async def speakbox_quote(exclude="", most=9, cap=0, rid="", only="", tinted=True):
            self.quote_calls += 1
            if quote_delay:
                await asyncio.sleep(quote_delay)
            if quote_fails:
                raise RuntimeError("the share is down")
            return {"file": "43d.md", "text": "I want to eat. Someone got eaten.",
                    "lines": ["I want to eat.", "Someone got eaten."], "mind": ""}

        def banter_turns(script, caller_name="", caller2_name=""):
            return [(m, t.strip()) for m, t in re.findall(r"(?m)^([ABCDE]):\s*(.+)$", script or "")]

        def require_auth(authorization):
            if authorization != "Bearer k":
                raise HTTPException(401, "no")

        self.update(
            data_path=lambda *p: self.root.joinpath(*p),
            pipeline_log=lambda kind, text, extra="": self.logged.append((kind, text)),
            station_flow_event=lambda *a, **k: self.flow.append(a),
            banter_turns=banter_turns, speakbox_quote=speakbox_quote,
            speakbox_remember=lambda q: self.remembered.append(q),
            speakbox_all=lambda rid="": sorted(docs.glob("*.md")),
            speakbox_files=lambda rid="": sorted(docs.glob("*.md")),
            speakbox_weight=lambda name, weights=None, rid="", uses=None: 3 if name == "43d.md" else 1,
            mind_weights=lambda rid="": {},
            mean_turn_seconds=lambda kind="": 11.0,
            segment_budget_now=lambda road: {"seconds": 180.0},
            require_auth=require_auth, require_read_auth=lambda a: None,
            require_listen_auth=lambda t, a: None if t == "tune-token" else require_auth(a))


def ctx(**over):
    base = {"lines": 8, "bank": True, "dj": {"host_name": "Caine", "cohost_name": "Skip",
                                             "speakbox_prepend_rate": 0.9, "speakbox_append_rate": 0.9},
            "seats": ["A", "B"], "seed_text": "The raccoon took the van.", "seed_file": "aa.md",
            "angle": "", "weather": {"seats": {"dj": {"irritation": 0.4}}}, "approach": {"id": "x"}}
    base.update(over)
    return base


def written(handle):
    return "\n".join("%s: %s" % (t["speaker"], "No, that is wrong? Thanks, back to the music. " + t["turn_id"])
                     for t in handle.conv["turns"])


def settle():
    system3_runtime._STORE_POOL.submit(lambda: None).result(timeout=10)


class RuntimeTests(unittest.TestCase):
    def boot(self, mode="active_selected_roads", **station):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.station = FakeStation(self.tmp.name, **station)
        app = FastAPI()
        system3_runtime.install(app, self.station)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.rt = self.station["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        self.assertTrue(self.rt.ready)
        r = self.client.post("/api/system3/settings", json={"mode": mode, "roads": ["banter"],
                                                             "test_seed": "rt-1"},
                             headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        return self.rt

    def run_(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def test_active_round_end_to_end(self):
        rt = self.boot()
        h = self.run_(self.station["system3_direct_banter"](**ctx()))
        self.assertIsNotNone(h)
        self.assertTrue(h.active)
        self.assertIn("THE RUNNING ORDER OF THIS EXCHANGE", h.sheet)
        # [s3-window] the slot asked 8; the length is System 3's roll in the segment band (8..12 here)
        rows_written = len(re.findall(r"(?m)^\s*\d+\s+[AB]\s+-", h.sheet))
        self.assertTrue(8 <= rows_written <= 12, rows_written)
        self.assertEqual(rows_written, h.conv["length_roll"]["turns"])
        # the round-level doors stand down under System 3 (engine v2): its
        # running order carries the speakerbox, so there is no door roll
        self.assertIsNone(self.station["system3_door_roll"](h, "prepend"))
        u = 0.41
        # a written script is bound; every turn carries its chain
        entry = {"script": written(h), "quotes": {"prepend": {"applies": True, "rate": 0.6, "roll": u,
                                                               "hit": u < 0.6, "file": "aa.md"}},
                 "dealt": []}
        script_before = entry["script"]
        self.station["system3_bind_entry"](entry, h)
        self.assertEqual(entry["script"], script_before, "binding never touches the words")
        self.assertEqual(entry["system3"]["mode"], "active")
        self.assertEqual(entry["system3"]["turns"]["3"], h.conv["turns"][3]["turn_id"])
        self.assertEqual(len(entry["turn_dice"]), h.conv["length_roll"]["turns"])   # [s3-window] the rolled length
        stamp = entry["turn_dice"]["3"]["s3"]
        self.assertEqual(stamp["conversation_id"], h.id)
        self.assertEqual(set(stamp["perf"]["dims"]), set(system3.EMOTION_DIMS))
        # ES -> the voice
        text3 = self.station["banter_turns"](entry["script"])[3][1]
        # every written turn opens with the same words; the whole chunk and
        # the seat still find turn 3 and not the first turn that starts alike
        dims = self.station["system3_perf_state"](entry, None, text3, "cohost")
        self.assertEqual(dims, {d: float(stamp["perf"]["dims"][d]) for d in system3.EMOTION_DIMS})
        # the SFX guy: turn 2 (first exchange) always wants a clip
        text2 = self.station["banter_turns"](entry["script"])[2][1]
        d2 = self.station["system3_sfx_direction"](entry, "dj", text2)
        planned = h.conv["turns"][2]["sfx"]
        self.assertTrue(planned["play"])
        if planned["placement"] == "after":
            self.assertTrue(d2["extra"])
            self.assertTrue(d2["query"])
            again = self.station["system3_sfx_direction"](entry, "dj", text2)
            self.assertFalse(again["extra"], "one extra due per planned clip")
        self.station["system3_sfx_observe"](entry, d2, True, [
            {"who": "board", "path": "/sfx/clip_0298.wav", "sfx_sample_id": "s298", "seconds": 2.0}],
            {"path": "/sfx/clip_0298.wav", "why": "raccoon", "score": 3.0, "cands": 17, "tied": 4,
             "eligible": 13, "at": time.time()})
        # the script ledger freezes it
        rows = [{"line_id": "L%d" % i, "who": "dj", "text": t, "dice": entry["turn_dice"].get(str(i))}
                for i, (_m, t) in enumerate(self.station["banter_turns"](entry["script"]))]
        self.station["system3_observe_ledger"](41, "sid-9", rows, "banter")
        settle()
        # the operator surface
        got = self.client.get("/api/system3/conversation/" + h.id).json()
        self.assertEqual(got["validation"]["seat_order"], 1.0)
        # the seed passage is on the record, so an opened line can mark it
        self.assertEqual(got["inputs"]["seed_text"], "The raccoon took the van.")
        asset = self.client.get("/system3/system3.js")
        self.assertEqual(asset.status_code, 200)
        self.assertEqual(asset.headers.get("cache-control"), "no-cache")
        fams = {o["family"] for o in got["observations_air"]}
        self.assertTrue({"SPEAKERBOX", "SFX", "COMMIT"} <= fams, fams)
        sfx = next(o for o in got["observations_air"] if o["family"] == "SFX")
        self.assertEqual(sfx["matcher"]["eligible"], 13)
        self.assertEqual(sfx["played"][0]["clip"], "clip_0298.wav")
        self.assertEqual(len(got["lines"]), h.conv["length_roll"]["turns"])   # [s3-window] the rolled length
        line = self.client.get("/api/system3/line", params={"line_id": "L3"}).json()
        self.assertEqual(line["turn"]["turn_id"], h.conv["turns"][3]["turn_id"])
        self.assertTrue(line["decisions"])
        self.assertTrue(all(d["turn_id"] == line["turn"]["turn_id"] for d in line["decisions"]))
        replay = self.client.post("/api/system3/replay/" + h.id).json()
        self.assertTrue(replay["ok"], replay)
        feed = self.client.get("/api/system3/events", params={"after": 0, "limit": 1000}).json()
        self.assertEqual(feed["head"], feed["cursor"])
        status = self.client.get("/api/system3/status").json()
        # [s3-roads] every road on the register has a mode; only banter is ticked
        self.assertEqual(status["road_modes"]["banter"], "active")
        self.assertEqual({m for r, m in status["road_modes"].items() if r != "banter"}, {"shadow"})
        self.assertIn("recap", status["road_modes"])
        self.assertTrue(any(r["id"] == "sfxguy" for r in status["roads"]))
        self.assertEqual(status["metrics"]["failures"], 0)

    def test_material_is_fetched_through_the_station_and_recorded_honestly(self):
        rt = self.boot()
        h = None
        for seed in map(str, range(40)):
            rt.settings["test_seed"] = "m" + seed
            h = self.run_(self.station["system3_direct_banter"](**ctx()))
            if h.conv.get("material"):
                break
        self.assertTrue(h.conv.get("material"), "some seed rolls a speakerbox hit at 90%")
        m = h.conv["material"][0]
        self.assertEqual(m["selected"]["file"], "43d.md")
        self.assertEqual(m["selected"]["passage"], {"index": 1, "of": 3})
        self.assertEqual({c["id"] for c in m["candidates"]}, {"aa.md", "43d.md"})
        self.assertIn("no System 3 random number chose this document", m["draw"])
        self.assertIn("I want to eat.", h.sheet)

    def test_the_passage_is_counted_in_the_lines_it_was_cut_from(self):
        # [line-reel] a transcript's file line is a paragraph; the draw cuts
        # its swath from the station's harvested lines, and "passage N/M"
        # is the line the Messenger's reel lands on in that same list
        rt = self.boot()
        self.station["speakbox_gems"] = lambda doc, rid="": ["Opening words here.", "Then the middle of it.",
                                                            "I want to eat.", "Someone got eaten."]
        pos = self.run_(rt._passage_position({"file": "43d.md", "mind": "", "text": "I want to eat. Someone got eaten.",
                                              "lines": ["I want to eat.", "Someone got eaten."]}))
        self.assertEqual(pos, {"index": 3, "of": 4})

    def test_an_active_call_is_built_from_system3s_call_structure(self):
        # [s3-calls] the call's own legs, rolled - not the station's sheet annotated
        rt = self.boot()
        r = self.client.post("/api/system3/settings", json={"mode": "active_selected_roads", "roads": ["banter", "caller"]},
                             headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        h = self.run_(self.station["system3_direct_banter"](**ctx(
            caller_name="Monk Brennan", lines=11, seats=["A", "B", "C"],
            call_meta={"topic": "a cat in the sewer", "speakerbox_text": "The cat kidnapped somebody."},
            call_sheet=" 1  A  - ANSWER THE RINGING LINE.")))
        self.assertTrue(h.active)
        for words in ("THE RUNNING ORDER OF THIS CALL", "MONK INTRODUCES THEMSELF", "[Say it in", "The cat kidnapped somebody."):
            self.assertIn(words, h.sheet)
        self.assertEqual(h.conv["turns"][-1]["leg"], "sign_off")
        bad = self.client.put("/api/system3/structures/caller", json={"legs": [{"id": "bad"}]},
                              headers={"Authorization": "Bearer k"})
        self.assertEqual(bad.status_code, 400)
        good = self.client.put("/api/system3/structures/caller", json={"legs": h.conv["inputs"] and
                               system3_runtime.system3_tables.default_structures()["caller"]["legs"]},
                               headers={"Authorization": "Bearer k"})
        self.assertEqual(good.status_code, 200, good.text)
        self.assertEqual(good.json()["structure"]["version"], 2)

    def test_a_slow_share_times_out_into_no_passage(self):
        system3_runtime.MATERIAL_TIMEOUT, old = 0.05, system3_runtime.MATERIAL_TIMEOUT
        self.addCleanup(setattr, system3_runtime, "MATERIAL_TIMEOUT", old)
        rt = self.boot(quote_delay=1.0)
        h = None
        for seed in map(str, range(40)):
            rt.settings["test_seed"] = "t" + seed
            h = self.run_(self.station["system3_direct_banter"](**ctx()))
            if h.conv["material_requests"]:
                break
        self.assertTrue(h.active)
        self.assertTrue(all(not r["resolved"]["ok"] for r in h.conv["material_requests"]))
        self.assertGreater(rt.metrics["material_timeouts"], 0)
        self.assertNotIn("word for word as their own words", h.sheet)

    def test_shadow_never_reaches_the_words(self):
        rt = self.boot(mode="shadow")
        h = self.run_(self.station["system3_direct_banter"](**ctx()))
        self.assertFalse(h.active)
        self.assertEqual(h.sheet, "")
        self.assertIsNone(self.station["system3_door_roll"](h, "prepend"))
        self.assertEqual(self.station.quote_calls, 0, "shadow draws no material")
        entry = {"script": "A: hello there.\nB: no way.", "turn_dice": {"0": {"roll": 0.3}}}
        self.station["system3_bind_entry"](entry, h)
        self.assertEqual(entry["turn_dice"], {"0": {"roll": 0.3}}, "shadow does not stamp the lines")
        self.assertEqual(entry["system3"]["mode"], "shadow")
        settle()
        got = self.client.get("/api/system3/conversation/" + h.id).json()
        self.assertEqual(got["status"], "shadowed")
        self.assertEqual(got["comparison"]["actual_turns"], 2)
        self.assertIsNone(self.station["system3_perf_state"](entry, None, "hello there.", "dj"))

    def test_shadow_lines_resolve_to_their_conversation(self):
        """Every script line of a shadowed round names its conversation and
        the planned turn it lined up with, so the Script page can open the
        messenger and the Rolodex on any line - with the aired words."""
        self.boot(mode="shadow")
        h = self.run_(self.station["system3_direct_banter"](**ctx(lines=6)))
        script = "\n".join("%s: words for turn %d." % (t["speaker"], i) for i, t in enumerate(h.conv["turns"]))
        entry = {"script": script}
        self.station["system3_bind_entry"](entry, h)
        turns = entry["system3"]["turns"]
        self.assertEqual(turns["2"], h.conv["turns"][2]["turn_id"])
        self.assertNotIn("turn_dice", entry, "shadow stamps no dice")
        rows = [{"line_id": "S%d" % i, "who": "dj", "text": t,
                 "system3": {"conversation_id": h.id, "mode": "shadow", "turn_id": turns.get(str(i), "")}}
                for i, (_m, t) in enumerate(self.station["banter_turns"](script))]
        rows.append({"line_id": "S-sting", "who": "board", "text": "a sting",
                     "system3": {"conversation_id": h.id, "mode": "shadow", "turn_id": ""}})
        self.station["system3_observe_ledger"](77, "sid", rows, "banter")
        settle()
        got = self.client.get("/api/system3/line", params={"line_id": "S2"}).json()
        self.assertEqual(got["turn"]["turn_id"], h.conv["turns"][2]["turn_id"])
        self.assertEqual(got["conversation"]["mode"], "shadow")
        sting = self.client.get("/api/system3/line", params={"line_id": "S-sting"}).json()
        self.assertIsNone(sting["turn"], "a sting belongs to the conversation, not to a turn")
        conv = self.client.get("/api/system3/conversation/" + h.id).json()
        self.assertTrue(6 <= len(conv["shadow_bindings"]) <= 9, len(conv["shadow_bindings"]))   # [s3-window] the band
        self.assertEqual(conv["shadow_bindings"][2]["script_index"], 2)

    def test_listener_feed_shows_the_rolls_and_nothing_private(self):
        self.boot()
        h = self.run_(self.station["system3_direct_banter"](**ctx(lines=6)))
        entry = {"script": written(h)}
        self.station["system3_bind_entry"](entry, h)
        rows = [{"line_id": "feedline%04d" % i, "who": "dj", "text": t, "dice": entry["turn_dice"].get(str(i)),
                 "system3": {"conversation_id": h.id, "mode": "active", "turn_id": entry["system3"]["turns"].get(str(i), "")}}
                for i, (_m, t) in enumerate(self.station["banter_turns"](entry["script"]))]
        self.station["system3_observe_ledger"](88, "sid", rows, "banter")
        settle()
        denied = self.client.get("/api/system3/public/lines", params={"ids": "feedline0001"})
        self.assertEqual(denied.status_code, 401, "no tune-in token, no feed")
        got = self.client.get("/api/system3/public/lines", params={"ids": "feedline0001,feedline0002,nopenope99", "t": "tune-token"}).json()
        by = {x["line_id"]: x for x in got["lines"]}
        self.assertFalse(by["nopenope99"]["system3"])
        turn = by["feedline0001"]["turn"]
        self.assertEqual(turn["turn"], 2)
        fams = [r["family"] for r in turn["rolls"]]
        self.assertIn("ES", fams)
        es = next(r for r in turn["rolls"] if r["family"] == "ES")
        self.assertIn(es["label"], es["reel"], "the reel holds the real candidates, the pick among them")
        self.assertTrue(1 <= es["dice"] <= 100)
        blob = json.dumps(got)
        for private in ("seed", "config_hash", "settings", h.conv["seed"]):
            self.assertNotIn(private, blob)

    def test_off_is_the_legacy_station(self):
        self.boot(mode="off")
        self.assertIsNone(self.run_(self.station["system3_direct_banter"](**ctx())))
        self.assertIsNone(self.station["system3_door_roll"](None, "prepend"))
        self.assertFalse(self.station["system3_repair_wanted"](None, "A: x"))
        self.assertEqual(self.station["system3_repair_clause"](None), "")
        self.assertIsNone(self.station["system3_director"](None))
        self.station["system3_bind_entry"]({"script": "A: x"}, None)
        self.assertIsNone(self.station["system3_sfx_direction"]({}, "dj", "x"))

    def test_a_planner_fault_falls_back_and_says_so(self):
        rt = self.boot()
        rt.config = {"tables": [], "structure": {"steps": []}}
        self.assertIsNone(self.run_(self.station["system3_direct_banter"](**ctx())))
        self.assertEqual(rt.metrics["fallbacks"], 1)
        self.assertTrue(any("stood aside" in t for _k, t in self.station.logged))

    def test_repair_only_for_a_banked_round(self):
        self.boot()
        live = self.run_(self.station["system3_direct_banter"](**ctx(bank=False)))
        self.assertFalse(self.station["system3_repair_wanted"](live, "A: one speech."))
        banked = self.run_(self.station["system3_direct_banter"](**ctx(bank=True)))
        # [s3-rewrite] the REPAIR roll decides for a System 3 round: stands, or goes back
        banked.conv["repair_roll"] = {"repair": False, "event_id": "t"}
        self.assertFalse(self.station["system3_repair_wanted"](banked, "A: one speech."))
        banked.conv["repair_roll"] = {"repair": True, "event_id": "t"}
        self.assertTrue(self.station["system3_repair_wanted"](banked, "A: one speech."))
        self.assertIn("RUNNING ORDER", self.station["system3_repair_clause"](banked))

    def test_turn_by_turn_director(self):
        rt = self.boot()
        self.client.post("/api/system3/settings", json={"generation_mode": "turn"},
                         headers={"Authorization": "Bearer k"})
        h = self.run_(self.station["system3_direct_banter"](**ctx(lines=10)))
        step = self.station["system3_director"](h)
        self.assertIsNotNone(step)
        made = [(t["speaker"], "No! You are wrong!! Ridiculous.") for t in h.conv["turns"][:4]]
        rows = self.run_(step(made, 4, []))
        turns = [r["turn"] for r in rows]                       # [s3-window] up to the rolled budget
        self.assertEqual(turns, list(range(5, 5 + len(turns))))
        self.assertTrue(6 <= len(turns) <= 11, turns)
        self.assertEqual(h.conv["identity"]["revision"], 2)
        self.assertEqual(len(h.conv["observations"]), 4)
        self.assertEqual(rt.metrics["mode_b_beats"], 1)

    def test_a_story_callback_keeps_the_station_protocol_annotated(self):
        # [s3-calls] a call is built from System 3's own legs now (see
        # test_an_active_call_is_built_from_system3s_call_structure); a story
        # call-back has no protocol by design and keeps the old road
        self.boot(mode="active")
        sheet = ("\n\nTHE RUNNING ORDER OF THIS CALL.\n 1  A  - ANSWER THE RINGING LINE.\n"
                 " 2  C  - BETTY INTRODUCES THEMSELF.\n 3  A  - keeps it going; every turn answers.\n"
                 " 4  C  - BETTY LANDS IT.\n 5  A  - SIGN OFF.")
        h = self.run_(self.station["system3_direct_banter"](**ctx(caller_name="Betty", seats=["A", "B", "C"],
                                                                     call_meta={"story": True}, call_sheet=sheet)))
        self.assertTrue(h.active)
        for line in sheet.splitlines():
            self.assertIn(line, h.sheet)
        self.assertEqual(h.sheet.count("[Say it in"), 5)

    def test_tables_structure_and_settings_apis(self):
        self.boot()
        auth = {"Authorization": "Bearer k"}
        cfg = self.client.get("/api/system3/config").json()
        es1 = next(t for t in cfg["config"]["tables"] if t["id"] == "ES1")
        es2 = dict(es1, label="Emotional Set 2")
        r = self.client.put("/api/system3/tables/ES2", json=es2, headers=auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotEqual(r.json()["hash"], cfg["hash"])
        self.assertEqual(self.client.put("/api/system3/tables/ES2", json=es2).status_code, 401)
        self.assertEqual(self.client.put("/api/system3/tables/ES3", json={"family": "ES"},
                                         headers=auth).status_code, 400)
        steps = cfg["config"]["structure"]["steps"]
        steps[0]["speakerbox"] = ["append"]
        r = self.client.put("/api/system3/structure", json={"steps": steps}, headers=auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["structure"]["steps"][0]["speakerbox"], ["append"])
        self.assertEqual(self.client.delete("/api/system3/tables/CTS1", headers=auth).status_code, 400)
        versions = self.client.get("/api/system3/config").json()["versions"]
        self.assertGreaterEqual(len(versions), 3)
        old = self.client.get("/api/system3/config", params={"hash": cfg["hash"]}).json()
        self.assertEqual(old["hash"], cfg["hash"])
        r = self.client.post("/api/system3/settings", json={"controls": {"sfx_aggression": 0.9}}, headers=auth)
        self.assertEqual(r.json()["settings"]["controls"]["sfx_aggression"], 0.9)
        r = self.client.post("/api/system3/settings", json={"reset": True}, headers=auth)
        self.assertEqual(r.json()["settings"]["controls"], system3.DEFAULT_CONTROLS)
        self.assertEqual(r.json()["settings"]["mode"], "active_selected_roads", "reset keeps the mode")
        self.assertEqual(self.client.post("/api/system3/settings", json={"mode": "loud"},
                                          headers=auth).status_code, 400)
        sim = self.client.post("/api/system3/simulate", json={"turns": 6, "seed": "s", "topic": "mugs"}).json()
        self.assertEqual(len(sim["turns"]), 6)
        self.assertEqual(self.client.post("/api/system3/simulate", json={"keep": True}).status_code, 401)
        self.assertEqual(self.client.post("/api/system3/config/reset", headers=auth).status_code, 200)
        page = self.client.get("/system3")
        self.assertIn("system3.js", page.text)


if __name__ == "__main__":
    unittest.main()
