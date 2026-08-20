"""Draw the Pine Box mark and assemble a Windows .ico from it.

The mark: a pine standing in a box, in the app's own palette. Chosen over
a PB monogram and three other candidates because it is the only one that
still reads as BOTH a pine and a box at sixteen pixels, which is the size
that actually decides whether a taskbar icon is any good.

The .ico is assembled by hand rather than left to Pillow's ICO writer,
because Pillow emits PNG-compressed entries at every size and those are
not universally readable. Measured on this machine: with PNG entries at
128 and 256, System.Drawing.Icon.ToBitmap() decodes 16/24/32/48/64 and
throws "Requested range extends past the end of the array" on both PNG
entries. The Windows shell itself does read PNG entries (Vista+), so
that is a GDI+ limitation rather than a shell one - but an application
icon is read by a great many things and there is no reason at all to
ship one that half the decoders in Windows cannot open. Every entry is
an uncompressed BMP/DIB, which every Windows surface has read since 1995.
It costs about 320 KB, which for an app icon is nothing.

Also emits PNGs, because Electron's BrowserWindow icon option is happiest
with a PNG on every platform and the .ico is for the shell.
"""
from PIL import Image, ImageDraw
import io
import os
import struct
import sys

# --- the palette, read off the app's own stylesheet -------------------
NAVY = (12, 17, 23, 255)        # --bg, the app ground
PANEL = (22, 32, 43, 255)       # panel surface
CYAN = (101, 199, 218, 255)     # --cyan, the accent the app is built on
MINT = (124, 232, 169, 255)     # the "ready/good" green
LINE = (36, 56, 74, 255)        # --line, the border everywhere

S = 1024                        # drawn large, downsampled per entry


def pine(d, cx, top, bot, half, fill, tiers=3):
    """A conifer as stacked triangles - the one construction that still
    reads as a pine tree when it is nine pixels tall."""
    span = bot - top
    for i in range(tiers):
        t = top + span * i * 0.30
        b = top + span * (0.42 + i * 0.29)
        h = half * (0.62 + 0.19 * i)
        d.polygon([(cx, t), (cx - h, b), (cx + h, b)], fill=fill)


def mark(size=S, plate=True):
    """The mark at any size. Everything is expressed as a fraction of the
    canvas so the 16px render is the same drawing, not a scaled photo."""
    k = size / 256.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def r(*v):
        return [x * k for x in v]

    if plate:
        d.rounded_rectangle(r(0, 0, 255, 255), radius=56 * k, fill=NAVY)
        d.rounded_rectangle(r(3, 3, 252, 252), radius=54 * k,
                            outline=LINE, width=max(1, int(5 * k)))
    # the box: a lid seam across a solid body, so it reads as a crate and
    # not as a plinth the tree happens to be standing on
    d.rounded_rectangle(r(38, 156, 218, 226), radius=15 * k, fill=CYAN)
    d.rectangle(r(38, 177, 218, 186), fill=NAVY)
    # the pine, its base overlapping the lid so it stands IN the box
    pine(d, 128 * k, 32 * k, 170 * k, 63 * k, MINT)
    return img


def dib_entry(img):
    """One BMP/DIB icon entry: a 40-byte BITMAPINFOHEADER whose height is
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


# 20 and 40 are the 125% and 175% taskbar steps. Without them Windows
# bilinearly rescales 16 or 24 on exactly the two display scalings most
# laptops ship with, and the mark goes soft at the one size it is most
# often seen at.
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def build_ico(path, sizes=ICON_SIZES, png_from=None):
    art = mark(S)
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
    ico = os.path.join(outdir, "pinebox.ico")
    total, entries = build_ico(ico)
    art = mark(S)
    art.resize((512, 512), Image.LANCZOS).save(
        os.path.join(outdir, "pinebox.png"))
    art.resize((256, 256), Image.LANCZOS).save(
        os.path.join(outdir, "pinebox-256.png"))
    print("wrote %s (%d bytes)" % (ico, total))
    for n, blob in entries:
        kind = "PNG" if blob[:8] == b"\x89PNG\r\n\x1a\n" else "BMP"
        print("  %3dx%-3d %7d bytes  %s" % (n, n, len(blob), kind))
    print("wrote pinebox.png (512) and pinebox-256.png")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "icon_out")
