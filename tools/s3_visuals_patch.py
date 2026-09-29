"""[s3-visuals] The rotating visuals roll through System 3's own dice.

"VISUALS = roulette where they rotate" (operator, the total-coverage audit,
2026-09-28). Two of the audit's gaps close here:

GAP 6 - the hourly H3 video ad (~24 renders a day) picked everything with the
station's bare random: which source road (gallery picture vs dialogue clip vs
the host's cast), which unused clip or picture the fresh rotation takes, and
where the ten-second window's markers land. Every one of those is now a draw
through the [s3-dice-door] (s3_chance / s3_pool+s3_weighted / s3_roll), on the
STATION keys h3.hourly_host (STATION1 chance row, follows the host_share
dial), h3.hourly_source (POOLS1 row, weighted by the gallery_share dial),
h3.hourly_fresh (the never-repeat rotation's pick, uniform over what is
left) and h3.hourly_marker (a number in [0, 1) over the clip's spare room).
The preset pick was already System 3's (h3.hourly_preset, the gallery's
dice); its ladder - pin > dice > active - is not touched. The door's rolls
are written onto the hour's record in the presets history (`rolls`), ride
every render row's `h3_prompts` record (ad-viewer shows them under the
video), and one durable line per hourly render lands in
data/h3_hourly_airings.jsonl - the joinable record the audit found missing.
Distributions are unchanged to the digit: randint(1,100) <= share was
share/100, and s3_chance / the weighted pick roll at exactly share/100;
random.choice was uniform and the fresh pick's weights are all 1.0;
random.uniform(0, room) was u * room. With System 3 off (or in a test
namespace without the door) every draw falls back to the station's own
random, as the whole dice door does.

GAP 7 - the slideshow rotated 1,404 pictures off the client's Math.random
(slideshow.js seeded the server shuffle; transitions were Math.random too).
The deal moves server-side on the records.rotation_deal pattern: a playlist
ask that brings no seed rolls slideshow.deal ONCE, the roll deals the page's
whole order (seed = 1 + u * (2^53 - 2)) and the dealt seed rides the answer,
so the client keeps it and page two - and every later ask - continues the
same deal with no new roll. Each served row also carries the transition it
enters with, dealt from the POOLS1-tabled pool slideshow.transition (the
desk can weight a transition or retire it) by ONE recorded roll per page.
The hot-load road (?since=) deals a new render's entrance the same way.
Nothing about pacing, paging or the response shape changes for a client
that brings a seed - only the randomness source moves, and is recorded.

Nothing here adds or moves a render (#1285), and no existing draw moves to
a different stream - the new keys are their own.

--check exits 0 ready / 2 applied / 1 missing; --apply is idempotent and
writes LF atomically. ON THE HOST, from a fresh copy. The older tools whose
stored text these lines land inside ship ALREADY RECONCILED in this same
change - h3_fresh_patch.py (the-fresh-helpers, a-fresh-clip),
h3_hourly_door_patch.py (render-and-door), h3_prompt_presets_patch.py
(presets-store-and-doors) and h3_cast_patch.py (the-host-has-hours). Copy
those four over tools/ AFTER this --apply, and never --apply one of them
against an app.py that lacks these edits: their stored text is the
post-s3_visuals text, so there they read "ready" and a blind apply would
double-insert. On the patched app.py reconcile_patch_text reads four of the
five as "already matches" (exit 2); it cannot parse a-fresh-clip (its last
stored line repeats in the region - ValueError, nothing written), so that
literal was re-anchored by hand.
"""
import os
import sys
import tempfile
from pathlib import Path

# --- GAP 6: the hourly door -------------------------------------------------

