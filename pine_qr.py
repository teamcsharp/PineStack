"""pine_qr — a QR code, drawn with nothing but the standard library. [#1252]

WHY THIS EXISTS. A link you have to type into a phone is a link nobody
uses. The car needs one glance: hold the phone up to the panel and the
tune-in page opens. The station's container is python:3.12-slim with
fastapi/uvicorn/httpx/mutagen/pyserial/imageio-ffmpeg and nothing else —
there is no `qrcode`, no `segno`, no PIL, and adding one would mean a
rebuilt image for a picture of a string. So the encoder is here: byte
mode, error correction level M, versions 1 to 14, which covers every
tune-in link the station can mint (the longest is about 95 characters).

VERIFIED on 2026-09-21, three ways. Against the `qrcode` library 8.2:
66 payloads spanning versions 3-14, every matrix identical to one of that
library's eight forced-mask renderings. Against segno 1.6.6: identical
whenever the payload exactly fills its version (segno writes one extra
0x00 before the pad codewords; `qrcode` and ISO/IEC 18004 8.4.9 do not,
and this follows them). And end to end through OpenCV's QRCodeDetector:
120 real tune-in links encoded here and read back as the same string,
except where OpenCV's own detector cannot read mask 2 at version 5 -
segno's mask-2 output of the same payload fails identically, so that is
the reader, not this.

Two entry points:

    qr_matrix(text) -> list[list[bool]]   True = a dark module
    qr_svg(text, quiet=4, scale=4) -> str  a self-contained <svg> string

qr_svg raises ValueError for text that will not fit in version 14 at
level M (365 data codewords, 362 bytes) — callers hand it URLs.
"""
from __future__ import annotations

# --- GF(256), the field Reed-Solomon lives in ------------------------------
_EXP = [0] * 512
_LOG = [0] * 256


def _tables() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D                      # the QR primitive polynomial
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_tables()


def _mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _generator(n: int) -> list[int]:
    """The degree-n generator polynomial, highest power first."""
    poly = [1]
    for i in range(n):
        out = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            out[j] ^= coef
            out[j + 1] ^= _mul(coef, _EXP[i])
        poly = out
    return poly


def _remainder(data: list[int], n: int) -> list[int]:
    gen = _generator(n)
    res = list(data) + [0] * n
    for i in range(len(data)):
        coef = res[i]
        if not coef:
            continue
        for j, g in enumerate(gen):
            res[i + j] ^= _mul(g, coef)
    return res[len(data):]


# --- what fits where -------------------------------------------------------
# Level M only. (ec codewords per block, blocks in group 1, data codewords
# in each, blocks in group 2, data codewords in each).
_BLOCKS_M: dict[int, tuple[int, int, int, int, int]] = {
    1: (10, 1, 16, 0, 0), 2: (16, 1, 28, 0, 0), 3: (26, 1, 44, 0, 0),
    4: (18, 2, 32, 0, 0), 5: (24, 2, 43, 0, 0), 6: (16, 4, 27, 0, 0),
    7: (18, 4, 31, 0, 0), 8: (22, 2, 38, 2, 39), 9: (22, 3, 36, 2, 37),
    10: (26, 4, 43, 1, 44), 11: (30, 1, 50, 4, 51), 12: (22, 6, 36, 2, 37),
    13: (22, 8, 37, 1, 38), 14: (24, 4, 40, 5, 41),
}

_ALIGN: dict[int, list[int]] = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
    11: [6, 30, 54], 12: [6, 32, 58], 13: [6, 34, 62], 14: [6, 26, 46, 66],
}

_ECL_M = 0b00                                # level M's two-bit indicator


def _data_codewords(version: int) -> int:
    ec, g1, d1, g2, d2 = _BLOCKS_M[version]
    return g1 * d1 + g2 * d2


def _count_bits(version: int) -> int:
    return 8 if version <= 9 else 16


def _fit(length: int) -> int:
    for version in sorted(_BLOCKS_M):
        room = _data_codewords(version) * 8 - 4 - _count_bits(version)
        if length * 8 <= room:
            return version
    raise ValueError(
        "%d bytes will not fit in a version 14 QR at level M" % length)


