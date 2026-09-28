"""[s3-bank] The SFX Guy's banked lines air only when the roulette brings one
up, and which take is the roulette's pick."""
import inspect
import unittest
from unittest import mock

import sfx_speech_bank


class ChooserTests(unittest.TestCase):
    def bank(self, rows):
        bank = sfx_speech_bank.SfxSpeechBank.__new__(sfx_speech_bank.SfxSpeechBank)
        import threading
        bank.lock = threading.RLock()
        bank.clock = lambda: 1000.0
        bank._rows = {r["id"]: r for r in rows}
        bank._load = lambda: bank._rows
        bank._save = lambda rows: bank._rows.update(rows)
        bank.eligible = lambda *a, **k: list(bank._rows.values())
        return bank

    def rows(self):
        return [{"id": "a", "text": "I am listening. Keep talking.", "text_plain": "listening keep talking"},
                {"id": "b", "text": "I sold the tapes to Sawyer.", "text_plain": "sold tapes sawyer"}]

    def test_the_roulette_picks_the_take(self):
        bank = self.bank(self.rows())
        seen = []
        got = bank.pick("tapes", "v", "p", lambda r: True,
                        chooser=lambda takes: (seen.append(takes), 0)[1])
        self.assertEqual(got["entry_id"], "a", "index 0 - not the keyword winner 'b'")
        self.assertEqual([t["text"] for t in seen[0]], ["I am listening. Keep talking.", "I sold the tapes to Sawyer."])
        self.assertEqual(seen[0][1]["overlap"], 1)

    def test_without_a_roulette_the_bank_ranks_as_before(self):
        bank = self.bank(self.rows())
        self.assertEqual(bank.pick("tapes", "v", "p", lambda r: True)["entry_id"], "b")

    def test_a_failing_roulette_falls_back_to_the_ranking(self):
        bank = self.bank(self.rows())
        got = bank.pick("tapes", "v", "p", lambda r: True, chooser=lambda takes: 1 / 0)
        self.assertEqual(got["entry_id"], "b")


class StationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import app  # noqa: F401
        except Exception as exc:
            raise unittest.SkipTest("app.py imports only in the station's container: %s" % exc)

    def test_no_roulette_hit_no_banked_line(self):
        import app
        with mock.patch.object(app, "dj_settings", lambda: {"drop_voice": "v"}), \
                mock.patch.object(app, "_s3_dice_live", lambda: True), \
                mock.patch.object(app, "s3_chance", lambda key, odds, label="", dial="": False), \
                mock.patch.object(app._SFX_READY_BANK, "pick", side_effect=AssertionError("never asked")):
            self.assertIsNone(app.sfxguy_ready_pick("ctx", "v"))

    def test_a_hit_asks_the_bank_with_the_roulette_and_a_long_rest(self):
        import app
        asked = {}

        def pick(context, voice, profile, validate, **kw):
            asked.update(kw)
            return None
        with mock.patch.object(app, "dj_settings", lambda: {"drop_voice": "v"}), \
                mock.patch.object(app, "_s3_dice_live", lambda: True), \
                mock.patch.object(app, "s3_chance", lambda key, odds, label="", dial="": key == "sfxguy.bank_line"), \
                mock.patch.object(app, "_sfxguy_ready_profile", lambda: "p"), \
                mock.patch.object(app._SFX_READY_BANK, "pick", side_effect=pick):
            app.sfxguy_ready_pick("ctx", "v")
        self.assertIs(asked.get("chooser"), app._sfxguy_bank_roll)
        self.assertGreaterEqual(asked.get("cooldown"), 3600)

    def test_with_system3_off_the_bank_is_as_it_was(self):
        import app
        asked = {}
        with mock.patch.object(app, "dj_settings", lambda: {"drop_voice": "v"}), \
                mock.patch.object(app, "_s3_dice_live", lambda: False), \
                mock.patch.object(app, "_sfxguy_ready_profile", lambda: "p"), \
                mock.patch.object(app._SFX_READY_BANK, "pick", side_effect=lambda *a, **kw: asked.update(kw)):
            app.sfxguy_ready_pick("ctx", "v")
        self.assertEqual(asked, {})


if __name__ == "__main__":
    unittest.main()
