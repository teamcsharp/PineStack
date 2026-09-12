"""2026-09-09: is the crystal actually raising the register, or only rhyming?

The operator: "I need the rhetoric and verbiage style of the rhymes used by
the crystal." That is a claim about WORDS, so it is measurable - and nothing
in the station measured it. The grader proves a bar rhymes, preserves its
facts and borrows crystal vocabulary; none of those say whether the line
sounds like the crystal or like a weather report that happens to rhyme.

Run it against the air log. Every number is computed off the station's own
aired text, so a figure here is what listeners actually heard.

    python tools/lexicon_watch.py [hours] [--since EPOCH]
"""
from __future__ import annotations

import collections
import json
import re
import sys
import time
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
# Spoken furniture. A station saying "the" often is not saying anything dull;
# these are excluded so richness is measured over content words only.
COMMON = set("""a an the and or but so if then than that this these those there here
i me my we us our you your he him his she her it its they them their
is am are was were be been being do does did done have has had having
will would can could shall should may might must
of to in on at by for with from into over under about after before as
not no yes just now what when where who why how which all any some more most
one two three four five six seven eight nine ten
get got go going come came take took make made say said see saw know knew
think thought want like right good bad big little new old thing things way
back down up out off over again still even only very really much many
im ive dont cant wont thats its youre were theyre hes shes lets aint gonna
gotta wanna yeah okay ok oh uh hey well man look listen""".split())
VOWELS = "aeiouy"


def syllables(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and n > 1 and not w.endswith(("le", "ee", "ye")):
        n -= 1
    return max(1, n)


def words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'-]*", str(text or ""))


def bars(text: str) -> list[str]:
    return [b.strip() for b in re.split(r"\s*/\s*", str(text or "")) if b.strip()]


def score(rows: list[str]) -> dict:
    toks, landings, long_words, content = [], [], 0, []
    for text in rows:
        w = words(text)
        toks.extend(x.lower() for x in w)
        for bar in bars(text):
            bw = words(bar)
            if bw:
                landings.append(bw[-1].lower())
    for t in toks:
        if syllables(t) >= 3:
            long_words += 1
        if t not in COMMON:
            content.append(t)
    n = max(1, len(toks))
    land_multi = sum(1 for l in landings if syllables(l) >= 2)
    return {
        "lines": len(rows),
        "words": len(toks),
        "distinct_words": len(set(toks)),
        "type_token": round(len(set(toks)) / n, 3),
        "content_share": round(len(content) / n, 3),
        "distinct_content": len(set(content)),
        "mean_syllables": round(sum(syllables(t) for t in toks) / n, 3),
        "polysyllabic_share": round(long_words / n, 3),
        "bars": len(landings),
        "distinct_landings": len(set(landings)),
        "landing_multisyllabic": round(land_multi / max(1, len(landings)), 3),
        "landing_reuse": round(1 - len(set(landings)) / max(1, len(landings)), 3),
    }


def aired(since: float, kinds: tuple[str, ...] = ()) -> list[str]:
    out = []
    path = DATA / "air_log.jsonl"
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        at = float(row.get("air_at") or row.get("ts") or 0)
        if at < since:
            continue
        if kinds and str(row.get("kind")) not in kinds:
            continue
        text = str(row.get("text") or "").strip()
        if text and str(row.get("kind")) not in ("sfx", "marker", "image_analysis"):
            out.append(text)
    return out


def banked(since: float) -> list[str]:
    """Freshly TINTED bars, off the pantry.

    The air log is a lagging indicator: the bank runs hours deep, so a
    prompt change cannot be heard until the shelf in front of it drains.
    The pantry is where a bar lands the moment it is rapped and recorded,
    which is where a change shows up first.
    """
    out = []
    try:
        data = json.loads((DATA / "pantry.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    rows = data if isinstance(data, list) else list(data.values())
    for row in rows:
        if not isinstance(row, dict):
            continue
        if float(row.get("at") or 0) < since:
            continue
        text = str(row.get("text") or "").strip()
        if text:
            out.append(text)
    return out


def main() -> None:
    hours = 1.0
    since = 0.0
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--since" and i + 1 < len(args):
            since = float(args[i + 1])
        elif not a.startswith("-"):
            try:
                hours = float(a)
            except ValueError:
                pass
    if not since:
        since = time.time() - hours * 3600
    rows = (banked(since) if "--banked" in args else aired(since))
    where = "banked (freshly tinted)" if "--banked" in args else "aired"
    if not rows:
        print("no aired lines in that window (check the station's clock, not yours)")
        return
    print(f"window: {len(rows)} {where} lines since "
          f"{time.strftime('%H:%M:%S', time.localtime(since))}")
    for key, value in score(rows).items():
        print(f"  {key:24} {value}")
    top = collections.Counter(
        w.lower() for text in rows for w in words(text) if w.lower() not in COMMON)
    print("  commonest content words:",
          ", ".join(f"{w}({n})" for w, n in top.most_common(12)))


if __name__ == "__main__":
    main()
