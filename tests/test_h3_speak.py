"""[h3-speak] The hourly H3 video's spoken dialogue is the H3SPEAK node.

The operator saw H3 make people say "105 What is that man 390 wider system of
Song analysis complete: Ring System" - the chat ring's clip titles and status
rows glued into {conversation} - and "{station}" sent as written. Now System 3
rolls what people were heard saying on air (lines and monologues, leaned on by
their feeling), then how many whole sentences, over a Speakerbox document when
no aired line passes, FORCED when nothing does; every slot is filled and the
last gate refuses a prompt with "{...}" or glued titles.

Pure rules (h3_speak.py) and the station's own code exec'd out of app.py with
the presets harness (tests/test_h3_prompt_presets.station) - no station, no
GPU, no render."""
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import h3_speak  # noqa: E402
import test_h3_prompt_presets as presets  # noqa: E402 - the presets harness, reused

APP_TEXT = presets.APP_TEXT
FLAGS = presets.FLAGS
OLD_FRAGMENTS = ["105 What is that man 390 wider system of Song analysis complete: Ring System",
                 "39 time moves at 79 into weapons Song analysis complete: 乾いた塗料",
                 "Image analysis complete: PineBox_00233_.png \U0001f50a 732 yes."]


def block_source():
    start = APP_TEXT.index("# --- [h3-speak] THE HOURLY VIDEO'S DIALOGUE")
    end = APP_TEXT.index("# --- [h3-prompts] THE HOURLY PROMPTS", start)
    return APP_TEXT[start:end]


def aired(i, who, text, sid="r1", at=None, kind="call", name=""):
    return {"id": "line%03d" % i, "who": who, "name": name or who, "sid": sid, "kind": kind, "round": "banter",
            "text": text, "air_at": at if at is not None else time.time() - 600 + i, "aired": "stream",
            "heard_ack_at": time.time()}


AIR = [aired(1, "board", "\U0001f50a 105 What is that man", kind="sfx"),
       aired(2, "dj", "I cannot believe the manager took the last coffee again tonight!"),
       aired(3, "cohost", "He says it is for morale, which is the funniest thing I have heard all week."),
       aired(4, "caller", "I have been listening since midnight and I love you both.", sid="r2", name="Dana"),
       aired(5, "caller", "Please never stop doing this show, it keeps me sane on the night shift.", sid="r2",
             name="Dana"),
       aired(6, "analysis", "Song analysis complete: Ring System", kind="song_analysis"),
       aired(7, "dj", "You're listening to Pine Box FM.", kind="emergency_host"),
       aired(8, "third", "39 time moves at 79 into weapons"),
       aired(9, "dj", "That was the best night we have had in a month, and I mean that.")]


