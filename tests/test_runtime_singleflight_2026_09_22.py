"""Regression coverage for live-loop work that must never multiply or block."""
import ast
import asyncio
import re
import threading
import time
import unittest
from pathlib import Path
from typing import Any


SOURCE = Path(__file__).parents[1].joinpath("app.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def function_source(name):
    node = next(row for row in TREE.body
                if isinstance(row, (ast.FunctionDef, ast.AsyncFunctionDef)) and row.name == name)
    return compile(ast.Module(body=[node], type_ignores=[]), "app.py:runtime-performance", "exec")


def banter_beat_source():
    names = {"_BANTER_BEAT_ROW", "_BANTER_BEAT_STOCK", "_BANTER_BEAT_STOP",
             "WritingDeferred",
             "_beat_content_words", "_beat_answers", "_beat_sequence_answers",
             "_banter_beat_plan",
             "_banter_beats"}
    nodes = []
    for node in TREE.body:
        name = getattr(node, "name", "")
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            assigned = {target.id for target in targets if isinstance(target, ast.Name)}
            if assigned & names:
                nodes.append(node)
        elif name in names:
            nodes.append(node)
    return compile(ast.Module(body=nodes, type_ignores=[]), "app.py:banter-beats", "exec")


class RuntimeSingleFlightTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_library_readers_share_one_probe(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        library = {"at": 0.0, "reading": "stale"}

        def probe():
            calls.append(time.time())
            entered.set()
            release.wait(2)
            library.update(at=time.time(), reading="fresh")
            return dict(library)

        namespace = {"asyncio": asyncio, "time": time, "Any": Any,
                     "_LIBRARY": library, "_LIBRARY_PROBE_TASK": [None],
                     "library_probe": probe}
        exec(function_source("library_speed"), namespace)
        readers = [asyncio.create_task(namespace["library_speed"](0)) for _ in range(8)]
        await asyncio.to_thread(entered.wait, 1)
        release.set()
        results = await asyncio.gather(*readers)
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(row["reading"] == "fresh" for row in results))

    def test_sting_hot_path_uses_local_duration_book(self):
        node = next(row for row in TREE.body
                    if isinstance(row, ast.AsyncFunctionDef) and row.name == "dj_sting")
        body = ast.get_source_segment(SOURCE, node) or ""
        self.assertIn("await sfx_db_seconds_async(sample)", body)
        self.assertNotIn("sfx_seconds(sample)", body)

    def test_pinebox_status_reads_an_off_loop_diagnosis_snapshot(self):
        status = next(row for row in TREE.body
                      if isinstance(row, ast.AsyncFunctionDef)
                      and row.name == "pinebox_status_api")
        body = ast.get_source_segment(SOURCE, status) or ""
        self.assertIn("pinebox_diagnose_start()", body)
        self.assertNotIn("await pinebox_diagnose()", body)
        starter = next(row for row in TREE.body
                       if isinstance(row, ast.FunctionDef)
                       and row.name == "pinebox_diagnose_start")
        start_body = ast.get_source_segment(SOURCE, starter) or ""
        self.assertIn('name="pinebox-diagnose"', start_body)
        self.assertIn("asyncio.run(pinebox_diagnose())", start_body)

    def test_exact_video_match_still_obeys_rotation_and_cooldown(self):
        node = next(row for row in TREE.body
                    if isinstance(row, ast.FunctionDef) and row.name == "sfx_match_sting_pick")
        body = ast.get_source_segment(SOURCE, node) or ""
        self.assertIn("sting_recent(str(path))", body)
        self.assertIn("sfx_video_on_cooldown(key)", body)

    def test_every_automatic_video_door_uses_the_shared_cooldown(self):
        def body(name):
            node = next(row for row in TREE.body
                        if isinstance(row, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and row.name == name)
            return ast.get_source_segment(SOURCE, node) or ""

        cue = body("sfx_video_cue_api")
        self.assertIn("await sfx_video_fresh_pick()", cue)
        self.assertIn("sfx_video_note_played(key", cue)
        self.assertNotIn("await sfx_db_pick_row_async(True)", cue)
        self.assertIn("sfx_video_note_played(key", body("sfx_video_cut_api"))
        self.assertIn("sfx_video_on_cooldown", body("sfx_cycle_request"))
        self.assertNotIn("return first", body("sfx_video_fresh_pick"))

    def test_dead_air_matcher_unpacks_metadata_before_building_a_path(self):
        body = next(row for row in TREE.body
                    if isinstance(row, ast.FunctionDef) and row.name == "_sfx_any")
        source = ast.get_source_segment(SOURCE, body) or ""
        self.assertIn("_hit[0]", source)

    def test_listener_identity_keeps_the_kiosk_marker_and_collapses_webviews(self):
        def body(name):
            node = next(row for row in TREE.body
                        if isinstance(row, ast.FunctionDef) and row.name == name)
            return ast.get_source_segment(SOURCE, node) or ""

        self.assertIn('str(agent)[:320]', body("listener_note"))
        self.assertNotIn('key in ("desktop", "pinetab")', body("listener_device"))
        roster = body("listener_roster")
        self.assertIn('device == "desktop"', roster)
        self.assertIn('device == "pinetab"', roster)

    async def test_banked_beat_chain_carries_completed_lines_forward(self):
        prompts = []

        async def ask_model(prompt, **_kwargs):
            prompts.append(prompt)
            rows = re.findall(r"(?m)^(\d+)  ([ABCD])  -", prompt)
            return "\n".join("%s: signal answer for turn %s." % (seat, turn)
                              for turn, seat in rows)

        def parse(script, *_args):
            return [(marker, text.strip()) for marker, text in
                    re.findall(r"(?m)^([ABCD]):\s*(.+)$", script)]

        namespace = {"asyncio": asyncio, "re": re, "time": time, "Any": Any,
                     "ask_model": ask_model, "banter_turns": parse,
                     "spoken_text": lambda value: value,
                     "prep_should_stop": lambda: "",
                     "_verbatim_turn_text": lambda value: str(value)}
        exec(banter_beat_source(), namespace)
        trace = []
        sheet = "\n".join("%2d  %s  - answers the prior turn" %
                          (turn, "A" if turn % 2 else "B")
                          for turn in range(1, 11))
        script = await namespace["_banter_beats"](
            "Discuss the signal.", sheet, 10, ["A", "B"],
            seed_text="The signal begins here.", trace=trace)
        turns = parse(script)
        self.assertEqual(len(turns), 10)
        self.assertEqual(turns[0], ("A", "The signal begins here."))
        self.assertEqual(len(prompts), 3)
        self.assertIn("A has just said - The signal begins here.", prompts[0])
        self.assertIn("COMPLETED TRANSCRIPT", prompts[1])
        self.assertEqual([row["made"] for row in trace], [4, 4, 1])
        self.assertTrue(namespace["_beat_answers"]("the signal is clear", "that signal is fading"))
        self.assertFalse(namespace["_beat_answers"]("the signal is clear", "back to the music"))

    async def test_banked_beat_chain_keeps_the_retry_and_never_returns_empty(self):
        prompts = []

        async def off_topic(prompt, **_kwargs):
            prompts.append(prompt)
            rows = re.findall(r"(?m)^(\d+)  ([ABCD])  -", prompt)
            return "\n".join("%s: unrelated reply %s." % (seat, turn)
                              for turn, seat in rows)

        def parse(script, *_args):
            return [(marker, text.strip()) for marker, text in
                    re.findall(r"(?m)^([ABCD]):\s*(.+)$", script)]

        namespace = {"asyncio": asyncio, "re": re, "time": time, "Any": Any,
                     "ask_model": off_topic, "banter_turns": parse,
                     "spoken_text": lambda value: value,
                     "prep_should_stop": lambda: "",
                     "_verbatim_turn_text": lambda value: str(value)}
        exec(banter_beat_source(), namespace)
        trace = []
        sheet = "\n".join("%2d  %s  - answers the prior turn" %
                          (turn, "A" if turn % 2 else "B")
                          for turn in range(1, 6))
        script = await namespace["_banter_beats"](
            "SUBJECT AND DIRECTION: discuss the signal.", sheet, 5,
            ["A", "B"], seed_text="The signal begins here.", trace=trace)
        self.assertEqual(len(parse(script)), 5)
        self.assertEqual(len(prompts), 2, "one failed check gets one retry")
        self.assertEqual(trace[0]["attempts"], 2)
        self.assertEqual(trace[0]["made"], 4)

        async def broken(*_args, **_kwargs):
            raise RuntimeError("writer unavailable")

        namespace["ask_model"] = broken
        trace = []
        script = await namespace["_banter_beats"](
            "SUBJECT AND DIRECTION: the toilet is overflowing in the booth.",
            sheet, 5, ["A", "B"], trace=trace)
        turns = parse(script)
        self.assertGreaterEqual(len(turns), 2)
        self.assertIn("toilet", turns[0][1].lower())
        self.assertEqual(trace[-1]["beat"], "glue")

        async def deferred(*_args, **_kwargs):
            raise namespace["WritingDeferred"]("the station lane is full")

        namespace["ask_model"] = deferred
        with self.assertRaises(namespace["WritingDeferred"]):
            await namespace["_banter_beats"](
                "SUBJECT AND DIRECTION: discuss the signal.",
                sheet, 5, ["A", "B"], trace=[])

        ask = next(row for row in TREE.body
                   if isinstance(row, ast.AsyncFunctionDef)
                   and row.name == "ask_model")
        ask_body = ast.get_source_segment(SOURCE, ask) or ""
        self.assertIn('_mark_kind == "banter beat"', ask_body)

    def test_system2_keeps_its_exact_budget_out_of_the_beat_chain(self):
        node = next(row for row in TREE.body
                    if isinstance(row, ast.AsyncFunctionDef)
                    and row.name == "dj_banter")
        body = ast.get_source_segment(SOURCE, node) or ""
        self.assertIn('and not _system2_job', body)

    def test_banked_banter_fragments_are_not_accepted_after_failed_repair(self):
        node = next(row for row in TREE.body
                    if isinstance(row, ast.AsyncFunctionDef)
                    and row.name == "dj_banter")
        body = ast.get_source_segment(SOURCE, node) or ""
        self.assertIn("bank and not caller_name", body)
        self.assertIn("not substantial_radio_script(script, _judge_lines)", body)
        self.assertIn("banked draft is still too thin after repair", body)
        self.assertIn("return []", body)

    def test_hourly_h3_render_is_claimed_before_rendering(self):
        clock = next(row for row in TREE.body
                     if isinstance(row, ast.AsyncFunctionDef)
                     and row.name == "h3_hourly_ad_clock")
        body = ast.get_source_segment(SOURCE, clock) or ""
        self.assertIn("h3_hourly_enabled()", body)
        self.assertIn("h3_hourly_claim(marker)", body)
        self.assertLess(body.index("h3_hourly_claim(marker)"),
                        body.index("voice_ad_render"))
        self.assertIn("h3_hourly_finish(marker", body)
        self.assertIn("@app.get(\"/api/h3/hourly\")", SOURCE)
        self.assertIn("@app.post(\"/api/h3/hourly\")", SOURCE)

    def test_h3_sources_use_the_durable_video_deck(self):
        picker = next(row for row in TREE.body
                      if isinstance(row, ast.FunctionDef)
                      and row.name == "voice_ad_person_clip")
        body = ast.get_source_segment(SOURCE, picker) or ""
        self.assertIn("sfx_db_pick_rotation_row", body)
        self.assertIn('excluded_folders=("sfx_ads",)', body)
        self.assertIn("_sfx_video_rotation_mark_clip(identifier)", body)
        self.assertLess(body.index("sfx_db_pick_rotation_row"),
                        body.index("sfx_match_score"))

    def test_zero_output_beat_artifacts_never_enter_the_cupboard_or_gold(self):
        namespace = {"Any": Any}
        exec(function_source("larder_empty_beat_chain"), namespace)
        invalid = {"writer_engine": "beats", "beat_chain": [
            {"beat": 1, "made": 0}, {"beat": "glue", "made": 0}]}
        self.assertTrue(namespace["larder_empty_beat_chain"](invalid))
        self.assertFalse(namespace["larder_empty_beat_chain"](
            {**invalid, "beat_chain": [{"beat": 1, "made": 2}]}))
        self.assertFalse(namespace["larder_empty_beat_chain"](
            {"writer_engine": "one", "beat_chain": []}))
        trim = next(row for row in TREE.body
                    if isinstance(row, ast.FunctionDef)
                    and row.name == "larder_trim")
        trim_body = ast.get_source_segment(SOURCE, trim) or ""
        self.assertIn("larder_empty_beat_chain(entry)", trim_body)
        self.assertIn("none entered gold", trim_body)

    def test_broadcast_destination_survives_settings_validation(self):
        # This contract is integration-tested through app.py elsewhere. Keep a
        # source assertion here so the hot-path suite does not import the full
        # station or touch its live settings file.
        node = next(row for row in TREE.body
                    if isinstance(row, ast.FunctionDef)
                    and row.name == "validate_settings")
        body = ast.get_source_segment(SOURCE, node) or ""
        self.assertIn('"broadcast_to": broadcast_to', body)
        self.assertIn('"pinetab", "app", "box", "nabu", "off"', body)

    def test_episode_staging_moves_every_filesystem_operation_off_loop(self):
        stage = next(row for row in TREE.body
                     if isinstance(row, ast.AsyncFunctionDef)
                     and row.name == "_episode_stage")
        body = ast.get_source_segment(SOURCE, stage) or ""
        self.assertIn("await asyncio.to_thread(_episode_stage_file, src, dst)", body)
        self.assertNotIn("shutil.copyfile", body)
        calls = [node for node in ast.walk(TREE)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)
                 and node.func.id == "_episode_stage_call"]
        self.assertGreaterEqual(len(calls), 8)
        parents = {}
        for node in ast.walk(TREE):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        self.assertTrue(all(isinstance(parents.get(call), ast.Await)
                            for call in calls))

    def test_report_context_disk_reads_are_off_the_http_loop(self):
        node = next(row for row in TREE.body
                    if isinstance(row, ast.AsyncFunctionDef)
                    and row.name == "_script_report_observe")
        body = ast.get_source_segment(SOURCE, node) or ""
        self.assertIn("await asyncio.to_thread", body)
        self.assertIn("script_diagnostic_context", body)

    def test_mixtape_share_never_blocks_an_async_broadcast_road(self):
        def body(name):
            node = next(row for row in TREE.body
                        if isinstance(row, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and row.name == name)
            return ast.get_source_segment(SOURCE, node) or ""

        self.assertIn("await asyncio.to_thread(dj_next_track)", body("_dj_loop"))
        advert = body("ad_produce")
        self.assertIn("await asyncio.to_thread(mixtape_files)", advert)
        self.assertIn("await asyncio.to_thread(tape_duration, _tp)", advert)
        self.assertIn("await asyncio.to_thread(mixtape_catalog)",
                      body("dj_mixtapes_list"))
        request = body("dj_mixtape_api")
        self.assertIn("tapes = await asyncio.to_thread(mixtape_files)", request)
        self.assertIn("await asyncio.to_thread(tape_crystal, tape)",
                      body("dj_mixtape_outro"))

    def test_admission_identity_filesystem_work_is_off_the_event_loop(self):
        for name in ("page_recovery_start", "_dj_speak_floorless",
                     "dj_upstairs_page", "_air_produced_ad", "dj_sting",
                     "script_line_replay", "dj_sfx_play",
                     "sfx_video_cue_api"):
            node = next(row for row in TREE.body
                        if isinstance(row, ast.AsyncFunctionDef)
                        and row.name == name)
            source = ast.get_source_segment(SOURCE, node) or ""
            self.assertIn("asyncio.to_thread(\n", source, name)
            self.assertIn("admission_admit_line,", source, name)

        sting = next(row for row in TREE.body
                     if isinstance(row, ast.AsyncFunctionDef)
                     and row.name == "dj_sting")
        source = ast.get_source_segment(SOURCE, sting) or ""
        self.assertIn("length=_sample_seconds", source)

        rounds = next(row for row in TREE.body
                      if isinstance(row, ast.AsyncFunctionDef)
                      and row.name == "_speak_turns_floorless")
        source = ast.get_source_segment(SOURCE, rounds) or ""
        self.assertRegex(
            source,
            r"await asyncio\.to_thread\(\s+admission_admit_round",
        )

    def test_continuous_polls_only_read_non_blocking_snapshots(self):
        def body(name):
            node = next(row for row in TREE.body
                        if isinstance(row, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and row.name == name)
            return ast.get_source_segment(SOURCE, node) or ""

        self.assertIn('"admission": admission_state_cached(12)',
                      body("dj_state"))
        cached = body("admission_state_cached")
        self.assertIn('name="admission-state"', cached)
        self.assertIn("Thread(target=refresh", cached)
        self.assertNotIn("controller.cue_map", cached)
        clip_seconds = body("page_clip_seconds")
        self.assertIn('clip.get("seconds")', clip_seconds)
        self.assertLess(clip_seconds.index('clip.get("seconds")'),
                        clip_seconds.index("measured = _clip_seconds"))
        self.assertIn("await asyncio.to_thread(page_reservation_repair)",
                      body("dj_voice_api"))
        self.assertIn("await asyncio.to_thread(reflection_due)",
                      body("reflection_clock"))
        self.assertIn("return await asyncio.to_thread(work)",
                      body("admission_api"))
        perf = body("perf")
        self.assertIn("await asyncio.to_thread(_perf_host_snapshot)", perf)
        self.assertNotIn("read_text", perf)

    def test_airlog_share_writes_do_not_hold_reader_locks(self):
        writer = body = next(row for row in TREE.body
                           if isinstance(row, ast.FunctionDef)
                           and row.name == "airlog_write_rows")
        source = ast.get_source_segment(SOURCE, writer) or ""
        self.assertLess(source.index('AIR_LOG_PATH.open("a"'),
                        source.index("with _AIRLOG_LOCK"))
        compact = next(row for row in TREE.body
                       if isinstance(row, ast.FunctionDef)
                       and row.name == "airlog_compact")
        source = ast.get_source_segment(SOURCE, compact) or ""
        self.assertLess(source.index("tmp.write_text"),
                        source.index("with _AIRLOG_LOCK"))
        for name in ("airlog_heat_load", "airlog_heat_flush",
                     "airlog_heat_sample", "heat_ring_rows"):
            node = next(row for row in TREE.body
                        if isinstance(row, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and row.name == name)
            source = ast.get_source_segment(SOURCE, node) or ""
            self.assertIn("_HEAT_LOCK", source, name)
            self.assertNotIn("_AIRLOG_LOCK", source, name)


if __name__ == "__main__":
    unittest.main()
