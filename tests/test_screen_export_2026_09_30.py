"""[screen-export] "export the last X minutes of the pine tab / pine app / the
visual broadcast" -> a screen export; "... of the audio broadcast" / "... of
the broadcast" -> the audio cut, as before (#1025)."""
import ast
import re
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "app.py").read_text(encoding="utf-8")
WANT = {"export_number", "parse_export_command", "export_screen_target", "export_dir_shaped"}


def _parser():
    tree = ast.parse(SRC)
    keep = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in WANT:
            keep.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = [t.id for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
                     if isinstance(t, ast.Name)]
            if any(n.startswith("_EXPORT") for n in names):
                keep.append(node)
    ns = {"re": re, "Any": Any}
    exec(compile(ast.Module(keep, []), "app.py", "exec"), ns)
    return ns["parse_export_command"]


parse = _parser()


class ScreenOrders(unittest.TestCase):
    def test_the_pine_tab(self):
        self.assertEqual(parse("export the last 5 minutes of the pine tab"), {"seconds": 300, "screen": "tab"})
        self.assertEqual(parse("Export the last two minutes of the PineTab."), {"seconds": 120, "screen": "tab"})
        self.assertEqual(parse("export the last ten minutes of the tablet's screen"), {"seconds": 600, "screen": "tab"})

    def test_the_nabu_hears_pine_tap(self):
        # [screen-export-claim] 06:47 "Export the last minute of the Pine Tap broadcast." became an audio cut
        self.assertEqual(parse("Export the last minute of the Pine Tap broadcast."), {"seconds": 60, "screen": "tab"})
        self.assertEqual(parse("export the last 5 minutes of pinetap"), {"seconds": 300, "screen": "tab"})

    def test_the_pine_app(self):
        self.assertEqual(parse("export the last 3 minutes of the pine app"), {"seconds": 180, "screen": "app"})
        self.assertEqual(parse("export the last five minutes of the pine box app"), {"seconds": 300, "screen": "app"})

    def test_the_visual_broadcast_is_the_tablet_screen(self):
        self.assertEqual(parse("export the last 5 minutes of the visual broadcast"), {"seconds": 300, "screen": "tab"})
        self.assertEqual(parse("export the last 5 minutes of the video broadcast"), {"seconds": 300, "screen": "tab"})

    def test_the_audio_broadcast_stays_audio(self):
        for said in ("export the last 5 minutes of the audio broadcast",
                     "export the last 5 minutes of the broadcast"):
            got = parse(said)
            self.assertIsNotNone(got, said)
            self.assertNotIn("screen", got, said)
            self.assertEqual(got["seconds"], 300, said)

    def test_talk_about_a_tablet_is_not_an_order(self):
        self.assertIsNone(parse("why does the pine tab export the last five minutes so slowly?"))


class TheRoad(unittest.TestCase):
    def test_the_order_rides_the_state_and_the_panel_answers_it(self):
        self.assertIn('base["screen_export"] = export_screen_public()', SRC)
        self.assertIn('@app.post("/api/export/screen/claim")', SRC)
        self.assertIn('@app.post("/api/export/screen/done")', SRC)
        self.assertIn("try { screenExportWatch(state); }", SRC)
        self.assertIn("desk.replayExport({seconds: claim.seconds, upload: true, name: claim.name})", SRC)
        self.assertIn('if cmd.get("screen"):', SRC)

    def test_the_claim_and_the_report_are_posts(self):
        # [screen-export-claim] the main panel's api(path, options) takes fetch
        # options: a bare {id, device} went out as a GET, 405, and the tablet
        # never claimed an order.
        for route in ("/api/export/screen/claim", "/api/export/screen/done"):
            calls = re.findall(r'api\("' + re.escape(route) + r'", (\{[^\n]*\n?[^\n]*)', SRC)
            self.assertTrue(calls, route)
            for call in calls:
                self.assertRegex(call, r'^\{method: "POST",\s+body: JSON\.stringify\(', route)


if __name__ == "__main__":
    unittest.main()
