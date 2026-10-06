"""Final dialogue handoffs through a stand-in station and a temporary ledger.

These tests never import app.py, call a production model, or open station data.
"""
import asyncio
import copy
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import system3
import system3_handoff
import system3_runtime
from test_system3_runtime import FakeStation, settle


DJ = {"host_name": "Dill", "cohost_name": "Skip", "third_name": "Billy"}


class HandoffRuntimeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.station = FakeStation(tmp.name)
        app = FastAPI()
        system3_runtime.install(app, self.station)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.rt = self.station["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        self.assertTrue(self.rt.ready)
        self.rt.settings = self.rt.apply_settings({"mode": "active", "test_seed": "handoff-runtime"})

    def handle(self, road="banter", status="planned"):
        config = copy.deepcopy(self.rt.config)
        inputs = {"road": road, "seats": ["A", "B", "D"],
                  "names": {"A": "Dill", "B": "Skip", "D": "Billy"},
                  "roles": {"A": "dj", "B": "cohost", "D": "third"},
                  "turns": 4, "target_seconds": 60, "subject": {"topic": "the missing photograph"},
                  "availability": {}, "speakerbox_rates": {}, "bank": True}
        conv = system3.plan_scene(inputs, config, self.rt.settings, conversation_id="test-handoff")
        conv["mode"] = "active"
        conv["status"] = status
        h = system3_runtime.Handle(self.rt, conv, config, True)
        h.turns = len(conv["turns"])
        h.rolls = [{"turn": i + 1, "roll": i + 10} for i in range(h.turns)]
        self.rt.remember(conv)
        self.rt.persist(conv)
        settle()
        return h

    @staticmethod
    def rows(handle):
        phrases = ["The photograph vanished from the table.",
                   "Someone moved the evidence before lunch.",
                   "The gallery staff should check the doorway.",
                   "Tomorrow we can ask the manager about it.",
                   "That question deserves a concrete answer."]
        return [(t["speaker"], phrases[i % len(phrases)] + " Detail %d." % i)
                for i, t in enumerate(handle.conv["turns"])]

    @staticmethod
    async def ready(conv, config, rows, candidates, writer, kind=""):
        conv["handoff"] = {"status": "ready", "policy_hash": system3_handoff.policy_hash(config), "output_rows": list(rows)}
        return {"rows": list(rows), "changed": False, "traces": [], "status": "ready"}

    def finalize(self, handle, rows=None, **options):
        return asyncio.run(self.station["system3_handoff_exchange"](
            handle, rows or self.rows(handle), AsyncMock(), dj=DJ, **options))

    def test_short_final_text_and_policy_receipt_are_saved(self):
        h = self.handle()
        stable = h.conv
        writer = AsyncMock(side_effect=AssertionError("a short turn needs no model"))
        result = asyncio.run(self.station["system3_handoff_exchange"](h, self.rows(h), writer, dj=DJ))
        self.assertEqual(result["status"], "ready", result)
        self.assertIs(h.conv, stable)
        self.assertFalse(result["changed"])
        self.assertEqual([t["text"] for t in h.conv["turns"]], [text for _seat, text in result["rows"]])
        self.assertTrue(all(t["status"] == "generated" for t in h.conv["turns"]))
        self.assertTrue(asyncio.run(self.station["system3_handoff_policy_current"](h)))
        writer.assert_not_awaited()
        settle()
        saved = self.rt.store.conversation(h.id)
        self.assertEqual(saved["handoff"]["policy_hash"], system3_handoff.policy_hash(h.config))
        self.assertTrue(any(e["family"] == "HANDOFF" for e in saved["decision_events"]))

    def test_final_handoff_accepts_gate_drops_and_preserves_roll_identity(self):
        h = self.handle()
        original = copy.deepcopy(h.conv["turns"])
        rows = self.rows(h)
        h.conv["turn_gate"] = {"turns": [{"turn_id": original[1]["turn_id"], "turn": 1, "state": "dropped"}],
                              "output_turn_ids": [t["turn_id"] for i, t in enumerate(original) if i != 1]}
        surviving_rows = [row for i, row in enumerate(rows) if i != 1]
        writer = AsyncMock(return_value="I found the missing frame near the doorway, which explains the empty wall.")
        result = asyncio.run(self.station["system3_handoff_exchange"](
            h, surviving_rows, writer, dj=DJ, protected=[0]))
        self.assertEqual(result["status"], "ready", result)
        ids = [t["turn_id"] for i, t in enumerate(original) if i != 1]
        self.assertEqual([t["turn_id"] for t in h.conv["turns"]], ids)
        self.assertEqual([r["roll"] for r in h.rolls], [i + 10 for i in range(len(original)) if i != 1])
        self.assertEqual([r["turn"] for r in h.rolls], list(range(1, len(ids) + 1)))
        self.assertTrue(h.conv["turns"][0]["handoff_protected"])
        self.assertEqual(h.conv["handoff_gate"]["dropped_turn_ids"], [original[1]["turn_id"]])
        self.assertEqual(h.turns, len(ids))

    def test_unrecorded_writer_omissions_remain_refused(self):
        h = self.handle()
        before = copy.deepcopy(h.conv)
        result = self.finalize(h, self.rows(h)[:-1])
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["rows"], [])
        # Missing rows still cannot air. Recovery accounting is durable, but
        # failed rewrites must not alter the original plan or its words.
        recovery = h.conv.get("dialogue_recovery") or {}
        self.assertEqual({key: value for key, value in h.conv.items()
                          if key != "dialogue_recovery"}, before)
        self.assertTrue(recovery.get("active"))
        self.assertEqual(recovery.get("attempt"), 3)

    def test_long_final_copy_becomes_a_bounded_exchange_and_replay_is_idempotent(self):
        h = self.handle()
        h.config["handoff"] = dict(system3_handoff.config_of(h.config), continue_probability=0)
        h.conv["config_hash"] = system3.config_hash(h.config)
        rows = self.rows(h)
        sentence = "The exhibit opens next Friday, and the curator needs the photos arranged before the guest tour arrives. "
        rows[0] = (rows[0][0], (sentence * 12).strip())
        requests = []
        replies = ["I found a spare frame in the storage cupboard and we can use that today.",
                   "The visitors should hear about the missing label before the doors open.",
                   "Someone at the desk can phone the artist and check the actual deadline.",
                   "The delivery van is outside, so the staff have another job to finish.",
                   "Our next job is to find the receipt and send it to the manager."]

        async def writer(request):
            requests.append(request)
            return replies[(len(requests) - 1) % len(replies)]

        result = asyncio.run(self.station["system3_handoff_exchange"](h, rows, writer, dj=DJ))
        self.assertEqual(result["status"], "ready", result)
        self.assertTrue(result["changed"])
        self.assertTrue(requests)
        self.assertTrue(any(t.get("handoff_parent") for t in h.conv["turns"]))
        self.assertLessEqual(len(result["rows"]), len(rows) + 3)
        self.assertTrue(all(len(text) <= 800 for _seat, text in result["rows"]))
        draws = h.conv["handoff_draws"]
        no_writer = AsyncMock(side_effect=AssertionError("the final exchange must not roll twice"))
        again = asyncio.run(self.station["system3_handoff_exchange"](h, result["rows"], no_writer, dj=DJ))
        self.assertEqual(again["status"], "ready", again)
        self.assertEqual(again["rows"], result["rows"])
        self.assertEqual(h.conv["handoff_draws"], draws)
        no_writer.assert_not_awaited()

    def test_single_original_read_can_handoff_and_late_bind_preserves_all_parts(self):
        config = copy.deepcopy(self.rt.config)
        config["handoff"] = dict(system3_handoff.config_of(config), continue_probability=0)
        self.rt.config = config
        inputs = {"road": "ad_spot", "seats": ["A"], "names": {"A": "Dill"},
                  "roles": {"A": "dj"}, "turns": 1, "subject": {"topic": "the exhibit"}, "availability": {}}
        conv = system3.new_conversation(inputs, config, self.rt.settings, conversation_id="single-handoff")
        system3.plan_line(conv, config, inputs)
        conv["mode"] = "active"
        h = system3_runtime.LineHandle(self.rt, conv, True)
        h.stamp = system3.turn_stamp(conv, conv["turns"][0])
        self.rt.remember(conv)
        self.rt.persist(conv)
        settle()
        whole = ("The gallery needs another framed photograph before the guest tour arrives on Friday. " * 12).strip()
        requests = []

        async def writer(request):
            requests.append(request)
            return "I found the spare frame in the cupboard, so we can finish this before lunch."

        result = asyncio.run(self.station["system3_handoff_exchange"](
            h.stamp, [("A", whole)], writer, dj=DJ, kind="ad"))
        self.assertEqual(result["status"], "ready", result)
        self.assertTrue(result["changed"])
        self.assertGreater(len(result["rows"]), 1)
        self.assertTrue(requests)
        self.assertEqual(len({t["turn_id"] for t in conv["turns"]}), len(result["rows"]))
        before = copy.deepcopy(conv["actual"])
        self.station["system3_bind_line"](h, whole)
        self.assertEqual(conv["actual"], before)
        self.assertEqual([t["text"] for t in conv["turns"]], [text for _seat, text in result["rows"]])

    def test_one_available_voice_shortens_long_copy_when_nobody_can_take_over(self):
        h = self.handle()
        h.config["handoff"] = dict(system3_handoff.config_of(h.config), continue_probability=0)
        h.conv["config_hash"] = system3.config_hash(h.config)
        h.conv["turns"] = [h.conv["turns"][0]]
        h.conv["turns"][0].update(speaker="A", name="Dill")
        whole = ("The host needs the photographs on the gallery wall before the visitors arrive this afternoon. " * 14).strip()
        writer = AsyncMock(side_effect=AssertionError("there is no second voice to write"))
        result = asyncio.run(self.station["system3_handoff_exchange"](
            h, [("A", whole)], writer, dj={"host_name": "Dill", "cohost_name": "Skip"}, away="cohost"))
        self.assertEqual(result["status"], "ready", result)
        self.assertTrue(result["changed"])
        self.assertEqual(len(result["rows"]), 1)
        self.assertLessEqual(len(result["rows"][0][1]), 800)
        self.assertEqual(h.conv["turns"][0]["length_trace"]["status"], "no_speaker_shortened")
        writer.assert_not_awaited()

    def test_missing_active_conversation_or_unloaded_runtime_refuses_source(self):
        stamp = {"conversation_id": "missing-active-conversation", "turn_id": "missing-turn", "mode": "active"}
        result = self.finalize(stamp, [("A", "This source must wait for its missing active plan.")])
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["rows"], [])
        h = self.handle()
        self.rt.ready = False
        result = self.finalize(h)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["rows"], [])
        self.assertIn("not loaded", result["why"])

    def test_expanded_plan_keeps_stable_object_and_original_roll_positions(self):
        h = self.handle()
        stable = h.conv
        original_ids = [t["turn_id"] for t in h.conv["turns"]]

        async def expand(conv, config, rows, candidates, writer, kind=""):
            child = copy.deepcopy(conv["turns"][0])
            child.update(turn_id=h.id + ":handoff-child", speaker="D", name="Billy", decisions=[],
                         handoff_of=original_ids[0])
            conv["turns"].insert(1, child)
            result_rows = [rows[0], ("D", "I checked the hallway and found the missing envelope.")] + rows[1:]
            got = await self.ready(conv, config, result_rows, candidates, writer, kind)
            got["changed"] = True
            return got

        with patch.object(system3_handoff, "finalize_exchange", expand):
            result = self.finalize(h)
        self.assertEqual(result["status"], "ready", result)
        self.assertIs(h.conv, stable)
        self.assertEqual(h.turns, len(original_ids) + 1)
        self.assertEqual([r["turn"] for r in h.rolls], [1] + list(range(3, len(original_ids) + 2)))
        self.assertEqual([t["index"] for t in h.conv["turns"]], list(range(h.turns)))
        entry = {"script": "\n".join("%s: %s" % row for row in result["rows"])}
        self.station["system3_bind_entry"](entry, h)
        self.assertEqual(entry["system3"]["turns"]["1"], h.id + ":handoff-child")
        self.assertEqual(len(entry["turn_dice"]), h.turns)
        self.assertTrue(all(t["status"] == "generated" for t in h.conv["turns"]))

    def test_protected_ids_and_indexes_and_writer_evidence_are_preserved(self):
        h = self.handle()
        ids = [t["turn_id"] for t in h.conv["turns"]]
        evidence = [{"draft_chars": 120, "final_chars": len(text), "source": "actual final writer"}
                    for _seat, text in self.rows(h)]

        async def inspect(conv, config, rows, candidates, writer, kind=""):
            self.assertTrue(conv["turns"][0]["handoff_protected"])
            self.assertTrue(conv["turns"][1]["handoff_protected"])
            return await self.ready(conv, config, rows, candidates, writer, kind)

        with patch.object(system3_handoff, "finalize_exchange", inspect):
            result = self.finalize(h, protected=[0, ids[1]], assembly_trace=evidence)
        self.assertEqual(result["status"], "ready", result)
        self.assertEqual(h.conv["handoff"]["assembly"], evidence)
        self.assertEqual(h.conv["turns"][1]["length_trace"]["assembly"], evidence[1])

    def test_model_failure_rolls_back_plan_and_returns_no_playable_rows(self):
        h = self.handle()
        before = copy.deepcopy(h.conv)

        async def broken(conv, *args, **kwargs):
            conv["turns"][0]["text"] = "A mutation that must never escape."
            raise RuntimeError("writer unavailable")

        with patch.object(system3_handoff, "finalize_exchange", broken):
            result = self.finalize(h)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["rows"], [])
        self.assertEqual(h.conv, before)
        self.assertFalse(self.rt._handoff_busy)
        settle()
        saved = self.rt.store.conversation(h.id)
        self.assertTrue(any(e["family"] == "HANDOFF" and e.get("status") == "refused"
                            for e in saved["observations_air"]))

    def test_unresolved_extra_plan_is_refused(self):
        h = self.handle()
        before = copy.deepcopy(h.conv)

        async def incomplete(conv, config, rows, candidates, writer, kind=""):
            conv["turns"].append(copy.deepcopy(conv["turns"][0]))
            return await self.ready(conv, config, rows, candidates, writer, kind)

        with patch.object(system3_handoff, "finalize_exchange", incomplete):
            result = self.finalize(h)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["rows"], [])
        self.assertEqual(h.conv, before)

    def test_commit_during_model_await_refuses_transaction(self):
        h = self.handle()
        before = copy.deepcopy(h.conv)

        async def committed(conv, config, rows, candidates, writer, kind=""):
            self.station["system3_observe_ledger"](21, "temporary-test", [
                {"line_id": "temp-line", "who": "dj", "text": rows[0][1],
                 "system3": {"conversation_id": h.id, "turn_id": h.conv["turns"][0]["turn_id"]}}], "banter")
            return await self.ready(conv, config, rows, candidates, writer, kind)

        with patch.object(system3_handoff, "finalize_exchange", committed):
            result = self.finalize(h)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["rows"], [])
        self.assertEqual(h.conv, before)

    def test_changed_conversation_during_writer_await_is_not_overwritten(self):
        h = self.handle()

        async def changed(conv, config, rows, candidates, writer, kind=""):
            h.conv["external_change"] = "newer director state"
            return await self.ready(conv, config, rows, candidates, writer, kind)

        with patch.object(system3_handoff, "finalize_exchange", changed):
            result = self.finalize(h)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(h.conv["external_change"], "newer director state")
        self.assertNotIn("handoff", h.conv)

    def test_stamp_resolves_saved_plan_and_keeps_pinned_config(self):
        h = self.handle()
        self.rt.store.save_config(h.config, "test pinned config")
        old_hash = h.conv["config_hash"]
        self.rt.recent.clear()
        newer = copy.deepcopy(h.config)
        newer["handoff"] = dict(system3_handoff.config_of(newer), enabled=False)
        self.rt.config = newer
        stamp = {"conversation_id": h.id, "config_hash": old_hash, "revision": 1}

        async def inspect(conv, config, rows, candidates, writer, kind=""):
            self.assertEqual(system3.config_hash(config), old_hash)
            self.assertTrue(system3_handoff.config_of(config)["enabled"])
            return await self.ready(conv, config, rows, candidates, writer, kind)

        with patch.object(system3_handoff, "finalize_exchange", inspect):
            result = self.finalize(stamp, self.rows(h))
        self.assertEqual(result["status"], "ready", result)
        self.assertIn(h.id, self.rt.recent)

    def test_prepared_chapter_can_finalize_before_commit(self):
        h = self.handle(road="ad_spot", status="chapter_ready")
        with patch.object(system3_handoff, "finalize_exchange", self.ready):
            result = self.finalize(h)
        self.assertEqual(result["status"], "ready", result)

    def test_committed_or_airing_exchange_cannot_be_rewritten(self):
        h = self.handle(status="chapter_airing")
        engine = AsyncMock()
        with patch.object(system3_handoff, "finalize_exchange", engine):
            result = self.finalize(h)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["rows"], [])
        engine.assert_not_awaited()

    def test_ineligible_exchange_records_an_explicit_skip(self):
        h = self.handle(road="caller")
        engine = AsyncMock()
        rows = [("C", text) for _seat, text in self.rows(h)]
        with patch.object(system3_handoff, "finalize_exchange", engine):
            result = self.finalize(h, rows)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["rows"], rows)
        self.assertIsNone(result["traces"][0]["rng"])
        engine.assert_not_awaited()

    def test_caller_original_is_protected_while_studio_replies_are_eligible(self):
        h = self.handle(road="caller")
        h.conv["turns"][0]["speaker"] = "C"
        rows = self.rows(h)

        async def inspect(conv, config, rows, candidates, writer, kind=""):
            self.assertTrue(conv["turns"][0]["handoff_protected"])
            self.assertFalse(conv["turns"][1].get("handoff_protected", False))
            return await self.ready(conv, config, rows, candidates, writer, kind)

        with patch.object(system3_handoff, "finalize_exchange", inspect):
            result = self.finalize(h, rows)
        self.assertEqual(result["status"], "ready", result)
        self.assertIn("outside", h.conv["turns"][0]["length_trace"]["exemption_reason"])

    def test_sfx_voice_is_excluded_when_dialogue_parser_cannot_bind_its_seat(self):
        h = self.handle()

        async def inspect(conv, config, rows, candidates, writer, kind=""):
            sam = next(p for p in candidates if p["seat"] == "S")
            self.assertFalse(sam["available"])
            self.assertIn("parser", sam["unavailable_reason"])
            return await self.ready(conv, config, rows, candidates, writer, kind)

        with patch.object(system3_handoff, "finalize_exchange", inspect):
            result = asyncio.run(self.station["system3_handoff_exchange"](
                h, self.rows(h), AsyncMock(), dj=dict(DJ, drop_voice="temporary-test-voice")))
        self.assertEqual(result["status"], "ready", result)
        self.assertEqual(h.conv["handoff"]["candidate_exclusions"][0]["seat"], "S")

    def test_policy_requires_a_final_receipt(self):
        h = self.handle()
        self.assertFalse(asyncio.run(self.station["system3_handoff_policy_current"](h)))

    def test_final_turn_and_its_transport_chunk_are_ready_but_other_words_are_not(self):
        h = self.handle()
        with patch.object(system3_handoff, "finalize_exchange", self.ready):
            result = self.finalize(h)
        self.assertEqual(result["status"], "ready", result)
        turn = h.conv["turns"][0]
        stamp = system3.turn_stamp(h.conv, turn)
        final = turn["text"]
        check = self.station["system3_handoff_turn_ready"]
        self.assertTrue(asyncio.run(check(stamp, final)))
        self.assertTrue(asyncio.run(check(stamp, "photograph vanished from the table.")))
        self.assertFalse(asyncio.run(check(stamp, final + " This was the old dropped tail.")))
        self.assertFalse(asyncio.run(check(dict(stamp, turn_id="missing-turn"), final)))
        self.assertFalse(asyncio.run(check(dict(stamp, revision=99), final)))
        turn["text"] = "Later words that did not pass the final dialogue review."
        self.assertFalse(asyncio.run(check(stamp, turn["text"])))

    def test_protected_body_remains_ready_and_missing_or_empty_stamps_do_not(self):
        h = self.handle()
        rows = self.rows(h)
        protected = "The exact sponsor copy must remain unchanged for the approved station recording. " * 12
        rows[0] = (rows[0][0], protected.strip())
        result = self.finalize(h, rows, protected=[0])
        self.assertEqual(result["status"], "ready", result)
        stamp = system3.turn_stamp(h.conv, h.conv["turns"][0])
        check = self.station["system3_handoff_turn_ready"]
        self.assertTrue(asyncio.run(check(stamp, protected.strip())))
        self.assertFalse(asyncio.run(check({}, protected)))
        self.assertFalse(asyncio.run(check(stamp, "")))
        self.assertFalse(asyncio.run(check(stamp, "123")))

    def test_old_standalone_source_is_not_ready_after_its_tail_was_dropped(self):
        h = self.handle()
        rows = self.rows(h)
        old = rows[0][1] + " A long old tail should never be silently replayed."
        stamp = system3.turn_stamp(h.conv, h.conv["turns"][0])
        self.assertFalse(asyncio.run(self.station["system3_handoff_turn_ready"](stamp, old)))
        with patch.object(system3_handoff, "finalize_exchange", self.ready):
            result = self.finalize(h, rows)
        self.assertEqual(result["status"], "ready", result)
        self.assertFalse(asyncio.run(self.station["system3_handoff_turn_ready"](stamp, old)))

    def test_section_is_validated_saved_and_reviewable(self):
        headers = {"Authorization": "Bearer k"}
        view = self.client.get("/api/system3/config", headers=headers).json()["config"]["handoff"]
        self.assertEqual(view["thresholds"], [250, 350, 450, 550])
        saved = self.client.put("/api/system3/config/section/handoff", json={"enabled": False}, headers=headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertFalse(saved.json()["handoff"]["enabled"])
        invalid = self.client.put("/api/system3/config/section/handoff",
                                  json={"continue_probability": 2}, headers=headers)
        self.assertEqual(invalid.status_code, 400)


if __name__ == "__main__":
    unittest.main()
