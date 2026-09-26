"""Durable local LLM wire history and conflict-checked prompt configuration."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import sqlite3
import time
import uuid
import zlib
from pathlib import Path
from threading import RLock
from contextlib import contextmanager

from fastapi import Header, HTTPException, Request


def packed(value):
    return zlib.compress(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


def unpacked(value):
    return json.loads(zlib.decompress(value)) if value else {}


def text_request(body):
    """Keep exact text and tool messages; omit binary image payloads and headers."""
    out = copy.deepcopy(body)
    for message in out.get("messages", []):
        if isinstance(message, dict) and message.get("images"):
            message["images"] = [{"omitted_binary_image": True} for _ in message["images"]]
    if out.get("images"):
        out["images"] = [{"omitted_binary_image": True} for _ in out["images"]]
    return out


class History:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = RLock()
        self.ready = False
        self.last_error = ""

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        if not self.ready:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS configurations (hash TEXT PRIMARY KEY, body BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS calls (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    at REAL NOT NULL, finished REAL, model TEXT, purpose TEXT,
                    state TEXT, request BLOB, response BLOB, error TEXT,
                    config TEXT, preview TEXT);
                CREATE INDEX IF NOT EXISTS calls_model ON calls(model, seq DESC);
                CREATE TABLE IF NOT EXISTS edits (at REAL, path TEXT, before BLOB, after BLOB);
            """)
            self.ready = True
        try:
            with db:
                yield db
        finally:
            db.close()

    def start(self, body, purpose, context):
        body = text_request(body)
        config = packed(context)
        key = hashlib.sha256(config).hexdigest()
        messages = body.get("messages") or []
        preview = next((str(m.get("content") or "") for m in messages
                        if isinstance(m, dict) and m.get("role") == "system"), str(body.get("prompt") or ""))
        if not preview and messages:
            preview = str(messages[-1].get("content") or "")
        identity = uuid.uuid4().hex
        with self.lock, self.connect() as db:
            db.execute("INSERT OR IGNORE INTO configurations VALUES (?, ?)", (key, config))
            db.execute("INSERT INTO calls(id,at,model,purpose,state,request,config,preview) VALUES(?,?,?,?,?,?,?,?)",
                       (identity, time.time(), str(body.get("model") or ""), purpose, "running", packed(body), key, preview[:280]))
        return identity

    def finish(self, identity, response=None, error="", state="complete"):
        with self.lock, self.connect() as db:
            db.execute("UPDATE calls SET finished=?,response=?,error=?,state=? WHERE id=?",
                       (time.time(), packed(response or {}), error, state, identity))

    def page(self, model="", before=0, limit=30):
        limit = max(1, min(100, int(limit)))
        where, args = [], []
        if model:
            where.append("model=?"); args.append(model)
        if before:
            where.append("seq<?"); args.append(int(before))
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self.lock, self.connect() as db:
            rows = db.execute("SELECT seq,id,at,finished,model,purpose,state,error,preview FROM calls" + clause
                              + " ORDER BY seq DESC LIMIT ?", (*args, limit + 1)).fetchall()
            models = [r[0] for r in db.execute("SELECT DISTINCT model FROM calls ORDER BY model")]
            started = db.execute("SELECT MIN(at) FROM calls").fetchone()[0]
        return {"rows": [dict(r) for r in rows[:limit]], "models": models,
                "next": rows[limit - 1]["seq"] if len(rows) > limit else 0,
                "recording_since": started, "capture_error": self.last_error,
                "coverage": "Station-originated local Ollama requests captured since this recorder was installed. Earlier requests and calls from other applications are unavailable. Binary images are omitted; textual messages and outputs are retained."}

    def detail(self, identity):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM calls WHERE id=?", (identity,)).fetchone()
            if not row:
                raise KeyError(identity)
            config = db.execute("SELECT body FROM configurations WHERE hash=?", (row["config"],)).fetchone()
        result = dict(row)
        result["request"] = unpacked(row["request"])
        result["response"] = unpacked(row["response"])
        result["properties"] = unpacked(config[0]) if config else {}
        result["properties_evidence"] = "Configuration observed at dispatch. Exact messages above are authoritative; an enabled property alone does not prove it contributed."
        return result

    def edit(self, path, before, after):
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO edits VALUES(?,?,?,?)", (time.time(), path, packed(before), packed(after)))

    async def post(self, client, url, *, context, purpose="direct", **kwargs):
        body = kwargs.get("json") or {}
        identity = ""
        if body.get("messages") or body.get("prompt"):
            try:
                identity = await asyncio.to_thread(self.start, body, purpose, context())
            except Exception as exc:
                self.last_error = "Request capture failed: " + type(exc).__name__
        try:
            response = await client.post(url, **kwargs)
        except (Exception, asyncio.CancelledError) as exc:
            if identity:
                try:
                    await asyncio.shield(asyncio.to_thread(self.finish, identity, None, type(exc).__name__, "failed"))
                except Exception:
                    self.last_error = "Failure receipt could not be stored"
            raise
        if identity:
            try:
                result = response.json()
                state = "failed" if response.status_code >= 400 else "complete"
                await asyncio.to_thread(self.finish, identity, result, "", state)
            except Exception as exc:
                self.last_error = "Response capture failed: " + type(exc).__name__
        return response


