"""[kitchen-hour] One kitchen under the hour (wave H, 2026-10-06).

The rules the kitchen's board and the writer lanes follow, kept apart from app.py so they read on their own and
can be tested with a fake sheet and fake windows. app.py gathers the facts (the upcoming windows, a window's
unvoiced parts, the box's readings) and acts on the answers. Nothing here touches a store, a model, a file or a
clock it was not handed.

Window needs. Every upcoming Book Time or supercut window that still has a part not ready to air is one need on
the board:
  kind      the window's prep road (banter for both windows today)
  why       "Book Time at HH:MM needs its <phase> part voiced (N chunks left)"
  cost      chunks_left * the seconds per chunk (10 s by default)
  deadline  the window's start minus 60 s
Needs run nearest deadline first. Within one window a part with no takes at all comes first, then the book's own
order (opening, discussion, closing).

Writer lanes. A second writer lane is admitted only when every condition holds: the ceiling allows it (the env
OLLAMA_LANES), the engine is system3 or kitchen.second_lane is on, no H3 or ComfyUI render is in flight, the box
is under its render ceiling, and the pantry is short of its horizon or a window is within twenty minutes.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Iterable

WINDOW_KINDS = ("book_time", "sfx_supercut")
CHUNK_SECONDS = 10.0             # seconds per unvoiced chunk when nothing better is measured
DEADLINE_LEAD_SECONDS = 60.0     # a window's deadline is its start minus this
URGENT_SECONDS = 1200.0          # a window this close outranks every need that has no deadline
LANE_CEILING = 2                 # the most writer lanes this dial ever opens
PHASE_ORDER = {"opening": 0, "clip": 0, "discussion": 1, "closing": 2}


def window_kind(row: Any) -> str:
    """The window's own kind (book_time or sfx_supercut), or "" when the row is not a window."""
    if not isinstance(row, dict):
        return ""
    slot = row.get("slot") if isinstance(row.get("slot"), dict) else {}
    for value in (row.get("kind"), row.get("dynamic_kind"), slot.get("dynamic_kind"),
                  slot.get("dynamic_template"), slot.get("kind")):
        if str(value or "") in WINDOW_KINDS:
            return str(value)
    return ""


def window_start(row: dict, now: float) -> float:
    """When the window takes the air: its due moment, or now plus its starts_in."""
    at = float(row.get("due_at") or 0)
    if at > 0:
        return at
    return float(now) + float(row.get("starts_in") or 0)


def clock(at: float) -> str:
    return time.strftime("%H:%M", time.localtime(float(at)))


def window_need_why(kind: str, at: float, phase: str, chunks: int) -> str:
    if kind == "sfx_supercut":
        return "Supercut at %s needs its clip made (%d chunks left)" % (clock(at), chunks)
    return ("Book Time at %s needs its %s part voiced (%d chunks left)"
            % (clock(at), phase, chunks))


def window_needs(rows: Iterable[dict], parts_of: Callable[[dict], Iterable[dict]], *,
                 now: float | None = None, chunk_seconds: float = CHUNK_SECONDS) -> list[dict[str, Any]]:
    """One need per window part that is not ready to air, nearest deadline first.

    rows      the upcoming rows (coord_upcoming shape: kind or slot.dynamic_kind, road, slot_id, occurrence,
              due_at or starts_in).
    parts_of  row -> the parts still owed a voice: {"id", "phase", "chunks_left", "takes"}. A part with no
              chunks left is not owed and is skipped here as well.
    """
    now = time.time() if now is None else float(now)
    chunk = float(chunk_seconds)
    out: list[dict[str, Any]] = []
    for row in rows or []:
        kind = window_kind(row)
        if not kind:
            continue
        at = window_start(row, now)
        road = str(row.get("road") or "banter")
        for part in list(parts_of(row) or []):
            chunks = int(part.get("chunks_left") or 0)
            if chunks <= 0:
                continue
            phase = str(part.get("phase") or "discussion")
            takes = int(part.get("takes") or 0)
            why = window_need_why(kind, at, phase, chunks)
            out.append({
                "prep": road, "kind": road, "face": "the window", "verdict": "window",
                "why": why, "window": dict(row), "window_kind": kind,
                "part": str(part.get("id") or phase), "phase": phase, "takes": takes,
                "chunks": chunks, "short": chunks, "each": chunk,
                "cost": round(chunks * chunk, 1),
                "deadline": round(at - DEADLINE_LEAD_SECONDS, 3),
                "starts_in": round(at - now, 1), "at": round(at, 3),
                "slot_id": str(row.get("slot_id") or ""),
                "occurrence": str(row.get("occurrence") or ""),
            })
    out.sort(key=lambda n: (n["deadline"], 0 if n["takes"] == 0 else 1,
                            PHASE_ORDER.get(n["phase"], 3), n["at"]))
    return out


def merge_needs(needs: list[dict], window_items: list[dict]) -> list[dict]:
    """Window needs placed against the board's own needs by time to the leg.

    A window within URGENT_SECONDS goes ahead of every need (its deadline is nearer than any quota's).
    A window further out goes after the board's needs, so the quota-only needs keep their order until the
    window is close. Both groups keep the nearest-deadline order they arrived in.
    """
    urgent = [n for n in window_items if float(n.get("starts_in") or 0) <= URGENT_SECONDS]
    later = [n for n in window_items if float(n.get("starts_in") or 0) > URGENT_SECONDS]
    return urgent + list(needs or []) + later


def window_due_soon(window_items: Iterable[dict]) -> bool:
    return any(float(n.get("starts_in") or 0) <= URGENT_SECONDS for n in window_items or [])


def writer_lanes(facts: dict[str, Any]) -> tuple[int, str]:
    """(lanes, why): 1 unless every condition holds, then 2 (never past the ceiling)."""
    ceiling = max(1, int(facts.get("ceiling") or 1))
    if ceiling < 2:
        return 1, "OLLAMA_LANES is one, and that is the ceiling"
    if not (facts.get("system3") or facts.get("second_lane")):
        return 1, "the engine is not system3 and kitchen.second_lane is off"
    if facts.get("render_in_flight"):
        return 1, "an H3 or ComfyUI render is in flight"
    hot = facts.get("hot_c")
    limit = facts.get("hot_ceiling_c")
    if hot is None or limit is None:
        return 1, "the box's thermal reading is missing"
    if float(hot) >= float(limit):
        return 1, "the box is at %.0f C, at or over its %.0f C ceiling" % (float(hot), float(limit))
    short = bool(facts.get("pantry_short"))
    soon = bool(facts.get("window_soon"))
    if not (short or soon):
        return 1, "the pantry is at its horizon and no window is within twenty minutes"
    reasons = []
    if short:
        reasons.append("the pantry holds %d s of %d s" % (int(facts.get("pantry_seconds") or 0),
                                                       int(facts.get("target_seconds") or 0)))
    if soon:
        reasons.append("a window is within twenty minutes")
    return min(LANE_CEILING, ceiling), ("; ".join(reasons) + "; no render in flight and the box at %.0f C"
                                       % float(hot))


def lane_admits(held: int, lanes: int) -> bool:
    """May one more ask take a lane, given how many of this model's asks already hold one?"""
    return int(held) < max(1, int(lanes))
