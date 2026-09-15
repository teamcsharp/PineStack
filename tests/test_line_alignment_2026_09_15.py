"""The alignment matcher, offline, on synthetic word timestamps.

docs/notes/speaker-recording-and-script-assembly.md is what these assert:

    "Silence alone cannot establish which line was spoken. Alignment must
    reject missing, repeated or mismatched speech; a timestamp assigned to
    every input word does not itself prove the audio contains it."

So the interesting tests here are the refusals, not the happy path. Every
case below hands the matcher a word-timestamp stream where EVERY word has a
timestamp - the recogniser is perfectly confident and perfectly timed - and
the performance is still wrong. A matcher that trusts the timestamps passes
none of them.

No engine, no GPU, no HTTP: the recognition is the input, which is the whole
reason the matching lives in a pure module. Nothing here reads or writes the
script ledger, the larder, the pantry or any other live store; the one test
that touches disk writes into a TemporaryDirectory and deletes it.
"""
import json
import tempfile
import unittest
from pathlib import Path

from line_alignment import (MODE_CONTINUOUS, MODE_SEGMENTED, REFUSAL_CODES,
                            AlignmentPolicy, RecognizedWord, ScriptLine,
                            align_script, from_whisper_words,
                            normalize_tokens, result_to_json)

RATE = 24000
WORD = 0.30          # how long a spoken word lasts in these fixtures
GAP = 0.05           # between words inside a line
PAUSE = 0.70         # between lines


def script(*texts, speaker="dj"):
    return [ScriptLine(f"occ-{index:02d}", index, speaker, text)
            for index, text in enumerate(texts)]


def speak(chunks, start=0.0, probability=0.95, pause=PAUSE):
    """Turn a list of spoken strings into a word-timestamp stream.

    One chunk is one continuous stretch of speech; `pause` separates them.
    What the recogniser heard, not what the script says - the two are
    deliberately allowed to differ, because that difference is the subject."""
    words = []
    clock = start
    for chunk in chunks:
        for token in str(chunk).split():
            words.append(RecognizedWord(token, round(clock, 4),
                                        round(clock + WORD, 4), probability))
            clock += WORD + GAP
        clock += pause
    return words, clock


def frames_for(clock, tail=0.0):
    return int(round((clock + tail) * RATE))


class HappyPath(unittest.TestCase):

    def test_a_clean_read_cuts_into_its_lines_in_integer_samples(self):
        lines = script("Good evening from the pines.",
                       "The weather is doing something strange.",
                       "Stay where you are.")
        words, clock = speak([line.text for line in lines])
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertTrue(result.ok, result.reasons())
        self.assertEqual(len(result.cuts), 3)
        self.assertEqual([c.occurrence_id for c in result.cuts],
                         ["occ-00", "occ-01", "occ-02"])
        for cut in result.cuts:
            self.assertIsInstance(cut.start_sample, int)
            self.assertIsInstance(cut.end_sample, int)
            self.assertGreater(cut.end_sample, cut.start_sample)
            self.assertEqual(cut.sample_rate, RATE)
            self.assertEqual(cut.verification["coverage"], 1.0)
            self.assertEqual(cut.verification["verdict"], "verified")
            self.assertTrue(cut.boundary_method.startswith("word_span"))
        # Cuts never overlap: strict sequential mode has one spoken line.
        for earlier, later in zip(result.cuts, result.cuts[1:]):
            self.assertLessEqual(earlier.end_sample, later.start_sample)

    def test_the_declared_mode_rides_on_every_cut(self):
        lines = script("One line only.")
        words, clock = speak([lines[0].text])
        for mode in (MODE_CONTINUOUS, MODE_SEGMENTED):
            result = align_script(lines, words, RATE, frames_for(clock), mode)
            self.assertTrue(result.ok, result.reasons())
            self.assertEqual({c.mode for c in result.cuts}, {mode})
        # And a mode nobody declared is refused rather than assumed.
        result = align_script(lines, words, RATE, frames_for(clock), "")
        self.assertFalse(result.ok)
        self.assertEqual(result.refusal_codes, ("bad_mode",))

    def test_numbers_spoken_as_digits_still_match_the_written_words(self):
        lines = script("It is twenty four degrees outside right now.")
        words, clock = speak(["It is 24 degrees outside right now."])
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertTrue(result.ok, result.reasons())


