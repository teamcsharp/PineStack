"""[es-probe] The science-table meter reads what it is shown: a take whose melody
was moved +1.5 st by the station's own TD-PSOLA reads about +1.5 st, a slowed take
reads a rate under 1, a take with a longer pause reads more pause, and the verdict
counts a sign against the master table. Synthetic voice only; nothing renders."""
import importlib.util
import io
import unittest
import wave
from pathlib import Path

import numpy as np

import es_voice

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("es_probe", ROOT / "tools" / "es_probe.py")
es_probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(es_probe)


def take(seconds=2.4, sr=24000, f0=118.0, gap=(1.0, 1.3), stretch=1.0):
    n = int(seconds * stretch * sr)
    t = np.arange(n) / sr
    f = f0 * (1 + 0.06 * np.sin(2 * np.pi * 1.3 * t / stretch))
    ph = np.cumsum(f) / sr
    src = sum(a * np.sin(2 * np.pi * k * ph) for k, a in ((1, 1.0), (2, 0.5), (3, 0.3), (5, 0.2), (8, 0.15)))
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 3.0 * t / stretch) ** 2
    env[int(gap[0] * stretch * sr):int(gap[1] * stretch * sr)] = 0.0
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.clip(np.round(0.25 * src * env * 32767), -32768, 32767).astype("<i2").tobytes())
    return out.getvalue()


class MeterTests(unittest.TestCase):
    def test_the_meter_reads_pitch_rate_and_pauses(self):
        plain = take()
        base = es_probe.measure(plain)
        up, _how = es_voice.intonate(plain, 1.5, 1.0)
        self.assertAlmostEqual(es_probe.delta(es_probe.measure(up), base)["f0_st"], 1.5, delta=0.3)
        slow = es_probe.delta(es_probe.measure(take(stretch=1.2, gap=(1.0, 1.25))), base)
        self.assertLess(slow["rate_ratio"], 0.9)
        paused = es_probe.delta(es_probe.measure(take(gap=(0.9, 1.5))), base)
        self.assertGreater(paused["pause_prop"], 0.05)

    def test_the_verdict_counts_signs_against_the_master_table(self):
        d = {"f0_st": -1.0, "rate_ratio": 0.85, "brightness_db": -1.2}
        self.assertEqual(es_probe.verdict("sadness", d)["right"], 3)
        self.assertEqual(es_probe.verdict("joy", d)["opposite"], ["f0", "rate", "energy"])

    def test_the_render_pass_needs_the_window(self):
        with self.assertRaises(SystemExit):
            es_probe.main(["--render", "--voices", "vl_00000000"])


if __name__ == "__main__":
    unittest.main()
