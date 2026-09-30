"""[call-voice-roll] every call rolls over the voice models of the set engine only."""
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")


class CallVoice(unittest.TestCase):
    def test_every_call_rolls_on_the_set_engine(self):
        i = SRC.index("def caller_voice_for(")
        body = SRC[i:SRC.index("\ndef ", i + 10)]
        roll = body.index('s3_weighted("call.voice_model"')
        self.assertLess(body.index("_engine_now(voice_meta(v) or {}) == _set"), roll,
                        "the pool is only the set engine's voices")
        self.assertLess(roll, body.index("held = book.get(name)"),
                        "the roll comes before the remembered voice, so every call rolls")
        self.assertIn("_set = host_clone_engine()", body)


if __name__ == "__main__":
    unittest.main()
