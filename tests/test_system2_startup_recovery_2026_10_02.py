"""Database failure cannot take down unrelated station HTTP and playback tasks."""
import asyncio
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from fastapi import FastAPI, HTTPException
import httpx
import system2_runtime as adapter
from system2 import System2Store


class StartupRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.logs = mock.Mock()
        self.namespace = {"DATA_DIR": self.directory, "pipeline_log": self.logs,
                          "require_read_auth": self.auth, "require_auth": self.auth}
        self.app = FastAPI()
        self.app.get("/healthz")(lambda: {"ok": True})
        self.factory = adapter.install(self.app, self.namespace)

    @staticmethod
    def auth(value):
        if value != "Bearer fixture":
            raise HTTPException(401, "Authentication required")

    async def test_invalid_database_keeps_http_and_workers_alive_without_data_reset(self):
        path = self.directory / "system2.sqlite3"
        original = b"An interrupted database transfer; preserve this evidence."
        path.write_bytes(original)
        constructor = adapter.System2Runtime
        with mock.patch.object(adapter, "System2Runtime", wraps=constructor) as create:
            await self.app.router.startup()
            try:
                await asyncio.sleep(.02)
                workers = [task for task in asyncio.all_tasks()
                           if task.get_name().startswith("system2:")]
                self.assertEqual(len(workers), 4)
                self.assertTrue(all(not task.done() for task in workers))
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                             base_url="http://fixture") as client:
                    self.assertEqual((await client.get("/healthz")).status_code, 200)
                    denied = await client.get("/api/system2/status")
                    self.assertEqual(denied.status_code, 401)
                    failed = await client.get("/api/system2/status", headers={"Authorization": "Bearer fixture"})
                    self.assertEqual(failed.status_code, 503)
                    self.assertTrue(failed.json()["data_preserved"])
                    self.assertGreater(failed.json()["retry_in_seconds"], 0)
                self.assertEqual(create.call_count, 1, "one attempt per retry window, including error logging")
                self.assertEqual(path.read_bytes(), original)
            finally:
                await self.app.router.shutdown()
            self.assertTrue(all(task.done() for task in workers))

    async def test_original_database_recovers_after_cooldown_with_retained_rows(self):
        path = self.directory / "system2.sqlite3"
        good = self.directory / "retained.sqlite3"
        store = System2Store(good)
        with sqlite3.connect(good) as db:
            db.execute("INSERT INTO s2_heard VALUES(?,?,?,?)", ("retained-proof", 1234, "reservation", "receipt"))
        db.close()  # Checkpoint the fixture's WAL before copying its retained bytes.
        original = good.read_bytes()
        path.write_bytes(b"not a database")
        clock = [1000.0]
        constructor = adapter.System2Runtime
        with mock.patch.object(adapter.time, "monotonic", side_effect=lambda: clock[0]), \
             mock.patch.object(adapter, "System2Runtime", wraps=constructor) as create:
            with self.assertRaises(adapter.System2Unavailable):
                self.factory()
            path.write_bytes(original)
            clock[0] = 1010.0
            with self.assertRaises(adapter.System2Unavailable):
                self.factory()
            self.assertEqual(create.call_count, 1)
            clock[0] = 1031.0
            recovered = self.factory()
            self.assertEqual(create.call_count, 2)
            self.assertIs(self.factory(), recovered)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT fingerprint FROM s2_heard").fetchone()[0], "retained-proof")
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    async def test_one_bad_abandoned_job_does_not_hold_healthy_worker_loops(self):
        recovered = self.factory()
        with mock.patch.object(recovered.store, "reclaim_jobs", side_effect=ValueError("malformed old job")) as jobs, \
             mock.patch.object(recovered.store, "reclaim_reservations", return_value=[]) as reservations, \
             mock.patch.object(recovered, "events_tick", new_callable=mock.AsyncMock) as events:
            await self.app.router.startup()
            try:
                await asyncio.sleep(.02)
                jobs.assert_called_once_with("system2-preparer")
                reservations.assert_called_once_with("system2-air")
                self.assertGreaterEqual(events.await_count, 1)
                self.assertTrue(any("malformed old job" in row["message"] for row in recovered._errors))
            finally:
                await self.app.router.shutdown()

    async def test_delayed_initialization_reclaims_abandoned_work_before_workers_run(self):
        path = self.directory / "system2.sqlite3"
        path.write_bytes(b"temporarily unavailable")
        await self.app.router.startup()
        try:
            # Restore only the test database; the real store is never replaced by recovery.
            path.unlink()
            System2Store(path)
            # Constructor cooldown is elapsed before running an actual worker iteration.
            real_clock = adapter.time.monotonic
            with mock.patch.object(adapter.time, "monotonic", side_effect=lambda: real_clock() + 31):
                self.factory()
            recovered = self.factory()
            with mock.patch.object(recovered.store, "reclaim_jobs", return_value=[]) as jobs, \
                 mock.patch.object(recovered.store, "reclaim_reservations", return_value=[]) as reservations, \
                 mock.patch.object(recovered, "events_tick", new_callable=mock.AsyncMock):
                await asyncio.sleep(1.1)
                jobs.assert_called_once_with("system2-preparer")
                reservations.assert_called_once_with("system2-air")
        finally:
            await self.app.router.shutdown()


class FailedConnectionTests(unittest.TestCase):
    def test_connection_is_closed_if_initial_journal_setup_fails(self):
        store = System2Store.__new__(System2Store)
        store.path = Path("fixture.sqlite3")
        store._journal = False
        connection = mock.Mock()
        connection.execute.side_effect = [None, sqlite3.DatabaseError("file is not a database")]
        with mock.patch("system2.sqlite3.connect", return_value=connection):
            with self.assertRaises(sqlite3.DatabaseError):
                store._connect()
        connection.close.assert_called_once()
        self.assertFalse(store._journal)


if __name__ == "__main__":
    unittest.main()
