"""Source echo cleanup is exact and preserves actual quoted speech."""
import unittest

from crystal_source import clean_repair_prompt_echo, strip_repair_prompt_echo


class CrystalSourceTests(unittest.TestCase):
    def test_actual_reordered_cached_echo_retains_source_after_it(self):
        echo = ('Give back the repaired text and nothing else. '
                'Do not summarise it, do not tidy up the language, do not add anything '
                'of your own and do not comment on it. Put in the full stops and the '
                'capitals, break it into sentences, and repair what has obviously come out wrong. ')
        actual = "Good. It's about two billion people all over the world that look like us."
        result = clean_repair_prompt_echo(echo + actual)
        self.assertEqual(result['text'], actual)
        self.assertEqual(''.join(row['text'] for row in result['removed']), echo)
        self.assertEqual(len(result['removed']), 3)
        self.assertTrue(result['changed'])

    def test_full_harvest_prompt_echo_and_punctuation_spacing_case_variants(self):
        echoed = ('Below is a rough machine transcript of people talking: no punctuation, '
            'no capitals, no sentence breaks, words mis-heard all through it. '
            'Write it out properly: put in the full stops and the capitals, break it '
            'into sentences, and repair what has obviously come out wrong. '
            'Keep every word and every turn of phrase you can. '
            'Do not summarise it, do not tidy up the language, do not add anything '
            'of your own and do not comment on it. '
            'Give back the repaired text and nothing else. ')
        self.assertEqual(strip_repair_prompt_echo(echoed + 'The actual source stays.'), 'The actual source stays.')
        variant = '  GIVE BACK\n the repaired text, and nothing else!\nStill Mixed CASE; still here.'
        self.assertEqual(strip_repair_prompt_echo(variant), 'Still Mixed CASE; still here.')

    def test_old_cache_gem_can_be_entirely_echo_without_inventing_replacement(self):
        for line in ('Give back the repaired text and nothing else.',
                     'Put in the full stops and the capitals.',
                     'Do not summarise it. Do not tidy up the language.',
                     'Keep every word and every turn of phrase you can.'):
            self.assertEqual(strip_repair_prompt_echo(line), '')

    def test_legitimate_quoted_embedded_or_similar_imperatives_are_untouched(self):
        examples = [
            '"Give back the repaired text and nothing else," she said.',
            '“Give back the repaired text and nothing else.”',
            'She said: Give back the repaired text and nothing else.',
            'A: Give back the repaired text and nothing else.',
            'Give back my property and nothing else.',
            'Do not summarise my story. I need every word.',
            '"Do not summarise it," she told the reporter.',
            'Put in the full stops and the capitals it was like working there.',
            'Keep every word, every promise, and every receipt.',
            'Keep every word and every turn of phrase you can remember.',
            'Give back the repaired text and nothing else will happen.',
            'First comes the scene. Give back the repaired text and nothing else.',
            'Give back the repaired text and nothing elsewhere.',
            '  Actual speech with its leading spaces.  ',
        ]
        for text in examples:
            with self.subTest(text=text):
                result = clean_repair_prompt_echo(text)
                self.assertEqual(result, {'text': text, 'changed': False, 'removed': []})

    def test_cleanup_is_idempotent_and_only_removes_anchored_complete_clauses(self):
        text = 'Give back the repaired text and nothing else. She said, "Do not summarise it."'
        once = strip_repair_prompt_echo(text)
        self.assertEqual(once, 'She said, "Do not summarise it."')
        self.assertEqual(strip_repair_prompt_echo(once), once)
        with self.assertRaises(TypeError):
            clean_repair_prompt_echo(None)


if __name__ == '__main__':
    unittest.main()
