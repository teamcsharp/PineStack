"""[sfxseen] SFX DISPLAY RECEIPTS: did the picture REACH THE SCREEN?

"Make sure that you are able to access a diagnostics based on the script
 system to see which SFX play and also have a follow up that also is able to
 tell you if they displayed on the screen and how they were able to display
 and react with the Pine tablet."                   - the operator, 2026-09-29

The script says "A sting off the board: ...". The heard receipt
(/api/dj/voice/ack, heard_ack_at on the air row) says the SOUND came out.
Nothing said whether the PICTURE was painted: PineSfxTv.played() notes the
first 'playing' event only, which a veiled, occluded, 0x0 or hidden element
fires just the same. Each player (the tablet's kiosk, the desk) now sends a
DISPLAY RECEIPT per clip it was handed: the surface, the first frame actually
painted, the rect and how much of it was unoccluded, the display on or off,
frames, stalls, the error, seconds on screen, and the operator's reaction.

This module is the station half, pure and testable:

  ReceiptStore   data/sfx_display_receipts.jsonl - a KEEP store (telemetry,
                 not air memory), bounded: 7 days and SFX_SEEN_MAX_BYTES.
  script_rows()  the script's SFX rows (the air log's board rows - the same
                 rows the screenplay turns into "A sting off the board").
  audit()        the join: per script row, played? displayed per player
                 (surface, rect, first frame, seconds)? the reaction, and the
                 reason when it was not shown. Plus the summary rates.
  install()      the two routes, wired the way system3_origin installs.

Nothing here speaks, decides or may stop the air: every station entry point
swallows its own failure.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterable

try:    # module level: FastAPI resolves the routes' string annotations here
    from fastapi import Header, HTTPException, Request
except ImportError:  # the CLI and the pure tests need none of it
    Header = HTTPException = Request = None  # type: ignore[assignment,misc]

SCHEMA = "sfx.display/1"
STORE_NAME = "sfx_display_receipts.jsonl"
KEEP_S = 7 * 86400.0
MAX_BYTES = int(os.getenv("SFX_SEEN_MAX_BYTES", str(24 * 1024 * 1024)))
PRUNE_EVERY_S = 3600.0
BATCH_MOST = 60                      # rows accepted from one POST
MATCH_S = 25.0                       # a receipt this far from the row's air is not it
SHOWN_MIN_S = 0.5                    # seconds on screen that count as "displayed"
HEARD_STATES = ("heard",)            # plus heard_ack_at on the row

SURFACES = ("tube", "native_wall", "bubble", "endless_wall", "audio_only", "none")
SURFACE_WORDS = {"tube": "web tube", "native_wall": "native wall",
                 "bubble": "Message view bubble", "endless_wall": "endless wall",
                 "audio_only": "audio only", "none": "no surface"}
PLAYER_WORDS = {"pinetab": "PineTab", "desk": "the desk", "browser": "a browser"}
INTERACTIONS = ("tap", "hold", "radial", "replay", "parody", "stinger", "sheet",
                "cut", "next", "prev", "close", "full")
OUTCOMES = ("shown", "partial", "not_shown")

_ID = re.compile(r"[^A-Za-z0-9_.:-]")
_SFX_IN_URL = re.compile(r"/sfx/([0-9A-Za-z_-]{6,64})")


# --------------------------------------------------------------- helpers

def _s(v: Any, cap: int = 120) -> str:
    return " ".join(str(v if v is not None else "").split())[:cap]


def _ident(v: Any, cap: int = 80) -> str:
    return _ID.sub("", str(v or ""))[:cap]


def _f(v: Any, lo: float = -1e15, hi: float = 1e15) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    if x != x:                        # NaN
        return 0.0
    return max(lo, min(hi, x))


def _i(v: Any, lo: int = 0, hi: int = 10**9) -> int:
    return int(_f(v, lo, hi))


def sfx_of_url(url: Any) -> str:
    m = _SFX_IN_URL.search(str(url or ""))
    return m.group(1) if m else ""


def bare_url(url: Any) -> str:
    """The media path without its signature - a receipt must not carry a
    capability anybody could replay."""
    return str(url or "").split("?", 1)[0][:200]


def text_key(text: Any) -> str:
    t = re.sub(r"[^\w ]+", " ", str(text or "").lower())
    return " ".join(t.split())[:80]


# ------------------------------------------------------- normalisation

def normalise(row: Any, player: str, skew_ms: float, rx: float, addr: str = "") -> dict[str, Any] | None:
    """One client row -> the stored shape, or None. Whitelisted and clamped:
    the page is a browser and this is a file that lives for a week."""
    if not isinstance(row, dict):
        return None
    kind = str(row.get("kind") or "receipt")
    if kind not in ("receipt", "interaction", "beat"):
        return None
    out: dict[str, Any] = {"kind": kind, "rx": round(rx, 3),
                           "player": _ident(row.get("player") or player, 24) or "unknown",
                           "skew_ms": round(skew_ms)}
    if addr:
        out["addr"] = _s(addr, 48)
    # every client clock is moved onto the station's with the batch's skew
    def station_s(key: str) -> float:
        v = _f(row.get(key), 0, 1e14)
        return round((v + skew_ms) / 1000.0, 3) if v > 0 else 0.0
    if kind == "beat":
        out.update({"at": station_s("at_ms") or round(rx, 3),
                    "tv_on": bool(row.get("tv_on")), "wall_on": bool(row.get("wall_on")),
                    "hidden": bool(row.get("hidden")),
                    "screen_on": (None if row.get("screen_on") is None else bool(row.get("screen_on"))),
                    "open": _i(row.get("open"), 0, 999)})
        return out
    url = bare_url(row.get("url"))
    out.update({"rid": _ident(row.get("rid"), 48),
                "line": _ident(row.get("line"), 80),
                "delivery_id": _ident(row.get("delivery_id"), 64),
                "sfx": _ident(row.get("sfx") or sfx_of_url(url), 64),
                "url": url, "sting": _s(row.get("sting"), 120)})
    if kind == "interaction":
        what = str(row.get("what") or row.get("action") or "")
        out.update({"what": what if what in INTERACTIONS else "other",
                    "at": station_s("at_ms") or round(rx, 3),
                    "during": bool(row.get("during"))})
        return out
    surface = str(row.get("surface") or "none")
    outcome = str(row.get("outcome") or "")
    rect = row.get("rect") if isinstance(row.get("rect"), dict) else {}
    disp = row.get("display") if isinstance(row.get("display"), dict) else {}
    due = _f(row.get("due_ms"), 0, 1e14)          # the STATION's own clock already
    out.update({
        "surface": surface if surface in SURFACES else "none",
        "outcome": outcome if outcome in OUTCOMES else "not_shown",
        "reason": _s(row.get("reason"), 160),
        "due": round(due / 1000.0, 3) if due > 0 else 0.0,
        "requested": station_s("requested_ms"),
        "first_frame": station_s("first_frame_ms"),
        "first_frame_via": _s(row.get("first_frame_via"), 16),
        "first_frame_lag_ms": _i(row.get("first_frame_lag_ms"), -600000, 600000)
        if row.get("first_frame_lag_ms") is not None else None,
        "closed": station_s("closed_ms"),
        "shown_s": round(_f(row.get("shown_s"), 0, 86400), 2),
        "hidden_s": round(_f(row.get("hidden_s"), 0, 86400), 2),
        "frames": _i(row.get("frames"), 0, 10**7),
        "dropped": _i(row.get("dropped"), 0, 10**7),
        "stalls": _i(row.get("stalls"), 0, 10**5),
        "error": _s(row.get("error"), 160),
        "error_code": _i(row.get("error_code"), 0, 9999),
        "rect": {k: _i(rect.get(k), -100000, 100000) for k in ("x", "y", "w", "h")},
        "unoccluded": round(_f(row.get("unoccluded"), 0, 1), 2),
        "occluder": _s(row.get("occluder"), 80),
        "display": {"hidden": bool(disp.get("hidden")),
                    "screen_on": (None if disp.get("screen_on") is None else bool(disp.get("screen_on")))},
        "silent": bool(row.get("silent")), "endless": bool(row.get("endless")),
        "replay": bool(row.get("replay")),
        "interactions": [{"what": (str(x.get("what")) if str(x.get("what")) in INTERACTIONS else "other"),
                          "at": round((_f(x.get("at_ms"), 0, 1e14) + skew_ms) / 1000.0, 3)}
                         for x in (row.get("interactions") or [])[:12] if isinstance(x, dict)],
    })
    return out


# ------------------------------------------------------------------ store

class ReceiptStore:
    """Append-only JSONL, bounded by age (7 days) and size. One lock; every
    method sync - the station calls them in threads."""

    def __init__(self, path: Any, keep_s: float = KEEP_S, max_bytes: int = MAX_BYTES):
        self.path = Path(path)
        self.keep_s = float(keep_s)
        self.max_bytes = int(max_bytes)
        self.lock = threading.RLock()
        self._pruned = 0.0
        self.stats = {"accepted": 0, "refused": 0, "batches": 0}

    def append(self, body: Any, addr: str = "", now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else float(now)
        body = body if isinstance(body, dict) else {}
        rows = body.get("rows") if isinstance(body.get("rows"), list) else []
        player = _ident(body.get("player"), 24) or "unknown"
        sent = _f(body.get("sent_ms"), 0, 1e14)
        # the batch's own clock against ours; a nonsense clock is not trusted
        skew = (now * 1000.0 - sent) if sent > 0 else 0.0
        if abs(skew) > 7 * 86400 * 1000:
            skew = 0.0
        kept: list[dict[str, Any]] = []
        for row in rows[:BATCH_MOST]:
            got = normalise(row, player, skew, now, addr)
            if got is not None:
                kept.append(got)
        refused = len(rows) - len(kept)
        if kept:
            text = "".join(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n" for r in kept)
            with self.lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(text)
                self.stats["accepted"] += len(kept)
                self.stats["refused"] += refused
                self.stats["batches"] += 1
                if now - self._pruned > PRUNE_EVERY_S or self._size() > self.max_bytes:
                    self.prune(now)
        return {"ok": True, "accepted": len(kept), "refused": refused,
                "skew_ms": round(skew)}

    def _size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def prune(self, now: float | None = None) -> int:
        now = time.time() if now is None else float(now)
        floor = now - self.keep_s
        with self.lock:
            self._pruned = now
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return 0
            keep = []
            for line in lines:
                try:
                    if float(json.loads(line).get("rx") or 0) >= floor:
                        keep.append(line)
                except Exception:  # noqa: BLE001 - a torn line goes
                    continue
            # and by size: the newest rows win
            total, cut = 0, len(keep)
            for i in range(len(keep) - 1, -1, -1):
                total += len(keep[i].encode("utf-8")) + 1
                if total > self.max_bytes * 0.8:
                    cut = i + 1
                    break
            else:
                cut = 0
            keep = keep[cut:]
            dropped = len(lines) - len(keep)
            if dropped:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text("".join(x + "\n" for x in keep), encoding="utf-8")
                os.replace(tmp, self.path)
            return dropped

    def read(self, since: float = 0.0, until: float = 0.0) -> list[dict[str, Any]]:
        until = until or 1e15
        out = []
        with self.lock:
            try:
                fh = self.path.open("r", encoding="utf-8")
            except OSError:
                return []
            with fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    t = float(r.get("rx") or 0)
                    # a receipt is written after its clip: read a margin past `until`
                    if since - 600 <= t <= until + 600:
                        out.append(r)
        return out


# ------------------------------------------------------------ script rows

def is_script_sfx(row: dict[str, Any], board: Iterable[str] = ("board",)) -> bool:
    return str(row.get("kind") or "") == "sfx" or str(row.get("who") or "") in set(board)


def script_rows(air_log: Any, since: float, until: float = 0.0,
                board: Iterable[str] = ("board",), chunk: int = 1 << 20) -> list[dict[str, Any]]:
    """The script's SFX rows in [since, until], read from the END of the air
    log (29 MB and growing - never the whole file for an hour's question)."""
    until = until or 1e15
    path = Path(air_log)
    rows: list[dict[str, Any]] = []
    try:
        size = path.stat().st_size
    except OSError:
        return rows
    board = tuple(board)
    with path.open("rb") as fh:
        pos, tail, done = size, b"", False
        while pos > 0 and not done:
            step = min(chunk, pos)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + tail
            parts = buf.split(b"\n")
            tail = parts[0] if pos > 0 else b""
            body = parts[1:] if pos > 0 else parts
            older = 0
            for raw in reversed(body):
                if not raw.strip():
                    continue
                try:
                    r = json.loads(raw)
                except Exception:  # noqa: BLE001
                    continue
                at = float(r.get("air_at") or r.get("ts") or 0)
                if float(r.get("ts") or at) < since - 900:
                    older += 1
                    if older > 200:           # well past the window: stop
                        done = True
                        break
                    continue
                if since <= at <= until and is_script_sfx(r, board):
                    rows.append(r)
    # read newest first: the air log is append-only, so the first copy of an
    # id met here is its latest rewrite (the one with the hearing stamp)
    seen: dict[str, dict[str, Any]] = {}
    for r in rows:
        seen.setdefault(str(r.get("id") or id(r)), r)
    return sorted(seen.values(), key=lambda r: float(r.get("air_at") or r.get("ts") or 0))


# ------------------------------------------------------------------ the join

def _played(row: dict[str, Any]) -> dict[str, Any]:
    heard = float(row.get("heard_ack_at") or 0)
    aired = str(row.get("aired") or "")
    if heard:
        return {"state": "heard", "at": heard, "by": str(row.get("heard_ack_by") or "")}
    if aired in ("withdrawn", "dropped", "cut"):
        return {"state": "withdrawn", "why": str(row.get("withdrawn_why") or row.get("cut_why") or aired)}
    if aired:
        return {"state": "aired-unconfirmed", "aired": aired}
    return {"state": "not-aired"}


def _is_video(row: dict[str, Any]) -> bool | None:
    if row.get("video") is True or row.get("sfx_video_id"):
        return True
    if str(row.get("text") or "").startswith("\U0001f50a"):
        return None                      # a welded punct clip: the picture may ride silent
    if row.get("video") is False:
        return False
    url = str(row.get("url") or "")
    if re.search(r"\.(mp4|m4v|webm|mov|mkv)(\?|$)", url, re.I):
        return True
    # airlog_row_from writes `video` only when it is true: a sample row
    # without it is a sound with no picture
    return False


RANK = {"shown": 3, "partial": 2, "not_shown": 1}
# on a tie the surface that owns the picture wins: the native wall over the
# page copy it retired, the tube over the Message view's muted echo
SURFACE_RANK = {"native_wall": 3, "tube": 2, "endless_wall": 2, "bubble": 1}


def _rank(rc: dict[str, Any]) -> tuple[int, int]:
    return (RANK.get(str(rc.get("outcome")), 0), SURFACE_RANK.get(str(rc.get("surface")), 0))


def _when(rc: dict[str, Any]) -> float:
    return float(rc.get("due") or rc.get("requested") or rc.get("first_frame") or rc.get("rx") or 0)


def _brief(rc: dict[str, Any]) -> dict[str, Any]:
    lag = rc.get("first_frame_lag_ms")
    return {"surface": rc.get("surface"), "outcome": rc.get("outcome"),
            "reason": rc.get("reason") or "", "rect": rc.get("rect"),
            "unoccluded": rc.get("unoccluded"), "occluder": rc.get("occluder") or "",
            "first_frame_lag_ms": lag, "first_frame_via": rc.get("first_frame_via") or "",
            "shown_s": rc.get("shown_s"), "frames": rc.get("frames"),
            "dropped": rc.get("dropped"), "stalls": rc.get("stalls"),
            "error": rc.get("error") or "", "error_code": rc.get("error_code") or 0,
            "display": rc.get("display"), "hidden_s": rc.get("hidden_s"),
            "silent": rc.get("silent"), "replay": rc.get("replay"),
            "delivery_id": rc.get("delivery_id") or "", "rid": rc.get("rid") or "",
            "sentence": sentence(rc)}


def sentence(rc: dict[str, Any], player: str = "") -> str:
    """"Displayed on PineTab: web tube 355x201, 4.1 s, first frame +180 ms"
    or "Not shown on PineTab: <reason>"."""
    who = PLAYER_WORDS.get(player or str(rc.get("player") or ""), str(rc.get("player") or "a player"))
    surf = SURFACE_WORDS.get(str(rc.get("surface") or ""), str(rc.get("surface") or ""))
    rect = rc.get("rect") or {}
    size = ("%dx%d" % (rect.get("w") or 0, rect.get("h") or 0)) if (rect.get("w") or rect.get("h")) else ""
    if rc.get("outcome") in ("shown", "partial"):
        bits = [" ".join(x for x in (surf, size) if x)]
        bits.append("%.1f s" % float(rc.get("shown_s") or 0))
        lag = rc.get("first_frame_lag_ms")
        if lag is not None and rc.get("first_frame"):
            bits.append("first frame %+d ms" % int(lag))
        uo = rc.get("unoccluded")
        if uo is not None and float(uo) < 1:
            bits.append("%d%% unoccluded" % round(float(uo) * 100))
        head = "Displayed" if rc.get("outcome") == "shown" else "Barely displayed"
        return "%s on %s: %s" % (head, who, ", ".join(b for b in bits if b))
    return "Not shown on %s: %s" % (who, rc.get("reason") or rc.get("error") or "no reason given")


def _beat_near(beats: list[dict[str, Any]], player: str, at: float, span: float = 240.0) -> dict[str, Any] | None:
    best, gap = None, span
    for b in beats:
        if b.get("player") != player:
            continue
        d = abs(float(b.get("at") or 0) - at)
        if d <= gap:
            best, gap = b, d
    return best


def audit(rows: list[dict[str, Any]], receipts: list[dict[str, Any]], since: float,
          until: float, line: str = "", origin: Any = None) -> dict[str, Any]:
    """Per script SFX row: what the script said, whether it played (heard
    receipt), whether it DISPLAYED on each player (surface, rect, first frame,
    seconds), the operator's reaction, and the reason when it was not shown."""
    recs = [r for r in receipts if r.get("kind") == "receipt"]
    acts = [r for r in receipts if r.get("kind") == "interaction"]
    beats = [r for r in receipts if r.get("kind") == "beat"]
    players = sorted({str(r.get("player")) for r in receipts if r.get("player")})
    used: set[int] = set()
    by_line: dict[str, list[int]] = {}
    by_delivery: dict[str, list[int]] = {}
    for i, rc in enumerate(recs):
        if rc.get("line"):
            by_line.setdefault(str(rc["line"]), []).append(i)
        if rc.get("delivery_id"):
            by_delivery.setdefault(str(rc["delivery_id"]), []).append(i)
    out_rows = []
    for row in rows:
        rid = str(row.get("id") or "")
        if line and rid != line:
            continue
        at = float(row.get("air_at") or row.get("ts") or 0)
        sfx = str(row.get("sfx") or row.get("sfx_video_id") or sfx_of_url(row.get("url")))
        tkey = text_key(row.get("text"))
        mine: list[int] = []
        for i in by_line.get(rid, []) + by_delivery.get(str(row.get("delivery_id") or "-"), []):
            if i not in used and i not in mine:
                mine.append(i)
        if not mine:
            # no id on the receipt (an older client, the endless set): the
            # same clip at the same moment - one per player, the nearest
            near: dict[str, tuple[float, int]] = {}
            for i, rc in enumerate(recs):
                if i in used or rc.get("line"):
                    continue
                same = (sfx and rc.get("sfx") == sfx) or (tkey and text_key(rc.get("sting")) == tkey)
                if not same:
                    continue
                d = abs(_when(rc) - at)
                if d <= MATCH_S:
                    p = str(rc.get("player"))
                    if p not in near or d < near[p][0]:
                        near[p] = (d, i)
            mine = [i for _, i in near.values()]
        used.update(mine)
        per: dict[str, dict[str, Any]] = {}
        for i in mine:
            rc = recs[i]
            p = str(rc.get("player"))
            cur = per.get(p)
            if cur is None:
                per[p] = {"_rc": rc, "count": 1, "_all": [rc]}
                continue
            cur["count"] += 1
            cur["_all"].append(rc)
            if _rank(rc) > _rank(cur["_rc"]):
                cur["_rc"] = rc
        video = _is_video(row)
        displays: dict[str, Any] = {}
        for p in players:
            if p in per:
                rc = per[p]["_rc"]
                d = _brief(rc)
                d["sentence"] = sentence(rc, p)
                d["receipts"] = per[p]["count"]
                # how else it was on that glass: the Message view's copy, the tube it left
                d["also"] = [sentence(o, p) + " (%s)" % SURFACE_WORDS.get(str(o.get("surface")), "")
                             for o in per[p]["_all"] if o is not rc][:4]
                displays[p] = d
                continue
            beat = _beat_near(beats, p, at)
            if video is False:
                why = "audio-only clip: no picture to show"
                surface = "audio_only"
            elif beat is None:
                why = "no receipt, and the player was not reporting then (off, asleep, or an older build)"
                surface = "none"
            elif beat.get("screen_on") is False:
                why = "display off"
                surface = "none"
            elif not beat.get("tv_on") and not beat.get("wall_on"):
                why = "the TV was off"
                surface = "none"
            elif beat.get("hidden"):
                why = "the page was hidden"
                surface = "none"
            else:
                why = ("never reached the set (not offered, or dropped before a receipt)"
                       if video else "no picture reached the set (audio clip or silent welded cue)")
                surface = "none"
            displays[p] = {"surface": surface, "outcome": "not_shown", "reason": why,
                           "sentence": "Not shown on %s: %s" % (PLAYER_WORDS.get(p, p), why),
                           "receipts": 0}
        reacted = []
        rids = {str(recs[i].get("rid")) for i in mine if recs[i].get("rid")}
        for rc_i in mine:
            for x in recs[rc_i].get("interactions") or []:
                reacted.append({"player": recs[rc_i].get("player"), "what": x.get("what"), "at": x.get("at"),
                                "during": True})
        for a in acts:
            if (a.get("rid") and a.get("rid") in rids) or (a.get("line") and a.get("line") == rid) \
                    or (sfx and a.get("sfx") == sfx and 0 <= float(a.get("at") or 0) - at <= 120):
                if not any(r["what"] == a.get("what") and r.get("player") == a.get("player")
                           and abs(float(r["at"] or 0) - float(a.get("at") or 0)) < 2 for r in reacted):
                    reacted.append({"player": a.get("player"), "what": a.get("what"), "at": a.get("at"),
                                    "during": bool(a.get("during"))})
        item = {"line": rid, "at": round(at, 3), "text": str(row.get("text") or "")[:160],
                "script": "A sting off the board: %s" % (" ".join(str(row.get("text") or "").split()) or "a cue"),
                "sfx": sfx, "video": video, "seconds": float(row.get("seconds") or 0),
                "played": _played(row), "displays": displays,
                "displayed": any(d.get("outcome") in ("shown", "partial") for d in displays.values()),
                "reactions": sorted(reacted, key=lambda r: float(r.get("at") or 0))}
        if origin is not None:
            try:
                got = origin(rid)
                if isinstance(got, dict):
                    item["origin"] = {k: got.get(k) for k in ("verdict", "road", "producer") if k in got}
            except Exception:  # noqa: BLE001 - the origin is a nicety here
                pass
        out_rows.append(item)
    unscripted: dict[str, int] = {}
    for i, rc in enumerate(recs):
        if i in used or not (since - 60 <= _when(rc) <= until + 60):
            continue
        key = "%s/%s/%s" % (rc.get("player"), rc.get("surface"),
                            "replay" if rc.get("replay") else ("endless" if rc.get("endless") else "other"))
        unscripted[key] = unscripted.get(key, 0) + 1
    return {"schema": SCHEMA, "since": since, "until": until, "players": players,
            "rows": out_rows, "summary": summarise(out_rows, players), "unscripted": unscripted}


def _median(xs: list[float]) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else round((xs[m - 1] + xs[m]) / 2.0, 2)


def summarise(rows: list[dict[str, Any]], players: list[str]) -> dict[str, Any]:
    played = sum(1 for r in rows if r["played"]["state"] == "heard")
    per: dict[str, Any] = {}
    for p in players:
        shown = partial = 0
        reasons: dict[str, int] = {}
        surfaces: dict[str, int] = {}
        lags, secs = [], []
        pictures = 0
        for r in rows:
            d = r["displays"].get(p)
            if not d or r.get("video") is False:
                continue
            pictures += 1
            if d["outcome"] == "shown":
                shown += 1
            elif d["outcome"] == "partial":
                partial += 1
            else:
                key = str(d.get("reason") or "unknown").split(":")[0][:90]
                reasons[key] = reasons.get(key, 0) + 1
            if d["outcome"] != "not_shown":
                surfaces[d["surface"]] = surfaces.get(d["surface"], 0) + 1
                if d.get("first_frame_lag_ms") is not None:
                    lags.append(float(d["first_frame_lag_ms"]))
                secs.append(float(d.get("shown_s") or 0))
        per[p] = {"picture_rows": pictures, "displayed": shown, "partial": partial,
                  "not_displayed": pictures - shown - partial,
                  "displayed_rate": round(shown / pictures, 3) if pictures else None,
                  "not_displayed_by_reason": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
                  "surfaces": surfaces, "first_frame_lag_ms_median": _median(lags),
                  "shown_s_median": _median(secs)}
    return {"script_sfx_rows": len(rows),
            "picture_rows": sum(1 for r in rows if r.get("video") is not False),
            "audio_only_rows": sum(1 for r in rows if r.get("video") is False),
            "played_heard": played,
            "played_rate": round(played / len(rows), 3) if rows else None,
            "displayed_anywhere": sum(1 for r in rows if r["displayed"]),
            "reactions": sum(len(r["reactions"]) for r in rows),
            "players": per}


def format_text(rep: dict[str, Any], most: int = 60) -> str:
    """The CLI's page: the summary first, then one line per script row."""
    s = rep["summary"]
    out = ["SFX display audit  %s .. %s  (%s)" % (
        time.strftime("%H:%M:%S", time.localtime(rep["since"])),
        time.strftime("%H:%M:%S", time.localtime(rep["until"])), SCHEMA),
        "script SFX rows %d  (pictures %d, audio-only %d)  heard %d%s  displayed anywhere %d  reactions %d" % (
            s["script_sfx_rows"], s["picture_rows"], s["audio_only_rows"], s["played_heard"],
            (" (%.0f%%)" % (100 * s["played_rate"])) if s["played_rate"] is not None else "",
            s["displayed_anywhere"], s["reactions"])]
    for p, v in s["players"].items():
        out.append("  %-8s pictures %d: displayed %d, partial %d, not %d%s; lag~%s ms, on screen~%s s" % (
            p, v["picture_rows"], v["displayed"], v["partial"], v["not_displayed"],
            (" (%.0f%%)" % (100 * v["displayed_rate"])) if v["displayed_rate"] is not None else "",
            v["first_frame_lag_ms_median"], v["shown_s_median"]))
        for why, n in v["not_displayed_by_reason"].items():
            out.append("           %4d  %s" % (n, why))
    if rep.get("unscripted"):
        out.append("receipts with no script row: " + ", ".join(
            "%s=%d" % kv for kv in sorted(rep["unscripted"].items())))
    out.append("")
    for r in rep["rows"][-most:]:
        out.append("%s  %-10s %-18s %s" % (time.strftime("%H:%M:%S", time.localtime(r["at"])),
                                          r["line"][:10], r["played"]["state"], r["text"][:60]))
        for p, d in r["displays"].items():
            out.append("            %s" % d["sentence"])
            for also in d.get("also") or []:
                out.append("              also %s" % also)
        for x in r["reactions"]:
            out.append("            reaction: %s %s%s" % (x.get("player"), x.get("what"),
                                                        " (during)" if x.get("during") else ""))
    return "\n".join(out)


# ------------------------------------------------------------- the station

def install(app: Any, namespace: dict[str, Any]) -> ReceiptStore | None:
    """POST /api/sfx/display-receipts (batched from each player) and
    GET /api/sfx/display-audit?hours=N | ?line=ID."""
    data_path = namespace["data_path"]
    store = ReceiptStore(data_path(STORE_NAME))
    namespace["_SFX_DISPLAY_STORE"] = store
    air_log = namespace.get("AIR_LOG_PATH") or data_path("air_log.jsonl")
    board = tuple(namespace.get("SCREENPLAY_BOARD") or ("board",))

    def _auth(fn_name: str, authorization: Any) -> None:
        fn = namespace.get(fn_name)
        if callable(fn):
            fn(authorization)

    def _ring_rows(since: float, until: float) -> list[dict[str, Any]]:
        radio = namespace.get("_RADIO") or {}
        out = []
        for e in list(radio.get("chat") or [])[-400:]:
            if not isinstance(e, dict) or not e.get("id") or not is_script_sfx(e, board):
                continue
            at = float(e.get("air_at") or e.get("ts") or 0)
            if since <= at <= until:
                out.append(dict(e))
        return out

    def _origin(lid: str) -> Any:
        led = namespace.get("_ORIGIN_LEDGER")
        return led.get(lid) if led is not None else None

    def run_audit(hours: float, line: str, now: float) -> dict[str, Any]:
        since = now - hours * 3600.0
        if line:
            since = now - KEEP_S
        rows = {str(r.get("id")): r for r in script_rows(air_log, since, now, board)}
        for r in _ring_rows(since, now):
            rows.setdefault(str(r.get("id")), r)
        ordered = sorted(rows.values(), key=lambda r: float(r.get("air_at") or r.get("ts") or 0))
        if line:
            hit = [r for r in ordered if str(r.get("id")) == line]
            if hit:
                at = float(hit[0].get("air_at") or hit[0].get("ts") or 0)
                since, now = at - 120, at + 600
        return audit(ordered, store.read(since, now), since, now, line=line,
                     origin=_origin if (line or len(ordered) <= 150) else None)

    @app.post("/api/sfx/display-receipts")
    async def sfx_display_receipts_api(request: Request,
                                       authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _auth("require_auth", authorization)      # a write: the station key, as every set's POST carries
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="a JSON body is required") from exc
        import asyncio
        addr = str(getattr(request.client, "host", "") or "")
        got = await asyncio.to_thread(store.append, body, addr)
        # [mp4only-undecodable] a clip no player could open is quarantined
        hook = namespace.get("sfx_quarantine_receipts")
        if callable(hook):
            try:
                await asyncio.to_thread(hook, body)
            except Exception:  # noqa: BLE001
                pass
        return got

    @app.get("/api/sfx/display-audit")
    async def sfx_display_audit_api(hours: float = 1.0, line: str = "", text: int = 0,
                                    authorization: str | None = Header(default=None)) -> Any:
        _auth("require_read_auth", authorization)
        import asyncio
        hours = max(0.05, min(168.0, float(hours or 1.0)))
        rep = await asyncio.to_thread(run_audit, hours, _ident(line, 80), time.time())
        rep["store"] = {"path": str(store.path), "keep_days": KEEP_S / 86400, **store.stats}
        if int(text or 0):
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(format_text(rep))
        return rep

    return store
