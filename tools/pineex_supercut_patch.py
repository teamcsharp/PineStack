#!/usr/bin/env python3
"""[pineex-supercut] The supercut version of an hourly H3 render: a captioned copy in the clip book and
on the endless set.

"one ten second scene. Also do a supercut version with supercut text at the bottom that plays also in
the sfx queue." (the operator, 2026-10-06, the pineEX preset.)

Where the decision belongs: update_generation() is the one door both landing roads pass through -
_track_generation (the live poller, app.py ~6511) and reconcile_generations (the restart repair, ~6583)
both call update_generation(prompt_id, files=..., status="done"). The hook runs there, after the gallery
row is written and outside the lock, so the render itself is never at stake.

Edits (app.py):
  1. update_generation          remembers the row it changed; a row that just read done is offered its
                                supercut version (h3_supercut_landed - a module-level name resolved at
                                call time, defined further down with the H3 hourly section).
  2. [s3-visuals] section       after h3_hourly_airing_note: the [pineex-supercut] block - the opt-in rule
                                (h3_supercut_wanted: pineEX by name, or "supercut" in a preset's style or
                                constraints), the caption (h3_supercut_caption), the folder under the
                                writable samples root (h3_supercut_folder), the PNG strip drawn with
                                Pillow's bundled face (_h3_supercut_png), the one ffmpeg overlay pass
                                (h3_supercut_burn), the bounded async road (h3_supercut_version) and the
                                hook (h3_supercut_landed).
  3. h3_prompts_history         the videos an hour made carry their supercut version (the rolodex).

Usage:  pineex_supercut_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pineex_supercut_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

UPDATE_OLD = '''    async with _generations_lock:
        records = _read_all_generations()
        changed = False
        for rec in records:
            if rec.get("prompt_id") == prompt_id:
                rec.update(fields)
                changed = True
        if changed:
            try:
                GENERATIONS_PATH.write_text(
                    "".join(json.dumps(r) + "\\n" for r in records)
                )
            except Exception:
                pass
'''
UPDATE_NEW = '''    landed: dict[str, Any] | None = None               # [pineex-supercut] the row this call changed
    async with _generations_lock:
        records = _read_all_generations()
        changed = False
        for rec in records:
            if rec.get("prompt_id") == prompt_id:
                rec.update(fields)
                changed = True
                landed = rec
        if changed:
            try:
                GENERATIONS_PATH.write_text(
                    "".join(json.dumps(r) + "\\n" for r in records)
                )
            except Exception:
                pass
    # [pineex-supercut] a row that just read done is offered its supercut version: an
    # hourly render whose preset asks for one gets a captioned copy for the clip book
    # and the endless set. Outside the lock, after the row is written, never raising.
    if landed is not None and fields.get("status") == "done":
        h3_supercut_landed(landed)
'''

NOTE_OLD = '''    try:
        _h3_prompts_offloop(write)
    except Exception:  # noqa: BLE001 - a test namespace without the section
        write()
'''
NOTE_NEW = '''    try:
        _h3_prompts_offloop(write)
    except Exception:  # noqa: BLE001 - a test namespace without the section
        write()


# --- [pineex-supercut] THE SUPERCUT VERSION OF AN HOURLY RENDER ----------------
#
# "one ten second scene. Also do a supercut version with supercut text at the
# bottom that plays also in the sfx queue." (the operator, 2026-10-06, the pineEX
# preset.) When an hourly H3 render lands under a preset that asks for one -
# pineEX by name, or any preset whose style or constraints say "supercut" - a
# captioned copy is cut off the loop: the line it sings and the station's name
# along the bottom, H3_SUPERCUT_MARGIN_PX up from the edge, BURNT IN (the endless
# set and the tablet's wall play files natively, so a page caption would not
# travel with the clip). The copy lives in the writable samples root (#839:
# /samples is the read-only drop share) under a folder named for the preset,
# goes in the clip book by hand the second it exists (sfx_db_write_row, the road
# every made clip takes) and is handed to the endless set's own request door
# (sfx_cycle_request, #1417), which keeps the cooldown rule. The render itself is
# never at stake: the hook runs after the gallery row is written, every step is
# bounded, one cut at a time, and a failure is one line in the ads log. The
# gallery row remembers what was made (supercut_version) and the presets history
# lists it beside the hour's videos.
H3_SUPERCUT_PRESETS = ("pineex",)          # presets that get one by name (lower-case)
H3_SUPERCUT_WORD = "supercut"              # ...or by asking for it in their style / constraints
H3_SUPERCUT_SECONDS = 150.0                # the bound on one cut, picture probe to finished file
H3_SUPERCUT_MARGIN_PX = 10                 # the caption's distance from the very bottom
H3_SUPERCUT_STATION = "Pine Box FM"        # the second line of the caption
_H3_SUPERCUT_BUSY: set[str] = set()        # prompt ids being cut now (done can be marked twice)
_H3_SUPERCUT_LOCK = asyncio.Lock()         # one cut at a time: a restart's repair can land several

# [supercut-brand] THE CARD, THE FONT AND THE WAY IT ARRIVES. "for the supercut text, I
# want it to use a font rolled on the roulette from ... Fonts ... the text with a
# cinematic kerning and a 2nd row with the station name and then a brand of the preset
# on a row"; "10 different cinematic text appearance animation effects ... entry and
# exit animations chosen at random by the roulette" (the operator, 2026-10-06).
# supercut_brand.py draws the three-row card (SUPERCUT / PINEBOX FM / the station's long
# name) in ONE font per cut, rolled by System 3 over the operator's collection (the
# supercut_fonts_folder setting; listed only while the collection answers; the pick
# copied once into data/fonts_cache so a burn never touches the share) and renders its
# entry and its exit as frames (supercut.text_in / supercut.text_out, two more rolls).
# Both supercut roads - this one and the SFX guy's hourly and custom cuts in
# sfx_supercut.py - take their brand from supercut_brand_plan and keep its record.
import supercut_brand as _supercut_brand                                  # [supercut-brand]

H3_SUPERCUT_FONT_CACHE = "fonts_cache"     # [supercut-brand] under DATA_DIR: the local copies the burn reads


def supercut_fonts_folder() -> Path:
    """[supercut-brand] The operator's font collection: the DJ setting, under SFX_ROOT
    unless it is an absolute path (the NAS sits at another path after the move)."""
    settings = globals().get("dj_settings")
    defaults = globals().get("DEFAULT_DJ") or {}
    try:
        raw = str((settings() if callable(settings) else {}).get("supercut_fonts_folder") or "").strip()
    except Exception:  # noqa: BLE001
        raw = ""
    raw = raw or str(defaults.get("supercut_fonts_folder") or "Fonts")
    path = Path(raw)
    root = globals().get("SFX_ROOT")
    return path if path.is_absolute() else Path(root if root is not None else "/samples") / raw


def supercut_font_shelf() -> list[Path]:
    """[supercut-brand] The fonts the die rolls over - the folder listed only while the
    collection answers (a folder under SFX_ROOT is the share and waits for the probe; an
    absolute folder elsewhere is not gated; with no probe at all, nothing is listed).
    Blocking: a worker thread's."""
    folder = supercut_fonts_folder()
    reach = globals().get("sfx_reachable")
    under = globals().get("sfx_reach_under")
    gated = bool(under(folder)) if callable(under) else True
    reachable = (bool(reach()) if callable(reach) else False) or not gated
    return _supercut_brand.font_shelf(folder, reachable=reachable)


