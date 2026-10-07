"""[supercut-brand] THE BRAND CARD EVERY SUPERCUT WEARS, AND HOW IT ARRIVES AND LEAVES.

"for the supercut text, I want it to use a font rolled on the roulette from the
Fonts folder ... the text with a cinematic kerning and a 2nd row with the
station name and then a brand of the preset on a row"
"with each supercut video I want the text overlay to have a unique text
transition effect animation ... 10 different cinematic text appearance
animation effects that these bounce between ... reveals, slow reveals and pop
effects as entry and exit animations chosen at random by the roulette."
                                                   (the operator, 2026-10-06)

THE CARD. Three rows, each centred, light grey (#dcdcdc) with a soft dark
shadow, no box, on the lower part of the picture:

  row 1   SUPERCUT                  size width/11, tracking 0.42 em, upper case
  row 2   PINEBOX FM                size width/26, tracking 0.38 em, upper case
  row 3   the station's long name   size width/34, tracking 0.12 em, as written

The tracking is drawn character by character (Pillow has no letter-spacing);
a row wider than the picture less two side margins is shrunk until it fits; the
card is as tall as the rows need (rows 0.35 of row 3's size apart) and never
taller than half the picture. Every character is rendered ONCE to its own RGBA
tile (ink + shadow), and the frames below move, scale, fade, mask or blur those
tiles - so a whole entry is a few dozen cheap composites.

THE FONT. One per cut, rolled by System 3 over the operator's collection
(font_shelf lists .ttf/.otf one level deep, only while the collection is
reachable), copied once into a local cache (cache_font) so the burn never
touches the share; a font that will not load falls back to Pillow's bundled
face and the record says so (brand_record).

THE EFFECTS. Ten named entries, each with its matching exit (EFFECTS, EFFECT_SAY,
EXIT_SAY). System 3 rolls the entry (supercut.text_in) and the exit
(supercut.text_out) separately; the frames are deterministic for a seed.
entry_frames() ends on the finished card, exit_frames() starts from it, and the
hold frame between them is that card - so the burn is three overlays:

  entry   an image2 sequence, offset to ENTRY_AT seconds into the clip
  hold    one PNG looped for the time between
  exit    an image2 sequence, offset to end EXIT_GAP seconds before the clip ends

each overlay centred, MARGIN_PX up from the bottom edge, enabled only in its
window (overlay_graph builds the inputs and the filter; burn runs one ffmpeg
pass for a finished mp4). A clip with little room shortens the hold first,
then takes the short pair (pop in, a quick fade out), then the card alone; a
clip under SHORT_CLIP seconds simply wears the card from its first frame.

Pure: no station imports; the dice, the clock and the ffmpeg runner are
injected. Pillow is imported inside the functions that draw.
"""
from __future__ import annotations

import math
import os
import random
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Sequence

WORD = "SUPERCUT"
STATION_SHORT = "PINEBOX FM"
STATION_FALLBACK = "Pine Box FM"
FONT_TYPES = (".ttf", ".otf")
# (size as a fraction of the picture's width, tracking in em, upper case)
ROWS = ((1 / 11.0, 0.42, True), (1 / 26.0, 0.38, True), (1 / 34.0, 0.12, False))
INK = (220, 220, 220, 255)
SHADOW = (0, 0, 0, 153)              # 60 % black
SHADOW_PX = 2
SHADOW_BLUR = 1.2
GAP = 0.35                           # between rows, of row 3's size
SIDE = 0.05                          # each side margin, of the width
TALLEST = 0.5                        # the card is never taller than this of the picture
MARGIN_PX = 10                       # the burn: the card's distance from the bottom edge
FPS = 24
ENTRY_AT = 0.4                       # the entry starts this far into the clip
EXIT_GAP = 0.3                       # the exit ends this far before the clip ends
MIN_SIZE = 3                         # the smallest face a row is shrunk to (a tiny preview picture may need it)
SHORT_CLIP = 2.0                     # under this, the card is simply on from the first frame
MIN_HOLD = 0.5                       # less hold than this: the short pair, then the card alone
ROOMY_HOLD = 2.0                     # less than this is a shortened hold, and the record says so
DEFAULT_FACE = "Pillow default"
FLIP_ONE = 0.35                      # one character's flip
TYPE_ONE = 0.03                      # the typewriter's step
EFFECTS = ("flip_chars", "drop_bounce", "rise_settle", "typewriter", "slow_reveal",
           "wipe", "pop", "blur_in", "scatter", "glitch")
EFFECT_SAY = {
    "flip_chars": "each character flips in one by one, scale-x through zero",
    "drop_bounce": "the rows drop in from above the top edge and bounce to rest",
    "rise_settle": "the rows rise from below and settle",
    "typewriter": "character by character, fast",
    "slow_reveal": "a slow 2.5 s fade while the tracking eases open",
    "wipe": "a left-to-right wipe uncovers the card",
    "pop": "each row pops from nothing with an overshoot",
    "blur_in": "the card comes into focus as its blur eases to zero",
    "scatter": "the characters fly in from scattered places to their own",
    "glitch": "horizontal slices jitter and flicker, then lock",
}
EXIT_SAY = {
    "flip_chars": "flip-out, character by character",
    "drop_bounce": "drop-out below the bottom edge",
    "rise_settle": "sink back down",
    "typewriter": "erased character by character from the end",
    "slow_reveal": "fade out as the tracking widens",
    "wipe": "wiped away left to right",
    "pop": "pop-out to nothing",
    "blur_in": "blur out",
    "scatter": "scatter-out to the winds",
    "glitch": "glitch apart and flicker out",
}
EXIT_SECONDS = {"flip_chars": 1.0, "drop_bounce": 0.8, "rise_settle": 0.8, "typewriter": 0.9,
                "slow_reveal": 1.0, "wipe": 0.9, "pop": 0.5, "blur_in": 0.9, "scatter": 1.1, "glitch": 0.8}
