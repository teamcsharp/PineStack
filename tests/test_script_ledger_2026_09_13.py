"""#1330: THE SCRIPT IS WRITTEN DOWN BEFORE IT IS HEARD.

The operator: "The script must be sequential and cannonical and scripted
with the sfx guy interjecting additional clips occasionally and
randomness."

Until this ticket there was no script document at all. `screenplay_compose`
rebuilt the hour from `air_log.jsonl` on every poll and ordered it by
`air_at` - a field eight paths rewrite - then ran four corrective passes
over the result to undo what the clock had got wrong. The tickets that
built those passes measured the cost themselves:

  #1274  "104 of 129 re-appended ids had their air_at move, median 88s
          ... reading one hour twice, 45 seconds apart, six changed
          stamps put 83 of 468 elements back in a different order."
  #1299  "of 1,055 elements, 52 run backwards in time, median 37.1s
          ... the two biggest pairs are action -> character and
          dialogue -> action. Those actions are the SFX guy."
  #1259  "air_at cannot order a script."

The cure is not a fifth pass. A round is assembled in order - the SFX
guy rolled into it at his own cadence and dial, which is where the
"occasionally, and at random" already lives - and it is welded before it
is audible. So the order is known before air, and `script_ledger_commit`
writes it down: (block, ord), assigned once, never rewritten, carrying
the same line ids the ring goes out with.

The tests worth having are the ones whose failure is SILENT:

  * An order that quietly reverts to the clock looks fine on a static
    hour and only misbehaves while the stamps are still moving - which
    is exactly the live tail the operator reads.

  * A scripted sting that drifts out of its conversation still renders;
    it just answers the wrong line, which reads as the show being
    incoherent rather than as a bug.

  * The ledger sharing an id space with `speaking_now` is the entire
    reason a panel can highlight the right line. If the ids stop
    matching, the view falls back to a text search that was already
    documented as failing on short lines and on retired rounds.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class ScriptLedgerOrder(unittest.TestCase):
    """The ledger itself: what it promises is that the order never moves."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ledger-"))
        self.patches = [
            mock.patch.object(app, "SCRIPT_LEDGER_PATH",
                              self.tmp / "script_ledger.jsonl"),
            mock.patch.object(app, "SCRIPT_LEDGER_SEQ_PATH",
                              self.tmp / "script_ledger_seq.json"),
        ]
        for p in self.patches:
            p.start()
        app._SCRIPT_LEDGER_MEMO["at"] = 0.0
        app._SCRIPT_LEDGER_MEMO["rows"] = []

    def tearDown(self):
        for p in self.patches:
            p.stop()
        app._SCRIPT_LEDGER_MEMO["at"] = 0.0
        app._SCRIPT_LEDGER_MEMO["rows"] = []

    def rows(self, prefix, n):
        return [{"line_id": f"{prefix}{i}", "who": "dj",
                 "text": f"line {i}", "seconds": 1.0, "turn": i}
                for i in range(n)]

    def test_a_round_keeps_the_order_it_was_written_in(self):
        app.script_ledger_commit("sid-one", self.rows("a", 3), "banter")
        app._SCRIPT_LEDGER_MEMO["at"] = 0.0
        got = app.script_ledger_order()
        self.assertEqual([got[f"a{i}"][1] for i in range(3)], [0, 1, 2])
        self.assertEqual({got[f"a{i}"][0] for i in range(3)}, {1})

    def test_the_sfx_guy_holds_the_slot_he_was_rolled_into(self):
        """His row is committed in place, between the turns it punctuates.

        #1299 is the failure this prevents: a sting holds no slot in the
        conversation's own permutation, so it was 'left at an absolute
        index beside whatever lands there'."""
        app.script_ledger_commit("sid-two", [
            {"line_id": "b0", "who": "dj", "text": "one", "turn": 0},
            {"line_id": "b1", "who": "drop", "text": "quip",
             "kind": "sfxguy", "turn": -1},
            {"line_id": "b2", "who": "dj", "text": "two", "turn": 1},
        ], "banter")
        app._SCRIPT_LEDGER_MEMO["at"] = 0.0
        got = app.script_ledger_order()
        self.assertEqual(got["b1"][1], 1)
        self.assertEqual(got["b0"][0], got["b1"][0], "same block")

    def test_a_lost_counter_never_reissues_a_block(self):
        """A reused block number would file a new round in front of an old
        one, which is the single thing this file must never do."""
        app.script_ledger_commit("one", self.rows("a", 2), "banter")
        app.script_ledger_commit("two", self.rows("b", 2), "banter")
        app.SCRIPT_LEDGER_SEQ_PATH.unlink()
        third = app.script_ledger_commit("three", self.rows("c", 2), "ad")
        self.assertEqual(third, 3)

    def test_read_back_is_by_block_not_by_clock(self):
        """A round welded slowly can be committed after one welded later.

        The file is read by (block, ord) precisely so that a commit whose
        wall clock runs backwards cannot reorder the document."""
        app.script_ledger_commit("one", self.rows("a", 2), "banter")
        app.script_ledger_commit("two", self.rows("b", 2), "banter")
        lines = app.SCRIPT_LEDGER_PATH.read_text().splitlines()
        patched = []
        for line in lines:
            row = json.loads(line)
            if row["block"] == 2:
                row["at"] = 1.0          # older than everything before it
            patched.append(json.dumps(row))
        app.SCRIPT_LEDGER_PATH.write_text("\n".join(patched) + "\n")
        app._SCRIPT_LEDGER_MEMO["at"] = 0.0
        seq = [(r["block"], r["ord"]) for r in app.script_ledger_rows()]
        self.assertEqual(seq, sorted(seq))
        self.assertEqual([r["block"] for r in app.script_ledger_rows()][-2:],
                         [2, 2])

    def test_a_row_with_no_id_is_never_placed(self):
        """An unnamed row cannot be matched to anything on air, and a
        blank key in the order map would claim every one of them."""
        app.script_ledger_commit(
            "sid", [{"line_id": "", "who": "board", "text": "sting"}], "x")
        app._SCRIPT_LEDGER_MEMO["at"] = 0.0
        self.assertNotIn("", app.script_ledger_order())


