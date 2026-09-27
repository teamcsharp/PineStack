"""An A/B of H3 graph settings on this box, straight against ComfyUI.

Four short text-to-video renders (3 s, 640x384, 8 turbo steps, one seed, one
brief), one after another, each waiting for the box to be under the heat
line and ComfyUI to be idle:

  A_cache      the graph as shipped (EasyCache on)
  A_nocache    the same without EasyCache        -> what the cache saves
  B_shift      + MiniMaxH3SigmaShift 12 / 3       -> detail and audio
  C_euler_beta euler + beta instead of the turbo sampler + simple

Writes data/h3_ab/<run>.json with the timing and output file of each, and a
contact sheet data/h3_ab/<run>.png (three frames per variant) when ffmpeg
is on the box. Run ON THE HOST from the repo:  python3 tools/h3_ab.py
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import comfy_workshop as cw  # noqa: E402

COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
STATION = os.environ.get("STATION_URL", "http://127.0.0.1:8096")
HEAT_LINE = float(os.environ.get("AB_HEAT_C", "84"))
OUT_DIR = os.environ.get("COMFY_OUTPUT", "/home/ehm_eckx/AI/comfyui-minimax-h3-dgx-spark/ComfyUI/output")
RUN = time.strftime("%Y%m%d-%H%M%S")
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "h3_ab")
os.makedirs(HERE, exist_ok=True)

PROMPT = cw.compose_prompt(
    "A radio host at a wooden desk in a warm studio, one desk lamp, direct to camera, "
    "a slow push in", "Pine Box FM, the sound of the valley.", "", "text", seconds=73 / 24.0)
SEED = 1234567
VARIANTS = {
    "A_cache": dict(easycache=True),
    "A_nocache": dict(easycache=False),
    "B_shift": dict(easycache=True, shift=[12, 3]),
    "C_euler_beta": dict(easycache=True, sampler="euler", scheduler="beta"),
}


def get(url):
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def hottest():
    try:
        return float((get(STATION + "/api/h3/hourly").get("box") or {}).get("hottest_c") or 0)
    except Exception:  # noqa: BLE001
        return 0.0


def comfy_idle():
    try:
        q = get(COMFY + "/queue")
        return not q.get("queue_running") and not q.get("queue_pending")
    except Exception:  # noqa: BLE001
        return False


def wait_ready(name):
    for _ in range(240):
        hot, idle = hottest(), comfy_idle()
        if idle and (hot == 0 or hot < HEAT_LINE):
            return hot
        print("%s waits: %.0f C, comfy %s" % (name, hot, "idle" if idle else "busy"), flush=True)
        time.sleep(15)
    return hottest()


def submit(graph):
    req = urllib.request.Request(COMFY + "/prompt", data=json.dumps({"prompt": graph, "client_id": "h3-ab"}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["prompt_id"]


def wait_done(pid):
    for _ in range(600):
        h = get(COMFY + "/history/" + pid)
        if pid in h:
            entry = h[pid]
            status = entry.get("status") or {}
            if status.get("completed") or status.get("status_str") in ("success", "error"):
                return entry
        time.sleep(5)
    return None


def timing(entry):
    start = end = None
    for msg in (entry.get("status") or {}).get("messages") or []:
        kind, body = msg[0], msg[1] if len(msg) > 1 else {}
        if kind == "execution_start":
            start = body.get("timestamp")
        if kind in ("execution_success", "execution_error"):
            end = body.get("timestamp")
    return (end - start) / 1000.0 if start and end else None


def output_file(entry):
    """The finished clip, fetched through ComfyUI's own /view door into
    data/h3_ab (the output folder on disk is not where the station thinks)."""
    for node in (entry.get("outputs") or {}).values():
        for key in ("videos", "gifs", "images"):
            for item in node.get(key) or []:
                name = item.get("filename") or ""
                sub = item.get("subfolder") or ""
                if not name:
                    continue
                local = os.path.join(HERE, name)
                try:
                    url = COMFY + "/view?filename=%s&subfolder=%s&type=%s" % (
                        urllib.parse.quote(name), urllib.parse.quote(sub), item.get("type") or "output")
                    with urllib.request.urlopen(url, timeout=120) as r, open(local, "wb") as fh:
                        fh.write(r.read())
                    return local
                except Exception as exc:  # noqa: BLE001
                    print("could not fetch", name, exc, flush=True)
                    return os.path.join(OUT_DIR, sub, name)
    return ""


results = {}
CHOSEN = [n for n in sys.argv[1:] if n in VARIANTS] or list(VARIANTS)   # a subset: python3 tools/h3_ab.py A_cache A_nocache
for name, kw in ((n, VARIANTS[n]) for n in CHOSEN):
    hot = wait_ready(name)
    graph = cw.build_workflow(PROMPT, mode="text", frames=73, steps=8, seed=SEED, width=640, height=384, max_frames=73, **kw)
    graph["15"]["inputs"]["filename_prefix"] = "h3_ab/%s_%s" % (RUN, name)
    t0 = time.time()
    try:
        pid = submit(graph)
    except Exception as exc:  # noqa: BLE001
        results[name] = {"error": "submit: %s" % exc}
        print(name, "submit failed:", exc, flush=True)
        continue
    entry = wait_done(pid)
    took = timing(entry) if entry else None
    status = ((entry or {}).get("status") or {}).get("status_str")
    path = output_file(entry) if entry else ""
    results[name] = {"seconds": took, "wall": round(time.time() - t0, 1), "status": status, "file": path,
                     "hot_before": hot, "hot_after": hottest(), "settings": kw}
    print("%-12s %s  %s s (wall %s)  %s" % (name, status, took, results[name]["wall"], path), flush=True)
    with open(os.path.join(HERE, RUN + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"run": RUN, "prompt": PROMPT, "seed": SEED, "results": results}, fh, indent=1)

ffmpeg = shutil.which("ffmpeg")
if ffmpeg:
    tiles = []
    for name in CHOSEN:
        f = results.get(name, {}).get("file")
        if not f or not os.path.exists(f):
            continue
        for k, at in enumerate((0.4, 1.5, 2.6)):
            png = os.path.join(HERE, "%s_%s_%d.png" % (RUN, name, k))
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", str(at), "-i", f, "-frames:v", "1", "-vf", "scale=320:-1", png], check=False)
            if os.path.exists(png):
                tiles.append(png)
    if tiles:
        sheet = os.path.join(HERE, RUN + ".png")
        inputs = []
        for t in tiles:
            inputs += ["-i", t]
        cols = 3
        rows = max(1, len(tiles) // cols)
        layout = "|".join("%d_%d" % ((i % cols) * 320, (i // cols) * 192) for i in range(len(tiles)))
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", *inputs, "-filter_complex",
                        "xstack=inputs=%d:layout=%s" % (len(tiles), layout), sheet], check=False)
        print("sheet:", sheet if os.path.exists(sheet) else "not made", flush=True)
print("done:", json.dumps({k: (v.get("seconds"), v.get("status")) for k, v in results.items()}))