# The door's own collectors, the fresh rotation's read-back slot and the
# durable airing record. Inserted at the end of the [h3-fresh] helper block,
# BEFORE h3_hourly_render, so tests/test_h3_fresh.py's extraction span
# (everything from _H3_FRESH_FILE up to the render) carries them too - they
# exec clean in that bare namespace and only reach for the dice door through
# globals().get at call time.
DOOR_HELPERS = '''# --- [s3-visuals] THE DOOR'S ROLLS, KEPT FOR THE HOUR'S RECORD ----------------
#
# "VISUALS = roulette where they rotate" (operator, 2026-09-28): every pick the
# hourly door makes is one of System 3's recorded draws, and the door writes
# what it rolled onto the hour's record (the presets history ad-viewer reads),
# onto every render row's h3_prompts record, and - one line per hourly render -
# into data/h3_hourly_airings.jsonl, the durable record that joins a render to
# its rolls. {} when the station rolled its own (System 3 off): never fake dice.
_H3_AIRINGS_FILE = DATA_DIR / "h3_hourly_airings.jsonl"
_H3_HOURLY_ROLLS: dict[str, Any] = {}
_H3_HOURLY_ROLLS_LAST: list[Any] = [None]
_H3_FRESH_ROLL: list[Any] = [None]
H3_HOURLY_SOURCE_LABEL = ("which source road the hourly H3 stinger takes "
                          "(gallery_share percent of hours start from a gallery picture, the rest from a dialogue clip)")


def h3_hourly_fresh_roll() -> dict[str, Any]:
    """[s3-visuals] The roll that made the last fresh pick. The pick may run in
    a worker thread (asyncio.to_thread), where System 3's per-thread read-back
    cannot be seen from the loop - so the pick leaves its record here."""
    rec, _H3_FRESH_ROLL[0] = _H3_FRESH_ROLL[0], None
    if isinstance(rec, dict) and time.time() - float(rec.get("at") or 0) <= 120:
        return {k: v for k, v in rec.items() if k != "at"}
    return {}


def h3_hourly_roll_note(name: str, key: str, rec: Any = None) -> None:
    """[s3-visuals] Keep the roll the door just made under `key` (or the record
    handed in), compact, for the hour's record and the airing log."""
    if rec is None:
        fn = globals().get("system3_last_roll")
        try:
            rec = fn(key) if fn else None
        except Exception:  # noqa: BLE001
            rec = None
        if isinstance(rec, dict) and time.time() - float(rec.get("at") or 0) > 120:
            rec = None
    got = {}
    if isinstance(rec, dict) and rec:
        got = {k: rec[k] for k in ("kind", "key", "label", "odds", "hit", "dice", "u", "index", "of", "picked")
               if rec.get(k) is not None}
        got.setdefault("key", key)
    _H3_HOURLY_ROLLS[name] = got


def h3_hourly_rolls_bind(goal: str) -> dict[str, Any]:
    """[s3-visuals] The door's rolls, onto the hour's record - the entry the
    presets history keeps and every render row's h3_prompts record reads -
    and left for the clock's airing line. Called once per road, right before
    the render is queued or made."""
    rolls = {k: v for k, v in _H3_HOURLY_ROLLS.items() if v}
    _H3_HOURLY_ROLLS.clear()
    entry = None
    find = globals().get("h3_prompts_hour_for")
    try:
        entry = find(goal, exact=True) if find else None
    except Exception:  # noqa: BLE001
        entry = None
    if isinstance(entry, dict) and entry.get("hour"):
        if isinstance(entry.get("roll"), dict):
            rolls = dict(rolls, preset={k: entry["roll"][k]
                                        for k in ("by", "key", "picked", "index", "of", "dice", "u")
                                        if entry["roll"].get(k) is not None})
        if rolls:
            entry["rolls"] = rolls
            try:
                _h3_prompts_offloop(h3_prompts_commit_hour, dict(entry))
            except Exception:  # noqa: BLE001 - the memory entry still carries them
                pass
    _H3_HOURLY_ROLLS_LAST[0] = {"at": time.time(), "hour": str((entry or {}).get("hour") or ""), "rolls": rolls}
    return rolls


def h3_hourly_airing_note(marker: Any, source: Any, message: Any, job: Any) -> None:
    """[s3-visuals] One durable line per hourly render: the hour, its marker,
    the source road, the job and the rolls that picked everything - what the
    census joins (data/h3_hourly_airings.jsonl <-> h3_prompt_presets.json
    history by `hour`, <-> h3_hourly.json by `marker`)."""
    bound, _H3_HOURLY_ROLLS_LAST[0] = _H3_HOURLY_ROLLS_LAST[0], None
    if not (isinstance(bound, dict) and time.time() - float(bound.get("at") or 0) <= 600):
        bound = {}
    row = {"at": round(time.time(), 3), "marker": str(marker or ""), "source": str(source or ""),
           "hour": str(bound.get("hour") or ""), "rolls": bound.get("rolls") or {},
           "message": str(message or "")[:200],
           "job": str(job.get("id") or "") if isinstance(job, dict) else ""}

    def write() -> None:
        try:
            with _H3_AIRINGS_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\\n")
        except Exception as exc:  # noqa: BLE001
            pipeline_log("ads", "hourly H3: the airing record was not written (%s)" % type(exc).__name__)
    try:
        _h3_prompts_offloop(write)
    except Exception:  # noqa: BLE001 - a test namespace without the section
        write()


'''

