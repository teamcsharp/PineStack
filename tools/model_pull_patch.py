#!/usr/bin/env python3
"""[model-pull] The pencil in the header's model picker: pull any Ollama model.

"put an icon of a pencil here that when clicked, allows me to type or paste
 in the url to a model to download and pull with ollama and use with this
 parameter ... when pulling a model, I want to see a loading bar, console
 output and npx animations of what is going on"      - the operator, 2026-09-29

Three edits to app.py:
  py    /api/model's body becomes writer_model_apply() - the one road a writer
        change takes - and the pull routes (/api/ollama/pull...) sit beside it.
  html  #headerModel goes into a small relative box with the Carbon pencil
        (c:edit) laid over its right end, left of the chevron.
  js    the pull window: stages, the bar, the layers the way the ollama CLI
        draws them (braille spinner, eighth-cell bars), and the console.

Usage:  model_pull_patch.py --check <app.py>   0 ready, 2 applied, 1 anchors missing
        model_pull_patch.py --apply <app.py>   idempotent; LF only; atomic;
                                               ast-parses the result and
                                               node --checks the panel script
"""
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------- py --------

PY_OLD = '''@app.post("/api/model")
async def switch_model(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Change the active model immediately and warm it in the background."""
    require_auth(authorization)
    payload = await request.json()
    model = str(payload.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="No model given")
    settings = load_settings()
    settings["model"] = model
    save_settings(settings)

    async def _warm() -> None:
        try:
            await call_ollama(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.0,
                max_tokens=1,
                num_ctx=2048,
            )
        except Exception:
            pass

    fire_and_forget(_warm())
    return {"model": model, "warming": True}
'''

