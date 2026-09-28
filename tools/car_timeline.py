#!/usr/bin/env python3
"""tools/car_timeline.py - #1476: one drive, told in order.

    python3 tools/car_timeline.py latest [--from HH:MM --to HH:MM] [--all] [--json]
    python3 tools/car_timeline.py <sid>  [--from HH:MM --to HH:MM] [--all] [--json]
    python3 tools/car_timeline.py list

WHY THIS EXISTS. The first real drive (2026-09-27) was reconstructed after
the fact from three ledgers and a memory: the phone opened the station during
an eleven-minute outage, was locked, and nothing retried for twenty minutes;
later Tailscale dropped at 16:02:52 and the phone carried on over the Funnel.
Every one of those facts was on disk somewhere, in a different file, in a
different clock. This puts them on one page.

The tune page posts its telemetry continuously (frontend/car-diag.js) and the
station files each batch in data/car_sessions/<date>_<sid>.jsonl beside what
it was doing itself. This reads that file and, for the same window, the HLS
ledger rows for that listener's token (data/hls_ledger.jsonl and its .1), the
dead-air ledger (data/gap_log.jsonl) and the restart log (data/boot_log.jsonl),
and prints one merged timeline in the station's local time (America/Chicago -
CDT in summer; the DGX host's own clock is CST, so the host clock is NOT used)
under a header that answers "why did it lag": road changes, stalls with their
durations, freezes, reconnects, station restarts, segment-request gaps over
6 s, and dead-air gaps.

Stdlib only, read-only, bounded reads (the ledgers only grow; they are read
backwards from the end and the read stops at the window). app.py imports
build_timeline() and summarize() from this file for GET /api/car/sessions/{sid},
so the API and the terminal tell the same story.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ: Any = ZoneInfo("America/Chicago")
except Exception:  # noqa: BLE001 - no tzdata: the summer offset
    LOCAL_TZ = timezone(timedelta(hours=-5), "CDT")

SESSION_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_([A-Za-z0-9_-]{6,40})\.jsonl$")
SEG_GAP_S = 6.0                  # the ledger's own stall threshold (#1475)
PAD_S = 60.0                     # context either side of the drive
READ_CAP = 24 * 1024 * 1024      # never read more than this of one ledger
SRC_ORDER = {"station": 0, "air": 1, "hls": 2, "phone": 3}
TROUBLE_KINDS = ("stall", "freeze", "error", "reconnect", "road_change",
                 "station_restart", "offline")
SECONDS_KEYS = ("seconds", "s", "dur_s", "duration_s", "stalled_s", "for_s",
                "secs", "dur", "gap_s")


# --- small readers ----------------------------------------------------------

def default_data_dir() -> Path:
    env = os.getenv("SPARK_AGENT_DATA_DIR", "")
    if env and Path(env).is_dir():
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data"


def epoch(v: Any) -> float | None:
    """Seconds since the epoch from seconds or milliseconds, else None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f <= 0:
        return None
    if f > 1e12:
        f /= 1000.0
    return f


def num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def local(t: float, fmt: str = "%H:%M:%S") -> str:
    return datetime.fromtimestamp(float(t), LOCAL_TZ).strftime(fmt)


def session_files(data_dir: Path) -> list[Path]:
    d = Path(data_dir) / "car_sessions"
    try:
        out = [p for p in d.iterdir() if SESSION_RE.match(p.name)]
    except (FileNotFoundError, NotADirectoryError):
        return []
    out.sort(key=lambda p: p.stat().st_mtime)
    return out


def find_session(data_dir: Path, which: str) -> Path | None:
    files = session_files(data_dir)
    if not files:
        return None
    if which in ("", "latest", "last"):
        return files[-1]
    exact = [p for p in files if SESSION_RE.match(p.name).group(2) == which]
    if exact:
        return exact[-1]
    loose = [p for p in files if which in p.name]
    return loose[-1] if loose else None


def load_session(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, "rb") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:  # noqa: BLE001 - a torn last line
                continue
            if isinstance(r, dict):
                rows.append(r)
    return rows