FRESH_PICK_OLD = '''        if fresh:
            pick = random.choice(fresh)
'''
FRESH_PICK_NEW = '''        if fresh:
            # [s3-visuals] the never-repeat rotation is System 3's roulette:
            # drawn on its dice and recorded, uniform over what is left
            # (h3.hourly_fresh); the station's own uniform choice only when
            # the dice are off or this runs outside the station.
            _draw = globals().get("s3_weighted")
            _k = _draw("h3.hourly_fresh", fresh, [1.0] * len(fresh),
                       "which unused source the hourly H3 stinger takes (the fresh rotation, %s)" % what) if _draw else None
            pick = fresh[_k] if isinstance(_k, int) and 0 <= _k < len(fresh) else random.choice(fresh)
            _read = globals().get("_s3_sfx_rolled")
            _rec = _read("h3.hourly_fresh", pick, _k) if _read and isinstance(_k, int) else {}
            _H3_FRESH_ROLL[0] = dict(_rec, kind="pick", key="h3.hourly_fresh",
                                     picked=pick, at=time.time()) if _rec else None
'''

WINDOW_OLD = '''    whole = float(clip.get("seconds") or 0.0)
    span = min(H3_HOURLY_WINDOW_S, whole)
    start = round(random.uniform(0.0, max(0.0, whole - span)), 2)
'''
WINDOW_NEW = '''    whole = float(clip.get("seconds") or 0.0)
    span = min(H3_HOURLY_WINDOW_S, whole)
    # [s3-visuals] where the window's markers land on the clip is System 3's
    # roll: one number in [0, 1) over the clip's spare room, recorded
    # (h3.hourly_marker). The same uniform the station always rolled.
    _draw = globals().get("s3_roll")
    _u = _draw("h3.hourly_marker",
               "where the ten-second window's markers land on the hourly clip (0 = its start, 1 = its end)") if _draw else random.random()
    start = round(float(_u) * max(0.0, whole - span), 2)
'''

HOST_GATE_OLD = '''        if host_share and random.randint(1, 100) <= host_share:
            payload = {"mode": "text", "purpose": "parody_stinger", "source": "", "source_type": "",
'''
HOST_GATE_NEW = '''        _h3_host_hit = bool(host_share) and s3_chance(
            "h3.hourly_host", host_share / 100.0,
            "whether the host's cast LoRA presents this hourly H3 stinger (host_share percent of hours)",
            dial="host_share (the H3 door's own dial)")                      # [s3-visuals]
        if host_share:
            h3_hourly_roll_note("host", "h3.hourly_host")
        if _h3_host_hit:
            h3_hourly_rolls_bind(goal)                                       # [s3-visuals]
            payload = {"mode": "text", "purpose": "parody_stinger", "source": "", "source_type": "",
'''

SOURCE_GATE_OLD = '''    if share and random.randint(1, 100) <= share:
'''
SOURCE_GATE_NEW = '''    _h3_gallery = False
    if share:
        # [s3-visuals] which source road this hour takes is System 3's pick
        # from the tabled pool (POOLS1 h3.hourly_source - the desk can retire
        # a road), weighted by the operator's own gallery_share dial: the
        # same share/100 odds randint(1, 100) <= share always rolled.
        _h3_srcs = ["gallery picture", "dialogue clip"]
        _h3_pool = [s for s in (s3_pool("h3.hourly_source", _h3_srcs, H3_HOURLY_SOURCE_LABEL) or _h3_srcs)
                    if s in _h3_srcs] or _h3_srcs
        _h3_w = {"gallery picture": float(share), "dialogue clip": float(100 - share)}
        _h3_k = s3_weighted("h3.hourly_source", _h3_pool, [_h3_w[s] for s in _h3_pool], H3_HOURLY_SOURCE_LABEL)
        _h3_gallery = _h3_pool[_h3_k if isinstance(_h3_k, int) and 0 <= _h3_k < len(_h3_pool) else 0] == "gallery picture"
        h3_hourly_roll_note("source", "h3.hourly_source")
    if _h3_gallery:
'''