PY_NEW = r'''def writer_model_apply(model: str) -> dict[str, Any]:
    """The one road a writer change takes (#29): the setting saved, and the
    model warmed in the background so the next line is not a cold start.
    /api/model and a pull from the header pencil ([model-pull]) both come
    through here."""
    settings = load_settings()
    settings["model"] = model
    save_settings(settings)

    async def _warm() -> None:
        try:
            await call_ollama(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.0,
                max_tokens=1,
                num_ctx=2048,
            )
        except Exception:
            pass

    fire_and_forget(_warm())
    return {"model": model, "warming": True}


@app.post("/api/model")
async def switch_model(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Change the active model immediately and warm it in the background."""
    require_auth(authorization)
    payload = await request.json()
    model = str(payload.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="No model given")
    return writer_model_apply(model)


# ---- [model-pull] The model door: the pencil in the header's model picker --
# "put an icon of a pencil here that when clicked, allows me to type or paste
#  in the url to a model to download and pull with ollama and use with this
#  parameter"                                        - the operator, 2026-09-29
#
# The operator pastes whatever the model's page says - `ollama run huihui_ai/
# gemma-4-abliterated:e2b`, an ollama.com link, a Hugging Face repo or .gguf
# link - and the station pulls it through Ollama's own streamed /api/pull.
# Every status line and every layer's bytes are kept on the job, so the panel
# can draw the bar, the layers the way the ollama CLI draws them, and the
# console; the pull runs here, not in the page, so closing the window loses
# nothing. One pull at a time: they share one pipe and one disk. When it
# lands it can become the writer through writer_model_apply(), the same road
# /api/model takes. Jobs live in memory - a restart ends a pull, and Ollama
# resumes the part already on disk when the same name is pulled again.

_OLLAMA_PULLS: dict[str, dict[str, Any]] = {}
_OLLAMA_PULL_KEEP_JOBS = 8
_OLLAMA_PULL_KEEP_LINES = 600
_OLLAMA_PULL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/:]{0,199}$")
_OLLAMA_HOSTS = ("ollama.com", "www.ollama.com", "ollama.ai",
                 "registry.ollama.ai")
_HF_HOSTS = ("huggingface.co", "www.huggingface.co", "hf.co")


def ollama_pull_ref(text: str) -> str:
    """What Ollama should pull, from whatever the operator pasted: a bare
    name, an `ollama run|pull` line, an ollama.com page, or a Hugging Face
    repo / .gguf link (Ollama pulls those as hf.co/<user>/<repo>[:<quant>]).
    "" when it is none of those."""
    raw = str(text or "").strip().strip("`'\"").strip()
    words = raw.split()
    if not words:
        return ""
    if words[0].lower() == "ollama":
        rest = [w for w in words[1:] if not w.startswith("-")]
        if rest and rest[0].lower() in ("run", "pull"):
            rest = rest[1:]
        raw = rest[0] if rest else ""
    else:
        raw = words[0]
    raw = raw.strip("`'\"<>")
    low = raw.lower()
    if (not low.startswith(("http://", "https://")) and "/" in low
            and low.split("/", 1)[0] in _OLLAMA_HOSTS + _HF_HOSTS):
        raw, low = "https://" + raw, "https://" + low
    if low.startswith(("http://", "https://")):
        try:
            url = urlparse(raw)
        except ValueError:
            return ""
        host = (url.hostname or "").lower()
        parts = [p for p in url.path.split("/") if p]
        if host in _OLLAMA_HOSTS:
            if parts[:1] == ["library"]:
                parts = parts[1:]
            if len(parts) > 1 and parts[-1] in ("tags", "blobs"):
                parts = parts[:-1]
            raw = "/".join(parts[:2])
        elif host in _HF_HOSTS:
            if len(parts) < 2:
                return ""
            leaf = parts[-1] if len(parts) > 3 else ""
            quant = re.search(r"(?i)[.\-_]((?:i?q\d\w*)|bf16|f16|f32)\.gguf$",
                              leaf)
            raw = "hf.co/" + "/".join(parts[:2]) + (
                ":" + quant.group(1) if quant else "")
        else:
            raw = host + "".join("/" + p for p in parts)
    raw = raw.strip("/")
    if ".." in raw or not _OLLAMA_PULL_NAME.match(raw):
        return ""
    return raw


def _ollama_pull_say(job: dict[str, Any], text: str) -> None:
    job["seq"] += 1
    job["log"].append({"seq": job["seq"], "t": round(time.time(), 2),
                       "text": str(text)[:400]})
    if len(job["log"]) > _OLLAMA_PULL_KEEP_LINES:
        del job["log"][:len(job["log"]) - _OLLAMA_PULL_KEEP_LINES]


def _ollama_pull_size(n: float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1000:
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} TB"


def _ollama_pull_layer(job: dict[str, Any], ev: dict[str, Any],
                       now: float) -> None:
    """One progress event for one layer: bytes, a smoothed rate, and a
    console line when the layer first shows and when it is whole."""
    digest = str(ev.get("digest") or "")
    total = int(ev.get("total") or 0)
    done = int(ev.get("completed") or 0)
    short = digest.split(":")[-1][:12]
    lay = job["layers"].get(digest)
    if lay is None:
        lay = job["layers"][digest] = {
            "digest": digest, "total": total, "completed": done, "rate": 0.0,
            "began": now, "_t": now, "_c": done, "whole": False}
        if total and done >= total:
            lay["whole"] = True
            _ollama_pull_say(job, f"{short} already here · "
                                  f"{_ollama_pull_size(total)}")
            return
        _ollama_pull_say(job, f"pulling {short} · {_ollama_pull_size(total)}"
                              + (f" (resuming at {_ollama_pull_size(done)})"
                                 if done else ""))
        return
    if total:
        lay["total"] = total
    gap = now - lay["_t"]
    if gap >= 0.5:
        step = max(0, done - lay["_c"]) / gap
        lay["rate"] = step if not lay["rate"] else lay["rate"] * 0.6 + step * 0.4
        lay["_t"], lay["_c"] = now, done
    lay["completed"] = max(lay["completed"], done)
    if lay["total"] and lay["completed"] >= lay["total"] and not lay["whole"]:
        lay["whole"] = True
        lay["rate"] = 0.0
        took = max(0.0, now - lay["began"])
        _ollama_pull_say(job, f"{short} downloaded · "
                              f"{_ollama_pull_size(lay['total'])} in {took:.0f}s")


async def _ollama_pull_stored(name: str) -> str:
    """The name Ollama filed the pull under (a bare name lands as :latest)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            got = (await client.get(f"{OLLAMA_URL}/api/tags")).json() or {}
        names = [str(m.get("name") or "") for m in got.get("models") or []]
    except Exception:  # noqa: BLE001
        return name
    for want in (name, name + ":latest"):
        for have in names:
            if have.lower() == want.lower():
                return have
    return name


async def _ollama_pull_run(job: dict[str, Any]) -> None:
    name = job["model"]
    _ollama_pull_say(job, f"$ ollama pull {name}")
    said = ""
    try:
        timeout = httpx.Timeout(connect=15.0, read=600.0, write=30.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                    "POST", f"{OLLAMA_URL}/api/pull",
                    json={"model": name, "name": name, "stream": True}) as reply:
                if reply.status_code != 200:
                    body = (await reply.aread()).decode("utf-8", "replace")
                    try:
                        why = str((json.loads(body) or {}).get("error") or body)
                    except (ValueError, AttributeError):
                        why = body
                    raise RuntimeError(f"Ollama answered {reply.status_code}: "
                                       f"{why.strip()[:300]}")
                async for line in reply.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        _ollama_pull_say(job, line)
                        continue
                    if not isinstance(ev, dict):
                        continue
                    if ev.get("error"):
                        raise RuntimeError(str(ev["error"]))
                    now = time.time()
                    job["heard"] = now
                    status = str(ev.get("status") or "")
                    if status:
                        job["status"] = status
                    if ev.get("digest"):
                        # a layer's status repeats with every chunk: its
                        # lines come from _ollama_pull_layer, not from here
                        _ollama_pull_layer(job, ev, now)
                    elif status and status != said:
                        said = status
                        _ollama_pull_say(job, status)
                    if status == "success":
                        job["landed"] = True
        if not job.get("landed"):
            raise RuntimeError("the stream ended before Ollama said success")
        stored = await _ollama_pull_stored(name)
        job["stored"] = stored
        _MODEL_CAPS.pop(stored, None)
        caps = await model_capabilities(stored)
        job["capabilities"] = caps
        _ollama_pull_say(job, "it can do: " + (", ".join(caps) if caps
                                               else "(Ollama did not say)"))
        if caps and "vision" not in caps:
            _ollama_pull_say(job, f"no vision - pictures keep going to "
                                  f"{VISION_MODEL}, as they always do")
        if job.get("use"):
            writer_model_apply(stored)
            job["switched"] = True
            _ollama_pull_say(job, f"the writer is now {stored} - warming it "
                                  f"for the next line")
        job["state"] = "done"
    except asyncio.CancelledError:
        job["state"] = "cancelled"
        job["error"] = "stopped"
        _ollama_pull_say(job, "stopped - what is already on disk stays; pull "
                              "the same name again and Ollama resumes it")
        raise
    except Exception as exc:  # noqa: BLE001
        job["state"] = "error"
        job["error"] = str(exc) or exc.__class__.__name__
        _ollama_pull_say(job, "error: " + job["error"])
    finally:
        job["ended"] = time.time()
        job.pop("_task", None)


def _ollama_pull_view(job: dict[str, Any], since: int = 0) -> dict[str, Any]:
    live = job["state"] == "pulling"
    layers = [{"digest": l["digest"], "total": l["total"],
               "completed": min(l["completed"], l["total"] or l["completed"]),
               "rate": round(l["rate"], 1) if live else 0.0}
              for l in job["layers"].values()]
    return {
        "id": job["id"], "asked": job["asked"], "model": job["model"],
        "stored": job.get("stored") or "", "state": job["state"],
        "status": job.get("status") or "", "use": bool(job.get("use")),
        "switched": bool(job.get("switched")), "error": job.get("error") or "",
        "capabilities": job.get("capabilities") or [],
        "started": job["started"], "ended": job.get("ended") or 0,
        "heard": job.get("heard") or 0, "now": time.time(),
        "total": sum(l["total"] for l in layers),
        "completed": sum(l["completed"] for l in layers),
        "rate": round(sum(l["rate"] for l in layers), 1),
        "layers": layers, "seq": job["seq"],
        "log": [l for l in job["log"] if l["seq"] > since],
    }


@app.post("/api/ollama/pull")
async def ollama_pull_start(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Start pulling a model - or hand back the same pull already running."""
    require_auth(authorization)
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    asked = str(payload.get("model") or "").strip()
    name = ollama_pull_ref(asked)
    if not name:
        raise HTTPException(
            status_code=400,
            detail="That is not a model name or a link Ollama can pull - "
                   "for example huihui_ai/gemma-4-abliterated:e2b")
    for job in _OLLAMA_PULLS.values():
        if job["state"] == "pulling":
            if job["model"] == name:
                return _ollama_pull_view(job)
            raise HTTPException(
                status_code=409,
                detail=f"Already pulling {job['model']} - one at a time; "
                       f"stop it or let it land first")
    job: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12], "asked": asked[:300], "model": name,
        "use": bool(payload.get("use", True)), "state": "pulling",
        "status": "starting", "started": time.time(), "seq": 0, "log": [],
        "layers": {}}
    _OLLAMA_PULLS[job["id"]] = job
    ended = [k for k, j in _OLLAMA_PULLS.items() if j["state"] != "pulling"]
    for k in ended[:max(0, len(_OLLAMA_PULLS) - _OLLAMA_PULL_KEEP_JOBS)]:
        _OLLAMA_PULLS.pop(k, None)
    job["_task"] = asyncio.create_task(_ollama_pull_run(job))
    return _ollama_pull_view(job)


@app.get("/api/ollama/pull")
async def ollama_pull_list(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """The pull running now (with its whole log), and the last few."""
    require_read_auth(authorization)
    jobs = list(_OLLAMA_PULLS.values())
    active = next((j for j in jobs if j["state"] == "pulling"), None)
    return {
        "active": _ollama_pull_view(active) if active else None,
        "recent": [{"id": j["id"], "model": j["model"], "state": j["state"],
                    "started": j["started"], "ended": j.get("ended") or 0,
                    "error": j.get("error") or ""} for j in reversed(jobs)],
    }


@app.get("/api/ollama/pull/{job_id}")
async def ollama_pull_get(
    job_id: str,
    since: int = 0,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_read_auth(authorization)
    job = _OLLAMA_PULLS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404,
                            detail="No such pull - the station may have "
                                   "restarted since it began")
    return _ollama_pull_view(job, since)


@app.post("/api/ollama/pull/{job_id}/cancel")
async def ollama_pull_cancel(
    job_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_auth(authorization)
    job = _OLLAMA_PULLS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such pull")
    task = job.get("_task")
    if job["state"] == "pulling" and task is not None and not task.done():
        task.cancel()
    return _ollama_pull_view(job)
'''

