"""Read-only deployment evidence. Run inside the station container."""
import json
import os
import sys
import time
import urllib.request


def get(path, raw=False):
    request = urllib.request.Request("http://127.0.0.1:8096" + path,
        headers={"Authorization": "Bearer " + os.environ.get("SPARK_AGENT_API_KEY", "")})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
        return body.decode("utf-8") if raw else json.loads(body)


state = get("/api/dj")
stream = state.get("stream_now") or {}
speaking = state.get("speaking_now") or {}
result = {"at": time.time(), "on": state.get("on"), "paused": state.get("paused"),
          "speaking": bool(speaking.get("text")),
          "remaining": max(0, float(stream.get("at") or 0) + float(stream.get("length") or 0) - time.time())}
if "--before" not in sys.argv:
    queue = get("/api/orchestrator/rejections?status=all&limit=2")
    context = get("/api/orchestrator/rejections/context")
    policy = get("/api/orchestrator/rejection-policy")
    result.update(review_total=queue["total"], unreviewed=queue["unreviewed"],
        cursor=queue["latest_cursor"], policy=policy, route=context.get("route"),
        writing=context.get("writing"), recording=context.get("recording"),
        orchestrator_visible=isinstance(context.get("orchestrator"), dict),
        module_served="export function create" in get("/orchestrator-review/rejection-review.js", True),
        style_served="prr-dialog" in get("/orchestrator-review/rejection-review.css", True),
        radio_boot="radioReviewBoot" in get("/radio", True),
        control_boot="lineReviewBoot" in get("/", True))
    if queue.get("items"):
        row = get("/api/orchestrator/rejections/" + queue["items"][0]["id"])
        result["retained_evidence"] = {"id": row["id"], "gate": row["gate"],
            "source_chars": len(row["source"]), "candidate_chars": len(row["candidate"]),
            "script_chars": len(str(row["context"].get("script") or "")),
            "reasons": len(row["reasons"]), "machine_evaluation": bool(row["evaluation"]),
            "review_status": row["review_status"], "occurrences": row["occurrences"]}
    if "--master" in sys.argv:
        module = get("/orchestrator-review/rejection-review.js", True)
        paths = get("/openapi.json").get("paths", {})
        result["master_controls"] = {
            "switch_served": "master.setAttribute('role', 'switch')" in module,
            "batch_served": "/approve-current" in module,
            "batch_backend": "post" in paths.get("/api/orchestrator/rejections/approve-current", {}),
        }
        if not all(result["master_controls"].values()):
            raise SystemExit("The running backend and delivered module must both support the master controls.")
print(json.dumps(result, indent=2))
if "--require-quiet" in sys.argv and (result["speaking"] or result["remaining"] > 0):
    raise SystemExit("Active audio: postpone the restart until the next quiet gap.")
