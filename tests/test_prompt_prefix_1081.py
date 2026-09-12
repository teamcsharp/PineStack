"""#1081: one cacheable prefix across roads and asks; landing words first;
the passage sample held for a window."""
import time
import unittest
from unittest import mock

import app
from crystal_prompts import frame_prefix, round_prompt, turn_prompt


class PromptPrefixTests(unittest.TestCase):
    world = "the world of a masked villain: dense internal rhyme, cartoon menace"
    chunks = [{"text": "Before it leaves you cut up and swimming with dirty porcelain"},
              {"text": "The world aint always merciful, and I might be the first to fall"}]

    def test_rules_world_and_passages_precede_the_road_and_the_line(self):
        text = turn_prompt("Mara needs one copper plate.", self.world, self.chunks, .88, "caller")
        order = [text.index("priorities in order"), text.index("THE STYLE WORLD"),
                 text.index("HOW THAT WRITER WRITES"), text.index("Road: "),
                 text.index("OUTPUT FORMAT:"), text.index("ORIGINAL SOURCE")]
        self.assertEqual(order, sorted(order))
        self.assertIn("Decide the landing words first", text)

    def test_the_prefix_is_identical_across_roads_and_lines(self):
        one = turn_prompt("Mara needs one copper plate.", self.world, self.chunks, .88, "caller")
        two = turn_prompt("Dale took the turn flat out.", self.world, self.chunks, .88, "banter")
        three = round_prompt([("A", "Mara needs one copper plate."), ("B", "Not tonight.")],
                             self.world, self.chunks, .88, "gallery")
        paper = turn_prompt("The market opens at 3:49 AM.", self.world, self.chunks, .88, "paper")
        self.assertEqual(frame_prefix(one), frame_prefix(two))
        self.assertEqual(frame_prefix(one), frame_prefix(three))
        self.assertEqual(frame_prefix(one), frame_prefix(paper))
        self.assertGreater(len(frame_prefix(one)), len(one) * 0.5)
        self.assertIn("PRINTED newspaper paragraph", paper)
        self.assertLess(paper.index("HOW THAT WRITER WRITES"), paper.index("PRINTED newspaper paragraph"))
        self.assertLess(paper.index("PRINTED newspaper paragraph"), paper.index("ORIGINAL SOURCE"))

    def test_a_different_strength_or_passage_sample_changes_the_prefix(self):
        one = turn_prompt("Mara needs one copper plate.", self.world, self.chunks, .88, "caller")
        softer = turn_prompt("Mara needs one copper plate.", self.world, self.chunks, .5, "caller")
        other = turn_prompt("Mara needs one copper plate.", self.world, self.chunks[:1], .88, "caller")
        self.assertNotEqual(frame_prefix(one), frame_prefix(softer))
        self.assertNotEqual(frame_prefix(one), frame_prefix(other))


class StableMaterialTests(unittest.TestCase):
    def setUp(self):
        app._CRYSTAL_MATERIAL_MEMO.clear()
        self.addCleanup(app._CRYSTAL_MATERIAL_MEMO.clear)
        self.calls = 0

        def sample(most, cap, ceiling):
            self.calls += 1
            return [{"text": f"passage {self.calls}-{i}", "mind": "doom"} for i in range(most)]
        self.sample = sample

    def test_the_sample_holds_for_the_window_then_turns(self):
        now = [100000.0]
        with mock.patch.object(app, "_crystal_material_sample", self.sample), \
                mock.patch.object(app, "crystal_active", lambda: [{"name": "DOOM", "minds": ["doom"]}]), \
                mock.patch.object(app.time, "time", lambda: now[0]):
            first = app.crystal_material(5, 900, stable=True)
            again = app.crystal_material(5, 900, stable=True)
            self.assertEqual(first, again)
            self.assertEqual(self.calls, 1)
            again[0]["text"] = "mutated"                       # a copy, not the memo
            self.assertEqual(app.crystal_material(5, 900, stable=True)[0]["text"], "passage 1-0")
            self.assertEqual(app.crystal_material_status()["passages"], 5)
            now[0] += app.CRYSTAL_MATERIAL_WINDOW + 1
            turned = app.crystal_material(5, 900, stable=True)
            self.assertNotEqual(first, turned)
            self.assertEqual(self.calls, 2)
            # A different crystal or a different ask size is its own sample.
            app.crystal_material(3, 900, stable=True)
            self.assertEqual(self.calls, 3)
            # The pool builder still samples fresh every time.
            app.crystal_material(240, 900, ceiling=240)
            app.crystal_material(240, 900, ceiling=240)
            self.assertEqual(self.calls, 5)


if __name__ == "__main__":
    unittest.main()
