"""Pure MiniMax H3 workflow assembly for the Pine Box workshop.

The web API owns media lookup and ComfyUI uploads.  This module only turns a
validated request into an API-format graph, which keeps graph tests fast and
prevents them from importing the station runtime.
"""

from __future__ import annotations

from copy import deepcopy
import math
import re
import secrets
from typing import Any


FL2VA_MODEL = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
REF2VA_MODEL = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
TEXT_ENCODER = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
TURBO_LORA = "minimax_h3_turbo_v4_step600_ema.safetensors"

# [h3-free-wins] H3 takes clip lengths on a 17n+5 lattice at 24 fps (5, 22,
# 39, ... 73, 124, 175, 243, 294, 362). 169, 241, 289 and 361 were off it and
# the node snapped them silently; these are exact: about 3, 5, 7, 10, 12, 15 s.
FRAME_LATTICE = 17
FRAME_CHOICES = (73, 124, 175, 243, 294, 362)


def lattice_frames(value: Any) -> int:
    """The nearest length on H3's 17n+5 lattice (never below 5)."""
    try:
        wanted = int(value)
    except (TypeError, ValueError):
        wanted = FRAME_CHOICES[0]
    return max(5, FRAME_LATTICE * int(round((wanted - 5) / FRAME_LATTICE)) + 5)
STEP_CHOICES = (4, 6, 8, 12)

# [h3-quality] THE QUALITY PROFILE. "for H3, double the quality settings ...
# I want to double the quality and resolution at the moment unless it chokes
# the DGX to death." The steps and the frame size the graph renders at, and
# the longest clip that size may run to - set from the gallery's gear, kept
# by the station in data/h3_hourly.json, honoured by every H3 render. Sizes
# are multiples of 64 (the VAE's stride). Doubling the frame quadruples the
# pixels the sampler holds, which is why `double` caps the length and why
# quality_for_box() steps down when the box is hot or short of room.
PRESETS = {
    "standard": {"preset": "standard", "steps": 4, "width": 640, "height": 384, "max_frames": 362},
    "balanced": {"preset": "balanced", "steps": 6, "width": 960, "height": 576, "max_frames": 294},
    "double": {"preset": "double", "steps": 8, "width": 1280, "height": 768, "max_frames": 243},
}
QUALITY = dict(PRESETS["double"])
SIZE_MIN, SIZE_MAX = 384, 1536

# [h3-cinematic] THE BASE PATH. "How come I don't have options like sixteen
# steps or thirty-two steps or sixty-four steps when it comes to getting very
# cinematic fine results?" The turbo LoRA collapses the trajectory into four
# to eight jumps; more steps on it only drift. The base model runs the whole
# trajectory: no turbo LoRA, the res_multistep sampler, 20 to 30 steps
# (Comfy-Org's own H3 templates run 20). It costs two and a half to three
# times the turbo time for the same clip, so it is its own preset with its own
# gate: clips up to five seconds, never the hourly ad, and it starts only on a
# box at or under CINEMATIC_HEAT_C - otherwise the render steps down to the
# double profile and says why. A step count names its path: 4-12 are the
# turbo LoRA's, 20-30 the base model's, and the two lists never overlap.
BASE_STEP_CHOICES = (20, 25, 30)
# 84 C, not 80: measured 2026-09-27 the box idles at 83-88 C between jobs, so an
# 80 C line would never open (a gate that can never pass is an off switch); 84
# is the line the A/B and the cast trainer wait for, and the time budget caps
# how long any cinematic render can run.
CINEMATIC_HEAT_C = 84.0
PRESETS["cinematic"] = {"preset": "cinematic", "steps": 20, "width": 1280, "height": 768, "max_frames": 124,
                        "turbo": False, "sampler": "res_multistep", "scheduler": "simple"}
NO_CINEMATIC_PURPOSES = ("hourly",)

# [h3-budget] THE RENDER-TIME BUDGET. Measured on this box, 2026-09-27: the
# double profile ran a 10 s reference render at ~300 s a step (ComfyUI logged
# 00:50:29 and 00:47:24), the 640x384 / 3 s shape at ~10 s a step. The model
# below reproduces both within about a tenth; a render whose estimate is over
# the budget is stepped down in frame size (never in length - the line needs
# it) until it fits. 0 means no limit.
LOAD_S = 45.0
STEP_S = 10.0
REF_PX = 640 * 384 * 73
STEP_EXP = 1.35
BUDGET_DEFAULT_S = 900
BUDGET_CHOICES = (300, 600, 900, 1800, 3600, 0)
SIZE_LADDER = ((1536, 896), (1280, 768), (960, 576), (640, 384))
QUALITY["budget_s"] = BUDGET_DEFAULT_S


def estimate_seconds(width: Any, height: Any, frames: Any, steps: Any) -> float:
    """[h3-budget] About how long one render of this shape takes on this box."""
    try:
        px = max(1.0, float(width) * float(height) * float(frames))
        return round(LOAD_S + float(steps) * STEP_S * (px / REF_PX) ** STEP_EXP, 1)
    except (TypeError, ValueError):
        return 0.0


