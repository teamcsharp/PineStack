import subprocess
import tempfile
import unittest
from pathlib import Path

from changelog import ChangeLog, cst_label


class ChangeLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.git_run("init")
        self.git_run("config", "user.name", "Pine Test")
        self.git_run("config", "user.email", "pine@example.test")
        self.commit({"one.py": "one\n"}, "First task")
        self.second = self.commit({"one.py": "two\n", "two.py": "two\n",
                                   "three.py": "three\n", "four.py": "four\n"},
                                  "Large station task")
        self.log = ChangeLog(self.repo, Path(self.tmp.name) / "tasks.json")

    def git_run(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              text=True, stdout=subprocess.PIPE).stdout.strip()

    def commit(self, files, message):
        for name, value in files.items():
            (self.repo / name).write_text(value, encoding="utf-8")
        self.git_run("add", ".")
        self.git_run("commit", "-m", message)
        return self.git_run("rev-parse", "HEAD")

    def test_reads_the_real_graph_and_marks_large_changes(self):
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
        older = self.log.page(limit=2, before=row["commit"])
        self.assertEqual(len(older["entries"]), 1)
        self.assertEqual(older["entries"][0]["task_name"], "First task")

    def test_records_future_task_telemetry_without_rewriting_the_commit(self):
        self.log.page(limit=1)  # establish the Git cache before ledger changes
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

    def test_ledger_refreshes_cached_head_without_another_git_log(self):
        self.log.page(limit=1)
        original_git = self.log._git
        calls = []

        def watched(*args, **kwargs):
            calls.append(args)
            return original_git(*args, **kwargs)

        self.log._git = watched
        self.log.record(self.second, {"prompt": "Name the new task"})
        page = self.log.page(limit=1)
        self.assertEqual(page["entries"][0]["prompt"], "Name the new task")
        self.assertFalse(any("log" in args for args in calls))

    def test_cache_adds_new_head_commits_without_rewalking_old_history(self):
        self.assertEqual(self.log.page()["total"], 2)  # writes the durable baseline
        third = self.commit({"five.py": "five\n"}, "Future task")
        page = self.log.page(limit=1)
        self.assertEqual(page["total"], 3)
        self.assertEqual(page["entries"][0]["commit"], third)

    def test_cst_label_is_operator_readable(self):
        self.assertEqual(cst_label(0), "not recorded")
        self.assertRegex(cst_label(1790000000), r" CST$")


if __name__ == "__main__":
    unittest.main()
