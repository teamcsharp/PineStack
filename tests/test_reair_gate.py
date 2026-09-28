"""[s3-banks-roll] The re-air gate (reair_gate.py) and the one-time sweep
(tools/reair_sweep.py): which banked rounds may ever go out again.

A round is never eligible when it has copied turns (> 0.9 like an earlier
turn of the same round), an echo loop, a non_compliant verdict, turns the
turnchain gate flagged ([s3-turnchain]: the stamp's "gate" counts, a
conversation's "turn_gate" record, events of family GATE), or a mark from
the sweep. No station import: these run anywhere.
"""
import importlib.util
import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import reair_gate

# ef39853f9fa54974, as it sat in the larder on 2026-09-28 (first words of each turn)
BROKEN = """A: buried inside of me lucky my dad's here get the damn truck son i need to take you home
B: Buried inside of me lucky my dad's here get the damn truck son i need to take you home
A: Sounds like someone needs to sit down and process that kind of mess.
B: Whoa, hold on. You're trying to frame this like it's about what we saw or what the studio decided.
A: Exactly! It's a joke, right? I'm just saying it's a joke. No, apparently music is everything.
B: Whoa, hold on. You're trying to frame this like it's about what we saw or what the studio decided.
A: Exactly! It's a joke, right? I'm just saying it's a joke. No, apparently music is everything. 10
B: Yeah, I get it. Whatever. Let's just move on then. 11"""

CLEAN = """A: The late train into town was running on a donkey's schedule again tonight.
B: Which donkey? The one from the parade or the one who runs the timetable?
A: Same donkey, different hat. He had the whole platform waiting on a sandwich.
B: I respect a donkey with priorities. Back to the music."""


def _row(script=CLEAN, cid="c1", verdict="compliant", aired=1, **extra):
    entry = {"script": script, "at": time.time() - 3600,
             "system3": {"conversation_id": cid, "mode": "active", "verdict": verdict}}
    entry.update(extra)
    if aired:
        entry.update(aired=aired, aired_at=time.time() - 1800)
    return entry