# -------------------------------------------------------------- html --------

HTML_OLD = '''    <select id="headerModel" title="Active model — switches immediately"
            onchange="switchModel(this.value)"
            style="width:auto;flex:0 1 auto;min-width:0;
                   padding:6px 10px;font-size:13px"></select>
'''

HTML_NEW = '''    <!-- [model-pull] the pencil: type or paste a model - an `ollama run`
         line, an ollama.com or Hugging Face link - and pull it with Ollama,
         watching the bar, the layers and the console while it lands. -->
    <span id="headerModelBox" class="model-box"
          style="position:relative;display:inline-flex;align-items:center;
                 flex:0 1 auto;min-width:0;max-width:100%">
    <select id="headerModel" title="Active model — switches immediately"
            onchange="switchModel(this.value)"
            style="width:auto;flex:1 1 auto;min-width:0;
                   padding:6px 36px 6px 10px;font-size:13px"></select>
    <button id="modelPullBtn" class="model-pull-btn" type="button"
            data-pine-icon="c:edit"
            aria-label="Pull a model with Ollama"
            title="Pull a model with Ollama — type or paste its name, its
ollama run line, or an ollama.com / Hugging Face link"
            onclick="modelPullOpen()"
            style="position:absolute;right:24px;top:50%;
                   transform:translateY(-50%);width:24px;height:24px;
                   padding:0;margin:0;border:0;background:transparent;
                   display:grid;place-items:center;line-height:0"></button>
    </span>
'''

# ---------------------------------------------------------------- js --------

JS_OLD = '''  } catch (error) { /* panel works without it */ }
}

/* ---- Voice system + voice model, in the header (#80, #81, #84) ---- */'''

