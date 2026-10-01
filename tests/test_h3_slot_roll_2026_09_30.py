"""[h3-slot-roll] {speakerbox} and {a|b|c} in an hourly prompt are rolls, and the viewer spins them."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "app.py").read_text(encoding="utf-8")
JS = (ROOT / "desktop" / "renderer" / "ad-viewer.js").read_text(encoding="utf-8")


class Slots(unittest.TestCase):
    def test_the_slot_pattern(self):
        # [h3-slots] 2026-10-01: the named slots ({mxtape} ... {arena2}) joined the pattern,
        # [h3-feature] then {feature} and {releaselog}
        names = r"(?:mxtape|fordtape|videos|sfxclip|convograph|gazette|arena|feature|releaselog)\d?"
        rx = re.compile(r"\{(speakerbox|" + names + r"|[^{}|\n]+(?:\|[^{}|\n]+)+)\}")
        self.assertIn('H3_SLOT_NAMES = r"' + names + '"', SRC)
        self.assertIn('H3_SLOT_RX = re.compile(r"\\{(speakerbox|" + H3_SLOT_NAMES + r"|[^{}|\\n]+(?:\\|[^{}|\\n]+)+)\\}")', SRC)
        found = [m.group(1) for m in rx.finditer("tune in {speakerbox} - {red|blue} for {station} and {conversation} "
                                                 "in {arena2}")]
        self.assertEqual(found, ["speakerbox", "red|blue", "arena2"])   # the station's own slots are left alone

    def test_the_rolls_are_system3s_and_ride_the_hour(self):
        for key in ('"h3.slot_doc"', '"h3.slot_sentence"', '"h3.slot_choice"'):
            self.assertIn(key, SRC)
        self.assertIn('_h3_slot_note("slot_doc", "h3.slot_doc"', SRC)
        self.assertIn("template = h3_slots_roll(template)", SRC)

    def test_the_viewer_spins_a_rolodex(self):
        self.assertIn("function rolodex(reels)", JS)
        self.assertIn("if (item.reels) cell.append(label, rolodex(item.reels));", JS)
        self.assertIn(".join('\\n')", JS)


if __name__ == "__main__":
    unittest.main()
