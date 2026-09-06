"""Measured resource decisions; never infer memory pressure from missing data."""
from __future__ import annotations

import json
import math
import subprocess
import time
from pathlib import Path


def available_gb(pressure: dict) -> float | None:
    try:
        value = float(pressure["avail_gb"])
        return value if math.isfinite(value) and value >= 0 else None
    except (KeyError, TypeError, ValueError):
        return None


def memory_snapshot(path: Path = Path("/proc/meminfo")) -> dict:
    try:
        fields = {line.split(":", 1)[0]: int(line.split()[1]) * 1024
                  for line in path.read_text().splitlines() if ":" in line}
        return {"total_gb": round(fields["MemTotal"] / 1024**3, 2),
                "avail_gb": round(fields["MemAvailable"] / 1024**3, 2),
                "source": "/proc/meminfo (host unified memory)"}
    except (OSError, KeyError, ValueError, IndexError):
        return {"avail_gb": None, "source": "unavailable"}


def gpu_snapshot() -> dict:
    fields = ("name", "utilization_percent", "temperature_c", "power_watts",
              "dedicated_memory_used_mib", "dedicated_memory_total_mib")
    result = {field: None for field in fields}
    result.update({"at": time.time(), "memory_model": "host unified memory"})
    try:
        output = subprocess.run([
            "nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total",
            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3, check=True)
        values = output.stdout.strip().splitlines()[0].split(",")
        result["name"] = values[0].strip()
        for field, value in zip(fields[1:], values[1:]):
            try:
                number = float(value.strip())
                result[field] = number if math.isfinite(number) else None
            except ValueError:
                pass                    # GB10 legitimately reports N/A for dedicated VRAM
        result["observed"] = True
    except (OSError, subprocess.SubprocessError, IndexError):
        result["observed"] = False
    return result


def engine_busy(engine: str, booths: dict, recent: dict | None = None) -> bool:
    # Live jobs do not yet expose their engine: protect all engines while any
    # live render exists. Shared preparation likewise has unknown ownership.
    by = booths.get("engines") or {}
    if booths.get("live") or by.get("shared") or by.get(engine):
        return True
    if booths.get("preparing") and not by:
        return True
    try:
        age = (recent or {}).get(engine)
        return age is not None and float(age) < 60
    except (TypeError, ValueError):
        return True


def assess(snapshot: dict, pressure_samples: int = 0) -> dict:
    available = available_gb(snapshot.get("memory") or {})
    tier = ("unknown" if available is None else "critical" if available < 12
            else "pressure" if available < 24 else "healthy")
    actions, questions = [], []
    if tier == "healthy":
        reason = "Memory has headroom; keep working models resident and let admitted jobs finish."
    elif tier == "unknown":
        reason = "Memory telemetry is unavailable; repair observation before making memory-based unload decisions."
    else:
        reason = "Memory is constrained; protect active recordings and writers, then consider known idle caches."
        comfy = snapshot.get("comfy") or {}
        if (pressure_samples >= 2 and comfy.get("observed") and not comfy.get("busy")
                and float(comfy.get("idle_seconds") or 0) >= 300):
            actions.append({"kind": "free_comfy_cache", "reason":
                            "Two low-memory samples and an empty image queue with five minutes idle."})
        if not actions:
            questions.append("If pressure persists after active jobs finish, which non-station workload may be paused?")
    writing = snapshot.get("writing") or {}
    if writing.get("waiting"):
        reason += " Writer queueing is measured separately from GPU execution time; avoid adding duplicate work."
    return {"tier": tier, "reason": reason, "actions": actions, "questions": questions,
            "protected": ["active or queued writers", "active recording engines",
                          "selected cast engine while FM is on", "shared embedding model",
                          "Home Assistant, microphones, and unrelated services"]}


class ResourceHistory:
    """Bounded atomic evidence, retained through restarts and hour reflection."""
    MAX_SAMPLES = 120

    def __init__(self, path: Path):
        self.path = path
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            self.rows = rows[-self.MAX_SAMPLES:] if isinstance(rows, list) else []
        except (OSError, ValueError):
            self.rows = []

    def record(self, snapshot: dict, decision: dict, action: dict | None = None) -> dict:
        row = {"at": time.time(), "memory": snapshot.get("memory"),
               "gpu": snapshot.get("gpu"), "writing": snapshot.get("writing"),
               "booths": snapshot.get("booths"), "models": snapshot.get("models"),
               "comfy": snapshot.get("comfy"),
               "engines_last_render_seconds": snapshot.get("engines_last_render_seconds"),
               "decision": decision, "action": action}
        self.rows.append(row)
        self.rows = self.rows[-self.MAX_SAMPLES:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        pending = self.path.with_suffix(".tmp")
        pending.write_text(json.dumps(self.rows, ensure_ascii=False), encoding="utf-8")
        pending.replace(self.path)
        return row
