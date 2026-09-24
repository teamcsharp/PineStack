import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


def state(master=False, **enabled):
    gates = {key: False for key in app.CONTENT_GATE_INFO}
    gates.update(enabled)
    return {"revision": 0, "master_enabled": master,
            "gates": gates, "updated_at": 0.0}


class ContentGatePolicyTests(unittest.TestCase):
    def test_missing_policy_starts_with_every_gate_off(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(app, "CONTENT_GATE_PATH", Path(root) / "missing.json"):
            policy = app._content_gate_load()
        self.assertFalse(policy["master_enabled"])
        self.assertTrue(policy["gates"])
        self.assertFalse(any(policy["gates"].values()))

    def test_enabling_requires_operator_approval_and_revision(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(app, "CONTENT_GATE_PATH", Path(root) / "policy.json"), \
                mock.patch.object(app, "_CONTENT_GATE_STATE", state()), \
                mock.patch.object(app._LINE_REVIEW, "policy", return_value={
                    "enabled": False, "disabled_gates": []}) as review:
            with self.assertRaisesRegex(ValueError, "operator approval"):
                app.content_gate_patch({"expected_revision": 0,
                                        "master_enabled": True,
                                        "gates": {"profile": True}})
            self.assertFalse(app.CONTENT_GATE_PATH.exists())
            changed = app.content_gate_patch({"expected_revision": 0,
                                              "master_enabled": True,
                                              "gates": {"profile": True},
                                              "approval": "enable"})
            self.assertEqual(changed["revision"], 1)
            self.assertTrue(changed["effective"]["profile"])
            self.assertFalse(changed["effective"]["tint"])
            self.assertTrue(json.loads(app.CONTENT_GATE_PATH.read_text())[
                "master_enabled"])
            review.assert_any_call({"enabled": True, "disabled_gates": []})
            with self.assertRaises(app.ContentGateConflict):
                app.content_gate_patch({"expected_revision": 0,
                                        "master_enabled": False})
            disabled = app.content_gate_patch({"expected_revision": 1,
                                               "master_enabled": False})
            self.assertFalse(disabled["effective"]["profile"])
            self.assertFalse(any(disabled["gates"].values()))

    def test_master_off_bypasses_editorial_review_but_not_technical(self):
        with mock.patch.object(app, "_CONTENT_GATE_STATE", state()), \
                mock.patch.object(app._LINE_REVIEW, "evaluate", return_value={
                    "allowed": False}) as evaluate:
            self.assertTrue(app.line_review_permits(
                "line_quality", "line", reasons=["buried by grader"]))
            evaluate.assert_not_called()
            self.assertFalse(app.line_review_permits(
                "recording_requirement", "line", reasons=["missing audio"],
                technical=True))
            evaluate.assert_called_once()
        self.assertEqual(app.line_review_drop_gate("binned by editorial profile"),
                         ("line_quality", False))
        self.assertEqual(app.line_review_drop_gate("deadline expired"),
                         ("freshness", False))
        self.assertEqual(app.line_review_drop_gate("lost the floor"),
                         ("timing", False))

    def test_stored_editorial_flags_do_not_hide_playable_audio(self):
        row = {"off_brief": True, "entry": {"off_brief": True,
               "profile": "old", "script": "A: words", "caller_name": "caller"}}
        with mock.patch.object(app, "_CONTENT_GATE_STATE", state()), \
                mock.patch.object(app, "dialogue_entry", return_value=row["entry"]), \
                mock.patch.object(app, "_larder_profile_signature", return_value="new"), \
                mock.patch.object(app, "phrase_ban_row_blocked", return_value=True), \
                mock.patch.object(app, "call_entry_contract", return_value=False), \
                mock.patch.object(app, "dialogue_audio_ready", return_value=True):
            self.assertTrue(app.profile_compatible("old", "new"))
            self.assertTrue(app.dialogue_row_ready("caller", row))
            with mock.patch.object(app, "dialogue_audio_ready", return_value=False):
                self.assertFalse(app.dialogue_row_ready("caller", row))

    def test_repeat_and_phrase_filters_are_off_until_enabled(self):
        with mock.patch.object(app, "_CONTENT_GATE_STATE", state()), \
                mock.patch.object(app, "banned_words", side_effect=AssertionError(
                    "ban list should not be read")):
            self.assertTrue(app.repeat_safe("caller", {"text": "just played"}))
            self.assertEqual(app.strip_banned("Keep these exact words"),
                             "Keep these exact words")
            self.assertFalse(app.phrase_ban_row_blocked("caller", {
                "text": "Keep these exact words"}))
