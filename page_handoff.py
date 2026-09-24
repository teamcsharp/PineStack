"""Pure decisions for handing page audio to a replacement listener.

The caller supplies the ordered page feed and an owner generation. This module
does not grant the audio lease, pause a player, persist receipts, or serve clips.
In particular, a crash receipt is not an exact stop position: its bounded
rewind is explicitly uncertain, unlike a confirmed pause-and-yield.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Sequence


END_TOLERANCE_S = 0.5
CRASH_REWIND_S = 2.0
MAX_CRASH_REWIND_S = 2.0


@dataclass(frozen=True)
class Clip:
    delivery_id: str
    duration_s: float


@dataclass(frozen=True)
class Receipt:
    delivery_id: str
    listener_id: str
    generation: int
    sequence: int
    event: str  # playing, ended, or yielded
    position_s: float
    audible_volume: float = 0.0
    muted: bool = False
    stopped: bool = False  # yielded only: player paused before the ACK


@dataclass(frozen=True)
class HandoffState:
    owner_id: str
    generation: int = 1
    receipts: tuple[Receipt, ...] = ()


@dataclass(frozen=True)
class Decision:
    delivery_id: str
    action: str  # skip, resume, or play
    start_s: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class Snapshot:
    owner_id: str
    generation: int
    decisions: tuple[Decision, ...]
    blocked_reason: str = ""


def fence_owner(state: HandoffState, new_owner_id: str) -> HandoffState:
    """Advance the lease generation; late receipts from its old owner fail."""
    if not new_owner_id:
        raise ValueError("new owner is required")
    return replace(state, owner_id=new_owner_id, generation=state.generation + 1)


def record_receipt(state: HandoffState, receipt: Receipt) -> tuple[HandoffState, bool]:
    """Accept only ordered, audible receipts from the current fenced owner.

    `yielded` is the install path: the caller must stop the actual player,
    capture its final audible position, and only then submit this receipt.
    The boolean reports whether the receipt changed the decision state.
    """
    if receipt.event not in ("playing", "ended", "yielded"):
        raise ValueError("unknown handoff receipt")
    if (not receipt.delivery_id or not receipt.listener_id
            or receipt.generation < 1 or receipt.sequence < 1
            or not math.isfinite(receipt.position_s) or receipt.position_s < 0
            or not math.isfinite(receipt.audible_volume)
            or not 0 <= receipt.audible_volume <= 1):
        raise ValueError("invalid handoff receipt")
    if (receipt.listener_id != state.owner_id
            or receipt.generation != state.generation
            or receipt.muted or receipt.audible_volume <= 0):
        return state, False
    prior = [r for r in state.receipts
             if r.generation == receipt.generation
             and r.delivery_id == receipt.delivery_id]
    last = prior[-1] if prior else None
    if last and (receipt.sequence <= last.sequence
                 or receipt.position_s < last.position_s
                 or last.event in ("ended", "yielded")):
        return state, False
    if receipt.event != "playing" and not any(r.event == "playing" for r in prior):
        return state, False
    if receipt.event == "yielded" and not receipt.stopped:
        return state, False
    return replace(state, receipts=state.receipts + (receipt,)), True


def first_poll_snapshot(
    state: HandoffState,
    clips: Sequence[Clip],
    *,
    crash_rewind_s: float = CRASH_REWIND_S,
) -> Snapshot:
    """Decide once, in feed order, from prior fenced owners' audible receipts.

    A completed delivery is omitted only when its audible owner reported an
    end near the clip duration. A yielded partial resumes at the final paused
    playhead. A crash resumes before the last ACK and is marked uncertain;
    periodic ACKs cannot prove the exact position where sound stopped.
    """
    if not math.isfinite(crash_rewind_s) or not 0 <= crash_rewind_s <= MAX_CRASH_REWIND_S:
        raise ValueError("crash rewind is out of bounds")
    ids: set[str] = set()
    decisions: list[Decision] = []
    unfinished = 0
    for clip in clips:
        if (not clip.delivery_id or clip.delivery_id in ids
                or not math.isfinite(clip.duration_s) or clip.duration_s <= 0):
            raise ValueError("feed requires unique delivery IDs and positive durations")
        ids.add(clip.delivery_id)
        prior = [r for r in state.receipts
                 if r.delivery_id == clip.delivery_id and r.generation < state.generation]
        ended = any(r.event == "ended" and
                    clip.duration_s - END_TOLERANCE_S <= r.position_s
                    <= clip.duration_s + END_TOLERANCE_S for r in prior)
        if ended:
            decisions.append(Decision(clip.delivery_id, "skip", reason="audible_completed"))
            continue
        if prior:
            last = max(prior, key=lambda r: (r.generation, r.sequence))
            position = min(last.position_s, clip.duration_s)
            yielded = last.event == "yielded"
            start = position if yielded else max(0.0, position - crash_rewind_s)
            decisions.append(Decision(
                clip.delivery_id, "resume", start,
                "yielded_final" if yielded else "crash_rewind_uncertain"))
            unfinished += 1
        else:
            decisions.append(Decision(clip.delivery_id, "play", reason="not_started"))
    if unfinished > 1:
        return Snapshot(state.owner_id, state.generation, (),
                        "multiple unfinished deliveries require an operator decision")
    return Snapshot(state.owner_id, state.generation, tuple(decisions))