def estimates(frames: Any = 243) -> dict[str, float]:
    """[h3-budget] Each preset's estimate for a clip of `frames` (10 s by default)."""
    out = {}
    for name, pr in PRESETS.items():
        out[name] = estimate_seconds(pr["width"], pr["height"], min(int(frames), int(pr["max_frames"])), pr["steps"])
    return out


def fit_budget(profile: dict[str, Any], frames: Any, budget_s: Any) -> tuple[dict[str, Any], str]:
    """[h3-budget] The profile with its frame size stepped down until the
    estimate fits the budget; a note when it had to."""
    try:
        budget = float(budget_s)
        want = min(int(frames), int(profile.get("max_frames") or frames))
    except (TypeError, ValueError):
        return profile, ""
    if budget <= 0 or want <= 0:
        return profile, ""
    first = estimate_seconds(profile["width"], profile["height"], want, profile["steps"])
    if first <= budget:
        return profile, ""
    out = dict(profile)
    was = "%dx%d" % (out["width"], out["height"])
    for w, h in SIZE_LADDER:
        if w * h >= out["width"] * out["height"]:
            continue
        out["width"], out["height"] = w, h
        if estimate_seconds(w, h, want, out["steps"]) <= budget:
            break
    if estimate_seconds(out["width"], out["height"], want, out["steps"]) > budget and out.get("turbo", True) is not False:
        out["steps"] = min(STEP_CHOICES, key=lambda k: abs(k - 4))       # the last rung: the turbo LoRA's own four
    out["preset"] = "custom" if out.get("preset") != "custom" else out["preset"]
    for name, known in PRESETS.items():
        if (all(out.get(k) == known[k] for k in ("steps", "width", "height", "max_frames"))
                and (out.get("turbo", True) is not False) == (known.get("turbo", True) is not False)):
            out["preset"] = name
    took = estimate_seconds(out["width"], out["height"], want, out["steps"])
    return out, ("fitted to the %d-minute budget: %s about %d min, %dx%d%s about %d min"
                 % (round(budget / 60), was, round(first / 60), out["width"], out["height"],
                    "" if out["steps"] == profile["steps"] else " at %d steps" % out["steps"], max(1, round(took / 60))))

# [h3-cast] THE HOST'S FACE. An identity LoRA trained on the Pine Box host
# (tools/h3_cast_train.py, run by the pinebox-h3-cast service) rides a render
# when the cast is on: LoraLoaderModelOnly after the turbo LoRA (or the base
# model) at CAST["strength"], and the brief names the presenter by
# CAST["trigger"] - the word the training captions used. It applies on the
# text road, where no reference brings a face of its own to fight it, or
# when a caller asks for it (cast=True).
CAST_DEFAULTS = {"on": False, "lora": "", "trigger": "pinehost", "strength": 0.9, "who": "the Pine Box host"}
CAST = dict(CAST_DEFAULTS)

# [h3-free-wins] EasyCache skips sampler steps whose model output would barely
# change; the community measures about 1.5x with it. On by default; the A/B
# and a render that smears motion can turn it off (easycache=False).
EASYCACHE_ON = True
EASYCACHE = {"reuse_threshold": 0.2, "start_percent": 0.15, "end_percent": 0.95}
# The sigma shift every published base-model graph carries (12 on video, 3 on
# audio) and the sampler pairing the 8-step turbo guides use (euler + beta).
# Neither is on by default until the A/B on this box says so:
# QUALITY["shift"] = [12, 3]; QUALITY["sampler"] = "euler"; QUALITY["scheduler"] = "beta".
SAMPLER_CHOICES = ("turbo", "euler", "euler_ancestral", "dpmpp_2m", "res_multistep")
SCHEDULER_CHOICES = ("simple", "beta", "normal", "sgm_uniform")

# [h3-brief-config] THE BRIEF'S KNOBS, set from the gallery's gear and kept by the
# station beside the quality profile. Blank means the compiler's own default:
# the style term per road, shots following the reference on a reference road,
# the shot count by length, the standard constraints and audio direction.
BRIEF_DEFAULTS = {"style": "", "follow": "auto", "shots": "auto", "constraints": "", "audio_direction": ""}
BRIEF = dict(BRIEF_DEFAULTS)
FOLLOW_CHOICES = ("auto", "reference", "presenter")
SHOT_CHOICES = ("auto", "1", "2", "3")
DEFAULT_CONSTRAINTS = ("No added subtitles, captions, logos or on-screen text - what the source already shows stays. "
                       "One style only.")
DEFAULT_AUDIO = "One voice only, close and clear; natural room tone; no music; no other voices."


def set_cast(profile: Any) -> dict[str, Any]:
    """[h3-cast] Take the cast from the desk (or the trainer's finished run);
    the clean profile now in force. A LoRA name is one plain file name."""
    if not isinstance(profile, dict):
        return dict(CAST)
    out = dict(CAST)
    if "on" in profile:
        out["on"] = bool(profile.get("on"))
    if "lora" in profile:
        name = str(profile.get("lora") or "").strip()
        out["lora"] = name if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,120}\.safetensors", name) else ""
    if "trigger" in profile:
        word = re.sub(r"[^A-Za-z0-9_-]", "", str(profile.get("trigger") or ""))[:24]
        out["trigger"] = word or CAST_DEFAULTS["trigger"]
    if "strength" in profile:
        try:
            out["strength"] = round(max(0.0, min(1.5, float(profile.get("strength")))), 2)
        except (TypeError, ValueError):
            pass
    if "who" in profile:
        out["who"] = " ".join(str(profile.get("who") or "").split())[:60] or CAST_DEFAULTS["who"]
    CAST.clear()
    CAST.update(out)
    return dict(CAST)


