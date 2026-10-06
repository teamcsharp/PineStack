"""Real NumPy mapping ownership and descriptor regressions; never imports app."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gc
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Barrier, Event, current_thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

import numpy as np

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("library_matrix_cache_test_target", ROOT / "library.py")
LIB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIB)


def descriptor_count():
    fd_dir = Path("/proc/self/fd")
    return len(os.listdir(fd_dir)) if fd_dir.exists() else None


class MatrixCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original_cap = LIB.MATRIX_CACHE
        LIB._MATS.clear()
        LIB._SHARDS.clear()
        LIB._INDEX = None
        LIB.configure(data_dir=self.root, embed=lambda rows: None)

    def tearDown(self):
        LIB._MATS.clear()
        LIB._SHARDS.clear()
        LIB._INDEX = None
        LIB.MATRIX_CACHE = self.original_cap
        gc.collect()
        self.temp.cleanup()

    def write(self, slug, values, root=None):
        root = root or self.root
        target = root / "vec" / (slug + ".npy")
        target.parent.mkdir(parents=True, exist_ok=True)
        values = np.asarray(values, dtype=np.float32)
        with target.open("wb") as stream:
            np.save(stream, values)
        rows = [{"page": i + 1, "heading": "row " + str(i), "text": slug + str(i)}
                for i in range(values.shape[0])]
        target.with_suffix(".jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        return target

    def replace(self, target, values):
        stamp = target.stat().st_mtime_ns
        temp = target.with_suffix(".replacement")
        with temp.open("wb") as stream:
            np.save(stream, np.asarray(values, dtype=np.float32))
        os.utime(temp, ns=(stamp + 10_000_000, stamp + 10_000_000))
        os.replace(temp, target)

    def test_more_than_1024_shards_and_repeated_scan_keep_real_descriptors_bounded(self):
        self.assertEqual(64, LIB.MATRIX_CACHE)
        for index in range(1100):
            self.write("doc" + str(index), [[index, 1], [2, index]])
        baseline = descriptor_count()
        peak = baseline
        for _scan in range(2):
            for index in range(1100):
                matrix = LIB.shard_matrix("doc" + str(index))
                self.assertIsInstance(matrix, np.memmap)
                self.assertEqual((2, 2), matrix.shape)
                np.testing.assert_array_equal(matrix, [[index, 1], [2, index]])
                self.assertLessEqual(len(LIB._MATS), 64)
                current = descriptor_count()
                if current is not None:
                    peak = max(peak, current)
                    self.assertLessEqual(current, baseline + 67)
        del matrix
        self.assertEqual(64, len(LIB._MATS))
        LIB._MATS.clear()
        gc.collect()
        if baseline is not None:
            self.assertLessEqual(descriptor_count(), baseline + 2)
        print(json.dumps({"matrix_cache_fd_receipt": {"shards": 1100, "scans": 2,
              "cache_cap": 64, "baseline_fd": baseline, "peak_fd": peak,
              "fd_after_cache_release": descriptor_count()}}))

    def test_cache_hit_refreshes_lru_and_only_old_cache_ownership_is_evicted(self):
        LIB.MATRIX_CACHE = 2
        for slug in ("a", "b", "c"):
            self.write(slug, [[1, 2]])
        first = LIB.shard_matrix("a")
        borrowed = LIB.shard_matrix("b")
        self.assertIs(first, LIB.shard_matrix("a"))
        LIB.shard_matrix("c")
        self.assertEqual(["a", "c"], list(LIB._MATS))
        self.assertFalse(borrowed._mmap.closed)
        np.testing.assert_array_equal(borrowed, [[1, 2]])

    def test_borrowed_numpy_view_keeps_evicted_mapping_alive_until_last_owner_drops(self):
        LIB.MATRIX_CACHE = 1
        self.write("a", [[3, 4]])
        self.write("b", [[5, 6]])
        matrix = LIB.shard_matrix("a")
        mapping = weakref.ref(matrix._mmap)
        view = np.asarray(matrix)[0]
        LIB.shard_matrix("b")
        self.assertNotIn("a", LIB._MATS)
        del matrix
        gc.collect()
        self.assertIsNotNone(mapping())
        self.assertFalse(mapping().closed)
        self.assertEqual(11, float(view @ np.asarray([1, 2])))
        del view
        gc.collect()
        self.assertIsNone(mapping())

    @unittest.skipUnless(os.name == "posix", "atomic replacement of mapped files requires POSIX")
    def test_replacement_drops_only_cache_owner_and_retained_old_view_stays_readable(self):
        target = self.write("a", [[1, 2]])
        old = LIB.shard_matrix("a")
        view = np.asarray(old)[0]
        self.replace(target, [[7, 8]])
        new = LIB.shard_matrix("a")
        self.assertIsNot(old, new)
        np.testing.assert_array_equal(new, [[7, 8]])
        np.testing.assert_array_equal(view, [1, 2])
        self.assertFalse(old._mmap.closed)

    def test_unchanged_version_reuses_mapping_and_mtime_change_invalidates_cache(self):
        target = self.write("a", [[1, 2]])
        first = LIB.shard_matrix("a")
        self.assertIs(first, LIB.shard_matrix("a"))
        stamp = target.stat().st_mtime_ns
        os.utime(target, ns=(stamp + 10_000_000, stamp + 10_000_000))
        changed = LIB.shard_matrix("a")
        self.assertIsNot(first, changed)
        self.assertIs(changed, LIB.shard_matrix("a"))
        np.testing.assert_array_equal(changed, [[1, 2]])
        self.assertFalse(first._mmap.closed)

    def test_simultaneous_same_version_loads_publish_one_mapping(self):
        self.write("a", [[1, 2]])
        gate = Barrier(2)
        mappings = []
        def load(*args, **kwargs):
            result = np.load(*args, **kwargs)
            mappings.append(weakref.ref(result._mmap))
            gate.wait(timeout=3)
            return result
        with patch.object(LIB, "_numpy", return_value=SimpleNamespace(load=load)):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(LIB.shard_matrix, "a") for _ in range(2)]
                results = [future.result(timeout=5) for future in futures]
        gc.collect()
        self.assertIs(results[0], results[1])
        self.assertEqual(1, len(LIB._MATS))
        self.assertEqual(1, sum(mapping() is not None for mapping in mappings))
        np.testing.assert_array_equal(results[0], [[1, 2]])

    @unittest.skipUnless(os.name == "posix", "atomic replacement of mapped files requires POSIX")
    def test_inflight_old_version_is_not_published_after_atomic_replacement(self):
        target = self.write("a", [[1, 2]])
        loaded, resume = Event(), Event()
        def load(*args, **kwargs):
            matrix = np.load(*args, **kwargs)
            loaded.set()
            if not resume.wait(3):
                raise TimeoutError("test load did not resume")
            return matrix
        with patch.object(LIB, "_numpy", return_value=SimpleNamespace(load=load)):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(LIB.shard_matrix, "a")
                try:
                    self.assertTrue(loaded.wait(2))
                    self.replace(target, [[7, 8]])
                finally:
                    resume.set()
                old = future.result(timeout=5)
        self.assertNotIn("a", LIB._MATS)
        np.testing.assert_array_equal(old, [[1, 2]])
        np.testing.assert_array_equal(LIB.shard_matrix("a"), [[7, 8]])

    @unittest.skipUnless(os.name == "posix", "atomic replacement of mapped files requires POSIX")
    def test_old_load_cannot_overwrite_new_entry_published_after_its_second_stat(self):
        target = self.write("a", [[1, 2]])
        captured, resume = Event(), Event()
        original_stat = Path.stat
        old_stats = 0
        def paused_old_stat(candidate, *args, **kwargs):
            nonlocal old_stats
            observed = original_stat(candidate, *args, **kwargs)
            if candidate == target and current_thread().name.startswith("old-cache-load"):
                old_stats += 1
                if old_stats == 2:
                    # Return this old version only AFTER a fresh version has
                    # published, reproducing the outside-lock publication race.
                    captured.set()
                    if not resume.wait(3):
                        raise TimeoutError("test old stat did not resume")
            return observed
        with patch.object(Path, "stat", paused_old_stat):
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="old-cache-load") as pool:
                future = pool.submit(LIB.shard_matrix, "a")
                try:
                    self.assertTrue(captured.wait(2))
                    self.replace(target, [[7, 8]])
                    fresh = LIB.shard_matrix("a")
                    self.assertIs(fresh, LIB._MATS["a"][1])
                finally:
                    resume.set()
                old = future.result(timeout=5)
        np.testing.assert_array_equal(old, [[1, 2]])
        np.testing.assert_array_equal(fresh, [[7, 8]])
        self.assertIs(fresh, LIB._MATS["a"][1])
        self.assertIs(fresh, LIB.shard_matrix("a"))
        self.assertFalse(old._mmap.closed)

    def test_data_directory_change_with_same_slug_and_mtime_cannot_reuse_old_matrix(self):
        first_path = self.write("a", [[1, 2]])
        old = LIB.shard_matrix("a")
        other = self.root / "other"
        second_path = self.write("a", [[7, 8]], root=other)
        stamp = first_path.stat().st_mtime_ns
        os.utime(second_path, ns=(stamp, stamp))
        LIB.configure(data_dir=other, embed=lambda rows: None)
        new = LIB.shard_matrix("a")
        self.assertIsNot(old, new)
        np.testing.assert_array_equal(new, [[7, 8]])
        np.testing.assert_array_equal(old, [[1, 2]])

    def test_inflight_load_from_previous_data_directory_cannot_poison_new_cache(self):
        self.write("a", [[1, 2]])
        other = self.root / "other"
        self.write("a", [[7, 8]], root=other)
        loaded, resume = Event(), Event()
        def load(*args, **kwargs):
            matrix = np.load(*args, **kwargs)
            loaded.set()
            if not resume.wait(3):
                raise TimeoutError("test load did not resume")
            return matrix
        with patch.object(LIB, "_numpy", return_value=SimpleNamespace(load=load)):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(LIB.shard_matrix, "a")
                try:
                    self.assertTrue(loaded.wait(2))
                    LIB.configure(data_dir=other, embed=lambda rows: None)
                finally:
                    resume.set()
                old = future.result(timeout=5)
        self.assertNotIn("a", LIB._MATS)
        np.testing.assert_array_equal(old, [[1, 2]])
        np.testing.assert_array_equal(LIB.shard_matrix("a"), [[7, 8]])

    def test_real_ranking_matches_dense_baseline_across_repeated_evictions(self):
        LIB.MATRIX_CACHE = 1
        values = {"a": [[1, 0], [0, 1]], "b": [[.25, .5], [.75, 0]],
                  "c": [[-.5, 0], [.125, 1]]}
        LIB._INDEX = {"docs": {slug: {"slug": slug, "title": slug, "state": "ready", "chunks": 2}
                               for slug in values}}
        for slug, rows in values.items():
            self.write(slug, rows)
        query = np.asarray([1, 0], dtype=np.float32)
        expected = sorted([(float(np.asarray(rows, dtype=np.float32)[i] @ query), slug, i + 1)
                           for slug, rows in values.items() for i in range(2)], reverse=True)
        for _scan in range(3):
            actual = LIB._vector_rows(query, 2)
            self.assertEqual(expected, [(row["cosine"], row["slug"], row["page"]) for row in actual])
            self.assertEqual(1, len(LIB._MATS))

    def test_missing_and_invalid_files_preserve_existing_none_result(self):
        self.assertIsNone(LIB.shard_matrix("missing"))
        target = self.root / "vec" / "bad.npy"
        target.write_bytes(b"invalid npy")
        self.assertIsNone(LIB.shard_matrix("bad"))
        self.assertEqual(0, len(LIB._MATS))


if __name__ == "__main__":
    unittest.main()
