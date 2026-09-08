"""#1088: machine-handled refusals are notes; only a cut is pending."""
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from line_review import LineReviewStore, TRIAGE_VERSION, INFORMATIONAL_GATES


class TriageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "reviews.sqlite3"
        self.store = LineReviewStore(self.path)

    def tearDown(self):
        try:
            self.tmp.cleanup()
        except Exception:  # noqa: BLE001 - Windows keeps the handle a moment
            pass

    def test_intermediate_refusals_are_noted_and_a_cut_is_pending(self):
        ctx = {"kind": "banter", "who": "A"}
        noted = self.store.record("tint", "Mara needs one plate.", "Mara needs a plate, mate.",
                                  ["semantic preservation failed"], ctx, disposition="rewrite_rejected")
        self.assertEqual(noted["review_status"], "noted")
        trimmed = self.store.record("draft_trimming", "A long draft.", "A draft.", ["too long"], ctx,
                                    disposition="trimmed")
        self.assertEqual(trimmed["review_status"], "noted")
        technical = self.store.record("tint", "No audio here.", "", ["no audio"], ctx, technical=True,
                                      disposition="cut")
        self.assertEqual(technical["review_status"], "noted")
        cut = self.store.record("tint", "Mara needs one plate.", "Plates for Mara, eight.",
                                ["no rhyme evidence"], ctx, disposition="cut")
        self.assertEqual(cut["review_status"], "pending")
        page = self.store.summaries(status="pending", limit=10)
        self.assertEqual(page["unreviewed"], 1)
        self.assertEqual(page["attention"], 1)
        self.assertEqual(page["noted"], 3)
        self.assertEqual([row["id"] for row in page["items"]], [cut["id"]])
        # The pending feed carries the cut's event only; the notes do not wake a watcher.
        self.assertEqual([e["id"] for e in page["events"]], [cut["id"]])
        everything = self.store.summaries(status="all", limit=10)
        self.assertEqual(len(everything["events"]), 4)
        notes = self.store.summaries(status="noted", limit=10)
        self.assertEqual(len(notes["items"]), 3)

    def test_a_note_becomes_a_request_when_the_same_pair_is_finally_cut(self):
        ctx = {"kind": "caller", "who": "B"}
        first = self.store.record("tint", "Hold on, line seven.", "Line seven, hold the phone.",
                                  ["no rhyme evidence"], ctx, disposition="rewrite_rejected")
        self.assertEqual(first["review_status"], "noted")
        again = self.store.record("tint", "Hold on, line seven.", "Line seven, hold the phone.",
                                  ["no rhyme evidence"], ctx, disposition="cut")
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(again["review_status"], "pending")
        self.assertEqual(again["occurrences"], 2)

    def test_the_backlog_is_triaged_once_on_open(self):
        ctx = {"kind": "paper", "who": ""}
        self.store.record("tint", "An old paragraph.", "An old bar.", ["x"], ctx, disposition="cut")
        with sqlite3.connect(self.path) as db:
            # Pretend the rows were written before #1088: everything pending, no triage stamp.
            db.execute("UPDATE line_reviews SET review_status='pending', disposition='rewrite_rejected'")
            body = json.loads(db.execute("SELECT body FROM review_policy WHERE singleton=1").fetchone()[0])
            body.pop("triage_version", None)
            db.execute("UPDATE review_policy SET body=? WHERE singleton=1", (json.dumps(body),))
            db.commit()
        reopened = LineReviewStore(self.path)
        self.assertEqual(reopened.policy().get("triage_version"), TRIAGE_VERSION)
        page = reopened.summaries(status="pending", limit=10)
        self.assertEqual(page["unreviewed"], 0)
        self.assertEqual(page["noted"], 1)

    # 2026-09-08, the rejections census: the desk's own retries are notes too.
    def test_the_machines_own_retries_are_notes_whatever_the_disposition(self):
        ctx = {"kind": "model_draft", "who": ""}
        for gate in INFORMATIONAL_GATES:
            with self.subTest(gate=gate):
                row = self.store.record(gate, "Mara left the", "", ["no finished sentence"], ctx,
                                        disposition="cut")
                self.assertEqual(row["review_status"], "noted")
                again = self.store.record(gate, "Mara left the", "", ["no finished sentence"], ctx,
                                          disposition="cut")
                self.assertEqual(again["review_status"], "noted")
        cut = self.store.record("tint", "Mara left the plate.", "The plate, Mara left it late.",
                                ["no rhyme evidence"], ctx, disposition="cut")
        self.assertEqual(cut["review_status"], "pending")
        page = self.store.summaries(status="pending", limit=10)
        self.assertEqual(page["unreviewed"], 1)
        self.assertEqual(page["noted"], len(INFORMATIONAL_GATES))

    def test_a_passed_rewrite_supersedes_the_pending_cuts_of_its_line(self):
        ctx = {"kind": "caller", "who": "B"}
        cut = self.store.record("tint", "Hold on,  line seven.", "Line seven, hold the phone.",
                                ["no rhyme evidence"], ctx, disposition="cut")
        other = self.store.record("tint", "Another line entirely.", "A line, entirely other.",
                                  ["no rhyme evidence"], ctx, disposition="cut")
        self.assertEqual({cut["review_status"], other["review_status"]}, {"pending"})
        self.assertEqual(self.store.supersede("tint", "Hold on, line seven."), 1)
        self.assertEqual(self.store.supersede("tint", "Hold on, line seven."), 0)
        self.assertEqual(self.store.supersede("tint", ""), 0)
        page = self.store.summaries(status="pending", limit=10)
        self.assertEqual([row["id"] for row in page["items"]], [other["id"]])
        notes = self.store.summaries(status="noted", limit=10)
        self.assertEqual([row["id"] for row in notes["items"]], [cut["id"]])
        self.assertEqual(notes["items"][0]["effect"]["status"], "superseded")

    def test_the_backlog_is_triaged_again_for_the_machines_gates(self):
        ctx = {"kind": "model_draft", "who": ""}
        self.store.record("draft_fragment", "Mara left the", "", ["no finished sentence"], ctx,
                          disposition="cut")
        with sqlite3.connect(self.path) as db:
            # Pretend the rows were written under triage 1: a fragment sat pending.
            db.execute("UPDATE line_reviews SET review_status='pending'")
            body = json.loads(db.execute("SELECT body FROM review_policy WHERE singleton=1").fetchone()[0])
            body["triage_version"] = 1
            db.execute("UPDATE review_policy SET body=? WHERE singleton=1", (json.dumps(body),))
            db.commit()
        reopened = LineReviewStore(self.path)
        self.assertEqual(reopened.policy().get("triage_version"), TRIAGE_VERSION)
        page = reopened.summaries(status="pending", limit=10)
        self.assertEqual(page["unreviewed"], 0)
        self.assertEqual(page["noted"], 1)

    def test_decisions_still_work_on_a_noted_row(self):
        ctx = {"kind": "ad", "who": ""}
        row = self.store.record("tint", "Buy the lamp.", "The lamp, buy it, damp.", ["x"], ctx,
                                disposition="rewrite_rejected")
        kept = self.store.decide(row["id"], "keep", note="fine as it was")
        self.assertEqual(kept["row"]["review_status"], "kept")


if __name__ == "__main__":
    unittest.main()
