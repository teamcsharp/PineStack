"""#1063: a recorded line airs.

"If a statement is recorded and staged for the radio, then it is to be
played on the radio." The air-time gates keep their judgment for lines
that are not yet recorded; on a recorded round they write down what they
would have cut and the line airs.
"""
import inspect
import unittest
from unittest import mock

import app


class RecordedAirsTests(unittest.TestCase):
    def test_gate_drops_an_unrecorded_line_and_keeps_a_recorded_one(self):
        with (mock.patch.object(app, "note_drop") as drop,
              mock.patch.object(app, "pipeline_log") as log):
            self.assertTrue(app.air_gate(False, "dj", "some words", "a repeat"))
            drop.assert_called_once_with("dj", "some words", "a repeat")
            self.assertFalse(app.air_gate(True, "dj", "some words", "a repeat"))
            drop.assert_called_once()
            self.assertIn("airs as recorded", log.call_args.args[1])
            self.assertIn("a repeat", log.call_args.args[1])

    def test_both_air_doors_carry_the_flag(self):
        for fn in (app.speak_turns, app._speak_turns_floorless):
            params = inspect.signature(fn).parameters
            self.assertIn("recorded", params)
            self.assertIs(params["recorded"].default, False)

    def test_a_recorded_line_is_exempt_from_the_repeat_gate(self):
        with mock.patch.object(app, "_repeat_flow_verdict",
                               side_effect=lambda t, w, k, v, *a: v):
            verdict = app.rerun_check("the very same sentence again and again",
                                      "dj", allow_repeat=True)
        self.assertFalse(verdict["block"])


if __name__ == "__main__":
    unittest.main()
