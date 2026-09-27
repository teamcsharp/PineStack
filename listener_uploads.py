"""[listener-uploads] Media a listener sends in from the tune page.

"through the tail scale page allow users to submit video and upload them (as
 long as they are under 20mb) and they get posted to the
 \\\\10.89.1.125\\QuickSwap\\samples_grabbed\\user ... Make it a plus icon on
 the page that a user can click and then upload a file from their phone /
 computer ... and audio. Just media in general"

Pure: no station imports, so the tests need no station. The station's door
(app.py, POST /api/listener/upload) reads the body with a hard cap, asks
sniff() what the bytes ARE (never the name or the browser's word for it),
names the file with upload_name() and stages it with stage() in
data/uploads/outbox. The host courier (tools/uploads_courier.py, the
pinebox-uploads service) carries each staged file to the share through a
read-write mount of that one folder - the station's own view of QuickSwap
stays read-only - and writes a receipt that receipt() reads back.

samples_grabbed is one of the station's DROP folders (SFX_DROP_FOLDERS): a
playable sound or video that lands there is in the SFX Guy's draw a couple
of minutes later.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from typing import Any

MAX_BYTES = 20 * 1024 * 1024                      # "under 20mb"
DEST_UNC = "\\\\10.89.1.125\\QuickSwap\\samples_grabbed\\user"
OUTBOX_CAP_BYTES = 2 * 1024 * 1024 * 1024         # a courier that is down cannot fill the disk
PER_HOUR = 20                                     # uploads an hour from one link or address
PER_HOUR_BYTES = 300 * 1024 * 1024
ALL_PER_HOUR = 120                                # every listener together
MIN_GAP_S = 2.0
CONCURRENT = 2

# The one GUID an ASF file (wma / wmv) begins with.
_ASF = bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}
_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")


def sniff(head: bytes) -> tuple[str, str] | None:
    """What the bytes are: ("audio" | "video" | "image", extension), or None
    for anything that is not media - a page, a script, an archive, a
    program. Only the first bytes are read; the name and the browser's
    Content-Type are never believed."""
    h = bytes(head[:4096])
    if len(h) < 12:
        return None
    if h[4:8] == b"ftyp":                                   # the ISO box family
        brand = h[8:12]
        if brand == b"qt  ":
            return ("video", "mov")
        if brand in (b"M4A ", b"M4B ", b"M4P "):
            return ("audio", "m4a")
        if brand in _HEIF_BRANDS:
            return ("image", "heic")
        if brand in (b"avif", b"avis"):
            return ("image", "avif")
        if brand[:3] in (b"3gp", b"3g2"):
            return ("video", "3gp")
        if brand == b"M4V ":
            return ("video", "m4v")
        return ("video", "mp4")
    if h[:4] == b"\x1a\x45\xdf\xa3":                         # EBML: webm / matroska
        return ("video", "webm") if b"webm" in h[:64] else ("video", "mkv")
    if h[:4] == b"RIFF":
        form = h[8:12]
        if form == b"WAVE":
            return ("audio", "wav")
        if form == b"AVI ":
            return ("video", "avi")
        if form == b"WEBP":
            return ("image", "webp")
        return None
    if h[:4] == b"FORM" and h[8:12] in (b"AIFF", b"AIFC"):
        return ("audio", "aiff")
    if h[:4] == b"fLaC":
        return ("audio", "flac")
    if h[:4] == b"OggS":
        if b"OpusHead" in h[:96]:
            return ("audio", "opus")
        if b"theora" in h[:96]:
            return ("video", "ogv")
        return ("audio", "ogg")
    if h[:3] == b"ID3":
        return ("audio", "mp3")
    if h[:5] == b"#!AMR":
        return ("audio", "amr")
    if h[:4] == b"caff":
        return ("audio", "caf")
    if h[:16] == _ASF:
        return ("video", "wmv")
    if h[:3] == b"FLV":
        return ("video", "flv")
    if h[:4] == b"\x00\x00\x01\xba":
        return ("video", "mpg")
    if h[0] == 0x47 and len(h) > 376 and h[188] == 0x47 and h[376] == 0x47:
        return ("video", "ts")
    if h[:3] == b"\xff\xd8\xff":
        return ("image", "jpg")
    if h[:8] == b"\x89PNG\r\n\x1a\n":
        return ("image", "png")
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return ("image", "gif")
    if h[0] == 0xFF and (h[1] & 0xF6) == 0xF0:              # ADTS AAC (layer 00)
        return ("audio", "aac")
    if h[0] == 0xFF and (h[1] & 0xE0) == 0xE0:              # an MPEG audio frame
        version, layer = (h[1] >> 3) & 3, (h[1] >> 1) & 3
        rate, freq = (h[2] >> 4) & 0xF, (h[2] >> 2) & 3
        if version != 1 and layer != 0 and rate != 0xF and freq != 3:
            return ("audio", "mp3")
    return None


def safe_part(text: Any, most: int = 40) -> str:
    """A piece of a file name: letters, digits, dot, dash and underscore,
    in ASCII, no leading dot, at most `most` characters."""
    raw = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    raw = re.sub(r"\s+", "-", raw.strip())
    raw = re.sub(r"[^A-Za-z0-9._-]+", "", raw)
    raw = re.sub(r"([._-])\1+", r"\1", raw)
    return raw.strip("._-")[:most].strip("._-")


def upload_name(who: Any, original: Any, ext: str, now: float | None = None) -> str:
    """<date>_<time>_<who>_<the name it had>.<what it is>. The extension is
    the sniffed one, whatever the file was called."""
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(now if now is not None else time.time()))
    stem = str(original or "")
    stem = stem.replace("\\", "/").rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    stem = safe_part(stem, 60) or "upload"
    person = safe_part(who, 24) or "listener"
    ext = safe_part(ext, 8).lower() or "bin"
    return "%s_%s_%s.%s" % (stamp, person, stem, ext)


def name_ok(name: Any) -> bool:
    """A staged name the status door may be asked about: one plain file
    name, nothing that walks a path."""
    text = str(name or "")
    return bool(_NAME_OK.match(text)) and ".." not in text and not text.endswith(".part")


def stage(outbox: str, name: str, data: bytes) -> str:
    """Write the upload into the outbox atomically: a hidden .part first,
    synced, then renamed - the courier never sees half a file."""
    if not name_ok(name):
        raise ValueError("not a plain file name")
    os.makedirs(outbox, exist_ok=True)
    final = os.path.join(outbox, name)
    stem, ext = os.path.splitext(name)
    n = 1
    while os.path.exists(final):
        final = os.path.join(outbox, "%s-%d%s" % (stem, n, ext))
        n += 1
    part = os.path.join(outbox, "." + os.path.basename(final) + ".part")
    with open(part, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(part, final)
    return final


def outbox_bytes(outbox: str) -> int:
    total = 0
    try:
        with os.scandir(outbox) as it:
            for entry in it:
                try:
                    if entry.is_file():
                        total += entry.stat().st_size
                except OSError:
                    pass
    except FileNotFoundError:
        return 0
    return total


def receipt(receipts: str, outbox: str, name: str) -> dict[str, Any]:
    """Where an upload is: delivered (with the share path), waiting or
    failed (with the courier's reason), queued while it is still in the
    outbox, or unknown."""
    if not name_ok(name):
        return {"state": "unknown", "why": "not a plain file name"}
    try:
        with open(os.path.join(receipts, name + ".json"), encoding="utf-8") as fh:
            got = json.load(fh)
        if isinstance(got, dict):
            return got
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        return {"state": "unknown", "why": "the receipt could not be read"}
    if os.path.exists(os.path.join(outbox, name)):
        return {"state": "queued", "why": "waiting for the courier to carry it to the share"}
    return {"state": "unknown", "why": "no upload by that name"}


def throttle(log: list[tuple[float, str, int]], key: str, size: int, now: float) -> str:
    """Why this upload may not start now, or "" when it may. `log` holds
    (at, key, bytes) for the last hour and is trimmed in place."""
    log[:] = [x for x in log if now - x[0] < 3600]
    mine = [x for x in log if x[1] == key]
    if mine and now - mine[-1][0] < MIN_GAP_S:
        return "one at a time - the last one only just arrived"
    if len(mine) >= PER_HOUR:
        return "that is %d uploads in an hour from here - try again later" % PER_HOUR
    if sum(x[2] for x in mine) + size > PER_HOUR_BYTES:
        return "that is %d MB in an hour from here - try again later" % (PER_HOUR_BYTES // (1024 * 1024))
    if len(log) >= ALL_PER_HOUR:
        return "the station has taken all it can this hour - try again later"
    return ""
