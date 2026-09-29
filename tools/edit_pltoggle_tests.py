"""[pltoggle] tests/test_pinelive.py: the album choice in state, System 3's
read and the host's control (master follows album). The full proofs live in
tests/test_pinelive_toggles.py (copy it beside this file's target).

  python edit_pltoggle_tests.py [--check|--apply] tests/test_pinelive.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pltoggle_lib  # noqa: E402

EDITS = [
    ("test.album_in_state_and_control",
     "    def test_troubleshoot_first_fail_walks_the_chain(self):\n",
     "    def test_album_choice_in_state_and_control(self):\n"
     "        \"\"\"[pltoggle] the album switch is settings.record: state shows it,\n"
     "        a rehearsal never records, and the host's master follows it.\"\"\"\n"
     "        import json\n"
     "        with tempfile.TemporaryDirectory() as td:\n"
     "            pl = self._pl(td)\n"
     "            self.assertTrue(pl.state()[\"recording\"][\"album\"])      # default on\n"
     "            pl.event = {\"id\": \"e\", \"folder\": \"f\"}\n"
     "            pl.phase = \"live\"\n"
     "            pl.write_control()\n"
     "            self.assertTrue(json.loads(pl.control_path.read_text())[\"master\"])\n"
     "            self.assertTrue(pl.state()[\"recording\"][\"on\"])\n"
     "            pl.settings[\"record\"] = False\n"
     "            pl.write_control()\n"
     "            self.assertFalse(json.loads(pl.control_path.read_text())[\"master\"])\n"
     "            st = pl.state()\n"
     "            self.assertFalse(st[\"recording\"][\"on\"])\n"
     "            self.assertFalse(st[\"recording\"][\"album\"])\n"
     "            pl.settings[\"record\"] = True\n"
     "            pl.event[\"rehearse\"] = True\n"
     "            self.assertFalse(pl.state()[\"recording\"][\"on\"])         # a test is never recorded\n"
     "\n"
     "    def test_troubleshoot_first_fail_walks_the_chain(self):\n",
     "    def test_album_choice_in_state_and_control(self):\n"),
]


if __name__ == "__main__":
    sys.exit(pltoggle_lib.main(lambda path: EDITS))