GALLERY_TAKE_OLD = '''        file = (await asyncio.to_thread(h3_hourly_fresh_image, images)) if images else ""
        if file:
            payload = {"mode": "reference", "purpose": "parody_stinger", "source": file,
'''
GALLERY_TAKE_NEW = '''        file = (await asyncio.to_thread(h3_hourly_fresh_image, images)) if images else ""
        if file:
            h3_hourly_roll_note("fresh", "h3.hourly_fresh", rec=h3_hourly_fresh_roll())   # [s3-visuals]
            h3_hourly_rolls_bind(goal)
            payload = {"mode": "reference", "purpose": "parody_stinger", "source": file,
'''

CLIP_TAKE_OLD = '''    if fresh.get("id"):
        trim_in, trim_out = h3_hourly_window(fresh)
        message, job = await voice_ad_render(goal, reference_clip=fresh, hourly=True,
'''
CLIP_TAKE_NEW = '''    if fresh.get("id"):
        trim_in, trim_out = h3_hourly_window(fresh)
        h3_hourly_roll_note("fresh", "h3.hourly_fresh", rec=h3_hourly_fresh_roll())       # [s3-visuals]
        h3_hourly_roll_note("marker", "h3.hourly_marker")
        h3_hourly_rolls_bind(goal)
        message, job = await voice_ad_render(goal, reference_clip=fresh, hourly=True,
'''

FALLBACK_OLD = '''    message, job = await voice_ad_render(goal, hourly=True)      # [h3-cinematic]
    return (message, job, "clip")
'''
FALLBACK_NEW = '''    h3_hourly_roll_note("fresh", "h3.hourly_fresh", rec=h3_hourly_fresh_roll())          # [s3-visuals]
    h3_hourly_rolls_bind(goal)
    message, job = await voice_ad_render(goal, hourly=True)      # [h3-cinematic]
    return (message, job, "clip")
'''

CLOCK_OLD = '''                    h3_hourly_save({"last_at": time.time(), "last_message": str(message)[:200],
                                    "last_source": source, "last_marker": marker})
'''
CLOCK_NEW = '''                    h3_hourly_save({"last_at": time.time(), "last_message": str(message)[:200],
                                    "last_source": source, "last_marker": marker})
                    h3_hourly_airing_note(marker, source, message, job)      # [s3-visuals]
'''

WORDS_OLD = '''            "how": hour.get("how"), "preset": dict(hour.get("preset") or {}), "roll": hour.get("roll"),
'''
WORDS_NEW = '''            "how": hour.get("how"), "preset": dict(hour.get("preset") or {}), "roll": hour.get("roll"),
            "rolls": hour.get("rolls") if isinstance(hour.get("rolls"), dict) else None,   # [s3-visuals] the door's dice
'''

HOUR_VIEW_OLD = '''            "roll": entry.get("roll"), "goal": str(entry.get("goal") or "")[:1200],
'''
HOUR_VIEW_NEW = '''            "roll": entry.get("roll"), "goal": str(entry.get("goal") or "")[:1200],
            "rolls": entry.get("rolls") if isinstance(entry.get("rolls"), dict) else None,   # [s3-visuals]
'''

# --- GAP 7: the slideshow deal ----------------------------------------------

