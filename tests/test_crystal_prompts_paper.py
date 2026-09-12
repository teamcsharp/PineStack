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

    def test_spoken_roads_never_get_the_PRINT_register(self):
        """2026-09-09 (#1157): a spoken road now carries a register too - the
        operator asked for the style world's own mouth, swearing included,
        and measured across 199 tint turns the model had proposed a swear
        zero times because nothing ever asked. What must stay true is that
        the two registers are never confused: print is third-person with no
        vocatives, and that must never reach a spoken bar."""
        for kind in ('', 'banter', 'caller', 'ad', 'news', 'sfxguy'):
            prompt = turn_prompt(self.SOURCE, 'world', [{'text': 'sample'}], 0.88, kind)
            self.assertNotIn('PRINTED newspaper paragraph', prompt, kind)
            self.assertNotIn('no radio sign-offs', prompt, kind)
            self.assertIn('spoken bar on a late-night radio station', prompt, kind)

    def test_the_print_register_never_carries_the_spoken_one(self):
        prompt = turn_prompt(self.SOURCE, 'world', [{'text': 'sample'}], 0.88, 'paper')
        self.assertNotIn('spoken bar on a late-night radio station', prompt)


if __name__ == '__main__':
    unittest.main()