SHORT_IN, SHORT_OUT, SHORT_OUT_SECONDS = "pop", "slow_reveal", 0.5     # the pair for a clip with little room
KEY_FONT, KEY_IN, KEY_OUT = "supercut.font", "supercut.text_in", "supercut.text_out"
LABEL_FONT = "which font the supercut's brand card is set in"
LABEL_IN = "which entry animation the supercut's brand card arrives with"
LABEL_OUT = "which exit animation the supercut's brand card leaves with"


# --- the words -------------------------------------------------------------------------------

def lines(station_long: Any) -> list[str]:
    """The three rows: SUPERCUT, the station's short brand, the station's long name as written."""
    long_name = " ".join(str(station_long or "").split())[:80] or STATION_FALLBACK
    return [WORD, STATION_SHORT, long_name]


# --- the font --------------------------------------------------------------------------------

def font_shelf(folder: Any, reachable: bool = True, most: int = 600) -> list[Path]:
    """Every .ttf/.otf in the folder and one level of subfolders, sorted; [] when the
    collection is not reachable or the folder is not there. scandir, not stat-per-file:
    the folder is a CIFS share (call this on a worker thread, never on the loop)."""
    if not reachable or not folder:
        return []
    root = Path(folder)
    found: list[Path] = []

    def take(where: Path, deeper: bool) -> None:
        try:
            with os.scandir(str(where)) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            if Path(entry.name).suffix.lower() in FONT_TYPES:
                                found.append(Path(entry.path))
                        elif deeper and entry.is_dir(follow_symlinks=False):
                            take(Path(entry.path), False)
                    except OSError:
                        continue
        except OSError:
            return
    take(root, True)
    return sorted(found, key=lambda p: str(p).lower())[:max(1, int(most))]


