#!/usr/bin/env python3
"""[supercut-brand] The SUPERCUT brand card: three cinematically kerned rows in a font System 3 rolls off the
operator's collection, arriving and leaving with one of ten text animations System 3 rolls too - on EVERY
supercut (the SFX guy's hourly and custom cuts, and the pineEX supercut version of an hourly H3 render).

"for the supercut text, I want it to use a font rolled on the roulette from ... Fonts. I want the supercuts
to have the text with a cinematic kerning and a 2nd row with the station name and then a brand of the preset
on a row similar to the image." / "10 different cinematic text appearance animation effects that these
bounce between ... reveals, slow reveals and pop effects as entry and exit animations chosen at random by the
roulette."                                                                   (the operator, 2026-10-06)

The card, the font shelf, the cache, the ten effects, the frames and the one-pass ffmpeg burn are in the NEW
module supercut_brand.py (beside app.py; the integrator copies it in - this tool edits, it does not create).

Edits:
  app.py                  DEFAULT_DJ + dj_settings(): the `supercut_fonts_folder` setting (default "Fonts", under
                          SFX_ROOT unless absolute - the NAS moves, the operator points the setting there);
                          the [pineex-supercut] section: the import, supercut_fonts_folder / supercut_font_shelf
                          (listed only while the collection answers) / supercut_brand_roll (supercut.font,
                          supercut.text_in, supercut.text_out through s3_choice) / supercut_brand_plan (shelf on a
                          worker, dice on the loop, the pick cached once in data/fonts_cache) / h3_supercut_station /
                          h3_supercut_hour_note (the rolls onto the hour's rolodex entry, after the fact);
                          h3_supercut_caption -> the three rows; _h3_supercut_png -> the shared card;
                          h3_supercut_burn -> supercut_brand.prepare + burn (three overlays, one pass);
                          h3_supercut_version rolls, burns with the brand, keeps `font` and `brand` on the row.
  tools/pineex_supercut_patch.py
                          its NEW text carries the same section edits, so its --check still reads applied
                          (tests.test_pineex_supercut_2026_10_06.PatchApplied asserts that).
  tests/test_pineex_supercut_2026_10_06.py
                          the burn fakes take the brand; the caption test expects the three rows.
  sfx_supercut_video.py   render_video(..., brand=, station=): the frames beside the cuts, three overlays in the
                          mux pass; the result carries `brand`.
  sfx_supercut.py         render(): the brand from the host's supercut_brand_plan (app.py's globals), the plan
                          remembers it.
  sfx_supercut_archive.py record() keeps `brand`; decorate() surfaces an older row's from its plan.
  desktop/renderer/supercut-review.js + app/src/main/assets/pine-views/supercut-review.js (identical)
                          showArchive: "Set in <font> - arrives: <effect>, leaves: <effect>".

Usage:  supercut_brand_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        supercut_brand_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

# --- app.py: the setting -------------------------------------------------------------------------------------

DEFAULT_OLD = '''    "fordtape_folder": "samples_grabbed/user/ford",   # [h3-slots] General Ford's tapes (his submissions), for {fordtape}
'''
DEFAULT_NEW = '''    "fordtape_folder": "samples_grabbed/user/ford",   # [h3-slots] General Ford's tapes (his submissions), for {fordtape}
    "supercut_fonts_folder": "Fonts",   # [supercut-brand] the operator's font collection the supercut card's face is rolled from (under SFX_ROOT, or an absolute path)
'''

CLAMP_OLD = '''        "fordtape_folder": (str(raw_dj.get("fordtape_folder")             # [h3-slots]
                                or DEFAULT_DJ["fordtape_folder"])
                            .strip().strip("/")[:200]),
'''
CLAMP_NEW = '''        "fordtape_folder": (str(raw_dj.get("fordtape_folder")             # [h3-slots]
                                or DEFAULT_DJ["fordtape_folder"])
                            .strip().strip("/")[:200]),
        "supercut_fonts_folder": (str(raw_dj.get("supercut_fonts_folder")   # [supercut-brand] an absolute path keeps its slash
                                      or DEFAULT_DJ["supercut_fonts_folder"])
                                  .strip().rstrip("/")[:300]),
'''

# --- the [pineex-supercut] section (app.py AND the NEW text of tools/pineex_supercut_patch.py) ---------------

LOCK_OLD = '''_H3_SUPERCUT_LOCK = asyncio.Lock()         # one cut at a time: a restart's repair can land several
'''
LOCK_NEW = '''_H3_SUPERCUT_LOCK = asyncio.Lock()         # one cut at a time: a restart's repair can land several

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
'''

CAPTION_OLD = '''def h3_supercut_caption(rec: Any) -> list[str]:
    """[pineex-caption] What the bottom of the copy says: SUPERCUT, then the product the hour sold
    ("SUPERCUT + the product" - the operator, 2026-10-06)."""
    return [H3_SUPERCUT_CAPTION_WORD, h3_supercut_product(rec)[:80]]
'''
CAPTION_NEW = '''def h3_supercut_caption(rec: Any) -> list[str]:
    """[supercut-brand] The card's three rows: SUPERCUT, PINEBOX FM, the station's long name
    as the station setting has it ("a 2nd row with the station name and then a brand of the
    preset on a row" - the operator, 2026-10-06; the product line of [pineex-caption] gave
    way to the card; h3_supercut_product still reads what the hour sold)."""
    return _supercut_brand.lines(h3_supercut_station())
'''

PNG_OLD = '''def _h3_supercut_png(lines: list[str], width: int, height: int, out: Path) -> Path:
    """The caption strip as a PNG no wider than the picture, drawn with Pillow's
    bundled face (ImageFont.load_default(size=N) - no system font in the
    container; the gazette card's road): a dark band the size of the words,
    white text with a dark edge, centred. Disk and CPU - a worker thread."""
    from PIL import Image, ImageDraw, ImageFont  # type: ignore

    def font(size: int):  # noqa: ANN202
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    big = max(14, int(round(height * 0.055)))
    small = max(12, int(round(big * 0.72)))
    pad = max(6, big // 2)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))

    def measure(s: str, f: Any) -> float:
        try:
            return float(probe.textlength(s, font=f))
        except Exception:  # noqa: BLE001
            return len(s) * big * 0.55

    def wrap(s: str, f: Any, most: int = 2) -> list[str]:
        rows: list[str] = []
        cur = ""
        for word in str(s).split():
            trial = (cur + " " + word).strip()
            if measure(trial, f) <= width - 2 * pad or not cur:
                cur = trial
            else:
                rows.append(cur)
                cur = word
            if len(rows) >= most:
                break
        if cur and len(rows) < most:
            rows.append(cur)
        return rows

    rows: list[tuple[str, Any]] = []
    for ix, line in enumerate([x for x in lines if x][:3]):
        f = font(big if ix == 0 else small)
        rows.extend((row, f) for row in wrap(line, f))
    if not rows:
        rows = [(H3_SUPERCUT_STATION, font(big))]
    steps = [int(round(float(getattr(f, "size", big)) * 1.3)) for _r, f in rows]
    band_w = int(min(width, max(measure(r, f) for r, f in rows) + 2 * pad))
    band_h = int(sum(steps) + 2 * pad)
    img = Image.new("RGBA", (max(8, band_w), max(8, band_h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, band_w - 1, band_h - 1), fill=(0, 0, 0, 150))
    y = float(pad)
    for (row, f), step in zip(rows, steps):
        x = max(float(pad), (band_w - measure(row, f)) / 2)
        draw.text((x, y), row, font=f, fill=(255, 255, 255, 255),
                  stroke_width=max(1, big // 14), stroke_fill=(0, 0, 0, 255))
        y += step
    img.save(out)
    return out
'''
PNG_NEW = '''def _h3_supercut_png(lines: list[str], width: int, height: int, out: Path, font_path: Any = None) -> Path:
    """[supercut-brand] The finished card as a PNG exactly the picture's width: the shared
    three-row card (supercut_brand.card) in the given font, Pillow's bundled face when none
    loads - a still of the hold frame, for a probe or a test. Disk and CPU - a worker thread."""
    rows = [x for x in lines if x][:3] or [H3_SUPERCUT_STATION]
    img = _supercut_brand.card(rows, font_path, width, height)
    img.save(out)
    return out
'''

BURN_OLD = '''def h3_supercut_burn(source: Path, target: Path, lines: list[str], exe: str = "") -> dict[str, Any]:
    """The captioned copy: the strip laid over the picture, centred,
    H3_SUPERCUT_MARGIN_PX up from the bottom edge; the sound as it was (AAC
    in an mp4). One ffmpeg pass through the overlay filter - the container's
    imageio ffmpeg has no drawtext and no fonts. Blocking: a worker thread."""
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
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.stem + ".tmp" + target.suffix)
    strip = target.with_name(target.stem + ".caption.png")
    try:
        _h3_supercut_png(lines, width, height, strip)
        subprocess.run(
            [exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(source), "-i", str(strip),
             "-filter_complex",
             "[0:v:0][1:v:0]overlay=(main_w-overlay_w)/2:main_h-overlay_h-%d:format=auto,format=yuv420p[v]"
             % H3_SUPERCUT_MARGIN_PX,
             "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(temporary)],
            capture_output=True, timeout=max(30.0, H3_SUPERCUT_SECONDS - 30.0), check=True)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
        strip.unlink(missing_ok=True)
    return {"path": str(target), "size": [width, height], "lines": list(lines)}
'''
BURN_NEW = '''def h3_supercut_burn(source: Path, target: Path, lines: list[str], exe: str = "", brand: Any = None) -> dict[str, Any]:
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
'''

VERSION_CALL_OLD = '''            target = folder / ("%s-%s-supercut.mp4" % (folder.name, stem))
            await asyncio.wait_for(asyncio.to_thread(h3_supercut_burn, source, target, lines),
                                   timeout=H3_SUPERCUT_SECONDS)
'''
VERSION_CALL_NEW = '''            target = folder / ("%s-%s-supercut.mp4" % (folder.name, stem))
            # [supercut-brand] the font and the two text effects, System 3's, noted on the hour's rolodex
            brand = await supercut_brand_plan(pid, lambda key, opts, picked: h3_supercut_hour_note(rec, key, opts, picked))
            got = await asyncio.wait_for(asyncio.to_thread(h3_supercut_burn, source, target, lines, "", brand),
                                         timeout=H3_SUPERCUT_SECONDS)
'''

VERSION_MADE_OLD = '''            made = {"file": target.name, "path": str(target), "folder": folder.name, "sid": sfx_id(target),
                    "seconds": round(seconds, 3), "caption": lines, "booked": booked, "queued": queued,
                    "source": source.name, "at": round(time.time(), 3)}
'''
VERSION_MADE_NEW = '''            record = got.get("brand") if isinstance(got, dict) and isinstance(got.get("brand"), dict) else {
                "font": Path(brand["cached"]).stem if brand.get("cached") else _supercut_brand.DEFAULT_FACE,
                "effect_in": brand.get("effect_in"), "effect_out": brand.get("effect_out"), "seed": brand.get("seed")}
            made = {"file": target.name, "path": str(target), "folder": folder.name, "sid": sfx_id(target),
                    "seconds": round(seconds, 3), "caption": lines, "booked": booked, "queued": queued,
                    "source": source.name, "at": round(time.time(), 3),
                    "font": record.get("font"), "brand": record}                   # [supercut-brand] kept with the cut
'''

VERSION_LOG_OLD = '''            pipeline_log("ads", "supercut version (%s): %s - %.1f s, %s, %s" % (
                name, target.name, seconds,
                "in the clip book" if booked else "NOT in the clip book",
                "handed to the endless set" if queued else
                "not handed to the endless set (its door said no: four waiting, or on cooldown)"))
'''
VERSION_LOG_NEW = '''            pipeline_log("ads", "supercut version (%s): %s - %.1f s, %s, %s; set in %s, %s in / %s out" % (
                name, target.name, seconds,
                "in the clip book" if booked else "NOT in the clip book",
                "handed to the endless set" if queued else
                "not handed to the endless set (its door said no: four waiting, or on cooldown)",
                record.get("font"), record.get("effect_in_used") or record.get("effect_in"),
                record.get("effect_out_used") or record.get("effect_out")))          # [supercut-brand]
'''

SECTION_EDITS = [
    ("[supercut-brand] the import, the shelf, the three rolls, the plan, the hour note", LOCK_OLD, LOCK_NEW, 1),
    ("h3_supercut_caption: the three rows of the card", CAPTION_OLD, CAPTION_NEW, 1),
    ("_h3_supercut_png: the shared card, a still of the hold frame", PNG_OLD, PNG_NEW, 1),
    ("h3_supercut_burn: three overlays in one pass, the brand's font and effects", BURN_OLD, BURN_NEW, 1),
    ("h3_supercut_version: rolls the brand, burns with it", VERSION_CALL_OLD, VERSION_CALL_NEW, 1),
    ("h3_supercut_version: the row keeps font and brand", VERSION_MADE_OLD, VERSION_MADE_NEW, 1),
    ("h3_supercut_version: the log says the font and the effects", VERSION_LOG_OLD, VERSION_LOG_NEW, 1),
]

# --- tests/test_pineex_supercut_2026_10_06.py: the contract it asserts moved with the card ------------------

TEST_FAKE_OLD = '''        def fake_burn(source, target, lines, exe=""):
'''
TEST_FAKE_NEW = '''        def fake_burn(source, target, lines, exe="", brand=None):      # [supercut-brand] the plan rides along
'''
TEST_BROKEN_OLD = '''        def broken(source, target, lines, exe=""):
'''
TEST_BROKEN_NEW = '''        def broken(source, target, lines, exe="", brand=None):         # [supercut-brand]
'''
TEST_ROWS_OLD = '''        self.assertEqual(self.burns[0][2], ["SUPERCUT", "Pine Box FM"])   # [pineex-caption]
'''
TEST_ROWS_NEW = '''        self.assertEqual(self.burns[0][2], ["SUPERCUT", "PINEBOX FM", "Pine Box FM"])   # [supercut-brand] three rows
'''
TEST_CAPTION_OLD = '''    def test_the_caption_is_supercut_and_the_product(self):
        """[pineex-caption] "SUPERCUT + the product" (the operator)."""
        caption = self.ns["h3_supercut_caption"]
        row = pineex_row()
        row["h3_prompts"]["direction"] = ('A music video. What is sold tonight is the product "Pine Box FM Vinyl Record Holder" '
                                          '- it keeps the records upright. Sing it.')
        self.assertEqual(caption(row), ["SUPERCUT", "Pine Box FM Vinyl Record Holder"], "the product the hour sold")
        row["h3_prompts"]["direction"] = 'Tonight it is the Pine Box feature "One press builds the PineTab" [tablet-update-ask] - pitch it.'
        self.assertEqual(caption(row), ["SUPERCUT", "One press builds the PineTab"], "a feature when the offer rolled one")
        self.assertEqual(caption(pineex_row()), ["SUPERCUT", "Pine Box FM"], "nothing sold in the words: the station")
        self.assertEqual(caption({}), ["SUPERCUT", "Pine Box FM"])
'''
TEST_CAPTION_NEW = '''    def test_the_caption_is_the_three_row_brand_card(self):
        """[supercut-brand] SUPERCUT / PINEBOX FM / the station's long name (the operator, 2026-10-06);
        the product line of [pineex-caption] gave way to the card. h3_supercut_product still reads the hour."""
        caption = self.ns["h3_supercut_caption"]
        row = pineex_row()
        row["h3_prompts"]["direction"] = ('A music video. What is sold tonight is the product "Pine Box FM Vinyl Record Holder" '
                                          '- it keeps the records upright. Sing it.')
        self.assertEqual(self.ns["h3_supercut_product"](row), "Pine Box FM Vinyl Record Holder", "the product the hour sold")
        self.assertEqual(caption(row), ["SUPERCUT", "PINEBOX FM", "Pine Box FM"], "no station setting: the short name")
        self.ns["dj_settings"] = lambda: {"station_name": "Chicken Tendo Little Pine Box FM Station"}
        self.assertEqual(caption(row), ["SUPERCUT", "PINEBOX FM", "Chicken Tendo Little Pine Box FM Station"],
                         "the station setting's long name on the third row")
        self.assertEqual(caption({}), ["SUPERCUT", "PINEBOX FM", "Chicken Tendo Little Pine Box FM Station"])
'''
TEST_BAND_OLD = '''        self.assertGreater(bottom, top * 4 + 10, "the caption changed the bottom of the picture")
'''
TEST_BAND_NEW = '''        self.assertGreater(bottom, top * 4 + 3, "the card changed the bottom of the picture")   # [supercut-brand] light letters, no dark band
'''

# --- sfx_supercut_video.py: the hourly and custom road ------------------------------------------------------

VIDEO_IMPORT_OLD = '''import tempfile
from pathlib import Path
'''
VIDEO_IMPORT_NEW = '''import tempfile
from pathlib import Path

import supercut_brand                  # [supercut-brand] the three-row card, its font and its entry / exit frames
'''
VIDEO_SIG_OLD = '''def render_video(plan, result, output, executable):
    """Cut the same measured source intervals as the audio, then mux that audio."""
'''
VIDEO_SIG_NEW = '''def render_video(plan, result, output, executable, *, brand=None, station=''):
    """Cut the same measured source intervals as the audio, then mux that audio - with the
    brand card over the picture ([supercut-brand]: its entry, hold and exit, three overlays
    in the mux pass). `brand` is the station's supercut_brand_plan dict (the cached font, the
    two rolled effects, the seed); `station` the long name on the card's third row."""
