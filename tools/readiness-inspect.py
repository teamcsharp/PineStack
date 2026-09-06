"""Read-only comparison of live prepared inventory and its persisted takes."""
import json
import os
from collections import Counter
from pathlib import Path

import httpx


def main():
    key = os.environ.get("SPARK_AGENT_API_KEY", "")
    headers = {"Authorization": "Bearer " + key} if key else {}
    report = {}
    with httpx.Client(base_url="http://127.0.0.1:8096", headers=headers, timeout=60) as client:
        for path in ("/api/radio/pause", "/api/pantry/table?most=1", "/api/dj/pending", "/api/recording-room"):
            data = client.get(path).json()
            if path == "/api/dj/pending":
                report[path] = {"buffered_seconds": data.get("buffered_seconds"),
                               "pantry_clips": data.get("pantry_clips"),
                               "pending": [{k: r.get(k) for k in
                                            ("id", "state", "chunks", "made", "seconds", "use", "kind", "tint_revalidation")}
                                           for r in data.get("pending") or []]}
            elif path == "/api/recording-room":
                report[path] = {k: data.get(k) for k in ("shelf", "booths", "kinds", "preparing", "tint_recovery")}
            else:
                report[path] = {k: v for k, v in data.items() if k != "rows"}
    root = Path(os.environ.get("SPARK_AGENT_DATA_DIR", "/app/data"))
    pantry = json.loads((root / "pantry.json").read_text())
    shelf = json.loads((root / "prep_shelf.json").read_text())
    larder = json.loads((root / "larder.json").read_text())
    report["disk_pantry"] = {"rows": len(pantry),
        "seconds": round(sum(float((r.get("clip") or {}).get("seconds") or 0) for r in pantry.values()), 2),
        "files_exist": sum((root / "voice_media" / str((r.get("clip") or {}).get("path") or "").split("?")[0].rsplit("/", 1)[-1]).is_file() for r in pantry.values())}
    report["disk_shelf"] = {}
    for kind, rows in {**shelf, "larder": larder}.items():
        states, examples = Counter(), []
        seconds = 0.0
        for row in rows:
            entry = row.get("entry") or row
            coverage = (entry.get("tint") or {}).get("coverage") or {}
            keys = set(entry.get("keys") or []) | {str(t.get("key")) for t in entry.get("takes") or [] if t.get("key")}
            if entry.get("key"):
                keys.add(entry["key"])
            present = sum(k in pantry for k in keys)
            states["prepared_flag"] += bool(entry.get("prepared"))
            states["partial_flag"] += bool(entry.get("partial"))
            states["off_brief"] += bool(entry.get("off_brief") or row.get("off_brief"))
            states["made_ge_chunks"] += bool(entry.get("chunks") and int(entry.get("made") or 0) >= int(entry["chunks"]))
            states["tint_met"] += bool(coverage.get("met"))
            states["all_keys_present"] += bool(keys) and present == len(keys)
            seconds += sum(float((pantry[k].get("clip") or {}).get("seconds") or 0) for k in keys if k in pantry)
            if len(examples) < 2:
                examples.append({k: entry.get(k) for k in
                                 ("at", "chunks", "made", "prepared", "partial", "use", "seconds", "missing_voice_chunks", "yielded")}
                                | {"keys": len(keys), "keys_present": present,
                                   "coverage": coverage, "profile": entry.get("profile")})
        report["disk_shelf"][kind] = {"rows": len(rows), "states": dict(states),
                                     "referenced_audio_seconds": round(seconds, 2), "examples": examples}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
