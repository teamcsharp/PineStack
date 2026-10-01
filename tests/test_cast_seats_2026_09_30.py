"""[cast-seats] banked footage survives a change to a seat it never speaks in.

414 of 427 shelf rows (3.9 h) were refused as "recast" because the rotating
guest seat changed, though the DJ and co-host had not.
"""
import unittest
from unittest import mock

import app

BOOTH = "cohost=john|dj=amy|drop_voice=vl_d|third=vl_new"
OLD_GUEST = "cohost=john|dj=amy|drop_voice=vl_d|third=vl_old"


def round_row(*who, **extra):
    entry = {"takes": [{"who": w, "voice": "v"} for w in who]}
    entry.update(extra)
    return {"cast": OLD_GUEST, "entry": entry}


class CastSeats(unittest.TestCase):

    def setUp(self):
        p = mock.patch.object(app, "cast_signature", return_value=BOOTH)
        p.start()
        self.addCleanup(p.stop)

    def test_a_guest_change_leaves_a_dj_round_airable(self):
        self.assertFalse(app.shelf_cast_stale(round_row("dj", "cohost", "drop")))

    def test_a_round_the_old_guest_speaks_in_is_stale(self):
        self.assertTrue(app.shelf_cast_stale(round_row("dj", "third")))

    def test_the_recast_desk_keeps_it_airing(self):
        self.assertFalse(app.shelf_cast_stale(round_row("dj", "third", recast_needed=True)))

    def test_a_dj_change_still_stales_a_dj_round(self):
        row = round_row("dj", "cohost")
        row["cast"] = "cohost=john|dj=someone_else|drop_voice=vl_d|third=vl_new"
        self.assertTrue(app.shelf_cast_stale(row))

    def test_a_flat_read_ignores_the_guest(self):
        self.assertFalse(app.shelf_cast_stale({"cast": OLD_GUEST, "voice": "v"}))
        self.assertTrue(app.shelf_cast_stale(
            {"cast": "cohost=john|dj=x|drop_voice=vl_d|third=vl_new", "voice": "v"}))

    def test_unstamped_and_matching_rows(self):
        self.assertFalse(app.shelf_cast_stale({"entry": {"takes": []}}))
        self.assertFalse(app.shelf_cast_stale({"cast": BOOTH}))

    def test_a_larder_entry_is_its_own_entry(self):
        self.assertFalse(app.shelf_cast_stale({"cast": OLD_GUEST, "takes": [{"who": "dj"}]}))


if __name__ == "__main__":
    unittest.main()
