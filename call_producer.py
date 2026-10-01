"""[call-prod] PRODUCED CALLS: a banked call mixed like a produced spot, while paused.

"we have produced phone calls similar to produced ads where during the pause
time of the station we can have actual sound effects and things mixed in with
phone calls to make them more riveting."            - the operator, 2026-10-01
He asked for all four: the phone line's own sounds, the caller's background,
SFX hits on the beats, and a music bed under the win.

A banked call is a list of recorded takes, one per line, each bound to its
System 3 turn - the script ledger, the dice and the flowchart all key on
those. So a produced call keeps its takes and mixes the production INTO
them, each into a NEW file under a NEW pantry key (the shared voice cache,
keyed on words and voice, is never written over):

  the first take      the line rings and is picked up before the host speaks
  the caller's takes  line hiss and the caller's own background under them
  the manager's take  the intercom chime before he cuts in
  the arc's peak      a tension hit after the line it boils over on
  the reaction        a win: a bed under it and a fanfare after; a loss: a hit
  the last take       the hang-up, by how the call ended: a click and the
                      dial tone, a slam, or the busy tone of a dead line

plan_production() is pure and decides NOTHING: it offers dice doors (each
sound's odds, the outcome only leaning the weights); the station rolls them
through System 3 and resolve_plan() turns the rolls into per-take ops;
mix_take() is ffmpeg. The phone's own sounds are SYNTHESISED here, so they
never depend on what is in the sample library; the hits, the ambience and
the bed are found by the station (its SFX library and its music) and handed
in as paths.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

SR = 24000
PEAK_BEATS = ("arc_boils", "arc_digs", "arc_corners", "arc_settles", "arc_holds", "arc_demands")
CALLER_SEATS = ("C", "E")
HIT_SECONDS = 4.0
AMBIENCE_GAIN = 0.14
HISS_GAIN = 0.010
BED_GAIN = 0.22
HIT_GAIN = 0.55

# the phone's own sounds, as ffmpeg lavfi sources (24 kHz mono)
_SYNTH = {
    # a North American ring (440 + 480 Hz), two short bursts, then the pickup click
    "ring": ("aevalsrc='0.25*(sin(2*PI*440*t)+sin(2*PI*480*t))*lt(mod(t,1.6),0.9)':s=%d:d=2.6" % SR),
    "pickup": ("anoisesrc=d=0.06:c=white:a=0.5:r=%d,afade=t=out:st=0.01:d=0.05" % SR),
    # the intercom chime: two tones
    "intercom": ("aevalsrc='0.3*sin(2*PI*880*t)*lt(t,0.18)+0.3*sin(2*PI*660*t)*gte(t,0.2)*lt(t,0.42)':s=%d:d=0.5" % SR),
    # a click, then the dial tone (350 + 440 Hz)
    "hangup_click": ("aevalsrc='0.6*lt(t,0.03)*sin(2*PI*2000*t)+0.18*(sin(2*PI*350*t)+sin(2*PI*440*t))*gte(t,0.35)':"
                     "s=%d:d=1.6" % SR),
    # a slam: a thud of low noise, then the dial tone
    "hangup_slam": ("aevalsrc='0.9*exp(-18*t)*sin(2*PI*90*t)+0.18*(sin(2*PI*350*t)+sin(2*PI*440*t))*gte(t,0.5)':"
                    "s=%d:d=1.8" % SR),
    # a dead line: the busy tone (480 + 620 Hz, half a second on, half off)
    "busy": ("aevalsrc='0.18*(sin(2*PI*480*t)+sin(2*PI*620*t))*lt(mod(t,1.0),0.5)':s=%d:d=2.0" % SR),
}


def _seat_of(seats: list[str], i: int) -> str:
    return str(seats[i]) if 0 <= i < len(seats) else ""


def plan_production(legs: Iterable[Any], seats: Iterable[Any], callend: dict[str, Any] | None,
                    manager_seat: str = "E") -> list[dict[str, Any]]:
    """The produced call as DICE DOORS - nothing here is decided, only offered.

    "the point of system 3 is to unify everything under a procedural node based
    system. So i want no wedging. I need it all happening by chance."
                                                        - the operator, 2026-10-01
    Each door is a roll the station makes through System 3 (s3_chance /
    s3_weighted), so every sound in a produced call is a recorded draw: a
    `chance` door ({key, odds}) puts its asset in or leaves it out; a `choice`
    door ({key, options, weights}) picks one - the call's own outcome LEANS the
    weights (a win leans the fanfare, a refusal the slam) but never decides.
    Every door names the take(s) it acts on (`at`), the slot (pre/post/under)
    and why. resolve_plan() turns the rolled doors into per-take ops."""
    legs = [str(x or "") for x in legs or []]
    seats = [str(x or "") for x in seats or []]
    ce = callend if isinstance(callend, dict) else {}
    res = ce.get("resolve") if isinstance(ce.get("resolve"), dict) else {}
    tags = {str(t) for t in res.get("tags") or []}
    wrap = ce.get("wrap") if isinstance(ce.get("wrap"), dict) else {}
    n = len(legs)
    if n == 0:
        return []
    doors: list[dict[str, Any]] = []
    callers = [i for i, seat in enumerate(seats[:n])
               if seat in CALLER_SEATS and legs[i] != "manager_cuts_in"]
    doors.append({"kind": "chance", "key": "call.produced.ring", "odds": 0.9, "at": [0], "slot": "pre",
                  "assets": ["ring", "pickup"], "label": "the line rings and is picked up before the host speaks"})
    if callers:
        doors.append({"kind": "chance", "key": "call.produced.hiss", "odds": 0.85, "at": callers, "slot": "under",
                      "assets": ["hiss"], "label": "the caller's line hisses"})
        doors.append({"kind": "chance", "key": "call.produced.background", "odds": 0.7, "at": callers,
                      "slot": "under", "assets": ["ambience"], "label": "the caller has a room behind them"})
    if "manager_cuts_in" in legs:
        doors.append({"kind": "chance", "key": "call.produced.intercom", "odds": 0.9,
                      "at": [legs.index("manager_cuts_in")], "slot": "pre", "assets": ["intercom"],
                      "label": "the intercom chimes before the manager cuts in"})
    peaks = [i for i, leg in enumerate(legs) if leg in PEAK_BEATS]
    if peaks:
        doors.append({"kind": "chance", "key": "call.produced.peak_hit", "odds": 0.6, "at": [peaks[0]],
                      "slot": "post", "assets": ["hit:tension"], "label": "a hit where the arc peaks"})
    if "reaction" in legs:
        won = bool(tags & {"won", "sale", "prize", "painting", "honour", "granted"})
        lost = bool(tags & {"refused", "short", "fire", "disagree"})
        doors.append({"kind": "choice", "key": "call.produced.reaction", "at": [legs.index("reaction")],
                      "label": "what sounds under and after the caller's reaction",
                      "options": ["a bed and a fanfare", "a losing hit", "nothing"],
                      "weights": [4.0 if won else 0.6, 3.0 if lost else 0.6, 1.0],
                      "ops": [{"under": ["bed:win"], "post": ["hit:win"]}, {"post": ["hit:lose"]}, {}]})
    dead = bool(wrap.get("dead_line") or ce.get("ended"))
    angry = bool(tags & {"refused", "fire"}) or wrap.get("polite") is False
    doors.append({"kind": "choice", "key": "call.produced.hangup", "at": [n - 1],
                  "label": "how the phone goes down",
                  "options": ["a click and the dial tone", "a slam", "the busy tone"],
                  "weights": [0.3 if dead else (1.0 if angry else 4.0), 0.3 if dead else (4.0 if angry else 1.0),
                              6.0 if dead else 0.3],
                  "ops": [{"post": ["hangup_click"]}, {"post": ["hangup_slam"]}, {"post": ["busy"]}]})
    return doors


def resolve_plan(doors: Iterable[dict[str, Any]], chance: Any, weighted: Any) -> tuple[dict[int, dict[str, Any]],
                                                                                    list[dict[str, Any]]]:
    """Roll every door - `chance(key, odds, label) -> bool`, `weighted(key, options,
    weights, label) -> index` (the station passes System 3's s3_chance and
    s3_weighted) - into {take index: {pre, post, under, why}} and the record of
    what each door rolled."""
    plan: dict[int, dict[str, Any]] = {}
    rolled: list[dict[str, Any]] = []

    def at(i: int) -> dict[str, Any]:
        return plan.setdefault(int(i), {"pre": [], "post": [], "under": [], "why": []})

    for d in doors or []:
        if d.get("kind") == "chance":
            hit = bool(chance(d["key"], float(d.get("odds") or 0), d.get("label") or d["key"]))
            rolled.append({"key": d["key"], "odds": d.get("odds"), "hit": hit, "label": d.get("label")})
            if hit:
                for i in d.get("at") or []:
                    at(i)[d.get("slot") or "post"] += list(d.get("assets") or [])
                    at(i)["why"].append(str(d.get("label") or d["key"]))
        elif d.get("kind") == "choice":
            k = int(weighted(d["key"], list(d.get("options") or []), list(d.get("weights") or []),
                             d.get("label") or d["key"]))
            k = k if 0 <= k < len(d.get("options") or []) else 0
            rolled.append({"key": d["key"], "picked": (d.get("options") or [""])[k], "label": d.get("label"),
                           "weights": d.get("weights")})
            ops = (d.get("ops") or [{}])[k] if k < len(d.get("ops") or []) else {}
            for i in d.get("at") or []:
                for slot in ("pre", "post", "under"):
                    at(i)[slot] += list(ops.get(slot) or [])
                if ops:
                    at(i)["why"].append("%s: %s" % (d.get("label") or d["key"], (d.get("options") or [""])[k]))
    return {i: ops for i, ops in plan.items() if ops["pre"] or ops["post"] or ops["under"]}, rolled


def production_key(key: str, ops: dict[str, Any], assets: dict[str, str]) -> str:
    """A new pantry key for the produced take: the old key plus what was mixed in."""
    blob = "%s|%s|%s|%s|%s" % (key, ",".join(ops.get("pre") or []), ",".join(ops.get("post") or []),
                               ",".join(ops.get("under") or []),
                               ",".join("%s=%s" % (k, assets.get(k, "")) for k in sorted(assets)))
    return "prod-" + hashlib.sha1(blob.encode("utf-8")).hexdigest()[:20]


def ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _run(args: list[str], timeout: float = 60.0) -> bool:
    try:
        got = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout)
        return got.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def synth(name: str, out: Path) -> bool:
    """One of the phone's own sounds into `out` (wav)."""
    src = _SYNTH.get(name)
    if not src:
        return False
    return _run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", src,
                 "-ac", "1", "-ar", str(SR), str(out)])


