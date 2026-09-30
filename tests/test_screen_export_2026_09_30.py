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


if __name__ == "__main__":
    unittest.main()
