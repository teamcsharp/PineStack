"""Read existing recording metadata and authenticated read-only summaries.

No app import, scripts, secrets, model calls, recordings or playback. Outputs
aggregate counts; disk flags are persisted evidence, not live task ownership.
"""
from collections import Counter
import json
import os
from pathlib import Path
import time
import urllib.request


def read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def main():
    data = Path(os.environ.get("SPARK_AGENT_DATA_DIR", "/app/data"))
    shelf = read(data / "prep_shelf.json", {})
    larder = read(data / "larder.json", [])
    groups = {str(kind): rows for kind, rows in shelf.items() if isinstance(rows, list)}
    groups["banter_larder"] = larder if isinstance(larder, list) else []
    report = {"at": time.time(), "disk": {}, "live": {}}
    for kind, rows in groups.items():
        counts = Counter()
        waits = Counter()
        for row in rows:
            if not isinstance(row, dict):
                continue
            entry = row.get("entry") if isinstance(row.get("entry"), dict) else row
            counts["rows"] += 1
            for key in ("prepared", "preparing", "tinting", "partial", "off_brief", "discarded", "review_recovery_pending"):
                counts[key] += bool(entry.get(key))
            counts["has_audio_refs"] += bool(entry.get("key") or entry.get("keys") or entry.get("takes") or row.get("key"))
            counts["declared_missing_voices"] += bool(entry.get("missing_voice_chunks"))
            counts["known_failed_lines"] += sum(bool(value) for value in (entry.get("bad") or {}).values())
            counts["full_audio_metadata"] += bool(entry.get("chunks") and int(entry.get("made") or 0) >= int(entry.get("chunks") or 0))
            tint = entry.get("tint") or {}
            coverage = tint.get("coverage") or {}
            counts["tint_ok_metadata"] += bool(tint.get("ok") or entry.get("tint_ok"))
            counts["coverage_v4"] += int(coverage.get("version") or 0) >= 4
            counts["active_tinted_script"] += bool(entry.get("script_tinted") and entry.get("script") == entry.get("script_tinted"))
            tried = float(entry.get("tint_tried") or entry.get("tint_failed_at") or 0)
            counts["recent_tint_failure_120s"] += bool(tried and time.time() - tried < 120)
            if entry.get("yielded"):
                waits[str(entry["yielded"])[:120]] += 1
        report["disk"][kind] = {"counts": dict(counts), "yielded": dict(waits)}
    key = os.environ.get("SPARK_AGENT_API_KEY", "")
    if key:
        for endpoint in ("/api/recording-room", "/api/orchestrator/rejections/context"):
            try:
                request = urllib.request.Request("http://127.0.0.1:8096" + endpoint,
                                                 headers={"Authorization": "Bearer " + key})
                with urllib.request.urlopen(request, timeout=20) as response:
                    value = json.load(response)
                if endpoint.endswith("/context"):
                    report["live"][endpoint] = {name: value.get(name) for name in ("recording", "tint")}
                else:
                    report["live"][endpoint] = {name: value[name] for name in ("prepared", "waiting", "engines", "booths", "capacity", "rendering") if name in value}
                    writers = value.get("writers") or {}
                    jobs = writers.get("jobs") or []
                    report["live"][endpoint]["writer_jobs"] = dict(Counter(
                        str(row.get("state") or "unknown") + ":" + str(row.get("purpose") or "unknown")
                        for row in jobs if isinstance(row, dict)))
            except Exception as exc:
                report["live"][endpoint] = {"unavailable": type(exc).__name__}
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
