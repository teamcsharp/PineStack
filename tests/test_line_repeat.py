import unittest

import line_repeat as repeat


class RepeatEvidenceTests(unittest.TestCase):
    def test_receipts_are_not_publication_or_scheduling(self):
        now = 200000
        rows = [
            {"id": "heard", "text": "Don't repeat this!", "heard_ack_at": now - 5, "air_at": now - 20},
            {"id": "heard", "text": "DON'T repeat this.", "aired": "page", "air_at": now - 20},
            {"id": "queued", "text": "Don't repeat this", "aired": "prepared", "air_at": now - 10},
            {"id": "sent", "text": "Don't repeat this", "aired": "stream", "air_at": now - 10},
            {"id": "old", "text": "Don't repeat this", "heard_ack_at": now - 86401},
            {"id": "future", "text": "Don't repeat this", "heard_ack_at": now + 3},
            {"id": "estimate", "text": "Don't repeat this", "heard_ack_at": now - 3, "heard_ack_by": "set"},
            {"id": "other", "text": "Don't repeat this whole sentence", "heard_ack_at": now - 1},
        ]
        result = repeat.analyze("Don't repeat this", rows, [], now)
        self.assertEqual(result["played_24h"], 1)
        self.assertEqual(result["occurrences_24h"], 3)
        self.assertEqual(result["published_unconfirmed_24h"], 1)
        self.assertEqual(result["retained_occurrences"], 6)

    def test_exact_turns_and_iterations_are_deduplicated(self):
        call = {"at": 199980, "model": "writer", "script": "A: Fresh start.\nCALLER: Repeat this.", "prompt": "A static prompt", "temp": 0}
        result = repeat.analyze("repeat this", [], [call, call, {**call, "at": 199990}], 200000)
        self.assertEqual(result["writing_iterations"], 2)
        self.assertEqual(result["iterations"][0]["temp"], 0)
        self.assertTrue(any("unchanged" in cause for cause in result["causes"]))
        self.assertFalse(repeat.script_contains("A: Do not repeat this", "repeat this"))
        self.assertFalse(repeat.script_contains("A: repeat this later", "repeat this"))
        self.assertFalse(repeat.script_contains("anything", ""))

    def test_long_text_fingerprint_and_shared_recording(self):
        text = "A whole long dialogue line. " * 40
        rows = [{"id": str(i), "text": text[:600], "repeat_text_key": repeat.fingerprint(text),
                 "clip_media": "same.wav", "heard_ack_at": 199900 + i} for i in range(2)]
        result = repeat.analyze(text, rows, [], 200000)
        self.assertEqual(result["played_24h"], 2)
        self.assertTrue(any("recording" in cause for cause in result["causes"]))

    def test_missing_ids_and_invalid_times_do_not_invent_plays(self):
        result = repeat.analyze("test", [{"text": "test", "heard_ack_at": 199999},
                                        {"id": "a", "text": "test", "heard_ack_at": "nan"}], [], 200000)
        self.assertEqual(result["played_24h"], 0)
        self.assertEqual(result["writing_iterations"], 0)
        self.assertIn("does not establish", result["causes"][0])


if __name__ == "__main__":
    unittest.main()
