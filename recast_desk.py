"""recast_desk - #1215: re-record the cupboard in a new seat voice while the
old recording keeps airing.

WHAT HAPPENED (measured on data/prep_shelf.json, 2026-09-21): at 11:29 on
2026-09-16 - eleven minutes after the operator filed #1215 - the co-host was
changed on the cast bar and pantry_keeper -> recast_sweep() -> _recast_round()
DELETED the co-host takes from 95 banked rounds (48 gallery, 47 manager; every
one still carries recast_at 11:29 / recast_seats ['cohost']). Each of them fell
below made == chunks, dialogue_audio_ready() refused it, and the cupboard went
dark for that seat until the recording room came back round - which, for a row
the four-hour desk was not naming, took days (#1363 later measured "284 of 289
cupboard rounds holding half their audio": that is the fingerprint of this).

THE RULE NOW: a recast is a SHADOW take set standing beside the takes, never
a hole cut into them.

    entry["recast"] = {"at": <opened>, "seats": {who: {"old", "new"}},
                       "takes": [{"i", "who", "text", "voice", "key",
                                  "made", "seconds", "old_key",
                                  "old_seconds"}, ...],
                       "want": n, "made": k, "keys": [made keys]}

The old takes stay exactly as they are, so the row stays READY and airs as
recorded. The desk in app.py (recast_tick -> prep_render_line) records the
shadow lines one at a time, and when every shadow line has audio the takes
are SWAPPED in one dict operation - swap_round() - so a round changes voice
between two airings, never during one. A single-line read (an advert, a
station ID) carries the same shadow on the row itself (open_read/swap_read);
reads are aired by (text, current voice) rather than by their stored key, so
app.py keeps a read off the air while its shadow is open and re-cuts reads
early in the worklist.

After a swap the row carries entry["recast_done"] = {"at", "seats", "lines",
"keys": [the old keys]} for DONE_KEYS_GRACE_S, so _row_clip_keys() still
finds the old clips and nothing prunes a file a staged performance may hold.

This module is pure bookkeeping over the station's own dicts: it never
touches the engine, the loop, the disk or app.py's globals. app.py hands in
a key function (text, voice -> pantry key), a have function (key -> {"seconds"}
when the clip exists now, else None) and a name function (voice -> name).
"""
from __future__ import annotations

import time
from typing import Any, Callable, Iterable

SHADOW = "recast"
DONE = "recast_done"
DONE_KEYS_GRACE_S = 3600.0
JOBS_KEPT = 8
FINISHED_RECENT_S = 120.0
# settings key -> the seat name takes carry (takes say "dj", never "host")
SETTINGS_SEATS = (("voice", "dj"), ("cohost_voice", "cohost"),
                  ("third_voice", "third"), ("drop_voice", "drop"))
SEAT_FACE = {"dj": "the host", "host": "the host", "cohost": "the co-host",
             "third": "the third seat", "drop": "the SFX guy"}
# render_seconds = 2.97 + 1.05 x audio_seconds (memory: render-is-slower-than-speech)
RENDER_FIXED_S = 2.97
RENDER_RATE = 1.05

KeyFn = Callable[[str, str], str]
HaveFn = Callable[[str], Any]
NameFn = Callable[[str], str]


# --- shapes ----------------------------------------------------------------

def carrier(row: Any) -> dict[str, Any] | None:
    """The dict that carries the takes: row["entry"] for a shelf round, the
    row itself for a larder round or a single-line read."""
    if not isinstance(row, dict):
        return None
    entry = row.get("entry")
    return entry if isinstance(entry, dict) else row


def shadow_of(row: Any) -> dict[str, Any] | None:
    c = carrier(row)
    if c is None:
        return None
    got = c.get(SHADOW)
    return got if isinstance(got, dict) else None


def in_flight(row: Any) -> bool:
    """A shadow is open on this row: the desk is still re-recording it, or
    waiting for it to leave the air so the takes can be swapped."""
    return shadow_of(row) is not None


def seat_voice(cast: dict[str, str] | None, who: Any) -> str:
    try:
        return str((cast or {}).get(str(who or "")) or "")
    except Exception:  # noqa: BLE001
        return ""


