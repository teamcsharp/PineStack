"""Observe normal SFX preparation/playback without commissioning or playing anything.

Run only after deployment authorization, inside the station container. Every
HTTP request is GET; SQLite/media/source files are opened read-only. The only
writes are this observer's JSON and Markdown evidence files.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import urllib.request
import wave


ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("SPARK_AGENT_DATA_DIR", str(ROOT / "data")))
BASE = "http://127.0.0.1:8096"
COUNTERS = ("heard_units", "heard_samples", "sample_due", "sample_omitted",
            "guy_due", "guy_omitted")


def get(path):
    request = urllib.request.Request(BASE + path, method="GET", headers={
        "Authorization": "Bearer " + os.environ["SPARK_AGENT_API_KEY"]})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return json.load(response)
    except Exception as exc:
        return {"error": type(exc).__name__, "status": getattr(exc, "code", None)}


def pick(row, keys):
    return {key: row.get(key) for key in keys if key in row}


def receipts(after=0):
    path = DATA / "sfx_cadence.sqlite3"
    if not path.exists():
        return {"cursor": 0, "rows": [], "absent": True}
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            cursor = db.execute("SELECT COALESCE(MAX(rowid),0) FROM receipts").fetchone()[0]
            rows = db.execute("SELECT rowid,id,units,sample FROM receipts WHERE rowid>? AND rowid<=? ORDER BY rowid LIMIT 5000",
                              (after, cursor)).fetchall() if after >= 0 else []
        return {"cursor": cursor, "rows": [dict(zip(("seq", "id", "units", "sample"), row)) for row in rows]}
    except Exception as exc:
        return {"error": type(exc).__name__, "cursor": after, "rows": []}


def bank_evidence(status):
    """Retain exact short source/wording and stored proof; never run a grader."""
    try:
        stored = json.loads((DATA / "sfxguy_speech.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"rows": [], "absent": True}
    except Exception as exc:
        return {"rows": [], "error": type(exc).__name__}
    visible = {row.get("id") for row in status.get("rows", [])}
    out = []
    for identity, row in stored.items():
        if identity not in visible:
            continue
        proof = pick(row, ("id", "who", "voice", "profile", "state", "why", "attempts",
            "retry_at", "last_attempt", "plays", "last_played", "reserved_until", "generic",
            "text_plain", "text", "tint_ok", "tint", "tint_text_hash", "key", "engine",
            "recorded_text", "recorded_voice", "seconds", "errors"))
        text = str(row.get("text") or "")
        proof["text_hash_matches"] = row.get("tint_text_hash") == hashlib.sha256(text.encode()).hexdigest()
        proof["recorded_text_matches"] = row.get("recorded_text") == text
        proof["recorded_voice_matches"] = row.get("recorded_voice") == row.get("voice")
        clip = row.get("clip") or {}
        name = str(clip.get("path") or "").split("?", 1)[0].rsplit("/", 1)[-1]
        media = DATA / "voice_media" / name
        if name and name not in (".", "..") and media.is_file():
            proof["media"] = {"name": name, "bytes": media.stat().st_size,
                "sha256": hashlib.sha256(media.read_bytes()).hexdigest(),
                "saved_seconds": clip.get("seconds")}
            try:
                with wave.open(str(media), "rb") as audio:
                    proof["media"].update(wav_seconds=round(audio.getnframes() / audio.getframerate(), 4),
                        sample_rate=audio.getframerate(), channels=audio.getnchannels())
            except (OSError, wave.Error, EOFError) as exc:
                proof["media"]["wave_error"] = type(exc).__name__
        elif name:
            proof["media"] = {"name": name, "missing": True}
        out.append(proof)
    return {"rows": out, "validation_basis": "GET speech_bank.ready is the production current-profile validator; stored proof and WAV metadata below are read independently, with no grader/model call."}


def snapshot(with_pipeline=False):
    paths = ["/api/dj", "/api/sfxguy/quips", "/api/sfx/stats", "/api/sfx/history?limit=200"]
    if with_pipeline:
        paths.append("/api/orchestrator/logic")
    at = time.time()
    with ThreadPoolExecutor(max_workers=5) as pool:
        raw = dict(zip(paths, pool.map(get, paths)))
    station = raw[paths[0]]
    bank = raw[paths[1]].get("speech_bank") or {}
    chat = []
    for row in station.get("chat") or []:
        item = pick(row, ("id", "who", "voice", "ts", "air_at", "heard", "delivery",
            "state", "kind", "played", "clip_from", "clip_until", "sfx_sample_id"))
        item["text_sha256"] = hashlib.sha256(str(row.get("text") or "").encode()).hexdigest()
        if row.get("who") == "drop":
            item["text"] = row.get("text")
        chat.append(item)
    history = raw[paths[3]]
    pipeline = (raw.get("/api/orchestrator/logic") or {}).get("pipeline") or {}
    return {"at": at, "completed_at": time.time(),
        "errors": {path: pick(data, ("error", "status")) for path, data in raw.items() if data.get("error")},
        "station": pick(station, ("on", "paused", "speaking", "voice_to", "voice_device", "music_to",
            "reply_to", "box_talk", "box", "stream_now", "pulse", "activity")),
        "chat": chat, "bank": bank, "cadence": raw[paths[2]].get("cadence") or {},
        "sfx_history": {"total": history.get("total"), "distinct": history.get("distinct"),
            "pool": history.get("pool"), "rows": [pick(row, ("id", "at", "ts", "who", "name", "plays"))
                                                        for row in history.get("rows", [])]},
        "pipeline": pick(pipeline, ("at", "total", "stages", "roads", "writers", "booths", "bottleneck",
            "recording_waiting", "tint_waiting"))}


def summarize(report):
    frames = report["snapshots"]
    first, last = frames[0], frames[-1]
    deltas, resets = {}, []
    for key in COUNTERS:
        before, after = first["cadence"].get(key), last["cadence"].get(key)
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            deltas[key] = after - before
            if after < before:
                resets.append(key)
    bank_keys = ("total", "ready", "waiting", "suspended", "reserved", "heard", "why")
    bank_first, bank_last = pick(first["bank"], bank_keys), pick(last["bank"], bank_keys)
    heard = bank_last.get("heard", 0) - bank_first.get("heard", 0)
    new_receipts = report.get("audible_receipts", {}).get("rows", [])
    return {"seconds": round(last["completed_at"] - first["at"], 3), "snapshots": len(frames),
        "bank_before": bank_first, "bank_after": bank_last, "bank_heard_delta": heard,
        "cadence_before": first["cadence"], "cadence_after": last["cadence"],
        "cadence_deltas": deltas, "counter_resets": resets,
        "new_durable_receipts": len(new_receipts),
        "new_durable_host_units": sum(row["units"] for row in new_receipts),
        "new_durable_sample_receipts": sum(bool(row["sample"]) for row in new_receipts),
        "api_error_snapshots": sum(bool(frame["errors"]) for frame in frames),
        "station_before": pick(first["station"], ("on", "paused", "voice_to", "voice_device", "box")),
        "station_after": pick(last["station"], ("on", "paused", "voice_to", "voice_device", "box")),
        "pipeline_before": first["pipeline"],
        "pipeline_after": next((frame["pipeline"] for frame in reversed(frames) if frame["pipeline"]), {}),
        "observed_bank_reasons": sorted({str(frame["bank"].get("why")) for frame in frames if frame["bank"].get("why")}),
        "limits": ["Due/omitted counters describe planning in the current process, not audible delivery.",
            "Heard counters and durable receipts use production playback acknowledgements; no microphone or acoustic measurement was made.",
            "A sampled chat row can be prepared or held; it is not proof of being heard.",
            "Bank totals apply to the current voice/profile. A profile change or restart can invalidate simple deltas.",
            "This short observation cannot establish sustained preparation throughput or station-wide audio quality."]}


def save(report, path):
    report["summary"] = summarize(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    summary = report["summary"]
    body = ["# SFX broadcast observation", "", "Read-only observation of the normal deployed station. No model, TTS, playback, route, or volume requests were issued.", "",
        f"Observed {summary['seconds']} seconds in {summary['snapshots']} snapshots. Completion: {report['state']}.", "",
        f"Bank before: `{json.dumps(summary['bank_before'], ensure_ascii=False)}`.", "",
        f"Bank after: `{json.dumps(summary['bank_after'], ensure_ascii=False)}`.", "",
        f"Cadence deltas: `{json.dumps(summary['cadence_deltas'])}`. New durable host receipts: {summary['new_durable_host_units']}; sample receipts: {summary['new_durable_sample_receipts']}; bank heard delta: {summary['bank_heard_delta']}.", "",
        "Preparation reasons: " + "; ".join(summary["observed_bank_reasons"]), "",
        f"[Exact snapshots, saved proof and receipts]({path.name}).", "", *["- " + item for item in summary["limits"]], ""]
    path.with_suffix(".md").write_text("\n".join(body), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Explicitly start the authorized read-only observation")
    parser.add_argument("--seconds", type=int, default=240, choices=range(180, 301), metavar="180..300")
    parser.add_argument("--interval", type=int, default=10, choices=range(5, 31), metavar="5..30")
    parser.add_argument("--output", default="docs/sfx-broadcast-observation.json")
    args = parser.parse_args()
    if not args.run:
        parser.exit(message="Prepared only. Await deployment authorization, then pass --run.\n")
    path = Path(args.output)
    if not path.is_absolute():
        path = ROOT / path
    if path.exists():
        parser.error("Output already exists; choose a new evidence path rather than overwrite a completed observation")
    settings = (get("/api/settings").get("dj") or {})
    initial = receipts(-1)
    report = {"started_at": time.time(), "state": "observing", "read_only": True,
        "requests": "GET only; no listener registration, media downloads, models, TTS, controls, votes or playback",
        "configuration": pick(settings, ("sfx", "sfx_rate", "sfx_every_units", "sfx_max_seconds", "sfxguy_rate",
            "sfx_folders", "sfx_drop_folders", "sfx_rescan_seconds",
            "sfxguy_every_units", "drop_voice", "talk_ratio", "strict_rhyme", "crystal_coverage")),
        "initial_receipt_cursor": initial, "snapshots": []}
    until = time.monotonic() + args.seconds
    next_pipeline = 0
    while True:
        started = time.monotonic()
        last = started >= until
        frame = snapshot(with_pipeline=started >= next_pipeline or last)
        if frame["pipeline"]:
            next_pipeline = started + 45
        report["snapshots"].append(frame)
        report["audible_receipts"] = receipts(initial.get("cursor", 0))
        if len(report["snapshots"]) == 1:
            report["bank_evidence_before"] = bank_evidence(frame["bank"])
        report["bank_evidence_after"] = bank_evidence(frame["bank"])
        if last:
            report["state"] = "complete"
        save(report, path)
        print(json.dumps({"at": frame["at"], "state": report["state"], "bank": pick(frame["bank"],
            ("ready", "reserved", "heard", "waiting", "suspended", "why")), "cadence": frame["cadence"],
            "errors": frame["errors"]}), flush=True)
        if last:
            break
        time.sleep(max(0, min(args.interval - (time.monotonic() - started), until - time.monotonic())))


if __name__ == "__main__":
    main()
