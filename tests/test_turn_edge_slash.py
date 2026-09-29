"""[s3-slash] The real broken lines of 2026-09-27..29, replayed through the fixed
parser and the gates: no turn, spoken line, voice text, script row or feed row
opens on a slash or a speaker marker, and the middle of a line is never touched.

Fixtures (tests/slash_fixtures.json, dumped read-only off the host):
  ledger  - every aired line in 48 h that opened on / | \\ or "X: " (116)
  raw     - every writer response in 60 h with "X:/" or "X: X:" (67)
  scripts - every stored round script holding one (manager_memos, larder, prep_shelf)
Imports app (run in the container). Writes only to a temp file.
"""
import importlib.util
import inspect
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app

HERE = Path(__file__).resolve().parent
ROOT = Path(app.__file__).resolve().parent
FIX = json.loads((HERE / "slash_fixtures.json").read_text(encoding="utf-8"))
EDGE = re.compile(r"^\s*(?:[/\\|]|[ABCDE]\s*:(?!\d))")
SLASH = re.compile(r"^\s*[/\\|]")
OLD_SPLIT = r"(?:^|\s)([ABCDE])\s*:\s*"


def old_turns(script):
    """HEAD's split, for the before/after count."""
    parts = re.split(OLD_SPLIT, " " + str(script or ""), flags=re.I)
    return [(parts[i].upper(), parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]


def load_repair():
    spec = importlib.util.spec_from_file_location(
        "turn_edge_slash_store_repair", ROOT / "tools" / "turn_edge_slash_store_repair.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LedgerLines(unittest.TestCase):
    def test_fixture_is_real(self):
        self.assertGreaterEqual(len(FIX["ledger"]), 100)
        self.assertGreaterEqual(len(FIX["raw"]), 20)
        self.assertGreaterEqual(len(FIX["scripts"]), 10)

    def test_turn_edge_takes_the_edge_and_only_the_edge(self):
        for row in FIX["ledger"]:
            t = row["text"]
            c = app.turn_edge_clean(t)
            self.assertFalse(EDGE.match(c), (t[:80], c[:80]))
            self.assertTrue(t.endswith(c), t[:80])          # nothing past the edge moves
            self.assertTrue(c.strip(), t[:80])

    def test_spoken_text_never_says_a_slash(self):
        for row in FIX["ledger"]:
            t = row["text"]
            s = app.spoken_text(t)
            self.assertFalse(SLASH.match(s), (t[:80], s[:80]))
            if re.match(r"^\s*[/\\|]+\s*[ABCDE]\s*:", t):
                self.assertFalse(re.match(r"^[ABCDE]\s*:", s), (t[:80], s[:80]))

    def test_one_turn_through_the_parser(self):
        cases = {
            "/B: every pause is a calculated opportunity.": "every pause is a calculated opportunity.",
            "/Out of hand? Are you kidding me?": "Out of hand? Are you kidding me?",
            "A: A: Well, maybe they don't care.": "Well, maybe they don't care.",
            "B:/That is just noise.": "That is just noise.",
            "A:/B: From management.": "From management.",
            " / black magician girl is coming into focus.": "black magician girl is coming into focus.",
        }
        for raw, want in cases.items():
            # a writer's line as it came: its own first marker speaks, else it is B's
            lead = re.match(r"\s*([ABCDE])\s*:", raw)
            got = app.banter_turns(raw if lead else "B: " + raw)
            self.assertEqual(got, [(lead.group(1) if lead else "B", want)], raw)
            self.assertEqual(app.turn_edge_clean(raw), want, raw)

    def test_middle_is_never_touched(self):
        keep = ["It runs 24/7 and nobody asks why.", "AC/DC is up next, then either/or.",
                "Ratio is 3:1 tonight.", "A:30 is not a marker.", "Dill: that's a name, not a seat.",
                "Page A: the memo says so.", "This and/or that; B: not at the front."]
        for t in keep:
            self.assertEqual(app.turn_edge_clean(t), t)
            self.assertEqual(app.spoken_text(t), app.spoken_text(t.strip()))
        self.assertEqual(app.banter_turns("A: I like AC/DC and/or Queen. B: /Really? 24/7?"),
                         [("A", "I like AC/DC and/or Queen."), ("B", "Really? 24/7?")])
        # a whole script handed to spoken_text keeps its first marker (markers=False)
        self.assertTrue(app.spoken_text("A: first line. B: second line.").startswith("A:"))


class WriterOutputs(unittest.TestCase):
    def test_raw_writer_outputs_parse_clean(self):
        before = after = total = 0
        for row in FIX["raw"]:
            old = old_turns(row["text"])
            new = app.banter_turns(row["text"])
            before += sum(1 for _m, x in old if EDGE.match(x))
            after += sum(1 for _m, x in new if EDGE.match(x))
            total += len(new)
            for m, x in new:
                self.assertFalse(EDGE.match(x), (row["seq"], m, x[:80]))
        print("\n[s3-slash] raw writer outputs: %d responses, %d turns; turns opening on an edge: "
              "HEAD %d -> fixed %d" % (len(FIX["raw"]), total, before, after))
        self.assertGreater(before, 50)
        self.assertEqual(after, 0)

    def test_first_marker_is_the_speaker(self):
        # seq 8183 (09-27 22:54): "A:/B: ...", "B:/A: ..." alternating - the first letter speaks
        rows = [r for r in FIX["raw"] if r["text"].startswith("A:/B:") and "\nB:/A:" in r["text"]]
        self.assertTrue(rows)
        for r in rows:
            firsts = re.findall(r"(?m)^([ABCDE]):", r["text"])
            self.assertEqual([m for m, _x in app.banter_turns(r["text"])], firsts)

    def test_stored_scripts_parse_clean_and_repair_is_air_neutral(self):
        rep = load_repair()
        self.assertEqual(rep.TURN_EDGE.pattern, app._TURN_EDGE.pattern)
        self.assertEqual(rep.TURN_EDGE_SLASH.pattern, app._TURN_EDGE_SLASH.pattern)
        for row in FIX["scripts"]:
            turns = app.banter_turns(row["text"])
            for m, x in turns:
                self.assertFalse(EDGE.match(x), (row["store"], row["at"], x[:80]))
            fixed, n = rep.repair_script(row["text"])
            if re.search(r"(?m)^\s*[ABCDE]\s*:\s*(?:[/\\|]|[ABCDE]\s*:)", row["text"]):
                self.assertGreater(n, 0, (row["store"], row["at"]))
            # (an inline "... B: A: ..." stays in the store; the parser takes it at air)
            self.assertEqual(app.banter_turns(fixed), turns, (row["store"], row["at"]))
            self.assertFalse(re.search(r"(?m)^\s*[ABCDE]\s*:\s*[/\\|]", fixed), (row["store"], row["at"]))

    def test_prompts_no_longer_teach_the_token(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn('"Return only A:/B"', src)
        self.assertNotIn("the listed A:/B:/C:/D: marker. No preface, labels, markdown, stage ", src)
        self.assertIn("turn_edge_clean(text) or text", inspect.getsource(app.voice_generate))


class Rows(unittest.TestCase):
    def test_script_row_and_feed_row(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "script_ledger.jsonl"
            with mock.patch.object(app, "SCRIPT_LEDGER_PATH", path), \
                    mock.patch.dict(app._SCRIPT_LEDGER_MEMO, {"at": 0, "rows": []}), \
                    mock.patch.dict(app.__dict__, {"system3_observe_ledger": None,
                                                   "system3_segment_block": None}):
                block = app.script_ledger_commit("sid-test", [
                    {"who": "cohost", "kind": "dialogue", "text": "/Out of hand? Are you kidding me?"},
                    {"who": "dj", "kind": "dialogue", "text": "/B: every pause is a calculated opportunity."},
                    {"who": "board", "kind": "sfx", "text": "/samples/x/clip.mp3"},
                ], round_kind="manager", block=987654321, at=1.0)
            self.assertEqual(block, 987654321)
            rows = [json.loads(x) for x in path.read_text().splitlines()]
        self.assertEqual([r["text"] for r in rows],
                         ["Out of hand? Are you kidding me?", "every pause is a calculated opportunity.",
                          "/samples/x/clip.mp3"])
        row = app.airlog_row_from({"id": "x", "ts": 1, "who": "dj", "kind": "call",
                                   "text": "/B: every pause is a calculated opportunity."})
        self.assertEqual(row["text"], "every pause is a calculated opportunity.")
        row = app.airlog_row_from({"id": "y", "ts": 1, "who": "host", "kind": "chat", "text": "/help"})
        self.assertEqual(row["text"], "/help")


if __name__ == "__main__":
    unittest.main()
