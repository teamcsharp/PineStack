"""tools/script_watch.py - the Script view watcher's reading and its verdict.

Pure: no station, no data directory. Run:
    PYTHONPATH=tests:.:tools python3 -m unittest tests.test_script_watch
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import script_watch as sw  # noqa: E402

T0 = 1790690000.0
SEG_A = {"occurrence": "h:hour-05", "label": "Banter", "start": T0, "deadline": T0 + 240, "state": "aired"}
SEG_B = {"occurrence": "h:hour-06", "label": "Call", "start": T0 + 240, "deadline": T0 + 480, "state": "on air"}


def led(block, ord_, lid, at, seg="h:hour-05", kind="dialogue", scripted=True, turn_id=None):
    return {"k": "ledger", "t": at + 0.5, "b": {
        "block": block, "ord": ord_, "at": at, "line_id": lid, "sid": "s", "who": "dj", "kind": kind,
        "turn": ord_, "round": "banter", "scripted": scripted, "cue": "", "seg": seg, "seg_label": "Banter",
        "seg_kind": "banter", "seg_start": T0, "seg_ends": T0 + 240, "conv": "c1" if turn_id else None,
        "turn_id": turn_id, "replay": None, "text": "words %s" % lid}}


def heard(lid, at, kind="dialogue"):
    return {"k": "air", "t": at + 1, "b": {"id": lid, "aired": "stream", "air_at": at, "heard": at, "by": "page",
                                          "kind": kind, "who": "dj", "sid": "s", "turn": 0, "round": "banter",
                                          "rtk": "", "text": "w"}}


def recording(*events):
    return [{"k": "start", "t": T0, "b": {}}, {"k": "director", "t": T0, "b": {"entries": [SEG_A, SEG_B]}}] \
        + list(events) + [{"k": "end", "t": T0 + 470, "b": {}}]


class Tail(unittest.TestCase):
    def test_a_rewrite_in_place_and_a_partial_line_lose_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "script_ledger.jsonl"
            rows = [{"block": 1, "ord": i, "line_id": "a%d" % i} for i in range(3)]
            path.write_text("".join(json.dumps(r) + "\n" for r in rows))
            tail = sw.Tail(path, back=10_000)
            self.assertEqual(len(tail.read()), 3)
            with open(path, "a") as fh:                       # a write caught half way
                fh.write(json.dumps({"block": 2, "ord": 0, "line_id": "b0"}) + "\n" + '{"block": 2, "o')
            self.assertEqual([r["line_id"] for r in tail.read()], ["b0"])
            # the hourly prune: the whole file written again, with the rest of block 2 on the end
            body = "".join(json.dumps(r) + "\n" for r in rows)
            body += "".join(json.dumps({"block": 2, "ord": i, "line_id": "b%d" % i}) + "\n" for i in range(3))
            path.write_text(body)
            self.assertEqual([r["line_id"] for r in tail.read()], ["b1", "b2"])


class Verdict(unittest.TestCase):
    def test_air_rows_fold_into_their_furthest_state(self):
        a = sw.air_merge(None, {"id": "x", "aired": "published", "air_at": 5.0, "heard": None})
        a = sw.air_merge(a, {"id": "x", "aired": "stream", "air_at": 7.0, "heard": 7.0})
        a = sw.air_merge(a, {"id": "x", "aired": "published", "air_at": 5.0, "heard": None})
        self.assertEqual((a["aired"], a["air_at"], a["heard"]), ("stream", 7.0, 7.0))

    def test_one_early_line_is_one_out_of_place_not_a_cascade(self):
        ev = recording(led(10, 0, "a", T0 + 1), led(11, 0, "b", T0 + 2), led(12, 0, "c", T0 + 3),
                       led(13, 0, "sting", T0 + 25, kind="sfx", scripted=False),
                       heard("sting", T0 + 19, "sfx"), heard("a", T0 + 30), heard("b", T0 + 40), heard("c", T0 + 50))
        rep = sw.analyze(ev)
        self.assertEqual([f["line"] for f in rep["flags"]["insert_out_of_place"]], ["sting"])
        self.assertEqual(rep["flags"]["out_of_order"], [])
        self.assertEqual([f["line"] for f in rep["flags"]["filed_after_heard"]], ["sting"])

    def test_a_line_heard_in_the_next_entry_is_filed_wrong(self):
        ev = recording(led(10, 0, "a", T0 + 200), heard("a", T0 + 260))
        rep = sw.analyze(ev)
        got = rep["flags"]["segment_filed"]
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["filed"], got[0]["on_air"]), ("h:hour-05", "h:hour-06"))

    def test_the_tree_of_the_entry_it_went_out_in_must_hold_it(self):
        tree_b = {"k": "tree", "t": T0 + 400, "b": {"segment_id": "h:hour-06", "rounds": []}}
        tree_a = {"k": "tree", "t": T0 + 400, "b": {"segment_id": "h:hour-05", "rounds": [
            {"conv": "c1", "elements": [{"t": "s", "line_id": "a", "line_ids": ["a"], "speaker": "A",
                                         "state": "aired", "turn_id": "c1:t00"}]}]}}
        ev = recording(led(10, 0, "a", T0 + 200, turn_id="c1:t00"), heard("a", T0 + 260), tree_a, tree_b)
        rep = sw.analyze(ev)
        miss = rep["flags"]["tree_missing_stage"]
        self.assertEqual([(m["line"], m["went_out_in"], m["in_tree_of"]) for m in miss],
                         [("a", "h:hour-06", ["h:hour-05"])])

    def test_a_clean_recording_exits_zero(self):
        ev = recording(led(10, 0, "a", T0 + 1), led(10, 1, "b", T0 + 1), heard("a", T0 + 30), heard("b", T0 + 34))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.jsonl"
            path.write_text("".join(json.dumps(e) + "\n" for e in ev))
            out = io.StringIO()
            with redirect_stdout(out):
                code = sw.main(["--analyze", str(path)])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("VERDICT: the script unfolded entry to entry", out.getvalue())


if __name__ == "__main__":
    unittest.main()
