import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from system2_runtime import System2Runtime


class Host:
    OLLAMA_LANES = 1

    def __init__(self, directory):
        self.DATA_DIR = Path(directory)
        self._RADIO = {"on": False}

    def radio_paused(self):
        return False


class System2RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 2_000_000.0
        self.runtime = System2Runtime(Host(self.temp.name))
        self.runtime.store.now = lambda: self.now

    def save(self, table, body):
        columns = {
            "s2_hours": ("start", "revision", "config"),
            "s2_slots": ("hour_id", "ordinal"),
            "s2_jobs": ("slot_id", "state", "deadline"),
            "s2_candidates": ("kind",),
            "s2_reservations": ("slot_id", "candidate_id", "state", "request_id"),
            "s2_receipts": ("at", "reservation_id"),
            "s2_events": ("request_id", "state", "deadline", "priority"),
        }
        with self.runtime.store._tx() as db:
            self.runtime.store._save(db, table, body, columns[table])

    def seed_hour(self, identity, start, *, state="completed", candidate_id=None,
                  job_state="completed", padding=""):
        slot_id = identity + ":slot"
        candidate_id = candidate_id or identity + ":candidate"
        reservation_id = identity + ":reservation"
        receipt_id = identity + ":receipt"
        old = start + 120
        candidate = {
            "id": candidate_id, "kind": "banter", "created_at": old,
            "slot_id": slot_id, "blocked_reasons": ["absent_from_current_inventory"],
            "source": {"system2_job": slot_id + ":prepare"}, "padding": padding,
        }
        self.save("s2_candidates", candidate)
        self.save("s2_hours", {"id": identity, "start": start, "revision": 1,
                               "config": "test", "updated_at": old, "padding": padding})
        self.save("s2_slots", {"id": slot_id, "hour_id": identity, "ordinal": 0,
                               "start": start, "deadline": start + 3600,
                               "allocations": [{"candidate": {"id": candidate_id}}]})
        self.save("s2_jobs", {"id": slot_id + ":prepare", "slot_id": slot_id,
                              "hour_id": identity, "state": job_state,
                              "deadline": start, "hard_deadline": start + 3600,
                              "finished_at": old})
        self.save("s2_reservations", {
            "id": reservation_id, "slot_id": slot_id, "hour_id": identity,
            "candidate_id": candidate_id, "state": state, "request_id": identity + ":request",
            "reserved_at": old - 10, "completed_at": old,
        })
        self.save("s2_receipts", {"id": receipt_id, "at": old,
                                  "reservation_id": reservation_id, "audible": True})
        with self.runtime.store._tx() as db:
            db.execute("INSERT INTO s2_heard(fingerprint,at,reservation_id,receipt_id) VALUES(?,?,?,?)",
                       (identity + ":fingerprint", old, reservation_id, receipt_id))
        return {"hour": identity, "slot": slot_id, "job": slot_id + ":prepare",
                "candidate": candidate_id, "reservation": reservation_id,
                "receipt": receipt_id, "fingerprint": identity + ":fingerprint"}

    def ids(self, table, key="id"):
        with self.runtime.store._lock:
            db = self.runtime.store._connect()
            try:
                return {row[0] for row in db.execute("SELECT " + key + " FROM " + table)}
            finally:
                db.close()

    def archive_rows(self, path):
        with gzip.open(path, "rt", encoding="utf-8") as source:
            rows = [json.loads(line) for line in source]
        self.assertEqual(rows[0]["type"], "system2_retention")
        self.assertEqual(rows[0]["rows"], len(rows) - 1)
        return rows[1:]

    def test_old_terminal_graph_is_durably_archived_then_pruned_with_metrics(self):
        old = self.seed_hour("hour-old", self.now - 10 * 86400)
        current = self.seed_hour("hour-current", self.now - 100)
        self.save("s2_events", {"id": "old-event", "request_id": "old-request",
                                "state": "completed", "deadline": self.now - 10 * 86400,
                                "completed_at": self.now - 10 * 86400, "priority": 0})

        result = self.runtime.run_retention(now=self.now, max_age_seconds=3 * 86400,
                                            compact=False)

        self.assertEqual(result["deleted_total"], 8)
        self.assertEqual(result["skipped_changed"], 0)
        self.assertTrue(Path(result["archive"]["path"]).is_file())
        self.assertEqual(len(result["archive"]["sha256"]), 64)
        archived = {(row["table"], row["key"]) for row in
                    self.archive_rows(result["archive"]["path"])}
        self.assertIn(("s2_hours", old["hour"]), archived)
        self.assertIn(("s2_slots", old["slot"]), archived)
        self.assertIn(("s2_candidates", old["candidate"]), archived)
        self.assertIn(("s2_events", "old-event"), archived)
        self.assertNotIn(old["hour"], self.ids("s2_hours"))
        self.assertNotIn(old["reservation"], self.ids("s2_reservations"))
        self.assertNotIn(old["fingerprint"], self.ids("s2_heard", "fingerprint"))
        self.assertIn(current["hour"], self.ids("s2_hours"))
        self.assertIn(current["candidate"], self.ids("s2_candidates"))

        status = self.runtime.retention_status()
        self.assertEqual(status["last"]["deleted_total"], result["deleted_total"])
        self.assertEqual(status["observed"]["rows"]["hours"], 1)
        self.assertGreater(status["observed"]["database_bytes"], 0)
        self.assertEqual(status["policy"]["repeat_seconds"], 7200)

    def test_count_limit_prunes_recent_history_but_keeps_newest(self):
        oldest = self.seed_hour("hour-recent-oldest", self.now - 6000)
        middle = self.seed_hour("hour-recent-middle", self.now - 5000)
        newest = self.seed_hour("hour-recent-newest", self.now - 4000)

        self.runtime.run_retention(
            now=self.now, max_age_seconds=86400, compact=False,
            limits={"hours": 1, "jobs": 100, "reservations": 100,
                    "receipts": 100, "heard": 100, "events": 100,
                    "absent_candidates": 100})

        remaining = self.ids("s2_hours")
        self.assertEqual(remaining, {newest["hour"]})
        self.assertNotIn(oldest["slot"], self.ids("s2_slots"))
        self.assertNotIn(middle["reservation"], self.ids("s2_reservations"))

    def test_current_active_and_unfinished_dependency_graphs_are_never_removed(self):
        current = self.seed_hour("hour-current", self.now - 60)
        unfinished = self.seed_hour("hour-unfinished", self.now - 20 * 86400,
                                    job_state="progress")
        active = self.seed_hour("hour-active", self.now - 20 * 86400,
                                state="playing")
        event_hour = self.seed_hour("event-live-event", self.now - 20 * 86400)
        doomed = self.seed_hour("hour-doomed", self.now - 20 * 86400)
        self.save("s2_events", {"id": "live-event", "request_id": "live-request",
                                "state": "pending", "deadline": self.now + 300,
                                "due_at": self.now, "priority": 0})

        zero = {key: 0 for key in self.runtime.RETENTION_LIMITS}
        self.runtime.run_retention(now=self.now, max_age_seconds=7200,
                                   limits=zero, compact=False)

        hours = self.ids("s2_hours")
        self.assertIn(current["hour"], hours)
        self.assertIn(unfinished["hour"], hours)
        self.assertIn(active["hour"], hours)
        self.assertIn(event_hour["hour"], hours)
        self.assertNotIn(doomed["hour"], hours)
        self.assertIn(unfinished["candidate"], self.ids("s2_candidates"))
        self.assertIn(active["reservation"], self.ids("s2_reservations"))
        self.assertIn(active["receipt"], self.ids("s2_receipts"))
        self.assertIn(active["fingerprint"], self.ids("s2_heard", "fingerprint"))
        self.assertIn("live-event", self.ids("s2_events"))

    def test_changed_job_is_revalidated_and_its_whole_graph_survives(self):
        protected = self.seed_hour("hour-raced", self.now - 20 * 86400)
        original = self.runtime._write_retention_archive

        def archive_then_claim(entries, *, now, policy):
            archive = original(entries, now=now, policy=policy)
            with self.runtime.store._tx() as db:
                raw = db.execute("SELECT body FROM s2_jobs WHERE id=?",
                                 (protected["job"],)).fetchone()[0]
                body = json.loads(raw)
                body.update(state="pending", retry_at=self.now)
                self.runtime.store._save(db, "s2_jobs", body,
                                         ("slot_id", "state", "deadline"))
            return archive

        with mock.patch.object(self.runtime, "_write_retention_archive",
                               side_effect=archive_then_claim):
            result = self.runtime.run_retention(now=self.now, max_age_seconds=7200,
                                                compact=False)

        self.assertGreater(result["skipped_changed"], 0)
        self.assertIn(protected["job"], self.ids("s2_jobs"))
        self.assertIn(protected["slot"], self.ids("s2_slots"))
        self.assertIn(protected["hour"], self.ids("s2_hours"))
        self.assertTrue(Path(result["archive"]["path"]).is_file())

    def test_archive_failure_aborts_before_any_database_deletion(self):
        protected = self.seed_hour("hour-archive-failure", self.now - 20 * 86400)

        with mock.patch.object(self.runtime, "_write_retention_archive",
                               side_effect=OSError("audit disk unavailable")):
            with self.assertRaisesRegex(OSError, "audit disk unavailable"):
                self.runtime.run_retention(now=self.now, max_age_seconds=7200,
                                           compact=False)

        self.assertIn(protected["hour"], self.ids("s2_hours"))
        self.assertIn(protected["reservation"], self.ids("s2_reservations"))
        self.assertIn("OSError", self.runtime.retention_status()["last"]["error"])

    def test_automatic_physical_compaction_defers_while_station_is_live(self):
        self.seed_hour("hour-live-compact", self.now - 20 * 86400)
        self.runtime.host._RADIO["on"] = True

        with mock.patch.object(self.runtime, "RETENTION_COMPACT_MIN_BYTES", 0), \
             mock.patch.object(self.runtime, "RETENTION_COMPACT_FREE_RATIO", 0):
            result = self.runtime.run_retention(now=self.now, max_age_seconds=7200)

        self.assertTrue(result["compaction"]["attempted"])
        self.assertFalse(result["compaction"]["ran"])
        self.assertIn("station active", result["compaction"]["reason"])

    def test_forced_compaction_reports_pages_before_and_after(self):
        self.seed_hour("hour-large", self.now - 20 * 86400,
                       padding="x" * (2 * 1024 * 1024))

        result = self.runtime.run_retention(now=self.now, max_age_seconds=7200,
                                            compact=True, force_compact=True)

        compact = result["compaction"]
        self.assertTrue(compact["attempted"])
        self.assertTrue(compact["ran"])
        self.assertLessEqual(compact["after_pages"], compact["before_pages"])
        self.assertEqual(compact["after_free_pages"], 0)

    def test_status_is_a_cached_read_and_never_walks_sqlite(self):
        with mock.patch.object(self.runtime.store, "_connect",
                               side_effect=AssertionError("status touched sqlite")):
            status = self.runtime.retention_status()
        self.assertTrue(status["observed"]["pending"])
        self.assertFalse(status["busy"])


if __name__ == "__main__":
    unittest.main()
