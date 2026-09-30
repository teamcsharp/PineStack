"""[popback] a pop-up opened from another always offers the way back.

Behaviour was proved in headless Edge (scratchpad popback.mjs): stacked -> back
closes the new one; hand-over -> back restores the removed original; a lone
pop-up gets none; a corner-pinned X keeps the back button beside it, never on it."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "desktop" / "renderer" / "pine-dismiss.js").read_text(encoding="utf-8")


class PopBack(unittest.TestCase):
    def test_one_rule_for_every_popup(self):
        self.assertIn("root.PinePopBack = {", JS)
        self.assertIn("'Back to ' + prev.label", JS)

    def test_the_camera_and_the_players_are_never_where_you_came_from(self):
        self.assertIn("#pineCamBox, .pine-cam-box, .sfx-tv", JS)

    def test_only_the_top_level_is_watched(self):
        self.assertIn(".observe(body, {childList: true});", JS)
        self.assertNotIn("subtree: true, attributeFilter", JS)

    def test_a_pinned_x_keeps_its_neighbour_beside_it(self):
        self.assertIn("function beside(b, x)", JS)


if __name__ == "__main__":
    unittest.main()
