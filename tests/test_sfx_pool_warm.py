"""Prompt verified SFX availability without a cold NAS scan on the event loop."""
import asyncio
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import app


class SfxPoolWarmTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "grabbed"
        self.folder.mkdir()
        self.settings = {**app.DEFAULT_DJ, "sfx_folders": ["grabbed"],
            "sfx_drop_folders": [], "sfx_make": False, "sfx_max_seconds": 4}
        self.bans, self.weights = set(), {}
        self.threads = []
        def folders():
            self.threads.append(threading.get_ident())
            return [self.folder]
        patches = [mock.patch.object(app, name, value) for name, value in {
            "SFX_ROOT": self.root, "SFX_LOCAL_ROOT": self.root / "local",
            "SFX_MADE_DIR": self.root / "made", "SFX_LEN_PATH": self.root / "lengths.json",
            "SFX_ARRIVALS_PATH": self.root / "arrivals.json",
            "_SFX_LEN_CACHE": {}, "_SFX_LEN_DIRTY": [0],
            "_SFX_POOL_CACHE": [], "_SFX_POOL_AT": [0], "_SFX_POOL_READY_AT": [0],
            "_SFX_POOL_FILLING": [False], "_SFX_POOL_JOB": [None],
            "_SFX_POOL_SIGNATURE": [None], "_SFX_SEEN": set(),
            "_SFX_ARRIVALS": {"loaded": False, "rows": {}},
        }.items()]
        patches += [mock.patch.object(app, "dj_settings", return_value=self.settings),
            mock.patch.object(app, "sfx_folders", side_effect=folders),
            mock.patch.object(app, "sfx_bans", return_value=self.bans),
            mock.patch.object(app, "sfx_weights", return_value=self.weights),
            mock.patch.object(app, "pipeline_log"),
            mock.patch.object(app, "fire_and_forget", side_effect=lambda coro: coro.close())]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def clip(self, name, seconds=1):
        path = self.folder / (name + ".mp3")
        path.write_bytes(b"retained clip")
        app._SFX_LEN_CACHE[f"{path}:{path.stat().st_mtime_ns}"] = seconds
        return path

    async def test_cached_subset_publishes_before_full_walk_and_stays_off_loop(self):
        clip = self.clip("ready")
        entered, release = asyncio.Event(), threading.Event()
        loop, real_iterdir = asyncio.get_running_loop(), Path.iterdir
        def delayed_walk(path):
            if path == self.folder:
                loop.call_soon_threadsafe(entered.set)
                release.wait(3)
            return real_iterdir(path)
        with mock.patch.object(Path, "iterdir", delayed_walk):
            task = asyncio.create_task(app._sfx_pool_refresh())
            try:
                await asyncio.wait_for(entered.wait(), 2)
                self.assertEqual(app._SFX_POOL_CACHE, [clip])
                self.assertTrue(app._SFX_POOL_FILLING[0])
                self.assertEqual(app._SFX_POOL_AT[0], 0)
                self.assertGreater(app._SFX_POOL_READY_AT[0], 0)
                self.assertTrue(all(t != threading.get_ident() for t in self.threads))
                await app._sfx_pool_refresh()  # overlapping request never starts another worker
                self.assertEqual(len(self.threads), 1)
            finally:
                release.set()
                await task
        self.assertGreater(app._SFX_POOL_AT[0], 0)
        self.assertFalse(app._SFX_POOL_FILLING[0])

    async def test_restart_loads_duration_file_before_delayed_startup_hook(self):
        clip = self.clip("stored")
        app.SFX_LEN_PATH.write_text(json.dumps(app._SFX_LEN_CACHE))
        app._SFX_LEN_CACHE.clear()
        app._SFX_LEN_CACHE["/unrelated/early.mp3:123"] = 1  # an early probe must not hide disk cache
        with mock.patch.object(app, "sfx_seconds", wraps=app.sfx_seconds):
            await app._sfx_pool_refresh()
        self.assertEqual(app._SFX_POOL_CACHE, [clip])
        self.assertEqual(app._SFX_LEN_CACHE[f"{clip}:{clip.stat().st_mtime_ns}"], 1)

    async def test_warm_requires_finite_short_exact_mtime_and_configured_path(self):
        good = self.clip("good")
        for name, seconds in [("long", 5), ("zero", 0), ("nan", float("nan")), ("infinity", float("inf"))]:
            self.clip(name, seconds)
        changed = self.clip("changed")
        old = changed.stat().st_mtime_ns
        import os
        os.utime(changed, ns=(old + 1000000, old + 1000000))
        missing = self.clip("missing")
        missing.unlink()
        outside = self.root / "outside.mp3"
        outside.write_bytes(b"outside")
        app._SFX_LEN_CACHE[f"{outside}:{outside.stat().st_mtime_ns}"] = 1
        link = self.folder / "outside-link.mp3"
        link.symlink_to(outside)
        app._SFX_LEN_CACHE[f"{link}:{link.stat().st_mtime_ns}"] = 1
        emitted = []
        result = await asyncio.to_thread(app._sfx_pool_warm, [self.folder], 4,
                                          lambda: True, emitted.append)
        self.assertEqual(result, [good])
        self.assertTrue(emitted)
        self.assertEqual(set(emitted[-1]), {good})

    async def test_warm_is_bounded_and_never_probes_uncached_duration(self):
        for i in range(90):
            self.clip(f"clip-{i:03}")
        with mock.patch.object(app, "sfx_seconds", side_effect=AssertionError("warm decoded media")):
            result = await asyncio.to_thread(app._sfx_pool_warm, [self.folder], 4,
                                             lambda: True, lambda rows: None)
        self.assertEqual(len(result), 64)

    async def test_cold_scan_publishes_first_verified_clip_before_slow_probe(self):
        first, second = self.clip("a"), self.clip("b")
        app._SFX_LEN_CACHE.clear()
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        def measure(path):
            self.assertNotEqual(threading.get_ident(), self.main_thread)
            if path == second:
                loop.call_soon_threadsafe(entered.set)
                release.wait(3)
            return 1
        self.main_thread = threading.get_ident()
        with mock.patch.object(app, "sfx_seconds", side_effect=measure):
            task = asyncio.create_task(app._sfx_pool_refresh())
            try:
                await asyncio.wait_for(entered.wait(), 2)
                self.assertEqual(app._SFX_POOL_CACHE, [first])
                self.assertEqual(app._SFX_POOL_AT[0], 0)
            finally:
                release.set()
                await task
        self.assertEqual(app._SFX_POOL_CACHE, [first, second])

    async def test_settings_change_during_scan_refuses_stale_publish_and_requests_restart(self):
        clip = self.clip("old")
        app._SFX_LEN_CACHE.clear()
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        def measure(path):
            loop.call_soon_threadsafe(entered.set)
            release.wait(3)
            return 1
        with mock.patch.object(app, "sfx_seconds", side_effect=measure):
            task = asyncio.create_task(app._sfx_pool_refresh())
            try:
                await asyncio.wait_for(entered.wait(), 2)
                self.settings["sfx_folders"] = ["new-family"]
            finally:
                release.set()
                await task
        self.assertNotIn(clip, app._SFX_POOL_CACHE)
        self.assertEqual(app._SFX_POOL_AT[0], 0)
        self.assertFalse(app._SFX_POOL_FILLING[0])
        app.fire_and_forget.assert_called_once()

    async def test_periodic_refresh_keeps_current_variety_while_probes_continue(self):
        first, second = self.clip("a"), self.clip("b")
        app._SFX_LEN_CACHE.clear()
        app._SFX_POOL_CACHE[:] = [first, second]
        app._SFX_POOL_SIGNATURE[0] = app._sfx_pool_signature()
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        def measure(path):
            if path == second:
                loop.call_soon_threadsafe(entered.set)
                release.wait(3)
            return 1
        with mock.patch.object(app, "sfx_seconds", side_effect=measure):
            task = asyncio.create_task(app._sfx_pool_refresh())
            try:
                await asyncio.wait_for(entered.wait(), 2)
                self.assertEqual(app._SFX_POOL_CACHE, [first, second])
            finally:
                release.set()
                await task
        self.assertEqual(app._SFX_POOL_CACHE, [first, second])

    async def test_new_ban_and_zero_weight_filter_progressive_and_final_publication(self):
        good, banned, down = self.clip("good"), self.clip("banned"), self.clip("down")
        self.bans.add(app.sfx_id(banned))
        self.weights[app.sfx_id(down)] = 0
        await app._sfx_pool_refresh()
        self.assertEqual(app._SFX_POOL_CACHE, [good])

    async def test_recent_arrival_still_bypasses_rotating_folder_cap(self):
        first, fresh = self.clip("a"), self.clip("z")
        app._SFX_ARRIVALS.update(loaded=True, rows={str(first): 0, str(fresh): time.time()})
        with (mock.patch.object(app, "SFX_MAX_FILES", 1),
              mock.patch.object(app.random, "sample", return_value=[first])):
            await app._sfx_pool_refresh()
        self.assertEqual(app._SFX_POOL_CACHE, [first, fresh])


if __name__ == "__main__":
    unittest.main()
