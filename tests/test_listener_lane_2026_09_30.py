"""[listener-lane] listeners' submissions: library records, a rolled lane, never stings."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "app.py").read_text(encoding="utf-8")


class Lane(unittest.TestCase):
    def test_the_folder_is_a_music_root_and_never_a_sting_folder(self):
        self.assertIn('USER_MUSIC_ROOT = SFX_ROOT / "samples_grabbed" / "user"', SRC)
        self.assertIn("MUSIC_ROOTS.append(USER_MUSIC_ROOT)", SRC)
        self.assertIn('SFX_DROP_SKIP = {"user"}', SRC)
        self.assertIn("and one.name.lower() not in SFX_DROP_SKIP", SRC)

    def test_the_lane_is_rolled_and_airs_like_a_request(self):
        at = SRC.index("# [listener-lane] now and then, a listener's own track")
        body = SRC[at:at + 1400]
        self.assertIn('s3_chance("records.listener_due", LISTENER_ODDS', body)
        self.assertIn('_spin_stamp(sub, "listener", roll="records.listener_pick"', body)
        self.assertLess(at, SRC.index("if _RADIO[\"requests\"] and _spin_request_jump():"))
        self.assertIn('"requested": True, "listener": True, "submitted_by"', SRC)
        self.assertIn("norepeat_record_used(t.get(\"id\"))", SRC)

    def test_the_djs_are_told_whose_it_is(self):
        self.assertIn("This record is a listener's own submission", SRC)

    def test_a_new_submission_is_read_in(self):
        self.assertIn("_listener_watch(got)", SRC)


if __name__ == "__main__":
    unittest.main()