def h3_supercut_station() -> str:
    """[supercut-brand] The station's long name for the card's third row (the station setting)."""
    settings = globals().get("dj_settings")
    try:
        name = str((settings() if callable(settings) else {}).get("station_name") or "").strip()
    except Exception:  # noqa: BLE001
        name = ""
    return name or H3_SUPERCUT_STATION


def supercut_brand_roll(shelf: list[Path], seed_text: str = "", note: Any = None) -> dict[str, Any]:
    """[supercut-brand] The three rolls, System 3's: the font (supercut.font) over the
    shelf's labels, the entry (supercut.text_in) and the exit (supercut.text_out) over the
    ten effects - through the tabled die, so the desk can retire one. `note(key, options,
    picked)` hears each roll (the hourly road's rolodex). Not blocking: the loop's."""
    die = globals().get("s3_choice")
    seed = _supercut_brand.seed_for(seed_text)
    rolled = callable(die)
    font = _supercut_brand.roll_font(
        shelf, (lambda labels: die(_supercut_brand.KEY_FONT, labels, _supercut_brand.LABEL_FONT)) if rolled else None,
        (lambda labels, picked: note(_supercut_brand.KEY_FONT, labels, picked)) if callable(note) else None, seed)
    effect_in, effect_out = _supercut_brand.roll_effects(
        (lambda key, options, label: die(key, options, label)) if rolled else None,
        note if callable(note) else None, seed)
    return {"font_path": str(font) if font else "", "effect_in": effect_in, "effect_out": effect_out,
            "seed": seed, "rolled": rolled, "shelf": len(shelf)}


