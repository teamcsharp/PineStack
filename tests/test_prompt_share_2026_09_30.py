"""[prompt-share] every roll says what it put into the writer's prompt."""
import unittest
from pathlib import Path

import system3

ROOT = Path(__file__).resolve().parents[1]


def conv():
    return {"turns": [{"index": 0, "speaker": "A"}, {"index": 1, "speaker": "B"}],
            "decision_events": [
                {"family": "RS", "turn_index": 1, "selected": {"label": "Argue", "prompt": "debunks it, arguing the statement point by point"}},
                {"family": "ES", "turn_index": 1, "selected": {"label": "pity", "text": "pities them openly"}},
                {"family": "SFX", "turn_index": 1, "selected": {"label": "no clip"}},
                {"family": "FL", "turn_index": 0, "selected": {"label": "Wrap", "prompt": "wraps the subject up"}},
            ]}


class Marks(unittest.TestCase):
    def test_each_roll_knows_its_row_and_whether_it_is_in_it(self):
        c = conv()
        rows = [" 1  A  - opens the subject.",
                " 2  B  - answers what A just said: debunks it, arguing the statement point by point. "
                "DIRECTION (B): SADNESS > feeling pity (strong) - PLAY IT BIG. pities them openly."]
        system3.prompt_mark(c, rows)
        rs, es, sfx, fl = c["decision_events"]
        self.assertTrue(rs["selected"]["in_prompt"])
        self.assertEqual(rs["selected"]["prompt_row"], rows[1])
        self.assertTrue(es["selected"]["in_prompt"])
        self.assertEqual(es["selected"]["prompt"], "pities them openly")
        self.assertFalse(sfx["selected"]["in_prompt"])                   # decides a clip, not words
        self.assertEqual(sfx["selected"]["prompt"], "")
        self.assertFalse(fl["selected"]["in_prompt"])                    # its words never reached turn 1's row

    def test_the_sheets_mark_and_the_popup_shows_it_first(self):
        src = (ROOT / "system3.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("        prompt_mark(conv, rows)  "), 2)   # banter and legs sheets
        js = (ROOT / "desktop" / "renderer" / "script-page.js").read_text(encoding="utf-8")
        at = js.index("function mvRrPopOpen(")
        body = js[at:at + 2500]
        self.assertLess(body.index("mvRrPromptShare(box, r)"), body.index("every entry this roulette held"))


if __name__ == "__main__":
    unittest.main()
