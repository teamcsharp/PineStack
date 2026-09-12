"""Run an explicitly requested bounded pause, always restoring its prior state."""
import argparse
import json
import os
import time

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()
    duration = max(1, min(60, args.seconds))
    key = os.environ.get("SPARK_AGENT_API_KEY", "")
    headers = {"Authorization": "Bearer " + key} if key else {}
    with httpx.Client(base_url="http://127.0.0.1:8096", headers=headers, timeout=30) as client:
        initial = client.get("/api/radio/pause").json()
        before = bool(initial["paused"])
        began = time.monotonic()
        try:
            client.post("/api/radio/pause", json={"paused": True}).raise_for_status()
            while True:
                room = client.get("/api/recording-room").json()
                pause = client.get("/api/radio/pause").json()
                bank = client.get("/api/dj/responses").json()
                recovery = room.get("tint_recovery") or {}
                report = {"elapsed": round(time.monotonic() - began, 2),
                    "pause": pause, "booths": room.get("booths"), "takes": room.get("takes"),
                    "preparing": room.get("preparing"),
                    "recovery": {k: recovery.get(k) for k in ("running", "checked", "last_at", "why", "states")},
                    "recovery_attempts": [row for row in recovery.get("pending") or [] if row.get("attempts")],
                    "bank": {k: bank.get(k) for k in ("cast", "recording", "drafting")}}
                print(json.dumps(report, ensure_ascii=False), flush=True)
                left = duration - (time.monotonic() - began)
                if left <= 0:
                    break
                time.sleep(min(20, left))
        finally:
            response = client.post("/api/radio/pause", json={"paused": before})
            response.raise_for_status()
            print(json.dumps({"restored": response.json(), "prior_paused": before}), flush=True)


if __name__ == "__main__":
    main()