def cast_applies(mode: str = "text", wanted: Any = None) -> bool:
    """[h3-cast] Whether the host's LoRA rides this render: the cast is on and
    trained, and the road is the text road - or the caller said so."""
    if not (CAST.get("on") and CAST.get("lora")):
        return False
    if wanted is not None:
        return bool(wanted)
    return (mode if mode in MODES else "text") == "text"


def set_brief(profile: Any) -> dict[str, Any]:
    """[h3-brief-config] Take the brief's knobs from the desk; the clean set now in force."""
    if not isinstance(profile, dict):
        return dict(BRIEF)
    out = dict(BRIEF)
    if "style" in profile:
        out["style"] = " ".join(str(profile.get("style") or "").split())[:120]
    if "follow" in profile:
        out["follow"] = str(profile.get("follow") or "auto") if str(profile.get("follow") or "auto") in FOLLOW_CHOICES else "auto"
    if "shots" in profile:
        out["shots"] = str(profile.get("shots") or "auto") if str(profile.get("shots") or "auto") in SHOT_CHOICES else "auto"
    for key in ("constraints", "audio_direction"):
        if key in profile:
            out[key] = " ".join(str(profile.get(key) or "").split())[:400]
    BRIEF.clear()
    BRIEF.update(out)
    return dict(BRIEF)
MODES = frozenset({"text", "frame", "reference"})
MEDIA_KINDS = frozenset({"", "image", "video", "audio"})
VIDEO_RENDER_INTERVAL_MIN_S = 60.0
VIDEO_RENDER_INTERVAL_MAX_S = 120.0
VIDEO_RENDER_INTERVAL_DEFAULT_S = 90.0


def render_interval_seconds(value: Any = None) -> float:
    """Clamp the H3 rest interval to the operator-approved safe range."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = VIDEO_RENDER_INTERVAL_DEFAULT_S
    return max(VIDEO_RENDER_INTERVAL_MIN_S,
               min(VIDEO_RENDER_INTERVAL_MAX_S, seconds))


def quoted_speech(value: Any) -> str:
    """Return dialogue enclosed in straight or curly double quotes."""
    text = str(value or "")
    parts = []
    for match in re.finditer(r'"([^"\n]+)"|\u201c([^\u201d\n]+)\u201d', text):
        line = " ".join((match.group(1) or match.group(2) or "").split())
        if line:
            parts.append(line)
    return " ".join(parts)[:800]


def clamp_frames(value: Any) -> int:
    """Snap a frame request to a supported 24 fps H3 length."""
    try:
        wanted = int(value)
    except (TypeError, ValueError):
        wanted = FRAME_CHOICES[0]
    return min(FRAME_CHOICES, key=lambda item: abs(item - wanted))


def duration_frames(duration_s: Any = None, *, prompt: str = "",
                    speech: str = "", reference_s: float = 0.0,
                    duration_mode: str = "auto") -> int:
    """Choose a short default, or meet an explicit/contextual length up to 15s."""
    if duration_s is not None and duration_s != "":
        try:
            wanted = float(duration_s)
            if not 3.0 <= wanted <= 15.0:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("Duration must be between 3 and 15 seconds") from None
    elif reference_s > 0:
        if duration_mode not in {"auto", "reference", "double", "at_least"}:
            raise ValueError("Unknown duration mode")
        doubled = duration_mode == "double" or (duration_mode == "auto" and bool(
            re.search(r"\b(double|twice|2x|two times)\b", prompt, re.I)))
        wanted = reference_s * (2 if doubled else 1)
    else:
        words = len(str(speech or "").split())
        wanted = min(15.0, max(3.0, 3.0 + words / 2.5)) if words else 5.0
        if re.search(r"\b(longer|extended|ten seconds|fifteen seconds)\b", prompt, re.I):
            wanted = max(wanted, 10.0)
    wanted = max(3.0, min(15.0, wanted))
    # A parody must never end before its reference window or exact dialogue.
    # Explicit durations are a contract, so choose the first supported H3
    # length at or above it rather than the mathematically nearest (shorter)
    # frame count.
    if duration_s is not None and duration_s != "" or duration_mode == "at_least":
        return next((item for item in FRAME_CHOICES if item / 24.0 >= wanted),
                    FRAME_CHOICES[-1])
    return min(FRAME_CHOICES, key=lambda item: abs(item / 24.0 - wanted))


def reference_window(source_s: float, at_share: float = 0.0,
                     trim_in_s: Any = None,
                     trim_out_s: Any = None) -> tuple[float, float]:
    """Return (start, length) for the video bytes uploaded to H3."""
    duration = float(source_s)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("The selected video has no measurable duration")
    if trim_in_s is not None or trim_out_s is not None:
        if trim_in_s is None or trim_out_s is None:
            raise ValueError("Choose both video trim points")
        try:
            start, end = float(trim_in_s), float(trim_out_s)
        except (TypeError, ValueError):
            raise ValueError("Video trim points must be seconds") from None
        if not all(math.isfinite(value) for value in (start, end)):
            raise ValueError("Video trim points must be finite")
        if start < 0 or start >= duration or end > duration + 0.05:
            raise ValueError("Video trim points are outside the source")
        length = min(end, duration) - start
        if not 2.2 <= length <= 15.0:
            raise ValueError("Video trim must be between 2.2 and 15 seconds")
        return start, length
    try:
        share = float(at_share)
    except (TypeError, ValueError):
        share = 0.0
    share = max(0.0, min(1.0, share if math.isfinite(share) else 0.0))
    length = min(15.0, max(2.2, duration))
    return max(0.0, (duration - length) * share), length


def clamp_steps(value: Any, turbo: Any = None) -> int:
    """The Turbo LoRA runs at four to six steps; eight and twelve are the
    doubled profile's (quality over speed). [h3-cinematic] The base path
    (turbo=False) runs 20, 25 or 30. Without `turbo` the number chooses:
    anything from 16 up is a base-path count."""
    try:
        wanted = int(value)
    except (TypeError, ValueError):
        wanted = STEP_CHOICES[0] if turbo is not False else BASE_STEP_CHOICES[0]
    base = (turbo is False) or (turbo is None and wanted >= 16)
    choices = BASE_STEP_CHOICES if base else STEP_CHOICES
    return min(choices, key=lambda item: abs(item - wanted))


def is_turbo_steps(steps: Any) -> bool:
    """[h3-cinematic] A step count names its path: 4-12 the turbo LoRA's,
    20-30 the base model's."""
    try:
        return int(steps) < 16
    except (TypeError, ValueError):
        return True


