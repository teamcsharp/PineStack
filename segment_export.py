"""#1220: DOWNLOAD THE WHOLE SEGMENT.

    "I want to be able to download an entire segment, offer an option to
     download the whole segment and export it to Pinebox for recordings as
     a segment."

A segment is a BLOCK of the script ledger (#1330): every line one round
wrote, in the order it was heard, the SFX guy's stings included. The audio
behind those lines is the round's own welded file - one wav per burst, and
every turn's exact window inside it is written onto its air row (#908:
clip_media / clip_from / clip_until / clip_tail). So "the whole segment" is
a handful of exact cuts joined back together, with the records and adverts
that dropped inside it at their clock slot.

Two roads, both planned here and rendered here, gathered by app.py:

  welded   every heard line of the block in ledger order, cut from the
           round's own file(s) with the stings where they fell; a record
           or advert that dropped inside the segment is included in full,
           as a short bed (the first 20 s, faded), or not at all.
  aired    the same stretch cut out of the broadcast shelf's full mix
           (#667): the mixed twin, records underneath, gaps as they were.
           It is a reconstruction from the air log and the music log -
           nothing in this station records the stream output - and it
           exists only once the episode holding the stretch was sealed.

The plan is PURE (rows in, pieces out) so it can be tested without a
station or a sound card; `render` is the only thing that runs ffmpeg. The
sidecars - a screenplay .md with timestamps and a .json cue sheet - are
written AFTER rendering, from the frames actually appended, so every offset
in them is measured rather than estimated.

This module never imports app.py. Everything it needs from the station
(where a media key lives, how long a clip is, the shelf of sealed moments)
arrives as `deps`, a namespace of callables - see `Deps` below.
"""
from __future__ import annotations

import bisect
import json
import re
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SAMPLE_RATE = 24000                 # every voice engine here renders at 24 kHz mono
SHORT_BED_S = 20.0                  # `records: short` keeps this much of a record
SHORT_FADE_S = 3.0                  # ...and fades the last seconds of it
BREATH_S = 0.2                      # between pieces that were not contiguous on disk
OPENING_MAX_S = 8.0                 # a ring before the first line is included up to this
CLOSING_MAX_S = 6.0                 # a hang-up after the last line, likewise
MERGE_SLACK_S = 0.06                # two windows this close in one file are one span
MOMENT_MAX_S = 40.0                 # a whole shelved moment is only handed over when short
RECORD_AFTER_S = 2.0                # a record starting this soon after the last line is the outro
MP3_BITRATE = "192k"

RECORD_MODES = ("full", "short", "none")
SOURCES = ("welded", "aired")
FORMATS = ("mp3", "wav")


class SegmentEmpty(Exception):
    """Nothing of this block can be handed over - said in the station's words."""


@dataclass
class Deps:
    """The station's roads, so this module never imports app.py.

    media_path(key)     -> path of a voice_media key on disk, or ""
    ad_path(key)        -> path of a produced spot, or ""
    record_path(row)    -> path of a music-log row's audio (hot copy or library), or ""
    shelf()             -> [(began, ends, path, offset_into_file)] of every shelved moment
    clip_seconds(path)  -> how long a file plays, 0.0 when unreadable
    box_tail            -> the silence pad every own clip carries at its end (seconds)
    concat_keep         -> what the mixer leaves of it at a seam (seconds)
    published           -> the `aired` states that mean the line was handed to the air
    """
    media_path: Callable[[str], str]
    ad_path: Callable[[str], str]
    record_path: Callable[[dict[str, Any]], str]
    shelf: Callable[[], list[tuple[float, float, str, float]]]
    clip_seconds: Callable[[str], float]
    box_tail: float = 0.9
    concat_keep: float = 0.06
    published: tuple[str, ...] = ("published", "stream", "both", "box", "page", "airing")


@dataclass
class Piece:
    """One ffmpeg cut. `cues` are the lines inside it, with `rel` seconds
    from the piece's own start; `at` (seconds into the output) is filled by
    render() from the frames actually written."""
    kind: str                       # opening | speech | span | record | advert | closing | air
    src: str
    src_from: float
    seconds: float
    fade_out: float = 0.0
    label: str = ""
    exact: bool = True
    how: str = ""
    cues: list[dict[str, Any]] = field(default_factory=list)
    at: float = 0.0
    real: float = 0.0               # measured after decoding
    contiguous: bool = False        # follows the previous piece with no breath


@dataclass
class Plan:
    block: int
    sid: str
    road: str
    committed_at: float
    source: str
    records: str
    fmt: str
    pieces: list[Piece]
    lines: list[dict[str, Any]]     # every ledger row, aired or not, with what was decided
    skipped: list[dict[str, Any]]
    first_air_at: float
    last_air_end: float
    notes: list[str] = field(default_factory=list)
    cues: list[dict[str, Any]] = field(default_factory=list)   # filled by render()
    total_seconds: float = 0.0                                 # filled by render()
    lines_seconds: float = 0.0
    budget: dict[str, Any] = field(default_factory=dict)        # filled by render()
    mix: dict[str, Any] = field(default_factory=dict)           # the aired road's source


# ----------------------------------------------------------------- helpers