def _i(take: Any) -> int:
    try:
        return int((take or {}).get("i", -1))
    except (TypeError, ValueError):
        return -1


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def stale_takes(entry: dict[str, Any], cast: dict[str, str]) -> list[dict[str, Any]]:
    """The takes whose seat holds a different voice now."""
    out: list[dict[str, Any]] = []
    for take in (entry.get("takes") or []):
        if not isinstance(take, dict):
            continue
        want = seat_voice(cast, take.get("who"))
        if want and want != str(take.get("voice") or ""):
            out.append(take)
    return out


def round_whole(entry: dict[str, Any]) -> bool:
    """Every planned line has a take - the shape _ready_round_takes accepts.
    A round short of takes is the recording room's to finish (in the current
    cast); the desk only shadows what is airable now."""
    takes = [t for t in (entry.get("takes") or []) if isinstance(t, dict)]
    try:
        chunks = int(entry.get("chunks") or 0)
    except (TypeError, ValueError):
        chunks = 0
    if not takes or chunks <= 0 or len(takes) != chunks:
        return False
    return sorted(_i(t) for t in takes) == list(range(chunks))


def _tally(shadow: dict[str, Any]) -> None:
    takes = [t for t in (shadow.get("takes") or []) if isinstance(t, dict)]
    shadow["want"] = len(takes)
    shadow["made"] = sum(1 for t in takes if t.get("made"))
    shadow["keys"] = [str(t.get("key") or "") for t in takes
                      if t.get("made") and t.get("key")]


# --- rounds ----------------------------------------------------------------

def open_round(entry: dict[str, Any], cast: dict[str, str], key_fn: KeyFn,
               have_fn: HaveFn, now: float | None = None) -> dict[str, Any]:
    """Open (or refresh) the shadow on one banked round. Idempotent: a second
    call with the same cast opens nothing and changes nothing. A cast that has
    gone back to what the takes hold closes the shadow ("cancelled")."""
    now = now or time.time()
    out = {"opened": 0, "hits": 0, "want": 0, "made": 0, "complete": False,
           "cancelled": False, "skipped": ""}
    if not isinstance(entry, dict):
        out["skipped"] = "shape"
        return out
    done_expire(entry, now)
    takes = [t for t in (entry.get("takes") or []) if isinstance(t, dict)]
    held = entry.get(SHADOW) if isinstance(entry.get(SHADOW), dict) else None
    if not takes:
        if held is not None:
            entry.pop(SHADOW, None)
            out["cancelled"] = True
        out["skipped"] = "no takes"
        return out
    stale = stale_takes(entry, cast)
    if not stale:
        if held is not None:
            entry.pop(SHADOW, None)
            out["cancelled"] = True
        return out
    if not round_whole(entry):
        if held is not None:
            entry.pop(SHADOW, None)
            out["cancelled"] = True
        out["skipped"] = "partial"
        return out
    shadow = held if held is not None else {"at": now, "seats": {}, "takes": [],
                                            "want": 0, "made": 0, "keys": []}
    old_by_index = {_i(t): t for t in (shadow.get("takes") or [])
                    if isinstance(t, dict)}
    fresh: list[dict[str, Any]] = []
    seats: dict[str, dict[str, str]] = {}
    for take in stale:
        who = str(take.get("who") or "")
        new_voice = seat_voice(cast, who)
        index = _i(take)
        text = str(take.get("text") or "")
        key = str(key_fn(text, new_voice) or "") if text and new_voice else ""
        prev = old_by_index.get(index)
        if (prev is not None and str(prev.get("key") or "") == key
                and str(prev.get("voice") or "") == new_voice):
            row = prev
        else:
            row = {"i": index, "who": who, "text": text, "voice": new_voice,
                   "key": key, "made": False, "seconds": 0.0,
                   "old_key": str(take.get("key") or ""),
                   "old_seconds": _f(take.get("seconds"))}
            got = have_fn(key) if key else None
            if got:
                row["made"] = True
                row["seconds"] = _f((got if isinstance(got, dict) else {}).get("seconds"))
                out["hits"] += 1
            out["opened"] += 1
        fresh.append(row)
        seat = seats.setdefault(who, {"old": str(take.get("voice") or ""),
                                      "new": new_voice})
        seat["new"] = new_voice
    shadow["takes"] = sorted(fresh, key=_i)
    shadow["seats"] = seats
    _tally(shadow)
    entry[SHADOW] = shadow
    out.update(want=shadow["want"], made=shadow["made"],
               complete=shadow["want"] > 0 and shadow["made"] >= shadow["want"])
    return out


