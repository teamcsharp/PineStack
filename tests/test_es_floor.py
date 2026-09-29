"""[es-floor] The calibrated audibility floor in system3.voice_intent
(tools/es_floor_patch.py): a key an ES row moves is at least its floor off
neutral at any intensity, keeps its sign, still rises with intensity, and never
goes past the full send (intensity 1.0, exactly as before). range and temp are
the old curve. Pure arithmetic; nothing renders."""
import unittest

import system3
import system3_tables

MULT = ("tempo", "range", "pause")
LEVELS = [x / 20 for x in range(21)]


def old_curve(block, i):
    s = 0.35 + 0.65 * i
    return {k: round(v ** s if k in MULT else v * s, 4) for k, v in (system3.clean_es_voice(block) or {}).items()}


def v2_blocks():
    table = getattr(system3_tables, "ES1_V2", None) or system3_tables.ES1
    out = []
    for cat in table["categories"]:
        if isinstance(cat.get("voice"), dict):
            out.append((cat["id"], cat["voice"]))
        for item in cat.get("items") or []:
            if isinstance(item.get("voice"), dict):
                out.append((cat["id"] + "/" + str(item.get("id")), dict(cat.get("voice") or {}, **item["voice"])))
    return out


class FloorTests(unittest.TestCase):
    def test_the_floor_is_the_one_asked_for(self):
        self.assertEqual(system3.ES_VOICE_FLOOR, {"tempo": 0.05, "pitch": 0.8, "energy": 0.25, "pause": 0.08})

    def test_every_moved_key_is_heard_signed_and_capped(self):
        blocks = v2_blocks()
        self.assertTrue(blocks)
        for name, block in blocks:
            full = system3.clean_es_voice(block)
            for i in LEVELS:
                got = system3.voice_intent(block, i)
                self.assertEqual(set(got), set(full), name)
                for k, v in full.items():
                    n = system3.ES_VOICE_NEUTRAL[k]
                    d, df = got[k] - n, v - n
                    if k not in system3.ES_VOICE_FLOOR or abs(df) <= 0.004:
                        self.assertEqual(got[k], old_curve(block, i)[k], (name, k, i))
                        continue
                    self.assertGreater(d * df, 0, (name, k, i, "sign"))
                    self.assertLessEqual(abs(d), abs(df) + 1e-4, (name, k, i, "past the full send"))
                    self.assertGreaterEqual(abs(d) + 1e-4, min(system3.ES_VOICE_FLOOR[k], abs(df)),
                                            (name, k, i, "under the floor"))
                    self.assertGreaterEqual(abs(d) + 1e-4, abs(old_curve(block, i)[k] - n),
                                            (name, k, i, "less than it was"))

    def test_it_still_rises_with_intensity_and_full_strength_is_unchanged(self):
        for name, block in v2_blocks():
            full = system3.clean_es_voice(block)
            self.assertEqual(system3.voice_intent(block, 1.0), old_curve(block, 1.0), name)
            for k, v in full.items():
                n = system3.ES_VOICE_NEUTRAL[k]
                seq = [abs(system3.voice_intent(block, i)[k] - n) for i in LEVELS]
                self.assertEqual(seq, sorted(seq), (name, k, "falls with intensity"))
                if k in system3.ES_VOICE_FLOOR and abs(v - n) > system3.ES_VOICE_FLOOR[k] + 0.01:
                    self.assertLess(seq[0], seq[-1], (name, k, "flat"))

    def test_a_small_send_gets_its_whole_send_and_neutral_stays_neutral(self):
        got = system3.voice_intent({"tempo": 1.03, "pitch": -0.5, "energy": 0.0, "range": 1.2, "temp": 0.05}, 0.2)
        self.assertEqual(got["tempo"], 1.03)
        self.assertEqual(got["pitch"], -0.5)
        self.assertEqual(got["energy"], 0.0)
        self.assertEqual(got["range"], round(1.2 ** (0.35 + 0.65 * 0.2), 4))
        self.assertEqual(got["temp"], round(0.05 * (0.35 + 0.65 * 0.2), 4))
        self.assertEqual(system3.voice_intent({}, 0.5), {})


if __name__ == "__main__":
    unittest.main()
