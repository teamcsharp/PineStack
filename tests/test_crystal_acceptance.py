"""Fluid permission preserves actual rhyme and measured content boundaries."""
import copy
import json
from pathlib import Path
import unittest

from crystal_acceptance import evaluate_acceptance


class CrystalAcceptanceTests(unittest.TestCase):
    def report(self, faults=None):
        faults = ['rhetoric was not materially transformed'] if faults is None else faults
        return {'ok': not faults, 'machine_ok': not faults, 'machine_faults': list(faults),
                'faults': list(faults), 'semantic': {'ok': True, 'entities': True,
                'question': True, 'negation': True}, 'copying': {'ok': True, 'phrases': []},
                'rhyme': {'ok': True, 'rap': {'ok': True}},
                'transformation': {'ok': not faults, 'lexical_distance': .1}}

    def decide(self, report, **kwargs):
        return evaluate_acceptance(report, source='We live and clear, spit it, dear.',
                                   candidate='We live and clear, spit it, dear.', **kwargs)

    def test_default_keeps_existing_rejection_and_fluid_explains_style_permission(self):
        grade = self.report()
        original = copy.deepcopy(grade)
        self.assertFalse(self.decide(grade)['ok'])
        result = self.decide(grade, mode='fluid')
        self.assertTrue(result['ok'])
        self.assertTrue(result['accepted_with_advisories'])
        self.assertFalse(result['machine_ok'])
        self.assertEqual(result['machine_faults'], grade['faults'])
        self.assertEqual(result['advisory_faults'], grade['faults'])
        self.assertEqual(result['blocking_faults'], [])
        self.assertEqual(grade, original)

    def test_raw_fault_order_and_multiplicity_remain_evidence(self):
        raw = ['rhetoric was not materially transformed',
               'no new lexicon word drawn from the crystal passage',
               'rhetoric was not materially transformed']
        grade = self.report(raw)
        result = self.decide(grade, mode='fluid')
        self.assertTrue(result['ok'])
        self.assertEqual(result['machine_faults'], raw)
        self.assertEqual(grade['machine_faults'], raw)

    def test_only_named_transformation_and_lexicon_faults_are_waived(self):
        grade = self.report(['rhetoric was not materially transformed',
                             'no new lexicon word drawn from the crystal passage'])
        self.assertTrue(self.decide(grade, mode='fluid')['ok'])
        for other in ('no rhyme evidence - the bar does not land a rhyme',
                      'semantic preservation failed', 'copied a prohibited six-word source phrase',
                      'an unrecognized future fault'):
            with self.subTest(fault=other):
                made = copy.deepcopy(grade)
                made['machine_faults'].append(other)
                decision = self.decide(made, mode='fluid')
                self.assertFalse(decision['ok'])
                self.assertIn(other, decision['blocking_faults'])

    def test_spelling_pairs_or_punctuation_cannot_replace_positive_rap_evidence(self):
        for rap in ({'ok': False}, {}, None):
            grade = self.report()
            grade['rhyme'] = {'ok': True, 'end_pairs': [['move', 'love']], 'rap': rap}
            self.assertFalse(self.decide(grade, mode='fluid')['ok'])
        grade = self.report()
        grade['strength'] = .2
        grade['rhyme']['rap']['ok'] = False
        self.assertFalse(self.decide(grade, mode='fluid')['ok'])

    def test_already_rhyming_original_can_pass_but_unchanged_plain_source_cannot(self):
        self.assertTrue(self.decide(self.report(), mode='fluid')['ok'])
        plain = self.report()
        plain['rhyme']['rap']['ok'] = False
        decision = evaluate_acceptance(plain, source='Keep the copper plate.',
                                       candidate='Keep the copper plate.', mode='fluid')
        self.assertFalse(decision['ok'])

    def test_missing_names_numbers_polarity_and_questions_remain_blocking(self):
        for key in ('ok', 'entities', 'question', 'negation'):
            with self.subTest(key=key):
                grade = self.report()
                grade['semantic'][key] = False
                decision = self.decide(grade, mode='fluid')
                self.assertFalse(decision['ok'])
                self.assertIn('semantic checks did not pass', decision['blocking_faults'])
        grade = self.report()
        del grade['semantic']
        self.assertFalse(self.decide(grade, mode='fluid')['ok'])

    def test_caller_structure_cannot_be_waived_by_a_stylistic_only_fault_list(self):
        for location in ('top', 'semantic'):
            grade = self.report()
            owner = grade if location == 'top' else grade['semantic']
            owner['call_contract'] = {'ok': False, 'faults': ['caller lost its self-introduction']}
            self.assertFalse(self.decide(grade, mode='fluid')['ok'])

    def test_copied_phrase_or_missing_copy_evidence_is_never_waived(self):
        for copying in ({'ok': False, 'phrases': []},
                        {'ok': True, 'phrases': ['a prohibited phrase from the passage']}, {}):
            grade = self.report()
            grade['copying'] = copying
            self.assertFalse(self.decide(grade, mode='fluid')['ok'])

    def test_technical_empty_or_meta_output_remains_ineligible_in_both_modes(self):
        grade = self.report([])
        for mode in ('strict', 'fluid'):
            for kwargs in ({'technical': True}, {'usable': False}):
                self.assertFalse(self.decide(grade, mode=mode, **kwargs)['ok'])
            self.assertFalse(evaluate_acceptance(grade, source='Original words',
                                                candidate=' / ... ', mode=mode)['ok'])
            self.assertFalse(evaluate_acceptance(grade, source='', candidate='Recorded words',
                                                mode=mode)['ok'])

    def test_existing_pass_is_not_mislabeled_as_a_relaxed_rejection(self):
        for mode in ('strict', 'fluid'):
            result = self.decide(self.report([]), mode=mode)
            self.assertTrue(result['ok'])
            self.assertTrue(result['machine_ok'])
            self.assertFalse(result['accepted_with_advisories'])

    def test_unclassified_rejection_and_invalid_mode_do_not_silently_pass(self):
        grade = self.report([])
        grade['machine_ok'] = False
        self.assertFalse(self.decide(grade, mode='fluid')['ok'])
        with self.assertRaises(ValueError):
            self.decide(grade, mode='anything')

    def test_actual_gallery_low_distance_is_newly_eligible_without_claiming_semantic_proof(self):
        path = Path(__file__).resolve().parents[1] / 'docs' / 'crystal-rewrite-second-pass.json'
        case = json.loads(path.read_text(encoding='utf-8'))['cases'][3]
        grade = case['trial']['evaluation']['tint']
        self.assertEqual(grade['machine_faults'], ['rhetoric was not materially transformed'])
        self.assertTrue(grade['rhyme']['rap']['ok'])
        decision = evaluate_acceptance(grade, source=case['before']['source'],
                                       candidate=case['trial']['candidate'], mode='fluid')
        self.assertTrue(decision['accepted_with_advisories'])
        self.assertFalse(decision['machine_ok'])
        self.assertIn('do not certify', decision['limitations'])


if __name__ == '__main__':
    unittest.main()
