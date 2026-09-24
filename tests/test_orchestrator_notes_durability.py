import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

import app


class NoteSaveDurabilityTests(unittest.IsolatedAsyncioTestCase):
    def test_strict_save_propagates_write_failure(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(app, "_ORCH", {"asks": [], "policy": {},
                                                  "read": True, "last": 0}), \
                mock.patch.object(app, "ORCH_ASK_PATH", Path(root) / "asks.json"), \
                mock.patch.object(app, "ORCH_POLICY_PATH", Path(root) / "policy.json"), \
                mock.patch.object(Path, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                app.orch_save(strict=True)

    async def test_typed_note_failure_rolls_back_and_returns_503(self):
        prior = {"value": [{"text": "Keep the old order"}], "at": 1}
        state = {"asks": [], "policy": {"operator_notes": prior},
                 "read": True, "last": 0}
        request = mock.AsyncMock()
        request.json.return_value = {"text": "New direction", "road": ""}
        with mock.patch.object(app, "_ORCH", state), \
                mock.patch.object(app, "require_auth"), \
                mock.patch.object(app, "orch_save", side_effect=OSError(
                    "disk full")) as save, \
                mock.patch.object(app, "judgment_move") as move, \
                mock.patch.object(app, "pipeline_log") as log:
            with self.assertRaises(HTTPException) as raised:
                await app.api_orch_note_write(request, authorization="test")
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(state["policy"]["operator_notes"], prior)
        save.assert_called_once_with(strict=True)
        move.assert_not_called()
        log.assert_not_called()
