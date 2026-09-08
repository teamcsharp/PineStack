"""Bound admission and finish retained work without treating deferral as failure."""
import asyncio
import copy
import hashlib
import unittest
from contextlib import ExitStack
from unittest import mock

import app
import test_tint_round_pass as tint_fixture


class WritingCoordinationTests(unittest.IsolatedAsyncioTestCase):
    async def test_reasoning_is_per_call_and_defaults_to_station_fast_path(self):
        response = mock.Mock()
        response.json.return_value = {"message": {"content": "real result"}}
        client = mock.AsyncMock()
        client.__aenter__.return_value = client
        client.post.return_value = response
        with (mock.patch.object(app, "_OLLAMA_JOBS", {}),
              mock.patch.object(app, "_OLLAMA_ONE", {}),
              mock.patch.object(app, "_OLLAMA_GATE", asyncio.Semaphore(2)),
              mock.patch.object(app.httpx, "AsyncClient", return_value=client)):
            base = dict(model="model", messages=[], temperature=.3, max_tokens=768)
            await app.call_ollama(**base)
            await app.call_ollama(**base, thinking=True)
            await app.call_ollama(**base)
        self.assertEqual([call.kwargs["json"]["think"] for call in client.post.call_args_list],
                         [False, True, False])
        self.assertTrue(all(call.kwargs["json"]["options"]["num_predict"] == 768
                            for call in client.post.call_args_list))

    async def test_tint_admission_is_bounded_and_every_waiter_is_visible(self):
        entered, release = asyncio.Event(), asyncio.Event()
        response = mock.Mock(); response.json.return_value = {"message": {"content": "real result"}}
        async def post(*_args, **_kwargs):
            entered.set(); await release.wait(); return response
        client = mock.AsyncMock(); client.__aenter__.return_value = client; client.post.side_effect = post
        with (mock.patch.object(app, "_OLLAMA_JOBS", {}), mock.patch.object(app, "_OLLAMA_DEFERRED", {}),
              mock.patch.object(app, "_OLLAMA_DEFERRED_CATEGORIES", {}), mock.patch.object(app, "_OLLAMA_ONE", {}),
              mock.patch.object(app, "_OLLAMA_GATE", asyncio.Semaphore(2)),
              mock.patch.object(app.httpx, "AsyncClient", return_value=client)):
            async def write():
                return await app.call_ollama(model="model", messages=[], temperature=.5,
                                              max_tokens=30, purpose="station:tint round")
            first = asyncio.create_task(write()); await entered.wait()
            second = asyncio.create_task(write()); await asyncio.sleep(0)
            refused = await asyncio.gather(write(), write(), write())
            self.assertTrue(all(row.get("deferred") for row in refused))
            state = app.writing_room_state()
            self.assertEqual((state["active"], state["waiting"]), (1, 1))
            self.assertEqual(state["tint_limit_per_model"], 2)
            self.assertEqual({row["category"] for row in state["jobs"]}, {"tint"})
            self.assertEqual(state["deferred_by_category"]["model:tint"], 3)
            self.assertEqual(client.post.await_count, 1)
            release.set(); await asyncio.gather(first, second)
            self.assertEqual(app._OLLAMA_JOBS, {})

    async def test_deferred_first_batch_does_not_record_an_empty_output_rejection(self):
        units = [("A", "The copper plate must reach the station before midnight."),
                 ("B", "The station can accept the copper plate at its north door.")]
        source = "\n".join(f"{m}: {s}" for m, s in units)
        fixture = tint_fixture.TintRoundPassTests()
        patches = fixture.tint_patches(True, [], [])
        with ExitStack() as stack:
            for patch in patches: stack.enter_context(patch)
            stack.enter_context(mock.patch.object(app, "banter_turns", return_value=units))
            stack.enter_context(mock.patch.object(app, "_crystal_round_first_pass",
                new=mock.AsyncMock(side_effect=app.WritingDeferred("writer full"))))
            capture = stack.enter_context(mock.patch.object(app, "line_review_capture"))
            result = await app.crystal_tint(source, "banter", critical=True)
        self.assertTrue(result["deferred"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["script"], "")
        self.assertEqual(result["progress"]["source"], hashlib.sha1(source.encode()).hexdigest())
        capture.assert_not_called()

    async def test_deferred_turn_preserves_completed_and_unvisited_candidates_and_deadline(self):
        units = [("A", "The first original statement requires a copper plate."),
                 ("B", "The second original statement requests the plate before midnight."),
                 ("A", "The final original statement confirms the station north door.")]
        source = "\n".join(f"{m}: {s}" for m,s in units)
        rows = [{"marker": m, "source": hashlib.sha1(s.encode()).hexdigest(),
                 "text": "Good retained first" if i==0 else "Bad retained middle" if i==1 else "Good retained tail"}
                for i,(m,s) in enumerate(units)]
        progress = {"source": hashlib.sha1(source.encode()).hexdigest(), "turns": copy.deepcopy(rows)}
        fixture = tint_fixture.TintRoundPassTests()
        with ExitStack() as stack:
            for patch in fixture.tint_patches(True, rows, [app.WritingDeferred("writer full")]):
                stack.enter_context(patch)
            stack.enter_context(mock.patch.object(app, "banter_turns", return_value=units))
            stack.enter_context(mock.patch.object(app, "tint_evaluate", side_effect=lambda _s,c,*a,**k:
                {"ok": c.startswith("Good"), "faults": [] if c.startswith("Good") else ["meaning"]}))
            stack.enter_context(mock.patch.object(app, "_PREP_DEADLINE", [123.0]))
            capture = stack.enter_context(mock.patch.object(app, "line_review_capture"))
            result = await app.crystal_tint(source, "banter", progress=progress, critical=True)
            self.assertEqual(app._PREP_DEADLINE[0], 123.0)
        self.assertTrue(result["deferred"])
        self.assertEqual([r["text"] for r in result["progress"]["turns"]], [r["text"] for r in rows])
        self.assertFalse(result["ok"])
        capture.assert_not_called()

    async def test_deferred_second_repass_retains_the_first_repass_success(self):
        units = [("A", "Source first"), ("B", "Source second"), ("A", "Source third")]
        rows = [{"marker": m, "source": hashlib.sha1(s.encode()).hexdigest(),
                 "text": "Good first" if i==0 else "Bad candidate"} for i,(m,s) in enumerate(units)]
        with (mock.patch.object(app, "ask_model", new=mock.AsyncMock(
                side_effect=["2: Good newly repaired second\n3: Bad candidate",
                             app.WritingDeferred("writer full")])),
              mock.patch.object(app, "tint_evaluate", side_effect=lambda _s,c,*a,**k:
                {"ok": c.startswith("Good"), "faults": [] if c.startswith("Good") else ["meaning"]}),
              mock.patch.object(app, "tint_should_stop", return_value=""),
              mock.patch.object(app, "line_review_capture") as capture,
              mock.patch.object(app, "pipeline_log"), mock.patch.object(app, "tint_seen")):
            with self.assertRaises(app.WritingDeferred) as raised:
                await app._crystal_round_repass(units, rows, "prompt", "world", [], [], "model", "banter")
        self.assertEqual(raised.exception.turns[1]["text"], "Good newly repaired second")
        self.assertEqual(raised.exception.turns[2]["text"], "")
        self.assertEqual(raised.exception.turns[2]["rejected_candidate"], "Bad candidate")
        self.assertFalse(raised.exception.turns[2]["evaluation"]["ok"])
        self.assertTrue(all(call.args[0] != "tint_structure" for call in capture.call_args_list))

    async def test_paused_and_caller_floor_overrides_finish_viable_committed_work_first(self):
        for paused, floor in ((True, False), (False, True), (True, True)):
            with self.subTest(paused=paused, floor=floor), ExitStack() as stack:
                patches = {
                    "_SHELF": {"caller": [{"entry": {"script": "A: Saved host.\nC: Saved caller."}}]},
                    "shelf_unvoiced": lambda _k: 0, "commitment_write_needed": lambda _k: False,
                    "committed_stock_ids": lambda *_a,**_k: {"existing"}, "alt_sid": lambda *_a: "existing",
                    "dialogue_row_viable": lambda *_a: True, "dialogue_row_ready": lambda *_a: False,
                    "radio_paused": lambda: paused, "hour_short_kinds": lambda: ["caller"],
                    "story_bank_short": lambda: floor, "prep_note": mock.Mock(),
                    "prep_context_set": mock.Mock(), "prep_context_clear": mock.Mock(),
                }
                for name,value in patches.items(): stack.enter_context(mock.patch.object(app,name,value))
                writer = stack.enter_context(mock.patch.object(app,"prep_round",new=mock.AsyncMock(return_value=True)))
                self.assertFalse(await app._prep_one_work("caller"))
                writer.assert_not_awaited()

    async def test_unusable_committed_work_does_not_prevent_a_needed_replacement(self):
        with (mock.patch.object(app,"_SHELF",{"caller":[{"entry":{"script":"Broken original"}}]}),
              mock.patch.object(app,"shelf_unvoiced",return_value=0),
              mock.patch.object(app,"commitment_write_needed",return_value=False),
              mock.patch.object(app,"committed_stock_ids",return_value={"broken"}),
              mock.patch.object(app,"alt_sid",return_value="broken"),
              mock.patch.object(app,"dialogue_row_viable",return_value=False),
              mock.patch.object(app,"radio_paused",return_value=True),
              mock.patch.object(app,"hour_short_kinds",return_value=["caller"]),
              mock.patch.object(app,"prep_note"),mock.patch.object(app,"prep_context_set"),
              mock.patch.object(app,"prep_context_clear"),
              mock.patch.object(app,"prep_round",new=mock.AsyncMock(return_value=True)) as writer):
            self.assertTrue(await app._prep_one_work("caller"))
            writer.assert_awaited_once_with("caller")

    async def test_batched_repairs_do_not_repeat_the_nested_per_line_repair_stack(self):
        fixture = tint_fixture.TintRoundPassTests()
        units = [("A", fixture.SOURCE), ("B", fixture.SOURCE)]
        source = "\n".join(f"{m}: {s}" for m,s in units)
        rows = [{"marker": m, "source": hashlib.sha1(s.encode()).hexdigest(),
                 "text": fixture.TINTED if i == 0 else fixture.BAD} for i,(m,s) in enumerate(units)]
        model = mock.AsyncMock(return_value=fixture.BAD)
        async def nested_repair(*_args, **_kwargs):
            await model("initial per-line rewrite")
            await model("evaluator-directed repair")
            return fixture.BAD
        with ExitStack() as stack:
            for patch in fixture.tint_patches(True, rows, nested_repair): stack.enter_context(patch)
            stack.enter_context(mock.patch.object(app,"banter_turns",return_value=units))
            stack.enter_context(mock.patch.object(app,"_crystal_round_repass",
                new=mock.AsyncMock(return_value=(rows, True))))
            stack.enter_context(mock.patch.object(app,"line_review_capture"))
            result = await app.crystal_tint(source,"banter",critical=True)
        self.assertEqual(model.await_count, 2, "The completed batch already supplied both retry rounds")
        self.assertTrue(result["progress"]["turns"][1]["cut"])
        self.assertEqual(result["progress"]["turns"][0]["text"], fixture.TINTED)
        self.assertFalse(result["progress"]["turns"][1]["evaluation"]["ok"])
        self.assertNotIn(fixture.BAD, result["script"])

    async def test_first_pass_propagates_admission_denial_without_false_empty_rejection(self):
        with (mock.patch.object(app,"ask_model",new=mock.AsyncMock(side_effect=app.WritingDeferred("writer full"))),
              mock.patch.object(app,"dj_settings",return_value={**app.DEFAULT_DJ}),
              mock.patch.object(app,"line_review_capture") as capture):
            with self.assertRaises(app.WritingDeferred):
                await app._crystal_round_first_pass("A: Original first.\nB: Original second.",
                    [("A","Original first."),("B","Original second.")], "prompt", "world", [], [], "model")
        capture.assert_not_called()

    async def test_independent_paused_banter_producer_also_finishes_assigned_work_first(self):
        radio = {"on": True}
        async def tick(_delay):
            radio["on"] = False  # Run one real keeper iteration, without waiting.
        with (mock.patch.object(app, "_RADIO", radio),
              mock.patch.object(app, "_LARDER", [{"at": 0.0, "script": "A: Already written."}]),
              mock.patch.object(app, "_LARDER_WRITING", [False]),
              mock.patch.object(app, "_BOX_DOWN", {"until": 0}),
              mock.patch.object(app, "_BOX_HOLD", []),
              mock.patch.object(app, "radio_paused", return_value=True),
              mock.patch.object(app, "row_unaired", return_value=True),
              mock.patch.object(app, "_larder_current", return_value=True),
              mock.patch.object(app, "dj_settings", return_value={**app.DEFAULT_DJ}),
              mock.patch.object(app, "prepare_target_seconds", return_value=21600),
              mock.patch.object(app, "larder_cap", return_value=100),
              mock.patch.object(app, "dialogue_row_viable", return_value=True),
              mock.patch.object(app, "prep_has_assigned_work", return_value=True) as assigned,
              mock.patch.object(app, "commitment_write_needed") as fresh_demand,
              mock.patch.object(app.asyncio, "sleep", side_effect=tick)):
            await app.larder_keeper()
        assigned.assert_called_once_with("banter")
        fresh_demand.assert_not_called()


if __name__ == "__main__":
    unittest.main()
