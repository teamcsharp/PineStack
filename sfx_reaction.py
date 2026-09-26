"""Occasional presenter reactions to the SFX board."""
from __future__ import annotations

import os
import random
import time


COMPLAINT_LINES = (
    "That one came in sideways.",
    "The board has opinions again.",
    "I am choosing to believe that was deliberate.",
    "Put a little warning light on that button.",
    "That clip just walked through the door like it pays rent.",
    "The sound booth is awake, unfortunately.",
)

_LAST = 0.0


def complaint_due(now: float | None = None) -> bool:
    """Return true for a rested, low-frequency reaction."""
    global _LAST
    now = time.time() if now is None else float(now)
    rest = float(os.getenv("SFX_REACTION_REST_SECONDS", "90") or 90)
    rate = max(0.0, min(1.0, float(os.getenv("SFX_REACTION_RATE", "0.12") or 0.12)))
    if now - _LAST < rest:
        return False
    if random.random() >= rate:
        return False
    _LAST = now
    return True
