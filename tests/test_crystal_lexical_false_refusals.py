"""Measured refusal mechanisms, with names, real questions and facts retained."""
import unittest
from unittest.mock import patch

import app
from crystal_contract import extract_contract, compare_contract
from crystal_rhyme import terminal_rhymes


class LexicalFalseRefusalTests(unittest.TestCase):
    def test_dictionary_proves_flow_go_but_not_sameword_or_function_word_endings(self):
        result=terminal_rhymes(['Moving with the flow','Time for us to go'],excluded={'to'})
        self.assertEqual(result['pairs'][0]['words'],['flow','go'])
        self.assertEqual(result['pairs'][0]['rhyme_phones'],['OW'])
        self.assertEqual(terminal_rhymes(['Time to go','We can go'])['pairs'],[])
        self.assertEqual(terminal_rhymes(['Move with the flow','The way to'],excluded={'to'})['pairs'],[])
        actual=app.rap_rhyme_evidence('Moving with the flow; Time for us to go')
        self.assertTrue(actual['ok'])
        self.assertTrue(actual['pronunciation']['pairs'])

    def test_actual_new_flow_go_candidate_gains_sound_evidence_not_semantic_certification(self):
        text='Just see people moving through it, same as always in the flow; Finding solace in the groove where thin air lets them go'
        self.assertTrue(app.rap_rhyme_evidence(text)['ok'])

    def test_sentence_initial_gerund_subject_and_life_modifier_are_not_people(self):
        for text in ['Reclaiming ownership is important.', 'Keeping the records is important.',
                     'Teaming with life that knows not what it has lost.',
                     'Teeming with life that knows not what it has lost.']:
            with self.subTest(text=text):
                first=text.split()[0].lower()
                self.assertNotIn(first,[r['normalized'] for r in extract_contract(text)['names']])
        checked=compare_contract('Reclaiming ownership is important.',
                                 'Ownership reclaimed is important.',anchor_floor=0)
        self.assertEqual(checked['missing_names'],[])

    def test_real_names_titles_and_interior_capitals_stay_binding(self):
        for text,name in [('Sterling said the records are ready.','sterling'),
                          ('Reading is a town.','reading'),
                          ('Reclaiming called the station.','reclaiming'),
                          ('I spoke to Reclaiming yesterday.','reclaiming'),
                          ('Reading The City is the title.','reading'),
                          ('TEAMING with life is the project name.','teaming')]:
            with self.subTest(text=text):
                self.assertIn(name,[r['normalized'] for r in extract_contract(text)['names']])

    def test_declarative_you_know_tag_is_optional_but_real_questions_remain(self):
        source="Yeah, that's not just some small thing; there's always something twisted about these things, you know? It smells like a setup."
        result=extract_contract(source)
        self.assertFalse(result['question']);self.assertTrue(result['discourse_question_tags'])
        for text in ['You know?', 'Do you know?', 'You know where the record is?',
                     'Where did they go, you know?', 'Honestly, what are they doing, you know?',
                     '"What are they doing, you know?"',
                     'Can we leave, you know?', 'The records are gone, you know? Where are they?']:
            with self.subTest(text=text):self.assertTrue(extract_contract(text)['question'])

    def test_caller_path_uses_same_question_role_and_still_blocks_lost_substantive_question(self):
        source='There is something twisted about these things, you know? It smells like a setup.'
        candidate='There is something twisted about these things. It smells like a setup.'
        with patch.object(app,'_crystal_vocab',return_value=set()):
            result=app.call_tint_report('A: '+source,'A: '+candidate)
            self.assertTrue(result['ok'],result)
            failed=app.call_tint_report('A: Where are the missing records?',
                                        'A: The missing records are there.')
        self.assertIn('tint turn 1 turned a question into a statement',failed['faults'])

    def test_names_numbers_negation_and_unprovided_contrast_still_fail(self):
        for source,candidate in [
            ('Mara kept twelve records.','Nora kept thirteen records.'),
            ('Dale woulda taken that turn flat out.','Dale woulda taken that turn flat out; No brakes on that route.'),
            ('It is not our abilities that show what we truly are.',
             'It is not our abilities that show what we truly are; it is how we act that shows what we truly are.')]:
            with self.subTest(source=source):self.assertFalse(compare_contract(source,candidate,anchor_floor=0)['ok'])
        retained=compare_contract('Teaming with life that knows not what it has lost.',
            'Teeming with life, a vibrant cost; unaware of what it lost',anchor_floor=0)
        self.assertFalse(retained['negation'])
        self.assertFalse(retained['ok'])


if __name__=='__main__':unittest.main()
