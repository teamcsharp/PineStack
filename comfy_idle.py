"""comfy_idle — the ComfyUI idle policy, as a dial with its price on it.  [#1196]

    "So there are hours and hours and hours in which I am not using comfy UI.
     We might need to try a situation where we offload it from memory so that
     it can be more efficient during those times."

WHAT WAS MEASURED BEFORE ANY OF THIS WAS WRITTEN (lilspark, 2026-09-21, the
numbers in SEED below):

  ComfyUI AT REST, models unloaded:      351 MiB GPU + 648 MB anon = 0.97 GB
  ComfyUI HOLDING the last workflow:  19,935 MiB GPU + 20.9 GB anon = 39.9 GB
  What one POST /free gave back:      MemAvailable 30.6 G -> 71.2 G = 40.6 GB
  A render with the cache warm:                21.4 s and 19.8 s  (median 20.6)
  A render with the cache cold:                37.1 s and 36.6 s  (median 36.9)
  So the price of an unload, on the next picture only:            +16.3 s
  A whole-process restart through the comfyui-kick bridge:  14.0 s to the API,
  and the first render after that restart:                  36.2 s - the same
  as after a plain /free, so the restart buys nothing and costs 14 s.

TWO CONCLUSIONS, AND THEY POINT OPPOSITE WAYS.

  1. Stopping the PROCESS buys 0.97 GB of a 127.6 GB box - 0.76%. "Offload
     ComfyUI from memory" is, at rest, worth almost nothing, and the repeated
     "tier1: ComfyUI cache freed" line the operator was reading was written
     while the box had 66.7 GB free. It was never the hog.
  2. But ComfyUI holding a finished workflow is 40 GB, and on 2026-09-21 it
     held exactly that for twenty minutes with no clock about to take it:
     the host valve only acts under pressure, the cron waits two hours, and
     the station's own idle clock could not see a render it had not made.
     THAT is the thing worth a policy.

So the dial is real, its default acts on the 40 GB and not on the 0.97 GB,
and every screen that shows it shows the price beside it.

THE MODES
  off   never unload automatically. The operator pays nothing and keeps the
        40 GB resident between pictures.
  free  POST /free {unload_models, free_memory}. Gives back ~40.6 GB, costs
        ~16.3 s on the next picture only. This is the default.
  stop  ALSO stop the process. Buys 0.97 GB more than `free` and costs the
        14 s restart on top of the cold render. It needs a host bridge
        (data/comfy_power, a companion to comfyui-kick.path); where that
        bridge is not installed the flag file is never consumed, and this
        module says so out loud rather than pretending the stop happened.

Nothing in here talks to ComfyUI or to the network; the caller does the
HTTP and hands the outcome back. That keeps it importable and testable
with no station and no engine.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

MODES = ("off", "free", "stop")
FILENAME = "comfy_idle.json"
POWER_FILENAME = "comfy_power"
LOG_CAP = 40
RENDER_CAP = 40
MIN_MINUTES = 1
MAX_MINUTES = 720

# Measured on lilspark, 2026-09-21, with the probes named in the docstring.
# These are the fallback prices: as soon as the station has timed two cold
# and two warm renders of its own, prices() prefers those and says so.
SEED: dict[str, Any] = {
    "at": "2026-09-21T21:10-06:00",
    "rest_gpu_mib": 351,
    "rest_anon_mb": 648,
    "rest_gb": 0.97,
    "loaded_gpu_mib": 19935,
    "loaded_anon_mb": 20951,
    "loaded_gb": 39.9,
    "free_gives_back_gb": 40.6,
    "cold_s": 36.9,
    "warm_s": 20.6,
    "penalty_s": 16.3,
    "restart_to_api_s": 14.0,
    "restart_first_render_s": 36.2,
    "box_total_gb": 127.6,
    "how": "two cold and two warm z-image renders at 8 steps, nvidia-smi "
           "per-process MiB plus RssAnon, MemAvailable either side of a "
           "POST /free, and one restart through the comfyui-kick bridge",
}

DEFAULTS: dict[str, Any] = {
    "minutes": 15,
    "mode": "free",
    "updated": 0.0,
    "by": "",
}


def path_for(data_dir: str | os.PathLike[str]) -> Path:
    return Path(data_dir) / FILENAME


def power_path(data_dir: str | os.PathLike[str]) -> Path:
    return Path(data_dir) / POWER_FILENAME


def _blank() -> dict[str, Any]:
    doc = dict(DEFAULTS)
    doc["seed"] = dict(SEED)
    doc["log"] = []
    doc["renders"] = []
    return doc


def clamp_minutes(value: Any, fallback: int = 15) -> int:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return fallback
    return max(MIN_MINUTES, min(MAX_MINUTES, n))


def clean_mode(value: Any, fallback: str = "free") -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in MODES else fallback


def read(data_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """The policy as stored, with every key present and sane."""
    doc = _blank()
    try:
        raw = json.loads(path_for(data_dir).read_text(encoding="utf-8"))
    except Exception:                                      # noqa: BLE001
        raw = {}
    if isinstance(raw, dict):
        doc["minutes"] = clamp_minutes(raw.get("minutes"), DEFAULTS["minutes"])
        doc["mode"] = clean_mode(raw.get("mode"), DEFAULTS["mode"])
        try:
            doc["updated"] = float(raw.get("updated") or 0.0)
        except (TypeError, ValueError):
            doc["updated"] = 0.0
        doc["by"] = str(raw.get("by") or "")
        if isinstance(raw.get("log"), list):
            doc["log"] = [r for r in raw["log"] if isinstance(r, dict)][-LOG_CAP:]
        if isinstance(raw.get("renders"), list):
            doc["renders"] = [r for r in raw["renders"]
                              if isinstance(r, dict)][-RENDER_CAP:]
    return doc


def write(data_dir: str | os.PathLike[str], doc: dict[str, Any]) -> dict[str, Any]:
    """Atomic; a half-written policy must never be readable."""
    target = path_for(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(doc, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(prefix=".comfy-idle-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, target)
    except Exception:                                      # noqa: BLE001
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return doc


def set_policy(data_dir: str | os.PathLike[str], minutes: Any = None,
               mode: Any = None, by: str = "") -> dict[str, Any]:
    doc = read(data_dir)
    if minutes is not None:
        doc["minutes"] = clamp_minutes(minutes, doc["minutes"])
    if mode is not None:
        doc["mode"] = clean_mode(mode, doc["mode"])
    doc["updated"] = time.time()
    doc["by"] = str(by or doc.get("by") or "")
    return write(data_dir, doc)


def note_unload(data_dir: str | os.PathLike[str], *, mode: str, idle_s: float,
                before_gb: float | None, after_gb: float | None,
                ok: bool, why: str = "") -> dict[str, Any]:
    """Record one unload. `before_gb`/`after_gb` are host MemAvailable, which
    is the only number that answers "what did the offload actually buy"."""
    doc = read(data_dir)
    freed = (round(after_gb - before_gb, 1)
             if before_gb is not None and after_gb is not None else None)
    doc["log"] = (doc.get("log") or []) + [{
        "at": time.time(),
        "mode": clean_mode(mode, "free"),
        "idle_minutes": round(max(0.0, float(idle_s)) / 60.0, 1),
        "before_gb": None if before_gb is None else round(before_gb, 1),
        "after_gb": None if after_gb is None else round(after_gb, 1),
        "freed_gb": freed,
        "ok": bool(ok),
        "why": str(why or ""),
    }][-LOG_CAP:]
    return write(data_dir, doc)


def note_render(data_dir: str | os.PathLike[str], seconds: float,
                cold: bool) -> dict[str, Any]:
    """One finished picture, and whether it was the first after an unload.

    This is what turns the seeded price into a measured one: the station
    times its own renders anyway (stats.duration_s), so the only new fact
    needed is which side of an unload each one fell."""
    try:
        secs = round(float(seconds), 1)
    except (TypeError, ValueError):
        return read(data_dir)
    if secs <= 0:
        return read(data_dir)
    doc = read(data_dir)
    doc["renders"] = (doc.get("renders") or []) + [
        {"at": time.time(), "seconds": secs, "cold": bool(cold)}][-RENDER_CAP:]
    return write(data_dir, doc)


def _median(values: list[float]) -> float | None:
    rows = sorted(v for v in values if isinstance(v, (int, float)) and v > 0)
    if not rows:
        return None
    mid = len(rows) // 2
    if len(rows) % 2:
        return round(float(rows[mid]), 1)
    return round((float(rows[mid - 1]) + float(rows[mid])) / 2.0, 1)


def prices(doc: dict[str, Any]) -> dict[str, Any]:
    """What an unload costs, preferring this box's own renders over the seed.

    A price nobody measured is not a price, so `source` always says which
    it is and `samples` says how many pictures it rests on."""
    seed = dict(SEED)
    renders = [r for r in (doc.get("renders") or []) if isinstance(r, dict)]
    cold = [float(r.get("seconds") or 0) for r in renders if r.get("cold")]
    warm = [float(r.get("seconds") or 0) for r in renders if not r.get("cold")]
    cold_s = _median(cold) if len(cold) >= 2 else None
    warm_s = _median(warm) if len(warm) >= 2 else None
    if cold_s is not None and warm_s is not None:
        return {"cold_s": cold_s, "warm_s": warm_s,
                "penalty_s": round(cold_s - warm_s, 1),
                "samples": {"cold": len(cold), "warm": len(warm)},
                "source": "measured here, from this station's own pictures",
                "seed": seed}
    return {"cold_s": seed["cold_s"], "warm_s": seed["warm_s"],
            "penalty_s": seed["penalty_s"],
            "samples": {"cold": len(cold), "warm": len(warm)},
            "source": ("measured on this box 2026-09-21 by hand; the station "
                       "needs two cold and two warm pictures of its own "
                       "before it can quote its own numbers"),
            "seed": seed}


def host_available_gb() -> float | None:
    """MemAvailable of the WHOLE BOX, in GB.

    Docker does not namespace /proc/meminfo, so the container reads the
    host's figure here - verified 2026-09-21, container and host both
    reported MemAvailable 31264804 kB in the same second. On unified
    memory this one number covers GPU and CPU alike, which is exactly
    why no gauge can name a tenant: only the delta across an action can."""
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return round(int(line.split()[1]) / 1048576.0, 1)
    except Exception:                                      # noqa: BLE001
        return None
    return None


def offer(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The three modes with their prices, for a screen to lay out."""
    p = prices(doc)
    seed = p["seed"]
    return [
        {"mode": "off", "label": "leave it loaded",
         "buys_gb": 0.0,
         "costs": "nothing on the next picture; the last workflow stays "
                  "resident, which measured %.0f GB here" % seed["loaded_gb"]},
        {"mode": "free", "label": "free its models",
         "buys_gb": seed["free_gives_back_gb"],
         "costs": "about %.0f seconds more on the next picture only "
                  "(%.0f cold against %.0f warm)"
                  % (p["penalty_s"], p["cold_s"], p["warm_s"])},
        {"mode": "stop", "label": "stop the whole engine",
         "buys_gb": round(seed["free_gives_back_gb"] + seed["rest_gb"], 1),
         "costs": "only %.2f GB more than freeing its models, and it adds "
                  "the %.0f second restart on top of the cold picture; it "
                  "also needs the host power bridge"
                  % (seed["rest_gb"], seed["restart_to_api_s"])},
    ]