def rows_between(path: Path, t0: float, t1: float, tkey: str,
                 needle: bytes = b"", cap: int = READ_CAP
                 ) -> tuple[list[dict[str, Any]], bool]:
    """Rows of a jsonl file whose `tkey` lies in [t0, t1], oldest first.

    Read BACKWARDS from the end in 1 MB blocks, and no further back than the
    first block that reaches ten minutes before t0 (rows are appended in
    roughly time order; the margin covers a ledger that stamps a gap with
    its START and writes it at its end). The time is pulled out of each line
    with a regex so only rows in the window are JSON-parsed. The second
    value says whether the read reached the start of the file without
    passing t0 - i.e. an older rotation may hold more of the window."""
    pat = re.compile(rb'"' + tkey.encode() + rb'":\s*([0-9]+(?:\.[0-9]+)?)')
    out: list[dict[str, Any]] = []
    try:
        fh = open(path, "rb")
    except OSError:
        return out, True
    with fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        carry = b""
        read = 0
        done = False
        while pos > 0 and read < cap and not done:
            step = min(1 << 20, pos)
            pos -= step
            fh.seek(pos)
            chunk = fh.read(step) + carry
            read += step
            lines = chunk.split(b"\n")
            if pos > 0:
                carry = lines[0]
                lines = lines[1:]
            else:
                carry = b""
            for ln in reversed(lines):
                m = pat.search(ln)
                if not m:
                    continue
                t = float(m.group(1))
                if t > 1e12:
                    t /= 1000.0
                if t < t0:
                    if t < t0 - 600.0:
                        done = True
                    continue
                if t > t1 or (needle and needle not in ln):
                    continue
                try:
                    r = json.loads(ln)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(r, dict):
                    out.append(r)
        reached_start = pos == 0 and not done
    out.reverse()
    return out, reached_start


def ledger_rows(data_dir: Path, tails: list[str], t0: float,
                t1: float) -> list[dict[str, Any]]:
    """The HLS ledger rows for these token tails, from the live file and,
    when the window reaches back past its start, the rotated .1."""
    if not tails:
        return []
    needle = (('"tail":"%s"' % tails[0]).encode() if len(tails) == 1 else b"")
    base = Path(data_dir) / "hls_ledger.jsonl"
    out: list[dict[str, Any]] = []
    for path in (base, base.with_name(base.name + ".1")):
        rows, reached_start = rows_between(path, t0, t1, "ts", needle)
        out = [r for r in rows if str(r.get("tail") or "") in tails] + out
        if not reached_start:
            break
    out.sort(key=lambda r: epoch(r.get("ts")) or 0.0)
    return out


def gap_rows(data_dir: Path, t0: float, t1: float) -> list[dict[str, Any]]:
    """Dead-air gaps that overlap [t0, t1]."""
    rows, _ = rows_between(Path(data_dir) / "gap_log.jsonl", t0 - 300.0, t1,
                           "at")
    out = []
    for r in rows:
        at = epoch(r.get("at"))
        if at is None:
            continue
        until = epoch(r.get("until")) or at
        if until < t0 or at > t1:
            continue
        out.append(r)
    return out


def boot_rows(data_dir: Path, t0: float, t1: float) -> list[dict[str, Any]]:
    rows, _ = rows_between(Path(data_dir) / "boot_log.jsonl", t0, t1, "at",
                           cap=4 << 20)
    return rows


# --- the phone's rows, compacted -------------------------------------------

def event_kind(e: dict[str, Any]) -> str:
    return str(e.get("kind") or e.get("k") or e.get("type") or "event")[:40]


def event_time(e: dict[str, Any]) -> float | None:
    for k in ("t", "at", "ts", "time"):
        t = epoch(e.get(k))
        if t is not None:
            return t
    return None


def event_detail(e: dict[str, Any]) -> dict[str, Any]:
    d = e.get("detail")
    if isinstance(d, dict):
        return d
    return {k: v for k, v in e.items()
            if k not in ("kind", "k", "type", "t", "at", "ts", "time")}


