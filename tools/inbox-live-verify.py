"""Inspect deployed inbox features from inside the agent container.

Credentials stay in the process environment and never enter the report.
Use --warm --batch 24 to prepare recorded responses using spare room slots.
"""
import argparse
import json
import os
import uuid

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8096")
    parser.add_argument("--warm", action="store_true")
    parser.add_argument("--conversation", action="store_true")
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--continuity-prepare", action="store_true")
    parser.add_argument("--only", nargs="+", help="Read only the named checks, such as responses")
    args = parser.parse_args()
    key = os.environ.get("SPARK_AGENT_API_KEY", "")
    headers = {"Authorization": "Bearer " + key} if key else {}
    report = {}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=120) as client:
        paths = {
            "health": "/healthz", "requests": "/api/pine-requests",
            "responses": "/api/dj/responses", "paper": "/api/paper",
            "memory": "/api/coordinator/memory?q=recording%20shortfall",
            "recording": "/api/recording-room", "flow": "/api/dj/flow",
            "pause": "/api/radio/pause", "capacity": "/api/coordinator/capacity",
            "resources": "/api/coordinator/resources", "continuity": "/api/dj/continuity",
        }
        for name, path in paths.items():
            if args.only and name not in args.only:
                continue
            try:
                response = client.get(path)
                data = response.json()
                item = {"status": response.status_code, "fields": list(data)}
                if name == "requests":
                    item["ids"] = [r["id"] for r in data.get("requests", [])]
                elif name == "responses":
                    item.update(cast=data.get("cast"), recording=data.get("recording"), drafting=data.get("drafting"))
                    item["audio"] = [{"who": who, "text": row.get("text"),
                                      "seconds": row.get("clip", {}).get("seconds"),
                                      "bytes": row.get("clip", {}).get("bytes")}
                                     for who, rows in data.get("responses", {}).items()
                                     for row in rows[:4]]
                    item["source_examples"] = [{"who": who, "text": row.get("text"),
                        "source_file": row.get("source", {}).get("file")}
                        for who, rows in data.get("responses", {}).items()
                        for row in [next((r for r in rows if r.get("source")), {})] if row]
                    item["sample_checks"] = []
                    for who, rows in data.get("responses", {}).items():
                        if not rows:
                            continue
                        clip = rows[0].get("clip") or {}
                        path = str(clip.get("path") or "")
                        if not path.startswith("/media/"):
                            continue
                        sample = client.get(path, params={"t": clip.get("sig", "")},
                                            headers={"Range": "bytes=0-63"})
                        item["sample_checks"].append({"who": who, "status": sample.status_code,
                            "type": sample.headers.get("content-type"), "received_bytes": len(sample.content)})
                elif name == "recording":
                    item.update(booths=data.get("booths"), takes=data.get("takes"),
                                tint_recovery=data.get("tint_recovery"))
                elif name == "memory":
                    item.update({k: v for k, v in data.items()
                                 if k in ("stored_outcomes", "indexed_outcomes", "embedding_model", "journal_error")})
                    item["matches"] = [{"hour": row.get("trace_id"),
                                        "retrieval": row.get("retrieval"), "relevance": row.get("relevance")}
                                       for row in data.get("outcomes", [])]
                elif name == "paper":
                    item.update(latest=data.get("latest"), running=data.get("running"))
                elif name == "resources":
                    item["snapshot"] = data.get("snapshot")
                    item["history_rows"] = len(data.get("history") or [])
                elif name == "flow":
                    health = data.get("health") or {}
                    item["health"] = {k: v for k, v in health.items() if k != "last_delivery"}
                    delivery = health.get("last_delivery") or {}
                    item["line_audit"] = delivery.get("line_audit")
                    item["render_recovery_lines"] = delivery.get("render_recovery_lines")
                else:
                    item.update({k: v for k, v in data.items() if k != "roads"})
                report[name] = item
            except Exception as exc:
                report[name] = {"error": type(exc).__name__, "message": str(exc)[:160]}
        if args.warm:
            response = client.post("/api/dj/responses/prepare",
                                   params={"limit": max(0, min(24, args.batch)), "draft": args.draft},
                                   timeout=900)
            report["warm"] = {"status": response.status_code, "result": response.json()}
        if args.continuity_prepare:
            response = client.post("/api/dj/continuity/prepare", params={"limit": 8}, timeout=900)
            report["continuity_prepare"] = {"status": response.status_code, "result": response.json()}
        if args.conversation:
            identity = "inbox-verification-" + uuid.uuid4().hex
            states = []
            for text in ("I would like to file a Pine Box request.", "Cancel."):
                response = client.post("/api/test", json={"text": text, "conversation_id": identity})
                response.raise_for_status()
                states.append(response.json().get("pine_request", {}).get("state"))
            report["conversation"] = {"states": states, "passed": states == ["awaiting_request", "cancelled"]}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
