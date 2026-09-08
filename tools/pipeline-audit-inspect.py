"""Read-only, credential-free evidence for the radio pipeline audit.

Run inside spark-agent. All station requests are GETs; this does not ask a
model, render a test line, change policy, resume radio, or submit receipts.
"""
import argparse
import json
import os
from pathlib import Path
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    parser.add_argument("--since", type=float, default=0.0)
    args = parser.parse_args()
    base = "http://127.0.0.1:8096"
    headers = {"Authorization": "Bearer " + os.environ["SPARK_AGENT_API_KEY"]}

    def get(path):
        with urllib.request.urlopen(urllib.request.Request(base + path, headers=headers), timeout=30) as response:
            return json.load(response)

    report = {"at": time.time(), "read_only": True}
    state = get("/api/dj")
    report["station"] = {name: state.get(name) for name in ("on", "paused")}
    report["station"]["speaking"] = bool((state.get("speaking_now") or {}).get("text"))
    stream = state.get("stream_now") or {}
    report["stream"] = {"at": stream.get("at"), "seconds": stream.get("length"),
                        "line_count": len(stream.get("rows") or [])}
    programmes = {}
    for row in state.get("chat") or []:
        delivery_id = str(row.get("delivery_id") or "")
        if not delivery_id:
            continue
        programme = programmes.setdefault(delivery_id, {"delivery_id": delivery_id,
            "kinds": [], "voices": [], "visible_lines": 0})
        programme["visible_lines"] += 1
        for source, target in (("kind", "kinds"), ("voice", "voices")):
            value = str(row.get(source) or "")
            if value and value not in programme[target]:
                programme[target].append(value)
    report["delivery_programmes"] = list(programmes.values())[-20:]
    brief = get("/api/coordinator/brief")
    report["brief"] = {name: brief.get(name) for name in
        ("worries", "doing", "say", "banked", "next_hole", "bare_count", "held", "quiet_for", "gap_open")}
    report["capacity"] = get("/api/coordinator/capacity")
    room = get("/api/recording-room")
    report["recording"] = {name: room.get(name) for name in ("takes", "airtime", "booths", "writers", "shelf")}
    recovery = room.get("tint_recovery") or {}
    report["recovery"] = {name: recovery.get(name) for name in ("running", "checked", "last_at", "why", "states", "attempts")}
    report["recovery"]["pending"] = [{name: row.get(name) for name in
        ("id", "kind", "state", "attempts", "last_attempt", "audio_preserved", "coverage")}
        for row in recovery.get("pending") or []]
    logic = get("/api/orchestrator/logic")
    report["orchestration"] = {name: logic.get(name) for name in
        ("hours_ready", "target_hours", "order", "slots", "hour", "workshop", "plan_why", "pipeline")}
    report["road_debt"] = {name: {key: row.get(key) for key in ("owed", "held", "uncovered", "cost", "task")}
        for name, row in (logic.get("roads") or {}).items()}
    hourly = get("/api/coordinator/hourly")
    report["current_hour"] = {"id": hourly.get("id"), "active_seconds": hourly.get("active_seconds"),
        "roads": {name: {key: row.get(key) for key in
                    ("target_seconds", "aired_seconds", "attainment", "schedule")}
                  for name, row in (hourly.get("roads") or {}).items()}}
    tint = get("/api/tint")
    report["tint"] = {name: tint.get(name) for name in ("hold", "grade", "force", "coverage", "coverage_target")}
    reviews = get("/api/orchestrator/rejections?status=all&limit=1")
    report["reviews"] = {name: reviews.get(name) for name in ("total", "unreviewed", "latest_cursor", "policy")}
    flow = get("/api/dj/flow?limit=1")
    health = flow.get("health") or {}
    report["flow"] = {name: health.get(name) for name in
        ("on", "paused", "talk_gap_seconds", "talk_gap_monitoring", "floor_busy", "last_speech")}
    report["flow"]["line_audit"] = [{name: row.get(name) for name in
        ("delivery_id", "state", "complete", "scheduled_lines", "acknowledged_lines", "unconfirmed_line_ids")}
        for row in (health.get("last_delivery") or {}).get("line_audit") or []]
    if args.since:
        data_root = Path(os.environ.get("SPARK_AGENT_DATA_DIR", "/app/data"))
        stored = json.loads((data_root / "pantry.json").read_text(encoding="utf-8"))
        recent = []
        for key, row in stored.items():
            if float(row.get("at") or 0) < args.since:
                continue
            clip = row.get("clip") or {}
            name = str(clip.get("path") or "").split("?", 1)[0].rsplit("/", 1)[-1]
            file = data_root / "voice_media" / name
            exists = bool(name and file.is_file())
            recent.append({"key": key, "kind": row.get("kind"), "voice": row.get("voice"),
                "at": row.get("at"), "seconds": float(clip.get("seconds") or 0),
                "file_exists": exists, "new_media": exists and file.stat().st_mtime >= args.since})
        report["new_stored_takes"] = {"since": args.since, "rows": len(recent),
            "existing_files": sum(row["file_exists"] for row in recent),
            "new_media_files": sum(row["new_media"] for row in recent),
            "seconds": round(sum(row["seconds"] for row in recent), 3),
            "items": sorted(recent, key=lambda row: row["at"], reverse=True)[:20]}
    rendered = json.dumps(report, indent=2, ensure_ascii=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
