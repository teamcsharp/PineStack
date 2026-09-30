# -*- coding: utf-8 -*-
"""[model-pull] the header pencil's pull: what a pasted line becomes, and the
job a streamed /api/pull leaves behind.

Runs the shipped source of the new functions (extracted from app.py) against
a fake Ollama stream - never the live app, never the real Ollama."""
import ast
import asyncio
import io
import json
import os
import re
import time
import unittest
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SRC = str(os.environ.get("MODEL_PULL_APP_SRC")
          or (Path(__file__).resolve().parents[1] / "app.py"))
S = io.open(SRC, encoding="utf-8").read()
TREE = ast.parse(S)
LINES = S.split("\n")


def fn(name):
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            start = n.lineno - 1
            if n.decorator_list:
                start = n.decorator_list[0].lineno - 1
            return "\n".join(LINES[start:n.end_lineno])
    raise AssertionError("no function " + name)


def const(name):
    for n in TREE.body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(getattr(t, "id", "") == name for t in targets):
                return "\n".join(LINES[n.lineno - 1:n.end_lineno])
    raise AssertionError("no constant " + name)


class _App:
    def get(self, *a, **k):
        return lambda f: f

    post = get


class _HTTPException(Exception):
    def __init__(self, status_code=500, detail=""):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _Reply:
    def __init__(self, status, lines, body=b""):
        self.status_code = status
        self._lines = lines
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aread(self):
        return self._body

    async def aiter_lines(self):
        for line in self._lines:
            await asyncio.sleep(0)
            yield line


class _Tags:
    def __init__(self, names):
        self._names = names

    def json(self):
        return {"models": [{"name": n} for n in self._names]}


def fake_httpx(reply, tags):
    sent = []

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, json=None):
            sent.append((method, url, json))
            return reply

        async def get(self, url):
            return _Tags(tags)

    class Httpx:
        AsyncClient = Client

        @staticmethod
        def Timeout(**k):
            return k

    return Httpx, sent


def load(reply=None, tags=(), caps=("completion", "tools")):
    switched = []
    httpx, sent = fake_httpx(reply, list(tags))

    async def model_capabilities(name):
        return list(caps)

    ns: dict[str, Any] = {
        "Any": Any, "re": re, "json": json, "time": time, "uuid": uuid,
        "asyncio": asyncio, "urlparse": urlparse, "httpx": httpx,
        "OLLAMA_URL": "http://ollama.test", "VISION_MODEL": "gemma4:e2b",
        "_MODEL_CAPS": {}, "model_capabilities": model_capabilities,
        "writer_model_apply": lambda m: switched.append(m) or {"model": m},
        "app": _App(), "Request": object, "HTTPException": _HTTPException,
        "Header": lambda default=None: default,
        "require_auth": lambda a: None, "require_read_auth": lambda a: None,
    }
    for name in ("_OLLAMA_PULLS", "_OLLAMA_PULL_KEEP_JOBS",
                 "_OLLAMA_PULL_KEEP_LINES", "_OLLAMA_PULL_NAME",
                 "_OLLAMA_HOSTS", "_HF_HOSTS"):
        exec(const(name), ns)
    for name in ("ollama_pull_ref", "_ollama_pull_say", "_ollama_pull_size",
                 "_ollama_pull_layer", "_ollama_pull_stored",
                 "_ollama_pull_run", "_ollama_pull_view", "ollama_pull_start",
                 "ollama_pull_cancel"):
        exec(fn(name), ns)
    return ns, sent, switched


def lines(*events):
    return [json.dumps(e) for e in events]


GOOD = lines(
    {"status": "pulling manifest"},
    {"status": "pulling 4c2a1e9d3f0b", "digest": "sha256:4c2a1e9d3f0b7777",
     "total": 7162000000, "completed": 0},
    {"status": "pulling 4c2a1e9d3f0b", "digest": "sha256:4c2a1e9d3f0b7777",
     "total": 7162000000, "completed": 3000000000},
    {"status": "pulling 4c2a1e9d3f0b", "digest": "sha256:4c2a1e9d3f0b7777",
     "total": 7162000000, "completed": 7162000000},
    {"status": "pulling 0ba8f0e314b4", "digest": "sha256:0ba8f0e314b49999",
     "total": 12000, "completed": 12000},
    {"status": "verifying sha256 digest"},
    {"status": "writing manifest"},
    {"status": "success"},
)


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def job(model="huihui_ai/gemma-4-abliterated:e2b", use=True):
    return {"id": "j1", "asked": model, "model": model, "use": use,
            "state": "pulling", "status": "starting", "started": time.time(),
            "seq": 0, "log": [], "layers": {}}