class GateRuleTests(unittest.TestCase):
    def test_norm_drops_the_row_number_and_the_punctuation(self):
        self.assertEqual(reair_gate.norm("Yeah, I get it. Whatever. 11"), "yeah i get it whatever")
        self.assertEqual(reair_gate.norm("  It's  a joke!  "), "it s a joke")

    def test_script_turns_read_markers_names_and_carried_lines(self):
        turns = reair_gate.script_turns("A: one two\ncarried on\nSalta: hello there\n\nB: three")
        self.assertEqual(turns, [("A", "one two carried on"), ("Salta", "hello there"), ("B", "three")])

    def test_copied_turns_are_found_with_the_earlier_turn_they_copy(self):
        copies = reair_gate.copied_turns(reair_gate.script_turns(BROKEN))
        self.assertEqual(copies, [(1, 0), (5, 3), (6, 4)])

    def test_short_lines_and_answers_are_not_copies(self):
        turns = [("A", "Yeah."), ("B", "Yeah."), ("A", "What do you mean by that, exactly?"),
                 ("B", "What I mean is the timetable is a fiction the donkey wrote.")]
        self.assertEqual(reair_gate.copied_turns(turns), [])
        self.assertEqual(reair_gate.content_refusal({"script": "\n".join("%s: %s" % t for t in turns)}), "")

    def test_the_echo_loop_is_system3s_own_rule(self):
        turns = [("A", "Shave it."), ("B", "Shave it? What do you mean?")] * 4
        echo, loop = reair_gate.echo_loop(turns)
        self.assertTrue(loop)
        self.assertEqual(echo, reair_gate._echoes_local(turns), "the carried copy agrees with the engine")
        why = reair_gate.content_refusal({"script": "\n".join("%s: %s" % t for t in turns)})
        self.assertTrue(why.startswith("an echo loop"), why)

    def test_a_non_compliant_verdict_retires_the_round(self):
        why = reair_gate.refusal(_row(verdict="non_compliant"))
        self.assertIn("non_compliant", why)

    def test_the_copy_gates_flags_retire_the_round_when_it_carries_them(self):
        row = _row()
        row["system3"]["copy_gate"] = {"turns": ["c1:t03"]}
        self.assertIn("copy gate flagged 1", reair_gate.refusal(row))
        self.assertEqual(reair_gate.refusal(_row()), "")

    def test_the_turnchain_gates_counts_retire_the_round(self):
        # the LIVE shape ([s3-turnchain]): the stamp carries system3.gate_counts
        row = _row()
        row["system3"]["gate"] = {"caught": 2, "rewritten": 2, "dropped": 0, "trimmed": 0,
                                  "visits": 3, "held": "", "in_chain": 0}
        why = reair_gate.refusal(row)
        self.assertIn("turnchain gate flagged", why)
        self.assertIn("caught 2", why)
        held = _row()
        held["system3"]["gate"] = {"caught": 1, "rewritten": 0, "dropped": 1, "trimmed": 0, "visits": 10,
                                   "held": "turn 3 (open) could not be written without copying", "in_chain": 0}
        self.assertIn("turnchain gate held the round", reair_gate.refusal(held))
        chain = _row()
        chain["system3"]["gate"] = {"caught": 0, "rewritten": 0, "dropped": 0, "trimmed": 0,
                                    "visits": 0, "held": "", "in_chain": 2}
        self.assertIn("in the beat chain 2", reair_gate.refusal(chain))

    def test_a_clean_turnchain_walk_and_a_missing_record_pass(self):
        clean = _row()
        clean["system3"]["gate"] = {"caught": 0, "rewritten": 0, "dropped": 0, "trimmed": 0,
                                    "visits": 0, "held": "", "in_chain": 0}
        self.assertEqual(reair_gate.refusal(clean), "")
        none = _row()
        none["system3"]["gate"] = None
        self.assertEqual(reair_gate.refusal(none), "")

    def test_a_conversations_own_turn_gate_record_is_read(self):
        # a conversation row (the sweep's DB read) carries turn_gate itself,
        # in_chain in its dict shape
        conv = {"script": CLEAN, "turn_gate": {"caught": 1, "rewritten": 1, "dropped": 0, "trimmed": 0,
                                               "visits": 1, "held": "", "in_chain": {"caught": 1, "turns": []}}}
        why = reair_gate.content_refusal(conv)
        self.assertIn("caught 1", why)
        self.assertIn("in the beat chain 1", why)

    def test_copied_turns_retire_the_round_and_say_which(self):
        why = reair_gate.refusal(_row(BROKEN))
        self.assertTrue(why.startswith("copied turns - 3 of its 8 turns"), why)
        self.assertIn("turn 2 = turn 1", why)

    def test_a_shelf_row_is_read_through_its_entry(self):
        row = {"at": time.time(), "aired_at": time.time() - 60, "entry": _row(BROKEN)}
        self.assertTrue(reair_gate.refusal(row))
        self.assertEqual(reair_gate.stamp_of(row)["conversation_id"], "c1")

    def test_a_finished_call_is_read_by_its_transcript(self):
        call = {"id": "call-1", "transcript": [{"who": "caller", "text": t} for t in (
            "Hi, it's Salta, calling about the cat stuck in the storm drain again.",
            "Hi, it's Salta, calling about the cat stuck in the storm drain again!",
            "What happened to the cat?")]}
        self.assertTrue(reair_gate.refusal(call).startswith("copied turns"))
        self.assertIn("call:call-1", reair_gate.mark_keys(call))

    def test_a_mark_retires_a_round_its_words_would_pass(self):
        row = _row(cid="marked")
        self.assertEqual(reair_gate.refusal(row), "")
        why = reair_gate.refusal(row, {"cid:marked": {"why": "the copy gate's record"}})
        self.assertEqual(why, "marked ineligible by the sweep: the copy gate's record")
        sha = [k for k in reair_gate.mark_keys(_row(cid="")) if k.startswith("sha:")][0]
        self.assertTrue(reair_gate.refusal(_row(cid=""), {sha: {"why": "x"}}))

    def test_the_answer_is_remembered_by_the_words(self):
        row = _row(BROKEN, cid="memo")
        first = reair_gate.content_refusal(row)
        with mock.patch.object(reair_gate, "copied_turns", side_effect=AssertionError("asked again")):
            self.assertEqual(reair_gate.content_refusal(row), first)
            with self.assertRaises(AssertionError):
                reair_gate.content_refusal(_row(BROKEN + "\nA: and one more line to make it new", cid="memo"))

    def test_marks_round_trip_atomically(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "reair_ineligible.json")
            self.assertEqual(reair_gate.load_marks(path), {})
            reair_gate.save_marks(path, {"cid:a": {"why": "w"}})
            self.assertEqual(reair_gate.load_marks(path), {"cid:a": {"why": "w"}})
            self.assertEqual(os.listdir(d), ["reair_ineligible.json"], "no temp file left behind")
            body = open(path, "rb").read()
            self.assertNotIn(b"\r", body)


