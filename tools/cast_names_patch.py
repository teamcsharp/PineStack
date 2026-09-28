"""[cast-names] The cast have names: Dill (host), Skip (co-host), Sam (the SFX guy).

"In the system let's establish these as the following characters. Dill (Host)
/ Skip (Co-Host) / Sam (SFX guy)." and "I want to see the naming reflected
everywhere so it makes more sense than seeing host, co-host and other
impersonal names. Connect it to the props in the DJ options so i can change
the names if needed or the user can set it to custom names or have them be
custom names or even random names if desired." (operator, 2026-09-28)

What this does to app.py:
  * DEFAULT_DJ / validate_settings: host_name (Dill), cohost_name (Skip),
    sfxguy_name (Sam), each with <role>_name_mode (fixed | custom | random)
    and <role>_name_pool, plus cast_reroll_daily - all kept through the
    wholesale rebuild (host_name was a dead key; the SFX guy had none).
  * cast_name(role) / cast_names(): the one answer to "what is he called",
    by mode. Random names are rolled through System 3's dice door
    (s3_pool + s3_choice: the pool goes on the desk, the roll is recorded),
    once a station day or on the operator's button, and kept in
    data/cast_names.json so a restart keeps them.
  * dj_settings() carries the answers as host_name / cohost_name /
    sfxguy_name, so every existing reader (prompts, System 3's seats, the
    booth glass, the screenplay via booth_actor_name) says the same names.
  * booth_actor_name(): the cast's names; "The SFX Guy" handed in by an old
    road is his name now; who="host" (the operator's desk rows) reads "The
    desk", never the host's name.
  * GET /api/cast/names, POST /api/cast/names/roll.
  * overdwelt_subjects() exempts host_name / sfxguy_name too (the pair say
    "Dill" all night; it must never be ordered off its own name).
  * The SFX guy's rows (heard notes, verdicts, passages, selections, the
    director's cues, the crystal and paper casts) carry cast_name("sfxguy").
  * The DJ options: the cast box (name, mode, pool, roll button), and the
    control panel's person labels read the names.

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only. ON THE HOST (app.py is baked into the image).
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path


# --- 1. the cast's defaults and validators, before DEFAULT_DJ ----------------
_VALIDATORS = r'''# --- [cast-names] THE CAST'S NAMES, AS THE SETTINGS KEEP THEM -----------------
# Dill (host), Skip (co-host), Sam (the SFX guy): the operator's cast
# (2026-09-28). Each name has a mode in the DJ options - fixed, custom or
# random - and validate_settings() keeps all of it through its wholesale
# rebuild. cast_name() and the rolls sit beside dj_settings(), further down.
CAST_ROLES = ("host", "cohost", "sfxguy")
CAST_MODES = ("fixed", "custom", "random")
CAST_DEFAULT_NAMES = {"host": "Dill", "cohost": "Skip", "sfxguy": "Sam"}
CAST_NAME_MOST = 30
CAST_POOL_MOST = 60
# The random pool when the operator has not written one. None of the caller
# name book's seed names (CALLER_NAME_SEED has a Gus and a Grandma Lou).
CAST_NAME_POOL = (
    "Dill", "Skip", "Sam", "Rex", "Moe", "Vic", "Ray", "Hank", "Otis", "Mick",
    "Fitz", "Nell", "Dot", "Roz", "Mae", "Tess", "Bea", "Jo", "Cal", "Wes",
)


def cast_name_clean(raw: Any) -> str:
    """[cast-names] A name as the station says and prints it, or "" when it
    will not do: 1-30 printable characters, letters and digits with spaces,
    apostrophes, hyphens, full stops and ampersands between them. Nothing
    that breaks a transcript ("Name: line"), a template ({station}) or a
    tag, and no emoji."""
    name = " ".join(str(raw or "").split())
    if not 1 <= len(name) <= CAST_NAME_MOST or not name.isprintable():
        return ""
    if not any(ch.isalnum() for ch in name):
        return ""
    if any(not (ch.isalnum() or ch in " '.-&") for ch in name):
        return ""
    return name


def cast_pool_clean(raw: Any) -> list[str]:
    """[cast-names] A random pool - a list, or one string with the names
    separated by commas, semicolons or new lines - as valid names, each once
    whatever its case, sixty at most."""
    items = (raw if isinstance(raw, (list, tuple))
             else re.split(r"[,;\n]", str(raw or "")))
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        name = cast_name_clean(item)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
            if len(out) >= CAST_POOL_MOST:
                break
    return out


def cast_mode_of(raw_dj: Any, role: str) -> str:
    """[cast-names] How `role`'s name is chosen in these DJ settings: the
    stored mode - or, for settings from before the modes (or a dict that
    never went through validate_settings), custom when a name other than the
    station's own is written there, fixed otherwise."""
    raw = raw_dj if isinstance(raw_dj, dict) else {}
    key = role + "_name"
    mode = str(raw.get(key + "_mode") or "").strip().lower()
    if mode in CAST_MODES:
        return mode
    name = cast_name_clean(raw.get(key))
    return "custom" if name and name != CAST_DEFAULT_NAMES[role] else "fixed"