# These are actual stochastic thresholds, not every numeric setting.
CHANCES = {
    "chattiness": (0, 1, "No optional model-written host line", "Always attempt the optional model-written host line"),
    "accent_pin": (0, 1, "No accent cue", "Always add an accent cue"),
    "speakbox_prepend_rate": (0, 1, "No opening passage", "Always request an opening passage when eligible"),
    "speakbox_append_rate": (0, 1, "No closing passage", "Always request a closing passage when eligible"),
}


def configuration(host):
    settings = host["load_settings"]()
    desk = host["radio_prompt_desk_state"]()
    specs = {c["key"]: c for role in desk["roles"] for c in role["controls"]}
    nodes = []
    def put(path, label, value, group, **meta):
        kind = "checkbox" if isinstance(value, bool) else "number" if isinstance(value, (float, int)) else "json" if isinstance(value, (dict, list)) else "text"
        nodes.append({"path": path, "label": label, "value": copy.deepcopy(value), "group": group, "type": kind, **meta})
    for key, value in (settings.get("dj") or {}).items():
        if key not in host["DEFAULT_DJ"] or any(word in key.lower() for word in ("token", "password", "secret", "api_key")):
            continue
        if key in ("radio_prompt_overrides", "radio_prompt_enabled", "radio_prompt_presets"):
            values = {r["id"]: ("" if key == "radio_prompt_overrides" else True if key == "radio_prompt_enabled" else []) for r in desk["roles"]}
            if key == "radio_prompt_enabled":
                values["station_system"] = False
            values.update(value)
            for role, item in values.items():
                put(["dj", key, role], role.replace("_", " ") + " / " + key.replace("radio_prompt_", ""), item, "Prompt layers")
            continue
        spec = specs.get(key, {})
        meta = {}
        if spec.get("type") in ("range", "number"):
            scale = spec.get("scale", 1)
            meta.update(min=spec["min"] * scale, max=spec["max"] * scale, step=spec["step"] * scale)
        if key in CHANCES:
            low, high, lower, upper = CHANCES[key]
            meta["random"] = {"distribution": "Uniform draw from 0 to 1 compared with this threshold", "min": low, "max": high, "low": lower, "high": upper}
        if key in ("ad_price_low", "ad_price_high"):
            meta["random"] = {"distribution": "Uniform integer gallery asking price", "min": settings["dj"].get("ad_price_low"), "max": settings["dj"].get("ad_price_high"), "low": "Lowest generated asking price", "high": "Highest generated asking price"}
        put(["dj", key], spec.get("label") or key.replace("_", " "), value,
            "Prompt text" if "persona" in key or "prompt" in key else "Station properties", **meta)
    for index, row in enumerate(settings.get("prompts") or []):
        put(["prompts", index, "prompt"], "Agent: " + str(row.get("name") or index), row.get("prompt") or "", "Agent prompts")
    for kind in host["SCHEDULE_KIND_NAMES"]:
        view = host["segment_prompts"].entry_view(kind)
        if not view.get("alternatives"):
            continue
        put(["segment", kind, "mode"], kind + " selection", view.get("mode") or "cycle", "Segment alternatives",
            type="select", choices=["cycle", "random"] + ["fixed:" + r["id"] for r in view["alternatives"]],
            random={"distribution": "Weighted random over enabled alternatives; avoids the previous pick when possible", "min": 1,
                    "max": host["segment_prompts"].WEIGHT_MAX, "low": "Weight 1: least relative chance", "high": "Weight 9: nine times weight 1 before exclusions"})
        for row in view["alternatives"]:
            for field in ("text", "weight", "on"):
                put(["segment", kind, row["id"], field], kind + " / " + row["name"] + " / " + field,
                    row.get(field), "Segment alternatives", **({"min": 1, "max": 9, "step": 1} if field == "weight" else {}))
    return {"nodes": nodes, "roles": [{"id": r["id"], "name": r["name"], "systems": r["systems"]} for r in desk["roles"]],
            "coverage": "Persisted radio properties, prompt layers, agent prompts and saved segment alternatives. Compiled rules and transient source draws are evidence, not writable settings."}


