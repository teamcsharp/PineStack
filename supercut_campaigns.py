"""Frozen hourly creative briefs for source-only Super Cuts; never makes audio."""
from __future__ import annotations
import asyncio
import copy
import hashlib
import json
import re
import secrets
import time
from pathlib import Path
from threading import RLock
from typing import Any

import dynamic_segments
import segment_prompts

MODES = {"mixed", "random", "saved", "invented", "fixed"}
IDEAS = ("a novelty coffee", "an eccentric coffee mug", "a pair of headphones",
         "an unusual snack", "a household tool", "a radio souvenir")

def clean_products(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, (list, tuple)):
        return []
    rows, seen = [], set()
    for item in raw[:300]:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("product") or item.get("title") or "").strip()[:200]
            description = str(item.get("description") or item.get("pitch") or "").strip()[:1000]
        else:
            name, description = str(item or "").strip()[:200], ""
        key = " ".join(name.casefold().split())
        if name and key not in seen:
            seen.add(key)
            rows.append({"name": name, "description": description})
    return rows

def _fill(text, row):
    product = row.get("product") or "a new invented product"
    values = dict(product=product, item=product, sponsor=row["sponsor"], stationname=row["station"], hour=row["hour"])
    return re.sub(r"(?<!\{)\{(product|item|sponsor|stationname|hour)\}(?!\})",
                  lambda match: str(values[match.group(1)]), str(text or ""))