class TwoOccurrencesOfTheSameWords(unittest.TestCase):
    """The note: "Assign a revision and an ordered occurrence ID to every
    utterance, including two occurrences with identical words." Text cannot
    tell them apart; position can, and a global alignment is positional."""

    def test_identical_lines_get_their_own_cuts_in_reading_order(self):
        lines = script("Say that again.",
                       "The tape is running.",
                       "Say that again.")
        words, clock = speak([line.text for line in lines])
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertTrue(result.ok, result.reasons())
        first, _, third = result.cuts
        self.assertEqual(first.occurrence_id, "occ-00")
        self.assertEqual(third.occurrence_id, "occ-02")
        self.assertLess(first.end_sample, third.start_sample)
        # The identical text did NOT make them the same audio.
        self.assertNotEqual(first.start_sample, third.start_sample)

    def test_only_one_of_two_identical_lines_being_spoken_is_refused(self):
        lines = script("Say that again.",
                       "The tape is running.",
                       "Say that again.")
        words, clock = speak([lines[0].text, lines[1].text])
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertFalse(result.ok)
        self.assertIn("occ-02", [r.occurrence_id for r in result.refusals])
        self.assertTrue(
            {"no_speech_for_occurrence", "coverage_low", "missing_speech",
             "global_coverage_low"} & set(result.refusal_codes),
            result.refusal_codes)


class MissingSpeech(unittest.TestCase):

    def test_a_dropped_clause_names_the_line_it_fell_out_of(self):
        lines = script("Good evening from the pines.",
                       "The weather is doing something strange tonight.",
                       "Stay where you are.")
        heard = [lines[0].text, "The weather is", lines[2].text]
        words, clock = speak(heard)
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertFalse(result.ok)
        self.assertEqual(result.cuts, ())
        blamed = {r.occurrence_id for r in result.refusals}
        self.assertIn("occ-01", blamed)
        self.assertNotIn("occ-00", blamed)
        self.assertTrue({"missing_speech", "coverage_low"}
                        & set(result.refusal_codes), result.refusal_codes)
        # The reason is readable, and it says which line.
        self.assertTrue(any("occ-01" in reason and "word" in reason
                            for reason in result.reasons()), result.reasons())

    def test_one_lost_word_in_a_long_line_is_still_accepted(self):
        """A recogniser dropping an article is not a dropped performance.
        A matcher that refuses this refuses everything and gets turned off."""
        lines = script("The weather is doing something strange over the whole "
                       "of the county tonight and nobody can say why.")
        heard = ["weather is doing something strange over the whole of the "
                 "county tonight and nobody can say why."]
        words, clock = speak(heard)
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertTrue(result.ok, result.reasons())
        self.assertLess(result.cuts[0].verification["coverage"], 1.0)


class RepeatedSpeech(unittest.TestCase):

    def test_a_phrase_said_twice_inside_a_line_is_refused_by_name(self):
        lines = script("Good evening from the pines.",
                       "Stay where you are.")
        heard = ["Good evening from the from the pines.", lines[1].text]
        words, clock = speak(heard)
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertFalse(result.ok)
        self.assertIn("repeated_speech", result.refusal_codes)
        repeat = [r for r in result.refusals if r.code == "repeated_speech"][0]
        self.assertEqual(repeat.occurrence_id, "occ-00")

    def test_a_whole_line_read_twice_is_refused(self):
        lines = script("Good evening from the pines.",
                       "Stay where you are.")
        heard = [lines[0].text, lines[0].text, lines[1].text]
        words, clock = speak(heard)
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertFalse(result.ok)
        self.assertTrue({"repeated_speech", "extra_speech"}
                        & set(result.refusal_codes), result.refusal_codes)


class TransposedLines(unittest.TestCase):
    """The failure that puts a line on air out of order - the exact thing the
    code note at app.py:32685 said a mis-split would cause."""

    def test_two_lines_performed_in_the_wrong_order_are_refused(self):
        lines = script("First we take the weather.",
                       "Then we take the traffic.")
        words, clock = speak([lines[1].text, lines[0].text])
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertFalse(result.ok, result.stats)
        self.assertEqual(result.cuts, ())
        self.assertTrue(result.refusals)

    def test_a_middle_line_moved_to_the_end_is_refused(self):
        lines = script("Good evening from the pines.",
                       "The weather is doing something strange.",
                       "Stay where you are tonight.")
        words, clock = speak([lines[0].text, lines[2].text, lines[1].text])
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertFalse(result.ok)
        self.assertEqual(result.cuts, ())


