"""Pinned pronunciation evidence helps rhyme without granting meaning."""
import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app
import crystal_rhyme as rhyme


class CrystalRhymeTests(unittest.TestCase):
    def evidence(self, bars):
        return rhyme.terminal_rhymes(bars, normalize=app._rap_norm,
                                    excluded=app._RAP_STOP, required_depth=app._rap_depth)

    def test_real_missed_endings_report_exact_pinned_phones(self):
        for left, right, tail in [('there', 'care', ['EH', 'R']),
                                  ('key', 'fee', ['IY']),
                                  ('breakthrough', 'view', ['UW']),
                                  ('view', 'through', ['UW'])]:
            with self.subTest(left=left, right=right):
                self.assertFalse(app._rap_slant(left, right))
                report = self.evidence(['Keep the actual ' + left, 'Carry the actual ' + right])
                self.assertEqual(report['pairs'][0]['words'], [left, right])
                self.assertEqual(report['pairs'][0]['rhyme_phones'], tail)
                self.assertTrue(all(rhyme._PHONE.fullmatch(p) for side in report['pairs'][0]['phones'] for p in side))
                self.assertEqual(report['dictionary']['sha256'], rhyme.DICTIONARY_SHA256)
                self.assertEqual(report['dictionary']['version'], rhyme.DICTIONARY_VERSION)

    def test_identical_tags_suffixes_prose_and_unknowns_cannot_gain_dictionary_evidence(self):
        for bars in [
            ['Cut to the chase, man', 'Got records to spin in the space, man'],
            ['They continue walking', 'They continue cooking'],
            ['The performance is dramatic', 'The instructions are specific'],
            ['The key opens this', 'The fee is due now'],
            ['The sky is blue', 'We pass right by'],
            ['The end is qzvrk', 'The next is mzvrk'],
            ['I checked it and noted the time.'],
        ]:
            with self.subTest(bars=bars):
                self.assertEqual(self.evidence(bars)['pairs'], [])

    def test_numeric_endpoints_and_alphanumeric_tokens_are_not_discarded(self):
        for a, b in [('move 12', 'prove 12'), ('move42', 'prove42'),
                     ('42move', '42prove'), ('move \u00e9', 'prove \u00e9')]:
            self.assertEqual(self.evidence([a, b])['pairs'], [], (a, b))
        self.assertTrue(self.evidence(['We can move!', 'We can prove?'])['pairs'])

    def test_inline_comments_are_not_part_of_pronunciations(self):
        pronunciations = rhyme._pronunciations('fine')
        self.assertIn(('F', 'IH1', 'N', 'AH0'), [row[0] for row in pronunciations])
        for phones, _tail, _nuclei in pronunciations:
            self.assertTrue(all(rhyme._PHONE.fullmatch(phone) for phone in phones))
            self.assertNotIn('#', phones)

    def test_corrupt_or_missing_dictionary_fails_closed_and_does_not_retry_reads(self):
        for exists in (False, True):
            with self.subTest(exists=exists), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                path = Path(directory) / 'cmudict.dict'
                if exists:
                    path.write_bytes(b'there DH EH1 R\ncare K EH1 R\n')
                proxy = mock.Mock(wraps=path)
                stack.enter_context(mock.patch.object(rhyme, '_PATH', proxy))
                stack.enter_context(mock.patch.object(rhyme, '_LINES', None))
                stack.enter_context(mock.patch.object(rhyme, '_ERROR', ''))
                rhyme._pronunciations.cache_clear()
                try:
                    for _ in range(2):
                        report = self.evidence(['Stay there', 'Take care'])
                        self.assertFalse(report['dictionary']['available'])
                        self.assertEqual(report['pairs'], [])
                    self.assertEqual(proxy.open.call_count, 1)
                    # A missing dictionary cannot disable existing slant proof.
                    self.assertTrue(app.rap_rhyme_evidence('Here is the trick / It lands slick')['ok'])
                finally:
                    rhyme._pronunciations.cache_clear()

    def test_one_verified_load_across_threads_and_bounded_lookup_cache(self):
        proxy = mock.Mock(wraps=rhyme._PATH)
        with mock.patch.object(rhyme, '_PATH', proxy), mock.patch.object(rhyme, '_LINES', None):
            rhyme._pronunciations.cache_clear()
            with ThreadPoolExecutor(max_workers=8) as pool:
                reports = list(pool.map(lambda _n: self.evidence(['Stay there', 'Take care']), range(16)))
            self.assertTrue(all(report['pairs'] for report in reports))
            self.assertEqual(proxy.open.call_count, 1)
            self.assertEqual(rhyme._pronunciations.cache_info().maxsize, 2048)
        rhyme._pronunciations.cache_clear()
        self.assertEqual(hashlib.sha256(rhyme._PATH.read_bytes()).hexdigest(), rhyme.DICTIONARY_SHA256)

    def test_repeated_endings_do_not_spend_the_distinct_evidence_budget(self):
        report = self.evidence(['There is a key', 'There is a fee', 'There is a key'] * 200)
        self.assertEqual(len(report['pairs']), 1)
        report = self.evidence(['Keep the ' + word for word in ['key', 'fee', 'bee', 'tree']])
        self.assertEqual(len(report['pairs']), 4)
        self.assertEqual(len({tuple(row['bars']) for row in report['pairs']}), 4)
        self.assertTrue(all(row['words'][0] != row['words'][1] for row in report['pairs']))

    def test_one_repeated_dictionary_pair_cannot_meet_the_long_line_two_pair_floor(self):
        long = 'copper ' * 18
        repeated = app.rap_rhyme_evidence(long + 'key / ' + long + 'fee / ' + long + 'key')
        self.assertFalse(repeated['ok'], repeated)
        self.assertEqual(repeated['end'], [('key', 'fee')])
        distinct = app.rap_rhyme_evidence(long + 'key / ' + long + 'fee / Stay there / Take care')
        self.assertTrue(distinct['ok'], distinct)
        self.assertEqual(distinct['end'], [('key', 'fee'), ('there', 'care')])

    def test_full_grade_still_rejects_changed_quantity_name_and_polarity(self):
        token = app._REJECTION_LAB_PREVIEW.set(True)
        try:
            with mock.patch.object(app, '_crystal_vocab', return_value=frozenset()), \
                    mock.patch.object(app, 'crystal_acceptance_mode', return_value='strict'):
                for before, after in [
                    ('Mara returned twelve copper plates before midnight.',
                     'Mara returned thirteen copper plates there / Those plates returned before midnight with care.'),
                    ('Mara cannot return twelve copper plates before midnight.',
                     'Mara can return twelve copper plates there / Before midnight she will return them with care.'),
                    ('Mara returned twelve copper plates before midnight.',
                     'David returned twelve copper plates there / Before midnight he returned them with care.'),
                ]:
                    with self.subTest(before=before, after=after):
                        report = app.tint_evaluate(before, after, [], force=.88, strict=False)
                        self.assertTrue(report['rhyme']['rap']['ok'])
                        self.assertTrue(report['rhyme']['rap']['pronunciation']['pairs'])
                        self.assertFalse(report['semantic']['ok'])
                        self.assertFalse(report['machine_ok'])
                        self.assertFalse(report['ok'])
        finally:
            app._REJECTION_LAB_PREVIEW.reset(token)

    def test_meaning_preserving_key_fee_can_pass_without_lowering_any_other_gate(self):
        token = app._REJECTION_LAB_PREVIEW.set(True)
        try:
            with mock.patch.object(app, '_crystal_vocab', return_value=frozenset()), \
                    mock.patch.object(app, 'crystal_acceptance_mode', return_value='strict'):
                source = 'You hold the key, which opens the door for no fee.'
                candidate = 'That key is yours, the lock yields to your key / The door swings open without a fee.'
                report = app.tint_evaluate(source, candidate, [], force=.88, strict=False)
                self.assertTrue(report['machine_ok'], report['machine_faults'])
                self.assertTrue(report['ok'])
                self.assertEqual(report['rhyme']['rap']['end'], [('key', 'fee')])
                # Word-for-word repetition still cannot claim a transformation.
                copied = app.tint_evaluate(candidate, candidate, [], force=.88, strict=False)
                self.assertTrue(copied['rhyme']['rap']['ok'])
                self.assertFalse(copied['machine_ok'])
        finally:
            app._REJECTION_LAB_PREVIEW.reset(token)

    def test_retained_5325_cannot_supply_the_missing_positive_explanation_after_rhyme_recovery(self):
        token = app._REJECTION_LAB_PREVIEW.set(True)
        try:
            with mock.patch.object(app, '_crystal_vocab', return_value=frozenset()), \
                    mock.patch.object(app, 'crystal_acceptance_mode', return_value='fluid'):
                report = app.tint_evaluate('It is not our abilities that show what we truly are.',
                    'Not abilities that show the true state, but how we act, keep it straight',
                    [], force=.88, strict=False)
                self.assertTrue(report['rhyme']['rap']['ok'])
                self.assertFalse(report['semantic']['contrast'])
                self.assertEqual(report['semantic']['unsupported_positive_contrasts'][0]['unsupported_terms'], ['act'])
                self.assertFalse(report['semantic']['ok'])
                self.assertFalse(report['machine_ok'])
                self.assertFalse(report['ok'])
        finally:
            app._REJECTION_LAB_PREVIEW.reset(token)


if __name__ == '__main__':
    unittest.main()
