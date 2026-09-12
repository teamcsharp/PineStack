"""Archive verified inbox resolutions through the station's normal API."""
import argparse
import json
import os
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("resolutions", type=Path, help="JSON object mapping request IDs to completion notes")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8096")
    args = parser.parse_args()
    notes = json.loads(args.resolutions.read_text(encoding="utf-8-sig"))
    if not isinstance(notes, dict) or not notes:
        parser.error("Provide a nonempty object of verified completion notes")
    records = {int(key): value for key, value in notes.items()}
    if any(not isinstance(value, str) or not value.strip() for value in records.values()):
        parser.error("Every completion note must be a nonempty string")
    key = os.environ.get("SPARK_AGENT_API_KEY", "")
    headers = {"Authorization": "Bearer " + key} if key else {}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=60) as client:
        response = client.get("/api/pine-requests")
        response.raise_for_status()
        open_ids = {int(row["id"]) for row in response.json().get("requests", [])}
        for request_id, reply in records.items():
            if request_id not in open_ids:
                print(json.dumps({"id": request_id, "state": "already absent; no action"}), flush=True)
                continue
            if not args.apply:
                print(json.dumps({"id": request_id, "state": "preview", "reply": reply}), flush=True)
                continue
            response = client.post(f"/api/pine-requests/{request_id}/resolve", json={"reply": reply})
            response.raise_for_status()
            if response.json().get("resolved", {}).get("id") != request_id:
                raise RuntimeError(f"Unexpected completion result for {request_id}")
            print(json.dumps({"id": request_id, "state": "archived and resolved"}), flush=True)
        response = client.get("/api/pine-requests")
        response.raise_for_status()
        print(json.dumps({"remaining": [row["id"] for row in response.json().get("requests", [])]}))


if __name__ == "__main__":
    main()
