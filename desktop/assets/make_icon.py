"""Draw the Pine Box mark and assemble a Windows .ico from it.

THE MARK is the PB badge the app already wears in its own header - the
operator asked for exactly that ("This should also be the Pine Box
icon"), so the colours are lifted from the stylesheet rather than
invented: desktop/renderer/styles.css .mark is background #d6f2de,
colour #112318, border-radius 8 on a 42px square, font-weight 800. Each
of those is expressed here as a fraction of the canvas, so the 16px
render is the same drawing rather than a photograph of a big one.

A pine-in-a-box mark was built first and is kept below as pine_mark(),
because it reads better at 16px - two letters in sixteen pixels is
always going to be a smudge. But the app's own badge is what was asked
for, and an icon that matches the window it opens is worth more than one
that is merely easier to read. Both are emitted; the shortcut points at
pinebox.ico.

The .ico is assembled by hand rather than left to Pillow's ICO writer,
because Pillow emits PNG-compressed frames at every size and those are
not universally readable. Measured on this machine: with PNG frames at
128 and 256, System.Drawing.Icon.ToBitmap decodes 16/24/32/48/64 and
throws "Requested range extends past the end of the array" on both PNG
entries. The Windows shell itself does read PNG frames (Vista+), so that
is a GDI+ limitation rather than a shell one - but an application icon
is read by a great many things and there is no reason to ship one that
half the decoders in Windows cannot open. Every frame is an
uncompressed BMP/DIB, which every Windows surface has read since 1995.
It costs about 380 KB, which for an app icon is nothing.
"""
from PIL import Image, ImageDraw, ImageFont
import io
import os
import struct
import sys

# --- the badge, straight off the app's stylesheet ---------------------
BADGE_BG = (214, 242, 222, 255)     # .mark background: #d6f2de
BADGE_FG = (17, 35, 24, 255)        # .mark color:      #112318
BADGE_RADIUS = 8.0 / 42.0           # .mark border-radius over its size

# --- the palette the pine variant uses --------------------------------
NAVY = (12, 17, 23, 255)
CYAN = (101, 199, 218, 255)
MINT = (124, 232, 169, 255)
LINE = (36, 56, 74, 255)

S = 1024                            # drawn large, downsampled per frame

# 20 and 40 are the 125% and 175% taskbar steps. Without them Windows
# bilinearly rescales 16 or 32 on exactly the two display scalings most
# laptops ship with, and the mark goes soft at the size it is most often
# seen at.
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _font(px):
    """The heaviest Segoe available, because .mark is font-weight 800."""
    for name in ("seguibl.ttf", "segoeuib.ttf", "seguisb.ttf",
                 "arialbd.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, max(1, int(px)))
        except OSError:
            continue
    return ImageFont.load_default()


def mark(size=S):
    """The PB badge, at any size."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1],
                        radius=size * BADGE_RADIUS, fill=BADGE_BG)
    # Fit the letters to the plate rather than to a guessed point size:
    # the badge is 42px in the app and the letters fill most of it, so
    # the same proportion has to hold at 16 and at 256.
    want = size * 0.64
    px = size * 0.64
    f = _font(px)
    for _ in range(24):
        f = _font(px)
        box = d.textbbox((0, 0), "PB", font=f)
        w = box[2] - box[0]
        if w <= 0:
            break
        if abs(w - want) <= max(1.0, size * 0.01):
            break
        px *= want / w
    box = d.textbbox((0, 0), "PB", font=f)
    d.text(((size - (box[2] - box[0])) / 2 - box[0],
            (size - (box[3] - box[1])) / 2 - box[1]),
           "PB", font=f, fill=BADGE_FG)
    return img


def pine_mark(size=S):
    """The alternative: a pine standing in a box, on the app's navy."""
    k = size / 256.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def r(*v):
        return [x * k for x in v]

    d.rounded_rectangle(r(0, 0, 255, 255), radius=56 * k, fill=NAVY)
    d.rounded_rectangle(r(3, 3, 252, 252), radius=54 * k,
                        outline=LINE, width=max(1, int(5 * k)))
    d.rounded_rectangle(r(38, 156, 218, 226), radius=15 * k, fill=CYAN)
    d.rectangle(r(38, 177, 218, 186), fill=NAVY)
    top, bot, half, cx = 32 * k, 170 * k, 63 * k, 128 * k
    span = bot - top
    for i in range(3):
        t = top + span * i * 0.30
        b = top + span * (0.42 + i * 0.29)
        h = half * (0.62 + 0.19 * i)
        d.polygon([(cx, t), (cx - h, b), (cx + h, b)], fill=MINT)
    return img


def dib_entry(img):
    """One BMP/DIB icon frame: a 40-byte BITMAPINFOHEADER whose height is
    doubled for the (empty but mandatory) AND mask, then BGRA rows bottom
    up, then the mask itself padded to 32-bit rows."""
    w, h = img.size
    px = img.load()
    hdr = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, w * h * 4,
                      0, 0, 0, 0)
    body = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = px[x, y]
            body += bytes((b, g, r, a))
    mask_row = ((w + 31) // 32) * 4
    body += bytes(mask_row * h)
    return hdr + bytes(body)


def png_entry(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def build_ico(path, sizes=ICON_SIZES, png_from=None, art=None):
    art = art if art is not None else mark(S)
    entries = []
    for n in sizes:
        one = art.resize((n, n), Image.LANCZOS)
        blob = (png_entry(one) if (png_from is not None and n >= png_from)
                else dib_entry(one))
        entries.append((n, blob))
    out = bytearray(struct.pack("<HHH", 0, 1, len(entries)))
    offset = 6 + 16 * len(entries)
    for n, blob in entries:
        out += struct.pack("<BBBBHHII", 0 if n == 256 else n,
                           0 if n == 256 else n, 0, 0, 1, 32,
                           len(blob), offset)
        offset += len(blob)
    for _n, blob in entries:
        out += blob
    with open(path, "wb") as fh:
        fh.write(bytes(out))
    return len(out), entries


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    art = mark(S)
    ico = os.path.join(outdir, "pinebox.ico")
    total, entries = build_ico(ico, art=art)
    art.resize((512, 512), Image.LANCZOS).save(
        os.path.join(outdir, "pinebox.png"))
    art.resize((256, 256), Image.LANCZOS).save(
        os.path.join(outdir, "pinebox-256.png"))
    # kept beside it so the choice can be reversed without re-deriving it
    build_ico(os.path.join(outdir, "pinebox-pine.ico"), art=pine_mark(S))
    print("wrote %s (%d bytes)" % (ico, total))
    for n, blob in entries:
        kind = "PNG" if blob[:8] == b"\x89PNG\r\n\x1a\n" else "BMP"
        print("  %3dx%-3d %7d bytes  %s" % (n, n, len(blob), kind))
    print("wrote pinebox.png (512), pinebox-256.png, pinebox-pine.ico")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "icon_out")