class SupercutCampaigns:
    def __init__(self, host):
        self.host, self.lock, self.selection_lock = host, RLock(), asyncio.Lock()
        self.path = Path(host["DATA_DIR"]) / "supercut_campaigns.json"
        self.items, self.tasks, self.worker_task = {}, {}, None
        self.poll_seconds, self.writer_seconds = 4.0, 180.0
        # The current hour's prepared station-only spots keep their identity.
        self.effective_hour = self.hour_at() + 3600
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.effective_hour = int(raw.get("effective_hour", self.effective_hour))
            for row in raw.get("items", []):
                if isinstance(row, dict) and re.fullmatch(r"campaign-[a-f0-9]{24}", str(row.get("id") or "")):
                    row = copy.deepcopy(row)
                    if row.get("status") == "writing":
                        row.update(status="pending", why="The same hourly brief resumes after restart")
                    self.items[str(row["hour_epoch"])] = row
        except (OSError, ValueError, TypeError, KeyError):
            pass

    @staticmethod
    def hour_at(at=None):
        return int(float(time.time() if at is None else at) // 3600) * 3600

    def save(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"version": 1, "effective_hour": self.effective_hour,
                "items": list(self.items.values())}, ensure_ascii=False, indent=1), encoding="utf-8")
            temporary.replace(self.path)

    def snapshot(self, hour):
        with self.lock:
            return copy.deepcopy(self.items.get(str(hour), {}))

    def products(self, config):
        settings = self.host.get("dj_settings")
        settings = settings() if callable(settings) else {}
        source = self.host.get("supercut_saved_products")
        try:
            imported = source() if callable(source) else settings.get("sponsors") or []
        except Exception:
            imported = []
        imported = imported if isinstance(imported, (list, tuple)) else [imported] if imported else []
        return clean_products(list(config.get("products") or []) + list(imported) +
                              [settings.get("station_name") or "Pine Box FM"])

    async def freeze(self, hour, *, occurrence="", chosen=None):
        hour = self.hour_at(hour)
        if hour < self.effective_hour:
            return {}
        async with self.selection_lock:
            row = self.snapshot(hour)
            if row:
                return row
            key = segment_prompts.memo_key("sfx_supercut", "hourly-supercut", f"hour@{hour}")
            if chosen is None:
                await asyncio.to_thread(segment_prompts.govern, "sfx_supercut", dynamic_segments.SFX_SUPERCUT["text"], key)
                chosen = segment_prompts.occurrence_view("sfx_supercut", key) or {}
            config = copy.deepcopy(chosen.get("config") or dynamic_segments.SFX_SUPERCUT["config"])
            if config.get("campaign_enabled") is False:
                return {}
            mode = str(config.get("product_mode") or "mixed")
            mode = mode if mode in MODES else "mixed"
            products = self.products(config)
            with self.lock:
                earlier = sorted((one for one in self.items.values() if one["hour_epoch"] < hour), key=lambda one: one["hour_epoch"])
                previous = earlier[-1] if earlier else {}
                forbidden = {str(one.get("product") or "").casefold() for one in self.items.values()
                             if abs(one["hour_epoch"] - hour) == 3600 and one.get("product")}
            candidates = [one for one in products if one["name"].casefold() not in forbidden]
            if mode == "fixed":
                selected, source = {"name": str(config.get("item") or "Pine Box FM"), "description": ""}, "fixed"
            else:
                use_saved = mode in {"saved", "random"} or (mode == "mixed" and previous.get("product_source") == "invented")
                if mode == "mixed" and not previous:
                    use_saved = secrets.choice((True, False))
                selected, source = (secrets.choice(candidates), "saved") if use_saved and candidates else ({"name": "", "description": ""}, "invented")
            settings = self.host.get("dj_settings")
            station = str((settings() if callable(settings) else {}).get("station_name") or "Pine Box FM")
            row = {"id": "campaign-" + hashlib.sha256(f"supercut-hour:{hour}".encode()).hexdigest()[:24],
                "hour_epoch": hour, "hour": time.strftime("%Y-%m-%dT%H", time.localtime(hour)),
                "occurrence": occurrence or f"hour@{hour}", "prompt_occurrence": key,
                "product": selected["name"], "product_description": selected["description"],
                "product_source": source, "product_mode": mode, "creative_seed": secrets.token_hex(8),
                "creative_idea": secrets.choice(IDEAS), "station": station, "sponsor": str(config.get("sponsor") or station),
                "system_prompt": str(chosen.get("system_prompt") or dynamic_segments.SFX_SUPERCUT["text"]),
                "generation_prompt": str(chosen.get("generation_prompt") or dynamic_segments.SFX_SUPERCUT["generation_prompt"]),
                "template_id": str(chosen.get("alt") or ""), "template_name": str(chosen.get("name") or ""),
                "config": config, "target_seconds": max(30.0, min(60.0, float(config.get("target_seconds") or 45))),
                "script": "", "status": "pending", "created_at": time.time(), "generated_at": 0.0,
                "attempts": 0, "why": "Waiting for the station writer", "retry_at": 0.0, "avoid_products": sorted(forbidden)}
            with self.lock:
                self.items[str(hour)] = row
            await asyncio.to_thread(self.save)
            return self.snapshot(hour)

    def request(self, row):
        with self.lock:
            avoid = sorted({str(one.get("product") or "") for one in self.items.values() if one.get("product")})[-80:]
        product = (f"Invent one original product name for {row['creative_idea']}. Include its recognizable category (coffee, mug, headphones, snack, tool or radio) in the name. Avoid used names: {json.dumps(avoid)}. "
                   if row["product_source"] == "invented" else
                   f"Sell exactly this saved product: {json.dumps(row['product'])}. Description: {row['product_description']}. Do not rename it. ")
        generation = _fill(row["generation_prompt"], row)
        generation += (f"\n\nHOURLY SUPER CUT: {product} Station: {row['station']}. Target {row['target_seconds']:.0f} seconds; creative seed {row['creative_seed']}. "
            "Write a new playful 60–120 word sales script with an opening hook, product pitch, timely stinger idea and closing station tag. "
            "This script is a creative blueprint for the SFX Guy, an MP4 video editor. Super Cuts are videos assembled exclusively from existing MP4 clips, keeping each source picture and original audio together. Never make an audio-only WAV, synthetic narration or slideshow. Generated copy cannot certify source speech. "
            "Return only JSON with string fields product and script. Name the product in the script and close by naming the station.")
        return _fill(row["system_prompt"], row), generation

    def accept(self, row, raw):
        if isinstance(raw, dict):
            result = raw
        else:
            text = str(raw or "").strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
            result = json.loads(text)
        if not isinstance(result, dict):
            raise ValueError("The hourly writer did not return a product and script")
        product, script = str(result.get("product") or "").strip(), str(result.get("script") or "").strip()
        if not product or len(product) > 200 or not 40 <= len(script) <= 5000 or len(script.split()) < 12:
            raise ValueError("The hourly product/script is empty or incomplete")
        if row["product_source"] != "invented" and product.casefold() != row["product"].casefold():
            raise ValueError("The hourly writer changed the frozen saved product")
        if row["product_source"] == "invented":
            with self.lock:
                old = {str(one.get("product") or "").casefold() for one in self.items.values() if one["id"] != row["id"]}
            if product.casefold() in old or product.casefold() in row.get("avoid_products", []):
                raise ValueError("The invented hourly product repeats an existing campaign")
        if product.casefold() not in script.casefold() or row["station"].casefold() not in script.casefold():
            raise ValueError("The hourly script must name its product and station")
        return row["product"] or product, script

    def writer_busy(self, exclude=None):
        writing = self.host.get("_LARDER_WRITING") or [False]
        gate = self.host.get("_OLLAMA_GATE")
        if writing[0] or (callable(getattr(gate, "locked", None)) and gate.locked()):
            return True
        adapter = self.host.get("DYNAMIC_SEGMENTS_SYSTEM2")
        if callable(getattr(adapter, "writer_ticket_active", None)) and adapter.writer_ticket_active():
            return True
        return any(task is not exclude and not task.done() for task in self.tasks.values())

    async def write(self, hour):
        writing, owned = self.host.setdefault("_LARDER_WRITING", [False]), False
        try:
            if self.writer_busy(exclude=asyncio.current_task()):
                return
            writing[0], owned = True, True
            with self.lock:
                row = self.items[str(hour)]
                row.update(status="writing", why="The station writer is creating the hourly script", attempts=int(row.get("attempts") or 0) + 1)
            await asyncio.to_thread(self.save)
            frozen = self.snapshot(hour)
            system, generation = self.request(frozen)
            result = await asyncio.wait_for(self.host["supercut_campaign_write"](system, generation,
                product=frozen["product"], occurrence=frozen["occurrence"]), self.writer_seconds)
            product, script = self.accept(frozen, result)
            with self.lock:
                row = self.items[str(hour)]
                row.update(product=product, script=script, generated_at=time.time(), status="script_ready", why="",
                    resolved_system_prompt=_fill(row["system_prompt"], {**row, "product": product}),
                    resolved_generation_prompt=_fill(row["generation_prompt"], {**row, "product": product}),
                    script_sha256=hashlib.sha256(script.encode()).hexdigest(), retry_at=0.0)
            await asyncio.to_thread(self.save)
        except asyncio.CancelledError:
            with self.lock:
                row = self.items.get(str(hour))
                if row and not row.get("script"):
                    row.update(status="pending", why="The same hourly brief will resume after restart")
            await asyncio.to_thread(self.save)
            raise
        except Exception as exc:
            with self.lock:
                row = self.items.get(str(hour))
                if row:
                    row.update(status="error", why=str(exc)[:300], retry_at=time.time() + 90)
            await asyncio.to_thread(self.save)
        finally:
            if owned:
                writing[0] = False

    async def ensure(self, hour, *, occurrence="", chosen=None, wait_seconds=None):
        hour = self.hour_at(hour)
        row = await self.freeze(hour, occurrence=occurrence, chosen=chosen)
        if not row or row.get("script"):
            return row
        task = self.tasks.get(str(hour))
        if task is None or task.done():
            if not callable(self.host.get("supercut_campaign_write")) or self.writer_busy() or row.get("retry_at", 0) > time.time() or row.get("attempts", 0) >= 3:
                return row
            task = asyncio.create_task(self.write(hour), name="supercut:campaign:" + str(hour))
            self.tasks[str(hour)] = task
        try:
            await asyncio.wait_for(asyncio.shield(task), self.poll_seconds if wait_seconds is None else max(.001, wait_seconds))
        except asyncio.TimeoutError:
            pass
        return self.snapshot(hour)

    def status(self, limit=72):
        with self.lock:
            rows = copy.deepcopy(sorted(self.items.values(), key=lambda row: row["hour_epoch"], reverse=True)[:max(1, min(500, int(limit)))])
        selected = segment_prompts.dial_preview("sfx_supercut") or {}
        config = selected.get("config") or dynamic_segments.SFX_SUPERCUT["config"]
        return {"ok": True, "items": rows, "enabled": config.get("campaign_enabled") is not False,
            "product_mode": config.get("product_mode") or "mixed", "products": self.products(config),
            "target_seconds": config.get("target_seconds") or 45, "effective_hour": self.effective_hour,
            "pending": sum(not row.get("script") for row in rows), "writer_busy": self.writer_busy()}

    def detail(self, ident):
        with self.lock:
            return copy.deepcopy(next((row for row in self.items.values() if row["id"] == str(ident)), {}))

    async def worker(self):
        while True:
            try:
                dynamic = self.host.get("DYNAMIC_SEGMENTS_RUNTIME")
                current = dynamic.plan_for(dynamic.hour_key()) if dynamic else {}
                if (self.host.get("_RADIO") or {}).get("on") and current and current.get("enabled"):
                    hour = self.hour_at()
                    await self.ensure(hour, occurrence=f"hour@{hour}", wait_seconds=.05)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log = self.host.get("pipeline_log")
                if callable(log):
                    log("lookahead", "The hourly Super Cut script waits", extra=str(exc)[:300])
            await asyncio.sleep(30)

    async def stop(self):
        tasks = list(self.tasks.values()) + ([self.worker_task] if self.worker_task else [])
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