def font_labels(shelf: Sequence[Path]) -> list[str]:
    """One label per font for the dice: the stem, prefixed by its subfolder when it has
    one (BankGothic Bold/BankGothic), the suffix added when two still collide."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for path in shelf:
        path = Path(path)
        label = path.stem
        parent = path.parent.name
        if parent and any(Path(p).stem == path.stem and Path(p) != path for p in shelf):
            label = parent + "/" + path.stem
        if label in seen:
            label = label + path.suffix.lower()
        n = seen.get(label, 0)
        seen[label] = n + 1
        out.append(label if n == 0 else "%s (%d)" % (label, n + 1))
    return out


def roll_font(shelf: Sequence[Path], choose: Callable[[list[str]], Any] | None, note: Callable[..., Any] | None = None,
              seed: int = 0) -> Path | None:
    """The one font this cut is set in: `choose` (the station's die over the labels) names
    it; with no die a seeded draw stands in. `note(labels, picked)` hears the roll.
    None when the shelf is empty."""
    paths = [Path(p) for p in (shelf or [])]
    if not paths:
        return None
    labels = font_labels(paths)
    picked: Any = None
    if callable(choose):
        try:
            picked = choose(list(labels))
        except Exception:  # noqa: BLE001 - a die that fails leaves the seeded draw
            picked = None
    index = None
    if isinstance(picked, int) and 0 <= picked < len(labels):
        index = picked
    elif isinstance(picked, str) and picked in labels:
        index = labels.index(picked)
    if index is None:
        index = random.Random(int(seed)).randrange(len(labels))
    if callable(note):
        try:
            note(list(labels), labels[index])
        except Exception:  # noqa: BLE001 - the note never costs the cut its font
            pass
    return paths[index]


def safe_stem(stem: str) -> str:
    return (re.sub(r"[^A-Za-z0-9._ -]+", "-", str(stem or "")).strip(" .-")[:80]) or "font"


def cache_font(path: Any, cache_dir: Any) -> Path:
    """A local copy of the font, by stem and suffix, copied once (again only when the
    source's size differs): the burn reads THIS file, never the share."""
    source = Path(path)
    folder = Path(cache_dir)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (safe_stem(source.stem) + source.suffix.lower())
    try:
        want = source.stat().st_size
        if target.is_file() and target.stat().st_size == want and want > 0:
            return target
    except OSError:
        pass
    tmp = target.with_name(target.name + ".tmp")
    try:
        shutil.copyfile(str(source), str(tmp))
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def load_face(font_path: Any, size: int) -> tuple[Any, bool, str]:
    """(font, fell_back, why): the TrueType/OpenType face at this size, else Pillow's
    bundled face and the reason."""
    from PIL import ImageFont  # type: ignore
    size = max(MIN_SIZE, int(round(size)))
    why = ""
    if font_path:
        try:
            return ImageFont.truetype(str(font_path), size), False, ""
        except (OSError, ValueError, TypeError) as exc:
            why = "%s: %s" % (type(exc).__name__, str(exc)[:100])
    try:
        return ImageFont.load_default(size=size), True, why
    except TypeError:
        return ImageFont.load_default(), True, why


def brand_record(font: Any, cached: Any, fell_back: bool, why: str = "", **more: Any) -> dict[str, Any]:
    """What the archive row and the hour's record keep of the card: the font (its stem, or
    the default face), its file on the shelf, the cached copy the burn read, whether the
    face fell back and why - plus whatever the road adds (lines, effects, seed, timing)."""
    path = Path(font) if font else None
    rec: dict[str, Any] = {
        "font": (path.stem if path and not fell_back else DEFAULT_FACE),
        "font_file": str(path) if path else "",
        "cached": str(cached) if cached else "",
        "fell_back": bool(fell_back),
        "why": str(why or ("" if path else "no font on the shelf")),
    }
    if path and fell_back and not why:
        rec["why"] = "the font did not load"
    if path and fell_back:
        rec["rolled_font"] = path.stem
    rec.update(more)
    return rec


# --- the rows and the layout -----------------------------------------------------------------

def rows(lines_: Sequence[Any], width: int) -> list[dict[str, Any]]:
    """The three rows with their own size and tracking for a picture this wide."""
    out = []
    for text, (frac, tracking, upper) in zip(list(lines_ or [])[:3], ROWS):
        text = " ".join(str(text or "").split())
        if upper:
            text = text.upper()
        if text:
            out.append({"text": text, "size": max(MIN_SIZE, int(round(width * frac))), "tracking": tracking, "upper": upper})
    return out


class Glyph:
    __slots__ = ("char", "row", "index", "x", "y", "tile", "cx", "cy")

    def __init__(self, char: str, row: int, index: int, x: int, y: int, tile: Any) -> None:
        self.char, self.row, self.index, self.x, self.y, self.tile = char, row, index, x, y, tile
        self.cx = x + tile.width / 2.0
        self.cy = y + tile.height / 2.0


class Layout:
    """The card's geometry: the picture's width, the card's height, the rows (text, size,
    top, height, centre) and every character's tile and place."""

    def __init__(self) -> None:
        self.width = 0
        self.height = 0
        self.rows: list[dict[str, Any]] = []
        self.glyphs: list[Glyph] = []
        self.fell_back = False
        self.why = ""
        self.font_path = ""
        self.pad = 0

    def row_glyphs(self, row: int) -> list[Glyph]:
        return [g for g in self.glyphs if g.row == row]


def _measure(probe: Any, text: str, font: Any) -> float:
    try:
        return float(probe.textlength(text, font=font))
    except Exception:  # noqa: BLE001 - a bitmap face without textlength
        try:
            box = font.getbbox(text)
            return float(box[2] - box[0])
        except Exception:  # noqa: BLE001
            return 0.6 * float(getattr(font, "size", 10)) * len(text)


def _metrics(font: Any, size: int) -> tuple[int, int]:
    try:
        ascent, descent = font.getmetrics()
        return int(ascent), int(descent)
    except Exception:  # noqa: BLE001
        return int(round(size * 0.8)), int(round(size * 0.25))


def layout(rows_: Sequence[Any], font_path: Any, width: int, height: int) -> Layout:
    """Fit the rows to the picture and render every character's tile once. `rows_` is the
    list rows() makes, or the three plain lines."""
    from PIL import Image, ImageDraw, ImageFilter  # type: ignore
    width = max(16, int(width))
    height = max(16, int(height))
    specs = list(rows_ or [])
    if specs and not isinstance(specs[0], dict):
        specs = rows(specs, width)
    lay = Layout()
    lay.width = width
    lay.font_path = str(font_path or "")
    pad = SHADOW_PX + int(math.ceil(SHADOW_BLUR * 3)) + 1
    lay.pad = pad
    limit = width - 2 * max(8, int(round(width * SIDE)))
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))

    def fit(spec: dict[str, Any], size: int) -> dict[str, Any]:
        """The face at a size the row fits the width at."""
        for _ in range(12):
            font, fell, why = load_face(font_path, size)
            adv = [_measure(probe, ch, font) for ch in spec["text"]]
            track = spec["tracking"] * size
            row_w = sum(adv) + track * max(0, len(adv) - 1)
            if row_w <= limit or size <= MIN_SIZE:
                break
            size = max(MIN_SIZE, int(size * min(0.95, limit / max(1.0, row_w))))
        ascent, descent = _metrics(font, size)
        return {"spec": spec, "font": font, "size": size, "adv": adv, "width": row_w, "track": track,
                "ascent": ascent, "descent": descent, "fell": fell, "why": why}

    fitted = [fit(spec, int(spec["size"])) for spec in specs]
    if fitted:
        gap = GAP * fitted[-1]["size"]
        total = sum(f["ascent"] + f["descent"] for f in fitted) + gap * (len(fitted) - 1) + 2 * pad
        if total > TALLEST * height:
            k = (TALLEST * height) / total
            fitted = [fit(f["spec"], max(MIN_SIZE, int(f["size"] * k))) for f in fitted]
    lay.fell_back = any(f["fell"] for f in fitted)
    lay.why = next((f["why"] for f in fitted if f["why"]), "")
    y = float(pad)
    gap = GAP * fitted[-1]["size"] if fitted else 0.0
    index = 0
    for r, f in enumerate(fitted):
        font, spec = f["font"], f["spec"]
        row_h = f["ascent"] + f["descent"]
        pen = (width - f["width"]) / 2.0
        top = int(round(y))
        lay.rows.append({"text": spec["text"], "size": f["size"], "tracking": spec["tracking"], "top": top,
                         "height": row_h, "x0": pen, "x1": pen + f["width"], "cx": width / 2.0, "cy": top + row_h / 2.0,
                         "width": f["width"]})
        for ch, adv in zip(spec["text"], f["adv"]):
            if not ch.isspace():
                try:
                    l, t, rgt, b = font.getbbox(ch)
                except Exception:  # noqa: BLE001
                    l, t, rgt, b = 0, 0, int(adv), row_h
                if rgt > l and b > t:
                    tile = Image.new("RGBA", (int(rgt - l) + 2 * pad, int(b - t) + 2 * pad), (0, 0, 0, 0))
                    shade = tile.copy()
                    ImageDraw.Draw(shade).text((pad - l + SHADOW_PX, pad - t + SHADOW_PX), ch, font=font, fill=SHADOW)
                    shade = shade.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
                    ImageDraw.Draw(tile).text((pad - l, pad - t), ch, font=font, fill=INK)
                    tile = Image.alpha_composite(shade, tile)
                    lay.glyphs.append(Glyph(ch, r, index, int(round(pen)) + l - pad, top + t - pad, tile))
                    index += 1
            pen += adv + f["track"]
        y += row_h + gap
    lay.height = int(math.ceil(y - gap + pad)) if fitted else 2 * pad
    lay.height = max(8, lay.height)
    return lay