class PastedLineBecomesAName(unittest.TestCase):
    def setUp(self):
        self.ref = load()[0]["ollama_pull_ref"]

    def test_the_operators_own_line(self):
        self.assertEqual(self.ref("ollama run huihui_ai/gemma-4-abliterated:e2b"),
                         "huihui_ai/gemma-4-abliterated:e2b")

    def test_command_forms(self):
        self.assertEqual(self.ref("ollama pull gemma3:4b"), "gemma3:4b")
        self.assertEqual(self.ref("  `ollama run --verbose qwen3:8b`  "), "qwen3:8b")
        self.assertEqual(self.ref("gemma4:e2b"), "gemma4:e2b")

    def test_ollama_com_links(self):
        self.assertEqual(
            self.ref("https://ollama.com/huihui_ai/gemma-4-abliterated:e2b"),
            "huihui_ai/gemma-4-abliterated:e2b")
        self.assertEqual(self.ref("https://ollama.com/library/gemma3:4b"), "gemma3:4b")
        self.assertEqual(self.ref("ollama.com/huihui_ai/gemma-4-abliterated/tags"),
                         "huihui_ai/gemma-4-abliterated")

    def test_hugging_face_links(self):
        self.assertEqual(
            self.ref("https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF"),
            "hf.co/bartowski/Llama-3.2-1B-Instruct-GGUF")
        self.assertEqual(
            self.ref("https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF"
                     "/blob/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf"),
            "hf.co/bartowski/Llama-3.2-1B-Instruct-GGUF:Q4_K_M")
        self.assertEqual(self.ref("hf.co/bartowski/Llama-3.2-1B-Instruct-GGUF:Q8_0"),
                         "hf.co/bartowski/Llama-3.2-1B-Instruct-GGUF:Q8_0")

    def test_refusals(self):
        for bad in ("", "   ", "ollama run", "gemma; ls", "../../etc/passwd",
                    "https://huggingface.co/onlyuser", "$(reboot)"):
            self.assertEqual(self.ref(bad), "", bad)


class StreamLeavesAJob(unittest.TestCase):
    def run_job(self, reply, use=True, tags=("huihui_ai/gemma-4-abliterated:e2b",),
                caps=("completion", "tools")):
        ns, sent, switched = load(reply, tags, caps)
        j = job(use=use)
        asyncio.run(ns["_ollama_pull_run"](j))
        return ns, j, sent, switched

    def test_a_good_pull_lands_and_becomes_the_writer(self):
        ns, j, sent, switched = self.run_job(_Reply(200, GOOD))
        self.assertEqual(j["state"], "done")
        self.assertEqual(sent[0][1], "http://ollama.test/api/pull")
        self.assertEqual(sent[0][2]["model"], "huihui_ai/gemma-4-abliterated:e2b")
        self.assertTrue(sent[0][2]["stream"])
        self.assertEqual(switched, ["huihui_ai/gemma-4-abliterated:e2b"])
        view = ns["_ollama_pull_view"](j)
        self.assertEqual(view["total"], 7162012000)
        self.assertEqual(view["completed"], 7162012000)
        said = [l["text"] for l in view["log"]]
        self.assertEqual(said[0], "$ ollama pull huihui_ai/gemma-4-abliterated:e2b")
        for want in ("pulling manifest", "verifying sha256 digest",
                     "writing manifest", "success"):
            self.assertIn(want, said)
        # a layer's status repeats with every chunk: one line in, one line out
        self.assertEqual(sum(1 for t in said if t.startswith("pulling 4c2a1e9d3f0b")), 1)
        self.assertTrue(any(t.startswith("4c2a1e9d3f0b downloaded") for t in said))
        self.assertTrue(any(t.startswith("0ba8f0e314b4 already here") for t in said))
        self.assertTrue(any("no vision" in t and "gemma4:e2b" in t for t in said))
        self.assertTrue(any(t.startswith("the writer is now") for t in said))
        self.assertEqual(ns["_ollama_pull_view"](j, since=view["seq"])["log"], [])

    def test_unticked_it_lands_without_touching_the_writer(self):
        ns, j, sent, switched = self.run_job(_Reply(200, GOOD), use=False)
        self.assertEqual(j["state"], "done")
        self.assertEqual(switched, [])
        self.assertFalse(j.get("switched"))

    def test_a_bare_name_is_switched_under_the_name_ollama_filed(self):
        ns, sent, switched = load(_Reply(200, GOOD), ["gemma3:latest"])
        j = job(model="gemma3")
        asyncio.run(ns["_ollama_pull_run"](j))
        self.assertEqual(j["stored"], "gemma3:latest")
        self.assertEqual(switched, ["gemma3:latest"])

    def test_an_error_in_the_stream_is_the_jobs_error(self):
        reply = _Reply(200, lines({"status": "pulling manifest"},
                                  {"error": "pull model manifest: file does not exist"}))
        ns, j, sent, switched = self.run_job(reply)
        self.assertEqual(j["state"], "error")
        self.assertIn("file does not exist", j["error"])
        self.assertEqual(switched, [])
        self.assertTrue(j["log"][-1]["text"].startswith("error:"))

    def test_a_refused_request_says_what_ollama_said(self):
        reply = _Reply(404, [], json.dumps({"error": "model not found"}).encode())
        ns, j, sent, switched = self.run_job(reply)
        self.assertEqual(j["state"], "error")
        self.assertIn("404", j["error"])
        self.assertIn("model not found", j["error"])

    def test_a_stream_that_stops_short_is_not_success(self):
        reply = _Reply(200, lines({"status": "pulling manifest"}))
        ns, j, sent, switched = self.run_job(reply)
        self.assertEqual(j["state"], "error")
        self.assertEqual(switched, [])


