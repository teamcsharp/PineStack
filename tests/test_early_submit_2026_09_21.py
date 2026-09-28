"""Every producer that puts audio on the air commits it FIRST.

This one reads `app.py` as text rather than importing it - importing it
starts a radio station - and asks, of each producer the observe-mode census
named, one question: does the commitment come before the transport?

    "Playback must not write, record, choose a replacement, or reconstruct
     the line sequence as it airs."
    - docs/notes/speaker-recording-and-script-assembly.md, section 4

An ordering that reads correctly today and is quietly reversed by a later
edit is the exact failure the gate exists to stop, so it is a test rather
than a comment.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
PATCH = ROOT / "tools" / "_admission_early_submit_patch.py"

# producer -> how its function starts. Every one of these was named by the
# census in `data/broadcast_admission/ledger.jsonl` as dispatching audio the
# gate had never been told about.
PRODUCERS = {
    "_dj_speak_floorless": "async def _dj_speak_floorless(",
    "dj_sting": "async def dj_sting(",
    "dj_sfx_play": "async def dj_sfx_play(",
    "sfx_video_cue_api": "async def sfx_video_cue_api(",
    "_air_produced_ad": "async def _air_produced_ad(",
    "dj_upstairs_page": "async def dj_upstairs_page(",
    "page_recovery_start": "async def page_recovery_start(",
}

TRANSPORTS = ("page_feed_append(", "_play_on_box(")

# HOW A PRODUCER COMMITS. Directly - `admission_admit_line(...)` - or, since
# 8252333 ("Stabilize perpetual broadcast"), off the event loop:
# `await asyncio.to_thread(admission_admit_line, ...)`. The gate's ledger
# write is disk work, so every named producer moved its commit into a worker
# thread (test_runtime_singleflight's admission test pins that half). A
# to_thread that is not AWAITED would be a commit that never runs, so the
# await is part of the pattern, not decoration.
COMMIT = re.compile(
    r"admission_admit_(?:line|round)\(|"
    r"await\s+asyncio\.to_thread\(\s*admission_admit_(?:line|round)\s*,")


def body_of(text, opener):
    """The source of one top-level function, from its `def` to the next."""
    start = text.index(opener)
    after = text.find("\ndef ", start + 1)
    after_async = text.find("\nasync def ", start + 1)
    ends = [n for n in (after, after_async) if n > 0]
    return text[start:min(ends)] if ends else text[start:]


def first(text, needles):
    found = [text.index(n) for n in needles if n in text]
    return min(found) if found else -1


def first_commit(text):
    got = COMMIT.search(text)
    return got.start() if got else -1


class EarlySubmitTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not APP.is_file():
            raise unittest.SkipTest("no app.py beside this test")
        cls.text = APP.read_text(encoding="utf-8", errors="replace")
        if "def admission_admit_line(" not in cls.text:
            raise unittest.SkipTest("the admission patches are not applied")

    def test_every_named_producer_commits_before_it_dispatches(self):
        for producer, opener in PRODUCERS.items():
            with self.subTest(producer=producer):
                body = body_of(self.text, opener)
                admit = first_commit(body)
                sends = first(body, TRANSPORTS)
                self.assertNotEqual(admit, -1,
                                    "%s never commits anything" % producer)
                self.assertNotEqual(sends, -1,
                                    "%s no longer dispatches - check this "
                                    "test, not the code" % producer)
                self.assertLess(admit, sends,
                                "%s dispatches before it commits" % producer)

    def test_the_roads_that_can_air_nothing_withdraw(self):
        """A committed occurrence that never airs stands in front of every
        line behind it once ordering is enforced. Each of these roads can
        decide, after committing, that nothing will carry the audio."""
        for producer in ("dj_sting", "_air_produced_ad",
                         "_dj_speak_floorless"):
            with self.subTest(producer=producer):
                body = body_of(self.text, PRODUCERS[producer])
                self.assertIn("admission_withdraw(", body)

    def test_a_live_burst_nobody_carried_gives_its_commitment_back(self):
        """#1341. A live burst of 20 lines stood admitted for thirteen
        minutes with all twenty feed rows still reading `prepared`, and
        every out-of-order refusal in that window named it: the commitment
        comes back whichever kind of round it was.

        #1300 (c3b22e0) then took the `ready_takes is not None` gate off the
        FEED withdrawal as well - a live round's rows are appended `prepared`
        exactly like a prepared round's, so the gate was abandoning them, not
        protecting them. What stays gated is the `return []`, so a live
        conversation still runs into its next burst (#767)."""
        burst = body_of(self.text, "async def _speak_turns_floorless(")
        plain = "if not (page_delivery or (to_box and played_ok)):"
        gated = ("if ready_takes is not None and not (page_delivery or "
                 "(to_box and played_ok)):")
        # #1300: the prepared-only gate on the feed rows must not come back.
        self.assertNotIn(gated, burst)
        first = burst.index(plain)
        second = burst.index(plain, first + len(plain))
        # the commitment, for every kind of round (#1341)
        self.assertIn("admission_withdraw(", burst[first:second])
        # ...and the feed rows, for every kind of round (#1300), with only
        # the early return still reserved to a prepared round
        door = burst[second:second + 700]
        rows = door.index("_burst_withdraw(")
        gate = door.index("if ready_takes is not None:")
        self.assertLess(rows, gate)
        self.assertLess(gate, door.index("return []"))

    def test_a_refused_burst_is_withdrawn_from_the_committed_sequence(self):
        """#1340. The burst road commits the whole round and then has five
        separate ways to refuse it at hand-over; 674 occurrences stood
        admitted and undispatched because none of them said so."""
        body = body_of(self.text, "def _burst_withdraw(")
        self.assertIn("admission_withdraw(", body)
        self.assertIn("admission_occurrence", body)
        burst = body_of(self.text, "async def _speak_turns_floorless(")
        self.assertIn('_e4["admission_occurrence"] = _round_occurrence',
                      burst)

    def test_a_withdrawal_names_a_reason(self):
        for producer in ("dj_sting", "_air_produced_ad",
                         "_dj_speak_floorless"):
            body = body_of(self.text, PRODUCERS[producer])
            for call in re.findall(r"admission_withdraw\((.{0,160})",
                                   body, re.S):
                self.assertIn('"', call,
                              "%s withdraws without saying why" % producer)

    def test_a_preserved_delivery_must_still_have_its_audio(self):
        """#1342. /media is pruned, so a preserved page delivery can
        outlive its own file. This station's FIFO held exactly one row -
        /media/test.wav, a fixture whose file has never existed - replayed
        on every restart since the ledger begins, and it was the last thing
        standing between the speech lane and clean enforcement.

        The gate's own resolver is the test, so what can be replayed and
        what the gate can name cannot disagree."""
        body = body_of(self.text, "def page_recovery_read(")
        self.assertIn("_admission_resolve(", body)

    def test_the_resolver_knows_every_route_a_producer_uses(self):
        """A producer that commits audio the gate cannot NAME is refused at
        `verify`, which is where 4,991 admissions died. Each of these route
        prefixes appears in a committed path above, so each must appear in
        the resolver."""
        resolver = body_of(self.text, "def _admission_resolve(")
        for route in ("/sfx/", "/ads-audio/", "/upstairs-audio/"):
            self.assertIn(route, resolver, route)

    def test_the_resolver_stays_off_the_share_walk(self):
        resolver = body_of(self.text, "def _admission_resolve(")
        code = " | ".join(line.split("#", 1)[0]
                          for line in resolver.splitlines())
        self.assertNotIn("sfx_by_id", code)
        self.assertNotIn("sfx_all(", code)
        self.assertNotIn("sfx_id_map", code)

    def test_committing_never_stops_the_air(self):
        """`admission_admit_line` returns "" on every refusal, and no caller
        may treat that as a reason not to broadcast. The statement that
        commits is read whichever way it is written - a direct call, or the
        line that opens `await asyncio.to_thread(admission_admit_line, ...)`
        - and every producer has at least one, so this cannot pass by
        finding nothing to read."""
        statement = re.compile(
            r"^([^\n]*)(?:admission_admit_line\(|"
            r"asyncio\.to_thread\(\s*admission_admit_line\s*,)", re.M)
        for producer, opener in PRODUCERS.items():
            body = body_of(self.text, opener)
            opened = [m.group(1) for m in statement.finditer(body)]
            self.assertTrue(opened, "%s: no commit statement found" % producer)
            for line in opened:
                bare = line.strip()
                self.assertFalse(
                    bare.startswith(("if ", "while ", "assert ",
                                     "return ", "raise ")),
                    "%s: %s" % (producer, bare))


class PatchShapeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not PATCH.is_file():
            raise unittest.SkipTest("no early-submit patch beside this test")
        import importlib.util
        spec = importlib.util.spec_from_file_location("_early_patch", PATCH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.patch = module

    def test_every_anchor_survives_into_its_replacement(self):
        """Nothing here replaces existing behaviour; it all inserts above
        it. A round that the gate refuses airs exactly as it does today."""
        for name, anchor, new in self.patch.EDITS:
            for line in anchor.strip().splitlines():
                self.assertIn(line.strip(), new, "%s: %s" % (name, line))

    def test_it_refuses_to_run_before_the_helper_exists(self):
        self.assertEqual(self.patch.NEEDS, "def admission_admit_line(")

    def test_nothing_here_enforces_anything(self):
        for name, _anchor, new in self.patch.EDITS:
            code = " | ".join(line.split("#", 1)[0]
                              for line in new.splitlines())
            for forbidden in ("_ADMISSION_MODE_FILE", ".mode =",
                              "enforce_lanes", "enforce_order"):
                self.assertNotIn(forbidden, code, "%s: %s" % (name, forbidden))


if __name__ == "__main__":
    unittest.main()