'''
VIDEO_MUX_OLD = '''            listing = folder / 'cuts.txt'
            listing.write_text(''.join(f"file '{ix}.mp4'\\n" for ix in range(len(cues))), encoding='utf-8')
            run(['-f', 'concat', '-safe', '0', '-i', str(listing), '-i', str(result['path']),
                 '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
                 '-t', f"{float(result['seconds']):.6f}", '-movflags', '+faststart', str(temporary)])
'''
VIDEO_MUX_NEW = '''            listing = folder / 'cuts.txt'
            listing.write_text(''.join(f"file '{ix}.mp4'\\n" for ix in range(len(cues))), encoding='utf-8')
            # [supercut-brand] the card: its entry, hold and exit rendered as frames beside the cuts and laid
            # over the picture in the mux pass - three overlays, each in its window, 10 px up from the bottom
            plan_brand = dict(brand or {})
            seed = int(plan_brand.get('seed') or supercut_brand.seed_for(plan.get('id') or output.stem))
            if not plan_brand.get('effect_in') or not plan_brand.get('effect_out'):
                plan_brand['effect_in'], plan_brand['effect_out'] = supercut_brand.roll_effects(None, None, seed)
            font = plan_brand.get('cached') or plan_brand.get('font_path') or ''
            lines = supercut_brand.lines(station or (plan.get('config') or {}).get('station') or 'Pine Box FM')
            prep = supercut_brand.prepare(lines, font, 640, 360, float(result['seconds']), plan_brand['effect_in'],
                                          plan_brand['effect_out'], folder / 'brand', seed=seed)
            inputs, graph = supercut_brand.overlay_graph(prep, first_input=2)
            run(['-f', 'concat', '-safe', '0', '-i', str(listing), '-i', str(result['path']), *inputs,
                 '-filter_complex', graph, '-map', '[v]', '-map', '1:a:0',
                 '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-c:a', 'aac', '-b:a', '128k',
                 '-t', f"{float(result['seconds']):.6f}", '-movflags', '+faststart', str(temporary)])
            record = supercut_brand.record_of(prep, plan_brand.get('font_path') or font, plan_brand.get('cached') or '',
                                              lines, plan_brand['effect_in'], plan_brand['effect_out'],
                                              rolled=bool(plan_brand.get('rolled')))