def explain(doc: dict[str, Any], live: dict[str, Any] | None = None) -> str:
    """Plain words for the console, composed once so no two screens differ."""
    live = live or {}
    p = prices(doc)
    seed = p["seed"]
    mode = doc.get("mode") or "free"
    minutes = doc.get("minutes") or 15
    if mode == "off":
        head = ("ComfyUI is never unloaded automatically - you asked for it "
                "to stay loaded.")
    elif mode == "stop":
        head = ("After %d quiet minutes ComfyUI's models are freed and the "
                "engine itself is stopped." % minutes)
    else:
        head = ("After %d quiet minutes ComfyUI's models are freed; the "
                "engine stays up." % minutes)
    size = ("At rest it holds about %.1f GB of the box's %.0f GB - under one "
            "percent - so stopping it outright is not where the memory is. "
            "Holding a finished workflow it measured %.0f GB, and that is "
            "what this unloads." % (seed["rest_gb"], seed["box_total_gb"],
                                    seed["loaded_gb"]))
    price = ("The price is about %.0f seconds on the first picture "
             "afterwards: %.0f cold against %.0f warm (%s)."
             % (p["penalty_s"], p["cold_s"], p["warm_s"], p["source"]))
    tail = ""
    if live.get("idle_seconds") is not None and mode != "off":
        idle_m = float(live["idle_seconds"]) / 60.0
        if live.get("busy"):
            tail = " It is rendering now, so nothing will be unloaded."
        elif idle_m >= float(minutes):
            tail = " It has been quiet %.0f minutes and is due." % idle_m
        else:
            tail = (" It has been quiet %.0f of the %d minutes."
                    % (idle_m, minutes))
    elif not live.get("up", True):
        tail = " The engine is not answering right now."
    return " ".join(x for x in (head, size, price, tail.strip()) if x)
