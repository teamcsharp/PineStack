"""[seg-aired-in] A scene heading names the entry it went out in.

Run (never against the live data): SPARK_AGENT_DATA_DIR=/tmp/x/data \
    PYTHONPATH=tests:. python3 -m unittest tests.test_scene_aired_in
"""
import unittest
from unittest import mock

import app

WRITTEN_FOR = {"slot": {"label": "Banter during recordings", "id": "h:hour-05", "entry": "hour-05", "how": "banked"}}
ON_AIR = {"id": "h:hour-17", "label": "Painting selling", "kind": "gallery", "start": 100.0, "ends": 340.0}


class AiredIn(unittest.TestCase):
    def test_a_round_heard_in_another_entry_names_both(self):
        with mock.patch.object(app, "segment_on_air", return_value=dict(ON_AIR)) as seg:
            got = app.screenplay_scene_aired_in(WRITTEN_FOR, 200.0)
        seg.assert_called_once_with(200.0)
        self.assertEqual(got["slot"]["label"], "Banter during recordings", "the written-for name stays")
        self.assertEqual(got["slot"]["aired_in"], {"label": "Painting selling", "id": "h:hour-17"})
        self.assertNotIn("aired_in", WRITTEN_FOR["slot"], "the caller's dict is not changed")

    def test_heard_in_its_own_entry_says_nothing_more(self):
        with mock.patch.object(app, "segment_on_air", return_value=dict(ON_AIR, id="h:hour-05")):
            self.assertEqual(app.screenplay_scene_aired_in(WRITTEN_FOR, 200.0), WRITTEN_FOR)

    def test_a_heading_with_no_slot_names_the_entry_on_air(self):
        none = {"slot": {"none": True, "why": "not reserved"}}
        with mock.patch.object(app, "segment_on_air", return_value=dict(ON_AIR)):
            got = app.screenplay_scene_aired_in(none, 200.0)
        self.assertTrue(got["slot"]["none"])
        self.assertEqual(got["slot"]["aired_in"]["label"], "Painting selling")

    def test_unknown_stays_unknown(self):
        with mock.patch.object(app, "segment_on_air", return_value=dict(ON_AIR)):
            self.assertEqual(app.screenplay_scene_aired_in({}, 200.0), {})
            self.assertEqual(app.screenplay_scene_aired_in(WRITTEN_FOR, 0.0), WRITTEN_FOR)
        with mock.patch.object(app, "segment_on_air", return_value={}):
            self.assertEqual(app.screenplay_scene_aired_in(WRITTEN_FOR, 200.0), WRITTEN_FOR)
        with mock.patch.object(app, "segment_on_air", side_effect=RuntimeError("no")):
            self.assertEqual(app.screenplay_scene_aired_in(WRITTEN_FOR, 200.0), WRITTEN_FOR)


if __name__ == "__main__":
    unittest.main()