class TheTrailingTail(unittest.TestCase):
    """app.py:32685, in full:

        "a three-line take with deliberate separators reported 2 silences at
        -35dB/0.45s and 3 at -40dB/0.35s, one of them the trailing tail."

    A silence splitter counted the tail as a separator and produced a fourth
    piece. Two things must be true here: a silent tail must never be part of
    the last cut, and a tail with SPEECH in it must be refused rather than
    swallowed."""

    def test_a_silent_tail_is_not_part_of_the_last_line(self):
        lines = script("Good evening from the pines.",
                       "The weather is doing something strange.",
                       "Stay where you are.")
        words, clock = speak([line.text for line in lines])
        master_frames = frames_for(clock, tail=6.0)     # six seconds of nothing
        result = align_script(lines, words, RATE, master_frames,
                              MODE_CONTINUOUS)
        self.assertTrue(result.ok, result.reasons())
        last = result.cuts[-1]
        self.assertLess(last.end_sample, master_frames)
        # And by a real margin, not a rounding: the tail is not in the cut.
        self.assertGreater((master_frames - last.end_sample) / RATE, 5.0)

    def test_a_silent_tail_never_becomes_a_fourth_cut(self):
        lines = script("One.", "Two.", "Three.")
        words, clock = speak([line.text for line in lines])
        result = align_script(lines, words, RATE, frames_for(clock, tail=4.0),
                              MODE_CONTINUOUS)
        self.assertTrue(result.ok, result.reasons())
        self.assertEqual(len(result.cuts), 3)

    def test_speech_in_the_tail_is_refused_not_absorbed(self):
        lines = script("Good evening from the pines.",
                       "Stay where you are.")
        words, clock = speak([lines[0].text, lines[1].text,
                              "and that is the end of the tape thank you"])
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertFalse(result.ok)
        self.assertIn("unscripted_tail", result.refusal_codes)
        tail = [r for r in result.refusals if r.code == "unscripted_tail"][0]
        self.assertEqual(tail.occurrence_id, "occ-01")
        self.assertIn("32685", tail.detail)


