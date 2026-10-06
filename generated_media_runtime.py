"""Read-only completion notices for every output of the Comfy generation ledger.

The baseline is the existing archive, never a replay of old files. An earlier
queued record becoming done is an event even when newer requests precede it.
"""
from __future__ import annotations

import asyncio
from collections import deque
import hashlib
from pathlib import Path
import threading
from typing import Any
from urllib.parse import quote
import uuid

from fastapi import Header, HTTPException

IMAGE = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".bmp"})
VIDEO = frozenset({".mp4", ".webm", ".mov", ".m4v", ".mkv"})
AUDIO = frozenset({".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"})


def completed_outputs(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """All media outputs, independently of ad/stinger/hourly purpose or kind."""
    found: dict[str, dict[str, Any]] = {}
    for row in records:
        if not isinstance(row, dict) or row.get("status") != "done":
            continue
        # A Gazette screenshot shares the gallery ledger but did not use Comfy.
        if row.get("model") == "gazette" or row.get("kind") == "paper":
            continue
        pid = str(row.get("prompt_id") or "")
        if not pid or not isinstance(row.get("files"), list):
            continue
        for file in row["files"]:
            if not isinstance(file, str) or not file or "/" in file or "\\" in file or ".." in file:
                continue
            suffix = Path(file).suffix.lower()
            kind = "image" if suffix in IMAGE else "video" if suffix in VIDEO else "audio" if suffix in AUDIO else "file"
            identity = hashlib.sha256((pid + "\0" + file).encode()).hexdigest()[:32]
            found[identity] = {
                "id": identity, "prompt_id": pid, "file": file, "kind": kind,
                "title": str(row.get("request") or row.get("purpose") or file)[:180],
                "request": str(row.get("request") or "")[:12000],
                "tags": str(row.get("tags") or "")[:12000],
                "purpose": str(row.get("purpose") or ""),
                "model": str(row.get("model") or ""),
                "ts": row.get("ts"), "analysis": str(row.get("analysis") or ""),
                "h3_prompts": row.get("h3_prompts"),
            }
    return list(found.values())


class MediaEvents:
    def __init__(self, read, sign, keep: int = 10000):
        self.read, self.sign = read, sign
        self.epoch = uuid.uuid4().hex[:16]
        self.lock = threading.Lock()
        self.ready = False
        self.seen: set[str] = set()
        self.events = deque(maxlen=keep)
        self.sequence = 0

    def decorate(self, item):
        item = dict(item)
        filename = quote(item["file"], safe="")
        credential = quote(self.sign("gen:" + item["file"]), safe="")
        route = "image" if item["kind"] == "image" else "media"
        item["url"] = f"/api/generations/{route}/{filename}?t={credential}"
        if item["kind"] == "image":
            item["poster"] = item["url"] + "&w=480"
        elif item["kind"] == "video":
            item["poster_request"] = "/api/generations/poster-url/" + filename
        return item

    def page(self, cursor: str = "", limit: int = 100):
        with self.lock:
            rows = completed_outputs(self.read())
            if not self.ready:
                self.seen.update(row["id"] for row in rows)
                self.ready = True
            else:
                for row in rows:
                    if row["id"] in self.seen:
                        continue
                    self.seen.add(row["id"])
                    self.sequence += 1
                    self.events.append({**row, "sequence": self.sequence})
            head = f"{self.epoch}:{self.sequence}"
            if not cursor:
                return {"events": [], "cursor": head, "baseline": True, "reset": False, "more": False}
            try:
                epoch, number = cursor.split(":", 1)
                offset = int(number)
                if epoch != self.epoch or offset < 0 or offset > self.sequence:
                    raise ValueError
            except (ValueError, AttributeError):
                return {"events": [], "cursor": head, "baseline": True, "reset": True, "more": False}
            behind = bool(self.events and offset < self.events[0]["sequence"] - 1)
            candidates = [row for row in self.events if row["sequence"] > offset]
            page = candidates[:max(1, min(200, int(limit)))]
            return {"events": [self.decorate(row) for row in page],
                    "cursor": f"{self.epoch}:{page[-1]['sequence']}" if page else head,
                    "baseline": False, "reset": False, "more": len(candidates) > len(page),
                    "archive_gap": behind}

    def item(self, identity: str):
        return next((self.decorate(row) for row in completed_outputs(self.read())
                     if row["id"] == identity), None)


def install(host: dict[str, Any]):
    """Register beside the app's existing generation, H3 and vision routes."""
    events = MediaEvents(host["_read_all_generations"], host["media_sign"])

    async def get_events(cursor: str = "", limit: int = 100,
                         authorization: str | None = Header(default=None)):
        host["require_read_auth"](authorization)
        return await asyncio.to_thread(events.page, cursor[:100], limit)

    async def get_item(identity: str, authorization: str | None = Header(default=None)):
        host["require_read_auth"](authorization)
        item = await asyncio.to_thread(events.item, identity)
        if not item:
            raise HTTPException(404, "This generated output is no longer in the archive")
        return item

    async def analyze(identity: str, authorization: str | None = Header(default=None)):
        host["require_auth"](authorization)
        item = await asyncio.to_thread(events.item, identity)
        if not item:
            raise HTTPException(404, "This generated output is no longer in the archive")
        row = host["workshop_generation"](item["prompt_id"])
        if not row:
            raise HTTPException(404, "No such generation")
        try:
            if item["kind"] == "audio":
                path, _ = await asyncio.to_thread(host["workshop_source_path"], "generation", item["file"])
                text = await asyncio.to_thread(host["clip_speech"].transcribe_file, str(path))
                analysis = "Spoken words: " + text if text else "No speech was recognized in this audio."
            elif item["kind"] in {"image", "video"}:
                # Analyze the clicked output, not the first file of a batch.
                analysis = await host["workshop_analyze_generation"]({**row, "files": [item["file"]]})
            else:
                raise HTTPException(400, "This output can be downloaded; visual analysis needs an image or video")
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "id": identity, "file": item["file"], "analysis": analysis}

    app = host["app"]
    async def baseline():
        await asyncio.to_thread(events.page)
    app.add_event_handler("startup", baseline)
    app.add_api_route("/api/generated-media/events", get_events, methods=["GET"])
    app.add_api_route("/api/generated-media/item/{identity}", get_item, methods=["GET"])
    app.add_api_route("/api/generated-media/analyze/{identity}", analyze, methods=["POST"])
    return events