JS_BLOCK_V1 = r'''/* ---- [model-pull] The pencil in the model picker: pull any Ollama model ----
   "put an icon of a pencil here that when clicked, allows me to type or paste
    in the url to a model to download and pull with ollama and use with this
    parameter"                                        - the operator, 2026-09-29
   Paste what the model's page says - `ollama run huihui_ai/gemma-4-abliterated:e2b`,
   an ollama.com link, a Hugging Face repo or .gguf link - and the station
   pulls it through Ollama. The pull lives on the station (/api/ollama/pull);
   this window is a view of it, so closing it loses nothing and opening it
   again picks the same pull back up. It draws the stages, the whole bar, the
   layers the way the ollama CLI draws them (a spinner on the one still
   moving) and every line the stream said. When it lands it can become the
   writer through /api/model's own road, and both pickers refill. */

const MODEL_PULL_SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";
const MODEL_PULL_STAGES = ["manifest", "download", "verify", "write", "ready"];
const modelPull = {win: null, job: null, since: 0, poll: 0, every: 0,
                   spin: 0, tick: 0, busy: false, landed: ""};

function modelPullCss() {
  if (document.getElementById("modelPullStyle")) return;
  const s = document.createElement("style");
  s.id = "modelPullStyle";
  s.textContent = `
.model-pull-btn { color: var(--muted); cursor: pointer; border-radius: 6px;
  z-index: 1; }
.model-pull-btn:hover, .model-pull-btn:focus-visible { color: var(--text);
  background: rgba(255,255,255,.10) !important; }
.model-pull-btn svg { width: 15px; height: 15px; }
.model-pull-btn.busy { color: var(--accent); }
.model-pull-btn.busy::after { content: ""; position: absolute; inset: -1px;
  border-radius: 50%; border: 2px solid transparent;
  border-top-color: var(--accent); animation: mpTurn .9s linear infinite; }
@keyframes mpTurn { to { transform: rotate(360deg); } }
@keyframes mpStripe { to { background-position: 28px 0; } }
@keyframes mpPulse { 50% { opacity: .5; } }
@keyframes mpBlink { 50% { opacity: 0; } }
@keyframes mpFlow { from { left: -8%; } to { left: 102%; } }
.mp { display: flex; flex-direction: column; gap: 10px; height: 100%;
  box-sizing: border-box; padding: 12px; color: var(--text); font-size: 13px;
  background: var(--panel); }
.mp-ask { display: flex; gap: 8px; margin: 0; }
.mp-ask input { flex: 1; min-width: 0; padding: 8px 10px; font-size: 13px;
  font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; }
.mp-ask button, .mp-foot button { display: inline-flex; align-items: center;
  gap: 6px; white-space: nowrap; }
.mp-ask button { padding: 7px 12px; }
.mp-foot button { padding: 6px 11px; font-size: 12px; }
.mp-foot button[hidden] { display: none; }
.mp-ask button svg, .mp-foot button svg { width: 14px; height: 14px; }
.mp-use { display: flex; align-items: center; gap: 8px; margin: 0;
  font-size: 12px; color: var(--muted); cursor: pointer; }
.mp-use input { width: auto; margin: 0; padding: 0; }
.mp-wire { display: flex; align-items: center; gap: 10px; font-size: 11px;
  color: var(--muted); }
.mp-wire svg { width: 16px; height: 16px; }
.mp-end { display: inline-flex; align-items: center; gap: 5px; flex: none; }
.mp-line { position: relative; flex: 1; height: 2px; border-radius: 2px;
  background: var(--border); }
.mp-line i { position: absolute; top: -2px; left: -8%; width: 6px;
  height: 6px; border-radius: 50%; background: var(--accent); opacity: 0; }
.mp.live .mp-line i { opacity: 1; animation: mpFlow 1.5s linear infinite; }
.mp.live .mp-line i:nth-child(2) { animation-delay: .5s; }
.mp.live .mp-line i:nth-child(3) { animation-delay: 1s; }
.mp-stages { display: flex; gap: 4px; }
.mp-stage { flex: 1 1 0; min-width: 0; text-align: center; padding: 4px 6px;
  border: 1px solid var(--border); border-radius: 999px; font-size: 11px;
  color: var(--muted); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.mp-stage.done { color: var(--text); border-color: var(--accent); }
.mp-stage.now { color: var(--bg); background: var(--accent);
  border-color: var(--accent); animation: mpPulse 1.2s ease-in-out infinite; }
.mp-stage.bad { color: #fff; background: var(--danger);
  border-color: var(--danger); }
.mp-bar { position: relative; flex: none; height: 12px; border-radius: 6px;
  overflow: hidden; background: var(--panel2); border: 1px solid var(--border); }
.mp-bar i { position: absolute; left: 0; top: 0; bottom: 0; width: 0;
  background-color: var(--accent); transition: width .45s ease; }
.mp.live .mp-bar i { background-image: repeating-linear-gradient(-45deg,
  rgba(255,255,255,.24) 0 7px, transparent 7px 14px);
  background-size: 28px 12px; animation: mpStripe .7s linear infinite; }
.mp.failed .mp-bar i { background-color: var(--danger); }
.mp-nums { display: flex; gap: 14px; flex-wrap: wrap; align-items: baseline;
  font-size: 12px; color: var(--muted);
  font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; }
.mp-nums b { color: var(--text); font-size: 15px; }
.mp-con { flex: 1; min-height: 110px; overflow: auto; margin: 0;
  padding: 10px 12px; border-radius: 8px; border: 1px solid var(--border);
  background: #05070b; color: #cfd8e3; font-size: 12px; line-height: 1.55;
  font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; }
.mp-ln { white-space: pre-wrap; word-break: break-word; }
.mp-ln .mp-t { color: #5d6b7e; margin-right: 8px; }
.mp-ln.cmd { color: var(--accent); }
.mp-ln.bad { color: var(--danger); }
.mp-ln.ok { color: #7fd99a; }
.mp-ln.hint { color: #6f7d90; }
.mp-lay { white-space: pre; color: #e8eef6; }
.mp-spin { display: inline-block; width: 1.6em; color: var(--accent); }
.mp-lay svg { width: 12px; height: 12px; vertical-align: -1px; color: #7fd99a; }
.mp-cursor { display: inline-block; width: .6em; height: 1.1em;
  vertical-align: -2px; background: #cfd8e3;
  animation: mpBlink 1s step-end infinite; }
.mp-foot { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  font-size: 12px; color: var(--muted); }
.mp-say { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; font-family: ui-monospace, "Cascadia Mono", Consolas,
  monospace; }
`;
  document.head.appendChild(s);
}
modelPullCss();

function modelPullSize(n) {
  n = Number(n) || 0;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1000 && i < units.length - 1) { n /= 1000; i += 1; }
  return (i < 2 ? Math.round(n) : n.toFixed(1)) + " " + units[i];
}

function modelPullClock(sec) {
  sec = Math.max(0, Math.round(Number(sec) || 0));
  const h = Math.floor(sec / 3600);
  const m = Math.floor(sec / 60) % 60;
  const s = sec % 60;
  if (h) return h + "h" + String(m).padStart(2, "0") + "m";
  return m ? m + "m" + String(s).padStart(2, "0") + "s" : s + "s";
}

// The bar the ollama CLI draws, to an eighth of a cell.
function modelPullTextBar(frac, width) {
  const cells = Math.max(0, Math.min(1, Number(frac) || 0)) * width;
  const full = Math.floor(cells);
  const part = Math.round((cells - full) * 8);
  let s = "█".repeat(full);
  if (full < width) {
    s += (part ? " ▏▎▍▌▋▊▉█"[part] : " ") + " ".repeat(width - full - 1);
  }
  return "▕" + s + "▏";
}

// Which of the five stages the pull is in: 0 manifest .. 4 ready, 5 = all done.
function modelPullStage(job) {
  if (!job) return -1;
  if (job.state === "done") return 5;
  const st = String(job.status || "");
  if (/^success/.test(st)) return 4;
  if (/writing manifest|removing|unused/.test(st)) return 3;
  if (/verifying/.test(st)) return 2;
  if ((job.layers || []).length || /^pulling [0-9a-f]/.test(st)) return 1;
  return 0;
}

function modelPullQ(sel) {
  const w = modelPull.win;
  return w && w.box.isConnected ? w.host.querySelector(sel) : null;
}

function modelPullLine(text, time, kind) {
  const log = modelPullQ(".mp-log");
  if (!log) return;
  const row = el("div", "mp-ln", "");
  text = String(text || "");
  if (kind) row.classList.add(kind);
  else if (/^\$ /.test(text)) row.classList.add("cmd");
  else if (/^(error|stopped)/.test(text)) row.classList.add("bad");
  else if (/^(success|the writer is now)/.test(text)) row.classList.add("ok");
  if (time) {
    row.appendChild(el("span", "mp-t", new Date(time * 1000)
      .toLocaleTimeString([], {hour12: false})));
  }
  row.appendChild(document.createTextNode(text));
  log.appendChild(row);
}

function modelPullFollow() {
  const con = modelPullQ(".mp-con");
  if (con && window.pineStick) pineStick(con, {edge: "bottom"}).follow();
}

function modelPullHint() {
  [
    "# type or paste what the model's page says, for example",
    "#   ollama run huihui_ai/gemma-4-abliterated:e2b",
    "#   https://ollama.com/library/gemma3:4b",
    "#   https://huggingface.co/<user>/<repo>-GGUF   (a .gguf link picks its quant)",
    "# then Pull. It runs on the station: close this and it keeps going.",
  ].forEach((t) => modelPullLine(t, 0, "hint"));
}

function modelPullSpinTick() {
  modelPull.tick += 1;
  const frame = MODEL_PULL_SPIN[modelPull.tick % MODEL_PULL_SPIN.length];
  const w = modelPull.win;
  if (!w || !w.box.isConnected) return;
  w.host.querySelectorAll(".mp-spin[data-live]").forEach((n) => {
    n.textContent = frame;
  });
}

function modelPullTimers() {
  const job = modelPull.job;
  const live = !!(job && job.state === "pulling");
  const open = !!(modelPull.win && modelPull.win.box.isConnected);
  const every = open ? 500 : 2000;       // closed: just enough for the pencil
  if (live && modelPull.every !== every) {
    clearInterval(modelPull.poll);
    modelPull.poll = setInterval(modelPullPoll, every);
    modelPull.every = every;
  }
  if (!live && modelPull.poll) {
    clearInterval(modelPull.poll);
    modelPull.poll = 0;
    modelPull.every = 0;
  }
  if (live && open && !modelPull.spin) {
    modelPull.spin = setInterval(modelPullSpinTick, 90);
  }
  if (!(live && open) && modelPull.spin) {
    clearInterval(modelPull.spin);
    modelPull.spin = 0;
  }
  const pen = document.getElementById("modelPullBtn");
  if (pen) pen.classList.toggle("busy", live);
}

function modelPullRender() {
  const root = modelPullQ(".mp");
  if (!root) return;
  const job = modelPull.job;
  const live = !!(job && job.state === "pulling");
  const bad = !!(job && (job.state === "error" || job.state === "cancelled"));
  root.classList.toggle("live", live);
  root.classList.toggle("failed", bad);
  modelPullQ(".mp-go").disabled = live;
  modelPullQ(".mp-in").disabled = live;
  modelPullQ(".mp-from").textContent = job && /^hf\.co\//i.test(job.model)
    ? "huggingface.co" : "registry.ollama.ai";

  const at = modelPullStage(job);
  root.querySelectorAll(".mp-stage").forEach((node, i) => {
    node.className = "mp-stage" + (i < at ? " done"
      : i === at ? (bad ? " bad" : " now") : "");
  });

  const total = job ? Number(job.total) || 0 : 0;
  const done = job ? Number(job.completed) || 0 : 0;
  const rate = job ? Number(job.rate) || 0 : 0;
  const frac = job && job.state === "done" ? 1 : total ? done / total : 0;
  modelPullQ(".mp-bar i").style.width = (frac * 100).toFixed(1) + "%";
  modelPullQ(".mp-pct").textContent = job ? Math.floor(frac * 100) + "%" : "";
  modelPullQ(".mp-bytes").textContent = total
    ? modelPullSize(done) + " / " + modelPullSize(total) : "";
  modelPullQ(".mp-rate").textContent = live && rate > 0
    ? modelPullSize(rate) + "/s" : "";
  modelPullQ(".mp-eta").textContent = live && rate > 0 && total > done
    ? modelPullClock((total - done) / rate) + " left" : "";
  const began = job ? Number(job.started) || 0 : 0;
  const upto = job ? Number(job.ended) || Number(job.now) || 0 : 0;
  modelPullQ(".mp-took").textContent = began && upto > began
    ? modelPullClock(upto - began) + " elapsed" : "";

  // The layers, drawn in place under the log the way the ollama CLI does.
  const lays = modelPullQ(".mp-layers");
  lays.textContent = "";
  (job && job.layers || []).forEach((l) => {
    const row = el("div", "mp-lay", "");
    const whole = l.total > 0 && l.completed >= l.total;
    const spin = el("span", "mp-spin", "");
    if (whole && window.pineIcon) spin.innerHTML = pineIcon("c:checkmark");
    else if (live) {
      spin.dataset.live = "1";
      spin.textContent = MODEL_PULL_SPIN[modelPull.tick % MODEL_PULL_SPIN.length];
    }
    row.appendChild(spin);
    const part = l.total ? l.completed / l.total : 0;
    const short = String(l.digest || "").split(":").pop().slice(0, 12);
    row.appendChild(document.createTextNode("pulling " + short + ": "
      + String(Math.floor(part * 100)).padStart(3) + "% "
      + modelPullTextBar(part, 22) + " "
      + (l.total ? modelPullSize(l.completed) + "/" + modelPullSize(l.total) : "")
      + (!whole && live && l.rate > 0
        ? "  " + modelPullSize(l.rate) + "/s  "
          + modelPullClock((l.total - l.completed) / l.rate) : "")));
    lays.appendChild(row);
  });

  const say = modelPullQ(".mp-say");
  say.textContent = "";
  if (live) {
    const spin = el("span", "mp-spin", MODEL_PULL_SPIN[modelPull.tick % 10]);
    spin.dataset.live = "1";
    say.appendChild(spin);
    say.appendChild(document.createTextNode(job.status || "starting"));
  } else if (job && job.state === "done") {
    say.textContent = "landed as " + (job.stored || job.model)
      + (job.switched ? " · the writer now" : "");
  } else if (job) {
    say.textContent = job.error || job.state;
  }
  modelPullQ(".mp-stop").hidden = !live;
  modelPullQ(".mp-adopt").hidden = !(job && job.state === "done"
    && !job.switched);
  modelPullFollow();
}

// The model is in Ollama now: refill both pickers, and say so.
async function modelPullLanded(job) {
  if (!job || job.state !== "done" || modelPull.landed === job.id) return;
  modelPull.landed = job.id;
  const name = job.stored || job.model;
  if (job.switched && typeof settings === "object" && settings) {
    settings.model = name;
  }
  try { await populateHeaderModel(); } catch (e) {}
  try { await loadModels(); } catch (e) {}
  if (job.switched) {
    const field = document.getElementById("model");
    if (field) field.value = name;
    setStatus("Writer → " + name);
  } else {
    setStatus("Pulled " + name + " · pick it in the model list to use it");
  }
}

async function modelPullPoll() {
  const job = modelPull.job;
  if (!job || job.state !== "pulling") { modelPullTimers(); return; }
  if (modelPull.busy) return;
  modelPull.busy = true;
  const open = !!modelPullQ(".mp");
  try {
    // A closed window reads no log (since stays put), so reopening shows
    // every line it missed.
    const got = await api("/api/ollama/pull/" + encodeURIComponent(job.id)
      + "?since=" + (open ? modelPull.since : 1e9));
    modelPull.job = got;
    if (open) {
      (got.log || []).forEach((l) => modelPullLine(l.text, l.t));
      modelPull.since = got.seq || modelPull.since;
    }
    if (got.state === "done") modelPullLanded(got);
  } catch (error) {
    if (/No such pull/.test(error.message)) {
      modelPull.job = {...job, state: "error", error: error.message};
      modelPullLine("error: " + error.message, Date.now() / 1000);
    }
  } finally {
    modelPull.busy = false;
  }
  modelPullRender();
  modelPullTimers();
}

async function modelPullStart() {
  const input = modelPullQ(".mp-in");
  if (!input) return;
  const text = input.value.trim();
  if (!text) { input.focus(); return; }
  const use = modelPullQ(".mp-use-box").checked;
  modelPullQ(".mp-log").textContent = "";
  modelPull.since = 0;
  modelPull.job = null;
  modelPullRender();
  try {
    const job = await api("/api/ollama/pull", {
      method: "POST", body: JSON.stringify({model: text, use}),
    });
    modelPull.job = job;
    (job.log || []).forEach((l) => modelPullLine(l.text, l.t));
    modelPull.since = job.seq || 0;
  } catch (error) {
    modelPullLine("error: " + error.message, Date.now() / 1000);
  }
  modelPullRender();
  modelPullTimers();
}

async function modelPullStop() {
  const job = modelPull.job;
  if (!job || job.state !== "pulling") return;
  try {
    await api("/api/ollama/pull/" + encodeURIComponent(job.id) + "/cancel",
              {method: "POST"});
  } catch (error) {
    modelPullLine("error: " + error.message, Date.now() / 1000);
  }
  modelPullPoll();
}

// Landed without the switch ticked: make it the writer now, the same way the
// model picker does.
async function modelPullAdopt() {
  const job = modelPull.job;
  if (!job || job.state !== "done") return;
  const name = job.stored || job.model;
  await switchModel(name);
  modelPull.job = {...job, switched: true};
  if (typeof settings === "object" && settings) settings.model = name;
  modelPullLine("the writer is now " + name, Date.now() / 1000);
  setStatus("Writer → " + name);
  modelPullRender();
}

async function modelPullOpen() {
  if (modelPull.win && modelPull.win.box.isConnected) {
    pineWinRaise(modelPull.win.box);
    const input = modelPullQ(".mp-in");
    if (input && !input.disabled) input.focus();
    return;
  }
  const w = pineWin("modelPull", "Pull a model with Ollama", {
    width: 660, height: 540, minWidth: 360, minHeight: 330,
    onClose: () => { modelPull.win = null; modelPullTimers(); },
  });
  modelPull.win = w;
  w.host.innerHTML = `
<div class="mp">
  <form class="mp-ask" autocomplete="off">
    <input class="mp-in" spellcheck="false"
           aria-label="Model name, ollama run line, or link"
           placeholder="ollama run huihui_ai/gemma-4-abliterated:e2b  ·  or an ollama.com / huggingface.co link">
    <button class="mp-go" type="submit" title="Pull it with Ollama"><span data-pine-icon="c:download"></span>Pull</button>
  </form>
  <label class="mp-use" title="When it lands, switch the station's writer to it - the same switch as the model picker"><input class="mp-use-box" type="checkbox" checked>make it the writer when it lands</label>
  <div class="mp-wire"><span class="mp-end"><span data-pine-icon="c:cloud"></span><span class="mp-from">registry.ollama.ai</span></span><span class="mp-line"><i></i><i></i><i></i></span><span class="mp-end"><span data-pine-icon="c:box"></span>Pine Box</span></div>
  <div class="mp-stages">${MODEL_PULL_STAGES.map((s) => `<span class="mp-stage">${s}</span>`).join("")}</div>
  <div class="mp-bar"><i></i></div>
  <div class="mp-nums"><b class="mp-pct"></b><span class="mp-bytes"></span><span class="mp-rate"></span><span class="mp-eta"></span><span class="mp-took"></span></div>
  <div class="mp-con"><div class="mp-log"></div><div class="mp-layers"></div><span class="mp-cursor"></span></div>
  <div class="mp-foot"><span class="mp-say"></span><button class="mp-adopt" type="button" hidden><span data-pine-icon="c:checkmark"></span>Make it the writer</button><button class="mp-stop" type="button" hidden><span data-pine-icon="c:stop--filled"></span>Stop</button></div>
</div>`;
  if (window.pineIconUpgrade) pineIconUpgrade(w.host);
  modelPullQ(".mp-ask").addEventListener("submit", (event) => {
    event.preventDefault();
    modelPullStart();
  });
  modelPullQ(".mp-stop").onclick = modelPullStop;
  modelPullQ(".mp-adopt").onclick = modelPullAdopt;

  // Whatever is pulling now - or the last pull this page watched - is what
  // the window shows, with its whole log.
  modelPull.since = 0;
  let show = null;
  try { show = (await api("/api/ollama/pull")).active; } catch (e) {}
  if (!show && modelPull.job) {
    try {
      show = await api("/api/ollama/pull/"
        + encodeURIComponent(modelPull.job.id) + "?since=0");
    } catch (e) { show = null; }
  }
  if (modelPull.win !== w) return;          // closed while we asked
  modelPull.job = show;
  if (show) {
    (show.log || []).forEach((l) => modelPullLine(l.text, l.t));
    modelPull.since = show.seq || 0;
    if (show.state === "done") modelPullLanded(show);
  } else {
    modelPullHint();
  }
  modelPullRender();
  modelPullTimers();
  const input = modelPullQ(".mp-in");
  if (input && !input.disabled) input.focus();
}

'''

