"""[h3-cinematic] Prove the base-model path runs on this box: one small text
render (3 s, 640x384, 20 steps, no turbo LoRA, res_multistep), straight to
ComfyUI, after the box is at or under the heat line and ComfyUI is idle.
Reports the time against the estimate and fetches the clip into
data/h3_ab/. Run ON THE HOST from the repo:  python3 tools/h3_cinematic_proof.py
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import comfy_workshop as cw  # noqa: E402

COMFY = "http://127.0.0.1:8188"
HEAT = float(os.environ.get("PROOF_HEAT_C", "86"))
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "h3_ab")
os.makedirs(HERE, exist_ok=True)


def get(path):
    with urllib.request.urlopen(COMFY + path, timeout=20) as r:
        return json.load(r)


def hottest():
    best = 0.0
    for z in range(0, 16):
        try:
            with open("/sys/class/thermal/thermal_zone%d/temp" % z) as fh:
                best = max(best, int(fh.read()) / 1000.0)
        except OSError:
            pass
    return best


for _ in range(360):
    q = get("/queue")
    idle = not q.get("queue_running") and not q.get("queue_pending")
    if idle and hottest() <= HEAT:
        break
    print("waiting: %.0f C, comfy %s" % (hottest(), "idle" if idle else "busy"), flush=True)
    time.sleep(20)
else:
    sys.exit("the box never got cool and idle enough")

frames, steps = 73, 20
prompt = cw.compose_prompt("A radio host at a wooden desk in a warm studio, one desk lamp, a slow push in",
                           "Pine Box FM, the sound of the valley.", "", "text", seconds=frames / 24.0)
graph = cw.build_workflow(prompt, mode="text", frames=frames, steps=steps, turbo=False, width=640, height=384,
                          max_frames=frames, seed=1234567)
assert "5" not in graph and graph["9"]["class_type"] == "KSamplerSelect", "not the base path"
graph["15"]["inputs"]["filename_prefix"] = "h3_ab/cinematic_proof"
est = cw.estimate_seconds(640, 384, frames, steps)
t0 = time.time()
hot0 = hottest()
req = urllib.request.Request(COMFY + "/prompt", data=json.dumps({"prompt": graph, "client_id": "h3-cine"}).encode(),
                             headers={"Content-Type": "application/json"})
pid = json.load(urllib.request.urlopen(req, timeout=30))["prompt_id"]
print("submitted", pid, "at %.0f C, estimate %.0f s" % (hot0, est), flush=True)
peak = hot0
entry = None
while time.time() - t0 < 2400:
    peak = max(peak, hottest())
    h = get("/history/" + pid)
    if pid in h:
        st = h[pid].get("status") or {}
        if st.get("completed") or st.get("status_str") in ("success", "error"):
            entry = h[pid]
            break
    time.sleep(5)
took = time.time() - t0
status = ((entry or {}).get("status") or {}).get("status_str")
print("status %s in %.0f s (estimate %.0f s), peak %.0f C" % (status, took, est, peak), flush=True)
if entry and status == "error":
    for msg in (entry.get("status") or {}).get("messages") or []:
        if msg[0] == "execution_error":
            print("error:", json.dumps(msg[1])[:600])
for node in ((entry or {}).get("outputs") or {}).values():
    for key in ("videos", "gifs", "images"):
        for item in node.get(key) or []:
            q = urllib.parse.urlencode({"filename": item.get("filename"), "subfolder": item.get("subfolder") or "",
                                        "type": item.get("type") or "output"})
            dest = os.path.join(HERE, item.get("filename"))
            with urllib.request.urlopen(COMFY + "/view?" + q, timeout=120) as r, open(dest, "wb") as fh:
                fh.write(r.read())
            print("clip:", dest, os.path.getsize(dest), "bytes")