def seconds_of(d: Any) -> float | None:
    if not isinstance(d, dict):
        return None
    for k in SECONDS_KEYS:
        v = num(d.get(k))
        if v is not None:
            return v
    for k in ("ms", "dur_ms", "duration_ms"):
        v = num(d.get(k))
        if v is not None:
            return v / 1000.0
    return None


def kv_text(d: dict[str, Any], limit: int = 170) -> str:
    bits = []
    for k, v in d.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v, separators=(",", ":"))[:60]
        elif isinstance(v, float):
            v = ("%.2f" % v).rstrip("0").rstrip(".")
        bits.append("%s=%s" % (k, v))
    text = " ".join(bits)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def compact_sample(s: dict[str, Any]) -> dict[str, Any]:
    c: dict[str, Any] = {}
    for k in ("road", "mode", "play", "vis", "online", "ct", "ahead", "rs",
              "ns", "paused", "adv", "reset", "ended", "reload"):
        if k in s:
            c[k] = s[k]
    pos = s.get("pos")
    if isinstance(pos, dict) and pos.get("kmh") is not None:
        c["kmh"] = pos.get("kmh")
    err = s.get("err")
    if isinstance(err, dict) and (err.get("code") or err.get("msg")):
        c["err"] = err.get("code") or str(err.get("msg") or "")[:60]
    ev = s.get("ev")
    if isinstance(ev, dict):
        hot = {k: v for k, v in ev.items() if v}
        if hot:
            c["ev"] = hot
    pg = s.get("pg")
    if isinstance(pg, dict) and pg:
        c["pg"] = pg
    conn = s.get("conn")
    if isinstance(conn, dict):
        net = conn.get("type") or conn.get("effectiveType") or conn.get("et")
        if net:
            c["net"] = net
    return c


def sample_notable(c: dict[str, Any]) -> bool:
    if c.get("err") or c.get("online") is False or c.get("reset") \
            or c.get("reload"):
        return True
    ev = c.get("ev") or {}
    if any(ev.get(k) for k in ("error", "stalled", "emptied", "ended")):
        return True
    if not c.get("play"):
        return False
    ahead, adv, rs = num(c.get("ahead")), num(c.get("adv")), num(c.get("rs"))
    return bool(c.get("paused")
                or (ahead is not None and ahead < 3.0)
                or (adv is not None and adv < 0.8)
                or (rs is not None and rs < 3))


def sample_text(c: dict[str, Any]) -> str:
    bits = []
    ahead = num(c.get("ahead"))
    bits.append("buf %.1fs" % ahead if ahead is not None else "buf -")
    adv = num(c.get("adv"))
    if adv is not None:
        bits.append("adv %.2f" % adv)
    if c.get("rs") is not None:
        bits.append("rs%s" % c.get("rs"))
    if c.get("play") is False:
        bits.append("not-playing")
    elif c.get("paused"):
        bits.append("PAUSED")
    if c.get("road"):
        bits.append(str(c.get("road")))
    if c.get("mode"):
        bits.append(str(c.get("mode")))
    if c.get("kmh") is not None:
        bits.append("%s km/h" % c.get("kmh"))
    if c.get("net"):
        bits.append(str(c.get("net")))
    if c.get("vis") and c.get("vis") != "visible":
        bits.append(str(c.get("vis")))
    if c.get("online") is False:
        bits.append("OFFLINE")
    if c.get("err"):
        bits.append("err=%s" % c.get("err"))
    if c.get("reset"):
        bits.append("src-reset")
    if c.get("reload"):
        bits.append("PAGE-RELOAD")
    if c.get("ev"):
        bits.append("ev{%s}" % ",".join("%s:%s" % kv for kv in
                                        sorted(c["ev"].items())))
    return " ".join(bits)


