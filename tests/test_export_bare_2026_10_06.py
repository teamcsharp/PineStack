"""[export-bare] 2026-10-06: "export the broadcast" is the audio; "export the <device> broadcast" is that screen.

"If I say export the broadcast then I mean audio and if I say export the audio, I also mean
audio. If I say export <device/app> broadcast, I mean the video of the screen recording."
"""
import unittest
from pathlib import Path

import app

SOURCE = Path(app.__file__).read_text(encoding="utf-8")


class BareOrders(unittest.TestCase):
    def test_broadcast_and_audio_mean_the_audio_of_the_default_span(self):
        for said in ("export the broadcast", "export the audio", "Export the broadcast.", "save the broadcast please",
                     "export the radio", "export the show"):
            got = app.parse_export_command(said)
            self.assertEqual(got, {"seconds": app.EXPORT_BARE_SECONDS, "kind": "talk"}, said)

    def test_a_device_broadcast_means_that_screen(self):
        self.assertEqual(app.parse_export_command("export the pine tab broadcast"), {"seconds": app.EXPORT_BARE_SECONDS, "screen": "tab"})
        self.assertEqual(app.parse_export_command("export the pine app broadcast"), {"seconds": app.EXPORT_BARE_SECONDS, "screen": "app"})
        self.assertEqual(app.parse_export_command("export the pine pip broadcast"), {"seconds": app.EXPORT_BARE_SECONDS, "screen": "pip"})
        self.assertEqual(app.parse_export_command("export the pinepip broadcast"), {"seconds": app.EXPORT_BARE_SECONDS, "screen": "pip"})

    def test_a_window_still_wins(self):
        self.assertEqual(app.parse_export_command("export the last 5 minutes of the broadcast"), {"seconds": 300, "kind": "talk"})
        self.assertEqual(app.parse_export_command("export the last 10 minutes of audio"), {"seconds": 600, "kind": "talk"})
        self.assertEqual(app.parse_export_command("export the last 3 minutes of the pine app broadcast"), {"seconds": 180, "screen": "app"})

    def test_a_sentence_is_not_an_order(self):
        self.assertIsNone(app.parse_export_command("I think we should export the broadcast to everyone in the city tonight and see"))
        self.assertIsNone(app.parse_export_command("why would anyone export the broadcast?"))
        self.assertIsNone(app.parse_export_command("the broadcast was great"))

    def test_the_default_span_is_five_minutes_and_export_is_asked_before_routing(self):
        self.assertEqual(app.EXPORT_BARE_SECONDS, 300)
        self.assertLess(SOURCE.index("export_cmd = parse_export_command(user_text)"), SOURCE.index("else parse_broadcast_command(user_text))"),
                        "an export order is read before a routing order, so 'export the pine app broadcast' never re-routes the show")


if __name__ == "__main__":
    unittest.main()
