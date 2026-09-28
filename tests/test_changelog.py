"""The operator changelog always answers: from a durable cache, never from Git.

2026-09-28: the popup said "Changelog unavailable: Git history is unavailable:
[Errno 2] No such file or directory: 'git'" - the station's container has no
git binary and the page ran ``git rev-parse``/``git log`` on every open.
Now ``page()`` only reads ``data/changelog_cache.json``; a background
refresher (git when present, the pure-Python reader otherwise) and the
host's commit hooks keep that cache at HEAD, and a failed refresh leaves the
last good cache showing with its as-of time.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import changelog  # noqa: E402
from changelog import ChangeLog, cst_label, load_cache  # noqa: E402

GIT = shutil.which("git")


def _rmtree(path):
    def unlock(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass
    shutil.rmtree(path, onerror=unlock)


def _no_git_binary():
    """shutil.which finds nothing and any git subprocess fails like the container."""
    def missing(cmd, *args, **kwargs):
        if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "git":
            raise FileNotFoundError(2, "No such file or directory", "git")
        return real_run(cmd, *args, **kwargs)
    real_run = subprocess.run
    return mock.patch.multiple(changelog, shutil=mock.Mock(which=lambda name: None),
                               subprocess=mock.Mock(run=missing, PIPE=subprocess.PIPE,
                                                    DEVNULL=subprocess.DEVNULL,
                                                    SubprocessError=subprocess.SubprocessError,
                                                    TimeoutExpired=subprocess.TimeoutExpired))


@unittest.skipUnless(GIT, "the git binary builds the fixture repository")
class ChangeLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.data = Path(self.tmp.name) / "data"
        self.git_run("init", "-q")
        self.git_run("config", "user.name", "Pine Test")
        self.git_run("config", "user.email", "pine@example.test")
        self.git_run("config", "core.autocrlf", "false")
        self.git_run("config", "commit.gpgsign", "false")
        self.first = self.commit({"one.py": "one\n"}, "First task")
        self.second = self.commit({"one.py": "two\n", "two.py": "two\n",
                                   "three.py": "three\n", "four.py": "four\n"},
                                  "Large station task")
        self.log = self.make_log()

    def make_log(self, **kwargs):
        kwargs.setdefault("refresh_in_subprocess", False)
        kwargs.setdefault("background", False)
        return ChangeLog(self.repo, self.data / "changelog_tasks.json", **kwargs)

    def git_run(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              text=True, stdout=subprocess.PIPE).stdout.strip()

    def commit(self, files, message):
        for name, value in files.items():
            (self.repo / name).write_text(value, encoding="utf-8")
        self.git_run("add", ".")
        self.git_run("commit", "-q", "-m", message)
        return self.git_run("rev-parse", "HEAD")

    # -- the graph -------------------------------------------------------
    def test_reads_the_real_graph_and_marks_large_changes(self):
        self.assertTrue(self.log.refresh_now())
        page = self.log.page(limit=1)
        self.assertEqual(page["total"], 2)
        self.assertTrue(page["has_more"])
        row = page["entries"][0]
        self.assertEqual(row["commit"], self.second)
        self.assertEqual(row["file_count"], 4)
        self.assertTrue(row["major"])
        self.assertEqual(row["tokens"]["source"], "unrecorded")
        self.assertIsNone(row["prompt"])
        self.assertRegex(row["completed_label"], r"^\d{2}-\d{2}-\d{2} / \d{1,2}:\d{2} (AM|PM) CST$")
        self.assertFalse(page["stale"])
        self.assertFalse(page["behind"])
        self.assertRegex(page["as_of_label"], r" CST$")
        older = self.log.page(limit=2, before=row["commit"])
        self.assertEqual(len(older["entries"]), 1)
        self.assertEqual(older["entries"][0]["task_name"], "First task")

    def test_records_future_task_telemetry_without_rewriting_the_commit(self):
        self.log.refresh_now()
        self.log.record(self.second[:12], {"task_name": "Show the SFX receipt",
                                           "prompt": "Make clips visible on air",
                                           "goal": "Visible cadence history",
                                           "result": "Receipts now populate the SFX log",
                                           "input_tokens": 120, "output_tokens": 48,
                                           "elapsed_ms": 4300})
        row = self.log.page(limit=1)["entries"][0]
        self.assertEqual(row["prompt"], "Make clips visible on air")
        self.assertEqual(row["tokens"], {"input": 120, "output": 48,
                                          "source": "task ledger"})
        self.assertEqual(row["elapsed_ms"], 4300)
        self.assertEqual(row["goal"], "Visible cadence history")

    def test_ledger_changes_need_no_refresh(self):
        self.log.refresh_now()
        with mock.patch.object(changelog, "refresh_cache",
                               side_effect=AssertionError("no refresh for a ledger edit")):
            self.log.record(self.second, {"prompt": "Name the new task"})
            page = self.log.page(limit=1)
        self.assertEqual(page["entries"][0]["prompt"], "Name the new task")

    # -- the popup never waits on git ------------------------------------------
    def test_the_popup_path_never_runs_a_subprocess(self):
        self.log.refresh_now()
        self.commit({"five.py": "five\n"}, "Committed after the cache")
        with mock.patch.object(changelog.subprocess, "run",
                               side_effect=AssertionError("page() ran a subprocess")):
            page = self.log.page(limit=5)
            self.log.cached_page(limit=5)
            self.log.memory_page(limit=5)
        self.assertEqual(page["total"], 2)            # the cache, not a live walk
        self.assertTrue(page["behind"])                # it knows HEAD moved
        self.assertTrue(page["stale"])                 # so the panel polls again
        self.assertEqual(page["refresh_error"], "")

    def test_new_commit_appears_after_refresh_and_old_files_are_reused(self):
        self.log.refresh_now()
        third = self.commit({"five.py": "five\n"}, "Future task")
        asked = []
        real = changelog._git_numstat

        def watched(repo, shas):
            asked.extend(shas)
            return real(repo, shas)

        with mock.patch.object(changelog, "_git_numstat", watched):
            self.assertTrue(self.log.refresh_now())
        self.assertEqual(asked, [third])               # only the new commit was counted
        page = self.log.page(limit=1)
        self.assertEqual(page["total"], 3)
        self.assertEqual(page["entries"][0]["commit"], third)
        self.assertFalse(page["behind"])

    def test_no_git_binary_builds_the_same_cache_with_the_reader(self):
        with_git = self.data / "with_git.json"
        changelog.refresh_cache(self.repo, with_git, use_git=True)
        with _no_git_binary():
            self.assertFalse(changelog.git_available())
            self.assertTrue(self.log.refresh_now())
            page = self.log.page(limit=5)
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["entries"][0]["file_count"], 4)
        mine, theirs = load_cache(self.log.cache_path), load_cache(with_git)
        self.assertEqual(mine["walk"], "reader")
        self.assertEqual(theirs["walk"], "git")
        strip = lambda rows: [{k: v for k, v in row.items() if k != "numstat"} for row in rows]
        self.assertEqual(strip(mine["commits"]), strip(theirs["commits"]))
        self.assertEqual(mine["numstat"], {"reader": 2})

    def test_record_resolves_a_commit_newer_than_the_cache_without_git(self):
        self.log.refresh_now()
        third = self.commit({"five.py": "five\n"}, "Seconds old")
        with _no_git_binary():
            answer = self.log.record(third[:10], {"prompt": "Recorded before any refresh"})
        self.assertEqual(answer["commit"], third)
        with self.assertRaises(ValueError):
            self.log.record("not-a-sha", {"prompt": "x"})

    # -- failures keep the last good history ------------------------------------------
    def test_failed_refresh_keeps_the_last_good_cache_with_its_age(self):
        self.log.refresh_now()
        before = load_cache(self.log.cache_path)
        self.commit({"five.py": "five\n"}, "Cannot be read yet")
        with mock.patch.object(changelog, "refresh_cache",
                               side_effect=changelog.ChangelogRefreshError("object store unreadable")):
            self.assertFalse(self.log.refresh_now())
        page = self.log.page(limit=5)
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["as_of"], before["as_of"])
        self.assertEqual(page["as_of_label"], cst_label(before["as_of"]))
        self.assertIn("object store unreadable", page["refresh_error"])
        self.assertFalse(page["stale"])                # no endless "refreshing" note
        self.assertTrue(page["behind"])
        self.assertEqual(load_cache(self.log.cache_path), before)  # untouched

    def test_no_git_and_an_unreadable_repository_is_still_a_page(self):
        self.log.refresh_now()
        _rmtree(self.repo / ".git")
        with _no_git_binary():
            self.assertFalse(self.log.refresh_now())
            page = self.log.page(limit=5)
        self.assertEqual(page["total"], 2)
        self.assertTrue(page["as_of_label"])

    def test_nothing_cached_yet_is_a_warming_page_not_an_error(self):
        _rmtree(self.repo / ".git")
        with _no_git_binary():
            page = self.make_log().page(limit=5)
        self.assertEqual(page["entries"], [])
        self.assertTrue(page["warming"])

    def test_cold_process_serves_durable_snapshot_without_calling_git(self):
        self.log.refresh_now()
        cold = self.make_log()
        with mock.patch.object(changelog.subprocess, "run",
                               side_effect=AssertionError("must not invoke Git")):
            page = cold.cached_page(limit=1)
            live = cold.page(limit=1)
        self.assertIsNotNone(page)
        self.assertTrue(page["stale"])
        self.assertEqual(page["entries"][0]["commit"], self.second)
        self.assertEqual(live["entries"][0]["commit"], self.second)

    def test_the_old_row_cache_is_served_until_the_first_refresh(self):
        legacy = {"head": self.second, "ledger_stamp": 0, "entries": [
            {"commit": self.second, "short_commit": self.second[:12], "task_name": "Saved row",
             "files": [{"path": "saved.py", "added": 7, "deleted": 1, "binary": False}],
             "file_count": 1}]}
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "changelog_git_cache.json").write_text(json.dumps(legacy), encoding="utf-8")
        page = self.log.page(limit=5)
        self.assertEqual(page["entries"][0]["task_name"], "Saved row")
        self.assertEqual(page["source"], "saved")
        self.assertTrue(page["stale"])
        # Its git-made numstat is reused, not recounted, by the first refresh.
        with _no_git_binary():
            self.assertTrue(self.log.refresh_now())
        page = self.log.page(limit=5)
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["entries"][0]["files"][0]["path"], "saved.py")
        self.assertEqual(page["entries"][1]["file_count"], 1)   # counted by the reader

    def test_rewritten_history_under_a_cursor_is_an_empty_page(self):
        self.log.refresh_now()
        page = self.log.page(limit=5, before="0" * 40)
        self.assertEqual(page["entries"], [])
        self.assertTrue(page["cursor_lost"])

    def test_a_malformed_trailer_does_not_break_the_page(self):
        self.commit({"six.py": "six\n"}, "Odd trailer\n\nPine-Token-In: lots\nPine-Prompt: hello")
        self.log.refresh_now()
        row = self.log.page(limit=1)["entries"][0]
        self.assertIsNone(row["tokens"]["input"])
        self.assertEqual(row["prompt"], "hello")

    # -- the refresher's real roads --------------------------------------------------------
    def test_refresh_runs_in_a_child_process(self):
        log = self.make_log(refresh_in_subprocess=True)
        self.assertTrue(log.refresh_now(), log.status())
        self.assertEqual(log.page(limit=1)["entries"][0]["commit"], self.second)
        self.assertEqual(log.status()["last_summary"].get("head"), self.second)

    def wait_for(self, log, commit, seconds=30.0):
        deadline = time.time() + seconds
        while time.time() < deadline:
            entries = log.page(limit=1)["entries"]
            if entries and entries[0]["commit"] == commit:
                return True
            time.sleep(0.1)
        return False

    def test_background_thread_follows_head(self):
        log = self.make_log(background=True, poll_seconds=0.2)
        self.addCleanup(log.stop)
        log.start()
        self.assertTrue(self.wait_for(log, self.second))
        third = self.commit({"five.py": "five\n"}, "Picked up by the thread")
        self.assertTrue(self.wait_for(log, third))

    def test_cli_refresh_and_show(self):
        cache = self.data / "cli.json"
        here = Path(changelog.__file__).resolve()
        done = subprocess.run([sys.executable, str(here), "refresh", "--repo", str(self.repo),
                               "--cache", str(cache), "--no-git"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(load_cache(cache)["head"], self.second)
        shown = subprocess.run([sys.executable, str(here), "show", "--repo", str(self.repo),
                                "--cache", str(cache), "-n", "1"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertIn(self.second[:12], shown.stdout)

    def test_cst_label_is_operator_readable(self):
        self.assertEqual(cst_label(0), "not recorded")
        self.assertRegex(cst_label(1790000000), r" CST$")


@unittest.skipUnless(GIT, "hooks are git's")
class CommitHookTests(unittest.TestCase):
    """tools/changelog_hooks.py: a commit on the host refreshes the cache."""

    def tool(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        import changelog_hooks
        return changelog_hooks

    def test_install_keeps_existing_hooks_and_is_idempotent(self):
        hooks = self.tool()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            folder = hooks.hooks_dir(repo)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "post-merge").write_text("#!/bin/sh\necho theirs\nexit 0\n", encoding="utf-8")
            self.assertEqual(sorted(hooks.check(repo)), sorted(hooks.HOOKS))
            hooks.install(repo)
            hooks.install(repo)
            self.assertEqual(hooks.check(repo), [])
            merged = (folder / "post-merge").read_text(encoding="utf-8")
            self.assertEqual(merged.count(hooks.BEGIN), 1)
            self.assertTrue(merged.startswith("#!/bin/sh\n" + hooks.BEGIN))
            self.assertTrue(merged.endswith("echo theirs\nexit 0\n"))
            hooks.uninstall(repo)
            self.assertEqual((folder / "post-merge").read_text(encoding="utf-8"),
                             "#!/bin/sh\necho theirs\nexit 0\n")
            self.assertFalse((folder / "post-commit").exists())

    def test_post_commit_hook_writes_the_cache(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True,
                                            stdout=subprocess.PIPE, text=True).stdout.strip()
            run("init", "-q")
            run("config", "user.name", "Pine Test")
            run("config", "user.email", "pine@example.test")
            run("config", "core.autocrlf", "false")
            for name in ("changelog.py", "git_log_reader.py"):
                shutil.copy(root / name, repo / name)
            tool = root / "tools" / "changelog_hooks.py"
            done = subprocess.run([sys.executable, str(tool), "install", "--repo", str(repo)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            run("add", ".")
            run("commit", "-q", "-m", "Hooked commit")
            head = run("rev-parse", "HEAD")
            cache = repo / "data" / "changelog_cache.json"
            deadline = time.time() + 60
            while time.time() < deadline and load_cache(cache).get("head") != head:
                time.sleep(0.2)
            self.assertEqual(load_cache(cache).get("head"), head)


if __name__ == "__main__":
    unittest.main()
