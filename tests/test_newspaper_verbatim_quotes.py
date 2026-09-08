"""#1075: a quoted interview answer is the air log verbatim; the paper does not rewrite it."""
import unittest

import app


class VerbatimQuoteTests(unittest.TestCase):
    def test_quoted_answers_are_not_tint_units_but_questions_and_plain_answers_are(self):
        story = {'slug': 'the-interview', 'body': '', 'meta': {'interview': {'qa': [
            {'q': 'Last word?', 'a': '"I\'ll spill what she scripted, lay it out plain; is it clear in your brain?"'},
            {'q': 'Which line are you standing by?', 'a': 'The log has me quiet on that, and I would rather the paper printed the quiet.'},
            {'q': 'What did the other seat get wrong?', 'a': '“Heat? It’s not just heat; it’s the pressure building.”'},
        ]}}}
        keys = [unit['key'] for unit in app.paper_tint_units(story)]
        self.assertEqual(keys, ['qa:0:q', 'qa:1:q', 'qa:1:a', 'qa:2:q'])
        plan = app.paper_tint_plan(story)
        self.assertEqual(plan['eligible'], 4)


if __name__ == '__main__':
    unittest.main()
