"""Pure choice for one already-due SFX cue.

The caller supplies cached, validated metadata and owns the due roll, file checks,
playout, and history. ``pick`` may wrap the station's weighted/unrepeated draw;
``match`` may wrap its semantic matcher. Both receive only eligible keys from one
media side, so neither can make this helper select an overlong or barred cue.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Callable, Generic, Literal, Sequence, TypeVar


T = TypeVar("T")
VIDEO_SHARE = 0.8


@dataclass(frozen=True)
class CueCandidate(Generic[T]):
    key: T
    duration_seconds: float
    video: bool
    eligible: bool = True


@dataclass(frozen=True)
class CueChoice(Generic[T]):
    key: T
    video: bool
    requested_video: bool
    source: Literal["semantic", "random"]


def choose_due_cue(
    candidates: Sequence[CueCandidate[T]],
    *,
    max_seconds: float,
    random_float: Callable[[], float],
    pick: Callable[[tuple[T, ...]], T | None],
    preceding_line: str = "",
    semantic_enabled: bool = False,
    match: Callable[[str, tuple[T, ...]], T | None] | None = None,
    video_share: float = VIDEO_SHARE,
) -> CueChoice[T] | None:
    """Choose one cue, drawing video at the configured share on each due call.

    Invalid/overlong/ineligible candidates never reach either selector. The
    selected side has first refusal; an empty or unpickable side falls back to
    the other. A callback result outside its offered keys is rejected.
    """
    if not isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("max_seconds must be finite and positive")
    if not isfinite(video_share) or not 0 <= video_share <= 1:
        raise ValueError("video_share must be between zero and one")

    video_keys: list[T] = []
    audio_keys: list[T] = []
    for candidate in candidates:
        duration = candidate.duration_seconds
        if (candidate.eligible and isfinite(duration)
                and 0 < duration <= max_seconds):
            (video_keys if candidate.video else audio_keys).append(candidate.key)

    if not video_keys and not audio_keys:
        return None

    draw = random_float()
    if not isfinite(draw) or not 0 <= draw < 1:
        raise ValueError("random_float must return a value in [0, 1)")
    requested_video = draw < video_share

    for video, keys in ((requested_video, video_keys if requested_video else audio_keys),
                        (not requested_video, audio_keys if requested_video else video_keys)):
        offered = tuple(keys)
        if not offered:
            continue
        if semantic_enabled and preceding_line.strip() and match is not None:
            try:
                matched = match(preceding_line, offered)
            except Exception:  # A failed optional matcher must not block a due cue.
                matched = None
            if matched is not None and matched in offered:
                return CueChoice(matched, video, requested_video, "semantic")
        try:
            chosen = pick(offered)
        except Exception:
            chosen = None
        if chosen is not None and chosen in offered:
            return CueChoice(chosen, video, requested_video, "random")
    return None
