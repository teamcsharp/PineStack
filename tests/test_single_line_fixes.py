"""[s3-line-fix] A single line's node sits in the speaker's seat, a line
that speaks its own running-order row is caught, and the ledger asks for a
line's stamp once."""
import unittest

import system3

try:
    from tests.test_system3 import inputs, settings
except ModuleNotFoundError:  # the container runs the suites with tests/ on the path
    from test_system3 import inputs, settings


class SeatTests(unittest.TestCase):
    def test_the_speaker_the_door_passed_in_is_the_nodes_seat(self):
        config = system3.default_config()
        # the dj reads the station ID live: seat A, though the leg says D
        conv = system3.new_conversation(inputs(road="station_id", seats=["A"], turns=1), config, settings(),
                                        conversation_id="sid-a")
        system3.plan_line(conv, config)
        self.assertEqual(conv["turns"][0]["speaker"], "A")
        # the SFX Guy's liner: the door passes his seat
        conv = system3.new_conversation(inputs(road="station_id", seats=["D"], turns=1), config, settings(),
                                        conversation_id="sid-d")
        system3.plan_line(conv, config)
        self.assertEqual(conv["turns"][0]["speaker"], "D")
        # a cohost's send-off is a cohost's node
        conv = system3.new_conversation(inputs(road="track_talk", seats=["B"], turns=1), config, settings(),
                                        conversation_id="tt-b")
        system3.plan_line(conv, config)
        self.assertEqual(conv["turns"][0]["speaker"], "B")
        sheet = system3.render_legs_sheet(conv)
        self.assertRegex(sheet, r"(?m)^\s*1\s+B\s+-")


class EchoTests(unittest.TestCase):
    """The door's check lives in app.py; it is imported lazily because app is
    the whole station."""

    @classmethod
    def setUpClass(cls):
        import app
        cls.check = staticmethod(app._sheet_speaks_direction)

    def test_a_line_that_speaks_its_row_is_caught(self):
        sheet = ("\n\nTHE RUNNING ORDER OF THIS LINE.\n"
                 " 1  D  - shouts the station's name like it is the only station there is, and means it. "
                 "[Say it in pride, plainly.]\n")
        self.assertTrue(self.check("D shouts the station's name like it is the only station there is", sheet))
        self.assertTrue(self.check("Shouts the station's name like it is the only station there is - Pine Box FM!", sheet))

    def test_a_real_line_passes(self):
        sheet = " 1  A  - shouts the station's name like it is the only station there is.\n"
        self.assertEqual(self.check("Pine Box FM! The only station worth the batteries.", sheet), "")
        self.assertEqual(self.check("", sheet), "")
        self.assertEqual(self.check("anything at all", ""), "")

    def test_the_ledger_asks_for_a_stamp_once(self):
        import inspect
        import app
        src = inspect.getsource(app.script_ledger_catch_up) if hasattr(app, "script_ledger_catch_up") else open(app.__file__, encoding="utf-8").read()
        self.assertIn('(_st := _s3_line_stamp_of(one))', src)
        self.assertNotIn('if _s3_line_stamp_of(one) else {}', src)


if __name__ == "__main__":
    unittest.main()
