"""#1075: the Gazette's rewrite is asked for as print, every other road as before."""
import unittest

from crystal_prompts import round_prompt, turn_prompt


class PaperRegisterTests(unittest.TestCase):
    SOURCE = 'Later, at 4:00 AM, Junebug called live from the apartment stairwell.'

    def test_paper_turns_carry_the_print_register_and_clock_rule(self):
        prompt = turn_prompt(self.SOURCE, 'world', [{'text': 'sample'}], 0.88, 'paper')
        self.assertIn('PRINTED newspaper paragraph', prompt)
        self.assertIn('Keep every clock time as digits', prompt)
        self.assertIn('Keep the sentence count', prompt)
        self.assertIn('Road: "paper"', prompt)
        # The register sits inside the shared frame, before the quoted evidence.
        self.assertLess(prompt.index('PRINTED newspaper paragraph'), prompt.index('ORIGINAL SOURCE'))
        grouped = round_prompt([('P', self.SOURCE), ('P', 'Skip inquired about her request.')],
                               'world', [{'text': 'sample'}], 0.88, 'paper')
        self.assertIn('PRINTED newspaper paragraph', grouped)

    def test_spoken_roads_are_unchanged(self):
        for kind in ('', 'banter', 'caller', 'ad', 'news', 'sfxguy'):
            prompt = turn_prompt(self.SOURCE, 'world', [{'text': 'sample'}], 0.88, kind)
            self.assertNotIn('PRINTED newspaper paragraph', prompt, kind)
            self.assertNotIn('Register:', prompt, kind)


if __name__ == '__main__':
    unittest.main()
