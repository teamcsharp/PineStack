"""The station's long-lived clocks are named, observable, and recoverable."""
import ast
import asyncio
import time
import unittest
from pathlib import Path
from typing import Any


SOURCE = Path(__file__).parents[1].joinpath("app.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def worker_source():
    names = {"radio_worker_state", "_radio_worker", "radio_worker_start"}
    nodes = []
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            nodes.append(node)
    return compile(ast.Module(body=nodes, type_ignores=[]),
                   "app.py:radio-workers", "exec")


class RadioWorkerSupervisionTests(unittest.IsolatedAsyncioTestCase):
    def namespace(self):
        events = []
        namespace = {
            "asyncio": asyncio, "time": time, "traceback": __import__("traceback"),
            "Any": Any, "_RADIO": {"on": True}, "_RADIO_RUN": [7],
            "_RADIO_TASK": [], "_RADIO_WORKERS": {},
            "RADIO_WORKER_BACKOFF_MAX": 0.01,
            "pipeline_log": lambda *args, **kwargs: events.append((args, kwargs)),
        }
        exec(worker_source(), namespace)
        return namespace, events

    async def test_persistent_worker_restarts_after_a_fault(self):
        namespace, events = self.namespace()
        calls = []

        async def worker():
            calls.append(len(calls) + 1)
            if len(calls) == 1:
                raise RuntimeError("clock broke")
            namespace["_RADIO"]["on"] = False

        task = namespace["radio_worker_start"]("clock", worker)
        await asyncio.wait_for(task, 1)
        state = namespace["radio_worker_state"]()
        self.assertEqual(calls, [1, 2])
        self.assertEqual(state["workers"][0]["restarts"], 1)
        self.assertTrue(events)

    async def test_generation_change_prevents_resurrection(self):
        namespace, _events = self.namespace()
        calls = []

        async def worker():
            calls.append(1)
            namespace["_RADIO_RUN"][0] += 1

        task = namespace["radio_worker_start"]("old-clock", worker)
        await asyncio.wait_for(task, 1)
        self.assertEqual(calls, [1])
        self.assertEqual(namespace["_RADIO_WORKERS"]["old-clock"]["state"],
                         "stopped")

    async def test_one_shot_job_completes_without_restart(self):
        namespace, _events = self.namespace()
        calls = []

        async def once():
            calls.append(1)

        task = namespace["radio_worker_start"]("startup", once,
                                                persistent=False)
        await asyncio.wait_for(task, 1)
        self.assertEqual(calls, [1])
        self.assertEqual(namespace["_RADIO_WORKERS"]["startup"]["state"],
                         "complete")

    def test_periodic_regrade_is_registered_as_recoverable(self):
        self.assertIn('radio_worker_start("regrade", regrade_once)', SOURCE)
        self.assertNotIn(
            'radio_worker_start("regrade", regrade_once, persistent=False)',
            SOURCE)


if __name__ == "__main__":
    unittest.main()
