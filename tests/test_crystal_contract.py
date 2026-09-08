"""Normalized surface changes pass; changed source facts remain inspectable failures."""
import json
from pathlib import Path
import unittest

from crystal_contract import compare_contract, content_words, contract_prompt, extract_contract


class CrystalContractTests(unittest.TestCase):
    def assert_equivalent(self, source, candidate, **kwargs):
        result = compare_contract(source, candidate, **kwargs)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['missing_names'], [])
        self.assertEqual(result['missing_numbers'], [])
        self.assertEqual(result['added_numbers'], [])
        return result

    def test_case_curly_apostrophes_and_possessives_share_content_and_name_roots(self):
        self.assert_equivalent("Wakanda's people honor Mara’s promise.", "wakanda’s people honor mara's promise.")
        report = self.assert_equivalent('Wakanda keeps its beauty.', "Wakanda’s beauty is what it keeps.")
        self.assertNotIn('wakanda', report['missing'])
        self.assertEqual(report['anchor_recall'], 1)

    def test_internal_apostrophe_in_a_real_name_is_retained_not_removed(self):
        self.assert_equivalent("O’Neill's copper plate remains.", "o'neill’s copper plate remains.")
        rejected = compare_contract("O'Neill has the plate.", "Neill has the plate.")
        self.assertFalse(rejected['entities'])
        self.assertEqual(rejected['missing_names'][0]['normalized'], "o'neill")

    def test_contractions_and_expansion_keep_the_same_content_and_polarity(self):
        for source, candidate in [("I'm keeping the copper plate.", 'I am keeping the copper plate.'),
                                  ('We can’t lose the frame.', 'We cannot lose the frame.'),
                                  ("They won't lose the frame.", 'They will not lose the frame.'),
                                  ("She doesn't keep the frame.", 'She does not keep the frame.')]:
            with self.subTest(source=source):
                self.assert_equivalent(source, candidate)
                self.assertEqual(content_words(source), content_words(candidate))

    def test_missing_or_added_negation_is_not_hidden_by_apostrophe_style(self):
        for source, candidate in [('We can’t lose the frame.', 'We can lose the frame.'),
                                  ('We keep the frame.', 'We do not keep the frame.'),
                                  ('We keep the frame without its glass.', 'We keep the frame with its glass.')]:
            with self.subTest(source=source):
                result = compare_contract(source, candidate)
                self.assertFalse(result['negation'])
                self.assertFalse(result['ok'])

    def test_redundant_negation_and_imperative_contractions_do_not_create_new_count_gate(self):
        result = self.assert_equivalent("No, I won't drop the copper plate.", 'I will not drop the copper plate.')
        self.assertTrue(result['negation_terms_changed'])
        self.assert_equivalent("Don't drop the copper plate!", 'Do not drop the copper plate.')
        idiom = compare_contract('No doubt, Mara keeps the copper plate.', 'Mara certainly keeps the copper plate.')
        self.assertTrue(idiom['negation'])
        self.assertTrue(idiom['ok'], idiom)

    def test_pronominal_one_is_advisory_but_explicit_item_counts_still_bind(self):
        for source, candidate in [('Mara keeps the one I remember.', 'Mara keeps what I remember.'),
                                  ('One can keep the copper plate.', 'We can keep the copper plate.'),
                                  ('Mara and I help one another.', 'Mara and I help each other.')]:
            with self.subTest(source=source):
                result = self.assert_equivalent(source, candidate)
                self.assertTrue(result['ambiguous_numbers']['source'])
        self.assertFalse(compare_contract('Mara needs one copper plate.', 'Mara needs two copper plates.')['entities'])
        self.assertFalse(compare_contract('Mara needs 1 copper plate.', 'Mara needs a copper plate.')['entities'])

    def test_retained_corpus_pronominal_one_variants_do_not_claim_missing_quantities(self):
        pairs = [('The third one has orange hair.', 'The third has orange hair.'),
                 ('The second one has a quiet gaze.', "The second one's gaze is quiet."),
                 ('Which one is up first?', 'Which piece is up first?'),
                 ('This one right next to it has orange hair.', 'The piece right next to it has orange hair.'),
                 ('It is a second subject instead of one more symptom.', 'It is a second subject instead of another symptom.'),
                 ('The value is quantified by no one.', 'The value is quantified by nobody.')]
        for source, candidate in pairs:
            with self.subTest(source=source):
                result = compare_contract(source, candidate)
                self.assertEqual(result['missing_numbers'], [], result)
                self.assertEqual(result['added_numbers'], [], result)
                self.assertTrue(result['ambiguous_numbers']['source'])
        self.assertFalse(compare_contract('Mara needs one orange frame.', 'Mara needs three orange frames.')['entities'])

    def test_one_thing_and_only_thing_keep_uniqueness_without_excusing_item_counts(self):
        source = ('The one thing that keeps me warm is the thought that I will look down upon the city. '
                  'The city.')
        candidate = ("The only thing to keep me warm is the thought I'll be vacancy taking, looking down "
                     'on the city while the masses are shaking and breaking.')
        self.assert_equivalent(source, candidate)
        self.assert_equivalent('The only thing I keep is the copper plate.',
                               'The one thing I keep is the copper plate.')
        for original, made in [('Mara needs one copper plate.', 'Mara needs only copper plates.'),
                               ('Mara needs one copper plate.', 'Mara needs two copper plates.'),
                               ('The one thing I keep is the plate.', 'The thing I keep is the plate.'),
                               ('The one thing I keep is the plate.', 'The two things I keep are plates.')]:
            with self.subTest(original=original, made=made):
                self.assertFalse(compare_contract(original, made)['entities'])

    def test_reflexive_do_imperative_is_not_an_inferred_question(self):
        self.assertFalse(extract_contract('Do it yourself!')['question'])
        self.assertFalse(extract_contract('Do this yourselves!')['question'])
        self.assertTrue(extract_contract('Do it yourself?')['question'])
        self.assertTrue(extract_contract('Do you keep the copper plate')['question'])
        self.assertTrue(extract_contract('Did it keep the copper plate')['question'])
        source = ("You wouldn't sully your hands, but you'll damn us to a black hole for "
                  'eternity, because no matter how much you try you cannot make it happen.')
        candidate = ('You yank the plug / tug the rug / you die in a shrug / do it yourself! / '
                     "Your palms too pristine for the grime but you'll consign us to a black hole / "
                     "no matter how you try, the trick won't fly.")
        self.assert_equivalent(source, candidate, anchor_floor=.2)
        self.assertFalse(compare_contract(source, candidate, anchor_floor=.5)['ok'])

    def test_ungrammatical_source_auxiliary_does_not_invent_a_question(self):
        source = "Is we're getting closer to you confronting your true feelings about what's really going on here."
        result = compare_contract(source, 'We are getting closer to your true feelings about what is really going on here.')
        self.assertTrue(result['question'], result)
        self.assertFalse(extract_contract(source)['question'])
        self.assertTrue(extract_contract('Are we getting closer to your true feelings')['question'])
        self.assertFalse(compare_contract('Are we getting closer to your true feelings?',
                                         'We are getting closer to your true feelings.')['question'])

    def test_contracted_question_tag_keeps_its_job_despite_transcribed_period(self):
        self.assert_equivalent("The story keeps you hooked, doesn't it.",
                               "The story keeps you hooked, doesn't it?")
        self.assert_equivalent('Mara keeps the plate, doesn\u2019t she.',
                               "Mara keeps the plate, doesn't she?")
        self.assertTrue(extract_contract("Mara can keep the plate, can't she")['question'])
        self.assertFalse(compare_contract("Mara keeps the plate, doesn't she.",
                                         'Mara keeps the plate.')['question'])
        for imperative in ["Keep the plate, don't drop it.", "Do it yourself, don't delay.",
                           "Don't you drop the plate.", 'Do it yourself!']:
            with self.subTest(imperative=imperative):
                self.assertFalse(extract_contract(imperative)['question'])

    def test_question_without_final_punctuation_still_requires_question_word_order(self):
        self.assert_equivalent('Can you keep the copper plate?', 'Can you keep the copper plate')
        self.assertFalse(compare_contract('Can you keep the copper plate?', 'You can keep the copper plate.')['question'])
        self.assertFalse(compare_contract('You keep the copper plate.', 'Can you keep the copper plate?')['question'])

    def test_unknown_sentence_opener_and_changed_proper_name_are_not_waved_away(self):
        for source, candidate, missing in [('Mara holds the copper plate.', 'Nora holds the copper plate.', 'mara'),
                                            ('Ious. The king holds the plate.', 'The king holds the plate.', 'ious')]:
            result = compare_contract(source, candidate)
            self.assertFalse(result['entities'])
            self.assertIn(missing, [name['normalized'] for name in result['missing_names']])
            self.assertIn('heuristic', result['limitations'])

    def test_known_ordinary_quoted_opener_is_not_an_inferred_name(self):
        result = self.assert_equivalent('"Relax," Mara said.', 'Mara said to relax.', vocabulary={'relax'})
        self.assertEqual([name['normalized'] for name in result['name_candidates']], ['mara'])

    def test_dropped_g_rap_spelling_preserves_existing_name_accommodation(self):
        result = compare_contract('Bleeding keeps the copper plate.', "Bleedin' keeps the copper plate.")
        self.assertTrue(result['entities'], result)
        self.assertTrue(result['ok'], result)

    def test_exact_integer_and_spelled_out_values_match_without_number_word_count_shortcut(self):
        for digits, words in [('12', 'twelve'), ('24', 'twenty-four'), ('100', 'one hundred'),
                              ('1,200', 'one thousand two hundred'), ('1205', 'one thousand two hundred and five'),
                              ('2300000', 'two million three hundred thousand')]:
            with self.subTest(digits=digits):
                self.assert_equivalent(f'Mara needs {digits} copper plates.', f'Mara needs {words} copper plates.')
        for wrong in ('twenty four', 'one two', 'ninety thousand', 'eleven'):
            result = compare_contract('Mara needs 12 copper plates.', f'Mara needs {wrong} copper plates.')
            self.assertFalse(result['entities'], result)
            self.assertEqual(result['missing_numbers'], [{'kind': 'number', 'value': '12', 'count': 1}])

    def test_source_number_words_are_obligations_too(self):
        result = compare_contract('Mara needs twelve copper plates.', 'Mara needs thirteen copper plates.')
        self.assertFalse(result['ok'])
        self.assertEqual(result['source_numbers'][0]['value'], '12')
        self.assertEqual(result['added_numbers'][0]['value'], '13')

    def test_decimal_sign_and_currency_are_retained_exactly(self):
        self.assert_equivalent('Mara needs $12.50 for the frame.', 'Mara needs twelve point five zero dollars for the frame.')
        self.assert_equivalent('Mara measured -3 on the gauge.', 'Mara measured minus three on the gauge.')
        for candidate in ['Mara needs $12.05 for the frame.', 'Mara needs €12.50 for the frame.',
                          'Mara needs 12.50 for the frame.']:
            self.assertFalse(compare_contract('Mara needs $12.50 for the frame.', candidate)['entities'])
        self.assertFalse(compare_contract('Mara measured -3 on the gauge.', 'Mara measured three on the gauge.')['entities'])

    def test_percentage_and_repeated_quantities_cannot_disappear(self):
        self.assert_equivalent('Mara saved 12% on the frame.', 'Mara saved twelve percent on the frame.')
        self.assertFalse(compare_contract('Mara saved 12% on the frame.', 'Mara saved twelve on the frame.')['entities'])
        result = compare_contract('Mara needs 2 plates and 2 frames.', 'Mara needs two plates and frames.')
        self.assertEqual(result['missing_numbers'], [{'kind': 'number', 'value': '2', 'count': 1}])
        self.assertFalse(result['ok'])

    def test_clock_spelling_requires_actual_hour_and_minute_not_arbitrary_number_words(self):
        self.assert_equivalent('Mara arrives at 9:59.', 'Mara arrives at nine fifty-nine.')
        self.assert_equivalent('Mara arrives at 9:59.', 'Mara arrives at nine-fifty-nine.')
        self.assert_equivalent('Mara arrives at 12:00.', 'Mara arrives at noon.')
        self.assert_equivalent('Mara arrives at 21:59.', 'Mara arrives at nine fifty-nine pm.')
        self.assertFalse(compare_contract('Mara arrives at 9:59 am.', 'Mara arrives at nine fifty-nine pm.')['entities'])
        for candidate in ['Mara arrives at nine fifty-eight.', 'Mara arrives at twelve forty-two.', 'Mara arrives at nine plates and fifty-nine frames.']:
            self.assertFalse(compare_contract('Mara arrives at 9:59.', candidate)['entities'])

    def test_number_words_separated_by_punctuation_are_not_merged_into_a_different_value(self):
        contract = extract_contract('Mara needs twenty, four copper plates.')
        self.assertEqual([row['value'] for row in contract['numbers']], ['20', '4'])
        self.assertFalse(compare_contract('Mara needs 24 copper plates.', contract['source'])['entities'])

    def test_normalization_does_not_stem_unrelated_words_or_substitute_semantic_guesses(self):
        source = 'Mara keeps a cruel action beside the frame.'
        result = compare_contract(source, 'Mara keeps a kind actor beside the frame.')
        self.assertIn('action', result['missing'])
        self.assertIn('cruel', result['missing'])
        self.assertNotIn('actor', result['anchors'])
        self.assertIn('proposition', result['limitations'])

    def test_negative_only_focus_cannot_gain_an_unprovided_positive_answer(self):
        source = 'It is not our abilities that show what we truly are.'
        for candidate in [
            'Not abilities that show the true state, but how we act, keep it straight',
            "It isn't our abilities that show what we truly are; it's our choices that show our true character.",
            'It is not our abilities that show what we truly are, but our actions.',
        ]:
            with self.subTest(candidate=candidate):
                report = compare_contract(source, candidate, anchor_floor=.2)
                self.assertFalse(report['ok'])
                self.assertFalse(report['contrast'])
                self.assertTrue(report['unsupported_positive_contrasts'])
                self.assertEqual(report['contract_version'], 3)
        exact = compare_contract(source, 'Not abilities that show the true state, but how we act, keep it straight')
        self.assertEqual(exact['unsupported_positive_contrasts'][0]['unsupported_terms'], ['act'])

    def test_contrast_rule_generalizes_reveal_focus_without_claiming_all_propositions(self):
        source = "It isn't the paint that reveals the chair's age."
        candidate = "Not the paint that reveals the chair's age, but how the wood bends, the final stage."
        report = compare_contract(source, candidate, anchor_floor=.2)
        self.assertFalse(report['contrast'])
        self.assertEqual(report['unsupported_positive_contrasts'][0]['unsupported_terms'], ['bends', 'wood'])

    def test_source_established_contrast_and_same_negative_rephrasing_remain_eligible(self):
        for source, candidate in [
            ('It is not our abilities that show what we truly are, but how we act.',
             "It isn't our abilities that show what we truly are; it's how we act that shows what we truly are."),
            ('It is not our abilities that show what we truly are; it is our choices that show what we truly are.',
             'Not our abilities that show what we truly are, but our choices.'),
            ('It is not our abilities that show what we truly are, but our choices in hard times.',
             'It is not our abilities that show what we truly are; it is our own choices in hard times that show what we truly are.'),
            ('It is not our abilities that show what we truly are, but our choices in hard times.',
             'It is not our abilities that show what we truly are; it is our decisions in hard times that show what we truly are.'),
            ('It is not our abilities that show what we truly are.',
             "Our abilities do not show what we truly are."),
        ]:
            with self.subTest(source=source, candidate=candidate):
                report = compare_contract(source, candidate, anchor_floor=.2)
                self.assertTrue(report['contrast'])
                self.assertTrue(report['ok'], report)

    def test_question_not_only_and_unrelated_but_clauses_are_outside_narrow_guard(self):
        for source, candidate in [
            ('Is it not our abilities that show what we truly are?',
             'Is it not our abilities that show what we truly are, but how we act?'),
            ('It is not only our abilities that show what we truly are.',
             'It is not only our abilities that show what we truly are, but how we act.'),
            ('It is not just our abilities that show what we truly are.',
             'It is not just our abilities that show what we truly are, but our choices.'),
            ('The kettle is not boiling, but the oven is hot.',
             'The kettle is not boiling, but the oven stays hot.'),
            ('It is not our abilities that show what we truly are, but we are late.',
             'Our abilities do not show what we truly are, but we are late.'),
            ('It is our abilities that show what we truly are.',
             'It is our abilities that show what we truly are, but how we act matters too.'),
        ]:
            with self.subTest(source=source, candidate=candidate):
                self.assertTrue(compare_contract(source, candidate, anchor_floor=.2)['contrast'])

    def test_prompt_uses_the_exact_contract_obligations_and_does_not_lower_any_ratio(self):
        contract = extract_contract('Can Mara keep 12 copper plates without the frame?')
        prompt = contract_prompt(contract)
        facts = json.loads(prompt.split('\n', 1)[1])
        self.assertEqual(facts['content_anchors'], contract['anchors'])
        self.assertEqual(facts['names_to_retain'], [{'text': 'Mara', 'match': 'mara'}])
        self.assertEqual(facts['quantities_to_retain'][0]['value'], '12')
        self.assertTrue(facts['is_question'])
        self.assertEqual(facts['negation_to_retain'], ['without'])
        self.assertNotIn('half', prompt)
        self.assertNotIn('fifth', prompt)
        self.assertIn('A negative-only statement gives no positive answer', prompt)

    def test_live_trial_possessive_false_miss_is_removed_but_actual_omissions_remain(self):
        fixture = Path(__file__).resolve().parents[1] / 'docs' / 'rejection-workbench-model-check.json'
        data = json.loads(fixture.read_text(encoding='utf-8'))
        trial = next(operation['trial'] for operation in data['operations'] if operation.get('trial'))
        result = compare_contract(trial['baseline']['source'], trial['candidate'], anchor_floor=.2)
        self.assertNotIn('wakanda', result['missing'])
        self.assertNotIn('wakanda', [row['normalized'] for row in result['missing_names']])
        self.assertIn('oppressors', result['missing'])
        self.assertIn('action', result['missing'])
        self.assertIn('ious', [row['normalized'] for row in result['missing_names']])
        self.assertFalse(result['ok'], 'A normalized possessive cannot excuse the actual missing original name.')


if __name__ == '__main__':
    unittest.main()
