"""[num-leak] Bookkeeping numbers never reach a voice - the real lines of 2026-09-29.

Does NOT import app: the pieces under test are read out of app.py's source with ast
and run against stubs, so nothing touches /app/data. Run from a dry tree:
  docker exec -w /tmp/wX -e PYTHONPATH=tests:. spark-agent python3 -m unittest test_num_leak_2026_09_29
"""
import ast
import hashlib
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

import bookkeeping_numbers as bn

ROOT = Path(bn.__file__).resolve().parent
APP_SRC = (ROOT / "app.py").read_text(encoding="utf-8")

# prompt_history seq 16240 (station:chapter repair, conversation a509727c998d42a8) - AIRED as
# 3c6d9fb8 "...plain wrong 5", a27a1195 "...turn two ... at all 6", 68d35649 "...you idiot 7"
RAW_16240 = ("4 B: Crochet Ashley you are so misinformed about the situation and your response is just plain wrong\n"
             "5 A: That's just not right you're ignoring the actual point I made in turn two it's not what you think it is at all\n"
             "6 D: You are completely delusional that is what I am saying it has taken my money before and it will again you idiot\n"
             "7 B: Well, there you go then we'll just have to feed the machine then.")

# Numbers the scene called for - aired 2026-09-29, must come through untouched.
LEGIT = [
    "So I just lit the manager's office on fire. We have maybe. 6 - 7 minutes max. Spin it.",           # 6ca97349
    "Memory: 83.9 gigabytes used of 121.7 gigabytes . CPU: 20 cores, load average 7.53, 10.69, 12.40 over 1, 5 and 15 minutes.",
    "Uptime: 131 hours. Board temperature: 84C at the hottest of 7 sensors, 79C average. GPU: NVIDIA GB10, 96% utilization, 74 C.",
    "What the fuck? It's my reaction too, buddy. You spend $6,000 for the weekend, and some stupid-ass pig is staying here too.",
    "The story says anthropic had twenty point two eight billion in cash equivalents as of december thirty first.",
    "Sixty-three degrees Celsius? Are you sure about that?",
    "It's just a bunch of noise designed to distract from the actual vibe on this Tuesday, September 29th.",
    "I'm gonna be nice and give you a 3 seconds heads up.",
    "Number four syndrome. The incredibles. Almost in anticipation of two decades of superhero films.",
    "Oh dear god, i've been in this family for sixteen years and i don't think we've ever had a conversation.",
    "It's my turn to talk now, and I'm taking it.",
    "Take the second turn on the left past the gas station.",
    "Call 911 if the machine starts smoking, gate 7 is open, and Ocean's 11 is on at nine.",
    "Twenty-one, twenty-two, twenty-three. How many? 12.",
]