def set_quality(profile: Any) -> dict[str, Any]:
    """[h3-quality] Take a profile from the desk; the clean one now in force.
    A preset name alone selects the preset; any explicit field makes it
    custom (a custom equal to a preset is named as that preset)."""
    if not isinstance(profile, dict):
        return dict(QUALITY)
    preset = str(profile.get("preset") or "").strip().lower()
    fields = ("steps", "width", "height", "max_frames")
    explicit = fields + ("shift", "sampler", "scheduler", "easycache", "turbo")
    base = dict(PRESETS.get(preset) or QUALITY)
    budget = QUALITY.get("budget_s", BUDGET_DEFAULT_S)                   # [h3-budget]
    if "budget_s" in profile:
        try:
            budget = max(0, min(7200, int(profile.get("budget_s") or 0)))
        except (TypeError, ValueError):
            pass
    if preset in PRESETS and not any(k in profile for k in explicit):
        QUALITY.clear()
        QUALITY.update(base)
        QUALITY["budget_s"] = budget
        return dict(QUALITY)
    out = dict(base)
    out["budget_s"] = budget
    for key in ("width", "height"):
        if key in profile:
            try:
                out[key] = max(SIZE_MIN, min(SIZE_MAX, (int(profile[key]) // 64) * 64))
            except (TypeError, ValueError):
                pass
    if "turbo" in profile:                                    # [h3-cinematic]
        out["turbo"] = profile.get("turbo") is not False
    if "steps" in profile:
        out["steps"] = clamp_steps(profile["steps"], out.get("turbo", True) is not False)
    elif out.get("turbo", True) is False and is_turbo_steps(out.get("steps")):
        out["steps"] = BASE_STEP_CHOICES[0]
    elif out.get("turbo", True) is not False and not is_turbo_steps(out.get("steps")):
        out["steps"] = 8
    if "max_frames" in profile:
        out["max_frames"] = clamp_frames(profile["max_frames"])
    # [h3-free-wins] the graph knobs the A/B compares; a preset name clears them
    if "shift" in profile:
        shift = profile.get("shift")
        try:
            out["shift"] = [round(float(shift[0]), 2), round(float(shift[1]), 2)] if shift else None
        except (TypeError, ValueError, IndexError):
            out["shift"] = None
    if "sampler" in profile:
        out["sampler"] = str(profile.get("sampler") or "turbo") if str(profile.get("sampler") or "turbo") in SAMPLER_CHOICES else "turbo"
    if out.get("turbo", True) is False and out.get("sampler", "turbo") == "turbo":
        out["sampler"] = "res_multistep"               # [h3-cinematic] the turbo sampler is the LoRA's
    if "scheduler" in profile:
        out["scheduler"] = str(profile.get("scheduler") or "simple") if str(profile.get("scheduler") or "simple") in SCHEDULER_CHOICES else "simple"
    if "easycache" in profile:
        out["easycache"] = bool(profile.get("easycache"))
    out["preset"] = "custom"
    for name, known in PRESETS.items():
        if (all(out.get(k) == known[k] for k in fields)
                and (out.get("turbo", True) is not False) == (known.get("turbo", True) is not False)):
            out["preset"] = name
    if out.get("turbo", True) is not False:
        out.pop("turbo", None)                         # a turbo profile reads as it always did
    QUALITY.clear()
    QUALITY.update(out)
    return dict(QUALITY)


def quality_for_box(hot_c: Any, available_gb: Any, ceiling_c: Any, reserve_gb: Any,
                    purpose: str = "", frames: Any = None) -> tuple[dict[str, Any], str]:
    """[h3-budget] With `frames`, the result is also fitted to the render-time
    budget; the rest is quality_for_heat()'s."""
    profile, note = quality_for_heat(hot_c, available_gb, ceiling_c, reserve_gb, purpose)
    if frames is None:
        return profile, note
    fitted, why = fit_budget(profile, frames, QUALITY.get("budget_s", BUDGET_DEFAULT_S))
    if not why:
        return profile, note
    return fitted, (note + "; then " + why) if note else why


def quality_for_heat(hot_c: Any, available_gb: Any, ceiling_c: Any, reserve_gb: Any,
                     purpose: str = "") -> tuple[dict[str, Any], str]:
    """[h3-quality] The profile THIS render may use. A profile above the
    standard one asks more of the box than render_admission's gates: eight
    degrees under the ceiling and 30 GB above the reserve. Short of either it
    steps down - double to balanced, balanced to standard - and says so.
    The render still passes render_admission afterwards; this is the extra
    margin the bigger frame needs, not a replacement for the gate."""
    profile = dict(QUALITY)
    lead = ""
    if profile.get("turbo", True) is False:                   # [h3-cinematic]
        why = []
        if str(purpose or "").strip().lower() in NO_CINEMATIC_PURPOSES:
            why.append("the cinematic path never renders the hourly ad")
        try:
            if hot_c is None:
                why.append("the box will not say how hot it is")
            elif float(hot_c) > CINEMATIC_HEAT_C:
                why.append("%.0f C - the cinematic path starts only at or under %.0f C"
                           % (float(hot_c), CINEMATIC_HEAT_C))
        except (TypeError, ValueError):
            why.append("the box's heat reading is not a number")
        try:
            if available_gb is not None and reserve_gb and float(available_gb) < float(reserve_gb) + 30:
                why.append("%.0f GB free against %.0f GB needed" % (float(available_gb), float(reserve_gb) + 30))
        except (TypeError, ValueError):
            pass
        if not why:
            return profile, ""
        profile = dict(PRESETS["double"])
        lead = "cinematic stepped down to double for this render: " + "; ".join(why)
    standard = PRESETS["standard"]
    heavy = profile["width"] * profile["height"] > standard["width"] * standard["height"] or profile["steps"] > 6
    if not heavy:
        return profile, lead
    tight = []
    try:
        if hot_c is not None and ceiling_c and float(hot_c) > float(ceiling_c) - 8:
            tight.append("%.0f C against a %.0f C ceiling" % (float(hot_c), float(ceiling_c)))
    except (TypeError, ValueError):
        pass
    try:
        if available_gb is not None and reserve_gb and float(available_gb) < float(reserve_gb) + 30:
            tight.append("%.0f GB free against %.0f GB needed" % (float(available_gb), float(reserve_gb) + 30))
    except (TypeError, ValueError):
        pass
    if not tight:
        return profile, lead
    balanced = PRESETS["balanced"]
    lighter = (profile["width"] * profile["height"] > balanced["width"] * balanced["height"]
               or profile["steps"] > balanced["steps"])
    down = dict(balanced if lighter else standard)
    note = "stepped down to %s for this render: %s" % (down["preset"], "; ".join(tight))
    return down, (lead + "; then " + note) if lead else note


def render_seed(value: Any = None) -> int:
    """A real variant gets a fresh noise field; an explicit seed is repeatable."""
    if value is None or value == "":
        return secrets.randbits(63)
    try:
        return max(0, min((1 << 63) - 1, int(value)))
    except (TypeError, ValueError):
        return secrets.randbits(63)


def shot_list(seconds: float, said: str, subject: str = "<Subject 1>", source: str = "<Video 1>",
              follow: bool = True, count: Any = None) -> list[str]:
    """[h3-brief] Timed shots the way H3's 32B text encoder reads a brief.
    `follow`: the shots follow the reference's own action, framing and camera
    (a reference road) instead of prescribing a presenter's moves - the brief
    also asks to keep the motion of <Video 1>, and the two must not fight.
    The count follows the clip: one shot under 5 s, two under 8 s, three from
    8 s; untimed when the length is unknown. The line sits in the middle and
    is spoken exactly once."""
    try:
        total = float(seconds or 0)
    except (TypeError, ValueError):
        total = 0.0
    span = lambda x, y: f"[{x:g} to {y:g} seconds]"  # noqa: E731
    line = (f"{subject} (S1) says clearly, naturally and exactly once: <d>[English] {said}</d>; "
            "the sentence completes before the shot ends; no other intelligible speech."
            if said else f"{subject} performs without required spoken dialogue.")
    if follow:
        act = f"the action, framing and camera movement of {source} continue as they are"
        opening = f"{subject} as {source} shows them; {act}; no speech yet."
        closing = f"{act} to the end; {subject} finishes the movement {source} was making; nothing is added on screen."
    else:
        act = "natural movement in the scene with one camera move"
        opening = f"{subject} in place; {act}; no speech yet."
        closing = f"{subject} holds the last beat for the cut; nothing is added on screen."
    try:
        want = int(count) if count not in (None, "", "auto") else 0
    except (TypeError, ValueError):
        want = 0
    if total <= 0:
        return [f"[Shot 1] {opening}", f"[Shot 2] {line}", f"[Shot 3] {closing}"]
    if want == 1 or (want == 0 and total < 5.0):
        return [f"{span(0, total)} One shot: {act}; midway, {line}"]
    if want == 2 or (want == 0 and total < 8.0):
        a = round(total * 0.6, 1)
        return [f"{span(0, a)} {opening.replace('; no speech yet.', '.')} Then {line}",
                f"{span(a, total)} {closing}"]
    a = round(max(0.8, total * 0.25), 1)
    b = round(max(a + 1.0, total * 0.8), 1)
    return [f"{span(0, a)} {opening}", f"{span(a, b)} {line}", f"{span(b, total)} {closing}"]


def style_for(purpose: str = "", mode: str = "text", media_kind: str = "") -> str:
    """[h3-brief] ONE style term per road (two make H3 pick one at random):
    an ad or a stinger is a polished broadcast commercial; a render off a
    gallery picture or a clip takes that source's style; free direction gets
    a clean default it can override by naming its own style."""
    road = str(purpose or "").strip().lower()
    if road in ("parody_stinger", "voice_ad", "image_ad", "ad", "stinger", "hourly"):
        return "polished broadcast commercial"
    if mode == "reference" and media_kind == "video":
        return "the style of <Video 1>, as it is"
    if (mode == "reference" and media_kind == "image") or mode == "frame":
        return "the style of <Picture 1>, as it is"
    return "clean cinematic realism"


def compose_prompt(prompt: str, speech: str = "", media_kind: str = "",
                   mode: str = "text", seconds: float = 0.0, purpose: str = "",
                   style: Any = None, cast: Any = None) -> str:
    """Build H3's reference-aware prompt, including an exact dialogue contract.

    [h3-free-wins] The brief reads like production paperwork: a role for
    every reference, timecoded shots, the sound directed as deliberately as
    the picture, constraints, and ONE style term (two styles make H3 pick
    one at random per generation)."""
    clean = " ".join(str(prompt or "").split())[:900]
    # Dialogue markup is model syntax, not user-authored HTML.  Strip any
    # accidental tags before placing the source line inside H3's <d> block.
    said = re.sub(r"<[^>]+>", "", " ".join(str(speech or "").split()))[:700]
    kind = media_kind if media_kind in MEDIA_KINDS else ""
    use_mode = mode if mode in MODES else "text"
    style_term = (" ".join(str(style or "").split())[:120] or BRIEF.get("style")
                  or style_for(purpose, use_mode, kind))                                  # [h3-brief][h3-brief-config]
    follow_pref = BRIEF.get("follow") or "auto"
    shot_count = BRIEF.get("shots") or "auto"
    constraints_line = BRIEF.get("constraints") or ""
    audio_line = BRIEF.get("audio_direction") or ""

    # MiniMax H3's full-reference format makes both sides of the source
    # explicit: the picture is <Video 1>; its paired sound is <Audio 1>.
    # It also needs a physical speaker id and <d>[language] text</d> for
    # speech that must be performed rather than merely described.
    if use_mode == "reference" and kind == "video":
        visual = clean or "A concise Pine Box FM commercial performance"
        if said:
            # Do not leave a second free-form copy of the line in the visual
            # direction: it competes with the exact-dialect dialogue block.
            visual = visual.replace(said, "the scripted commercial line")
            visual = visual.replace('"' + said + '"', "the scripted commercial line")
            visual = visual.replace("'" + said + "'", "the scripted commercial line")
            dialogue = (
                "<Subject 1> (S1) says clearly, naturally, and exactly once: "
                f"<d>[English] {said}</d>. Ensure the sentence completes before "
                "the end of the clip. No other spoken words, voice-over, "
                "background speech, lyrics, or competing vocal sounds.")
            soundscape = ("Natural quiet room tone and subtle diegetic movement only. "
                          "The target dialogue is the only intelligible speech.")
        else:
            dialogue = ("<Subject 1> (S1) performs the action naturally without any "
                        "required spoken dialogue.")
            soundscape = "Natural diegetic sound and quiet room tone only."
        shots = shot_list(seconds, said, follow=(follow_pref != "presenter"), count=shot_count)
        return "\n".join((
            "subject_definitions:",
            "<Subject 1> is the primary visible performer in <Video 1>.",
            "<Audio 1>: reference - the paired soundtrack of <Video 1> provides "
            "vocal timbre, cadence, and natural room texture for <Subject 1> (S1). "
            "Do not reuse its source words.",
            "", "summary:",
            "Create one continuous, polished performance that retains the identity, "
            "camera language, and motion of <Video 1> while producing new synchronized speech.",
            "", "style:", f"{style_term} - one style only, no second style.",
            "", "retention_analysis:",
            "<Subject 1>: preserve the visible person's identity, facial features, "
            "hair, clothing, body language, and performance energy from <Video 1>.",
            "<Video 1>: preserve its visual identity, camera movement, and temporal rhythm.",
            "<Audio 1>: reference only for timbre, cadence, and room character; do not copy source words.",
            "", "detailed_description:",
            f"Scene: {visual}.",                     # the line itself is in the performance shot, once
            *shots,
            "", "audio_direction:",
            audio_line or ("Only <Subject 1>'s voice, in the timbre and cadence of <Audio 1>; the room tone of <Video 1> "
                           "under it; clothing and movement sounds where the picture shows them; no other voices."),
            "", "overall_soundscape:", soundscape,
            "", "non_diegetic_music:", "No background music.",
            "", "constraints:",
            (constraints_line + " " if constraints_line else
             "No added subtitles, captions, logos or on-screen text - what <Video 1> already shows stays. One style only. ")
            + "Preserve <Subject 1>'s identity exactly. The scripted line is spoken once and completes.",
        ))[:3400]

    lead = clean or "A concise cinematic station ident"
    if use_mode == "reference":
        if kind == "image":
            lead = f"Use <Picture 1> as the visual identity. {lead}"
        elif kind == "video":
            lead = f"Keep the person and visual identity from <Video 1>. {lead}"
        elif kind == "audio":
            lead = f"Use <Audio 1> as the sound reference. {lead}"
    # [h3-cast] the host's LoRA answers to its trigger word
    presenter = ("%s, %s" % (CAST.get("trigger") or "pinehost", CAST.get("who") or "the Pine Box host")
                 if cast_applies(use_mode, cast) else "")
    if presenter:
        lead = f"{lead} The presenter is {presenter}."
    if said:
        lead += f" The presenter says exactly once: <d>[English] {said}</d>."
    # [h3-free-wins] timed shots, sound and constraints for the text and frame roads too
    subject = "<Picture 1>'s subject" if (use_mode == "reference" and kind == "image") or use_mode == "frame" else (presenter or "the presenter")
    source = "<Picture 1>" if subject.startswith("<Picture") else "the scene"
    follow_here = (source != "the scene") if follow_pref == "auto" else follow_pref == "reference"
    shots = shot_list(seconds, said, subject=subject, source=source, follow=follow_here, count=shot_count)
    return "\n".join((
        lead, "", "style:", f"{style_term} - one style only.",
        "", "shots:", *shots,
        "", "audio_direction:", audio_line or DEFAULT_AUDIO,
        "", "constraints:", constraints_line or DEFAULT_CONSTRAINTS,
    ))[:3400]


def _base_graph(prompt: str, frames: int, steps: int,
                model_name: str, seed: int) -> dict[str, Any]:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": model_name, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": TEXT_ENCODER, "type": "minimax",
            "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": VIDEO_VAE}},
        "4": {"class_type": "VAELoader", "inputs": {
            "vae_name": AUDIO_VAE}},
        "5": {"class_type": "MiniMaxH3TurboLoRA", "inputs": {
            "model": ["1", 0], "lora_name": TURBO_LORA,
            "strength": 1.0, "low_vram": True}},
        "7": {"class_type": "BasicGuider", "inputs": {
            "model": ["5", 0], "conditioning": ["6", 0]}},
        "8": {"class_type": "BasicScheduler", "inputs": {
            "model": ["5", 0], "scheduler": "simple", "steps": steps,
            "denoise": 1.0}},
        "9": {"class_type": "MiniMaxH3TurboSampler", "inputs": {}},
        "10": {"class_type": "RandomNoise", "inputs": {
            "noise_seed": seed}},
        "11": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["10", 0], "guider": ["7", 0],
            "sampler": ["9", 0], "sigmas": ["8", 0],
            "latent_image": ["6", 1]}},
        "12": {"class_type": "VAEDecode", "inputs": {
            "samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "VAEDecodeAudio", "inputs": {
            "samples": ["11", 0], "vae": ["4", 0]}},
        "14": {"class_type": "CreateVideo", "inputs": {
            "images": ["12", 0], "fps": 24.0, "audio": ["13", 0]}},
        "15": {"class_type": "SaveVideo", "inputs": {
            "video": ["14", 0], "filename_prefix": "sfx_ads/PineBox-H3",
            "format": "auto", "codec": "auto"}},
    }