'''
VIDEO_RETURN_OLD = '''        return {**facts, 'kind': 'video', 'video': output.name, 'video_path': str(output),
                'video_source_only': True}
'''
VIDEO_RETURN_NEW = '''        return {**facts, 'kind': 'video', 'video': output.name, 'video_path': str(output),
                'video_source_only': True, 'brand': record}                        # [supercut-brand]
'''

# --- sfx_supercut.py: render() takes the brand from the host --------------------------------------------------

RENDER_OLD = '''            video = await asyncio.to_thread(render_video, plan, result, output.with_suffix(".mp4"), imageio_ffmpeg.get_ffmpeg_exe())
            result.update(video)
            result["source_plan"].update(video=video["video"], video_sha256=video["video_sha256"], video_source_only=True)
'''
RENDER_NEW = '''            brand_plan = self.host.get("supercut_brand_plan")      # [supercut-brand] app.py's: the font and the effects, System 3's
            brand = await brand_plan(str(plan["id"])) if callable(brand_plan) else None
            station = str((brand or {}).get("station") or (plan.get("config") or {}).get("station") or "Pine Box FM")
            video = await asyncio.to_thread(render_video, plan, result, output.with_suffix(".mp4"), imageio_ffmpeg.get_ffmpeg_exe(),
                                            brand=brand, station=station)
            result.update(video)
            result["source_plan"].update(video=video["video"], video_sha256=video["video_sha256"], video_source_only=True,
                                         brand=video.get("brand") or {})           # [supercut-brand] the plan remembers the card
