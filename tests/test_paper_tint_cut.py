"""#1077: under the crystal a Gazette paragraph that would not rap is cut before print."""
import unittest
from unittest import mock

import app


def _story(body, classifieds=None, records=None, target=100):
    story = {"slug": "on-air", "body": body, "meta": {}}
    if classifieds is not None:
        story["meta"]["classifieds"] = classifieds
    units = app.paper_tint_units(story)
    story["meta"]["tint"] = {"eligible": len(units), "attempted": len(records or []), "changed": 0,
                             "target": target, "required": (len(units) * target + 99) // 100,
                             "met": False, "status": "failed",
                             "paragraphs": list(records or [])}
    return story


class PaperTintCutTests(unittest.TestCase):
    def setUp(self):
        self.p0 = "The first paragraph is the lead and it is kept whatever the crystal said about it."
        self.p1 = "The second paragraph was refused by the grade and has no rhyme in it at all."
        self.p2 = "The third paragraph came back as a bar: the night is long and the record spins on strong."
        self.p3 = "The fourth paragraph was never asked because the window closed before it."

    def test_refused_and_unasked_paragraphs_are_cut_and_records_rekeyed(self):
        body = "\n\n".join([self.p0, self.p1, self.p2, self.p3])
        story = _story(body, records=[
            {"key": "body:0", "ok": False, "faults": "refused"},
            {"key": "body:1", "ok": False, "faults": "refused"},
            {"key": "body:2", "ok": True, "output_hash": "x", "faults": ""}])
        cut = app.paper_tint_cut(story)
        self.assertEqual(cut, 2)
        self.assertEqual(story["body"].split("\n\n"), [self.p0, self.p2])
        keys = {r["key"]: r for r in story["meta"]["tint"]["paragraphs"]}
        self.assertEqual(set(keys), {"body:0", "body:1"})
        self.assertTrue(keys["body:1"]["ok"], "the accepted third paragraph is now the second")
        self.assertFalse(keys["body:0"]["ok"], "the kept lead paragraph still says it stayed plain")
        self.assertEqual(story["meta"]["tint"]["cut"], 2)
        self.assertEqual(story["meta"]["tint"]["eligible"], 2)
        self.assertEqual(story["meta"]["tint"]["required"], 2)

    def test_classifieds_that_stayed_plain_are_dropped_and_qa_is_kept(self):
        story = _story(self.p0, classifieds=[
            {"body": "For sale: one accordion, slightly haunted, plays itself at dusk."},
            {"body": "Wanted: a quiet room near the station for a loud thinker to sit in."}],
            records=[{"key": "classified:0", "ok": True, "output_hash": "y", "faults": ""},
                     {"key": "classified:1", "ok": False, "faults": "refused"}])
        story["meta"]["interview"] = {"qa": [{"q": "What keeps the record turning through the night?",
                                              "a": "Patience, and a needle that was never asked to rhyme."}]}
        story["meta"]["tint"]["paragraphs"].append({"key": "qa:0:a", "ok": False, "faults": "refused"})
        cut = app.paper_tint_cut(story)
        self.assertEqual(cut, 1)
        self.assertEqual(len(story["meta"]["classifieds"]), 1)
        self.assertIn("accordion", story["meta"]["classifieds"][0]["body"])
        self.assertEqual(len(story["meta"]["interview"]["qa"]), 1, "answers are never cut")
        keys = {r["key"] for r in story["meta"]["tint"]["paragraphs"]}
        self.assertEqual(keys, {"classified:0", "qa:0:a"})

    def test_a_met_story_is_left_alone(self):
        story = _story("\n\n".join([self.p0, self.p2]))
        story["meta"]["tint"].update(met=True, changed=2)
        self.assertEqual(app.paper_tint_cut(story), 0)
        self.assertEqual(story["body"].split("\n\n"), [self.p0, self.p2])

    def test_summary_after_the_cut_reads_the_remaining_paragraphs(self):
        body = "\n\n".join([self.p0, self.p1, self.p2])
        story = _story(body, records=[
            {"key": "body:0", "ok": False, "faults": "refused"},
            {"key": "body:1", "ok": False, "faults": "refused"},
            {"key": "body:2", "ok": True, "faults": "",
             "output_hash": __import__("hashlib").sha1(self.p2.encode("utf-8", "ignore")).hexdigest()}])
        app.paper_tint_cut(story)
        with mock.patch.object(app, "crystal_coverage_target", return_value=100):
            summary = app.paper_tint_summary([story])
        self.assertEqual(summary["eligible"], 2)
        self.assertEqual(summary["changed"], 1)
        self.assertIn("1 cut for want of a rhyme", app.paper_tint_status(story["meta"]))


if __name__ == "__main__":
    unittest.main()
