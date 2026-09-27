"""[h3-fresh] The hourly H3 stinger never reuses its source.

"make sure that for the hourly H3 stingers, that it never uses the same video
 twice for the ad. It should always use a new randomized clip every single
 time"

Before: the clip road took one of the eight clips that ranked best against
the hour's talk (voice_ad_person_clip - so the same few came back), and the
picture road one of the last thirty renders. Now every clip or picture an
hourly stinger takes is written down (data/h3_hourly_used.json) and never
offered to it again; the next is drawn uniformly at random from the rest -
10,552 dialogue clips on 2026-09-27 (a random ten-second window of a long
one, since only 81 run 15 s or less), every picture on the wall. The
deferred road (the clip book rebuilding at render time) binds a fresh clip
too. Should the list ever run out, the one used longest ago goes again and
the log says so.

--check exits 0 ready / 2 applied / 1 missing; --apply writes LF atomically.
ON THE HOST, from a fresh copy; re-anchor h3_hourly_door's render-and-door
afterwards (tools/reconcile_patch_text.py).
"""
import os
import sys
import tempfile
from pathlib import Path

HELPERS = r'''# --- [h3-fresh] THE HOURLY STINGER NEVER REUSES ITS SOURCE ---------------------
#
# "make sure that for the hourly H3 stingers, that it never uses the same video
#  twice for the ad. It should always use a new randomized clip every single
#  time." Every clip or picture an hourly stinger takes is written down here
# and never offered to it again; the next is drawn uniformly at random from
# what is left (10,552 dialogue clips on 2026-09-27). Should it ever run out,
# the one used longest ago goes again and the log says so.
_H3_FRESH_FILE = DATA_DIR / "h3_hourly_used.json"
_H3_FRESH_LOCK = RLock()
H3_HOURLY_WINDOW_S = 10.0


def h3_hourly_used() -> dict[str, float]:
    """[h3-fresh] Every source an hourly stinger has taken, and when."""
    try:
        got = json.loads(_H3_FRESH_FILE.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in got.items()} if isinstance(got, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:  # noqa: BLE001
        return {}


def h3_hourly_fresh_pick(keys: list[str], what: str) -> str:
    """[h3-fresh] One of `keys` no hourly stinger has used, uniformly at
    random, and written down as used before it is returned."""
    with _H3_FRESH_LOCK:
        used = h3_hourly_used()
        fresh = [k for k in keys if k not in used]
        if fresh:
            pick = random.choice(fresh)
        elif keys:
            pick = min(keys, key=lambda k: used.get(k, 0.0))
            pipeline_log("ads", "hourly H3: every one of the %d %s has been used once; the one used "
                                "longest ago goes again" % (len(keys), what))
        else:
            return ""
        used[pick] = time.time()
        if len(used) > 60000:
            used = dict(sorted(used.items(), key=lambda kv: kv[1])[-50000:])
        try:
            tmp = _H3_FRESH_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(used), encoding="utf-8")
            tmp.replace(_H3_FRESH_FILE)
        except Exception as exc:  # noqa: BLE001
            pipeline_log("ads", "hourly H3: the used-sources ledger could not be written (%s)"
                         % type(exc).__name__)
        pipeline_log("ads", "hourly H3 source: %s - %d of %d %s still unused"
                     % (pick, max(0, len(fresh) - 1), len(keys), what))
        return pick


def h3_hourly_fresh_clip() -> dict[str, Any]:
    """[h3-fresh] A dialogue-capable MP4 no hourly stinger has used, drawn at
    random from the whole clip book."""
    try:
        con = sfx_db_reader()
        with _SFX_DB_LOCK:
            rows = con.execute(
                "SELECT sid,name,seconds,folder FROM clips "
                "WHERE playable=1 AND video=1 AND seconds >= 3 "
                "AND length(trim(COALESCE(said,''))) >= 6").fetchall()
    except Exception as exc:  # noqa: BLE001
        pipeline_log("ads", "hourly H3: the clip book could not be read (%s)" % type(exc).__name__)
        return {}
    by_key = {"clip:" + str(r[0]): r for r in rows if r[0]}
    key = h3_hourly_fresh_pick(list(by_key), "dialogue clips")
    if not key:
        return {}
    row = by_key[key]
    return {"id": str(row[0]), "name": str(row[1] or "clip")[:120], "seconds": round(float(row[2] or 0), 2),
            "video": True, "match": "a fresh clip for the hourly stinger (%s)" % str(row[3] or "")[:80]}


def h3_hourly_fresh_image(images: list[str]) -> str:
    """[h3-fresh] A gallery picture no hourly stinger has used, drawn at random."""
    key = h3_hourly_fresh_pick(["img:" + str(f) for f in images if f], "gallery pictures")
    return key[4:] if key else ""


def h3_hourly_window(clip: dict[str, Any]) -> tuple[float, float]:
    """[h3-fresh] A random ten-second window of the clip (all of a short one)."""
    whole = float(clip.get("seconds") or 0.0)
    span = min(H3_HOURLY_WINDOW_S, whole)
    start = round(random.uniform(0.0, max(0.0, whole - span)), 2)
    return start, round(min(whole, start + span), 2)


'''