# --- the bit stream --------------------------------------------------------
def _codewords(payload: bytes, version: int) -> list[int]:
    total = _data_codewords(version)
    bits: list[int] = []

    def put(value: int, width: int) -> None:
        for shift in range(width - 1, -1, -1):
            bits.append((value >> shift) & 1)

    put(0b0100, 4)                                   # byte mode
    put(len(payload), _count_bits(version))
    for byte in payload:
        put(byte, 8)
    put(0, min(4, total * 8 - len(bits)))            # terminator
    while len(bits) % 8:
        bits.append(0)
    words = [int("".join(str(b) for b in bits[i:i + 8]), 2)
             for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    while len(words) < total:
        words.append(pad[(len(words) - len(bits) // 8) % 2])
    return words


def _interleave(words: list[int], version: int) -> list[int]:
    ec, g1, d1, g2, d2 = _BLOCKS_M[version]
    blocks: list[list[int]] = []
    at = 0
    for _ in range(g1):
        blocks.append(words[at:at + d1])
        at += d1
    for _ in range(g2):
        blocks.append(words[at:at + d2])
        at += d2
    checks = [_remainder(b, ec) for b in blocks]
    out: list[int] = []
    for i in range(max(len(b) for b in blocks)):
        for b in blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(ec):
        for c in checks:
            out.append(c[i])
    return out


# --- the picture -----------------------------------------------------------
def _bch(value: int, generator: int, width: int) -> int:
    rest = value
    while rest.bit_length() >= width:
        rest ^= generator << (rest.bit_length() - width)
    return rest


def _format_bits(mask: int) -> int:
    data = (_ECL_M << 3) | mask
    rest = _bch(data << 10, 0b10100110111, 11)
    return ((data << 10) | rest) ^ 0b101010000010010


def _version_bits(version: int) -> int:
    rest = _bch(version << 12, 0b1111100100101, 13)
    return (version << 12) | rest


def _blank(version: int):
    size = version * 4 + 17
    grid = [[0] * size for _ in range(size)]
    fixed = [[False] * size for _ in range(size)]

    def finder(row: int, col: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = row + dr, col + dc
                if not (0 <= r < size and 0 <= c < size):
                    continue
                fixed[r][c] = True
                on = (0 <= dr <= 6 and dc in (0, 6)) or \
                     (0 <= dc <= 6 and dr in (0, 6)) or \
                     (2 <= dr <= 4 and 2 <= dc <= 4)
                grid[r][c] = 1 if on else 0

    finder(0, 0)
    finder(0, size - 7)
    finder(size - 7, 0)

    for i in range(size):                                    # timing
        if not fixed[6][i]:
            fixed[6][i] = True
            grid[6][i] = 1 if i % 2 == 0 else 0
        if not fixed[i][6]:
            fixed[i][6] = True
            grid[i][6] = 1 if i % 2 == 0 else 0

    centres = _ALIGN[version]
    last = centres[-1] if centres else 0
    # Three of the combinations sit under a finder and are never drawn. The
    # rest are, INCLUDING the ones that land on the timing lines - skipping
    # those (because the cell was already reserved) is a bug that only shows
    # from version 7 up, where a centre first falls on row 6 away from a
    # finder, and it makes every such code undecodable.
    for row in centres:
        for col in centres:
            if (row, col) in ((6, 6), (6, last), (last, 6)):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    fixed[row + dr][col + dc] = True
                    grid[row + dr][col + dc] = 1 if (
                        max(abs(dr), abs(dc)) != 1) else 0

    for i in range(9):                                       # format areas
        if i != 6:
            fixed[8][i] = True
            fixed[i][8] = True
    for i in range(8):
        fixed[8][size - 1 - i] = True
        fixed[size - 1 - i][8] = True
    fixed[8][6] = True
    fixed[6][8] = True
    fixed[size - 8][8] = True
    grid[size - 8][8] = 1                                    # the dark module

    if version >= 7:
        bits = _version_bits(version)
        for i in range(18):
            bit = (bits >> i) & 1
            row, col = i // 3, i % 3
            fixed[row][size - 11 + col] = True
            grid[row][size - 11 + col] = bit
            fixed[size - 11 + col][row] = True
            grid[size - 11 + col][row] = bit
    return grid, fixed, size


def _place(grid, fixed, size, stream: list[int]) -> None:
    bits = [(word >> shift) & 1
            for word in stream for shift in range(7, -1, -1)]
    at = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1                                        # the timing line
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if fixed[row][c]:
                    continue
                grid[row][c] = bits[at] if at < len(bits) else 0
                at += 1
        col -= 2
        upward = not upward


_MASKS = (
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
)


def _penalty(grid, size) -> int:
    score = 0
    for line in list(grid) + [list(col) for col in zip(*grid)]:
        run = 1
        for i in range(1, size):
            if line[i] == line[i - 1]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)
        # Rule 3: the finder-like run, either way round. The four light
        # modules may run off the edge of the symbol - outside is light -
        # so the line is padded before it is scanned. Leaving that out
        # under-scores exactly the striped masks, and picking one of those
        # is how a code ends up readable by some scanners and not others.
        edged = [0] * 4 + list(line) + [0] * 4
        for i in range(len(edged) - 10):
            window = edged[i:i + 11]
            if window[:7] == [1, 0, 1, 1, 1, 0, 1] and window[7:] == [0] * 4:
                score += 40
            if window[4:] == [1, 0, 1, 1, 1, 0, 1] and window[:4] == [0] * 4:
                score += 40
    for r in range(size - 1):
        for c in range(size - 1):
            block = (grid[r][c], grid[r][c + 1],
                     grid[r + 1][c], grid[r + 1][c + 1])
            if block in ((0, 0, 0, 0), (1, 1, 1, 1)):
                score += 3
    dark = sum(sum(row) for row in grid)
    total = size * size
    low = (dark * 100 // total) // 5 * 5           # the multiples of 5 either
    high = low + 5                                  # side of the dark share
    score += 10 * min(abs(low - 50) // 5, abs(high - 50) // 5)
    return score


def qr_matrix(text: str) -> list[list[bool]]:
    """The module grid for `text`. True is a dark module."""
    payload = str(text).encode("utf-8")
    version = _fit(len(payload))
    stream = _interleave(_codewords(payload, version), version)
    best = None
    for mask in range(8):
        grid, fixed, size = _blank(version)
        _place(grid, fixed, size, stream)
        rule = _MASKS[mask]
        for r in range(size):
            for c in range(size):
                if not fixed[r][c] and rule(r, c):
                    grid[r][c] ^= 1
        bits = _format_bits(mask)
        for i in range(15):
            bit = (bits >> i) & 1
            # The two copies, exactly as the spec lays them out: one wrapped
            # round the top-left finder, one split between the other two.
            if i < 6:
                grid[i][8] = bit
            elif i == 6:
                grid[7][8] = bit
            elif i == 7:
                grid[8][8] = bit
            elif i == 8:
                grid[8][7] = bit
            else:
                grid[8][14 - i] = bit
            if i < 8:
                grid[8][size - 1 - i] = bit
            else:
                grid[size - 15 + i][8] = bit
        cost = _penalty(grid, size)
        if best is None or cost < best[0]:
            best = (cost, grid)
    return [[bool(v) for v in row] for row in best[1]]


def qr_svg(text: str, quiet: int = 4, scale: int = 4,
           dark: str = "#04070c", light: str = "#ffffff") -> str:
    """A self-contained SVG. No external anything — it goes straight into
    an innerHTML or an <img src="data:...">."""
    grid = qr_matrix(text)
    size = len(grid)
    span = (size + quiet * 2) * scale
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
             'viewBox="0 0 %d %d" shape-rendering="crispEdges" '
             'role="img" aria-label="tune-in link">'
             % (span, span, span, span),
             '<rect width="%d" height="%d" fill="%s"/>' % (span, span, light),
             '<path fill="%s" d="' % dark]
    runs: list[str] = []
    for r, row in enumerate(grid):
        c = 0
        while c < size:
            if not row[c]:
                c += 1
                continue
            run = 0
            while c + run < size and row[c + run]:
                run += 1
            runs.append("M%d %dh%dv%dh-%dz"
                        % ((c + quiet) * scale, (r + quiet) * scale,
                           run * scale, scale, run * scale))
            c += run
    parts.append("".join(runs))
    parts.append('"/></svg>')
    return "".join(parts)