def mmss(seconds: float) -> str:
    seconds = max(0, int(round(float(seconds or 0))))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _norm(text: Any) -> str:
    return " ".join(str(text or "").lower().split())


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


# A board sting's air text is a feed label, not speech - it leads with the
# feed's own glyph ("🔊 125 clip-4"). The screenplay is prose, so the
# glyph comes off there; the cue sheet keeps the row exactly as it was written.
_LEAD_GLYPH = re.compile(r"^[^\w\"'(\[]+")


def _said(text: Any) -> str:
    return _LEAD_GLYPH.sub("", " ".join(str(text or "").split())).strip()


def _slug(text: str, most: int = 24) -> str:
    text = str(text or "").lower()
    if text.endswith(".md"):
        text = text[:-3]
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:most] or "round"


def file_stem(plan: Plan, station: str) -> str:
    """Named after WHEN THE SEGMENT AIRED, not when it was built, so the
    recording folder sorts into the running order of the show."""
    stamp = time.strftime("%Y-%m-%d_%H%M%S",
                          time.localtime(plan.first_air_at or plan.committed_at
                                         or time.time()))
    return (f"{stamp}-{_slug(station, 40)}-segment-{int(plan.block)}"
            f"-{_slug(plan.road)}-{plan.source}")


def _air_index(air: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]],
                                                    dict[tuple[str, str], dict[str, Any]]]:
    """Air rows by id, and - for a welded sting, which airs under the
    SAMPLE's id rather than the ledger's (#1133) - by (round, text)."""
    by_id: dict[str, dict[str, Any]] = {}
    by_round_text: dict[tuple[str, str], dict[str, Any]] = {}
    for row in air or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or "")
        if rid:
            by_id[rid] = row
        sid = str(row.get("sid") or "")
        if sid and str(row.get("kind") or "") == "sfx":
            by_round_text.setdefault((sid, _norm(row.get("text"))), row)
    return by_id, by_round_text


class _Shelf:
    """The booth's shelf of moments, built once per plan and bisected."""

    def __init__(self, deps: Deps) -> None:
        self._deps = deps
        self._rows: list[tuple[float, float, str, float]] | None = None
        self._starts: list[float] = []

    def rows(self) -> list[tuple[float, float, str, float]]:
        if self._rows is None:
            try:
                got = sorted((tuple(r) for r in (self._deps.shelf() or [])),
                             key=lambda r: float(r[0]))
            except Exception:  # noqa: BLE001
                got = []
            self._rows = [(float(r[0]), float(r[1]), str(r[2]), float(r[3]))
                          for r in got if len(r) >= 4]
            self._starts = [r[0] for r in self._rows]
        return self._rows

    def covering(self, at: float) -> tuple[float, float, str, float] | None:
        rows = self.rows()
        if not rows or not at:
            return None
        ix = bisect.bisect_right(self._starts, at) - 1
        while ix >= 0 and at - rows[ix][0] < 3600:
            began, ends, path, off = rows[ix]
            if began <= at < ends and Path(path).is_file():
                return rows[ix]
            ix -= 1
        return None


def _resolve_line(got: dict[str, Any], deps: Deps, shelf: _Shelf) -> dict[str, Any] | None:
    """Where this line's audio is, and exactly which span of it.

    The same three roads as /api/booth/clip, in the same order of how much
    the row itself knows: the welded round's window, the line's own clip,
    the produced spot; then the shelf by air time, said honestly."""
    air_at = _f(got.get("air_at")) or _f(got.get("ts"))
    key = str(got.get("clip_media") or "")
    c_from, c_until = got.get("clip_from"), got.get("clip_until")
    if key and c_from is not None and c_until is not None:
        lo, hi = _f(c_from), _f(c_until)
        tail = max(0.0, _f(got.get("clip_tail")))
        if hi - lo > 0.08:
            path = deps.media_path(key)
            if path:
                return {"src": path, "src_from": lo, "src_until": hi, "tail": tail,
                        "how": "welded", "exact": True, "key": key}
            # The round's file has been swept, but the burst was staged
            # into an episode: the window is the row's own, the audio is
            # the same, hardlinked or sealed.
            hit = shelf.covering(air_at)
            if hit:
                began, ends, spath, off = hit
                if ends - began >= hi - 0.5:
                    return {"src": spath, "src_from": off + lo, "src_until": off + hi,
                            "tail": tail, "how": "shelf", "exact": True, "key": key}
    own = str(got.get("media") or "")
    if own:
        path = deps.media_path(own)
        if path:
            full = _f(deps.clip_seconds(path))
            pad = _f(deps.box_tail)
            keep = full - pad + _f(deps.concat_keep)
            if full > 0.4 and pad > 0.05 and keep > 0.35 and keep > full * 0.5:
                return {"src": path, "src_from": 0.0, "src_until": keep, "tail": 0.0,
                        "how": "own", "exact": True, "key": own}
            if full > 0.05:
                return {"src": path, "src_from": 0.0, "src_until": full, "tail": 0.0,
                        "how": "own-whole", "exact": True, "key": own}
    ad = str(got.get("ad_audio") or "")
    if ad:
        path = deps.ad_path(ad)
        if path:
            full = _f(deps.clip_seconds(path))
            if full > 0.05:
                return {"src": path, "src_from": 0.0, "src_until": full, "tail": 0.0,
                        "how": "advert", "exact": True, "key": ad}
    if air_at:
        hit = shelf.covering(air_at)
        if hit:
            began, ends, spath, off = hit
            span = ends - began
            said = _f(got.get("seconds"))
            if said > 0.2 and abs(span - said) <= 1.0:
                # the moment IS this line - a board sting, a station ident
                return {"src": spath, "src_from": off, "src_until": off + span, "tail": 0.0,
                        "how": "moment", "exact": True, "key": ""}
            if said > 0.2 and began <= air_at:
                take = min(said, ends - air_at)
                if take > 0.2:
                    return {"src": spath, "src_from": off + (air_at - began),
                            "src_until": off + (air_at - began) + take, "tail": 0.0,
                            "how": "estimated", "exact": False, "key": ""}
            if span <= MOMENT_MAX_S:
                return {"src": spath, "src_from": off, "src_until": off + span, "tail": 0.0,
                        "how": "moment-whole", "exact": False, "key": ""}
    return None


