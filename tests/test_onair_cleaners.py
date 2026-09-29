"""[s3-rownum] [s3-scaffold] [s3-heading] [s3-echo] What the writer returns is not
all words: the on-air cleaners.

Four things aired on 2026-09-28 that were never words: a running-order row
number after a sentence ("...It's nothing to worry about. 5"), the sheet's own
header ("... TONIGHT'S TEMPERS : 1"), the segment's name printed as a heading
("Call with banter A man's cat dragged someone into the sewer, ...") and a row's
direction said as dialogue ("I can't believe it and says so, and widens it out
to the bigger picture."). The engine (system3: scaffold kit, direction kit,
validate), the runtime (the station's doors, REPAIR, the cut before the bind)
and app.py's half (writer_turn_clean, writer_headings, dj_line, the beat check,
the single-line road; tools/turns_rownum_patch.py and tools/direction_echo_patch.py
must be applied). No test touches the station's data dir; app.py is read, never
imported."""
import asyncio
import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

import system3
import system3_runtime
from test_system3_runtime import FakeStation, ctx, settle

ROOT = Path(__file__).resolve().parents[1]

# the two lines that AIRED (air_log 43d64ae264944f9ab8f1812b0f7478ea, 519eff5d788e4f7bb72df3caa5a1c2f8)
AIRED_1 = "trouble brewing under the floorboards of this whole operation. TONIGHT'S TEMPERS : 1"
AIRED_2 = ("anything else to happen. TONIGHT'S TEMPERS : A is deadly serious, refusing to let the other one turn "
           "it into a bit; B is bored to the back teeth and barely hiding it. 1")
# ...and the second as the writer wrote it (the Messenger's bubble: the header, a blank line, a row number)
WRITTEN_2 = ("anything else to happen.\n\nTONIGHT'S TEMPERS (rolled): A is deadly serious, refusing to let the other "
             "one turn it into a bit; B is bored to the back teeth and barely hiding it.\n\n1")
# line cb38bcc872164cf7b74b09c3736729a4, and the row of conversation 388893e718784230 it said (t20)
AIRED_ECHO = "I can't believe it and says so, and widens it out to the bigger picture."
ROW_20 = (" 21  A  - answers what Skip just said (Skip takes it further than they did, in disgust), feeling "
          "repulsion (plainly) about it: cannot believe it and says so, and widens it out to the bigger picture. "
          "Picks up a word or claim from Skip's line and takes it somewhere new - never hands that line back as "
          "the whole turn.")
# line 8ec28d70e393443db3c615454403336a, a station ID, 2026-09-28 05:25 local
AIRED_HEADING = ("Call with banter A man's cat dragged someone into the sewer, and now this kid was involved "
                 "yesterday and someone else today.")


