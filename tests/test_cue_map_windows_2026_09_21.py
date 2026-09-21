"""The measured cue map on air: the three helpers `tools/_cue_map_windows_patch.py`
inserts into `app.py`, executed.

`app.py` is 10 MB and importing it starts a radio station, so what is
executed here is the exact source text the patch inserts, in a namespace
holding stand-ins for the two app.py globals it touches. A typo in the patch
fails here rather than on air.

The acceptance line these tests exist for is the note's own:

    "The final cue sequence must equal the frozen script sequence."

and its companion, that a map which does not describe the file that was
actually built is refused WHOLE rather than half-used.
"""
import importlib.util
import random
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "tools" / "_cue_map_windows_patch.py"
RATE = 24000
LATENCY = 120                       # frames; the limiter's measured lookahead


def load_patch():
    spec = importlib.util.spec_from_file_location("_cue_map_patch", PATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def helpers():
    """The inserted helper text, executed in a stand-in namespace."""
    patch = load_patch()
    source = patch.HELPERS_NEW
    end = source.index("# --- the measured cue map, on air (#1337) --- end")
    space = {
        "Any": Any,
        # app.py's own: count-1 drawn beats and a zero for the last clip.
        "concat_beats": lambda count: (
            [round(random.uniform(0.18, 0.42), 3)
             for _ in range(max(0, count - 1))] + [0.0]),
    }
    exec(compile(source[:end], str(PATCH), "exec"), space)
    return space


def a_cue_map(spans, *, pauses=None, rate=RATE, latency=LATENCY,
              derivation="measured", beats=None):
    """A cue map shaped exactly like `conversation_assembly` emits one.

    `spans` is one speech length in frames per line; `pauses` the seam after
    each. Positions are integer prefix sums from the measured latency, which
    is how the real assembler builds them."""
    pauses = list(pauses if pauses is not None else [0] * len(spans))
    cues, offset, body = [], latency, 0
    for index, span in enumerate(spans):
        pause = int(pauses[index])
        speech_end = offset + int(span)
        cue_end = speech_end + pause
        cues.append({
            "occurrence_id": "occ-%d" % index, "ordinal": index + 1,
            "kind": "line", "speaker": "dj", "text": "line %d" % index,
            "start_sample": offset, "speech_end_sample": speech_end,
            "cue_end_sample": cue_end, "pause_frames": pause,
            "start_seconds": round(offset / rate, 6),
            "speech_end_seconds": round(speech_end / rate, 6),
            "cue_end_seconds": round(cue_end / rate, 6),
            "pause_seconds": round(pause / rate, 6), "exact": True})
        body += int(span) + pause
        offset = cue_end
    return {"cue_map_revision": 1, "derivation": derivation,
            "sample_rate": rate, "mix_latency_frames": latency,
            "latency_measured": True, "mix_residual_frames": 0,
            "body_frames": body, "tail_pad_frames": int(rate * 0.9),
            "frame_count": body + int(rate * 0.9),
            "seconds": round((body + int(rate * 0.9)) / rate, 6),
            "cues": cues,
            "sequence": [c["occurrence_id"] for c in cues],
            "mix": {"rate": rate, "beats": list(beats if beats is not None
                                                else [p / rate for p in pauses])}}


def rows_for(count, *, ids=True):
    return [{"id": "airing-%d" % i, "who": "dj", "text": "line %d" % i,
             "from": 0.0, "until": 0.0,
             "production": ({"occurrence_id": "occ-%d" % i} if ids else {})}
            for i in range(count)]


def body_seconds(cue_map):
    return cue_map["body_frames"] / cue_map["sample_rate"]


class CueMapTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not PATCH.is_file():
            raise unittest.SkipTest("no cue-map patch beside this test")
        cls.space = helpers()

    def windows(self, *args, **kwargs):
        return self.space["production_cue_windows"](*args, **kwargs)

    # -- what counts as a map at all ------------------------------------

    def test_no_map_is_silent(self):
        """No produced round means no complaint: `why` is empty, and the
        caller keeps today's rescale without writing a line about it."""
        got, why = self.windows({}, rows_for(3), 10.0)
        self.assertIsNone(got)
        self.assertEqual(why, "")

    def test_an_estimated_map_is_not_a_map(self):
        cue_map = a_cue_map([24000, 24000], derivation="estimated")
        got, why = self.windows({"cue_map": cue_map}, rows_for(2),
                                body_seconds(cue_map))
        self.assertIsNone(got)
        self.assertEqual(why, "")

    # -- the sequence rule ----------------------------------------------

    def test_the_measured_windows_are_adopted(self):
        cue_map = a_cue_map([24000, 36000], pauses=[7200, 0])
        rows = rows_for(2)
        got, why = self.windows({"cue_map": cue_map}, rows,
                                body_seconds(cue_map))
        self.assertEqual(why, "")
        self.assertEqual(len(got), 2)
        # Line one starts at the measured latency, not at zero.
        self.assertAlmostEqual(got[0]["from"], LATENCY / RATE, 6)
        # ...and line two starts where line one's PAUSE ends, not where its
        # speech ended: an inserted pause belongs to the line before it.
        self.assertAlmostEqual(got[0]["speech_end_s"],
                               (LATENCY + 24000) / RATE, 6)
        self.assertAlmostEqual(got[0]["until"],
                               (LATENCY + 24000 + 7200) / RATE, 6)
        self.assertAlmostEqual(got[1]["from"], got[0]["until"], 6)
        self.assertAlmostEqual(got[0]["clip_tail"], 7200 / RATE, 6)

    def test_a_ring_moves_the_whole_timeline(self):
        """A call opens with a ring that is in the file and not in the map."""
        cue_map = a_cue_map([24000, 24000])
        got, _why = self.windows({"cue_map": cue_map}, rows_for(2),
                                 body_seconds(cue_map), 3.5)
        self.assertAlmostEqual(got[0]["from"], 3.5 + LATENCY / RATE, 6)

    def test_a_row_without_a_frozen_id_refuses(self):
        cue_map = a_cue_map([24000, 24000])
        rows = rows_for(2)
        rows[1]["production"] = {}
        got, why = self.windows({"cue_map": cue_map}, rows,
                                body_seconds(cue_map))
        self.assertIsNone(got)
        self.assertIn("no frozen occurrence id", why)

    def test_the_wrong_order_refuses(self):
        """#1330: two lists of the same shape, wrongly paired."""
        cue_map = a_cue_map([24000, 36000])
        rows = rows_for(2)
        rows.reverse()
        got, why = self.windows({"cue_map": cue_map}, rows,
                                body_seconds(cue_map))
        self.assertIsNone(got)
        self.assertIn("sequence", why)

    def test_a_missing_line_refuses(self):
        cue_map = a_cue_map([24000, 24000, 24000])
        got, why = self.windows({"cue_map": cue_map}, rows_for(2),
                                body_seconds(cue_map))
        self.assertIsNone(got)
        self.assertIn("sequence", why)

    def test_an_extra_line_refuses(self):
        cue_map = a_cue_map([24000, 24000])
        got, why = self.windows({"cue_map": cue_map}, rows_for(3),
                                body_seconds(cue_map))
        self.assertIsNone(got)
        self.assertIn("sequence", why)

    def test_a_duplicate_occurrence_refuses(self):
        """Two occurrences of identical words are different cues; two ROWS
        claiming one occurrence is not a sequence."""
        cue_map = a_cue_map([24000, 24000])
        rows = rows_for(2)
        rows[1]["production"] = {"occurrence_id": "occ-0"}
        got, why = self.windows({"cue_map": cue_map}, rows,
                                body_seconds(cue_map))
        self.assertIsNone(got)
        self.assertIn("sequence", why)

    # -- the body rule ---------------------------------------------------

    def test_a_body_that_does_not_match_refuses(self):
        """The mixer built a different file from the one that was measured -
        a sting welded in, a clip re-rendered. The map describes neither
        half of it, so none of it is used."""
        cue_map = a_cue_map([24000, 24000])
        got, why = self.windows({"cue_map": cue_map}, rows_for(2),
                                body_seconds(cue_map) + 0.4)
        self.assertIsNone(got)
        self.assertIn("the map's body is", why)

    def test_the_loudness_residual_is_inside_the_tolerance(self):
        """+/-3 frames is what the loudness pass leaves; 0.03 s is 720."""
        cue_map = a_cue_map([24000, 24000])
        got, why = self.windows({"cue_map": cue_map}, rows_for(2),
                                body_seconds(cue_map) + 3 / RATE)
        self.assertEqual(why, "")
        self.assertEqual(len(got), 2)

    def test_a_map_without_a_body_refuses(self):
        cue_map = a_cue_map([24000, 24000])
        cue_map["body_frames"] = 0
        got, why = self.windows({"cue_map": cue_map}, rows_for(2), 2.0)
        self.assertIsNone(got)
        self.assertIn("how long its body is", why)

    def test_a_broken_map_never_raises(self):
        """A cue map must never be the reason a round fails to air."""
        got, why = self.windows({"cue_map": {"derivation": "measured",
                                             "cues": [{"occurrence_id": "occ-0"}],
                                             "sequence": ["occ-0"],
                                             "sample_rate": "not a number",
                                             "body_frames": 24000}},
                                rows_for(1), 1.0)
        self.assertIsNone(got)
        self.assertTrue(why)

    # -- the beats -------------------------------------------------------

    def test_the_beats_are_the_measured_ones(self):
        """#778 one step earlier: the mixer and the timeline must be built
        out of the same numbers."""
        cue_map = a_cue_map([24000, 24000, 24000], beats=[0.31, 0.22, 0.0])
        got = self.space["production_cue_beats"](
            {"cue_map": cue_map}, [0, 1, 2], 3)
        self.assertEqual(got, [0.31, 0.22, 0.0])

    def test_a_ring_and_a_hang_up_keep_their_drawn_beats(self):
        """`seg` is [ring] + turns + [hang-up]; only the turns are in the
        map, and the rest keep the beat they were drawn."""
        cue_map = a_cue_map([24000, 24000], beats=[0.31, 0.0])
        got = self.space["production_cue_beats"](
            {"cue_map": cue_map}, [1, 2], 4)
        self.assertEqual(len(got), 4)
        self.assertEqual(got[1], 0.31)
        self.assertEqual(got[2], 0.0)
        self.assertNotEqual(got[0], 0.31)      # the ring's own beat, drawn

    def test_no_map_draws_them_fresh(self):
        self.assertIsNone(self.space["production_cue_beats"]({}, [0, 1], 2))


class PatchShapeTests(unittest.TestCase):
    """The edits the patch makes to the burst road, as text."""

    @classmethod
    def setUpClass(cls):
        if not PATCH.is_file():
            raise unittest.SkipTest("no cue-map patch beside this test")
        cls.patch = load_patch()

    def test_the_rescale_is_guarded_by_the_adoption(self):
        """Both the windows and the download's cut point stop being scaled
        when the windows came off a measured map."""
        self.assertIn("if rows and not _cue_exact and _ours > 0.5",
                      self.patch.ADOPT_NEW)
        self.assertIn("if (rows and not _cue_exact", self.patch.TAIL_NEW)

    def test_the_fallback_is_the_untouched_original(self):
        """A round that does not prove out airs on exactly today's code, so
        every line of every anchor has to survive into its replacement -
        except the two conditions that deliberately gain the guard, and the
        beat draw that becomes the fallback of an `or`."""
        REWRITTEN = {
            "beats = concat_beats(len(seg))": "or concat_beats(len(seg))",
            "if rows and _ours > 0.5 and _made > 0.5:":
                "if rows and not _cue_exact and _ours > 0.5 and _made > 0.5:",
            "if (rows and _ours > 0.5 and _made > 0.5)":
                "if (rows and not _cue_exact",
        }
        for name, anchor, new_text in self.patch.EDITS:
            if name == "the cue-map helpers":
                # Pure insertion: the anchor is the line it is inserted
                # above, and it must still be the last thing in the block.
                self.assertTrue(new_text.endswith(anchor), name)
                continue
            for line in anchor.strip().splitlines():
                bare = line.strip()
                self.assertIn(REWRITTEN.get(bare, bare), new_text,
                              "%s: %s" % (name, bare))

    def test_it_says_which_guard_refused(self):
        """A refusal nobody can read is a refusal nobody can fix."""
        self.assertIn("a supplied cue map was not used", self.patch.ADOPT_NEW)
        self.assertIn("no rescale (#1337)", self.patch.ADOPT_NEW)


if __name__ == "__main__":
    unittest.main()
