"""Exercise actual hot-path functions without importing the running station."""
from __future__ import annotations
import ast
import asyncio
from pathlib import Path
import sqlite3
from threading import Event, RLock, Thread
from types import SimpleNamespace
import unittest

from loop_side_effects import OrderedSideEffects
from camera_report_worker import OrderedReports, StaleReportError

SOURCE = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text())
FUNCTIONS = {node.name: node for node in SOURCE.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def actual(names, namespace):
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    functions = []
    for name in names:
        node = FUNCTIONS[name]
        node.decorator_list = []
        functions.append(node)
    tree = ast.fix_missing_locations(ast.Module(body=[future] + functions, type_ignores=[]))
    exec(compile(tree, "actual-station-functions", "exec"), namespace)
    return namespace


class BackendSideEffectTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_ack_side_effect_returns_and_http_loop_answers_while_database_lock_is_held(self):
        worker = OrderedSideEffects(capacity=1)
        database = sqlite3.connect(":memory:", check_same_thread=False)
        database.row_factory = sqlite3.Row
        database.execute("CREATE TABLE sfx_meta(name TEXT PRIMARY KEY,value TEXT)")
        database.execute("INSERT INTO sfx_meta VALUES('video_deck_cycle','7')")
        database.execute("CREATE TABLE clips(sid TEXT,name TEXT,bytes INT,seconds REAL,folder TEXT,video INT,deck_cycle INT)")
        database.executemany("INSERT INTO clips VALUES(?,?,?,?,?,?,0)", [
            ("a", "same title", 10, 2, "first", 1),
            ("b", "same title", 11, 2, "second", 1),
            ("c", "other title", 10, 2, "third", 1)])
        database.commit()
        lock = RLock()
        rotation = {"used": set(), "cycle": 7, "picked": 0, "why": ""}
        recorded = set()
        def record(rows):
            fresh = [row["id"] for row in rows if row["id"] not in recorded]
            recorded.update(fresh)
            return fresh
        ns = {"asyncio": asyncio, "_SFX_VIDEO_FAMILY_WORK": worker,
              "_SFX_VIDEO_ROTATION": rotation, "_SFX_VIDEO_ROTATION_LOCK": RLock(),
              "_SFX_DB_LOCK": lock, "sfx_db": lambda: database,
              "_sfx_video_rotation_load": lambda: None,
              "sfx_video_rotation_cycle": lambda: 7,
              "SFX_VIDEO_FOLDER_REST": 4, "_SFX_CADENCE": SimpleNamespace(record=record),
              "require_read_auth": lambda value: None, "Header": lambda **kw: None}
        actual(["_sfx_video_rotation_mark_clip_blocking", "_sfx_video_rotation_mark_clip",
                "_sfx_cadence_audible", "sfx_video_on_cooldown", "dj_voice_ack_api"], ns)
        ns["sfx_video_note_played"] = ns["_sfx_video_rotation_mark_clip"]
        ns["page_playback_ack"] = lambda *args: (ns["_sfx_cadence_audible"](
            [{"id": "line", "who": "dj", "from": 0, "until": 2, "sfx_video_id": "a"}], 3), {"ok": True})[1]
        request = SimpleNamespace(json=lambda: asyncio.sleep(0, result={}), client=None, headers={})
        async def health(reader, writer):
            await reader.read(32)
            writer.write(b"healthy")
            await writer.drain()
            writer.close()
        server = await asyncio.start_server(health, "127.0.0.1", 0)
        held, release = Event(), Event()
        def hold_database():
            with lock:
                held.set()
                release.wait(5)
        holder = Thread(target=hold_database)
        holder.start()
        self.assertTrue(held.wait(1))
        try:
            result = await asyncio.wait_for(ns["dj_voice_ack_api"](request), 0.5)
            self.assertTrue(result["ok"])
            self.assertIn("a", rotation["used"])
            self.assertTrue(worker.pending())
            self.assertTrue(ns["sfx_video_on_cooldown"]("b"))
            # A duplicate receipt/key must not enqueue a second durable write.
            ns["_sfx_video_rotation_mark_clip"]("a")
            reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1]), 0.5)
            writer.write(b"GET health")
            await writer.drain()
            self.assertEqual(b"healthy", await asyncio.wait_for(reader.read(32), 0.5))
            writer.close()
            await writer.wait_closed()
        finally:
            release.set()
            holder.join(1)
            server.close()
            await server.wait_closed()
            await worker.drain()
            await worker.close()
        self.assertFalse(worker.pending())
        self.assertEqual({"a", "b", "c"}, rotation["used"])
        self.assertEqual(1, rotation["picked"])
        self.assertEqual([7, 7, 7], [r[0] for r in database.execute("SELECT deck_cycle FROM clips")])
        database.close()

    async def test_bounded_queue_keeps_every_accepted_job_in_order(self):
        worker = OrderedSideEffects(capacity=1)
        released = Event()
        began = Event()
        output = []
        def work(index):
            if index == 0:
                began.set()
                released.wait(2)
            output.append(index)
        for index in range(5):
            worker.submit(str(index), lambda index=index: work(index), lambda: None)
        try:
            for _ in range(50):
                if began.is_set():
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(began.is_set())
            self.assertLessEqual(worker._queue.qsize(), 1)
            self.assertTrue(worker.pending())
            await asyncio.sleep(0)
        finally:
            released.set()
            await worker.drain()
            await worker.close()
        self.assertEqual(list(range(5)), output)
        self.assertFalse(worker.pending())

    async def test_failed_commit_keeps_reservation_and_retries_before_later_jobs(self):
        worker = OrderedSideEffects(capacity=1)
        output = []
        attempts = 0
        def first():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise sqlite3.OperationalError("temporary writer failure")
            output.append("first")
        worker.submit("first", first, lambda: None)
        worker.submit("second", lambda: output.append("second"), lambda: None)
        await asyncio.sleep(0.05)
        self.assertTrue(worker.pending())
        self.assertEqual([], output)
        await worker.drain()
        await worker.close()
        self.assertEqual(["first", "second"], output)
        self.assertEqual(2, attempts)
        self.assertFalse(worker.pending())

    async def test_pending_family_stops_video_draws_and_generation_reset_before_any_database_read(self):
        touched = []
        ns = {"_SFX_VIDEO_FAMILY_WORK": SimpleNamespace(pending=lambda: True, checkpoint=lambda: None),
              "sfx_db_reader": lambda: touched.append("read"),
              "_sfx_video_rotation_load": lambda: touched.append("load")}
        actual(["sfx_db_pick_short_video", "sfx_db_pick_rotation_row", "sfx_video_rotation_reset"], ns)
        self.assertIsNone(ns["sfx_db_pick_short_video"](8))
        self.assertIsNone(ns["sfx_db_pick_rotation_row"]())
        self.assertFalse(ns["sfx_video_rotation_reset"]())
        self.assertEqual([], touched)


    def generation_namespace(self, worker, lock, database, rotation, loaded=None):
        return actual(["_sfx_video_rotation_mark_clip_blocking", "_sfx_video_rotation_mark_clip",
                       "sfx_video_rotation_reset"], {
            "asyncio": asyncio, "_SFX_VIDEO_FAMILY_WORK": worker,
            "_SFX_VIDEO_ROTATION": rotation, "_SFX_VIDEO_ROTATION_LOCK": RLock(),
            "_SFX_DB_LOCK": lock, "sfx_db": lambda: database,
            "_sfx_video_rotation_load": lambda: loaded.set() if loaded else None,
            "sfx_pin_prefix": lambda: "", "_sfx_video_played_load": lambda: None,
            "_SFX_VIDEO_PLAYED_LOCK": RLock(), "_SFX_VIDEO_PLAYED": {},
            "SFX_VIDEO_BOUNDARY_KEEP": 4, "SFX_VIDEO_FOLDER_REST": 4,
            "pipeline_log": lambda *args: None})

    def generation_database(self):
        database = sqlite3.connect(":memory:", check_same_thread=False)
        database.row_factory = sqlite3.Row
        database.execute("CREATE TABLE sfx_meta(name TEXT PRIMARY KEY,value TEXT)")
        database.execute("INSERT INTO sfx_meta VALUES('video_deck_cycle','7')")
        database.execute("CREATE TABLE clips(sid TEXT,name TEXT,bytes INT,seconds REAL,folder TEXT,video INT,deck_cycle INT)")
        database.executemany("INSERT INTO clips VALUES(?,?,?,?,?,?,0)", [
            ("a", "same", 10, 2, "first", 1), ("b", "same", 11, 2, "second", 1)])
        database.commit()
        return database

    async def test_receipt_arriving_after_reset_idle_check_cancels_waiting_reset(self):
        worker = OrderedSideEffects()
        database = self.generation_database()
        lock = RLock()
        loaded = Event()
        rotation = {"used": set(), "cycle": 7, "picked": 0}
        ns = self.generation_namespace(worker, lock, database, rotation, loaded)
        results = []
        lock.acquire()
        reset = Thread(target=lambda: results.append(ns["sfx_video_rotation_reset"]()))
        reset.start()
        try:
            self.assertTrue(loaded.wait(1))
            ns["_sfx_video_rotation_mark_clip"]("a")
            self.assertTrue(worker.pending())
        finally:
            lock.release()
        await asyncio.to_thread(reset.join, 2)
        await worker.drain()
        await worker.close()
        self.assertEqual([False], results)
        self.assertEqual("7", database.execute("SELECT value FROM sfx_meta").fetchone()[0])
        self.assertEqual([7, 7], [row[0] for row in database.execute("SELECT deck_cycle FROM clips")])
        database.close()

    async def test_queued_receipt_reads_generation_after_reset_commit_not_stale_memory(self):
        worker = OrderedSideEffects()
        database = self.generation_database()
        lock = RLock()
        rotation = {"used": set(), "cycle": 7, "picked": 0}
        ns = self.generation_namespace(worker, lock, database, rotation)
        # Simulate the reset already owning disk: it advances the generation
        # before the queued receipt obtains that lock; memory is still old.
        held, release = Event(), Event()
        def complete_reset():
            with lock:
                held.set()
                release.wait(2)
                database.execute("UPDATE sfx_meta SET value='8'")
                database.commit()
        reset = Thread(target=complete_reset)
        reset.start()
        try:
            self.assertTrue(held.wait(1))
            ns["_sfx_video_rotation_mark_clip"]("a")
        finally:
            release.set()
        await asyncio.to_thread(reset.join, 2)
        await worker.drain()
        await worker.close()
        self.assertEqual(7, rotation["cycle"])
        self.assertEqual([8, 8], [row[0] for row in database.execute("SELECT deck_cycle FROM clips")])
        database.close()

    async def test_blank_generation_keeps_existing_default_for_mark_and_reset(self):
        for empty in ("", None):
            worker = OrderedSideEffects()
            database = self.generation_database()
            database.execute("UPDATE sfx_meta SET value=?", (empty,))
            database.commit()
            rotation = {"used": set(), "cycle": 7, "picked": 0}
            ns = self.generation_namespace(worker, RLock(), database, rotation)
            ns["_sfx_video_rotation_mark_clip"]("a")
            await worker.drain()
            self.assertEqual([1, 1], [row[0] for row in database.execute("SELECT deck_cycle FROM clips")])
            self.assertTrue(ns["sfx_video_rotation_reset"]())
            self.assertEqual("2", database.execute("SELECT value FROM sfx_meta").fetchone()[0])
            await worker.close()
            database.close()

    async def test_completed_reservation_still_invalidates_reset_checkpoint(self):
        worker = OrderedSideEffects()
        checkpoint = worker.checkpoint()
        worker.submit("a", lambda: None, lambda: None)
        await worker.drain()
        self.assertFalse(worker.pending())
        self.assertTrue(worker.changed(checkpoint))
        await worker.close()


class CameraReportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.wall = 100.0
        self.mono = 10.0
        self.worker = OrderedReports(clock=lambda: self.wall, monotonic=lambda: self.mono)
        self.writes = []
        self.state = {"at": 100.0, "source": {"want_tablet": True}}
        self.ns = {"Header": lambda **kw: None, "_PINELINK_REPORT_WORK": self.worker,
                   "_StaleCameraReport": StaleReportError, "_PINELINK_ANNOUNCE": {"at": 1},
                   "PINELINK_RELAY_ALLOW": [], "PINELINK_RELAY_FILE": None,
                   "pinelink_relay_ip": lambda value: value,
                   "require_auth": self.auth,
                   "pinelink_relay_clean": lambda body, now, announce, peer: {**body, "at": now},
                   "_pinelink_relay_write": lambda path, report: self.writes.append(dict(report)),
                   "_pinelink_relay_state_raw": lambda: dict(self.state),
                   "pinelink_relay_reply": lambda state, report, now, allow: {
                       "ok": True, "want": bool(state["source"]["want_tablet"] and now - state["at"] < 30), "at": now}}
        actual(["pinelink_relay_report_api"], self.ns)

    async def asyncTearDown(self):
        self.worker.close()

    def auth(self, value):
        if value != "test authorized":
            raise PermissionError("authentication required")

    def request(self, value, gate=None):
        async def body():
            if gate:
                await gate.wait()
            return {"value": value}
        return SimpleNamespace(json=body, client=SimpleNamespace(host="127.0.0.1"), url=SimpleNamespace(hostname="127.0.0.1"))

    async def test_delayed_old_body_cannot_overwrite_newer_committed_report(self):
        gate = asyncio.Event()
        first = asyncio.create_task(self.ns["pinelink_relay_report_api"](self.request("old", gate), "test authorized"))
        await asyncio.sleep(0)
        newer = await self.ns["pinelink_relay_report_api"](self.request("new"), "test authorized")
        gate.set()
        older = await first
        self.assertTrue(newer["ok"])
        self.assertFalse(older["ok"])
        self.assertFalse(older["want"])
        self.assertEqual(["new"], [r["value"] for r in self.writes])

    async def test_expired_body_is_discarded_without_writing_or_echoing_success(self):
        gate = asyncio.Event()
        task = asyncio.create_task(self.ns["pinelink_relay_report_api"](self.request("stale", gate), "test authorized"))
        await asyncio.sleep(0)
        self.mono += 20
        self.wall += 20
        gate.set()
        result = await task
        self.assertFalse(result["ok"])
        self.assertFalse(result["want"])
        self.assertEqual([], self.writes)

    async def test_timestamp_is_worker_execution_and_reply_freshness_is_completion_time(self):
        receipt = self.worker.receive()
        self.wall = 105
        def write(report):
            self.writes.append(dict(report))
            self.wall = 132
        result = await self.worker.run(receipt, lambda now: {"at": now}, write,
            lambda: self.state, lambda state, report, now: {"want": now - state["at"] < 30, "at": now})
        self.assertEqual(105, self.writes[0]["at"])
        self.assertEqual(132, result["at"])
        self.assertFalse(result["want"])

    async def test_failed_write_does_not_claim_a_committed_sequence(self):
        receipt = self.worker.receive()
        def fail(report):
            raise OSError("temporary disk failure")
        with self.assertRaises(OSError):
            await self.worker.run(receipt, lambda now: {"at": now}, fail, lambda: {}, lambda *args: {})
        await self.worker.run(receipt, lambda now: {"at": now}, self.writes.append, lambda: {}, lambda *args: {"ok": True})
        self.assertEqual(1, len(self.writes))

    async def test_authentication_precedes_receipt_allocation_and_body_read(self):
        with self.assertRaises(PermissionError):
            await self.ns["pinelink_relay_report_api"](self.request("bad"), "not authorized")
        self.assertEqual(0, self.worker._counter)
        self.assertEqual([], self.writes)