class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.kit = system3.scaffold_kit()

    def test_both_aired_lines_come_back_clean(self):
        cut = lambda t: system3.strip_scaffold(t, self.kit)
        self.assertEqual(cut(AIRED_1), "trouble brewing under the floorboards of this whole operation.")
        self.assertEqual(cut(AIRED_2), "anything else to happen.")
        self.assertEqual(cut(WRITTEN_2), "anything else to happen.")
        for t in (AIRED_1, AIRED_2, WRITTEN_2):
            self.assertTrue(system3.find_scaffold(t, self.kit).upper().startswith("TONIGHT'S TEMPERS"))

    def test_a_rows_label_goes_and_the_line_stays(self):
        cut = lambda t: system3.strip_scaffold(t, self.kit)
        self.assertEqual(cut("The subject changes here: I was in the kitchen."), "I was in the kitchen.")
        self.assertEqual(cut('LANDS IT: It should have been called "Man with Feline Companions." I will take it.'),
                         'It should have been called "Man with Feline Companions." I will take it.')
        self.assertEqual(cut("LANDS IT: back to the station, glowing. Pure structural collapse, a heavy release."),
                         "Pure structural collapse, a heavy release.")
        self.assertEqual(cut("BACK TO THE MUSIC: one line that closes the bulletin and hands over."), "")
        self.assertEqual(cut("OPENS THE SPOT: names the sponsor out loud in the first sentence."), "")

    def test_ordinary_speech_is_untouched(self):
        for t in ("Back to the music: here's Prince.", "In the booth. That's where we are.",
                  "Here's the schedule: we open at nine.", "We sold 12 of them.", "Tonight's tempers are short, Skip.",
                  "Lands it? I doubt it.", "No, that is wrong? Thanks, back to the music."):
            self.assertEqual(system3.strip_scaffold(t, self.kit), t)
            self.assertEqual(system3.find_scaffold(t, self.kit), "")

    def test_the_labels_are_the_prompts_own(self):
        labels = system3.scaffold_labels()
        for lab in (system3.TEMPERS_LABEL, system3.EXCHANGE_LABEL, system3.SUBJECT_LABEL,
                    "THE RUNNING ORDER OF THIS CALL", "HOW THIS STATION ID IS SAID", "SCHEDULE", "SHOW MEMORY",
                    "LANDS IT", "ANSWER THE RINGING LINE"):
            self.assertIn(lab, labels)
        cfg = system3.default_config()
        cfg["structures"] = {"news": dict(system3.road_structure(cfg, "news"),
                                          head="THE WIRE DESK. Write these turns.",
                                          legs=[{"id": "x", "place": "close", "seat": "A", "act": "READS THE WIRE: the story."}])}
        cfg["blocks"] = {"forecast": {"kind": "obligation", "label": "FORECAST (#1): the weather"}}
        self.assertTrue({"THE WIRE DESK", "READS THE WIRE", "FORECAST"} <= set(system3.scaffold_labels(cfg)),
                        "a desk edit is read off its own text")

    def test_the_sheet_writes_the_label_the_parser_knows(self):
        cfg = system3.default_config()
        conv = system3.plan_scene({"road": "banter", "seats": ["A", "B"], "turns": 8, "round_rolls": True,
                                   "dice_hosts": True, "subject": {"topic": "the van"}},
                                  cfg, system3.normalise_settings({"mode": "active", "test_seed": "tempers"}))
        sheet = system3.render_sheet(conv)
        if conv.get("tempers"):
            self.assertIn("\n%s (rolled): " % system3.TEMPERS_LABEL, sheet)
        self.assertIn(system3.EXCHANGE_LABEL, sheet)