def air(rid, at, text, who="dj", kind="banter"):
    return {"id": rid, "who": who, "kind": kind, "round": "banter",
            "text": text, "air_at": at, "ts": at, "aired": "published",
            "seconds": 2.0, "sid": "s1", "turn": 0}


class ScreenplayTakesTheLedgersWord(unittest.TestCase):
    """The merge: the ledger overrules the clock, and only where it knows."""

    def compose(self, rows, order, records=None, now=None):
        d = {"air": rows, "prov": {}, "rounds": [],
             "records": records or [], "ads": [], "calls": [],
             "memos": [], "pauses": [], "models": []}
        with mock.patch.object(app, "script_ledger_order", return_value=order):
            with mock.patch.dict(app._RADIO, {"now": now}, clear=False):
                return app.screenplay_compose(0.0, 1e12, d, [])

    def ids(self, script):
        return [e["line"] for e in script["elements"]
                if e.get("type") == "dialogue"]

    def test_written_order_beats_a_stamp_that_moved(self):
        """#1274's exact failure: heard lines re-ordered under the reader
        because their air_at was rewritten after they aired."""
        rows = [air("t0", 500.0, "first"),
                air("t1", 100.0, "second"),
                air("t2", 300.0, "third")]
        order = {"t0": (7, 0), "t1": (7, 1), "t2": (7, 2)}
        self.assertEqual(self.ids(self.compose(rows, order)),
                         ["t0", "t1", "t2"])

    def test_without_a_ledger_the_clock_still_orders_it(self):
        """The merge must be inert where it knows nothing, or every hour
        recorded before this ticket would be scrambled."""
        rows = [air("t0", 500.0, "first"),
                air("t1", 100.0, "second"),
                air("t2", 300.0, "third")]
        self.assertEqual(self.ids(self.compose(rows, {})),
                         ["t1", "t2", "t0"])

    def test_an_unledgered_line_keeps_its_clock_slot(self):
        """A rescue sting and an emergency filler are minted outside any
        round, so nothing wrote them down. They still have to land where
        they sounded - between the blocks, not after all of them."""
        rows = [air("a0", 10.0, "one"), air("a1", 11.0, "two"),
                air("resc", 15.0, "cover"),
                air("b0", 20.0, "three"), air("b1", 21.0, "four")]
        order = {"a0": (1, 0), "a1": (1, 1), "b0": (2, 0), "b1": (2, 1)}
        self.assertEqual(self.ids(self.compose(rows, order)),
                         ["a0", "a1", "resc", "b0", "b1"])


class TheRecordOnTheDeck(unittest.TestCase):
    """#1330: which record is turning, said on the entry itself."""

    def compose(self, records, now):
        d = {"air": [], "prov": {}, "rounds": [], "records": records,
             "ads": [], "calls": [], "memos": [], "pauses": [], "models": []}
        with mock.patch.object(app, "script_ledger_order", return_value={}):
            with mock.patch.dict(app._RADIO, {"now": now}, clear=False):
                return app.screenplay_compose(0.0, 1e12, d, [])

    def rec(self, rid, at):
        return {"at": at, "ends": at + 200, "title": "U", "artist": "The Greys",
                "seconds": 200.0, "length": 200.0, "id": rid, "tape": False}

    def test_the_one_on_the_deck_says_so(self):
        """Before this, a record that began forty seconds ago read exactly
        like one that finished an hour ago - which is what made a script
        that had simply not caught up look like one that skipped the
        track change."""
        script = self.compose([self.rec("r1", 10.0), self.rec("r2", 300.0)],
                              {"id": "r2"})
        texts = [e["text"] for e in script["elements"]
                 if e.get("tag") == "record"]
        self.assertTrue(any(t.startswith("A record is spinning:")
                            for t in texts), texts)
        self.assertTrue(any(t.startswith("A record drops:")
                            for t in texts), texts)

    def test_nothing_playing_marks_nothing(self):
        script = self.compose([self.rec("r1", 10.0)], None)
        marked = [e for e in script["elements"] if e.get("playing")]
        self.assertEqual(marked, [])


if __name__ == "__main__":
    unittest.main()
