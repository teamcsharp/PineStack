"""Actual refresh reclassifies pinned old evidence without production actions."""
import copy
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app
from line_review import LineReviewStore
from prompt_learning import PromptLearningStore


class PromptLearningRefreshTests(unittest.TestCase):
    def test_exact_retained_refs_outside_recent_page_and_missing_original_stays_pending(self):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            reviews = LineReviewStore(Path(temp) / "review.sqlite3")
            learning = PromptLearningStore(Path(temp) / "learning.sqlite3")
            report = {"version": 5, "grade": "meaning", "machine_ok": False,
                "rhyme": {"required": True, "ok": False, "rap": {"ok": True}},
                "transformation": {"ok": False, "cadence_changed": False}}
            old = []
            with mock.patch("prompt_learning.CLASSIFIER_VERSION", 1), mock.patch(
                    "prompt_learning._patterns", return_value=["rhyme", "cadence"]):
                for i in range(3):
                    row = reviews.record("tint", f"Original old line {i}.", f"Candidate old line {i}.",
                        ["style changed too little"], context={"kind": "gallery", "script_plain": f"Parent {i // 2}"},
                        evaluation=report)
                    old.append(row)
                    learning.observe(row)
                decision = reviews.decide(old[0]["id"], "keep", "Preserve my exact note.",
                    expected_revision=old[0]["revision"], expected_event_seq=old[0]["event_seq"])
                learning.decision(reviews.get(old[0]["id"], event_seq=old[0]["event_seq"]))
            # These newer, unrelated records keep all old IDs off the latest200.
            for i in range(205):
                reviews.record("technical", f"Recent source {i}", "", ["Missing media"], technical=True)
            recent_ids = {r["id"] for r in reviews.summaries(status="all", limit=200)["items"]}
            self.assertTrue(all(r["id"] not in recent_ids for r in old))
            before = {r["id"]: copy.deepcopy(reviews.get(r["id"], event_seq=r["event_seq"])) for r in old}
            with learning._connect() as db:
                decisions_before = db.execute("SELECT source_key,body FROM prompt_decisions").fetchall()
            total = reviews.summaries(status="all")["total"]
            original_get = reviews.get
            def get(review_id, **kwargs):
                if review_id == old[2]["id"]:
                    return None  # missing exact evidence must never be guessed from text
                return original_get(review_id, **kwargs)
            getter = stack.enter_context(mock.patch.object(reviews, "get", side_effect=get))
            for name, value in {
                "_PROMPT_LEARNING": learning, "_LINE_REVIEW": reviews,
                "_PROMPT_LEARNING_ERRORS": {"count": 0, "last_error": ""},
                "_LAB_RUNTIME": mock.Mock(), "station_flow_event": mock.Mock(),
            }.items():
                stack.enter_context(mock.patch.object(app, name, value))
            forbidden = []
            for name in ("ask_model", "call_ollama", "voice_render_any", "line_review_recover", "_play_on_box"):
                fn = stack.enter_context(mock.patch.object(app, name, side_effect=AssertionError("No generation, vote or playback")))
                forbidden.append(fn)
            token = app._REJECTION_LAB_PREVIEW.set(False)
            try:
                result = app.prompt_learning_refresh()
            finally:
                app._REJECTION_LAB_PREVIEW.reset(token)
            self.assertEqual(result["reclassified"], 2)
            self.assertEqual(result["observed"], 200)
            self.assertEqual(result["errors"]["count"], 0)
            for row in old:
                self.assertIn(mock.call(row["id"], event_seq=row["event_seq"]), getter.call_args_list)
                self.assertEqual(original_get(row["id"], event_seq=row["event_seq"]), before[row["id"]])
            self.assertEqual(reviews.summaries(status="all")["total"], total)
            self.assertEqual(learning.pending_reclassifications(), [{"review_id": old[2]["id"],
                "event_seq": old[2]["event_seq"], "classifier_version": 1}])
            with learning._connect() as db:
                self.assertEqual([tuple(r) for r in db.execute("SELECT source_key,body FROM prompt_decisions")],
                                 [tuple(r) for r in decisions_before])
                migrated = json.loads(db.execute("SELECT body FROM prompt_evidence WHERE review_id=?",
                                                 (old[0]["id"],)).fetchone()[0])
            self.assertEqual(migrated["patterns"], ["cadence"])
            self.assertEqual(learning.classification_history()["total"], 2)
            for fn in forbidden:
                fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
