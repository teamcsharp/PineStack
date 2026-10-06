"""[unstick-all] "Unstick it now" releases the page, the floor and all four rooms (#1578, 2026-10-05).

Run from the repo root:  python3 tests/test_unstick_all_2026_10_05.py
Reads the source the station runs; imports nothing of the station.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")


def body(head: str, stop: str) -> str:
    start = APP.index(head)
    return APP[start:APP.index(stop, start + len(head))]


class UnstickAllTest(unittest.TestCase):
    def test_it_is_a_rung_on_the_ladder(self):
        steps = body("BROADCAST_STEPS: list[dict[str, str]] = [", "\n]\n")
        self.assertIn('{"key": "unstick", "label": "Unstick everything"', steps)
        self.assertLess(steps.index('"key": "unstick"'), steps.index('"key": "floor"'))

    def test_the_rung_releases_every_room(self):
        rung = body('    elif step == "unstick":', '    elif step == "floor":')
        for word in ("page_wedge_clear(force=True)", "_floor_break(",
                     '.pop("preparing", None)', '.pop("tinting", None)',
                     "dialogue_recovery_release()", "_UNHEARD_PENDING_HANDOFFS.clear()",
                     "_UNHEARD_REFUSED.clear()", "_UNHEARD_ROAD_OUT.clear()"):
            self.assertIn(word, rung, word)
        for room in ("  page ", "  floor ", "  writing ", "  recording ", "  reserve ", "  pantry "):
            self.assertIn(room, rung, room)                 # each room says what it gave back

    def test_the_page_reset_cannot_park_the_rung(self):
        rung = body('    elif step == "unstick":', '    elif step == "floor":')
        self.assertIn("asyncio.wait_for(page_wedge_clear(force=True), 8.0)", rung)
        self.assertIn("asyncio.create_task(dialogue_recovery_release()", rung)   # the queue drains off the request

    def test_nothing_is_deleted(self):
        rung = body('    elif step == "unstick":', '    elif step == "floor":')
        for word in (".unlink(", "retire_", "_LARDER.clear()", "_SHELF.clear()", "del _LARDER", "del _SHELF"):
            self.assertNotIn(word, rung, word)

    def test_the_button_runs_the_rung_and_answers_shortly(self):
        route = body("async def api_broadcast_unwedge(", "\n# --- #1208: THE TROUBLESHOOTING STEPS")
        self.assertIn('await broadcast_step("unstick")', route)
        self.assertNotIn("got = await page_wedge_clear(force=True)", route)
        self.assertIn("asyncio.wait_for(api_broadcast_health(authorization), 4.0)", route)
        say = re.search(r'"say": "([^"]+)"', route).group(1)
        self.assertLessEqual(len(say % 9999), 40)           # the card shows forty characters


if __name__ == "__main__":
    unittest.main()