'''

# --- sfx_supercut_archive.py ---------------------------------------------------------------------------------

ARCHIVE_RECORD_OLD = '''                 'occurrence': str(plan.get('occurrence') or ''), 'autoplay': False}
'''
ARCHIVE_RECORD_NEW = '''                 'occurrence': str(plan.get('occurrence') or ''), 'autoplay': False}
        brand = plan.get('brand') or result.get('brand')                   # [supercut-brand] the font, the effects
        if isinstance(brand, dict) and brand:
            value['brand'] = copy.deepcopy(brand)
'''
ARCHIVE_DECORATE_OLD = '''        value['reusable_ad_id'] = str(row['reusable_ad_id'] or '')
'''
ARCHIVE_DECORATE_NEW = '''        value['reusable_ad_id'] = str(row['reusable_ad_id'] or '')
        if not isinstance(value.get('brand'), dict):                        # [supercut-brand] an older row: its plan's
            plan = value.get('source_plan') if isinstance(value.get('source_plan'), dict) else {}
            if isinstance(plan.get('brand'), dict) and plan['brand']:
                value['brand'] = plan['brand']
'''

# --- the studio (both copies) --------------------------------------------------------------------------------

JS_OLD = '''      audio = make(row.video_url ? 'video' : 'audio', 'psc-audio'); audio.controls = true; audio.preload = 'none'; audio.autoplay = false;
'''
JS_NEW = '''      if (row.brand && row.brand.font) {   /* [supercut-brand] the font the card is set in, and how it arrives and leaves */
        var arrives = row.brand.effect_in_used || row.brand.effect_in, leaves = row.brand.effect_out_used || row.brand.effect_out;
        resultBody.append(make('p', 'psc-hint psc-brand', 'Set in ' + row.brand.font + (arrives ? ' - arrives: ' + arrives + ', leaves: ' + leaves : '')));
      }
      audio = make(row.video_url ? 'video' : 'audio', 'psc-audio'); audio.controls = true; audio.preload = 'none'; audio.autoplay = false;