def _lines_of(led: list[dict[str, Any]], air: list[dict[str, Any]],
              deps: Deps, shelf: _Shelf | None) -> list[dict[str, Any]]:
    """Every ledger row of the block, in ord order, with what the air log
    knows about it and - when it can be handed over - where its audio is."""
    by_id, by_round_text = _air_index(air)
    rows = sorted((r for r in led if isinstance(r, dict)),
                  key=lambda r: int(_f(r.get("ord"))))
    out: list[dict[str, Any]] = []
    for r in rows:
        lid = str(r.get("line_id") or "")
        got = by_id.get(lid) or {}
        if not got and str(r.get("kind") or "") == "sfx":
            got = by_round_text.get((str(r.get("sid") or ""), _norm(r.get("text")))) or {}
        aired = str(got.get("aired") or "")
        air_at = _f(got.get("air_at")) or _f(got.get("ts"))
        entry: dict[str, Any] = {
            "ord": int(_f(r.get("ord"))), "line_id": lid,
            "air_id": str(got.get("id") or ""),
            "who": str(r.get("who") or got.get("who") or ""),
            "name": str(got.get("name") or "") or _seat_name(str(r.get("who") or "")),
            "kind": str(r.get("kind") or got.get("kind") or ""),
            "text": " ".join(str(r.get("text") or got.get("text") or "").split()),
            "cue": str(r.get("cue") or ""),
            "scripted": bool(r.get("scripted", True)),
            "ledger_seconds": round(_f(r.get("seconds")), 2),
            "seconds": round(_f(got.get("seconds")) or _f(r.get("seconds")), 2),
            "aired": aired, "air_at": air_at,
            "withdrawn_why": str(got.get("withdrawn_why") or ""),
            "skip_why": "",
        }
        if not got:
            entry["skip_why"] = "never reached the air log - it was written but not aired"
        elif aired not in deps.published:
            # The station's own legend for "prepared" is "prepared and appended
            # to the feed - NEVER HEARD" (app.py's aired-state legend, and the
            # ghost-round measurement under it). A prepared row carries a real
            # air_at and a real clip window, so it would cut perfectly - and it
            # would put in the file a line nobody ever heard. It is named in the
            # sidecar instead, like every other line that did not get out.
            entry["skip_why"] = (
                "prepared and appended to the feed, never heard" if aired == "prepared"
                else f"not aired ({aired or 'no state'})"
                     + (f": {entry['withdrawn_why']}" if entry["withdrawn_why"] else ""))
        elif shelf is not None:
            where = _resolve_line(got, deps, shelf)
            if not where:
                entry["skip_why"] = ("no audio can be found for it - the round's file "
                                     "has been swept and nothing on the shelf covers it")
            else:
                entry.update(where)
                entry["window"] = round(_f(where["src_until"]) - _f(where["src_from"]), 3)
        out.append(entry)
    return out


_SEATS = {"dj": "HOST", "cohost": "CO-HOST", "drop": "THE SFX GUY", "board": "THE BOARD",
          "caller": "CALLER", "caller2": "CALLER", "guest": "GUEST", "manager": "UPSTAIRS"}


def _seat_name(who: str) -> str:
    return _SEATS.get(str(who or ""), str(who or "").upper() or "VOICE")


def _events(records: list[dict[str, Any]], ads: list[dict[str, Any]],
            first_air: float, last_end: float, deps: Deps) -> list[dict[str, Any]]:
    """Records and adverts that DROPPED inside the segment, by clock. A
    record already turning when the segment began is the bed under it, not
    part of it; one starting within a breath after the last line is the
    outro and is."""
    out: list[dict[str, Any]] = []
    lo, hi = first_air - 0.5, last_end + RECORD_AFTER_S
    for r in records or []:
        began = _f(r.get("began")) or _f(r.get("at"))
        if not began or not lo <= began <= hi:
            continue
        ends = _f(r.get("ends")) or began + _f(r.get("seconds"))
        out.append({"kind": "record", "at": began, "ends": ends,
                    "played": round(max(0.0, ends - began), 2),
                    "length": round(_f(r.get("seconds")), 2),
                    "title": str(r.get("title") or "an untitled record"),
                    "artist": str(r.get("artist") or ""), "id": str(r.get("id") or ""),
                    "src": deps.record_path(r) if callable(deps.record_path) else ""})
    for a in ads or []:
        at = _f(a.get("at"))
        if not at or not lo <= at <= hi:
            continue
        out.append({"kind": "advert", "at": at, "played": round(_f(a.get("seconds")), 2),
                    "length": round(_f(a.get("seconds")), 2),
                    "title": str(a.get("label") or a.get("product") or "an advert"),
                    "artist": "", "id": str(a.get("id") or ""),
                    "src": str(a.get("path") or "")})
    out.sort(key=lambda e: e["at"])
    return out


