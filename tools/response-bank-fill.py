"""Fill the configured cast's real repertoire in bounded, observable batches."""
import argparse
import json
import os
import time

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=30)
    args = parser.parse_args()
    deadline = time.monotonic() + max(1, min(60, args.minutes)) * 60
    key = os.environ.get("SPARK_AGENT_API_KEY", "")
    headers = {"Authorization": "Bearer " + key} if key else {}
    with httpx.Client(base_url="http://127.0.0.1:8096", headers=headers, timeout=900) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get("/api/dj/responses", timeout=30)
                response.raise_for_status()
                state = response.json()
                cast = state.get("cast") or {}
                status = {who: {field: row.get(field) for field in
                          ("ready", "target", "source_ready", "source_drafts", "awaiting_recording", "eligible_now")}
                          for who, row in cast.items()}
                print(json.dumps({"at": time.time(), "cast": status,
                    "drafting": state.get("drafting"), "recording": state.get("recording")}), flush=True)
                if cast and all(row["ready"] >= row["target"] for row in cast.values()):
                    print(json.dumps({"complete": True}), flush=True)
                    return
                response = client.post("/api/dj/responses/prepare",
                                       params={"limit": 24, "draft": True})
                response.raise_for_status()
                print(json.dumps({"batch": response.json()}), flush=True)
            except (httpx.HTTPError, ValueError) as exc:
                print(json.dumps({"retry": type(exc).__name__}), flush=True)
            time.sleep(15)
    print(json.dumps({"complete": False, "why": "This bounded fill window ended; the station's background preparation continues."}), flush=True)


if __name__ == "__main__":
    main()
