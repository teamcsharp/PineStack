"""[s3-split] app.py's doors for the SPLIT node: dj_speak speaks a shared-out
read part by part, in order, under one floor, with the SFX cadence held until
the last part; the manager's page keeps its parts; the caps that cut a line
mid-word are gone; a gold bar's take must hold its words; and the page players
let a sounding clip finish (#1237 cuts only what is still queued).

Imports app (run in the container). Nothing here touches the station's data
dir or renders a voice: every store path is a temp file and every door that
would speak is a stand-in."""
import asyncio
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app

ROOT = Path(app.__file__).resolve().parent
STAMP = {"conversation_id": "c1", "mode": "active", "turn_id": "c1:t00", "road": "ad_spot"}


def part(n, of, who, text, whole="ONE. TWO. THREE."):
    return {"part": n, "of": of, "who": who, "name": who.title(), "voice": "", "text": text, "clip": None,
            "whole": whole, "stamp": dict(STAMP, turn_id="c1:t00s%d" % n, split={"part": n, "of": of})}


class ToolTests(unittest.TestCase):
    def test_the_patch_is_applied(self):
        spec = importlib.util.spec_from_file_location("system3_split_patch", ROOT / "tools" / "system3_split_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = (ROOT / "app.py").read_text(encoding="utf-8")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)))


class DjSpeakTests(unittest.TestCase):
    def run_speak(self, first_said="ONE.", parts=None):
        calls = []

        async def fake(kind, track=None, **kw):
            box = app._S3_SPLIT_TAIL.get()
            if not calls and isinstance(box, dict) and not box.get("claimed"):
                box["claimed"] = True
                box["parts"] = list(parts or [])
                calls.append(("first", kw.get("line"), app._S3_SPLIT_HOLD.get()))
                return first_said
            calls.append((kw.get("who"), kw.get("line"), app._S3_SPLIT_HOLD.get(), kw.get("checked"),
                          kw.get("remember_text"), (kw.get("system3") or {}).get("turn_id"), kw.get("round_as")))
            return kw.get("line") or ""

        async def take(label=""):
            return False

        with mock.patch.object(app, "_dj_speak_floorless", fake), \
                mock.patch.object(app, "_floor_take", take), \
                mock.patch.object(app, "radio_paused", lambda: False):
            said = asyncio.run(app.dj_speak("ad", None, line="ONE. TWO. THREE.", round_as="ad"))
        return said, calls

    def test_the_parts_go_out_in_order_after_the_first(self):
        said, calls = self.run_speak(parts=[part(2, 3, "cohost", "Give me that. TWO."), part(3, 3, "drop", "My turn. THREE.")])
        self.assertEqual(said, "ONE. TWO. THREE.")          # the caller keeps the whole read (the ad book)
        self.assertEqual([c[0] for c in calls], ["first", "cohost", "drop"])
        self.assertEqual([c[2] for c in calls[1:]], [True, False])     # the SFX cadence waits for the last part
        self.assertEqual([c[3] for c in calls[1:]], [True, True])
        self.assertEqual([c[4] for c in calls[1:]], ["Give me that. TWO.", "My turn. THREE."])
        self.assertEqual([c[5] for c in calls[1:]], ["c1:t00s2", "c1:t00s3"])
        self.assertEqual([c[6] for c in calls[1:]], ["ad", "ad"])

    def test_a_read_that_is_not_split_is_one_call(self):
        said, calls = self.run_speak(parts=[])
        self.assertEqual(said, "ONE.")
        self.assertEqual(len(calls), 1)

    def test_a_first_part_that_did_not_go_out_takes_the_rest_with_it(self):
        said, calls = self.run_speak(first_said="", parts=[part(2, 3, "cohost", "TWO."), part(3, 3, "drop", "THREE.")])
        self.assertEqual(said, "")
        self.assertEqual(len(calls), 1)

    def test_a_part_that_fails_stops_the_read_there(self):
        parts = [part(2, 3, "cohost", ""), part(3, 3, "drop", "THREE.")]
        parts[0]["text"] = "TWO."
        calls = []

        async def fake(kind, track=None, **kw):
            calls.append(kw.get("who"))
            return ""

        async def take(label=""):
            return False

        with mock.patch.object(app, "_dj_speak_floorless", fake), mock.patch.object(app, "_floor_take", take), \
                mock.patch.object(app, "radio_paused", lambda: False):
            said = asyncio.run(app._s3_split_speak("ad", None, parts))
        self.assertEqual(said, [])
        self.assertEqual(calls, ["cohost"])


class SplitDoorTests(unittest.TestCase):
    def test_the_node_is_asked_and_the_later_parts_are_made_ahead(self):
        asked = {}

        def ask(stamp, text, **kw):
            asked.update(kw, text=text, stamp=stamp)
            return {"split": True, "whole": "ONE. TWO.", "parts": [
                {"part": 1, "of": 2, "who": "dj", "text": "ONE.", "body": "ONE.", "stamp": dict(STAMP, split={"part": 1})},
                {"part": 2, "of": 2, "who": "drop", "voice": "sam-voice", "name": "Sam", "text": "Give me that. TWO.",
                 "body": "TWO.", "stamp": dict(STAMP, turn_id="c1:t00s2", split={"part": 2})}]}

        async def render(text, who, voice):
            return {"path": "/media/x.wav", "sig": "s", "who": who, "voice": voice, "text": text}

        async def voices():
            return {"dj": "dj-voice"}

        with mock.patch.dict(app.__dict__, {"system3_split_line": ask}), \
                mock.patch.object(app, "_s3_split_render", render), \
                mock.patch.object(app, "session_voices", voices), \
                mock.patch.object(app, "_pantry_key_ready", lambda key: True), \
                mock.patch.object(app, "seat_away_who", lambda: ""):
            got = asyncio.run(app._s3_split_line("ad", "ONE. TWO.", "dj", "dj-voice", dict(STAMP), None))
        first, stamp, rest = got
        self.assertEqual(first, "ONE.")
        self.assertEqual(stamp["split"]["part"], 1)
        self.assertTrue(asked["prepared"])                       # recorded, and still split
        self.assertEqual(len(rest), 1)
        self.assertEqual(rest[0]["voice"], "sam-voice")
        self.assertEqual(rest[0]["clip"]["voice"], "sam-voice")
        self.assertEqual(rest[0]["whole"], "ONE. TWO.")

    def test_no_node_no_split(self):
        with mock.patch.dict(app.__dict__, {"system3_split_line": lambda *a, **k: {"split": False, "why": "short"}}), \
                mock.patch.object(app, "_pantry_key_ready", lambda key: False):
            self.assertIsNone(asyncio.run(app._s3_split_line("ad", "ONE.", "dj", "v", dict(STAMP), None)))
            self.assertIsNone(asyncio.run(app._s3_split_line("ad", "ONE.", "dj", "v", {}, None)))


class PageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(app, "UPSTAIRS_PATH", Path(self.tmp.name) / "upstairs_pages.json")
        p.start()
        self.addCleanup(p.stop)

    def test_the_page_keeps_its_words_its_node_and_its_parts(self):
        long = "The manager is not happy about the coffee machine. " * 60
        row = app.upstairs_save(long, "gripe", "context")
        self.assertEqual(row["text"], long)                       # no 2,000 cap
        app.upstairs_update(row["id"], system3=dict(STAMP), split={"whole": long, "parts": [{"part": 2}]})
        kept = next(r for r in app.upstairs_list() if r["id"] == row["id"])
        self.assertEqual(kept["system3"]["conversation_id"], "c1")
        self.assertEqual(kept["split"]["parts"], [{"part": 2}])

    def test_a_page_the_node_shares_out_keeps_part_one_for_his_recording(self):
        row = app.upstairs_save("ONE. TWO.", "gripe", "context")

        def ask(stamp, text, **kw):
            return {"split": True, "whole": text, "parts": [
                {"part": 1, "of": 2, "who": "manager", "text": "ONE.", "body": "ONE.", "stamp": dict(stamp, split={"part": 1})},
                {"part": 2, "of": 2, "who": "cohost", "name": "Skip", "text": "If I may. TWO.", "body": "TWO.",
                 "stamp": dict(stamp, turn_id="c1:t00s2", split={"part": 2})}]}

        handle = mock.Mock(stamp=dict(STAMP))
        with mock.patch.dict(app.__dict__, {"system3_split_line": ask}), \
                mock.patch.object(app, "seat_away_who", lambda: ""):
            asyncio.run(app._s3_split_page(row, handle, "ONE. TWO."))
        self.assertEqual(row["text"], "ONE.")
        kept = next(r for r in app.upstairs_list() if r["id"] == row["id"])
        self.assertEqual(kept["text"], "ONE.")
        self.assertEqual(kept["split"]["whole"], "ONE. TWO.")
        self.assertEqual(kept["split"]["parts"][0]["who"], "cohost")
        self.assertEqual(kept["system3"]["split"]["part"], 1)


class CapTests(unittest.TestCase):
    def test_the_ad_book_keeps_a_read_whole(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        long = "Buy the thing, it is very good and it is on sale tonight. " * 40
        with mock.patch.object(app, "ADS_PATH", Path(tmp.name) / "ad_reads.json"):
            entry = app.ad_save("thing", long)
            self.assertEqual(entry["text"], long)
            app.ad_update(entry["id"], text=long + " Really.", product="x" * 2000)
            kept = next(r for r in app.ad_list() if r["id"] == entry["id"])
        self.assertEqual(kept["text"], long + " Really.")
        self.assertEqual(len(kept["product"]), 1200)

    def test_the_script_ledger_keeps_a_line_whole(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"text": str(row.get("text") or ""),                              # [s3-split]', src)
        self.assertNotIn('            "text": str(row.get("text") or "")[:2000],\n', src)


class GoldTests(unittest.TestCase):
    def test_only_a_take_that_holds_its_turn_is_a_bar(self):
        turn = "It's a girl. Congratulations. You are about to become someone's parent tonight."
        self.assertTrue(app._gold_take_holds({"turn_text": turn, "chunk": turn}))
        self.assertFalse(app._gold_take_holds({"turn_text": turn, "chunk": "someone's parent tonight."}))
        self.assertTrue(app._gold_take_holds({"chunk": "a lone chunk"}))

    def test_a_banked_tail_loses_its_take(self):
        self.assertFalse(app._gold_take_fits({"text": "x " * 81, "seconds": 2.43}))    # 162 characters in 2.4 s
        self.assertTrue(app._gold_take_fits({"text": "x " * 81, "seconds": 9.0}))
        self.assertTrue(app._gold_take_fits({"text": "anything", "seconds": 0}))
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "gold_bars.json"
        path.write_text(json.dumps([{"key": "a", "text": "x " * 81, "path": "a.wav", "seconds": 2.43},
                                    {"key": "b", "text": "fine words here", "path": "b.wav", "seconds": 1.5}]))
        with mock.patch.object(app, "GOLD_PATH", path), mock.patch.dict(app._GOLD, {"loaded": False, "rows": []}):
            rows = app._gold_rows()
            self.assertEqual([r["path"] for r in rows], ["", "b.wav"])     # the take goes, the line stays


class PagePlayerTests(unittest.TestCase):
    def test_a_sounding_clip_is_never_stopped_by_its_record_cut(self):
        for name in ("CONTROL_PANEL_HTML", "RADIO_PAGE_HTML"):
            page = getattr(app, name)
            self.assertIn("data.cut_ids", page)
            self.assertIn("[s3-split]", page)
        self.assertNotIn("djVoiceNow && cutIds.indexOf", app.CONTROL_PANEL_HTML)
        self.assertIn("djVoiceQueue.splice(i, 1);", app.CONTROL_PANEL_HTML)      # the queued ones still go
        self.assertNotIn('voiceAck(voiceCurrentClip, "error", "cut with its record (#1237)")', app.RADIO_PAGE_HTML)
        self.assertIn("voiceQueue.splice(i, 1);", app.RADIO_PAGE_HTML)


if __name__ == "__main__":
    unittest.main()