# --- compositing -----------------------------------------------------------------------------

def _blit(canvas: Any, tile: Any, x: int, y: int) -> None:
    """Composite the tile at (x, y), clipped to the canvas (negative and overhanging places allowed)."""
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(canvas.width, x + tile.width), min(canvas.height, y + tile.height)
    if x1 <= x0 or y1 <= y0:
        return
    if (x0, y0, x1, y1) != (x, y, x + tile.width, y + tile.height):
        tile = tile.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    canvas.alpha_composite(tile, dest=(x0, y0))


def _faded(tile: Any, alpha: float) -> Any:
    alpha = max(0.0, min(1.0, float(alpha)))
    if alpha >= 0.999:
        return tile
    out = tile.copy()
    out.putalpha(tile.getchannel("A").point(lambda v: int(v * alpha)))
    return out


def compose(lay: Layout, place: Callable[[Glyph], Any] | None = None) -> Any:
    """The card from its tiles. `place(glyph)` returns None (not drawn) or
    (dx, dy, alpha, scale_x, scale_y) - the finished card when place is None."""
    from PIL import Image  # type: ignore
    canvas = Image.new("RGBA", (lay.width, lay.height), (0, 0, 0, 0))
    for g in lay.glyphs:
        if place is None:
            _blit(canvas, g.tile, g.x, g.y)
            continue
        got = place(g)
        if got is None:
            continue
        dx, dy, alpha, sx, sy = got
        if alpha <= 0.002 or sx <= 0.002 or sy <= 0.002:
            continue
        tile = g.tile
        if abs(sx - 1.0) > 1e-6 or abs(sy - 1.0) > 1e-6:
            nw, nh = max(1, int(round(tile.width * sx))), max(1, int(round(tile.height * sy)))
            tile = tile.resize((nw, nh), Image.Resampling.BILINEAR)
            x = int(round(g.x + dx + (g.tile.width - nw) / 2.0))
            y = int(round(g.y + dy + (g.tile.height - nh) / 2.0))
        else:
            x, y = int(round(g.x + dx)), int(round(g.y + dy))
        if alpha < 0.999:
            tile = _faded(tile, alpha)
        _blit(canvas, tile, x, y)
    return canvas


def card(rows_: Sequence[Any], font_path: Any, width: int, height: int) -> Any:
    """The finished card (the hold frame) as an RGBA image exactly the picture's width.
    img.info carries fell_back and why."""
    lay = rows_ if isinstance(rows_, Layout) else layout(rows_, font_path, width, height)
    img = compose(lay)
    img.info["fell_back"] = lay.fell_back
    img.info["why"] = lay.why
    img.info["rows"] = [dict(r) for r in lay.rows]
    return img


# --- easing ----------------------------------------------------------------------------------

def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else float(x)


def ease_out_cubic(p: float) -> float:
    p = clamp01(p)
    return 1 - (1 - p) ** 3


def ease_in_cubic(p: float) -> float:
    p = clamp01(p)
    return p ** 3


def ease_in_out(p: float) -> float:
    p = clamp01(p)
    return 0.5 - 0.5 * math.cos(math.pi * p)


def ease_out_back(p: float, s: float = 1.70158) -> float:
    p = clamp01(p) - 1
    return 1 + p * p * ((s + 1) * p + s)


def ease_out_bounce(p: float) -> float:
    p = clamp01(p)
    n1, d1 = 7.5625, 2.75
    if p < 1 / d1:
        return n1 * p * p
    if p < 2 / d1:
        p -= 1.5 / d1
        return n1 * p * p + 0.75
    if p < 2.5 / d1:
        p -= 2.25 / d1
        return n1 * p * p + 0.9375
    p -= 2.625 / d1
    return n1 * p * p + 0.984375


# --- the ten effects -------------------------------------------------------------------------

