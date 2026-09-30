"""[whole-words] nobody is cut off in the middle of a sentence: a roll's label
and what a host is handed end where a sentence ends, never where a character
count fell ("its important people never get cut off in the middle of sentences").
"""
import unittest

import system3

TOPIC = ("So I was having an emergency and I ran into restroom to use the bathroom and took a seat "
         "and sat down on the manager and he didn't say anything. He let me sit there and do my "
         "business on his lap.")


class WholeWords(unittest.TestCase):
    def test_label_keeps_a_board_row_whole(self):
        self.assertEqual(system3.label_cut(TOPIC), TOPIC)       # 190 characters, the popup's row

    def test_label_past_the_cap_ends_on_a_sentence(self):
        got = system3.label_cut(TOPIC, 150)
        self.assertTrue(got.endswith("anything."), got)

    def test_whole_cut_keeps_what_fits_untouched(self):
        laid = "Line one.\n  Line two."
        self.assertEqual(system3.whole_cut(laid, 400), laid)    # line breaks kept

    def test_whole_cut_ends_on_a_sentence(self):
        got = system3.whole_cut(TOPIC, 150)
        self.assertTrue(got.endswith("anything."), got)
        self.assertLessEqual(len(got), 150)

    def test_whole_cut_falls_back_to_a_word(self):
        got = system3.whole_cut("word " * 100, 42)
        self.assertLessEqual(len(got), 42)
        self.assertTrue(got.endswith("word"), got)

    def test_none_is_empty(self):
        self.assertEqual(system3.whole_cut(None, 10), "")
        self.assertEqual(system3.label_cut(None), "")

    def test_no_raw_label_slices_left(self):
        import re
        for mod in ("system3.py", "system3_runtime.py", "system3_gold.py"):
            src = open(system3.__file__.replace("system3.py", mod), encoding="utf-8").read()
            self.assertIsNone(re.search(r'"label": [^\n]*\)\[:(80|90)\]', src), mod)


if __name__ == "__main__":
    unittest.main()