def compact_station(st: Any) -> dict[str, Any]:
    if not isinstance(st, dict):
        return {}
    out: dict[str, Any] = {}
    p = st.get("pulse")
    if isinstance(p, dict):
        out["pulse"] = {k: p.get(k) for k in ("window_s", "stalls", "worst_s",
                                              "stalled_s")}
    h = st.get("hls_since_last")
    if isinstance(h, list):
        out["hls_reqs"] = len(h)
        out["hls_segments"] = sum(1 for r in h if isinstance(r, dict)
                                  and str(r.get("k") or "").startswith("seg"))
    g = st.get("gaps_since_last")
    if isinstance(g, list):
        out["gaps"] = len(g)
        out["gap_s"] = round(sum(num(r.get("s")) or 0.0 for r in g
                                 if isinstance(r, dict)), 1)
    li = st.get("listener")
    if isinstance(li, dict):
        out["listener"] = {k: li.get(k) for k in ("road", "rate", "segments",
                                                  "stalls", "dropouts",
                                                  "worst_gap_s", "idle_s")}
    return out


def trouble_text(tr: dict[str, Any]) -> str:
    kind = str(tr.get("kind") or "?")
    det = tr.get("detail") if isinstance(tr.get("detail"), dict) else {}
    secs = seconds_of(det)
    text = "TROUBLE %s" % kind
    if secs is not None:
        text += " %.1f s" % secs
    rest = {k: v for k, v in det.items() if k not in SECONDS_KEYS}
    if rest:
        text += " " + kv_text(rest, 120)
    return text


def batch_text(r: dict[str, Any], st: dict[str, Any]) -> str:
    bits = ["batch #%s via %s" % (r.get("seq"), r.get("road_seen") or "?")]
    if r.get("boot_id"):
        bits.append("boot %s" % str(r.get("boot_id"))[:12])
    p = st.get("pulse") or {}
    if p:
        bits.append("loop %s stalls worst %ss" % (p.get("stalls"),
                                                  p.get("worst_s")))
    if "hls_reqs" in st:
        bits.append("%s hls reqs (%s seg)" % (st.get("hls_reqs"),
                                              st.get("hls_segments")))
    if st.get("gaps"):
        bits.append("%s dead-air gaps %.1fs" % (st.get("gaps"),
                                                st.get("gap_s") or 0.0))
    q = num(r.get("queued_s"))
    if q:
        bits.append("queued %.0fs on the phone" % q)
    tr = r.get("trouble")
    if isinstance(tr, dict) and tr.get("kind"):
        bits.append("trouble=%s" % tr.get("kind"))
    return " · ".join(bits)


def ledger_text(r: dict[str, Any]) -> str:
    kind = str(r.get("kind") or "?")
    text = "%s %sk %s %.1f kB %s ms %s" % (
        kind, r.get("rate"), r.get("name"),
        (num(r.get("bytes")) or 0.0) / 1000.0, r.get("ms"), r.get("road"))
    if r.get("stall"):
        text += " STALL(gap)"
    if r.get("dropout"):
        text += " DROPOUT"
    return text


# --- the merge --------------------------------------------------------------

def session_span(rows: list[dict[str, Any]]) -> tuple[float, float, list[str]]:
    lo: float | None = None
    hi: float | None = None
    tails: list[str] = []

    def see(t: float | None) -> None:
        nonlocal lo, hi
        if t is None:
            return
        lo = t if lo is None else min(lo, t)
        hi = t if hi is None else max(hi, t)

    for r in rows:
        see(epoch(r.get("at")))
        if r.get("kind") != "batch":
            continue
        tail = str(r.get("tail") or "")
        if tail and tail != "-" and tail not in tails:
            tails.append(tail)
        for s in r.get("samples") or []:
            if isinstance(s, dict):
                see(epoch(s.get("t") or s.get("at")))
        for e in r.get("events") or []:
            if isinstance(e, dict):
                see(event_time(e))
    return (lo or 0.0), (hi or 0.0), tails


