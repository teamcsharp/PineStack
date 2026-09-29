"""[s3-account] app.py's half of the origin ledger: the booth ring names who
appended every row, the keeper and the hourly housekeeping feed the ledger, the
script ledger tells it each row's place, the screenplay route answers any aged
line on ?origin=1, and the rogue roads measured on the air are closed at their
source (the emergency pair's welded clip, the endless set's clip, the SFX Guy's
quip shelf). Imports app (run in the container); nothing touches the station's
data dir: every ledger here is a temp file and every write door is patched."""
import asyncio
import importlib.util
import inspect
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import app
import system3_origin as so

ROOT = Path(app.__file__).resolve().parent


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Ring(unittest.TestCase):
    def test_the_booth_ring_names_the_appender(self):
        self.assertIsInstance(app._RADIO["chat"], app._OriginRing)
        ring = app._OriginRing()

        def a_producer():
            ring.append({"id": "x"})
            ring.extend([{"id": "y"}])
            ring.insert(0, {"id": "w"})
        a_producer()
        self.assertTrue(all(r["origin_path"].startswith("a_producer<") for r in ring))
        ring.append({"id": "z", "origin_path": "kept"})
        self.assertEqual(ring[-1]["origin_path"], "kept")
        del ring[:-2]
        self.assertIsInstance(ring, app._OriginRing)
        ring.append("not a row")                       # anything else passes untouched
        self.assertEqual(ring[-1], "not a row")

    def test_every_ring_reset_keeps_the_ring(self):
        for fn in (app.clean_station_backlog, app.dj_start, app.dj_chat_delete_api):
            self.assertIn("_OriginRing(", inspect.getsource(fn), fn.__name__)

    def test_real_append_sites_are_named_and_traced(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(app._RADIO, {"chat": app._OriginRing(), "ad_now": {}, "voice_to": "box"}):
            app._desk_sound("☎ the phone ringing", 2.0)
            app.ad_booth_row("\U0001f4e3 sponsor spot — OLLAMA", product="OLLAMA")
            ring = app._RADIO["chat"]
            self.assertTrue(ring[0]["origin_path"].startswith("_desk_sound<"))
            self.assertTrue(ring[1]["origin_path"].startswith("ad_booth_row<"))
            ring[0]["id"] = "desk1"
            led = so.OriginLedger(Path(d) / "o.sqlite3")
            led.tick(list(ring), now=time.time() + so.MARKER_LINK_S + 60)
            desk = led.get("desk1")
            self.assertEqual((desk["verdict"], desk["forced"]["road"]), ("forced", "desk"))
            listing = led.get(ring[1]["id"])
            self.assertEqual(listing["verdict"], "forced")          # its spot never aired here
            self.assertEqual(listing["forced"]["road"], "desk label")
            led.close()


class Wiring(unittest.TestCase):
    def test_installed_lazily_and_fed_by_the_keeper(self):
        self.assertIsInstance(app._ORIGIN_LEDGER, so.OriginLedger)
        self.assertIsNone(app._ORIGIN_LEDGER._db)                   # nothing opened at import
        for hook in ("origin_keeper_tick", "origin_housekeeping", "origin_ledger_note",
                     "origin_side_note", "origin_lookup"):
            self.assertTrue(callable(getattr(app, hook)), hook)
        self.assertIn("origin_keeper_tick", inspect.getsource(app.airlog_keeper))
        self.assertIn("asyncio.to_thread(_otick", inspect.getsource(app.airlog_keeper))
        self.assertIn("origin_housekeeping", inspect.getsource(app.airlog_compact_all))
        paths = {getattr(r, "path", "") for r in app.app.routes}
        for p in ("/api/system3/origin/{line_id}", "/api/system3/untraced", "/api/system3/coverage",
                  "/system3-coverage"):
            self.assertIn(p, paths)

    def test_the_script_ledger_tells_the_origin_ledger(self):
        seen = mock.Mock()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(app, "SCRIPT_LEDGER_PATH", Path(d) / "sl.jsonl"), \
                mock.patch.object(app, "origin_ledger_note", seen), \
                mock.patch.object(app, "system3_observe_ledger", None, create=True), \
                mock.patch.object(app, "system3_segment_block", None, create=True):
            rows = [{"line_id": "l1", "who": "dj", "text": "hi",
                     "system3": {"conversation_id": "c1", "turn_id": "c1:t00"}}]
            self.assertEqual(app.script_ledger_commit("sid1", rows, "banter", block=77, at=5.0), 77)
        args = seen.call_args[0]
        self.assertEqual((args[0], args[1], args[2], args[3]), (77, 5.0, "sid1", "banter"))
        self.assertEqual(args[5][0]["line_id"], "l1")

    def test_screenplay_answers_any_aged_line_only_when_asked(self):
        chain = {"line_id": "old1", "verdict": "forced", "nodes": [{"node": "forced", "road": "gold"}]}
        with mock.patch.object(app, "screenplay_hour", mock.AsyncMock(return_value={"provenance": {}})), \
                mock.patch.object(app, "_screenplay_span", lambda k: (k, 0.0, 1.0)), \
                mock.patch.object(app, "origin_lookup", lambda lid: chain if lid == "old1" else None):
            got = asyncio.run(app.api_screenplay_line("h", "old1", authorization=None, origin=1))
            self.assertEqual(got["provenance"]["origin"]["verdict"], "forced")
            with self.assertRaises(app.HTTPException):                      # default: not in this hour
                asyncio.run(app.api_screenplay_line("h", "old1", authorization=None, origin=0))
            with self.assertRaises(app.HTTPException):
                asyncio.run(app.api_screenplay_line("h", "nope", authorization=None, origin=1))


class RogueRoadsClosed(unittest.TestCase):
    def test_the_emergency_pair_keeps_its_clip_dice_and_names_its_trigger(self):
        src = inspect.getsource(app.continuity_air)
        self.assertIn('"sfx_roll", "poster", "sfx_dir", "sfx_video_id"', src)
        self.assertIn('"origin_forced": {"road": "emergency_host"', src)
        self.assertIn('if _cont_row.get("who") not in ("dj", "cohost") and not _cont_row.get("system3")', src)

    def test_a_cadence_clip_names_its_folder_on_both_roads(self):
        self.assertIn('"sfx_dir": sample.parent.name or "sfx"', inspect.getsource(app._sfx_cadence_additions_inner))
        self.assertIn('"sfx_dir")}', inspect.getsource(app._speak_turns_floorless))

    def test_the_endless_sets_row_carries_the_dice_that_chose_it(self):
        sample = Path("/tmp/samples/vine/92 did you.mp4")
        with mock.patch.dict(app._RADIO, {"chat": app._OriginRing()}), \
                mock.patch.object(app, "sfx_id", lambda p: "abc123"), \
                mock.patch.object(app, "media_sign", lambda k: "sig"), \
                mock.patch.object(app, "note_activity", lambda *a, **k: None), \
                mock.patch.object(app, "sfx_history_add", lambda *a, **k: None):
            app._sfx_roll_note(sample, "book", {"label": "vine", "dice": 37, "of": 34, "index": 13},
                               {"label": "92 did you", "dice": 40, "of": 489, "index": 194}, 1)
            app._sfx_cycle_note(sample, 4.0, time.time(), "dj")
            row = app._RADIO["chat"][-1]
        self.assertEqual(row["sfx_roll"]["clip"]["dice"], 40)
        self.assertEqual(row["origin_path"].split("<")[0], "_sfx_cycle_note")
        rec = so.build(dict(row, id="cyc1", aired="page"))["compact"]
        self.assertEqual((rec["road"], rec["verdict"]), ("board clip", "rolled"))

    def test_the_quip_draw_names_its_shelf(self):
        class Chooser:
            def __init__(self):
                self.draws, self.said = [], None

            def takes(self, kind, available):
                return False

            def pick(self, label, candidates):
                self.draws.append({"pool": label, "of": len(candidates)})
                return 1

            def done(self, line, kind):
                self.said = (line, kind)
        ch = Chooser()
        with mock.patch.object(app, "sfxguy_quips", lambda v="": ["one", "two", "three"]), \
                mock.patch.object(app, "_sfxguy_said", lambda: {}), \
                mock.patch.object(app, "_sfxguy_stamp", lambda line: None), \
                mock.patch.object(app, "crystal_active", lambda: []), \
                mock.patch.object(app, "_SFXGUY_WARPED", [1] * 8), \
                mock.patch.object(app, "_SFXGUY_NEWS", [{"line": "x"}]):
            line = app.sfxguy_line("vl_test", "", director=ch)
        self.assertEqual((line, ch.said[1]), ("two", "quip"))
        st = ch.draws[-1]["store"]
        self.assertEqual(st["kind"], "sfx guy quip shelf")
        self.assertTrue(st["db"].endswith(".json"))
        self.assertEqual(st["shelf"], 3)

    def test_the_sponsor_listing_carries_its_roll(self):
        self.assertIn('_sponsor_roll = _s3_spin_roll("ad.sponsor_service")', inspect.getsource(app.dj_service_ad))
        self.assertIn('_sp_row["s3_roll"] = _sponsor_roll', inspect.getsource(app.dj_service_ad))


class Matcher(unittest.TestCase):
    def test_each_pick_keeps_its_working_by_clip_id(self):
        import sfx_match
        c1 = sfx_match.Cand(0, 11, 0, "adamcurtis", 2.28, [("fury", "line"), ("rage", "context"),
                                                          ("anger", "context")])
        c2 = sfx_match.Cand(1, 12, 1, "vine", 1.9, [("fury", "line")])
        said = {"line": "she was furious, pure fury", "context": "the anger of the night",
                "source": "what is being said at that moment"}
        with mock.patch.object(app, "sfx_id", lambda p: "k-" + Path(str(p)).stem):
            app._origin_match_note("/s/adamcurtis/73 Her fury grew.mp4", said, [c1, c2], [c1, c2], 1,
                                   "sting", sfx_match.explain(c1), 2.28, {"banned": 1})
        got = app._SFX_MATCH_PICKS["k-73 Her fury grew"]
        self.assertEqual((got["line"], got["line_source"], got["cands"], got["tied"], got["eligible"]),
                         ("she was furious, pure fury", "what is being said at that moment", 2, 2, 1))
        self.assertEqual(got["words"], {"line": ["fury"], "context": ["anger"], "senses": ["rage"], "folder": []})
        self.assertEqual([c["rowid"] for c in got["candidates"]], [11, 12])
        self.assertEqual(got["removed"], {"banned": 1})

    def test_the_endless_sets_matched_clip_is_a_system3_draw(self):
        src = inspect.getsource(app.sfx_match_video_pick)
        self.assertIn('_S3ClipDice("sfx.match_video"', src)
        self.assertIn("_origin_match_note(path, said, cands, tied, len(_eligible)", src)
        self.assertIn('_removed["just heard"] += 1', inspect.getsource(app.sfx_match_sting_pick))

    def test_records_and_live_sets_get_an_origin_key(self):
        src = inspect.getsource(app.dj_on_air)
        self.assertIn('("live:%s:" % _ev) if track.get("pinelive") else "rec:"', src)
        self.assertIn('"s3_spin": (dict(track["s3_spin"])', src)


class Tool(unittest.TestCase):
    def test_the_patch_tool_reads_applied(self):
        tool = load_tool("s3_origin_patch")
        text = (ROOT / "app.py").read_text(encoding="utf-8")
        applied, missing = tool.check(text)
        self.assertEqual((applied, missing), (len(tool.EDITS), []))


if __name__ == "__main__":
    unittest.main()
