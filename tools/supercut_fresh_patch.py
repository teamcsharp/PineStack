#!/usr/bin/env python3
"""[supercut-fresh] Supercut footage rests 48 hours; never-played, freshly studied clips come first. 2026-10-06.

"When making supercuts I want the SFX guy using different clips each time so he
is forced to push the boundaries... I want footage to have a 48 hour cooldown
time in which he is prompted to study, analyze and plan using content that is
being actively explored that has never gotten play. I am seeing supercuts using
the same footage and I dont want that. I need him pushing further and farther
into the 300k clips available to make supercut ads."

Before: scan_catalog scored every playable short clip the same way every hour,
so the same high-scoring rows won the same roles cut after cut; the archive
(data/sfx_ads/supercuts/archive.sqlite3) and the saved plans (data/sfx_supercuts/
sc-*.json) both record exactly which sids each cut used, and nothing read them
back. The clip book records when the SFX Guy studied a clip (said_at,
seen_desc_at) and the endless set records every clip it has put on the air
(_SFX_VIDEO_PLAYED, the durable deck); neither reached the picker.

Now, in sfx_supercut.py:
  - COOLDOWN_HOURS (48, env PINE_SUPERCUT_COOLDOWN_HOURS): SupercutRuntime.cooled()
    is every sid any supercut used inside the window (archive cues + saved plans),
    cached a minute; _plan passes it to scan_catalog as `exclude`. A verified
    station identity is never rested - every cut needs its tag.
  - scan_catalog(played=...): a clip the set has played scores x0.6; a clip the
    SFX Guy studied inside FRESH_DAYS (7) scores x1.3 - never-played, freshly
    explored footage wins ties and most contests. Coverage reports rested_sources,
    explored_recently, played_known; each pick's `why` carries fresh_gain.
  - Never nothing: if compose() cannot make the cut without the resting footage,
    one relaxed scan (no cooldown, the gains still on) makes it, and the plan's
    `freshness.relaxed` says so.
  - runtime.fresh_note(): the rule in one sentence with live counts; registered
    as host["supercut_fresh_note"] and appended to the campaign writer's system
    prompt (supercut_campaigns.py), so the brief the SFX Guy plans against names
    the rule and the numbers.

Usage:  supercut_fresh_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        supercut_fresh_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

IMPORT_OLD = '''import math
import re
import sqlite3
'''
IMPORT_NEW = '''import math
import os
import re
import sqlite3
'''

SIG_OLD = '''def scan_catalog(book_path: Any, store: Any, cfg: Mapping[str, Any], *, prompt: str = "",
                 vectors: Mapping[str, list[float]] | None = None, banned: set[str] | None = None,
                 weights: Mapping[str, float] | None = None, mp4_only: bool = False,
                 exclude: set[str] | None = None, extra_sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
'''
SIG_NEW = '''COOLDOWN_HOURS = float(os.getenv("PINE_SUPERCUT_COOLDOWN_HOURS", "48"))   # [supercut-fresh] footage rests after a cut
FRESH_DAYS = float(os.getenv("PINE_SUPERCUT_FRESH_DAYS", "7"))            # [supercut-fresh] "actively explored" = studied this week
PLAYED_GAIN = 0.6                                                          # [supercut-fresh] a clip that has had play scores at this
FRESH_GAIN = 1.3                                                           # [supercut-fresh] a freshly studied clip scores at this


def scan_catalog(book_path: Any, store: Any, cfg: Mapping[str, Any], *, prompt: str = "",
                 vectors: Mapping[str, list[float]] | None = None, banned: set[str] | None = None,
                 weights: Mapping[str, float] | None = None, mp4_only: bool = False,
                 exclude: set[str] | None = None, extra_sources: list[dict[str, Any]] | None = None,
                 played: set[str] | None = None, fresh_days: float | None = None) -> dict[str, Any]:
'''

INIT_OLD = '''    scanned = eligible = 0
    digest = hashlib.sha256()
'''
INIT_NEW = '''    scanned = eligible = 0
    rested = explored = 0                                                  # [supercut-fresh]
    played_set = set(played or ())
    fresh_since = time.time() - (FRESH_DAYS if fresh_days is None else float(fresh_days)) * 86400.0
    digest = hashlib.sha256()
'''

COLS_OLD = '''        wanted = [c for c in ("sid", "path", "name", "folder", "video", "seconds", "mtime", "said", "said_at", "seen_desc") if c in columns]
'''
COLS_NEW = '''        wanted = [c for c in ("sid", "path", "name", "folder", "video", "seconds", "mtime", "said", "said_at", "seen_desc", "seen_desc_at") if c in columns]
'''

EXCL_OLD = '''            length = _number(d.get("seconds"))
            weight = max(0, min(9, _number(controls.get(sid, 1), 1)))
            if sid in blocked or sid in excluded or weight <= 0.05 or length < 0.45 or length > 6.0:
                continue
'''
EXCL_NEW = '''            length = _number(d.get("seconds"))
            weight = max(0, min(9, _number(controls.get(sid, 1), 1)))
            if sid in blocked or weight <= 0.05 or length < 0.45 or length > 6.0:
                continue
            # [supercut-fresh] footage a supercut used inside the cooldown rests - except a verified station
            # identity, which every cut needs for its tag. A resting row is counted, not scored.
            if sid in excluded and not _identity(_text(d.get("said"), 2000), str(cfg["station"])) \\
                    and not _identity(str(d.get("name") or ""), str(cfg["station"])):
                rested += 1
                continue
'''

GAIN_OLD = '''            similarities = semantic.get(sid) or {}
            for role in ROLES:
'''
GAIN_NEW = '''            similarities = semantic.get(sid) or {}
            # [supercut-fresh] never-played footage first, and what the SFX Guy studied this week before the rest
            fresh_gain = PLAYED_GAIN if sid in played_set else 1.0
            if max(_number(d.get("said_at")), _number(d.get("seen_desc_at"))) > fresh_since:
                fresh_gain *= FRESH_GAIN
                explored += 1
            for role in ROLES:
'''

SCORE_OLD = '''                score = (lexical + cosine * (0.7 if said else 0.25) + timely +
                         (0.15 if said else 0) + (0.1 if 0.8 <= length <= 2.8 else 0)) * math.sqrt(weight)
'''
SCORE_NEW = '''                score = (lexical + cosine * (0.7 if said else 0.25) + timely +
                         (0.15 if said else 0) + (0.1 if 0.8 <= length <= 2.8 else 0)) * math.sqrt(weight) * fresh_gain
'''

WHY_OLD = '''                                   "operator_weight": weight})
'''
WHY_NEW = '''                                   "operator_weight": weight, "fresh_gain": round(fresh_gain, 3)})
'''

COVER_OLD = '''catalog_scanned=scanned, recorded_station_sources=len(extra_sources or ()),'''
COVER_NEW = '''catalog_scanned=scanned, rested_sources=rested, explored_recently=explored, played_known=len(played_set), recorded_station_sources=len(extra_sources or ()),'''

RUNTIME_OLD = '''    def remember(self, key, plan):
        self.memo[key] = plan['id']
'''
RUNTIME_NEW = '''    _cooled_cache: tuple[float, set[str]] = (0.0, set())

    def cooled(self, hours: float | None = None) -> set[str]:
        """[supercut-fresh] Every source sid a supercut used inside the cooldown: the archive's
        cues and the saved plans' clips (rendered or only composed). Cached a minute."""
        hours = COOLDOWN_HOURS if hours is None else float(hours)
        now = time.time()
        at, cached = self._cooled_cache
        if hours == COOLDOWN_HOURS and now - at < 60.0:
            return set(cached)
        since = now - hours * 3600.0
        out: set[str] = set()
        try:
            with self.archive.connection() as con:
                for row in con.execute("select metadata from archive where created_at >= ?", (since,)):
                    try:
                        meta = json.loads(row["metadata"])
                    except ValueError:
                        continue
                    cues = list(meta.get("cues") or []) + list((meta.get("source_plan") or {}).get("clips") or [])
                    for cue in cues:
                        if isinstance(cue, dict) and cue.get("sid"):
                            out.add(str(cue["sid"]))
        except Exception:  # noqa: BLE001
            pass
        for path in self.root.glob("sc-*.json"):
            try:
                stamp = path.stat().st_mtime
                if stamp < since:
                    continue
                plan = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if _number(plan.get("rendered_at"), stamp) < since:
                continue
            for clip in plan.get("clips") or []:
                if isinstance(clip, dict) and clip.get("sid"):
                    out.add(str(clip["sid"]))
        if hours == COOLDOWN_HOURS:
            self._cooled_cache = (now, set(out))
        return out

    def played_sids(self) -> set[str]:
        """[supercut-fresh] Every clip the endless set has put on the air (its durable deck)."""
        try:
            loader = self.host.get("_sfx_video_played_load")
            if callable(loader):
                loader()
            return set(str(k) for k in (self.host.get("_SFX_VIDEO_PLAYED") or {}).keys())
        except Exception:  # noqa: BLE001
            return set()

    def fresh_note(self) -> str:
        """[supercut-fresh] The footage rule in one sentence, with live counts, for the writer's brief."""
        try:
            resting = len(self.cooled())
        except Exception:  # noqa: BLE001
            resting = 0
        return ("Footage rule: every clip a supercut used rests %d hours (%d clip(s) resting now); build this one "
                "from clips that have never had play on the station (%d have), and prefer the ones the SFX Guy "
                "studied this week - push further into the unexplored library rather than returning to the "
                "same footage." % (int(COOLDOWN_HOURS), resting, len(self.played_sids())))

    def remember(self, key, plan):
        self.memo[key] = plan['id']