def unmade_takes(entry: dict[str, Any]) -> list[dict[str, Any]]:
    shadow = entry.get(SHADOW) if isinstance(entry, dict) else None
    if not isinstance(shadow, dict):
        return []
    return [t for t in (shadow.get("takes") or [])
            if isinstance(t, dict) and not t.get("made")]


def line_made(entry: dict[str, Any], index: int, made: dict[str, Any]) -> bool:
    """Record one rendered shadow line ({"key", "voice", "seconds"} - what
    prep_render_line hands back)."""
    shadow = entry.get(SHADOW) if isinstance(entry, dict) else None
    if not isinstance(shadow, dict) or not isinstance(made, dict):
        return False
    for take in (shadow.get("takes") or []):
        if isinstance(take, dict) and _i(take) == int(index):
            if made.get("key"):
                take["key"] = str(made["key"])
            if made.get("voice"):
                take["voice"] = str(made["voice"])
            take["seconds"] = _f(made.get("seconds")) or _f(take.get("seconds"))
            take["made"] = True
            _tally(shadow)
            return True
    return False


def complete(entry: dict[str, Any]) -> bool:
    shadow = entry.get(SHADOW) if isinstance(entry, dict) else None
    if not isinstance(shadow, dict) or "takes" not in shadow:
        return False
    _tally(shadow)
    return shadow["want"] > 0 and shadow["made"] >= shadow["want"]


def swap_round(entry: dict[str, Any], now: float | None = None) -> dict[str, Any] | None:
    """Every shadow line has audio: put the new takes in the old ones' places.
    One dict operation, no awaits - a round changes voice between airings.
    Returns the recast_done stamp, or None when there is nothing to swap."""
    if not complete(entry):
        return None
    now = now or time.time()
    shadow = entry[SHADOW]
    new_by_index = {_i(t): t for t in (shadow.get("takes") or []) if isinstance(t, dict)}
    takes = [t for t in (entry.get("takes") or []) if isinstance(t, dict)]
    old_keys: list[str] = []
    swapped = 0
    for take in takes:
        new = new_by_index.get(_i(take))
        if new is None or not new.get("key"):
            continue
        if str(take.get("key") or ""):
            old_keys.append(str(take["key"]))
        take["voice"] = str(new.get("voice") or "")
        take["key"] = str(new.get("key") or "")
        if _f(new.get("seconds")) > 0:
            take["seconds"] = _f(new.get("seconds"))
        swapped += 1
    entry["takes"] = takes
    entry["keys"] = list(dict.fromkeys(str(t.get("key")) for t in takes if t.get("key")))
    entry["seconds"] = round(sum(_f(t.get("seconds")) for t in takes), 2)
    stamp = {"at": now, "seats": dict(shadow.get("seats") or {}),
             "lines": swapped, "keys": old_keys}
    entry[DONE] = stamp
    entry.pop(SHADOW, None)
    return stamp


def done_expire(entry: dict[str, Any], now: float | None = None) -> bool:
    """The old clips are protected for an hour after a swap; then let go."""
    now = now or time.time()
    stamp = entry.get(DONE) if isinstance(entry, dict) else None
    if isinstance(stamp, dict) and stamp.get("keys") \
            and now - _f(stamp.get("at")) > DONE_KEYS_GRACE_S:
        stamp["keys"] = []
        return True
    return False


# --- single-line reads (adverts, station IDs) -----------------------------

