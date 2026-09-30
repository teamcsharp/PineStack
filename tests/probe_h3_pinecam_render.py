"""[h3-anyfootage] a REAL H3 stinger from a Pine Cam recording, end to end, the way
the stinger window sends it: pin (/api/pinecam/h3-ref), then POST /api/comfy/workshop
{purpose: parody_stinger, mode: reference, source_type: pinecam}, then follow the
parody queue until the render is done. air_it is false: it lands in the gallery,
it does not air. Run in the container:
    docker exec -w /app -e PYTHONPATH=/app spark-agent python tests/probe_h3_pinecam_render.py
"""
import json
import os
import time
import urllib.request

B = "http://127.0.0.1:8096"
H = {"Authorization": "Bearer " + os.environ.get("SPARK_AGENT_API_KEY", ""), "Content-Type": "application/json"}


def call(path, body=None):
    req = urllib.request.Request(B + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers=H, method="POST" if body is not None else "GET")
    return json.load(urllib.request.urlopen(req, timeout=120))


recs = call("/api/pinecam/recordings")
pick = next(x for x in recs["items"] if x["kind"] == "footage" and not x["writing"] and not x.get("broken"))
print("reference footage:", pick["name"])
seed = call("/api/pinecam/h3-ref", {"name": pick["name"]})
print("pinned:", seed.get("id"), seed.get("seconds"), "s", seed.get("say"))
direction = "the Pine Box FM logo slams in over this studio desk with neon rim light and a quick bass drop"
body = {"mode": "reference", "purpose": "parody_stinger", "source": seed["id"], "source_type": "pinecam",
        "prompt": "Create a short Pine Box FM radio stinger as a parody of the reference video. "
                  "Keep its recognizable composition and performance while making it feel native to Pine Box FM. "
                  "Follow this direction: " + direction,
        "speech": "", "frames": 73, "steps": 4, "air_it": False,
        "trim_in_s": 20.0, "trim_out_s": 24.0}
got = call("/api/comfy/workshop", body)
print("queued:", json.dumps(got))
qid = got.get("queue_id")
t0 = time.time()
last = ""
while time.time() - t0 < 1500:
    time.sleep(20)
    try:
        q = call("/api/comfy/workshop/parody-queue")
    except Exception as exc:  # noqa: BLE001
        print("queue read failed:", exc)
        continue
    rows = q.get("items") or q.get("queue") or q.get("jobs") or []
    me = next((r for r in rows if str(r.get("id")) == str(qid)), None)
    if me is None:
        hist = q.get("history") or q.get("done") or []
        me = next((r for r in hist if str(r.get("id")) == str(qid)), None)
    line = json.dumps({k: (me or {}).get(k) for k in ("status", "note", "error", "prompt_id", "attempts")})
    if line != last:
        print("%4ds" % (time.time() - t0), line)
        last = line
    if me and me.get("status") in ("done", "cancelled", "failed"):
        break
if me and me.get("prompt_id"):
    try:
        gen = call("/api/comfy/workshop")
        print("workshop state keys:", list(gen)[:12])
    except Exception as exc:  # noqa: BLE001
        print("workshop read:", exc)
