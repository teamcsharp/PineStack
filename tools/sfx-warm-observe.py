"""Bounded GET-only startup readiness evidence; run in the station container."""
import argparse
import json
import os
from pathlib import Path
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--restart-at", type=float, default=0)
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--output", default="docs/sfx-warm-live-observation.json")
    args = parser.parse_args()
    if not 5 <= args.seconds <= 40:
        raise SystemExit("Observation must be bounded to 5..40 seconds")
    started = time.time()
    rows = []
    while time.time() < started + args.seconds:
        row = {"at": time.time()}
        request = urllib.request.Request("http://127.0.0.1:8096/api/sfx/history?limit=1",
            headers={"Authorization": "Bearer " + os.environ["SPARK_AGENT_API_KEY"]})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                data = json.load(response)
            row.update({name: data.get(name) for name in (
                "pool", "ready_at", "filling", "walked_at", "fresh", "note")})
        except Exception as exc:
            row["error"] = type(exc).__name__
        rows.append(row)
        time.sleep(min(1, max(0, started + args.seconds - time.time())))
    ready = [r for r in rows if (r.get("pool") or 0) > 0]
    first = ready[0] if ready else {}
    report = {"read_only": True, "started_at": started, "ended_at": time.time(),
        "restart_at": args.restart_at or None, "observations": rows,
        "first_nonempty_observed_at": first.get("at"), "first_pool_size": first.get("pool"),
        "server_ready_at": first.get("ready_at"),
        "ready_seconds_after_restart": (round(float(first["ready_at"]) - args.restart_at, 3)
            if first.get("ready_at") and args.restart_at else None),
        "limits": "GET-only snapshots of verified pool publication; does not claim a sample was selected or audible. ready_at is the most recent progressive publication when observed."}
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "observations"}))


if __name__ == "__main__":
    main()
