"""Bounded fluid guards for exact failures found in the 47-event replay."""
import copy
import unittest

from crystal_acceptance import evaluate_acceptance


class FluidEvidenceGuardTests(unittest.TestCase):
    def grade(self, style=False):
        faults = ['rhetoric was not materially transformed'] if style else []
        return {'ok': not faults, 'machine_ok': not faults, 'machine_faults': faults,
                'semantic': {'ok': True, 'entities': True, 'question': True, 'negation': True},
                'copying': {'ok': True, 'phrases': []}, 'rhyme': {'rap': {'ok': True}}}

    def decide(self, source, candidate, *, style=False, mode='fluid'):
        return evaluate_acceptance(self.grade(style), source=source, candidate=candidate, mode=mode)

    def test_actual_dropped_try_is_blocked_even_when_raw_grade_passed(self):
        source = 'Yeah, the way they try to put a price on whatever they touch just makes it worse.'
        candidate = 'Yeah, they put a price on whatever they touch, Just makes it worse, an excessive clutch.'
        result = self.decide(source, candidate)
        self.assertFalse(result['ok'])
        self.assertTrue(result['machine_ok'])
        self.assertEqual(result['machine_faults'], [])
        self.assertIn('attempt became an accomplished action', result['blocking_faults'])
        self.assertEqual(result['guard_evidence'][0]['source_quote'], 'try to put')
        self.assertEqual(result['guard_evidence'][0]['candidate_quote'], 'they put')

    def test_progressive_attempt_must_not_turn_into_assertion(self):
        result = self.decide('They are trying to open the gate.', 'They open the gate, arriving late.', style=True)
        self.assertFalse(result['ok'])
        self.assertEqual(result['guard_evidence'][0]['predicate'], 'open')

    def test_preserved_or_explicit_paraphrased_attempt_is_allowed(self):
        for attempt in ('try to', 'are trying to', 'attempt to', 'aim to', 'seek to'):
            with self.subTest(attempt=attempt):
                self.assertTrue(self.decide('They try to put a price on what they touch.',
                    'They ' + attempt + ' put a price on what they touch, a clumsy clutch.', style=True)['ok'])

    def test_modal_uncertainty_is_not_mislabeled_as_accomplishment(self):
        for modal in ('may', 'might', 'could'):
            with self.subTest(modal=modal):
                self.assertTrue(self.decide('They try to open the gate.',
                    'They ' + modal + ' open the gate, arriving late.', style=True)['ok'])

    def test_unrelated_attempt_does_not_launder_the_changed_predicate(self):
        result = self.decide('They try to open the gate.',
                             'They open the gate while they try to paint the slate.')
        self.assertFalse(result['ok'])

    def test_noun_try_and_try_this_are_not_global_required_tokens(self):
        for source, candidate in (
            ('Give it another try to open the gate.', 'They open the gate, arriving late.'),
            ('Try this bright light.', 'Use this light, keep it bright.'),
            ('The try was a delight.', 'The effort was a delight, keeping it bright.'),
        ):
            with self.subTest(source=source):
                self.assertTrue(self.decide(source, candidate, style=True)['ok'])

    def test_actual_dense_orphan_is_source_repair_debt_not_a_style_exception(self):
        source = 'go, "Wait, that actually makes some sense." And what I\'m saying to you, genuinely from the.'
        for join in ('what', 'And what'):
            candidate = 'Go, "Wait, that actually makes some sense", ' + join + " I'm saying genuinely from the... dense"
            result = self.decide(source, candidate, style=True)
            self.assertFalse(result['ok'])
            self.assertIn('source needs repair: dangling determiner and orphaned completion', result['blocking_faults'])
            evidence = result['guard_evidence'][0]
            self.assertEqual(evidence['code'], 'source_needs_repair')
            self.assertEqual(evidence['source_quote'], 'from the.')
            self.assertEqual(evidence['candidate_quote'], 'from the... dense')

    def test_complete_source_or_legitimate_adjective_ending_is_not_rejected(self):
        for source, candidate in (
            ('The fog makes the view dense.', 'The view is dense, a curtain on the fence.'),
            ('We are speaking from the station.', 'We speak from the station, our broadcast location.'),
            ('The selected word is "the".', 'The word is the, spoken to me.'),
        ):
            with self.subTest(source=source):
                self.assertTrue(self.decide(source, candidate, style=True)['ok'])

    def test_strict_permission_and_raw_grade_are_unchanged(self):
        grade = self.grade()
        original = copy.deepcopy(grade)
        result = evaluate_acceptance(grade, source='They try to open the gate.',
                                     candidate='They open the gate.', mode='strict')
        self.assertTrue(result['ok'])
        self.assertEqual(result['guard_evidence'], [])
        self.assertEqual(grade, original)


if __name__ == '__main__':
    unittest.main()
