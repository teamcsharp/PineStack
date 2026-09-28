"""[s3-sfx-roll] app.py carries every edit tools/system3_sfx_roll_patch.py
describes (its --check says "applied", exit 2), and system3_runtime.py
carries the door the edits call. Reads the files; imports neither."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "system3_sfx_roll_patch.py"


def tool():
    spec = importlib.util.spec_from_file_location("system3_sfx_roll_patch", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SfxRollWiringTests(unittest.TestCase):
    def test_every_edit_is_in_app_py_once(self):
        mod = tool()
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)), "every [s3-sfx-roll] edit is present exactly once")

    def test_the_tools_check_says_applied(self):
        got = subprocess.run([sys.executable, str(TOOL), "--check", str(ROOT / "app.py")],
                             capture_output=True, text=True, timeout=600)
        self.assertEqual(got.returncode, 2, got.stdout + got.stderr)

    def test_the_runtime_carries_the_door_the_edits_call(self):
        text = (ROOT / "system3_runtime.py").read_text(encoding="utf-8")
        for needle in ('def pick(self, key, candidates, label="", weights=None, media=None):',
                       "def last_roll(self, key):", "def line_media(conv):",
                       'namespace["system3_last_roll"] = rt.last_roll',
                       'namespace["system3_dice_live"] = rt._dice_live',
                       'meta["poster"] = r["poster"]', "rt.line_media(got)"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