async def supercut_brand_plan(seed_text: str = "", note: Any = None) -> dict[str, Any]:
    """[supercut-brand] The brand a cut is burnt with: the shelf (a worker - the share),
    the rolls (the loop), the rolled font cached locally (a worker), the station's long
    name - the dict the burn and the record read. Never raises: with nothing to roll
    over the card is set in Pillow's face and the record says so."""
    try:
        shelf = await asyncio.to_thread(supercut_font_shelf)
    except Exception as exc:  # noqa: BLE001
        pipeline_log("ads", "supercut brand: the font shelf was not listed (%s)" % type(exc).__name__)
        shelf = []
    plan = supercut_brand_roll(list(shelf or []), seed_text, note)
    plan["cached"] = ""
    if plan["font_path"]:
        try:
            data = globals().get("data_path")
            cache = data(H3_SUPERCUT_FONT_CACHE) if callable(data) else Path(H3_SUPERCUT_FONT_CACHE)
            plan["cached"] = str(await asyncio.to_thread(_supercut_brand.cache_font, plan["font_path"], cache))
        except Exception as exc:  # noqa: BLE001
            pipeline_log("ads", "supercut brand: the font %s was not cached (%s)"
                         % (Path(plan["font_path"]).name, type(exc).__name__))
    plan["station"] = h3_supercut_station()
    return plan


def h3_supercut_hour_note(rec: Any, key: str, opts: list[str], picked: str) -> None:
    """[supercut-brand] A supercut roll onto the hour's rolodex entry, after the fact: the
    hour's own rolls were bound when its render was queued, so this goes through
    _h3_slot_note (the roll's record, with what it was drawn from), is taken back off the
    live tray, and is written onto the hour's entry by its id, committed to the store."""
    name = "supercut_" + str(key).rsplit(".", 1)[-1]
    slot_note = globals().get("_h3_slot_note")
    tray = globals().get("_H3_HOURLY_ROLLS")
    got = None
    if callable(slot_note) and isinstance(tray, dict):
        try:
            slot_note(name, key, list(opts), str(picked))
        except Exception:  # noqa: BLE001
            pass
        got = tray.pop(name, None)
    got = dict(got) if isinstance(got, dict) and got else {"key": key, "picked": str(picked)[:300]}
    got.setdefault("picked", str(picked)[:300])
    words = rec.get("h3_prompts") if isinstance(rec, dict) and isinstance(rec.get("h3_prompts"), dict) else {}
    hour = str(words.get("hour") or "")
    if not hour:
        return
    memory = globals().get("_H3_PROMPTS_MEM")
    store = memory[0] if isinstance(memory, list) and memory and isinstance(memory[0], dict) else {}
    hours = list(store.get("history") or []) + list(globals().get("_H3_PROMPTS_HOURS") or [])
    commit = globals().get("h3_prompts_commit_hour")
    offloop = globals().get("_h3_prompts_offloop")
    for entry in reversed(hours):
        if isinstance(entry, dict) and entry.get("hour") == hour:
            had = entry.get("rolls") if isinstance(entry.get("rolls"), dict) else {}
            had[name] = got
            entry["rolls"] = had
            if callable(commit) and callable(offloop):
                try:
                    offloop(commit, dict(entry))
                except Exception:  # noqa: BLE001 - the memory entry still carries it
                    pass
            return


