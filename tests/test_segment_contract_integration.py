"""The contextual ad supplement reaches actual draft and retained brief checks."""
import unittest
from unittest import mock

import app
import test_segment_contract as fixtures


class SegmentContractIntegrationTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(app, "line_review_permits", return_value=False)
        patch.start()
        self.addCleanup(patch.stop)

    def test_actual_sale_passes_only_with_expected_product_context(self):
        source = fixtures.SegmentContractTests.AD
        self.assertFalse(app.segment_audit("ad", source)["ok"])
        self.assertFalse(app.segment_audit("ad", source, product="F5, another voice server")["ok"])
        report = app.segment_audit("ad", source, product=fixtures.SegmentContractTests.PRODUCT)
        self.assertTrue(report["checked"])
        self.assertTrue(report["ok"])
        self.assertTrue(report["sale_evidence"]["ok"])
        self.assertIn("sign up", report["found"])

    def test_retained_brief_note_uses_product_without_generating_rejection(self):
        with (mock.patch.object(app, "_BRIEF_LOG", []),
              mock.patch.object(app, "line_review_capture") as capture):
            report = app.brief_note("ad", "XTTS fixture", fixtures.SegmentContractTests.AD,
                                    product=fixtures.SegmentContractTests.PRODUCT)
        self.assertTrue(report["ok"])
        capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