GALLERY_OLD = r'''        try:
            page = await asyncio.to_thread(generation_history_page, "", "", 30)
            images = [str(f) for r in page.get("generations", []) for f in (r.get("files") or [])
                      if re.search(r"\.(png|jpe?g|webp)$", str(f), re.I) and not gallery_paper_file(str(f))]
        except Exception:  # noqa: BLE001
            images = []
        if images:
            file = random.choice(images[:30])
'''
GALLERY_NEW = r'''        try:
            # [h3-fresh] every picture on the wall, not only the last thirty renders
            images = [p.name for p in await asyncio.to_thread(gallery_files, 600)
                      if re.search(r"\.(png|jpe?g|webp)$", p.name, re.I) and not gallery_paper_file(p.name)]
        except Exception:  # noqa: BLE001
            images = []
        file = (await asyncio.to_thread(h3_hourly_fresh_image, images)) if images else ""
        if file:
'''
CLIP_OLD = '''    message, job = await voice_ad_render(goal, hourly=True)      # [h3-cinematic]
    return (message, job, "clip")
'''
CLIP_NEW = '''    # [h3-fresh] a dialogue clip no hourly stinger has used, drawn at random,
    # and a random ten-second window of it
    fresh = await asyncio.to_thread(h3_hourly_fresh_clip)
    if fresh.get("id"):
        trim_in, trim_out = h3_hourly_window(fresh)
        message, job = await voice_ad_render(goal, reference_clip=fresh, hourly=True,
                                             trim_in_s=trim_in, trim_out_s=trim_out)
        return (message, job, "clip")
''' + CLIP_OLD
BIND_OLD = '''    clip = await asyncio.to_thread(
        voice_ad_person_clip, str(body.get("prompt") or body.get("speech") or ""))
'''
BIND_NEW = '''    if body.get("hourly"):                                               # [h3-fresh]
        clip = await asyncio.to_thread(h3_hourly_fresh_clip)
    else:
        clip = await asyncio.to_thread(
            voice_ad_person_clip, str(body.get("prompt") or body.get("speech") or ""))
'''
BOUND_OLD = '''    bound.update({"source": str(clip["id"]), "source_type": "clip"})
'''
BOUND_NEW = '''    bound.update({"source": str(clip["id"]), "source_type": "clip"})
    if body.get("hourly") and "trim_in_s" not in bound:                 # [h3-fresh] a random window
        bound["trim_in_s"], bound["trim_out_s"] = h3_hourly_window(clip)
'''

EDITS = [
    ("the-fresh-helpers",
     "async def h3_hourly_render(state: dict[str, Any]) -> tuple[str, Any, str]:\n",
     HELPERS + "async def h3_hourly_render(state: dict[str, Any]) -> tuple[str, Any, str]:\n", 1),
    ("a-fresh-picture", GALLERY_OLD, GALLERY_NEW, 1),
    ("a-fresh-clip", CLIP_OLD, CLIP_NEW, 1),
    ("the-deferred-road-binds-fresh", BIND_OLD, BIND_NEW, 1),
    ("the-deferred-road-takes-a-window", BOUND_OLD, BOUND_NEW, 1),
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
