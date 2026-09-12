"""#1064 (reading the LCD): the rap reading is the only rhyme evidence, a
dropped g keeps a name, banked rounds get the deep model under the hold,
and the cupboard shows the bars as they land."""
import unittest
from unittest import mock

import app


class RapOnlyTests(unittest.TestCase):
    def test_the_spelling_proof_alone_no_longer_passes_a_line(self):
        source = "The station needs a copper plate before midnight."
        prose = "Before midnight the station requires a copper plate, honestly / and a second thing."
        with (mock.patch.object(app, "_crystal_vocab", return_value=frozenset()),
              mock.patch.object(app, "_rhyme_pairs", return_value={"internal_pairs": [["a", "b"], ["c", "d"]],
                                                                   "multisyllabic_pairs": [], "chain_pairs": [], "ok": True}),
              mock.patch.object(app, "rap_rhyme_evidence", return_value={"ok": False})):
            report = app.tint_evaluate(source, prose, [], force=0.9, strict=False)
        self.assertFalse(report["ok"])
        self.assertIn("no rhyme evidence - the bar does not land a rhyme", report["faults"])
        self.assertTrue(report["rhyme"]["ok"])            # still reported
        self.assertEqual(report["version"], 9)

    def test_a_dropped_g_keeps_the_name(self):
        source = "It should have been called Bleeding Sky, honestly."
        bar = "Call it bleedin' sky, a cheap dye on the sly, the mistake you can't deny."
        with mock.patch.object(app, "_crystal_vocab", return_value=frozenset()):
            report = app.tint_evaluate(source, bar, [], force=0.9, strict=False)
        self.assertTrue(report["semantic"]["entities"], report["semantic"])

    def test_every_road_gets_the_deep_model_under_the_hold(self):
        with (mock.patch.object(app, "crystal_tint_holds", return_value=True),
              mock.patch.object(app, "tint_model_now", return_value="deep"),
              mock.patch.object(app, "tint_fast_model", return_value="fast")):
            for kind in ("banter", "caller", "manager", "gallery", "news", "ad", "track_talk"):
                self.assertEqual(app.tint_model_for(kind), "deep", kind)

    def test_the_cupboard_shows_the_bars_as_they_land(self):
        entry = {"prep_kind": "banter", "label": "booth rounds", "at": 5.0,
                 "script": "A: plain one\nB: plain two\nA: plain three", "made": 0, "chunks": 0,
                 "tint": {"ok": False, "coverage": {"met": False, "version": 4}},
                 "tint_progress": {"turns": [
                     {"marker": "A", "text": "Copper plate by midnight, that's the spark, the lights go dark.",
                      "selected": True, "evaluation": {"ok": True}},
                     {"marker": "B", "text": "", "selected": True, "cut": True, "evaluation": {"ok": False}},
                 ]}}
        ready = {"prep_kind": "manager", "label": "memos", "at": 4.0,
                 "script": "A: Copper plate by midnight, that's the spark, the lights go dark.",
                 "made": 1, "chunks": 1, "keys": ["k"],
                 "tint": {"ok": True, "coverage": {"met": True, "version": 4, "cut": 0}}}
        with (mock.patch.object(app, "_SHELF", {"manager": [{"entry": ready}]}),
              mock.patch.object(app, "_LARDER", [entry]),
              mock.patch.object(app, "_CUPBOARD_MEMO", {"at": 0.0, "value": None}),
              mock.patch.object(app, "dialogue_row_ready", side_effect=lambda k, e: e is ready),
              mock.patch.object(app, "radio_paused", return_value=True),
              mock.patch.object(app, "crystal_active", return_value=[{"name": "DOOM"}]),
              mock.patch.object(app, "crystal_tint_holds", return_value=True),
              mock.patch.object(app, "writing_room_state", return_value={}),
              mock.patch.object(app, "_PREP_NOW", {}),
              mock.patch.object(app, "_TINT_JUDGE_RING", []),
              mock.patch.dict(app._RADIO, {"pipeline": []})):
            got = app.cupboard_state()
        first, second = got["rounds"][0], got["rounds"][1]
        self.assertEqual(first["state"], "ready")                 # bars first
        self.assertEqual(first["grade"], "rhyme")
        self.assertEqual(second["state"], "rapping 1/2")
        self.assertEqual(second["grade"], "rapping")
        self.assertEqual([l["mark"] for l in second["lines"]], ["bar", "cut"])
        self.assertIn("spark", second["lines"][0]["text"])


if __name__ == "__main__":
    unittest.main()
