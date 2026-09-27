"""[h3-cast] Prove the host's LoRA works in the station's own graph: two small
text renders (3 s, 640x384, 8 turbo steps, one seed), without and with the
cast, straight to ComfyUI, each after the box is at or under the heat line and
ComfyUI is idle. Reports whether ComfyUI loaded every LoRA key (its log names
any it could not map), the times, and stills to compare with the portraits in
data/h3_ab/. Run ON THE HOST from the repo:  python3 tools/h3_cast_proof.py
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import comfy_workshop as cw  # noqa: E402

COMFY = "http://127.0.0.1:8188"
HEAT = float(os.environ.get("PROOF_HEAT_C", "86"))
LOG = os.path.expanduser("~/comfyui.log")
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "h3_ab")
os.makedirs(HERE, exist_ok=True)
LORA = os.environ.get("CAST_LORA", "pinehost_h3.safetensors")


def get(path):
    with urllib.request.urlopen(COMFY + path, timeout=20) as r:
        return json.load(r)


def hottest():
    best = 0.0
    for z in range(16):
        try:
            with open("/sys/class/thermal/thermal_zone%d/temp" % z) as fh:
                best = max(best, int(fh.read()) / 1000.0)
        except OSError:
            pass
    return best


def ready():
    for _ in range(720):
        q = get("/queue")
        if not q.get("queue_running") and not q.get("queue_pending") and hottest() <= HEAT:
            return True
        time.sleep(10)
    return False


def render(tag, graph):
    if not ready():
        sys.exit("the box never got cool and idle")
    graph["15"]["inputs"]["filename_prefix"] = "h3_ab/cast_%s" % tag
    log_at = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    t0 = time.time()
    req = urllib.request.Request(COMFY + "/prompt", data=json.dumps({"prompt": graph, "client_id": "h3-cast"}).encode(),
                                 headers={"Content-Type": "application/json"})
    pid = json.load(urllib.request.urlopen(req, timeout=30))["prompt_id"]
    entry = None
    while time.time() - t0 < 1800:
        h = get("/history/" + pid)
        if pid in h and ((h[pid].get("status") or {}).get("completed") or (h[pid].get("status") or {}).get("status_str") in ("success", "error")):
            entry = h[pid]
            break
        time.sleep(4)
    took = time.time() - t0
    status = ((entry or {}).get("status") or {}).get("status_str")
    missed = []
    try:
        with open(LOG, "rb") as fh:
            fh.seek(log_at)
            for line in fh.read().decode("utf-8", "replace").splitlines():
                if "lora key not loaded" in line.lower() or "error loading lora" in line.lower():
                    missed.append(line.strip()[:160])
    except OSError:
        pass
    clip = ""
    for node in ((entry or {}).get("outputs") or {}).values():
        for item in node.get("videos") or node.get("gifs") or node.get("images") or []:
            q = urllib.parse.urlencode({"filename": item.get("filename"), "subfolder": item.get("subfolder") or "",
                                        "type": item.get("type") or "output"})
            clip = os.path.join(HERE, item.get("filename"))
            with urllib.request.urlopen(COMFY + "/view?" + q, timeout=120) as r, open(clip, "wb") as fh:
                fh.write(r.read())
    still = ""
    if clip:
        still = clip[:-4] + "_still.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.5", "-i", clip, "-frames:v", "1", still], check=False)
    print("%-9s %s in %.0f s, lora keys not loaded: %d%s, clip %s" % (tag, status, took, len(missed),
                                                                    (" e.g. " + missed[0]) if missed else "", clip), flush=True)
    return missed, still


prompt_text = "The presenter sits at a radio desk in a warm late-night studio, one desk lamp, a slow push in"
speech = "This is Pine Box FM, and I am still here with you."
cw.set_cast({"on": True, "lora": LORA, "strength": 0.9})
with_cast = cw.build_workflow(cw.compose_prompt(prompt_text, speech, "", "text", seconds=73 / 24.0), mode="text",
                              frames=73, steps=8, seed=424242, width=640, height=384, max_frames=73)
assert with_cast.get("20", {}).get("class_type") == "LoraLoaderModelOnly", "the cast is not in the graph"
cw.set_cast({"on": False})
without = cw.build_workflow(cw.compose_prompt(prompt_text, speech, "", "text", seconds=73 / 24.0), mode="text",
                            frames=73, steps=8, seed=424242, width=640, height=384, max_frames=73)
_, plain_still = render("plain", without)
missed, cast_still = render("pinehost", with_cast)
if plain_still and cast_still:
    strip = os.path.join(HERE, "cast_compare.jpg")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", plain_still, "-i", cast_still, "-filter_complex",
                    "hstack=inputs=2", strip], check=False)
    print("compare:", strip, flush=True)
print("VERDICT:", "every LoRA key loaded" if not missed else "%d LoRA keys were NOT loaded" % len(missed), flush=True)