def apply_config(host, history, body):
    path, value = body.get("path"), body.get("value")
    with host["SETTINGS_LOCK"]:
        node = next((n for n in configuration(host)["nodes"] if n["path"] == path), None)
        if not node:
            raise ValueError("That property is not an editable prompt setting")
        if "was" not in body or body["was"] != node["value"]:
            raise RuntimeError("This property changed; refresh before saving")
        if node["type"] == "checkbox" and not isinstance(value, bool):
            raise ValueError("Expected a boolean")
        if node["type"] == "number":
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError("Expected a number")
            if ("min" in node and value < node["min"]) or ("max" in node and value > node["max"]):
                raise ValueError("Value is outside this property's range")
        if node["type"] == "select" and value not in node["choices"]:
            raise ValueError("Unknown selection mode")
        if node["type"] == "text" and not isinstance(value, str):
            raise ValueError("Expected text")
        if path[0] == "segment":
            segment = host["segment_prompts"]
            if path[2] == "mode":
                segment.set_mode(path[1], value)
            else:
                view = segment.entry_view(path[1])
                source = next(r for r in view["alternatives"] if r["id"] == path[2])
                segment.put_alternative(path[1], {**source, path[3]: value})
        else:
            settings = copy.deepcopy(host["load_settings"]())
            cursor = settings
            for key in path[:-1]:
                cursor = cursor.setdefault(key, {}) if isinstance(cursor, dict) else cursor[key]
            cursor[path[-1]] = value
            normalized = host["validate_settings"](settings)
            accepted = normalized
            for key in path:
                accepted = accepted[key]
            if accepted != value:
                raise ValueError("The setting validator would change this value; it was not saved")
            old_dj = host["load_settings"]().get("dj") or {}
            host["save_settings"](normalized)
            if any(old_dj.get(key) != normalized["dj"].get(key)
                   for key in ("voice", "cohost_voice", "third_voice", "drop_voice")):
                host["recast_desk"].note_change(host["_RECAST_JOBS"], old_dj, normalized["dj"])
                host["_TALK_CUT"][0] += 1
    try:
        history.edit(json.dumps(path), node["value"], value)
    except Exception:
        history.last_error = "A configuration edit was saved but its audit receipt could not be stored"
    return {"ok": True, "say": "Saved for future requests. Historical calls are unchanged.", "value": value}


def install(app, host, history):
    @app.get("/api/prompt-history")
    async def listing(model: str = "", before: int = 0, limit: int = 30, authorization: str | None = Header(default=None)):
        host["require_read_auth"](authorization)
        return await asyncio.to_thread(history.page, model[:200], before, limit)

    @app.get("/api/prompt-history/config")
    async def config(authorization: str | None = Header(default=None)):
        host["require_read_auth"](authorization)
        return await asyncio.to_thread(configuration, host)

    @app.post("/api/prompt-history/config")
    async def edit(request: Request, authorization: str | None = Header(default=None)):
        host["require_auth"](authorization)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "Expected an object")
        try:
            return await asyncio.to_thread(apply_config, host, history, body)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/prompt-history/{identity}")
    async def detail(identity: str, authorization: str | None = Header(default=None)):
        host["require_read_auth"](authorization)
        try:
            return await asyncio.to_thread(history.detail, identity)
        except KeyError as exc:
            raise HTTPException(404, "That request is not in the retained history") from exc
