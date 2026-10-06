"""[perf-off-loop] [cut-anyway] The line's feeling is looked up off the loop; the accuracy dial reaches the renderer (2026-10-05).

Run from the repo root:  python3 tests/test_perf_off_loop_2026_10_05.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def src(name: str) -> str:
    return (ROOT / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


class PerfOffLoopTest(unittest.TestCase):
    def test_larder_prepare_never_calls_the_lookups_on_the_loop(self):
        app = src("app.py")
        start = app.index("async def larder_prepare(")
        body = app[start:app.index("\n_RESPONSE_WARM_LOCK = ", start)]
        self.assertIn("await asyncio.to_thread(_pv, entry, None, text, who)", body)
        self.assertIn("await asyncio.to_thread(_ps, entry, None, text, who)", body)
        self.assertNotIn('globals()["system3_perf_voice"](entry', body)
        self.assertNotIn('globals()["system3_perf_state"](entry', body)


class DialReachesTheRendererTest(unittest.TestCase):
    def test_config_keeps_the_dial_and_defaults_to_exact(self):
        import sfx_supercut as cut
        ident = "scc-" + "a" * 24
        loose = cut.config({"custom": {"id": ident, "words": "pine box", "max_seconds": 30, "accuracy": 70}})
        self.assertEqual(loose["custom"]["accuracy"], 70.0)
        old = cut.config({"custom": {"id": ident, "words": "pine box", "max_seconds": 30}})
        self.assertEqual(old["custom"]["accuracy"], 100.0)            # a plan from before the dial stays word for word
        self.assertEqual(cut.config({"custom": {"id": ident, "words": "x", "accuracy": 400}})["custom"]["accuracy"], 100.0)

    def test_a_loose_plan_is_not_refused_for_its_proof_and_an_exact_one_still_is(self):
        import sfx_supercut as cut
        ident = "scc-" + "b" * 24
        clip = {"sid": "s1", "path": "/nonexistent/clip.mp4", "from_s": 0.0, "until_s": 1.0, "seconds": 5.0,
                "said": "pine bocks", "word_cut_verified": False, "source_audio_verified": False}
        def plan(accuracy):
            return {"ok": True, "source_only": True, "complete": True, "clips": [dict(clip)],
                    "config": cut.config({"item": "x", "custom": {"id": ident, "words": "pine box",
                                                                    "max_seconds": 30, "accuracy": accuracy}})}
        with self.assertRaises(ValueError) as exact:
            cut.render_source_plan(plan(100), "/tmp/never.wav", "ffmpeg")
        self.assertIn("verified trimmed source audio", str(exact.exception))
        with self.assertRaises(Exception) as loose:
            cut.render_source_plan(plan(70), "/tmp/never.wav", "ffmpeg")
        self.assertNotIn("verified trimmed source audio", str(loose.exception))     # it got past the proof to the file itself
        self.assertNotIn("exact requested words", str(loose.exception))

    def test_a_retry_counts_from_nothing(self):
        custom = src("sfx_supercut_custom.py")
        start = custom.index("    def retry(self,ident):")
        self.assertIn("matched_words=0,unverified_words=0)", custom[start:custom.index("    async def visit(self,ident):")])


if __name__ == "__main__":
    unittest.main()