def _event_piece(ev: dict[str, Any], mode: str, deps: Deps) -> tuple[Piece | None, str]:
    """The piece for a record/advert event under `mode`, or (None, why)."""
    if mode == "none":
        return None, f"records: none - left out ({mmss(ev.get('played'))} as played)"
    src = str(ev.get("src") or "")
    if not src or not Path(src).is_file():
        return None, "its audio is not on this box (the record plays off a share the station only streams)"
    played = _f(ev.get("played"))
    if played <= 0.2:
        played = _f(deps.clip_seconds(src))
    if played <= 0.2:
        return None, "it played for less than a moment"
    if ev["kind"] == "advert" or mode == "full":
        take, fade = played, 0.0
        how = "full"
    else:
        take = min(SHORT_BED_S, played)
        fade = SHORT_FADE_S if take >= 5.0 else 0.0
        how = "short"
    label = (f'The advert airs - {ev["title"]} ({mmss(take)}).' if ev["kind"] == "advert" else
             f'A record drops: "{ev["title"]}"'
             + (f' by {ev["artist"]}' if ev.get("artist") else "")
             + (f" ({mmss(take)} of {mmss(ev.get('length'))}, as a bed)." if how == "short"
                else f" ({mmss(take)} as played, of {mmss(ev.get('length'))})."))
    piece = Piece(kind=ev["kind"], src=src, src_from=0.0, seconds=round(take, 3),
                  fade_out=fade, label=label, exact=True, how=how)
    piece.cues.append({"kind": ev["kind"], "rel": 0.0, "seconds": round(take, 3),
                       "title": ev["title"], "artist": ev.get("artist") or "",
                       "id": ev.get("id") or "", "air_at": ev["at"],
                       "played": ev.get("played"), "length": ev.get("length"),
                       "mode": how, "text": label})
    return piece, ""


def _line_cue(e: dict[str, Any], rel: float, seconds: float) -> dict[str, Any]:
    return {"kind": "sting" if e["kind"] in ("sfx", "sfxguy") and e["who"] == "board" else
            ("sfxguy" if e["kind"] == "sfxguy" else "speech"),
            "ord": e["ord"], "line_id": e["line_id"], "air_id": e.get("air_id") or "",
            "who": e["who"], "name": e["name"], "text": e["text"],
            "rel": round(rel, 3), "seconds": round(seconds, 3),
            "air_at": e["air_at"], "aired": e["aired"], "exact": bool(e.get("exact")),
            "how": e.get("how") or "", "src": e.get("src") or "",
            "src_from": e.get("src_from"), "src_until": e.get("src_until"),
            "scripted": e.get("scripted", True), "cue": e.get("cue") or ""}


# ------------------------------------------------------------------- plans

