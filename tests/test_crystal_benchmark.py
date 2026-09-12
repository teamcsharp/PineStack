"""Reporting cannot relabel a tolerated style rejection as a machine pass."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / 'tools' / 'crystal-rewrite-benchmark.py'
spec = importlib.util.spec_from_file_location('crystal_benchmark', path)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class CrystalBenchmarkTests(unittest.TestCase):
    def case(self, trial, status='completed'):
        return {'status': status, 'trial': trial, 'before': {'source': 'Full original words.', 'context': {'kind': 'gallery'}}}

    def test_fluid_permission_and_unchanged_raw_verdict_have_separate_counts(self):
        fluid = {'evaluation': {'ok': True, 'faults': [], 'call_contract': {'ok': True},
            'tint': {'machine_ok': False, 'machine_faults': ['rhetoric was not materially transformed'],
                     'editorial': {'accepted_with_advisories': True}}}}
        raw_pass = {'evaluation': {'ok': True, 'tint': {'machine_ok': True, 'machine_faults': []}}}
        raw_fail = {'evaluation': {'ok': False, 'faults': ['meaning'],
                                  'tint': {'machine_ok': False, 'machine_faults': ['meaning']}}}
        result = benchmark.summary({'cases': [self.case(fluid), self.case(raw_pass),
                                              self.case(raw_fail), self.case(None, 'failed')]})
        self.assertEqual(result['completed_trials'], 3)
        self.assertEqual(result['accepted'], 2)
        self.assertEqual(result['accepted_with_advisories'], 1)
        self.assertEqual(result['machine_passed'], 1)
        self.assertEqual(result['machine_failed'], 2)
        self.assertEqual(result['machine_unavailable'], 0)
        self.assertEqual(result['machine_faults']['rhetoric was not materially transformed'], 1)
        self.assertNotIn('rhetoric was not materially transformed', result['faults'])

    def test_missing_raw_proof_is_unknown_and_failed_caller_structure_remains_a_machine_failure(self):
        unknown = {'evaluation': {'ok': True}}
        failed = {'evaluation': {'ok': False, 'tint': {'machine_ok': True},
                                'call_contract': {'ok': False, 'faults': ['lost caller turn']}}}
        result = benchmark.summary({'cases': [self.case(unknown), self.case(failed)]})
        self.assertEqual(result['accepted'], 1)
        self.assertEqual(result['machine_passed'], 0)
        self.assertEqual(result['machine_failed'], 1)
        self.assertEqual(result['machine_unavailable'], 1)

    def test_actual_learning_revision_and_mode_are_preserved_without_inference(self):
        trial = {'baseline': {'grader_version': 6, 'prompt_version': 2,
                              'learning_revision': 12, 'acceptance_mode': 'fluid'},
                 'provenance': {'learning_revision': 11, 'acceptance_mode': 'strict'}}
        self.assertEqual(benchmark.trial_metadata(trial), trial['baseline'])
        self.assertIsNone(benchmark.trial_metadata({})['learning_revision'])


if __name__ == '__main__':
    unittest.main()