'''

KEY_OLD = '''        scan_key = hashlib.sha256(json.dumps([cfg, prompt, sorted(bans), weights, only], sort_keys=True).encode()).hexdigest()
'''
KEY_NEW = '''        cooled = set() if cfg.get('custom') else await asyncio.to_thread(self.cooled)        # [supercut-fresh]
        played = set() if cfg.get('custom') else await asyncio.to_thread(self.played_sids)   # [supercut-fresh]
        scan_key = hashlib.sha256(json.dumps([cfg, prompt, sorted(bans), weights, only, sorted(cooled), len(played)], sort_keys=True).encode()).hexdigest()
'''

CALL_OLD = '''mp4_only=only, extra_sources=extra_sources))'''
CALL_NEW = '''mp4_only=only, extra_sources=extra_sources, exclude=cooled, played=played))'''

COMPOSE_OLD = '''        result = compose(scan, cfg, occurrence, roulette=roulette if callable(roll) else None)
        if result.get("ok"):
'''
COMPOSE_NEW = '''        result = compose(scan, cfg, occurrence, roulette=roulette if callable(roll) else None)
        freshness = {"cooldown_hours": COOLDOWN_HOURS, "resting": len(cooled), "played_known": len(played),
                     "rested_sources": int((scan.get("coverage") or {}).get("rested_sources") or 0),
                     "explored_recently": int((scan.get("coverage") or {}).get("explored_recently") or 0),
                     "relaxed": False}
        if not result.get("ok") and cooled:
            # [supercut-fresh] never nothing: a cut that only the resting footage can make is made from it, and says so
            relaxed = await self.bounded_catalog('relaxed-scan:'+scan_key, lambda store:scan_catalog(self.host["SFX_DB_PATH"], store, cfg, prompt=prompt,
                                                     vectors=vectors, banned=bans, weights=weights, mp4_only=only, extra_sources=extra_sources, played=played))
            again = compose(relaxed, cfg, occurrence, roulette=roulette if callable(roll) else None)
            if again.get("ok"):
                result, scan = again, relaxed
                freshness["relaxed"] = True
        result["freshness"] = freshness
        if result.get("ok"):