def open_read(row: dict[str, Any], who: str, cast: dict[str, str], key_fn: KeyFn,
              have_fn: HaveFn, now: float | None = None) -> int:
    """Open a shadow on a read whose seat voice moved. 1 when newly opened."""
    if not isinstance(row, dict) or row.get("produced"):
        return 0
    now = now or time.time()
    done_expire(row, now)
    want = seat_voice(cast, who)
    old = str(row.get("voice") or "")
    text = str(row.get("text") or "")
    held = row.get(SHADOW) if isinstance(row.get(SHADOW), dict) else None
    if not want or not text or want == old or not str(row.get("key") or ""):
        # nothing to recast, the seat went back, or the read was never
        # voiced (the keeper records those in the current voice anyway)
        if held is not None:
            row.pop(SHADOW, None)
        return 0
    key = str(key_fn(text, want) or "")
    if held is not None and str(held.get("key") or "") == key:
        return 0
    shadow: dict[str, Any] = {"at": now, "who": str(who), "old": old, "new": want,
                              "key": key, "made": False, "seconds": 0.0, "keys": []}
    got = have_fn(key) if key else None
    if got:
        shadow["made"] = True
        shadow["seconds"] = _f((got if isinstance(got, dict) else {}).get("seconds"))
        shadow["keys"] = [key]
    row[SHADOW] = shadow
    return 1


def read_made(row: dict[str, Any], made: dict[str, Any]) -> bool:
    shadow = row.get(SHADOW) if isinstance(row, dict) else None
    if not isinstance(shadow, dict) or "takes" in shadow or not isinstance(made, dict):
        return False
    if made.get("key"):
        shadow["key"] = str(made["key"])
    if made.get("voice"):
        shadow["new"] = str(made["voice"])
    if made.get("engine"):
        shadow["engine"] = str(made["engine"])
    shadow["seconds"] = _f(made.get("seconds")) or _f(shadow.get("seconds"))
    shadow["made"] = True
    shadow["keys"] = [shadow["key"]] if shadow.get("key") else []
    return True


def swap_read(row: dict[str, Any], now: float | None = None) -> dict[str, Any] | None:
    shadow = row.get(SHADOW) if isinstance(row, dict) else None
    if not isinstance(shadow, dict) or "takes" in shadow or not shadow.get("made"):
        return None
    now = now or time.time()
    old_key = str(row.get("key") or "")
    row["voice"] = str(shadow.get("new") or "")
    row["key"] = str(shadow.get("key") or "")
    if _f(shadow.get("seconds")) > 0:
        row["seconds"] = _f(shadow.get("seconds"))
    if shadow.get("engine"):
        row["engine"] = str(shadow["engine"])
    stamp = {"at": now, "lines": 1, "keys": [old_key] if old_key else [],
             "seats": {str(shadow.get("who") or ""): {"old": str(shadow.get("old") or ""),
                                                       "new": str(shadow.get("new") or "")}}}
    row[DONE] = stamp
    row.pop(SHADOW, None)
    return stamp


# --- the worklist ----------------------------------------------------------

def _unaired(row: dict[str, Any]) -> bool:
    try:
        return not (_f(row.get("aired_at")) or int(row.get("aired") or 0))
    except (TypeError, ValueError):
        return True


def worklist(piles: Iterable[tuple[str, dict[str, Any], dict[str, Any] | None]],
             first_ids: Iterable[str] = (), busy: Iterable[int] = (),
             sid_fn: Callable[[str, dict[str, Any]], str] | None = None
             ) -> list[dict[str, Any]]:
    """What to record next, in air priority: rounds the four-hour desk has
    picked, then unheard rounds oldest first, then heard ones - with the
    reads (which cannot air at all until re-cut) dealt in one per round,
    reads first. `piles` is (kind, row, entry-or-None); `busy` is the ids of
    rows on the air right now."""
    first = set(str(x) for x in (first_ids or ()))
    busy_ids = set(busy or ())
    rounds: list[tuple[tuple, dict[str, Any]]] = []
    reads: list[dict[str, Any]] = []
    for kind, row, entry in piles:
        if not isinstance(row, dict) or id(row) in busy_ids:
            continue
        if entry is not None:
            if not isinstance(entry, dict):
                continue
            todo = unmade_takes(entry)
            if not todo:
                continue
            sid = ""
            if sid_fn is not None:
                try:
                    sid = str(sid_fn(kind, row) or "")
                except Exception:  # noqa: BLE001
                    sid = ""
            rank = (0 if sid and sid in first else 1,
                    0 if _unaired(row) else 1,
                    _f(row.get("at")) or _f(entry.get("at")))
            rounds.append((rank, {"kind": str(kind), "row": row, "entry": entry,
                                  "read": False, "takes": todo}))
        else:
            shadow = row.get(SHADOW)
            if not isinstance(shadow, dict) or "takes" in shadow or shadow.get("made"):
                continue
            reads.append({"kind": str(kind), "row": row, "entry": None,
                          "read": True, "takes": [],
                          "who": str(shadow.get("who") or ""),
                          "voice": str(shadow.get("new") or "")})
    rounds.sort(key=lambda pair: pair[0])
    ordered = [item for _rank, item in rounds]
    merged: list[dict[str, Any]] = []
    while ordered or reads:
        if reads:
            merged.append(reads.pop(0))
        if ordered:
            merged.append(ordered.pop(0))
    return merged


