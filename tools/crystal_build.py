#!/usr/bin/env python3
"""Distil SongSight projects into data crystals the Pine Box agent can read.

A .songsight project is a few megabytes of per-frame analysis. A crystal is
the ~2 KB of it worth speaking aloud: tempo, key, the chord chart, what's
playing, how long it is. One JSON per song, same deployment shape as the
gear-manual corpus in data/te.

    python3 tools/crystal_build.py ~/Music/SongSight --out /tmp/crystals
    rsync -a /tmp/crystals/ ehm_eckx@lilspark.local:\\
        pinevoice-stack/spark-agent/data/crystals/

Runs on the machine that has SongSight; nothing here imports SongSight.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Relative-minor pairs, so a chord set that sits in C major can be reported as
# A minor when the tonic chord says so.
MAJOR_KEYS = {
    "C": "Am", "G": "Em", "D": "Bm", "A": "F#m", "E": "C#m", "B": "G#m",
    "F#": "D#m", "F": "Dm", "A#": "Gm", "D#": "Cm", "G#": "Fm", "C#": "A#m",
}


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def note_name(midi: int) -> str:
    return f"{NOTE_NAMES[int(midi) % 12]}{int(midi) // 12 - 1}"


def title_of(slug: str) -> str:
    """Turn a filename into something speakable."""
    name = re.sub(r"[_]+", " ", slug)
    name = re.sub(r"\s*[-–—]\s*(Official\s+)?(Music\s+)?"
                  r"(Video|Lyric Video|Audio|Visualizer)\s*$", "", name,
                  flags=re.I)
    return re.sub(r"\s{2,}", " ", name).strip()


def estimate_key(chords: list[dict[str, Any]]) -> tuple[str, float]:
    """Weight each chord root by how long it sounds, then let the longest-held
    chord decide major or minor.
    ponytail: chord-duration voting, not Krumhansl-Schmuckler. It agrees with
    the ear on tonal material; swap in a pitch-class profile if it drifts."""
    if not chords:
        return "", 0.0

    held: Counter[str] = Counter()
    for chord in chords:
        root = str(chord.get("root") or "")
        if not root:
            continue
        span = float(chord.get("end", 0)) - float(chord.get("start", 0))
        held[root] += max(0.0, span)

    if not held:
        return "", 0.0

    total = sum(held.values()) or 1.0
    root, weight = held.most_common(1)[0]

    minor = sum(
        float(c.get("end", 0)) - float(c.get("start", 0))
        for c in chords
        if str(c.get("root")) == root and "m" in str(c.get("quality") or "")
        and "maj" not in str(c.get("quality") or "")
    )
    major = sum(
        float(c.get("end", 0)) - float(c.get("start", 0))
        for c in chords
        if str(c.get("root")) == root
    ) - minor

    quality = "minor" if minor > major else "major"
    return f"{root} {quality}", round(weight / total, 2)


def progression(chords: list[dict[str, Any]], bars: int = 16) -> str:
    """The chart as you'd write it down: consecutive repeats collapsed."""
    names: list[str] = []
    for chord in chords:
        name = str(chord.get("chord") or "").strip()
        if name and (not names or names[-1] != name):
            names.append(name)
    return " → ".join(names[:bars]) + (" → …" if len(names) > bars else "")


def crystallize(project: Path) -> dict[str, Any] | None:
    meta = load(project / "project.json")
    if not meta:
        return None

    analysis = project / "analysis"
    structure = load(analysis / "structure.json") or {}
    chords = load(analysis / "chords.json") or []
    instruments = load(analysis / "instruments.json") or {}
    drums = load(analysis / "drums.json") or []
    notes = load(analysis / "notes.json") or []
    lyrics = load(analysis / "lyrics.json") or {}

    slug = re.sub(r"[^a-z0-9]+", "-", str(meta.get("name") or project.stem).lower()).strip("-")
    key, key_confidence = estimate_key(chords if isinstance(chords, list) else [])

    hits: Counter[str] = Counter()
    for hit in drums if isinstance(drums, list) else []:
        label = str((hit or {}).get("instrument_class") or "")
        if label:
            hits[label] += 1

    # notes.json is keyed by role — bass, melody, vocals, drone — each a list.
    pitches: list[int] = []
    per_role: dict[str, int] = {}
    for role, played in (notes if isinstance(notes, dict) else {}).items():
        if not isinstance(played, list) or not played:
            continue
        per_role[role] = len(played)
        pitches += [
            int(n["pitch"]) for n in played
            if isinstance(n, dict) and isinstance(n.get("pitch"), (int, float))
        ]

    lines: list[str] = []
    if isinstance(lyrics, dict):
        for segment in (lyrics.get("segments") or lyrics.get("lines") or [])[:40]:
            text = str((segment or {}).get("text") or "").strip()
            if text:
                lines.append(text)

    stems = sorted(p.stem for p in (project / "stems").glob("*.wav")) \
        if (project / "stems").is_dir() else []

    duration = float(structure.get("duration_seconds") or 0.0)
    return {
        "slug": slug,
        "title": title_of(str(meta.get("name") or project.stem)),
        "aliases": sorted({str(meta.get("name") or ""), project.stem,
                           title_of(project.stem)} - {""}),
        "source": str((meta.get("source") or {}).get("file") or ""),
        "duration_seconds": round(duration, 1),
        "duration_text": f"{int(duration // 60)}:{int(duration % 60):02d}",
        "bpm": round(float(structure.get("bpm") or 0.0), 2),
        "meter": str(structure.get("meter_assumed") or ""),
        "bars": len(structure.get("downbeat_times") or []),
        "key": key,
        "key_confidence": key_confidence,
        "chords": progression(chords if isinstance(chords, list) else []),
        "chord_count": len(chords) if isinstance(chords, list) else 0,
        "instruments": {
            role: str((info or {}).get("family") or "")
            for role, info in (instruments or {}).items()
            if isinstance(info, dict)
        },
        "stems": stems,
        "drums": dict(hits.most_common(8)),
        "notes": {
            "count": len(pitches),
            "lowest": note_name(min(pitches)) if pitches else "",
            "highest": note_name(max(pitches)) if pitches else "",
            "per_role": per_role,
        },
        "lyrics": lines,
        "separation_model": str((meta.get("models") or {}).get("separation") or ""),
        "built": time.strftime("%Y-%m-%d"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path,
                        help="folder containing .songsight projects")
    parser.add_argument("--out", type=Path, required=True,
                        help="where the crystal JSONs are written")
    args = parser.parse_args()

    projects = sorted(args.root.rglob("*.songsight"))
    if not projects:
        print(f"no .songsight projects under {args.root}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    built = 0
    for project in projects:
        if not project.is_dir():
            continue
        crystal = crystallize(project)
        if not crystal or not crystal["slug"]:
            print(f"  skip {project.name} (no project.json)", file=sys.stderr)
            continue
        (args.out / f"{crystal['slug']}.json").write_text(
            json.dumps(crystal, indent=1) + "\n"
        )
        built += 1
        print(f"  {crystal['slug']:<44} {crystal['bpm']:>7} bpm  "
              f"{crystal['key'] or '—':<10} {crystal['duration_text']}")

    print(f"\n{built} crystals → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
