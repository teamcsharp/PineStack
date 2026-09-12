"""Read-only deployed Nabu mix snapshot; run inside the station container."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import time
import urllib.request


def get(path):
    request = urllib.request.Request("http://127.0.0.1:8096" + path,
        headers={"Authorization": "Bearer " + os.environ["SPARK_AGENT_API_KEY"]})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except Exception as exc:
        return {"error": type(exc).__name__}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/nabu-mix-live-observation.json")
    args = parser.parse_args()
    paths = ["/api/dj", "/api/settings", "/api/pinebox/speaker", "/api/pinebox/status"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        raw = dict(zip(paths, pool.map(get, paths)))
    settings = raw["/api/settings"].get("dj") or {}
    station = raw["/api/dj"]
    report = {"at": time.time(), "read_only": True,
        "errors": {path: data["error"] for path, data in raw.items() if data.get("error")},
        "settings": {name: settings.get(name) for name in (
            "nabu_music_level", "nabu_voice_level", "nabu_reply_level", "music_box_level")},
        "station": {name: station.get(name) for name in (
            "on", "paused", "voice_to", "voice_device", "music_to", "reply_to", "box_talk")},
        "speaker": [{name: entity.get(name) for name in (
            "entity_id", "state", "volume_level", "volume_percent", "muted")}
            for entity in raw["/api/pinebox/speaker"].get("entities", [])
            if "09f8a8" in entity.get("entity_id", "")],
        "delivery": raw["/api/pinebox/status"].get("delivery"),
        "limits": "Read-only configuration and state evidence; no playback, volume, model, or route commands. HA state does not prove acoustic output."}
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
