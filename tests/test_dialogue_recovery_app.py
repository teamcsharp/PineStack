"""Exercise the actual app adapters without booting station services or data."""
import ast
import asyncio
import copy
import hashlib
import json
from contextvars import ContextVar
from pathlib import Path
import re
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import dialogue_recovery


FUNCTIONS = {
    "dialogue_entry", "dialogue_row_ready", "dialogue_row_viable", "shelf_put",
    "tint_retry_status", "tint_exhausted", "tint_retry_due", "_tint_retry_accepted",
    "_tint_retry_note", "_tint_recovery_begin", "_tint_recovery_lesson",
    "_dialogue_recovery_enqueue", "_dialogue_recovery_repair", "_dialogue_recovery_refused",
    "tint_recovery_step", "tint_recovery_status", "larder_prepare", "_s3_handoff_rows", "_s3_split_line",
    "_s3_handoff_entry", "_s3_recover_larder_candidates",
    "_dialogue_recovery_style_ready", "dialogue_tint_ready",
    "ask_model", "structured_turns_within", "whole_sentences", "banter_turns",
}
SOURCE = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
RECOVERY_GLOBAL_NAMES = (
    "DIALOGUE_RECOVERY_PATH", "_DIALOGUE_RECOVERY", "_DIALOGUE_RECOVERY_ACTIVE",
    "_DIALOGUE_RECOVERY_LOCK", "_DIALOGUE_RECOVERY_DIRTY", "_DIALOGUE_RECOVERY_FLUSHING",
)
RECOVERY_DECLARATIONS = {}
for name in RECOVERY_GLOBAL_NAMES:
    match = re.search(r"(?m)^" + re.escape(name) + r"\s*(?::[^\n=]+)?=", SOURCE)
    if match is None:
        continue
    tail = SOURCE[match.start():]
    end = re.search(r"(?m)^(?:@|(?:async )?def |class |[A-Za-z_]\w*\s*(?::[^\n=]+)?=)",
                    tail[tail.index("\n") + 1:])
    body = tail[:tail.index("\n") + 1 + end.start()] if end else tail
    RECOVERY_DECLARATIONS[name] = (match.start(), ast.parse(body).body[0])
FIRST_QUEUE_HELPER_POSITION = SOURCE.index("def _dialogue_recovery_save(")
# The full app also embeds several megabytes of browser source. Parse only
# these top-level adapter definitions so isolated tests stay cheap to run.
NODES = []
for name in sorted(FUNCTIONS):
    match = re.search(r"(?m)^(?:async )?def " + re.escape(name) + r"\(", SOURCE)
    if match is None:
        raise AssertionError("missing production adapter: " + name)
    tail = SOURCE[match.start():]
    end = re.search(r"(?m)^(?:@|(?:async )?def |class |[A-Za-z_]\w*\s*(?::[^\n=]+)?=)",
                    tail[tail.index("\n") + 1:])
    body = tail[:tail.index("\n") + 1 + end.start()] if end else tail
    NODES.append(ast.parse(body).body[0])
for node in NODES:
    node.decorator_list = []
CODE = compile(ast.fix_missing_locations(ast.Module(body=NODES, type_ignores=[])),
               "app.py recovery adapters", "exec")
del SOURCE, NODES, body, tail


def production_recovery_globals(data_path):
    """Use the real production initializers, so missing globals cannot hide."""
    missing = sorted(set(RECOVERY_GLOBAL_NAMES) - set(RECOVERY_DECLARATIONS))
    if missing:
        raise AssertionError("missing production recovery globals: " + ", ".join(missing))
    namespace = {"Any": object, "RLock": RLock, "data_path": data_path}
    declarations = [RECOVERY_DECLARATIONS[name][1] for name in RECOVERY_GLOBAL_NAMES]
    code = compile(ast.fix_missing_locations(ast.Module(body=declarations, type_ignores=[])),
                   "app.py recovery state initializers", "exec")
    exec(code, namespace)
    return {name: namespace[name] for name in RECOVERY_GLOBAL_NAMES}


