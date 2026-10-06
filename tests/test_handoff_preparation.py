import ast
import asyncio
import copy
import unittest
from pathlib import Path

import handoff_preparation as hp


class PreparationTests(unittest.IsolatedAsyncioTestCase):
    def test_exact_copy_exemption_is_explicit(self):
        rows = [("A", "Recorded gallery opening."), ("B", "Terms: the price is fifty dollars. Call us.")]
        self.assertEqual([], hp.protected_rows({"first_clip": {"path": "old.wav"}}, rows))
        self.assertEqual([0, 1], hp.protected_rows({"read_exactly": True}, rows))
        self.assertEqual([1], hp.protected_rows({"verbatim": [["head", "the price is fifty dollars."]]}, rows))

    async def test_writer_receipt_and_rolled_mode(self):
        received = []
        async def ask(prompt, **kwargs):
            received.append((prompt, kwargs))
            return "Skip: That photograph feels like a warning. Who chose the lighting?"
        request = {"mode": "respond", "name": "Skip", "seat": "B", "char_budget": 250,
                   "preceding_text": "I am holding up a photograph.", "remaining_ideas": "A long sales pitch.",
                   "turn_id": "child", "parent_turn_id": "parent", "directions": "Ask a pointed question",
                   "rejection": "copies an earlier sentence exactly"}
        words = await hp.write_turn(request, ask, lambda text: text.strip())
        self.assertFalse(words.startswith("Skip:"))
        self.assertIn("trim or drop", received[0][0])
        self.assertIn("250 characters", received[0][0])
        self.assertIn("PREVIOUS ATTEMPT FAILED: copies an earlier sentence exactly", received[0][0])
        self.assertEqual("child", received[0][1]["mark"]["turn_id"])
        self.assertEqual(words, request["writing_receipt"]["clean_result"])
        self.assertIn("Skip:", request["writing_receipt"]["raw_result"])

    def test_changed_script_invalidates_audio_and_preserves_source(self):
        entry = {"script": "A: Original.\nB: Closing.", "script_plain": "A: Plain.\nB: Closing.",
                 "script_tinted": "A: Original.\nB: Closing.", "use": "tinted", "lines": 2,
                 "keys": ["old"], "takes": [{"path": "old.wav"}], "frozen": "old",
                 "turn_source": {"1": "closing.md"}, "turn_dice": {"0": {"roll": 1}, "1": {"roll": 2}}}
        result = {"changed": True, "status": "ready", "original_turn_ids": ["p", "q"],
                  "turn_ids": ["p", "p:h1", "q"],
                  "rows": [("A", "A shorter opening."), ("B", "A new reaction."), ("B", "Closing.")]}
        def invalidate(row):
            for key in ("keys", "takes", "frozen"):
                row.pop(key, None)
        words = hp.apply_script_result(entry, result, invalidate)
        self.assertEqual(3, entry["lines"])
        self.assertNotIn("takes", entry)
        self.assertEqual(words, entry["script_tinted"])
        self.assertEqual("A: Original.\nB: Closing.", entry["handoff_source"]["script"])
        self.assertEqual({"2": "closing.md"}, entry["turn_source"])
        self.assertEqual({"0": {"roll": 1}, "2": {"roll": 2}}, entry["turn_dice"])

    def test_unchanged_script_keeps_recordings(self):
        entry = {"script": "A: Hello.\nB: Hi.", "takes": ["original"], "lines": 2}
        calls = []
        hp.apply_script_result(entry, {"changed": False, "status": "ready",
                                      "rows": [("A", "Hello."), ("B", "Hi.")]}, calls.append)
        self.assertEqual([], calls)
        self.assertEqual(["original"], entry["takes"])

    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        wanted = {"_s3_chapter_voice", "_s3_handoff_rows", "_s3_chapter_prepare", "_s3_split_line", "_banter_air", "_s3_source_chapter"}
        nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
        nodes.extend(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in wanted)
        cls.app_code = compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "app.py", "exec")

    async def test_real_chapter_voice_rerenders_changed_opening_and_child(self):
        calls = []
        async def voices():
            return {"dj": "dill", "cohost": "skip"}
        async def render(text, who, voice, stamp=None):
            calls.append((text, who, voice, stamp["turn_id"]))
            return {"path": f"/voice-media/{stamp['turn_id']}.wav", "sig": "new", "seconds": 5}
        ns = {"session_voices": voices, "configured_radio_voice": lambda who, voice: voice,
              "_s3_chapter_clip_ok": lambda clip: bool(clip and clip.get("path")),
              "_s3_split_render": render}
        exec(self.app_code, ns)
        entry = {"opening": "The entire old long advert.", "voice": "dill",
                 "first_clip": {"path": "/ads-audio/old.wav", "sig": "old", "seconds": 90},
                 "clips": [{"path": "/ads-audio/old.wav", "sig": "old", "seconds": 90}],
                 "rows": [{"who": "dj", "text": "The shorter opening.", "stamp": {"turn_id": "p"}},
                          {"who": "cohost", "text": "A responsive question.", "stamp": {"turn_id": "p:h1"}}]}
        self.assertEqual("", await ns["_s3_chapter_voice"](entry))
        self.assertEqual([("The shorter opening.", "dj", "dill", "p"),
                          ("A responsive question.", "cohost", "skip", "p:h1")], calls)
        self.assertEqual(10.0, entry["seconds"])
        self.assertEqual("/voice-media/p.wav", entry["clips"][0]["path"])
        # A retry reuses these very takes; no new recording or speaker assignment.
        self.assertEqual("", await ns["_s3_chapter_voice"](entry))
        self.assertEqual(2, len(calls))

    async def test_real_chapter_voice_reuses_unchanged_protected_opener(self):
        async def voices():
            return {"dj": "dill"}
        async def render(*args, **kwargs):
            self.fail("unchanged source should not be rendered")
        ns = {"session_voices": voices, "configured_radio_voice": lambda who, voice: voice,
              "_s3_chapter_clip_ok": lambda clip: bool(clip and clip.get("path")),
              "_s3_split_render": render}
        exec(self.app_code, ns)
        entry = {"opening": "Exact sponsor copy.", "first_clip": {"path": "/ads-audio/exact.wav", "seconds": 8},
                 "rows": [{"who": "dj", "text": "Exact sponsor copy.", "stamp": {"turn_id": "p"}}]}
        self.assertEqual("", await ns["_s3_chapter_voice"](entry))
        self.assertEqual("/ads-audio/exact.wav", entry["clips"][0]["path"])
        self.assertTrue(hp.clip_matches_row(entry["clips"][0], entry["rows"][0]))

    async def test_refused_candidate_cannot_be_played_whole(self):
        async def refused(*args, **kwargs):
            return {"status": "refused", "rows": [], "why": "no valid bounded response"}
        ns = {"system3_handoff_exchange": refused, "dj_settings": lambda: {},
              "seat_away_who": lambda: "", "ask_model": None, "writer_turn_clean": str}
        exec(self.app_code, ns)
        with self.assertRaisesRegex(RuntimeError, "no valid bounded response"):
            await ns["_s3_handoff_rows"]({"conversation_id": "x"}, [("A", "Long turn.")], "ad", {})


    def test_receipt_detects_a_later_transcript_change(self):
        entry = {"script": "A: Original.\\nB: Response."}
        hp.apply_script_result(entry, {"changed": False, "status": "ready",
                                      "rows": [("A", "Original."), ("B", "Response.")]}, lambda _e: None)
        self.assertTrue(hp.receipt_matches_script(entry))
        entry["script"] += "\\nA: A later insertion."
        self.assertFalse(hp.receipt_matches_script(entry))

    async def test_standalone_children_record_before_opener(self):
        calls = []
        async def prepare(*args):
            return {"status": "ready", "changed": True,
                    "rows": [("A", "A shorter opening."), ("B", "Why that particular photograph?")],
                    "turn_ids": ["p", "ph1"]}
        async def render(text, who, voice, stamp=None):
            calls.append((text, who, voice, stamp["turn_id"]))
            return {"path": "/voice-media/child.wav", "seconds": 4}
        async def voices():
            return {"dj": "dill", "cohost": "skip"}
        ns = {"_s3_handoff_rows": prepare, "_s3_split_render": render, "session_voices": voices,
              "dj_settings": lambda: {"host_name": "Dill", "cohost_name": "Skip"},
              "configured_radio_voice": lambda who, voice: voice}
        exec(self.app_code, ns)
        # exec installs the real row driver too; use a fake runtime door for this isolated case.
        async def runtime(*args, **kwargs):
            return await prepare()
        ns.update(system3_handoff_exchange=runtime, seat_away_who=lambda: "",
                  ask_model=None, writer_turn_clean=str)
        head, stamp, rest = await ns["_s3_split_line"]("ad", "The entire old long advert.", "dj", "dill",
                                                       {"conversation_id": "x", "turn_id": "p"}, None)
        self.assertEqual("A shorter opening.", head)
        self.assertEqual("p", stamp["turn_id"])
        self.assertEqual("cohost", rest[0]["who"])
        self.assertEqual("ph1", rest[0]["stamp"]["turn_id"])
        self.assertEqual([("Why that particular photograph?", "cohost", "skip", "ph1")], calls)

    async def test_standalone_final_round_chunk_does_not_reroll(self):
        async def reviewed(*args):
            return True
        async def runtime(*args, **kwargs):
            self.fail("already finalized transport chunk must not enter the one-row writer")
        ns = {"system3_handoff_turn_ready": reviewed, "system3_handoff_exchange": runtime}
        exec(self.app_code, ns)
        self.assertIsNone(await ns["_s3_split_line"]("banter", "A recorded transport chunk.", "dj", "dill",
                                                   {"conversation_id": "round", "turn_id": "p"}, None))

    async def test_graph_disabled_prepared_ad_still_hands_off(self):
        calls = []
        async def runtime(*args, **kwargs):
            return {"status": "ready", "changed": True, "policy_hash": "policy",
                    "rows": [("A", "Look at this photograph."), ("B", "The lighting is unsettling.")],
                    "turn_ids": ["p", "ph1"], "traces": []}
        async def voices():
            return {"dj": "dill", "cohost": "skip"}
        async def render(text, who, voice, stamp=None):
            calls.append((text, who, stamp["turn_id"]))
            return {"path": f"/voice-media/{stamp['turn_id']}.wav", "sig": "new", "seconds": 5}
        def note(entry, state, why):
            entry["state"] = state
        ns = {"system3_line_chapter": lambda _stamp: {"chapter": False, "road": "ad_spot", "turns": 1},
              "system3_handoff_exchange": runtime, "session_voices": voices,
              "dj_settings": lambda: {"host_name": "Dill", "cohost_name": "Skip"},
              "seat_away_who": lambda: "", "configured_radio_voice": lambda who, voice: voice,
              "_s3_chapter_clip_ok": lambda clip: bool(clip and clip.get("path")),
              "_s3_split_render": render, "_s3_chapter_note": note,
              "WritingDeferred": type("WritingDeferred", (Exception,), {}),
              "ask_model": None, "writer_turn_clean": str}
        exec(self.app_code, ns)
        entry = {"stamp": {"conversation_id": "x", "turn_id": "p"}, "state": "pending", "who": "dj",
                 "kind": "ad", "opening": "A saved ninety-second gallery advert.",
                 "first_clip": {"path": "/ads-audio/old.wav", "seconds": 90}}
        self.assertTrue(await ns["_s3_chapter_prepare"](entry))
        self.assertEqual("prepared", entry["state"])
        self.assertEqual(2, len(entry["rows"]))
        self.assertEqual(10.0, entry["seconds"])
        self.assertEqual([("Look at this photograph.", "dj", "p"),
                          ("The lighting is unsettling.", "cohost", "ph1")], calls)
        self.assertNotIn("no_chapter", entry)

    async def test_saved_round_is_withheld_if_final_review_refuses(self):
        async def runtime(*args, **kwargs):
            return {"status": "refused", "rows": [], "why": "already committed"}
        ns = {"system3_handoff_exchange": runtime, "dj_settings": lambda: {},
              "seat_away_who": lambda: "", "ask_model": None, "writer_turn_clean": str,
              "banter_turns": lambda *args: [("A", "Original."), ("B", "Response.")],
              "_banter_no": lambda why: {"refused": why}}
        exec(self.app_code, ns)
        # _banter_air calls the entry adapter, which is deliberately a fake here;
        # the refusal must return before forgotten/repeat or playback checks.
        async def entry_review(*args):
            raise RuntimeError("already committed")
        ns["_s3_handoff_entry"] = entry_review
        entry = {"script": "A: Original.\\nB: Response.", "system3": {"mode": "active", "conversation_id": "x"}}
        got = await ns["_banter_air"](entry, None, ready_takes=[{"path": "old.wav"}])
        self.assertIn("already committed", got["refused"])


    async def test_graph_disabled_source_keeps_its_original_roulette_identity(self):
        async def take(entry, **kwargs):
            return entry
        ns = {"system3_line_chapter": lambda _stamp: {"chapter": False, "road": "ad_spot", "turns": 1},
              "_s3_chapter_shelf": lambda: {}, "_S3_CHAPTER_LIVE": ("pending", "prepared"),
              "_s3_chapter_new": lambda key, **fields: dict(key=key, **fields),
              "_s3_chapter_superseded": lambda _entry: False, "_s3_chapter_take": take}
        exec(self.app_code, ns)
        stamp = {"conversation_id": "original-cid", "turn_id": "p", "mode": "active"}
        got = await ns["_s3_source_chapter"](
            "ad:source", "ad_spot", "ad", "dj", "A recorded opening.",
            {"path": "/ads-audio/source.wav"}, "A gallery sale.", "produced_ad", stamp=stamp)
        self.assertEqual(stamp, got["stamp"])
        self.assertEqual("original-cid", got["sid"])


if __name__ == "__main__":
    unittest.main()