def plan_welded(block: int, led: list[dict[str, Any]], air: list[dict[str, Any]],
                records: list[dict[str, Any]], ads: list[dict[str, Any]], deps: Deps,
                *, records_mode: str = "short", fmt: str = "mp3",
                edges: bool = True) -> Plan:
    """The whole segment from the round's own audio, as pieces."""
    if records_mode not in RECORD_MODES:
        records_mode = "short"
    if fmt not in FORMATS:
        fmt = "mp3"
    led = [r for r in (led or []) if isinstance(r, dict)]
    if not led:
        raise SegmentEmpty(f"no block {int(block)} is in the script ledger - it holds "
                           "the last 48 hours, so an older segment is gone")
    shelf = _Shelf(deps)
    lines = _lines_of(led, air, deps, shelf)
    first = sorted(led, key=lambda r: int(_f(r.get("ord"))))[0]
    included = [e for e in lines if not e["skip_why"]]
    skipped = [{"ord": e["ord"], "line_id": e["line_id"], "who": e["who"], "name": e["name"],
                "kind": e["kind"], "text": e["text"][:200], "aired": e["aired"],
                "why": e["skip_why"]} for e in lines if e["skip_why"]]
    if not included:
        why = "; ".join(sorted({s["why"] for s in skipped}))[:300]
        raise SegmentEmpty(f"none of block {int(block)}'s {len(lines)} line(s) can be "
                           f"handed over - {why}")
    timed = [e for e in included if e["air_at"]]
    first_air = min(e["air_at"] for e in timed) if timed else _f(first.get("at"))
    last_end = max(e["air_at"] + _f(e.get("window")) for e in timed) if timed else first_air
    events = _events(records, ads, first_air, last_end, deps)

    # THE RUNNING ORDER: lines by ord, an event before the first line that
    # aired after it (so a record dropped between two lines splits them).
    seq: list[tuple[str, dict[str, Any]]] = []
    pending = list(events)
    for e in included:
        while pending and e["air_at"] and pending[0]["at"] < e["air_at"]:
            seq.append(("event", pending.pop(0)))
        seq.append(("line", e))
    seq.extend(("event", ev) for ev in pending)

    pieces: list[Piece] = []
    notes: list[str] = []
    for what, item in seq:
        if what == "event":
            piece, why = _event_piece(item, records_mode, deps)
            if piece is None:
                skipped.append({"kind": item["kind"], "title": item["title"],
                                "artist": item.get("artist") or "", "id": item.get("id") or "",
                                "air_at": item["at"], "why": why})
                continue
            pieces.append(piece)
            continue
        e = item
        src_from, src_until = _f(e["src_from"]), _f(e["src_until"])
        last = pieces[-1] if pieces else None
        if (last is not None and last.kind in ("speech", "span", "opening")
                and last.src == e["src"] and e["how"] in ("welded", "shelf")
                and abs((last.src_from + last.seconds) - src_from) <= MERGE_SLACK_S):
            # the next turn of the same welded file: one span, the real
            # seam beat and any sting between them kept where they fell
            last.seconds = round(src_until - last.src_from, 3)
            last.kind = "span"
            last.cues.append(_line_cue(e, src_from - last.src_from,
                                       src_until - src_from - _f(e.get("tail"))))
            last.exact = last.exact and bool(e.get("exact"))
            continue
        piece = Piece(kind="speech", src=e["src"], src_from=src_from,
                      seconds=round(src_until - src_from, 3), exact=bool(e.get("exact")),
                      how=e["how"], label=e["text"][:80])
        piece.cues.append(_line_cue(e, 0.0, src_until - src_from - _f(e.get("tail"))))
        pieces.append(piece)

    # The seam beat the mixer glued after a turn is the run-up to the NEXT
    # speaker (#908); a span ends on its last line's words, not its beat.
    for p in pieces:
        if p.kind in ("speech", "span") and p.cues:
            tail = 0.0
            for e in included:
                if e["line_id"] == p.cues[-1]["line_id"]:
                    tail = _f(e.get("tail"))
                    break
            if tail > 0 and p.seconds - tail >= 0.2:
                p.seconds = round(p.seconds - tail, 3)   # the cue already excluded it

    # THE EDGES: what the welded file holds before the first line (a ring)
    # and after the last (a hang-up) - only when no skipped line's audio
    # could be hiding there, which is what the ord checks are for.
    if edges and pieces:
        head = next((p for p in pieces if p.kind in ("speech", "span")), None)
        if (head is not None and head.how in ("welded",) and included[0]["ord"] == lines[0]["ord"]
                and head.cues and head.cues[0]["ord"] == included[0]["ord"]
                and 0.25 < head.src_from <= OPENING_MAX_S):
            opening = Piece(kind="opening", src=head.src, src_from=0.0,
                            seconds=round(head.src_from, 3), exact=True, how="welded",
                            label="the round's opening, before the first line - a ring or a sting")
            opening.cues.append({"kind": "opening", "rel": 0.0, "seconds": opening.seconds,
                                 "text": opening.label, "src": head.src, "src_from": 0.0,
                                 "src_until": head.src_from})
            pieces.insert(pieces.index(head), opening)
            head.contiguous = True
        tail_piece = next((p for p in reversed(pieces) if p.kind in ("speech", "span")), None)
        if (tail_piece is not None and tail_piece.how == "welded" and tail_piece.cues
                and tail_piece.cues[-1]["ord"] == lines[-1]["ord"]
                and included[-1]["ord"] == lines[-1]["ord"]):
            full = _f(deps.clip_seconds(tail_piece.src))
            last_until = 0.0
            for e in included:
                if e["line_id"] == tail_piece.cues[-1]["line_id"]:
                    last_until = _f(e.get("src_until"))
            rest = full - _f(deps.box_tail) - last_until
            if 0.3 <= rest <= CLOSING_MAX_S and pieces[-1] is tail_piece:
                closing = Piece(kind="closing", src=tail_piece.src, src_from=last_until,
                                seconds=round(rest, 3), exact=True, how="welded",
                                label="after the last line - a hang-up or the round's tail",
                                contiguous=True)
                closing.cues.append({"kind": "closing", "rel": 0.0, "seconds": closing.seconds,
                                     "text": closing.label, "src": tail_piece.src,
                                     "src_from": last_until, "src_until": last_until + rest})
                pieces.append(closing)

    # contiguity decides the breath between pieces at render time
    for ix in range(1, len(pieces)):
        prev, cur = pieces[ix - 1], pieces[ix]
        if prev.src == cur.src and abs((prev.src_from + prev.seconds) - cur.src_from) <= MERGE_SLACK_S:
            cur.contiguous = True

    lines_seconds = round(sum(_f(e.get("seconds")) for e in included), 2)
    inexact = sum(1 for p in pieces if not p.exact)
    if inexact:
        notes.append(f"{inexact} piece(s) were placed by air time rather than by the row's "
                     "own window - the round's file had been swept")
    return Plan(block=int(block), sid=str(first.get("sid") or ""),
                road=str(first.get("round") or ""), committed_at=_f(first.get("at")),
                source="welded", records=records_mode, fmt=fmt, pieces=pieces, lines=lines,
                skipped=skipped, first_air_at=first_air, last_air_end=last_end,
                notes=notes, lines_seconds=lines_seconds)


