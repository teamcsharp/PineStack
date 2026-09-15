"""Exercise the real report routes without importing or starting the station.

The application import initializes runtime stores. Compile only the diagnostic
functions into an isolated ASGI app and keep every artifact under a temp dir.
"""
import ast
import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response

from script_report_store import ScriptReportStore, REPORT_NAME


def view(phase="tap", line="first", at=1000):
    return {"schema_version": 2, "incident_id": "capture-one", "phase": phase,
            "captured_at_ms": at, "window": {"start_ms": at - 100, "end_ms": at},
            "events": [{"first_ms": at, "last_ms": at, "samples": 1,
                        "highlight_id": line, "active_id": line,
                        "document_revision": "revision-1", "element_index": at,
                        "audio": {"source": "local", "file": "one.wav", "position_end_s": 2}}],
            "rows": {line: {"id": line, "text": "Useful line text", "media": "one.wav"}},
            "snapshot": {"highlight_id": line, "active_id": line,
                         "audio": {"source": "local", "file": "one.wav", "position_s": 2}}}


class ScriptReportRoutes(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).parents[1].joinpath("app.py").read_text(encoding="utf-8")
        wanted = {"script_report_status_api", "script_report_file_api", "_script_report_payload",
                  "_script_report_observe", "_script_report_answer", "script_report_api",
                  "script_report_finish_api", "script_diagnostic_context", "_script_report_attach_inbox"}
        tree = ast.parse(source)
        selected = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name in wanted]
        if {n.name for n in selected} != wanted:
            raise AssertionError("Diagnostic route extraction is incomplete")
        cls.code = compile(ast.Module(body=selected, type_ignores=[]), "app.py:diagnostics", "exec")

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        app = FastAPI()

        def require_auth(authorization):
            if authorization != "Bearer isolated-test":
                raise HTTPException(status_code=401)

        self.inbox = mock.AsyncMock(return_value={"id": 82})
        self.items = [{"id": 82, "text": "Operator's original description"}]
        self.save_images = mock.Mock(return_value=["isolated-image.png"])
        self.ns = dict(Any=Any, Request=Request, Response=Response, Header=Header,
                       HTTPException=HTTPException, asyncio=asyncio, json=json, time=time,
                       Path=Path, app=app, require_auth=require_auth, require_read_auth=require_auth,
                       SCRIPT_REPORT_NAME=REPORT_NAME, SCRIPT_REPORTS_DIR=self.folder,
                       _SCRIPT_REPORT_STORE=ScriptReportStore(self.folder),
                       _save_pine_images=self.save_images, pine_append=self.inbox,
                       pipeline_log=mock.Mock(), _BUILD_MS=123,
                       _RADIO={"on": True, "chat": [], "voice_clips": []}, _AUDIO_OWNER={},
                       _SPEAKING_NOW={}, _STREAM_NOW={}, _LISTENERS={}, _PAGE_ACK_EVENTS=[], _PAGE_DELIVERIES={},
                       _TALK_ACK={}, _PULSE={"stalls": []}, radio_paused=lambda: False)
        self.ns.update(_pine_lock=asyncio.Lock(), pine_read=lambda: self.items,
                       _pine_render=json.dumps, PINE_REQUESTS_PATH=self.folder / "inbox.md")
        exec(self.code, self.ns)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                       headers={"Authorization": "Bearer isolated-test"})
        self.addAsyncCleanup(self.client.aclose)

    async def test_tap_is_durable_before_followup_and_screenshot(self):
        result = await self.client.post("/api/script/report", json={"view": view(), "incident_id": "capture-one"})
        self.assertEqual(result.status_code, 200, result.text)
        got = result.json()
        name = Path(got["file"]).name
        initial = self.ns["_SCRIPT_REPORT_STORE"].read(name)
        self.assertEqual(initial["status"], "awaiting_post")
        self.assertEqual(initial["view"]["captured_at_ms"], 1000)
        self.save_images.assert_not_called()
        response = await self.client.get("/api/script-reports/" + name.replace(".md", ".json"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["inbox_id"], 82)

        result = await self.client.post("/api/script/report/" + name + "/finish", json={
            "incident_id": "capture-one", "view": view("post", "second", 11000),
            "image": "data:image/png;base64,test", "screenshot": {"captured_at_ms": 1200}})
        self.assertEqual(result.status_code, 200, result.text)
        finished = self.ns["_SCRIPT_REPORT_STORE"].read(name)
        self.assertEqual(finished["status"], "complete")
        self.assertEqual([e["highlight_id"] for e in finished["view"]["events"]], ["first", "second"])
        self.assertEqual(finished["server_observed_at_ms"], initial["server_observed_at_ms"])
        self.assertEqual(finished["images"], ["isolated-image.png"])
        self.assertTrue(finished["inbox_images_linked"])
        self.assertIn("Operator's original description", self.items[0]["text"])
        self.assertEqual(self.items[0]["text"].count("[img:isolated-image.png]"), 1)
        self.inbox.assert_awaited_once()

        # A retry must not add events, another image, or another inbox entry.
        self.items[0]["text"] = "Operator annotated the image: [img:annotated.png]"
        await self.client.post("/api/script/report/" + name + "/finish", json={
            "incident_id": "capture-one", "view": view("post", "second", 11000), "image": "same"})
        self.save_images.assert_called_once()
        self.assertEqual(len(self.ns["_SCRIPT_REPORT_STORE"].read(name)["view"]["events"]), 2)
        self.assertNotIn("[img:isolated-image.png]", self.items[0]["text"])

    async def test_flat_client_screenshot_metadata_survives_finish(self):
        got = (await self.client.post("/api/script/report", json={"view": view()})).json()
        name = Path(got["file"]).name
        result = await self.client.post("/api/script/report/" + name + "/finish", json={
            "incident_id": "capture-one", "view": view("post", "second", 11000),
            "screenshot_at_ms": 1400, "screenshot_requested_at_ms": 1100,
            "screenshot_source": "shotView", "screenshot_error": "image unavailable"})
        self.assertEqual(result.status_code, 200, result.text)
        screenshot = self.ns["_SCRIPT_REPORT_STORE"].read(name)["screenshot"]
        self.assertEqual(screenshot, {"captured_at_ms": 1400, "requested_at_ms": 1100,
                                     "source": "shotView", "error": "image unavailable"})

    async def test_rapid_taps_get_distinct_artifacts_and_complete_json(self):
        names = []
        for _ in range(2):
            result = await self.client.post("/api/script/report", json={"view": view()})
            self.assertEqual(result.status_code, 200, result.text)
            names.append(Path(result.json()["file"]).name)
        self.assertNotEqual(*names)
        for name in names:
            report = self.ns["_SCRIPT_REPORT_STORE"].read(name)
            md = self.folder.joinpath(name).read_text(encoding="utf-8")
            self.assertIn(name.replace(".md", ".json"), md)
            self.assertNotIn('"events":', md)
            self.assertEqual(report["view"]["rows"]["first"]["text"], "Useful line text")

    async def test_wrong_identity_cannot_overwrite_initial_evidence(self):
        got = (await self.client.post("/api/script/report", json={"view": view()})).json()
        name = Path(got["file"]).name
        before = self.folder.joinpath(name.replace(".md", ".json")).read_bytes()
        result = await self.client.post("/api/script/report/" + name + "/finish", json={
            "incident_id": "wrong", "view": view("post")})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.folder.joinpath(name.replace(".md", ".json")).read_bytes(), before)

    async def test_old_markdown_is_readable_and_all_writes_require_auth(self):
        name = "script_2026-09-14_120000.md"
        self.folder.joinpath(name).write_text("Legacy report: café", encoding="utf-8")
        result = await self.client.get("/api/script-reports/" + name)
        self.assertEqual(result.json()["text"], "Legacy report: café")
        self.assertEqual(result.json()["bytes"], len("Legacy report: café".encode("utf-8")))
        result = await self.client.post("/api/script/report", json={"view": view()}, headers={"Authorization": "bad"})
        self.assertEqual(result.status_code, 401)
        self.inbox.assert_not_awaited()

    async def test_receipts_are_coalesced_and_queue_capture_does_not_run_repairs(self):
        now = time.time()
        self.ns["_PAGE_ACK_EVENTS"] = [
            {"at": now - 2 + i, "listener_id": "player", "delivery_id": "delivery", "event": "playing",
             "muted": False, "volume": 1, "audible_volume": 1, "current_time": i, "sequence": i + 1}
            for i in range(3)]
        result = self.ns["script_diagnostic_context"](view())
        self.assertEqual(len(result["playback"]["events"]), 1)
        self.assertEqual(result["playback"]["events"][0]["samples"], 3)
        self.assertEqual(result["playback"]["events"][0]["position_end_s"], 2)
        self.assertEqual(result["air"]["owner"], "")

    async def test_finished_feed_history_cannot_displace_the_pending_queue(self):
        self.ns["_RADIO"]["voice_clips"] = [{"delivery_id": "old-%d" % i} for i in range(30)] + [
            {"delivery_id": "next", "media": "next.wav"}]
        self.ns["_PAGE_DELIVERIES"] = {"old-%d" % i: {"state": "ended"} for i in range(30)}
        self.ns["_PAGE_DELIVERIES"]["next"] = {"state": "published"}
        queue = self.ns["script_diagnostic_context"](view())["queue"]
        self.assertEqual(queue["feed_total"], 31)
        self.assertEqual(queue["total"], 1)
        self.assertEqual(queue["rows"][0]["delivery_id"], "next")


if __name__ == "__main__":
    unittest.main()