def build_timeline(rows: list[dict[str, Any]], data_dir: Any = None,
                   t_from: float | None = None,
                   t_to: float | None = None) -> dict[str, Any]:
    """Every source, one list, sorted by time. Each entry is
    {t, src, kind, text, ...data}; `src` is phone | station | hls | air."""
    data_dir = Path(data_dir) if data_dir else default_data_dir()
    t0, t1, tails = session_span(rows)
    lo = t_from if t_from is not None else t0
    hi = t_to if t_to is not None else t1
    entries: list[dict[str, Any]] = []

    def add(t: float | None, src: str, kind: str, text: str,
            **data: Any) -> None:
        if t is None:
            return
        if t_from is not None and t < t_from:
            return
        if t_to is not None and t > t_to:
            return
        e: dict[str, Any] = {"t": round(t, 3), "src": src, "kind": kind,
                             "text": text}
        e.update(data)
        entries.append(e)

    for r in rows:
        k = r.get("kind")
        at = epoch(r.get("at"))
        if k == "batch":
            for s in r.get("samples") or []:
                if not isinstance(s, dict):
                    continue
                c = compact_sample(s)
                add(epoch(s.get("t") or s.get("at")), "phone", "sample",
                    sample_text(c), sample=c, notable=sample_notable(c))
            for e in r.get("events") or []:
                if not isinstance(e, dict):
                    continue
                kind = event_kind(e)
                det = event_detail(e)
                add(event_time(e) or at, "phone", kind,
                    (kind + " " + kv_text(det)).strip(), detail=det)
            tr = r.get("trouble")
            if isinstance(tr, dict) and tr.get("kind"):
                add(epoch(tr.get("at")) or at, "phone", "trouble",
                    trouble_text(tr), trouble=tr)
            st = compact_station(r.get("station"))
            add(at, "station", "batch", batch_text(r, st), seq=r.get("seq"),
                road=r.get("road_seen"), boot_id=r.get("boot_id"),
                queued_s=r.get("queued_s"), station=st)
        elif k == "voice":
            add(at, "phone", "voice", 'spoken note: "%s" (%s%s)' % (
                str(r.get("text") or "")[:200], r.get("file"),
                (", " + str(r.get("error"))[:80]) if r.get("error") else ""),
                file=r.get("file"), note=r.get("text"))
        elif k == "auto_report":
            add(at, "station", "auto_report", "filed Pine #%s: %s" % (
                r.get("id"), str(r.get("summary") or "")[:220]),
                id=r.get("id"), trouble=r.get("trouble"))
        elif k == "report":
            add(at, "phone", "report", "tapped a report -> Pine #%s (%s)" % (
                r.get("id"), r.get("file")), id=r.get("id"), file=r.get("file"))

    wlo, whi = lo - PAD_S, hi + PAD_S
    prev_seg: tuple[float, str] | None = None
    for r in ledger_rows(data_dir, tails, wlo, whi):
        t = epoch(r.get("ts"))
        if t is None:
            continue
        kind = str(r.get("kind") or "?")
        if kind == "segment":
            if prev_seg is not None and t - prev_seg[0] > SEG_GAP_S:
                add(t, "hls", "seg_gap",
                    "no segment asked for %.1f s (after %s; next %s)" % (
                        t - prev_seg[0], prev_seg[1], r.get("name")),
                    gap_s=round(t - prev_seg[0], 1), after=prev_seg[1],
                    road=r.get("road"))
            prev_seg = (t, str(r.get("name") or ""))
        add(t, "hls", "hls_" + kind, ledger_text(r),
            row={k2: r.get(k2) for k2 in ("kind", "rate", "name", "bytes",
                                          "ms", "road", "stall", "dropout")
                 if r.get(k2) is not None})

    for g in gap_rows(data_dir, wlo, whi):
        at = epoch(g.get("at"))
        secs = num(g.get("seconds")) or num(g.get("gap")) or 0.0
        add(at, "air", "dead_air", "dead air %.1f s - %s" % (
            secs, str(g.get("cause") or "?")[:100]),
            seconds=round(secs, 1), cause=str(g.get("cause") or "")[:100],
            until=epoch(g.get("until")))

    for b in boot_rows(data_dir, wlo, whi):
        at = epoch(b.get("at"))
        kind = str(b.get("kind") or "boot")
        if kind == "stop":
            text = "station stopped (pid %s, boot %s)" % (
                b.get("pid"), str(b.get("boot_id") or "")[:12])
        else:
            text = "STATION RESTART - booted pid %s, boot %s" % (
                b.get("pid"), str(b.get("boot_id") or "")[:12])
        add(at, "station", kind, text, boot_id=b.get("boot_id"),
            pid=b.get("pid"))

    entries.sort(key=lambda e: (e["t"], SRC_ORDER.get(e["src"], 9)))
    return {"from": round(lo, 3), "to": round(hi, 3), "tails": tails,
            "entries": entries}