def app_pieces(names, extra=None):
    """Top-level defs / assignments of app.py by name, executed against stubs."""
    tree = ast.parse(APP_SRC)
    want, found = set(names), {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in want:
            found[node.name] = ast.get_source_segment(APP_SRC, node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id in want:
                    found[t.id] = ast.get_source_segment(APP_SRC, node)
    missing = want - set(found)
    assert not missing, "not in app.py: %s" % sorted(missing)
    ns = {"re": re, "Any": Any, "hashlib": hashlib, "time": time}
    ns.update(extra or {})
    for name in names:
        exec(found[name], ns)
    return ns


def parser_ns():
    return app_pieces(
        ["_ROW_NUMBER_TAIL", "_ROW_NUMBER_LINE", "_TURN_EDGE", "_TURN_EDGE_SLASH", "_heading_cut",
         "_HEADING_RX", "_HEADING_OPEN", "_HEADING_CLOSE", "_HEADING_SEP", "_HEADING_NEXT",
         "writer_turn_clean", "turn_edge_clean", "banter_turns"],
        {"dj_settings": lambda: {"host_name": "Dill", "cohost_name": "Skip", "third_name": "Crochet Ashley"}})


class RowNumbers(unittest.TestCase):
    def test_the_aired_chapter_parses_clean_flat_or_not(self):
        ns = parser_ns()
        flat = " ".join(RAW_16240.split())                  # what ask_model hands back
        for raw in (RAW_16240, flat):
            turns = ns["banter_turns"](raw)
            self.assertEqual([m for m, _ in turns], ["B", "A", "D", "B"], raw[:40])
            for _m, text in turns:
                self.assertFalse(re.search(r"\s\d{1,3}\s*$", text), text)
            self.assertTrue(turns[0][1].endswith("just plain wrong"))
            self.assertTrue(turns[2][1].endswith("you idiot"))

    def test_other_aired_shapes(self):
        cut = bn.row_numbers_cut
        self.assertEqual(cut("B: Shrug it off 3 D: No.")[0], "B: Shrug it off 3 D: No.")  # lone inline: kept
        self.assertEqual(cut("2 B: Shrug it off 3 D: No.")[0], "B: Shrug it off D: No.")
        self.assertEqual(cut("10. A: one\n11) B: two")[0], "A: one\nB: two")
        self.assertEqual(cut("A: I'll take 2 B: deal")[0], "A: I'll take 2 B: deal")
        self.assertEqual(cut("A: It runs 3:46 tonight.")[0], "A: It runs 3:46 tonight.")
        s, nums = cut("12 A: x 13 B: y 14 C: z")
        self.assertEqual((s, nums), ("A: x B: y C: z", [12, 13, 14]))

    def test_gallery_turns_cut_them_too(self):
        ns = app_pieces(["_GALLERY_MARKER", "_ROW_NUMBER_TAIL", "_ROW_NUMBER_LINE", "_heading_cut",
                         "_HEADING_RX", "writer_turn_clean", "gallery_turns"])
        got = ns["gallery_turns"]("3 A: It's worth fifty dollars 4 B: Fifty? Sold to line two")
        self.assertEqual(got, ["It's worth fifty dollars", "Fifty? Sold to line two"])


class LastGate(unittest.TestCase):
    def test_leaks_are_cut_and_named(self):
        cases = {
            "It makes me wonder what else they're hiding on the other side of that door. 11":
                "It makes me wonder what else they're hiding on the other side of that door.",
            "26 clip-40.": "",                                                     # 90a4096a AIRED
            "That's just not right you're ignoring the actual point I made in turn two it's not what you think":
                "That's just not right you're ignoring the actual point I made earlier it's not what you think",
            "Did you hear 731 clip?": "Did you hear?",
            "\U0001F50A 577 clip-2": "",
        }
        for said, want in cases.items():
            out, hits = bn.spoken_gate(said)
            self.assertEqual(out, want, said)
            self.assertTrue(hits, said)

    def test_a_clip_index_before_its_own_words(self):
        labels = ["\U0001F50A 25 dental plan in", "\U0001F50A 83 I'm the trash", "\U0001F50A 26 clip-40"]
        out, hits = bn.spoken_gate("He said 83 I'm the trash and meant it.", labels)
        self.assertEqual(out, "He said I'm the trash and meant it.")
        self.assertIn("83", hits[0])
        out, hits = bn.spoken_gate("I'm the trash, apparently.", labels)   # the words alone are fine
        self.assertEqual((out, hits), ("I'm the trash, apparently.", []))

    def test_legit_numbers_survive(self):
        labels = ["\U0001F50A 29 I don't know", "\U0001F50A 7 sensors"]
        for said in LEGIT:
            self.assertEqual(bn.spoken_gate(said, labels), (said, []), said)

    def test_gate_in_app_records_once(self):
        logs, reviews = [], []
        ns = app_pieces(["_NUM_LEAK_SEEN", "num_leak_gate"], {
            "_RADIO": {"chat": [{"who": "board", "text": "\U0001F50A 83 I'm the trash"}]},
            "pipeline_log": lambda *a, **k: logs.append((a, k)),
            "line_review_capture": lambda *a, **k: reviews.append((a, k)),
        })
        gate = ns["num_leak_gate"]
        for _ in range(3):
            self.assertEqual(gate("Well 83 I'm the trash, he says."), "Well I'm the trash, he says.")
        self.assertEqual(len(logs), 1)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0][0][0], "bookkeeping_number")
        self.assertEqual(reviews[0][1]["disposition"], "rewrite")
        self.assertEqual(gate(LEGIT[0]), LEGIT[0])
        self.assertEqual(len(reviews), 1)

    def test_spoken_text_uses_the_gate(self):
        seg = ast.get_source_segment(APP_SRC, next(
            n for n in ast.parse(APP_SRC).body if isinstance(n, ast.FunctionDef) and n.name == "spoken_text"))
        self.assertIn("clean = num_leak_gate(clean)", seg)


