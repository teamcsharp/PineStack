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
# [s3-visuals] 2026-09-28: the clip road's picks are System 3's draws now
# (tools/s3_visuals_patch.py) and this stored text was re-anchored by hand -
# its last line repeats in the region, which reconcile_patch_text refuses.
# Applying on a fresh file writes the final, dice-door text, so the
# s3_visuals clip/fallback edits then read as applied.
CLIP_NEW = '''    # [h3-fresh] a dialogue clip no hourly stinger has used, drawn at random,
    # and a random ten-second window of it
    fresh = await asyncio.to_thread(h3_hourly_fresh_clip)
    if fresh.get("id"):
        trim_in, trim_out = h3_hourly_window(fresh)
        h3_hourly_roll_note("fresh", "h3.hourly_fresh", rec=h3_hourly_fresh_roll())       # [s3-visuals]
        h3_hourly_roll_note("marker", "h3.hourly_marker")
        h3_hourly_rolls_bind(goal)
        message, job = await voice_ad_render(goal, reference_clip=fresh, hourly=True,
                                             trim_in_s=trim_in, trim_out_s=trim_out)
        return (message, job, "clip")
    h3_hourly_roll_note("fresh", "h3.hourly_fresh", rec=h3_hourly_fresh_roll())          # [s3-visuals]
    h3_hourly_rolls_bind(goal)
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
     '# --- [h3-fresh] THE HOURLY STINGER NEVER REUSES ITS SOURCE ---------------------\n'
     '#\n'
     '# "make sure that for the hourly H3 stingers, that it never uses the same video\n'
     '#  twice for the ad. It should always use a new randomized clip every single\n'
     '#  time." Every clip or picture an hourly stinger takes is written down here\n'
     '# and never offered to it again; the next is drawn uniformly at random from\n'
     '# what is left (10,552 dialogue clips on 2026-09-27). Should it ever run out,\n'
     '# the one used longest ago goes again and the log says so.\n'
     '_H3_FRESH_FILE = DATA_DIR / "h3_hourly_used.json"\n'
     '_H3_FRESH_LOCK = RLock()\n'
     'H3_HOURLY_WINDOW_S = 10.0\n'
     '\n'
     '\n'
     'def h3_hourly_used() -> dict[str, float]:\n'
     '    """[h3-fresh] Every source an hourly stinger has taken, and when."""\n'
     '    try:\n'
     '        got = json.loads(_H3_FRESH_FILE.read_text(encoding="utf-8"))\n'
     '        return {str(k): float(v) for k, v in got.items()} if isinstance(got, dict) else {}\n'
     '    except FileNotFoundError:\n'
     '        return {}\n'
     '    except Exception:  # noqa: BLE001\n'
     '        return {}\n'
     '\n'
     '\n'
     'def h3_hourly_fresh_pick(keys: list[str], what: str) -> str:\n'
     '    """[h3-fresh] One of `keys` no hourly stinger has used, uniformly at\n'
     '    random, and written down as used before it is returned."""\n'
     '    with _H3_FRESH_LOCK:\n'
     '        used = h3_hourly_used()\n'
     '        fresh = [k for k in keys if k not in used]\n'
     '        if fresh:\n'
     "            # [s3-visuals] the never-repeat rotation is System 3's roulette:\n"
     '            # drawn on its dice and recorded, uniform over what is left\n'
     "            # (h3.hourly_fresh); the station's own uniform choice only when\n"
     '            # the dice are off or this runs outside the station.\n'
     '            _draw = globals().get("s3_weighted")\n'
     '            _k = _draw("h3.hourly_fresh", fresh, [1.0] * len(fresh),\n'
     '                       "which unused source the hourly H3 stinger takes (the fresh rotation, %s)" % what) if _draw else None\n'
     '            pick = fresh[_k] if isinstance(_k, int) and 0 <= _k < len(fresh) else random.choice(fresh)\n'
     '            _read = globals().get("_s3_sfx_rolled")\n'
     '            _rec = _read("h3.hourly_fresh", pick, _k) if _read and isinstance(_k, int) else {}\n'
     '            _H3_FRESH_ROLL[0] = dict(_rec, kind="pick", key="h3.hourly_fresh",\n'
     '                                     picked=pick, at=time.time()) if _rec else None\n'
     '        elif keys:\n'
     '            pick = min(keys, key=lambda k: used.get(k, 0.0))\n'
     '            pipeline_log("ads", "hourly H3: every one of the %d %s has been used once; the one used "\n'
     '                                "longest ago goes again" % (len(keys), what))\n'
     '        else:\n'
     '            return ""\n'
     '        used[pick] = time.time()\n'
     '        if len(used) > 60000:\n'
     '            used = dict(sorted(used.items(), key=lambda kv: kv[1])[-50000:])\n'
     '        try:\n'
     '            tmp = _H3_FRESH_FILE.with_suffix(".json.tmp")\n'
     '            tmp.write_text(json.dumps(used), encoding="utf-8")\n'
     '            tmp.replace(_H3_FRESH_FILE)\n'
     '        except Exception as exc:  # noqa: BLE001\n'
     '            pipeline_log("ads", "hourly H3: the used-sources ledger could not be written (%s)"\n'
     '                         % type(exc).__name__)\n'
     '        pipeline_log("ads", "hourly H3 source: %s - %d of %d %s still unused"\n'
     '                     % (pick, max(0, len(fresh) - 1), len(keys), what))\n'
     '        return pick\n'
     '\n'
     '\n'
     'def h3_hourly_fresh_clip() -> dict[str, Any]:\n'
     '    """[h3-fresh] A dialogue-capable MP4 no hourly stinger has used, drawn at\n'
     '    random from the whole clip book."""\n'
     '    try:\n'
     '        con = sfx_db_reader()\n'
     '        with _SFX_DB_LOCK:\n'
     '            rows = con.execute(\n'
     '                "SELECT sid,name,seconds,folder FROM clips "\n'
     '                "WHERE playable=1 AND video=1 AND seconds >= 3 "\n'
     '                "AND length(trim(COALESCE(said,\'\'))) >= 6").fetchall()\n'
     '    except Exception as exc:  # noqa: BLE001\n'
     '        pipeline_log("ads", "hourly H3: the clip book could not be read (%s)" % type(exc).__name__)\n'
     '        return {}\n'
     '    by_key = {"clip:" + str(r[0]): r for r in rows if r[0]}\n'
     '    key = h3_hourly_fresh_pick(list(by_key), "dialogue clips")\n'
     '    if not key:\n'
     '        return {}\n'
     '    row = by_key[key]\n'
     '    return {"id": str(row[0]), "name": str(row[1] or "clip")[:120], "seconds": round(float(row[2] or 0), 2),\n'
     '            "video": True, "match": "a fresh clip for the hourly stinger (%s)" % str(row[3] or "")[:80]}\n'
     '\n'
     '\n'
     'def h3_hourly_fresh_image(images: list[str]) -> str:\n'
     '    """[h3-fresh] A gallery picture no hourly stinger has used, drawn at random."""\n'
     '    key = h3_hourly_fresh_pick(["img:" + str(f) for f in images if f], "gallery pictures")\n'
     '    return key[4:] if key else ""\n'
     '\n'
     '\n'
     'def h3_hourly_window(clip: dict[str, Any]) -> tuple[float, float]:\n'
     '    """[h3-fresh] A random ten-second window of the clip (all of a short one)."""\n'
     '    whole = float(clip.get("seconds") or 0.0)\n'
     '    span = min(H3_HOURLY_WINDOW_S, whole)\n'
     "    # [s3-visuals] where the window's markers land on the clip is System 3's\n"
     "    # roll: one number in [0, 1) over the clip's spare room, recorded\n"
     '    # (h3.hourly_marker). The same uniform the station always rolled.\n'
     '    _draw = globals().get("s3_roll")\n'
     '    _u = _draw("h3.hourly_marker",\n'
     '               "where the ten-second window\'s markers land on the hourly clip (0 = its start, 1 = its end)") if _draw else random.random()\n'
     '    start = round(float(_u) * max(0.0, whole - span), 2)\n'
     '    return start, round(min(whole, start + span), 2)\n'
     '\n'
     '\n'
     "# --- [s3-visuals] THE DOOR'S ROLLS, KEPT FOR THE HOUR'S RECORD ----------------\n"
     '#\n'
     '# "VISUALS = roulette where they rotate" (operator, 2026-09-28): every pick the\n'
     "# hourly door makes is one of System 3's recorded draws, and the door writes\n"
     "# what it rolled onto the hour's record (the presets history ad-viewer reads),\n"
     "# onto every render row's h3_prompts record, and - one line per hourly render -\n"
     '# into data/h3_hourly_airings.jsonl, the durable record that joins a render to\n'
     '# its rolls. {} when the station rolled its own (System 3 off): never fake dice.\n'
     '_H3_AIRINGS_FILE = DATA_DIR / "h3_hourly_airings.jsonl"\n'
     '_H3_HOURLY_ROLLS: dict[str, Any] = {}\n'
     '_H3_HOURLY_ROLLS_LAST: list[Any] = [None]\n'
     '_H3_FRESH_ROLL: list[Any] = [None]\n'
     'H3_HOURLY_SOURCE_LABEL = ("which source road the hourly H3 stinger takes "\n'
     '                          "(gallery_share percent of hours start from a gallery picture, the rest from a dialogue clip)")\n'
     '\n'
     '\n'
     'def h3_hourly_fresh_roll() -> dict[str, Any]:\n'
     '    """[s3-visuals] The roll that made the last fresh pick. The pick may run in\n'
     "    a worker thread (asyncio.to_thread), where System 3's per-thread read-back\n"
     '    cannot be seen from the loop - so the pick leaves its record here."""\n'
     '    rec, _H3_FRESH_ROLL[0] = _H3_FRESH_ROLL[0], None\n'
     '    if isinstance(rec, dict) and time.time() - float(rec.get("at") or 0) <= 120:\n'
     '        return {k: v for k, v in rec.items() if k != "at"}\n'
     '    return {}\n'
     '\n'
     '\n'
     'def h3_hourly_roll_note(name: str, key: str, rec: Any = None) -> None:\n'
     '    """[s3-visuals] Keep the roll the door just made under `key` (or the record\n'
     '    handed in), compact, for the hour\'s record and the airing log."""\n'
     '    if rec is None:\n'
     '        fn = globals().get("system3_last_roll")\n'
     '        try:\n'
     '            rec = fn(key) if fn else None\n'
     '        except Exception:  # noqa: BLE001\n'
     '            rec = None\n'
     '        if isinstance(rec, dict) and time.time() - float(rec.get("at") or 0) > 120:\n'
     '            rec = None\n'
     '    got = {}\n'
     '    if isinstance(rec, dict) and rec:\n'
     '        got = {k: rec[k] for k in ("kind", "key", "label", "odds", "hit", "dice", "u", "index", "of", "picked")\n'
     '               if rec.get(k) is not None}\n'
     '        got.setdefault("key", key)\n'
     '    _H3_HOURLY_ROLLS[name] = got\n'
     '\n'
     '\n'
     'def h3_hourly_rolls_bind(goal: str) -> dict[str, Any]:\n'
     '    """[s3-visuals] The door\'s rolls, onto the hour\'s record - the entry the\n'
     "    presets history keeps and every render row's h3_prompts record reads -\n"
     "    and left for the clock's airing line. Called once per road, right before\n"
     '    the render is queued or made."""\n'
     '    rolls = {k: v for k, v in _H3_HOURLY_ROLLS.items() if v}\n'
     '    _H3_HOURLY_ROLLS.clear()\n'
     '    entry = None\n'
     '    find = globals().get("h3_prompts_hour_for")\n'
     '    try:\n'
     '        entry = find(goal, exact=True) if find else None\n'
     '    except Exception:  # noqa: BLE001\n'
     '        entry = None\n'
     '    if isinstance(entry, dict) and entry.get("hour"):\n'
     '        if isinstance(entry.get("roll"), dict):\n'
     '            rolls = dict(rolls, preset={k: entry["roll"][k]\n'
     '                                        for k in ("by", "key", "picked", "index", "of", "dice", "u")\n'
     '                                        if entry["roll"].get(k) is not None})\n'
     '        if rolls:\n'
     '            entry["rolls"] = rolls\n'
     '            try:\n'
     '                _h3_prompts_offloop(h3_prompts_commit_hour, dict(entry))\n'
     '            except Exception:  # noqa: BLE001 - the memory entry still carries them\n'
     '                pass\n'
     '    _H3_HOURLY_ROLLS_LAST[0] = {"at": time.time(), "hour": str((entry or {}).get("hour") or ""), "rolls": rolls}\n'
     '    return rolls\n'
     '\n'
     '\n'
     'def h3_hourly_airing_note(marker: Any, source: Any, message: Any, job: Any) -> None:\n'
     '    """[s3-visuals] One durable line per hourly render: the hour, its marker,\n'
     '    the source road, the job and the rolls that picked everything - what the\n'
     '    census joins (data/h3_hourly_airings.jsonl <-> h3_prompt_presets.json\n'
     '    history by `hour`, <-> h3_hourly.json by `marker`)."""\n'
     '    bound, _H3_HOURLY_ROLLS_LAST[0] = _H3_HOURLY_ROLLS_LAST[0], None\n'
     '    if not (isinstance(bound, dict) and time.time() - float(bound.get("at") or 0) <= 600):\n'
     '        bound = {}\n'
     '    row = {"at": round(time.time(), 3), "marker": str(marker or ""), "source": str(source or ""),\n'
     '           "hour": str(bound.get("hour") or ""), "rolls": bound.get("rolls") or {},\n'
     '           "message": str(message or "")[:200],\n'
     '           "job": str(job.get("id") or "") if isinstance(job, dict) else ""}\n'
     '\n'
     '    def write() -> None:\n'
     '        try:\n'
     '            with _H3_AIRINGS_FILE.open("a", encoding="utf-8") as fh:\n'
     '                fh.write(json.dumps(row) + "\\n")\n'
     '        except Exception as exc:  # noqa: BLE001\n'
     '            pipeline_log("ads", "hourly H3: the airing record was not written (%s)" % type(exc).__name__)\n'
     '    try:\n'
     '        _h3_prompts_offloop(write)\n'
     '    except Exception:  # noqa: BLE001 - a test namespace without the section\n'
     '        write()\n'
     '\n'
     '\n'
     'async def h3_hourly_render(state: dict[str, Any]) -> tuple[str, Any, str]:\n', 1),
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
