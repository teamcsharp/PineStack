"""Bounded, durable media work for fictional Gazette city stories.

All generation goes through callbacks supplied by the application: its existing
Comfy image submission and Workshop H3 path retain their admission and quality
gates. A receipt records every attempt before submission; recovery follows
existing tickets and never repeats a submission with a missing ticket.
"""
from __future__ import annotations

import asyncio
import copy
import html
import json
import math
from pathlib import Path
import re
import time
from typing import Any, Callable

DEFAULT_POLICY = {
    "enabled": True, "images": 1, "videos": 1, "interval_s": 3600.0,
    "deadline_s": 1500.0, "poll_s": 12.0, "duration_s": 4.0,
}
_EDITION = re.compile(r"\d{4}-\d{2}-\d{2}-\d{2}(?:x\d{4})?")
_ARTICLE = re.compile(r"[\w .-]{1,180}\.md")
_FILE = re.compile(r"[\w.\- ()\[\]]{1,200}")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}
_FINAL_FAILURES = {"failed", "error", "cancelled", "audio_failed", "unknown", "lost"}
_OPEN_STATUSES = {"pending", "working", "deferred"}


def policy(raw: Any = None) -> dict[str, Any]:
    out = dict(DEFAULT_POLICY)
    if not isinstance(raw, dict):
        return out
    out["enabled"] = raw.get("enabled", True) is not False
    for key in ("images", "videos"):
        try:
            out[key] = max(0, min(1, int(raw.get(key, out[key]))))
        except (ValueError, TypeError):
            pass
    for key, low, high in (("interval_s", 60.0, 86400.0),
                            ("deadline_s", 1.0, 2400.0),
                            ("poll_s", 0.01, 60.0),
                            ("duration_s", 2.5, 8.0)):
        try:
            value = float(raw.get(key, out[key]))
            if math.isfinite(value):
                out[key] = max(low, min(high, value))
        except (ValueError, TypeError):
            pass
    return out


