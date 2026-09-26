"""Small SFX cue selection helpers.

The broadcast path asks for a cue family, not a file.  Keep that decision
pure and cheap so a missing preference never blocks the round assembler.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence


@dataclass(frozen=True)
class CueCandidate:
    key: str
    weight: float = 1.0
    video: bool = False


def choose_due_cue(
    candidates: Iterable[CueCandidate],
    *,
    max_seconds: float = 0.0,
    random_float: Callable[[], float] | None = None,
    pick: Callable[[Sequence[str]], str] | None = None,
    video_share: float = 0.0,
) -> CueCandidate | None:
    """Choose a cue candidate without touching media storage.

    `video_share` is a preference, not a hard requirement.  If the preferred
    family is absent, all candidates remain eligible.
    """
    rows = [row for row in candidates if row and float(row.weight or 0) > 0]
    if not rows:
        return None
    share = max(0.0, min(1.0, float(video_share or 0.0)))
    rand = random_float or (lambda: 0.0)
    prefer_video = bool(rand() < share)
    pool = [row for row in rows if bool(row.video) == prefer_video] or rows
    if pick:
        chosen = pick([row.key for row in pool])
        for row in pool:
            if row.key == chosen:
                return row
    total = sum(float(row.weight or 0) for row in pool)
    mark = max(0.0, min(1.0, rand())) * total
    upto = 0.0
    for row in pool:
        upto += float(row.weight or 0)
        if mark <= upto:
            return row
    return pool[-1]
