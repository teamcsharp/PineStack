"""#1075: a clock time is one fact however the bar says it.

Measured on the Gazette: "4:00 AM" spoken as "four AM" was a lost time plus an
invented count; "3:18 AM" as "three eighteen" was a lost time plus two counts.
Every other quantity keeps its exact obligation.
"""
import unittest

from crystal_contract import compare_contract, extract_contract


class ClockEquivalenceTests(unittest.TestCase):
    def assert_equivalent(self, source, candidate):
        result = compare_contract(source, candidate, anchor_floor=0.2)
        self.assertTrue(result['entities'], result)
        self.assertEqual(result['missing_numbers'], [])
        self.assertEqual(result['added_numbers'], [])
        return result

    def test_whole_hour_with_meridiem_matches_its_bare_hour_in_either_direction(self):
        self.assert_equivalent('Later, at 4:00 AM, Junebug called live from the apartment stairwell.',
                               'Later at four AM Junebug called live from the apartment stairwell.')
        self.assert_equivalent('Later, at 4:00 AM, Junebug called live from the apartment stairwell.',
                               'Later at four in the morn Junebug called live from the apartment stairwell.')
        self.assert_equivalent('He rang at 4 AM about the bins.', 'He rang at 4:00 AM about the bins.')
        self.assert_equivalent('The show ends at 9 PM sharp.', 'The show ends at nine, sharp.')

    def test_spoken_teen_and_oh_minutes_are_the_clock(self):
        self.assert_equivalent('The hour opened at 3:18 AM with the record Skyfire.',
                               'The hour opened at three eighteen with the record Skyfire.')
        self.assert_equivalent('The hour opened at 3:18 AM with the record Skyfire.',
                               'The hour opened at three eighteen AM with the record Skyfire.')
        self.assert_equivalent('Sarah Sherman called at 3:04 AM regarding stolen garbage.',
                               'Sarah Sherman called at three oh four AM regarding stolen garbage.')
        self.assertEqual([row['value'] for row in extract_contract('Mara rang at three eighteen.')['numbers']], ['03:18'])
        self.assertEqual([row['value'] for row in extract_contract('Mara rang at seven oh five pm.')['numbers']], ['19:05'])

    def test_a_different_hour_minute_or_a_real_count_still_binds(self):
        self.assertFalse(compare_contract('Mara arrives at 4:00 AM.', 'Mara arrives at 5 AM.')['entities'])
        self.assertFalse(compare_contract('Mara arrives at 3:18 AM.', 'Mara arrives at three nineteen.')['entities'])
        self.assertFalse(compare_contract('Mara arrives at 3:18 AM.', 'Mara arrives at three, eighteen plates.')['entities'])
        self.assertFalse(compare_contract('Mara arrives at 3:49 AM.', 'Mara arrives at 3:49 PM.')['entities'])
        # A lost quantity next to a whole-hour clock is still lost: one pairing per hour.
        report = compare_contract('At 4:00 AM she took 4 plates and 4 cups.', 'At four AM she took four plates.')
        self.assertFalse(report['entities'], report)
        self.assertEqual(report['missing_numbers'], [{'kind': 'time', 'value': '04:00', 'count': 1}])
        self.assertEqual(report['added_numbers'], [])
        # ...and a bar that keeps every quantity passes, whichever "four" is the clock.
        self.assert_equivalent('At 4:00 AM she took 4 plates and 4 cups.', 'At four AM she took four plates and four cups.')
        # Existing behaviour untouched: comma-separated number words stay two values.
        self.assertEqual([row['value'] for row in extract_contract('Mara needs twenty, four copper plates.')['numbers']], ['20', '4'])


if __name__ == '__main__':
    unittest.main()