def candidates(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only intentionally fictional editorial scenes can request media."""
    found = []
    for article in articles:
        if not isinstance(article, dict) or article.get("error"):
            continue
        meta = article.get("meta") or {}
        editorial = meta.get("editorial") or {}
        if not isinstance(editorial, dict) or editorial.get("fictional") is not True:
            continue
        media = editorial.get("media") or article.get("media") or {}
        file = str(article.get("file") or "")
        if not isinstance(media, dict) or not _ARTICLE.fullmatch(file) or ".." in file:
            continue
        if not any(str(media.get(key) or "").strip()
                   for key in ("image_prompt", "video_prompt")):
            continue
        found.append(article)
    return found[:32]


def _url(value: Any, kind: str) -> str:
    value = str(value or "")
    road = "/api/generations/image/" if kind == "image" else "/api/generations/media/"
    if not value.startswith(road) or any(c in value for c in ('"', "'", "<", ">", "\n", "\r")):
        return ""
    return value


def printable(media: Any) -> dict[str, str]:
    """Poster and real reaction link for the native PDF and static exports."""
    empty = {"image": "", "caption": "", "video": "", "link_label": ""}
    if not isinstance(media, dict):
        return empty
    image = media.get("image") if isinstance(media.get("image"), dict) else {}
    video = media.get("video") if isinstance(media.get("video"), dict) else {}
    image_url = _url(image.get("url"), "image") if image.get("status") == "ready" else ""
    video_url = _url(video.get("url"), "video") if video.get("status") == "ready" else ""
    if not image_url and not video_url:
        return empty
    caption = (str(video.get("caption") or "Fictional reaction scene generated for this story.")
               if video_url else
               str(image.get("caption") or "Fictional city scene generated for this story."))
    return {"image": image_url, "caption": caption[:240], "video": video_url,
            "link_label": "Watch the fictional reaction scene" if video_url else ""}


def render(media: Any, escape: Callable[[Any], str] = html.escape) -> str:
    """One stable-sized scene plate; a finished H3 clip uses its own image poster."""
    scene = printable(media)
    image_url, video_url = scene["image"], scene["video"]
    if not image_url and not video_url:
        return ""
    if video_url:
        poster = ' poster="%s"' % escape(image_url) if image_url else ""
        visual = ('<video controls playsinline preload="none"%s '
                  'style="display:block;width:100%%;aspect-ratio:16/9;object-fit:cover" '
                  'aria-label="Fictional city reaction scene">'
                  '<source src="%s"><a href="%s">Watch the fictional reaction scene</a>'
                  '</video>') % (poster, escape(video_url), escape(video_url))
        caption = scene["caption"]
    else:
        visual = ('<img src="%s" loading="lazy" '
                  'style="display:block;width:100%%;aspect-ratio:16/9;object-fit:cover" '
                  'alt="Fictional city scene generated for this story">') % escape(image_url)
        caption = scene["caption"]
    return ('<figure class="gazette-scene" style="margin:10px 0;break-inside:avoid">'
            + visual + '<figcaption style="font-size:11px;line-height:1.3;margin-top:5px">'
            + escape(caption[:240]) + '</figcaption></figure>')


def estimate(media: Any, width: float) -> float:
    if not render(media):
        return 0.0
    caption = printable(media)["caption"]
    columns = max(12.0, float(width) / 5.0)
    lines = max(1, math.ceil(len(caption) / columns))
    return max(80.0, float(width)) * 9.0 / 16.0 + 30.0 + lines * 16.0


class GazetteMedia:
    """At most one story's image and H3 reaction per interval, with one worker."""

    def __init__(self, edition_dir: Callable, submit_image: Callable,
                 submit_video: Callable, lookup: Callable, attach: Callable,
                 url_for: Callable, exists: Callable, select: Callable | None = None,
                 *, policy: dict[str, Any] | None = None,
                 clock: Callable = time.time, sleep: Callable = asyncio.sleep):
        self.edition_dir = edition_dir
        self.submit_image = submit_image
        self.submit_video = submit_video
        self.lookup = lookup
        self.attach = attach
        self.url_for = url_for
        self.exists = exists
        self.select = select
        self.policy = globals()["policy"](policy)
        self.clock = clock
        self.sleep = sleep
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    def _folder(self, edition_id: str) -> Path:
        if not _EDITION.fullmatch(edition_id):
            raise ValueError("Invalid Gazette edition id")
        folder = Path(self.edition_dir(edition_id))
        if not (folder / "edition.json").is_file():
            raise FileNotFoundError("The Gazette edition is no longer published")
        return folder

    def _edition_at(self, edition_id: str) -> Any:
        return json.loads((self._folder(edition_id) / "edition.json")
                          .read_text(encoding="utf-8")).get("at")

    def _read(self, edition_id: str) -> dict[str, Any]:
        try:
            value = json.loads((self._folder(edition_id) / "media.json").read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, receipt: dict[str, Any]) -> None:
        folder = self._folder(str(receipt["edition"]))
        if "edition_at" in receipt and receipt["edition_at"] != self._edition_at(str(receipt["edition"])):
            raise ValueError("This Gazette edition was reprinted; its old media worker has stopped")
        receipt["updated_at"] = self.clock()
        temporary = folder / "media.json.tmp"
        temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(folder / "media.json")

    def _clock_path(self, edition_id: str) -> Path:
        return self._folder(edition_id).parent / "media-clock.json"

    def _last_started(self, edition_id: str) -> float:
        try:
            return float(json.loads(self._clock_path(edition_id).read_text(encoding="utf-8"))
                         .get("started_at") or 0.0)
        except (OSError, ValueError, TypeError, AttributeError):
            return 0.0

    def _stamp_start(self, edition_id: str) -> None:
        path = self._clock_path(edition_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"started_at": self.clock(), "edition": edition_id}),
                             encoding="utf-8")
        temporary.replace(path)

    async def _save(self, receipt: dict[str, Any], kind: str = "status", url: str = "") -> None:
        await asyncio.to_thread(self._write, receipt)
        await self.attach(str(receipt["edition"]), str(receipt["article"]),
                          kind, url, copy.deepcopy(receipt))

    async def run(self, edition_id: str, articles: list[dict[str, Any]]) -> dict[str, Any]:
        """Reserve one story and return immediately; the newspaper never waits for a GPU."""
        async with self._lock:
            if not self.policy["enabled"]:
                return {"started": False, "reason": "Gazette scene rendering is disabled"}
            if not self.policy["images"] and not self.policy["videos"]:
                return {"started": False, "reason": "Gazette scene caps are zero"}
            if self._task is not None and not self._task.done():
                return {"started": False, "reason": "One Gazette scene is already being followed"}
            existing = await asyncio.to_thread(self._read, edition_id)
            if existing:
                return {"started": False, "reason": "This edition already has a media receipt",
                        "status": existing.get("status")}
            rows = candidates(articles)
            if not rows:
                return {"started": False, "reason": "No fictional city scene requested media"}
            last = await asyncio.to_thread(self._last_started, edition_id)
            if last and self.clock() - last < self.policy["interval_s"]:
                return {"started": False, "reason": "Gazette scene rendering is between intervals"}
            labels = [str((row.get("meta") or {}).get("headline") or row["file"])[:180] for row in rows]
            weights = []
            for row in rows:
                editorial = row["meta"]["editorial"]
                form = str(editorial.get("form") or editorial.get("format") or editorial.get("kind") or "").lower()
                weights.append(4.0 if any(s in form for s in ("hidden", "corrupt", "scandal"))
                               else 2.0 if row["meta"].get("section") in ("gallery", "interview", "upstairs")
                               else 1.0)
            index = (self.select("gazette.media.story", labels, weights,
                                 "Which fictional Gazette city scene gets a picture and H3 reaction")
                     if self.select else 0)
            if not isinstance(index, int) or not 0 <= index < len(rows):
                index = 0
            article = rows[index]
            editorial = article["meta"]["editorial"]
            media = editorial.get("media") or article.get("media") or {}
            receipt = {
                "edition": edition_id, "article": article["file"], "status": "pending",
                "editorial_id": str(editorial.get("id") or "")[:180],
                "edition_at": await asyncio.to_thread(self._edition_at, edition_id),
                "started_at": self.clock(), "headline": labels[index],
                "topic": copy.deepcopy(editorial.get("topic")),
                "cast": copy.deepcopy(editorial.get("cast")),
                "reaction": copy.deepcopy(editorial.get("reaction")),
                "emotion": copy.deepcopy(editorial.get("emotion")),
                "selection": {"table": "gazette.media.story", "labels": labels,
                              "weights": weights, "chosen": labels[index]},
                "subject": str(media.get("subject") or "")[:160],
                "topic_id": str(media.get("topic_id") or "")[:160],
                "arc_id": str(media.get("arc_id") or "")[:160],
                "speech": str(media.get("speech") or "")[:500],
                "policy": dict(self.policy),
            }
            for kind, key, cap in (("image", "image_prompt", "images"), ("video", "video_prompt", "videos")):
                prompt = str(media.get(key) or "").strip()[:2800]
                receipt[kind] = {
                    "status": "pending" if prompt and self.policy[cap] else "disabled",
                    "prompt": prompt, "attempted": False,
                    "caption": ("Fictional city scene" if kind == "image" else "Fictional reaction scene")
                               + " generated for this Gazette story.",
                }
            if all(receipt[kind]["status"] == "disabled" for kind in ("image", "video")):
                return {"started": False, "reason": "No scene fits the enabled media caps"}
            await self._save(receipt)
            await asyncio.to_thread(self._stamp_start, edition_id)
            self._task = asyncio.create_task(self._work(receipt, allow_submit=True))
            return {"started": True, "article": article["file"], "status": "pending"}

    async def recover(self, edition_ids: list[str]) -> dict[str, Any]:
        """Resume only the newest pending receipt, without repeating render requests."""
        async with self._lock:
            if not self.policy["enabled"]:
                return {"started": False, "reason": "Gazette scene rendering is disabled"}
            if self._task is not None and not self._task.done():
                return {"started": False, "reason": "A Gazette scene worker is active"}
            for edition_id in list(edition_ids)[:24]:
                receipt = await asyncio.to_thread(self._read, str(edition_id))
                if receipt.get("status") not in _OPEN_STATUSES:
                    continue
                if not _ARTICLE.fullmatch(str(receipt.get("article") or "")):
                    continue
                if not any((receipt.get(kind) or {}).get("prompt_id") for kind in ("image", "video")):
                    receipt["status"] = "interrupted"
                    receipt["reason"] = "A restart interrupted submission; no ticket is safe to repeat"
                    await self._save(receipt)
                    continue
                self._task = asyncio.create_task(self._work(receipt, allow_submit=False))
                return {"started": True, "edition": edition_id, "recovered": True}
            return {"started": False, "reason": "No submitted Gazette scene needs recovery"}

    async def _wait(self, stage: dict[str, Any], kind: str, deadline: float) -> tuple[str, str]:
        while self.clock() < deadline:
            try:
                row = await asyncio.to_thread(self.lookup, stage["prompt_id"])
            except Exception as exc:
                stage["last_error"] = str(exc)[:220]
                row = {}
            if isinstance(row, dict):
                status = str(row.get("status") or "")
                if status in _FINAL_FAILURES:
                    return "", str(row.get("error") or "Generation ended with " + status)[:240]
                if status == "done":
                    extensions = _IMAGE_SUFFIXES if kind == "image" else _VIDEO_SUFFIXES
                    files = row.get("files") or []
                    if isinstance(files, str):
                        try:
                            files = json.loads(files)
                        except ValueError:
                            files = []
                    for name in files if isinstance(files, list) else []:
                        name = str(name)
                        if (_FILE.fullmatch(name) and ".." not in name
                                and Path(name).suffix.lower() in extensions
                                and await asyncio.to_thread(self.exists, name)):
                            return name, ""
                    return "", "The completed generation has no available " + kind + " output"
            await self.sleep(min(self.policy["poll_s"], max(0.01, deadline - self.clock())))
        return "", "deferred"

    async def _work(self, receipt: dict[str, Any], *, allow_submit: bool) -> None:
        deadline = self.clock() + self.policy["deadline_s"]
        try:
            receipt["status"] = "working"
            await self._save(receipt)
            for kind in ("image", "video"):
                stage = receipt.get(kind) or {}
                if stage.get("status") in ("disabled", "ready", "failed", "refused", "interrupted"):
                    continue
                if not stage.get("prompt_id"):
                    if not allow_submit or stage.get("attempted"):
                        stage["status"] = "interrupted"
                        stage["reason"] = "No submitted ticket; recovery never repeats generation"
                        continue
                    if self.clock() >= deadline:
                        stage["status"] = "disabled"
                        stage["reason"] = "The scene-following budget was spent before submission"
                        continue
                    stage["attempted"] = True
                    stage["status"] = "submitting"
                    await self._save(receipt)
                    try:
                        if kind == "image":
                            result = await self.submit_image(
                                stage["prompt"],
                                {"edition": receipt["edition"], "article": receipt["article"],
                                 "topic": receipt.get("topic"), "purpose": "gazette_scene"})
                        else:
                            image = receipt.get("image") or {}
                            source = str(image.get("file") or "") if image.get("status") == "ready" else ""
                            payload = {
                                "mode": "frame" if source else "text",
                                "purpose": "gazette_reaction", "prompt": stage["prompt"],
                                "speech": receipt.get("speech") or "",
                                "duration_seconds": self.policy["duration_s"],
                                "duration_mode": "at_least", "air_it": False,
                            }
                            if source:
                                payload.update({"source": source, "source_type": "generation"})
                            result = await self.submit_video(payload)
                        if not isinstance(result, dict) or not str(result.get("prompt_id") or ""):
                            raise ValueError("The render did not return a generation ticket")
                        stage.update({"prompt_id": str(result["prompt_id"])[:200],
                                      "model": str(result.get("model") or "")[:120],
                                      "status": "queued", "submitted_at": self.clock()})
                        await self._save(receipt)
                    except Exception as exc:
                        stage["status"] = "refused"
                        stage["reason"] = str(exc)[:240]
                        await self._save(receipt)
                        continue
                filename, reason = await self._wait(stage, kind, deadline)
                if reason == "deferred":
                    stage["status"] = "deferred"
                    stage["reason"] = "Render is still pending; its existing ticket can be recovered"
                    receipt["status"] = "deferred"
                    await self._save(receipt)
                    return
                if not filename:
                    stage["status"] = "failed"
                    stage["reason"] = reason
                    await self._save(receipt)
                    continue
                url = _url(self.url_for(filename, kind), kind)
                if not url:
                    stage["status"] = "failed"
                    stage["reason"] = "The generation did not have a safe media URL"
                    await self._save(receipt)
                    continue
                stage.update({"status": "ready", "file": filename, "url": url,
                              "completed_at": self.clock()})
                stage.pop("reason", None)
                await self._save(receipt, kind, url)
            statuses = [receipt.get(kind, {}).get("status") for kind in ("image", "video")]
            receipt["status"] = ("ready" if all(s in ("ready", "disabled") for s in statuses)
                                 else "partial" if "ready" in statuses else "failed")
            await self._save(receipt)
        except asyncio.CancelledError:
            receipt["status"] = "deferred"
            receipt["reason"] = "The Gazette media follower was interrupted"
            try:
                await asyncio.to_thread(self._write, receipt)
            except Exception:
                pass
            raise
        except Exception as exc:
            receipt["status"] = "deferred"
            receipt["reason"] = str(exc)[:240]
            try:
                await asyncio.to_thread(self._write, receipt)
            except Exception:
                pass

    async def idle(self) -> None:
        """Wait for this bounded worker; useful for shutdown and focused verification."""
        task = self._task
        if task is not None:
            await task
