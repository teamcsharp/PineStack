"""Inspect copied station inventory with System2; never start providers or play.

Run inside the agent container. All mutable state goes into a temporary directory;
existing audio is opened only by the media proof reader.
"""
import asyncio
import collections
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time


original = Path(os.environ.get("SPARK_AGENT_DATA_DIR", "/app/data"))
started = time.time()
with tempfile.TemporaryDirectory(prefix="system2-inventory-") as directory:
    target = Path(directory)
    names = ("settings.json", "crystals.json", "crystal_notes.json", "schedule.json", "plot.json",
             "larder.json", "pantry.json", "prep_shelf.json", "track_talk_queue.json", "cast.json", "ads.json")
    inputs = {}
    for name in names:
        source = original / name
        if source.is_file():
            raw = source.read_bytes()
            (target / name).write_bytes(raw)
            inputs[name] = hashlib.sha256(raw).hexdigest()
    os.environ["SPARK_AGENT_DATA_DIR"] = directory
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import app
    app.VOICE_MEDIA_DIR = original / "voice_media"
    app.PRODUCED_ADS_DIR = original / "ads_audio"
    # Copy the durable queues exactly. The ordinary loader also grooms and
    # regrades them; this audit explicitly measures only the new adapter.
    for name, destination in (("pantry.json", app._PANTRY), ("prep_shelf.json", app._SHELF),
                              ("track_talk_queue.json", app._TRACK_TALK)):
        if (target / name).is_file():
            destination.update(json.loads((target / name).read_text()))
    if (target / "larder.json").is_file():
        app._LARDER[:] = json.loads((target / "larder.json").read_text())
    runtime = app._system2()
    # No provider calls, no startup tasks, no settings or playout mutations.
    state = asyncio.run(runtime.refresh(force=True))
    groups = collections.defaultdict(lambda: {"total": 0, "ready": 0, "seconds": 0, "reasons": collections.Counter()})
    entries = []
    for candidate in runtime._candidates:
        group = groups[candidate["kind"]]
        group["total"] += 1
        group["ready"] += candidate["ready"]
        group["seconds"] += candidate["seconds"] if candidate["ready"] else 0
        group["reasons"].update(candidate["why"])
        entries.append({key: candidate.get(key) for key in ("id", "kind", "ready", "eligible", "seconds", "why", "expires_at")})
    report = {"started": started, "finished": time.time(), "isolated_state": True,
              "provider_calls": 0, "plays": 0, "input_sha256": inputs,
              "groups": dict(groups), "candidates": entries,
              "plans": [{"id": hour["id"], "ready_seconds": hour["ready_seconds"],
                         "debt_seconds": hour["debt_seconds"],
                         "slots": [{k: slot.get(k) for k in ("id", "kind", "label", "start", "deadline",
                                   "ready_seconds", "debt_seconds", "status", "target_seconds")} for slot in hour["slots"]]}
                        for hour in state["hours"]], "errors": state["errors"]}
Path("docs/system2-inventory-snapshot.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"seconds": report["finished"] - started, "groups": report["groups"], "errors": report["errors"]}, indent=2))
