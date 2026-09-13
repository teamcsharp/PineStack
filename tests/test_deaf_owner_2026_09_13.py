"""#1332: an owner that holds the air and takes nothing loses it.

#1187 asks whether a device is SET to play out loud. It never asks whether
it does. The two came apart on a freshly launched desktop: it claimed the
exclusive with play=on, polled steadily so the stopped-polling test (#1208)
passed, and acknowledged NOTHING - it did not appear in the ack ledger at
all - while two tablets that had played 52 and 50 clips sat muted 75 and 74
times each, waiting for it. Polling is not consuming.

Every check here exists because the rule failed that way ONCE, live:

  * #1332b - timed from the last CLAIM, the threshold was never reached,
    because the page re-claims every few seconds. That is what triangulate
    means by "it re-gags itself". It has to be timed from when the owner
    CHANGED.

  * #1332c - dropping the exclusive was not enough. The page claimed it
    back on its next poll and the house went quiet for another seventy-five
    seconds, over and over. A cure undone faster than it can be noticed is
    a cure nobody has.

  * #1332d - the ack window was the whole run, which asks "has it EVER
    worked" instead of "is it working now". A page that acknowledged one
    clip at the start of a long run was immune for as long as it held on,
    however deaf it went later. Caught live: the desktop played normally
    for minutes, went silent, and sat on the exclusive through 140s of
    quiet with the rule watching and unable to fire.

  * And the pre-ship catch: the helper read `ev["who"]` from rows that key
    it `listener_id`. It would have matched nothing and returned True for
    EVERY owner - a check that can only ever print one answer.
"""
import time
import unittest
from unittest import mock

import app


class OwnerTakesNothing(unittest.TestCase):

    def setUp(self):
        self.now = time.time()
        app._OWNER_RUN.update({"who": "", "since": 0.0})
        app._OWNER_DEAF.clear()
        self._acks = list(app._PAGE_ACK_EVENTS)
        app._PAGE_ACK_EVENTS.clear()

    def tearDown(self):
        app._PAGE_ACK_EVENTS.clear()
        app._PAGE_ACK_EVENTS.extend(self._acks)
        app._OWNER_RUN.update({"who": "", "since": 0.0})
        app._OWNER_DEAF.clear()

    def hold(self, who, seconds):
        """Pretend `who` has held the air, unbroken, for this long."""
        app._OWNER_RUN.update({"who": who, "since": self.now - seconds})

    def acked(self, who, ago):
        app._PAGE_ACK_EVENTS.append(
            {"at": self.now - ago, "listener_id": who, "event": "playing"})

    def ask(self, who, others=("tablet-a",)):
        with mock.patch.object(app, "_listeners_live",
                               return_value=[who] + list(others)):
            return app._owner_takes_nothing(who)

    # ---------------------------------------------------------------

    def test_a_holder_that_has_never_acknowledged_loses_the_air(self):
        self.hold("desktop-x", app.OWNER_DEAF_SECONDS + 10)
        self.assertTrue(self.ask("desktop-x"))

    def test_a_holder_that_is_taking_clips_is_left_alone(self):
        self.hold("desktop-x", app.OWNER_DEAF_SECONDS + 10)
        self.acked("desktop-x", 2)
        self.assertFalse(self.ask("desktop-x"))

    def test_it_asks_whether_it_is_working_NOW_not_whether_it_ever_did(self):
        """#1332d. The window is the last OWNER_DEAF_SECONDS, not the whole
        run - otherwise one ack at the start buys permanent immunity."""
        self.hold("desktop-x", 600)                 # ten minutes on the air
        self.acked("desktop-x", 590)                # ...worked at the start
        self.assertTrue(self.ask("desktop-x"),
                        "an owner deaf for the last 75s must lose the air "
                        "however well it behaved ten minutes ago")

    def test_a_fresh_holder_is_given_time(self):
        self.hold("desktop-x", app.OWNER_DEAF_SECONDS - 5)
        self.assertFalse(self.ask("desktop-x"))

    def test_the_run_is_not_reset_by_re_claiming(self):
        """#1332b. `_AUDIO_OWNER["at"]` moves on every claim and the page
        this rule exists for re-claims constantly; the run clock must only
        restart when the OWNER changes."""
        self.hold("desktop-x", app.OWNER_DEAF_SECONDS + 10)
        with mock.patch.dict(app._AUDIO_OWNER,
                             {"who": "desktop-x", "at": self.now}, clear=False):
            self.assertTrue(self.ask("desktop-x"))

    def test_a_different_owner_restarts_the_clock(self):
        self.hold("desktop-x", 600)
        self.assertFalse(self.ask("someone-else"),
                         "a newly arrived owner has not held anything yet")

    def test_the_last_device_in_the_house_keeps_the_air(self):
        """Taking it from the only listener would silence the house to cure
        a silence - there is nobody to hand it to."""
        self.hold("desktop-x", app.OWNER_DEAF_SECONDS + 10)
        self.assertFalse(self.ask("desktop-x", others=()))

    def test_another_pages_acks_do_not_excuse_this_one(self):
        """The pre-ship catch: these rows key `listener_id`, not `who`.
        Reading the wrong field matched nothing and would have returned
        True for every owner; reading it too loosely would excuse every
        owner. Both are checks that can only print one answer."""
        self.hold("desktop-x", app.OWNER_DEAF_SECONDS + 10)
        self.acked("tablet-a", 1)          # somebody else is playing fine
        self.assertTrue(self.ask("desktop-x"))

    def test_a_dropped_owner_is_refused_re_entry(self):
        """#1332c. Without this it claimed the air back on its next poll."""
        self.hold("desktop-x", app.OWNER_DEAF_SECONDS + 10)
        self.assertTrue(self.ask("desktop-x"))
        self.assertIn("desktop-x", app._OWNER_DEAF)
        self.assertGreater(app._OWNER_DEAF["desktop-x"], time.time())

    def test_the_refusal_expires(self):
        """It must clear itself. This can never become a way to lock a
        working device out of the air for good."""
        self.hold("desktop-x", app.OWNER_DEAF_SECONDS + 10)
        self.ask("desktop-x")
        self.assertLessEqual(app._OWNER_DEAF["desktop-x"],
                             time.time() + app.OWNER_DEAF_REST + 1)


if __name__ == "__main__":
    unittest.main()
