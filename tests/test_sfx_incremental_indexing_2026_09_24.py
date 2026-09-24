import sqlite3
from pathlib import Path
import tempfile
import unittest

import clip_speech
import sfx_match


class IncrementalIndexFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "clips.db"
        self.now = [1000.0]
        self.connection = self.open()
        self.connection.execute("""CREATE TABLE clips (
            path TEXT PRIMARY KEY,
            name TEXT,
            folder TEXT,
            video INTEGER NOT NULL DEFAULT 0,
            seconds REAL,
            playable INTEGER NOT NULL DEFAULT 0
        )""")
        self.connection.execute("""CREATE TABLE sfx_meta (
            name TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""")
        self.connection.commit()

    def open(self):
        return sqlite3.connect(str(self.path), check_same_thread=False)

    def add(self, name, seconds, *, video=False, playable=True):
        path = "/clips/%s.mp4" % name
        self.connection.execute(
            "INSERT INTO clips(path,name,folder,video,seconds,playable) "
            "VALUES (?,?,?,?,?,?)",
            (path, name, "fixture", int(video), seconds, int(playable)))
        self.connection.commit()
        return path

    def indexer(self, connection=None, **kwargs):
        return clip_speech.IncrementalClipIndexer(
            connection or self.connection, clock=lambda: self.now[0],
            retry_base_seconds=30, retry_max_seconds=300, **kwargs)


class IncrementalSelectionTests(IncrementalIndexFixture):
    def test_selection_is_bounded_filtered_and_leased_without_duplicates(self):
        first = self.add("first", 1)
        second = self.add("second", 2, video=True)
        self.add("too-long", clip_speech.MOST_SECONDS + 1)
        self.add("zero", 0, video=True)
        self.add("unplayable", 0.5, video=True, playable=False)
        indexer = self.indexer(lease_seconds=10)

        claimed = indexer.claim("speech", 1)
        self.assertEqual([row["path"] for row in claimed], [first])

        other_connection = self.open()
        self.addCleanup(other_connection.close)
        overlapping = self.indexer(other_connection, lease_seconds=10)
        next_claim = overlapping.claim("speech", 1)
        self.assertEqual([row["path"] for row in next_claim], [second])
        self.assertNotEqual(claimed[0]["token"], next_claim[0]["token"])

        self.assertTrue(indexer.release(claimed[0]))
        self.assertTrue(overlapping.release(next_claim[0]))
        self.assertEqual([row["path"] for row in indexer.claim("vision", 4)],
                         [second])

    def test_requested_batch_cannot_exceed_hard_limit(self):
        for number in range(70):
            self.add("clip-%02d" % number, (number % 20) + 1)
        self.assertEqual(len(self.indexer().claim("speech", 10_000)),
                         sfx_match.INDEX_BATCH_MAX)

    def test_stop_releases_unstarted_rows_without_spending_attempts(self):
        self.add("one", 1)
        self.add("two", 2)
        result = self.indexer().run_batch(
            "speech", lambda job: "unused", 2, should_stop=lambda: True)
        self.assertEqual(result["released"], 2)
        self.assertEqual(result["attempted"], 0)
        self.assertEqual(result["progress"]["attempts"], 0)
        self.assertEqual(result["progress"]["claimed"], 0)


class IncrementalPersistenceTests(IncrementalIndexFixture):
    def test_completed_and_blank_results_persist_as_inspected(self):
        first = self.add("one", 1)
        second = self.add("two", 2)
        indexer = self.indexer()
        completed = indexer.run_batch("speech", lambda job: "clear words", 1)
        self.assertEqual((completed["completed"], completed["productive"]), (1, 1))

        blank = indexer.run_batch("speech", lambda job: "", 1)
        self.assertEqual((blank["completed"], blank["productive"]), (1, 0))
        self.connection.close()

        restored_connection = self.open()
        self.addCleanup(restored_connection.close)
        restored = self.indexer(restored_connection)
        progress = restored.progress("speech")
        self.assertEqual(progress["playable"], 2)
        self.assertEqual(progress["listened"], 2)
        self.assertEqual(progress["with_words"], 1)
        self.assertEqual(progress["left"], 0)
        self.assertEqual(restored.claim("speech", 2), [])
        values = dict(restored_connection.execute(
            "SELECT path, said FROM clips ORDER BY seconds").fetchall())
        self.assertEqual(values, {first: "clear words", second: ""})

    def test_lane_rotation_survives_a_new_worker(self):
        self.add("audio", 1)
        self.add("picture", 2, video=True)
        first = self.indexer().run_next(
            {"speech": lambda job: "spoken", "vision": lambda job: "seen"},
            {"speech": 1, "vision": 1})
        self.assertEqual((first["kind"], first["next_kind"]), ("speech", "vision"))

        restored_connection = self.open()
        self.addCleanup(restored_connection.close)
        second = self.indexer(restored_connection).run_next(
            {"speech": lambda job: "spoken", "vision": lambda job: "seen"},
            {"speech": 1, "vision": 1})
        self.assertEqual((second["kind"], second["next_kind"]),
                         ("vision", "speech"))
        self.assertEqual(second["completed"], 1)

    def test_failures_cool_down_and_do_not_hot_loop_on_one_clip(self):
        first = self.add("poison", 1)
        second = self.add("also-poison", 2)
        seen = []

        def fail(job):
            seen.append(job["path"])
            raise RuntimeError("decoder busy")

        indexer = self.indexer()
        self.assertEqual(indexer.run_batch("speech", fail, 1)["failed"], 1)
        self.assertEqual(indexer.run_batch("speech", fail, 1)["failed"], 1)
        self.assertEqual(seen, [first, second])
        idle = indexer.run_batch("speech", fail, 1)
        self.assertEqual((idle["selected"], idle["attempted"]), (0, 0))
        progress = idle["progress"]
        self.assertEqual((progress["attempts"], progress["failures"],
                          progress["retrying"]), (2, 2, 2))

        self.now[0] += 31
        retried = indexer.run_batch("speech", lambda job: "recovered", 1)
        self.assertEqual(retried["completed"], 1)
        self.assertEqual(seen, [first, second])


class IncrementalMatcherTests(unittest.TestCase):
    def test_new_terms_are_visible_immediately_and_delivery_is_idempotent(self):
        index = sfx_match.ClipIndex().build([
            (7, "1965 clip", "fixture", False, 2.0),
            (8, "breakfast pancakes", "fixture", False, 2.0),
        ])
        self.assertEqual(index.score("spaceship emergency"), [])
        self.assertEqual(index.add_document_terms(
            7, "A spaceship sounds an emergency alarm"), 3)
        self.assertEqual(index.add_document_terms(
            7, "A spaceship sounds an emergency alarm"), 0)
        self.assertEqual(index.score("spaceship emergency alarm")[0].rowid, 7)
        self.assertEqual(index.add_document_terms(999, "missing row"), 0)


if __name__ == "__main__":
    unittest.main()
