"""[tint-off] [flow-ledger] Tinting off means off; every rejection is seen and can be approved (#1584 #1585 #1570).

Run from the repo root:  python3 tests/test_tint_off_ledger_2026_10_05.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import flow_ledger  # noqa: E402

APP = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")


def block(head: str, stop: str) -> str:
    start = APP.index(head)
    return APP[start:APP.index(stop, start + len(head))]


class TintOffTest(unittest.TestCase):
    def test_a_tint_that_never_ran_prints_nothing_and_one_that_ran_still_does(self):
        ns: dict = {"Any": object}
        exec(compile(block("def paper_tint_status(", "\ndef paper_tinted_by("), "status", "exec"), ns)
        status = ns["paper_tint_status"]
        never = {"tint": {"eligible": 23, "attempted": 0, "changed": 0, "target": 82, "required": 19,
                          "met": False, "status": "pending", "paragraphs": []}}
        self.assertEqual(status(never), "")                                   # the line the operator screenshotted
        self.assertEqual(status({}), "")
        ran = {"tint": {"eligible": 23, "attempted": 9, "changed": 7, "target": 82, "status": "partial"}}
        self.assertIn("Crystal tint: 7/23 eligible paragraphs; 9 attempted", status(ran))
        self.assertIn("deferred by the tint lane", status({"tint": {"eligible": 3, "deferred": 2}}))

    def test_the_press_plans_only_when_a_tint_is_on(self):
        at = APP.index("# [tint-off] NO TINT, NO TINT PAPERWORK")
        after = APP[at:at + 700]
        self.assertLess(APP.rfind("tinted_by = paper_tinted_by()", 0, at), at)
        self.assertLess(after.index("if tinted_by:"), after.index("paper_tint_plan(story)"))
        self.assertEqual(APP.count("paper_tint_plan(story)"), 2)              # here, and paper_tint_story's own

    def test_stored_editions_are_rendered_again(self):
        self.assertIn("\nPAPER_RENDER_VERSION = 14 ", APP)

    def test_the_repair_step_and_the_rhyme_warm_stand_down(self):
        step = block("async def tint_recovery_step(", "\ndef _audit_superseded(")
        self.assertIn("and (not _DIALOGUE_RECOVERY or s3_flow_is_open())):", step)
        warm = block("async def crystal_rhyme_warm_once(", "\nasync def _crystal_rhyme_warm_work(")
        self.assertLess(warm.index("if not dialogue_tint_wanted() and not crystal_active():"),
                        warm.index("_RHYME_ASSISTANCE_EMBED_LOCK.locked()"))


class LedgerTest(unittest.TestCase):
    def test_a_row_carries_its_seat_and_can_be_found_and_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = flow_ledger.Ledger(Path(tmp) / "flow.jsonl", autoflush=False)
            led.note("final_handoff", "passed one", passed=True)
            row = led.note("dropped_line", "System 3 copy gate: it repeats the line", passed=False,
                           who="cohost", road="banter", text="Well, that is the  station for you.")
            self.assertEqual(row["who"], "cohost")
            self.assertNotIn("who", led.find(1))
            self.assertEqual(led.find(row["n"])["text"], "Well, that is the station for you.")
            self.assertIsNone(led.find(999))
            got = led.mark(row["n"], approved=True, approved_at=5.0)
            self.assertTrue(got["approved"])
            self.assertTrue(led.recent(5, passed=False)[0]["approved"])
            self.assertIsNone(led.mark(999, approved=True))
            led.flush()
            lines = [json.loads(x) for x in (Path(tmp) / "flow.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(lines[-1]["decision"], {"approved": True, "approved_at": 5.0})   # the decision is on the record
            self.assertEqual(len(led.recent(50)), 2)                                          # and is not a third row

    def test_long_lines_are_kept_whole_enough_to_say(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = flow_ledger.Ledger(Path(tmp) / "flow.jsonl", autoflush=False)
            self.assertEqual(len(led.note("dropped_line", "", passed=False, text="word " * 200)["text"]), 600)


class EveryRefusalIsSeenTest(unittest.TestCase):
    def test_the_three_doors_write_to_the_ledger_as_refusals(self):
        for head, stop, gate in (("def note_drop(", "\ndef ", '"dropped_line"'),
                                 ("def norepeat_refuse(", "\ndef norepeat_select_refuse(", '"norepeat_%s" % kind'),
                                 ("def _radio_entry_rejected(", "\ndef ", '"round:" + str(stage)')):
            body = block(head, stop)
            at = body.index("FLOW_LEDGER.note(" + gate)
            self.assertIn("passed=False", body[at:at + 420], head)
            self.assertIn("except Exception", body[at:at + 620], head)        # the ledger never takes a line down with it

    def test_approve_says_a_line_by_hand_and_never_a_round(self):
        route = block("async def api_flow_ledger_approve(", '\n@app.post("/api/flow/release")')
        self.assertIn("require_auth(authorization)", route)
        self.assertIn('.startswith("round:")', route)
        self.assertLess(route.index('.startswith("round:")'), route.index("await dj_speak("))
        self.assertIn("by_hand=True", route)
        self.assertIn("FLOW_LEDGER.mark(", route)
        self.assertIn('if row.get("passed"):', route)

    def test_the_panel_gets_the_rows_with_the_gates(self):
        self.assertIn('"rows": FLOW_LEDGER.recent(60)', block("async def api_speech_gates_get(", "\n@app.post(\"/api/speech-gates\")"))
        for name in ("desktop/renderer/speech-gates.js", "app/src/main/assets/pine-views/speech-gates.js"):
            path = ROOT / name
            if not path.exists():
                continue
            js = path.read_text(encoding="utf-8")
            self.assertIn("ui.body.appendChild(ledgerSection());", js, name)
            self.assertIn("post('/api/flow-ledger/approve', {n: r.n}", js, name)
            self.assertIn("indexOf('round:') !== 0", js, name)              # no Approve on a whole round


if __name__ == "__main__":
    unittest.main()