'''

EDITS = {
    "app.py": [
        ("DEFAULT_DJ: supercut_fonts_folder", DEFAULT_OLD, DEFAULT_NEW, 1),
        ("dj_settings(): the setting is kept on every save", CLAMP_OLD, CLAMP_NEW, 1),
        *SECTION_EDITS,
    ],
    "tools/pineex_supercut_patch.py": [
        (label + " (the pineEX tool's NEW text)", old, new, 1) for label, old, new, _n in SECTION_EDITS
    ],
    "tests/test_pineex_supercut_2026_10_06.py": [
        ("the burn fake takes the brand", TEST_FAKE_OLD, TEST_FAKE_NEW, 1),
        ("the broken burn fake takes the brand", TEST_BROKEN_OLD, TEST_BROKEN_NEW, 1),
        ("the road test expects the three rows", TEST_ROWS_OLD, TEST_ROWS_NEW, 1),
        ("the caption test expects the three-row card", TEST_CAPTION_OLD, TEST_CAPTION_NEW, 1),
        ("the real burn's band threshold: light letters, no dark band", TEST_BAND_OLD, TEST_BAND_NEW, 1),
    ],
    "sfx_supercut_video.py": [
        ("import supercut_brand", VIDEO_IMPORT_OLD, VIDEO_IMPORT_NEW, 1),
        ("render_video takes brand= and station=", VIDEO_SIG_OLD, VIDEO_SIG_NEW, 1),
        ("the mux pass lays the card's entry, hold and exit over the picture", VIDEO_MUX_OLD, VIDEO_MUX_NEW, 1),
        ("the result carries the brand record", VIDEO_RETURN_OLD, VIDEO_RETURN_NEW, 1),
    ],
    "sfx_supercut.py": [
        ("render(): the brand from the host's supercut_brand_plan; the plan remembers it", RENDER_OLD, RENDER_NEW, 1),
    ],
    "sfx_supercut_archive.py": [
        ("record() keeps the brand", ARCHIVE_RECORD_OLD, ARCHIVE_RECORD_NEW, 1),
        ("decorate() surfaces an older row's brand from its plan", ARCHIVE_DECORATE_OLD, ARCHIVE_DECORATE_NEW, 1),
    ],
    "desktop/renderer/supercut-review.js": [
        ("showArchive: Set in <font> - arrives / leaves", JS_OLD, JS_NEW, 1),
    ],
    "app/src/main/assets/pine-views/supercut-review.js": [
        ("showArchive: Set in <font> - arrives / leaves (the tablet's identical copy)", JS_OLD, JS_NEW, 1),
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
        tmp = path.with_suffix(path.suffix + ".supercutbrand.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
