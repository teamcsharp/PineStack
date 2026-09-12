import unittest

from segment_contract import ad_sale_evidence


class SegmentContractTests(unittest.TestCase):
    PRODUCT = 'XTTS, one of the live services running on this station’s own DGX Spark — the voice-cloning server is up and answering'
    # Actual sale passage from retained event 2506, formerly missed by the
    # fixed ad keyword list despite explicitly naming the expected product.
    AD = ('Hear the XTTS voice clone / on the DGX Spark throne / luxury service known / '
          'five hundred flat for the loan / pay through the portal zone. '
          'Grab that sonic replication state / sign up before the commercial break date.')

    def test_actual_named_service_sale_is_recognized_with_its_expected_identity(self):
        report = ad_sale_evidence(self.AD, self.PRODUCT)
        self.assertTrue(report['ok'])
        self.assertEqual(report['identity_terms'], ['xtts'])
        self.assertEqual(set(report['sale_actions']), {'pay through', 'sign up'})

    def test_unrelated_product_generic_description_and_missing_identity_stay_unproved(self):
        for product in ('F5, the other voice server', '', 'a voice cloning service'):
            with self.subTest(product=product):
                self.assertFalse(ad_sale_evidence(self.AD, product)['ok'])
        self.assertFalse(ad_sale_evidence('Sign up now and pay through the portal.', self.PRODUCT)['ok'])

    def test_name_without_sale_action_and_negated_sales_do_not_pass(self):
        for text in ('XTTS is the clone engine that runs here.',
                     'XTTS is running. Do not sign up.',
                     "XTTS is running, but don't pay through the portal.",
                     'Avoid subscribing to XTTS; never subscribe.'):
            with self.subTest(text=text):
                self.assertFalse(ad_sale_evidence(text, self.PRODUCT)['ok'])

    def test_multiple_word_named_product_requires_its_complete_identity(self):
        self.assertTrue(ad_sale_evidence('The Copper Finch service is ready. Subscribe today.', 'The Copper Finch, a service')['ok'])
        self.assertFalse(ad_sale_evidence('The Copper service is ready. Subscribe today.', 'The Copper Finch, a service')['ok'])

    def test_input_is_not_rewritten_and_false_input_types_are_rejected(self):
        text = self.AD
        report = ad_sale_evidence(text, self.PRODUCT)
        self.assertEqual(text, self.AD)
        self.assertIn('price accuracy', report['limitations'])
        with self.assertRaises(TypeError):
            ad_sale_evidence(None, self.PRODUCT)


if __name__ == '__main__':
    unittest.main()
