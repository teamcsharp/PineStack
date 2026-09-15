"""Durable, compact script incidents; independent of the running station."""
from __future__ import annotations

import json
import math
import re
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from script_diagnostics import build_report, merge_views, render_report


REPORT_NAME = re.compile(r"script_[0-9_-]{8,60}\.(?:md|json)\Z")


class ScriptReportStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.lock = RLock()

    def path(self, name: str) -> Path:
        if not REPORT_NAME.fullmatch(name):
            raise ValueError("invalid report name")
        return self.root / name

    @staticmethod
    def _write(path: Path, text: str) -> None:
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _save(self, name: str, report: dict[str, Any]) -> None:
        path = self.path(name).with_suffix(".json")
        # Bound objects before encoding. Cutting encoded JSON loses evidence
        # and produces an unreadable artifact precisely when it is needed.
        self._write(path, json.dumps(report, ensure_ascii=False,
                                     allow_nan=False, separators=(",", ":")))
        self._write(path.with_suffix(".md"), render_report(
            report, "/api/script-reports/" + path.name))

    def create(self, view: dict[str, Any], server: dict[str, Any], *,
               incident_id: str = "", reason: str = "",
               image: str = "", save_images: Callable | None = None) -> dict[str, Any]:
        report = build_report(view, server, server_observed_at_ms=server.get("observed_at_ms"))
        report.update({"incident_id": str(incident_id or uuid.uuid4().hex)[:128],
                       "reason": str(reason or "")[:1200],
                       "created_at_ms": int(time.time() * 1000),
                       "status": "awaiting_post" if view.get("schema_version") == 2 else "complete",
                       "images": []})
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            while True:
                suffix = str(uuid.uuid4().int % (10 ** 18)).zfill(18)
                name = "script_" + time.strftime("%Y-%m-%d_%H%M%S") + "_" + suffix + ".md"
                if not self.path(name).with_suffix(".json").exists():
                    break
            report["file"] = "data/script_reports/" + name
            if image and save_images:
                report["images"] = list(save_images([image]))
            self._save(name, report)
        return report

    def read(self, name: str) -> dict[str, Any]:
        return json.loads(self.path(name).with_suffix(".json").read_text(encoding="utf-8"))

    def set_inbox(self, name: str, inbox_id: int) -> None:
        with self.lock:
            report = self.read(name)
            report["inbox_id"] = inbox_id
            self._save(name, report)

    def mark_images_linked(self, name: str) -> None:
        with self.lock:
            report = self.read(name)
            report["inbox_images_linked"] = True
            self._save(name, report)

    def finish(self, name: str, incident_id: str, view: dict[str, Any],
               server: dict[str, Any], *, image: str = "",
               screenshot: dict[str, Any] | None = None,
               save_images: Callable | None = None) -> dict[str, Any]:
        with self.lock:
            old = self.read(name)
            if str(old.get("incident_id")) != str(incident_id):
                raise ValueError("incident identity does not match")
            # A retried upload cannot double the post events or save the same
            # screenshot again. The original tap remains durable either way.
            if old.get("status") == "complete":
                return old
            combined = merge_views(old.get("view") or {}, view)
            report = build_report(combined, {"tap": old.get("server") or {}, "post": server},
                                  server_observed_at_ms=old.get("server_observed_at_ms"))
            for key in ("incident_id", "reason", "created_at_ms", "file", "images", "inbox_id", "inbox_images_linked"):
                if key in old:
                    report[key] = old[key]
            report["status"] = "complete"
            report["completed_at_ms"] = int(time.time() * 1000)
            shot = screenshot if isinstance(screenshot, dict) else {}
            report["screenshot"] = {}
            for key in ("captured_at_ms", "requested_at_ms", "source", "error"):
                value = shot.get(key)
                if isinstance(value, str):
                    report["screenshot"][key] = value[:240]
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    try:
                        if math.isfinite(value):
                            report["screenshot"][key] = value
                    except (OverflowError, ValueError):
                        pass
            if image and save_images:
                report["images"] = list(save_images([image]))
            self._save(name, report)
            return report