def summarize(rows: list[dict[str, Any]],
              tl: dict[str, Any]) -> dict[str, Any]:
    """The header: what a person asks first about a drive that lagged."""
    entries = tl.get("entries") or []
    out: dict[str, Any] = {
        "road_changes": [], "stalls": [], "freezes": [], "reconnects": [],
        "wake_recovers": 0, "probes": [], "restarts": [], "seg_gaps": [],
        "dead_air": {"count": 0, "seconds": 0.0, "worst_s": 0.0,
                     "causes": {}},
        "troubles": {}, "batches": 0, "samples": 0, "voice": 0,
        "auto_reports": 0,
    }
    last_road = None
    last_boot = None
    for e in entries:
        k = e.get("kind")
        t = e.get("t")
        if k == "batch":
            out["batches"] += 1
            road = e.get("road")
            if road and last_road and road != last_road:
                out["road_changes"].append({"t": t, "from": last_road,
                                            "to": road, "seen_by": "station"})
            if road:
                last_road = road
            bid = e.get("boot_id")
            if bid and last_boot and bid != last_boot:
                out["restarts"].append({"t": t, "how": "boot id changed",
                                        "from": last_boot, "to": bid})
            if bid:
                last_boot = bid
        elif k == "sample":
            out["samples"] += 1
        elif k == "road_change":
            d = e.get("detail") or {}
            out["road_changes"].append({"t": t, "from": d.get("from"),
                                        "to": d.get("to") or d.get("road"),
                                        "seen_by": "phone"})
        elif k in ("stall", "freeze"):
            d = e.get("detail") or {}
            out["stalls" if k == "stall" else "freezes"].append(
                {"t": t, "seconds": seconds_of(d)})
        elif k == "reconnect":
            d = e.get("detail") or {}
            out["reconnects"].append({"t": t, "n": d.get("n"),
                                      "why": d.get("why"),
                                      "wait": d.get("wait")})
        elif k == "wake_recover":
            out["wake_recovers"] += 1
        elif k == "stream_probe":
            d = e.get("detail") or {}
            out["probes"].append({"t": t, "status": d.get("status"),
                                  "error": d.get("error")})
        elif k == "trouble":
            tr = e.get("trouble") or {}
            kind = str(tr.get("kind") or "?")
            out["troubles"][kind] = out["troubles"].get(kind, 0) + 1
            det = tr.get("detail") if isinstance(tr.get("detail"),
                                                 dict) else {}
            if kind in ("stall", "freeze") and not any(
                    abs((x.get("t") or 0) - (t or 0)) < 3
                    for x in out["stalls" if kind == "stall" else "freezes"]):
                out["stalls" if kind == "stall" else "freezes"].append(
                    {"t": t, "seconds": seconds_of(det), "from": "trouble"})
        elif k in ("boot", "stop"):
            if k == "boot":
                out["restarts"].append({"t": t, "how": "boot log",
                                        "to": e.get("boot_id")})
        elif k == "seg_gap":
            out["seg_gaps"].append({"t": t, "seconds": e.get("gap_s"),
                                    "road": e.get("road")})
        elif k == "dead_air":
            da = out["dead_air"]
            secs = float(e.get("seconds") or 0.0)
            da["count"] += 1
            da["seconds"] = round(da["seconds"] + secs, 1)
            da["worst_s"] = max(da["worst_s"], secs)
            cause = str(e.get("cause") or "?")[:60]
            da["causes"][cause] = da["causes"].get(cause, 0) + 1
        elif k == "voice":
            out["voice"] += 1
        elif k == "auto_report":
            out["auto_reports"] += 1
    # a restart seen both in the boot log and as a changed boot id is one
    seen: list[dict[str, Any]] = []
    for r in sorted(out["restarts"], key=lambda x: x.get("t") or 0):
        if r.get("how") == "boot id changed" and any(
                s.get("how") == "boot log" and s.get("to") == r.get("to")
                for s in out["restarts"]):
            continue
        seen.append(r)
    out["restarts"] = seen
    out["road_changes"].sort(key=lambda x: x.get("t") or 0)
    return out