DEAL_HELPERS = '''# [s3-visuals] "roulette where they rotate": the slideshow's shuffle and its
# transitions are System 3's deals, on the records.rotation_deal pattern -
# ONE recorded roll deals a page's whole order (slideshow.deal), one more
# deals each served row the transition it enters with, from the POOLS1-tabled
# pool slideshow.transition the desk can weight or retire. The client brings
# no seed on its first ask, keeps the dealt one, and nothing about pacing or
# paging changes - only the randomness source moves, and is recorded.
SLIDESHOW_TRANSITION_LABEL = ("which transition each slideshow advance enters with "
                              "(one roll deals the served rows' transitions from the tabled pool)")


def _slideshow_last_roll(key: str) -> dict[str, Any]:
    """The roll System 3 just recorded under `key`, compact - {} when the
    station rolled its own (the answer then simply carries no dice)."""
    fn = globals().get("system3_last_roll")
    try:
        rec = fn(key) if fn else None
    except Exception:  # noqa: BLE001
        rec = None
    if not (isinstance(rec, dict) and time.time() - float(rec.get("at") or 0) <= 60):
        return {}
    return {k: rec[k] for k in ("kind", "key", "label", "dice", "u") if rec.get(k) is not None}


def _slideshow_transition_weights(pool: list[str]) -> list[float]:
    """Each pooled transition's weight on System 3's desk (POOLS1
    slideshow.transition); 1.0 for one the desk has not seen."""
    getter = globals().get("_system3")
    try:
        config = getter().config if callable(getter) else {}
    except Exception:  # noqa: BLE001
        config = {}
    desk: dict[str, float] = {}
    for table in (config or {}).get("tables") or []:
        if not isinstance(table, dict) or table.get("family") != "POOL" or table.get("enabled") is False:
            continue
        for cat in table.get("categories") or []:
            if not (isinstance(cat, dict) and cat.get("id") == "slideshow.transition"):
                continue
            for item in cat.get("items") or []:
                if not isinstance(item, dict):
                    continue
                text = " ".join(str(item.get("text") or "").split())
                try:
                    desk[text] = 0.0 if item.get("enabled") is False else max(0.0, float(item.get("weight", 1.0) or 0))
                except (TypeError, ValueError):
                    desk[text] = 1.0
    out = [desk.get(t, 1.0) for t in pool]
    return out if sum(out) > 0 else [1.0] * len(pool)


def _slideshow_deal_transitions(page: list[dict[str, Any]]) -> dict[str, Any]:
    """[s3-visuals] Deal each served row the transition it enters with: the
    pool is tabled (POOLS1 slideshow.transition), ONE recorded roll seeds the
    whole deal, and the client's 'all' setting consumes row["transition"] - a
    fixed transition setting ignores it, exactly as before. Returns the deal's
    record for the answer; a failed deal never costs the playlist."""
    if not page:
        return {}
    try:
        concrete = [t for t in SLIDESHOW_TRANSITIONS if t != "all"]
        pool = [t for t in (s3_pool("slideshow.transition", concrete, SLIDESHOW_TRANSITION_LABEL) or concrete)
                if t in concrete] or concrete
        weights = _slideshow_transition_weights(pool)
        u = s3_roll("slideshow.transition", SLIDESHOW_TRANSITION_LABEL)
        dealer = random.Random(1 + int(float(u) * float((1 << 53) - 2)))
        for row in page:
            row["transition"] = dealer.choices(pool, weights=weights, k=1)[0]
        rec = _slideshow_last_roll("slideshow.transition")
        if not rec:
            return {}                # the station dealt its own: no record is claimed
        return dict(rec, pool=pool[:24], weights=[round(w, 3) for w in weights[:24]])
    except Exception:  # noqa: BLE001
        return {}


'''

SINCE_OLD = '''    if since > 0:
        fresh = [r for r in rows if r["at"] > since]
        return {"ok": bool(scan.get("ok")), "at": time.time(),
'''
SINCE_NEW = '''    if since > 0:
        fresh = [r for r in rows if r["at"] > since]
        if fresh:
            _slideshow_deal_transitions(fresh[:200])   # [s3-visuals] a new render's entrance is dealt too
        return {"ok": bool(scan.get("ok")), "at": time.time(),
'''

ORDER_OLD = '''    want_order = (order or "shuffle").strip().lower()
'''
ORDER_NEW = '''    want_order = (order or "shuffle").strip().lower()
    _deal_seed = max(0, int(seed))                # [s3-visuals] 0: the station deals
    _deal_roll: dict[str, Any] = {}
'''