'''

INSTALL_OLD = '''    host["_sfx_supercut_runtime"] = runtime
'''
INSTALL_NEW = '''    host["_sfx_supercut_runtime"] = runtime
    host["supercut_fresh_note"] = runtime.fresh_note             # [supercut-fresh] the rule, for the writer's brief
'''

WRITER_OLD = '''            return await host["ask_model"](generation, limit=2000, spice=.35, system_prompt=system,
'''
WRITER_NEW = '''            note = host.get("supercut_fresh_note")                 # [supercut-fresh] the footage rule rides the brief
            if callable(note):
                try:
                    system = str(system) + "\\n\\n" + str(note())
                except Exception:  # noqa: BLE001
                    pass
            return await host["ask_model"](generation, limit=2000, spice=.35, system_prompt=system,
'''

EDITS = {
    "sfx_supercut.py": [
        ("import os", IMPORT_OLD, IMPORT_NEW, 1),
        ("the cooldown constants and the two scan parameters", SIG_OLD, SIG_NEW, 1),
        ("rested / explored counters, the played set, the fresh window", INIT_OLD, INIT_NEW, 1),
        ("seen_desc_at joins the scan", COLS_OLD, COLS_NEW, 1),
        ("resting footage is counted, not scored; identities never rest", EXCL_OLD, EXCL_NEW, 1),
        ("fresh_gain per row", GAIN_OLD, GAIN_NEW, 1),
        ("the gain in the score", SCORE_OLD, SCORE_NEW, 1),
        ("the gain in each pick's why", WHY_OLD, WHY_NEW, 1),
        ("coverage reports rested / explored / played", COVER_OLD, COVER_NEW, 1),
        ("cooled(), played_sids(), fresh_note()", RUNTIME_OLD, RUNTIME_NEW, 1),
        ("_plan reads the cooldown and the deck", KEY_OLD, KEY_NEW, 1),
        ("both scans take the cooldown and the deck", CALL_OLD, CALL_NEW, 2),
        ("never nothing: one relaxed scan, said so", COMPOSE_OLD, COMPOSE_NEW, 1),
        ("the note is on the host", INSTALL_OLD, INSTALL_NEW, 1),
    ],
    "supercut_campaigns.py": [
        ("the writer's brief carries the footage rule", WRITER_OLD, WRITER_NEW, 1),
    ],
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s MISSING FILE" % name)
            missing = True
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, want in edits:
            if text.count(new) >= want:
                print("%-72s applied" % label[:72])
                continue
            n = text.count(old)
            if n == want:
                print("%-72s ready" % label[:72])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-72s MISSING (anchor count %d, wanted %d)" % (label[:72], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    if missing:
        print("anchors missing - nothing applied")
        return 1
    if not ready:
        print("every edit reads applied")
        return 2
    if argv[1] == "--check":
        print("ready to apply")
        return 0
    for path, text, mode, bom in plans:
        out = text.replace("\n", "\r\n") if mode == "crlf" else text
        data = out.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        tmp = path.with_suffix(path.suffix + ".scfresh.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
