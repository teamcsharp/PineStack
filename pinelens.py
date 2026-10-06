"""Authenticated, in-memory relay between a Pine desktop and PineTab.

The desktop owns capture, input and persistent crop settings. The station
holds one frame per host and short-lived commands; desktop pixels stay off disk.
"""
import base64
import math
import time
import uuid
from collections import deque

from fastapi import HTTPException, Request


def install(app, namespace):
    hosts = {}
    exports = {}

    def request_export(seconds, identifier=""):
        live = [(key, h) for key, h in hosts.items()
                if time.monotonic() - h["seen"] <= 12 and h["info"].get("recording")]
        if identifier:
            live = [(key, h) for key, h in live if key == identifier]
        if not live:
            raise HTTPException(409, "No active Pine Lens recording. Open a desktop session first.")
        identifier, h = max(live, key=lambda item: item[1]["viewed"])
        if any(j["host"] == identifier and j["state"] == "queued"
               and time.monotonic() - j["created"] < 600 for j in exports.values()):
            raise HTTPException(409, "This computer is already exporting Pine Lens")
        for key in list(exports):
            if time.monotonic() - exports[key]["created"] >= 600:
                del exports[key]
        seconds = max(1, min(600, int(seconds)))
        job = {"id": uuid.uuid4().hex, "host": identifier, "session": h["session"],
               "seconds": seconds, "created": time.monotonic(), "state": "queued"}
        exports[job["id"]] = job
        return {"ok": True, "id": job["id"], "host": identifier,
                "say": f"Exporting the last {seconds / 60:g} minutes of Pine Lens on {h['info']['name']}. Only recorded history can be exported; the ring holds up to ten minutes."}

    def spoken_export(cmd):
        try:
            return request_export(cmd.get("seconds") or 60).get("say")
        except HTTPException as exc:
            return str(exc.detail)

    namespace["export_lens_request"] = spoken_export

    @app.post("/api/pinelens/export")
    async def export_api(request: Request):
        auth(request)
        b = await body(request, 16000)
        try:
            seconds = float(b.get("seconds") or 60)
            if not math.isfinite(seconds) or seconds <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(400, "Choose a positive number of seconds")
        return request_export(seconds, str(b.get("host") or ""))

    @app.get("/api/pinelens/export/{job_id}")
    async def export_state(job_id: str, request: Request):
        auth(request)
        job = exports.get(job_id)
        if not job:
            raise HTTPException(404, "Pine Lens export not found")
        return {k: v for k, v in job.items() if k not in ("session", "created")}

    @app.post("/api/pinelens/hosts/{identifier}/export-done")
    async def export_done(identifier: str, request: Request):
        auth(request)
        b = await body(request, 16000)
        job = exports.get(str(b.get("id") or ""))
        if not job or job["host"] != identifier or job["session"] != b.get("session"):
            raise HTTPException(409, "Pine Lens export belongs to another desktop session")
        job.update(state="done" if b.get("state") == "done" else "failed",
                   result={k: b[k] for k in ("seconds", "partial", "path", "uploaded", "error") if k in b})
        return {"ok": True}

    def auth(request):
        namespace["require_auth"](request.headers.get("authorization"))

    def host_for(identifier):
        host = hosts.get(identifier)
        if not host or time.monotonic() - host["seen"] > 12:
            raise HTTPException(404, "This Pine desktop is offline")
        return host

    async def body(request, limit=3_000_000):
        import json
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > limit:
                raise HTTPException(413, "PineLens message is too large")
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, TypeError):
            raise HTTPException(400, "Expected a PineLens object")

    @app.get("/api/pinelens/hosts")
    async def listing(request: Request):
        auth(request)
        now = time.monotonic()
        for key in list(hosts):
            if now - hosts[key]["seen"] > 60:
                del hosts[key]
        return {"hosts": [{"id": key, **h["info"]} for key, h in hosts.items()
                          if now - h["seen"] <= 12]}

    @app.post("/api/pinelens/hosts/{identifier}/exchange")
    async def exchange(identifier: str, request: Request):
        auth(request)
        b = await body(request)
        if len(identifier) > 80 or not b.get("session") or len(str(b["session"])) > 80:
            raise HTTPException(400, "Missing desktop session identity")
        now = time.monotonic()
        h = hosts.get(identifier)
        if not h or h["session"] != b["session"]:
            for job in exports.values():
                if job["host"] == identifier and job["state"] == "queued":
                    job.update(state="failed", result={"error": "The desktop restarted before completing this export"})
            if len(hosts) >= 32 and identifier not in hosts:
                raise HTTPException(429, "Too many PineLens desktops")
            h = hosts[identifier] = {"session": b["session"], "commands": deque(maxlen=128),
                                     "frame": None, "viewed": 0, "info": {}, "seen": now}
        info = b.get("info")
        if not isinstance(info, dict):
            raise HTTPException(400, "Missing desktop status")
        h["info"] = {"name": str(info.get("name") or identifier)[:100],
                     "control": bool(info.get("control")), "error": str(info.get("error") or "")[:240],
                     "crop": info.get("crop"), "display": info.get("display"),
                     "recording": bool(info.get("recording")), "history": info.get("history"),
                     "export": info.get("export"), "full": bool(info.get("full")),
                     "revision": str(info.get("revision") or "")[:80]}
        h["seen"] = now
        frame = b.get("frame")
        if frame is not None:
            try:
                jpeg = base64.b64decode(frame["jpeg"], validate=True)
                if not 4 <= len(jpeg) <= 2_000_000 or not jpeg.startswith(b"\xff\xd8"):
                    raise ValueError()
                if not frame.get("id") or len(str(frame["id"])) > 80:
                    raise ValueError()
            except (KeyError, ValueError, TypeError):
                raise HTTPException(400, "Invalid PineLens frame")
            h["frame"] = {"id": frame["id"], "jpeg": frame["jpeg"],
                          "revision": h["info"]["revision"], "at": now}
        commands = [cmd for deadline, cmd in h["commands"] if deadline > now]
        h["commands"].clear()
        pending = [{"id": j["id"], "seconds": j["seconds"]} for j in exports.values()
                   if j["host"] == identifier and j["session"] == h["session"]
                   and j["state"] == "queued" and now - j["created"] < 600]
        return {"active": now - h["viewed"] < 4, "commands": commands, "exports": pending}

    @app.get("/api/pinelens/hosts/{identifier}/view")
    async def view(identifier: str, request: Request):
        auth(request)
        h = host_for(identifier)
        now = time.monotonic()
        h["viewed"] = now
        frame = h["frame"]
        valid = frame and now - frame["at"] < 4 and frame["revision"] == h["info"]["revision"]
        return {"info": h["info"], "frame": {k: frame[k] for k in ("id", "jpeg", "revision")} if valid else None}

    @app.post("/api/pinelens/hosts/{identifier}/command")
    async def command(identifier: str, request: Request):
        auth(request)
        h = host_for(identifier)
        b = await body(request, 16000)
        kind = b.get("type")
        if kind in ("full", "lens"):
            cmd = {"type": kind}
        elif kind in ("pointer", "wheel", "key", "text", "release"):
            frame = h["frame"]
            if (not h["info"]["control"] or not frame or time.monotonic() - frame["at"] > 4
                    or b.get("revision") != h["info"]["revision"]):
                raise HTTPException(409, "Wait for a current frame with desktop control available")
            cmd = {"type": kind, "revision": b["revision"]}
            if kind == "pointer":
                if b.get("action") not in ("move", "down", "up") or b.get("button", "left") not in ("left", "right", "middle"):
                    raise HTTPException(400, "Invalid pointer action")
                for key in ("x", "y"):
                    val = b.get(key)
                    if not isinstance(val, (int, float)) or not math.isfinite(val) or not 0 <= val <= 1:
                        raise HTTPException(400, "Pointer is outside the lens")
                    cmd[key] = val
                cmd.update(action=b["action"], button=b.get("button", "left"))
            elif kind == "wheel":
                delta = b.get("delta")
                if not isinstance(delta, (int, float)) or not math.isfinite(delta):
                    raise HTTPException(400, "Invalid scroll amount")
                cmd["delta"] = max(-10, min(10, int(delta)))
            elif kind == "key":
                key = str(b.get("key") or "")
                if (len(key) != 1 and key not in ("Enter", "Tab", "Escape", "Backspace", "Delete", "ArrowLeft",
                        "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown")
                        and key not in [f"F{i}" for i in range(1, 13)]):
                    raise HTTPException(400, "Unsupported keyboard key")
                modifiers = b.get("modifiers", [])
                if not isinstance(modifiers, list):
                    raise HTTPException(400, "Invalid keyboard modifiers")
                cmd.update(key=key, modifiers=[m for m in modifiers
                                              if m in ("ctrl", "shift", "alt", "meta")])
            elif kind == "text":
                cmd["text"] = str(b.get("text") or "")[:2000]
        else:
            raise HTTPException(400, "Unknown PineLens command")
        if len(h["commands"]) >= 128:
            raise HTTPException(429, "Desktop input queue is full")
        h["commands"].append((time.monotonic() + 2, cmd))
        return {"ok": True}