def build_workflow(prompt: str, mode: str = "text", upload_name: str = "",
                   media_kind: str = "", frames: Any = 73,
                   steps: Any = None, seed: Any = None, width: Any = None,
                   height: Any = None, max_frames: Any = None, easycache: Any = None,
                   shift: Any = None, sampler: Any = None, scheduler: Any = None,
                   turbo: Any = None, cast: Any = None) -> dict[str, Any]:
    """Return an API-format H3 graph for text, first-frame, or reference use.

    ``upload_name`` is a name already accepted by ComfyUI's input upload road.
    Dynamic MiniMax reference inputs are serialized as the flat
    dotted ``ref_images.ref_image_0``/``ref_videos.ref_video_0`` keys expected
    by COMFY_AUTOGROW_V3.
    """
    use_mode = mode if mode in MODES else "text"
    kind = media_kind if media_kind in MEDIA_KINDS else ""
    name = str(upload_name or "").strip()
    if use_mode != "text" and not name:
        raise ValueError("A media source is required for this mode")
    if use_mode == "frame" and kind not in {"image", "video"}:
        raise ValueError("Frame mode needs an image or video source")
    if use_mode == "reference" and kind not in {"image", "video", "audio"}:
        raise ValueError("Reference mode needs image, video, or audio media")

    # [h3-quality] the profile in force, unless the caller says otherwise
    cap = clamp_frames(max_frames if max_frames is not None else QUALITY.get("max_frames") or max(FRAME_CHOICES))
    frame_count = min(clamp_frames(frames), cap)
    # [h3-cinematic] the path: the caller's word, else the steps' (a count names
    # its path), else the profile's
    if turbo is not None:
        use_turbo = turbo is not False
    elif steps is not None:
        use_turbo = is_turbo_steps(steps)
    else:
        use_turbo = QUALITY.get("turbo", True) is not False
    step_count = clamp_steps(steps if steps is not None else QUALITY.get("steps"), use_turbo)
    frame_w = int(width or QUALITY.get("width") or 640)
    frame_h = int(height or QUALITY.get("height") or 384)
    noise_seed = render_seed(seed)
    model = REF2VA_MODEL if use_mode == "reference" else FL2VA_MODEL
    graph = _base_graph(prompt, frame_count, step_count, model, noise_seed)
    # [h3-free-wins] the model chain after the LoRA: shift (when asked) -> cache (on
    # by default) -> the guider and the scheduler; the sampler pairing when asked.
    # [h3-cinematic] a render on the other path than the profile's (cinematic
    # stepped down to double) takes that path's defaults, not the profile's knobs
    same_path = use_turbo == (QUALITY.get("turbo", True) is not False)
    knobs = QUALITY if same_path else {}
    use_shift = knobs.get("shift") if shift is None else shift
    use_cache = (EASYCACHE_ON if knobs.get("easycache") is None else bool(knobs.get("easycache"))) if easycache is None else bool(easycache)
    use_sampler = str(sampler or knobs.get("sampler") or "turbo")
    use_sched = str(scheduler or knobs.get("scheduler") or "simple")
    tail = "5"
    if not use_turbo:                                          # [h3-cinematic] the base path
        graph.pop("5", None)
        tail = "1"
        if use_sampler == "turbo":
            use_sampler = "res_multistep"
    if cast_applies(use_mode, cast):                           # [h3-cast] the host's face
        graph["20"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": [tail, 0], "lora_name": CAST["lora"],
            "strength_model": float(CAST.get("strength") or 0.9)}}
        tail = "20"
    if use_shift:
        graph["19"] = {"class_type": "MiniMaxH3SigmaShift", "inputs": {
            "model": [tail, 0], "shift_video": float(use_shift[0]), "shift_audio": float(use_shift[1])}}
        tail = "19"
    if use_cache:
        graph["18"] = {"class_type": "EasyCache", "inputs": {"model": [tail, 0], "verbose": False, **EASYCACHE}}
        tail = "18"
    graph["7"]["inputs"]["model"] = [tail, 0]
    graph["8"]["inputs"]["model"] = [tail, 0]
    graph["8"]["inputs"]["scheduler"] = use_sched if use_sched in SCHEDULER_CHOICES else "simple"
    if use_sampler != "turbo" and use_sampler in SAMPLER_CHOICES:
        graph["9"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": use_sampler}}

    if use_mode in {"text", "frame"}:
        inputs: dict[str, Any] = {
            "clip": ["2", 0], "vae": ["3", 0], "prompt": prompt,
            "width": frame_w, "height": frame_h, "length": frame_count,
        }
        if use_mode == "frame":
            graph["16"] = {"class_type": "LoadImage", "inputs": {
                "image": name}}
            inputs["first_frame"] = ["16", 0]
        graph["6"] = {"class_type": "MiniMaxH3ImageToVideo",
                      "inputs": inputs}
        return deepcopy(graph)

    inputs = {
        "clip": ["2", 0], "vae": ["3", 0], "audio_vae": ["4", 0],
        "prompt": prompt, "width": frame_w, "height": frame_h,
        "length": frame_count, "ref_image_size": "match",
    }
    if kind == "image":
        graph["16"] = {"class_type": "LoadImage", "inputs": {
            "image": name}}
        inputs["ref_images.ref_image_0"] = ["16", 0]
    elif kind == "video":
        graph["16"] = {"class_type": "LoadVideo", "inputs": {"file": name}}
        graph["17"] = {"class_type": "GetVideoComponents", "inputs": {
            "video": ["16", 0]}}
        inputs["ref_videos.ref_video_0"] = ["17", 0]
        inputs["ref_video_audios.ref_video_audio_0"] = ["17", 1]
    else:
        graph["16"] = {"class_type": "LoadAudio", "inputs": {
            "audio": name}}
        inputs["ref_audios.ref_audio_0"] = ["16", 0]
    graph["6"] = {"class_type": "MiniMaxH3ReferenceToVideo",
                  "inputs": inputs}
    return deepcopy(graph)