def window_of(led: list[dict[str, Any]], air: list[dict[str, Any]], deps: Deps,
              pad: float = 0.3) -> tuple[float, float, list[dict[str, Any]]]:
    """[lo, hi] on the wall clock that the block's heard lines occupy, and
    the lines themselves - what the aired road needs before it knows which
    shelved mix to cut from."""
    lines = _lines_of(led, air, deps, None)
    timed = [e for e in lines if not e["skip_why"] and e["air_at"]]
    if not timed:
        raise SegmentEmpty("none of this block's lines carries an air time - nothing "
                           "was heard, so there is no stretch of the broadcast to cut")
    lo = min(e["air_at"] for e in timed) - pad
    hi = max(e["air_at"] + (_f(e.get("seconds")) or 3.0) for e in timed) + pad
    return lo, hi, lines


def plan_aired(block: int, led: list[dict[str, Any]], air: list[dict[str, Any]],
               records: list[dict[str, Any]], deps: Deps, *, mix_path: str,
               mix_lo: float, lo: float, hi: float, fmt: str = "mp3",
               mix_name: str = "") -> Plan:
    """The same stretch cut from a shelved full mix: one piece, the lines
    and the records underneath it as cues by air time."""
    if fmt not in FORMATS:
        fmt = "mp3"
    led = [r for r in (led or []) if isinstance(r, dict)]
    if not led:
        raise SegmentEmpty(f"no block {int(block)} is in the script ledger")
    first = sorted(led, key=lambda r: int(_f(r.get("ord"))))[0]
    lines = _lines_of(led, air, deps, None)
    skipped = [{"ord": e["ord"], "line_id": e["line_id"], "who": e["who"], "name": e["name"],
                "kind": e["kind"], "text": e["text"][:200], "aired": e["aired"],
                "why": e["skip_why"]} for e in lines if e["skip_why"]]
    piece = Piece(kind="air", src=mix_path, src_from=round(max(0.0, lo - mix_lo), 3),
                  seconds=round(max(0.5, hi - lo), 3), exact=True, how="fullmix",
                  label=f"cut from the broadcast shelf's full mix {mix_name or Path(mix_path).name}")
    for e in lines:
        if e["skip_why"] or not e["air_at"]:
            continue
        piece.cues.append(_line_cue(e, e["air_at"] - lo, _f(e.get("seconds")) or 3.0))
    for r in records or []:
        began = _f(r.get("began")) or _f(r.get("at"))
        ends = _f(r.get("ends")) or began + _f(r.get("seconds"))
        if not began or ends <= lo or began >= hi:
            continue
        b, e_ = max(lo, began), min(hi, ends)
        piece.cues.append({"kind": "record", "under": True, "rel": round(b - lo, 3),
                           "seconds": round(e_ - b, 3), "title": str(r.get("title") or ""),
                           "artist": str(r.get("artist") or ""), "id": str(r.get("id") or ""),
                           "air_at": began, "played": round(ends - began, 2),
                           "length": round(_f(r.get("seconds")), 2), "mode": "under",
                           "text": (f'Underneath, in the mix: "{r.get("title") or "a record"}"'
                                    + (f' by {r.get("artist")}' if r.get("artist") else "")
                                    + (" (already turning when the segment began)"
                                       if began < lo else ""))})
    piece.cues.sort(key=lambda c: (c["rel"], 0 if c["kind"] == "record" else 1))
    lines_seconds = round(sum(_f(e.get("seconds")) for e in lines if not e["skip_why"]), 2)
    return Plan(block=int(block), sid=str(first.get("sid") or ""),
                road=str(first.get("round") or ""), committed_at=_f(first.get("at")),
                source="aired", records="under", fmt=fmt, pieces=[piece], lines=lines,
                skipped=skipped, first_air_at=lo, last_air_end=hi,
                notes=["a reconstruction from the air log and the music log at the "
                       "shelf's saved levels - nothing in the station records the "
                       "stream itself"],
                lines_seconds=lines_seconds,
                mix={"path": mix_path, "lo": mix_lo, "name": mix_name or Path(mix_path).name})


# ------------------------------------------------------------------ render