SHUFFLE_OLD = '''    elif want_order == "shuffle":
        random.Random(int(seed) or 1).shuffle(rows)
'''
SHUFFLE_NEW = '''    elif want_order == "shuffle":
        # [s3-visuals] the deal is the station's, on the records.rotation_deal
        # pattern: an ask that brings no seed rolls slideshow.deal ONCE, the
        # roll deals the page's whole order and the dealt seed rides the
        # answer - the client keeps it, so page two and every later ask
        # continue the same deal with no new roll.
        if not _deal_seed:
            _deal_u = s3_roll("slideshow.deal",
                              "the order the slideshow's rotation is dealt in (one roll deals the page's shuffle; the client keeps the dealt seed)")
            _deal_seed = 1 + int(float(_deal_u) * float((1 << 53) - 2))
            _deal_roll = _slideshow_last_roll("slideshow.deal")
        random.Random(_deal_seed).shuffle(rows)
'''

PAGE_OLD = '''    page = rows[start:start + want]
    return {
'''
PAGE_NEW = '''    page = rows[start:start + want]
    _deal_t = _slideshow_deal_transitions(page)   # [s3-visuals] each row's entrance, from the tabled pool
    return {
'''

SEED_OLD = '''        "order": want_order,
        "seed": int(seed) or 1,
        "transitions": SLIDESHOW_TRANSITIONS,
'''
SEED_NEW = '''        "order": want_order,
        "seed": _deal_seed or 1,
        "deal": ({k: v for k, v in (("roll", _deal_roll or None), ("transition", _deal_t or None)) if v}
                 or None),                        # [s3-visuals] the recorded dice behind this page
        "transitions": SLIDESHOW_TRANSITIONS,
'''

PLAYLIST_DOOR_OLD = '''@app.get("/api/slideshow/playlist")
async def slideshow_playlist_api(
'''
PLAYLIST_DOOR_NEW = DEAL_HELPERS + PLAYLIST_DOOR_OLD

RENDER_DEF_OLD = '''async def h3_hourly_render(state: dict[str, Any]) -> tuple[str, Any, str]:
    """[h3-hourly] One hourly stinger: from a gallery image for gallery_share
'''
RENDER_DEF_NEW = DOOR_HELPERS + RENDER_DEF_OLD

EDITS = [
    ("the-door-collectors-and-the-airing-record", RENDER_DEF_OLD, RENDER_DEF_NEW, 1),
    ("the-fresh-rotation-rolls", FRESH_PICK_OLD, FRESH_PICK_NEW, 1),
    ("the-window-markers-roll", WINDOW_OLD, WINDOW_NEW, 1),
    ("the-host-gate-rolls", HOST_GATE_OLD, HOST_GATE_NEW, 1),
    ("the-source-road-rolls", SOURCE_GATE_OLD, SOURCE_GATE_NEW, 1),
    ("the-gallery-road-binds-its-rolls", GALLERY_TAKE_OLD, GALLERY_TAKE_NEW, 1),
    ("the-clip-road-binds-its-rolls", CLIP_TAKE_OLD, CLIP_TAKE_NEW, 1),
    ("the-fallback-road-binds-its-rolls", FALLBACK_OLD, FALLBACK_NEW, 1),
    ("the-clock-writes-the-airing", CLOCK_OLD, CLOCK_NEW, 1),
    ("the-words-carry-the-rolls", WORDS_OLD, WORDS_NEW, 1),
    ("the-hour-view-carries-the-rolls", HOUR_VIEW_OLD, HOUR_VIEW_NEW, 1),
    ("the-slideshow-deal-helpers", PLAYLIST_DOOR_OLD, PLAYLIST_DOOR_NEW, 1),
    ("the-hot-load-deals-an-entrance", SINCE_OLD, SINCE_NEW, 1),
    ("the-deal-seed", ORDER_OLD, ORDER_NEW, 1),
    ("the-shuffle-is-dealt", SHUFFLE_OLD, SHUFFLE_NEW, 1),
    ("the-page-transitions-are-dealt", PAGE_OLD, PAGE_NEW, 1),
    ("the-answer-carries-the-deal", SEED_OLD, SEED_NEW, 1),
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
