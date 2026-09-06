"""Read-only ordered playback and writing-room deployment evidence."""
import json
import os
from pathlib import Path

import httpx


def main():
    key = os.environ.get("SPARK_AGENT_API_KEY", "")
    headers = {"Authorization": "Bearer " + key} if key else {}
    with httpx.Client(base_url="http://127.0.0.1:8096", headers=headers, timeout=30) as client:
        flow = client.get("/api/dj/flow").json()
        room = client.get("/api/recording-room").json()
        station = client.get("/api/dj/state").json()
        state = (flow.get("health") or {}).get("last_delivery") or {}
        auditions = [{k: row.get(k) for k in ("id", "who", "voice", "text", "from", "until", "delivery_id", "aired")}
                    for row in station.get("chat", []) if row.get("kind") == "response_audition"]
        print(json.dumps({"audition_rows": auditions, "activity_log": station.get("activity_log"),
                          "writers": room.get("writers"), "booths": room.get("booths"),
                          "delivery": state, "health": {k: v for k, v in flow.get("health", {}).items()
                                                       if k != "last_delivery"}}, ensure_ascii=False), flush=True)
    path = Path(os.environ.get("SPARK_AGENT_DATA_DIR", "/app/data")) / "model_calls.jsonl"
    if path.exists():
        calls = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()[-8:]]
        print(json.dumps({"recent_model_calls": [{k: v for k, v in row.items()
                                                   if k not in ("prompt", "messages", "reply")}
                                                  for row in calls]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