def mix_take(src: Path, out: Path, ops: dict[str, Any], assets: dict[str, str]) -> bool:
    """Mix one take: `pre` sounds before it, `under` beds beneath it (looped and
    faded to its length), `post` sounds after it - into `out` (mp3, 24 kHz mono).

    `assets` maps symbolic names (ambience, bed:win, hit:*) to files; the phone's
    own sounds are synthesised. A missing asset is skipped, never fatal; the take
    itself is never altered. False if ffmpeg fails, so the call airs dry."""
    pre = [a for a in ops.get("pre") or [] if a in _SYNTH or assets.get(a)]
    post = [a for a in ops.get("post") or [] if a in _SYNTH or assets.get(a)]
    under = [a for a in ops.get("under") or [] if a == "hiss" or assets.get(a)]
    if not (pre or post or under):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        inputs: list[str] = ["-i", str(src)]
        files: dict[str, int] = {}
        k = 1
        for a in pre + post:
            if a in files:
                continue
            if a in _SYNTH:
                f = t / ("%s.wav" % a)
                if not synth(a, f):
                    continue
                inputs += ["-i", str(f)]
            else:
                inputs += ["-i", assets[a]]
            files[a] = k
            k += 1
        under_ix: list[tuple[str, int]] = []
        for a in under:
            if a == "hiss":
                inputs += ["-f", "lavfi", "-i", "anoisesrc=c=pink:a=1:r=%d" % SR]
            else:
                inputs += ["-stream_loop", "-1", "-i", assets[a]]
            under_ix.append((a, k))
            k += 1
        # every piece has its timestamps reset, or concat keeps only the voice's span
        chains: list[str] = ["[0:a]aformat=sample_rates=%d:channel_layouts=mono,asetpts=N/SR/TB[v]" % SR]
        mixed = "v"
        if under_ix:
            labels = ["[v]"]
            for a, ix in under_ix:
                gain = HISS_GAIN if a == "hiss" else (BED_GAIN if a.startswith("bed") else AMBIENCE_GAIN)
                chains.append("[%d:a]aformat=sample_rates=%d:channel_layouts=mono,volume=%s[u%d]"
                              % (ix, SR, gain, ix))
                labels.append("[u%d]" % ix)
            chains.append("%samix=inputs=%d:duration=first:dropout_transition=0:normalize=0,asetpts=N/SR/TB[vm]"
                          % ("".join(labels), len(labels)))
            mixed = "vm"
        seq = []
        for a in pre:
            if a in files:
                chains.append("[%d:a]aformat=sample_rates=%d:channel_layouts=mono%s,asetpts=N/SR/TB[p%d]"
                              % (files[a], SR, ",volume=%s" % HIT_GAIN if a.startswith("hit") else "", files[a]))
                seq.append("[p%d]" % files[a])
        seq.append("[%s]" % mixed)
        for a in post:
            if a in files:
                trim = ",atrim=0:%s,afade=t=out:st=%s:d=0.6" % (HIT_SECONDS, HIT_SECONDS - 0.6) \
                    if a.startswith("hit") else ""
                chains.append("[%d:a]aformat=sample_rates=%d:channel_layouts=mono%s%s,asetpts=N/SR/TB[q%d]"
                              % (files[a], SR, ",volume=%s" % HIT_GAIN if a.startswith("hit") else "", trim, files[a]))
                seq.append("[q%d]" % files[a])
        chains.append("%sconcat=n=%d:v=0:a=1[out]" % ("".join(seq), len(seq)))
        args = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"] + inputs + [
            "-filter_complex", ";".join(chains), "-map", "[out]", "-ac", "1", "-ar", str(SR),
            "-c:a", "libmp3lame", "-b:a", "64k", str(out)]
        return _run(args, timeout=90.0) and out.is_file() and out.stat().st_size > 0


def seconds_of(path: Path) -> float:
    try:
        got = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries",
                              "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                             capture_output=True, text=True, timeout=20)
        return round(float(got.stdout.strip() or 0), 2)
    except Exception:  # noqa: BLE001
        return 0.0
