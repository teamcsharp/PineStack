"""[review-queue] The desk's review strip: every open item can be resolved or
dismissed (one or many), the queue and its history read back, and every item
says what System 3 knows about it - by its stamp, its round, its line or its
words - or plainly that it has no System 3 record.

2026-09-28, the operator: "When I tap them, there's not options to fix them
or resolve them or mark them as complete or to get rid of them ... they
don't seem to be talking about any information from system three."
"""
import inspect
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import httpx
import app
import system3
from line_review import LineReviewStore
from system3_store import System3Store

WORDS = ("That's right, and that's exactly where the real conversation starts; "
         "it's about who controls the narrative.")
CUT = "round cut mid-flight — the box is not the destination, so nothing was shelved"


def plan(cid, created, texts):
    conv = system3.plan_scene(
        {"road": "banter", "seats": ["A", "B"], "turns": len(texts),
         "subject": {"topic": "the MX tape has just finished", "keywords": ["tape"]},
         "availability": {"speakbox": True}, "speakerbox_rates": {"prepend": 0.49, "append": 0.68}},
        system3.default_config(), system3.normalise_settings({"mode": "active", "test_seed": "rq-" + cid}),
        conversation_id=cid)
    for turn, text in zip(conv["turns"], texts):
        turn["text"] = text
    conv["created"] = created
    conv["status"] = "generated"
    return conv


class ReviewQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = LineReviewStore(root / "reviews.sqlite3")
        self.s3 = System3Store(root / "system3.sqlite3")
        self.addCleanup(self.s3.close)
        self.now = time.time()
        self.lab = mock.Mock()
        self.lab.current_id.return_value = ""
        replacements = {
            "_LINE_REVIEW": self.store, "_LARDER": [], "_SHELF": {}, "_TRACK_TALK": {},
            "_REVIEW_S3_MEMO": {}, "_REVIEW_QUEUE_SEEN": {"shape": {}, "census": {}, "scan": {}, "closed": []},
            "_LAB_RUNTIME": self.lab, "SPARK_AGENT_API_KEY": "review-queue-test", "LOCK_READS": True,
            "station_flow_event": mock.Mock(), "pipeline_log": mock.Mock(),
            "prompt_learning_observe": mock.Mock(),
            "line_review_recover": mock.Mock(return_value={"status": "queued"}),
            "line_review_keep": mock.Mock(return_value={"status": "kept"}),
            "line_review_clear_operator_proofs": mock.Mock(),
            "review_s3_path": lambda: root / "system3.sqlite3",
            "_s3_active": lambda: True,
        }
        for name, value in replacements.items():
            patch = mock.patch.object(app, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    async def request(self, method, path, body=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url="http://test") as client:
            return await client.request(method, path, json=body,
                                        headers={"Authorization": "Bearer review-queue-test"})

    def age(self, row, seconds):
        """Make a row `seconds` old (its first cut and its last)."""
        db = sqlite3.connect(str(self.store.path))
        with db:
            db.execute("UPDATE line_reviews SET first_at=?, last_at=? WHERE id=?",
                       (self.now - seconds, self.now - seconds, row["id"]))
        db.close()
        return self.store.get(row["id"])

    def timing(self, words=WORDS, **context):
        app.note_drop("cohost", words, CUT, context=context or None)
        page = self.store.summaries(status="pending", limit=50)
        return self.store.get(next(i["id"] for i in page["items"]
                                   if i["source_preview"] == words[:220]))

    # --- closing ---------------------------------------------------------------
    async def test_dismiss_leaves_the_queue_records_the_decision_and_teaches_nothing(self):
        row = self.timing()
        self.assertEqual(row["gate"], "timing")
        self.assertEqual(row["review_status"], "pending")
        endpoint = "/api/orchestrator/rejections/" + row["id"]
        stale = await self.request("POST", endpoint, {"action": "dismiss",
                                                      "expected_revision": row["revision"] + 5})
        self.assertEqual(stale.status_code, 409, stale.text)
        got = await self.request("POST", endpoint, {"action": "dismiss", "note": "nothing to decide",
                                                    "expected_revision": row["revision"],
                                                    "expected_event_seq": row["event_seq"]})
        self.assertEqual(got.status_code, 200, got.text)
        body = got.json()
        self.assertTrue(body["changed"])
        self.assertEqual(body["row"]["review_status"], "noted")
        self.assertEqual(body["row"]["effect"]["status"], "dismissed")
        self.assertEqual(body["row"]["effect"]["by"], "operator")
        self.assertEqual(body["row"]["decisions"][0]["action"], "dismiss")
        self.assertEqual(body["row"]["decisions"][0]["note"], "nothing to decide")
        pending = await self.request("GET", "/api/orchestrator/rejections?status=pending&limit=24")
        self.assertEqual(pending.json()["items"], [])
        self.assertEqual(pending.json()["unreviewed"], 0)
        app.line_review_recover.assert_not_called()
        app.line_review_keep.assert_not_called()
        app.prompt_learning_observe.assert_called_once()        # the capture, never the close
        self.assertEqual(self.store.preference_examples(), [])
        again = await self.request("POST", endpoint, {"action": "dismiss"})
        self.assertEqual(again.status_code, 200, again.text)
        self.assertFalse(again.json()["changed"])
        self.assertIn("Already closed", again.json()["say"])
        detail = (await self.request("GET", endpoint)).json()
        self.assertFalse(detail["resolve"]["open"])
        self.assertEqual(detail["resolve"]["closed"]["status"], "dismissed")
        self.assertEqual(detail["resolve"]["closed"]["by"], "operator")

    async def test_resolve_and_the_old_decisions_still_work(self):
        one = self.timing()
        two = self.store.record("tint", "The gate is red.", "The red gate waits.", ["meaning drift"],
                                context={"kind": "banter"})
        got = await self.request("POST", "/api/orchestrator/rejections/" + one["id"], {"action": "resolve"})
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json()["row"]["effect"]["status"], "resolved")
        kept = await self.request("POST", "/api/orchestrator/rejections/" + two["id"], {"action": "keep"})
        self.assertEqual(kept.status_code, 200, kept.text)
        app.line_review_keep.assert_called()
        bad = await self.request("POST", "/api/orchestrator/rejections/" + two["id"], {"action": "banish"})
        self.assertEqual(bad.status_code, 400)
        missing = await self.request("POST", "/api/orchestrator/rejections/nope", {"action": "dismiss"})
        self.assertEqual(missing.status_code, 404)

    async def test_bulk_close_by_age_with_a_dry_run_first(self):
        old = self.age(self.timing(), 3 * 86400)
        older = self.age(self.timing(words="A second line the talk cut long ago, never heard by anyone."), 9 * 86400)
        young = self.timing(words="A line the talk cut a minute ago, still worth a look.")
        dry = await self.request("POST", "/api/orchestrator/rejections/bulk-close",
                                 {"older_than_s": 86400, "dry_run": True})
        self.assertEqual(dry.status_code, 200, dry.text)
        self.assertEqual(dry.json()["matched"], 2)
        self.assertEqual(dry.json()["closed"], 0)
        self.assertEqual(self.store.get(old["id"])["review_status"], "pending")
        refused = await self.request("POST", "/api/orchestrator/rejections/bulk-close", {"action": "dismiss"})
        self.assertEqual(refused.status_code, 400, "an unfiltered close is refused")
        got = await self.request("POST", "/api/orchestrator/rejections/bulk-close",
                                 {"older_than_s": 86400, "note": "legacy sweep"})
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json()["closed"], 2)
        self.assertEqual({self.store.get(r["id"])["review_status"] for r in (old, older)}, {"noted"})
        self.assertEqual(self.store.get(young["id"])["review_status"], "pending")
        decision = self.store.get(old["id"])["decisions"][0]
        self.assertEqual(decision["batch"], got.json()["batch"])
        self.assertIn("older than 1 day", decision["why"])
        history = (await self.request("GET", "/api/orchestrator/rejections/history")).json()["items"]
        self.assertEqual({h["id"] for h in history}, {old["id"], older["id"]})
        self.assertEqual({h["label"] for h in history}, {"Dismissed"})
        self.assertEqual(history[0]["note"], "legacy sweep")

    # --- System 3 --------------------------------------------------------------
    async def test_system3_story_by_stamp_by_words_and_none(self):
        at = self.now - 3600
        conv = plan("a1b134f233c04813", at - 30, ["The tape is warm.", "It is.", "Tell me more.", WORDS])
        self.s3.save_conversation(conv)
        turn = conv["turns"][3]
        self.s3.add_observation(conv["identity"]["conversation_id"], "WITHHELD",
                                {"stage": "air", "why": "the talk cut took the floor"})
        stamped = self.age(self.timing(words="Stamped words that no turn carries at all, on purpose.",
                                       system3={"conversation_id": "a1b134f233c04813",
                                                "turn_id": turn["turn_id"], "mode": "active"},
                                       line_id="L-1"), 3600)
        by_words = self.age(self.timing(), 3500)
        loose = self.age(self.timing(words="A line from a road System 3 never directed, word for word."), 3500)
        ancient = self.age(self.timing(words="From the old days before any of this existed, by far."), 40 * 86400)

        got = (await self.request("GET", "/api/orchestrator/rejections/" + stamped["id"])).json()
        link = got["system3"]
        self.assertEqual(link["state"], "linked")
        self.assertEqual(link["why"], "stamp")
        self.assertEqual(link["turn"]["turn_id"], turn["turn_id"])
        self.assertEqual(link["turn"]["number"], 4)
        self.assertEqual(link["turn"]["of"], 4)
        self.assertEqual(link["turn"]["node"], turn["step"])
        rolled = {d["event_id"] for d in turn["decisions"]} | {s["event_id"] for s in turn.get("speakerbox") or []}
        rolled |= {turn[k]["event_id"] for k in ("sfx", "sfxguy") if (turn.get(k) or {}).get("event_id")}
        self.assertEqual(link["turn"]["rolls"], len(rolled), "the same rolls System 3's own story shows")
        self.assertEqual(link["road"], "banter")
        self.assertEqual([e["family"] for e in link["events"]], ["WITHHELD"])
        self.assertIn("turn 4 of 4", link["say"])
        self.assertEqual(got["context"]["system3"]["turn_id"], turn["turn_id"])
        self.assertIn("talk cut", got["what"]["say"])
        self.assertFalse(got["resolve"]["fix"]["available"], "a line cut on air has nowhere to go back to")
        self.assertEqual(got["resolve"]["actions"], ["resolve", "dismiss"])

        words = (await self.request("GET", "/api/orchestrator/rejections/" + by_words["id"])).json()["system3"]
        self.assertEqual((words["state"], words["why"], words["turn_id"]), ("linked", "words", turn["turn_id"]))
        self.assertIn("found by its words", words["say"])

        none = (await self.request("GET", "/api/orchestrator/rejections/" + loose["id"])).json()["system3"]
        self.assertEqual((none["state"], none["why"]), ("none", "unlinked"))
        before = (await self.request("GET", "/api/orchestrator/rejections/" + ancient["id"])).json()["system3"]
        self.assertEqual((before["state"], before["why"]), ("none", "before"))
        self.assertIn("from before System 3 directed this road", before["say"])

        queue = (await self.request("GET", "/api/orchestrator/rejections/queue")).json()
        self.assertEqual(queue["count"], 4)
        self.assertEqual(queue["linked"], 2)
        self.assertEqual(queue["legacy"], 2)
        self.assertEqual(queue["ages"]["86400"], 1)
        states = {i["id"]: i["system3"]["state"] for i in queue["items"]}
        self.assertEqual(states[ancient["id"]], "none")
        self.assertEqual(states[by_words["id"]], "linked")

        legacy = await self.request("POST", "/api/orchestrator/rejections/bulk-close", {"legacy": True})
        self.assertEqual(legacy.status_code, 200, legacy.text)
        self.assertEqual(legacy.json()["closed"], 2)
        self.assertEqual({r["id"]: self.store.get(r["id"])["review_status"]
                          for r in (stamped, by_words, loose, ancient)},
                         {stamped["id"]: "pending", by_words["id"]: "pending",
                          loose["id"]: "noted", ancient["id"]: "noted"})

    async def test_round_stamp_and_line_link_and_no_ledger(self):
        at = self.now - 600
        conv = plan("roundstamp000001", at - 60, ["First turn of the held round, long enough.",
                                                   "Second turn of the held round, long enough too."])
        self.s3.save_conversation(conv)
        self.s3.add_lines([{"line_id": "LINE-9", "conversation_id": "roundstamp000001",
                            "turn_id": conv["turns"][1]["turn_id"], "text": "x"}])
        hold = self.store.record("segment_brief", "A: whole script\nB: of the round", reasons=["off brief"],
                                 context={"kind": "banter", "entry": {"system3": {"conversation_id": "roundstamp000001"}}},
                                 disposition="held_before_recording")
        link = app.review_system3_link(self.store.get(hold["id"]))
        self.assertEqual((link["state"], link["why"], link["turn"], link["whole"]), ("linked", "round", None, True))
        self.assertIn("took the whole round", link["say"])
        lined = self.store.record("tint", "Some words the ledger linked by id.", "x", ["rhyme"],
                                  context={"kind": "banter", "line_id": "LINE-9"})
        link = app.review_system3_link(self.store.get(lined["id"]))
        self.assertEqual((link["state"], link["why"], link["turn_id"]),
                         ("linked", "line", conv["turns"][1]["turn_id"]))
        with mock.patch.object(app, "review_s3_path", lambda: Path(self.temp.name) / "absent.sqlite3"):
            self.assertEqual(app.review_system3_link(self.store.get(lined["id"]))["state"], "off")

    # --- the cut road now stamps its rows ---------------------------------------
    def test_the_talk_cut_stamps_its_review_with_the_system3_turn(self):
        finder = mock.Mock(return_value="c1:t03")
        with mock.patch.dict(app.__dict__, {"system3_turn_id_for": finder}):
            ctx = app.review_cut_context({"prep_kind": "banter", "script": "A: x\nB: y",
                                          "system3": {"conversation_id": "c1", "mode": "active"}},
                                         {"who": "cohost", "chunk": WORDS, "line_id": "L7"}, "sid42")
        self.assertEqual(ctx, {"line_id": "L7", "round_sid": "sid42", "kind": "banter",
                               "system3": {"conversation_id": "c1", "turn_id": "c1:t03", "mode": "active"}})
        self.assertEqual(app.review_cut_context(None, None), {})
        row = self.timing(**ctx)
        self.assertEqual(row["context"]["system3"]["turn_id"], "c1:t03")
        self.assertEqual(row["context"]["who"], "cohost", "note_drop's own fields win")
        self.assertEqual(row["context"]["stage"], "recording_or_air_admission")
        source = inspect.getsource(app._speak_turns_floorless)
        self.assertEqual(source.count("context=review_cut_context(ready_meta, item, _round_sid)"), 2)

    def test_timing_rows_are_read_by_the_sweep_when_their_round_is_gone(self):
        self.assertIn("timing", app.REVIEW_QUEUE_SCAN_GATES)
        gone = self.age(self.timing(), 5 * 3600)
        fresh = self.timing(words="A fresh cut the sweep must leave alone for now, thank you.")
        got = app.review_queue_scan(sweep=True, gone_after=3 * 3600)
        self.assertEqual(got["closed"], 1)
        self.assertEqual(self.store.get(gone["id"])["effect"]["status"], "round_gone")
        self.assertEqual(self.store.get(fresh["id"])["review_status"], "pending")
        history = app.review_history()
        self.assertEqual(history["items"][0]["closed_by"], "station")
        self.assertIn("its round had aired", history["items"][0]["label"])

    def test_fix_is_offered_only_while_the_round_waits(self):
        script = "A: The gate is red.\nB: The room is cold."
        entry = {"script": script, "script_plain": script, "prep_kind": "banter", "sid": "r1", "at": 1}
        row = self.store.get(self.store.record("tint", "The gate is red.", "The red gate waits.", ["drift"],
                                               context={"kind": "banter", "script_plain": script,
                                                        "entry": dict(entry)})["id"])
        self.assertFalse(app.review_fix_plan(row)["available"], "round gone + System 3 active = no fix")
        with mock.patch.object(app, "_LARDER", [entry]):
            fix = app.review_fix_plan(row)
        self.assertTrue(fix["available"])
        self.assertEqual((fix["action"], fix["label"]), ("allow", "Fix: restore the words"))
        self.assertIn("banter shelf", fix["say"])
        with mock.patch.object(app, "_s3_active", lambda: False):
            self.assertEqual(app.review_fix_plan(row)["label"], "Fix: rebuild from the capture")
        technical = self.store.get(self.store.record("recording_requirement", "No audio", reasons=["missing"],
                                                     technical=True)["id"])
        self.assertFalse(app.review_fix_plan(technical)["available"])


if __name__ == "__main__":
    unittest.main()