# --- the readout -----------------------------------------------------------

def _bucket(old: str, new: str) -> dict[str, Any]:
    return {"old": old, "new": new, "rounds_open": 0, "rounds_started": 0,
            "lines_want": 0, "lines_made": 0, "reads_open": 0, "reads_made": 0,
            "unmade_old_seconds": 0.0, "oldest_at": 0.0}


def census(piles: Iterable[tuple[str, dict[str, Any], dict[str, Any] | None]],
           now: float | None = None) -> dict[str, Any]:
    """Per seat: what is open and how far along; plus every recast_done stamp."""
    now = now or time.time()
    seats: dict[str, dict[str, Any]] = {}
    done: list[dict[str, Any]] = []
    for kind, row, entry in piles:
        target = entry if entry is not None else row
        if not isinstance(target, dict):
            continue
        shadow = target.get(SHADOW)
        if isinstance(shadow, dict):
            at = _f(shadow.get("at"))
            if "takes" in shadow:
                takes = [t for t in (shadow.get("takes") or []) if isinstance(t, dict)]
                for who, sv in (shadow.get("seats") or {}).items():
                    b = seats.setdefault(str(who), _bucket(str((sv or {}).get("old") or ""),
                                                           str((sv or {}).get("new") or "")))
                    mine = [t for t in takes if str(t.get("who") or "") == str(who)]
                    b["rounds_open"] += 1
                    if any(t.get("made") for t in mine):
                        b["rounds_started"] += 1
                    b["lines_want"] += len(mine)
                    b["lines_made"] += sum(1 for t in mine if t.get("made"))
                    b["unmade_old_seconds"] += sum(_f(t.get("old_seconds"))
                                                   for t in mine if not t.get("made"))
                    if at and (not b["oldest_at"] or at < b["oldest_at"]):
                        b["oldest_at"] = at
            else:
                who = str(shadow.get("who") or "")
                b = seats.setdefault(who, _bucket(str(shadow.get("old") or ""),
                                                  str(shadow.get("new") or "")))
                b["reads_open"] += 1
                if shadow.get("made"):
                    b["reads_made"] += 1
                else:
                    b["unmade_old_seconds"] += _f(row.get("seconds"))
                if at and (not b["oldest_at"] or at < b["oldest_at"]):
                    b["oldest_at"] = at
        stamp = target.get(DONE)
        if isinstance(stamp, dict):
            for who, sv in (stamp.get("seats") or {}).items():
                done.append({"who": str(who), "old": str((sv or {}).get("old") or ""),
                             "new": str((sv or {}).get("new") or ""),
                             "at": _f(stamp.get("at")), "read": entry is None,
                             "lines": int(stamp.get("lines") or 0)})
    return {"at": now, "seats": seats, "done": done}