def entry_seconds(effect: str, lay: Layout) -> float:
    n = max(1, len(lay.glyphs))
    r = max(1, len(lay.rows))
    if effect == "flip_chars":
        return round(FLIP_ONE + min(0.04, 1.3 / max(1, n - 1)) * (n - 1), 3)
    if effect == "drop_bounce":
        return round(1.0 + 0.15 * (r - 1), 3)
    if effect == "rise_settle":
        return round(0.9 + 0.12 * (r - 1), 3)
    if effect == "typewriter":
        return round(min(TYPE_ONE, 1.4 / n) * n + 0.15, 3)
    if effect == "slow_reveal":
        return 2.5
    if effect == "wipe":
        return 1.2
    if effect == "pop":
        return round(0.6 + 0.12 * (r - 1), 3)
    if effect == "blur_in":
        return 1.5
    if effect == "scatter":
        return 1.4
    if effect == "glitch":
        return 1.0
    return 1.0


def exit_seconds(effect: str, lay: Layout | None = None) -> float:
    return float(EXIT_SECONDS.get(effect, 0.8))


def _scatter_places(lay: Layout, seed: int) -> dict[int, tuple[float, float, float]]:
    rng = random.Random(("scatter", int(seed)).__repr__())
    out = {}
    for g in lay.glyphs:
        out[g.index] = (rng.uniform(-0.45, 0.45) * lay.width, rng.uniform(-1.2, 1.2) * lay.height, rng.uniform(0.0, 0.35))
    return out


def _wipe_mask(width: int, height: int, edge: float, soft: float, reverse: bool = False) -> Any:
    """An L mask: fully on left of `edge`, off right of it, a soft ramp `soft` wide (or the opposite)."""
    from PIL import Image  # type: ignore
    row = bytearray(width)
    for x in range(width):
        v = (edge - x) / max(1.0, soft) + 0.5
        v = 0.0 if v < 0 else 1.0 if v > 1 else v
        if reverse:
            v = 1.0 - v
        row[x] = int(round(255 * v))
    return Image.frombytes("L", (width, height), bytes(row) * height)


def _masked(img: Any, mask: Any) -> Any:
    from PIL import ImageChops  # type: ignore
    out = img.copy()
    out.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    return out