def _clock(t: Any) -> str:
    try:
        return local(float(t))
    except Exception:  # noqa: BLE001
        return "--:--:--"


def header_lines(path: Path | str, rows: list[dict[str, Any]],
                 tl: dict[str, Any], sm: dict[str, Any]) -> list[str]:
    lo, hi = tl.get("from") or 0.0, tl.get("to") or 0.0
    m = SESSION_RE.match(Path(str(path)).name)
    sid = m.group(2) if m else "?"
    roads: list[str] = []
    for r in rows:
        rd = r.get("road_seen")
        if r.get("kind") == "batch" and rd and rd not in roads:
            roads.append(str(rd))
    out = [
        "car session %s  (%s)" % (sid, path),
        "window  %s -> %s %s  (%.1f min)   token tail %s" % (
            local(lo, "%Y-%m-%d %H:%M:%S") if lo else "?",
            local(hi) if hi else "?", local(hi, "%Z") if hi else "",
            max(0.0, hi - lo) / 60.0, ",".join(tl.get("tails") or []) or "-"),
        "batches %d · samples %d · roads %s · voice notes %d · auto-reports %d"
        % (sm["batches"], sm["samples"], " > ".join(roads) or "-",
           sm["voice"], sm["auto_reports"]),
    ]
    rc = sm["road_changes"]
    out.append("road changes   %s" % ("none" if not rc else "; ".join(
        "%s %s -> %s (%s)" % (_clock(x["t"]), x.get("from") or "?",
                              x.get("to") or "?", x.get("seen_by"))
        for x in rc)))
    st = sm["stalls"]
    out.append("stalls         %s" % ("none" if not st else "%d: %s" % (
        len(st), "; ".join("%s %s" % (_clock(x["t"]), (
            "%.1f s" % x["seconds"]) if x.get("seconds") is not None
            else "(no duration)") for x in st[:12]))))
    fr = sm["freezes"]
    out.append("freezes        %s" % ("none" if not fr else "%d: %s" % (
        len(fr), "; ".join("%s %s" % (_clock(x["t"]), (
            "%.1f s" % x["seconds"]) if x.get("seconds") is not None
            else "(no duration)") for x in fr[:12]))))
    rcn = sm["reconnects"]
    probes = sm["probes"]
    out.append("reconnects     %s%s%s" % (
        "none" if not rcn else "%d (first %s, last %s; why: %s)" % (
            len(rcn), _clock(rcn[0]["t"]), _clock(rcn[-1]["t"]),
            ", ".join(sorted({str(x.get("why") or "?")[:24]
                              for x in rcn}))[:120]),
        " · wake recoveries %d" % sm["wake_recovers"]
        if sm["wake_recovers"] else "",
        " · probes: %s" % ", ".join(
            "%s %s" % (_clock(p["t"]), p.get("status") if p.get("status")
                       else (p.get("error") or "offline"))
            for p in probes[:6]) if probes else ""))
    rs = sm["restarts"]
    out.append("station restarts %s" % ("none" if not rs else "%d: %s" % (
        len(rs), "; ".join("%s (%s)" % (_clock(x["t"]), x.get("how"))
                           for x in rs))))
    sg = sm["seg_gaps"]
    out.append("segment gaps>%.0fs %s" % (SEG_GAP_S, "none" if not sg else
                                         "%d: %s" % (len(sg), "; ".join(
                                             "%s %.1f s" % (_clock(x["t"]),
                                                            x["seconds"] or 0)
                                             for x in sg[:12]))))
    da = sm["dead_air"]
    out.append("dead air       %s" % ("none" if not da["count"] else
                                     "%d gaps, %.1f s total, worst %.1f s; %s"
                                     % (da["count"], da["seconds"],
                                        da["worst_s"], ", ".join(
                                            "%s x%d" % kv for kv in sorted(
                                                da["causes"].items(),
                                                key=lambda kv: -kv[1])[:4]))))
    if sm["troubles"]:
        out.append("troubles       %s" % ", ".join(
            "%s x%d" % kv for kv in sorted(sm["troubles"].items())))
    return out