class Prompts(unittest.TestCase):
    def test_a_clip_is_its_words(self):
        self.assertEqual(bn.sfx_label_for_prompt("\U0001F50A 83 I'm the trash"),
                         'a sound clip from the board ("I\'m the trash")')
        self.assertEqual(bn.sfx_label_for_prompt("board: \U0001F50A 26 clip-40"), "a sound clip from the board")
        self.assertEqual(bn.sfx_label_for_prompt("26 clip-40", board=True), "a sound clip from the board")
        self.assertEqual(bn.sfx_label_for_prompt("395 like the.mp4", board=True), 'a sound clip from the board ("like the")')
        plain = "Going to feed the vending machine, it has taken my money before."
        self.assertEqual(bn.sfx_label_for_prompt(plain), plain)

    def test_the_verdict_is_about_a_person(self):
        spoken = ["dj: Is that right, Sam?", "cohost: Tell him.", "board: \U0001F50A 26 clip-40"]
        self.assertEqual(bn.last_said(spoken), "cohost: Tell him.")
        self.assertEqual(bn.last_said(["board: \U0001F50A 26 clip-40"]), "")
        self.assertEqual(bn.last_said([]), "")

    def test_the_prompt_sites_are_wired(self):
        for needle in ("_verdict_about = prompt_last_said(spoken)",
                       'prompt_sfx_label(str(row.get("text") or Path(str(sample)).stem), True)',
                       'prompt_sfx_label(str(e.get("context") or opening))[:600]',
                       '"%s has just said - %s" % (m, prompt_sfx_label(t))',
                       '"%s has just said - %s" % (marker, prompt_sfx_label(text))',
                       "a turn's number is the running order's, never a word to say"):
            self.assertIn(needle, APP_SRC, needle)
        self.assertNotIn("_sfx_verdict(spoken[-1])", APP_SRC)
        s2 = (ROOT / "system2_runtime.py").read_text(encoding="utf-8")
        self.assertIn('h.prompt_sfx_label(str(_o.get("text") or ""), True)', s2)


class Tool(unittest.TestCase):
    def tool(self):
        spec = importlib.util.spec_from_file_location("numleak_patch", ROOT / "tools" / "numleak_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_applied_idempotent_and_crlf(self):
        tool = self.tool()
        self.assertEqual(tool.main(["--check", str(ROOT)]), 2)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copy(ROOT / "bookkeeping_numbers.py", tmp)
            for name, edits in tool.TARGETS:
                text = (ROOT / name).read_text(encoding="utf-8")
                for _n, old, new, _c in reversed(edits):          # back to the base
                    text = text.replace(new, old)
                (tmp / name).write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
            self.assertEqual(tool.main(["--check", str(tmp)]), 0)
            self.assertEqual(tool.main(["--apply", str(tmp)]), 0)
            self.assertEqual(tool.main(["--apply", str(tmp)]), 2)
            for name, _e in tool.TARGETS:
                got = (tmp / name).read_bytes().decode("utf-8")
                self.assertNotIn("\n", got.replace("\r\n", ""), name)       # CRLF kept
                self.assertEqual(got.replace("\r\n", "\n"), (ROOT / name).read_text(encoding="utf-8"), name)
            (tmp / "bookkeeping_numbers.py").unlink()
            self.assertEqual(tool.main(["--check", str(tmp)]), 1)


if __name__ == "__main__":
    unittest.main()
