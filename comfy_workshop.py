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

FRAME_CHOICES = (73, 124, 169, 241, 289, 361)  # about 3, 5, 7, 10, 12, 15 seconds
STEP_CHOICES = (4, 6)
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
    """Choose a short default, or follow explicit/contextual length up to 15s."""
    if duration_mode not in {"auto", "reference", "double", "at_least"}:
        raise ValueError("Unknown duration mode")
    maximum_s = max(FRAME_CHOICES) / 24.0
    if duration_s is not None and duration_s != "":
        try:
            wanted = float(duration_s)
            if not 3.0 <= wanted <= maximum_s:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("Duration must be between 3 and 15 seconds") from None
    elif reference_s > 0:
        doubled = duration_mode == "double" or (duration_mode == "auto" and bool(
            re.search(r"\b(double|twice|2x|two times)\b", prompt, re.I)))
        wanted = reference_s * (2 if doubled else 1)
    else:
        words = len(str(speech or "").split())
        wanted = min(15.0, max(3.0, 3.0 + words / 2.5)) if words else 5.0
        if re.search(r"\b(longer|extended|ten seconds|fifteen seconds)\b", prompt, re.I):
            wanted = max(wanted, 10.0)
    wanted = max(3.0, min(maximum_s, wanted))
    if duration_mode == "at_least":
        return next((frames for frames in FRAME_CHOICES
                     if frames / 24.0 >= wanted), FRAME_CHOICES[-1])
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


def clamp_steps(value: Any) -> int:
    """The Turbo LoRA is useful at four to six steps on this machine."""
    try:
        wanted = int(value)
    except (TypeError, ValueError):
        wanted = STEP_CHOICES[0]
    return min(STEP_CHOICES, key=lambda item: abs(item - wanted))


def render_seed(value: Any = None) -> int:
    """A real variant gets a fresh noise field; an explicit seed is repeatable."""
    if value is None or value == "":
        return secrets.randbits(63)
    try:
        return max(0, min((1 << 63) - 1, int(value)))
    except (TypeError, ValueError):
        return secrets.randbits(63)


def compose_prompt(prompt: str, speech: str = "", media_kind: str = "",
                   mode: str = "text") -> str:
    """Add explicit H3 reference tags and an optional spoken DJ line."""
    clean = " ".join(str(prompt or "").split())[:1800]
    said = " ".join(str(speech or "").split())[:800]
    kind = media_kind if media_kind in MEDIA_KINDS else ""
    use_mode = mode if mode in MODES else "text"

    lead = clean or "A concise cinematic station ident"
    if use_mode == "reference":
        if kind == "image":
            lead = f"Use <Picture 1> as the visual identity. {lead}"
        elif kind == "video":
            lead = f"Keep the person and visual identity from <Video 1>. {lead}"
        elif kind == "audio":
            lead = f"Use <Audio 1> as the sound reference. {lead}"
    if said:
        lead += f' The presenter says exactly: "{said}"'
    return lead[:2600]


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
                   steps: Any = 4, seed: Any = None) -> dict[str, Any]:
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

    frame_count = clamp_frames(frames)
    step_count = clamp_steps(steps)
    noise_seed = render_seed(seed)
    model = REF2VA_MODEL if use_mode == "reference" else FL2VA_MODEL
    graph = _base_graph(prompt, frame_count, step_count, model, noise_seed)

    if use_mode in {"text", "frame"}:
        inputs: dict[str, Any] = {
            "clip": ["2", 0], "vae": ["3", 0], "prompt": prompt,
            "width": 640, "height": 384, "length": frame_count,
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
        "prompt": prompt, "width": 640, "height": 384,
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