def _decode(exe: str, piece: Piece, out_wav: Path, timeout: int = 600) -> bytes:
    args = [exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-accurate_seek"]
    if piece.src_from > 0.0005:
        args += ["-ss", f"{piece.src_from:.3f}"]
    args += ["-t", f"{max(0.05, piece.seconds):.3f}", "-i", str(piece.src)]
    filters = [f"aresample={SAMPLE_RATE}"]
    if piece.fade_out > 0.05 and piece.seconds > piece.fade_out + 0.2:
        filters.append(f"afade=t=out:st={piece.seconds - piece.fade_out:.3f}:d={piece.fade_out:.3f}")
    args += ["-vn", "-af", ",".join(filters), "-ac", "1", "-ar", str(SAMPLE_RATE),
             "-sample_fmt", "s16", "-f", "wav", str(out_wav)]
    subprocess.run(args, capture_output=True, timeout=timeout, check=True)
    with wave.open(str(out_wav), "rb") as handle:
        return handle.readframes(handle.getnframes())


def render(plan: Plan, out_base: Path, exe: str,
           progress: Callable[[float, str], None] | None = None) -> dict[str, Any]:
    """Cut every piece, join the PCM, write `<out_base>.<fmt>`. Fills each
    piece's `at`/`real` and the plan's flat `cues` from the frames actually
    written, so the sidecars never disagree with the file."""
    def tell(pct: float, step: str) -> None:
        if progress:
            try:
                progress(float(pct), str(step))
            except Exception:  # noqa: BLE001
                pass

    out_base = Path(out_base)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    total = max(1, len(plan.pieces))
    pcm = bytearray()
    breath = b"\x00" * int(SAMPLE_RATE * BREATH_S) * 2
    cursor = 0.0
    breaths = 0
    failed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="seg1220-") as work:
        for ix, piece in enumerate(plan.pieces):
            tell(3 + 85.0 * ix / total,
                 f"cutting {ix + 1} of {total}: {piece.label[:60] or piece.kind}")
            try:
                frames = _decode(exe, piece, Path(work) / f"p{ix:03d}.wav")
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{piece.kind} {ix}: {str(exc)[:80]}")
                piece.real = 0.0
                continue
            if not frames:
                failed.append(f"{piece.kind} {ix}: decoded to nothing")
                piece.real = 0.0
                continue
            if pcm and not piece.contiguous:
                pcm += breath
                cursor += BREATH_S
                breaths += 1
            piece.at = round(cursor, 3)
            piece.real = round(len(frames) / 2 / SAMPLE_RATE, 3)
            pcm += frames
            cursor = round(cursor + piece.real, 3)
        if len(pcm) < SAMPLE_RATE * 2 // 4:
            raise SegmentEmpty("nothing could be cut - " + ("; ".join(failed)[:300]
                                                             if failed else "no piece decoded"))
        tell(90, "joining the pieces")
        joined = Path(work) / "segment.wav"
        with wave.open(str(joined), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(bytes(pcm))
        out = out_base.with_suffix("." + plan.fmt)
        if plan.fmt == "wav":
            out.write_bytes(joined.read_bytes())
        else:
            tell(93, "encoding the mp3")
            subprocess.run([exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                            "-i", str(joined), "-codec:a", "libmp3lame", "-b:a", MP3_BITRATE,
                            str(out)], capture_output=True, timeout=900, check=True)
    plan.total_seconds = round(cursor, 3)
    plan.cues = []
    for piece in plan.pieces:
        if piece.real <= 0:
            continue
        for cue in piece.cues:
            rel = min(max(0.0, _f(cue.get("rel"))), piece.real)
            at = round(piece.at + rel, 3)
            until = round(min(piece.at + piece.real, at + _f(cue.get("seconds"))), 3)
            plan.cues.append({**cue, "at": at, "until": until,
                              "seconds": round(max(0.0, until - at), 3),
                              "piece": plan.pieces.index(piece)})
    plan.budget = _budget(plan, breaths)
    if failed:
        plan.notes.append("could not cut: " + "; ".join(failed)[:300])
    return {"path": str(out), "seconds": plan.total_seconds, "bytes": out.stat().st_size,
            "pieces": sum(1 for p in plan.pieces if p.real > 0), "failed": failed}


def _budget(plan: Plan, breaths: int) -> dict[str, Any]:
    """WHERE EVERY SECOND WENT, measured from the frames that were written.

    `spoken` is the sum of the heard lines as the file carries them and must
    equal `ledger` (what the air log says those same lines last) to within
    rounding; the rest of the file is named, so the total can never be a
    number nobody can account for:

        total = spoken + beats + records + edges + breaths
    """
    spoken = sum(_f(c.get("seconds")) for c in plan.cues
                 if c.get("kind") in ("speech", "sfxguy", "sting"))
    under = sum(_f(c.get("seconds")) for c in plan.cues
                if c.get("kind") in ("record", "advert") and not c.get("under"))
    edges = sum(_f(p.real) for p in plan.pieces if p.kind in ("opening", "closing"))
    pad = round(BREATH_S * max(0, int(breaths)), 3)
    if plan.source == "aired":
        # one continuous cut of the mix: everything that is not a line is the
        # show going on underneath it, and none of it can be separated out.
        return {"total": plan.total_seconds, "spoken": round(spoken, 2),
                "ledger": plan.lines_seconds, "beats": 0.0, "records": 0.0,
                "edges": 0.0, "breaths": 0.0,
                "mix": round(max(0.0, plan.total_seconds - spoken), 2)}
    beats = round(max(0.0, plan.total_seconds - spoken - under - edges - pad), 2)
    return {"total": plan.total_seconds, "spoken": round(spoken, 2),
            "ledger": plan.lines_seconds, "beats": beats, "records": round(under, 2),
            "edges": round(edges, 2), "breaths": pad, "mix": 0.0}


def budget_words(budget: dict[str, Any]) -> str:
    """The budget said out loud, for the screenplay and the toast."""
    if not budget:
        return ""
    bits = [f"{mmss(budget.get('spoken'))} of speech"]
    for key, word in (("beats", "seam beats"), ("records", "records and adverts"),
                      ("edges", "the round's own opening and tail"),
                      ("breaths", "breaths between the pieces"),
                      ("mix", "the show underneath")):
        if _f(budget.get(key)) >= 0.05:
            bits.append(f"{mmss(budget[key])} {word}")
    return f"{mmss(budget.get('total'))} in all - " + ", ".join(bits)


# ---------------------------------------------------------------- sidecars

def cue_sheet(plan: Plan, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": 1, "request": "#1220",
        "block": plan.block, "sid": plan.sid, "road": plan.road,
        "committed_at": plan.committed_at, "source": plan.source, "records": plan.records,
        "format": plan.fmt, "sample_rate": SAMPLE_RATE,
        "station": meta.get("station"), "scene": meta.get("scene"), "hour": meta.get("hour"),
        "file": meta.get("file"), "built_at": meta.get("built_at"),
        "seconds": plan.total_seconds, "lines_seconds": plan.lines_seconds,
        "budget": plan.budget,
        "first_air_at": plan.first_air_at, "last_air_end": plan.last_air_end,
        "lines": len(plan.lines), "heard": sum(1 for e in plan.lines if not e["skip_why"]),
        "cues": plan.cues,
        "pieces": [{"i": i, "kind": p.kind, "src": p.src, "src_from": p.src_from,
                    "seconds": p.seconds, "real": p.real, "at": p.at, "fade_out": p.fade_out,
                    "exact": p.exact, "how": p.how, "contiguous": p.contiguous,
                    "label": p.label} for i, p in enumerate(plan.pieces)],
        "skipped": plan.skipped, "notes": plan.notes,
        "mix": plan.mix or None,
    }


def markdown(plan: Plan, meta: dict[str, Any]) -> str:
    heard = sum(1 for e in plan.lines if not e["skip_why"])
    day = time.strftime("%A %d %B %Y", time.localtime(plan.first_air_at or plan.committed_at
                                                         or time.time()))
    committed = time.strftime("%H:%M:%S", time.localtime(plan.committed_at)) if plan.committed_at else "?"
    lines = [f"# {meta.get('station') or 'Pine Box FM'} — segment {plan.block}", ""]
    if meta.get("scene"):
        lines.append(str(meta["scene"]))
    lines.append(f"block {plan.block} · {plan.road or 'round'}"
                 + (f" · conversation {plan.sid}" if plan.sid else "")
                 + f" · committed {committed} · {len(plan.lines)} line(s), {heard} heard · {day}")
    if plan.source == "aired":
        lines.append("cut from the broadcast shelf's full mix - records underneath, gaps as "
                     f"they were ({(plan.mix or {}).get('name') or 'the shelf'})")
    else:
        beds = {"short": f"short ({int(SHORT_BED_S)} s beds)", "full": "in full, as played",
                "none": "left out"}.get(plan.records, plan.records)
        lines.append("welded from the round's own audio, stings where they fell · records: " + beds)
    lines.append(f"file: {meta.get('file') or ''} · {mmss(plan.total_seconds)}"
                 f" · built {meta.get('built_at_local') or ''}")
    if plan.budget:
        lines.append(budget_words(plan.budget))
    lines.append("")
    for cue in plan.cues:
        stamp = f"[{mmss(cue.get('at'))}]"
        kind = str(cue.get("kind") or "")
        if kind in ("speech", "sfxguy"):
            lines.append(f"{stamp} {str(cue.get('name') or '').upper()}"
                         + ("" if cue.get("exact", True) else "  (placed by air time)"))
            lines.append(f"    {cue.get('text') or ''}")
        elif kind == "sting":
            lines.append(f"{stamp} A sting off the board: {_said(cue.get('text')) or 'a sting'} "
                         f"({mmss(cue.get('seconds'))}).")
        else:
            lines.append(f"{stamp} {cue.get('text') or cue.get('label') or kind}")
        lines.append("")
    if plan.skipped:
        lines.append("Not in this file")
        for s in plan.skipped:
            if s.get("kind") in ("record", "advert"):
                lines.append(f"- {s['kind']}: \"{s.get('title') or ''}\""
                             + (f" by {s['artist']}" if s.get("artist") else "")
                             + f" — {s.get('why') or ''}")
            else:
                lines.append(f"- ord {s.get('ord')} · {str(s.get('name') or s.get('who') or '').upper()}"
                             f" · \"{str(s.get('text') or '')[:120]}\" — {s.get('why') or ''}")
        lines.append("")
    if plan.notes:
        lines.append("Notes")
        for n in plan.notes:
            lines.append(f"- {n}")
        lines.append("")
    return "\n".join(lines)


def to_json(plan: Plan, meta: dict[str, Any]) -> str:
    return json.dumps(cue_sheet(plan, meta), indent=1, ensure_ascii=False)
