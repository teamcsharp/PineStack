"""[#1328] The boot sweep and the carried claim, run against the REAL code.

This does not paraphrase `airlog_boot_withdraw`; it lifts the patched
function out of app.py by name and executes it with stubs for the four
things it touches that need a station behind them.  A paraphrase would
only prove that the paraphrase agrees with itself.
"""
import ast
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from playout_sequencer import LinearSequencer, MODE_LINEAR

HERE = Path(__file__).resolve().parent
APP = HERE.parent / "app.py"
CACHE = HERE / "__pycache__" / "_sweep_src.py"


def sweep_source() -> str:
    """The patched `airlog_boot_withdraw`, verbatim, cached (app.py is 11 MB)."""
    if CACHE.exists() and CACHE.stat().st_mtime > APP.stat().st_mtime:
        return CACHE.read_text(encoding="utf-8")
    text = APP.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "airlog_boot_withdraw":
            src = "".join(lines[node.lineno - 1:node.end_lineno])
            CACHE.parent.mkdir(exist_ok=True)
            CACHE.write_text(src, encoding="utf-8")
            return src
    raise AssertionError("airlog_boot_withdraw not found in app.py")


class Clock:
    def __init__(self, at=None):
        self.at = float(at if at is not None else time.time())

    def __call__(self):
        return self.at

    def move(self, seconds):
        self.at += float(seconds)


class BootSweepHandshakeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.book = self.root / "state.json"
        self.clock = Clock()
        self.written_rows = []
        self.withdrawn = []
        self.notes = []
        self.seq = None

    def build_sweep(self, seq):
        ns = {
            "os": os, "time": time, "Any": Any,
            "airlog_write_rows": self.written_rows.extend,
            "withdrawn_book_write": self.withdrawn.append,
            "pipeline_log": lambda *a, **k: self.notes.append(a),
            "playout_tell": (lambda method, *a, **k: getattr(seq, method)(*a, **k)),
        }
        exec(compile(sweep_source(), "app.py:airlog_boot_withdraw", "exec"), ns)
        return ns["airlog_boot_withdraw"]

    def sequencer(self, **kw):
        # snap_force_every_s=0: the clock is frozen here, so the burst floor
        # would coalesce two holds a millisecond apart into one written row.
        return LinearSequencer(clock=self.clock, mode_reader=lambda: MODE_LINEAR,
                               state_path=self.book, snap_every_s=0.0,
                               snap_force_every_s=0.0, **kw)

    # ------------------------------------------------------------------ tests

    def test_the_sweep_names_the_round_the_sequencer_was_carrying(self):
        # The player that died: a round rendered, committed, waiting its turn.
        dying = self.sequencer()
        dying.hold("sid:r1", block=14856, ord0=0, seconds=46.1, lines=11,
                   road="gallery", kind="round", sid="r1",
                   media="/media/round-r1.wav", occurrence="occ-r1",
                   cues=11, audio_ready=True)
        self.clock.move(157)

        # The next player: the sequencer restores the claim, the sweep decides.
        seq = self.sequencer()
        self.assertEqual(len(seq.carried()), 1)
        sweep = self.build_sweep(seq)

        rows = {"L1": {"id": "L1", "sid": "r1", "aired": "prepared",
                       "kind": "round", "text": "hello", "seconds": 4.0,
                       "air_at": 123.0},
                "L2": {"id": "L2", "sid": "r1", "aired": "prepared",
                       "kind": "round", "text": "there", "seconds": 5.0}}
        n = sweep(rows)

        self.assertEqual(n, 2)
        self.assertEqual(rows["L1"]["aired"], "withdrawn")
        self.assertNotIn("air_at", rows["L1"])          # #1218: it never aired
        self.assertEqual(len(self.withdrawn), 1)
        book = self.withdrawn[0]
        self.assertEqual(book["sid"], "r1")
        # ...and the sequencer's evidence rode along with it.
        self.assertIn("playout", book)
        got = book["playout"]
        self.assertEqual(got["key"], "sid:r1")
        self.assertEqual(got["block"], 14856)
        self.assertEqual(got["road"], "gallery")
        self.assertEqual(got["media_path"], "/media/round-r1.wav")
        self.assertEqual(got["cues"], 11)
        self.assertTrue(got["audio_ready"])
        self.assertGreaterEqual(got["carried_age_s"], 157.0)
        self.assertEqual(got["blockers"], [])
        self.assertTrue(got["needs"])
        self.assertIn("rendered and waiting its turn", got["why"])

    def test_the_sweep_answers_the_claim_so_the_two_books_agree(self):
        dying = self.sequencer()
        dying.hold("sid:r1", block=14856, seconds=46.1, sid="r1",
                   media="/media/r1.wav", audio_ready=True)
        seq = self.sequencer()
        self.assertEqual(len(seq.carried()), 1)

        sweep = self.build_sweep(seq)
        sweep({"L1": {"id": "L1", "sid": "r1", "aired": "prepared"}})

        # Withdrawn in the book AND forgotten in the sequencer.
        self.assertEqual(seq.carried(), [])
        self.assertIsNone(seq.head())
        self.assertEqual(int(seq.state()["counts"]["forgotten"]), 1)

    def test_a_round_the_sweep_never_saw_keeps_its_claim(self):
        dying = self.sequencer()
        dying.hold("sid:r1", block=1, seconds=10, sid="r1",
                   media="/m/r1.wav", audio_ready=True)
        dying.hold("sid:r2", block=2, seconds=10, sid="r2",
                   media="/m/r2.wav", audio_ready=True)
        seq = self.sequencer()
        sweep = self.build_sweep(seq)
        sweep({"L1": {"id": "L1", "sid": "r1", "aired": "prepared"}})
        self.assertEqual([c["key"] for c in seq.carried()], ["sid:r2"])

    def test_a_row_that_reached_a_transport_is_never_touched(self):
        """`published`, `stream`, `both`, `box`, `held` already went out."""
        seq = self.sequencer()
        sweep = self.build_sweep(seq)
        rows = {aired: {"id": aired, "sid": "s-" + aired, "aired": aired}
                for aired in ("published", "stream", "both", "box", "held",
                              "withdrawn", "airing")}
        self.assertEqual(sweep(rows), 0)
        self.assertEqual(self.withdrawn, [])
        for aired, row in rows.items():
            self.assertEqual(row["aired"], aired)

    def test_the_sweep_runs_with_no_sequencer_at_all(self):
        """`playout()` is allowed to answer None; the sweep predates the book."""
        ns_seq = None

        def tell(method, *a, **k):
            return None

        ns = {"os": os, "time": time, "Any": Any,
              "airlog_write_rows": self.written_rows.extend,
              "withdrawn_book_write": self.withdrawn.append,
              "pipeline_log": lambda *a, **k: None,
              "playout_tell": tell}
        exec(compile(sweep_source(), "app.py", "exec"), ns)
        n = ns["airlog_boot_withdraw"]({"L1": {"id": "L1", "sid": "r1",
                                               "aired": "prepared"}})
        self.assertEqual(n, 1)
        self.assertEqual(len(self.withdrawn), 1)
        self.assertNotIn("playout", self.withdrawn[0])
        self.assertIsNone(ns_seq)

    def test_a_sequencer_that_throws_never_stops_the_sweep(self):
        class Angry:
            def carried(self, *a, **k):
                raise RuntimeError("the book is on fire")

            def forget(self, *a, **k):
                raise RuntimeError("still on fire")

        sweep = self.build_sweep(Angry())
        n = sweep({"L1": {"id": "L1", "sid": "r1", "aired": "prepared"}})
        self.assertEqual(n, 1)
        self.assertEqual(len(self.withdrawn), 1)

    def test_the_switch_still_turns_the_whole_sweep_off(self):
        seq = self.sequencer()
        sweep = self.build_sweep(seq)
        os.environ["PINE_BOOT_WITHDRAW"] = "0"
        try:
            self.assertEqual(
                sweep({"L1": {"id": "L1", "sid": "r1", "aired": "prepared"}}), 0)
        finally:
            os.environ.pop("PINE_BOOT_WITHDRAW", None)
        self.assertEqual(self.withdrawn, [])

    def test_the_withdrawal_book_row_is_still_json(self):
        dying = self.sequencer()
        dying.hold("sid:r1", block=7, seconds=12.5, sid="r1",
                   media="/m/r1.wav", audio_ready=True)
        seq = self.sequencer()
        sweep = self.build_sweep(seq)
        sweep({"L1": {"id": "L1", "sid": "r1", "aired": "prepared",
                      "text": "a line", "seconds": 4.0}})
        json.dumps(self.withdrawn[0])          # the book is a jsonl file


if __name__ == "__main__":
    unittest.main()
