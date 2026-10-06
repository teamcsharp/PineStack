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


def h3_supercut_caption(rec: Any) -> list[str]:
    """What the bottom of the copy says: the line the render sings (the hour's
    speech after filling, else the record it sings to) and the station - the
    station once, so a line that already ends on its name is not doubled."""
    words = rec.get("h3_prompts") if isinstance(rec, dict) and isinstance(rec.get("h3_prompts"), dict) else {}
    line = " ".join(str(words.get("speech") or (rec or {}).get("speech") or words.get("record") or "").split())
    out = [line[:160]] if line else []
    if not line or not line.rstrip(" .!?").lower().endswith(H3_SUPERCUT_STATION.lower()):
        out.append(H3_SUPERCUT_STATION)
    return out


def h3_supercut_folder(name: str) -> Path:
    """The clip folder the copies live in: the writable samples root, named for
    the preset (pineEX -> data/samples/pineEX). The book's folder column reads
    that name, so the SFX guy's book lists the copies under it."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(name or "").strip()).strip("-")[:40] or H3_SUPERCUT_WORD
    return SFX_LOCAL_ROOT / slug


def _h3_supercut_png(lines: list[str], width: int, height: int, out: Path) -> Path:
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


def h3_supercut_burn(source: Path, target: Path, lines: list[str], exe: str = "") -> dict[str, Any]:
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
            await asyncio.wait_for(asyncio.to_thread(h3_supercut_burn, source, target, lines),
                                   timeout=H3_SUPERCUT_SECONDS)
            seconds = float(await asyncio.to_thread(_media_duration_probe, target) or 0.0)
            booked = bool(await asyncio.to_thread(sfx_db_write_row, target, seconds, 1 if seconds > 0 else 0))
            queued = bool(sfx_cycle_request(target, name, "the supercut version of this hour's %s render" % name))
            made = {"file": target.name, "path": str(target), "folder": folder.name, "sid": sfx_id(target),
                    "seconds": round(seconds, 3), "caption": lines, "booked": booked, "queued": queued,
                    "source": source.name, "at": round(time.time(), 3)}
            await update_generation(pid, supercut_version=made)
            pipeline_log("ads", "supercut version (%s): %s - %.1f s, %s, %s" % (
                name, target.name, seconds,
                "in the clip book" if booked else "NOT in the clip book",
                "handed to the endless set" if queued else
                "not handed to the endless set (its door said no: four waiting, or on cooldown)"))
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