def cast_settings_clean(raw_dj: Any) -> dict[str, Any]:
    """[cast-names] The cast's keys of the DJ settings, validated: for host,
    cohost and sfxguy, <role>_name (the operator's text for custom - the
    station's name when it is empty or will not do), <role>_name_mode and
    <role>_name_pool; and cast_reroll_daily."""
    raw = raw_dj if isinstance(raw_dj, dict) else {}
    out: dict[str, Any] = {}
    for role in CAST_ROLES:
        key = role + "_name"
        out[key] = cast_name_clean(raw.get(key)) or CAST_DEFAULT_NAMES[role]
        out[key + "_mode"] = cast_mode_of(raw, role)
        out[key + "_pool"] = (cast_pool_clean(raw.get(key + "_pool"))
                              or list(CAST_NAME_POOL))
    out["cast_reroll_daily"] = bool(raw.get("cast_reroll_daily", True))
    return out


DEFAULT_DJ = {
    "station_name": PINE_BOX_FM,
'''

# --- 2. DEFAULT_DJ's cast keys -------------------------------------------------
_DEFAULTS = r'''    "radio_prompt_presets": {},
    # [cast-names] the cast: a name, how it is chosen (fixed / custom /
    # random) and the pool a random one is rolled from. Skip was already
    # here; the host's name was a dead key (#750) and the SFX guy had none.
    "host_name": "Dill",
    "host_name_mode": "fixed",
    "host_name_pool": list(CAST_NAME_POOL),
    "cohost_name": "Skip",
    "cohost_name_mode": "fixed",
    "cohost_name_pool": list(CAST_NAME_POOL),
    "sfxguy_name": "Sam",
    "sfxguy_name_mode": "fixed",
    "sfxguy_name_pool": list(CAST_NAME_POOL),
    "cast_reroll_daily": True,
'''

# --- 3. validate_settings keeps them --------------------------------------------
_VALIDATE_OLD = '''        "cohost_name": str(
            raw_dj.get("cohost_name") or DEFAULT_DJ["cohost_name"])[:40],
'''
_VALIDATE_NEW = '''        # [cast-names] host_name, cohost_name, sfxguy_name, their modes and
        # pools, cast_reroll_daily: validated names, never a dropped key.
        **cast_settings_clean(raw_dj),
'''

# --- 4. cast_name(), the rolls, the routes, and dj_settings() carrying them -----
_DJ_SETTINGS_OLD = '''def dj_settings() -> dict[str, Any]:
    settings = load_settings().get("dj") or dict(DEFAULT_DJ)
'''
_DJ_SETTINGS_NEW = r'''# --- [cast-names] THE CAST HAVE NAMES ------------------------------------------
# "In the system let's establish these as the following characters. Dill
# (Host) / Skip (Co-Host) / Sam (SFX guy)." ... "Connect it to the props in
# the DJ options so i can change the names if needed or the user can set it
# to custom names or have them be custom names or even random names if
# desired." (operator, 2026-09-28)
#
# cast_name(role) answers every name, by the mode the DJ options set:
#   fixed   the station's own - Dill, Skip, Sam
#   custom  the operator's text (host_name / cohost_name / sfxguy_name)
#   random  a name rolled off the character's pool (<role>_name_pool)
#           through System 3's dice door - once a station day (unless
#           cast_reroll_daily is off) or when the operator presses "roll
#           new names" - and kept in data/cast_names.json, so a restart
#           keeps it.
# dj_settings() carries the answers under host_name / cohost_name /
# sfxguy_name, so every road that already read those keys - the writing
# prompts, System 3's seats, the booth glass, the script - says the same
# name without knowing any of this exists. load_settings()["dj"] keeps what
# the operator stored (the custom text, the mode, the pool).
CAST_NAMES_PATH = data_path("cast_names.json")
CAST_ROLE_OF = {"host": "host", "dj": "host", "a": "host",
                "cohost": "cohost", "co-host": "cohost", "b": "cohost",
                "sfxguy": "sfxguy", "sfx": "sfxguy", "drop": "sfxguy",
                "third": "third", "guest": "third", "d": "third",
                "manager": "manager"}
CAST_WHO = {"host": "the host", "cohost": "the co-host",
            "sfxguy": "the SFX guy"}
# What the code called him before he had a name. A road that still hands
# one of these in for his line gets the name he goes by now.
CAST_LEGACY_SFX = ("the sfx guy", "sfx guy")
_CAST_LOCK = RLock()          # a roll (never waited on from the loop)
_CAST_LOAD_LOCK = RLock()     # the first read of the file, and nothing else
_CAST_SAVE_LOCK = RLock()     # the keeper's write
_CAST_STATE: dict[str, Any] = {"loaded": False, "rolled": {},
                               "rolling": False, "version": 0}
_CAST_MEMO: dict[int, tuple[Any, ...]] = {}   # id -> (dict, day, version, names)
_CAST_OVERLAY: list[Any] = [None]             # (settings dict, names, the copy)


# The show day a rolled name holds for turns at five in the morning - where
# the booth's own clock ends "the small hours" - not at midnight, in the
# middle of the late show.
CAST_DAY_TURNS = 5


def cast_day(now: float | None = None) -> str:
    """[cast-names] The station's show day a rolled name holds for: the local
    date, turning at CAST_DAY_TURNS o'clock."""
    at = time.time() if now is None else float(now)
    return time.strftime("%Y-%m-%d", time.localtime(at - CAST_DAY_TURNS * 3600))


def _cast_state() -> dict[str, Any]:
    """The rolled names, read off data/cast_names.json the first time they
    are asked for. A missing or broken file is no rolls yet, never an error."""
    if _CAST_STATE["loaded"]:
        return _CAST_STATE
    with _CAST_LOAD_LOCK:
        if _CAST_STATE["loaded"]:
            return _CAST_STATE
        rolled: dict[str, dict[str, Any]] = {}
        try:
            got = json.loads(CAST_NAMES_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            got = {}
        book = got.get("rolled") if isinstance(got, dict) else None
        for role, row in (book.items() if isinstance(book, dict) else ()):
            if role not in CAST_ROLES or not isinstance(row, dict):
                continue
            name = cast_name_clean(row.get("name"))
            if not name:
                continue
            try:
                at = float(row.get("at") or 0)
            except (TypeError, ValueError):
                at = 0.0
            rolled[role] = {"name": name, "day": str(row.get("day") or "")[:10],
                            "at": at, "pool": str(row.get("pool") or "")[:16]}
        _CAST_STATE["rolled"] = rolled
        _CAST_STATE["loaded"] = True
    return _CAST_STATE


def _cast_save(wait: bool = False) -> None:
    """Keep the rolled names (a temp file, then a rename) - off the caller's
    thread unless `wait`: a roll can be asked for from the event loop, and
    data/ is a network share."""
    def write() -> None:
        with _CAST_SAVE_LOCK:
            book = dict(_CAST_STATE["rolled"])
            try:
                CAST_NAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
                tmp = CAST_NAMES_PATH.with_suffix(".tmp")
                tmp.write_text(json.dumps(
                    {"rolled": book, "saved_at": round(time.time(), 3)},
                    indent=1) + "\n", encoding="utf-8")
                tmp.replace(CAST_NAMES_PATH)
            except Exception as exc:  # noqa: BLE001
                print(f"[cast-names] the rolled names were not kept: {exc}",
                      flush=True)
    if wait:
        write()
    else:
        Thread(target=write, name="cast-names-keep", daemon=True).start()


def _cast_pool(dj: dict[str, Any], role: str) -> list[str]:
    return cast_pool_clean(dj.get(role + "_name_pool")) or list(CAST_NAME_POOL)


def _cast_pool_sig(pool: list[str]) -> str:
    return hashlib.sha1("\n".join(pool).encode("utf-8")).hexdigest()[:8]


def _cast_fresh(got: dict[str, Any], dj: dict[str, Any], role: str,
                day: str) -> bool:
    """Whether a rolled name still stands: rolled today (or the daily roll
    is off), off the pool in the DJ options - or that pool still holds it."""
    name = str((got or {}).get("name") or "")
    if not name:
        return False
    if dj.get("cast_reroll_daily", True) and got.get("day") != day:
        return False
    pool = _cast_pool(dj, role)
    return (got.get("pool") == _cast_pool_sig(pool)
            or name.lower() in {n.lower() for n in pool})


def _cast_roll(role: str, dj: dict[str, Any],
               avoid: set[str]) -> tuple[str, str]:
    """One random name for `role`, through System 3's dice door: the pool goes
    on the operator's desk (POOLS1) under a key made of the pool itself - so
    the pool in the DJ options is always the one drawn from - and the roll is
    recorded. `avoid` (the rest of the cast, and a name being replaced) is
    held back while the pool has anybody else. System 3 off: the station's
    own random. Returns (the name, the pool's signature)."""
    pool = _cast_pool(dj, role)
    sig = _cast_pool_sig(pool)
    key = "cast.%s.%s" % (role, sig)
    label = "a random name for " + CAST_WHO[role]
    name = ""
    try:
        desk = [n for n in (cast_name_clean(x)
                            for x in s3_pool(key, pool, label)) if n] or pool
        left = [n for n in desk if n.lower() not in avoid] or desk
        name = cast_name_clean(s3_choice(key, left, label, tabled=False))
    except Exception:  # noqa: BLE001 - the dice never cost him his name
        name = ""
    if not name:
        name = random.choice([n for n in pool if n.lower() not in avoid] or pool)
    return name, sig


def _cast_roll_roles(dj: dict[str, Any], roles: list[str],
                     names: dict[str, str], force: bool = False,
                     wait: float = 0.0) -> dict[str, str]:
    """Roll `roles` - the stale ones, or every one the operator asked for -
    and keep the result. The caller is never held on the lock unless `wait`
    says so: a busy roll hands the names back as they were, and the next ask
    rolls. A roll that asks for the cast's names on its way through the dice
    gets them as they are (the `rolling` flag)."""
    locked = (_CAST_LOCK.acquire(timeout=wait) if wait > 0
              else _CAST_LOCK.acquire(blocking=False))
    if not locked:
        return names
    try:
        st = _cast_state()
        if st["rolling"]:
            return names
        st["rolling"] = True
        try:
            out = dict(names)
            day = cast_day()
            said = []
            for role in roles:
                prev = st["rolled"].get(role) or {}
                if not force and _cast_fresh(prev, dj, role, day):
                    out[role] = prev["name"]
                    continue
                avoid = {str(n).lower() for r, n in out.items() if r != role}
                if force and prev.get("name"):
                    avoid.add(str(prev["name"]).lower())
                name, sig = _cast_roll(role, dj, avoid)
                st["rolled"] = dict(st["rolled"], **{role: {
                    "name": name, "day": day, "at": round(time.time(), 3),
                    "pool": sig}})
                out[role] = name
                said.append("%s is %s" % (CAST_WHO[role], name))
            if said:
                st["version"] += 1
                _CAST_MEMO.clear()
                _cast_save(wait=wait > 0)
                try:
                    pipeline_log("air", "[cast-names] rolled: " + ", ".join(said))
                except Exception:  # noqa: BLE001
                    pass
            return out
        finally:
            st["rolling"] = False
    finally:
        _CAST_LOCK.release()


def _cast_settings(dj: Any = None) -> dict[str, Any]:
    """The DJ settings a name is read from: `dj` when it is one, else the
    stored settings - never anything that is not a dict."""
    if isinstance(dj, dict):
        return dj
    got = load_settings()
    raw = got.get("dj") if isinstance(got, dict) else None
    return raw if isinstance(raw, dict) else DEFAULT_DJ


def cast_names(dj: dict[str, Any] | None = None) -> dict[str, str]:
    """[cast-names] {"host", "cohost", "sfxguy"} -> the name each goes by right
    now. A random name whose day has turned (or whose pool no longer holds
    it) is rolled here, once. Memoised on the settings dict, the day and the
    rolls, so the hot road through dj_settings() is a dictionary read. Never
    raises: a name is never worth a road its line."""
    try:
        return _cast_names(_cast_settings(dj))
    except Exception:  # noqa: BLE001
        return dict(CAST_DEFAULT_NAMES)


def _cast_names(raw: dict[str, Any]) -> dict[str, str]:
    st = _cast_state()
    day = cast_day()
    memo = _CAST_MEMO.get(id(raw))
    if (memo is not None and memo[0] is raw and memo[1] == day
            and memo[2] == st["version"]):
        return dict(memo[3])
    out: dict[str, str] = {}
    stale: list[str] = []
    for role in CAST_ROLES:
        key = role + "_name"
        mode = cast_mode_of(raw, role)
        if mode == "custom":
            out[role] = cast_name_clean(raw.get(key)) or CAST_DEFAULT_NAMES[role]
        elif mode == "random":
            prev = st["rolled"].get(role) or {}
            out[role] = str(prev.get("name") or "") or CAST_DEFAULT_NAMES[role]
            if not _cast_fresh(prev, raw, role, day):
                stale.append(role)
        else:
            out[role] = CAST_DEFAULT_NAMES[role]
    if stale:
        out = _cast_roll_roles(raw, stale, out)
        if any(not _cast_fresh(st["rolled"].get(r) or {}, raw, r, day)
               for r in stale):
            return out                  # the dice were busy: ask again next time
    if len(_CAST_MEMO) > 8:
        _CAST_MEMO.clear()
    _CAST_MEMO[id(raw)] = (raw, day, st["version"], dict(out))
    return out


def cast_name(role: str, dj: dict[str, Any] | None = None) -> str:
    """[cast-names] The name one character goes by right now: host (Dill),
    cohost (Skip) and sfxguy (Sam) by their modes; third - the guest or the
    third presenter, "" for a two-hander; manager - "" when unnamed. Seat
    words are understood too (dj, drop, sfx, guest, A, B, D)."""
    r = CAST_ROLE_OF.get(str(role or "").strip().lower(), "")
    if r in CAST_ROLES:
        return cast_names(dj)[r]
    if r in ("third", "manager"):
        try:
            d = dj if isinstance(dj, dict) else dj_settings()
            return str(d.get(r + "_name") or "").strip() if isinstance(d, dict) else ""
        except Exception:  # noqa: BLE001
            return ""
    return ""


def cast_names_overlay(dj: dict[str, Any]) -> dict[str, Any]:
    """[cast-names] The DJ settings with host_name / cohost_name / sfxguy_name
    set to the names the characters go by right now: the same dict when they
    already are, one cached copy per settings dict and cast otherwise."""
    try:
        names = cast_names(dj)
    except Exception:  # noqa: BLE001 - a name is never worth the settings
        return dj
    want = {role + "_name": name for role, name in names.items()}
    if all(dj.get(k) == v for k, v in want.items()):
        return dj
    memo = _CAST_OVERLAY[0]
    if memo is not None and memo[0] is dj and memo[1] == want:
        return memo[2]
    out = dict(dj)
    out.update(want)
    _CAST_OVERLAY[0] = (dj, want, out)
    return out


def cast_names_state() -> dict[str, Any]:
    """[cast-names] GET /api/cast/names: each character's name now, its mode,
    the operator's custom text, the pool and the last roll."""
    raw = _cast_settings()
    names = cast_names(raw)
    st = _cast_state()
    return {
        "names": dict(names), "day": cast_day(),
        "daily": bool(raw.get("cast_reroll_daily", True)),
        "defaults": dict(CAST_DEFAULT_NAMES),
        "keys": {role: role + "_name" for role in CAST_ROLES},
        "cast": {role: {"name": names[role],
                        "mode": cast_mode_of(raw, role),
                        "custom": str(raw.get(role + "_name") or ""),
                        "pool": _cast_pool(raw, role),
                        "rolled": dict(st["rolled"].get(role) or {})}
                 for role in CAST_ROLES},
        "third": str(raw.get("third_name") or ""),
    }


def cast_roll_now(roles: Any = None) -> dict[str, Any]:
    """[cast-names] The DJ options' "roll new names": everybody set to random
    (or those of them named in `roles`) gets a fresh name off the pool now -
    a different one from the name they had, while the pool has another."""
    raw = _cast_settings()
    asked = roles if isinstance(roles, list) and roles else list(CAST_ROLES)
    want = [r for r in CAST_ROLES if r in asked and cast_mode_of(raw, r) == "random"]
    if not want:
        out = cast_names_state()
        out.update(rolled=[], said=(
            "Nobody is set to a random name - set the host, the co-host or "
            "the SFX guy to random in the DJ options first."))
        return out
    version = _cast_state()["version"]
    after = _cast_roll_roles(raw, want, cast_names(raw), force=True, wait=5.0)
    out = cast_names_state()
    if _cast_state()["version"] == version:
        out.update(rolled=[], said="The dice were busy - roll again.")
        return out
    out.update(rolled=want, said="Rolled: " + ", ".join(
        "%s is %s" % (CAST_WHO[r], after[r]) for r in want) + ".")
    return out


@app.get("/api/cast/names")
async def cast_names_api(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[cast-names] Who the cast are right now, and how each name is chosen."""
    require_read_auth(authorization)
    return await asyncio.to_thread(cast_names_state)


@app.post("/api/cast/names/roll")
async def cast_names_roll_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[cast-names] Roll new names for everybody set to random - the button in
    the DJ options. Body, optional: {"roles": ["host", "cohost", "sfxguy"]}."""
    require_auth(authorization)
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - no body is "everybody"
        payload = {}
    roles = payload.get("roles") if isinstance(payload, dict) else None
    return await asyncio.to_thread(cast_roll_now, roles)


def dj_settings() -> dict[str, Any]:
    # [cast-names] with each character's name as the air uses it right now.
    settings = cast_names_overlay(load_settings().get("dj") or dict(DEFAULT_DJ))
'''

# --- 5. booth_actor_name: the cast's names ---------------------------------------
_BOOTH_OLD = '''    if str(name or "").strip():
        return str(name).strip()
    seat = str(who or "").strip().lower()
    dj = dj_settings()
    if seat in ("dj", "host"):
        return str(dj.get("host_name") or "Host")
    if seat == "cohost":
        return str(dj.get("cohost_name") or "Co-host")
    if seat in ("third", "guest"):
        guest = active_guest()
        return str(guest.get("name") or dj.get("third_name") or "Guest")
    if seat in ("drop", "sfx"):
        return "The SFX Guy"
'''
_BOOTH_NEW = '''    seat = str(who or "").strip().lower()
    given = str(name or "").strip()
    # [cast-names] "The SFX Guy" was what the code called him, not a name
    # anybody gave him: a road that still hands it in gets the name he goes
    # by now (cast_name - Sam, or the operator's).
    if given and not (seat in ("drop", "sfx", "sfxguy")
                      and given.lower() in CAST_LEGACY_SFX):
        return given
    dj = dj_settings()
    if seat == "host":
        # [cast-names] who="host" is the operator's own desk row - a request,
        # a call landing, a news break, what he typed to the DJ - never the
        # host in the booth, so it does not take the host's name.
        return "The desk"
    if seat == "dj":
        return str(dj.get("host_name") or "") or cast_name("host")
    if seat == "cohost":
        return str(dj.get("cohost_name") or "") or cast_name("cohost")
    if seat in ("third", "guest"):
        guest = active_guest()
        return str(guest.get("name") or dj.get("third_name") or "Guest")
    if seat in ("drop", "sfx", "sfxguy"):
        return str(dj.get("sfxguy_name") or "") or cast_name("sfxguy")
'''

EDITS = [
    ("cast-validators", 'DEFAULT_DJ = {\n    "station_name": PINE_BOX_FM,\n', _VALIDATORS, 1),
    ("cast-defaults", '    "radio_prompt_presets": {},\n    "cohost_name": "Skip",\n', _DEFAULTS, 1),
    ("cast-validate", _VALIDATE_OLD, _VALIDATE_NEW, 1),
    ("cast-helper", _DJ_SETTINGS_OLD, _DJ_SETTINGS_NEW, 1),
    ("cast-booth-name", _BOOTH_OLD, _BOOTH_NEW, 1),

    # --- the cast's own names are never an over-dwelt subject ----------------
    # host_name was a dead key, so "Dill" was never exempt; now the pair say
    # it all night and the dwell counter would order them off their own name.
    ("cast-dwell-exempt",
     '    exempt = {w.lower() for field in ("station_name", "cohost_name",\n'
     '                                      "third_name", "manager_name")\n',
     '    exempt = {w.lower() for field in ("station_name", "cohost_name",\n'
     '                                      "third_name", "manager_name",\n'
     '                                      "host_name", "sfxguy_name")   # [cast-names]\n', 1),

    # --- the SFX guy's rows carry his name ------------------------------------
    ("cast-sfx-heard",
     '                line=str(row["id"]), text=sample_name,\n                speaker="The SFX Guy")\n',
     '                line=str(row["id"]), text=sample_name,\n                speaker=cast_name("sfxguy"))   # [cast-names]\n', 1),
    ("cast-sfx-interjection",
     '                          text=str(row.get("text") or ""),\n                          speaker="The SFX Guy")\n',
     '                          text=str(row.get("text") or ""),\n                          speaker=cast_name("sfxguy"))   # [cast-names]\n', 1),
    ("cast-sfx-verdict",
     '            await dj_speak("reply", None, line=line, who="drop",\n                           voice=dj["drop_voice"], name="The SFX Guy",\n',
     '            await dj_speak("reply", None, line=line, who="drop",\n                           voice=dj["drop_voice"], name=cast_name("sfxguy"),   # [cast-names]\n', 1),
    ("cast-sfx-passage",
     '        await dj_speak("interject", None, line=seed["text"], who="drop",\n                       voice=dj["drop_voice"], name="The SFX Guy",\n',
     '        await dj_speak("interject", None, line=seed["text"], who="drop",\n                       voice=dj["drop_voice"], name=cast_name("sfxguy"),   # [cast-names]\n', 1),
    ("cast-sfx-selection",
     '        said = await dj_speak("station_id", None, line=text, who="drop",\n                              voice=dj["drop_voice"], name="The SFX Guy",\n',
     '        said = await dj_speak("station_id", None, line=text, who="drop",\n                              voice=dj["drop_voice"], name=cast_name("sfxguy"),   # [cast-names]\n', 1),
    ("cast-sfx-cues",
     '    cues = []\n    for after in range(every - 1, turn_count, every):\n'
     '        cues.append({"after": after, "seat": "board", "who": "The SFX Guy",\n'
     '                     "kind": "sfx", "text": "A stinger is scheduled here; the board chooses the clip at assembly."})\n'
     '    if turn_count >= guy_every:\n'
     '        cues.append({"after": min(turn_count - 1, guy_every - 1), "seat": "drop",\n'
     '                     "who": "The SFX Guy", "kind": "sfxguy",\n'
     '                     "text": "The SFX Guy has a voiced drop scheduled at this beat."})\n',
     '    cues = []\n    guy = cast_name("sfxguy")                   # [cast-names] his name on his cues\n'
     '    for after in range(every - 1, turn_count, every):\n'
     '        cues.append({"after": after, "seat": "board", "who": guy,\n'
     '                     "kind": "sfx", "text": "A stinger is scheduled here; the board chooses the clip at assembly."})\n'
     '    if turn_count >= guy_every:\n'
     '        cues.append({"after": min(turn_count - 1, guy_every - 1), "seat": "drop",\n'
     '                     "who": guy, "kind": "sfxguy",\n'
     '                     "text": guy + " has a voiced drop scheduled at this beat."})\n', 1),
    ("cast-crystal-cast",
     '        "cast": {"host": dj.get("dj_name") or "Host",\n'
     '                 "cohost": dj.get("cohost_name") or "Skip",\n'
     '                 "sfxguy": dj.get("sfx_name") or "The SFX Guy",\n',
     '        # [cast-names] dj_name and sfx_name were never keys: the cast\'s names\n'
     '        "cast": {"host": cast_name("host", dj),\n'
     '                 "cohost": cast_name("cohost", dj),\n'
     '                 "sfxguy": cast_name("sfxguy", dj),\n', 1),
    ("cast-crystal-labels",
     '              "drop": "The SFX Guy", "caller": "Callers"}\n',
     '              "drop": cast_name("sfxguy", dj), "caller": "Callers"}   # [cast-names]\n', 1),
    ("cast-paper-names",
     '        "sfx": "The SFX Guy"}\n    m["sponsors"]',
     '        "sfx": cast_name("sfxguy")}                 # [cast-names]\n    m["sponsors"]', 1),

    # --- the DJ options: the cast box ------------------------------------------
    ("cast-ui-box",
     '        <input id="djStationName" placeholder="Pine Box FM">\n',
     r'''        <input id="djStationName" placeholder="Pine Box FM">

        <!-- [cast-names] THE CAST. What the station calls each of them - on
             the air, in the script and on every screen: the station's own
             name, the operator's, or one rolled off a pool (System 3's dice,
             once a day or on the button). -->
        <div id="djCast" style="border:1px solid #2a2f3a;border-radius:8px;
                    padding:8px;margin:10px 0">
          <div style="font-weight:600;margin-bottom:2px">
            <span data-pine-icon="c:group"></span> The cast</div>
          <div class="muted" style="font-size:11px;margin-bottom:6px">
            What the station calls each of them - on the air, in the script
            and on every screen. Fixed keeps the station's name, custom is the
            name you type, random rolls one off the names you list.</div>
          <div class="row" style="flex-wrap:wrap;gap:6px;align-items:center">
            <label for="djHostName" style="flex:0 0 72px;margin:0">Host</label>
            <select id="djHostNameMode" onchange="castModeShow()"
                    aria-label="How the host's name is chosen">
              <option value="fixed">fixed - Dill</option>
              <option value="custom">custom</option>
              <option value="random">random</option>
            </select>
            <input id="djHostName" maxlength="30" placeholder="Dill"
                   style="flex:1;min-width:110px">
            <span id="djHostNameNow" class="muted" style="font-size:11px"></span>
            <input id="djHostNamePool" style="flex:1 1 100%"
                   placeholder="names to roll from, separated by commas"
                   aria-label="The names the host's random name is rolled from">
          </div>
          <div class="row" style="flex-wrap:wrap;gap:6px;align-items:center">
            <label for="djCohostName" style="flex:0 0 72px;margin:0">Co-host</label>
            <select id="djCohostNameMode" onchange="castModeShow()"
                    aria-label="How the co-host's name is chosen">
              <option value="fixed">fixed - Skip</option>
              <option value="custom">custom</option>
              <option value="random">random</option>
            </select>
            <input id="djCohostName" maxlength="30" placeholder="Skip"
                   style="flex:1;min-width:110px">
            <span id="djCohostNameNow" class="muted" style="font-size:11px"></span>
            <input id="djCohostNamePool" style="flex:1 1 100%"
                   placeholder="names to roll from, separated by commas"
                   aria-label="The names the co-host's random name is rolled from">
          </div>
          <div class="row" style="flex-wrap:wrap;gap:6px;align-items:center">
            <label for="djSfxguyName" style="flex:0 0 72px;margin:0">SFX guy</label>
            <select id="djSfxguyNameMode" onchange="castModeShow()"
                    aria-label="How the SFX guy's name is chosen">
              <option value="fixed">fixed - Sam</option>
              <option value="custom">custom</option>
              <option value="random">random</option>
            </select>
            <input id="djSfxguyName" maxlength="30" placeholder="Sam"
                   style="flex:1;min-width:110px">
            <span id="djSfxguyNameNow" class="muted" style="font-size:11px"></span>
            <input id="djSfxguyNamePool" style="flex:1 1 100%"
                   placeholder="names to roll from, separated by commas"
                   aria-label="The names the SFX guy's random name is rolled from">
          </div>
          <label class="toggle" title="On: a random name holds for the show day
and a new one is rolled the first time the station asks after five in the
morning. Off: it holds until you press Roll new names.">
            <input id="djCastRerollDaily" type="checkbox">
            Roll random names again every day
          </label>
          <div class="row" style="gap:6px;align-items:center;margin-top:4px">
            <button id="djCastRoll" type="button" onclick="castRollNames()"
                    title="Save the cast and give everybody set to random a new name now">
              <span data-pine-icon="c:shuffle"></span> Roll new names</button>
            <span id="djCastStatus" class="muted" style="font-size:11px"></span>
          </div>
        </div>
''', 1),
    ("cast-ui-cohost-field",
     '        <label>Co-host name</label>\n        <input id="djCohostName" placeholder="Skip">\n        <label>Co-host personality</label>\n',
     '        <!-- [cast-names] the co-host\'s name lives in the cast box above -->\n        <label>Co-host personality</label>\n', 1),
    ("cast-ui-load",
     '    document.getElementById("djCohostName").value = dj.cohost_name || "";\n',
     '    document.getElementById("djCohostName").value = dj.cohost_name || "";\n    castFill(dj);                                          // [cast-names]\n', 1),
    ("cast-ui-save",
     '      cohost_name: document.getElementById("djCohostName").value.trim(),\n',
     '      cohost_name: document.getElementById("djCohostName").value.trim(),\n      ...castCollect(),                                    // [cast-names]\n', 1),
    ("cast-ui-js",
     'async function djSaveSettings() {\n',
     r'''/* [cast-names] THE CAST, IN THE DJ OPTIONS AND IN EVERY LABEL.
   Each character has a name, a way it is chosen - fixed (the station's own:
   Dill, Skip, Sam), custom (the text typed here) or random (rolled off the
   pool through System 3's dice, once a day or on the button) - and a pool.
   castName() is what the panel's labels print: the name the station
   answers on /api/dj (dj_names), else the station's own. */
const CAST_FIELDS = [
  {role: "host", id: "djHostName", def: "Dill"},
  {role: "cohost", id: "djCohostName", def: "Skip"},
  {role: "sfxguy", id: "djSfxguyName", def: "Sam"},
];
const CAST_KEY = {dj: "host", host: "host", a: "host", cohost: "cohost",
  "co-host": "cohost", b: "cohost", sfxguy: "sfx", sfx: "sfx", drop: "sfx",
  third: "third", guest: "guest", d: "third"};
function castName(role, fallback) {
  const key = CAST_KEY[String(role || "").toLowerCase()] || String(role || "");
  const state = (typeof djLastState !== "undefined" && djLastState) || {};
  const names = state.dj_names || {};
  let got = String(names[key] || "").trim();
  if (!got && key === "third") got = String(names.guest || "").trim();
  if (got) return got;
  if (fallback !== undefined) return fallback;
  return ({host: "Dill", cohost: "Skip", sfx: "Sam"})[key] || "";
}
function castFill(dj) {
  for (const f of CAST_FIELDS) {
    const key = f.role + "_name";
    const mode = document.getElementById(f.id + "Mode");
    const name = document.getElementById(f.id);
    const pool = document.getElementById(f.id + "Pool");
    if (mode) mode.value = ["fixed", "custom", "random"].includes(dj[key + "_mode"])
      ? dj[key + "_mode"] : "fixed";
    if (name) name.value = dj[key] || "";
    if (pool) pool.value = (dj[key + "_pool"] || []).join(", ");
  }
  const daily = document.getElementById("djCastRerollDaily");
  if (daily) daily.checked = dj.cast_reroll_daily !== false;
  castModeShow();
  castNamesPaint();
}
function castCollect() {
  const out = {};
  for (const f of CAST_FIELDS) {
    const key = f.role + "_name";
    const mode = document.getElementById(f.id + "Mode");
    const name = document.getElementById(f.id);
    const pool = document.getElementById(f.id + "Pool");
    if (mode) out[key + "_mode"] = mode.value || "fixed";
    if (name) out[key] = name.value.trim() || f.def;
    if (pool) out[key + "_pool"] = pool.value.split(/[,;\n]/)
      .map((s) => s.trim()).filter(Boolean);
  }
  const daily = document.getElementById("djCastRerollDaily");
  if (daily) out.cast_reroll_daily = daily.checked;
  return out;
}
function castModeShow() {
  for (const f of CAST_FIELDS) {
    const mode = (document.getElementById(f.id + "Mode") || {}).value || "fixed";
    const name = document.getElementById(f.id);
    const pool = document.getElementById(f.id + "Pool");
    if (name) name.disabled = mode !== "custom";
    if (pool) pool.style.display = mode === "random" ? "" : "none";
  }
}
async function castNamesPaint(got) {
  try { got = got || await api("/api/cast/names"); } catch (err) { return; }
  const cast = (got && got.cast) || {};
  for (const f of CAST_FIELDS) {
    const c = cast[f.role] || {};
    const now = document.getElementById(f.id + "Now");
    if (now) now.textContent = c.name ? "on air as " + c.name
      + (c.mode === "random" && c.rolled && c.rolled.day
         ? " (rolled " + c.rolled.day + ")" : "") : "";
  }
  const host = document.getElementById("djHostLabel");
  if (host && cast.host && cast.host.name) host.textContent = cast.host.name;
  const cohost = document.getElementById("djCohostLabel");
  if (cohost && cast.cohost && cast.cohost.name) cohost.textContent = cast.cohost.name;
}
async function castRollNames() {
  const status = document.getElementById("djCastStatus");
  if (status) status.textContent = "rolling...";
  try {
    // The form's modes and pools are what the operator is looking at, so
    // they are saved first - the roll reads the stored settings.
    const settings = await api("/api/settings");
    if (settings.voice_out) delete settings.voice_out.ha_token;
    settings.dj = Object.assign({}, settings.dj, castCollect());
    await api("/api/settings", {method: "PUT", body: JSON.stringify(settings)});
    const got = await api("/api/cast/names/roll", {method: "POST", body: "{}"});
    if (status) status.textContent = got.said || "";
    castNamesPaint(got);
  } catch (error) { if (status) status.textContent = error.message; }
}

async function djSaveSettings() {
''', 1),

    # --- the control panel's person labels read the names ------------------------
    ("cast-ui-voice-host",
     'title="The voice engine the whole cast renders on - click to switch">\U0001f399 Host<span\n',
     'title="The voice engine the whole cast renders on - click to switch">\U0001f399 <span id="djHostLabel">Host</span><span\n', 1),
    ("cast-ui-voice-cohost",
     '          \U0001f399 Co-host\n          <select id="djCohostVoice" onchange="djSetVoices()"></select>\n',
     '          \U0001f399 <span id="djCohostLabel">Co-host</span>\n          <select id="djCohostVoice" onchange="djSetVoices()"></select>\n', 1),
    ("cast-ui-booth-room",
     '    {who: "dj", name: dj.host || "host"},\n    {who: "cohost", name: dj.cohost || "cohost"},\n',
     '    {who: "dj", name: dj.host || castName("host")},          // [cast-names]\n    {who: "cohost", name: dj.cohost || castName("cohost")},\n', 1),
    ("cast-ui-booth-sfx",
     '  cast.push({who: "sfx", name: dj.sfx || "The SFX Guy"});\n',
     '  cast.push({who: "sfx", name: dj.sfx || castName("sfx")});   // [cast-names]\n', 1),
    ("cast-ui-feed-who",
     '    const who = el("b", "", (line.name || ROLE[line.who] || "Booth") + " ");\n',
     '    const who = el("b", "", (line.name || castName(line.who, "")         // [cast-names]\n                             || ROLE[line.who] || "Booth") + " ");\n', 1),
    ("cast-ui-lock-voice",
     '              + (line.who === "cohost" ? "co-host" : "host") + " voice"\n',
     '              + (line.who === "cohost" ? "co-host" : "host") + " voice ("   // [cast-names]\n'
     '              + castName(line.who === "cohost" ? "cohost" : "host") + ")"\n', 1),
    ("cast-ui-selection",
     '      const send = el("button", "", icon + " " + label);\n',
     '      const send = el("button", "", icon + " " + (({host: castName("host"),      // [cast-names]\n        cohost: castName("cohost"), drop: castName("sfx")})[target] || label));\n', 1),
    ("cast-ui-3d-cast",
     '    const label = {dj: names.host, cohost: names.cohost, third: names.third,\n',
     '    const label = {dj: names.host, cohost: names.cohost, third: names.third,\n                   sfx: names.sfx,                              // [cast-names]\n', 1),
    ("cast-ui-desk-voices",
     '  deskRow("host (DJ)", settings.dj.voice,\n',
     '  deskRow(castName("host") + " (host)", settings.dj.voice,        // [cast-names]\n', 1),
    ("cast-ui-desk-cohost",
     '  deskRow("co-host", settings.dj.cohost_voice,\n',
     '  deskRow(castName("cohost") + " (co-host)", settings.dj.cohost_voice,   // [cast-names]\n', 1),
    ("cast-ui-desk-sfx",
     '  deskRow("the SFX guy", settings.dj.drop_voice,\n',
     '  deskRow(castName("sfx") + " (SFX guy)", settings.dj.drop_voice,  // [cast-names]\n', 1),
    ("cast-ui-glass",
     '          const wb = el("span", "", GLASS_WHO_LABEL[gwho] || gwho);\n',
     '          const wb = el("span", "", castName(gwho === "board" ? "sfx" : gwho, "")   // [cast-names]\n            || GLASS_WHO_LABEL[gwho] || gwho);\n', 1),
    ("cast-ui-said-who",
     '      const who = el("b", "", (r.who === "cohost" ? "Skip " : "DJ "));\n',
     '      const who = el("b", "", castName(r.who === "cohost" ? "cohost" : "host") + " ");   // [cast-names]\n', 1),
    ("cast-ui-chat-who",
     '      : (line.name ? line.name + " " : "DJ ");\n',
     '      : ((line.name || castName(line.who, "") || "DJ") + " ");   // [cast-names]\n', 1),
    ("cast-ui-paper-who",
     '  const book = {dj: "HOST", cohost: "CO-HOST", caller: "CALLER",\n                board: "SFX", drop: "SFX GUY", third: "GUEST"};\n',
     '  const book = {dj: castName("host"), cohost: castName("cohost"),   // [cast-names]\n                caller: "CALLER", board: "SFX", drop: castName("sfx"),\n                third: castName("third", "GUEST")};\n', 1),
]


def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
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
    edits = plan(text)
    if applied == len(edits):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in edits:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    assert "\r" not in text
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    try:
        shutil.copymode(str(path), tmp)
    except OSError:
        pass
    os.replace(tmp, path)
    return 0


def main(argv):
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if do_apply:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    total = len(plan(text))
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, total))
        return 1
    if applied == total:
        print("already applied (%d edits)" % total)
        return 2
    print("ready: %d edits, %d already in" % (total, applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