class EchoTests(unittest.TestCase):
    def test_the_aired_line_is_caught_by_its_rows_act_and_flow(self):
        kit = system3.direction_kit(ROW_20)
        self.assertIn("cannot believe it and says so", kit[0])
        self.assertIn("widens it out to the bigger picture", kit[0])
        self.assertIn(system3.direction_echo(AIRED_ECHO, kit),
                      ("cannot believe it and says so", "widens it out to the bigger picture"))
        # the station's old test read the first clause only, and missed it
        first = " ".join(re.findall(r"[a-z0-9']+", re.split(r"[,.;]", ROW_20.split(" - ", 1)[1], 1)[0].lower()))
        self.assertNotIn(first, AIRED_ECHO.lower())

    def test_a_direction_performed_is_not_said(self):
        row = " 3  B  - answers what Dill just said: tells them flatly that no, bro, that isn't gonna work, and turns the heat up."
        kit = system3.direction_kit(row)
        for line in ("No, bro, that isn't gonna work.", "No, bro, that's not gonna work; the van is gone.",
                     "Are you sure about that?", "I disagree, and I'm not kidding."):
            self.assertEqual(system3.direction_echo(line, kit), "", line)
        self.assertTrue(system3.direction_echo("No, bro, that isn't gonna work, and turns the heat up.", kit))
        self.assertTrue(system3.direction_echo(
            "In irritation, plainly: tells them flatly that no, bro, that isn't gonna work.", kit))

    def test_words_meant_to_be_said_are_not_directions(self):
        rows = "\n".join([
            ' 1  A  - opens with these exact words, as written: "We are square with the advertiser tonight."',
            ' 2  B  - answers what Dill just said. Begins by reading this out word for word as their own words: '
            '"Someone got eaten behind the diner last night."',
            " 3  A  - answers what Skip just said. THE OPERATOR'S DIRECTIVE FOR DILL ON THIS TURN: mention the bake "
            "sale at the church hall. Picks up a word or claim from Skip's line and takes it somewhere new"])
        kit = system3.direction_kit(rows)
        for line in ("We are square with the advertiser tonight.", "Someone got eaten behind the diner last night.",
                     "Don't forget to mention the bake sale at the church hall, Skip."):
            self.assertEqual(system3.direction_echo(line, kit), "", line)
        self.assertTrue(system3.direction_echo("Begins by reading this out word for word as their own words.", kit))

    def test_a_label_or_a_naming_clause_may_be_performed(self):
        kit = system3.direction_kit(
            " 4  A  - BACK TO THE MUSIC: one line that closes the bulletin and hands over.\n"
            " 2  B  - the next story off the page: says it, and what they make of it; answers the line before.")
        for line in ("Back to the music.", "We gotta get back to the music now.",
                     "The next story off the page is a fire on Elm Street."):
            self.assertEqual(system3.direction_echo(line, kit), "", line)
        self.assertTrue(system3.direction_echo(
            "The next story off the page: says it, and what they make of it; answers the line before.", kit))
        self.assertTrue(system3.direction_echo("One line that closes the bulletin and hands over.", kit))

    def test_the_rows_feeling_read_out(self):
        kit = system3.direction_kit(" 7  B  - in distaste (plainly): what they actually meant")
        self.assertEqual(system3.direction_echo("In distaste, plainly: I was in the kitchen.", kit), "in distaste, plainly")
        self.assertEqual(system3.direction_echo("Fun? In distaste, plainly, and I mean it.", kit), "in distaste, plainly")
        self.assertEqual(system3.direction_echo("I said it in distaste, and plainly too.", kit), "")

    def test_a_stumble_cannot_hide_it(self):
        kit = system3.direction_kit(ROW_20)
        self.assertTrue(system3.direction_echo(
            "I can't- I can't believe it and, uh, says so, and widens it out to the bigger picture.", kit))

    def test_the_validator_reads_every_written_turn(self):
        cfg = system3.default_config()
        conv = system3.plan_scene({"road": "banter", "seats": ["A", "B"], "turns": 8, "subject": {"topic": "the van"}},
                                  cfg, system3.normalise_settings({"mode": "active", "test_seed": "echo-v"}))
        kit = system3.conv_direction_kit(conv)
        self.assertTrue(kit[0])
        turns = [(t["speaker"], "Plain words number %d, said plainly about the van." % t["index"]) for t in conv["turns"]]
        clean = system3.validate(conv, turns)
        self.assertEqual((clean["direction_echo"], clean["scaffold"], clean["unplanned"]), (0, 0, []))
        said = [p for p in kit[0] if len(p.split()) >= 5][0]
        turns[2] = (turns[2][0], "Well. %s, obviously." % said)
        turns.append(("B", AIRED_2))                           # an unplanned turn airs too
        got = system3.validate(conv, turns)
        self.assertGreaterEqual(got["direction_echo"], 1)
        self.assertEqual(got["scaffold"], 1)
        self.assertEqual(got["verdict"], "non_compliant")
        self.assertTrue(got["repair_wanted"])
        whats = [c["what"] for r in got["turns"] + got["unplanned"] for c in r["checks"]]
        self.assertTrue(any(w.startswith("direction:") for w in whats), whats)
        self.assertTrue(any(w.startswith("scaffold:TONIGHT'S TEMPERS") for w in whats), whats)

    def test_the_default_config_is_unchanged(self):
        pin = re.search(r'config_hash\(system3\.default_config\(\)\), "([0-9a-f]{16})"',
                        (ROOT / "tests" / "test_system3.py").read_text(encoding="utf-8")).group(1)
        self.assertEqual(system3.config_hash(system3.default_config()), pin)


class RuntimeCleanerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.station = FakeStation(self.tmp.name)
        app = FastAPI()
        system3_runtime.install(app, self.station)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.rt = self.station["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        self.rt.settings = self.rt.apply_settings({"mode": "active", "test_seed": "rt-clean"})

    def test_the_station_doors(self):
        self.assertEqual(self.station["system3_scaffold_strip"](AIRED_1),
                         "trouble brewing under the floorboards of this whole operation.")
        self.assertTrue(self.station["system3_direction_echo"](AIRED_ECHO, ROW_20))
        self.assertEqual(self.station["system3_direction_echo"]("No, bro, that isn't gonna work.", ROW_20), "")
        self.assertEqual(self.station["system3_direction_echo"](AIRED_ECHO, None), "")

    def test_a_banked_draft_that_echoes_goes_back(self):
        self.rt.settings = self.rt.apply_settings({"controls": {"repair": 1.0}})
        h = asyncio.run(self.station["system3_direct_banter"](**ctx(bank=True)))
        self.assertTrue(h.active and h.bank)
        script = "\n".join("%s: Plain words number %d, said plainly, about the raccoon who took the van and never came "
                           "back to the lot." % (t["speaker"], t["index"]) for t in h.conv["turns"])
        self.assertFalse(self.station["system3_repair_wanted"](h, script))
        self.assertTrue(self.station["system3_repair_wanted"](h, script + " " + AIRED_1.split(". ", 1)[1]))
        said = [p for p in system3.conv_direction_kit(h.conv)[0] if len(p.split()) >= 5][0]
        self.assertTrue(self.station["system3_repair_wanted"](h, script.replace("Plain words number 1,", said + ",", 1)))

    def test_the_last_gate_cuts_a_turn_that_says_its_direction(self):
        h = asyncio.run(self.station["system3_direct_banter"](**ctx(bank=False)))
        self.assertTrue(h.active)
        said = [p for p in system3.conv_direction_kit(h.conv)[0] if len(p.split()) >= 5][0]
        lines = ["%s: Plain words number %d, about the raccoon and the van." % (t["speaker"], t["index"])
                 for t in h.conv["turns"]]
        lines[1] = "%s: Well, %s, and that is that." % (h.conv["turns"][1]["speaker"], said)
        entry = {"script": "\n".join(lines), "script_plain": "\n".join(lines), "caller_name": ""}
        self.station["system3_bind_entry"](entry, h)
        self.assertNotIn(said, entry["script"].lower())
        self.assertNotIn(said, entry["script_plain"].lower())
        self.assertEqual(len(entry["script"].split("\n")), len(lines) - 1)
        self.assertEqual([c["script_index"] for c in h.conv["echo_cut"]], [1])
        self.assertEqual(h.conv["validation"]["direction_echo"], 0, "what aired says no direction")
        self.assertTrue(any(k == "drop" and "running-order direction" in t for k, t in self.station.logged))
        clean = {"script": "\n".join(l for i, l in enumerate(lines) if i != 1), "caller_name": ""}
        h2 = asyncio.run(self.station["system3_direct_banter"](**ctx(bank=False)))
        self.station["system3_bind_entry"](clean, h2)
        self.assertNotIn("echo_cut", h2.conv)


# --- app.py's half --------------------------------------------------------------------

def _app_text():
    return (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")


def _top_level(text, head):
    """The source of one top-level statement of app.py, from `head` to the next
    line that starts in column 0."""
    i = text.find("\n" + head) + 1
    if not i:
        raise AssertionError("app.py has no top-level %r (are the tools applied?)" % head)
    out = [text[i:text.index("\n", i) + 1]]
    j = i + len(out[0])
    while j < len(text):
        k = text.index("\n", j) + 1
        line = text[j:k]
        if line.strip() and not line[0].isspace() and not line.startswith((")", "}", "]")):
            break
        out.append(line)
        j = k
    return "".join(out)


def _app(*heads, **ns):
    text = _app_text()
    src = "".join(_top_level(text, h) for h in heads)
    space: dict[str, Any] = {"re": re, "Any": Any, **ns}
    exec(compile(src, "app.py[on-air cleaners]", "exec"), space)
    return space


CLEAN_HEADS = ("_TURN_EDGE = ", "_TURN_EDGE_SLASH = ", "def turn_edge_clean(",   # [s3-slash-tests]
               "_ROW_NUMBER_TAIL = ", "_ROW_NUMBER_LINE = ", "_HEADING_OPEN = ", "_HEADING_CLOSE = ",
               "_HEADING_SEP = ", "_HEADING_NEXT = ", "_HEADING_NOT = ", "_HEADING_RX", "def writer_headings(",
               "def _heading_cut(", "def writer_turn_clean(")


def _cleaners(door=True, brief="", **dj):
    kit = system3.scaffold_kit()
    ns = {"system3_scaffold_strip": (lambda t: system3.strip_scaffold(t, kit))} if door else {}
    return _app(*(CLEAN_HEADS + ("def banter_turns(",)), dj_settings=lambda: dict(dj),
                _schedule_prompt_clause=lambda: brief, **ns)


def _tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / ("%s.py" % name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AppCleanerTests(unittest.TestCase):
    def test_the_tools_are_applied(self):
        text = _app_text()
        for name in ("turns_rownum_patch", "direction_echo_patch"):
            mod = _tool(name)
            applied, missing = mod.check(text)
            self.assertEqual((missing, applied), ([], len(mod.plan(text))), name)
            got = subprocess.run([sys.executable, str(ROOT / "tools" / ("%s.py" % name)), "--check",
                                  str(ROOT / "app.py")], capture_output=True, text=True, timeout=600)
            self.assertEqual(got.returncode, 2, got.stdout + got.stderr)

    def test_the_writers_row_numbers_are_not_words(self):
        parse = _cleaners()["banter_turns"]
        self.assertEqual(parse("10 A: Yeah, I get it, music is everything. 11 B: Let's just move on then. "
                               "12 A: Fine, I'll fix the damn thing."),
                         [("A", "Yeah, I get it, music is everything."), ("B", "Let's just move on then."),
                          ("A", "Fine, I'll fix the damn thing.")])
        self.assertEqual([t for _m, t in parse("10  A: One thing.\n11. B: Another thing\n12) A: And the last.")],
                         ["One thing.", "Another thing", "And the last."])
        self.assertEqual(parse("10 A: One. 11 B: Two. 12")[-1], ("B", "Two."))
        self.assertEqual(parse("A: That is the one. B: Go on then. 2")[-1], ("B", "Go on then."))
        # the lines that aired
        clean = _cleaners()["writer_turn_clean"]
        for said, want in (("It's nothing to worry about. 5", "It's nothing to worry about."), ("Cat. 6", "Cat."),
                           ("graphics from the Pine Box gallery) 7", "graphics from the Pine Box gallery)")):
            self.assertEqual(clean(said), want)

    def test_a_number_that_is_part_of_a_sentence_stays(self):
        parse = _cleaners()["banter_turns"]
        self.assertEqual(parse("A: We sold 12 of them. B: Twelve? That is nothing."),
                         [("A", "We sold 12 of them."), ("B", "Twelve? That is nothing.")])
        self.assertEqual(parse("A: How many did we sell? 12. B: That is a lot."),
                         [("A", "How many did we sell? 12."), ("B", "That is a lot.")])
        self.assertEqual(parse("A: The score was 3 to 12 B: no")[0], ("A", "The score was 3 to 12"))
        self.assertEqual(parse("A: It ended at 12.")[0], ("A", "It ended at 12."))
        self.assertEqual(parse("A: Call 911.")[0], ("A", "Call 911."))

    def test_a_prompts_own_header_is_not_a_word(self):
        parse = _cleaners()["banter_turns"]
        self.assertEqual(parse("A: Something first. B: " + AIRED_1),
                         [("A", "Something first."), ("B", "trouble brewing under the floorboards of this whole operation.")])
        self.assertEqual(parse("A: Something first.\nB: " + WRITTEN_2)[-1], ("B", "anything else to happen."))
        self.assertEqual(parse("A: Something first.\nB: " + AIRED_2)[-1], ("B", "anything else to happen."))
        self.assertEqual(parse("A: The subject changes here: I was in the kitchen.\nB: Were you."),
                         [("A", "I was in the kitchen."), ("B", "Were you.")])

    def test_a_line_that_is_only_a_number_is_never_dialogue(self):
        for door in (True, False):
            self.assertEqual(_cleaners(door=door)["banter_turns"]("A: Hello there.\n7\nB: Hi.\n\n12"),
                             [("A", "Hello there."), ("B", "Hi.")])

    def test_the_segments_name_printed_as_a_heading_is_not_a_word(self):
        ns = _cleaners(brief='SCHEDULE (#843) - THIS ROUND IS THE "Call with banter" ENTRY ON THE "system2" '
                             'SCHEDULE. THE SEGMENT IS CALLED "Call with banter" - that is the name.')
        names = ns["writer_headings"]("station_id")
        self.assertEqual(names, ("Call with banter", "station id"))
        clean = lambda t: ns["writer_turn_clean"](t, names)
        self.assertEqual(clean(AIRED_HEADING), AIRED_HEADING[len("Call with banter "):])
        for said in ("Call with banter\n\nA man's cat.", "**Call with banter**\nA man's cat.",
                     "CALL WITH BANTER: A man's cat.", "Call with banter - A man's cat.",
                     "Call with banter \u2014 A man's cat.", "Station ID: A man's cat."):
            self.assertEqual(clean(said), "A man's cat.", said)
        for said in ("Welcome back to Call with banter!", "Call with banter is back, and so are we.",
                     "Call with banter! Great show.", "call with banter and a man's cat."):
            self.assertEqual(clean(said), said, said)
        one = lambda t: ns["writer_turn_clean"](t, ("News", "Call"))
        self.assertEqual(one("News: The mayor resigned."), "The mayor resigned.")
        self.assertEqual(one("News\nThe mayor resigned."), "The mayor resigned.")
        self.assertEqual(one("News The mayor resigned."), "News The mayor resigned.", "one word needs its separator")
        self.assertEqual(one("Call Dill now."), "Call Dill now.")
        self.assertEqual(_cleaners()["writer_headings"]("caller", "ad"), (),
                         "a speaker's label or two letters is no heading")

    def test_the_line_writer_and_the_mouth_meet_the_same_cut(self):
        text = _app_text()
        body = _top_level(text, "async def dj_line(")
        self.assertIn("answer = writer_turn_clean(answer, writer_headings(kind))", body)
        self.assertLess(body.index("writer_turn_clean(answer"), body.index("#1038: THE SECOND PASS"))
        mouth = _top_level(text, "def spoken_text(")
        self.assertIn(r'clean = re.sub(r"(?<=[.!?\u2026\"\u201d' + "'" + r'\u2019)\]])\s+\d{1,2}\s*$", "", clean).strip()',
                      mouth)
        gold = _top_level(text, "def gold_note(")
        self.assertIn("if writer_turn_clean(text) != text:", gold)
        self.assertIn('namespace["system3_scaffold_strip"] = rt.strip_scaffold',
                      (ROOT / "system3_runtime.py").read_text(encoding="utf-8"))

    def test_the_beat_check_reads_every_clause_of_its_row(self):
        door = lambda text, work: system3.direction_echo(text, system3.direction_kit(work))
        check = _app("_BANTER_BEAT_STOP = ", "def _beat_content_words(", "def _beat_speaks_direction(",
                     system3_direction_echo=door)["_beat_speaks_direction"]
        row = {"work": ROW_20.split(" - ", 1)[1]}
        self.assertTrue(check(AIRED_ECHO, row))
        self.assertTrue(check("Answers what Skip just said, and more.", row), "the first clause, as before")
        self.assertFalse(check("That raccoon is not coming back, Skip.", row))
        old = _app("_BANTER_BEAT_STOP = ", "def _beat_content_words(", "def _beat_speaks_direction(")
        self.assertFalse(old["_beat_speaks_direction"](AIRED_ECHO, row), "without the door: the first clause only")

    def test_the_single_line_road_withholds_a_line_that_says_its_sheet(self):
        text = _app_text()
        i = text.index("    # [s3-echo] A LINE THAT SAYS A DIRECTION OF ITS SHEET NEVER AIRS.")
        block = text[i:i + 1400]
        self.assertIn('_echo_said = globals()["system3_direction_echo"](spoken, _s3_sheet)', block)
        self.assertIn('globals()["system3_withhold"](_s3_spoken_handle,', block)
        # after s3-line-fix's own check and its one rewrite, before the recording
        self.assertLess(text.rfind("_sheet_speaks_direction(spoken, _s3_sheet)", 0, i), i)
        self.assertGreater(text.index("    if line_forgotten(spoken):", i), i)


if __name__ == "__main__":
    unittest.main()
