import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

import app


def request(body):
    return SimpleNamespace(json=mock.AsyncMock(return_value=body))


class LineReviewReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_is_reviewed_and_directs_next_script(self):
        record = {"context": {"kind": "caller"}}
        saved = {"row": {"id": "review-1"},
                 "note": {"note": "Needs back-and-forth about why they called."}}
        direction = {"id": "direction-1", "text": saved["note"]["note"]}
        with mock.patch.object(app, "require_auth"), \
                mock.patch.object(app._LINE_REVIEW, "get", return_value=record), \
                mock.patch.object(app._LINE_REVIEW, "annotate", return_value=saved) as annotate, \
                mock.patch.object(app, "director_add", return_value=direction) as add, \
                mock.patch.object(app, "station_flow_event"):
            got = await app.api_line_review_reply(
                "review-1", request({"note": saved["note"]["note"],
                                     "expected_revision": 4, "expected_event_seq": 9}),
                authorization="Bearer test")
        self.assertTrue(got["ok"])
        self.assertEqual(got["direction"]["id"], "direction-1")
        annotate.assert_called_once_with("review-1", saved["note"]["note"], 4, 9)
        add.assert_called_once_with("caller", saved["note"]["note"], "next", who="operator")

    async def test_reply_without_segment_kind_cannot_claim_direction(self):
        with mock.patch.object(app, "require_auth"), \
                mock.patch.object(app._LINE_REVIEW, "get", return_value={"context": {}}), \
                mock.patch.object(app._LINE_REVIEW, "annotate") as annotate:
            with self.assertRaises(HTTPException) as error:
                await app.api_line_review_reply("review-1", request({"note": "Talk more"}),
                                                authorization="Bearer test")
        self.assertEqual(error.exception.status_code, 400)
        annotate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
