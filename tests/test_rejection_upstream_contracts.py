"""Real adapter contracts and narrow lexical regressions; no external requests."""
import json
import unittest
from unittest import mock

import app
import crystal_contract
import test_crystal_model_output as adapter_fixture


class ModelResultContractTests(unittest.IsolatedAsyncioTestCase):
    setUp = adapter_fixture.CrystalModelOutputTests.setUp

    async def test_explicit_reception_sentinel_is_not_a_rejected_spoken_line(self):
        self.call.return_value = {'message': {'content': 'NONE'}, 'done_reason': 'stop'}
        self.assertEqual(await app.ask_model('Reception.', result_contract='track_reception'), 'NONE')
        app.line_review_permits.assert_not_called()
        app.line_review_capture.assert_not_called()
        self.assertEqual(await app.ask_model('Ordinary dialogue.'), '')
        self.assertEqual(app.line_review_permits.call_args.args[0], 'draft_fragment')

    async def test_reception_contract_does_not_waive_other_fragments(self):
        self.call.return_value = {'message': {'content': 'NONE because the listener'}, 'done_reason': 'stop'}
        self.assertEqual(await app.ask_model('Reception.', result_contract='track_reception'), '')
        self.assertEqual(app.line_review_permits.call_args.args[0], 'draft_fragment')

    async def test_repair_echo_is_removed_before_limit_consumes_actual_source(self):
        instructions = ('Put in the full stops and the capitals, break it into sentences, '
            'and repair what has obviously come out wrong. Keep every word and every turn of phrase you can. '
            'Do not summarise it, do not tidy up the language, do not add anything of your own and do not comment on it. '
            'Give back the repaired text and nothing else.\n\n')
        actual = 'Mara left twelve plates on the table. She will return before midnight.'
        raw = instructions + actual
        self.call.return_value = {'message': {'content': raw}, 'done_reason': 'stop'}
        self.assertEqual(await app.ask_model('Repair this source.', limit=120,
            result_contract='transcript_repair'), actual)
        app.line_review_permits.assert_not_called()
        self.assertEqual(self.call.return_value['message']['content'], raw, 'Raw wire response must remain intact')
        evidence = [json.loads(call.kwargs['extra']) for call in app.pipeline_log.call_args_list
                    if call.args and call.args[0] == 'speakbox']
        self.assertEqual(evidence[0]['original'], raw)

    async def test_unfinished_actual_transcript_is_still_held_after_echo_cleanup(self):
        self.call.return_value = {'message': {'content': 'Give back the repaired text and nothing else.\nMara left the'}}
        self.assertEqual(await app.ask_model('Repair.', result_contract='transcript_repair'), '')
        self.assertEqual(app.line_review_permits.call_args.args[:2], ('draft_fragment', 'Mara left the'))

    async def test_quoted_instruction_remains_real_source_material(self):
        source = 'Mara said, "Keep every word and every turn of phrase you can."'
        self.call.return_value = {'message': {'content': source}}
        self.assertEqual(await app.ask_model('Repair.', result_contract='transcript_repair'), source)

    async def test_unknown_contract_fails_before_any_model_call(self):
        with self.assertRaises(ValueError):
            await app.ask_model('Text.', result_contract='anything_goes')
        self.call.assert_not_awaited()


class ShortEnglishContractTests(unittest.TestCase):
    def test_actual_retained_english_greetings_and_die_verb_pass(self):
        for source in ("Yo, what's good, brodie?", "Yo, what’s good, bro?", 'YO, YO, LOOK, LOOK, LOOK.',
                       "--- Yo, >> what's good, dog?", 'Hero fail, fall, die trying.'):
            with self.subTest(source=source):
                self.assertTrue(app.looks_english(source))

    def test_foreign_pronouns_articles_and_short_polish_still_fail(self):
        for source in ('Yo quiero comprar una casa.', 'Die Katze ist sehr klein.',
                       'Die Helden fallen und sterben.', 'Tak nudzi sie depresji dziura.',
                       'Yo no tengo nada.', 'Bonjour, je suis ici avec vous.'):
            with self.subTest(source=source):
                self.assertFalse(app.looks_english(source))


class PronounQuantityTests(unittest.TestCase):
    def quantities(self, source):
        return [row for row in crystal_contract._numbers(source) if not row.get('ambiguous')]

    def test_impersonal_causative_one_is_not_an_added_item(self):
        for source in ('It can make one wonder where power comes from.',
                       'It makes one wonder.', 'The scene made one wonder.'):
            self.assertEqual(self.quantities(source), [])

    def test_actual_another_one_and_one_more_predicate_agree(self):
        before = 'The phone rings again, another one bleeding into the silence.'
        after = 'Phone rings again, one more bleeding into the silence.'
        self.assertEqual(self.quantities(before), [])
        self.assertEqual(self.quantities(after), [])

    def test_counted_one_nouns_money_and_digits_remain_binding(self):
        for source in ('Bring one ticket.', 'She bought one painting.',
                       'Give one dollar.', 'Line seven five six three eight.',
                       'Make one wonder machine.', 'Another one hundred plates.'):
            with self.subTest(source=source):
                self.assertTrue(self.quantities(source))


if __name__ == '__main__':
    unittest.main()
