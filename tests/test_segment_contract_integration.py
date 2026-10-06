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
        # This fixture tests the machine audit, independent of the operator's
        # persisted decision to bypass that gate on the live station.
        enabled = app.content_gate_enabled
        gate = mock.patch.object(app, "content_gate_enabled", side_effect=lambda name:
                                 True if name == "segment_brief" else enabled(name))
        gate.start()
        self.addCleanup(gate.stop)

    def test_actual_sale_passes_only_with_expected_product_context(self):
        source = fixtures.SegmentContractTests.AD
        self.assertFalse(app.segment_audit("ad", source)["ok"])
        self.assertFalse(app.segment_audit("ad", source, product="F5, another voice server")["ok"])
        report = app.segment_audit("ad", source, product=fixtures.SegmentContractTests.PRODUCT)
        self.assertTrue(report["checked"])
        self.assertTrue(report["ok"])
        self.assertTrue(report["sale_evidence"]["ok"])
        self.assertIn("sign up", report["found"])

    def test_disabled_operator_gate_preserves_its_existing_policy_bypass(self):
        with mock.patch.object(app, "content_gate_enabled", return_value=False):
            report = app.segment_audit("ad", fixtures.SegmentContractTests.AD, capture=False)
        self.assertTrue(report["checked"])
        self.assertFalse(report["machine_ok"])
        self.assertTrue(report["policy_bypassed"])
        self.assertTrue(report["ok"])

    def test_retained_brief_note_uses_product_without_generating_rejection(self):
        with (mock.patch.object(app, "_BRIEF_LOG", []),
              mock.patch.object(app, "line_review_capture") as capture):
            report = app.brief_note("ad", "XTTS fixture", fixtures.SegmentContractTests.AD,
                                    product=fixtures.SegmentContractTests.PRODUCT)
        self.assertTrue(report["ok"])
        capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