def h3_supercut_wanted(rec: Any) -> str:
    """The preset's name when this gallery row is an hourly render whose preset
    asks for a supercut version, else "". The rule any preset can opt into is
    the word "supercut" in its style or constraints; pineEX has it by name."""
    if not isinstance(rec, dict) or not rec.get("hourly"):
        return ""
    words = rec.get("h3_prompts") if isinstance(rec.get("h3_prompts"), dict) else None
    if not words:
        return ""
    preset = words.get("preset") if isinstance(words.get("preset"), dict) else {}
    name = " ".join(str(preset.get("name") or "").split())
    fields = words.get("fields") if isinstance(words.get("fields"), dict) else {}
    asked = " ".join(str(words.get(k) or fields.get(k) or "") for k in ("style", "constraints")).lower()
    if name.lower() in H3_SUPERCUT_PRESETS or H3_SUPERCUT_WORD in asked:
        return name or H3_SUPERCUT_WORD
    return ""


H3_SUPERCUT_CAPTION_WORD = "SUPERCUT"      # [pineex-caption] the first line - "SUPERCUT + the product" (the operator)


def h3_supercut_product(rec: Any) -> str:
    """[pineex-caption] What the hour sold, as the filled direction carries it: the {product} / {offer} roll
    ('the product "Name" - pitch'), else the rolled feature ('the Pine Box feature "Name"'), else the station."""
    words = rec.get("h3_prompts") if isinstance(rec, dict) and isinstance(rec.get("h3_prompts"), dict) else {}
    text = " ".join(str(words.get("direction") or words.get("goal") or (rec or {}).get("prompt") or "").split())
    for pattern in (r'the product "([^"]{1,80})"', r'the Pine Box feature "([^"]{1,80})"'):
        found = re.search(pattern, text)
        if found and found.group(1).strip():
            return found.group(1).strip()
    return H3_SUPERCUT_STATION


def h3_supercut_caption(rec: Any) -> list[str]:
    """[supercut-brand] The card's three rows: SUPERCUT, PINEBOX FM, the station's long name
    as the station setting has it ("a 2nd row with the station name and then a brand of the
    preset on a row" - the operator, 2026-10-06; the product line of [pineex-caption] gave
    way to the card; h3_supercut_product still reads what the hour sold)."""
    return _supercut_brand.lines(h3_supercut_station())


