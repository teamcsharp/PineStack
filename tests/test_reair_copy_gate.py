"""[s3-reair-copy] A stored round drawn for re-air passes the same copy gate a
new round passes (system3.gate_check), or it is retired - recorded as a mark,
restorable - and never aired. The specimen is memo bank c33d5f0988e4's shape:
a turn that repeats a long run of an earlier turn (turn 8 = 16 words of turn 5),
and a sentence said twice inside one turn. Imports app for the station door."""
import asyncio
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import reair_gate

ROOT = Path(reair_gate.__file__).resolve().parent
LONG = "the heat coming off the machine upstairs is going to cost somebody their job by friday"
CLEAN = ("A: The boombox in the booth goes by Friday, the manager says.\n"
         "B: Friday? That boombox has survived three managers and a flood.\n"
         "A: Then it can survive a memo written on the back of a napkin.")
ACROSS = ("A: I am telling you %s and nobody is listening.\n"
          "B: Nobody listens to you at four in the morning, that is the job.\n"
          "A: Fine, but %s whatever you say." % (LONG, LONG))
INSIDE = ("A: Listen to me. %s. I mean it tonight. %s.\n"
          "B: You said that already, and louder than the record." % (LONG.capitalize(), LONG.capitalize()))


def load(name, target):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = (ROOT / target).read_text(encoding="utf-8")
    return mod, text


def row(script, cid="c1"):
    return {"entry": {"script": script, "system3": {"conversation_id": cid, "verdict": "compliant"}}}


class Gate(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(reair_gate, "RETIRE_HOOK", None)      # never the station's real marks
        p.start()
        self.addCleanup(p.stop)

    def test_the_gate_reports_a_retirement_once_through_its_hook(self):
        seen = []
        with mock.patch.object(reair_gate, "RETIRE_HOOK", lambda keys, why: seen.append((keys, why))):
            reair_gate.refusal(row(ACROSS, "h1"))
            reair_gate.refusal(row(ACROSS, "h1"))                   # memoised: reported once
            reair_gate.refusal(row(CLEAN, "h2"))
        self.assertEqual(len(seen), 1)
        self.assertIn("cid:h1", seen[0][0])
        self.assertTrue(seen[0][1].startswith("the copy gate:"))

    def test_the_tools_are_applied(self):
        for name, target in (("reair_copy_gate_patch", "reair_gate.py"), ("reair_copy_gate_app_patch", "app.py")):
            mod, text = load(name, target)
            applied, missing = mod.check(text)
            self.assertEqual(missing, [], name)
            self.assertEqual(applied, len(mod.plan(text)), name)

    def test_a_clean_round_passes(self):
        self.assertEqual(reair_gate.refusal(row(CLEAN)), "")

    def test_a_turn_repeating_an_earlier_turns_run_is_refused_by_the_copy_gate(self):
        why = reair_gate.refusal(row(ACROSS, "c2"))
        self.assertTrue(why.startswith("the copy gate: turn 3"), why)
        self.assertIn("turn 1", why)
        self.assertIn("words in a row", why)
        self.assertEqual(reair_gate.copied_turns(reair_gate.turns_of(row(ACROSS))), [])  # the old rule passed it

    def test_a_sentence_said_twice_inside_one_turn_is_refused(self):
        why = reair_gate.refusal(row(INSIDE, "c3"))
        self.assertTrue(why.startswith("the copy gate: a sentence of turn 1"), why)

    def test_an_allow_mark_restores_it_and_a_plain_mark_still_retires(self):
        r = row(ACROSS, "c4")
        self.assertEqual(reair_gate.refusal(r, {"cid:c4": {"why": "x", "allow": True}}), "")
        self.assertIn("marked ineligible", reair_gate.refusal(row(CLEAN, "c5"), {"cid:c5": {"why": "x"}}))


class StationDoor(unittest.TestCase):
    def setUp(self):
        import app
        self.assertIs(reair_gate.RETIRE_HOOK, app._reair_copy_retire)   # the station registered its recorder

    def test_a_refused_replay_is_retired_once_as_a_restorable_mark(self):
        import app
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reair_ineligible.json"
            with mock.patch.object(app, "REAIR_MARKS_PATH", path), \
                    mock.patch.object(app, "_REAIR_MARKS", {"at": 0.0, "mtime": -1.0, "marks": {}}), \
                    mock.patch.object(app, "_REAIR_COPY_RETIRED", set()), \
                    mock.patch.object(app, "_REAIR_GATE_SAID", {}), \
                    mock.patch.object(app, "pipeline_log", lambda *a, **k: None):
                why = app.bank_reair_refusal("memo", row(ACROSS, "c9"))      # no loop: written at once
                self.assertTrue(why.startswith("the copy gate:"))
                marks = json.loads(path.read_text())["rounds"]
                self.assertEqual(list(marks), ["cid:c9"])
                self.assertIn("copy gate", marks["cid:c9"]["by"])
                self.assertIn("allow", marks["cid:c9"]["restore"])
                app.bank_reair_refusal("memo", row(ACROSS, "c9"))           # once
                self.assertEqual(len(json.loads(path.read_text())["rounds"]), 1)
                self.assertEqual(app.bank_reair_refusal("memo", row(CLEAN, "c8")), "")
                # restored by the operator: the roulette decides again
                body = json.loads(path.read_text())
                body["rounds"]["cid:c9"]["allow"] = True
                path.write_text(json.dumps(body))
                app._REAIR_MARKS.update(mtime=-1.0, at=0.0)          # its 30 s look-again window
                self.assertEqual(app.bank_reair_refusal("memo", row(ACROSS, "c9")), "")

    def test_inside_the_loop_the_mark_is_written_off_it(self):
        import app
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reair_ineligible.json"

            async def go():
                app.bank_reair_refusal("banter", row(INSIDE, "c7"))
                for _ in range(50):
                    await asyncio.sleep(0.02)
                    if path.exists():
                        break
            with mock.patch.object(app, "REAIR_MARKS_PATH", path), \
                    mock.patch.object(app, "_REAIR_COPY_RETIRED", set()), \
                    mock.patch.object(app, "pipeline_log", lambda *a, **k: None):
                asyncio.run(go())
            self.assertIn("cid:c7", json.loads(path.read_text())["rounds"])


if __name__ == "__main__":
    unittest.main()
