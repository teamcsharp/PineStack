"""The gate can name the audio it gates, and the busiest producer commits
before it dispatches: the source `tools/_admission_reach_patch.py` inserts
into `app.py`, executed.

`app.py` is 10 MB and importing it starts a radio station, so the inserted
text runs here in a namespace holding stand-ins for the app.py globals it
touches, against a REAL `broadcast_admission.PlayoutController` writing into
a temporary directory. A typo in the patch fails here rather than on air.

What these tests are about, in one line each:

    a sting the station played must not be "audio that is not available"
    a line nobody is going to carry must not stand in the committed order
"""
import importlib.util
import re
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any

import broadcast_admission as ba

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "tools" / "_admission_reach_patch.py"
RATE = 24000


def load_patch():
    spec = importlib.util.spec_from_file_location("_reach_patch", PATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def a_wav(path: Path, seconds: float = 1.0, rate: int = RATE):
    """A real, readable wav - `audio_seconds_hint` reads its header and
    `audio_identity` hashes its bytes, and neither may be fooled here."""
    import struct
    frames = int(rate * seconds)
    data = b"\x00\x00" * frames
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data" + struct.pack("<I", len(data)) + data)
    return path


# --------------------------------------------------------------------------
# the resolver
# --------------------------------------------------------------------------

class ResolverTests(unittest.TestCase):
    """`_admission_resolve`'s new tail, as a function of its own."""

    @classmethod
    def setUpClass(cls):
        if not PATCH.is_file():
            raise unittest.SkipTest("no reach patch beside this test")
        cls.patch = load_patch()

    def setUp(self):
        self.room = Path(tempfile.mkdtemp(prefix="reach-"))
        self.media = self.room / "media"
        self.samples = self.room / "samples"
        self.levelled = self.room / "levelled"
        self.ads = self.room / "ads_audio"
        self.upstairs = self.room / "upstairs_audio"
        for each in (self.media, self.samples, self.levelled, self.ads,
                     self.upstairs):
            each.mkdir(parents=True, exist_ok=True)
        self.reverse = {}
        self.levelled_names = {}

        def sfx_levelled_name(path, vol=None):
            return self.levelled_names.get(str(path))

        body = textwrap.dedent(self.patch.RESOLVE_NEW)
        source = ("def resolve_tail(raw, key):\n"
                  + textwrap.indent(body, "    "))
        self.space = {
            "Path": Path, "re": re,
            "VOICE_MEDIA_DIR": self.media,
            "data_path": lambda name: self.room / name,
            "_SFX_ID_REVERSE": self.reverse,
            "sfx_levelled_name": sfx_levelled_name,
            "PRODUCED_ADS_DIR": self.ads,
            "UPSTAIRS_AUDIO_DIR": self.upstairs,
        }
        exec(compile(source, str(PATCH), "exec"), self.space)
        self.resolve = self.space["resolve_tail"]

    def test_a_sting_resolves_to_its_sample(self):
        sample = a_wav(self.samples / "door.wav")
        self.reverse["65d26c4e1827c8d7"] = str(sample)
        got = self.resolve("/sfx/65d26c4e1827c8d7", "65d26c4e1827c8d7")
        self.assertEqual(got, sample)

    def test_a_sting_resolves_to_what_the_box_is_handed(self):
        """`/sfx/{key}` serves the LEVELLED copy when there is one, so that
        is the file whose bytes the gate must name."""
        sample = a_wav(self.samples / "door.wav")
        level = a_wav(self.levelled / "door-v2.wav")
        self.reverse["65d26c4e1827c8d7"] = str(sample)
        self.levelled_names[str(sample)] = level
        got = self.resolve("/sfx/65d26c4e1827c8d7", "65d26c4e1827c8d7")
        self.assertEqual(got, level)

    def test_a_levelled_copy_that_is_not_made_yet_falls_back(self):
        sample = a_wav(self.samples / "door.wav")
        self.reverse["65d26c4e1827c8d7"] = str(sample)
        self.levelled_names[str(sample)] = self.levelled / "not-made.wav"
        got = self.resolve("/sfx/65d26c4e1827c8d7", "65d26c4e1827c8d7")
        self.assertEqual(got, sample)

    def test_an_unknown_sting_id_is_not_guessed_at(self):
        self.assertIsNone(
            self.resolve("/sfx/65d26c4e1827c8d7", "65d26c4e1827c8d7"))

    def test_a_deleted_sample_is_not_available(self):
        self.reverse["65d26c4e1827c8d7"] = str(self.samples / "gone.wav")
        self.assertIsNone(
            self.resolve("/sfx/65d26c4e1827c8d7", "65d26c4e1827c8d7"))

    def test_a_key_that_is_not_a_key_is_refused(self):
        self.assertIsNone(self.resolve("/sfx/../../etc/passwd", "passwd"))

    def test_a_produced_ad_resolves(self):
        made = a_wav(self.ads / "b6d77a65b358.mp3")
        self.assertEqual(
            self.resolve("/ads-audio/b6d77a65b358.mp3", "b6d77a65b358.mp3"),
            made)

    def test_an_upstairs_page_resolves(self):
        made = a_wav(self.upstairs / "page-1.mp3")
        self.assertEqual(
            self.resolve("/upstairs-audio/page-1.mp3", "page-1.mp3"), made)

    def test_a_missing_ad_is_not_available(self):
        self.assertIsNone(
            self.resolve("/ads-audio/nothing.mp3", "nothing.mp3"))

    def test_anything_else_still_ends_in_none(self):
        self.assertIsNone(self.resolve("/somewhere/else.wav", "else.wav"))


# --------------------------------------------------------------------------
# admitting one line
# --------------------------------------------------------------------------

class AdmitLineTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not PATCH.is_file():
            raise unittest.SkipTest("no reach patch beside this test")
        cls.patch = load_patch()

    def setUp(self):
        self.room = Path(tempfile.mkdtemp(prefix="reach-line-"))
        self.media = self.room / "media"
        self.media.mkdir(parents=True, exist_ok=True)
        self.logs = []
        self.controller = ba.PlayoutController.open(
            self.room / "admission",
            resolve_audio=lambda path: self._resolve(path))
        source = self.patch.ADMIT_LINE_NEW
        end = source.index("def admission_state(")
        self.space = {
            "Any": Any,
            "_admission_module": ba,
            "admission_controller": lambda: self.controller,
            "_admission_producer": lambda depth=2: "a_test",
            # app.py's own, in the part that matters here: a reply is the
            # reply lane, which the controller exempts.
            "_admission_lane": lambda path, kind="", reply=False: (
                "reply" if (reply or str(kind) == "reply")
                else "sfx" if "/sfx/" in str(path) else "speech"),
            "_admission_resolve": lambda path: self._resolve(path),
            "pipeline_log": lambda *a, **k: self.logs.append(a),
        }
        exec(compile(source[:end], str(PATCH), "exec"), self.space)
        self.admit = self.space["admission_admit_line"]
        self.withdraw = self.space["admission_withdraw"]

    def _resolve(self, path):
        raw = str(path or "").split("?")[0]
        got = self.media / raw.rsplit("/", 1)[-1]
        return got if got.is_file() else None

    def a_clip(self, name="line.wav", seconds=2.0):
        a_wav(self.media / name, seconds)
        return {"path": "/media/" + name, "sig": "s-" + name}

    # -- the plain case --------------------------------------------------

    def test_a_line_is_committed_before_it_is_dispatched(self):
        clip = self.a_clip()
        oid = self.admit(clip, who="dj", kind="banter", text="Evening.",
                         line_id="row-1", producer="_dj_speak_floorless")
        self.assertTrue(oid)
        row = self.controller.occurrence(oid)
        self.assertEqual(row["state"], "admitted")
        self.assertEqual(row["producer"], "_dj_speak_floorless")
        # One cue, covering the whole file: there is nothing inside a plain
        # line to point at, and the view must not pretend there is.
        self.assertEqual(len(row["cues"]), 1)
        self.assertAlmostEqual(row["cues"][0]["start_s"], 0.0, 3)

    def test_the_dispatch_then_finds_its_claim(self):
        """The whole point: the gate stops saying `unadmitted`."""
        clip = self.a_clip()
        self.admit(clip, who="dj", kind="banter", text="Evening.",
                   line_id="row-1", producer="_dj_speak_floorless")
        verdict = self.controller.gate(lane="speech", path=clip["path"],
                                       sig=clip["sig"],
                                       producer="_dj_speak_floorless")
        self.assertEqual(verdict.reason, "admitted")
        self.assertFalse(verdict.would_refuse)

    def test_without_it_the_gate_says_unadmitted(self):
        clip = self.a_clip()
        verdict = self.controller.gate(lane="speech", path=clip["path"],
                                       sig=clip["sig"],
                                       producer="_dj_speak_floorless")
        self.assertEqual(verdict.reason, "unadmitted")
        self.assertTrue(verdict.would_refuse)

    def test_the_length_comes_off_the_wav_header(self):
        clip = self.a_clip(seconds=3.5)
        oid = self.admit(clip, who="dj", text="A longer one.",
                         line_id="row-1")
        row = self.controller.occurrence(oid)
        self.assertAlmostEqual(row["audio"]["seconds"], 3.5, 1)
        self.assertAlmostEqual(row["cues"][0]["end_s"], 3.5, 1)

    # -- a line with a sting welded into it ------------------------------

    def test_a_welded_stream_keeps_its_own_cue_sheet(self):
        clip = self.a_clip(seconds=6.0)
        rows = [{"id": "row-1", "who": "dj", "kind": "banter",
                 "text": "Evening.", "from": 0.0, "until": 4.0,
                 "clip_tail": 0.25},
                {"id": "row-2", "who": "board", "kind": "sfx",
                 "text": "[door]", "from": 4.0, "until": 6.0}]
        oid = self.admit(clip, who="dj", kind="banter", text="Evening.",
                         line_id="row-1", rows=rows, length=6.0)
        row = self.controller.occurrence(oid)
        self.assertEqual(len(row["cues"]), 2)
        # `line_id` is the cue's own identity; `occurrence_id` on a cue is
        # the PLAYBACK occurrence the controller mints for its position.
        self.assertEqual(row["cues"][0]["line_id"], "row-1")
        self.assertEqual(row["cues"][1]["line_id"], "row-2")
        self.assertAlmostEqual(row["cues"][1]["start_s"], 4.0, 3)
        # The seam beat belongs to the line before it, not to the sting.
        self.assertAlmostEqual(row["cues"][0]["speech_end_s"], 3.75, 3)

    # -- refusing, without ever raising ----------------------------------

    def test_a_clip_whose_file_is_gone_is_refused_quietly(self):
        got = self.admit({"path": "/media/never-made.wav", "sig": "x"},
                         who="dj", text="Evening.", line_id="row-1")
        self.assertEqual(got, "")
        self.assertTrue(self.logs, "the refusal must be said out loud")

    def test_no_clip_at_all_is_not_an_error(self):
        self.assertEqual(self.admit(None, who="dj", text="x"), "")
        self.assertEqual(self.admit({}, who="dj", text="x"), "")

    def test_a_reply_is_never_committed(self):
        """AN ASSISTANT ANSWERING YOU IS NOT BROADCAST.

        #647 draws that boundary and `gate` keeps it there: the reply lane
        returns `exempt` without ever beginning or finishing the occurrence.
        So a reply committed here is a commitment nothing can consume - it
        stands `admitted` for ever, and with ordering enforced it stands in
        front of every line behind it.

        Measured on the live station within three minutes of the first
        deploy of this patch: one reply at position 37949, and every single
        dispatch after it refused as out_of_order."""
        clip = self.a_clip()
        self.assertEqual(
            self.admit(clip, who="dj", kind="reply", text="Yes, that one.",
                       line_id="row-1"), "")
        self.assertEqual(self.controller.stats()["occurrences"], 0)

    def test_the_gate_would_have_exempted_it_too(self):
        """The two answers have to agree, or the census is a fiction."""
        clip = self.a_clip()
        self.admit(clip, who="dj", kind="reply", text="Yes.", line_id="r")
        verdict = self.controller.gate(lane="reply", path=clip["path"],
                                       sig=clip["sig"], producer="p",
                                       reply=True)
        self.assertTrue(verdict.allow)
        self.assertEqual(verdict.reason, "exempt")
        self.assertFalse(verdict.would_refuse)

    def test_a_controller_that_is_off_changes_nothing(self):
        self.space["admission_controller"] = lambda: None
        self.assertEqual(self.admit(self.a_clip(), who="dj", text="x"), "")

    # -- taking it back ---------------------------------------------------

    def test_a_line_nobody_carried_is_withdrawn(self):
        clip = self.a_clip()
        oid = self.admit(clip, who="dj", text="Evening.", line_id="row-1")
        self.assertTrue(self.withdraw(oid, "neither transport carried it"))
        self.assertEqual(self.controller.occurrence(oid)["state"], "withdrawn")

    def test_a_withdrawn_line_does_not_stand_in_front_of_the_next(self):
        """The reason the withdrawal exists at all: with ordering enforced,
        a committed line that never airs blocks everything behind it."""
        first = self.a_clip("one.wav")
        second = self.a_clip("two.wav")
        held = self.admit(first, who="dj", text="One.", line_id="row-1")
        self.admit(second, who="dj", text="Two.", line_id="row-2")
        self.controller.mode = "enforce"
        self.controller.enforce_order = True
        blocked = self.controller.gate(lane="speech", path=second["path"],
                                       sig=second["sig"], producer="p")
        self.assertFalse(blocked.allow)
        self.assertEqual(blocked.reason, "out_of_order")
        self.withdraw(held, "neither transport carried the line")
        freed = self.controller.gate(lane="speech", path=second["path"],
                                     sig=second["sig"], producer="p")
        self.assertTrue(freed.allow)
        self.assertEqual(freed.reason, "admitted")

    def test_withdrawing_what_is_already_gone_is_not_an_error(self):
        self.assertFalse(self.withdraw("", "no reason"))
        self.assertFalse(self.withdraw("nothing-like-this", "no reason"))

    def test_a_dispatched_line_cannot_be_withdrawn(self):
        """It is on the air. The script may not pretend otherwise."""
        clip = self.a_clip()
        oid = self.admit(clip, who="dj", text="Evening.", line_id="row-1")
        self.controller.gate(lane="speech", path=clip["path"],
                             sig=clip["sig"], producer="p")
        self.assertFalse(self.withdraw(oid, "too late"))


# --------------------------------------------------------------------------
# the shape of the edits themselves
# --------------------------------------------------------------------------

class PatchShapeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not PATCH.is_file():
            raise unittest.SkipTest("no reach patch beside this test")
        cls.patch = load_patch()

    @staticmethod
    def code(text):
        """The text with its comments taken off - the prose in this patch
        names the very calls these tests forbid."""
        return " | ".join(line.split("#", 1)[0]
                          for line in text.splitlines())

    def test_the_resolver_never_walks_the_share(self):
        """`sfx_by_id` ends in a walk of the CIFS share on a miss, and this
        code runs on the event loop."""
        self.assertNotIn("sfx_by_id", self.code(self.patch.RESOLVE_NEW))
        self.assertIn("_SFX_ID_REVERSE", self.patch.RESOLVE_NEW)

    def test_the_resolver_never_makes_a_levelled_copy(self):
        self.assertNotIn("sfx_levelled(", self.code(self.patch.RESOLVE_NEW))
        self.assertIn("sfx_levelled_name(", self.patch.RESOLVE_NEW)

    def test_the_level_name_has_one_spelling(self):
        """#1420: the levels must not live in two places."""
        self.assertIn("out = sfx_levelled_name(path, vol)",
                      self.patch.LEVELNAME_NEW)
        self.assertNotIn("SFX_LEVELLED /", self.patch.LEVELNAME_NEW)

    def test_the_admit_is_above_both_transports(self):
        """It has to be, or it is not a commitment - it is a receipt."""
        self.assertIn("_line_occurrence = admission_admit_line(",
                      self.patch.PAGED_NEW)
        self.assertTrue(self.patch.PAGED_NEW.rstrip().endswith(
            "if page_carries_live(voice_to, to_box, box_down):          # #1118"))

    def test_the_withdrawal_only_fires_when_nothing_carried_it(self):
        self.assertIn("if _line_occurrence and not paged and not to_box:",
                      self.patch.WITHDRAW_NEW)

    def test_nothing_here_touches_the_mode_file(self):
        """This patch measures; it does not enforce."""
        for name, _anchor, new_text in self.patch.EDITS:
            code = self.code(new_text)
            for forbidden in ("_ADMISSION_MODE_FILE", ".mode =",
                              "enforce_lanes", "enforce_order",
                              "write_text", "write_bytes"):
                self.assertNotIn(forbidden, code, "%s: %s" % (name, forbidden))


if __name__ == "__main__":
    unittest.main()