def install(app, host):
    from fastapi import Header, HTTPException, Request
    globals()["Request"] = Request
    if not callable(host.get("supercut_campaign_write")) and callable(host.get("ask_model")):
        async def writer(system, generation, *, product, occurrence):
            schema = {"type": "object", "properties": {"product": {"type": "string"}, "script": {"type": "string"}},
                      "required": ["product", "script"], "additionalProperties": False}
            return await host["ask_model"](generation, limit=2000, spice=.35, system_prompt=system,
                result_contract="json", result_schema=schema,
                mark={"kind": "supercut_campaign", "occurrence": occurrence, "product": product})
        host["supercut_campaign_write"] = writer
    runtime = host.get("SUPERCUT_CAMPAIGNS") or SupercutCampaigns(host)
    host["SUPERCUT_CAMPAIGNS"] = runtime

    @app.get("/api/sfx/supercut/products")
    async def products(authorization: str | None = Header(default=None)):
        host["require_read_auth"](authorization)
        status = await asyncio.to_thread(runtime.status, 1)
        return {key: status[key] for key in ("ok", "product_mode", "products", "enabled", "target_seconds", "effective_hour")}

    @app.put("/api/sfx/supercut/products")
    async def save_products(request: Request, authorization: str | None = Header(default=None)):
        host["require_auth"](authorization)
        raw = await request.json()
        if not isinstance(raw, dict):
            raise HTTPException(422, "The product list must be an object")
        def update():
            chosen = segment_prompts.dial_preview("sfx_supercut") or {}
            cfg = dict(chosen.get("config") or dynamic_segments.SFX_SUPERCUT["config"])
            cfg.update(product_mode=str(raw.get("product_mode") or cfg.get("product_mode") or "mixed"),
                products=clean_products(raw.get("products", cfg.get("products", []))),
                campaign_enabled=raw.get("campaign_enabled", cfg.get("campaign_enabled", True)) is not False)
            if cfg["product_mode"] not in MODES:
                raise ValueError("Choose mixed, saved, invented, random or fixed products")
            ident = str(chosen.get("id") or chosen.get("alt") or dynamic_segments.SFX_SUPERCUT["id"])
            if segment_prompts.entry("sfx_supercut"):
                segment_prompts.patch_alternative("sfx_supercut", ident, {"config": cfg})
            else:
                segment_prompts.put_alternative("sfx_supercut", {**dynamic_segments.SFX_SUPERCUT, "config": cfg})
            return runtime.status(1)
        try:
            status = await asyncio.to_thread(update)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {key: status[key] for key in ("ok", "product_mode", "products", "enabled", "target_seconds", "effective_hour")}

    @app.get("/api/sfx/supercut/campaigns")
    async def campaigns(limit: int = 72, authorization: str | None = Header(default=None)):
        host["require_read_auth"](authorization)
        return await asyncio.to_thread(runtime.status, limit)

    @app.get("/api/sfx/supercut/campaigns/{ident}")
    async def campaign(ident: str, authorization: str | None = Header(default=None)):
        host["require_read_auth"](authorization)
        row = await asyncio.to_thread(runtime.detail, ident)
        if not row:
            raise HTTPException(404, "Unknown hourly Super Cut campaign")
        return row

    @app.on_event("startup")
    async def start():
        # Persist cutover immediately so a restart cannot keep postponing it.
        await asyncio.to_thread(runtime.save)
        runtime.worker_task = asyncio.create_task(runtime.worker(), name="supercut:hourly-campaigns")

    @app.on_event("shutdown")
    async def stop():
        await runtime.stop()
    return runtime