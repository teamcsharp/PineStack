"""Recording queue progress without engines, models, live state or media."""
import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import app


class RecordingProgressTests(unittest.IsolatedAsyncioTestCase):
    def test_restart_releases_raw_and_nested_owners_but_retains_their_work(self):
        raw = {"text": "Every original word is retained.", "voice": "original-cast",
               "tinting": True, "preparing": True, "key": "keep-audio",
               "brief": {"checked": True, "ok": True},
               "tint_progress": {"turns": [{"text": "Partial successful rewrite"}]},
               "tint_revalidation": {"state": "repairing", "attempts": 4, "last_attempt": 1000, "source": "keep-proof"}}
        nested = {"brief": {"checked": True, "ok": True}, "entry": {
            "script": "A: Whole accepted script.", "preparing": True, "tinting": True,
            "made": 1, "keys": ["original-take"],
            "tint_revalidation": {"state": "repairing", "attempts": 2}}}
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            shelf = root / "shelf.json"
            shelf.write_text(json.dumps({"ad": [raw], "manager": [nested]}), encoding="utf-8")
            original = shelf.read_bytes()
            for name, value in {"_PANTRY": {}, "_SHELF": {}, "PANTRY_PATH": root / "empty.json",
                                "SHELF_PATH": shelf, "SCHED_POS_PATH": root / "no-position.json",
                                "pipeline_log": mock.Mock(), "brief_note": mock.Mock(side_effect=AssertionError("Stored grade stays intact"))}.items():
                stack.enter_context(mock.patch.object(app, name, value))
            app._pantry_load()
            restored = app._SHELF["ad"][0]
            round_ = app._SHELF["manager"][0]["entry"]
            for item in (restored, round_):
                self.assertFalse(item.get("preparing"))
                self.assertFalse(item.get("tinting"))
                self.assertEqual(item["tint_revalidation"]["state"], "waiting")
                self.assertIn("restart", item["tint_revalidation"]["why"])
            self.assertEqual(restored["text"], raw["text"])
            self.assertEqual(restored["voice"], "original-cast")
            self.assertEqual(restored["key"], "keep-audio")
            self.assertEqual(restored["tint_progress"], raw["tint_progress"])
            self.assertEqual(restored["tint_revalidation"]["attempts"], 4)
            self.assertEqual(restored["tint_revalidation"]["source"], "keep-proof")
            self.assertEqual(round_["keys"], ["original-take"])
            self.assertTrue(round_["partial"])
            self.assertEqual(shelf.read_bytes(), original)

    def test_restart_keeps_completed_or_failed_tint_evidence_unchanged(self):
        for state in ("repaired", "repair_required", "waiting"):
            entry = {"tint_revalidation": {"state": state, "why": "Original evaluator result"}}
            before = json.loads(json.dumps(entry))
            app._unstrand(entry)
            self.assertEqual(entry, before)

    def booths(self, prepare, stop=lambda: ""):
        stack = ExitStack()
        for name, value in {
            "radio_paused": mock.Mock(return_value=True),
            "recording_booths": mock.Mock(return_value={"prep_limit": 2}),
            "prep_should_stop": mock.Mock(side_effect=stop),
            "voice_engine_for": mock.Mock(side_effect=lambda voice: voice),
            "larder_prepare": mock.AsyncMock(side_effect=prepare),
            "station_flow_event": mock.Mock(),
        }.items():
            stack.enter_context(mock.patch.object(app, name, value))
        return stack

    async def test_independent_booth_takes_free_script_before_waiting_on_busy_head(self):
        pool = [{"id": 1}, {"id": 2}]
        active, starts = set(), []
        overlap = asyncio.Event()

        async def prepare(entry, only_voice=""):
            self.assertNotIn(entry["id"], active)
            active.add(entry["id"])
            starts.append((only_voice, entry["id"]))
            if len(active) == 2:
                overlap.set()
            try:
                await asyncio.wait_for(overlap.wait(), 0.15)
                entry["made"] = entry.get("made", 0) + 1
                entry["prepared"] = entry["made"] == 2
            finally:
                active.remove(entry["id"])

        with self.booths(prepare):
            result = await app.recording_parallel_sitting(pool, ["xtts", "piper"], 30)
        self.assertTrue(overlap.is_set(), "Idle second script was stranded behind the first script's lock")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["finished"], 2)
        self.assertEqual(sum(actor["finished"] for actor in result["actors"]), 2)
        self.assertEqual(set(starts), {("xtts", 1), ("xtts", 2), ("piper", 1), ("piper", 2)})

    async def test_waiting_for_script_ownership_does_not_spend_actor_render_budget(self):
        now, seen = [1000.0], []
        entry = {"id": 1}

        async def prepare(row, only_voice=""):
            seen.append((only_voice, app._PREP_TASK_DEADLINE.get() - now[0]))
            if only_voice == "xtts":
                await asyncio.sleep(0)
                now[0] += 20.0  # A real engine can finish one long line past its boundary.
            row["made"] = row.get("made", 0) + 1
            row["prepared"] = row["made"] == 2

        def stop():
            deadline = app._PREP_TASK_DEADLINE.get()
            return "expired" if deadline and now[0] > deadline else ""

        with self.booths(prepare, stop), mock.patch.object(app.time, "time", side_effect=lambda: now[0]):
            result = await app.recording_parallel_sitting([entry], ["xtts", "piper"], 15)
        self.assertEqual([voice for voice, _budget in seen], ["xtts", "piper"])
        self.assertGreaterEqual(seen[1][1], 14.9)
        self.assertEqual(result["finished"], 1)
        self.assertEqual(app._PREP_TASK_DEADLINE.get(), 0)

    async def test_cancelling_parallel_sitting_releases_every_owned_script(self):
        active = set()
        entered = asyncio.Event()

        async def prepare(row, only_voice=""):
            active.add(row["id"])
            entered.set()
            try:
                await asyncio.Future()
            finally:
                active.remove(row["id"])

        with self.booths(prepare):
            task = asyncio.create_task(app.recording_parallel_sitting([{"id": 1}, {"id": 2}], ["xtts", "piper"], 30))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(active)
        self.assertEqual(app._PREP_TASK_DEADLINE.get(), 0)

    async def test_cancelled_render_releases_engine_admission_and_context(self):
        started = asyncio.Event()

        async def render(*_args, **_kwargs):
            self.assertEqual(app._ENGINE_PREP[0], 1)
            self.assertEqual(app._PREP_RENDER_ENGINE.get(), "piper")
            started.set()
            await asyncio.Future()

        with ExitStack() as stack:
            for name, value in {
                "_ENGINE_PREP": [0], "_ENGINE_LIVE": [0], "_ENGINE_PREP_BY": {},
                "configured_radio_voice": mock.Mock(return_value="original"),
                "voice_engine_for": mock.Mock(return_value="piper"),
                "pantry_get": mock.Mock(return_value=None), "radio_paused": mock.Mock(return_value=True),
                "render_relief": mock.Mock(return_value=False), "prep_should_stop": mock.Mock(return_value=""),
                "voice_effect_pick": mock.Mock(return_value={}), "performance_vector": mock.Mock(return_value={}),
                "dj_settings": mock.Mock(return_value={}), "voice_render_any": mock.AsyncMock(side_effect=render),
            }.items():
                stack.enter_context(mock.patch.object(app, name, value))
            task = asyncio.create_task(app.prep_render_line("Every word stays.", "dj", "original", "ad"))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(app._ENGINE_PREP[0], 0)
            self.assertEqual(app._ENGINE_PREP_BY, {})
            self.assertEqual(app._PREP_RENDER_ENGINE.get(), "")

    def reads(self, rows, ensure):
        stack = ExitStack()
        self.render = mock.AsyncMock(return_value={"key": "durable", "seconds": 3.5})
        self.tint = mock.AsyncMock(side_effect=ensure)
        for name, value in {
            "_SHELF": {"ad": rows},
            "committed_stock_ids": mock.Mock(return_value={row["id"] for row in rows}),
            "alt_sid": mock.Mock(side_effect=lambda kind, row: row["id"]),
            "dialogue_row_ready": mock.Mock(return_value=False),
            "dialogue_row_viable": mock.Mock(return_value=True),
            "dialogue_tint_ready": mock.Mock(side_effect=lambda kind, row: bool(row.get("tinted"))),
            "ensure_shelf_row_tinted": self.tint,
            "prep_render_line": self.render,
            "prep_should_stop": mock.Mock(return_value=""),
            "tint_retry_rest": mock.Mock(return_value=120),
            "pipeline_log": mock.Mock(),
        }.items():
            stack.enter_context(mock.patch.object(app, name, value))
        stack.enter_context(mock.patch.object(app.time, "time", return_value=1000.0))
        return stack

    async def test_unfinished_tint_at_head_does_not_block_recordable_later_read(self):
        head = {"id": "head", "text": "Unfinished draft"}
        ready = {"id": "ready", "text": "Every accepted word survives.", "tinted": True, "voice": "original"}
        with self.reads([head, ready], lambda kind, row, **kw: row is ready):
            self.assertTrue(await app.prep_voice_pending("ad"))
        self.render.assert_awaited_once_with(ready["text"], "dj", "original", kind="ad")
        self.assertNotIn("key", head)
        self.assertEqual(ready["key"], "durable")
        self.assertEqual(self.tint.await_count, 1)

    async def test_normal_read_preparer_leaves_exact_approved_text_to_review_worker(self):
        approved = {"id": "review", "text": "Exact approved candidate", "review_shelf_pending": True}
        normal = {"id": "normal", "text": "Another accepted read", "tinted": True}
        with self.reads([approved, normal], lambda kind, row, **kw: row is normal):
            self.assertTrue(await app.prep_voice_pending("ad"))
        self.tint.assert_awaited_once_with("ad", normal, critical=True)
        self.assertEqual(approved["text"], "Exact approved candidate")
        self.assertTrue(approved["review_shelf_pending"])
        self.assertNotIn("key", approved)

    async def test_failed_tint_respects_rest_and_does_not_starve_untried_read(self):
        resting = {"id": "rest", "text": "Keep this failed draft", "tint_tried": 950.0}
        fresh = {"id": "fresh", "text": "A later draft"}
        with self.reads([resting, fresh], lambda kind, row, **kw: row is fresh):
            self.assertTrue(await app.prep_voice_pending("ad"))
        self.tint.assert_awaited_once_with("ad", fresh, critical=True)
        self.assertEqual(resting["text"], "Keep this failed draft")

    async def test_repeated_render_failure_rotates_to_other_committed_ready_text(self):
        rows = [{"id": "one", "text": "First words", "tinted": True},
                {"id": "two", "text": "Second words", "tinted": True}]
        with self.reads(rows, lambda *_args, **_kw: True):
            self.render.side_effect = [None, {"key": "second-audio", "seconds": 2}]
            self.assertFalse(await app.prep_voice_pending("ad"))
            self.assertTrue(await app.prep_voice_pending("ad"))
        self.assertEqual([call.args[0] for call in self.render.await_args_list], ["First words", "Second words"])
        self.assertNotIn("key", rows[0])
        self.assertEqual(rows[1]["key"], "second-audio")


if __name__ == "__main__":
    unittest.main()