def note_change(jobs: list[dict[str, Any]], old_dj: dict[str, Any],
                new_dj: dict[str, Any], now: float | None = None) -> list[str]:
    """The settings road: a seat's voice moved. Opens a job per changed seat
    and supersedes any live job on that seat. Returns the seats changed."""
    now = now or time.time()
    changed: list[str] = []
    for key, seat in SETTINGS_SEATS:
        old = str((old_dj or {}).get(key) or "")
        new = str((new_dj or {}).get(key) or "")
        if old == new:
            continue
        for job in jobs:
            if job.get("seat") == seat and not job.get("finished_at"):
                job["finished_at"] = now
                job["superseded"] = True
        jobs.append({"seat": seat, "old": old, "new": new, "at": now,
                     "finished_at": 0.0, "cancelled": False, "superseded": False,
                     "rounds_total": 0, "lines_total": 0, "reads_total": 0,
                     "said_start": False, "said_end": False})
        changed.append(seat)
    del jobs[:-JOBS_KEPT]
    return changed


def _eta(unmade_lines: int, unmade_old_seconds: float, speed: float) -> float:
    if unmade_lines <= 0:
        return 0.0
    base = unmade_lines * RENDER_FIXED_S + RENDER_RATE * max(0.0, unmade_old_seconds)
    return round(base * max(0.3, min(5.0, float(speed or 1.0))), 1)


def _about(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0))
    if seconds < 90:
        return "about a minute"
    if seconds < 3600:
        return "about %d min" % max(2, int(round(seconds / 60.0)))
    hours = seconds / 3600.0
    return "about %.1f h" % hours if hours < 10 else "about %d h" % int(round(hours))