def ns_with_block(tmp, air=None, docs=None, s3=None, ledger=None):
    s3 = s3 or presets.FakeSystem3()
    ns = presets.station(tmp, s3=s3)
    import es_voice
    rows = list(AIR if air is None else air)

    def airlog_rows(since, until, who=None, kinds=None, rounds=None, quiet=False):
        whos = set(who or [])
        return [dict(r) for r in rows if since <= r["air_at"] < until and (not whos or r["who"] in whos)]

    docs = docs or {}
    ns.update({"H3_HOURLY_WINDOW_S": 10.0, "AIRLOG_AIRED": ("box", "stream", "both"), "h3_speak": h3_speak,
               "_es_voice": es_voice, "dj_settings": lambda: {"station_name": "The Box FM"},
               "airlog_rows": airlog_rows, "_review_s3_db": lambda: None,
               "speakbox_files": lambda: [Path(tmp) / n for n in docs], "mind_weights": lambda rid="": {},
               "speakbox_uses": lambda rid="": {}, "speakbox_weight": lambda n, w=None, rid="", uses=None: 50,
               "_H3_HOURLY_ROLLS": {}})
    for name, text in docs.items():
        (Path(tmp) / name).write_text(text, encoding="utf-8")
    for name in ("_xtts_sanitize", "s3_choice", "h3_hourly_roll_note"):
        exec(compile(presets.function_source(name), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102
    exec(compile(block_source(), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)  # noqa: S102
    return ns


def run(coro):
    import asyncio
    return asyncio.run(coro)


class Rules(unittest.TestCase):
    def test_the_fragments_that_went_to_air_are_refused(self):
        for frag in OLD_FRAGMENTS:
            self.assertTrue(h3_speak.sentence_why(frag), frag)
            self.assertTrue(h3_speak.fragment_why(frag), frag)
        for bad, why in (("Make a {station} stinger now please.", "placeholder"),
                         ("Check out https://example.com for more tonight.", "web address"),
                         ("The Whole World Is A Stage Take Seven.", "title"),
                         ("happened and why and what did he say.", "mid-sentence"),
                         ("No idea.", "fragment"),
                         ("Host: we are back on the air tonight.", "speaker label"),
                         ("Download complete, the tape is ready now.", "status")):
            self.assertIn(why, h3_speak.sentence_why(bad), bad)
        self.assertEqual(h3_speak.sentence_why("I think the Army is going to quarantine this whole town."), "")

    def test_a_sentence_split_across_timestamps_comes_back_whole(self):
        doc = ("# Title\n\n**Source:** x.mp4\n\n### [0:00]\n\nI want roving death squads\n\n### [0:47]\n\n"
               "patrolling the dome by morning. Who is hurt tonight?\n\n## Next source\n\nAnother one begins here.")
        self.assertEqual(h3_speak.split_sentences(doc), ["I want roving death squads patrolling the dome by morning.",
                                                         "Who is hurt tonight?", "Another one begins here."])

    def test_runs_are_side_by_side_and_fit_the_seconds(self):
        cands = [(0, "One two three four."), (1, "Five six seven eight."), (3, "Nine ten eleven twelve.")]
        self.assertEqual(h3_speak.runs(cands, 2, 8), [["One two three four.", "Five six seven eight."]])
        self.assertEqual(h3_speak.runs(cands, 2, 7), [])
        self.assertEqual(h3_speak.word_cap(10.0), 19)
        self.assertEqual(h3_speak.word_cap(10.0, 7), 12)

    def test_a_monologue_is_one_speakers_run_joined(self):
        rows = [aired(1, "dj", "This is the start of a long read and"), aired(2, "dj", "it ends right here tonight."),
                aired(3, "cohost", "Well, I hear you loud and clear.")]
        items = h3_speak.air_items(rows, 19)
        self.assertEqual([i["turns"] for i in items], [2, 1])
        self.assertEqual(items[0]["cands"][0][1], "This is the start of a long read and it ends right here tonight.")

    def test_the_gate(self):
        self.assertIn("{station}", h3_speak.gate("A {station} ad", "Hello there, my friend.", strict=True))
        self.assertIn("status", h3_speak.gate("Song analysis complete: Ring System", ""))
        self.assertIn("not whole", h3_speak.gate("An ad", "105 What is that man", strict=True))
        self.assertIn("conversation slot carries", h3_speak.gate("An ad", "Please tune in to us tonight.",
                                                                 conversation=OLD_FRAGMENTS[1], strict=True))
        self.assertIn("glued", h3_speak.fragment_why("105 What is that man 390 wider system of"))
        self.assertEqual(h3_speak.gate("An ad [0 to 4.4 seconds] <d>[English] Hi.</d>", "Please tune in to us tonight.",
                                       conversation="Please tune in to us tonight.", strict=True), "")
        self.assertEqual(h3_speak.gate("make an ad for 1990 cars in 2024", ""), "", "a listener's own words pass")


class Node(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def hour(self, ns, speech="please please support the pine box radio."):
        goal_tpl = ("Make a short, funny but professional {station} sponsor stinger that begs for people to tune in "
                    "while crying about this hour's conversation: {conversation}")
        store = ns["_h3_prompts_seed"]()
        store["presets"][0].update({"name": "Begging", "goal": goal_tpl, "speech": speech})
        ns["_H3_PROMPTS_MEM"][0] = store
        pool = run(ns["h3_speak_gather"]())
        ns["_H3_SPEAK_POOL"][0] = pool
        return ns["h3_prompts_hour"](" ".join(OLD_FRAGMENTS[:2]), "Ring System")

    def test_what_people_said_on_air_is_rolled_and_recorded(self):
        ns = ns_with_block(self.dir)
        entry = self.hour(ns)
        sp = entry["speak"]
        self.assertEqual((sp["verdict"], sp["source"]), ("rolled", "air"))
        self.assertNotIn("{", entry["goal"])
        self.assertIn("The Box FM sponsor stinger", entry["goal"])
        for frag in ("105 What", "390 wider", "analysis complete", "39 time"):
            self.assertNotIn(frag, entry["goal"])
        self.assertTrue(sp["line"].startswith("Please please support the pine box radio. "))
        self.assertEqual(h3_speak.speech_why(sp["line"]), "")
        self.assertLessEqual(len(sp["line"].split()), h3_speak.word_cap(10.0))
        self.assertEqual(entry["conversation"], sp["conversation"])
        self.assertTrue(sp["origin"]["line_ids"])
        self.assertTrue(set(sp["origin"]["line_ids"]) <= {r["id"] for r in AIR if r["who"] != "board"})
        rolled = {k for k, v in ns["_H3_HOURLY_ROLLS"].items() if v}
        self.assertTrue({"speak_lean", "speak_line", "speak_count"} <= rolled, rolled)
        tabled = {c["id"] for c in ns["_s3"].config["tables"][0]["categories"]}
        self.assertTrue({"h3.speak_lean", "h3.speak_count"} <= tabled, "the node's tables are on the desk")
        words = ns["h3_prompts_words"](entry, "clip", "garbage the brief's regex found")
        self.assertEqual(words["speech"], sp["line"])
        self.assertNotIn("{", words["direction"])
        self.assertEqual(words["speak"]["origin"]["node"], "H3SPEAK")

    def test_no_aired_line_speakerbox_rolls_a_document(self):
        doc = "# Doc\n\n### [0:00]\n\nThe weather turned cold before dawn. We kept the fire going all night.\n"
        ns = ns_with_block(self.dir, air=[AIR[0], AIR[5]], docs={"tales.md": doc})
        sp = self.hour(ns, speech="")["speak"]
        self.assertEqual((sp["verdict"], sp["source"], sp["doc"]), ("rolled", "speakerbox", "tales.md"))
        self.assertTrue(ns["_H3_HOURLY_ROLLS"].get("speak_doc"))
        self.assertIn(sp["line"].split(". ")[0].rstrip(".") + ".", doc.replace("\n", " "))

    def test_nothing_passes_the_forced_node_says_the_presets_own_line(self):
        ns = ns_with_block(self.dir, air=[AIR[0], AIR[5], AIR[7]], docs={"bad.md": "# only a heading\n"})
        sp = self.hour(ns)["speak"]
        self.assertEqual((sp["verdict"], sp["line"]), ("forced", "Please please support the pine box radio."))
        self.assertEqual(sp["forced_by"], "the preset's own line")
        ns2 = ns_with_block(self.dir, air=[], docs={})
        sp2 = self.hour(ns2, speech="")["speak"]
        self.assertEqual(sp2["verdict"], "forced")
        self.assertIn("The Box FM", sp2["line"])
        self.assertTrue(ns2["_H3_HOURLY_ROLLS"].get("speak_forced"), "the FORCED line is a roll off its table")

    def test_a_stray_slot_is_taken_out_and_logged(self):
        ns = ns_with_block(self.dir)
        self.assertEqual(ns["h3_speak_fill"]("A {station} ad for {mystery} fans."), "A The Box FM ad for fans.")
        self.assertTrue(any("{mystery}" in line for line in ns["_logs"]))

    def test_the_last_gate_refuses_and_names_it(self):
        ns = ns_with_block(self.dir)
        why = ns["h3_speak_gate"]("Scene: a {station} ad", "Hello to you all tonight.", {"hourly": True})
        self.assertIn("{station}", why)
        self.assertTrue(any("REFUSED" in line for line in ns["_logs"]))


class Wiring(unittest.TestCase):
    def test_every_edit_is_in_app_py_and_the_tables(self):
        for tool, target in (("h3_speak_patch.py", "app.py"), ("h3_speak_tables_patch.py", "system3_tables.py"),
                             ("edit_h3_speak_views.py", "desktop/renderer/ad-viewer.js"),
                             ("edit_h3_speak_views.py", "app/src/main/assets/pine-views/ad-viewer.js")):
            if not (ROOT / target).exists():
                continue
            got = subprocess.run([sys.executable, str(ROOT / "tools" / tool), "--check", str(ROOT / target)],
                                 capture_output=True, text=True)
            self.assertEqual(got.returncode, 2, tool + " " + target + "\n" + got.stdout)
        import system3_tables
        row = next(r for r in system3_tables.ROAD_REGISTER if r["id"] == "h3_speak")
        self.assertTrue(row["writer"] and row["hook"] and row["what"])

    def test_nothing_here_renders(self):
        block = block_source()
        for word in ("_submit_generation", "voice_ad_render(", "_parody_stinger_queue().add"):
            self.assertNotIn(word, block)

    def test_the_sheet_shows_the_node(self):
        js = ROOT / "desktop" / "renderer" / "ad-viewer.js"
        node = shutil.which("node")
        if not js.exists() or not node:
            self.skipTest("no renderer or no node")
        src = js.read_text(encoding="utf-8")
        fn = re.search(r"  function usedSpeak\(sp\) \{.*?\n  \}\n", src, re.S).group(0)
        rolls = re.search(r"  function usedRolls\(rolls\) \{.*?\n  \}\n", src, re.S).group(0)
        probe = fn + rolls + ("console.log(JSON.stringify([usedSpeak(%s), usedSpeak(%s), usedRolls(%s)]));" % (
            json.dumps({"verdict": "rolled", "source": "air", "count": {"rolled": 3, "took": 2},
                        "said": {"name": "Dana", "round": "caller", "turns": 2, "emotion": "delight",
                                 "intensity": 0.8, "at": 1790660000}}),
            json.dumps({"verdict": "forced", "forced_by": "the preset's own line", "why": "no aired line"}),
            json.dumps({"speak_line": {"kind": "pick", "dice": 44, "index": 3, "of": 9, "picked": "Dana: I love"},
                        "speak_count": {"kind": "pick", "dice": 70, "index": 2, "of": 3, "picked": "2"}})))
        out = json.loads(subprocess.run([node, "-e", probe], capture_output=True, text=True, check=True).stdout)
        self.assertIn("rolled from what Dana said on air", out[0])
        self.assertIn("feeling delight 0.80", out[0])
        self.assertTrue(out[1].startswith("FORCED - the preset's own line"))
        self.assertIn("line said on air: Dana: I love (d100 44, 3 of 9)", out[2])
        self.assertIn("sentences to take: 2 (d100 70, 2 of 3)", out[2])


if __name__ == "__main__":
    unittest.main()
