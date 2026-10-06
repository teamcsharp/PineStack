"""[flow-ledger] [s3-deadair] An approved line is said in place; a banked response finds a seat that has one (2026-10-05).

Run from the repo root:  python3 tests/test_approve_in_place_2026_10_05.py
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")


def block(head: str, stop: str) -> str:
    start = APP.index(head)
    return APP[start:APP.index(stop, start + len(head))]


class ApproveInPlaceTest(unittest.TestCase):
    def test_the_mark_is_set_before_the_line_is_spoken(self):
        route = block("async def api_flow_ledger_approve(", '\n@app.post("/api/flow/release")')
        self.assertLess(route.index('_S3_CHAPTER_ROW.set("row")'), route.index("await dj_speak("))
        # and only after every answer that says nothing: a refused request starts no line
        self.assertGreater(route.index('_S3_CHAPTER_ROW.set("row")'), route.index('.startswith("round:")'))

    def test_the_dead_air_node_carries_the_same_mark(self):
        run = block("async def _deadair_run(", "\ndef s3_dead_air_node(")
        self.assertLess(run.index('_S3_CHAPTER_ROW.set("row")'), run.index("s3_choice("))


class BankedSeatTest(unittest.TestCase):
    def test_a_roll_on_an_empty_seat_goes_to_one_that_has_a_response(self):
        run = block("async def _deadair_run(", "\ndef s3_dead_air_node(")
        at = run.index('if kind == "banked response":')
        bank = run[at:run.index('elif kind == "quote":', at)]
        self.assertIn("for seat in [who] + [w for w in seats if w != who]:", bank)   # the rolled seat first
        self.assertIn("who = seat", bank)
        self.assertLess(bank.index("who = seat"), bank.index('await dj_speak("aside", None, line=pick, who=who'))
        self.assertIn("norepeat_text_used", bank)                                    # still nothing heard inside the day


if __name__ == "__main__":
    unittest.main()