class AWholeLayerMovesNoBytes(unittest.TestCase):
    def test_a_repeated_last_event_does_not_revive_the_rate(self):
        # Measured live on all-minilm:22m: the layer finished inside half a
        # second of the last sample, Ollama repeated the final event, and the
        # total rate sat at 8.6 MB/s with nothing moving.
        ns = load()[0]
        j = job()
        ev = {"digest": "sha256:797b70c4edf8", "total": 100}
        ns["_ollama_pull_layer"](j, {**ev, "completed": 0}, 0.0)
        ns["_ollama_pull_layer"](j, {**ev, "completed": 50}, 1.0)
        self.assertGreater(j["layers"]["sha256:797b70c4edf8"]["rate"], 0)
        ns["_ollama_pull_layer"](j, {**ev, "completed": 100}, 1.2)
        ns["_ollama_pull_layer"](j, {**ev, "completed": 100}, 2.0)
        ns["_ollama_pull_layer"](j, {**ev, "completed": 100}, 3.0)
        lay = j["layers"]["sha256:797b70c4edf8"]
        self.assertTrue(lay["whole"])
        self.assertEqual(lay["rate"], 0.0)
        self.assertEqual(ns["_ollama_pull_view"](j)["rate"], 0.0)
        self.assertEqual(sum(1 for l in j["log"] if "downloaded" in l["text"]), 1)


class TheDoor(unittest.TestCase):
    def test_start_refuses_nonsense_and_a_second_pull(self):
        ns, sent, switched = load(_Reply(200, GOOD))

        async def go():
            with self.assertRaises(_HTTPException) as bad:
                await ns["ollama_pull_start"](_Req({"model": "gemma; ls"}), None)
            self.assertEqual(bad.exception.status_code, 400)
            first = await ns["ollama_pull_start"](
                _Req({"model": "ollama run huihui_ai/gemma-4-abliterated:e2b"}), None)
            again = await ns["ollama_pull_start"](
                _Req({"model": "huihui_ai/gemma-4-abliterated:e2b"}), None)
            self.assertEqual(first["id"], again["id"])
            with self.assertRaises(_HTTPException) as busy:
                await ns["ollama_pull_start"](_Req({"model": "gemma3:4b"}), None)
            self.assertEqual(busy.exception.status_code, 409)
            task = ns["_OLLAMA_PULLS"][first["id"]].get("_task")
            if task is not None:
                await task
            return first["id"]

        jid = asyncio.run(go())
        self.assertEqual(ns["_OLLAMA_PULLS"][jid]["state"], "done")

    def test_stop_cancels_the_pull(self):
        slow = [json.dumps({"status": "pulling manifest"})] + [
            json.dumps({"status": "pulling aa", "digest": "sha256:aa",
                        "total": 100, "completed": i}) for i in range(50)]

        class Slow(_Reply):
            async def aiter_lines(self):
                for line in self._lines:
                    await asyncio.sleep(0.01)
                    yield line

        ns, sent, switched = load(Slow(200, slow))

        async def go():
            view = await ns["ollama_pull_start"](_Req({"model": "gemma3:4b"}), None)
            await asyncio.sleep(0.05)
            await ns["ollama_pull_cancel"](view["id"], None)
            await asyncio.sleep(0.05)
            return ns["_OLLAMA_PULLS"][view["id"]]

        j = asyncio.run(go())
        self.assertEqual(j["state"], "cancelled")
        self.assertTrue(j["log"][-1]["text"].startswith("stopped"))
        self.assertEqual(switched, [])


class OneRoadForTheWriter(unittest.TestCase):
    def test_api_model_goes_through_writer_model_apply(self):
        self.assertIn("return writer_model_apply(model)", fn("switch_model"))
        self.assertIn('settings["model"] = model', fn("writer_model_apply"))


class ThePencil(unittest.TestCase):
    def panel(self):
        start = S.index('CONTROL_PANEL_HTML = r"""')
        return S[start:S.index('\n"""', start + 30)]

    def test_the_pencil_sits_in_the_model_box_and_is_carbon(self):
        html = self.panel()
        box = html[html.index('id="headerModelBox"'):]
        box = box[:box.index("</span>")]
        self.assertIn('id="headerModel"', box)
        self.assertIn('id="modelPullBtn"', box)
        self.assertIn('data-pine-icon="c:edit"', box)
        self.assertIn('onclick="modelPullOpen()"', box)

    def test_no_emoji_in_the_window(self):
        html = self.panel()
        start = html.index("/* ---- [model-pull] The pencil in the model picker")
        block = html[start:html.index("async function modelPullOpen", start) + 4000]
        emoji = [c for c in block if ord(c) >= 0x1F000 or 0x2600 <= ord(c) <= 0x27BF]
        self.assertEqual(emoji, [])


if __name__ == "__main__":
    unittest.main()
