"""#1065 the masthead follows a rename; #1066 caller pivots enter the story."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class MastheadAndPivotTests(unittest.IsolatedAsyncioTestCase):
    def test_the_masthead_follows_the_station_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.json"
            path.write_text(json.dumps({"masthead": "The Big Apple's Little Pine Box FM Station Gazette",
                                        "motto": "Printed on the hour", "founded": "2026-09-04"}))
            with (mock.patch.object(app, "PAPER_MASTHEAD_PATH", path),
                  mock.patch.object(app, "PAPER_DIR", Path(tmp)),
                  mock.patch.object(app, "pipeline_log"),
                  mock.patch.object(app, "dj_settings",
                                    return_value={"station_name": "Chicken Tendo Little Pine Box FM Station"})):
                head = app.paper_masthead()
                self.assertEqual(head["masthead"], "The Chicken Tendo Little Pine Box FM Station Gazette")
                self.assertEqual(head["motto"], "Printed on the hour")
                saved = json.loads(path.read_text())
                self.assertEqual(saved["station"], "Chicken Tendo Little Pine Box FM Station")
                # The refreshed file now wins for the same name...
                self.assertEqual(app.paper_masthead()["masthead"],
                                 "The Chicken Tendo Little Pine Box FM Station Gazette")
            # ...and a renamed station moves it again.
            with (mock.patch.object(app, "PAPER_MASTHEAD_PATH", path),
                  mock.patch.object(app, "PAPER_DIR", Path(tmp)),
                  mock.patch.object(app, "pipeline_log"),
                  mock.patch.object(app, "dj_settings", return_value={"station_name": "Pine Box FM"})):
                self.assertEqual(app.paper_masthead()["masthead"], "The Pine Box FM Gazette")
            # An owner's custom masthead survives any rename.
            path.write_text(json.dumps({"masthead": "The Daily Tendo", "custom": True, "station": "x"}))
            with (mock.patch.object(app, "PAPER_MASTHEAD_PATH", path),
                  mock.patch.object(app, "PAPER_DIR", Path(tmp)),
                  mock.patch.object(app, "dj_settings", return_value={"station_name": "Anything Else"})):
                self.assertEqual(app.paper_masthead()["masthead"], "The Daily Tendo")

    async def test_pivots_are_reworked_into_the_situation_and_fail_closed(self):
        scraps = ["Hunter Biden running the ship here she's like a true double threat",
                  "the arguments were just about the price of the croissants"]
        adjusted = ["Whoever runs this block is a double threat, my bins gone twice this week",
                    "the arguments were just about whose trash got lifted off the kerb"]
        with (mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock,
                                return_value=json.dumps(adjusted)) as ask,
              mock.patch.object(app, "pipeline_log")):
            got = await app.call_pivots_contextualize(scraps, "stolen garbage", "act 1: bins vanish")
            self.assertEqual(got, adjusted)
            self.assertIn("stolen garbage", ask.call_args.args[0])
            self.assertIn("bins vanish", ask.call_args.args[0])
        with (mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock,
                                return_value="Sure! Here is the rewritten line:"),
              mock.patch.object(app, "pipeline_log")):
            self.assertEqual(await app.call_pivots_contextualize(scraps, "stolen garbage", ""), scraps)
        with mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock) as ask:
            self.assertEqual(await app.call_pivots_contextualize(scraps, "", ""), scraps)
            ask.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