class NothingToAlign(unittest.TestCase):

    def test_an_empty_recognition_is_refused_and_not_treated_as_silence(self):
        lines = script("Good evening from the pines.")
        result = align_script(lines, [], RATE, RATE * 10, MODE_CONTINUOUS)
        self.assertFalse(result.ok)
        self.assertEqual(result.refusal_codes, ("no_recognition",))
        self.assertEqual(result.cuts, ())

    def test_silence_only_input_is_refused(self):
        """Timestamps over a silent master. Every "word" carries a time, and
        not one of them is a word - the note's point exactly."""
        lines = script("Good evening from the pines.")
        words = [RecognizedWord(token, at * 0.4, at * 0.4 + 0.3, 0.99)
                 for at, token in enumerate(["...", " ", "-", "  ", "!!"])]
        result = align_script(lines, words, RATE, RATE * 10, MODE_CONTINUOUS)
        self.assertFalse(result.ok)
        self.assertEqual(result.refusal_codes, ("silence_only",))

    def test_an_empty_script_is_refused(self):
        words, clock = speak(["anything at all"])
        result = align_script([], words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertFalse(result.ok)
        self.assertIn("empty_script", result.refusal_codes)


class TimestampsAreNotProof(unittest.TestCase):

    def test_a_perfectly_timed_reading_of_a_different_script_is_refused(self):
        """The sentence this module exists for: "a timestamp assigned to every
        input word does not itself prove the audio contains it." Same word
        count, same timings, same confidence - different words."""
        lines = script("Good evening from the pines.",
                       "Stay where you are.")
        words, clock = speak(["Tuesday markets closed lower again.",
                              "Rain until the weekend."])
        self.assertTrue(all(w.probability == 0.95 for w in words))
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertFalse(result.ok)
        self.assertEqual(result.refusal_codes, ("global_coverage_low",))
        self.assertEqual(result.cuts, ())

    def test_a_confident_recogniser_cannot_rescue_a_low_confidence_read(self):
        lines = script("Good evening from the pines.")
        words, clock = speak([lines[0].text], probability=0.2)
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertFalse(result.ok)
        self.assertIn("low_confidence", result.refusal_codes)

    def test_a_recogniser_with_no_probabilities_abstains_rather_than_guesses(self):
        lines = script("Good evening from the pines.")
        words, clock = speak([lines[0].text], probability=None)
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertTrue(result.ok, result.reasons())
        self.assertIsNone(result.cuts[0].verification["confidence"])


class Bounds(unittest.TestCase):

    def test_a_cut_past_the_end_of_the_master_is_refused(self):
        lines = script("Good evening from the pines.",
                       "Stay where you are.")
        words, clock = speak([line.text for line in lines])
        short = int(round(clock * RATE)) // 2
        result = align_script(lines, words, RATE, short, MODE_CONTINUOUS)
        self.assertFalse(result.ok)
        self.assertIn("bounds_outside_master", result.refusal_codes)

    def test_a_missing_sample_rate_is_refused_before_anything_else(self):
        lines = script("Good evening from the pines.")
        words, clock = speak([lines[0].text])
        result = align_script(lines, words, 0, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertFalse(result.ok)
        self.assertIn("bad_sample_rate", result.refusal_codes)

    def test_a_line_belonging_to_another_actor_is_refused(self):
        lines = [ScriptLine("occ-00", 0, "dj", "Good evening from the pines."),
                 ScriptLine("occ-01", 1, "cohost", "Stay where you are.")]
        words, clock = speak([line.text for line in lines])
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS, actor="dj")
        self.assertFalse(result.ok)
        self.assertIn("speaker_conflict", result.refusal_codes)


class Plumbing(unittest.TestCase):

    def test_every_refusal_this_module_gives_is_in_the_published_vocabulary(self):
        """A caller switches on these codes. One that is raised but not
        documented is a branch nobody can write."""
        lines = script("Good evening from the pines.", "Stay where you are.")
        cases = [
            ([], RATE, RATE * 10, MODE_CONTINUOUS),
            (speak(["zzz"])[0], RATE, RATE * 10, MODE_CONTINUOUS),
            (speak([line.text for line in lines])[0], 0, RATE * 10,
             MODE_CONTINUOUS),
        ]
        seen = set()
        for words, rate, frames, mode in cases:
            seen.update(align_script(lines, words, rate, frames,
                                     mode).refusal_codes)
        self.assertTrue(seen)
        self.assertTrue(seen <= set(REFUSAL_CODES), seen - set(REFUSAL_CODES))

    def test_whisper_and_voice_lab_word_rows_both_load(self):
        lab = [{"w": "hello", "t0": 0.0, "t1": 0.4}]
        whisper = [{"word": " hello", "start": 0.0, "end": 0.4,
                    "probability": 0.91}]
        self.assertEqual(from_whisper_words(lab)[0].word, "hello")
        self.assertEqual(from_whisper_words(whisper)[0].word, "hello")
        self.assertEqual(from_whisper_words(whisper)[0].probability, 0.91)
        # A row with no timing is dropped, never given a zero-length span.
        self.assertEqual(from_whisper_words([{"w": "x"}]), ())

    def test_normalisation_is_the_same_on_both_sides(self):
        self.assertEqual(normalize_tokens("Don't -- stop, now!"),
                         ["don't", "stop", "now"])
        self.assertEqual(normalize_tokens("twenty-four"), ["twenty", "four"])
        self.assertEqual(normalize_tokens("24"), ["twenty", "four"])
        self.assertEqual(normalize_tokens("  ...  "), [])

    def test_a_policy_fraction_outside_zero_to_one_is_rejected(self):
        with self.assertRaises(ValueError):
            AlignmentPolicy(min_coverage=1.5)

    def test_the_json_rendering_round_trips_through_a_temp_file(self):
        """Proves the result is JSON-safe for a manifest store. Writes only
        into a TemporaryDirectory - no live store is touched by this suite."""
        lines = script("Good evening from the pines.", "Stay where you are.")
        words, clock = speak([line.text for line in lines])
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS, master_hash="abc123")
        payload = result_to_json(result)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "alignment.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            back = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(back["ok"])
        self.assertEqual(len(back["cuts"]), 2)
        self.assertEqual(back["cuts"][0]["master_hash"], "abc123")
        self.assertEqual(back["cuts"][0]["mode"], MODE_CONTINUOUS)
        self.assertIn("boundary_method", back["cuts"][0])
        self.assertIn("verification", back["cuts"][0])

    def test_a_refusal_reads_as_a_sentence_naming_its_occurrence(self):
        lines = script("Good evening from the pines, where it is quiet.",
                       "The weather is doing something strange tonight.",
                       "Stay exactly where you are and do not move.")
        words, clock = speak([lines[0].text, "The weather is", lines[2].text])
        result = align_script(lines, words, RATE, frames_for(clock),
                              MODE_CONTINUOUS)
        self.assertFalse(result.ok)
        said = " ".join(result.reasons())
        self.assertIn("occurrence occ-01", said)
        self.assertIn("line 1", said)


if __name__ == "__main__":
    unittest.main()