def _load_sweep():
    here = Path(__file__).resolve().parent
    for root in (here.parent, Path(os.getcwd())):
        path = root / "tools" / "reair_sweep.py"
        if path.exists():
            spec = importlib.util.spec_from_file_location("reair_sweep_under_test", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise unittest.SkipTest("tools/reair_sweep.py is not beside these tests")


class SweepTests(unittest.TestCase):
    def setUp(self):
        self.sweep = _load_sweep()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        d = self.dir.name
        larder = [_row(BROKEN, cid="broken", aired=7), _row(CLEAN, cid="clean", aired=2),
                  _row(CLEAN.replace("donkey", "mule"), cid="planned-copies", aired=1),
                  _row(CLEAN.replace("donkey", "goat"), cid="chained", aired=1),
                  _row(CLEAN.replace("donkey", "horse"), cid="gate-events", aired=3)]
        shelf = {"gallery": [{"at": time.time(), "aired": 1, "aired_at": time.time() - 60,
                              "entry": _row(CLEAN.replace("train", "bus"), cid="nc", verdict="non_compliant", aired=0)}],
                 "news": [{"at": time.time(), "entry": _row(CLEAN.replace("train", "tram"), cid="fine", aired=0)}]}
        calls = [{"id": "echo-call", "ts": time.time() - 7200, "transcript": [
            {"who": "dj", "text": "Shave it."}, {"who": "caller", "text": "Shave it? What do you mean?"}] * 4},
                 {"id": "good-call", "ts": time.time(), "transcript": [{"who": "caller", "text": "A fine call."}]}]
        for name, body in (("larder.json", larder), ("prep_shelf.json", shelf), ("call_log.json", calls)):
            with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                json.dump(body, fh)
        db = sqlite3.connect(os.path.join(d, "system3.sqlite3"))
        db.execute("CREATE TABLE conversations(id TEXT PRIMARY KEY, verdict TEXT, body BLOB)")
        db.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, conversation_id TEXT, kind TEXT, "
                   "family TEXT, turn_id TEXT, body BLOB)")
        planned = {"turns": [{"speaker": "A", "text": "The late train was running on a donkey schedule"},
                             {"speaker": "B", "text": "The late train was running on a donkey schedule!"}],
                   "validation": {"verdict": "partial"}}
        db.execute("INSERT INTO conversations VALUES(?,?,?)",
                   ("planned-copies", "partial", zlib.compress(json.dumps(planned).encode())))
        db.execute("INSERT INTO conversations VALUES(?,?,?)",
                   ("clean", "compliant", zlib.compress(json.dumps({"turns": []}).encode())))
        # [s3-turnchain] the LIVE turnchain gate: a conversation whose own
        # turn_gate record flags turns, and one whose record is GATE events
        chained = {"turns": [], "turn_gate": {"caught": 1, "rewritten": 0, "dropped": 1,
                                              "trimmed": 0, "visits": 2, "held": ""}}
        db.execute("INSERT INTO conversations VALUES(?,?,?)",
                   ("chained", "partial", zlib.compress(json.dumps(chained).encode())))
        db.execute("INSERT INTO conversations VALUES(?,?,?)",
                   ("gate-events", "compliant", zlib.compress(json.dumps({"turns": []}).encode())))
        for i, stage in enumerate(("caught", "dropped")):
            db.execute("INSERT INTO events(conversation_id, kind, family, turn_id, body) VALUES(?,?,?,?,?)",
                       ("gate-events", "observation", "GATE", "gate-events:t%02d" % (i + 2),
                        zlib.compress(json.dumps({"stage": stage, "rule": "copy"}).encode())))
        db.commit()
        db.close()

    def run_sweep(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.sweep.main(["--data", self.dir.name, *argv])
        return code, out.getvalue(), err.getvalue()

    def test_the_dry_run_lists_every_round_the_gate_retires_and_writes_nothing(self):
        code, out, err = self.run_sweep("--json")
        self.assertEqual(code, 0)
        found = {f["key"]: f for f in json.loads(out)}
        self.assertEqual(sorted(found), ["call:echo-call", "cid:broken", "cid:chained",
                                         "cid:gate-events", "cid:nc", "cid:planned-copies"])
        self.assertTrue(found["cid:broken"]["why"].startswith("copied turns"))
        self.assertIn("non_compliant", found["cid:nc"]["why"])
        self.assertTrue(found["cid:planned-copies"]["why"].startswith("System 3's record: copied turns"))
        self.assertTrue(found["call:echo-call"]["why"].startswith("an echo loop"))
        self.assertIn("turnchain gate flagged its turns (caught 1, dropped 1)", found["cid:chained"]["why"])
        self.assertIn("turnchain gate flagged its turns - 2 event(s)", found["cid:gate-events"]["why"])
        self.assertIn("caught 1", found["cid:gate-events"]["why"])
        self.assertEqual(found["cid:broken"]["aired"], 7)
        self.assertIn("dry run", err)
        self.assertFalse(os.path.exists(os.path.join(self.dir.name, "reair_ineligible.json")))

    def test_apply_marks_them_once_and_the_gate_reads_the_marks(self):
        self.run_sweep("--apply")
        path = os.path.join(self.dir.name, "reair_ineligible.json")
        marks = reair_gate.load_marks(path)
        self.assertEqual(sorted(marks), ["call:echo-call", "cid:broken", "cid:chained",
                                         "cid:gate-events", "cid:nc", "cid:planned-copies"])
        # the one only System 3's record condemns is now refused by the gate as well
        row = json.load(open(os.path.join(self.dir.name, "larder.json")))[2]
        self.assertEqual(reair_gate.refusal(row), "")
        self.assertTrue(reair_gate.refusal(row, marks).startswith("marked ineligible by the sweep"))
        before = open(path, encoding="utf-8").read()
        stores = {n: open(os.path.join(self.dir.name, n), "rb").read()
                  for n in ("larder.json", "prep_shelf.json", "call_log.json", "system3.sqlite3")}
        _code, _out, err = self.run_sweep("--apply")
        self.assertIn("marked 0 round(s)", err)
        self.assertEqual(json.loads(before)["rounds"], json.loads(open(path, encoding="utf-8").read())["rounds"])
        for name, body in stores.items():
            self.assertEqual(open(os.path.join(self.dir.name, name), "rb").read(), body,
                             "the sweep never writes the station's own stores (%s)" % name)


if __name__ == "__main__":
    unittest.main()
