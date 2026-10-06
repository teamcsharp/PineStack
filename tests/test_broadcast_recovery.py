"""Recovery regressions without importing the station or touching live data.

Run the shipped app functions against an isolated clock and in-memory state.
"""
import ast
import asyncio
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from broadcast_recovery import AudioProgress, RecoveryJobs, recovery_gate

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))


def shipped(namespace, *names):
    nodes = [n for n in TREE.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
    return namespace


def music(progress, at, position, *, sequence=1, audible=0.2, playing=True, media="track"):
    return progress.observe(listener="desktop", source="music:page", media=media,
                            position=position, sequence=sequence, at=at,
                            audible=audible, playing=playing, monitor=True)


def evidence(**changes):
    return {"quiet": 500, "dialogue_quiet": 900, "waiting": 0,
            "listeners": 1, "mode": "air", "basis": "heard",
            "flow_ready": 10, "flow_target": 5, "flow_fresh": True,
            "bank_fresh": True, "banked_ready": 7, "consumer_idle": 600,
            "pass_age": 120, **changes}


def decisions():
    return shipped({"Any": object, "recovery_gate": recovery_gate,
                    "PAGE_WEDGE_WAITING": 4, "GAP_BASIS_PUBLISHED": "published",
                    "AIR_STALL_READY": 1, "AIR_STALL_QUIET": 150,
                    "AIR_STALL_PASS_S": 90, "AIR_WATCH_EVERY": 20,
                    "track_talk_segment": SimpleNamespace(MODE_AIR="air")},
                   "air_watch_roads")["air_watch_roads"]


class ProgressTests(unittest.TestCase):
    def test_music_progress_prevents_speech_gap_recovery(self):
        progress = AudioProgress()
        self.assertFalse(music(progress, 100, 30))
        self.assertTrue(music(progress, 103, 33, sequence=2))
        state = progress.snapshot(105)
        self.assertEqual(state["quiet"], 2)
        result = decisions()(evidence(**state, waiting=7, page_wedged=True))
        self.assertFalse(result["fire"])
        self.assertIn("advancing", result["say"])
        self.assertEqual(progress.last_speech, 0)

    def test_duplicate_muted_paused_and_static_reports_are_not_sound(self):
        progress = AudioProgress()
        music(progress, 100, 10)
        music(progress, 103, 13, sequence=2)
        self.assertFalse(music(progress, 106, 40, sequence=2))
        self.assertFalse(music(progress, 109, 13, sequence=3))
        self.assertFalse(music(progress, 112, 16, sequence=4, audible=0))
        self.assertFalse(music(progress, 115, 19, sequence=5, playing=False))
        self.assertEqual(progress.last_heard, 103)
        state = progress.snapshot(115)
        self.assertTrue(state["intentional_silence"])
        self.assertFalse(recovery_gate(evidence(**{**state, "quiet": 500}))["allow"])

    def test_stale_reports_and_a_new_track_do_not_claim_a_frozen_mix(self):
        progress = AudioProgress()
        music(progress, 100, 10)
        music(progress, 103, 13, sequence=2)
        self.assertFalse(progress.snapshot(200)["media_stalled"])
        music(progress, 200, 0, sequence=3, media="next")
        self.assertFalse(progress.snapshot(200)["media_stalled"])
        self.assertFalse(music(progress, 220, 20, sequence=4, media="next"))
        self.assertEqual(progress.last_heard, 103)

    def test_fresh_static_positions_eventually_confirm_a_frozen_mix(self):
        progress = AudioProgress()
        for sequence in range(1, 35):
            music(progress, 100 + sequence * 3, 10, sequence=sequence)
        state = progress.snapshot(202)
        self.assertTrue(state["media_stalled"])
        self.assertGreaterEqual(state["quiet"], 90)
        gate = recovery_gate(evidence(**state))
        self.assertTrue(gate["destructive"])

    def test_muted_music_does_not_hide_an_audible_frozen_voice(self):
        progress = AudioProgress()
        for sequence in range(1, 35):
            at = 100 + sequence * 3
            music(progress, at, 10, sequence=sequence, audible=0)
            progress.observe(listener="desktop", source="delivery:voice", media="voice",
                             position=1, sequence=sequence, at=at,
                             audible=1, playing=True, speech=True, monitor=True)
        state = progress.snapshot(202)
        self.assertFalse(state["intentional_silence"])
        self.assertTrue(state["media_stalled"])
        self.assertTrue(recovery_gate(evidence(**state))["destructive"])

    def test_document_reload_sequence_has_an_independent_baseline(self):
        progress = AudioProgress()
        music(progress, 100, 10, sequence=100)
        music(progress, 103, 13, sequence=101)
        for at, pos, seq in [(106, 1, 1), (109, 4, 2)]:
            progress.observe(listener="desktop", source="music:new-document", media="track",
                             position=pos, sequence=seq, at=at, audible=1,
                             playing=True, monitor=True)
        self.assertEqual(progress.last_heard, 109)

    def test_nonfinite_positions_rejected_and_tracker_is_bounded(self):
        progress = AudioProgress(limit=2)
        with self.assertRaises(ValueError):
            music(progress, 100, float("nan"))
        for i in range(3):
            progress.observe(listener=str(i), source="music", media="track",
                             position=1, sequence=1, at=100, audible=1, playing=True)
        self.assertEqual(len(progress.samples), 2)


class RecoveryJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_keeps_one_worker_and_second_request_joins_it(self):
        jobs = RecoveryJobs()
        release = asyncio.Event()
        calls = []

        async def produce():
            calls.append("started")
            await release.wait()
            calls.append("finished")
            return "a completed, voiced round"

        complete, result = await jobs.run("bank", produce, 0.001)
        self.assertFalse(complete)
        self.assertIsNone(result)
        self.assertEqual(jobs.pending(), ["bank"])
        complete, _result = await jobs.run("bank", produce, 0.001)
        self.assertFalse(complete)
        self.assertEqual(calls, ["started"])
        release.set()
        complete, result = await jobs.run("bank", produce, 1)
        self.assertTrue(complete)
        self.assertEqual(result, "a completed, voiced round")
        self.assertEqual(calls, ["started", "finished"])
        self.assertEqual(jobs.pending(), [])


class DialogueDiagnosisTests(unittest.TestCase):
    def triage(self, ready):
        ns = {"Any": object, "time": SimpleNamespace(time=lambda: 1000),
              "TRIAGE_WINDOW": 150, "_BUILD_MS": 100000,
              "_RADIO": {"on": True, "pipeline": [{"ts": 999000,
                  "text": "System 3 held the final exchange: handoff rows must align"}]},
              "_PAGE_ACK_EVENTS": [], "_PAGE_DELIVERIES": {},
              "radio_paused": lambda: False, "_listeners_live": lambda: [],
              "audio_owner": lambda: "", "page_delivery_waits": lambda row: False,
              "dialogue_quiet_for": lambda: 900,
              "bank_health": lambda: {"ready_now": ready, "say": "no voiced rounds"}}
        shipped(ns, "broadcast_triangulate")
        return ns["broadcast_triangulate"]()

    def test_empty_dialogue_bank_is_production_fault_and_cures_bank(self):
        result = self.triage(0)
        self.assertEqual(result["cause"], "nothing_to_play")
        self.assertEqual(result["cure"], "bank")
        self.assertIn("handoff rows", result["production_failures"][0])

    def test_ready_unheard_dialogue_is_served_instead_of_new_generation(self):
        self.assertEqual(self.triage(3)["cure"], "stock")

    def test_console_does_not_treat_music_progress_as_restored_djs(self):
        ns = {"Any": object, "Header": lambda **kw: None,
              "time": SimpleNamespace(time=lambda: 1000),
              "require_read_auth": lambda _: None,
              "page_wedge_state": lambda: {"wedged": False, "heard_at": 999, "dialogue_quiet": 900},
              "air_stall_mode": lambda: "air", "radio_paused": lambda: False,
              "DIALOGUE_QUIET_ALARM": 120, "_RADIO": {"on": True, "pipeline": []},
              "broadcast_triangulate": lambda: {"cause": "nothing_to_play", "why": "no voiced dialogue"},
              "_AIR_WATCH": {}, "_AIR_MUTE": {}, "_DEAD_AIR_PASS": {},
              "AIR_STALL_PASS_S": 90, "BROADCAST_STEPS": [],
              "_BROADCAST_RECOVERY_JOBS": RecoveryJobs()}
        shipped(ns, "broadcast_console_api")
        result = asyncio.run(ns["broadcast_console_api"]())
        self.assertTrue(result["stuck"])
        self.assertTrue(result["dialogue_stuck"])
        self.assertEqual(result["heard_seconds_ago"], 1)
        self.assertIn("DJs have not been heard", result["say"])

class RecoveryJobCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_producer_timeout_is_failure_not_a_pending_job(self):
        jobs = RecoveryJobs()

        async def expired():
            raise asyncio.TimeoutError()

        with self.assertRaisesRegex(RuntimeError, "production timed out"):
            await jobs.run("bank", expired, 1)
        self.assertEqual(jobs.pending(), [])

    async def test_cancelled_request_does_not_cancel_background_production(self):
        jobs = RecoveryJobs()
        release = asyncio.Event()

        async def produce():
            await release.wait()
            return True

        request = asyncio.create_task(jobs.run("stock", produce, 20))
        await asyncio.sleep(0)
        request.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request
        self.assertFalse(jobs.tasks["stock"].cancelled())
        release.set()
        complete, result = await jobs.run("stock", produce, 1)
        self.assertTrue(complete and result)

    async def test_failed_worker_releases_key_and_reports_error(self):
        jobs = RecoveryJobs()

        async def broken():
            raise ValueError("production handoff refused")

        with self.assertRaisesRegex(ValueError, "handoff refused"):
            await jobs.run("bank", broken, 1)
        self.assertEqual(jobs.pending(), [])


class RepairVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def repair(self, speech_heard):
        jobs = RecoveryJobs()
        heard = [0]
        snapshots = iter([{"cause": "nothing_to_play", "cure": "bank", "speech_offered": 0},
                          {"cause": "healthy", "cure": "", "listeners": {"desktop": {}}}])
        ns = {"Any": object, "asyncio": asyncio, "time": SimpleNamespace(time=lambda: 1000),
              "page_wedge_state": lambda: {"wedged": False},
              "broadcast_triangulate": lambda **kwargs: next(snapshots),
              "_BROADCAST_RECOVERY_JOBS": jobs, "_DIALOGUE_HEARD": heard,
              "larder_stock_count": lambda: 0,
              "dj_settings": lambda: {"dialogue_reserve_target": 4},
              "talk_quiet_for": lambda: 900,
              "_LARDER_FAILS": [0, ""], "_SFX_GAP": {}, "_LARDER": [],
              "note_action": lambda _: None}

        async def bank(_track, **kwargs):
            ns["_LARDER"].append({"script": "A: A verified new round has reached the shelf."})
            if speech_heard:
                heard[0] = 1001

        ns["dj_banter"] = bank
        ns["asyncio"] = SimpleNamespace(sleep=mock.AsyncMock(), TimeoutError=asyncio.TimeoutError)
        shipped(ns, "broadcast_step")
        return await ns["broadcast_step"]("repair")

    async def test_music_only_success_cannot_verify_restored_dialogue(self):
        result = await self.repair(False)
        self.assertFalse(result["ok"])
        self.assertFalse(result["verified"])

    async def test_speech_during_cure_counts_as_verified_recovery(self):
        result = await self.repair(True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["verified"])


class DecisionTests(unittest.TestCase):
    def test_paused_station_and_disconnected_receivers_do_not_escalate(self):
        for change in ({"paused": True}, {"on": False}, {"listeners": 0}, {"quiet": -1}):
            with self.subTest(change=change):
                self.assertFalse(decisions()(evidence(waiting=7, page_wedged=True, **change))["fire"])

    def test_accepted_future_audio_is_scheduling_not_silence_failure(self):
        result = decisions()(evidence(future_waiting=5))
        self.assertFalse(result["fire"])
        self.assertIn("scheduled", result["say"])

    def test_upstream_dialogue_stall_only_allows_preparation_relief(self):
        result = decisions()(evidence())
        self.assertTrue(result["fire"])
        self.assertEqual(result["max_rung"], 0)
        self.assertTrue(result["cap_rung"])

    def test_confirmed_page_wedge_can_climb_one_step_at_a_time(self):
        result = decisions()(evidence(waiting=4, page_wedged=True))
        self.assertTrue(result["fire"])
        self.assertTrue(result["cap_rung"])
        self.assertIsNone(result["max_rung"])

    def test_frozen_music_opens_recovery_without_any_speech_queue_or_bank(self):
        result = decisions()(evidence(waiting=0, media_stalled=True,
                                      flow_ready=0, flow_target=0, banked_ready=0,
                                      flow_fresh=False, bank_fresh=False, pass_age=-1,
                                      consumer_idle=0))
        self.assertTrue(result["fire"])
        self.assertTrue(result["cap_rung"])
        self.assertIsNone(result["max_rung"])
        self.assertEqual(result["road"], "wedge")

    def test_future_delivery_is_excluded_from_actual_page_backlog(self):
        ns = shipped({"Any": object, "time": SimpleNamespace(time=lambda: 100),
                      "PAGE_WAIT_LATE_S": 120}, "page_delivery_waits")
        queued = {"state": "received", "clip": {"speech": True, "broadcast_ms": 110000}}
        self.assertFalse(ns["page_delivery_waits"](queued))
        self.assertEqual(queued["clip"]["broadcast_ms"], 110000)
        queued["clip"]["broadcast_ms"] = 99000
        self.assertTrue(ns["page_delivery_waits"](queued))


class ReceiptTests(unittest.TestCase):
    def fixture(self):
        clock = SimpleNamespace(now=100)
        ns = {"Any": object, "re": re, "time": SimpleNamespace(time=lambda: clock.now),
              "_PAGE_DELIVERIES": {"clip": {"speech": True, "clip": {}, "listeners": {}}},
              "_PAGE_ACK_EVENTS": [], "_DIALOGUE_HEARD": [0], "_AUDIO_PROGRESS": AudioProgress(),
              "listener_note": mock.Mock(), "station_flow_event": mock.Mock(),
              "playout_tell": mock.Mock(), "_acknowledge_delivery_lines": lambda *a: False}
        shipped(ns, "page_playback_ack")
        return ns, clock

    def test_muted_and_out_of_order_receipts_cannot_refresh_dialogue_clock(self):
        ns, clock = self.fixture()
        ack = ns["page_playback_ack"]
        body = {"listener_id": "desktop", "delivery_id": "clip", "event": "playing",
                "sequence": 1, "current_time": 1, "volume": 1, "audible_volume": 1}
        ack(body)
        clock.now = 103
        ack({**body, "sequence": 2, "current_time": 4})
        self.assertEqual(ns["_DIALOGUE_HEARD"], [103])
        clock.now = 106
        ack({**body, "sequence": 3, "current_time": 7, "muted": True})
        clock.now = 109
        result = ack({**body, "sequence": 2, "current_time": 10})
        self.assertIn("ignored", result)
        self.assertEqual(ns["_DIALOGUE_HEARD"], [103])
        self.assertEqual(ns["_AUDIO_PROGRESS"].last_heard, 103)


class WatchTests(unittest.IsolatedAsyncioTestCase):
    def namespace(self, root, *, quiet=500, wedge=True, future=0, loops=18):
        clock = SimpleNamespace(now=20000, polls=0)
        actions, audit, tasks = [], [], []
        progress = AudioProgress()
        music(progress, clock.now - quiet - 3, 1)
        music(progress, clock.now - quiet, 4, sequence=2)
        wedge_state = {"waiting": 4 if wedge else 0, "wedged": wedge, "dialogue_quiet": -1}
        real_sleep = asyncio.sleep
        async def sleep(seconds):
            clock.now += seconds
            if seconds == 20:
                clock.polls += 1
                if clock.polls > loops:
                    raise asyncio.CancelledError()
            await real_sleep(0)
        async def step(name):
            actions.append(name)
            return {"lines": []}
        async def probe():
            return {"say": "probe"}
        async def restart():
            tasks.append("restart")
        ns = decisions().__globals__.copy()
        ladder_node = next(n for n in TREE.body if isinstance(n, ast.AnnAssign)
                           and getattr(n.target, "id", "") == "AIR_LADDER")
        exec(compile(ast.Module(body=[ladder_node], type_ignores=[]), "app.py", "exec"), ns)
        ns.update(asyncio=SimpleNamespace(sleep=sleep, CancelledError=asyncio.CancelledError,
                                         create_task=asyncio.create_task),
                  time=SimpleNamespace(time=lambda: clock.now), _RADIO={"on": True},
                  _AIR_WATCH={"rung": -1, "at": 0, "last_restart": 0},
                  _AIR_MUTE={"at": 0}, AIR_MUTE_QUIET=720, AIR_MUTE_REST=600,
                  AIR_WATCH_SETTLE=45, AIR_RESTART_REST=3600,
                  AIR_RESTART_STAMP=root / "restart", _AUDIO_PROGRESS=progress,
                  radio_paused=lambda: False, dialogue_quiet_for=lambda: 900,
                  orch_turn=mock.Mock(), page_wedge_state=lambda: wedge_state,
                  air_watch_evidence=lambda quiet, waiting: evidence(**{**progress.snapshot(clock.now), "quiet": quiet, "waiting": waiting,
                              "page_wedged": wedge, "future_waiting": future}),
                  air_fix_note=audit.append, pipeline_log=mock.Mock(),
                  broadcast_step=step, media_speed_probe=probe,
                  pages_reload=lambda why: actions.append("reload"), broadcast_restart_task=restart)
        shipped(ns, "air_watch", "air_quiet_for")
        return ns, clock, actions, audit, tasks

    async def drive(self, ns):
        with self.assertRaises(asyncio.CancelledError):
            await ns["air_watch"]()
        await asyncio.sleep(0)

    async def test_real_wedge_escalates_without_flushing_accepted_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            ns, clock, actions, audit, tasks = self.namespace(Path(tmp))
            await self.drive(ns)
            self.assertEqual(actions, ["relieve", "handover", "release", "reload"])
            self.assertEqual(tasks, ["restart"])
            self.assertNotIn("flush", actions)
            self.assertTrue((Path(tmp) / "restart").exists())

    async def test_stale_speech_only_stall_cannot_reload_or_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            ns, clock, actions, audit, tasks = self.namespace(Path(tmp), wedge=False)
            await self.drive(ns)
            self.assertEqual(actions, ["relieve"])
            self.assertEqual(tasks, [])

    async def test_future_accepted_interval_delivery_keeps_queue_and_station(self):
        with tempfile.TemporaryDirectory() as tmp:
            ns, clock, actions, audit, tasks = self.namespace(Path(tmp), wedge=False, future=4)
            await self.drive(ns)
            self.assertEqual(actions, [])
            self.assertEqual(tasks, [])

    async def test_audio_resuming_during_probe_cancels_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            ns, clock, actions, audit, tasks = self.namespace(Path(tmp), loops=1)
            ns["_AIR_WATCH"].update(rung=2, at=19000)
            async def resumed_probe():
                music(ns["_AUDIO_PROGRESS"], clock.now - 3, 10, sequence=3)
                music(ns["_AUDIO_PROGRESS"], clock.now, 13, sequence=4)
                return {}
            ns["media_speed_probe"] = resumed_probe
            await self.drive(ns)
            self.assertEqual(actions, [])
            self.assertEqual(tasks, [])
            self.assertEqual(audit[-1]["event"], "cancelled")

    async def test_healthy_music_still_allows_dialogue_bank_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            ns, clock, actions, audit, tasks = self.namespace(Path(tmp), quiet=0, wedge=False, loops=1)
            ns["page_wedge_state"] = lambda: {"waiting": 0, "wedged": False, "dialogue_quiet": 900}
            ns["bank_health"] = lambda: {"bare": True, "banked": 0, "say": "empty"}
            await self.drive(ns)
            self.assertEqual(actions, ["bank"])
            self.assertEqual(tasks, [])

    async def test_healthy_music_with_ready_unheard_dialogue_airs_stock(self):
        with tempfile.TemporaryDirectory() as tmp:
            ns, clock, actions, audit, tasks = self.namespace(Path(tmp), quiet=0, wedge=False, loops=1)
            ns["page_wedge_state"] = lambda: {"waiting": 0, "wedged": False, "dialogue_quiet": 900}
            ns["bank_health"] = lambda: {"bare": False, "banked": 4, "ready_now": 4}
            await self.drive(ns)
            self.assertEqual(actions, ["stock"])
            self.assertEqual(tasks, [])

    async def test_automatic_page_repair_preserves_feed_epoch_manual_force_flushes(self):
        ns = {"Any": object, "time": SimpleNamespace(time=lambda: 1000),
              "page_wedge_state": lambda: {"wedged": True, "waiting": 4},
              "_PAGE_WEDGE_AT": [0], "PAGE_WEDGE_REST": 180,
              "_RADIO": {"voice_cut_ms": 123}, "_PAGE_AIR_UNTIL": [9999],
              "_AUDIO_OWNER": {"listener_id": "bad"},
              "pipeline_log": mock.Mock(), "repair_note": mock.Mock(),
              "asyncio": SimpleNamespace(sleep=mock.AsyncMock())}
        shipped(ns, "page_wedge_clear")
        await ns["page_wedge_clear"]()
        self.assertEqual(ns["_RADIO"]["voice_cut_ms"], 123)
        self.assertEqual(ns["_PAGE_AIR_UNTIL"], [9999])
        await ns["page_wedge_clear"](force=True)
        self.assertEqual(ns["_RADIO"]["voice_cut_ms"], 1000000)
        self.assertEqual(ns["_PAGE_AIR_UNTIL"], [0])


if __name__ == "__main__":
    unittest.main()
