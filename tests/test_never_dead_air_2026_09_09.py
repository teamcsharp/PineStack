"""2026-09-09: "I want the gold tinted material filling in the dead air
constantly, ensuring that there is never dead air on the broadcast."

Measured over the eighteen hours before this: the bank held 514 rhymed bars
with their takes on disk - 67 minutes of finished audio, 282 of them never
fired once - and the filler still put ONE bar into each hole. 116 of its 134
fills were a single bar (median 6.8s) against holes of median 20.7s. A hole
is filled until it is closed now, not punctuated once.
"""
import time
import unittest
from contextlib import ExitStack
from unittest import mock

import app


def _bar(key, who, seconds=6.0):
    return {"key": key, "who": who, "text": f"bar {key} / spar {key}",
            "path": f"take-{key}.wav", "seconds": seconds,
            "at": time.time() - 3600, "fired": 0, "last": 0.0}


class GoldRunTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # Alternating seats, because a run picks a different one each time.
        self.gold = {"loaded": True, "rows": [
            _bar(str(i), "dj" if i % 2 else "cohost") for i in range(20)]}
        self.speak = mock.AsyncMock(return_value="ok")
        self.radio = {"on": True}
        for name, value in {
                "_GOLD": self.gold, "_gold_save": mock.Mock(),
                "pipeline_log": mock.Mock(), "dj_speak": self.speak,
                "_RADIO": self.radio, "radio_paused": lambda: False,
                "media_sign": lambda name: "sig-" + name,
                "VOICE_MEDIA_DIR": mock.MagicMock()}.items():
            self.stack.enter_context(mock.patch.object(app, name, value))
        app.VOICE_MEDIA_DIR.__truediv__ = lambda self_, name: mock.Mock(
            is_file=lambda: True)

    async def test_the_run_keeps_laying_bars_until_the_runway_is_full(self):
        self.assertEqual(await app.gold_fill_gap("dead air"), "bar")
        # 6-second bars against the default runway: enough of them to cover
        # it, and not one more.
        laid = self.speak.await_count
        self.assertGreater(laid, 1, "a hole was punctuated once, not filled")
        self.assertGreaterEqual(laid * 6.0, app.GOLD_RUN_AHEAD)
        self.assertLessEqual((laid - 1) * 6.0, app.GOLD_RUN_AHEAD)
        fired = [r for r in self.gold["rows"] if r["fired"]]
        self.assertEqual(len(fired), laid)

    async def test_a_run_never_lays_more_than_its_cap(self):
        for row in self.gold["rows"]:
            row["seconds"] = 0.4          # tiny bars: the seconds cap cannot bite
        self.gold["rows"].extend(
            _bar(f"x{i}", "dj" if i % 2 else "cohost", 0.4) for i in range(40))
        await app.gold_fill_gap("dead air", ahead=app.GOLD_RUN_SECONDS)
        self.assertEqual(self.speak.await_count, app.GOLD_RUN_MOST)

    async def test_a_pause_landing_mid_run_stops_it(self):
        paused = {"now": False}
        # The second bar finds the station paused; the first is already sold.
        async def speak(*a, **k):
            paused["now"] = True
            return "ok"
        self.stack.enter_context(mock.patch.object(app, "dj_speak", speak))
        self.stack.enter_context(mock.patch.object(
            app, "radio_paused", lambda: paused["now"]))
        self.assertEqual(await app.gold_fill_gap("dead air"), "bar")
        self.assertEqual(len([r for r in self.gold["rows"] if r["fired"]]), 1)

    async def test_the_run_alternates_seats(self):
        await app.gold_fill_gap("dead air")
        seats = [c.kwargs["who"] for c in self.speak.await_args_list]
        self.assertTrue(all(a != b for a, b in zip(seats, seats[1:])),
                        f"the same presenter answered himself: {seats}")


class SettingsStatRestTests(unittest.TestCase):
    def test_a_settings_read_does_not_stat_the_share_every_time(self):
        app.load_settings()
        with mock.patch.object(type(app.SETTINGS_PATH), "stat",
                               side_effect=AssertionError("statted again")):
            app.load_settings()

    def test_saving_settings_is_seen_at_once(self):
        app.load_settings()
        app._SETTINGS_CACHE.update({"key": None, "value": None, "at": 0.0})
        self.assertIsNotNone(app.load_settings())


if __name__ == "__main__":
    unittest.main()