def h3_supercut_folder(name: str) -> Path:
    """The clip folder the copies live in: the writable samples root, named for
    the preset (pineEX -> data/samples/pineEX). The book's folder column reads
    that name, so the SFX guy's book lists the copies under it."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(name or "").strip()).strip("-")[:40] or H3_SUPERCUT_WORD
    return SFX_LOCAL_ROOT / slug


def _h3_supercut_png(lines: list[str], width: int, height: int, out: Path, font_path: Any = None) -> Path:
    """[supercut-brand] The finished card as a PNG exactly the picture's width: the shared
    three-row card (supercut_brand.card) in the given font, Pillow's bundled face when none
    loads - a still of the hold frame, for a probe or a test. Disk and CPU - a worker thread."""
    rows = [x for x in lines if x][:3] or [H3_SUPERCUT_STATION]
    img = _supercut_brand.card(rows, font_path, width, height)
    img.save(out)
    return out


def h3_supercut_burn(source: Path, target: Path, lines: list[str], exe: str = "", brand: Any = None) -> dict[str, Any]:
    """[supercut-brand] The branded copy: the card's entry, hold and exit laid over the
    picture in ONE ffmpeg pass (three overlays, each enabled in its own window, centred,
    H3_SUPERCUT_MARGIN_PX up from the bottom edge - the container's imageio ffmpeg has no
    drawtext), the sound as it was (AAC in an mp4). `brand` is supercut_brand_plan's dict
    (the cached font, the two rolled effects, the seed); without one the card is set in
    Pillow's face with seeded effects. The frames live in a folder beside the target while
    it is made and go with the temporary. Blocking: a worker thread."""
    import imageio_ffmpeg
    exe = exe or _sfx_ffmpeg() or "ffmpeg"
    source, target = Path(source), Path(target)
    reader = imageio_ffmpeg.read_frames(str(source))
    try:
        meta = next(reader)
    finally:
        reader.close()
    width, height = (int(x) for x in (meta.get("size") or (0, 0)))
    if width <= 0 or height <= 0:
        raise ValueError("the render has no picture to caption")
    seconds = float(meta.get("duration") or 0.0)
    plan = dict(brand or {})
    seed = int(plan.get("seed") or _supercut_brand.seed_for(target.stem))
    if not plan.get("effect_in") or not plan.get("effect_out"):
        plan["effect_in"], plan["effect_out"] = _supercut_brand.roll_effects(None, None, seed)
    font = plan.get("cached") or plan.get("font_path") or ""
    target.parent.mkdir(parents=True, exist_ok=True)
    workdir = target.with_name(target.stem + ".brand")
    try:
        prep = _supercut_brand.prepare(list(lines), font, width, height, seconds, plan["effect_in"],
                                       plan["effect_out"], workdir, seed=seed)
        made = _supercut_brand.burn(exe, source, target, prep, run=subprocess.run,
                                    timeout=max(30.0, H3_SUPERCUT_SECONDS - 30.0))
    finally:
        _supercut_brand.clean_workdir(workdir)
    record = _supercut_brand.record_of(prep, plan.get("font_path") or font, plan.get("cached") or "", list(lines),
                                       plan["effect_in"], plan["effect_out"], rolled=bool(plan.get("rolled")),
                                       ffmpeg_ms=made.get("ffmpeg_ms"), shelf=plan.get("shelf"))
    return {"path": str(target), "size": [width, height], "lines": list(lines),
            "seconds": round(seconds, 3), "brand": record}


def h3_supercut_source(rec: dict[str, Any]) -> Path | None:
    """The landed render's video file: a published copy on the ads shelf first
    (workshop_publish_files may have moved and renamed it), else the gallery's
    own file by name."""
    for filename in list(rec.get("aired_files") or []) + list(rec.get("files") or []):
        name = str(filename or "")
        if not name:
            continue
        cand: Path | None = SFX_ADS_DIR / name
        if not cand.is_file():
            cand = comfy_output_find(name)
        if cand is not None and cand.is_file() and cand.suffix.lower() in SFX_VIDEO_TYPES:
            return cand
    return None


async def h3_supercut_version(rec: dict[str, Any]) -> dict[str, Any] | None:
    """[pineex-supercut] The supercut version of one landed hourly render: cut
    off the loop, in the clip book, handed to the endless set, written on the
    gallery row. None when the row does not ask for one or already has one.
    Never raises - the render it is made from is never at stake."""
    pid = str((rec or {}).get("prompt_id") or "")
    name = h3_supercut_wanted(rec)
    if not pid or not name or rec.get("supercut_version") or pid in _H3_SUPERCUT_BUSY:
        return None
    _H3_SUPERCUT_BUSY.add(pid)
    try:
        async with _H3_SUPERCUT_LOCK:
            source = await asyncio.to_thread(h3_supercut_source, rec)
            if source is None:
                pipeline_log("ads", "supercut version (%s): the render %s has no video file to caption"
                             % (name, pid[:8]))
                return None
            lines = h3_supercut_caption(rec)
            folder = h3_supercut_folder(name)
            stem = re.sub(r"[^A-Za-z0-9_-]+", "-", source.stem).strip("-")[:60] or pid[:8]
            target = folder / ("%s-%s-supercut.mp4" % (folder.name, stem))
            # [supercut-brand] the font and the two text effects, System 3's, noted on the hour's rolodex
            brand = await supercut_brand_plan(pid, lambda key, opts, picked: h3_supercut_hour_note(rec, key, opts, picked))
            got = await asyncio.wait_for(asyncio.to_thread(h3_supercut_burn, source, target, lines, "", brand),
                                         timeout=H3_SUPERCUT_SECONDS)
            seconds = float(await asyncio.to_thread(_media_duration_probe, target) or 0.0)
            booked = bool(await asyncio.to_thread(sfx_db_write_row, target, seconds, 1 if seconds > 0 else 0))
            queued = bool(sfx_cycle_request(target, name, "the supercut version of this hour's %s render" % name))
            record = got.get("brand") if isinstance(got, dict) and isinstance(got.get("brand"), dict) else {
                "font": Path(brand["cached"]).stem if brand.get("cached") else _supercut_brand.DEFAULT_FACE,
                "effect_in": brand.get("effect_in"), "effect_out": brand.get("effect_out"), "seed": brand.get("seed")}
            made = {"file": target.name, "path": str(target), "folder": folder.name, "sid": sfx_id(target),
                    "seconds": round(seconds, 3), "caption": lines, "booked": booked, "queued": queued,
                    "source": source.name, "at": round(time.time(), 3),
                    "font": record.get("font"), "brand": record}                   # [supercut-brand] kept with the cut
            await update_generation(pid, supercut_version=made)
            pipeline_log("ads", "supercut version (%s): %s - %.1f s, %s, %s; set in %s, %s in / %s out" % (
                name, target.name, seconds,
                "in the clip book" if booked else "NOT in the clip book",
                "handed to the endless set" if queued else
                "not handed to the endless set (its door said no: four waiting, or on cooldown)",
                record.get("font"), record.get("effect_in_used") or record.get("effect_in"),
                record.get("effect_out_used") or record.get("effect_out")))          # [supercut-brand]
            return made
    except Exception as exc:  # noqa: BLE001 - the render itself is never at stake
        pipeline_log("ads", "supercut version (%s): not made for %s (%s: %s)"
                     % (name, pid[:8], type(exc).__name__, str(exc)[:160]))
        return None
    finally:
        _H3_SUPERCUT_BUSY.discard(pid)


def h3_supercut_landed(rec: Any) -> None:
    """The hook update_generation calls once a row reads done: an hourly render
    whose preset asks for one gets its supercut version, fired and forgotten.
    Nothing happens for any other row; never raises."""
    try:
        if h3_supercut_wanted(rec) and not (rec or {}).get("supercut_version"):
            fire_and_forget(h3_supercut_version(dict(rec)))
    except Exception as exc:  # noqa: BLE001
        pipeline_log("ads", "supercut version: the hook did not fire (%s)" % type(exc).__name__)
'''

HISTORY_OLD = '''                    {"prompt_id": row.get("prompt_id"), "files": row.get("files") or [],
                     "status": row.get("status"), "road": rec.get("road"), "ts": row.get("ts")})
'''
HISTORY_NEW = '''                    {"prompt_id": row.get("prompt_id"), "files": row.get("files") or [],
                     "status": row.get("status"), "road": rec.get("road"), "ts": row.get("ts"),
                     "supercut": row.get("supercut_version")})            # [pineex-supercut] the rolodex
'''

EDITS = {
    "app.py": [
        ("update_generation: a row that just read done is offered its supercut version", UPDATE_OLD, UPDATE_NEW, 1),
        ("[pineex-supercut] the rule, the caption, the burn, the road and the hook", NOTE_OLD, NOTE_NEW, 1),
        ("h3_prompts_history: the hour's videos carry their supercut version", HISTORY_OLD, HISTORY_NEW, 1),
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
                print("%-78s applied" % label[:78])
                continue
            n = text.count(old)
            if n == want:
                print("%-78s ready" % label[:78])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-78s MISSING (anchor count %d, wanted %d)" % (label[:78], n, want))
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
        tmp = path.with_suffix(path.suffix + ".pineexsupercut.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