def _glitched(lay: Layout, hold: Any, strength: float, alpha: float, seed: Any, slices: int = 8) -> Any:
    from PIL import Image  # type: ignore
    rng = random.Random(repr(("glitch", seed)))
    out = Image.new("RGBA", hold.size, (0, 0, 0, 0))
    h = max(1, hold.height // slices)
    amp = 0.08 * lay.width * strength
    for i in range(slices):
        y0, y1 = i * h, hold.height if i == slices - 1 else (i + 1) * h
        band = hold.crop((0, y0, hold.width, y1))
        dx = int(round(rng.uniform(-amp, amp))) if strength > 0 else 0
        flicker = alpha * (1.0 if strength <= 0 else rng.uniform(0.35, 1.0))
        _blit(out, _faded(band, flicker), dx, y0)
    return out


def entry_frame(lay: Layout, effect: str, p: float, seconds: float, seed: int = 0, hold: Any = None) -> Any:
    """The entry at progress p (0 = nothing, 1 = the finished card)."""
    from PIL import ImageFilter  # type: ignore
    p = clamp01(p)
    t = p * seconds
    n = max(1, len(lay.glyphs))
    r = max(1, len(lay.rows))
    if effect == "flip_chars":
        stagger = (seconds - FLIP_ONE) / max(1, n - 1)

        def place(g: Glyph) -> Any:
            q = clamp01((t - g.index * stagger) / FLIP_ONE)
            if q <= 0:
                return None
            return (0.0, 0.0, min(1.0, q * 4), math.sin(q * math.pi / 2), 1.0)
        return compose(lay, place)
    if effect == "drop_bounce":
        one = seconds - 0.15 * (r - 1)

        def place(g: Glyph) -> Any:
            q = clamp01((t - 0.15 * g.row) / one)
            if q <= 0:
                return None
            start = -(g.y + g.tile.height)
            return (0.0, start * (1 - ease_out_bounce(q)), 1.0, 1.0, 1.0)
        return compose(lay, place)
    if effect == "rise_settle":
        one = seconds - 0.12 * (r - 1)

        def place(g: Glyph) -> Any:
            q = clamp01((t - 0.12 * g.row) / one)
            if q <= 0:
                return None
            start = lay.height - g.y
            return (0.0, start * (1 - ease_out_cubic(q)), min(1.0, q * 3), 1.0, 1.0)
        return compose(lay, place)
    if effect == "typewriter":
        step = (seconds - 0.15) / n

        def place(g: Glyph) -> Any:
            return (0.0, 0.0, 1.0, 1.0, 1.0) if t >= (g.index + 1) * step - 1e-9 else None
        return compose(lay, place)
    if effect == "slow_reveal":
        k = 0.4 + 0.6 * ease_out_cubic(p)
        a = ease_in_out(p)

        def place(g: Glyph) -> Any:
            row = lay.rows[g.row]
            return ((g.cx - row["cx"]) * (k - 1), 0.0, a, 1.0, 1.0)
        return compose(lay, place)
    if effect == "wipe":
        hold = hold if hold is not None else compose(lay)
        soft = 0.08 * lay.width
        edge = -soft + (lay.width + 2 * soft) * ease_in_out(p)
        return _masked(hold, _wipe_mask(lay.width, lay.height, edge, soft))
    if effect == "pop":
        one = seconds - 0.12 * (r - 1)

        def place(g: Glyph) -> Any:
            q = clamp01((t - 0.12 * g.row) / one)
            if q <= 0:
                return None
            s = max(0.0, ease_out_back(q))
            row = lay.rows[g.row]
            return ((g.cx - row["cx"]) * (s - 1), (g.cy - row["cy"]) * (s - 1), min(1.0, q * 4), s, s)
        return compose(lay, place)
    if effect == "blur_in":
        hold = hold if hold is not None else compose(lay)
        e = ease_out_cubic(p)
        radius = 16.0 * (1 - e)
        img = hold.filter(ImageFilter.GaussianBlur(radius)) if radius > 0.05 else hold.copy()
        return _faded(img, e)
    if effect == "scatter":
        places = _scatter_places(lay, seed)
        span = max(0.1, seconds - 0.35)

        def place(g: Glyph) -> Any:
            ox, oy, delay = places[g.index]
            q = clamp01((t - delay) / span)
            if q <= 0:
                return None
            e = ease_out_cubic(q)
            return (ox * (1 - e), oy * (1 - e), min(1.0, q * 3), 1.0, 1.0)
        return compose(lay, place)
    if effect == "glitch":
        hold = hold if hold is not None else compose(lay)
        lock = 0.8 / seconds
        strength = 0.0 if p >= lock else (1 - p / lock) ** 1.5
        alpha = min(1.0, t / 0.15)
        return _glitched(lay, hold, strength, alpha, (seed, round(p, 4)))
    return _faded(hold if hold is not None else compose(lay), p)


def exit_frame(lay: Layout, effect: str, p: float, seconds: float, seed: int = 0, hold: Any = None) -> Any:
    """The exit at progress p (0 = the finished card, 1 = gone)."""
    from PIL import ImageFilter  # type: ignore
    p = clamp01(p)
    t = p * seconds
    n = max(1, len(lay.glyphs))
    r = max(1, len(lay.rows))
    if effect == "flip_chars":
        one = min(FLIP_ONE, seconds * 0.5)
        stagger = (seconds - one) / max(1, n - 1)

        def place(g: Glyph) -> Any:
            q = clamp01((t - g.index * stagger) / one)
            if q >= 1:
                return None
            return (0.0, 0.0, 1.0, math.cos(q * math.pi / 2), 1.0)
        return compose(lay, place)
    if effect == "drop_bounce":
        one = seconds - 0.1 * (r - 1)

        def place(g: Glyph) -> Any:
            q = clamp01((t - 0.1 * g.row) / one)
            if q >= 1:
                return None
            return (0.0, (lay.height - g.y) * ease_in_cubic(q), 1.0, 1.0, 1.0)
        return compose(lay, place)
    if effect == "rise_settle":
        one = seconds - 0.1 * (r - 1)

        def place(g: Glyph) -> Any:
            q = clamp01((t - 0.1 * g.row) / one)
            if q >= 1:
                return None
            return (0.0, (lay.height - g.y) * ease_in_cubic(q), 1.0 - q * 0.6, 1.0, 1.0)
        return compose(lay, place)
    if effect == "typewriter":
        step = seconds / n

        def place(g: Glyph) -> Any:
            gone = (n - g.index) * step            # the last character goes first
            return None if t >= gone - 1e-9 else (0.0, 0.0, 1.0, 1.0, 1.0)
        return compose(lay, place)
    if effect == "slow_reveal":
        k = 1.0 + 0.15 * ease_in_out(p)
        a = 1.0 - ease_in_out(p)

        def place(g: Glyph) -> Any:
            row = lay.rows[g.row]
            return ((g.cx - row["cx"]) * (k - 1), 0.0, a, 1.0, 1.0)
        return compose(lay, place)
    if effect == "wipe":
        hold = hold if hold is not None else compose(lay)
        soft = 0.08 * lay.width
        edge = -soft + (lay.width + 2 * soft) * ease_in_out(p)
        return _masked(hold, _wipe_mask(lay.width, lay.height, edge, soft, reverse=True))
    if effect == "pop":
        one = seconds - 0.08 * (r - 1)

        def place(g: Glyph) -> Any:
            q = clamp01((t - 0.08 * g.row) / one)
            if q >= 1:
                return None
            s = (1 + 0.12 * math.sin(math.pi * min(1.0, q * 2))) * (1 - ease_in_cubic(q))
            row = lay.rows[g.row]
            return ((g.cx - row["cx"]) * (s - 1), (g.cy - row["cy"]) * (s - 1), 1.0, s, s)
        return compose(lay, place)
    if effect == "blur_in":
        hold = hold if hold is not None else compose(lay)
        e = ease_in_cubic(p)
        radius = 16.0 * e
        img = hold.filter(ImageFilter.GaussianBlur(radius)) if radius > 0.05 else hold.copy()
        return _faded(img, 1 - e)
    if effect == "scatter":
        places = _scatter_places(lay, seed)
        span = max(0.1, seconds - 0.3)

        def place(g: Glyph) -> Any:
            ox, oy, delay = places[g.index]
            q = clamp01((t - delay * (0.3 / 0.35)) / span)
            if q >= 1:
                return None
            e = ease_in_cubic(q)
            return (ox * e, oy * e, 1.0 - q, 1.0, 1.0)
        return compose(lay, place)
    if effect == "glitch":
        hold = hold if hold is not None else compose(lay)
        strength = ease_in_cubic(p) if p > 0 else 0.0
        alpha = 1.0 - clamp01((p - 0.5) / 0.5)
        return _glitched(lay, hold, strength, alpha, ("out", seed, round(p, 4)))
    return _faded(hold if hold is not None else compose(lay), 1 - p)


def _progress(count: int) -> list[float]:
    return [i / (count - 1) if count > 1 else 1.0 for i in range(count)]


def entry_frames(lay: Layout, effect: str, fps: int = FPS, seed: int = 0, seconds: float | None = None) -> list[Any]:
    """The entry, frame by frame; the last frame IS the finished card."""
    seconds = float(seconds if seconds is not None else entry_seconds(effect, lay))
    count = max(2, int(round(seconds * fps)))
    hold = compose(lay)
    return [entry_frame(lay, effect, p, seconds, seed, hold) for p in _progress(count)]


def exit_frames(lay: Layout, effect: str, fps: int = FPS, seed: int = 0, seconds: float | None = None) -> list[Any]:
    """The exit, frame by frame; the first frame IS the finished card."""
    seconds = float(seconds if seconds is not None else exit_seconds(effect, lay))
    count = max(2, int(round(seconds * fps)))
    hold = compose(lay)
    return [exit_frame(lay, effect, p, seconds, seed, hold) for p in _progress(count)]


# --- the rolls -------------------------------------------------------------------------------

def roll_effects(choose: Callable[..., Any] | None, note: Callable[..., Any] | None = None, seed: int = 0) -> tuple[str, str]:
    """The entry and the exit, two separate rolls: `choose(key, options, label)` is the
    station's tabled die (so the desk can retire an effect); with no die a seeded draw.
    `note(key, options, picked)` hears each roll."""
    rng = random.Random(repr(("effects", int(seed))))
    out = []
    for key, label in ((KEY_IN, LABEL_IN), (KEY_OUT, LABEL_OUT)):
        picked: Any = None
        if callable(choose):
            try:
                picked = choose(key, list(EFFECTS), label)
            except Exception:  # noqa: BLE001
                picked = None
        if isinstance(picked, int) and 0 <= picked < len(EFFECTS):
            picked = EFFECTS[picked]
        if picked not in EFFECTS:
            picked = rng.choice(EFFECTS)
        if callable(note):
            try:
                note(key, list(EFFECTS), picked)
            except Exception:  # noqa: BLE001
                pass
        out.append(str(picked))
    return out[0], out[1]


def seed_for(text: Any) -> int:
    """A seed per cut (its plan or prompt id), so a re-render matches."""
    import hashlib
    return int(hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()[:8], 16)


# --- timing and the burn ---------------------------------------------------------------------

def timing(clip_seconds: float, effect_in: str, effect_out: str, lay: Layout) -> dict[str, Any]:
    """When the entry, the hold and the exit sit in the clip. A clip with little room
    shortens the hold, then takes the short pair, then the card alone; one under
    SHORT_CLIP wears the card from the first frame."""
    clip = float(clip_seconds or 0.0)
    plan: dict[str, Any] = {"clip": round(clip, 3), "effect_in": effect_in, "effect_out": effect_out,
                            "entry": None, "exit": None, "shortened": "", "fps": FPS,
                            "entry_seconds": 0.0, "exit_seconds": 0.0}
    if clip <= 0 or clip < SHORT_CLIP:
        plan.update(effect_in="", effect_out="", shortened="hold-only", hold=[0.0, round(clip, 3) if clip > 0 else 3600.0])
        return plan
    start, end = ENTRY_AT, clip - EXIT_GAP
    room = end - start
    e_in, e_out = entry_seconds(effect_in, lay), exit_seconds(effect_out, lay)
    hold = room - e_in - e_out
    if hold < MIN_HOLD:
        effect_in, effect_out = SHORT_IN, SHORT_OUT
        e_in, e_out = entry_seconds(SHORT_IN, lay), SHORT_OUT_SECONDS
        hold = room - e_in - e_out
        plan["shortened"] = "short-effects"
        if hold < MIN_HOLD:
            plan.update(effect_in="", effect_out="", shortened="hold-only", hold=[round(start, 3), round(end, 3)])
            return plan
    elif hold < ROOMY_HOLD:
        plan["shortened"] = "hold"
    entry_end = start + e_in
    exit_start = entry_end + hold
    plan.update(effect_in=effect_in, effect_out=effect_out, entry_seconds=round(e_in, 3), exit_seconds=round(e_out, 3),
                entry=[round(start, 3), round(entry_end, 3)], hold=[round(entry_end, 3), round(exit_start, 3)],
                exit=[round(exit_start, 3), round(exit_start + e_out, 3)])
    return plan


def write_frames(frames: Sequence[Any], folder: Any, prefix: str) -> str:
    """The frames as <folder>/<prefix>_0000.png ...; returns the image2 pattern."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for i, img in enumerate(frames):
        img.save(str(folder / ("%s_%04d.png" % (prefix, i))), "PNG", compress_level=3)
    return str(folder / (prefix + "_%04d.png"))


def prepare(lines_: Sequence[Any], font_path: Any, width: int, height: int, clip_seconds: float,
            effect_in: str, effect_out: str, workdir: Any, seed: int = 0, fps: int = FPS) -> dict[str, Any]:
    """Lay the card out, plan its timing, render and write the entry, the hold and the
    exit under `workdir`. The dict that comes back is what overlay_graph / burn read, plus
    what the record keeps (fell_back, why, card, frames, timing, render_ms)."""
    began = time.monotonic()
    lay = layout(rows(lines_, width), font_path, width, height)
    tm = timing(clip_seconds, effect_in, effect_out, lay)
    tm["fps"] = int(fps)
    folder = Path(workdir)
    folder.mkdir(parents=True, exist_ok=True)
    hold = compose(lay)
    hold_path = folder / "hold.png"
    hold.save(str(hold_path), "PNG", compress_level=3)
    files: dict[str, str] = {"hold": str(hold_path), "entry": "", "exit": ""}
    counts = {"entry": 0, "hold": 1, "exit": 0}
    if tm.get("entry"):
        frames = entry_frames(lay, tm["effect_in"], fps, seed, tm["entry_seconds"])
        files["entry"] = write_frames(frames, folder, "in")
        counts["entry"] = len(frames)
    if tm.get("exit"):
        frames = exit_frames(lay, tm["effect_out"], fps, seed, tm["exit_seconds"])
        files["exit"] = write_frames(frames, folder, "out")
        counts["exit"] = len(frames)
    return {"layout": lay, "timing": tm, "files": files, "frames": counts, "card": [lay.width, lay.height],
            "fell_back": lay.fell_back, "why": lay.why, "seed": int(seed),
            "render_ms": int((time.monotonic() - began) * 1000)}


def overlay_graph(prep: dict[str, Any], first_input: int = 1, main: str = "[0:v:0]", margin: int = MARGIN_PX) -> tuple[list[str], str]:
    """The ffmpeg inputs (entry sequence, looped hold, exit sequence - each offset to its
    window) and the filter_complex that lays them over `main`, centred, `margin` px up from
    the bottom, each enabled only in its window, ending in format=yuv420p[v]."""
    tm, files = prep["timing"], prep["files"]
    fps = str(int(tm.get("fps") or FPS))
    inputs: list[str] = []
    steps: list[str] = []
    idx = first_input
    chain = main
    windows = []
    if tm.get("entry") and files.get("entry"):
        windows.append(("entry", tm["entry"]))
    if tm.get("hold"):
        windows.append(("hold", tm["hold"]))
    if tm.get("exit") and files.get("exit"):
        windows.append(("exit", tm["exit"]))
    for kind, (a, b) in windows:
        if kind == "hold":
            inputs += ["-itsoffset", "%.3f" % a, "-loop", "1", "-framerate", fps, "-t", "%.3f" % max(0.05, b - a),
                       "-i", files["hold"]]
        else:
            inputs += ["-itsoffset", "%.3f" % a, "-framerate", fps, "-start_number", "0", "-i", files[kind]]
        steps.append("%s[%d:v]overlay=x=(W-w)/2:y=H-h-%d:eof_action=pass:enable='between(t,%.3f,%.3f)'[v%d]"
                     % (chain, idx, int(margin), a, b, idx))
        chain = "[v%d]" % idx
        idx += 1
    if not steps:
        return [], "%snull,format=yuv420p[v]" % main
    last = steps[-1]
    steps[-1] = last[:last.rfind("[v")] + ",format=yuv420p[v]"
    return inputs, ";".join(steps)


def burn_command(exe: str, source: Any, target: Any, prep: dict[str, Any], audio: str = "aac") -> list[str]:
    """One ffmpeg pass: the picture with the three overlays, the sound as it was (re-encoded
    AAC, or copied when `audio` is "copy")."""
    inputs, graph = overlay_graph(prep, first_input=1)
    sound = ["-c:a", "copy"] if audio == "copy" else ["-c:a", "aac", "-b:a", "160k"]
    return [str(exe), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), *inputs,
            "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", *sound,
            "-movflags", "+faststart", str(target)]


def burn(exe: str, source: Any, target: Any, prep: dict[str, Any], run: Callable[..., Any] = subprocess.run,
         timeout: float = 120.0, audio: str = "aac") -> dict[str, Any]:
    """Run the one pass into a temporary beside the target, then put the target in place."""
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.stem + ".tmp" + target.suffix)
    command = burn_command(exe, source, temporary, prep, audio=audio)
    began = time.monotonic()
    try:
        run(command, capture_output=True, timeout=timeout, check=True)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": str(target), "command": command, "ffmpeg_ms": int((time.monotonic() - began) * 1000)}


def record_of(prep: dict[str, Any], font: Any, cached: Any, lines_: Sequence[Any], effect_in: str, effect_out: str,
              rolled: bool = True, **more: Any) -> dict[str, Any]:
    """The brand record both roads keep: the font and its fallback, the three lines, the
    effects as rolled and as used (a short clip may have swapped them), the seed, the
    timing, the frame counts, the card's size and the render time."""
    tm = dict(prep.get("timing") or {})
    rec = brand_record(font, cached, bool(prep.get("fell_back")), str(prep.get("why") or ""),
                       lines=list(lines_), effect_in=effect_in, effect_out=effect_out,
                       effect_in_used=tm.get("effect_in", effect_in), effect_out_used=tm.get("effect_out", effect_out),
                       seed=int(prep.get("seed") or 0), timing=tm, frames=dict(prep.get("frames") or {}),
                       card=list(prep.get("card") or []), render_ms=int(prep.get("render_ms") or 0), rolled=bool(rolled))
    rec.update(more)
    return rec


def clean_workdir(folder: Any) -> None:
    try:
        shutil.rmtree(str(folder), ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
