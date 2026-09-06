"""Audition four existing cast recordings, then inspect real listener receipts."""
import hashlib
import json
import os
import time

import httpx


def main():
    key = os.environ.get("SPARK_AGENT_API_KEY", "")
    headers = {"Authorization": "Bearer " + key} if key else {}
    with httpx.Client(base_url="http://127.0.0.1:8096", headers=headers, timeout=120) as client:
        bank = client.get("/api/dj/responses").json()
        request = []
        for who, preferred in (("dj", "I'm listening."), ("cohost", "Go on."),
                               ("dj", "I hear you."), ("cohost", "Yeah.")):
            rows = bank.get("responses", {}).get(who) or []
            row = next((r for r in rows if r["text"] == preferred), None)
            if row is None:
                raise RuntimeError(f"The selected real {who} recording is not ready")
            identity = row.get("id") or hashlib.sha256(
                f"{row['voice']}\0{row['engine']}\0{row['text']}".encode()).hexdigest()[:24]
            request.append({"who": who, "response_id": identity})
        response = client.post("/api/dj/responses/play", json={"lines": request})
        response.raise_for_status()
        audition = response.json()
        print(json.dumps({"audition": audition}, ensure_ascii=False), flush=True)
        delivery = audition["delivery_id"]
        due = time.monotonic() + 60
        while True:
            flow = client.get("/api/dj/flow").json()
            state = (flow.get("health") or {}).get("last_delivery") or {}
            audit = next((row for row in state.get("line_audit") or []
                          if row.get("delivery_id") == delivery), {})
            events = [row for row in state.get("events") or [] if row.get("delivery_id") == delivery]
            details = next((row for row in state.get("deliveries") or []
                            if row.get("delivery_id") == delivery), {})
            room = client.get("/api/recording-room").json()
            print(json.dumps({"audit": audit, "events": events, "delivery": details,
                              "writers": room.get("writers"),
                              "tint_recovery": {k: (room.get("tint_recovery") or {}).get(k)
                                                for k in ("states", "attempts", "why", "pending")}},
                             ensure_ascii=False), flush=True)
            if audit.get("complete") or time.monotonic() >= due:
                break
            time.sleep(5)


if __name__ == "__main__":
    main()
