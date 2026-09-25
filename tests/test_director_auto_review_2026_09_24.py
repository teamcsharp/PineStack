from __future__ import annotations

import time
import unittest
from unittest import mock

import app


def candidate(identity: str = "spot", text: str = "A finished spot.",
              seconds: float = 120.0) -> dict:
    return {
        "id": identity, "kind": "ad", "script": "A: " + text,
        "seconds": seconds, "ready": True, "eligible": True,
        "audio_hashes": ["a" * 64],
        "lines": [{"text": text, "seconds": seconds,
                   "audio_hash": "a" * 64}],
    }


def bound(*candidates: dict, topic: dict | None = None) -> dict:
    slot = {"id": "hour:ad", "kind": "ad", "prompt": "",
            "allocations": [{"candidate": row, "planned_start": 100.0}
                            for row in candidates]}
    topic = topic or {"checked": False, "ok": True, "topic": ""}
    with (mock.patch.object(app, "alt_find", return_value=("", None)),
          mock.patch.object(app, "dialogue_topic_review", return_value=topic),
          mock.patch.object(app, "tint_must_flow", return_value=False)):
        return app._director_script(slot)


class DirectorAutoReviewTests(unittest.TestCase):
    def test_bound_view_keeps_recorded_words_when_shelf_script_changes(self) -> None:
        recorded = candidate(text="The recorded words.")
        slot = {"id": "hour:ad", "kind": "ad", "prompt": "",
                "allocations": [{"candidate": recorded, "planned_start": 100.0}]}
        with (mock.patch.object(app, "alt_find", return_value=(
                    "ad", {"entry": {"script": "A: A newer unrecorded rewrite."}})),
              mock.patch.object(app, "dialogue_topic_review",
                                return_value={"checked": False, "ok": True}),
              mock.patch.object(app, "tint_must_flow", return_value=False)):
            script = app._director_script(slot)
        self.assertEqual([turn["text"] for turn in script["turns"]],
                         ["The recorded words."])
        self.assertTrue(script["auto_review"]["ok"])
        self.assertTrue(script["live"])

    def test_recorded_contract_reviews_without_fabricating_manual_approval(self) -> None:
        script = bound(candidate())
        got = app.director_orchestration(
            "ad", "Advert", 120.0, script, state="planned",
            review={"approved": False, "state": "unreviewed"})
        self.assertTrue(script["auto_review"]["ok"])
        self.assertEqual(script["auto_review"]["basis"], "recorded-contract")
        self.assertTrue(got["stages"]["reviewed"])
        self.assertTrue(got["stages"]["automatically_reviewed"])
        self.assertFalse(got["stages"]["manually_reviewed"])
        self.assertEqual(got["status"], "ready")
        self.assertEqual(got["target"]["lines"], 1)
        self.assertEqual(got["short"]["seconds"], 0.0)
        self.assertNotIn("review the script", got["needs"])

    def test_changed_words_or_missing_audio_proof_do_not_auto_review(self) -> None:
        changed = candidate()
        changed["script"] = "A: An edit that has not been recorded."
        missing = candidate()
        missing["lines"][0].pop("audio_hash")
        for row, check in ((changed, "words_match_recording"),
                           (missing, "recorded_lines")):
            with self.subTest(check=check):
                script = bound(row)
                got = app.director_orchestration(
                    "ad", "Advert", 120.0, script,
                    review={"approved": False})
                self.assertFalse(script["auto_review"]["ok"])
                self.assertFalse(script["performances"][0]
                                 ["auto_review"]["checks"][check])
                self.assertFalse(got["stages"]["reviewed"])
                self.assertIn("review the script", got["needs"])
                self.assertEqual(got["status"], "awaiting-review")

    def test_recording_may_split_one_spoken_turn_into_several_clips(self) -> None:
        split = candidate(text="First sentence. Second sentence.")
        split["lines"] = [
            {"text": "First sentence.", "seconds": 60.0,
             "audio_hash": "a" * 64},
            {"text": "Second sentence.", "seconds": 60.0,
             "audio_hash": "b" * 64},
        ]
        self.assertTrue(bound(split)["auto_review"]["ok"])
        split["lines"][1]["text"] = "A different sentence."
        self.assertFalse(bound(split)["auto_review"]["ok"])

    def test_battle_reply_is_not_mistaken_for_segment_topic(self) -> None:
        prompt = ('SCHEDULE: Sell the painting.\n'
                  'ANSWER THIS. the DJ held the floor last and said:\n'
                  '"Listen, there is something you need to know."')
        self.assertEqual(app._director_topic_from_prompt(prompt), "")
        explicit = prompt + '\nTHE SUBJECT OF THIS CALL: the painting\n'
        self.assertEqual(app._director_topic_from_prompt(explicit), "the painting")

    def test_phone_theme_excludes_calendar_instruction(self) -> None:
        prompt = ("THE PHONE'S SUBJECT TONIGHT, from the caller theme: "
                  "A man used my toilet. Whoever rings this entry rang about "
                  "THAT; they say so in their own words.")
        self.assertEqual(app._director_topic_from_prompt(prompt),
                         "A man used my toilet.")

    def test_topic_rejection_and_expiry_block_automatic_review(self) -> None:
        rejected = bound(candidate(), topic={"checked": True, "ok": False})
        self.assertFalse(rejected["auto_review"]["ok"])
        expired = candidate()
        expired["expires_at"] = time.time() - 1
        self.assertFalse(bound(expired)["auto_review"]["ok"])

    def test_every_allocation_must_pass(self) -> None:
        second = candidate("second", "Another finished spot.", 120.0)
        second["ready"] = False
        script = bound(candidate("first"), second)
        self.assertEqual(len(script["performances"]), 2)
        self.assertFalse(script["auto_review"]["ok"])
        self.assertTrue(script["performances"][0]["auto_review"]["ok"])
        self.assertFalse(script["performances"][1]["auto_review"]["ok"])

    def test_checked_draft_can_be_editorially_reviewed_but_not_recorded(self) -> None:
        slot = {"id": "draft", "kind": "caller", "prompt": "subject",
                "drafts": [{"id": "draft-1", "script": "A: On topic.",
                            "eligible": True}]}
        with (mock.patch.object(app, "script_choice", return_value={}),
              mock.patch.object(app, "dialogue_topic_review",
                                return_value={"checked": True, "ok": True,
                                              "topic": "topic"})):
            script = app._director_script(slot)
        got = app.director_orchestration("caller", "Call", 120.0, script)
        self.assertTrue(got["stages"]["automatically_reviewed"])
        self.assertFalse(got["stages"]["recorded"])
        self.assertNotEqual(got["status"], "ready")

    def test_unchecked_draft_still_awaits_review(self) -> None:
        slot = {"id": "draft", "kind": "caller", "prompt": "",
                "drafts": [{"id": "draft-1", "script": "A: A line.",
                            "eligible": True}]}
        with (mock.patch.object(app, "script_choice", return_value={}),
              mock.patch.object(app, "dialogue_topic_review",
                                return_value={"checked": False, "ok": True,
                                              "topic": ""})):
            script = app._director_script(slot)
        got = app.director_orchestration("caller", "Call", 120.0, script)
        self.assertFalse(got["stages"]["reviewed"])

    def test_manual_approval_remains_a_distinct_override(self) -> None:
        script = bound(candidate())
        script["auto_review"]["ok"] = False
        got = app.director_orchestration("ad", "Advert", 120.0, script,
                                         review={"approved": True})
        self.assertTrue(got["stages"]["reviewed"])
        self.assertTrue(got["stages"]["manually_reviewed"])
        self.assertFalse(got["stages"]["automatically_reviewed"])


if __name__ == "__main__":
    unittest.main()
