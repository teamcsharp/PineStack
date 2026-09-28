"""[cast-names] Round two: the names reach the personas, Sam's own writers, the
banks and the phone line.

Applies ON TOP OF tools/cast_names_patch.py (it anchors on text that tool
leaves in place, never inside the text it inserted, so both tools' --check
keep answering "applied" after both are in):

  1. PERSONAS FOLLOW THE NAME. dj_settings() hands every writer the personas
     with the role's default name (whole word, capitalised) spoken as the name
     it goes by now - "You are Skip, the co-host" reads "You are Rex, the
     co-host" while the co-host is Rex. Only in that role's persona, only when
     the names differ; the operator's stored text is never rewritten, and
     "the host" (the owner) is left alone.
  2. SAM BY NAME. His writers name him: the verdict prompt, "the board joins
     in" shape, the three banter angles, the cold-read passage, the flow
     instruction, the station-ID brew, the news take, the reaction and the
     warp. (director.py's beat is tools/cast_names2_modules_patch.py; this
     tool hands director.py cast_name.)
  3. STALE NAMES IN BANKS. Banked rows carry the names they were written under
     (row["cast_names"]: shelf_put stamps it, the rename desk stamps what it
     finds unstamped). A row whose recorded words say a name the cast no
     longer goes by is held off the air by dialogue_row_ready (beside #1239's
     phrase gate), says why (row["cast_stale"]), and the RENAME DESK
     re-records just those lines with the names changed and swaps words and
     takes together (entry["cast_rename"] -> swap). The recast desk (#1215)
     cannot do this: its shadow is keyed to each take's own text, it compares
     voices only, and its swap never changes the words - so this desk rides
     the same road beside it (prep_render_line, the same rest and line budget,
     prep_should_stop between lines, the keeper's clock). Gold bars and the
     SFX guy's banked lines have no re-record road: one that says a gone name
     is held back.
  4. CALLER NAMES never equal a cast member's (the whole name or its first
     word): caller_names(), the name book's draw, the redraw in
     conjure_caller and the regulars' pick. The names editor still sees the
     dictionary as kept (caller_names_raw).

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only. ON THE HOST, after tools/cast_names_patch.py.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path


# --- 1 + 3 + 4: the helpers, after dj_settings() ------------------------------
_HELPERS_OLD = '    return system2_settings_for_work(settings) if globals().get("system2_settings_for_work") else settings\n'
_HELPERS_NEW = r'''    settings = cast_personas_follow(settings)   # [cast-names] the personas speak the names
    return system2_settings_for_work(settings) if globals().get("system2_settings_for_work") else settings


# --- [cast-names] THE PERSONAS SPEAK THE NAMES ------------------------------------
# "any persona/prompt that names a cast member by their default name must speak
# the EFFECTIVE name" (2026-09-28). The co-host's persona opens "You are Skip,
# the co-host on ..." - so while the co-host is Rex, every prompt that carries
# it has to say Rex. It is done where every writer reads its persona, in
# dj_settings(): the role's own default name, whole word and capitalised, is
# spoken as the name it goes by now - in that role's persona only, and only
# when the two differ. The operator's stored text is never rewritten
# (load_settings()["dj"] keeps it and the persona editor reads that), and "the
# host" - the owner, in the station's own personas - is not a name and is left
# alone.
CAST_PERSONA_OF = {"host": "persona", "cohost": "cohost_persona"}
_CAST_PERSONA_MEMO: list[Any] = [None]        # (settings dict, the copy)


def cast_rename_text(text: Any, mapping: dict[str, str] | None) -> str:
    """[cast-names] `text` with each old name in `mapping` - whole word, as
    written (capitalised) - replaced by its new one. One pass, so two names
    that trade places trade cleanly."""
    said = str(text or "")
    pairs = {str(o): str(n) for o, n in (mapping or {}).items()
             if str(o or "") and str(n or "") and str(o) != str(n)}
    if not said or not pairs:
        return said
    rx = re.compile(r"\b(" + "|".join(re.escape(o) for o in sorted(pairs, key=len, reverse=True)) + r")\b")
    return rx.sub(lambda m: pairs[m.group(1)], said)


def cast_persona(role: str, text: Any, name: str = "") -> str:
    """[cast-names] A role's persona as a prompt reads it: the role's default
    name spoken as the name the character goes by now."""
    default = CAST_DEFAULT_NAMES.get(str(role or ""), "")
    now = str(name or "") or cast_name(role)
    if not default or not now or now == default:
        return str(text or "")
    return cast_rename_text(text, {default: now})


def cast_personas_follow(dj: dict[str, Any]) -> dict[str, Any]:
    """[cast-names] The DJ settings with each cast persona following its
    name (above). The same dict when nothing changes; one cached copy per
    settings dict otherwise."""
    memo = _CAST_PERSONA_MEMO[0]
    if memo is not None and memo[0] is dj:
        return memo[1]
    out = dj
    try:
        for role, key in CAST_PERSONA_OF.items():
            text = dj.get(key)
            if not isinstance(text, str) or not text:
                continue
            said = cast_persona(role, text, str(dj.get(role + "_name") or ""))
            if said != text:
                if out is dj:
                    out = dict(dj)
                out[key] = said
    except Exception:  # noqa: BLE001 - a persona is never worth the settings
        out = dj
    _CAST_PERSONA_MEMO[0] = (dj, out)
    return out


# --- [cast-names] A CALLER IS NEVER A CAST MEMBER ----------------------------------
def cast_taken_names() -> frozenset[str]:
    """[cast-names] The names a caller may not ring in under, lower-cased: the
    host's, the co-host's, the SFX guy's - and the third seat's while it is
    filled."""
    try:
        taken = {str(n).strip().lower() for n in cast_names().values() if str(n).strip()}
        third = str(cast_name("third") or "").strip().lower()
        if third:
            taken.add(third)
        return frozenset(taken)
    except Exception:  # noqa: BLE001
        return frozenset()


def cast_name_taken(name: Any, taken: Any = None) -> bool:
    """[cast-names] Whether `name` is a cast member's - the whole name, or its
    first word: a stranger called Skip, or Skip Johnson, on the line with Skip
    in the booth is two people nobody listening can tell apart."""
    said = " ".join(str(name or "").split()).lower()
    if not said:
        return False
    names = cast_taken_names() if taken is None else taken
    return said in names or said.split(" ", 1)[0] in names


# --- [cast-names] THE MODULES THAT WRITE ABOUT THE CAST ASK FOR THEIR NAMES ---
try:
    import director as _cast_director
    _cast_director.CAST_NAME = cast_name       # its "sfx" beat names him
except Exception:  # noqa: BLE001 - the director says Sam on its own
    pass


# --- [cast-names] STALE NAMES IN THE BANK -----------------------------------------
# With names rolled once a show day, a round banked under yesterday's names
# says yesterday's names. So a bank remembers the names it was written under
# (row["cast_names"]: shelf_put stamps it; the rename desk stamps any row it
# finds without one, with the names in force when it first sees it), and a
# banked row whose recorded words say a name the cast no longer goes by does
# not air as it is: dialogue_row_ready holds it (cast_names_row_blocked, beside
# #1239's phrase gate), the row says why (row["cast_stale"]), and the rename
# desk re-records just the lines that say it, with the names changed, then
# swaps words and takes in one dict operation - after which it airs again.
#
# Why not through the recast desk (#1215) itself: its shadow is keyed to each
# take's OWN text (open_round -> key_fn(take["text"], new voice)),
# stale_takes() only ever compares voices, and swap_round()/swap_read() never
# touch the words - a rename through it would put new-name audio under
# old-name words, and its next sweep would cancel a shadow whose voices had not
# moved. So this desk keeps its own shadow (entry["cast_rename"]) beside the
# recast desk's and rides the same road: prep_render_line, the same rest, the
# same line budget, prep_should_stop() between every line, the keeper's clock.
# A swap here drops an open voice shadow on the same row (the recast desk
# reopens it from the new words on its next sweep), and a voice swap there
# makes this desk reopen in the new voice - they never fight over one take.
#
# The line banks that are not rounds or reads - the gold bars, the SFX guy's
# banked lines - have no road that re-records changed words; one that says a
# gone name is held back (cast_names_line_stale) and ages out as it would.
CAST_STAMP_KEY = "cast_names"
CAST_STALE_KEY = "cast_stale"
CAST_RENAME_KEY = "cast_rename"
CAST_RENAME_DONE_KEY = "cast_rename_done"
CAST_RENAME_REST = 4.0
CAST_RENAME_LINES_PER_TICK = 2
CAST_RENAME_KEEP_OLD_S = 3600.0      # the old clips stay protected this long
CAST_HISTORY_PATH = data_path("cast_names_history.json")
CAST_HISTORY_MOST = 40
CAST_READ_SEAT = {"ad": "dj", "station_id": "drop"}
_CAST_HISTORY: dict[str, Any] = {"loaded": False, "seen": {}}
_CAST_HISTORY_LOCK = RLock()
_CAST_GONE_MEMO: list[Any] = [None]  # (names key, history size, {role: [gone]})
_CAST_RENAME_TICK: dict[str, Any] = {"at": 0.0, "stamped": 0, "opened": 0,
                                     "lines": 0, "swaps": 0, "held": 0, "why": ""}


def _cast_key(names: Any) -> str:
    got = names if isinstance(names, dict) else {}
    return "|".join("%s=%s" % (r, str(got.get(r) or "")) for r in CAST_ROLES)


def _cast_history() -> dict[str, list[str]]:
    """Every name each character has gone by (data/cast_names_history.json),
    read once. The guess for a line bank row that carries no stamp."""
    if not _CAST_HISTORY["loaded"]:
        with _CAST_HISTORY_LOCK:
            if not _CAST_HISTORY["loaded"]:
                seen: dict[str, list[str]] = {}
                try:
                    got = json.loads(CAST_HISTORY_PATH.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001 - no file is no names gone by
                    got = {}
                book = got.get("seen") if isinstance(got, dict) else None
                for role in CAST_ROLES:
                    rows = (book or {}).get(role) if isinstance(book, dict) else None
                    seen[role] = [n for n in (cast_name_clean(x) for x in (rows or [])
                                              if isinstance(rows, list)) if n][-CAST_HISTORY_MOST:]
                _CAST_HISTORY["seen"] = seen
                _CAST_HISTORY["loaded"] = True
    return _CAST_HISTORY["seen"]


def cast_history_note(names: dict[str, str] | None = None) -> bool:
    """Remember the names in force (the keeper's clock calls this). True
    when one was new - and then the book is written, off the caller's thread."""
    now = names or cast_names()
    seen = _cast_history()
    changed = False
    with _CAST_HISTORY_LOCK:
        for role in CAST_ROLES:
            name = str(now.get(role) or "")
            rows = seen.setdefault(role, [])
            if name and name not in rows:
                rows.append(name)
                del rows[:-CAST_HISTORY_MOST]
                changed = True
        snap = {r: list(v) for r, v in seen.items()}
    if changed:
        def write() -> None:
            try:
                CAST_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
                tmp = CAST_HISTORY_PATH.with_suffix(".tmp")
                tmp.write_text(json.dumps({"seen": snap, "saved_at": round(time.time(), 3)},
                                          indent=1) + "\n", encoding="utf-8")
                tmp.replace(CAST_HISTORY_PATH)
            except Exception as exc:  # noqa: BLE001
                print(f"[cast-names] the names book was not kept: {exc}", flush=True)
        Thread(target=write, name="cast-names-history", daemon=True).start()
    return changed


def _cast_gone(now: dict[str, str]) -> dict[str, list[str]]:
    """Per role, the names it has gone by that nobody goes by now (its
    default and its history). Memoised on the names and the book's size."""
    seen = _cast_history()
    size = sum(len(v) for v in seen.values())
    key = _cast_key(now)
    memo = _CAST_GONE_MEMO[0]
    if memo is not None and memo[0] == key and memo[1] == size:
        return memo[2]
    current = {str(n) for n in now.values() if n}
    out: dict[str, list[str]] = {}
    for role in CAST_ROLES:
        gone: list[str] = []
        for old in [CAST_DEFAULT_NAMES[role]] + list(seen.get(role) or []):
            if old and old not in current and old not in gone:
                gone.append(old)
        out[role] = gone
    _CAST_GONE_MEMO[0] = (key, size, out)
    return out


def cast_names_stamp_row(row: Any, names: dict[str, str] | None = None) -> bool:
    """[cast-names] Write down, once, the names a banked row was written
    under - on the conversation it carries (a shelf round's entry), or on the
    row itself (a read, a larder round). True when it stamped."""
    if not isinstance(row, dict):
        return False
    canonical = dialogue_entry(row) or row
    if isinstance(canonical.get(CAST_STAMP_KEY), dict):
        return False
    canonical[CAST_STAMP_KEY] = dict(names or cast_names())
    return True


def cast_rename_map(canonical: Any, now: dict[str, str] | None = None) -> dict[str, str]:
    """[cast-names] {old name: new name} for this row: the names it was
    written under that the cast no longer goes by. Exact when the row carries
    its stamp; for a row made before stamps, every name a character has gone
    by that nobody goes by now (its default and the names book)."""
    now = now or cast_names()
    if not isinstance(canonical, dict):
        return {}
    was = canonical.get(CAST_STAMP_KEY)
    out: dict[str, str] = {}
    if isinstance(was, dict):
        for role in CAST_ROLES:
            old = cast_name_clean(was.get(role))
            new = str(now.get(role) or "")
            if old and new and old != new:
                out[old] = new
        return out
    gone = _cast_gone(now)
    for role in CAST_ROLES:
        new = str(now.get(role) or "")
        for old in gone.get(role) or []:
            if new and old != new:
                out.setdefault(old, new)
    return out


def _cast_says(text: str, name: str) -> bool:
    return bool(name) and re.search(r"\b%s\b" % re.escape(name), text) is not None


def _cast_spoken(canonical: dict[str, Any]) -> str:
    """Everything the row would SAY: #1239's reading of it, and its takes."""
    said = [phrase_row_spoken(canonical)]
    for take in (canonical.get("takes") or [])[:200]:
        if isinstance(take, dict) and take.get("text"):
            said.append(str(take["text"]))
    return "\n".join(said)


def cast_names_row_blocked(kind: str, row: Any) -> bool:
    """[cast-names] A banked round or read whose recorded words say a name the
    cast no longer goes by is NOT ready: re-recording the lines is the rename
    desk's (cast_rename_tick), and until it has swapped them in the row stays
    on the shelf. The verdict is written on the row against the names and its
    stamp, so the polls re-read paperwork instead of re-scanning the words;
    with nobody renamed - the normal state - it costs one memoised read."""
    try:
        if not isinstance(row, dict):
            return False
        canonical = dialogue_entry(row) or row
        now = cast_names()
        rename = cast_rename_map(canonical, now)
        if not rename:
            if CAST_STALE_KEY in canonical:
                canonical.pop(CAST_STALE_KEY, None)
            return False
        key = "%s#%s#%d" % (_cast_key(now), _cast_key(canonical.get(CAST_STAMP_KEY)),
                            len(str(canonical.get("script") or canonical.get("text") or "")))
        got = canonical.get(CAST_STALE_KEY)
        if isinstance(got, dict) and str(got.get("key") or "") == key:
            return bool(got.get("hit"))
        spoken = _cast_spoken(canonical)
        hit = [old for old in rename if _cast_says(spoken, old)]
        why = ""
        if hit:
            said = ", ".join("%s (%s now)" % (old, rename[old]) for old in hit)
            why = ("held off the air: its recorded words say %s - " % said
                   + ("a produced spot has no road to re-record it, so it stays off"
                      if (canonical is row and row.get("produced")) else
                      "the rename desk re-records those lines with the new name, "
                      "then it airs again") + " [cast-names]")
        canonical[CAST_STALE_KEY] = {"key": key, "hit": hit,
                                     "map": {old: rename[old] for old in hit},
                                     "at": round(time.time()), "why": why}
        return bool(hit)
    except Exception:  # noqa: BLE001 - a name is never worth a row
        return False


def cast_names_line_stale(row: Any) -> bool:
    """[cast-names] A banked LINE - a gold bar, one of the SFX guy's banked
    lines - whose words say a name the cast no longer goes by. No road
    re-records these; they are held back and age out as they would."""
    try:
        if not isinstance(row, dict):
            return False
        now = cast_names()
        if (not isinstance(row.get(CAST_STAMP_KEY), dict)
                and not any(_cast_gone(now).values())):
            return False            # nobody has ever gone by another name
        text = str(row.get("text") or "")
        return bool(text) and any(_cast_says(text, old)
                                  for old in cast_rename_map(row, now))
    except Exception:  # noqa: BLE001
        return False


def _cast_rename_open(kind: str, row: dict[str, Any], entry: dict[str, Any] | None,
                      names: dict[str, str]) -> bool:
    """Open (or refresh) the rename shadow on a held row: the lines whose
    words change, with their new words, in the voice each line has now."""
    canonical = entry if entry is not None else row
    stale = canonical.get(CAST_STALE_KEY) or {}
    mapping = {str(o): str(n) for o, n in (stale.get("map") or {}).items()}
    if not mapping:
        return False
    held = canonical.get(CAST_RENAME_KEY)
    if (isinstance(held, dict) and held.get("names") == names
            and held.get("map") == mapping):
        return False                    # already open for this cast
    now = round(time.time(), 3)
    if entry is not None:
        if not recast_desk.round_whole(entry):
            return False                # the recording room is still on it
        lines = []
        for take in (entry.get("takes") or []):
            if not isinstance(take, dict):
                continue
            was = str(take.get("text") or "")
            said = cast_rename_text(was, mapping)
            if said == was:
                continue
            voice = str(take.get("voice") or "")
            key = _recast_key_fn(said, voice)
            have = _recast_have_fn(key) if key else None
            lines.append({"i": int(take.get("i", -1)), "who": str(take.get("who") or ""),
                          "text": said, "was": was, "voice": voice, "was_voice": voice,
                          "key": key if have else "", "made": bool(have),
                          "seconds": float((have or {}).get("seconds") or 0)})
        if not lines:
            # the name is in the script's paperwork but in no recorded line:
            # nothing to record, the words are renamed where they stand
            for field in ("script", "script_plain", "script_tinted"):
                if isinstance(entry.get(field), str):
                    entry[field] = cast_rename_text(entry[field], mapping)
            entry[CAST_STAMP_KEY] = dict(names)
            entry.pop(CAST_STALE_KEY, None)
            entry.pop(CAST_RENAME_KEY, None)
            return False
        canonical[CAST_RENAME_KEY] = {"at": now, "names": dict(names), "map": mapping,
                                      "takes": lines, "want": len(lines),
                                      "made": sum(1 for t in lines if t["made"]),
                                      "keys": [t["key"] for t in lines if t["key"]]}
        return True
    if row.get("produced"):
        return False                    # a finished mp3: no road re-records it
    was = str(row.get("text") or "")
    said = cast_rename_text(was, mapping)
    if not said or said == was:
        return False
    voice = str(row.get("voice") or "")
    key = _recast_key_fn(said, voice)
    have = _recast_have_fn(key) if key else None
    row[CAST_RENAME_KEY] = {"at": now, "names": dict(names), "map": mapping,
                            "text": said, "was": was, "voice": voice, "was_voice": voice,
                            "who": str(row.get("who") or CAST_READ_SEAT.get(str(kind), "dj")),
                            "key": key if have else "", "made": bool(have),
                            "seconds": float((have or {}).get("seconds") or 0),
                            "keys": [key] if have else []}
    return True


def _cast_rename_swap(kind: str, row: dict[str, Any],
                      entry: dict[str, Any] | None) -> bool:
    """Every renamed line has audio: put the new words and takes in the old
    ones' places, in one dict operation - a round changes between airings,
    never during one. A row that moved under the shadow (its words edited, a
    voice swapped by the recast desk) drops it, to be reopened next pass."""
    canonical = entry if entry is not None else row
    shadow = canonical.get(CAST_RENAME_KEY)
    if not isinstance(shadow, dict):
        return False
    mapping = {str(o): str(n) for o, n in (shadow.get("map") or {}).items()}
    old_keys: list[str] = []
    if entry is not None:
        lines = [t for t in (shadow.get("takes") or []) if isinstance(t, dict)]
        if not lines or not all(t.get("made") and t.get("key") for t in lines):
            return False
        by_i = {int(t.get("i", -1)): t for t in lines}
        takes = [t for t in (entry.get("takes") or []) if isinstance(t, dict)]
        for take in takes:
            new = by_i.get(int(take.get("i", -1)))
            if new is not None and (str(take.get("text") or "") != str(new.get("was") or "")
                                    or str(take.get("voice") or "") != str(new.get("was_voice") or "")):
                entry.pop(CAST_RENAME_KEY, None)
                return False
        for take in takes:
            new = by_i.get(int(take.get("i", -1)))
            if new is None:
                continue
            if take.get("key"):
                old_keys.append(str(take["key"]))
            take["text"] = str(new.get("text") or "")
            take["key"] = str(new.get("key") or "")
            if new.get("voice"):
                take["voice"] = str(new["voice"])
            if float(new.get("seconds") or 0) > 0:
                take["seconds"] = float(new["seconds"])
        entry["takes"] = takes
        entry["keys"] = list(dict.fromkeys(str(t.get("key")) for t in takes if t.get("key")))
        entry["seconds"] = round(sum(float(t.get("seconds") or 0) for t in takes), 2)
        for field in ("script", "script_plain", "script_tinted"):
            if isinstance(entry.get(field), str):
                entry[field] = cast_rename_text(entry[field], mapping)
        if row is not entry:
            row["seconds"] = float(entry.get("seconds") or row.get("seconds") or 0)
    else:
        if not shadow.get("made") or not shadow.get("key"):
            return False
        if (str(row.get("text") or "") != str(shadow.get("was") or "")
                or str(row.get("voice") or "") != str(shadow.get("was_voice") or "")):
            row.pop(CAST_RENAME_KEY, None)
            return False
        if row.get("key"):
            old_keys.append(str(row["key"]))
        row["text"] = str(shadow.get("text") or "")
        row["key"] = str(shadow.get("key") or "")
        if shadow.get("voice"):
            row["voice"] = str(shadow["voice"])
        if shadow.get("engine"):
            row["engine"] = str(shadow["engine"])
        if float(shadow.get("seconds") or 0) > 0:
            row["seconds"] = float(shadow["seconds"])
        if isinstance(row.get("text_plain"), str):
            row["text_plain"] = cast_rename_text(row["text_plain"], mapping)
    # The recast desk's shadow was cut from the old words: dropped, and its
    # next sweep reopens it from these ones if a voice still needs to move.
    if isinstance(canonical.get(recast_desk.SHADOW), dict):
        canonical.pop(recast_desk.SHADOW, None)
        for gone in ("recast_needed", "recast_seats", "recast_at"):
            canonical.pop(gone, None)
        row.pop("recast_needed", None)
    canonical[CAST_STAMP_KEY] = dict(shadow.get("names") or {})
    canonical[CAST_RENAME_DONE_KEY] = {"at": time.time(), "map": mapping, "keys": old_keys}
    canonical.pop(CAST_RENAME_KEY, None)
    canonical.pop(CAST_STALE_KEY, None)
    return True


def _cast_rename_rank(kind: str, row: dict[str, Any], entry: dict[str, Any] | None,
                      first: set[str]) -> tuple[int, int, float]:
    try:
        sid = str(alt_sid(str(kind), row) or "")
    except Exception:  # noqa: BLE001
        sid = ""
    target = entry if entry is not None else row
    heard = bool(float(row.get("aired_at") or 0) or int(row.get("aired") or 0))
    return (0 if sid and sid in first else 1, 1 if heard else 0,
            float(row.get("at") or target.get("at") or 0))


async def cast_rename_tick(budget: int = 0, force: bool = False) -> dict[str, Any]:
    """[cast-names] THE RENAME DESK, on the keeper's clock: stamp what is
    unstamped, hold and open every banked row whose words say a gone name,
    swap in what is whole, and record the renamed lines - a couple a pass,
    behind the live road, with the same yields as the recast desk."""
    out: dict[str, Any] = {"stamped": 0, "opened": 0, "lines": 0, "swaps": 0,
                           "held": 0, "why": ""}
    at = time.time()
    if not force and at - float(_CAST_RENAME_TICK.get("at") or 0) < CAST_RENAME_REST:
        out["why"] = "resting"
        return out
    _CAST_RENAME_TICK["at"] = at
    try:
        names = cast_names()
        cast_history_note(names)
        piles = _recast_piles()
        work: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []
        for kind, row, entry in piles:
            canonical = entry if entry is not None else row
            if not isinstance(canonical, dict) or canonical.get("preparing"):
                continue
            done = canonical.get(CAST_RENAME_DONE_KEY)
            if (isinstance(done, dict) and done.get("keys")
                    and at - float(done.get("at") or 0) > CAST_RENAME_KEEP_OLD_S):
                done["keys"] = []
            if cast_names_stamp_row(row, names):
                out["stamped"] += 1
                continue
            if cast_names_row_blocked(kind, row):
                out["held"] += 1
                if _cast_rename_open(kind, row, entry, names):
                    out["opened"] += 1
            elif isinstance(canonical.get(CAST_RENAME_KEY), dict):
                canonical.pop(CAST_RENAME_KEY, None)   # the names went back
            if isinstance(canonical.get(CAST_RENAME_KEY), dict):
                if _cast_rename_swap(kind, row, entry):
                    out["swaps"] += 1
                else:
                    work.append((kind, row, entry))
        out["why"] = ("the live road has the engine" if render_relief()
                      else prep_should_stop())
        if work and not out["why"]:
            want = int(budget or CAST_RENAME_LINES_PER_TICK)
            first = _recast_first_ids()
            work.sort(key=lambda item: _cast_rename_rank(item[0], item[1], item[2], first))
            for kind, row, entry in work:
                if out["lines"] >= want:
                    break
                canonical = entry if entry is not None else row
                shadow = canonical.get(CAST_RENAME_KEY)
                if not isinstance(shadow, dict):
                    continue
                todo = ([t for t in (shadow.get("takes") or []) if isinstance(t, dict)
                         and not t.get("made")] if entry is not None
                        else ([] if shadow.get("made") else [shadow]))
                for line in todo:
                    stop = prep_should_stop()
                    if out["lines"] >= want or stop:
                        out["why"] = out["why"] or stop
                        break
                    made = await prep_render_line(
                        str(line.get("text") or ""), str(line.get("who") or ""),
                        str(line.get("voice") or ""), kind=str(kind))
                    if not made or not made.get("key"):
                        break           # the engine said no; next pass
                    line["key"] = str(made["key"])
                    if made.get("voice"):
                        line["voice"] = str(made["voice"])
                    if made.get("engine"):
                        line["engine"] = str(made["engine"])
                    line["seconds"] = float(made.get("seconds") or 0) or float(line.get("seconds") or 0)
                    line["made"] = True
                    out["lines"] += 1
                if entry is not None:
                    got = [t for t in (shadow.get("takes") or []) if isinstance(t, dict)]
                    shadow["made"] = sum(1 for t in got if t.get("made"))
                    shadow["keys"] = [str(t.get("key")) for t in got if t.get("made") and t.get("key")]
                else:
                    shadow["keys"] = [str(shadow["key"])] if shadow.get("made") and shadow.get("key") else []
                if _cast_rename_swap(kind, row, entry):
                    out["swaps"] += 1
        if out["stamped"] or out["opened"] or out["lines"] or out["swaps"]:
            try:
                _larder_save()
                _pantry_save(True)
            except Exception:  # noqa: BLE001
                pass
        if out["swaps"]:
            pipeline_log("voice", "the rename desk swapped %d banked row(s) over to the "
                                  "cast's names now - they were off the air only while "
                                  "the lines were re-recorded [cast-names]" % int(out["swaps"]))
            note_action("banked rounds re-recorded with the cast's new names",
                        "%d row(s) swapped, %d line(s) recorded"
                        % (int(out["swaps"]), int(out["lines"])))
    except Exception:  # noqa: BLE001
        out["why"] = out["why"] or "the rename desk stumbled"
    _CAST_RENAME_TICK.update({k: out[k] for k in ("stamped", "opened", "lines",
                                                   "swaps", "held", "why")})
    return out


def cast_rename_state() -> dict[str, Any]:
    """[cast-names] What the rename desk is holding and re-recording."""
    held: list[dict[str, Any]] = []
    open_rows = want = made = 0
    for kind, row, entry in _recast_piles():
        canonical = entry if entry is not None else row
        if not isinstance(canonical, dict):
            continue
        stale = canonical.get(CAST_STALE_KEY)
        shadow = canonical.get(CAST_RENAME_KEY)
        if isinstance(stale, dict) and stale.get("hit"):
            try:
                sid = str(alt_sid(str(kind), row) or "")
            except Exception:  # noqa: BLE001
                sid = ""
            held.append({"kind": str(kind), "sid": sid, "names": dict(stale.get("map") or {}),
                         "why": str(stale.get("why") or ""), "open": isinstance(shadow, dict)})
        if isinstance(shadow, dict):
            open_rows += 1
            if entry is not None:
                lines = [t for t in (shadow.get("takes") or []) if isinstance(t, dict)]
                want += len(lines)
                made += sum(1 for t in lines if t.get("made"))
            else:
                want += 1
                made += 1 if shadow.get("made") else 0
    return {"at": time.time(), "names": cast_names(), "held": len(held),
            "rows": held[:80], "open": open_rows, "lines_want": want,
            "lines_made": made, "tick": dict(_CAST_RENAME_TICK),
            "gone_by": {r: list(v) for r, v in _cast_gone(cast_names()).items()}}


@app.get("/api/cast/rename")
async def cast_rename_api(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[cast-names] The rename desk: banked rows held for saying a name the
    cast no longer goes by, and how far their re-recording has got."""
    require_read_auth(authorization)
    return await asyncio.to_thread(cast_rename_state)
'''

EDITS = [
    ("cast2-helpers", _HELPERS_OLD, _HELPERS_NEW, 1),

    # --- 3. the gate, beside #1239's phrase gate ------------------------------
    ("cast2-gate",
     '        _phrase_gate = globals().get("phrase_ban_row_blocked")\n'
     '        if (content_gate_enabled("phrase_ban") and callable(_phrase_gate)\n'
     '                and _phrase_gate(kind, row)):\n'
     '            return False\n',
     '        _phrase_gate = globals().get("phrase_ban_row_blocked")\n'
     '        if (content_gate_enabled("phrase_ban") and callable(_phrase_gate)\n'
     '                and _phrase_gate(kind, row)):\n'
     '            return False\n'
     '        # [cast-names] ...and a round whose recorded words say a name the\n'
     '        # cast no longer goes by waits for the rename desk to re-record\n'
     '        # those lines. The same callable lookup, for the same reason.\n'
     '        _cast_gate = globals().get("cast_names_row_blocked")\n'
     '        if callable(_cast_gate) and _cast_gate(kind, row):\n'
     '            return False\n', 1),
    ("cast2-stamp",
     '        try:\n'
     '            row.setdefault("cast", cast_signature())\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass\n',
     '        try:\n'
     '            row.setdefault("cast", cast_signature())\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass\n'
     '        # [cast-names] ...and WHAT THEY WERE CALLED: the names the words\n'
     '        # were written under, so a rename later is an exact check.\n'
     '        try:\n'
     '            cast_names_stamp_row(row)\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass\n', 1),
    ("cast2-keeper",
     '            try:\n'
     '                await recast_sweep()\n'
     '            except Exception:  # noqa: BLE001\n'
     '                pass\n',
     '            try:\n'
     '                await recast_sweep()\n'
     '            except Exception:  # noqa: BLE001\n'
     '                pass\n'
     '            # [cast-names] and the rename desk: banked words that say a\n'
     '            # name the cast no longer goes by go back in, same clock.\n'
     '            try:\n'
     '                await cast_rename_tick()\n'
     '            except Exception:  # noqa: BLE001\n'
     '                pass\n', 1),
    ("cast2-gold",
     '        pool = [r for r in _gold_rows()\n'
     '                if str(r.get("who") or "") != str(exclude_who or "")\n'
     '                and now - float(r.get("last") or 0) >= rest]\n',
     '        pool = [r for r in _gold_rows()\n'
     '                if str(r.get("who") or "") != str(exclude_who or "")\n'
     '                and now - float(r.get("last") or 0) >= rest\n'
     '                and not cast_names_line_stale(r)]   # [cast-names] no gone names\n', 1),
    ("cast2-sfx-bank",
     '            or not _SFX_READY_BANK.media_ready(row)):\n'
     '        return False\n'
     '    if dialogue_tint_wanted():\n',
     '            or not _SFX_READY_BANK.media_ready(row)):\n'
     '        return False\n'
     '    if cast_names_line_stale(row):          # [cast-names] a gone name: held back\n'
     '        return False\n'
     '    if dialogue_tint_wanted():\n', 1),

    # --- 4. caller names are never a cast member's ------------------------------
    ("cast2-caller-names",
     'def caller_names() -> list[str]:\n'
     '    try:\n'
     '        data = json.loads(CALLER_NAMES_PATH.read_text())\n'
     '        names = [str(n).strip() for n in data if str(n).strip()]\n'
     '        return names or list(CALLER_NAME_SEED)\n'
     '    except Exception:\n'
     '        return list(CALLER_NAME_SEED)\n',
     'def caller_names_raw() -> list[str]:\n'
     '    """[cast-names] The caller-name dictionary as the operator keeps it -\n'
     '    what the names editor reads and writes."""\n'
     '    try:\n'
     '        data = json.loads(CALLER_NAMES_PATH.read_text())\n'
     '        names = [str(n).strip() for n in data if str(n).strip()]\n'
     '        return names or list(CALLER_NAME_SEED)\n'
     '    except Exception:\n'
     '        return list(CALLER_NAME_SEED)\n'
     '\n'
     '\n'
     'def caller_names() -> list[str]:\n'
     '    """The names a stranger can ring in under - [cast-names] never one\n'
     '    somebody in the booth goes by."""\n'
     '    taken = cast_taken_names()\n'
     '    return ([n for n in caller_names_raw() if not cast_name_taken(n, taken)]\n'
     '            or [n for n in CALLER_NAME_SEED if not cast_name_taken(n, taken)]\n'
     '            or list(CALLER_NAME_SEED))\n', 1),
    ("cast2-caller-editor",
     '    return {"callers": read_callers(), "names": caller_names(),\n',
     '    return {"callers": read_callers(), "names": caller_names_raw(),   # [cast-names] as kept\n', 1),
    ("cast2-name-draw-taken",
     '    taken |= {str(r.get("name") or "").lower() for r in read_callers()}\n',
     '    taken |= {str(r.get("name") or "").lower() for r in read_callers()}\n'
     '    _cast_taken = cast_taken_names()     # [cast-names] never a booth name\n'
     '    taken |= _cast_taken\n', 1),
    ("cast2-name-draw-free",
     '        free = [n for n in pool["names"] if str(n).lower() not in taken]\n',
     '        free = [n for n in pool["names"] if str(n).lower() not in taken\n'
     '                and not cast_name_taken(n, _cast_taken)]   # [cast-names]\n', 1),
    ("cast2-conjure",
     '    name, pool = name_draw()\n'
     '    return {"id": "", "name": name, "name_pool": pool,\n',
     '    name, pool = name_draw()\n'
     '    # [cast-names] the spent-book fallback draws blind: a cast member\'s\n'
     '    # name is drawn again rather than put on the line.\n'
     '    for _ in range(4):\n'
     '        if not cast_name_taken(name):\n'
     '            break\n'
     '        name, pool = name_draw()\n'
     '    return {"id": "", "name": name, "name_pool": pool,\n', 1),
    ("cast2-regulars",
     '        fresh = [r for r in rows if now - float(r.get("last") or 0) > 1500\n'
     '                 and not story_open_for(str(r.get("name") or ""))]   # #1039\n',
     '        fresh = [r for r in rows if now - float(r.get("last") or 0) > 1500\n'
     '                 and not story_open_for(str(r.get("name") or ""))   # #1039\n'
     '                 and not cast_name_taken(r.get("name"))]            # [cast-names]\n', 1),

    # --- 2. Sam by name ----------------------------------------------------------
    ("cast2-sam-verdict",
     '            "You are the SFX guy in the corner booth of a radio studio — "\n',
     '            f"You are {cast_name(\'sfxguy\')}, the SFX guy in the corner booth of a radio studio — "   # [cast-names]\n', 1),
    ("cast2-sam-shape",
     '     "{a} raises it and the SFX GUY behind the glass has an opinion and "\n',
     '     "{a} raises it and {guy}, the SFX guy behind the glass, has an opinion and "   # [cast-names]\n', 1),
    ("cast2-sam-shape-format",
     '        + deck[name].format(a=first, b=other) + " "\n',
     '        + deck[name].format(a=first, b=other, guy=cast_name("sfxguy")) + " "   # [cast-names]\n', 1),
    ("cast2-sam-angle-booth",
     '        angle += (" The SFX guy in the corner booth is a faded-NASCAR-"\n',
     '        angle += (f" {cast_name(\'sfxguy\')}, the SFX guy in the corner booth, is a faded-NASCAR-"   # [cast-names]\n', 1),
    ("cast2-sam-angle-news",
     '            angle += (" The SFX guy just slapped the desk and broke a "\n',
     '            angle += (f" {cast_name(\'sfxguy\')}, the SFX guy, just slapped the desk and broke a "   # [cast-names]\n', 1),
    ("cast2-sam-angle-verdict",
     '        angle += (" At some point one of you turns to the SFX guy in his "\n'
     '                  "booth and appeals for backup OUT LOUD — \'back me up "\n',
     '        angle += (f" At some point one of you turns to {cast_name(\'sfxguy\')}, the SFX guy in his "   # [cast-names]\n'
     '                  "booth, and appeals for backup OUT LOUD — \'back me up "\n', 1),
    ("cast2-sam-passage",
     '            "The SFX guy — who NEVER talks — just read a whole passage "\n',
     '            f"{cast_name(\'sfxguy\')}, the SFX guy — who NEVER talks — just read a whole passage "   # [cast-names]\n', 1),
    ("cast2-sam-flow",
     '            str(info.get("instruction") or ""))\n',
     '            str(info.get("instruction") or "").replace(   # [cast-names] he has a name\n'
     '                "The SFX Guy", cast_name("sfxguy") + ", the SFX guy,"))\n', 1),
    ("cast2-sam-ids",
     '        "You are the sting voice on a radio station — the guy who says "\n',
     '        f"You are {cast_name(\'sfxguy\')}, the SFX guy: the sting voice on a radio station — the guy who says "   # [cast-names]\n', 1),
    ("cast2-sam-news",
     '                "You are a thick-accented, NASCAR-loving country boy in "\n',
     '                f"You are {cast_name(\'sfxguy\')}, the SFX guy — a thick-accented, NASCAR-loving country boy in "   # [cast-names]\n', 1),
    ("cast2-sam-react",
     '                "You are a thick-accented country boy in a radio booth. "\n'
     '                f"Someone on air just said: \\"{context}\\". Fire back ONE "\n',
     '                f"You are {cast_name(\'sfxguy\')}, the SFX guy — a thick-accented country boy in a radio booth. "   # [cast-names]\n'
     '                f"Someone on air just said: \\"{context}\\". Fire back ONE "\n', 1),
    ("cast2-sam-warp",
     '            "You are a thick-accented country boy in a radio booth. "\n'
     '            f"Take these sayings: {\' / \'.join(picks)} — and {recipe}."\n',
     '            f"You are {cast_name(\'sfxguy\')}, the SFX guy — a thick-accented country boy in a radio booth. "   # [cast-names]\n'
     '            f"Take these sayings: {\' / \'.join(picks)} — and {recipe}."\n', 1),
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
