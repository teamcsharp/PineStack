"""2026-09-08: RapAssembly - the assembly line as one live state, and its view."""
import re
import unittest
from pathlib import Path
from unittest import mock

import app


class RapAssemblyStateTests(unittest.TestCase):
    def test_the_state_carries_every_station_and_never_raises(self):
        with mock.patch.object(app, "_RAP_ASSEMBLY_MEMO", {"at": 0.0, "value": None}), \
                mock.patch.object(app, "_RADIO", {"on": True, "now": {"artist": "A", "title": "T"},
                                                  "pipeline": [{"ts": 1.0, "kind": "crystal", "text": "a bar was refused"},
                                                               {"ts": 2.0, "kind": "air", "text": "a gold bar fills the air"},
                                                               {"ts": 3.0, "kind": "debug", "text": "hidden"}]}), \
                mock.patch.object(app, "_LARDER", []), mock.patch.object(app, "_SHELF", {}), \
                mock.patch.object(app, "_PANTRY", {}), mock.patch.object(app, "_TINT_JUDGE_RING", []), \
                mock.patch.object(app, "orchestrator_pipeline_state", lambda: {"stages": {"ready": 1}, "writers": {}}), \
                mock.patch.object(app, "writing_room_state", lambda: {"active": 1, "waiting": 2, "jobs": []}), \
                mock.patch.object(app, "hour_shortfall", lambda: {"entries": 4, "ready": [1, 2], "short": [{"label": "news"}]}), \
                mock.patch.object(app, "speaking_now", lambda: {"who": "dj", "text": "hello"}), \
                mock.patch.object(app, "crystal_active", mock.Mock(side_effect=RuntimeError("no crystal store"))):
            got = app.rap_assembly_state()
        for station in ("ideation", "writing", "crystal", "tint", "grader", "recording", "stores", "schedule", "air", "learning"):
            self.assertIn(station, got["stages"], station)
        self.assertEqual(got["stages"]["writing"]["active"], 1)
        self.assertEqual(got["stages"]["schedule"]["ready"], 2)
        self.assertEqual(got["stages"]["air"]["line"]["who"], "dj")
        self.assertEqual(got["stages"]["crystal"], {})          # a failed part is empty, never an error
        self.assertEqual([e["kind"] for e in got["events"]], ["crystal", "air"])
        # Memoised: the same object comes back inside the window.
        with mock.patch.object(app, "_RAP_ASSEMBLY_MEMO", {"at": app.time.time(), "value": got}):
            self.assertIs(app.rap_assembly_state(), got)

    def test_the_view_is_registered_on_the_panel_and_the_desktop_rail(self):
        self.assertIn('{key: "rapassembly", label: "🎛 RapAssembly"', app.CONTROL_PANEL_HTML)
        self.assertIn("async function rapAssemblyPanel()", app.CONTROL_PANEL_HTML)
        self.assertIn('api("/api/rapassembly")', app.CONTROL_PANEL_HTML)
        rail = (Path(__file__).resolve().parent.parent / "desktop" / "renderer" / "renderer.js").read_text(encoding="utf-8")
        self.assertRegex(rail, re.compile(r'key: "rapassembly", icon: "🎛", name: "RapAssembly"'))
        doc = (Path(__file__).resolve().parent.parent / "docs" / "RapAssembly.md").read_text(encoding="utf-8")
        self.assertIn("# RapAssembly", doc)


if __name__ == "__main__":
    unittest.main()