# ui2 - seen in a headless render of the live panel at 544 px: the flowing
# dots ran over the registry label, the pulsing stage faded its own text to
# half, the layer rows scrolled sideways, and the placeholder read like a
# value already typed. Each pair is v1 -> v2 inside the block.
UI2 = [
    ('const MODEL_PULL_SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";',
     'const MODEL_PULL_SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";   // [model-pull ui2] the npm/npx spinner'),
    ("@keyframes mpPulse { 50% { opacity: .5; } }",
     "@keyframes mpPulse { 50% { box-shadow: 0 0 0 4px rgba(255,255,255,.16); } }"),
    ("@keyframes mpFlow { from { left: -8%; } to { left: 102%; } }",
     "@keyframes mpFlow { 0% { left: 0; opacity: 0; } 15%, 85% { opacity: 1; }\n"
     "  100% { left: calc(100% - 6px); opacity: 0; } }"),
    (".mp-line i { position: absolute; top: -2px; left: -8%; width: 6px;",
     ".mp-line i { position: absolute; top: -2px; left: 0; width: 6px;"),
    (".mp.live .mp-line i { opacity: 1; animation: mpFlow 1.5s linear infinite; }",
     ".mp.live .mp-line i { animation: mpFlow 1.5s linear infinite; }"),
    (".mp-lay { white-space: pre; color: #e8eef6; }",
     ".mp-lay { white-space: pre-wrap; color: #e8eef6; }"),
    (".mp-spin { display: inline-block; width: 1.6em; color: var(--accent); }",
     ".mp-spin { display: inline-block; width: 1.6em; color: var(--accent);\n"
     "  font-size: 1.2em; line-height: 1; vertical-align: -1px; }"),
    ('placeholder="ollama run huihui_ai/gemma-4-abliterated:e2b  ·  or an ollama.com / huggingface.co link">',
     'placeholder="paste an ollama run line, a model name, or a link">'),
    (r'''    row.appendChild(document.createTextNode("pulling " + short + ": "
      + String(Math.floor(part * 100)).padStart(3) + "% "
      + modelPullTextBar(part, 22) + " "
      + (l.total ? modelPullSize(l.completed) + "/" + modelPullSize(l.total) : "")
      + (!whole && live && l.rate > 0
        ? "  " + modelPullSize(l.rate) + "/s  "
          + modelPullClock((l.total - l.completed) / l.rate) : "")));
''', r'''    // Non-breaking inside each group, so a narrow window wraps between
    // groups and never through the middle of the bar or a size.
    const nb = (s) => String(s).replace(/ /g, "\u00a0");
    const groups = [
      nb("pulling " + short + ":"),
      nb(String(Math.floor(part * 100)).padStart(3) + "%"),
      nb(modelPullTextBar(part, 20)),
    ];
    if (l.total) {
      groups.push(nb(modelPullSize(l.completed) + "/" + modelPullSize(l.total)));
    }
    if (!whole && live && l.rate > 0) {
      groups.push(nb(modelPullSize(l.rate) + "/s"),
                  nb(modelPullClock((l.total - l.completed) / l.rate)));
    }
    row.appendChild(document.createTextNode(groups.join(" ")));
'''),
]

