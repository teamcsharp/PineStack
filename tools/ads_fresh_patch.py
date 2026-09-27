"""[ads-fresh] No ad ever generates from a video another ad already used.

"make sure that for the hourly H3 stingers, that it never uses the same video
 twice for the ad" ([h3-fresh]) ... then: "due to me not wanting ads to use
 the same video for generation ever"

[h3-fresh] guarded only the hourly road. Every other ad the station picks a
video for - a listener's "Make ad", a voice ad, a deferred ad bound at
dispatch - went through voice_ad_person_clip(): a random pick among the eight
clips that rank best against the ad's words, with no memory, so a clip could
come back. Now:

  - voice_ad_person_clip() never returns a clip in the ledger
    (data/h3_hourly_used.json): the ranking keeps its relevance but loses every
    used clip; with nothing fresh left in it, a fresh clip is drawn at random
    from the whole book (h3_hourly_fresh_clip); the transcript and short-video
    fallbacks skip used clips too;
  - every H3 render records the source it actually used - hand-picked ones
    from the Workshop and the gallery included - so no automatic pick ever
    lands on it afterwards. A hand-picked render of a used clip is the
    operator's own choice and is not refused.

--check exits 0 ready / 2 applied / 1 missing; --apply writes LF atomically.
ON THE HOST, from a fresh copy.
"""
import os
import sys
import tempfile
from pathlib import Path

TAKE = '''def h3_ad_source_used(key: str) -> None:
    """[ads-fresh] Write a source an ad has used into the ledger (no-op when it
    is there already), so no automatic ad pick lands on it again."""
    if not key:
        return
    with _H3_FRESH_LOCK:
        used = h3_hourly_used()
        if key in used:
            return
        used[key] = time.time()
        try:
            tmp = _H3_FRESH_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(used), encoding="utf-8")
            tmp.replace(_H3_FRESH_FILE)
        except Exception as exc:  # noqa: BLE001
            pipeline_log("ads", "the used-sources ledger could not be written (%s)" % type(exc).__name__)


'''

RANKED_OLD = '''    if picked:
        # Do not always pick rank one: several close semantic matches should
        # still make separately requested ads feel like separate productions.
        path, seconds, candidate = random.choice(picked[:min(8, len(picked))])
        return {"id": sfx_id(path), "name": path.stem[:120],
                "seconds": round(seconds, 2), "video": True,
                "match": str(getattr(candidate, "folder", "indexed clip"))[:120]}
'''
RANKED_NEW = '''    # [ads-fresh] "me not wanting ads to use the same video for generation
    # ever": the ranking keeps its relevance but never offers a used clip; with
    # nothing fresh left in it, a fresh clip drawn at random from the whole book
    used = h3_hourly_used()
    picked = [p for p in picked if ("clip:" + sfx_id(p[0])) not in used]
    if picked:
        # Do not always pick rank one: several close semantic matches should
        # still make separately requested ads feel like separate productions.
        path, seconds, candidate = random.choice(picked[:min(8, len(picked))])
        h3_ad_source_used("clip:" + sfx_id(path))
        return {"id": sfx_id(path), "name": path.stem[:120],
                "seconds": round(seconds, 2), "video": True,
                "match": str(getattr(candidate, "folder", "indexed clip"))[:120]}
    fresh = h3_hourly_fresh_clip()
    if fresh.get("id"):
        return fresh
'''
ROWS_OLD = '''        if rows:
            row = random.choice(rows[:min(80, len(rows))])
            return {"id": str(row[0] or ""), "name": str(row[1] or "clip")[:120],
'''
ROWS_NEW = '''        rows = [r for r in rows if ("clip:" + str(r[0] or "")) not in used]      # [ads-fresh]
        if rows:
            row = random.choice(rows[:min(80, len(rows))])
            h3_ad_source_used("clip:" + str(row[0] or ""))
            return {"id": str(row[0] or ""), "name": str(row[1] or "clip")[:120],
'''
SHORT_OLD = '''            if path and sfx_is_video(path):
                return {"id": sfx_id(path), "name": path.stem[:120],
                        "seconds": round(float(seconds or 0), 2), "video": True,
                        "match": "short MP4 fallback while dialogue matching is unavailable"}
'''
SHORT_NEW = '''            if path and sfx_is_video(path) and ("clip:" + sfx_id(path)) not in used:   # [ads-fresh]
                h3_ad_source_used("clip:" + sfx_id(path))
                return {"id": sfx_id(path), "name": path.stem[:120],
                        "seconds": round(float(seconds or 0), 2), "video": True,
                        "match": "short MP4 fallback while dialogue matching is unavailable"}
'''
RECORD_OLD = '''    return {"prompt_id": prompt_id, "model": model, "mode": mode,
            "prompt": final_prompt, "air_it": bool(payload.get("air_it")),
'''
RECORD_NEW = '''    # [ads-fresh] the source this render used goes in the ledger - a hand-picked
    # one too - so no automatic ad pick ever lands on it afterwards
    if mode != "text" and source_id:
        _used_key = ("clip:" + source_id if source_type in ("clip", "recent")
                     else "img:" + source_id if source_type == "gallery" else "")
        if _used_key:
            try:
                await asyncio.to_thread(h3_ad_source_used, _used_key)
            except Exception:  # noqa: BLE001
                pass
''' + RECORD_OLD

EDITS = [
    ("the-ledger-takes-any-used-source",
     "def voice_ad_person_clip(goal: str) -> dict[str, Any]:\n",
     TAKE + "def voice_ad_person_clip(goal: str) -> dict[str, Any]:\n", 1),
    ("the-ranking-never-offers-a-used-clip", RANKED_OLD, RANKED_NEW, 1),
    ("the-transcript-fallback-skips-used", ROWS_OLD, ROWS_NEW, 1),
    ("the-short-fallback-skips-used", SHORT_OLD, SHORT_NEW, 1),
    ("every-render-records-its-source", RECORD_OLD, RECORD_NEW, 1),
]


def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new, n_old = text.count(new), text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    applied, missing = 0, []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    if applied == len(plan(text)):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in plan(text):
        if state_of(text, old, new, count) == "applied":
            continue
        text = text.replace(old, new)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, path)
    return 0


def main(argv):
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if "--apply" in argv:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    if applied == len(plan(text)):
        print("already applied")
        return 2
    print("ready")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
