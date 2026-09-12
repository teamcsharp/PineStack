"""#1241: what ComfyUI and OpenWebUI are ACTUALLY doing, for the overlays.

"I had a display on the top part of the screen and a separate type of
 display on the bottom part of the screen and it talked about very specific
 information... this thing talking about open web UI and the details of the
 task that were happening with Comfy UI."

Those are two panels of `~/bin/media-slideshow`, and neither is a summary:

  TopActivityBanner   the render happening right now — its model, its size,
                      its sampler and steps, the prompt text scrolling past,
                      how long it has been going and how far through it is.
  ServiceLogPanel     the OpenWebUI rolodex — version, every model, which
                      ones are RESIDENT, the chats, the tools, the
                      functions, the knowledge bases, the memories.

This module is the station's side of both. It is a separate file rather than
more of app.py because it is a self-contained subsystem with state of its
own, and because app.py is edited by more than one pair of hands at a time.

WHY THERE IS STATE HERE AT ALL. A render's elapsed time and its progress are
not in any single response: /queue says *what* is running, never *since
when*. The desktop app solves that by keeping `_http_prev` across polls —
when a prompt id first appears it stamps the clock, and when it disappears
it records how long that shape of workflow took. The progress bar is then
this render's elapsed time against the last one of the SAME shape. That is
an estimate and is labelled as one, but it is built from this box's own
measured history rather than from nothing.

THE ALTERNATIVE WAS A WEBSOCKET AND IT WAS REFUSED. ComfyUI publishes
node-by-node progress on /ws, which is where the desktop's node bars come
from. Holding that socket open from here would mean this process — which is
also recording a live radio show — carrying a second event loop client for
the sake of a progress bar, and reconnecting it whenever 8188 restarts. The
signature estimate costs one dict and is right to within the variance of the
box's own renders.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Optional

import httpx

# ---------------------------------------------------------------------------
# The workflow reader — ported from media-slideshow's own, node type for node
# type, so the two screens name a render the same way.
# ---------------------------------------------------------------------------

_LATENT_NODES = ("EmptyLatentImage", "EmptySD3LatentImage",
                 "EmptyHunyuanLatentVideo")
_CHECKPOINT_NODES = ("CheckpointLoaderSimple", "CheckpointLoader")
_UNET_NODES = ("UNETLoader", "DiffusionModelLoader")
_SAMPLER_NODES = ("KSampler", "KSamplerAdvanced", "SamplerCustom",
                  "SamplerCustomAdvanced")
_LORA_NODES = ("LoraLoader", "LoraLoaderModelOnly")
_SAVE_NODES = ("SaveImage", "SaveAnimatedWEBP", "SaveAnimatedPNG",
               "VHS_VideoCombine")


def analyze_workflow(prompt: Any) -> dict[str, Any]:
    """Render metadata out of a ComfyUI prompt-dict.

    width, height, batch_size, length (video frames), model, lora_names,
    sampler_name, scheduler, steps, cfg, filename_prefix, node_types.
    {} if this is not a prompt-dict."""
    if not isinstance(prompt, dict):
        return {}
    info: dict[str, Any] = {}
    loras: list[str] = []
    node_types: list[str] = []
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type") or "")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            inputs = {}
        node_types.append(cls)

        if cls in _LATENT_NODES:
            for key in ("width", "height", "batch_size", "length"):
                if key in inputs:
                    info[key] = inputs[key]
        if cls in _CHECKPOINT_NODES and "ckpt_name" in inputs:
            info["model"] = inputs["ckpt_name"]
        if cls in _UNET_NODES and "unet_name" in inputs:
            info["model"] = inputs["unet_name"]
        if cls in _SAMPLER_NODES:
            for key in ("sampler_name", "scheduler", "steps", "cfg"):
                if key in inputs:
                    info[key] = inputs[key]
        if cls in _LORA_NODES:
            name = inputs.get("lora_name")
            if isinstance(name, str) and name:
                loras.append(name)
        if cls in _SAVE_NODES and "filename_prefix" in inputs:
            info["filename_prefix"] = inputs["filename_prefix"]

    if loras:
        info["lora_names"] = loras
    info["node_types"] = node_types
    info["nodes"] = len(prompt)
    return info


def workflow_signature(info: dict[str, Any]) -> str:
    """Renders whose timing can usefully be compared: same model, sampler,
    resolution and step count."""
    if not info:
        return "?"
    return "|".join([
        str(info.get("model") or "?"),
        str(info.get("sampler_name") or "?"),
        f"{info.get('width') or 0}x{info.get('height') or 0}",
        f"s{info.get('steps') or 0}",
    ])


def _walk_conditioning(prompt: dict, start: str, hops: int = 6) -> Optional[str]:
    """Follow a conditioning input back to the CLIPTextEncode that fed it.

    A workflow rarely wires the sampler straight to its text node — there is
    usually a FluxGuidance or a ConditioningCombine in between — so this
    forwards through the intermediate nodes rather than giving up on them."""
    target = start
    for _ in range(hops):
        node = prompt.get(target)
        if not isinstance(node, dict):
            return None
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            return None
        if node.get("class_type") == "CLIPTextEncode":
            text = inputs.get("text")
            return text if isinstance(text, str) else None
        for key in ("conditioning", "positive", "negative", "conditioning_1"):
            ref = inputs.get(key)
            if isinstance(ref, list) and ref:
                target = str(ref[0])
                break
        else:
            return None
    return None


def extract_prompt_text(prompt: Any, which: str = "positive") -> Optional[str]:
    """The prompt a render is actually working from.

    Walks from the sampler's `positive`/`negative` input; falls back to any
    CLIPTextEncode, because some image-to-image flows have no sampler at
    all. `which` is the sampler input to start from."""
    if not isinstance(prompt, dict):
        return None
    sampler = None
    for nid, node in prompt.items():
        if isinstance(node, dict) and node.get("class_type") in _SAMPLER_NODES:
            sampler = nid
            break
    if sampler is not None:
        ref = ((prompt[sampler].get("inputs") or {}).get(which))
        if isinstance(ref, list) and ref:
            text = _walk_conditioning(prompt, str(ref[0]))
            if text and text.strip():
                return text.strip()
    if which != "positive":
        return None
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") != "CLIPTextEncode":
            continue
        text = (node.get("inputs") or {}).get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


# ---------------------------------------------------------------------------
# The render tracker. One dict, the way the desktop keeps `_http_prev`.
# ---------------------------------------------------------------------------

_RENDERS: dict[str, Any] = {
    "started": {},        # prompt_id -> monotonic stamp
    "meta": {},           # prompt_id -> analyze_workflow()
    "positive": {},       # prompt_id -> str
    "negative": {},       # prompt_id -> str
    "sig_seconds": {},    # workflow signature -> last duration
    "finished": [],       # recent completions, newest first
    "history_ids": None,  # baseline, so a first poll is not "all new"
    "last_seconds": None,
}
_FINISHED_KEEP = 8
_SIG_KEEP = 200


def _forget_old() -> None:
    """Bounded, because this process runs for days. The desktop caps the
    same dicts at 50/80/200 for the same reason."""
    sigs = _RENDERS["sig_seconds"]
    if len(sigs) > _SIG_KEEP:
        for key in list(sigs)[:len(sigs) - _SIG_KEEP]:
            sigs.pop(key, None)
    for field in ("meta", "positive", "negative"):
        book = _RENDERS[field]
        if len(book) > 80:
            live = set(_RENDERS["started"])
            for key in list(book):
                if key not in live:
                    book.pop(key, None)


async def comfy_activity(base: str, timeout: float = 3.0) -> dict[str, Any]:
    """What ComfyUI is doing, in the detail the banner was built to show."""
    out: dict[str, Any] = {"up": False, "why": "", "running": 0, "pending": 0,
                           "now": None, "finished": [], "board": {}}
    now = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            queue = (await client.get(f"{base}/queue")).json() or {}
            out["up"] = True
            try:
                stats = (await client.get(f"{base}/system_stats")).json() or {}
                device = (stats.get("devices") or [{}])[0]
                system = stats.get("system") or {}
                total = device.get("vram_total") or 0
                free = device.get("vram_free") or 0
                out["board"] = {
                    "device": device.get("name") or "",
                    "vram_used_gb": round((total - free) / 1e9, 1) if total else None,
                    "vram_total_gb": round(total / 1e9, 1) if total else None,
                    "comfyui": system.get("comfyui_version") or "",
                    "python": (system.get("python_version") or "")[:6],
                }
            except Exception:  # noqa: BLE001
                pass
            history = (await client.get(
                f"{base}/history", params={"max_items": 12})).json() or {}
    except Exception as exc:  # noqa: BLE001
        out["why"] = f"{type(exc).__name__}: {exc}"
        return out

    running = queue.get("queue_running") or []
    pending = queue.get("queue_pending") or []
    out["running"] = len(running)
    out["pending"] = len(pending)

    live_ids: list[str] = []
    for item in running:
        try:
            rid = str(item[1])
        except (IndexError, TypeError):
            continue
        live_ids.append(rid)
        if rid not in _RENDERS["started"]:
            _RENDERS["started"][rid] = now
            prompt = item[2] if len(item) > 2 else None
            if isinstance(prompt, dict):
                _RENDERS["meta"][rid] = analyze_workflow(prompt)
                positive = extract_prompt_text(prompt, "positive")
                negative = extract_prompt_text(prompt, "negative")
                if positive:
                    _RENDERS["positive"][rid] = positive
                if negative:
                    _RENDERS["negative"][rid] = negative

    # Anything that has left the running list has finished; record how long
    # that SHAPE of workflow took, which is what the next one's progress bar
    # is measured against.
    for rid in list(_RENDERS["started"]):
        if rid in live_ids:
            continue
        seconds = round(now - _RENDERS["started"].pop(rid), 1)
        meta = _RENDERS["meta"].get(rid) or {}
        _RENDERS["sig_seconds"][workflow_signature(meta)] = seconds
        _RENDERS["last_seconds"] = seconds
        _RENDERS["finished"].insert(0, {
            "id": rid[:12], "seconds": seconds,
            "model": meta.get("model") or "",
            "size": (f"{meta.get('width')}x{meta.get('height')}"
                     if meta.get("width") else ""),
            "at": time.time(),
        })
        del _RENDERS["finished"][_FINISHED_KEEP:]
    _forget_old()

    if live_ids:
        rid = live_ids[0]
        meta = _RENDERS["meta"].get(rid) or {}
        elapsed = round(now - _RENDERS["started"].get(rid, now), 1)
        expected = _RENDERS["sig_seconds"].get(workflow_signature(meta))
        out["now"] = {
            "id": rid[:12],
            "elapsed_s": elapsed,
            # ESTIMATED, and the field is named so the panel can say so. It
            # is this box's own last render of the same model, sampler,
            # resolution and step count — not a guess from nowhere, and not
            # a real progress number either.
            "expected_s": expected,
            "progress": (min(0.99, elapsed / expected)
                         if expected and expected > 0 else None),
            "model": meta.get("model") or "",
            "size": (f"{meta.get('width')}x{meta.get('height')}"
                     if meta.get("width") else ""),
            "batch": meta.get("batch_size"),
            "frames": meta.get("length"),
            "sampler": meta.get("sampler_name") or "",
            "scheduler": meta.get("scheduler") or "",
            "steps": meta.get("steps"),
            "cfg": meta.get("cfg"),
            "loras": meta.get("lora_names") or [],
            "nodes": meta.get("nodes"),
            "into": meta.get("filename_prefix") or "",
            "positive": (_RENDERS["positive"].get(rid) or "")[:600],
            "negative": (_RENDERS["negative"].get(rid) or "")[:300],
        }

    out["finished"] = list(_RENDERS["finished"])
    out["last_seconds"] = _RENDERS["last_seconds"]

    # New completions since the LAST poll, baselined on the first one —
    # ComfyUI keeps days of history and treating all of it as fresh on
    # startup is how the desktop once flew a polaroid for a week-old render.
    ids = set(history.keys()) if isinstance(history, dict) else set()
    known = _RENDERS["history_ids"]
    out["new_since_last_poll"] = len(ids - known) if known is not None else 0
    _RENDERS["history_ids"] = ids
    return out


# ---------------------------------------------------------------------------
# The OpenWebUI rolodex.
# ---------------------------------------------------------------------------

# Exactly the endpoints media-slideshow's `_owui_probe` asks for. Kept in its
# order so the two panels read alike.
_OWUI_ENDPOINTS = (
    ("version", "/api/version", False),
    ("config", "/api/config", False),
    ("models", "/api/models", True),
    ("ollama_models", "/ollama/api/tags", True),
    ("ollama_running", "/ollama/api/ps", True),
    ("chats", "/api/v1/chats/?page=1", True),
    ("users", "/api/v1/users/", True),
    ("prompts", "/api/v1/prompts/", True),
    ("tools", "/api/v1/tools/", True),
    ("functions", "/api/v1/functions/", True),
    ("knowledge", "/api/v1/knowledge/", True),
    ("memories", "/api/v1/memories/", True),
)

# OpenWebUI 0.8.x wraps model reasoning in a collapsible HTML block and some
# models leave their own tags in the stream. The panel shows what a person
# sees in the chat, not the scaffolding around it.
_OWUI_STRIP = (
    re.compile(r"<details\b[^>]*>.*?</details>", re.DOTALL | re.IGNORECASE),
    re.compile(r"</?summary\s*>", re.IGNORECASE),
    re.compile(r"</?think(?:ing)?\s*>", re.IGNORECASE),
    re.compile(r"<\|[^|>]*\|>"),
)


def clean_owui_text(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    out = text
    for pattern in _OWUI_STRIP:
        out = pattern.sub("", out)
    return re.sub(r"\s+", " ", out).strip()


def _count(payload: Any) -> Optional[int]:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("data", "items", "models", "chats", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
    return None


async def openwebui_rolodex(base: str, key: str = "",
                            timeout: float = 10.0) -> dict[str, Any]:
    """Everything the desktop's OpenWebUI tab lists, asked for in one pass.

    TEN SECONDS, not four. /api/models was answering with a ReadTimeout on
    the panel — OpenWebUI enumerates fifty models and the box behind it is
    busy. This whole sweep runs behind the answer on a twenty-second clock,
    so a slow endpoint costs nothing but patience, while a short timeout
    costs the row entirely.

    An endpoint that needs the key and does not get one is reported as
    `auth` rather than as a failure — "401" is a fact about this station's
    configuration, not about OpenWebUI being down, and the desktop makes the
    same distinction."""
    out: dict[str, Any] = {"up": False, "why": "", "base": base,
                           "key": bool(key), "rows": {}}
    headers = {"Authorization": f"Bearer {key}"} if key else {}

    async def ask(client: httpx.AsyncClient, name: str, path: str,
                  needs_key: bool) -> tuple[str, Any, dict[str, Any]]:
        if needs_key and not key:
            return name, None, {"state": "no api key configured"}
        try:
            response = await client.get(
                f"{base}{path}", headers=headers if needs_key else {})
        except Exception as exc:  # noqa: BLE001
            return name, None, {"state": type(exc).__name__}
        if response.status_code in (401, 403):
            return name, None, {"state": "the key was refused"}
        if response.status_code >= 400:
            return name, None, {"state": f"HTTP {response.status_code}"}
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            return name, None, {"state": "not JSON"}
        return name, body, {"count": _count(body), "state": "ok"}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            health = await client.get(f"{base}/health")
            out["up"] = health.status_code < 500
            # TWELVE AT ONCE, not twelve in a row. Sequentially this took
            # long enough that the tablet's twenty-second read timeout fired
            # on a cold start and the overlays reported the station down.
            # These are loopback calls to a service that is already answering
            # the panel; asking them together costs it nothing.
            results = await asyncio.gather(*[
                ask(client, name, path, needs_key)
                for name, path, needs_key in _OWUI_ENDPOINTS
            ])
            for name, body, row in results:
                out["rows"][name] = row
                if body is not None:
                    _detail(name, body, out)
    except Exception as exc:  # noqa: BLE001
        out["why"] = f"{type(exc).__name__}: {exc}"
    return out


def _detail(name: str, body: Any, out: dict[str, Any]) -> None:
    """The specific things the panel prints, per endpoint."""
    if name == "version" and isinstance(body, dict):
        out["version"] = body.get("version") or ""
    elif name == "config" and isinstance(body, dict):
        out["name"] = body.get("name") or ""
        out["auth"] = bool((body.get("features") or {}).get("auth"))
    elif name == "ollama_running" and isinstance(body, dict):
        # WHICH MODELS ARE RESIDENT, which is the one number that says
        # whether the next question will be answered instantly or after a
        # load. The desktop's panel puts it first for that reason.
        out["resident"] = [
            {"name": m.get("name") or m.get("model") or "?",
             "vram_gb": round((m.get("size_vram") or m.get("size") or 0) / 1e9, 1)}
            for m in (body.get("models") or [])
        ]
    elif name == "ollama_models" and isinstance(body, dict):
        out["installed"] = [m.get("name") for m in (body.get("models") or [])][:40]
    elif name == "chats":
        rows = body if isinstance(body, list) else (
            body.get("data") if isinstance(body, dict) else []) or []
        out["chats"] = [{
            "title": clean_owui_text(row.get("title"))[:80],
            "at": row.get("updated_at") or row.get("created_at"),
        } for row in rows[:8] if isinstance(row, dict)]
