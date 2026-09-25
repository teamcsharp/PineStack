"""Preauthored host complaints after a confirmed audible board clip."""

import hashlib
import random
from collections.abc import Callable, Collection, Mapping
from typing import Any


COMPLAINT_LINES = (
    "Ugh. Was that necessary?",
    "Do we need to do that every single time?",
    "I hate that button. I hate it.",
    "That was inappropriate and you know it.",
    "Every time. Every time with that thing.",
    "Warn me before you hit that. Please.",
)

_NOT_HEARD = frozenset({"omitted", "withdrawn", "never", "muted"})


def complaint_due(random_float: Callable[[], float] = random.random) -> bool:
    """Make one one-in-three draw; the random source is injectable for tests."""
    return random_float() < 1.0 / 3.0


def complaint_after_heard_clip(
    clip: Mapping[str, Any],
    *,
    heard_ids: Collection[str],
    prior_speaker: str,
    random_float: Callable[[], float] = random.random,
) -> dict[str, str] | None:
    """Return a reply cue only after this board row has an audible receipt.

    ``heard_ids`` contains completed row IDs, not sample IDs or publication
    events. The caller remains responsible for recording and scheduling the cue.
    """
    clip_id = str(clip.get("id") or "")
    if (not clip_id or clip_id not in heard_ids
            or clip.get("who") != "board" or clip.get("kind") != "sfx"
            or str(clip.get("aired") or "").lower() in _NOT_HEARD
            or prior_speaker not in ("dj", "cohost", "third")):
        return None
    if not complaint_due(random_float):
        return None

    who = "dj" if prior_speaker == "cohost" else "cohost"
    index = int.from_bytes(hashlib.sha256(clip_id.encode("utf-8")).digest()[:8], "big")
    return {"who": who, "text": COMPLAINT_LINES[index % len(COMPLAINT_LINES)],
            "after_clip_id": clip_id}
