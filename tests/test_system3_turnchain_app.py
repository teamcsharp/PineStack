"""[s3-turnchain] app.py's half of the copy gate, run out of app.py's own source.

The functions tools/system3_turnchain_patch.py adds or changes - _s3_copy_gate,
_banter_beats (Mode B), _s3_said_copy (the microphone) - are compiled out of
app.py and run in a namespace with stub writers (no model is called) and a
real System3Runtime on a temp store (test_system3_runtime.FakeStation), so
nothing here imports the station or touches its data dir. The wiring: the
tool answers "applied" on app.py, and the three roads call the gate."""
import ast
import asyncio
import copy
import importlib.util
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

import system3
import system3_runtime

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
TREE = ast.parse(SOURCE)
FIX = json.loads((Path(__file__).resolve().parent / "system3_turnchain_fixtures.json").read_text(encoding="utf-8"))
CALL_A, BANTER = "cc672e24cc5f452a", "ef39853f9fa54974"


def compiled(names):
    nodes = []
    for node in TREE.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if {t.id for t in targets if isinstance(t, ast.Name)} & names:
                nodes.append(node)
        elif getattr(node, "name", "") in names:
            nodes.append(node)
    return compile(ast.Module(body=nodes, type_ignores=[]), "app.py:turnchain", "exec")