class RecoveryStateInitializersTests(unittest.TestCase):
    def test_queue_state_is_declared_and_initialized_before_queue_helpers(self):
        data_path = Mock(side_effect=lambda name: Path("station-data") / name)
        state = production_recovery_globals(data_path)
        data_path.assert_called_once_with("dialogue_recovery.json")
        self.assertEqual(state["DIALOGUE_RECOVERY_PATH"], Path("station-data/dialogue_recovery.json"))
        self.assertEqual(state["_DIALOGUE_RECOVERY"], [])
        self.assertEqual(state["_DIALOGUE_RECOVERY_ACTIVE"], set())
        self.assertEqual(state["_DIALOGUE_RECOVERY_DIRTY"], [False])
        self.assertEqual(state["_DIALOGUE_RECOVERY_FLUSHING"], [False])
        self.assertTrue(all(position < FIRST_QUEUE_HELPER_POSITION
                            for position, node in RECOVERY_DECLARATIONS.values()))
        lock = state["_DIALOGUE_RECOVERY_LOCK"]
        self.assertTrue(lock.acquire(blocking=False))
        try:
            self.assertTrue(lock.acquire(blocking=False), "queue persistence requires a reentrant lock")
            lock.release()
        finally:
            lock.release()


class WritingDeferred(Exception):
    pass


class RecoveryAdaptersTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 1000.0
        self.ns = {
            "__builtins__": __builtins__, "Any": object, "copy": copy,
            "asyncio": asyncio, "dialogue_recovery": dialogue_recovery,
            "time": SimpleNamespace(time=lambda: self.now), "WritingDeferred": WritingDeferred,
            "_tint_retry_context": lambda entry, kind: "context",
            "_dialogue_recovery_save": Mock(),
            "row_unaired": lambda entry: not entry.get("aired_at"),
            "_dialogue_audio_drop": lambda entry: [entry.pop(k, None)
                for k in ("key", "keys", "takes", "prepared", "made", "seconds")],
            "TINT_DEFERRED_REST": 30.0, "_TINT_RECOVERY_STATE": {},
            "_SHELF": {}, "_LARDER": [], "_RADIO": {"on": True},
            "_LARDER_WRITING": [False], "TINT_FAMINE_SECONDS": 60,
            "_WRITING_DEFERRED": ContextVar("test_deferred", default=0),
            "dialogue_tint_required": lambda: True,
            "crystal_tint_holds": lambda: True,
            "tint_must_flow": lambda kind: False, "tint_coverage_ready": lambda report: False,
            "prepared_seconds": lambda: 1000,
            "tint_should_stop": lambda **kwargs: "",
            "prep_yielding": lambda: False, "_PREP_YIELD_WHY": [""],
            "writing_room_state": lambda: {},
            "committed_stock_ids": lambda **kwargs: set(),
            "tint_recovery_rows": lambda: [],
            "tint_retry_rest": lambda: 120,
            "alt_sid": lambda kind, row: row.get("sid", "normal"),
            "pipeline_log": Mock(),
            "_pantry_save": Mock(), "_larder_save": Mock(),
        }
        self.ns.update(production_recovery_globals(lambda name: Path("station-data") / name))
        exec(CODE, self.ns)

    def test_legacy_exhaustion_expires_and_never_retires_stock(self):
        entry = {"tint_retry_budget": {"context": "context", "exhausted": True,
                                      "exhausted_at": self.now - 59}}
        self.assertTrue(self.ns["tint_retry_status"](entry, "banter")["waiting"])
        self.now += 2
        self.assertTrue(self.ns["tint_retry_due"](entry, "banter"))
        self.assertFalse(self.ns["tint_exhausted"](entry))

    def test_three_distinct_attempts_cool_down_then_reenter_without_lifetime_cap(self):
        entry, operations, variations = {}, [], []
        for index in range(15):
            attempt = self.ns["_tint_recovery_begin"](entry)
            if not attempt["allow"]:
                self.now = entry["dialogue_recovery"]["cooldown_until"] + 1
                attempt = self.ns["_tint_recovery_begin"](entry)
            self.assertTrue(attempt["allow"])
            operations.append(attempt["operation"])
            variations.append(attempt["variation_id"])
            self.ns["_tint_retry_note"](entry, "context", 0,
                                       {"ok": False, "why": "same rejection"}, 1)
            self.now += 1
            if index == 2:
                self.assertTrue(self.ns["tint_retry_status"](entry, "banter")["waiting"])
        self.assertEqual(operations[:4], ["repair", "rewrite", "reroll", "rebuild"])
        self.assertEqual(len(set(variations)), 15)
        self.assertNotIn("exhausted", entry["tint_retry_budget"])
        self.assertTrue(entry["dialogue_recovery"]["stuck"])

    def test_writer_deferral_refunds_attempt_but_never_reuses_seed(self):
        entry = {}
        first = self.ns["_tint_recovery_begin"](entry)
        self.ns["_tint_retry_note"](entry, "context", 0, {"deferred": True}, 0)
        state = entry["dialogue_recovery"]
        self.assertEqual(state["attempt"], 0)
        self.assertEqual(state["failures"], 0)
        self.assertFalse(state["in_flight"])
        second = self.ns["_tint_recovery_begin"](entry)
        self.assertNotEqual(first["variation_id"], second["variation_id"])

    def entry(self):
        return {"script": "A: The copper plate vanished.\nB: Who moved that plate?",
                "prep_kind": "banter", "road": "gallery", "keys": ["invalid-old-audio"],
                "prepared": True, "dialogue_recovery_handle": {
                    "conversation_id": "conv-1", "mode": "active", "revision": 1}}

    def test_failed_round_is_deduplicated_and_audio_is_invalidated(self):
        entry = self.entry()
        self.assertTrue(self.ns["_dialogue_recovery_enqueue"](entry, None, "alignment failure"))
        self.assertTrue(self.ns["_dialogue_recovery_enqueue"](entry, None, "alignment failure"))
        self.assertEqual(len(self.ns["_DIALOGUE_RECOVERY"]), 1)
        self.assertNotIn("keys", entry)
        self.assertNotIn("prepared", entry)
        self.assertTrue(entry["dialogue_recovery_pending"])
        self.assertEqual(self.ns["_LARDER"], [])

    def test_status_helper_reads_real_module_queue_state_at_startup_and_after_admission(self):
        empty = self.ns["tint_recovery_status"]()
        self.assertEqual(empty["states"], {})
        self.assertEqual(empty["pending"], [])
        self.assertEqual(empty["attempts"], 0)
        entry = self.entry()
        self.ns["_dialogue_recovery_enqueue"](entry, None, "alignment failure")
        entry["dialogue_recovery"]["total_attempts"] = 6
        status = self.ns["tint_recovery_status"]()
        self.assertEqual(status["states"], {"handoff_required": 1})
        self.assertEqual(status["attempts"], 6)
        self.assertEqual(status["pending"][0]["attempts"], 6)
        self.assertEqual(status["pending"][0]["id"], "conv-1")
        self.assertEqual(status["pending"][0]["why"], "alignment failure")
        entry["dialogue_recovery"]["cooldown_until"] = self.now + 60
        self.assertEqual(self.ns["tint_recovery_status"]()["states"], {"cooldown": 1})
        self.assertEqual(self.ns["tint_recovery_status"]()["attempts"], 6)

    def test_saved_dictionary_stamp_can_enter_recovery_queue(self):
        entry = self.entry()
        stamp = entry.pop("dialogue_recovery_handle")
        self.assertTrue(self.ns["_dialogue_recovery_enqueue"](entry, stamp, "saved final handoff required", failed=False))
        self.assertEqual(entry["dialogue_recovery_handle"], stamp)
        self.assertEqual(self.ns["_DIALOGUE_RECOVERY"][0]["id"], stamp["conversation_id"])

    async def test_legacy_handoff_failure_enters_same_durable_queue(self):
        entry = self.entry()
        stamp = entry.pop("dialogue_recovery_handle")
        self.ns.update({"banter_turns": lambda *args: [("A", "The copper plate vanished."),
                                                        ("B", "Who moved that plate?")],
                        "_s3_handoff_rows": AsyncMock(side_effect=RuntimeError("same alignment refusal"))})
        with self.assertRaises(RuntimeError):
            await self.ns["_s3_handoff_entry"](entry, stamp)
        self.assertEqual(len(self.ns["_DIALOGUE_RECOVERY"]), 1)
        self.assertTrue(entry["dialogue_recovery_pending"])
        self.assertNotIn("keys", entry)

    async def test_saved_active_candidates_are_queued_but_committed_candidates_retire(self):
        active, committed = self.entry(), self.entry()
        active["system3"] = dict(active["dialogue_recovery_handle"])
        committed["system3"] = {**committed["dialogue_recovery_handle"], "conversation_id": "committed-2"}
        self.ns.update({"_LARDER": [active, committed],
                        "system3_handoff_candidate_status": AsyncMock(side_effect=[
                            {"ok": True}, {"ok": False, "permanent": True, "why": "committed ledger"}]),
                        "_s3_retire_handoff_candidate": Mock(return_value=1)})
        self.assertEqual(await self.ns["_s3_recover_larder_candidates"](), 1)
        self.assertTrue(active["dialogue_recovery_pending"])
        self.assertEqual([row["id"] for row in self.ns["_DIALOGUE_RECOVERY"]], ["conv-1"])
        self.ns["_s3_retire_handoff_candidate"].assert_called_once_with(committed, "committed ledger")

    async def test_saved_shelf_candidate_preserves_wrapper_provenance_in_queue(self):
        entry = self.entry()
        entry["system3"] = dict(entry["dialogue_recovery_handle"])
        wrapper = {"entry": entry, "image": "saved-copper.png", "at": 700}
        self.ns.update({"_SHELF": {"gallery": [wrapper]},
                        "system3_handoff_candidate_status": AsyncMock(return_value={"ok": True})})
        self.assertEqual(await self.ns["_s3_recover_larder_candidates"](), 0)
        item = self.ns["_DIALOGUE_RECOVERY"][0]
        self.assertEqual(item["kind"], "gallery")
        self.assertEqual(item["shelf_row"]["image"], "saved-copper.png")
        self.assertEqual(item["shelf_row"]["at"], 700)
        self.assertFalse(self.ns["dialogue_row_viable"]("gallery", wrapper))

    async def test_pending_provenance_cannot_be_ready_viable_or_recorded(self):
        entry = self.entry()
        entry["dialogue_recovery_pending"] = True
        wrapped = {"entry": entry}
        self.assertFalse(self.ns["dialogue_row_ready"]("gallery", wrapped))
        self.assertFalse(self.ns["dialogue_row_viable"]("gallery", wrapped))
        self.assertFalse(await self.ns["larder_prepare"](entry))

    def test_outer_wrapper_metadata_updates_queue_without_a_playable_ghost(self):
        entry = self.entry()
        self.ns["_dialogue_recovery_enqueue"](entry, None, "alignment failure")
        entry["prep_gallery"] = [{"image": "copper.png"}]
        self.ns["shelf_put"]("gallery", {"entry": entry, "image": "copper.png"})
        queued = self.ns["_DIALOGUE_RECOVERY"][0]
        self.assertEqual(queued["entry"]["prep_gallery"], [{"image": "copper.png"}])
        self.assertEqual(queued["shelf_row"]["image"], "copper.png")
        self.assertEqual(self.ns["_SHELF"], {})

    async def test_deferred_round_is_retained_without_a_creative_strike(self):
        entry = self.entry()
        self.ns["_dialogue_recovery_enqueue"](entry, None, "writer full", failed=False)
        item = self.ns["_DIALOGUE_RECOVERY"][0]
        self.assertEqual(entry["dialogue_recovery"]["failures"], 0)
        self.assertEqual(item["ready_at"], self.now + 30)
        self.ns["system3_recovery_bind_entry"] = AsyncMock(return_value=True)
        self.ns["_s3_handoff_entry"] = AsyncMock(side_effect=WritingDeferred("full"))
        self.assertFalse(await self.ns["_dialogue_recovery_repair"](item))
        self.assertEqual(entry["dialogue_recovery"]["failures"], 0)
        self.assertEqual(self.ns["_DIALOGUE_RECOVERY_ACTIVE"], set())

    async def test_failed_downstream_gate_invalidates_cached_success_for_next_variation(self):
        entry = self.entry()
        self.ns["_dialogue_recovery_enqueue"](entry, None, "alignment failure")
        item = self.ns["_DIALOGUE_RECOVERY"][0]
        self.ns.update({"_s3_handoff_entry": AsyncMock(return_value=True),
                        "system3_recovery_bind_entry": AsyncMock(return_value=True),
                        "brief_note": Mock(return_value={"checked": True, "ok": False, "why": "off source"}),
                        "dialogue_row_viable": Mock(return_value=False),
                        "system3_recovery_reject": AsyncMock(return_value={"active": True, "failures": 2})})
        self.assertFalse(await self.ns["_dialogue_recovery_repair"](item))
        self.ns["system3_recovery_reject"].assert_awaited_once_with(
            entry["dialogue_recovery_handle"], "off source")
        self.assertEqual(len(self.ns["_DIALOGUE_RECOVERY"]), 1)
        self.assertEqual(self.ns["_LARDER"], [])

    async def test_successful_review_promotes_exact_provenance_once(self):
        entry = self.entry()
        self.ns["_dialogue_recovery_enqueue"](entry, None, "alignment failure")
        item = self.ns["_DIALOGUE_RECOVERY"][0]
        item["shelf_row"] = {"image": "original-copper.png", "at": 700}
        self.ns.update({"_s3_handoff_entry": AsyncMock(return_value=True),
                        "system3_recovery_bind_entry": AsyncMock(return_value=True),
                        "brief_note": Mock(return_value={"checked": True, "ok": True}),
                        "dialogue_row_viable": Mock(return_value=True),
                        "dialogue_tint_ready": Mock(return_value=True),
                        "ensure_entry_tinted": AsyncMock(return_value=True),
                        "pantry_window": lambda: "",
                        "shelf_put": lambda kind, row: self.ns["_SHELF"].setdefault(kind, []).append(row)})
        self.assertTrue(await self.ns["_dialogue_recovery_repair"](item))
        self.assertEqual(self.ns["_DIALOGUE_RECOVERY"], [])
        self.assertNotIn("dialogue_recovery_pending", entry)
        self.assertEqual(len(self.ns["_SHELF"]["gallery"]), 1)
        self.assertEqual(self.ns["_SHELF"]["gallery"][0]["image"], "original-copper.png")
        self.assertEqual(self.ns["_SHELF"]["gallery"][0]["at"], 700)

    async def test_restarted_queue_updates_existing_shelf_copy_with_approved_words(self):
        entry = self.entry()
        entry["system3"] = dict(entry["dialogue_recovery_handle"])
        self.ns["_dialogue_recovery_enqueue"](entry, None, "alignment failure")
        item = self.ns["_DIALOGUE_RECOVERY"][0]
        stale = copy.deepcopy(entry)
        wrapper = {"entry": stale, "image": "current-copper.png", "at": 800,
                   "keys": ["obsolete-take"], "seconds": 9.0}
        item["shelf_row"] = {"image": "original-copper.png", "at": 700}
        self.ns.update({"_SHELF": {"gallery": [wrapper]},
                        "_s3_handoff_entry": AsyncMock(return_value=True),
                        "system3_recovery_bind_entry": AsyncMock(return_value=True),
                        "brief_note": Mock(return_value={"checked": True, "ok": True}),
                        "dialogue_row_viable": Mock(return_value=True),
                        "dialogue_tint_ready": Mock(return_value=True),
                        "ensure_entry_tinted": AsyncMock(return_value=True),
                        "pantry_window": lambda: ""})
        self.assertTrue(await self.ns["_dialogue_recovery_repair"](item))
        self.assertEqual(len(self.ns["_SHELF"]["gallery"]), 1)
        self.assertIs(wrapper["entry"], entry)
        self.assertNotIn("dialogue_recovery_pending", wrapper["entry"])
        self.assertEqual(wrapper["image"], "current-copper.png")
        self.assertEqual(wrapper["at"], 800)
        self.assertNotIn("keys", wrapper)
        self.assertEqual(wrapper["seconds"], 0.0)

    async def test_retired_candidate_cannot_be_released_with_identical_cached_text(self):
        entry = self.entry()
        entry["handoff_unavailable"] = {"why": "retired old identity"}
        self.ns["_dialogue_recovery_enqueue"](entry, None, "alignment failure")
        item = self.ns["_DIALOGUE_RECOVERY"][0]
        self.ns.update({"_s3_handoff_entry": AsyncMock(return_value=False),
                        "system3_recovery_bind_entry": AsyncMock(return_value=True),
                        "brief_note": Mock(return_value={"checked": True, "ok": True}),
                        "system3_recovery_reject": AsyncMock(return_value={"active": True})})
        self.assertFalse(await self.ns["_dialogue_recovery_repair"](item))
        self.assertIn("handoff_unavailable", entry)
        self.assertEqual(self.ns["_SHELF"], {})

    async def test_picker_alternates_runnable_normal_work_after_boosted_recovery(self):
        entry = self.entry()
        self.ns["_dialogue_recovery_enqueue"](entry, None, "alignment failure")
        normal = {"script": "A: Fresh work.", "prep_kind": "banter",
                  "tint_revalidation": {"state": "repair_required"}}
        self.ns.update({"tint_recovery_rows": lambda: [("banter", normal)],
                        "dialogue_tint_ready": lambda kind, row: False,
                        "dialogue_row_viable": lambda kind, row: True,
                        "_dialogue_recovery_repair": AsyncMock(return_value=False),
                        "ensure_shelf_row_tinted": AsyncMock(return_value=False),
                        "_pantry_save": Mock(), "_larder_save": Mock(),
                        "pantry_window": lambda: ""})
        await self.ns["tint_recovery_step"]()
        self.ns["_dialogue_recovery_repair"].assert_awaited_once()
        await self.ns["tint_recovery_step"]()
        self.ns["ensure_shelf_row_tinted"].assert_awaited_once_with("banter", normal, critical=True)

    async def test_optional_tint_budget_never_blocks_required_handoff_recovery(self):
        entry = self.entry()
        self.ns["_dialogue_recovery_enqueue"](entry, None, "alignment failure")
        self.ns.update({"tint_should_stop": Mock(return_value="hourly tint allowance exhausted"),
                        "tint_recovery_rows": Mock(),
                        "_dialogue_recovery_repair": AsyncMock(return_value=True),
                        "ensure_shelf_row_tinted": AsyncMock()})
        self.assertTrue(await self.ns["tint_recovery_step"]())
        self.ns["tint_should_stop"].assert_called_once_with(critical=True)
        self.ns["_dialogue_recovery_repair"].assert_awaited_once_with(self.ns["_DIALOGUE_RECOVERY"][0])
        self.ns["tint_recovery_rows"].assert_not_called()
        self.ns["ensure_shelf_row_tinted"].assert_not_awaited()

    async def test_optional_tint_budget_yields_when_no_handoff_is_queued(self):
        normal = {"script": "A: Fresh work.", "prep_kind": "banter",
                  "tint_revalidation": {"state": "repair_required"}}
        self.ns.update({"tint_should_stop": Mock(return_value="hourly tint allowance exhausted"),
                        "tint_recovery_rows": Mock(return_value=[("banter", normal)]),
                        "_dialogue_recovery_repair": AsyncMock(),
                        "ensure_shelf_row_tinted": AsyncMock()})
        self.assertFalse(await self.ns["tint_recovery_step"]())
        self.assertEqual(self.ns["_TINT_RECOVERY_STATE"]["why"], "hourly tint allowance exhausted")
        self.ns["tint_recovery_rows"].assert_not_called()
        self.ns["_dialogue_recovery_repair"].assert_not_awaited()
        self.ns["ensure_shelf_row_tinted"].assert_not_awaited()

    async def test_required_handoff_cooldown_is_reported_without_spending_an_attempt(self):
        entry = self.entry()
        self.ns["_dialogue_recovery_enqueue"](entry, None, "alignment failure")
        entry["dialogue_recovery"].update(cooldown_until=self.now + 60, total_attempts=6, attempt=3)
        before = copy.deepcopy(entry["dialogue_recovery"])
        self.ns.update({"tint_should_stop": Mock(return_value="hourly tint allowance exhausted"),
                        "tint_recovery_rows": Mock(),
                        "_dialogue_recovery_repair": AsyncMock(),
                        "ensure_shelf_row_tinted": AsyncMock()})
        self.assertFalse(await self.ns["tint_recovery_step"]())
        self.assertEqual(entry["dialogue_recovery"], before)
        self.ns["_dialogue_recovery_repair"].assert_not_awaited()
        self.ns["ensure_shelf_row_tinted"].assert_not_awaited()
        self.ns["tint_recovery_rows"].assert_not_called()
        reason = self.ns["_TINT_RECOVERY_STATE"]["why"]
        self.assertIn("final handoff", reason)
        self.assertIn("retry", reason)
        self.assertNotIn("hourly tint", reason)

    async def test_operator_interjection_still_yields_required_handoff_recovery(self):
        entry = self.entry()
        self.ns["_dialogue_recovery_enqueue"](entry, None, "alignment failure")
        self.ns.update({"prep_yielding": lambda: True,
                        "_PREP_YIELD_WHY": ["the operator is speaking"],
                        "tint_should_stop": Mock(),
                        "_dialogue_recovery_repair": AsyncMock()})
        self.assertFalse(await self.ns["tint_recovery_step"]())
        self.assertEqual(self.ns["_TINT_RECOVERY_STATE"]["why"], "the operator is speaking")
        self.assertEqual(len(self.ns["_DIALOGUE_RECOVERY"]), 1)
        self.ns["tint_should_stop"].assert_not_called()
        self.ns["_dialogue_recovery_repair"].assert_not_awaited()

    def style_entry(self):
        entry = self.entry()
        entry["dialogue_recovery_variant"] = {"style_level": 1, "variation_id": "new-variation"}
        entry["handoff_receipt"] = {"version": 1, "status": "ready",
            "final_digest": hashlib.sha256(entry["script"].encode()).hexdigest(),
            "recovery_variation_id": "new-variation"}
        return entry

    def test_style_relaxation_requires_current_script_and_same_completed_variation(self):
        entry = self.style_entry()
        self.assertTrue(self.ns["dialogue_tint_ready"]("banter", entry))
        entry["script"] += " Changed unreviewed text."
        self.assertFalse(self.ns["dialogue_tint_ready"]("banter", entry))
        entry = self.style_entry()
        entry["dialogue_recovery_variant"]["variation_id"] = "another-unfinished-attempt"
        self.assertFalse(self.ns["dialogue_tint_ready"]("banter", entry))
        entry = self.style_entry()
        entry["handoff_receipt"]["status"] = "disabled"
        self.assertFalse(self.ns["dialogue_tint_ready"]("banter", entry))

    def test_style_approval_preserves_news_brief_and_phone_contract_gates(self):
        entry = self.style_entry()
        self.ns.update({"_pantry_lifecycle": lambda: None,
                        "content_gate_enabled": lambda gate: True,
                        "_larder_current": lambda row: True,
                        "s3_binding_withheld": lambda row: "",
                        "dialogue_audio_ready": lambda kind, row: True,
                        "call_entry_contract": lambda row: False})
        entry["off_brief"] = True
        self.assertFalse(self.ns["dialogue_row_ready"]("news", {"entry": entry}))
        entry.pop("off_brief")
        self.assertFalse(self.ns["dialogue_row_ready"]("caller", {"entry": entry}))
        self.assertTrue(self.ns["dialogue_row_ready"]("banter", {"entry": entry}))

    def model_runtime(self, response):
        """Stub model admission and station surroundings, using the real wrapper."""
        settings = {"model": "test-writer", "temperature": 0.45, "max_tokens": 128,
                    "num_ctx": 32768, "top_p": 0.9,
                    "active_prompt": "test", "prompts": {"test": {"name": "Test direction"}}}
        self.ns.update({
            "re": re, "json": json,
            "time": SimpleNamespace(time=lambda: self.now, monotonic=lambda: self.now),
            "random": SimpleNamespace(uniform=lambda low, high: 0, randint=lambda low, high: 1),
            "gazette_prompt": SimpleNamespace(TOKEN=re.compile(r"NO_GAZETTE_TOKEN_IN_TEST")),
            "prompt_blocks_resolve": lambda prompt, mark: (prompt, []),
            "prompt_blocks_note": Mock(), "load_settings": lambda: settings,
            "dj_settings": lambda: {"reply_max_chars": 6500, "host_name": "Dill", "cohost_name": "Skip"},
            "writing_profile": lambda: {}, "box_depth": lambda: 0,
            "_ROUND_MARK": {}, "_mark_key": lambda: "test-round", "round_mark": Mock(),
            "_LINE_REVIEW_CONTEXT": ContextVar("test_model_review", default={}),
            "_CRYSTAL_LEARNING_WIRE": ContextVar("test_model_learning", default=None),
            "_SFX_RESERVE_WRITING": ContextVar("test_model_sfx", default=False),
            "_TINT_REPAIR_RESPONSES": ContextVar("test_model_tint", default=None),
            "model_ctx": lambda: 32768,
            "call_ollama": AsyncMock(return_value=response),
            "_SENTENCE_END": re.compile(r"[.!?…—][\"')\]]*"),
            "line_review_permits": Mock(return_value=False),
            "TINT_MARK_LINES": "HOW THAT WRITER WRITES", "TINT_MARK_FLAVOUR": "HOW THAT WORLD ACTUALLY TALKS",
            "segment_prompts": SimpleNamespace(find_in=lambda text: None),
            "_MODEL_CALLS": [], "airlog_model_call": Mock(), "task_note": Mock(),
            "writer_turn_clean": str.strip, "turn_edge_clean": str.strip,
        })
        return self.ns["ask_model"]

    async def test_actual_model_wrapper_raises_admission_deferral_for_both_handoff_kinds(self):
        ask = self.model_runtime({"deferred": True, "reason": "writer slots are full"})
        for kind in ("dialogue handoff", "dialogue recovery"):
            with self.subTest(kind=kind):
                self.ns["call_ollama"].reset_mock()
                with self.assertRaisesRegex(WritingDeferred, "writer slots are full"):
                    await ask("Write the next exchange.", mark={"kind": kind})
                self.ns["call_ollama"].assert_awaited_once()
                self.assertEqual(self.ns["call_ollama"].await_args.kwargs["purpose"], "station:" + kind)
                self.assertEqual(self.ns["_MODEL_CALLS"], [])

    async def test_actual_model_wrapper_preserves_all_labelled_lines_through_handoff_writer(self):
        import handoff_preparation as hp
        raw = "A: The gallery opens Friday.\nB: Shall we check the frames?\nA: We will check them together."
        ask = self.model_runtime({"message": {"content": raw}})
        request = {"mode": "recover_exchange", "char_budget": 150,
                   "planned_turns": [
                       {"turn_id": "p", "speaker": "A", "name": "Dill", "step": "open"},
                       {"turn_id": "q", "speaker": "B", "name": "Skip", "step": "respond"},
                       {"turn_id": "r", "speaker": "A", "name": "Dill", "step": "close",
                        "mandatory_closing": True}],
                   "participants": [{"actor_id": "A", "name": "Dill"}, {"actor_id": "B", "name": "Skip"}],
                   "subject": {"topic": "the gallery"}, "source_rows": [], "recovery": {}}
        output = await hp.write_turn(request, ask, str.strip)
        self.assertEqual(output, raw)
        self.assertEqual(len(output.splitlines()), 3)
        self.assertEqual([row.split(":", 1)[0] for row in output.splitlines()], ["A", "B", "A"])
        self.assertEqual(request["writing_receipt"]["raw_result"], raw)
        self.assertEqual(request["writing_receipt"]["clean_result"], raw)
        self.assertEqual(self.ns["_MODEL_CALLS"][0]["script"], raw)
        self.ns["call_ollama"].assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
