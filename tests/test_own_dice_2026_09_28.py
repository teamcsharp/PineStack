"""[s3-own-dice] Every aired line carries ITS OWN node's dice.

The operator saw two different aired lines wearing one identical System 3
stamp (script_ledger block 35646 ord 2 and block 35649 ord 1: both "t01,
bundle t01:b8732e023, dice 0.937025").  Root cause: _speak_turns_floorless
looked each row's dice up by `turn_ix` - a count of the AUDIO CHUNKS a burst
aired - in `turn_dice`, which is keyed by the SCRIPT's turns.  A turn aired
in several chunks handed the next turns' dice to its own continuations, and
every burst restarted the count, so each burst's first chunk wore t00's.

Proven here on the REAL round (tests/s3_own_dice_04cb_fixture.json, captured
read-only from the live ledger): app.py's own row builders (_td_of,
_s3_row_bare, _s3_row_of) and its commit pre-pass (_s3_air_rows) are
executed against the round's bursts with the real System 3 runtime linking
chunks by their words.  The PRE-FIX builder reproduces the live ledger's
wrong dice row for row (so the harness is the real road); the fixed builder
gives every dialogue row its own node's dice, dice.s3.turn_id ==
system3.turn_id on every row, marks each continuation chunk "cont", and
leaves System-2-only rounds exactly as they were.

Run one module at a time, niced, in the container tree:
  PYTHONPATH=/tmp/cover_a nice -n 19 timeout 600 \\
      python -m unittest tests.test_own_dice_2026_09_28 -v
"""
import copy
import json
from pathlib import Path
import re
import tempfile
import textwrap
import time
import unittest
from typing import Any

import system3_runtime

HERE = Path(__file__).resolve().parent.parent
FIXTURE = json.loads((Path(__file__).resolve().parent
                      / "s3_own_dice_04cb_fixture.json").read_text(encoding="utf-8"))

MARK = "                # [s3-own-dice] A System 3 round's dice belong to its NODES.\n"
TD_END = ("                                _got = dict(_got, cont=True)\n"
          "                    return _got if isinstance(_got, dict) else {}\n")
ORIGINAL_TD_OF = ("                def _td_of(_row_at: int) -> dict[str, Any]:\n"
                  "                    _t = (turn_ix[_row_at]\n"
                  "                          if _row_at < len(turn_ix) else -1)\n"
                  "                    _got = (turn_dice or {}).get(_t)\n"
                  "                    return _got if isinstance(_got, dict) else {}\n")


def app_source(pre_fix=False):
    src = (HERE / "app.py").read_bytes().decode("utf-8")
    if pre_fix and MARK in src:
        at = src.index(MARK)
        end = src.index(TD_END, at) + len(TD_END)
        src = src[:at] + ORIGINAL_TD_OF + src[end:]
    return src


def app_slice(src, name):
    head = "def %s(" % name
    at = src.index("\n" + head) + 1
    m = re.compile(r"\n(?:async def |def |@app\.|[A-Z_]+[A-Z0-9_]* *[:=])").search(src, at + len(head))
    return src[at:m.start()] + "\n"


