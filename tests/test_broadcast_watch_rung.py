import asyncio
import unittest
from unittest import mock

import app


class BroadcastWatchRungTests(unittest.TestCase):
    def test_first_repair_rung_is_reported_as_working(self):
        with (mock.patch.object(app, "require_read_auth"),
              mock.patch.object(app, "air_quiet_for", return_value=90),
              mock.patch.object(app, "air_stall_mode", return_value={}),
              mock.patch.object(app, "_AIR_WATCH", {"rung": 0, "say": "repairing"})):
            report = asyncio.run(app.broadcast_watch_api())
        self.assertTrue(report["working"])
        self.assertEqual(report["rung"], app.AIR_LADDER[0][1])


if __name__ == "__main__":
    unittest.main()