JS_BLOCK = JS_BLOCK_V1
for _old, _new in UI2:
    assert JS_BLOCK.count(_old) == 1, _old[:60]
    JS_BLOCK = JS_BLOCK.replace(_old, _new, 1)

JS_NEW = ('''  } catch (error) { /* panel works without it */ }
}

''' + JS_BLOCK + '''/* ---- Voice system + voice model, in the header (#80, #81, #84) ---- */''')

# Measured on the first live pull (all-minilm:22m): Ollama repeats a layer's
# last event after it is whole, and each repeat re-measured bytes against a
# sample taken before the finish, so the total rate stayed at 8.6 MB/s with
# nothing moving. A whole layer moves no more bytes.
RATE_OLD = '''    if total:
        lay["total"] = total
    gap = now - lay["_t"]
'''

RATE_NEW = '''    if total:
        lay["total"] = total
    if lay["whole"]:
        return          # a whole layer moves no more bytes; Ollama repeats its last event
    gap = now - lay["_t"]
'''

EDITS = [
    ("py", PY_OLD, PY_NEW, "# ---- [model-pull] The model door"),
    ("html", HTML_OLD, HTML_NEW, 'id="modelPullBtn"'),
    ("js", JS_OLD, JS_NEW, "/* ---- [model-pull] The pencil in the model picker"),
    ("rate", RATE_OLD, RATE_NEW, "return          # a whole layer moves no more bytes"),
    ("ui2", JS_BLOCK_V1, JS_BLOCK, "[model-pull ui2]"),
]


