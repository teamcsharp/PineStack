import asyncio
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import app
from station_flow import FlowJournal


class RecordingExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in (("_ENGINE_PREP", [0]), ("_ENGINE_LIVE", [0]),
                            ("_ENGINE_PREP_BY", {}), ("_PREP_DEADLINE", [0.0]),
                            ("_RENDER_BACKLOG", []), ("_BACKLOG_BUSY", [False])):
            self.stack.enter_context(mock.patch.object(app, name, value))
        self.stack.enter_context(mock.patch.object(app, "station_flow_event"))
        self.stack.enter_context(mock.patch.object(app, "pipeline_log"))

    # 2026-09-09 (#1157): these two pinned the ARITHMETIC of ENGINE_BUDGET 3
    # rather than the two rules underneath it, so raising the budget - the
    # change that lets preparation bank audio at all - read as a break. The
    # rules are: live always keeps two slots, and one engine renders one
    # thing at a time. Both are now pinned against the dial, not the number.
    ENGINES = ("xtts", "f5", "piper", "vox", "tone", "reed", "brass", "hush")

    def test_live_reserves_two_slots_and_never_exceeds_capacity(self):
        with mock.patch.object(app, "radio_paused", return_value=False):
            limit = app.recording_booths()["prep_limit"]
            self.assertEqual(limit, max(1, app.ENGINE_BUDGET - 2),
                             "live keeps two slots whatever the budget is")
            taken = list(self.ENGINES[:limit])
            for name in taken:
                self.assertTrue(app.engine_prep_take(name), name)
            self.assertFalse(app.engine_prep_take("one-too-many"))
            app.engine_live_enter()
            app.engine_live_enter()
            self.assertEqual(app.engine_inflight(), limit + 2)
            self.assertFalse(app.engine_prep_take("still-no"))
            for name in taken:
                app.engine_prep_give(name)
            self.assertEqual(app._ENGINE_PREP_BY, {})

    def test_paused_engines_are_independent_but_same_engine_is_serial(self):
        with mock.patch.object(app, "radio_paused", return_value=True):
            limit = app.recording_booths()["prep_limit"]
            self.assertEqual(limit, app.ENGINE_BUDGET,
                             "off air there is no live road to reserve for")
            self.assertTrue(app.engine_prep_take("xtts"))
            self.assertFalse(app.engine_prep_take("xtts"),
                             "one engine renders one thing at a time")
            for name in self.ENGINES[1:limit]:
                self.assertTrue(app.engine_prep_take(name), name)
            self.assertFalse(app.engine_prep_take("one-too-many"))
            self.assertEqual(app.engine_inflight(), limit)

    def test_generic_production_booth_is_exclusive_with_named_prep_lanes(self):
        with mock.patch.object(app, "radio_paused", return_value=True):
            self.assertTrue(app.engine_prep_take())
            self.assertFalse(app.engine_prep_take("xtts"))
            app.engine_prep_give()
            self.assertTrue(app.engine_prep_take("xtts"))
            self.assertFalse(app.engine_prep_take())

    async def test_expired_worker_deadline_does_not_stop_an_independent_booth(self):
        started = asyncio.Event()
        inspected = asyncio.Event()

        async def expired_worker():
            app._PREP_DEADLINE[0] = 1.0
            started.set()
            await inspected.wait()
            self.assertEqual(app.prep_should_stop(), "this task has used the room it was given")
            app._PREP_DEADLINE[0] = 0.0

        async def independent_worker():
            await started.wait()
            self.assertEqual(app._PREP_DEADLINE[0], 0.0)
            self.assertEqual(app.prep_should_stop(), "")
            inspected.set()

        with (mock.patch.object(app, "_PREP_DEADLINE", app._PreparationDeadline()),
              mock.patch.object(app, "prep_yielding", return_value=False)):
            token = app._PREP_TASK_DEADLINE.set(0.0)
            try:
                await asyncio.gather(expired_worker(), independent_worker())
                self.assertEqual(app._PREP_DEADLINE[0], 0.0)
            finally:
                app._PREP_TASK_DEADLINE.reset(token)

    def test_full_inventory_counts_other_actor_and_repeated_positions(self):
        plan = [("Yes.", "one", "dj"), ("I understand.", "two", "cohost"),
                ("Yes.", "one", "dj")]
        ready = {app.pantry_key(text, voice, "piper"): {"seconds": 2.0}
                 for text, voice, who in plan}
        entry = {"made": 99, "seconds": 999, "keys": ["stale"]}
        with (mock.patch.object(app, "voice_engine_for", return_value="piper"),
              mock.patch.object(app, "pantry_get", side_effect=ready.get)):
            self.assertEqual(app.reconcile_round_takes(entry, plan), 3)
            self.assertEqual([r["i"] for r in entry["takes"]], [0, 1, 2])
            self.assertEqual(len(entry["keys"]), 2)
            self.assertEqual(entry["seconds"], 6.0)
            ready.pop(app.pantry_key("I understand.", "two", "piper"))
            self.assertEqual(app.reconcile_round_takes(entry, plan), 2)
            self.assertEqual([r["i"] for r in entry["takes"]], [0, 2])

    async def test_actor_sittings_complete_a_round_without_recounting_seconds(self):
        plan = [("First thought.", "one", "dj"), ("A reply.", "two", "cohost")]
        ready, rendered = {}, []
        entry = {"script": "A: First thought.\nB: A reply.",
                 "freshened": True, "prep_kind": "banter"}

        async def render(text, voice, engine, **kwargs):
            rendered.append((text, voice))
            return {"path": "/media/ready.wav", "seconds": 2.0}

        def put(key, clip, **kwargs):
            ready[key] = clip

        with ExitStack() as stack:
            replacements = {"ensure_entry_tinted": mock.AsyncMock(return_value=True),
                "session_voices": mock.AsyncMock(return_value={"dj": "one", "cohost": "two"}),
                "banter_turns": mock.Mock(return_value=[("A", "First thought."), ("B", "A reply.")]),
                "_round_chunks": mock.Mock(return_value=plan),
                "round_line_plan": mock.Mock(return_value=[]),
                "voice_engine_for": mock.Mock(return_value="piper"),
                "pantry_get": mock.Mock(side_effect=ready.get),
                "pantry_put": mock.Mock(side_effect=put),
                "voice_render_any": mock.AsyncMock(side_effect=render),
                "render_relief": mock.Mock(return_value=False),
                "prep_should_stop": mock.Mock(return_value=""),
                "radio_paused": mock.Mock(return_value=True),
                "dj_settings": mock.Mock(return_value={}),
                "voice_effect_pick": mock.Mock(return_value={}),
                "performance_vector": mock.Mock(return_value={}),
                "prep_note": mock.Mock(), "round_stats_take": mock.Mock(return_value={})}
            for name, replacement in replacements.items():
                stack.enter_context(mock.patch.object(app, name, replacement))
            self.assertFalse(await app.larder_prepare(entry, only_voice="one"))
            self.assertEqual(entry["made"], 1)
            self.assertTrue(await app.larder_prepare(entry, only_voice="two"))
        self.assertEqual(entry["made"], 2)
        self.assertEqual(entry["seconds"], 4.0)
        self.assertEqual(rendered, [("First thought.", "one"), ("A reply.", "two")])

    async def test_parallel_booths_overlap_without_owning_same_script(self):
        pool = [{"id": 1}, {"id": 2}]
        working, active, maximum = set(), 0, 0

        async def prepare(entry, only_voice=""):
            nonlocal active, maximum
            self.assertNotIn(id(entry), working)
            working.add(id(entry))
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            entry["made"] = int(entry.get("made") or 0) + 1
            entry["prepared"] = entry["made"] == 2
            working.remove(id(entry))
            active -= 1

        with (mock.patch.object(app, "radio_paused", return_value=True),
              mock.patch.object(app, "prep_should_stop", return_value=""),
              mock.patch.object(app, "voice_engine_for", side_effect=lambda v: v),
              mock.patch.object(app, "larder_prepare", side_effect=prepare)):
            result = await app.recording_parallel_sitting(pool, ["xtts", "piper"], 30)
        self.assertEqual(maximum, 2)
        self.assertEqual(result["finished"], 2)
        self.assertEqual(result["lines_made"], 4)
        self.assertEqual(app._PREP_TASK_DEADLINE.get(), 0)

    def test_recorded_caller_is_in_prepared_transcript_offsets(self):
        with (mock.patch.object(app, "_prep_intro_pad", side_effect=lambda rows, name: rows),
              mock.patch.object(app, "spoken_text", side_effect=lambda t: t),
              mock.patch.object(app, "sentence_chunks", side_effect=lambda t, **kw: [t])):
            rows = app.round_line_plan([("A", "Host."), ("C", "Caller."), ("B", "Reply.")],
                                       "Alex", {"dj": "one", "caller": "two", "cohost": "three"})
        self.assertEqual([r["line_from"] for r in rows], [0, 1, 2])
        self.assertFalse(any(r["live"] for r in rows))

    def test_unheard_hold_shelf_is_not_trimmed_by_age_or_count(self):
        rows = [{"id": str(i), "ts": 1, "bytes": 1} for i in range(30)]
        with mock.patch.object(app, "_BOX_HOLD", list(rows)):
            app._hold_trim()
            self.assertEqual(app._BOX_HOLD, rows)

    def test_render_debt_survives_restart_and_only_completed_line_retires(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(app, "RENDER_BACKLOG_PATH", Path(folder) / "debt.json"):
                app._RENDER_BACKLOG.extend({"id": str(i), "text": f"Line {i}"} for i in range(50))
                app.render_backlog_save()
                app._RENDER_BACKLOG.clear()
                app.render_backlog_load()
                self.assertEqual(len(app._RENDER_BACKLOG), 50)
                app.render_backlog_ack("1")
                self.assertEqual(app._RENDER_BACKLOG[0]["id"], "0")
                self.assertEqual(app._RENDER_BACKLOG[1]["id"], "2")
                app._RENDER_BACKLOG.clear()
                app.render_backlog_load()
                self.assertEqual(len(app._RENDER_BACKLOG), 49)

    def test_repeated_miss_issues_reversible_work_order_and_respects_operator_pin(self):
        learned = {"caller": {"miss_streak": 3}}
        report = {"id": "hour3", "roads": {"caller": {"attainment": .1, "met": False}}}
        with (mock.patch.object(app, "_HOUR_LEARNING", learned),
              mock.patch.object(app, "orch_policy", return_value="none"),
              mock.patch.object(app, "orch_apply", return_value="caller built first") as apply):
            actions = app.coord_recovery_strategy(report)
        apply.assert_called_once_with("drive:caller")
        self.assertTrue(actions[0]["applied"])
        self.assertTrue(learned["caller"]["recovery_drive"])
        with (mock.patch.object(app, "_HOUR_LEARNING", learned),
              mock.patch.object(app, "orch_policy", return_value="gallery"),
              mock.patch.object(app, "orch_apply") as apply):
            self.assertEqual(app.coord_recovery_strategy(report), [])
        apply.assert_not_called()

    def test_operator_reaffirming_same_road_takes_ownership_of_recovery_pin(self):
        auto_policy = {"value": "caller", "at": 10, "revision": "auto"}
        operator_policy = {"value": "caller", "at": 10, "revision": "operator"}
        learned = {"caller": {"recovery_drive": True, "recovery_drive_policy": auto_policy}}
        report = {"id": "met", "roads": {"caller": {"met": True, "attainment": 1}}}
        with (mock.patch.object(app, "_HOUR_LEARNING", learned),
              mock.patch.object(app, "_ORCH", {"policy": {"drive_road": operator_policy}}),
              mock.patch.object(app, "orch_policy", return_value="caller"),
              mock.patch.object(app, "orch_apply") as apply):
            self.assertEqual(app.coord_recovery_strategy(report), [])
        apply.assert_not_called()
        self.assertNotIn("recovery_drive", learned["caller"])

    def test_controller_releases_only_the_exact_policy_it_owned(self):
        policy = {"value": "caller", "at": 10, "revision": "auto"}
        learned = {"caller": {"recovery_drive": True, "recovery_drive_policy": dict(policy)}}
        report = {"id": "met", "roads": {"caller": {"met": True, "attainment": 1}}}
        with (mock.patch.object(app, "_HOUR_LEARNING", learned),
              mock.patch.object(app, "_ORCH", {"policy": {"drive_road": policy}}),
              mock.patch.object(app, "orch_policy", return_value="caller"),
              mock.patch.object(app, "orch_apply", return_value="pin cleared") as apply):
            self.assertEqual(len(app.coord_recovery_strategy(report)), 1)
        apply.assert_called_once_with("drive:none")

    async def test_long_line_cannot_claim_success_with_missing_audio_piece(self):
        original = app.voice_render_any
        with (mock.patch.object(app, "VOICE_MAX_CHARS", 10),
              mock.patch.object(app, "sentence_chunks", return_value=["first", "second"]),
              mock.patch.object(app, "voice_render_any", side_effect=[{"path": "/media/first.wav", "seconds": 2}, None]),
              mock.patch.object(app, "_media_file", return_value=Path("first.wav")),
              mock.patch.object(app, "_call_concat_blocking") as concat,
              mock.patch.object(app, "_store_media") as store):
            result = await original("first second beyond cap", "one", "piper")
        self.assertIsNone(result)
        concat.assert_not_called()
        store.assert_not_called()

    async def test_concat_failure_cannot_substitute_first_chunk_for_whole_line(self):
        original = app.voice_render_any
        with (mock.patch.object(app, "VOICE_MAX_CHARS", 10),
              mock.patch.object(app, "sentence_chunks", return_value=["first", "second"]),
              mock.patch.object(app, "voice_render_any", side_effect=[
                  {"path": "/media/first.wav", "seconds": 2},
                  {"path": "/media/second.wav", "seconds": 2}]),
              mock.patch.object(app, "_media_file", side_effect=lambda p: Path(p)),
              mock.patch.object(app, "_call_concat_blocking", return_value=None),
              mock.patch.object(app, "_store_media") as store):
            result = await original("first second beyond cap", "one", "piper")
        self.assertIsNone(result)
        store.assert_not_called()

    async def test_failed_recovery_head_never_publishes_tail_before_completion(self):
        app._RENDER_BACKLOG.extend([
            {"id": "a", "text": "Question", "who": "dj"},
            {"id": "b", "text": "Answer", "who": "cohost"}])
        clip = {"path": "/media/take.wav", "sig": "test", "seconds": 2.0}
        with (mock.patch.object(app, "radio_paused", return_value=False),
              mock.patch.object(app, "_floor_take", return_value=False),
              mock.patch.object(app, "_floor_drop"),
              mock.patch.object(app, "_RADIO", {"voice_clips": [], "chat": []}),
              mock.patch.object(app, "_PAGE_DELIVERIES", {}),
              mock.patch.object(app, "_PAGE_AIR_UNTIL", [0.0]),
              mock.patch.object(app, "voice_render_any", return_value=clip),
              mock.patch.object(app, "_media_file", return_value=Path("take.wav")),
              mock.patch.object(app, "render_backlog_save"),
              mock.patch.object(app, "render_backlog_top")):
            await app.render_backlog_drain()
            await app.render_backlog_drain()
            self.assertEqual([r["row_id"] for r in app._RADIO["voice_clips"]], ["a"])
            app._PAGE_DELIVERIES[app._RENDER_BACKLOG[0]["delivery_id"]]["state"] = "error"
            await app.render_backlog_drain()
            self.assertEqual([r["row_id"] for r in app._RADIO["voice_clips"]], ["a", "a"])
            app.render_backlog_ack("a")
            await app.render_backlog_drain()
            self.assertEqual([r["row_id"] for r in app._RADIO["voice_clips"]], ["a", "a", "b"])

    def speech_fixture(self, add_response=None):
        clip = {"path": "/media/take.wav", "sig": "test", "seconds": .1}
        replacements = {"dj_settings": mock.Mock(return_value=dict(app.DEFAULT_DJ)),
            "_RADIO": {"voice_to": "here", "chat": [], "on": True},
            "_TALK_CUT": [0], "_PREMAKE_GATE": asyncio.Semaphore(2),
            "session_voices": mock.AsyncMock(return_value={"dj": "one", "cohost": "two"}),
            "fresh_pool_top": mock.Mock(), "render_backlog_top": mock.Mock(),
            "dialogue_tint_required": mock.Mock(return_value=False),
            "tint_coverage_ready": mock.Mock(return_value=False),
            "spoken_text": mock.Mock(side_effect=lambda t: t),
            "names_only": mock.Mock(return_value=True),
            "is_binned": mock.Mock(return_value=False),
            "looks_english": mock.Mock(return_value=True),
            "minutes_only": mock.Mock(return_value=True),
            "seat_reseat": mock.Mock(side_effect=lambda who: who),
            "rerun_check": mock.Mock(return_value={"block": False}),
            "rerun_note": mock.Mock(), "phrase_setup": mock.Mock(return_value={"n": 5}),
            "phrase_grams": mock.Mock(return_value=set()),
            "performance_vector": mock.Mock(return_value={}),
            "sentence_chunks": mock.Mock(side_effect=lambda t, **kw: t.split("|")),
            "inject_disfluencies": mock.Mock(side_effect=lambda t, vec, **kw: t),
            "breath_for": mock.Mock(return_value=""),
            "seat_away_who": mock.Mock(return_value=""),
            "add_listening_responses": mock.Mock(side_effect=add_response or (lambda rows, *a, **kw: rows)),
            "voice_engine_for": mock.Mock(return_value="piper"),
            "pantry_get": mock.Mock(return_value=clip),
            "take_note": mock.Mock(), "voice_effect_pick": mock.Mock(return_value={}),
            "banter_gap": mock.Mock(return_value=0), "box_talk_ok": mock.Mock(return_value=False),
            "render_backlog_save": mock.Mock(), "note_drop": mock.Mock()}
        for name, replacement in replacements.items():
            self.stack.enter_context(mock.patch.object(app, name, replacement))

    async def test_final_content_limit_keeps_attached_listening_response(self):
        def respond(rows, *args, **kwargs):
            return [rows[0], {"chunk": "Go on.", "who": "cohost", "turn_end": True,
                             "big": False, "listening_response": True,
                             "response_clip": {"path": "/media/response.wav"}}, *rows[1:]]
        self.speech_fixture(respond)
        said = []

        async def speak(kind, track, **kwargs):
            said.append(kwargs["line"])
            return kwargs["line"]

        with mock.patch.object(app, "dj_speak", side_effect=speak):
            await app._speak_turns_floorless([("A", "The opening."), ("B", "Next turn.")],
                                            None, 1, allow_repeat=True)
        self.assertEqual(said, ["The opening.", "Go on."])

    async def test_failed_turn_shelves_entire_tail_in_original_order(self):
        self.speech_fixture()
        called = []

        async def speak(kind, track, **kwargs):
            called.append(kwargs["line"])
            if len(called) == 2:
                app._RENDER_BACKLOG.append({"id": "failure", "who": kwargs["who"],
                                            "text": kwargs["line"]})
                return ""
            return kwargs["line"]

        with mock.patch.object(app, "dj_speak", side_effect=speak):
            await app._speak_turns_floorless([("A", "Opening."), ("B", "Question."),
                                            ("A", "Answer."), ("B", "Ending.")],
                                            None, 10, allow_repeat=True)
        self.assertEqual(called, ["Opening.", "Question."])
        self.assertEqual([r["text"] for r in app._RENDER_BACKLOG],
                         ["Question.", "Answer.", "Ending."])

    async def test_continuation_response_does_not_cut_off_original_speaker(self):
        def respond(rows, *args, **kwargs):
            return [rows[0], {"chunk": "Go on.", "who": "cohost", "turn_end": True,
                             "big": False, "listening_response": True,
                             "continuation_response": True,
                             "response_clip": {"path": "/media/response.wav"}}, *rows[1:]]
        self.speech_fixture(respond)
        said = []

        async def speak(kind, track, **kwargs):
            said.append(kwargs["line"])
            if kwargs["line"] == "Go on.":
                app._TALK_CUT[0] = 1
            return kwargs["line"]

        with mock.patch.object(app, "dj_speak", side_effect=speak):
            await app._speak_turns_floorless([("A", "First half.|Second half."),
                                            ("B", "Next turn.")], None, 3,
                                            allow_repeat=True)
        self.assertEqual(said, ["First half.", "Go on.", "Second half."])


class OutcomeMemoryTests(unittest.TestCase):
    def test_neural_and_lexical_recall_survive_restart_and_exclude_narration(self):
        with tempfile.TemporaryDirectory() as folder:
            journal = FlowJournal(Path(folder) / "flow.sqlite3")
            first = journal.record("reflection", "fail", "call readiness fell",
                {"broadcast_outcome": True, "report": {"id": "one", "score": 20}}, "one")
            journal.record("reflection", "info", "call readiness narration only")
            second = journal.record("reflection", "ok", "the bulletin improved",
                {"broadcast_outcome": True, "report": {"id": "two", "score": 90}}, "two")
            journal.pending.join()
            journal.index_embedding(first["id"], [1, 0], "test")
            journal.index_embedding(second["id"], [0, 1], "test")
            restored = FlowJournal(journal.path)
            neural = restored.recall("different wording", [1, 0], "test")
            self.assertEqual(neural["outcomes"][0]["trace_id"], "one")
            self.assertEqual(neural["outcomes"][0]["retrieval"], "neural")
            lexical = restored.recall("bulletin")
            self.assertEqual([r["trace_id"] for r in lexical["outcomes"]], ["two"])
            self.assertEqual(lexical["stored_outcomes"], 2)


class OutcomeMemoryConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_seed_imports_once_and_retries_failed_embedding(self):
        with tempfile.TemporaryDirectory() as folder:
            journal = FlowJournal(Path(folder) / "flow.sqlite3")
            with (mock.patch.object(app, "_STATION_FLOW", journal),
                  mock.patch.object(app, "station_flow_event", side_effect=journal.record),
                  mock.patch.object(app, "_HOURS", [{"id": "prior", "score": 20}]),
                  mock.patch.object(app, "_COORD_MEMORY_SEED_GATE", asyncio.Lock()),
                  mock.patch.object(app, "_COORD_EMBED_GATE", asyncio.Semaphore(1)),
                  mock.patch.object(app, "_COORD_EMBED_PENDING", set()),
                  mock.patch.object(app, "_COORD_EMBED_RETRY_AT", {}),
                  mock.patch.object(app, "EMBED_MODEL", "test"),
                  mock.patch.object(app, "_embed_texts", side_effect=[[], [[1, 0]]]) as embed):
                await asyncio.gather(*(app.coord_memory_seed() for _ in range(3)))
                for _ in range(100):
                    if not app._COORD_EMBED_PENDING:
                        break
                    await asyncio.sleep(.01)
                self.assertEqual(journal.recall()["stored_outcomes"], 1)
                self.assertEqual(embed.await_count, 1)
                self.assertTrue(app._COORD_EMBED_RETRY_AT)
                app._COORD_EMBED_RETRY_AT.clear()  # next allowed retry window
                await app.coord_memory_seed()
                for _ in range(100):
                    if not app._COORD_EMBED_PENDING:
                        break
                    await asyncio.sleep(.01)
                self.assertEqual(embed.await_count, 2)
                self.assertFalse(app._COORD_EMBED_RETRY_AT)
                journal.pending.join()
                result = journal.recall("prior", [1, 0], "test")
                self.assertEqual(result["stored_outcomes"], 1)
                self.assertTrue(result["outcomes"][0]["indexed"])
                self.assertEqual(result["outcomes"][0]["retrieval"], "neural")


if __name__ == "__main__":
    unittest.main()