def status(cen: dict[str, Any], jobs: list[dict[str, Any]], cast: dict[str, str],
           speed: float = 1.0, name_fn: NameFn | None = None,
           now: float | None = None) -> dict[str, Any]:
    """The readout GET /api/cast/recast serves, and the jobs' bookkeeping.

    Jobs come from note_change (the settings road) or are opened here when
    a shadow is found on a seat with no live job (set_guest, a settings
    file edited on disk, a restart part-way through - the state comparison
    cannot miss any of those). A job is live while its seat has open work;
    it finishes when the work is gone, and it is cancelled when the seat
    went back to the voice the takes already held."""
    now = now or time.time()
    name = name_fn or (lambda v: str(v or ""))
    seats = cen.get("seats") or {}
    done = cen.get("done") or []

    def live_job(seat: str) -> dict[str, Any] | None:
        for job in reversed(jobs):
            if job.get("seat") == seat and not job.get("finished_at"):
                return job
        return None

    for seat, b in seats.items():
        if not (b["rounds_open"] or b["reads_open"]):
            continue
        job = live_job(seat)
        if job is None or (job.get("new") and b["new"] and job["new"] != b["new"]):
            if job is not None:
                job["finished_at"] = now
                job["superseded"] = True
            jobs.append({"seat": seat, "old": b["old"], "new": b["new"],
                         "at": b["oldest_at"] or now, "finished_at": 0.0,
                         "cancelled": False, "superseded": False,
                         "rounds_total": 0, "lines_total": 0, "reads_total": 0,
                         "said_start": False, "said_end": False})
    del jobs[:-JOBS_KEPT]

    rows: list[dict[str, Any]] = []
    for job in jobs:
        seat = str(job.get("seat") or "")
        b = seats.get(seat) or _bucket(str(job.get("old") or ""), str(job.get("new") or ""))
        if not job.get("old") and b.get("old"):
            job["old"] = b["old"]
        if not job.get("new") and b.get("new"):
            job["new"] = b["new"]
        since = _f(job.get("at"))
        mine = [d for d in done if d["who"] == seat and d["at"] >= since
                and (not job.get("new") or d["new"] == job["new"])]
        done_rounds = sum(1 for d in mine if not d["read"])
        done_reads = sum(1 for d in mine if d["read"])
        done_lines = sum(int(d["lines"]) for d in mine if not d["read"])
        open_rounds = int(b["rounds_open"]) if not job.get("finished_at") else 0
        open_reads = int(b["reads_open"]) if not job.get("finished_at") else 0
        lines_want = int(b["lines_want"]) if not job.get("finished_at") else 0
        lines_made = int(b["lines_made"]) if not job.get("finished_at") else 0
        reads_made = int(b["reads_made"]) if not job.get("finished_at") else 0
        job["rounds_total"] = max(int(job.get("rounds_total") or 0), open_rounds + done_rounds)
        job["lines_total"] = max(int(job.get("lines_total") or 0), lines_want + done_lines)
        job["reads_total"] = max(int(job.get("reads_total") or 0), open_reads + done_reads)
        live = bool(open_rounds or open_reads) and not job.get("finished_at")
        if not live and not job.get("finished_at") and (job["rounds_total"] or job["reads_total"]):
            job["finished_at"] = now
            # the seat went back to what the takes held: nothing was swapped
            if job.get("old") and seat_voice(cast, seat) == job["old"] and not mine:
                job["cancelled"] = True
        unmade = (lines_want - lines_made) + (open_reads - reads_made)
        eta = _eta(unmade, _f(b.get("unmade_old_seconds")), speed) if live else 0.0
        new_name = name(str(job.get("new") or ""))
        old_name = name(str(job.get("old") or ""))
        finished_recently = bool(job.get("finished_at")) and now - _f(job.get("finished_at")) <= FINISHED_RECENT_S
        rounds_done = done_rounds
        if live:
            say = ("re-recording %d round%s%s in %s's voice - %d done%s%s"
                   % (job["rounds_total"], "" if job["rounds_total"] == 1 else "s",
                      (" and %d read%s" % (job["reads_total"], "" if job["reads_total"] == 1 else "s")
                       if job["reads_total"] else ""),
                      new_name, rounds_done + done_reads,
                      (", %d under way" % b["rounds_started"]) if b["rounds_started"] else "",
                      (" - %s to go" % _about(eta)) if eta else ""))
        elif job.get("cancelled"):
            say = "%s went back to %s before anything needed re-recording" % (
                SEAT_FACE.get(seat, seat), old_name or "the old voice")
        elif job.get("superseded"):
            say = "superseded by a later change of %s" % SEAT_FACE.get(seat, seat)
        elif job["rounds_total"] or job["reads_total"]:
            say = "%s is on every banked round now - %d round%s%s re-recorded" % (
                new_name, job["rounds_total"], "" if job["rounds_total"] == 1 else "s",
                (" and %d read%s" % (job["reads_total"], "" if job["reads_total"] == 1 else "s")
                 if job["reads_total"] else ""))
        else:
            say = "nothing banked was in %s's old voice" % SEAT_FACE.get(seat, seat)
        rows.append({
            "seat": seat, "face": SEAT_FACE.get(seat, seat),
            "old": str(job.get("old") or ""), "new": str(job.get("new") or ""),
            "old_name": old_name, "new_name": new_name,
            "started_at": since, "finished_at": _f(job.get("finished_at")),
            "live": live, "finished_recently": finished_recently,
            "cancelled": bool(job.get("cancelled")), "superseded": bool(job.get("superseded")),
            "rounds_total": job["rounds_total"], "done": rounds_done,
            "in_flight": int(b["rounds_started"]) if live else 0,
            "lines_total": job["lines_total"], "lines_done": lines_made + done_lines,
            "reads_total": job["reads_total"], "reads_done": reads_made + done_reads,
            "eta_s": eta, "say": say, "_job": job,
        })
    rows.sort(key=lambda r: (0 if r["live"] else 1, -r["started_at"]))
    head = next((r for r in rows if r["live"]), None) or \
        next((r for r in rows if r["finished_recently"]), None) or (rows[0] if rows else None)
    out: dict[str, Any] = {
        "at": now, "live": any(r["live"] for r in rows),
        "finished_recently": any(r["finished_recently"] for r in rows),
        "jobs": [{k: v for k, v in r.items() if k != "_job"} for r in rows],
        "seat": "", "old": "", "new": "", "old_name": "", "new_name": "",
        "rounds_total": 0, "done": 0, "in_flight": 0, "eta_s": 0.0,
        "lines_total": 0, "lines_done": 0, "reads_total": 0, "reads_done": 0,
        "say": "nothing to re-record - every banked line is in the voice its seat holds",
    }
    if head is not None:
        for k in ("seat", "old", "new", "old_name", "new_name", "rounds_total", "done",
                  "in_flight", "eta_s", "lines_total", "lines_done", "reads_total",
                  "reads_done"):
            out[k] = head[k]
        if head["live"] or head["finished_recently"]:
            out["say"] = head["say"]
    return out