def split_turns(script, caller_name="", caller2_name=""):
    """A plain A:/B: splitter - app.py's banter_turns without the persona-name folding."""
    parts = re.split(r"(?m)^([A-E]):\s*", str(script or ""))
    return [(parts[i], parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]


def row_builders(src, glb):
    """app.py's own per-row builders, cut from _speak_turns_floorless (from the
    passage-source line up to the `_script_rows` comprehension) and run as a
    closure over the burst's locals."""
    start = src.index("                _pass = [d for d in (passage_source or [])")
    end = src.index("                _script_rows = [", start)
    body = textwrap.indent(textwrap.dedent(src[start:end]), "    ")
    code = ("def _harness(turn_ix, turn_dice, transcript, ready_meta, ready_takes,\n"
            "             aired_items, _sfx_meta, passage_source, turn_source):\n"
            + body + "    return _td_of, _s3_row_of\n")
    exec(compile(code, "app-rows", "exec"), glb)
    return glb["_harness"]


class Round:
    """The 04cb round as the air path saw it: its script, its bind, its dice."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        ns = {"data_path": lambda *p: Path(self.tmp.name).joinpath(*p),
              "pipeline_log": lambda *a, **k: None,
              "banter_turns": split_turns}
        self.rt = system3_runtime.System3Runtime(system3_runtime._Host(ns))
        turns = FIXTURE["turns"]
        self.script = "\n".join("%s: %s" % (t["speaker"], t["text"]) for t in turns)
        self.meta = {"script": self.script,
                     "system3": {"conversation_id": FIXTURE["conversation_id"], "mode": "active",
                                 "turns": {str(t["index"]): t["turn_id"] for t in turns}}}
        dice = FIXTURE["dice_by_turn"]
        self.turn_dice = {t["index"]: copy.deepcopy(dice[t["turn_id"]]) for t in turns}
        norm = lambda s: " ".join(str(s or "").lower().split())
        self.pos = {}                      # line_id -> (turn_id, where its words sit)
        for burst in FIXTURE["bursts"]:
            for r in burst["rows"]:
                for t in turns:
                    at = norm(t["text"]).find(norm(r["text"]))
                    if r["who"] in ("dj", "cohost") and at >= 0:
                        self.pos[r["line_id"]] = (t["turn_id"], at)

    def close(self):
        try:
            self.rt.store.db.close()
        except Exception:  # noqa: BLE001
            pass
        self.tmp.cleanup()

    def air(self, src, burst, turn_dice=None, meta=None):
        """One burst through app.py's builders and _s3_air_rows: the rows the
        ledger would be handed."""
        glb = {"Any": Any, "copy": copy, "time": time, "banter_turns": split_turns,
               "system3_turn_id_for": self.rt.turn_id_for}
        harness = row_builders(src, glb)
        rows = burst["rows"]
        transcript = [(r["who"], r["text"], 1.0) for r in rows]
        turn_ix = [int(r["turn"]) if r["turn"] is not None else -1 for r in rows]
        aired = [{} for _ in range(max(turn_ix) + 1)]
        for r, ti in zip(rows, turn_ix):
            if ti >= 0:
                aired[ti] = {"turn_text": r["text"]}   # a prepared take carries its own
        td_of, s3_of = harness(turn_ix, self.turn_dice if turn_dice is None else turn_dice,
                               transcript, self.meta if meta is None else meta,
                               [{"text": r["text"]} for r in rows], aired, {}, [], {})
        out = []
        for i, r in enumerate(rows):
            row = {"line_id": r["line_id"], "who": r["who"], "text": r["text"], "turn": turn_ix[i]}
            d = td_of(i)
            if d:
                row["dice"] = d
            st = s3_of(i)
            if st:
                row["system3"] = st
            out.append(row)
        # the commit pre-pass: a line the air spliced in by a roll (a listening
        # response) names its own node and drops the round's turn dice
        air_ns = {"time": time, "Any": Any,
                  "_S3_AIR_OWN": {r["line_id"]: {"conversation_id": FIXTURE["conversation_id"],
                                                 "mode": "active", "turn_id": "", "listening": {}}
                                  for r in rows if r["who"] in ("dj", "cohost")
                                  and r["line_id"] not in self.pos}}
        exec(compile(app_slice(src, "_s3_air_rows"), "app-air-rows", "exec"), air_ns)
        air_ns["_s3_air_rows"](out, dict(self.meta))
        return out


def dice_tid(row):
    return (((row.get("dice") or {}).get("s3") or {}).get("turn_id")) or None


class OwnDiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.round = Round()
        cls.fixed = app_source()
        cls.before = app_source(pre_fix=True)

    @classmethod
    def tearDownClass(cls):
        cls.round.close()

    def aired(self, src):
        return {r["line_id"]: r for b in FIXTURE["bursts"] for r in self.round.air(src, b)}

    def test_the_patch_is_in_the_tree(self):
        self.assertIn(MARK, self.fixed, "run tools/cover_a_own_dice_patch.py --apply first")
        self.assertIn(ORIGINAL_TD_OF, self.before)

    def test_pre_fix_builder_reproduces_the_live_ledger(self):
        # the harness IS the road: the unfixed builder hands out exactly the
        # dice the live ledger recorded, wrong rows and missing rows alike
        got = self.aired(self.before)
        wrong = 0
        for b in FIXTURE["bursts"]:
            for r in b["rows"]:
                self.assertEqual(dice_tid(got[r["line_id"]]), r["dice_turn_id"],
                                 "block %s ord %s" % (b["block"], r["ord"]))
                if r["dice_turn_id"] and r["dice_turn_id"] != r["system3_turn_id"]:
                    wrong += 1
        self.assertEqual(wrong, 8, "8 of the round's diced rows wore another node's dice")

    def test_the_operators_two_lines_carry_their_own_node(self):
        got = self.aired(self.fixed)
        t00 = FIXTURE["conversation_id"] + ":t00"
        for lid in ("1efea24e3d894bcb929a89a10c8f11a8", "7a977477eea942598d69dccf8d87f6df"):
            row = got[lid]
            self.assertEqual(dice_tid(row), t00, lid)
            self.assertEqual(row["system3"]["turn_id"], t00)
            self.assertIsNone(row["dice"].get("roll"), "t00's own dice, not t01's 0.937025")
            self.assertTrue(row["dice"].get("cont"), "a split continuation of t00, said so")

    def test_every_dialogue_row_wears_its_own_node(self):
        got = self.aired(self.fixed)
        diced = 0
        for lid, (tid, at) in self.round.pos.items():
            row = got[lid]
            self.assertEqual(dice_tid(row), tid, row["text"][:40])
            self.assertEqual(row["system3"]["turn_id"], tid)
            self.assertEqual(bool(row["dice"].get("cont")), at > 0,
                             "head/continuation by where the words sit: %s" % row["text"][:40])
            diced += 1
        self.assertEqual(diced, 16)
        heads = sorted(dice_tid(got[lid])[-3:] for lid, (_t, at) in self.round.pos.items() if at == 0)
        self.assertEqual(heads, ["t00", "t01", "t02", "t03"], "one opening chunk per node")

    def test_t01s_roll_lands_on_t01s_lines_only(self):
        got = self.aired(self.fixed)
        holders = sorted(r["text"][:24] for r in got.values()
                         if (r.get("dice") or {}).get("roll") == 0.937025)
        self.assertEqual(holders, ["I don't buy that the who", "You are talking about so",
                                   "dream. It makes me wonde"])

    def test_dice_and_stamp_never_disagree(self):
        got = self.aired(self.fixed)
        for row in got.values():
            if row.get("dice") and row.get("system3"):
                self.assertEqual(dice_tid(row), row["system3"]["turn_id"], row["text"][:40])

    def test_spliced_board_and_quip_rows_stay_undiced(self):
        got = self.aired(self.fixed)
        for row in got.values():
            if row["who"] in ("board", "drop") or row["line_id"] not in self.round.pos:
                self.assertNotIn("dice", row, row["text"][:40])

    def test_a_round_without_node_dice_is_untouched(self):
        # System 2 dice carry no s3 node: the positional road, byte for byte
        plain = {i: {"roll": 0.1 * (i + 1), "axis": "stance"} for i in range(4)}
        for b in FIXTURE["bursts"]:
            fixed = self.round.air(self.fixed, b, turn_dice=plain)
            before = self.round.air(self.before, b, turn_dice=plain)
            self.assertEqual([r.get("dice") for r in fixed], [r.get("dice") for r in before])

    def test_a_live_written_round_marks_continuations_by_turn_text(self):
        # live-written: only a turn's FIRST chunk carries turn_text (#no-repeats)
        src = self.fixed
        glb = {"Any": Any, "copy": copy, "time": time, "banter_turns": split_turns,
               "system3_turn_id_for": self.round.rt.turn_id_for}
        harness = row_builders(src, glb)
        t = FIXTURE["turns"]
        a1, a2 = t[0]["text"][:120], t[0]["text"][133:290]
        transcript = [("dj", a1, 1.0), ("dj", a2, 1.0), ("cohost", t[1]["text"][:100], 1.0)]
        aired = [{"turn_text": t[0]["text"]}, {}, {"turn_text": t[1]["text"]}]
        td_of, _s3 = harness([0, 1, 2], self.round.turn_dice, transcript, self.round.meta,
                             None, aired, {}, [], {})
        self.assertEqual([dice_tid({"dice": td_of(i)})[-3:] for i in range(3)], ["t00", "t00", "t01"])
        self.assertEqual([bool(td_of(i).get("cont")) for i in range(3)], [False, True, False])


if __name__ == "__main__":
    unittest.main()