def body_of(name):
    node = next(n for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ast.get_source_segment(SOURCE, node) or ""


def parse(script, *_args):
    s = re.sub(r"(^|\s)Miss Patty\s*:\s*", r"\1C: ", str(script or ""))
    parts = re.split(r"(?:^|\s)([ABCDE])\s*:\s*", " " + s)
    return [(parts[i], " ".join(parts[i + 1].split())) for i in range(1, len(parts) - 1, 2)]


SYL = ("ka", "lo", "mi", "tru", "ven", "sa", "po", "dri", "zu", "fen", "gor", "ha", "jin", "ble", "qua",
       "rix", "tam", "wo", "yel", "nob")


def fresh(n):
    w = [SYL[(n * 7 + k * 3) % 20] + SYL[(n * 11 + k * 5 + 1) % 20] + SYL[(n * 13 + k + 2) % 20] for k in range(4)]
    return "The %s and the %s, after %s met %s." % tuple(w)


class Station:
    """A real System3Runtime on a temp store, and the namespace the gate's code runs in."""

    def __init__(self, test):
        from test_system3_runtime import FakeStation, settle
        self.settle = settle
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        test.addCleanup(self.tmp.cleanup)
        self.rt = system3_runtime.System3Runtime(system3_runtime._Host(FakeStation(self.tmp.name)))
        self.rt.settings = system3.normalise_settings({"mode": "active", "roads": ["banter", "caller"]})
        self.rt.ready = True
        test.addCleanup(lambda: (settle(), self.rt.store.close()))
        self.logged, self.dropped, self.asked = [], [], []
        self.ns = {"asyncio": asyncio, "re": re, "time": time, "Any": Any,
                   "banter_turns": parse, "spoken_text": lambda v: " ".join(str(v or "").split()),
                   "pipeline_log": lambda kind, text, extra="": self.logged.append((kind, text)),
                   "note_drop": lambda who, text, why: self.dropped.append((who, text, why)),
                   "prep_should_stop": lambda: "", "_verbatim_turn_text": lambda v: str(v),
                   "_s3_active": lambda: True, "line_review_capture": lambda *a, **k: None,
                   "system3_turn_gate": self.rt.turn_gate, "system3_turn_gate_next": self.rt.turn_gate_next,
                   "system3_turn_gate_reply": self.rt.turn_gate_reply, "system3_turn_gate_done": self.rt.turn_gate_done,
                   "system3_line_copies": self.rt.line_copies, "system3_line_gate": self.rt.line_gate}
        self.ns["globals"] = lambda: self.ns

    def handle(self, cid):
        conv = copy.deepcopy(FIX["rounds"][cid]["conv"])
        conv["identity"]["conversation_id"] = "x" + cid
        for t in conv["turns"]:
            t["turn_id"] = t["turn_id"].replace(cid, "x" + cid)
        return system3_runtime.Handle(self.rt, conv, system3.default_config(), True)

    def events(self, conv):
        self.rt.persist(conv)
        self.settle()
        got = self.rt.store.conversation(conv["identity"]["conversation_id"]) or {}
        return [e for e in got.get("observations_air") or [] if e.get("family") == "GATE"]


class CopyGateAtTheBind(unittest.TestCase):
    def setUp(self):
        self.st = Station(self)
        exec(compiled({"_s3_copy_gate"}), self.st.ns)

    def writer(self, fail=False):
        async def ask_model(prompt, **kw):
            self.st.asked.append((prompt, kw))
            seat = re.search(r"Output exactly one line and nothing else: ([A-E]): <the words>", prompt).group(1)
            if fail:
                return "%s: %s" % (seat, re.search(r'YOUR DRAFT REPEATED [^:]+: "(.+?)"', prompt).group(1).rstrip("…"))
            return "%s: %s" % (seat, fresh(len(self.st.asked)))
        return ask_model

    def run_gate(self, cid, prepared=True, fail=False):
        self.st.ns["ask_model"] = self.writer(fail)
        h = self.st.handle(cid)
        script = FIX["rounds"][cid]["writer"]
        written = int(FIX["rounds"][cid]["conv"]["validation"]["written"])
        script = "\n".join("%s: %s" % t for t in parse(script)[:written])
        out, held = asyncio.run(self.st.ns["_s3_copy_gate"](script, h, "Miss Patty", "", prepared))
        return h, script, out, held

    def test_the_sewer_call_airs_no_copy_and_keeps_its_ending(self):
        h, script, out, held = self.run_gate(CALL_A)
        self.assertEqual(held, "")
        turns = parse(out)
        for i, (_m, t) in enumerate(turns):
            for j in range(i):
                self.assertEqual(system3.gate_copies(system3.gate_words(t), system3.gate_words(turns[j][1])), "")
        self.assertLess(len(turns), len(parse(script)))
        self.assertEqual([m for m, _t in turns[-2:]], ["C", "A"])
        self.assertEqual(len(self.st.asked), h.conv["turn_gate"]["visits"])
        for prompt, kw in self.st.asked:
            self.assertEqual(kw["mark"]["kind"], "turn rewrite")
            self.assertFalse(kw["mark"]["live"])
            self.assertIn("THE LINE YOU ANSWER", prompt)
        stages = [e["stage"] for e in self.st.events(h.conv)]
        self.assertEqual(stages.count("caught"), 4)
        self.assertEqual(stages.count("re-written"), 3)
        self.assertTrue(any(k == "system3" and "copy gate: 4 caught, 3 re-written" in t for k, t in self.st.logged))

    def test_a_writer_that_keeps_copying_holds_the_call(self):
        h, _script, _out, held = self.run_gate(CALL_A, fail=True)
        self.assertIn("could not be written without copying", held)
        self.assertTrue(any("HELD" in t for _k, t in self.st.logged))

    def test_a_live_round_is_not_rewritten(self):
        h, _script, out, held = self.run_gate(BANTER, prepared=False)
        self.assertEqual(self.st.asked, [])
        self.assertEqual(held, "")
        self.assertEqual(h.conv["turn_gate"]["rewritten"], 0)
        self.assertGreater(h.conv["turn_gate"]["dropped"], 0)

    def test_no_system3_round_or_no_runtime_the_script_stands(self):
        async def never(*_a, **_k):
            raise AssertionError("no writer visit")
        self.st.ns["ask_model"] = never
        h = self.st.handle(CALL_A)
        h.active = False
        got = asyncio.run(self.st.ns["_s3_copy_gate"]("A: one.\nB: two.", h, "", "", True))
        self.assertEqual(got, ("A: one.\nB: two.", ""))
        del self.st.ns["system3_turn_gate"]
        got = asyncio.run(self.st.ns["_s3_copy_gate"]("A: one.\nB: two.", self.st.handle(CALL_A), "", "", True))
        self.assertEqual(got, ("A: one.\nB: two.", ""))

    def test_a_writer_fault_is_a_failed_try_not_a_lost_round(self):
        async def broken(*_a, **_k):
            raise RuntimeError("the lane is full")
        self.st.ns["ask_model"] = broken
        h = self.st.handle(BANTER)
        script = FIX["rounds"][BANTER]["writer"]
        out, held = asyncio.run(self.st.ns["_s3_copy_gate"](script, h, "", "", True))
        self.assertEqual(held, "")
        self.assertEqual(h.conv["turn_gate"]["rewritten"], 0)
        self.assertTrue(out.strip())
        self.assertTrue(any("was not written" in t for _k, t in self.st.logged))


class ModeBBeats(unittest.TestCase):
    NAMES = {"_BANTER_BEAT_ROW", "_BANTER_BEAT_STOCK", "_BANTER_BEAT_STOP", "WritingDeferred",
             "_beat_content_words", "_beat_answers", "_beat_sequence_answers", "_banter_beat_plan",
             "_beat_fresh_only", "_beat_speaks_direction", "_banter_beats"}

    def setUp(self):
        self.st = Station(self)
        exec(compiled(self.NAMES), self.st.ns)

    def test_a_copied_line_never_seats_and_the_retry_is_told(self):
        prompts = []
        h = self.st.handle(BANTER)

        async def ask_model(prompt, **_kw):
            prompts.append(prompt)
            rows = re.findall(r"(?m)^(\d+)  ([ABCD])  -", prompt)
            out = []
            for k, (turn, seat) in enumerate(rows):
                if len(prompts) == 1 and k == 1:
                    # the subject row read back word for word, on the first try
                    out.append("%s: You have to stop microwaving pets. The manager is going to catch you "
                               "and he's going to fire you bro." % seat)
                else:
                    out.append("%s: signal answer %s, %s." % (seat, turn, fresh(len(prompts) * 10 + k)))
            return "\n".join(out)

        self.st.ns["ask_model"] = ask_model
        sheet = "\n".join("%2d  %s  - answers the prior turn" % (t, "A" if t % 2 else "B") for t in range(1, 9))
        trace = []
        script = asyncio.run(self.st.ns["_banter_beats"](
            "Discuss the signal.", sheet, 8, ["A", "B"], seed_text="The signal begins here.", trace=trace,
            gate=self.st.rt.beat_gate(h)))
        turns = parse(script)
        self.assertEqual(len(turns), 8)
        self.assertFalse(any("microwaving" in t for _m, t in turns))
        self.assertIn("Its draft of the first listed turn repeated", prompts[1])
        self.assertEqual(h.conv["turn_gate"]["in_chain"]["caught"], 1)
        self.assertEqual([e["stage"] for e in self.st.events(h.conv)], ["caught in the beat chain"])

    def test_an_empty_line_is_written_again_not_skipped_past(self):
        prompts = []
        h = self.st.handle(BANTER)

        async def ask_model(prompt, **_kw):
            prompts.append(prompt)
            rows = re.findall(r"(?m)^(\d+)  ([ABCD])  -", prompt)
            return "\n".join("%s: %s" % (seat, "*laughs*" if (len(prompts) == 1 and k == 0) else
                                         "line %s, %s." % (turn, fresh(len(prompts) * 10 + k)))
                             for k, (turn, seat) in enumerate(rows))

        self.st.ns["ask_model"] = ask_model
        # the station's spoken_text drops a stage direction: nothing is left of that line
        self.st.ns["spoken_text"] = lambda v: " ".join(re.sub(r"\*[^*]*\*", " ", str(v or "")).split())
        sheet = "\n".join("%2d  %s  - answers the prior turn" % (t, "A" if t % 2 else "B") for t in range(1, 7))
        script = asyncio.run(self.st.ns["_banter_beats"](
            "Discuss the signal.", sheet, 6, ["A", "B"], seed_text="The signal begins here.", trace=[],
            gate=self.st.rt.beat_gate(h)))
        turns = parse(script)
        self.assertEqual([m for m, _t in turns], ["A", "B", "A", "B", "A", "B"], "no row slid a seat")
        self.assertIn("empty once cleaned", prompts[1])

    def test_without_a_gate_the_chain_is_as_it_was(self):
        prompts = []

        async def ask_model(prompt, **_kw):
            prompts.append(prompt)
            rows = re.findall(r"(?m)^(\d+)  ([ABCD])  -", prompt)
            return "\n".join("%s: signal %s, %s." % (seat, turn, fresh(len(prompts) * 10 + k))
                             for k, (turn, seat) in enumerate(rows))
        self.st.ns["ask_model"] = ask_model
        sheet = "\n".join("%2d  %s  - answers the prior turn" % (t, "A" if t % 2 else "B") for t in range(1, 11))
        trace = []
        script = asyncio.run(self.st.ns["_banter_beats"](
            "Discuss the signal.", sheet, 10, ["A", "B"], seed_text="The signal begins here.", trace=trace))
        turns = parse(script)
        self.assertGreaterEqual(len(turns), 8)
        self.assertEqual(turns[0], ("A", "The signal begins here."))
        self.assertFalse(any("Its draft of the first listed turn repeated" in p for p in prompts))


class TheMicrophone(unittest.TestCase):
    def setUp(self):
        self.st = Station(self)
        exec(compiled({"S3_SAID_KEEP", "S3_SAID_WINDOW", "_S3_SAID", "_s3_said_copy"}), self.st.ns)

    def test_the_line_just_said_is_not_said_again_on_any_road(self):
        said = self.st.ns["_s3_said_copy"]
        line = "Lines are open at the station. Waiting on our first caller."
        node = asyncio.run(self.st.rt.direct_line({"road": "open", "who": "dj", "dj": {"host_name": "Dill"},
                                                   "context": "open the show"}))
        self.assertEqual(said(line, "dj", "open", node), "")
        node2 = asyncio.run(self.st.rt.direct_line({"road": "open", "who": "dj", "dj": {"host_name": "Dill"},
                                                    "context": "open the show"}))
        why = said(line, "dj", "open", node2)
        self.assertIn("it repeats the line dj said", why)
        self.assertEqual(self.st.dropped[-1][0], "dj")
        self.assertEqual(node2.conv["status"], "dropped")
        self.assertEqual(self.st.events(node2.conv)[-1]["stage"], "dropped at the microphone")
        # another line is said; the stock phrase's other half is not a copy
        self.assertEqual(said("We are waiting for a request from our caller. Checking the lines now.", "dj", "open"), "")
        # a round's turn with its stamp, the same way
        self.assertTrue(said(line, "cohost", "turn", {"conversation_id": node.id, "turn_id": node.stamp["turn_id"]}))
        # out of the window, it may come round again
        self.st.ns["_S3_SAID"][:] = [dict(r, at=r["at"] - 10 * self.st.ns["S3_SAID_WINDOW"]) for r in self.st.ns["_S3_SAID"]]
        self.assertEqual(said(line, "dj", "open"), "")

    def test_system3_off_the_microphone_is_as_it_was(self):
        self.st.ns["_s3_active"] = lambda: False
        said = self.st.ns["_s3_said_copy"]
        self.assertEqual(said("Same line here, word for word.", "dj", "open"), "")
        self.assertEqual(said("Same line here, word for word.", "dj", "open"), "")
        self.assertEqual(self.st.ns["_S3_SAID"], [])


class Wiring(unittest.TestCase):
    def test_the_tool_is_applied_and_the_roads_call_the_gate(self):
        spec = importlib.util.spec_from_file_location("system3_turnchain_patch",
                                                      ROOT / "tools" / "system3_turnchain_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        applied, missing = mod.check(SOURCE)
        self.assertEqual((missing, applied), ([], len(mod.plan(SOURCE))))
        dj = body_of("dj_banter")
        at = dj.index("_s3_copy_gate(script, _s3, caller_name, caller2_name")
        self.assertLess(dj.index("script = plot_label_scrub(script)"), at)
        self.assertLess(at, dj.index("[#1249] the round's topic contract, graded on the words that will air"))
        self.assertLess(at, dj.index('globals()["system3_bind_entry"](entry, _s3)'))
        self.assertIn('gate=(globals()["system3_beat_gate"](_s3)', dj)
        self.assertIn("_s3_said_copy(\n            spoken, who, kind,", body_of("_dj_speak_floorless"))
        turns = body_of("_speak_turns_floorless")
        self.assertLess(turns.index("_s3_said_copy("), turns.index("_rerun = rerun_check(text, who,"))


if __name__ == "__main__":
    unittest.main()
