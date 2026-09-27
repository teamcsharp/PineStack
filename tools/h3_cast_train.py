#!/usr/bin/env python3
"""[h3-cast] Train the Pine Box host's identity LoRA for MiniMax H3, ON THE HOST.

"a host identity LoRA" - a locked cast: one face the station's H3 renders can
put on screen again and again. The pinebox-h3-cast service runs this when the
station drops data/h3_cast/kick.json (POST /api/h3/cast/train, the gallery
gear's Train button); it can also be run by hand:

    python3 tools/h3_cast_train.py [--look "..."] [--steps 600] [--fresh]

The run, and what it writes to data/h3_cast/status.json at every stage:

  1. portraits  - one canonical portrait of the host (Z-Image Turbo, the
                  station's own image workflow), then identity-keeping
                  variations of it with FLUX.1 Kontext (angles, expressions,
                  light, framing), each captioned with the trigger word.
                  Kept in data/h3_cast/dataset/images; --fresh remakes them.
  2. caching    - musubi-tuner's H3 latent and text caches (one-frame), and
                  the unconditional probe the guidance loss needs.
  3. training   - a rank-16 LoRA on the pruned ConvRot INT8 FL2VA base
                  (the model the station renders with), one-frame targets,
                  guidance loss (the released H3 is CFG-distilled; plain flow
                  training would de-distil it), saved every 100 steps.
  4. installing - the newest save copied into ComfyUI's loras folder as
                  pinehost_h3.safetensors, the status names it; the station's
                  gear turns it on.

THE GOVERNOR. This box has frozen hard from HEAT (the second H3 render of a
boot, before the render gate existed). Training is minutes of sustained GPU
work, so every GPU job here runs under a governor that watches the hottest
thermal zone, free memory and ComfyUI's queue every two seconds and
SIGSTOPs the whole job while the box is at or above HOT_C, short of memory,
or rendering, and SIGCONTs it once the box is back at or under COOL_C and
idle - so no burst runs hotter than the station's own render gate allows.
At PANIC_C the job is killed (it keeps its last save). A `stop` file (POST
/api/h3/cast/stop) ends a run at once; the newest save is still installed.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(REPO, "data", "h3_cast")
IMAGES = os.path.join(WORK, "dataset", "images")
CACHE = os.path.join(WORK, "dataset", "cache")
OUT = os.path.join(WORK, "out")
LOG = os.path.join(WORK, "train.log")
STATUS = os.path.join(WORK, "status.json")
KICK = os.path.join(WORK, "kick.json")
STOP = os.path.join(WORK, "stop")
LOOK_FILE = os.path.join(WORK, "look.txt")

COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
COMFY_HOME = os.path.expanduser("~/ComfyUI")
MUSUBI = os.path.expanduser("~/musubi-tuner")
VENV = os.path.expanduser("~/musubi-venv/bin")
MODELS = os.path.join(COMFY_HOME, "models")
DIT = os.path.realpath(os.path.join(MODELS, "diffusion_models", "minimax_h3_fl2va_pruned_int8_convrot.safetensors"))
TEXT_ENCODER = os.path.realpath(os.path.join(MODELS, "text_encoders", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"))
VIDEO_VAE = os.path.realpath(os.path.join(MODELS, "vae", "minimax_h3_video_vae_fp16.safetensors"))
AUDIO_VAE = os.path.realpath(os.path.join(MODELS, "vae", "minimax_h3_audio_vae_fp32.safetensors"))
LORA_NAME = "pinehost_h3.safetensors"
TRIGGER = "pinehost"

HOT_C = float(os.environ.get("CAST_HOT_C", "90"))        # the station's own render ceiling
COOL_C = float(os.environ.get("CAST_COOL_C", "84"))      # the A/B's "ready" line
PANIC_C = float(os.environ.get("CAST_PANIC_C", "97"))
MEM_MIN_GB = float(os.environ.get("CAST_MEM_MIN_GB", "10"))
# a portrait is an image render (~80 s): lighter than a training burst, so it
# may start at up to the station's own heavy-profile line, not the cool line
PORTRAIT_COOL_C = float(os.environ.get("CAST_PORTRAIT_COOL_C", "88"))
START_MEM_GB = float(os.environ.get("CAST_START_MEM_GB", "45"))

DEFAULT_LOOK = ("a man in his mid forties with a short salt-and-pepper beard, tousled dark hair going grey at "
                "the temples, warm brown eyes and a faint wry smile, wearing a worn olive field jacket over a "
                "dark t-shirt")
VARIATIONS = [
    ("three-quarter view facing left", "Turn him to a three-quarter view facing left"),
    ("three-quarter view facing right", "Turn him to a three-quarter view facing right"),
    ("in profile facing left", "Show him in full profile facing left"),
    ("smiling warmly at the camera", "Make him smile warmly at the camera"),
    ("laughing, eyes creased", "Make him laugh, eyes creased, head tilted back a little"),
    ("talking into a studio microphone", "Put a large studio microphone in front of him and show him talking into it, mouth mid-word"),
    ("seen from slightly below", "Show him from a slightly low angle, looking down at the camera"),
    ("close-up of the face", "Make it a close-up with his face filling the frame"),
    ("medium shot at a radio desk", "Pull back to a medium shot from the waist up, sitting at a radio desk with a mixing board"),
    ("in soft daylight by a window", "Relight him in soft daylight from a window on his left"),
    ("under blue and magenta neon light at night", "Relight him under blue and magenta neon light at night"),
    ("headphones around his neck", "Put a pair of studio headphones around his neck"),
    ("serious and thoughtful, hand on his chin", "Give him a serious, thoughtful expression with a hand on his chin"),
    ("on a city street at night", "Put him on a city street at night with blurred lights behind him"),
    ("eyebrows raised in surprise", "Make him raise his eyebrows in surprise"),
    ("against a plain grey backdrop, neutral expression", "Put him against a plain grey studio backdrop with a neutral expression"),
    ("holding a coffee mug, relaxed", "Show him relaxed, holding a coffee mug in both hands"),
    ("looking off to the side, mid-sentence", "Show him looking off to the side, mid-sentence, as if answering someone off camera"),
]

_state: dict = {"state": "idle"}


# --- status ---------------------------------------------------------------------
def say(text: str) -> None:
    line = time.strftime("%H:%M:%S ") + text
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def status(**kw) -> None:
    _state.update(kw)
    _state["at"] = time.time()
    _state["temp_c"] = hottest()
    _state["mem_gb"] = mem_gb()
    os.makedirs(WORK, exist_ok=True)
    tmp = STATUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(_state, fh, indent=1)
    os.replace(tmp, STATUS)


# --- the box ----------------------------------------------------------------------
def hottest() -> float | None:
    best = None
    for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        try:
            with open(path) as fh:
                c = int(fh.read().strip()) / 1000.0
            best = c if best is None else max(best, c)
        except (OSError, ValueError):
            pass
    return best


def mem_gb() -> float | None:
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1048576.0
    except OSError:
        pass
    return None


def comfy_get(path: str, timeout: float = 10):
    with urllib.request.urlopen(COMFY + path, timeout=timeout) as r:
        return json.load(r)


def comfy_busy() -> bool:
    try:
        q = comfy_get("/queue", 5)
        return bool(q.get("queue_running") or q.get("queue_pending"))
    except Exception:  # noqa: BLE001
        return False


def comfy_free() -> None:
    """Ask ComfyUI to drop its loaded models - the trainer needs the room."""
    try:
        req = urllib.request.Request(COMFY + "/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
    except Exception:  # noqa: BLE001
        pass


def stop_asked() -> bool:
    return os.path.exists(STOP)


def wait_ready(stage: str, need_gb: float = 0.0, comfy_ok: bool = False, cool: float | None = None) -> bool:
    """Until the box is cool, idle and roomy enough. False when a stop is asked."""
    said = 0.0
    while True:
        if stop_asked():
            return False
        hot, free, busy = hottest(), mem_gb(), (False if comfy_ok else comfy_busy())
        why = []
        line = COOL_C if cool is None else cool
        if hot is not None and hot > line:
            why.append("%.0f C, waiting for %.0f C" % (hot, line))
        if busy:
            why.append("ComfyUI is rendering")
        if need_gb and free is not None and free < need_gb:
            why.append("%.0f GB free of %.0f needed" % (free, need_gb))
        if not why:
            return True
        if time.time() - said > 30:
            status(state=stage, paused=True, why="; ".join(why))
            said = time.time()
        time.sleep(5)


# --- the governor -------------------------------------------------------------------
def governed(cmd: list[str], stage: str, progress=None, cwd: str | None = None, env: dict | None = None) -> int:
    """Run `cmd` under the heat / memory / ComfyUI governor. Returns its exit code
    (or -9 when the governor killed it, -15 when a stop was asked)."""
    say("run: " + " ".join(cmd))
    logf = open(LOG, "a", encoding="utf-8")
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, start_new_session=True)
    os.set_blocking(proc.stdout.fileno(), False)
    paused, since_ok, buf, last_status = False, 0.0, "", 0.0
    killed = 0
    try:
        while True:
            try:
                chunk = proc.stdout.read()
            except (OSError, TypeError):
                chunk = None
            if chunk:
                logf.write(chunk)
                logf.flush()
                buf = (buf + chunk)[-4000:]
                if progress:
                    progress(buf)
            code = proc.poll()
            if code is not None:
                rest = proc.stdout.read() or ""
                if rest:
                    logf.write(rest)
                    if progress:
                        progress((buf + rest)[-4000:])
                return code
            hot, free, busy = hottest(), mem_gb(), comfy_busy()
            if stop_asked():
                os.killpg(proc.pid, signal.SIGCONT)
                os.killpg(proc.pid, signal.SIGTERM)
                killed = -15
                try:
                    proc.wait(30)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                return killed
            if hot is not None and hot >= PANIC_C:
                os.killpg(proc.pid, signal.SIGCONT)
                os.killpg(proc.pid, signal.SIGKILL)
                say("PANIC: %.1f C - the job is killed; its last save stands" % hot)
                status(state="failed", why="the box reached %.0f C and the run was killed" % hot, paused=False)
                return -9
            bad = []
            if hot is not None and hot >= HOT_C:
                bad.append("%.0f C" % hot)
            if free is not None and free < MEM_MIN_GB:
                bad.append("%.0f GB free" % free)
            if busy:
                bad.append("ComfyUI is rendering")
            if bad and not paused:
                os.killpg(proc.pid, signal.SIGSTOP)
                paused, since_ok = True, 0.0
                say("pause: " + "; ".join(bad))
                status(state="paused", stage=stage, paused=True, why="; ".join(bad))
            elif paused:
                ok = (hot is None or hot <= COOL_C) and (free is None or free >= MEM_MIN_GB + 5) and not busy
                if ok:
                    since_ok = since_ok or time.time()
                    if time.time() - since_ok >= 10:
                        os.killpg(proc.pid, signal.SIGCONT)
                        paused = False
                        say("resume at %.0f C" % (hot or 0))
                        status(state=stage, paused=False, why="")
                else:
                    since_ok = 0.0
            if time.time() - last_status > 10:
                # every ten seconds, paused or not: the station's H3 gate trusts
                # a training state only while it is fresh (three minutes)
                if paused:
                    status(state="paused", stage=stage, paused=True)
                else:
                    status(state=stage, paused=False, why="")
                last_status = time.time()
            time.sleep(2)
    finally:
        logf.close()
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGCONT)
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


# --- ComfyUI renders: the portraits -----------------------------------------------
def comfy_submit(graph: dict) -> str:
    req = urllib.request.Request(COMFY + "/prompt", data=json.dumps({"prompt": graph, "client_id": "h3-cast"}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["prompt_id"]


def comfy_wait(pid: str, limit_s: float = 900) -> dict | None:
    t0 = time.time()
    while time.time() - t0 < limit_s:
        hot = hottest()
        if hot is not None and hot >= PANIC_C:
            try:
                urllib.request.urlopen(urllib.request.Request(COMFY + "/interrupt", data=b"{}"), timeout=10).read()
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError("the box reached %.0f C during a portrait; interrupted" % hot)
        h = comfy_get("/history/" + pid)
        if pid in h:
            st = h[pid].get("status") or {}
            if st.get("completed") or st.get("status_str") in ("success", "error"):
                return h[pid]
        time.sleep(3)
    return None


def comfy_image(entry: dict, dest: str) -> str:
    for node in (entry.get("outputs") or {}).values():
        for item in node.get("images") or []:
            q = urllib.parse.urlencode({"filename": item.get("filename"), "subfolder": item.get("subfolder") or "",
                                        "type": item.get("type") or "output"})
            with urllib.request.urlopen(COMFY + "/view?" + q, timeout=120) as r, open(dest, "wb") as fh:
                fh.write(r.read())
            return dest
    raise RuntimeError("the render left no picture")


def portrait_graph(prompt: str, seed: int) -> dict:
    """The station's own image workflow (Z-Image Turbo, data/comfy_workflow.json)."""
    with open(os.path.join(REPO, "data", "comfy_workflow.json"), encoding="utf-8") as fh:
        graph = json.load(fh)
    for node in graph.values():
        ins = node.get("inputs") or {}
        if node.get("class_type") == "CLIPTextEncode" and "{prompt}" in str(ins.get("text")):
            ins["text"] = prompt
        if node.get("class_type") == "KSampler":
            ins["seed"] = seed
        if node.get("class_type") == "SaveImage":
            ins["filename_prefix"] = "h3_cast/canonical"
    return graph