def survey(text):
    """In order, as --apply would: a later edit may anchor inside an earlier
    one's text (rate edits what py inserts)."""
    out = []
    for name, old, new, mark in EDITS:
        if mark in text:
            out.append((name, "applied", 0))
            continue
        n = text.count(old)
        out.append((name, "ready" if n == 1 else "missing", n))
        if n == 1:
            text = text.replace(old, new, 1)
    return out


def panel_script(text):
    start = text.index('CONTROL_PANEL_HTML = r"""') + len('CONTROL_PANEL_HTML = r"""')
    end = text.index('\n"""', start)
    html = text[start:end]
    blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
    return "\n;\n".join(blocks)


def node_check(text):
    node = shutil.which("node")
    if not node:
        print("node: not on PATH - panel script NOT checked")
        return True
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(panel_script(text))
        path = fh.name
    try:
        run = subprocess.run([node, "--check", path], capture_output=True,
                             text=True)
    finally:
        os.unlink(path)
    if run.returncode:
        print("node --check FAILED:\n" + (run.stderr or run.stdout)[-2000:])
        return False
    print("node --check: panel script parses")
    return True


def main(argv):
    if len(argv) != 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    path = argv[2]
    raw = open(path, "rb").read()
    text = raw.decode("utf-8")
    if "\r\n" in text:
        print("CRLF in " + path + " - normalise it first; LF anchors would miss")
        return 1
    rows = survey(text)
    for name, state, n in rows:
        print(f"  {name:5} {state}" + (f" (anchor count {n})" if state == "missing" else ""))
    if any(state == "missing" for _, state, _ in rows):
        return 1
    if all(state == "applied" for _, state, _ in rows):
        return 2
    if argv[1] == "--check":
        return 0
    for (name, old, new, mark), (_, state, _) in zip(EDITS, rows):
        if state != "ready":
            continue
        assert text.count(old) == 1, name
        text = text.replace(old, new, 1)
        assert mark in text, name
    ast.parse(text)
    print("ast.parse: ok")
    if not node_check(text):
        return 1
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)),
                               prefix=".model_pull.", suffix=".tmp")
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    shutil.copymode(path, tmp)
    os.replace(tmp, path)
    print("applied: " + ", ".join(name for name, state, _ in rows if state == "ready"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