def render(path: Path | str, rows: list[dict[str, Any]], tl: dict[str, Any],
           sm: dict[str, Any], show_all: bool = False) -> str:
    lines = header_lines(path, rows, tl, sm)
    lines.append("-" * 78)
    last_beat = 0.0
    for e in tl.get("entries") or []:
        k = str(e.get("kind") or "")
        t = float(e.get("t") or 0.0)
        if not show_all:
            if k == "sample":
                if not e.get("notable") and t - last_beat < 60.0:
                    continue
                if not e.get("notable"):
                    last_beat = t
            elif k.startswith("hls_"):
                row = e.get("row") or {}
                if not (row.get("stall") or row.get("dropout")):
                    continue
        lines.append("%s  %-7s %s" % (local(t), e.get("src"), e.get("text")))
    if not show_all:
        lines.append("-" * 78)
        lines.append("(quiet samples shown once a minute and HLS requests "
                     "only when flagged; --all prints every row)")
    return "\n".join(lines)


def parse_clock(text: str, ref: float) -> float:
    """HH:MM[:SS] in station time, on the day of `ref`."""
    parts = [int(x) for x in str(text).strip().split(":")]
    while len(parts) < 3:
        parts.append(0)
    day = datetime.fromtimestamp(ref, LOCAL_TZ)
    at = day.replace(hour=parts[0], minute=parts[1], second=parts[2],
                     microsecond=0)
    return at.timestamp()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="#1476: one drive's merged timeline (phone telemetry, "
                    "HLS ledger, dead air, restarts) in station time.")
    ap.add_argument("which", nargs="?", default="latest",
                    help="latest | list | <sid>")
    ap.add_argument("--from", dest="t_from", default=None,
                    help="HH:MM (station time)")
    ap.add_argument("--to", dest="t_to", default=None,
                    help="HH:MM (station time)")
    ap.add_argument("--all", action="store_true",
                    help="every sample and every HLS request")
    ap.add_argument("--json", action="store_true", help="the timeline as JSON")
    ap.add_argument("--data", default=None, help="the data/ directory")
    args = ap.parse_args(argv)
    data_dir = Path(args.data) if args.data else default_data_dir()

    if args.which == "list":
        files = session_files(data_dir)
        if not files:
            print("no car sessions under %s/car_sessions" % data_dir)
            return 1
        for p in reversed(files[-40:]):
            rows = load_session(p)
            lo, hi, tails = session_span(rows)
            print("%s  %s -> %s  %4d batches  %s" % (
                p.name, local(lo, "%m-%d %H:%M") if lo else "?",
                local(hi, "%H:%M") if hi else "?",
                sum(1 for r in rows if r.get("kind") == "batch"),
                ",".join(tails)))
        return 0

    path = find_session(data_dir, args.which)
    if path is None:
        print("no car session matching %r under %s/car_sessions"
              % (args.which, data_dir))
        return 1
    rows = load_session(path)
    t0, _t1, _ = session_span(rows)
    lo = parse_clock(args.t_from, t0) if args.t_from and t0 else None
    hi = parse_clock(args.t_to, t0) if args.t_to and t0 else None
    if lo is not None and hi is not None and hi < lo:
        hi += 86400.0
    tl = build_timeline(rows, data_dir, lo, hi)
    sm = summarize(rows, tl)
    if args.json:
        json.dump({"file": str(path), "summary": sm, "timeline": tl},
                  sys.stdout, indent=1, default=str)
        print()
        return 0
    print(render(path, rows, tl, sm, args.all))
    return 0


if __name__ == "__main__":
    sys.exit(main())