def kontext_graph(image_name: str, instruction: str, seed: int) -> dict:
    """FLUX.1 Kontext: the same person, one change."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev-kontext_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "clip_l.safetensors",
                                                         "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
                                                         "type": "flux", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "5": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["4", 0]}},
        "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["3", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": instruction, "clip": ["2", 0]}},
        "8": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["7", 0], "latent": ["6", 0]}},
        "9": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["8", 0], "guidance": 2.5}},
        "10": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["7", 0]}},
        "11": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["9", 0], "negative": ["10", 0],
                                                    "latent_image": ["6", 0], "seed": seed, "steps": 20, "cfg": 1.0,
                                                    "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": "h3_cast/kontext"}},
    }


def caption(scene: str) -> str:
    return ("%s, the Pine Box host, %s. A photograph, a still picture. sound: silence, no audio." % (TRIGGER, scene))


def portrait_path(k: int, scene: str) -> str:
    return os.path.join(IMAGES, "%02d_%s.png" % (k, scene.split(",")[0].replace(" ", "-")[:40]))


def make_portraits(look: str, fresh: bool) -> int:
    """The canonical portrait and its variations. Resumable: what is already
    made is kept and only the missing ones are rendered (--fresh starts over)."""
    os.makedirs(IMAGES, exist_ok=True)
    if fresh:
        for old in glob.glob(os.path.join(IMAGES, "*")):
            os.remove(old)
        shutil.rmtree(CACHE, ignore_errors=True)
    canon = os.path.join(IMAGES, "00_canonical.png")
    todo = [(k, scene, change) for k, (scene, change) in enumerate(VARIATIONS, 1)
            if not os.path.exists(portrait_path(k, scene))]
    if os.path.exists(canon) and not todo:
        have = len(glob.glob(os.path.join(IMAGES, "*.png")))
        say("portraits kept: %d" % have)
        return have
    shutil.rmtree(CACHE, ignore_errors=True)          # the set changes: the caches follow it
    if not os.path.exists(canon):
        status(state="portraits", stage="portraits", step=0, of=len(VARIATIONS) + 1, why="the canonical portrait")
        if not wait_ready("portraits", cool=PORTRAIT_COOL_C):
            return -1
        prompt = ("A photorealistic portrait photograph of %s, head and shoulders, looking at the camera, in a dim "
                  "late-night radio studio lit by a warm desk lamp, 85mm lens, natural skin texture, sharp focus." % look)
        entry = comfy_wait(comfy_submit(portrait_graph(prompt, random.randint(1, 2 ** 31))))
        if not entry:
            raise RuntimeError("the canonical portrait did not finish")
        comfy_image(entry, canon)
        with open(os.path.join(IMAGES, "00_canonical.txt"), "w", encoding="utf-8") as fh:
            fh.write(caption("head and shoulders, looking at the camera, in a dim radio studio lit by a warm desk lamp"))
    shutil.copyfile(canon, os.path.join(COMFY_HOME, "input", "h3_cast_canonical.png"))
    for k, scene, change in todo:
        if stop_asked():
            return -1
        status(state="portraits", stage="portraits", step=k, of=len(VARIATIONS) + 1, why=scene)
        if not wait_ready("portraits", cool=PORTRAIT_COOL_C):
            return -1
        instruction = (change + ". Keep the exact same man - the same face, the same hair and beard, the same age "
                       "and build, the same clothes - as a photorealistic photograph.")
        try:
            entry = comfy_wait(comfy_submit(kontext_graph("h3_cast_canonical.png", instruction, random.randint(1, 2 ** 31))))
            if not entry:
                raise RuntimeError("did not finish")
            dest = portrait_path(k, scene)
            comfy_image(entry, dest)
            with open(dest[:-4] + ".txt", "w", encoding="utf-8") as fh:
                fh.write(caption(scene))
            say("portrait %d/%d: %s" % (k, len(VARIATIONS), scene))
        except Exception as exc:  # noqa: BLE001
            say("portrait %d failed: %s" % (k, exc))
    return len(glob.glob(os.path.join(IMAGES, "*.png")))


# --- musubi-tuner -----------------------------------------------------------------
def write_dataset() -> str:
    path = os.path.join(WORK, "dataset.toml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('[general]\nresolution = [640, 640]\nbatch_size = 1\nenable_bucket = true\nbucket_no_upscale = false\n\n'
                 '[[datasets]]\nimage_directory = "%s"\ncache_directory = "%s"\ncaption_extension = ".txt"\nnum_repeats = 1\n'
                 % (IMAGES, CACHE))
    return path


def cache(dataset: str) -> bool:
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    py = os.path.join(VENV, "python")
    status(state="caching", stage="caching", why="the latents", step=None, of=None)
    code = governed([py, os.path.join(MUSUBI, "minimax_h3_cache_latents.py"), "--dataset_config", dataset,
                     "--task", "t2va", "--one_frame", "--video_vae", VIDEO_VAE, "--audio_vae", AUDIO_VAE,
                     "--cache_seed", "42", "--skip_existing"], "caching", cwd=MUSUBI, env=env)
    if code != 0:
        raise RuntimeError("latent caching ended with %s" % code)
    status(state="caching", stage="caching", why="the captions (the text encoder)")
    code = governed([py, os.path.join(MUSUBI, "minimax_h3_cache_text_encoder_outputs.py"), "--dataset_config", dataset,
                     "--task", "t2va", "--one_frame", "--text_encoder", TEXT_ENCODER, "--text_cache_dtype", "bf16",
                     "--uncond_output", os.path.join(WORK, "uncond.safetensors"), "--skip_existing"],
                    "caching", cwd=MUSUBI, env=env)
    if code != 0:
        raise RuntimeError("text caching ended with %s" % code)
    return True


def train(dataset: str, steps: int) -> int:
    os.makedirs(OUT, exist_ok=True)
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")
    cmd = [os.path.join(VENV, "accelerate"), "launch", "--num_processes", "1", "--num_machines", "1",
           "--mixed_precision", "bf16", "--dynamo_backend", "no", "--num_cpu_threads_per_process", "1",
           os.path.join(MUSUBI, "minimax_h3_train_network.py"),
           "--dataset_config", dataset, "--task", "t2va", "--one_frame", "--video_only",
           "--dit", DIT, "--network_dim", "16", "--network_alpha", "16", "--sdpa",
           "--mixed_precision", "bf16", "--gradient_checkpointing", "--optimizer_type", "adamw",
           "--learning_rate", "1e-4", "--max_train_steps", str(steps), "--save_every_n_steps", "100",
           "--output_dir", OUT, "--output_name", "pinehost", "--seed", "42",
           "--h3_guidance_loss_scale", "4.0", "--h3_guidance_loss_sigma_min", "0.15",
           "--h3_guidance_loss_uncond_cache", os.path.join(WORK, "uncond.safetensors")]

    def progress(buf: str) -> None:
        import re
        m = None
        for m in re.finditer(r"(\d+)/(\d+) \[", buf):
            pass
        loss = None
        for lm in re.finditer(r"avr_loss=([0-9.]+)", buf):
            loss = float(lm.group(1))
        if m and int(m.group(2)) == steps:
            _state.update(step=int(m.group(1)), of=steps)
        if loss is not None:
            _state["loss"] = loss

    status(state="training", stage="training", step=0, of=steps, why="")
    return governed(cmd, "training", progress=progress, cwd=MUSUBI, env=env)


def newest_save() -> str:
    final = os.path.join(OUT, "pinehost.safetensors")
    if os.path.exists(final):
        return final
    saves = sorted(glob.glob(os.path.join(OUT, "pinehost-*.safetensors")), key=os.path.getmtime)
    return saves[-1] if saves else ""


def install(src: str) -> str:
    dest = os.path.join(MODELS, "loras", LORA_NAME)
    tmp = dest + ".part"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)
    keep = os.path.join(WORK, "installed")
    os.makedirs(keep, exist_ok=True)
    shutil.copyfile(src, os.path.join(keep, time.strftime("%Y%m%d-%H%M%S_") + os.path.basename(src)))
    return dest


# --- the run --------------------------------------------------------------------------
def run(look: str, steps: int, fresh: bool) -> int:
    for f in (STOP,):
        if os.path.exists(f):
            os.remove(f)
    _state.clear()
    status(state="preparing", stage="preparing", started=time.time(), look=look, trigger=TRIGGER,
           of=steps, step=0, lora="", log=os.path.relpath(LOG, REPO))
    for need in (DIT, TEXT_ENCODER, VIDEO_VAE, AUDIO_VAE, os.path.join(MUSUBI, "minimax_h3_train_network.py")):
        if not os.path.exists(need):
            status(state="failed", why="missing " + need)
            return 1
    try:
        made = make_portraits(look, fresh)
        if made < 0:
            status(state="stopped", why="stopped before training")
            return 0
        if made < 8:
            status(state="failed", why="only %d portraits were made - too few to learn a face from" % made)
            return 1
        dataset = write_dataset()
        comfy_free()
        if not wait_ready("caching", need_gb=START_MEM_GB):
            status(state="stopped", why="stopped before caching")
            return 0
        cache(dataset)
        comfy_free()
        if not wait_ready("training", need_gb=START_MEM_GB):
            status(state="stopped", why="stopped before training")
            return 0
        code = train(dataset, steps)
    except Exception as exc:  # noqa: BLE001
        say("failed: %s: %s" % (type(exc).__name__, exc))
        status(state="failed", why="%s: %s" % (type(exc).__name__, str(exc)[:300]))
        return 1
    save = newest_save()
    if not save:
        status(state="failed" if code else "stopped", why="no save was written (exit %s)" % code)
        return 1
    status(state="installing", why=os.path.basename(save))
    dest = install(save)
    done = "done" if code == 0 else "stopped"
    status(state=done, lora=LORA_NAME, installed=dest, from_save=os.path.basename(save), exit=code,
           why=("trained %d steps; turn it on in the gallery's gear (Cast)" % steps) if code == 0
           else "stopped early; the newest save (%s) is installed" % os.path.basename(save), paused=False)
    say("%s: %s -> %s" % (done, save, dest))
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--look", default="")
    ap.add_argument("--steps", type=int, default=0)
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--from-kick", action="store_true", help="read (and consume) data/h3_cast/kick.json")
    args = ap.parse_args(argv)
    os.makedirs(WORK, exist_ok=True)
    look, steps, fresh = args.look, args.steps, args.fresh
    if args.from_kick:
        try:
            with open(KICK, encoding="utf-8") as fh:
                ask = json.load(fh)
            os.remove(KICK)
        except FileNotFoundError:
            return 0
        except (OSError, ValueError) as exc:
            say("kick unreadable: %s" % exc)
            os.remove(KICK)
            return 1
        look = str(ask.get("look") or "")
        steps = int(ask.get("steps") or 0)
        fresh = bool(ask.get("fresh"))
    if look:
        with open(LOOK_FILE, "w", encoding="utf-8") as fh:
            fh.write(look)
        fresh = True
    else:
        try:
            with open(LOOK_FILE, encoding="utf-8") as fh:
                look = fh.read().strip()
        except FileNotFoundError:
            look = ""
    look = look or DEFAULT_LOOK
    steps = max(100, min(2000, steps or 600))
    return run(look, steps, fresh)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
